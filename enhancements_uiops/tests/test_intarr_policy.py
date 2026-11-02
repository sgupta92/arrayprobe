# SPDX-License-Identifier: BSD-3-Clause
"""``intarr_policy`` -- the inter-arrival threshold-rule and neighbour-count switch.

Four proofs, each drawing its two sides from different places:

* **Equivalence (OFF is UIOOPS).** The flagging side is compared against the v3.5 engine's own
  ``flag_shattered_1hz`` (``arrayprobe_uiops.sizedist_tables``, v3.5 ``sizeDist.m:1384-1396``);
  the file side against the port's own ``write_threshold_file`` of ``threshold_ak``, byte for
  byte.
* **Both states.** Every rule and neighbour count, hand-built so the expected mask is read off
  the input, not recomputed.
* **Mutation.** The comparison helper the equivalence test uses is shown to fail when the
  policy is moved one step off UIOOPS, so the equivalence test is not vacuous.
* **A/B on the dense demo flight** (``demo_flight_dense_raw.2DS``, decoded in-test on the v3.5
  engine through ``scripts/run_flight.py``'s own stages): the flag counts are pinned as measured.
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np
from arrayprobe import intarr_analysis
from arrayprobe_uiops.sizedist_tables import flag_shattered_1hz

from arrayprobe_enhancements import applicability, registry
from arrayprobe_enhancements.intarr_policy import (
    NEIGHBOUR_COUNTS,
    RULES,
    UIOPS_POLICY,
    InterArrivalPolicy,
    compare_policies,
    flag_shattered,
    flag_shattered_by_second,
    select_threshold,
    write_threshold_file,
)

# Fixtures copied verbatim from test_outoffocus (whose v3.1.4 cases do not ship), so this
# module depends on no sibling test module.
_ROOT = Path(__file__).resolve().parents[2]
_PYTHON_PORT = _ROOT  # the pre-move port directory is the repository root
_DENSE_RAW = _PYTHON_PORT / "tests" / "data" / "demo_flight_dense_raw.2DS"


def _load_run_flight():
    """The flight driver (``arrayprobe.driver.run_flight``; ``scripts/run_flight.py`` is its shim) by path -- registered under a private
    name, never ``sys.modules["run_flight"]``, the same isolation
    ``test_demo_flight_thresholds.py`` and ``make_demo_reference.py`` use."""
    spec = importlib.util.spec_from_file_location(
        "_test_outoffocus_run_flight",
        _PYTHON_PORT / "src" / "arrayprobe" / "driver" / "run_flight.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_test_outoffocus_run_flight"] = module
    spec.loader.exec_module(module)
    return module


def _write_aircraft_cdf(path, *, start_hms=(6, 6, 20), n=50, tas_mps=130.0):
    """A NETCDF3_CLASSIC ``Time``/``TAS`` series bracketing the dense demo flight's
    six-minute-six window (``make_demo_flight.build_dense_demo_flight``'s default
    ``start_hour=6, start_minute=6, start_second=40``, ``n_seconds=20`` -> raw HHMMSS
    060640..060659), built with real HH:MM:SS rollover arithmetic (not raw integer
    addition -- ``060658 + 5`` is not ``060663``) so every value stays a valid HHMMSS,
    same shape as ``make_demo_reference.write_aircraft_v35``."""
    h0, m0, s0 = start_hms
    total0 = h0 * 3600 + m0 * 60 + s0
    hhmmss = []
    for i in range(n):
        total = total0 + i
        hh, rem = divmod(total, 3600)
        mm, ss = divmod(rem, 60)
        hhmmss.append(hh * 10000 + mm * 100 + ss)
    hhmmss = np.asarray(hhmmss, dtype=np.float64)
    tas = np.full(n, tas_mps, dtype=np.float64)
    with netCDF4.Dataset(str(path), "w", format="NETCDF3_CLASSIC") as ds:
        ds.createDimension("time", n)
        ds.createVariable("Time", "f8", ("time",))[:] = hhmmss
        ds.createVariable("TAS", "f8", ("time",))[:] = tas
    return path


def _matches_v35(int_arr, thresh, policy) -> bool:
    """Whether ``flag_shattered`` under ``policy`` equals v3.5's own flagging of one second."""
    ours = flag_shattered(int_arr, thresh, policy=policy)
    theirs = flag_shattered_1hz(int_arr, thresh) == "S"
    return bool(np.array_equal(ours, theirs))


def _random_seconds(seed, n_seconds=400):
    rng = np.random.default_rng(seed)
    for _ in range(n_seconds):
        n = int(rng.integers(1, 30))
        # a mix of shattering-scale and natural-scale gaps, and the record-start zero
        ia = 10.0 ** rng.uniform(-7.5, -2.0, n)
        ia[rng.random(n) < 0.1] = 0.0
        yield ia, float(10.0 ** rng.uniform(-6.5, -4.5))


class TheSwitchIsOffByDefault(unittest.TestCase):
    def test_the_default_policy_is_uioops_and_off(self):
        p = InterArrivalPolicy()
        self.assertFalse(p.enabled)
        self.assertEqual((p.rule, p.neighbours), ("min_measured", 1))
        self.assertEqual(p, UIOPS_POLICY)

    def test_setting_a_rule_without_enabling_is_refused_not_ignored(self):
        with self.assertRaises(ValueError):
            InterArrivalPolicy(rule="min_fitted")
        with self.assertRaises(ValueError):
            InterArrivalPolicy(neighbours=2)

    def test_unknown_rule_and_neighbour_count_are_refused(self):
        with self.assertRaises(ValueError):
            InterArrivalPolicy(enabled=True, rule="median")
        with self.assertRaises(ValueError):
            InterArrivalPolicy(enabled=True, neighbours=3)

    def test_turned_on_explicitly(self):
        p = InterArrivalPolicy(enabled=True, rule="twice_tau2", neighbours=2)
        self.assertEqual((p.rule, p.neighbours), ("twice_tau2", 2))


class OffIsByteIdenticalToUiops(unittest.TestCase):
    """Equivalence: OFF reproduces the engine, from code this module does not contain."""

    def test_off_flagging_equals_v35_flag_shattered_1hz_on_random_seconds(self):
        checked = 0
        for seed in (1, 2, 3):
            for ia, thr in _random_seconds(seed):
                self.assertTrue(_matches_v35(ia, thr, None), (ia, thr))
                self.assertTrue(_matches_v35(ia, thr, UIOPS_POLICY), (ia, thr))
                checked += 1
        self.assertEqual(checked, 1200)

    def test_off_threshold_file_is_byte_identical_to_the_ports_own_write(self):
        rng = np.random.default_rng(7)
        n = 50
        thresholds = {k: 10.0 ** rng.uniform(-8, -4, n) for k in RULES.values()}
        t = np.repeat(np.arange(60640, 60645, dtype=float), 10)
        kw = dict(probename="2DS", flight_date="20160902", data_source="test",
                  population_size=10, creation_time="2026/09/14 00:00:00")
        with tempfile.TemporaryDirectory() as d:
            ours = Path(d) / "ours.cdf"
            port = Path(d) / "port.cdf"
            write_threshold_file(ours, t, thresholds, **kw)
            intarr_analysis.write_threshold_file(port, t, thresholds["threshold_ak"], **kw)
            self.assertEqual(ours.read_bytes(), port.read_bytes())

    def test_off_selects_the_array_the_source_writes(self):
        th = {"threshold": np.array([1.0]), "threshold_ww": np.array([2.0]),
              "threshold_ak": np.array([3.0])}
        np.testing.assert_array_equal(select_threshold(th), [3.0])


class BothStates(unittest.TestCase):
    """ON: each rule and neighbour count, expected values read off the input."""

    def test_each_rule_selects_its_source_variable(self):
        th = {"threshold": np.array([1.0]), "threshold_ww": np.array([2.0]),
              "threshold_ak": np.array([3.0])}
        want = {"twice_tau2": 1.0, "min_fitted": 2.0, "min_measured": 3.0}
        for rule, v in want.items():
            p = InterArrivalPolicy(enabled=True, rule=rule)
            self.assertEqual(float(select_threshold(th, p)[0]), v)

    def test_neighbour_counts_on_one_interior_hit(self):
        ia = [0.1, 0.1, 1e-7, 0.1, 0.1]
        want = {0: [0, 0, 1, 0, 0], 1: [0, 1, 1, 0, 0], 2: [0, 1, 1, 1, 0]}
        for n, mask in want.items():
            p = UIOPS_POLICY if n == 1 else InterArrivalPolicy(enabled=True, neighbours=n)
            np.testing.assert_array_equal(flag_shattered(ia, 1e-6, policy=p),
                                          np.array(mask, bool), err_msg=f"neighbours={n}")

    def test_a_first_particle_hit_has_no_predecessor(self):
        ia = [0.0, 0.1, 0.1]
        want = {0: [1, 0, 0], 1: [1, 0, 0], 2: [1, 1, 0]}
        for n, mask in want.items():
            p = UIOPS_POLICY if n == 1 else InterArrivalPolicy(enabled=True, neighbours=n)
            np.testing.assert_array_equal(flag_shattered(ia, 1e-6, policy=p),
                                          np.array(mask, bool))

    def test_a_neighbour_never_crosses_a_second(self):
        ia = [0.1, 1e-7, 0.1, 0.1]
        sec = [1, 1, 2, 2]
        p = InterArrivalPolicy(enabled=True, neighbours=2)
        np.testing.assert_array_equal(flag_shattered_by_second(ia, 1e-6, sec, policy=p),
                                      [True, True, False, False])

    def test_per_particle_threshold_array_is_honoured(self):
        ia = [0.1, 5e-6, 5e-6]
        np.testing.assert_array_equal(flag_shattered(ia, [1e-6, 1e-6, 1e-5]),
                                      [False, True, True])


class Mutation(unittest.TestCase):
    """The equivalence comparison fires when the policy moves one step off UIOOPS."""

    def test_the_equivalence_helper_rejects_neighbours_0_and_2(self):
        ia, thr = np.array([0.1, 0.1, 1e-7, 0.1]), 1e-6
        self.assertTrue(_matches_v35(ia, thr, UIOPS_POLICY))
        for n in (0, 2):
            self.assertFalse(_matches_v35(ia, thr, InterArrivalPolicy(enabled=True,
                                                                      neighbours=n)))


class Registered(unittest.TestCase):
    def test_registered_and_applies_to_both_engines(self):
        """Resolved on like every module; the switch itself is the parameter, OFF
        by default, so the entry point called with no policy is UIOOPS."""
        self.assertIn("intarr_policy", registry.REGISTRY)
        self.assertTrue(applicability.applicable("intarr_policy", "3.5"))
        self.assertTrue(applicability.applicable("intarr_policy", "3.1.4"))
        self.assertIs(registry.entry_point("intarr_policy"), flag_shattered)


@unittest.skipUnless(_DENSE_RAW.exists(), f"tracked dense raw fixture not present: {_DENSE_RAW}")
class DenseDemoFlightAB(unittest.TestCase):
    """A/B on the v3.5 engine's decode of the dense demo flight (240 particles; designed
    gaps of 20 and 4000 particle-clock counts, i.e. 1.538 us and 307.7 us at 130 m/s, plus the
    record-start zero). Counts measured 2026-09-14 and pinned."""

    @classmethod
    def setUpClass(cls):
        from arrayprobe.profiles import STOCK_V35

        cls._tmp = tempfile.TemporaryDirectory()
        out = Path(cls._tmp.name)
        rf = _load_run_flight()
        cls._rf = rf
        cls._saved = (rf.ENGINE, rf.PROFILE, rf.TAS_FILE, rf.log)
        rf.log = lambda *a, **kw: None
        rf.ENGINE, rf.PROFILE = "3.5", STOCK_V35
        rf.TAS_FILE = str(_write_aircraft_cdf(out / "dense_aircraft.cdf"))
        proc = rf.stage3(rf.stage2(_DENSE_RAW, out), out)
        with netCDF4.Dataset(proc) as p:
            cls.ia = np.asarray(p.variables["inter_arrival"][:], float)
            cls.sec = np.asarray(p.variables["Time"][:], float)
            tis = np.asarray(p.variables["Time_in_seconds"][:], float)
        with np.errstate(all="ignore"):
            cls.thresholds = intarr_analysis.analyse(
                intarr_analysis.inter_arrival(tis), cls.sec, n_blocks=5)

    @classmethod
    def tearDownClass(cls):
        rf = cls._rf
        rf.ENGINE, rf.PROFILE, rf.TAS_FILE, rf.log = cls._saved
        cls._tmp.cleanup()

    def test_the_three_rules_and_three_neighbour_counts(self):
        self.assertEqual(self.ia.size, 240)
        got = compare_policies(self.ia, self.thresholds, self.sec)
        want = {
            ("min_measured", 0): 20, ("min_measured", 1): 20, ("min_measured", 2): 40,
            ("twice_tau2", 0): 20, ("twice_tau2", 1): 20, ("twice_tau2", 2): 40,
            ("min_fitted", 0): 68, ("min_fitted", 1): 116, ("min_fitted", 2): 184,
        }
        self.assertEqual(got, want)

    def test_neighbour_count_on_the_6_us_default_production_threshold(self):
        got = {n: int(flag_shattered_by_second(
                   self.ia, 6e-6, self.sec,
                   policy=UIOPS_POLICY if n == 1 else InterArrivalPolicy(
                       enabled=True, neighbours=n)).sum())
               for n in NEIGHBOUR_COUNTS}
        # measured 2026-09-14: 20 record-start zeros + 60 designed 1.538 us gaps are hits
        self.assertEqual(got, {0: 80, 1: 140, 2: 220})


if __name__ == "__main__":
    unittest.main()
