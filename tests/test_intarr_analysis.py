# SPDX-License-Identifier: BSD-3-Clause
"""S8b: the inter-arrival threshold driver and the file it writes.

Pins the parts of ``IntArrAnalysis_time.m`` that are ordinary array logic — construction order,
block sizing, threshold selection, the fallbacks — plus the output file's structure. The fit
itself is validated in ``test_intarr.py``; it cannot be bit-exact against MATLAB (a known gap).
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import numpy as np

try:
    import netCDF4
except ImportError:  # pragma: no cover
    netCDF4 = None

from arrayprobe.intarr_analysis import (
    DEFAULT_THRESHOLD,
    HIST_BINS,
    analyse,
    block_thresholds,
    inter_arrival,
    population_size,
    write_threshold_file,
)

try:  # scipy is an *extra* (pip install "arrayprobe[extra]"), not a core dependency:
    import scipy  # noqa: F401   the package must install with no toolchain.
    _HAS_SCIPY = True
except ImportError:                     # pragma: no cover - depends on the env
    _HAS_SCIPY = False


def setUpModule():
    """Skip, rather than error, when the optional fit dependency is absent.

    `intarr.py` imports scipy lazily inside the fitting function, so the module
    imports fine and the failure surfaced only when a test called it. On the
    author's laptop scipy has always been in the venv, so this path had never
    been taken; the first clean-environment CI run (2026-09-08) turned it into
    34 errors across the port and enhancement suites. An optional dependency
    that is absent must skip with a message, not raise.
    """
    if not _HAS_SCIPY:
        raise unittest.SkipTest(
            "scipy is not installed; it is an extra (pip install \"arrayprobe[extra]\") "
            "and the interarrival fits need it")


class InterArrivalConstruction(unittest.TestCase):
    """`:73-75`, `:93`, `:105-111` -- and the order they run in."""

    def test_first_particle_becomes_nan_not_zero(self):
        # the source sets it to 0, then NaNs everything <= 0, which takes the 0 with it
        out = inter_arrival([0.0, 1e-5, 2e-5])
        self.assertTrue(np.isnan(out[0]))

    def test_slow_arrivals_are_zeroed_not_dropped(self):
        out = inter_arrival([0.0, 0.05, 0.5, 0.5 + 1e-5])
        self.assertEqual(out.size, 4)
        self.assertEqual(out[1], 0.05)
        self.assertEqual(out[2], 0.0, "0.45 s > 0.1 s, so it is zeroed")
        self.assertAlmostEqual(out[3], 1e-5)

    def test_non_increasing_time_becomes_nan(self):
        out = inter_arrival([0.0, 1e-5, 1e-5, 2e-5])
        self.assertTrue(np.isnan(out[2]), "a zero gap is <= 0")

    def test_empty(self):
        self.assertEqual(inter_arrival([]).size, 0)


class PopulationSize(unittest.TestCase):
    """`:112-119` -- the coarse block-size rule."""

    def test_uses_the_base_size_when_no_second_is_crowded(self):
        t = np.repeat(np.arange(10), 2)          # 20 particles, busiest second holds 2
        self.assertEqual(population_size(t, 4), 5)

    def test_rounds_up_to_the_next_quarter_when_a_second_is_crowded(self):
        # base = ceil(40/4) = 10, quarter = 2.5, busiest = 30 -> 2.5*ceil(30/2.5) = 30.
        # The crowded second must not also appear in the filler, or busiest is 31 and the
        # answer is 32 -- the rounding is sensitive to one particle.
        t = np.concatenate([np.full(30, 100), np.arange(10)])
        self.assertEqual(population_size(t, 4), 30)

    def test_the_quarter_rounding_is_sensitive_to_a_single_particle(self):
        base_case = np.concatenate([np.full(30, 100), np.arange(10)])
        one_more = np.concatenate([np.full(31, 100), np.arange(9)])
        self.assertEqual(population_size(base_case, 4), 30)
        self.assertEqual(population_size(one_more, 4), 32)

    def test_rejects_empty_or_zero_blocks(self):
        with self.assertRaises(ValueError):
            population_size([], 4)
        with self.assertRaises(ValueError):
            population_size([1, 2], 0)


class ThresholdSelection(unittest.TestCase):
    def test_empty_histogram_falls_back(self):
        thr, ww, ak, tau = block_thresholds(np.zeros(len(HIST_BINS) - 1))
        self.assertEqual((thr, ww, ak), (DEFAULT_THRESHOLD,) * 3)
        self.assertIsNone(tau)

    def test_bimodal_population_yields_thresholds_between_the_modes(self):
        rng = np.random.RandomState(20260829)
        fast = rng.exponential(2e-6, 4000)       # shattered
        slow = rng.exponential(2e-2, 4000)       # real
        counts, _ = np.histogram(np.concatenate([fast, slow]), bins=HIST_BINS)
        thr, ww, ak, tau = block_thresholds(counts)
        self.assertIsNotNone(tau)
        lo, hi = float(np.min(tau[:2])), float(np.max(tau[:2]))
        for value in (ww, ak):
            self.assertGreater(value, lo)
            self.assertLess(value, hi)
        self.assertAlmostEqual(thr, lo * 2, places=12, msg="threshold is min(tau)*2 (:159)")


class DriverLoop(unittest.TestCase):
    def test_every_particle_gets_a_threshold_constant_within_its_block(self):
        rng = np.random.RandomState(7)
        arr = np.concatenate([rng.exponential(2e-6, 300), rng.exponential(1e-2, 300)])
        times = np.repeat(np.arange(60), 10)
        out = analyse(arr, times, n_blocks=3)
        size = out["population_size"]
        self.assertEqual(out["threshold_ak"].size, arr.size)
        for start in out["block_starts"]:
            block = out["threshold_ak"][start:start + size]
            self.assertEqual(len(set(block.tolist())), 1, "constant within a block")
        self.assertEqual(out["tau"].shape[1], 3)

    def test_all_three_thresholds_are_returned(self):
        rng = np.random.RandomState(3)
        arr = rng.exponential(1e-5, 200)
        out = analyse(arr, np.arange(200), n_blocks=2)
        for key in ("threshold", "threshold_ww", "threshold_ak"):
            self.assertEqual(out[key].size, 200)


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
class ThresholdFile(unittest.TestCase):
    """`:336-368` -- structure the twelfth `sizeDist` argument must have."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = str(Path(self.dir.name) / "2DS_intArrThreshold_test.cdf")
        write_threshold_file(
            self.path, np.array([64403.0, 64404.0, 64405.0]),
            np.array([1e-6, 2e-6, DEFAULT_THRESHOLD]),
            probename="2DS", flight_date="20160906", data_source="base160906064403.H_1.cdf",
            population_size=1234, creation_time="2000/01/01 00:00:00")

    def tearDown(self):
        self.dir.cleanup()

    def test_dimension_and_variables(self):
        with netCDF4.Dataset(self.path) as d:
            self.assertEqual(list(d.dimensions), ["particleTime"])
            self.assertEqual(len(d.dimensions["particleTime"]), 3)
            self.assertEqual(list(d.variables), ["particle_time", "threshold"])
            self.assertEqual(d.variables["particle_time"].units, "HHMMSS")
            self.assertEqual(d.variables["threshold"].units, "sec")

    def test_global_attributes_in_source_order(self):
        with netCDF4.Dataset(self.path) as d:
            self.assertEqual(d.ncattrs(), ["Software", "Institution", "Creation Time",
                                           "Description", "Flight Date", "Data Source",
                                           "Probe Type", "Population Size"])
            self.assertEqual(d.Software, "UIOOPS/IntArrAnalysis_revised")
            self.assertEqual(d.Institution, "Univ. Oklahoma, SoM")
            self.assertEqual(d.getncattr("Population Size"),
                             "1234 particles per distribution fit")

    def test_values_round_trip(self):
        with netCDF4.Dataset(self.path) as d:
            np.testing.assert_array_equal(d.variables["particle_time"][:],
                                          [64403.0, 64404.0, 64405.0])
            np.testing.assert_allclose(d.variables["threshold"][:],
                                       [1e-6, 2e-6, DEFAULT_THRESHOLD])

    def test_netcdf3_classic_like_every_other_output(self):
        with netCDF4.Dataset(self.path) as d:
            self.assertEqual(d.file_format, "NETCDF3_CLASSIC")

    def test_mismatched_lengths_raise(self):
        with self.assertRaises(ValueError):
            write_threshold_file(self.path, [1.0, 2.0], [1e-6], probename="2DS",
                                 flight_date="20160906", data_source="x", population_size=1)




class CliSubcommand(unittest.TestCase):
    """S9 wiring: the driver is reachable as `arrayprobe intarr-threshold`."""

    def test_registered_and_requires_its_fidelity_arguments(self):
        from arrayprobe.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["intarr-threshold", "proc.nc", "out.cdf",
                                  "--probe", "2DS", "--flight-date", "20160906"])
        self.assertEqual(args.probe, "2DS")
        self.assertEqual(args.blocks, 5, "the source's own fileNum default")
        with self.assertRaises(SystemExit):
            parser.parse_args(["intarr-threshold", "proc.nc", "out.cdf"])

    def test_end_to_end_against_a_synthetic_proc_file(self):
        if netCDF4 is None:
            self.skipTest("netCDF4 not installed")
        from arrayprobe.cli import main
        rng = np.random.RandomState(11)
        gaps = np.concatenate([rng.exponential(2e-6, 400), rng.exponential(1e-2, 400)])
        seconds = np.cumsum(gaps)
        times = np.floor(np.linspace(64403, 64500, seconds.size))
        with tempfile.TemporaryDirectory() as tmp:
            proc = str(Path(tmp) / "proc.synthetic.H.nc")
            with netCDF4.Dataset(proc, "w", format="NETCDF3_CLASSIC") as d:
                d.createDimension("time", seconds.size)
                d.createVariable("Time", "f8", ("time",))[:] = times
                d.createVariable("Time_in_seconds", "f8", ("time",))[:] = seconds
            out = str(Path(tmp) / "2DS_intArrThreshold_synthetic.cdf")
            rc = main(["intarr-threshold", proc, out, "--probe", "2DS",
                       "--flight-date", "20160906", "--blocks", "4"])
            self.assertEqual(rc, 0)
            with netCDF4.Dataset(out) as d:
                self.assertEqual(len(d.dimensions["particleTime"]), seconds.size)
                thresholds = np.asarray(d.variables["threshold"][:])
                self.assertTrue(np.all(thresholds > 0))
                self.assertEqual(d.getncattr("Probe Type"), "2DS")

    @staticmethod
    def _write_synthetic_proc(tmp, with_extras=False):
        rng = np.random.RandomState(11)
        gaps = np.concatenate([rng.exponential(2e-6, 400), rng.exponential(1e-2, 400)])
        seconds = np.cumsum(gaps)
        times = np.floor(np.linspace(64403, 64500, seconds.size))
        proc = str(Path(tmp) / "proc.synthetic.H.nc")
        with netCDF4.Dataset(proc, "w", format="NETCDF3_CLASSIC") as d:
            d.createDimension("time", seconds.size)
            d.createVariable("Time", "f8", ("time",))[:] = times
            d.createVariable("Time_in_seconds", "f8", ("time",))[:] = seconds
            if with_extras:
                d.createVariable("Date", "f8", ("time",))[:] = np.full(
                    seconds.size, 20160906.0)
                d.createVariable("image_diam_minR", "f8", ("time",))[:] = rng.uniform(
                    50, 500, seconds.size)
        return proc

    def test_default_off_writes_only_the_threshold_file(self):
        if netCDF4 is None:
            self.skipTest("netCDF4 not installed")
        from arrayprobe.cli import main
        with tempfile.TemporaryDirectory() as tmp:
            proc = self._write_synthetic_proc(tmp)
            out = str(Path(tmp) / "2DS_intArrThreshold_synthetic.cdf")
            rc = main(["intarr-threshold", proc, out, "--probe", "2DS",
                       "--flight-date", "20160906", "--blocks", "4"])
            self.assertEqual(rc, 0)
            self.assertEqual(
                sorted(os.listdir(tmp)),
                ["2DS_intArrThreshold_synthetic.cdf", "proc.synthetic.H.nc"],
            )

    def test_opt_in_writes_all_three_side_outputs(self):
        if netCDF4 is None:
            self.skipTest("netCDF4 not installed")
        try:
            import matplotlib  # noqa: F401
            import scipy  # noqa: F401
        except ImportError:
            self.skipTest("matplotlib/scipy not installed")
        from arrayprobe.cli import main
        with tempfile.TemporaryDirectory() as tmp_off:
            proc_off = self._write_synthetic_proc(tmp_off)
            out_off = str(Path(tmp_off) / "2DS_intArrThreshold_synthetic.cdf")
            rc = main(["intarr-threshold", proc_off, out_off, "--probe", "2DS",
                       "--flight-date", "20160906", "--blocks", "4"])
            self.assertEqual(rc, 0)
            with netCDF4.Dataset(out_off) as d:
                thresholds_off = np.array(d.variables["threshold"][:])

            with tempfile.TemporaryDirectory() as tmp_on:
                proc_on = self._write_synthetic_proc(tmp_on, with_extras=True)
                out_on = str(Path(tmp_on) / "2DS_intArrThreshold_synthetic.cdf")
                extra_json = str(Path(tmp_on) / "extra.json")
                plot_png = str(Path(tmp_on) / "contour.png")
                mat_ws = str(Path(tmp_on) / "ws.mat")
                rc = main(["intarr-threshold", proc_on, out_on, "--probe", "2DS",
                           "--flight-date", "20160906", "--blocks", "4",
                           "--extra-thresholds-json", extra_json,
                           "--plot", plot_png,
                           "--mat-workspace", mat_ws])
                self.assertEqual(rc, 0)
                for p in (extra_json, plot_png, mat_ws):
                    self.assertTrue(os.path.exists(p), p)
                    self.assertGreater(os.path.getsize(p), 0, p)
                with netCDF4.Dataset(out_on) as d:
                    thresholds_on = np.array(d.variables["threshold"][:])
                # 'Creation Time' is non-deterministic so compare the
                # threshold variable's array rather than the files' raw bytes.
                np.testing.assert_array_equal(thresholds_off, thresholds_on)


if __name__ == "__main__":
    unittest.main()
