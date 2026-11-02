# SPDX-License-Identifier: BSD-3-Clause
"""``docs/_build/clidoc.py`` documents nested subcommands, not only the top level.

Until 2026-09-15 the generator walked only ``build_parser()``'s first level, so the CLI
reference page showed ``soda2 {run,enhancements}`` but never ``soda2 run --out`` -- a nested
verb's own flags appeared nowhere. The two sides of each
check come from different places: the parser is walked here independently of the generator's
own walk, and every flag it declares must be found under the matching heading of the page.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
import unittest
from pathlib import Path

from tests._repo import repo_only

from arrayprobe import cli

ROOT = Path(__file__).resolve().parents[1]
CLIDOC = ROOT / "docs" / "_build" / "clidoc.py"


def _load_clidoc():
    if not CLIDOC.is_file():  # an sdist carries no docs/_build/
        raise unittest.SkipTest(f"{CLIDOC} absent (sdist)")
    spec = importlib.util.spec_from_file_location("docs_clidoc", CLIDOC)
    assert spec is not None and spec.loader is not None
    mod = sys.modules.get(spec.name)
    if mod is None:
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
    return mod


def _nested(parser: argparse.ArgumentParser, path: tuple[str, ...] = ()):
    """An independent walk: every (path, parser) below the top level."""
    for action in parser._actions:  # noqa: SLF001
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                yield (*path, name), sub
                yield from _nested(sub, (*path, name))


def _page_sections(text: str) -> dict[str, str]:
    """Heading text (the backticked command) -> the section body under it."""
    out: dict[str, str] = {}
    current = None
    for line in text.splitlines():
        if line.startswith("#") and "`" in line:
            current = line.split("`")[1]
            out[current] = ""
        elif current is not None:
            out[current] += line + "\n"
    return out


@repo_only
class NestedSubcommandsAreDocumented(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.clidoc = _load_clidoc()
        cls.page = cls.clidoc.render()
        cls.sections = _page_sections(cls.page)

    def test_every_nested_verb_has_its_own_section(self):
        nested = [p for p, _ in _nested(cli.build_parser()) if len(p) > 1]
        self.assertTrue(nested, "the parser declares no nested verb -- the check would be vacuous")
        for path in nested:
            with self.subTest(command=" ".join(path)):
                self.assertIn(" ".join(path), self.sections)

    def test_soda2_run_documents_out_and_the_config_note(self):
        body = self.sections["soda2 run"]
        self.assertIn("--out", body)
        self.assertIn("No [fidelity]", body)
        self.assertIn("numpy.float32", body)

    def test_every_flag_of_every_command_is_on_the_page_under_its_heading(self):
        for path, sub in _nested(cli.build_parser()):
            body = self.sections[" ".join(path)]
            # The three per-stage verbs run only the v3.1.4 engine, absent from the public
            # package: their section gives the `arrayprobe run` route instead of their flags.
            if path[0] in self.clidoc._STAGE_VERB_NOTES:  # noqa: SLF001
                with self.subTest(command=" ".join(path)):
                    self.assertIn("arrayprobe run", body)
                    self.assertIn("[run].engine = \"3.5\"", body)
                continue
            for action in sub._actions:  # noqa: SLF001
                # A flag hidden with help=argparse.SUPPRESS (the v3.1.4-only flags when that
                # engine is absent) is not on the page, by design.
                if action.help == argparse.SUPPRESS:
                    continue
                for flag in action.option_strings:
                    with self.subTest(command=" ".join(path), flag=flag):
                        self.assertIn(flag, body)

    def test_heading_depth_follows_nesting(self):
        self.assertIn("\n## `soda2`\n", self.page)
        self.assertIn("\n### `soda2 run`\n", self.page)
        self.assertIn("\n### `soda2 enhancements`\n", self.page)

    def test_a_three_level_parser_is_walked_to_the_leaf(self):
        """The generator's walk is not limited to two levels."""
        top = argparse.ArgumentParser(prog="x")
        a = top.add_subparsers().add_parser("a")
        b = a.add_subparsers().add_parser("b")
        b.add_subparsers().add_parser("c").add_argument("--deep")
        paths = [p for p, _ in self.clidoc._sections(top)]
        self.assertEqual(paths, [("a",), ("a", "b"), ("a", "b", "c")])

    def test_a_leaf_parser_has_no_subcommands(self):
        self.assertEqual(self.clidoc._subcommands(argparse.ArgumentParser()), [])


if __name__ == "__main__":
    unittest.main()
