# SPDX-License-Identifier: BSD-3-Clause
"""S2-c (``!pi`` is single precision, ``min_circle_fast.pro:34,37,41,51``) --
``double_pi_fix.corrected_min_circle_fast`` / ``.corrected_aspect_ratio``.

Bank cases come from ``gdl_oracle/run_soda2_min_circle_fast_bank.CASES`` (not the tracked JSON
directly) -- two of the 20 (``L_shape``, ``column_10010``) omit ``x``/``y`` from the golden file
(large synthetic arrays) and are only reconstructible through ``CaseSpec.py()``, exactly as
``tests/test_soda2_min_circle_fast.py::CharacterisedAgainstTheExactCircle`` does.

**Measured, not assumed, which cases actually change, and how.** The port's own
``test_right_angle_at_R_yields_three_corners_on_every_rectangle_like_case`` flags five cases
(``rect_4``, ``block_5x3``, ``outline_20x8``, ``disc_outline_r12``, ``rect_tas_1p037``) as
rectangle-like. Measuring :func:`corrected_min_circle_fast` against all 20 bank cases directly
(not read off that list) gives three distinct outcomes:

- **14 cases are bit-identical** to the port (``diam``, ``center``, ``corners``, ``area`` all
  equal) -- every case with no exact right angle at any candidate R.
- **2 cases** (``rect_4``, ``outline_20x8``) keep the **same corner count** (3) and the
  **same diam**, but the loop's mid-run swaps land on a different ``P``/``Q``/``R``
  assignment, so ``corners`` comes back in a different order/identity (e.g. ``[2,1,0]`` vs
  ``[0,1,2]``) -- the obtuse-angle tests at ``:37``/``:41`` fire during the loop, not only the
  final ``:51`` test, so widening the constant can reroute the walk even when the *final*
  branch taken is unchanged. Diam is unaffected either way.
- **4 cases** (``block_5x3``, ``disc_outline_r12``, ``rect_tas_1p037``, and ``L_shape`` -- not
  in the port's own five-case list at all, per
  ``CharacterisedAgainstTheExactCircle::test_S2_c_measured_directly_...``) change corner
  **count**, 3 -> 2, with ``diam`` agreeing to double rounding (worst case
  ``1.2176439171466038e-16`` relative, on ``rect_tas_1p037``). ``rect_4`` and ``outline_20x8``,
  despite being on the port's flagged list, do **not** change count.
"""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

import numpy as np
from arrayprobe_soda2.aspect_ratio import aspect_ratio
from arrayprobe_soda2.min_circle_fast import min_circle_fast

from arrayprobe_soda2_enhancements.double_pi_fix import (
    corrected_aspect_ratio,
    corrected_min_circle_fast,
)
from arrayprobe_soda2_enhancements.registry import REGISTRY, resolve

_ROOT = Path(__file__).resolve().parents[2]
_BANK = _ROOT / "scripts" / "validation" / "gdl" / "run_soda2_min_circle_fast_bank.py"
#: Present in the development repository, absent from a release tree (it does not ship).
_ALLOWLIST = _ROOT / "scripts" / "release_allowlist.txt"
#: The bank's cases are rebuilt only by its runner (two of them have no x/y in the golden JSON).
#: A release tree that does not ship the runner skips the tests that need its cases, by this
#: reason; the development repository must import it, so a lost runner fails rather than skips.
_NO_BANK = ("the oracle-bank runner scripts/validation/gdl/run_soda2_min_circle_fast_bank.py, "
            "whose CaseSpec.py() rebuilds the bank cases, does not ship in this release tree")
if _BANK.is_file() or _ALLOWLIST.is_file():
    sys.path.insert(0, str(_BANK.parent))
    from run_soda2_min_circle_fast_bank import CASES  # noqa: E402
else:
    CASES = None
_needs_bank = unittest.skipIf(CASES is None, _NO_BANK)

#: Measured directly (module docstring above): the 14 bank cases that are bit-identical to the
#: port under the correction.
_BIT_IDENTICAL_CASES = (
    "one_point", "two_points", "collinear_3", "collinear_4", "diagonal_10", "qflip",
    "circle_360", "acute_triangle", "column_10010", "column_100", "dup_of_q",
    "all_coincident_3", "real_roi_p4", "real_roi_p6",
)
#: Same corner count (3) and same diam, but a different P/Q/R identity/order -- a mid-loop
#: reroute, not the final :51 branch.
_REORDERED_SAME_COUNT_CASES = ("rect_4", "outline_20x8")
#: Corner count changes 3 -> 2; diam agrees to double rounding.
_CHANGED_CASES = ("block_5x3", "disc_outline_r12", "rect_tas_1p037", "L_shape")

DATA = Path(__file__).resolve().parents[2] / "tests" / "data"
S2_FIXTURE = DATA / "s2_spec_raw_fixture"
FRAME_FIXTURE = DATA / "soda2_spec_frame_fixture"

#: `test_soda2_process_2d.py::WritersAreWiredIn.CSV_HEADER_LINES`.
CSV_HEADER_LINES = 43


def _base_op(**overrides) -> dict:
    op = dict(
        fn=str(S2_FIXTURE), date="20160906", starttime=24240.0, stoptime=24250.0,
        format="SPEC", subformat=0, probetype="2DS", res=10.0,
        endbins=[0.0, 50.0, 100.0, 200.0, 500.0], arendbins=[0.0, 0.5, 1.0],
        rate=1.0, smethod="xy", pth="", particlefile=1, inttime_reject=0,
        stuckbits=0, water=0, fixedtas=0.0, timeoffset=0.0, armwidth=6.3,
        numdiodes=128, greythresh=0, probeid="H", eawmethod="centerin",
        wavelength=0.785e-6, dofconst=8.12, ncdfparticlefile=0, asciipsdfile=0,
    )
    op.update(overrides)
    return op


def _driver_aspect_pairs(op: dict) -> list[tuple[float, float, float, float]]:
    """Run the real driver once unpatched, once with
    ``arrayprobe_soda2.min_circle_fast.min_circle_fast`` monkey-patched to
    :func:`corrected_min_circle_fast` (legitimate -- ``aspect_ratio.py:518`` imports it lazily,
    inside the function, so the patched module attribute is what the next call reads), and
    return ``(port_aspr, port_orient, fixed_aspr, fixed_orient)`` per particle, read from the
    ``.pbp.csv`` both runs write."""
    from arrayprobe_soda2.process_2d import soda2_process_2d

    def _run() -> list[dict]:
        with tempfile.TemporaryDirectory() as tmp:
            run_op = dict(op)
            run_op["outdir"] = tmp + "/"
            run_op["particlefile"] = 1
            d = soda2_process_2d(run_op)
            if d is None:
                return []
            rows: list[dict] = []
            for p in Path(tmp).glob("*.pbp.csv"):
                lines = p.read_text(encoding="utf-8").splitlines()
                header = lines[CSV_HEADER_LINES - 1].split(",")
                for line in lines[CSV_HEADER_LINES:]:
                    if not line.strip():
                        continue
                    values = next(csv.reader([line]))
                    rows.append(dict(zip(header, values, strict=True)))
            return rows

    port_rows = _run()
    with mock.patch("arrayprobe_soda2.min_circle_fast.min_circle_fast",
                     corrected_min_circle_fast):
        fixed_rows = _run()

    return [
        (float(pr["aspectratio"]), float(pr["orientation"]),
         float(fr["aspectratio"]), float(fr["orientation"]))
        for pr, fr in zip(port_rows, fixed_rows, strict=True)
    ]


@_needs_bank
class Equivalence(unittest.TestCase):
    """On the 14 bank cases with no exact right angle at any candidate R (measured, see module
    docstring), :func:`corrected_min_circle_fast` matches
    :func:`~arrayprobe_soda2.min_circle_fast.min_circle_fast` bit for bit."""

    def test_matches_port_on_every_bank_case_with_no_right_angle(self):
        self.assertEqual(len(_BIT_IDENTICAL_CASES), 14)
        for name in _BIT_IDENTICAL_CASES:
            spec = CASES[name]
            with self.subTest(case=name):
                x, y = spec.py()
                port = min_circle_fast(x, y)
                fixed = corrected_min_circle_fast(x, y)
                self.assertEqual(fixed.diam, port.diam, name)
                np.testing.assert_array_equal(fixed.center, port.center, err_msg=name)
                np.testing.assert_array_equal(fixed.corners, port.corners, err_msg=name)
                self.assertEqual(fixed.area, port.area, name)


class ABConsequence(unittest.TestCase):
    @_needs_bank
    def test_same_count_cases_change_corner_identity_not_diam(self):
        """`rect_4`/`outline_20x8`: the loop's mid-run obtuse-angle tests (`:37`/`:41`) reroute
        which point ends up P/Q/R, even though the *final* branch (`:51`, 3-corner) is
        unchanged -- corners differ, but count and diam do not."""
        for name in _REORDERED_SAME_COUNT_CASES:
            with self.subTest(case=name):
                x, y = CASES[name].py()
                port = min_circle_fast(x, y)
                fixed = corrected_min_circle_fast(x, y)
                self.assertEqual(len(port.corners), 3, name)
                self.assertEqual(len(fixed.corners), 3, name)
                self.assertFalse(np.array_equal(port.corners, fixed.corners), name)
                self.assertEqual(fixed.diam, port.diam, name)

    @_needs_bank
    def test_rectangle_like_cases_return_two_corners(self):
        """The four bank cases that do change (measured, module docstring): corrected returns
        2 corners where the port returns 3, and `diam` agrees to double-rounding (1e-9
        relative) -- the register's "circle itself is unaffected"."""
        for name in _CHANGED_CASES:
            with self.subTest(case=name):
                x, y = CASES[name].py()
                port = min_circle_fast(x, y)
                fixed = corrected_min_circle_fast(x, y)
                self.assertEqual(len(port.corners), 3, name)
                self.assertEqual(len(fixed.corners), 2, name)
                rel = (abs(fixed.diam - port.diam) / abs(port.diam)
                       if port.diam else abs(fixed.diam - port.diam))
                self.assertLessEqual(rel, 1e-9, name)

    def test_changed_fraction_on_the_tracked_driver_fixtures(self):
        """The population-3 numbers, as literals written from
        ``enhancements_soda2/tools/double_pi_ab.py``'s own output (measured 2026-09-14): on
        both tracked fixtures, at both an equal (``yres == xres``, the base op) and an unequal
        (``stretchcorrect=1, fixedtas=120.0``) resolution ratio, not one of the 28 pooled
        real particles changed ``aspr``/``orientation`` -- ``f == 0`` on every run, which is
        the decision criterion's Default-ON branch (BACKLOG_STATUS.md's row has the full
        numbers and the small-sample caveat: 28 particles across two small fixtures is not
        proof no real ORACLES particle ever takes this branch)."""
        runs = {
            "s2_equal": _base_op(),
            "s2_unequal": _base_op(stretchcorrect=1, fixedtas=120.0),
            "frame_equal": _base_op(fn=str(FRAME_FIXTURE)),
            "frame_unequal": _base_op(fn=str(FRAME_FIXTURE), stretchcorrect=1, fixedtas=120.0),
        }
        expected_n = {"s2_equal": 1, "s2_unequal": 1, "frame_equal": 13, "frame_unequal": 13}
        total_n = 0
        total_changed = 0
        for label, op in runs.items():
            with self.subTest(run=label):
                pairs = _driver_aspect_pairs(op)
                self.assertEqual(len(pairs), expected_n[label], label)
                changed = sum(1 for pa, po, fa, fo in pairs if pa != fa or po != fo)
                self.assertEqual(changed, 0, label)
                total_n += len(pairs)
                total_changed += changed
        self.assertEqual(total_n, 28)
        self.assertEqual(total_changed, 0)


class SwitchStates(unittest.TestCase):
    def test_registered_default_off_a14(self):
        self.assertIn("double_pi_fix", REGISTRY)
        spec = REGISTRY["double_pi_fix"]
        self.assertFalse(spec.default_on)
        self.assertEqual(spec.finding, "S2-c")
        self.assertEqual(spec.reachability, "live")

    def test_off_reproduces_the_port(self):
        self.assertFalse(resolve({})["double_pi_fix"])
        self.assertTrue(resolve({"double_pi_fix": True})["double_pi_fix"])
        self.assertFalse(resolve({"double_pi_fix": False})["double_pi_fix"])


class Scope(unittest.TestCase):
    """Pins that this module did not widen `orientation_deg` (S2-e) -- guards against silent
    scope creep, per the module's own docstring caveat."""

    def test_orientation_deg_still_uses_single_pi(self):
        """AST-based, not a text search: the module's own docstring legitimately *discusses*
        S2-e/`orientation_deg` (to say it is out of scope), so a plain substring search would
        false-positive on that prose. What must be absent is any actual reference -- an
        import, a call, or a bare name -- to `orientation_deg` in the code."""
        import ast
        import inspect

        import arrayprobe_soda2_enhancements.double_pi_fix as mod
        tree = ast.parse(inspect.getsource(mod))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names |= {a.name for a in node.names}
        self.assertNotIn("orientation_deg", names)

    @_needs_bank
    def test_a_no_change_case_matches_the_port_through_aspect_ratio_too(self):
        """`two_points` never reaches the branch this module touches (its own `NC` is already
        2) -- corrected_aspect_ratio's orientation, computed by the port's own unmodified
        `axis_and_ratio`/`orientation_deg`, matches the port bit for bit."""
        x, y = CASES["two_points"].py()
        coords = np.stack([x, y], axis=1).astype(np.int64)
        port = aspect_ratio(coords, coordinates=True)
        fixed = corrected_aspect_ratio(coords, coordinates=True)
        self.assertEqual(fixed.orientation.dtype, np.float32)
        self.assertEqual(float(fixed.orientation), float(port.orientation))
        self.assertEqual(float(fixed.aspr), float(port.aspr))


if __name__ == "__main__":
    unittest.main()
