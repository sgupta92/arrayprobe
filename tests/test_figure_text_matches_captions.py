# SPDX-License-Identifier: BSD-3-Clause
"""Text drawn INSIDE a figure image must not go stale against its caption.

WHY THIS EXISTS. `test_figure_inputs_are_current.py` re-derives a figure's
*registry* numbers from the data on disk. It has no view of text the figure
script draws directly onto the image itself -- a title, an axis label, an
in-plot annotation -- because that text never touches the registry or the
section markdown; it is composed inside the `.py` generator and baked into
the PNG at render time. The author found this exact class twice by hand
(in the paper-figure review): Figure 10's
in-image ``fig.suptitle`` reported a freshly re-measured
``particles_per_record``, while the *caption* in the paper's evaluation section
still carried the number from an earlier run -- both read fine on their own,
and nothing compared them.

HOW THE TWO SIDES DIFFER. One side is what a figure script's own matplotlib
calls draw, recovered from the outside by `_figure_text_probe.py`, which
patches `Axes.set_title`/`set_xlabel`/`set_ylabel`/`text` and
`Figure.suptitle`/`text` before running the script -- no figure needs a
`--print-text` mode of its own, so a new figure is covered by construction.
The other side is the caption markdown in `paper/sections/*.md`, run through
`build_paper.py`'s own `substitute()` so a `{{dotted.path}}` placeholder
resolves to the same registry value the manuscript itself renders. The two
recovery mechanisms share no code and would not go stale together.

WHICH DIRECTION IS CHECKED, AND WHY. For each of the small set of *unit
classes* below (a percentage, a "particles ... per record" rate, an ISO or
US-style date, a `base<flight-stem>` token), a claim made in the CAPTION must
have a match among the values actually DRAWN -- not the reverse. A figure
routinely draws numbers a caption never restates (Figure 8's per-bar particle
counts, its "+1.60 %"/"+5.89 %" per-mechanism annotations); requiring every
drawn number to reappear in the caption made this check fail immediately on
that unrelated content. The actual defect ran the other way: the freshly
regenerated image was right and the hand-typed caption had gone stale. So the
caption is what is held to account, using only the classes it actually
invokes -- a caption with no percentage in it makes no percentage claim to
check. Channel/probe/version tokens (`.H`/`.V`, `2DS`/`HVPS`, `v3.1.4`/`v3.5`)
are checked the other way, symmetrically: if title and caption each name a
*different* member of the same mutually-exclusive group, that is a
contradiction regardless of which side is "new".

WHAT THIS CANNOT CHECK. Legend labels pulled from a plotted artist's own
`label=` kwarg rather than a `.text()`/`.set_title()` call (documented in
`_figure_text_probe.py`); whether a number that appears nowhere in either
side is nonetheless wrong; a figure whose generator cannot run in this
environment (its raw inputs are gitignored, machine-local data -- see
`test_figure_inputs_are_current.py`'s own docstring) draws nothing and is
skipped, not failed, so the check runs everywhere but only bites where a
figure's inputs are actually present.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

from tests._repo import repo_only
from tests._slow import slow

ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / "paper"
SECTIONS = PAPER / "sections"
FIGURES = PAPER / "figures"
PROBE = Path(__file__).resolve().parent / "_figure_text_probe.py"

#: Same shape as test_paper_figures.py's own `_PLACED` -- `![caption](figures/name.png)`.
#: Kept as a second, independent definition on purpose: this module's
#: comparison must not depend on that module's regex object staying exactly
#: as written, only on the same public Markdown convention.
_PLACED = re.compile(r"!\[(.*?)\]\((?:figures/)?([^)]+)\)", re.S)

#: (name, pattern-with-one-capture-group, absolute tolerance). The tolerance
#: absorbs the drawn text's own rounding (this project's figures format with
#: `:.1f`/`:.2f`) against a caption substituted at full registry precision --
#: 0.06 comfortably covers a `:.1f` rounding's worst case of 0.05.
_NUMERIC_CLASSES = [
    ("%", re.compile(r"([-+]?\d+(?:\.\d+)?)\s*%"), 0.06),
    ("particles/record",
     re.compile(r"([-+]?\d+(?:\.\d+)?)\s*particles(?:/record|\s*per\s*record)",
                re.I), 0.06),
]

#: Exact-match classes: a caption's ISO/US date or flight stem must appear
#: verbatim among the drawn strings, not merely close.
_EXACT_CLASSES = [
    ("ISO date", re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")),
    ("US-style date", re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b")),
    ("flight stem", re.compile(r"\b(base\d{9,})\b")),
]

#: Mutually-exclusive token groups. A title asserting one member and a
#: caption asserting a *different* member of the same group is the exact
#: shape of the Figure-10 class the author named (".V" drawn, ".H" captioned).
_TOKEN_GROUPS = [
    (r"\.H\b", r"\.V\b"),
    (r"\b2DS\b", r"\bHVPS\b"),
    (r"\bv3\.1\.4\b", r"\bv3\.5\b"),
]


def _placed_figures() -> dict[str, str]:
    """{image filename stem -> raw (unsubstituted) caption}, first placement wins."""
    out: dict[str, str] = {}
    for path in sorted(SECTIONS.glob("*.md")):
        body = path.read_text(encoding="utf-8")
        for m in _PLACED.finditer(body):
            stem = Path(m.group(2)).stem
            out.setdefault(stem, m.group(1))
    return out


def _load_build_paper():
    spec = importlib.util.spec_from_file_location("build_paper", PAPER / "build_paper.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("build_paper", mod)
    spec.loader.exec_module(mod)
    return mod


def drawn_text_for(script: Path) -> list[str]:
    """Run one figure script under the text probe; [] if it drew nothing.

    A figure whose on-disk inputs are gitignored, machine-local data (most of
    them -- see `test_figure_inputs_are_current.py`) prints ``MISSING ...``
    and returns early; the probe still exits 0 with an empty drawn-text list,
    which this function treats the same as any other empty result: nothing to
    check here, not a failure. A non-zero exit or unparsable output likewise
    yields [] rather than raising, so an environment lacking a figure's data
    cannot fail this test -- only a genuine title/caption contradiction can.
    """
    try:
        proc = subprocess.run(
            [sys.executable, str(PROBE), str(script)],
            capture_output=True, text=True, cwd=str(ROOT), timeout=120)
    except subprocess.TimeoutExpired:
        return []
    for line in proc.stdout.splitlines():
        if line.startswith("DRAWN_TEXT_JSON:"):
            try:
                return json.loads(line[len("DRAWN_TEXT_JSON:"):])
            except json.JSONDecodeError:
                return []
    return []


def numeric_problems(drawn: list[str], caption: str) -> list[str]:
    """Caption claims (only) held against the drawn text -- see module docstring."""
    joined = " ".join(drawn)
    problems = []
    for name, pattern, tol in _NUMERIC_CLASSES:
        drawn_vals = [float(v) for v in pattern.findall(joined)]
        caption_vals = [float(v) for v in pattern.findall(caption)]
        if not drawn_vals or not caption_vals:
            continue
        for cv in caption_vals:
            if not any(abs(cv - dv) <= tol for dv in drawn_vals):
                problems.append(
                    f"caption claims {cv}{'' if name == '%' else ' ' + name} but "
                    f"no drawn text is within {tol} of it (drawn values: {drawn_vals})")
    for name, pattern in _EXACT_CLASSES:
        drawn_vals = pattern.findall(joined)
        caption_vals = pattern.findall(caption)
        if not drawn_vals or not caption_vals:
            continue
        for cv in caption_vals:
            if cv not in drawn_vals:
                problems.append(
                    f"caption names {name} {cv!r} but the drawn text does not "
                    f"(drawn: {drawn_vals})")
    return problems


def token_problems(drawn: list[str], caption: str) -> list[str]:
    joined = " ".join(drawn)
    problems = []
    for group in _TOKEN_GROUPS:
        title_hits = {t for t in group if re.search(t, joined)}
        caption_hits = {t for t in group if re.search(t, caption)}
        if title_hits and caption_hits and title_hits.isdisjoint(caption_hits):
            problems.append(
                f"the drawn text uses {sorted(title_hits)} but the caption uses "
                f"{sorted(caption_hits)} -- contradiction")
    return problems


class SyntheticContradictionsAreDetected(unittest.TestCase):
    """The comparison logic itself, exercised on fabricated input -- runs
    everywhere, no subprocess, no figure data required. A guard is not done
    until it has been made to fire (the project's guard doctrine);
    this is that firing, kept in the suite as a permanent regression rather
    than a one-off manual edit-and-revert."""

    def test_a_stale_caption_percentage_is_caught(self):
        drawn = ["5.6 particles/record, each a single isolated diode"]
        caption = "the channel produces 7.1 particles per record on average"
        problems = numeric_problems(drawn, caption)
        self.assertTrue(problems, "a caption number with no drawn counterpart "
                                   "should have been flagged")

    def test_the_real_figure10_numbers_agree(self):
        """The actual current strings (title freshly measured, caption typed
        to match) must NOT be flagged -- a check that fires on everything is
        as useless as one that fires on nothing."""
        drawn = ["5.6 particles/record, each a single isolated diode"]
        caption = "the channel produces 5.6 particles per record on average"
        self.assertEqual(numeric_problems(drawn, caption), [])

    def test_a_channel_contradiction_is_caught(self):
        drawn = ["10 consecutive real particles, .V channel, 2016-09-06"]
        caption = "what the fouled .H channel actually recorded"
        problems = token_problems(drawn, caption)
        self.assertTrue(problems, "title says .V, caption says .H -- must be "
                                   "flagged as a contradiction")

    def test_matching_channel_tokens_are_not_flagged(self):
        drawn = ["10 consecutive real particles, .V channel, 2016-09-06"]
        caption = "what the fouled .V channel actually recorded"
        self.assertEqual(token_problems(drawn, caption), [])

    def test_an_unmentioned_drawn_number_is_not_flagged(self):
        """Figure 8's per-bar particle counts (33,141 / 53,586) have no
        caption counterpart and must not be flagged -- see module docstring
        on why the check runs caption-to-drawn, not drawn-to-caption."""
        drawn = ["+61.7 %", "33,141", "53,586", "+1.60 %", "+5.89 %"]
        caption = "the two configurations differ by 61.69 % in accepted particles"
        self.assertEqual(numeric_problems(drawn, caption), [])


@repo_only
@slow
@unittest.skipUnless(SECTIONS.is_dir(), "no drafted sections yet")
class DrawnTextMatchesItsCaption(unittest.TestCase):
    """The real generators, the real captions -- see module docstring for
    why a figure with no drawable inputs here is skipped rather than failed.

    Gated (measured 2026-09-14: ~47 s for all 12 figures, each paying a
    subprocess's own matplotlib/numpy/netCDF4 import cost) -- its cost is
    running every figure generator, not what it asserts; the assertion logic
    itself is exercised cheaply and unconditionally by
    `SyntheticContradictionsAreDetected` above."""

    @classmethod
    def setUpClass(cls):
        cls.build_paper = _load_build_paper()
        cls.figures = _placed_figures()

    def test_no_figure_contradicts_its_caption(self):
        problems: list[str] = []
        checked = 0
        for stem, raw_caption in sorted(self.figures.items()):
            script = FIGURES / f"{stem}.py"
            if not script.is_file():
                continue  # test_paper_figures.py already flags an orphan figure
            drawn = drawn_text_for(script)
            if not drawn:
                continue  # this environment cannot regenerate this figure
            caption = self.build_paper.substitute(raw_caption)
            figure_problems = numeric_problems(drawn, caption) + token_problems(drawn, caption)
            checked += 1
            problems.extend(f"{stem}.py: {p}" for p in figure_problems)
        self.assertGreater(
            checked, 0,
            "no figure could be regenerated in this environment, so nothing "
            "was actually compared -- this test would pass even if the "
            "mechanism below it were broken")
        self.assertEqual(
            problems, [],
            "a figure's drawn text contradicts its own caption:\n  " +
            "\n  ".join(problems))



class TheProbeWritesNothing(unittest.TestCase):
    """Running a figure script under the probe leaves the tracked figures untouched."""

    def test_savefig_under_the_probe_writes_no_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out.png"
            script = Path(d) / "fig_probe_check.py"
            lines = ["import matplotlib.pyplot as plt",
                     "fig, ax = plt.subplots()",
                     "ax.set_title('probe check')",
                     f"fig.savefig({str(out)!r})",
                     f"plt.savefig({str(out)!r})"]
            script.write_text("\n".join(lines) + "\n", encoding="utf-8")
            proc = subprocess.run([sys.executable, str(PROBE), str(script)],
                                  capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("probe check", proc.stdout)
            self.assertFalse(out.exists(), "the probe let a figure script write its output")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
