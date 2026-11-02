# SPDX-License-Identifier: BSD-3-Clause
"""A path a module builds to a document names a file that exists.

**The defect this was written after.** After the 2026-10-08 layout move, 13 code
sites in 13 files built paths to documents that had moved (``ROOT / "docs" /
"<name>.md"`` where the file now sits under ``docs/developer/``), and
the only signal was each consuming test erroring on its own (fixed in 4c7ced0).
``test_backtick_paths_exist`` reads documents, not code, so nothing caught them.

**What is scanned.** Every tracked ``.py`` file under ``src/``, ``tests/``,
``scripts/``, ``enhancements_uiops/`` and ``enhancements_soda2/`` (``git ls-files``),
parsed with ``ast``. Two shapes are collected:

* a ``/`` chain on a repository-root name (an upper-case name containing
  ``ROOT`` or ``REPO``: ``ROOT``, ``_REPO``, ``PKG_ROOT``, ``_ROOT.parent``)
  whose right-most operands are string constants and whose last
  constant ends in ``.md`` -- ``X / "docs" / "developer" / "Y.md"`` gives
  ``docs/developer/Y.md`` (a constant may itself hold ``/``);
* a single string constant containing ``/`` and ending in ``.md`` passed as the
  first argument to ``Path(...)``.

**Scope, kept narrow against false positives.** The collected segments are
trimmed to start at the first one naming a known top-level directory
(``TOP_DIRS``) that exists in the repository; a path with no such segment, or a
chain on any other base (a temp tree's ``root``, ``ENH``), is relative to
something else and is skipped. A path resolves if it exists relative
to the repository root or to any directory enclosing the scanning file (so
``ENH / "docs" / "X.md"`` inside ``enhancements_uiops/`` means
``enhancements_uiops/docs/X.md``). Paths in this module's own firing fixtures are
not scanned, because the module is parsed like any other but its fixtures are
held as source strings, not path expressions.

**Allowed exceptions** go in ``EXPECTED_STALE`` as ``"file:line -> path"``,
a set that may only shrink.
"""
from __future__ import annotations

import ast
import subprocess
import unittest
from pathlib import Path

from tests._hygiene import hygiene
from tests._repo import REPO_ROOT, repo_only

SCAN_DIRS = ("src", "tests", "scripts", "enhancements_uiops", "enhancements_soda2")
TOP_DIRS = frozenset({"docs", "tests", "scripts", "examples", "src", "validation",
                      "release", "archive", "project",
                      "enhancements_uiops", "enhancements_soda2"})

#: "file:line -> path" entries known to be stale; may only shrink.
EXPECTED_STALE: frozenset[str] = frozenset()


def _trailing_constants(node: ast.AST) -> list[str]:
    """The string constants at the right end of a ``/`` chain, left to right."""
    out: list[str] = []
    while isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        right = node.right
        if isinstance(right, ast.Constant) and isinstance(right.value, str):
            out.append(right.value)
            node = node.left
        else:
            break
    else:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append(node.value)
    return list(reversed(out))


def _root_base(node: ast.AST) -> bool:
    """True when a chain's base is a repository-root name (``ROOT``, ``_REPO``...).

    ``_ROOT.parent`` and ``REPO_ROOT`` count; a lower-case local such as a temp
    tree's ``root``, or a package-relative base such as ``ENH``, does not.
    """
    while isinstance(node, (ast.Attribute, ast.Subscript, ast.Call)):
        node = node.func if isinstance(node, ast.Call) else node.value
    return (isinstance(node, ast.Name) and node.id == node.id.upper()
            and ("ROOT" in node.id or "REPO" in node.id))


def _trim(parts: list[str], tops: frozenset[str]) -> str | None:
    segs = [s for p in parts for s in p.replace("\\", "/").split("/") if s]
    for i, s in enumerate(segs):
        if s in tops:
            return "/".join(segs[i:])
    return None


def find_doc_paths(source: str) -> list[tuple[int, str]]:
    """(line, relative path) for every document path ``source`` builds."""
    tree = ast.parse(source)
    found: list[tuple[int, str]] = []
    inner: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            if id(node) in inner:
                continue
            n = node.left
            while isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div):
                inner.add(id(n))
                n = n.left
            parts = _trailing_constants(node)
            if parts and parts[-1].endswith(".md") and _root_base(n):
                rel = _trim(parts, TOP_DIRS)
                if rel:
                    found.append((node.lineno, rel))
        elif isinstance(node, ast.Call) and node.args:
            f = node.func
            name = f.id if isinstance(f, ast.Name) else (
                f.attr if isinstance(f, ast.Attribute) else None)
            a = node.args[0]
            if (name == "Path" and isinstance(a, ast.Constant)
                    and isinstance(a.value, str) and "/" in a.value
                    and a.value.endswith(".md")):
                rel = _trim([a.value], TOP_DIRS)
                if rel:
                    found.append((node.lineno, rel))
    return found


def check_source(source: str, rel_file: str, root: Path) -> list[str]:
    """``"file:line -> path"`` for every built document path that does not exist."""
    bases = list(dict.fromkeys([root] + [root / q for q in Path(rel_file).parents
                                         if str(q) != "."]))
    missing = []
    for line, rel in find_doc_paths(source):
        if not any((b / rel).exists() for b in bases):
            missing.append(f"{rel_file}:{line} -> {rel}")
    return missing


def _tracked_py() -> list[str]:
    out = subprocess.run(["git", "ls-files", "--", *SCAN_DIRS], cwd=REPO_ROOT,
                         capture_output=True, text=True, check=True).stdout
    return [p for p in out.splitlines() if p.endswith(".py")]


@hygiene
@repo_only  # walks the repository's tracked code, not in the sdist
class CodeDocPathsExist(unittest.TestCase):
    def test_every_built_document_path_exists(self):
        missing = []
        for rel in _tracked_py():
            path = REPO_ROOT / rel
            if not path.is_file():
                continue
            src = path.read_text(encoding="utf-8", errors="replace")
            try:
                missing += check_source(src, rel, REPO_ROOT)
            except SyntaxError:
                continue
        # A path into a top-level directory this checkout does not carry (archive/ in the public
        # distribution) is guarded by its own test's skip, not reported here.
        missing = [m for m in missing
                   if (REPO_ROOT / m.split(" -> ", 1)[1].split("/", 1)[0]).exists()]
        new = sorted(set(missing) - EXPECTED_STALE)
        self.assertEqual(new, [], "code builds a path to a document that does not "
                         "exist:\n  " + "\n  ".join(new))
        gone = sorted(EXPECTED_STALE - set(missing))
        self.assertEqual(gone, [], "EXPECTED_STALE entries now resolve; remove them")


@hygiene
@repo_only  # resolves against the repository's own docs/ tree
class TheCheckerFires(unittest.TestCase):
    def test_a_missing_document_is_reported(self):
        src = 'ROOT = None\nP = ROOT / "docs" / "NO_SUCH_DOC.md"\n'
        self.assertEqual(check_source(src, "tests/fake.py", REPO_ROOT),
                         ["tests/fake.py:2 -> docs/NO_SUCH_DOC.md"])

    def test_a_missing_path_constant_is_reported(self):
        src = 'from pathlib import Path\nP = Path("docs/developer/NO_SUCH.md")\n'
        self.assertEqual(check_source(src, "src/x.py", REPO_ROOT),
                         ["src/x.py:2 -> docs/developer/NO_SUCH.md"])

    def test_an_existing_document_is_not_reported(self):
        existing = next(p for p in sorted((REPO_ROOT / "docs").rglob("*.md")))
        parts = existing.relative_to(REPO_ROOT).parts
        chain = " / ".join(f'"{p}"' for p in parts)
        src = f"ROOT = None\nP = ROOT / {chain}\n"
        self.assertEqual(find_doc_paths(src), [(2, "/".join(parts))])
        self.assertEqual(check_source(src, "tests/fake.py", REPO_ROOT), [])

    def test_a_path_relative_to_something_else_is_skipped(self):
        src = 'P = ROOT / "notes" / "NO_SUCH.md"\nQ = root / "docs" / "NO_SUCH.md"\n'
        self.assertEqual(find_doc_paths(src), [])

    def test_the_incident_shape_on_root_parent_is_reported(self):
        src = 'F = _ROOT.parent / "python_port" / "docs" / "SOME_NOTES.md"\n'
        self.assertEqual(find_doc_paths(src), [(1, "docs/SOME_NOTES.md")])


if __name__ == "__main__":
    unittest.main()
