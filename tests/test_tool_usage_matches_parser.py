# SPDX-License-Identifier: BSD-3-Clause
"""Every ``--flag`` a tool's own usage example shows must exist in its parser.

**Two instances in two days, and neither was findable by any check.**

* ``benchmark_pipeline.py`` (found 2026-09-05) documented a call the code did
  not make -- its docstring said the netCDF products "are compared through the
  project's own comparator instead" and there was no such call anywhere in the
  file. That one reached the manuscript as "identical output,
  checked byte for byte" on the strength of three text sidecars.
* ``ingest_review_flags.py`` (found 2026-09-06) showed a ``--proc`` argument in
  its usage block. The parser has never defined one, so anyone copying the line
  got ``unrecognized arguments``.

The transferable form was written into the first one's record: **a comment
cannot be executed, and review read the comment.** A docstring is the one part
of a tool that no test runs, which is exactly why the drift is silent -- and
`scripts/` had never even been linted until the same day.

This check is deliberately narrow, and the narrowness is what makes it usable.
It reads only the usage example that invokes **this** file, so a docstring may
freely discuss another tool's flags (``benchmark_pipeline.py`` legitimately
names ``run_flight.py --s2-jobs``, and must be allowed to). And it checks one
direction only: every flag *shown* must *exist*. A parser may define flags the
example does not show, because an example is not reference documentation.
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "scripts"

#: A long option as it appears in prose or a shell line. Trailing punctuation
#: and the ``=value`` form are trimmed by the caller.
_FLAG = re.compile(r"--[A-Za-z][A-Za-z0-9-]*")

#: Flags argparse itself provides, which no ``add_argument`` call declares.
_BUILTIN = {"--help"}
#: The tool the reconstructed defect below names (a path the release builder reads as a key).
_INGEST = "scripts/ingest_review_flags.py"


def _parser_flags(tree: ast.AST) -> set[str]:
    """Every long option the module hands to an ``add_argument`` call.

    AST rather than import: importing a tool runs its module body, and several
    of these read files or build state at import time. AST also sees flags
    behind an ``if`` that a particular import would skip.
    """
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "add_argument"):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if arg.value.startswith("--"):
                    found.add(arg.value)
    return found | _BUILTIN


def _delegated_subcommand(tree: ast.AST) -> str | None:
    """The ``arrayprobe`` subcommand a shim forwards to, if it is one.

    Since 2026-09-10 two tools -- ``compare_nc.py`` and
    ``render_flight_gallery.py`` -- are shims: their body is
    ``_cli_main(["compare", *argv])``, and the flags their usage examples show
    are defined by ``arrayprobe.cli``'s parser, not by any ``add_argument`` in
    the file. Without this the check reported those examples as unrunnable,
    which was wrong in a way worth being careful about: they run fine, and
    "fixing" it by deleting the examples would have removed real documentation
    to satisfy a check that was looking in the wrong place.

    Detected from the call rather than from a list of filenames here, so a
    third shim is covered the day it is written and a shim that stops
    delegating stops being exempt.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func
        if not (isinstance(name, ast.Name) and name.id.endswith("cli_main")):
            continue
        for arg in node.args:
            if isinstance(arg, ast.List) and arg.elts:
                first = arg.elts[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    return first.value
    return None


def _cli_subcommand_flags(command: str) -> set[str]:
    """Every long option ``arrayprobe <command>`` accepts, from the real parser.

    Imported and interrogated rather than parsed out of the source: this is
    the object that will actually reject a flag, so it is the right side of
    the comparison for a shim.
    """
    from arrayprobe.cli import build_parser
    flags: set[str] = set()
    for action in build_parser()._subparsers._group_actions:  # noqa: SLF001
        sub = getattr(action, "choices", {}).get(command)
        if sub is None:
            continue
        stack = [sub]
        while stack:
            parser = stack.pop()
            for act in parser._actions:  # noqa: SLF001
                flags.update(o for o in act.option_strings if o.startswith("--"))
                choices = getattr(act, "choices", None)
                if isinstance(choices, dict):
                    stack.extend(
                        c for c in choices.values() if hasattr(c, "_actions"))
    return flags


def _usage_flags(doc: str, filename: str) -> set[str]:
    """Flags shown in the usage example that invokes ``filename``.

    The example is taken as the line naming this file plus every following
    line that is a shell continuation of it -- indented, and not blank. That
    bounds the read to one command, so a later paragraph mentioning another
    tool's options is not swept in.
    """
    lines = doc.splitlines()
    flags: set[str] = set()
    stem = Path(filename).name
    i = 0
    while i < len(lines):
        if stem not in lines[i]:
            i += 1
            continue
        # A prose mention is not an invocation. Require it to look like a
        # command line: the file named with a path separator or after an
        # interpreter, not inside a sentence ending in a period.
        if not re.search(rf"(^|[\s/\\]){re.escape(stem)}(\s|$)", lines[i]):
            i += 1
            continue
        block = [lines[i]]
        j = i + 1
        while j < len(lines):
            nxt = lines[j]
            if not nxt.strip():
                break
            # A continuation is indented at least as far as the command and is
            # not the start of a new prose paragraph.
            if not nxt.startswith((" ", "\t")):
                break
            if nxt.strip().startswith(("**", "The ", "It ", "This ", "Nothing ")):
                break
            block.append(nxt)
            j += 1
        for line in block:
            for m in _FLAG.finditer(line):
                flags.add(m.group(0).rstrip(".,;:)]`").split("=")[0])
        i = j
    return flags


def _tools():
    return sorted(p for p in TOOLS.glob("*.py") if p.name != "__init__.py")


@unittest.skipUnless(TOOLS.is_dir(), f"scripts/ not present at {TOOLS}")
class EveryDocumentedFlagExists(unittest.TestCase):

    def test_tools_directory_is_not_empty(self):
        """A check that silently examines nothing is worse than no check --
        the `skipped=3` and `zero files` findings of 2026-09-05 both had that
        shape."""
        self.assertGreater(len(_tools()), 10,
                           f"expected the tool set at {TOOLS}, found "
                           f"{[p.name for p in _tools()]}")

    def test_every_flag_in_a_usage_example_is_defined_by_its_parser(self):
        offenders = {}
        examined = 0
        for path in _tools():
            source = path.read_text(encoding="utf-8", errors="replace")
            try:
                tree = ast.parse(source)
            except SyntaxError as e:  # pragma: no cover
                offenders[path.name] = f"does not parse: {e}"
                continue
            doc = ast.get_docstring(tree) or ""
            shown = _usage_flags(doc, path.name)
            if not shown:
                continue
            examined += 1
            defined = _parser_flags(tree)
            command = _delegated_subcommand(tree)
            if command is not None:
                defined |= _cli_subcommand_flags(command)
            missing = sorted(shown - defined)
            if missing:
                offenders[path.name] = missing
        self.assertEqual(
            offenders, {},
            "these tools show flags in their own usage example that their "
            f"parser does not define: {offenders}. Either add the argument or "
            "fix the example -- a usage line nobody can run is worse than none, "
            "because it reads as verified.")
        # The count is asserted so that a regression in the extractor -- which
        # would make this pass by examining nothing -- is visible.
        self.assertGreater(examined, 5,
                           f"only {examined} tools had a parseable usage "
                           "example; the extractor is probably broken")


@unittest.skipUnless(TOOLS.is_dir(), f"scripts/ not present at {TOOLS}")
class TheExtractorItself(unittest.TestCase):
    """The check's own two sides, on constructed input.

    Without these the test above is one function trusted to be right about
    every tool, and a bug in it reads as a pass.
    """

    def test_it_finds_a_flag_in_a_continued_shell_line(self):
        doc = ("Usage::\n\n"
               "    python scripts/thing.py \\\n"
               "        --flags ../x \\\n"
               "        --out ../y\n")
        self.assertEqual(_usage_flags(doc, "thing.py"), {"--flags", "--out"})

    def test_it_ignores_another_tools_flags_in_later_prose(self):
        doc = ("Usage::\n\n"
               "    python scripts/thing.py --real 1\n\n"
               "It drives run_flight.py, which takes --s2-jobs and --chunks.\n")
        self.assertEqual(_usage_flags(doc, "thing.py"), {"--real"})

    def test_it_reads_no_flags_when_the_file_is_never_invoked(self):
        doc = "A module that documents nothing runnable.\n"
        self.assertEqual(_usage_flags(doc, "thing.py"), set())

    def test_it_strips_trailing_punctuation_and_equals_values(self):
        doc = ("Usage::\n\n"
               "    python scripts/thing.py --a=5 --b.\n")
        self.assertEqual(_usage_flags(doc, "thing.py"), {"--a", "--b"})

    def test_the_parser_side_reads_add_argument_calls(self):
        tree = ast.parse('import argparse\n'
                         'ap = argparse.ArgumentParser()\n'
                         'ap.add_argument("--one")\n'
                         'ap.add_argument("-t", "--two")\n')
        self.assertEqual(_parser_flags(tree), {"--one", "--two", "--help"})

    def test_the_real_defect_would_have_been_caught(self):
        """``ingest_review_flags.py``'s usage block named ``--proc`` while the
        parser defined only ``--flags``, ``--out`` and ``--queue-out``.
        Reconstructed here so the check is shown to fire, not assumed to."""
        doc = ("Usage, from ``python_port/``::\n\n"
               f"    .venv/Scripts/python.exe {_INGEST} \\\n"
               "        --proc ../_decoded/proc.x.nc \\\n"
               "        --flags ../_decoded/flags_export \\\n"
               "        --out ../_decoded/review_labels.json\n")
        tree = ast.parse('import argparse\n'
                         'ap = argparse.ArgumentParser()\n'
                         'ap.add_argument("--flags")\n'
                         'ap.add_argument("--out")\n'
                         'ap.add_argument("--queue-out")\n')
        shown = _usage_flags(doc, "ingest_review_flags.py")
        self.assertIn("--proc", shown)
        self.assertEqual(sorted(shown - _parser_flags(tree)), ["--proc"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
