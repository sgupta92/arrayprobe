# SPDX-License-Identifier: BSD-3-Clause
"""Scope-boundary claims in SODA-2 source prose must match a refusal in the code.

The class (a staleness audit kept outside the repository): a
sentence stating a scope boundary -- "not ported", "version 1 only", "raises
``NotImplementedError``", "refused by name", "remains round-7 scope" -- is
written when the boundary is true and never revisited when the port moves past
it. ``test_soda2_docs_not_ported_drift.py`` reads only "not ported" on the docs
pages; this guard reads the **source**: every module/function/class docstring
and every comment in ``src/arrayprobe_soda2/*.py``.

Side A (prose, from docstrings and comments): each sentence matching
``CLAIM_RE``, split into clauses on ``;`` and `` -- ``. The subjects of the
matching clause are its backticked identifiers that resolve to a function,
class or module of the package, or that a refusal raise names (``.pro`` is
stripped, so ``spec_index_hk.pro`` reaches ``spec_index_hk``). A clause with no
such subject is about the docstring's owner (the enclosing ``def``, or the
module).

Side B (code, from the AST): a *refusal raise* is ``raise NotImplementedError``
or a raise of a refusal class -- one whose name ends ``NotPorted``/``Refused``,
``Unsupported`` (as a prefix or suffix), or that subclasses
``NotImplementedError`` directly or through another refusal class. A subject
has evidence when a refusal raise sits inside its ``def`` (or its module), or
when any refusal raise's message names it. A claim is stale when one of its
subjects has no evidence.

Skipped: docstrings and comments of refusal-class definitions (they *are* the
refusal); sentences containing "ported since", "is ported" or "are ported"
(positive claims); test files (not scanned). ``ALLOWLIST`` maps a finding's key
to the reason it is a genuine exception, and the test fails when an entry no
longer matches any finding, so the list cannot rot.

**First run (master at 1527aaa, 2026-10-07), resolved by merging branch
``stale-1006``, none allowlisted.** On master the guard flagged the stale
claims below; ``stale-1006`` rewrote each to match the code. The rewrite left
one clause with no backticked subject ("refused by name only on the parallel
driver ... and for a flush chunk under two slices"), which the guard read as a
claim about ``__init__`` itself; the clause now names the two functions whose
bodies raise ``PbpImagesNotPorted`` (``soda2_process_2d``,
``write_pbp_ncdf_images``), so it is checked rather than allowlisted. The
claims as found --

* ``spec_read_hk.py::spec_read_hk`` -- "``version=2`` ... raises
  ``NotImplementedError`` by name" while the body dispatches version 2 to
  ``_spec_read_hk_v2``;
* ``__init__.py::<module>`` -- the Round 6 lane B paragraph: "``process_hk``
  (``spec_process_hk``, version 1 only)" and "``spec_index_hk.pro``, version 2
  of ``spec_process_hk`` ... remain round-7 scope, each refused by name", while
  ``process_hk.spec_index_hk`` and both ``spec_process_hk`` versions are ported;
  and its "Still refused by name: particle-image output (``ncdfparticlefile``
  2)", which no refusal raise names (rewritten on ``stale-1006``);
* ``process_2d.py::soda2_process_2d`` (the comment near ``:975``) -- the
  ``process_cip1d_sea`` branch "is refused before any file is read", while
  ``:806-808`` says that branch is ported and no refusal names it. Not in the
  audit's table; left flagged for a decision, not allowlisted.

Self-tests plant a module whose docstring says "```foo``` version=2 raises
NotImplementedError" with and without the raise: exactly one finding, then zero.
"""

from __future__ import annotations

import ast
import io
import re
import tempfile
import tokenize
import unittest
from dataclasses import dataclass
from pathlib import Path

from tests._hygiene import hygiene
from tests._repo import PKG_ROOT, needs_source

SODA2_DIR = PKG_ROOT / "src" / "arrayprobe_soda2"

CLAIM_RE = re.compile(
    r"not (?:yet )?ported|version \d only|ports only version"
    r"|raises?\W{0,3}NotImplementedError|refused by name"
    r"|remains? round-\d+ scope|refused before any file is read",
    re.IGNORECASE,
)
POSITIVE_RE = re.compile(r"ported since|\bis ported\b|\bare ported\b", re.IGNORECASE)
_PARA_SPLIT_RE = re.compile(r"\n\s*\n")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9`*(\"'])")
_CLAUSE_SPLIT_RE = re.compile(r";|\s--\s")
_BACKTICK_RE = re.compile(r"`+([^`]+?)`+")
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
_REFUSAL_NAME_RE = re.compile(r"(NotPorted|Refused|Unsupported)$|^Unsupported")

#: finding key -> why it is a genuine exception (a claim about something that
#: needs no raise, or whose raise sits outside the owner the sentence lives in).
ALLOWLIST: dict[str, str] = {
    'decompress_dmt.py::<module>::``decompress_dmt3`` is what ``':
        "names the IDL file decompress_dmt.pro, which no vendored caller reaches; "
        "the Python module of the same stem ports decompress_dmt3, so nothing to refuse",
    "process_2d.py::_front_half::`:474-486`'s `activetime_sea` ":
        "a silent omission matching the IDL: :648 reads activetime_sea only for "
        "probetype ne 'CIP', so the unported update is never consumed and needs no raise",
}


@dataclass(frozen=True)
class Finding:
    file: str
    line: int
    owner: str
    subjects: tuple[str, ...]
    sentence: str

    @property
    def key(self) -> str:
        return f"{self.file}::{self.owner}::{self.sentence[:30]}"

    def __str__(self) -> str:
        return (f"{self.file}:{self.line} ({self.owner}) no refusal for "
                f"{', '.join(self.subjects)}: {self.sentence}")


def _exc_name(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _refusal_classes(trees: dict[str, ast.Module]) -> set[str]:
    bases: dict[str, set[str]] = {}
    for tree in trees.values():
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases[node.name] = {b for b in map(_exc_name, node.bases) if b}
    refusal = {n for n in bases if _REFUSAL_NAME_RE.search(n)}
    refusal.add("NotImplementedError")
    changed = True
    while changed:
        changed = False
        for name, bs in bases.items():
            if name not in refusal and bs & refusal:
                refusal.add(name)
                changed = True
    return refusal


def _strings(node: ast.AST) -> str:
    return " ".join(n.value for n in ast.walk(node)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str))


def _raises_in(node: ast.AST, refusal: set[str]) -> list[ast.Raise]:
    return [n for n in ast.walk(node)
            if isinstance(n, ast.Raise) and _exc_name(n.exc) in refusal]


def _owners(tree: ast.Module):
    """Yield (qualified owner name, node) for every def/class, outermost first."""
    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}{child.name}"
                yield name, child
                yield from walk(child, name + ".")
            else:
                yield from walk(child, prefix)
    yield from walk(tree, "")


def _sentences(text: str):
    for para in _PARA_SPLIT_RE.split(text):
        flat = " ".join(para.split())
        if flat:
            yield from _SENTENCE_SPLIT_RE.split(flat)


def _comment_blocks(source: str):
    """Yield (first line, joined text) for each run of consecutive comment lines."""
    block: list[str] = []
    start = last = 0
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type != tokenize.COMMENT:
            continue
        line = tok.start[0]
        if block and line != last + 1:
            yield start, " ".join(block)
            block = []
        if not block:
            start = line
        block.append(tok.string.lstrip("#").strip())
        last = line
    if block:
        yield start, " ".join(block)


def scan(package_dir: Path) -> list[Finding]:
    """Every stale scope claim in ``package_dir/*.py`` docstrings and comments."""
    sources = {p: p.read_text(encoding="utf-8") for p in sorted(package_dir.glob("*.py"))}
    trees = {p.stem: ast.parse(src, filename=str(p)) for p, src in sources.items()}
    refusal = _refusal_classes(trees)

    defs: dict[str, list[ast.AST]] = {}
    for tree in trees.values():
        for name, node in _owners(tree):
            defs.setdefault(name.rsplit(".", 1)[-1], []).append(node)
    all_raises = [r for t in trees.values() for r in _raises_in(t, refusal)]
    raise_text = [(_exc_name(r.exc) or "") + " " + _strings(r) for r in all_raises]

    def resolves(name: str) -> bool:
        return name in defs or name in trees or any(
            re.search(rf"\b{re.escape(name)}\b", t) for t in raise_text)

    def evidenced(name: str) -> bool:
        if any(re.search(rf"\b{re.escape(name)}\b", t) for t in raise_text):
            return True
        if any(_raises_in(n, refusal) for n in defs.get(name, [])):
            return True
        return name in trees and bool(_raises_in(trees[name], refusal))

    findings: list[Finding] = []
    for path, src in sources.items():
        tree = trees[path.stem]
        texts: list[tuple[int, str, ast.AST, str]] = []  # line, owner, node, text
        skip_spans: list[tuple[int, int]] = []
        spans: list[tuple[int, int, str, ast.AST]] = []
        doc = ast.get_docstring(tree, clean=True)
        if doc:
            texts.append((1, "<module>", tree, doc))
        for name, node in _owners(tree):
            end = getattr(node, "end_lineno", node.lineno)
            if isinstance(node, ast.ClassDef) and name.rsplit(".", 1)[-1] in refusal:
                skip_spans.append((node.lineno, end))
                continue
            spans.append((node.lineno, end, name, node))
            d = ast.get_docstring(node, clean=True)
            if d:
                texts.append((node.body[0].lineno, name, node, d))
        for line, text in _comment_blocks(src):
            if any(a <= line <= b for a, b in skip_spans):
                continue
            inner = [s for s in spans if s[0] <= line <= s[1]]
            if inner:
                _, _, owner, node = max(inner, key=lambda s: s[0])
                texts.append((line, owner, node, text))
            else:
                texts.append((line, "<module>", tree, text))

        for line, owner, node, text in texts:
            if any(a <= line <= b for a, b in skip_spans):
                continue
            for sentence in _sentences(text):
                if not CLAIM_RE.search(sentence) or POSITIVE_RE.search(sentence):
                    continue
                for clause in _CLAUSE_SPLIT_RE.split(sentence):
                    if not CLAIM_RE.search(clause):
                        continue
                    subjects = []
                    for raw in _BACKTICK_RE.findall(clause):
                        name = raw.strip().removesuffix(".pro").removesuffix(".py")
                        if (not _IDENT_RE.match(name) or name in refusal
                                or _REFUSAL_NAME_RE.search(name)):
                            continue
                        name = name.rsplit(".", 1)[-1]
                        if resolves(name) and name not in subjects:
                            subjects.append(name)
                    # A clause that names the exception class this module raises for the
                    # refusal (``:class:`BulkAttnameCarryOver``` in export_ncdf_raf) is
                    # evidenced by that raise, whatever the class is called.
                    raised = {_exc_name(r.exc) for r in ast.walk(tree)
                              if isinstance(r, ast.Raise)}
                    if any(r.strip() in raised for r in _BACKTICK_RE.findall(clause)):
                        continue
                    if subjects:
                        missing = [s for s in subjects if not evidenced(s)]
                    else:
                        missing = [] if _raises_in(node, refusal) else [owner]
                    if missing:
                        findings.append(Finding(path.name, line, owner,
                                                tuple(missing), sentence))
                        break
    return findings


@hygiene
@needs_source
class ScopeClaimsMatchCode(unittest.TestCase):
    def test_every_scope_claim_has_a_refusal_in_the_code(self):
        found = [f for f in scan(SODA2_DIR) if f.key not in ALLOWLIST]
        self.assertEqual([], found, "\n  ".join(
            ["stale scope claim (the code no longer refuses what the prose says):"]
            + [str(f) for f in found]))

    def test_every_allowlist_entry_still_matches(self):
        keys = {f.key for f in scan(SODA2_DIR)}
        self.assertEqual([], [k for k in ALLOWLIST if k not in keys],
                         "allowlist entries that match no finding; remove them")


_PLANTED = '''"""Planted module.

`foo` version=2 raises NotImplementedError.
"""


def foo(version=1):
    if version == 2:
        {body}
    return version
'''


@hygiene
class TheGuardFires(unittest.TestCase):
    def _scan(self, body: str) -> list[Finding]:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "planted.py").write_text(_PLANTED.format(body=body), encoding="utf-8")
            return scan(Path(tmp))

    def test_guard_fires_on_a_planted_claim(self):
        found = self._scan("return 2")
        self.assertEqual(1, len(found), [str(f) for f in found])
        self.assertEqual(("foo",), found[0].subjects)

    def test_guard_is_silent_when_the_raise_exists(self):
        self.assertEqual([], self._scan('raise NotImplementedError("version 2")'))

    def test_a_refusal_class_counts_as_the_raise(self):
        planted = _PLANTED.replace(
            'def foo', 'class FooNotPorted(Exception):\n    """not ported."""\n\n\ndef foo')
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "planted.py").write_text(
                planted.format(body='raise FooNotPorted("v2")'), encoding="utf-8")
            self.assertEqual([], scan(Path(tmp)))

    def _named_class(self, body: str) -> list[Finding]:
        planted = (
            '"""Planted module.\n\nA bad tag is refused by name (:class:`BadTag`).\n"""\n\n\n'
            'class BadTag(IndexError):\n    pass\n\n\n'
            'def bar(tag):\n    if tag:\n        {body}\n    return tag\n')
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "planted.py").write_text(planted.format(body=body), encoding="utf-8")
            return scan(Path(tmp))

    def test_a_named_class_the_module_raises_counts(self):
        self.assertEqual([], self._named_class('raise BadTag("x")'))

    def test_a_named_class_the_module_never_raises_still_fires(self):
        self.assertEqual(1, len(self._named_class("return 0")))


if __name__ == "__main__":
    unittest.main()
