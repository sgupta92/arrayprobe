# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe tune distributions``: per-particle distributions from a small synthetic proc file.

Pins the per-second counts, the inter-arrival fraction at the probe case's shattering threshold
(and that the mark says the threshold has no effect where the case's gate is off), that a
non-finite diameter gets its own bin rather than the top one, the size bins, the area-ratio and
axis-ratio cut fractions, the reject codes in words, and the CLI. No test here reads a real
flight file; every expected number is counted from the synthetic particles written below.
"""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from arrayprobe import cli
from arrayprobe.matlab_compat import REJECT_CODE_WORDS, REJECT_CODES, UNREACHABLE_REJECT_CODES
from arrayprobe.tune import distributions as dist
from arrayprobe.tune import settings
from arrayprobe_uiops.probe_cases import register_v35_2ds_ladder_fix

#: The shipped generic probe case; its shattering gate is off, which the tests below rely on.
CASE = register_v35_2ds_ladder_fix().name

WINDOWS = ((36000, 36002),)  # 10:00:00-10:00:02, three seconds
WINDOWS_TEXT = "36000-36002"

# Ten particles. Seconds 100000 (4), 100001 (3), 100002 (0), and three outside the window.
TIME = [100000] * 4 + [100001] * 3 + [100003, 95959, 100003]
DIAM = [0.03, 0.06, 0.15, np.nan, 0.06, 1.5, np.inf, 0.06, 0.06, 0.06]
# Area ratio = area / (pi/4 d^2): chosen as 0.9, 0.1, 0.5, -, 0.3, 2.0 (clipped to 1), -.
_AR = [0.9, 0.1, 0.5, 0.0, 0.3, 2.0, 0.0, 0.9, 0.9, 0.9]
AREA = [r * np.pi / 4 * d ** 2 if np.isfinite(d) else 0.0 for r, d in zip(_AR, DIAM, strict=True)]
AXIS = [1.0, 5.5, 7.0, 1.0, 2.0, 1.2, 1.0, 1.0, 1.0, 1.0]
IA = [1e-6, 3e-6, 5e-6, 1e-3, 0.0, 2e-2, 4e-6, 1e-6, 1e-6, 1e-6]
REJ = [ord(c) for c in "0a0zp0z000"]
HABIT = [ord(c) for c in "ssMttMtsss"]
HOLLOW = [0, 0, 1, 0, 0, 0, 0, 0, 0, 0]


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(argv)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def _cols():
    return {"Time": np.array(TIME), "image_diam_minR": np.array(DIAM),
            "image_area": np.array(AREA), "image_auto_reject": np.array(REJ, np.int16),
            "image_axis_ratio": np.array(AXIS), "inter_arrival": np.array(IA),
            "image_hollow": np.array(HOLLOW), "holroyd_habit": np.array(HABIT, np.int16)}


def _write_proc(path: Path) -> Path:
    import netCDF4

    types = {"Time": "i4", "image_auto_reject": "i2", "holroyd_habit": "i2", "image_hollow": "i2"}
    with netCDF4.Dataset(path, "w", format="NETCDF3_CLASSIC") as nc:
        nc.createDimension("Particle", len(TIME))
        for name, values in _cols().items():
            nc.createVariable(name, types.get(name, "f8"), ("Particle",))[:] = values
    return path


def _report(probe_case=CASE, **kw):
    marks = dist.threshold_marks(probe_case, kw.pop("area_ratio_z", None))
    return dist.report(_cols(), windows=WINDOWS, marks=marks, **kw)


class Counts(unittest.TestCase):

    def test_particles_in_the_window_and_per_second(self):
        rep = _report()
        self.assertEqual(rep["n_particles_file"], 10)
        self.assertEqual(rep["n_particles_in_windows"], 7)
        self.assertEqual(rep["window_seconds"], 3)
        np.testing.assert_array_equal(
            dist.per_second_counts([36000] * 4 + [36001] * 3, WINDOWS), [4, 3, 0])

    def test_per_second_at_or_above_the_floor_drops_the_small_one(self):
        rep = _report()
        # all: [4, 3, 0]; >= 0.055 mm: [2, 3, 0] (0.03 and the NaN fail, inf passes).
        self.assertEqual(rep["per_second"]["all"]["50"], 3.0)
        self.assertEqual(rep["per_second"]["at_or_above_0.055mm"]["50"], 2.0)
        self.assertEqual(rep["per_second"]["fraction_of_window_seconds_over_100_all"], 0.0)

    def test_a_second_in_two_windows_counts_once(self):
        counts = dist.per_second_counts([36001], ((36000, 36001), (36001, 36002)))
        np.testing.assert_array_equal(counts, [0, 1, 0])


class SizeBins(unittest.TestCase):

    def test_non_finite_diameters_get_their_own_bin_not_the_top_one(self):
        idx, labels = dist.size_bins([np.nan, np.inf, 1.5, 0.03, -0.01])
        self.assertEqual(labels[idx[0]], dist.NONFINITE_LABEL)
        self.assertEqual(labels[idx[1]], dist.NONFINITE_LABEL)
        self.assertEqual(labels[idx[2]], "1000-infum")
        self.assertEqual(labels[idx[3]], "0-55um")
        self.assertEqual(labels[idx[4]], dist.BELOW_FLOOR_LABEL)

    def test_report_bins(self):
        by = _report()["by_size"]
        self.assertEqual(by["0-55um"]["n"], 1)
        self.assertEqual(by["55-100um"]["n"], 2)
        self.assertEqual(by["100-200um"]["n"], 1)
        self.assertEqual(by["1000-infum"]["n"], 1)
        self.assertEqual(by[dist.NONFINITE_LABEL]["n"], 2)
        self.assertEqual(by[dist.BELOW_FLOOR_LABEL], {"n": 0})


class InterArrival(unittest.TestCase):

    def test_fraction_at_or_below_the_probe_case_threshold(self):
        rep = _report()
        thr = settings.resolve_probe_defaults(CASE).defaultIntArrThresh
        ia = rep["inter_arrival"]
        self.assertEqual(ia["threshold_s"], thr)
        # In the window: 1e-6, 3e-6, 5e-6, 1e-3, 0 (not counted), 2e-2, 4e-6 -> six positive.
        self.assertEqual(ia["nonpositive_or_nonfinite"], 1)
        expect = np.mean(np.array([1e-6, 3e-6, 5e-6, 1e-3, 2e-2, 4e-6]) <= thr)
        self.assertAlmostEqual(ia["fraction_at_or_below_threshold"], expect)
        self.assertEqual(sum(ia["counts"]), 6)

    def test_gate_off_case_says_the_threshold_has_no_effect(self):
        sh = _report()["thresholds"]["shattering"]
        self.assertEqual(sh["applyIntArrThresh"], 0)
        self.assertIn("no effect", sh["effect"])

    def test_no_probe_case_marks_no_shattering_threshold(self):
        rep = _report(probe_case=None)
        self.assertIsNone(rep["thresholds"]["shattering"]["value"])
        self.assertNotIn("fraction_at_or_below_threshold", rep["inter_arrival"])


class Cuts(unittest.TestCase):

    def test_area_ratio_is_clipped_at_one_and_cut_fraction_counts_below(self):
        np.testing.assert_allclose(dist.area_ratio([2.0 * np.pi / 4], [1.0]), [1.0])
        by = _report(area_ratio_z=0.2)["by_size"]
        self.assertEqual(by["55-100um"]["area_ratio_fraction_below_cut"], 0.5)  # 0.1 and 0.3
        self.assertEqual(by["1000-infum"]["area_ratio_percentiles"]["50"], 1.0)

    def test_marks_carry_their_sources(self):
        th = _report()["thresholds"]
        from arrayprobe_uiops import measure, sizedist

        self.assertEqual(th["area_ratio_z"]["value"], sizedist.AREA_RATIO_Z)
        self.assertEqual(th["max_comp_img_ar"]["value"],
                         measure.STOCK_V35_REJECT_CONFIG.max_comp_img_ar)
        self.assertEqual(th["max_edge_img_ar"]["value"],
                         measure.STOCK_V35_REJECT_CONFIG.max_edge_img_ar)
        for mark in th.values():
            self.assertIn("effect" if mark.get("value") is None else "source", mark)
        self.assertEqual(_report(area_ratio_z=0.5)["thresholds"]["area_ratio_z"]["value"], 0.5)

    def test_axis_ratio_fraction_above_each_ceiling(self):
        rep = _report()
        by = rep["by_size"]
        comp = rep["thresholds"]["max_comp_img_ar"]["value"]
        edge = rep["thresholds"]["max_edge_img_ar"]["value"]
        ax = np.array([5.5, 2.0])  # the 55-100 um bin
        self.assertEqual(by["55-100um"]["axis_ratio_fraction_above_max_comp_img_ar"],
                         float(np.mean(ax > comp)))
        self.assertEqual(by["55-100um"]["axis_ratio_fraction_above_max_edge_img_ar"],
                         float(np.mean(ax > edge)))


class Codes(unittest.TestCase):

    def test_every_reject_code_has_words(self):
        for key in list(REJECT_CODES) + list(UNREACHABLE_REJECT_CODES):
            with self.subTest(code=key):
                self.assertTrue(REJECT_CODE_WORDS.get(key))
        self.assertEqual(set(REJECT_CODE_WORDS),
                         set(REJECT_CODES) | set(UNREACHABLE_REJECT_CODES))

    def test_reject_codes_named_in_words_per_bin(self):
        by = _report()["by_size"]
        self.assertEqual(by["55-100um"]["reject_codes"],
                         {"a": {"n": 1, "meaning": REJECT_CODE_WORDS["a"]},
                          "p": {"n": 1, "meaning": REJECT_CODE_WORDS["p"]}})
        self.assertEqual(by["100-200um"]["hollow_fraction"], 1.0)
        self.assertEqual(by[dist.NONFINITE_LABEL]["habit_codes"], {"t": 2})
        self.assertEqual(dist.reject_code_counts([7])["#7"]["meaning"], "not a known reject code")


class Cli(unittest.TestCase):

    def test_writes_the_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = _write_proc(Path(tmp) / "proc.base000000000000.H.nc")
            out = Path(tmp) / "sub" / "report.json"
            code, stdout, err = _run(["tune", "distributions", "--proc", str(proc), "--windows",
                                      WINDOWS_TEXT, "--out", str(out),
                                      "--probe-case", CASE])
            self.assertEqual(code, 0, err)
            rep = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(rep["n_particles_in_windows"], 7)
        self.assertEqual(rep["by_size"][dist.NONFINITE_LABEL]["n"], 2)
        self.assertIn("no effect", stdout)

    def test_refusals(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = _write_proc(Path(tmp) / "proc.nc")
            out = str(Path(tmp) / "r.json")
            for argv in (["--windows", "36002-36000", "--proc", str(proc)],
                         ["--windows", WINDOWS_TEXT, "--proc", str(Path(tmp) / "none.nc")]):
                with self.subTest(argv=argv):
                    code, _, _ = _run(["tune", "distributions", "--out", out, *argv])
                    self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
