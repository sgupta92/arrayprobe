# SPDX-License-Identifier: BSD-3-Clause
"""Every ``scripts/*.py`` with a ``__main__`` entry answers ``--help`` with usage and exit 0.

On 2026-10-02 one tool crashed on ``--help``, taking it as a git revision;
the sweep that followed found eight more tools that ignored ``--help`` and started their work
(writing pages, mining transcripts, querying GitHub) and one (``wait_quiet.py``) that died on
``float('--help')``. Each now checks for a sole ``-h``/``--help`` before anything else runs.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PORT = Path(__file__).resolve().parents[1]
TOOLS = PORT / "scripts"

# tool file name -> why ``--help`` cannot answer yet. Empty since 2026-10-02: the three tools
# that exited at import on an unset input-path variable (build_labeling_tool,
# gallery_assemble_html, gallery_qa_verdicts) now answer --help before those paths resolve.
ALLOWED_TO_FAIL: dict[str, str] = {}


def entry_tools() -> list[Path]:
    return sorted(p for p in TOOLS.glob("*.py")
                  if 'if __name__ == "__main__":' in p.read_text(encoding="utf-8", errors="ignore"))


#: Present in the development repository, absent from a release tree (it does not ship).
ALLOWLIST = PORT / "scripts" / "release_allowlist.txt"


def ast_entry_tools() -> list[Path]:
    """The same discovery by a different method: a module-level ``if __name__ == "__main__"``
    found by parsing, not by matching one spelling of it, so a quoting change cannot drop a tool."""
    found = []
    for p in sorted(TOOLS.glob("*.py")):
        tree = ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
        for node in tree.body:
            test = getattr(node, "test", None) if isinstance(node, ast.If) else None
            if (isinstance(test, ast.Compare) and isinstance(test.left, ast.Name)
                    and test.left.id == "__name__" and len(test.comparators) == 1
                    and isinstance(test.comparators[0], ast.Constant)
                    and test.comparators[0].value == "__main__"):
                found.append(p)
                break
    return found


def release_shipped_entry_tools() -> set[str]:
    """Development view only: the entry tools the release builder ships, by its own rules."""
    spec = importlib.util.spec_from_file_location("_brt_tools_help",
                                                  TOOLS / "build_release_tree.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    rules = mod.parse_allowlist(ALLOWLIST.read_text(encoding="utf-8"))
    return {p.name for p in entry_tools()
            if mod.allowed(f"scripts/{p.name}", rules)
            and mod.never_ship(f"scripts/{p.name}") is None}


def run_help(path: Path) -> tuple[Path, int, str]:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        r = subprocess.run([sys.executable, str(path), "--help"], cwd=PORT, env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=120)
    except subprocess.TimeoutExpired:
        return path, -1, "timed out after 120 s"
    return path, r.returncode, r.stdout + r.stderr


class TestEveryToolAnswersHelp(unittest.TestCase):
    def test_help_exits_zero_with_a_usage_line(self):
        tools = [p for p in entry_tools() if p.name not in ALLOWED_TO_FAIL]
        # The floor is derived, not a count: discovery must find something, must agree with an
        # independent parse of the same directory, and (development view) must cover every entry
        # tool the release builder ships, so the release tree -- which ships fewer tools by
        # design -- answers for each of them.
        self.assertTrue(tools, f"the tool discovery found nothing under {TOOLS}")
        self.assertEqual([p.name for p in entry_tools()], [p.name for p in ast_entry_tools()],
                         "the marker scan and the parse disagree on which tools have a __main__")
        if ALLOWLIST.is_file():
            shipped = release_shipped_entry_tools()
            self.assertTrue(shipped, "the release builder ships no entry tool")
            self.assertLessEqual(shipped, {p.name for p in tools},
                                 "a shipped entry tool is missing from the discovery")
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(run_help, tools))
        bad = [f"{p.name}: exit {rc}: {out.strip()[-300:]}" for p, rc, out in results
               if rc != 0 or "usage" not in out.lower()]
        self.assertEqual(bad, [], "tools whose --help fails:\n" + "\n".join(bad))

    def test_allow_list_has_no_stale_entries(self):
        names = {p.name for p in entry_tools()}
        stale = sorted(set(ALLOWED_TO_FAIL) - names)
        self.assertEqual(stale, [], "allow-listed tools that no longer exist or have no __main__")
        for name in sorted(set(ALLOWED_TO_FAIL) & names):
            _, rc, out = run_help(TOOLS / name)
            self.assertFalse(rc == 0 and "usage" in out.lower(),
                             f"{name} now answers --help; remove it from ALLOWED_TO_FAIL")


if __name__ == "__main__":
    unittest.main()
