# SPDX-License-Identifier: BSD-3-Clause
"""Every example notebook opens with a Before this / Next-or-Related / Needs line that is true.

**The defect this was written after.** The author, 2026-10-15: *"there needs to be a flow
across notebooks too"*. Each of the 54 notebooks in ``examples/ORDER.toml`` now ends cell 0
with a generated line, ``**Before this:** ... **Next:** ... **Needs:** ...`` (tracks 1-3, the
sequence) or ``**Before this:** ... **Related:** ... **Needs:** ...`` (tracks 4-7, dip-in).
Nothing read it: a renamed notebook, a reordered track or a regenerated line could leave a
dead link or a ``Next`` that skips a notebook, and ``test_notebook_links`` would catch only
the dead link.

The two sides come from different places: the expected successor is read from ``ORDER.toml``
(the registry); the actual links come from each notebook's own cell 0. The generator is not
imported. The Next of the last notebook of a track is the documented track end: track 1 leads
into track 3, tracks 2 and 3 end at the examples index. ``TestFlowCheckFires`` runs the checker
on synthetic notebooks (line missing, link dead, Next wrong) so a check that matches nothing
cannot pass silently (2026-10-16).
"""

from __future__ import annotations

import json
import posixpath
import re
import tempfile
import tomllib
import unittest
from pathlib import Path
from urllib.parse import unquote

from tests._hygiene import hygiene
from tests._markdown_links import MD_LINK, ROOT
from tests._repo import repo_only

EXAMPLES = ROOT / "examples"
SEQUENCE_TRACKS = ("1_getting_started", "2_processing", "3_validation")
#: Where a track's last notebook sends the reader (path relative to ``examples/``).
TRACK_END = {
    "1_getting_started": "3_validation/01_validate_against_a_product.ipynb",
    "2_processing": "README.md",
    "3_validation": "README.md",
}
#: Optional extra -> the package the Needs parenthetical names for it (pyproject.toml).
EXTRA_PACKAGES = {"extra": "matplotlib", "zarr": "xarray", "parquet": "pyarrow", "jit": "numba"}
#: The Needs grammar (measured from the notebooks, 2026-10-30), a required part, an optional
#: part, then a full stop:
#:   required = "core package only" | "the enhancements package"
#:            | ["the enhancements package and "] PIP " (" <packages of the extras> ")"
#:   optional = "" | " (" ("the enhancements package" | PIP) " adds an optional section)"
#:   PIP      = `pip install "arrayprobe[<extras>]"`
#: Each label below must be used by some notebook, so the grammar holds no stale branch.
NEEDS_REQUIRED = frozenset({"core", "enhancements", "pip", "enhancements+pip"})
NEEDS_OPTIONAL = frozenset({"none", "enhancements", "pip"})
_PIP = r'`pip install "arrayprobe\[([a-z]+(?:,[a-z]+)*)\]"`'
_PIP_WITH_PACKAGES = re.compile(_PIP + r" \(([^()]+)\)")
_NEEDS_OPTIONAL = re.compile(r" \(([^()]+?) adds (?:an optional section|optional sections)\)$")
FIRST_NOTEBOOK = "1_getting_started/01_start_here.ipynb"  # "nothing; this is the first notebook"
_MARKER = re.compile(r"\*\*(Before this|Next|Related|Needs):\*\*")


def _cell0(nb: dict) -> str:
    cells = nb.get("cells", [])
    return "".join(cells[0].get("source", [])) if cells else ""


def parse_flow(nb: dict) -> tuple[dict[str, str] | None, int]:
    """The flow line's segments by marker, and how many such lines cell 0 holds."""
    lines = [ln for ln in _cell0(nb).split("\n") if ln.startswith("**Before this:**")]
    if not lines:
        return None, 0
    parts = _MARKER.split(lines[-1])  # ['', 'Before this', text, 'Next', text, ...]
    return {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}, len(lines)


def _extras(group: str) -> list[str] | None:
    extras = group.split(",")
    ok = len(set(extras)) == len(extras) and all(e in EXTRA_PACKAGES for e in extras)
    return extras if ok else None


def needs_shape(text: str) -> tuple[str, str] | None:
    """(required label, optional label) of a Needs text, or None when it is off the grammar."""
    if not text.endswith("."):
        return None
    body, optional, opt_extras = text[:-1], "none", []
    m = _NEEDS_OPTIONAL.search(body)
    if m:
        what, body = m.group(1), body[:m.start()]
        pip = re.fullmatch(_PIP, what)
        if what == "the enhancements package":
            optional = "enhancements"
        elif pip and _extras(pip.group(1)):
            optional, opt_extras = "pip", _extras(pip.group(1))
        else:
            return None
    if body in ("core package only", "the enhancements package"):
        required = "core" if body.startswith("core") else "enhancements"
    else:
        prefix = "the enhancements package and "
        required = "enhancements+pip" if body.startswith(prefix) else "pip"
        pip = _PIP_WITH_PACKAGES.fullmatch(body.removeprefix(prefix))
        extras = _extras(pip.group(1)) if pip else None
        if not extras or pip.group(2).split(", ") != [EXTRA_PACKAGES[e] for e in extras]:
            return None
        if set(extras) & set(opt_extras):
            return None
    if "enhancements" in required and optional == "enhancements":
        return None
    return required, optional


def links_of(text: str) -> list[str]:
    return [m.group(1) for m in MD_LINK.finditer(text)]


def notebook_problems(name: str, track: str, nb: dict, examples: Path,
                      expected_next: str | None) -> list[str]:
    """Everything wrong with one notebook's flow line (``name`` relative to ``examples``)."""
    flow, count = parse_flow(nb)
    if flow is None:
        return [f"{name}: cell 0 has no '**Before this:**' line"]
    out = []
    if count != 1:
        out.append(f"{name}: cell 0 has {count} flow lines, wants exactly one")
    want_kind = "Next" if track in SEQUENCE_TRACKS else "Related"
    if want_kind not in flow:
        out.append(f"{name}: no **{want_kind}:** (track {track} wants it)")
    if "Before this" not in flow or "Needs" not in flow:
        out.append(f"{name}: flow line lacks Before this or Needs")
        return out
    if not links_of(flow["Before this"]) and name != FIRST_NOTEBOOK:
        out.append(f"{name}: 'Before this' has no link")
    if needs_shape(flow["Needs"]) is None:
        out.append(f"{name}: Needs phrase is off the grammar: {flow['Needs']!r}")
    here = posixpath.dirname(name)
    for kind, text in flow.items():
        for link in links_of(text):
            path = unquote(link.split("#", 1)[0])
            if path and not (examples / here / path).is_file():
                out.append(f"{name}: {kind} link {link} does not resolve")
    if want_kind == "Next" and want_kind in flow and expected_next is not None:
        links = links_of(flow["Next"])
        got = (posixpath.normpath(posixpath.join(here, unquote(links[0].split("#")[0])))
               if links else None)
        if got != expected_next:
            out.append(f"{name}: Next is {got}, ORDER.toml says {expected_next}")
    return out


def expected_successors(order: list[dict]) -> dict[str, str]:
    """Each sequence-track notebook's designed Next: the successor, or the track end."""
    nxt: dict[str, str] = {}
    for track in SEQUENCE_TRACKS:
        seq = [e["old"] for e in sorted((e for e in order if e["track"] == track),
                                        key=lambda e: e["number"])]
        nxt.update(zip(seq[:-1], seq[1:], strict=True))
        nxt[seq[-1]] = TRACK_END[track]
    return nxt


def _order() -> list[dict]:
    with (EXAMPLES / "ORDER.toml").open("rb") as fh:
        return tomllib.load(fh)["notebook"]


def flow_problems(examples: Path = EXAMPLES) -> list[str]:
    order = _order()
    nxt = expected_successors(order)
    out: list[str] = []
    for e in order:
        nb = json.loads((examples / e["old"]).read_text(encoding="utf-8"))
        out += notebook_problems(e["old"], e["track"], nb, examples, nxt.get(e["old"]))
    return out


@hygiene
@repo_only
class TestNotebookFlow(unittest.TestCase):
    def test_every_notebook_opens_with_a_true_flow_line(self):
        self.assertEqual([], flow_problems())

    def test_needs_grammar_branches_are_all_in_use(self):
        """A grammar branch allowed but used by no notebook is a stale allowance."""
        shapes = set()
        for e in _order():
            flow, _ = parse_flow(json.loads((EXAMPLES / e["old"]).read_text(encoding="utf-8")))
            shapes.add(needs_shape(flow["Needs"]))
        self.assertEqual(NEEDS_REQUIRED, {s[0] for s in shapes if s})
        self.assertEqual(NEEDS_OPTIONAL, {s[1] for s in shapes if s})

    def test_extra_packages_match_pyproject(self):
        """Each extra the grammar names exists, and brings the package its parenthetical names."""
        with (ROOT / "pyproject.toml").open("rb") as fh:
            extras = tomllib.load(fh)["project"]["optional-dependencies"]
        for extra, package in EXTRA_PACKAGES.items():
            with self.subTest(extra=extra):
                self.assertIn(extra, extras)
                self.assertTrue(any(r.startswith(package) for r in extras[extra]), extras[extra])


def _nb(cell0: str) -> dict:
    return {"cells": [{"cell_type": "markdown", "metadata": {}, "source": [cell0]}]}


@hygiene
class TestFlowCheckFires(unittest.TestCase):
    """The checker on synthetic notebooks: a good one passes, each defect is caught."""

    NAME = "1_getting_started/02_b.ipynb"
    GOOD = ("# B\n\n**Before this:** [01_a](01_a.ipynb) (one). **Next:** [03_c](03_c.ipynb). "
            "**Needs:** core package only.")

    def _run(self, text: str) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "1_getting_started").mkdir()
            for f in ("01_a.ipynb", "03_c.ipynb"):
                (d / "1_getting_started" / f).write_text("{}")
            return notebook_problems(self.NAME, "1_getting_started", _nb(text), d,
                                     "1_getting_started/03_c.ipynb")

    def test_a_good_notebook_passes(self):
        self.assertEqual([], self._run(self.GOOD))

    def test_missing_line_fires(self):
        self.assertTrue(any("no '**Before this:**'" in p for p in self._run("# B\n\nNothing.")))

    def test_dead_link_fires(self):
        problems = self._run(self.GOOD.replace("(03_c.ipynb)", "(03_gone.ipynb)"))
        self.assertTrue(any("does not resolve" in p for p in problems), problems)

    def test_wrong_next_fires(self):
        problems = self._run(self.GOOD.replace("[03_c](03_c.ipynb)", "[01_a](01_a.ipynb)"))
        self.assertTrue(any("ORDER.toml says" in p for p in problems), problems)

    def test_unknown_needs_phrase_fires(self):
        problems = self._run(self.GOOD.replace("core package only.", "a GPU."))
        self.assertTrue(any("Needs phrase" in p for p in problems), problems)

    def test_every_grammar_branch_passes(self):
        pip = '`pip install "arrayprobe[extra,zarr]"` (matplotlib, xarray)'
        for needs in ("core package only.", "the enhancements package.", f"{pip}.",
                      f"the enhancements package and {pip}.",
                      "core package only (the enhancements package adds an optional section).",
                      f'{pip} (`pip install "arrayprobe[parquet]"` adds an optional section).'):
            with self.subTest(needs=needs):
                self.assertEqual([], self._run(self.GOOD.replace("core package only.", needs)))

    def test_off_grammar_needs_fire(self):
        for needs in ('`pip install "arrayprobe[extra]"` (xarray).',          # wrong package
                      '`pip install "arrayprobe[gpu]"` (cuda).',               # unknown extra
                      '`pip install "arrayprobe[extra]"`.',                    # no packages
                      '`pip install "arrayprobe[extra]"` (matplotlib)',        # no full stop
                      "the enhancements package (the enhancements package adds an optional "
                      "section).",                                             # contradiction
                      "core package only (a GPU adds an optional section).",   # unknown optional
                      'pip install "arrayprobe[extra]" (matplotlib).'):        # not code-quoted
            with self.subTest(needs=needs):
                problems = self._run(self.GOOD.replace("core package only.", needs))
                self.assertTrue(any("Needs phrase" in p for p in problems), problems)

    def test_empty_before_this_fires(self):
        problems = self._run(self.GOOD.replace("[01_a](01_a.ipynb) (one)", "nothing"))
        self.assertTrue(any("'Before this' has no link" in p for p in problems), problems)

    def test_wrong_kind_for_the_track_fires(self):
        problems = self._run(self.GOOD.replace("**Next:**", "**Related:**"))
        self.assertTrue(any("wants it" in p for p in problems), problems)

    def test_duplicate_line_fires(self):
        problems = self._run(self.GOOD + "\n\n" + self.GOOD)
        self.assertTrue(any("exactly one" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
