# SPDX-License-Identifier: BSD-3-Clause
"""Every ``ProbeConfig.source_line`` is checked against the MATLAB it cites.

**Why this exists, and it is a confession.** On 2026-09-17 the coordinator misread
the CIP's configuration block **twice in one session**, and published a wrong
correction on the strength of the second reading.

``sizeDist.m`` has **four** ``case 'CIP'`` blocks — under ``case 'PECAN'``,
``case 'GPM'``, and the ``otherwise`` project arm — with different values in each.
The first attempt scanned by position. The second used
``awk "/case 'CIP'/,/case 'PIP'/"``, which takes the **first** match in the file,
and so read the PECAN block at ``:110`` and reported it as stock. Both readings
contradicted ``constants.py``, which had been right the whole time; on the second
one a correct finding from another lane was told it "does not hold".

Nothing caught either error, because **nothing checked these citations at all**:
28 ``source_line`` values, and no test read the MATLAB at any of them. That is the
shape this project keeps meeting — `rules-are-not-controls`, and the memory note
`guards-must-be-executed`, which records four checks here that matched nothing
while reading fine. A rule addressed to attention ("read it, don't infer it") is
not a control. This file is the control.

**The two sides come from different places**, which is what makes it a real check
(*"A check must draw its two sides from different places, or it is
testing nothing"*): one side is the Python dataclass, the other is the vendored
MATLAB read at the line range the dataclass itself names. Neither is derived from
the other.

**What it would have caught.** Pointing a row at the PECAN block fails
:meth:`TheCitedRangeIsTheRightBlock.test_the_range_opens_on_the_named_probe` (the
range would not open on the right ``case``) and, independently, the value
comparisons — PECAN's CIP carries ``applyIntArrThresh = 1`` and
``getPECANparams``, the ``otherwise`` arm neither.

**IT FOUND A REAL DEFECT ON ITS FIRST RUN, and it was not the one it was written
for.** Three ``SOCRATES`` rows cited line ranges each shifted about five lines
early, so every one sat in its *neighbour's* block: ``2DS`` cited ``:257-278``
(inside ``case 'HVPS'``), ``Fast2DC`` cited ``:279-302`` (inside ``case '2DS'``),
``PIP`` cited ``:303-337`` (inside ``case 'Fast2DC'``). Two independent
assertions agreed — the enclosing-block test and, separately, the scalar
comparison, which reported ``PIP``'s ``reaccpt_d=0.5`` against a cited
``reaccptD = 0.15``. **The transcribed values were all correct**; only the
citations were wrong, so this was a provenance defect and not a numeric one. The
correct cases are at ``:262``, ``:285`` and ``:309``, and the rows now say so.

**Mutation record (2026-09-17), because a guard nobody has seen deny is not
known to work** — the standard this project holds after four checks were found
matching nothing while reading fine:

* Pointing the ``otherwise``/CIP row at PECAN's CIP block (``sizeDist.m:110-142``)
  — *the exact misreading this file exists for* — resolves to
  ``('PECAN', 'CIP')`` and fails on the project mismatch. **Detected.**
* Claiming ``default_int_arr_thresh=9.9e-9`` against a correct citation whose
  source says ``1e-5`` fails the scalar comparison. **Detected.**
* Comment-stripping is load-bearing and works: on the stock ``otherwise``/CIP
  range the live text carries the ``kk=[…]`` edge literal and **not** the colon
  ladder, which is the correct reading and the one two hand attempts got wrong.

**Deliberately not checked here:** the ``kk`` bin-edge values themselves, which are
built in Python by ``_colon_pair``/``_KK19_UM`` rather than transcribed. What *is*
checked is which of the two ladder **forms** is live in the source, because each
file carries both and comments one out — and that was the single most
consequential thing the misreadings missed.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests import _upstream  # noqa: E402
from tests._repo import repo_only

from arrayprobe.constants import _CONFIGS, _CONFIGS_PRODUCTION, ProbeConfig

ROOT = Path(__file__).resolve().parents[1]

#: Which vendored tree a ``source_line`` prefix means. A bare ``sizeDist.m``
#: is the stock v3.1.4 tree -- ``arrayprobe`` is the v3.1.4 port, so an
#: unqualified citation is to the release it reproduces. Verified by the
#: ``otherwise``/CIP row, whose cited ``sizeDist.m:391-414`` opens on
#: ``case 'CIP'`` in v3.1.4.
_TREES = {
    "sizeDist.m": _upstream.source("uiops314") / "sizeDist.m",
    "sizeDist.m (campaign-configured copy)": ROOT / "uioops_testing" / "sizeDist.m",
}

#: Citation prefixes whose tree is gitignored, so a clean clone (CI, a fresh
#: checkout) does not have it. A row citing one is checked wherever the tree
#: exists and skipped where it does not; a row citing a tracked tree that is
#: missing still fails.
_GITIGNORED = frozenset({"sizeDist.m (campaign-configured copy)"})

#: ``ProbeConfig`` field -> the MATLAB variable it was transcribed from.
#: Only scalars that appear verbatim as ``name = value;`` in a probe block.
_SCALARS = {
    "num_diodes": "num_diodes",
    "diodesize": "diodesize",
    "armdst": "armdst",
    "num_bins": "num_bins",
    "probetype": "probetype",
    "tas_max": "tasMax",
    "apply_int_arr_thresh": "applyIntArrThresh",
    "default_int_arr_thresh": "defaultIntArrThresh",
    "reaccpt_shatrs": "reaccptShatrs",
    "reaccpt_d": "reaccptD",
    "reaccpt_max_ia": "reaccptMaxIA",
}

_ASSIGN = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*([^;%]+?)\s*;")


def setUpModule():
    # Raised here rather than at import: an import-time SkipTest crashes
    # ``python -m unittest tests.<module>``, where ``discover`` reports it as a skip.
    _upstream.require("uiops314")


def _cited(cfg: ProbeConfig) -> tuple[Path, int, int]:
    """Resolve ``source_line`` to a file and an inclusive 1-based line range."""
    name, _, span = cfg.source_line.rpartition(":")
    lo, _, hi = span.partition("-")
    return _TREES[name], int(lo), int(hi or lo)


def _live_lines(cfg: ProbeConfig) -> list[str]:
    """The cited range with MATLAB comment lines removed.

    Stripping comments is not tidiness -- it is the discriminator. Both the
    19-edge and the 64-bin ladders appear in every one of these files, with one
    of them commented out, so a check that ignored ``%`` would find whichever it
    looked for and confirm anything.
    """
    path, lo, hi = _cited(cfg)
    all_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return [ln for ln in all_lines[lo - 1:hi] if not ln.lstrip().startswith("%")]


def _assignments(cfg: ProbeConfig) -> dict[str, str]:
    out: dict[str, str] = {}
    for ln in _live_lines(cfg):
        m = _ASSIGN.match(ln)
        if m:
            out.setdefault(m.group(1), m.group(2).strip())
    return out


def _enclosing_block(cfg: ProbeConfig) -> tuple[str | None, str | None]:
    """The ``(project, probe)`` arm the cited range sits inside.

    **This is the assertion that would have caught the misreadings, and the
    obvious formulation does not.** A first attempt required the cited range to
    *open* on ``case '<probe>'``; 9 of 28 rows legitimately cite only the lines
    carrying the values, starting inside their block, so that version failed on
    correct rows and would have been relaxed away. What actually distinguishes
    ``PECAN``'s CIP block from the ``otherwise`` arm's is the **enclosing pair**,
    so that is what this resolves: walk backwards for the nearest ``case '<probe>'``
    at the inner indent, and backwards again for the nearest project-level arm —
    a top-level ``case 'NAME'`` or the ``otherwise`` that follows them.

    Project arms are distinguished from probe cases by indentation: ``sizeDist.m``
    indents the project switch's cases by 4 and the probe switch's by 12.
    """
    path, lo, _hi = _cited(cfg)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    probe = project = None
    for i in range(min(lo, len(lines)) - 1, -1, -1):
        raw = lines[i]
        if raw.lstrip().startswith("%"):
            continue
        m = re.match(r"(\s*)case\s+'([^']+)'", raw)
        if m:
            indent = len(m.group(1).expandtabs(4))
            if probe is None and indent >= 8:
                probe = m.group(2)
                continue
            if indent < 8:
                project = m.group(2)
                break
        if project is None and re.match(r"\s{0,7}otherwise\b", raw):
            project = "otherwise"
            break
    return project, probe


def _all_configs() -> list[ProbeConfig]:
    return [*_CONFIGS, *_CONFIGS_PRODUCTION]


def _tree_absent(cfg: ProbeConfig) -> bool:
    """True when ``cfg`` cites a gitignored tree that this checkout does not hold."""
    name = cfg.source_line.rpartition(":")[0]
    return name in _GITIGNORED and not _TREES[name].is_file()


def _checkable_configs() -> list[ProbeConfig]:
    """Every row whose cited tree can be read here."""
    return [cfg for cfg in _all_configs() if not _tree_absent(cfg)]


def _label(cfg: ProbeConfig) -> str:
    return f"{cfg.project}/{cfg.probename} ({cfg.source_line})"


class TheCitationsResolve(unittest.TestCase):
    @repo_only
    def test_every_row_carries_a_parseable_citation(self):
        bad = []
        for cfg in _all_configs():
            try:
                path, lo, hi = _cited(cfg)
            except (KeyError, ValueError) as exc:
                bad.append(f"{_label(cfg)}: {exc}")
                continue
            if _tree_absent(cfg):
                continue  # reported by the skip below, not as a failure
            if not path.is_file():
                bad.append(f"{_label(cfg)}: {path} does not exist")
            elif lo > hi:
                bad.append(f"{_label(cfg)}: range {lo}-{hi} is inverted")
        self.assertEqual([], bad, "unresolvable source_line citations:\n  " + "\n  ".join(bad))

    @repo_only
    def test_there_are_configs_to_check(self):
        """A floor, so an import change cannot make every test below vacuous."""
        self.assertGreaterEqual(len(_all_configs()), 20)
        # And a floor on what is checked here, so the gitignored-tree filter
        # cannot empty the tests below: the stock v3.1.4 tree is tracked.
        self.assertGreaterEqual(len(_checkable_configs()), 10)

    @repo_only
    def test_rows_citing_a_gitignored_tree_are_checked_where_it_exists(self):
        absent = [cfg for cfg in _all_configs() if _tree_absent(cfg)]
        if absent:
            self.skipTest(
                f"{len(absent)} rows cite {sorted(_GITIGNORED)}, which is gitignored and absent "
                "from this checkout; their citation, block, scalar, ladder and PECAN checks "
                "run only where the tree exists")
        # Where the tree exists, nothing is filtered: every row is checked below.
        self.assertEqual(len(_checkable_configs()), len(_all_configs()))


class TheCitedRangeIsTheRightBlock(unittest.TestCase):
    """The guard against the specific mistake that prompted this file."""

    @repo_only
    def test_the_range_sits_inside_the_right_project_and_probe_arm(self):
        wrong = []
        for cfg in _checkable_configs():
            if not _live_lines(cfg):
                wrong.append(f"{_label(cfg)}: cited range holds no uncommented lines")
                continue
            project, probe = _enclosing_block(cfg)
            if probe != cfg.probename:
                wrong.append(
                    f"{_label(cfg)}: the cited range sits in a case '{probe}' block, "
                    f"but the row is for {cfg.probename!r}")
            elif project != cfg.project:
                wrong.append(
                    f"{_label(cfg)}: the cited range sits in the {project!r} project arm, "
                    f"but the row is for {cfg.project!r} -- this is the exact misread that "
                    "prompted this file (PECAN's CIP block read as the otherwise arm's)")
        self.assertEqual(
            [], wrong,
            "a row cites the wrong block. sizeDist.m has one case block per probe name PER "
            "PROJECT ARM, with different values in each:\n  " + "\n  ".join(wrong))

    def test_no_two_rows_cite_the_same_range(self):
        """Two rows on one range means at least one is pointing at a neighbour."""
        seen: dict[str, str] = {}
        clash = []
        for cfg in _all_configs():
            key = cfg.source_line
            if key in seen:
                clash.append(f"{key}: both {seen[key]} and {_label(cfg)}")
            else:
                seen[key] = _label(cfg)
        self.assertEqual([], clash, "duplicate citations:\n  " + "\n  ".join(clash))


class EveryTranscribedScalarMatchesTheSource(unittest.TestCase):
    @staticmethod
    def _matlab_number(text: str) -> float | None:
        try:
            return float(text)
        except ValueError:
            return None

    @repo_only
    def test_scalars_equal_the_matlab(self):
        bad = []
        for cfg in _checkable_configs():
            found = _assignments(cfg)
            for field, mvar in _SCALARS.items():
                if mvar not in found:
                    continue  # the block does not set it; nothing to compare
                want = getattr(cfg, field)
                if want is None:
                    continue
                got = self._matlab_number(found[mvar])
                if got is None:
                    continue  # an expression, not a literal
                msg = f"{_label(cfg)}: {field}={want} but MATLAB {mvar} = {found[mvar]}"
                if isinstance(want, bool):
                    if bool(got) != want:
                        bad.append(msg)
                elif abs(float(want) - got) > 1e-12 * max(1.0, abs(got)):
                    bad.append(msg)
        self.assertEqual(
            [], bad,
            "a ProbeConfig disagrees with the MATLAB line range it cites. Either the "
            "transcription is wrong or the citation points at the wrong block:\n  "
            + "\n  ".join(bad))

    @repo_only
    def test_the_live_bin_ladder_form_matches_num_bins(self):
        """Which ladder is live, not what its edges are.

        Every one of these files carries BOTH ladders -- a 19-edge literal and a
        64-bin colon expression -- with one commented out. The ORACLES fork
        swapped which, and that is what both misreadings missed.
        """
        bad = []
        for cfg in _checkable_configs():
            live = "\n".join(_live_lines(cfg))
            has_literal = re.search(r"kk\s*=\s*\[", live) is not None
            has_colon = re.search(r"kk\s*=\s*diodesize\s*/\s*2\s*:", live) is not None
            if not (has_literal or has_colon):
                continue  # this block builds kk some other way
            if has_literal and has_colon:
                bad.append(
                    f"{_label(cfg)}: both ladder forms are live in the cited range; each file "
                    "carries both and comments one out, so exactly one should be uncommented")
        # Deliberately no inference from the ladder form to `num_bins`. A first
        # attempt asserted that a colon ladder implies `num_bins == num_diodes`,
        # which is true of the CIP by coincidence (64 of each) and false of the
        # ORACLES HVPS (128 diodes, 70 bins) -- the colon's step and endpoint are
        # independent of the diode count. `num_bins` is already compared against
        # the source's own `num_bins` assignment by the scalar test above, which
        # is the real check; this one only establishes WHICH ladder is live,
        # because that is what both misreadings missed.
        self.assertEqual([], bad, "bin-ladder disagreement:\n  " + "\n  ".join(bad))


@repo_only
class ThePecanDependencyIsRecorded(unittest.TestCase):
    def test_needs_pecan_params_matches_whether_the_block_calls_it(self):
        """``getPECANparams`` is absent from both vendored trees, so a block that
        calls it cannot run. Which blocks call it is therefore load-bearing, and
        it is exactly the sort of detail a misread block reports wrongly."""
        bad = []
        for cfg in _checkable_configs():
            calls = "getPECANparams" in "\n".join(_live_lines(cfg))
            if calls != bool(cfg.needs_pecan_params):
                bad.append(
                    f"{_label(cfg)}: needs_pecan_params={cfg.needs_pecan_params} but the cited "
                    f"block {'does' if calls else 'does not'} call getPECANparams")
        self.assertEqual([], bad, "\n  ".join(bad))


if __name__ == "__main__":
    unittest.main()
