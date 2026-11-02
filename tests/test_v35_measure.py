# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe_uiops.measure`` against a real Octave run of v3.5's own measurement
block.

The fixture is written by ``octave_oracle/run_v35_measure_bank.py``, which slices
``imgProc_sm.m:1204-1291`` out of the vendored v3.5 file by textual anchor and runs
*those lines* under Octave with the vendored callees and the v3.5 ``CGAL_minR``
MEX. ``test_the_oracle_ran_the_vendored_source`` re-slices the file and requires it
to still match, so a later re-vendor fails here rather than silently invalidating
every record below.
"""

from __future__ import annotations

import json
import math
import unittest
import warnings
from pathlib import Path

import numpy as np
from tests import _upstream  # noqa: E402
from tests._repo import repo_only

from arrayprobe_uiops.measure import (
    STOCK_V35_REJECT_CONFIG,
    RecordGeometry,
    measure_record,
    sphericity_mrdivide,
)

FIXTURE = Path(__file__).resolve().parent / "data" / "v35_measure_oracle.json"
V35_IMGPROC = (
    _upstream.source("uiops35") / "imgProc_sm.m"
)

_FLOAT_FIELDS = [
    "minR", "ctx", "cty", "FS", "image_length", "image_width", "image_area",
    "longest_y_within_a_slice", "max_top_edge_touching", "max_bottom_edge_touching",
    "is_hollow", "percent_shadow", "part_z", "sf", "area_hole_ratio",
    "max_hole_diameter", "edge_at_max_hole", "center_in", "AreaR", "Perimeter",
    "sphericity", "axis_ratio",
]
_NEW_HABIT_FIELDS = {"w_l_p": "w_l_p", "c_r": "c_r", "e_d_r": "e_d_r", "m_g": "m_g",
                     "O": "O", "aspect_ratio": "a_r", "holroyd_perimeter": "p"}


def setUpModule():
    # Raised here rather than at import: an import-time SkipTest crashes
    # ``python -m unittest tests.<module>``, where ``discover`` reports it as a skip.
    _upstream.require("uiops35")


def _load() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _images(case: dict) -> list[np.ndarray]:
    out = []
    for im in case["images"]:
        rows, cols = im["rows"], im["cols"]
        out.append(np.array(list(im["flat"]), dtype="U1").reshape(rows, cols))
    return out


def _geometry(case: dict) -> RecordGeometry:
    return RecordGeometry(
        diodesize=case["diodesize"], diodenum=case["diodenum"], tas_ratio=case["tasRatio"],
        i_new_habit=case["iNewHabit"], probename=case["probename"],
        i_calc_all_diode_stats=case["iCalcAllDiodeStats"],
    )


def _f(v):
    return math.nan if v is None else float(v)


class TestAgainstTheOctaveOracle(unittest.TestCase):
    """Every record the bank ran, every written field, reproduced."""

    @classmethod
    def setUpClass(cls):
        cls.bank = _load()
        cls.cases = {c["name"]: c for c in cls.bank["cases"]}
        cls.results = {r["name"]: r for r in cls.bank["results"]}

    @repo_only
    def test_the_oracle_ran_the_vendored_source(self):
        lines = V35_IMGPROC.read_text(encoding="utf-8", errors="replace").splitlines()
        start = next((i for i, ln in enumerate(lines)
                      if ln.strip() == self.bank["start_anchor"]), None)
        self.assertIsNotNone(start, "the habit banner is gone from the vendored imgProc_sm.m")
        end = next((i for i in range(start, len(lines))
                    if lines[i].strip() == self.bank["end_anchor"]), None)
        self.assertIsNotNone(end, "the iRectEllipse line is gone from the vendored imgProc_sm.m")
        recovered = "\n".join(lines[start:end]).rstrip() + "\n"
        self.assertEqual(recovered, self.bank["source"],
                         "the vendored block no longer matches what the oracle ran; "
                         "re-run octave_oracle/run_v35_measure_bank.py")
        # The doc cites :1213-1292; the self-contained unit starts at :1204 (measured).
        self.assertEqual(start + 1, 1204)
        self.assertEqual(end + 1, 1293)

    def test_every_record_is_reproduced(self):
        checked = 0
        for name, res in self.results.items():
            case = self.cases[name]
            self.assertEqual(res["status"], "OK", name)
            with self.subTest(record=name):
                got = measure_record(_images(case), _geometry(case), STOCK_V35_REJECT_CONFIG)
                im = res["images"]
                n = len(im["minR"])
                self.assertEqual(len(got.particles), n)
                self.assertEqual("".join(p.holroyd_habit for p in got.particles), im["holroyd_habit"][0])  # noqa: E501
                self.assertEqual("".join(p.auto_reject for p in got.particles), im["auto_reject"][0])  # noqa: E501
                self.assertEqual("".join(str(p.image_touching_edge) for p in got.particles),
                                 im["image_touching_edge"][0])
                for f in _FLOAT_FIELDS:
                    want = [_f(v) for v in im[f]]
                    have = [float(getattr(p, f)) for p in got.particles]
                    np.testing.assert_allclose(have, want, rtol=1e-9, atol=1e-12, equal_nan=True,
                                               err_msg=f"{name}: {f}")
                if case["iNewHabit"]:
                    for mfield, pfield in _NEW_HABIT_FIELDS.items():
                        want = [_f(v) for v in im[mfield]]
                        have = [float(getattr(p.new_habit, pfield)) for p in got.particles]
                        np.testing.assert_allclose(have, want, rtol=1e-9, atol=1e-12,
                                                   equal_nan=True, err_msg=f"{name}: {mfield}")
                else:
                    self.assertTrue(all(p.new_habit is None for p in got.particles))
                np.testing.assert_array_equal(got.diode_stats_total, im["diode_stats_total"], name)
                np.testing.assert_array_equal(got.csum_last, im["csum_last"], name)
                if case["iCalcAllDiodeStats"]:
                    want_ds = np.array(im["diode_stats"], dtype=float)
                    have_ds = np.array([p.diode_stats for p in got.particles], dtype=float)
                    np.testing.assert_array_equal(have_ds, want_ds, name)
                # :1277's console warning: the fixture keeps Octave's console text
                self.assertEqual(len(got.warnings), res["console"].count("WARNING: Habit"), name)
            checked += 1
        self.assertEqual(checked, 65, "the bank is 65 records; a shorter fixture is a truncated run")  # noqa: E501

    def test_the_grid_reaches_every_branch_it_was_built_for(self):
        """Coverage is measured from the fixture, not assumed from the case names."""
        habits, rejects, hollow_in, cin0, multi = set(), set(), 0, 0, 0
        for res in self.results.values():
            im = res["images"]
            habits |= set(im["holroyd_habit"][0])
            rejects |= set(im["auto_reject"][0])
            cin0 += im["center_in"].count(0)
            multi += len(im["minR"]) > 1
        self.assertIn("C", habits, "centre-out 'C' (:1283-1285) never emitted")
        self.assertIn("H", rejects, "Korolev path (:1274-1280) never reached")
        self.assertGreater(cin0, 0)
        self.assertGreaterEqual(multi, 8, "sphericity needs multi-particle records")
        # both classifier families, both probes, three tasRatio values
        self.assertTrue(any(c["iNewHabit"] == 1 for c in self.cases.values()))
        self.assertEqual({c["probename"] for c in self.cases.values()}, {"2DS", "HVPS"})
        self.assertEqual({c["tasRatio"] for c in self.cases.values()}, {0.7, 1.0, 1.4})
        del hollow_in


class TestPreservedBugs(unittest.TestCase):
    """v3.5 defects reproduced on purpose, each named after the line it protects."""

    @classmethod
    def setUpClass(cls):
        cls.bank = _load()
        cls.results = {r["name"]: r for r in cls.bank["results"]}

    def test_imgProc_1272_sphericity_is_mrdivide_over_the_record(self):
        """``:1272`` divides the whole ``image_area`` row vector by the whole
        ``Perimeter`` row vector -- MATLAB mrdivide, a least-squares slope over
        every particle so far. Exact for the first particle of a record, wrong
        for every one after, by an amount depending on what preceded it."""
        im = self.results["sphericity_growing_squares"]["images"]
        area, perim, written = im["image_area"], im["Perimeter"], im["sphericity"]
        self.assertEqual(area, [4, 9, 16, 25])
        self.assertEqual(perim, [4, 8, 12, 16])
        per_particle = [math.sqrt(a) / p for a, p in zip(area, perim, strict=True)]
        self.assertAlmostEqual(written[0], per_particle[0], places=12)
        for k in range(1, 4):
            self.assertNotAlmostEqual(written[k], per_particle[k], places=6,
                                      msg=f"particle {k + 1} should diverge under mrdivide")
            self.assertAlmostEqual(
                sphericity_mrdivide(area[:k + 1], perim[:k + 1], 1.0), written[k], places=12)
        # the closed form of the 1-D least-squares slope, for the reader
        a = np.sqrt(np.array(area[:2])); b = np.array(perim[:2], dtype=float)  # noqa: E702
        self.assertAlmostEqual(float(a @ b / (b @ b)), 0.4, places=12)

    def test_imgProc_1218_hollow_probe_indexes_a_0_based_centre_1_based(self):
        """``CGAL_minR.cpp:80-84`` returns a 0-based centre; ``:1218-1219`` index it
        1-based, so a single shadowed pixel reads its own up-left neighbour, finds
        background, and is ruled hollow (habit ``'s'``, ``ihollow = 1``)."""
        geom = RecordGeometry(diodesize=0.010, diodenum=128, tas_ratio=1.0,
                              i_new_habit=0, probename="2DS")
        img = np.full((3, 128), "1", dtype="U1")
        img[1, 63] = "0"
        p = measure_record([img], geom, STOCK_V35_REJECT_CONFIG).particles[0]
        self.assertEqual((p.ctx, p.cty), (1.0, 63.0))   # 0-based from the MEX
        self.assertEqual(p.holroyd_habit, "s")
        # and the same pixel one row down is NOT hollow when the window lands on it
        oracle = self.results["single_pixel_mid"]["images"]
        self.assertEqual(oracle["holroyd_habit"][0], "s")

    def test_imgProc_1236_override_is_hollow_is_overwritten_by_the_reject_call(self):
        """``:1236`` sets ``is_hollow(kk) = 1``; ``:1256-1260`` reassigns it from
        ``calculate_reject_unified``. Measured on ``line_along_slices``: the override
        fired (habit ``'s'``) but the written ``is_hollow`` is 0."""
        im = self.results["line_along_slices"]["images"]
        self.assertEqual(im["holroyd_habit"][0], "s")
        self.assertEqual(im["is_hollow"], [0])
        # at tasRatio 0.7 the scaled minR exceeds 0.3 mm, the override does not
        # fire, and the classifier's own answer ('l') is written instead
        self.assertEqual(self.results["line_along_slices_r0.7"]["images"]["holroyd_habit"][0], "l")

    def test_measure_184_sphericity_0_over_0_is_nan_without_a_warning(self):
        """``:184`` -- a faithful ``0/0`` must still be ``nan``; only the
        ``RuntimeWarning: invalid value encountered in scalar divide`` a real
        run emitted 3,927 times for it is silenced (``np.errstate`` scoped to
        that one division). If this test ever has to change to keep passing,
        the fix stopped being cosmetic."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = sphericity_mrdivide([0], [0], 1.0)
        self.assertTrue(math.isnan(result))
        self.assertEqual(caught, [],
                         f"unexpected warnings: {[str(w.message) for w in caught]}")


class SphericityIsSolvedByQr(unittest.TestCase):
    """``a / b`` with non-square ``b`` is solved by Householder QR, as Octave does. An SVD solve
    (``np.linalg.lstsq``) gave ...832 on Linux for this particle of the a15 2DC golden, where
    Octave (Windows and Linux alike) and QR give ...835 (cloud pass 7, item 4)."""

    def test_golden_particle_matches_octave(self) -> None:
        from arrayprobe_uiops.measure import sphericity_mrdivide
        a = np.array([5.5677643628300215, 7.681145747868608])
        self.assertEqual(sphericity_mrdivide(a ** 2, np.array([31.0, 59.0]), 1.0),
                         0.14087985015127835)

    def test_degenerate_inputs_match_octave(self) -> None:
        """Octave 11.3's ``a / b`` on these (``[1 2]/[0 0]`` and so on): 0, 0, 0, 2/3, NaN."""
        from arrayprobe_uiops.measure import sphericity_mrdivide
        cases = (([1.0, 4.0], [0.0, 0.0], 0.0), ([0.0, 0.0], [0.0, 0.0], 0.0),
                 ([1.0, 4.0], [np.inf, 1.0], 0.0), ([1.0, 4.0], [0.0, 3.0], 2.0 / 3.0))
        for area, per, want in cases:
            with self.subTest(area=area, perimeter=per):
                self.assertAlmostEqual(sphericity_mrdivide(np.array(area), np.array(per), 1.0),
                                       want, places=15)
        self.assertTrue(math.isnan(sphericity_mrdivide(np.array([1.0, 4.0]),
                                                       np.array([np.nan, 1.0]), 1.0)))

if __name__ == "__main__":
    unittest.main()
