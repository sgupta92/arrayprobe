# SPDX-License-Identifier: BSD-3-Clause
"""The known-gaps page cites only refusals that still exist.

``docs/10-known-gaps.md`` lists what each engine does not port and
names, in its "Raised by" column, the module or exception that refuses it. On
2026-10-03 two rows (SODA-2 ``rakefix`` and ``.gz`` input) went stale the moment
their ports landed and nothing noticed. This guard resolves every name in that
column against ``python_port/src`` (and ``scripts/``): an exception name must
still be raised somewhere, and a module name must still contain a ``raise``.
A ``path:line`` citation must point inside the file.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests._hygiene import hygiene
from tests._repo import repo_only

PORT = Path(__file__).resolve().parents[1]
REPO = PORT
PAGE = REPO / "docs" / "10-known-gaps.md"
ROOTS = (PORT / "src", PORT / "scripts")

_TOKEN = re.compile(r"`([^`]+)`")
_EXC = re.compile(r"^[A-Z][A-Za-z0-9]*(NotPorted|Error|Warning)$")
_PATHLINE = re.compile(r"^([\w./-]+\.py):(\d+)")


def _sources() -> list[Path]:
    out: list[Path] = []
    for root in ROOTS:
        out += [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]
    return out


def _raised_by_cells(text: str) -> list[str]:
    """The "Raised by" cell of every table row under a header naming it."""
    cells: list[str] = []
    col = None
    for line in text.splitlines():
        if not line.startswith("|"):
            col = None
            continue
        parts = [c.strip() for c in line.strip().strip("|").split("|")]
        if "Raised by" in parts:
            col = parts.index("Raised by")
            continue
        if col is None or set(line) <= set("|- :"):
            continue
        if col < len(parts):
            cells.append(parts[col])
    return cells


def stale_citations(text: str, sources: list[Path]) -> list[str]:
    """Return one message per cited refusal that no longer exists."""
    by_stem: dict[str, list[Path]] = {}
    for p in sources:
        by_stem.setdefault(p.stem, []).append(p)
    bodies = {p: p.read_text(encoding="utf-8", errors="replace") for p in sources}
    problems: list[str] = []
    for cell in _raised_by_cells(text):
        # A parenthetical names MATLAB variables or lines, not refusal sites.
        for tok in _TOKEN.findall(re.sub(r"\([^)]*\)", "", cell)):
            tok = tok.strip()
            m = _PATHLINE.match(tok)
            if m:
                hits = [p for p in sources if p.as_posix().endswith(m.group(1))]
                if not hits:
                    problems.append(f"{tok}: no such file")
                elif int(m.group(2)) > len(bodies[hits[0]].splitlines()):
                    problems.append(f"{tok}: line past end of file")
                continue
            if tok.endswith(".m"):
                continue  # a MATLAB/IDL source, not a refusal site in the port
            if _EXC.match(tok):
                if not any(re.search(rf"\braise\s+{tok}\b", b) for b in bodies.values()):
                    problems.append(f"{tok}: no longer raised in the port")
                continue
            stem = tok.removesuffix(".py").split(".")[0]
            if not re.fullmatch(r"[a-z_][a-z0-9_]*", stem):
                continue
            files = by_stem.get(stem)
            if not files:
                problems.append(f"{tok}: no module {stem}.py in src or tools")
            elif not any(re.search(r"\braise\b", bodies[f]) for f in files):
                problems.append(f"{tok}: module refuses nothing (no raise)")
    return problems


@repo_only
@hygiene
class KnownGapsCiteLiveRefusals(unittest.TestCase):
    def test_page_has_raised_by_rows(self):
        self.assertGreaterEqual(len(_raised_by_cells(PAGE.read_text(encoding="utf-8"))), 5)

    def test_every_cited_refusal_still_exists(self):
        problems = stale_citations(PAGE.read_text(encoding="utf-8"), _sources())
        self.assertEqual(problems, [], "10-known-gaps.md cites refusals that are gone: "
                         "remove the ported row or say what part remains")

    def test_guard_fires_on_a_missing_exception(self):
        page = ("| Not ported | Raised by | Note |\n|---|---|---|\n"
                "| x | `FrobnicateNotPorted` (`pbp_writer`) | y |\n"
                "| z | `no_such_module_xyz` | w |\n"
                "| q | `pbp_writer.py:999999` | w |\n")
        problems = stale_citations(page, _sources())
        self.assertEqual(len(problems), 3, problems)


if __name__ == "__main__":
    unittest.main()
