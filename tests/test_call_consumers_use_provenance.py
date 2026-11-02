# SPDX-License-Identifier: BSD-3-Clause
"""Every ``.call`` consumer in ``src/`` and ``scripts/`` goes through :mod:`arrayprobe.provenance`,
or is exempt **here, with a reason**.

**Why this is the deliverable and not the parser** (2026-09-18). One module that parses the
five stamp formats correctly fixes nothing on its own: the defect was a *second* reader,
``src/arrayprobe/cli.py:1027``, doing it cheaply and wrongly beside the format's real owner. A
parser that some consumers use is exactly the state the repository was already in -- five formats,
five ad-hoc readers, no parser -- so what has to be prevented is the sixth ad-hoc reader, written
in six months by someone who has never read this file.

**How this draws its two sides from different places** ("A check must draw its two sides
from different places, or it is testing nothing"). One side is :func:`consumers`, which *walks the
source tree* and finds every file that names a ``.call`` sidecar in live code (AST string
constants, docstrings excluded) or uses the driver's stamp-helper names. The other is
:data:`EXEMPT`, a list typed by hand. Neither can be satisfied by editing the other alone: a new
consumer appears on the walked side and must be answered on the declared side, and an exemption
that stops matching anything is itself a failure (:meth:`NoStaleExemptions`).

**And it fires.** This project has found five guards that read fine while matching nothing
(the project's guard doctrine), so :class:`TheSweepFires` builds a temporary
source tree, drops an unregistered consumer into it, runs the same :func:`consumers` walk over it,
and asserts the file is reported -- then adds the import and asserts it is not. The walk under test
is the walk that runs against the real tree; nothing is re-implemented for the firing case.
"""
from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from tests._repo import needs_source

PYTHON_PORT = Path(__file__).resolve().parent.parent
ROOTS = (PYTHON_PORT / "src", PYTHON_PORT / "scripts")

#: The module that owns the answer. It is not a consumer of itself. It lives in the v3.5 engine
#: since 2026-09-30 ; ``src/arrayprobe/provenance.py`` is an alias that imports it.
PARSER = "src/arrayprobe_uiops/provenance.py"

#: The flight driver's stamp helpers (``src/arrayprobe/driver/run_flight.py`` since 2026-10-01;
#: ``scripts/run_flight.py`` is a shim onto it). A file using one of these names touches the sidecar
#: even when it never spells ``".call"`` -- ``driver/reprocess.py`` reaches it entirely through
#: ``drv.read_stamp``, and a walk that only looked for the string literal would miss it.
STAMP_HELPER_NAMES = frozenset({"call_path", "read_stamp", "write_stamp"})

#: How a file declares that it goes through the parser.
PROVENANCE_IMPORTS = ("arrayprobe.provenance", "provenance")

#: Files that touch a ``.call`` sidecar without importing :mod:`arrayprobe.provenance`, and why
#: that is accepted **today**. A reason is required; an entry whose file stops being a consumer is
#: a failure, so this list cannot quietly outlive its subject.
#:
#: Every row here is a debt.
#: The work package that introduced this check
#: owns only the parser and these two tests, so nothing below is edited by it.
EXEMPT: dict[str, str] = {
    "src/arrayprobe/run_page.py":
        "Lists the .call files a launched run wrote (by suffix and mtime) so the Run page can "
        "link them; it opens none of them and derives no engine from any, so an absent stamp "
        "is shown as no stamp, never read as an engine.",
    "src/arrayprobe/driver/run_flight.py":
        "The format owner (moved from scripts/run_flight.py, now a shim that execs this file, "
        "2026-10-01). It defines the driver text stamp that provenance.write mirrors, and "
        "its resume path compares stamps by string equality on purpose (_stamps_equivalent), "
        "which is a different question -- 'is this the configuration I am about to run' -- with a "
        "different safe answer than 'what wrote this file'. WP3 owns this file and is mid-edit "
        "in it.",
    "src/arrayprobe_uiops/combine.py":
        "Writes the v35-combine format. Its _write_call_sidecar docstring records the constraint "
        "-- 'must be usable with no dependency on the CLI driver' -- which importing "
        "arrayprobe.provenance satisfies (arrayprobe_uiops already imports arrayprobe "
        "in 15 files), "
        "but the file belongs to no WP1 file list. Handed back.",
    "src/arrayprobe/attributed_export.py":
        "Carries its own key=value parser (parse_stamp, _STAMP_KEY) that predates provenance and "
        "is the same algorithm. It should delegate, and provenance cannot import it in return "
        "(attributed_export pulls in numpy and netCDF4; provenance is stdlib-only and must stay "
        "importable from a lane script). Handed back as the one real duplication left.",
    "src/arrayprobe_uiops/product_sanity.py":
        "The product plausibility report (_call_stamp) only reports whether a '.call' sidecar "
        "exists and the raw text of its engine= token, as a fact on the report; it decides "
        "nothing from it and builds no engine. Added 2026-10-05 with the module.",
    "scripts/make_demo_reference.py":
        "Regenerates the tracked demo fixtures by copying the driver's own sidecars verbatim. "
        "Copying bytes is the point -- parsing them would put a second opinion between "
        "run_flight's output and the fixture it is pinned against.",
}

# Rows for development tools the release does not ship live in a dev-only module.
try:  # by module path (python -m unittest tests.X) or as a sibling (discover -s tests)
    try:
        from tests._call_consumers_dev_exemptions import DEV_EXEMPT
    except ImportError:
        from _call_consumers_dev_exemptions import DEV_EXEMPT
except ImportError:  # the public release tree
    DEV_EXEMPT = {}
EXEMPT.update(DEV_EXEMPT)


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """``id()`` of every Constant that is a module/class/function docstring.

    Prose mentioning ``.call`` is not a consumer; without this the walk would flag a dozen files
    that only explain the convention, and an exemption list full of documentation is a list nobody
    maintains.
    """
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                out.add(id(body[0].value))
    return out


def _is_path_fragment(text: str) -> bool:
    """Whether a string literal containing ``.call`` is building a path rather than describing one.

    The discriminator is whitespace, and it is the whole precision rule: every real consumer names
    the suffix in a fragment with no spaces in it -- ``".call"``, ``".pbp.call"``, ``"proc.call"``,
    the ``.call`` part of an f-string -- while every prose mention (an error message, a ``--help``
    string, an HTML paragraph, a catalogue note) is a sentence. Without this the walk flags six
    files that only explain the convention, and an exemption list that is mostly documentation is
    a list nobody reads. :class:`TheSweepFires` and :class:`ThePrecisionRuleIsChecked` pin both
    directions, and every real consumer today is an ``EXEMPT`` key, so
    :meth:`NoStaleExemptions.test_every_exempt_path_is_still_a_consumer` fails if this rule ever
    prunes one of them away.
    """
    return ".call" in text and not any(c.isspace() for c in text)


def why_consumer(source: str) -> list[str]:
    """Why ``source`` is a ``.call`` consumer -- an empty list if it is not.

    Two detections, because a consumer can reach a sidecar two ways: by naming the suffix in live
    code, or by using the driver's stamp helpers.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:  # pragma: no cover -- a file that does not parse is not a consumer
        return []
    skip = _docstring_nodes(tree)
    reasons: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and id(node) not in skip and _is_path_fragment(node.value):
            reasons.append(f"string literal {node.value!r}")
            break
    for node in ast.walk(tree):
        name = node.attr if isinstance(node, ast.Attribute) else (
            node.id if isinstance(node, ast.Name) else (
                node.name if isinstance(node, ast.FunctionDef) else None))
        if name in STAMP_HELPER_NAMES:
            reasons.append(f"stamp helper {name!r}")
            break
    return reasons


def imports_provenance(source: str) -> bool:
    """Whether ``source`` imports :mod:`arrayprobe.provenance` under any of its spellings."""
    try:
        tree = ast.parse(source)
    except SyntaxError:  # pragma: no cover
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.endswith("provenance") or module in PROVENANCE_IMPORTS:
                return True
            if any(alias.name == "provenance" for alias in node.names):
                return True
        elif isinstance(node, ast.Import):
            if any(alias.name.endswith("provenance") for alias in node.names):
                return True
    return False


#: The real-tree walk reads and AST-parses every ``.py`` under ``src/`` and ``scripts/``; the tests
#: below ask for it a dozen times. Cached on the default roots only -- a temporary tree gets a
#: fresh path every time, so caching it would buy nothing and could serve a deleted directory.
_REAL_TREE: dict[str, list[str]] | None = None


def consumers(roots=ROOTS, *, base: Path | None = None) -> dict[str, list[str]]:
    """Every ``.call`` consumer under ``roots``, keyed by its path relative to ``base``.

    ``roots``/``base`` are arguments rather than constants so :class:`TheSweepFires` can point the
    *same* walk at a temporary tree. A guard proved on a re-implementation is not proved.
    """
    global _REAL_TREE
    if roots is ROOTS and (base is None or Path(base) == PYTHON_PORT):
        if _REAL_TREE is None:
            _REAL_TREE = _walk(ROOTS, PYTHON_PORT)
        return dict(_REAL_TREE)
    return _walk(roots, base or PYTHON_PORT)


def _walk(roots, base: Path) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for root in roots:
        if not Path(root).is_dir():
            continue
        for path in sorted(Path(root).rglob("*.py")):
            rel = path.relative_to(base).as_posix()
            if rel == PARSER:
                continue
            reasons = why_consumer(path.read_text(encoding="utf-8"))
            if reasons:
                found[rel] = reasons
    return found


def unregistered(roots=ROOTS, *, base: Path | None = None,
                 exempt: dict[str, str] | None = None) -> dict[str, list[str]]:
    """Consumers that neither import the parser nor appear in ``exempt``. Empty is the pass."""
    exempt = EXEMPT if exempt is None else exempt
    base = base or PYTHON_PORT
    out: dict[str, list[str]] = {}
    for rel, reasons in consumers(roots, base=base).items():
        if rel in exempt:
            continue
        if imports_provenance((base / rel).read_text(encoding="utf-8")):
            continue
        out[rel] = reasons
    return out


class EveryConsumerIsAccountedFor(unittest.TestCase):
    def test_no_consumer_is_unregistered(self):
        missing = unregistered()
        self.assertEqual(
            missing, {},
            "these files reach a .call sidecar without importing arrayprobe.provenance and "
            "without an exemption: " + ", ".join(sorted(missing)) + ". Import the parser, or add "
            "a row to EXEMPT in this file saying why not. Absence of a stamp must not be readable "
            "as an engine anywhere.")

    def test_every_exemption_has_a_substantive_reason(self):
        for rel, reason in EXEMPT.items():
            with self.subTest(rel):
                self.assertGreater(len(reason.strip()), 60,
                                   f"{rel}'s exemption reason is too short to be a reason")


@needs_source
class NoStaleExemptions(unittest.TestCase):
    """An exemption that stops matching anything is a finding, never a skip -- the failure mode of
    a review finding where a check located files that had moved and printed
    'all clear' for three days while testing nothing."""

    def test_every_exempt_path_exists(self):
        missing = [rel for rel in EXEMPT if not (PYTHON_PORT / rel).is_file()]
        self.assertEqual(missing, [], f"EXEMPT names files that are not here: {missing}")

    def test_every_exempt_path_is_still_a_consumer(self):
        found = consumers()
        stale = [rel for rel in EXEMPT if rel not in found]
        self.assertEqual(
            stale, [],
            f"EXEMPT rows whose file no longer touches a .call sidecar: {stale}. Delete the row; "
            "leaving it makes the list look maintained when it is not.")

    def test_no_exempt_file_already_imports_the_parser(self):
        """Once a file goes through the parser its exemption is spent."""
        redundant = [rel for rel in EXEMPT
                     if imports_provenance((PYTHON_PORT / rel).read_text(encoding="utf-8"))]
        self.assertEqual(redundant, [],
                         f"these now import provenance; drop their EXEMPT rows: {redundant}")


@needs_source
class TheEnumerationIsNotVacuous(unittest.TestCase):
    def test_the_walk_finds_consumers_at_all(self):
        self.assertGreaterEqual(len(consumers()), 6, consumers())

    def test_it_finds_the_two_files_the_incident_was_about(self):
        """Anchored on named files as well as a count, so a walk that started matching everything
        (or nothing) fails here rather than reading clean."""
        found = consumers()
        self.assertIn("src/arrayprobe/cli.py", found)
        # The driver moved into the package on 2026-10-01; scripts/run_flight.py is now a shim
        # that names no sidecar, so the incident's second file is found at its new home.
        self.assertIn("src/arrayprobe/driver/run_flight.py", found)

    def test_the_parser_itself_is_not_counted_as_a_consumer(self):
        self.assertNotIn(PARSER, consumers())

    def test_a_docstring_mention_alone_is_not_a_consumer(self):
        self.assertEqual(why_consumer('"""Reads the .call sidecar beside it."""\nx = 1\n'), [])

    def test_a_comment_mention_alone_is_not_a_consumer(self):
        self.assertEqual(why_consumer("# the .call sidecar lives beside the product\nx = 1\n"), [])


class ThePrecisionRuleIsChecked(unittest.TestCase):
    """:func:`_is_path_fragment` decides which mentions count. Both directions are pinned here,
    with the real spellings from the tree, because a rule that silently stopped matching path
    fragments would empty the walk and this file would read clean."""

    BUILDS_A_PATH = (
        ".call",                       # attributed_export.CALL_SUFFIX
        ".pbp.call",                   # cli.py's SODA-2 sidecar extension
        "proc.call",                   # make_demo_reference's tracked fixture names
        "sea_s2.CIP.cdf.call",
    )
    DESCRIBES_ONE = (
        "a registered profile needs a name; it is what a .call stamp records",
        "It reads the .call sidecar, re-runs that stage under exactly the same configuration",
        "the one parser for every .call sidecar; absence is None, never an engine",
        ".call: ",
    )

    def test_path_fragments_are_detected(self):
        for text in self.BUILDS_A_PATH:
            with self.subTest(text):
                self.assertTrue(_is_path_fragment(text))

    def test_prose_is_not(self):
        for text in self.DESCRIBES_ONE:
            with self.subTest(text):
                self.assertFalse(_is_path_fragment(text))

    def test_a_with_suffix_call_is_a_consumer(self):
        self.assertTrue(why_consumer('import pathlib\np = pathlib.Path("x").with_suffix(".call")'))

    def test_an_fstring_part_is_a_consumer(self):
        self.assertTrue(why_consumer('name = "x"\ns = f"{name}.call"\n'))


class TheSweepFires(unittest.TestCase):
    """The proof. A consumer added without registration is reported by the same walk that runs
    against the real tree; adding the import silences it."""

    NEW_CONSUMER = (
        '"""A stage that writes a product."""\n'
        "from pathlib import Path\n"
        "\n"
        "def publish(product: Path) -> None:\n"
        '    sidecar = product.with_name(product.name + ".call")\n'
        '    sidecar.write_text("engine=3.5 profile=stock-v3.5\\n")\n'
    )

    def _tree(self, tmp: Path, body: str) -> dict[str, list[str]]:
        (tmp / "src" / "arrayprobe").mkdir(parents=True)
        (tmp / "scripts").mkdir()
        (tmp / "src" / "arrayprobe" / "new_stage.py").write_text(body, encoding="utf-8")
        return unregistered((tmp / "src", tmp / "scripts"), base=tmp, exempt={})

    def test_an_unregistered_new_consumer_is_reported(self):
        with tempfile.TemporaryDirectory() as td:
            found = self._tree(Path(td), self.NEW_CONSUMER)
        self.assertIn("src/arrayprobe/new_stage.py", found,
                      "the sweep did not notice a file that writes a .call sidecar -- it would "
                      "not have noticed the sixth ad-hoc reader either")

    def test_the_same_consumer_is_silent_once_it_imports_the_parser(self):
        with tempfile.TemporaryDirectory() as td:
            body = self.NEW_CONSUMER.replace(
                "from pathlib import Path\n",
                "from pathlib import Path\n\nfrom arrayprobe import provenance\n")
            found = self._tree(Path(td), body)
        self.assertEqual(found, {}, "the pass condition must be reachable, or the guard is a "
                                    "permanent failure rather than a check")

    def test_a_consumer_that_only_uses_the_stamp_helpers_is_reported(self):
        """The literal-".call" half of the walk would miss scripts/reprocess.py's shape."""
        body = ('"""No suffix spelled anywhere."""\n'
                "import run_flight as drv\n"
                "\n"
                "def check(product):\n"
                "    return drv.read_stamp(product)\n")
        with tempfile.TemporaryDirectory() as td:
            found = self._tree(Path(td), body)
        self.assertIn("src/arrayprobe/new_stage.py", found)

    def test_an_exemption_covers_the_new_consumer(self):
        """The third outcome: registered as exempt rather than converted."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "src" / "arrayprobe").mkdir(parents=True)
            (tmp / "scripts").mkdir()
            (tmp / "src" / "arrayprobe" / "new_stage.py").write_text(
                self.NEW_CONSUMER, encoding="utf-8")
            found = unregistered((tmp / "src", tmp / "scripts"), base=tmp,
                                 exempt={"src/arrayprobe/new_stage.py": "because"})
        self.assertEqual(found, {})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

# A repository sweep: run before every full suite by the pre-suite gate
# (tests/test_presuite_covers_repo_sweeps.py keeps that true).
PRESUITE_GUARD = True
