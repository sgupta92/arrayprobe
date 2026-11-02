# SPDX-License-Identifier: BSD-3-Clause
"""S4c decides whether a combined product is current from its ``.call`` stamp.

The observed failure: a v3.5 run into a directory, then a v3.1.4 run into the same directory.
The second run rebuilt every ``proc`` and ``sd`` file under its own engine (their stamps
changed), but the combine logged ``S4c skip ... current`` and kept the product stamped
``engine=3.5``, because the only thing it compared was how many files the product stitched.
The product on disk no longer matched its inputs, and nothing said so.

The rule these tests pin: the combine is current only when its own stamp is equivalent (by
``_stamps_equivalent``, the comparison every other stage uses) to the stamp it would write now
-- which names the engine and the constituent ``sd`` files' own stamps -- and the product is
not older than any file it stitches. An unchanged re-run still skips, and a product whose stamp
predates a key the driver later started writing is not rebuilt for that alone.
"""

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

from tests._profile_registry_guard import module_hooks

setUpModule, tearDownModule = module_hooks()

_SPEC = importlib.util.spec_from_file_location(
    "run_flight", Path(__file__).resolve().parent.parent / "scripts" / "run_flight.py")
assert _SPEC is not None and _SPEC.loader is not None
run_flight = importlib.util.module_from_spec(_SPEC)
sys.modules["run_flight"] = run_flight
_SPEC.loader.exec_module(run_flight)

STEMS = ["base160906064017", "base160906104932"]

#: Literal sd stamps, one per engine: the combine carries an input's stamp verbatim, so the
#: test needs no engine configured to build them.
V35_SD = "engine=3.5 iat_file=2DS_intArrThreshold_MISSING.cdf profile=stock-v35"
V314_SD = "engine=3.1.4 iat_file=2DS_intArrThreshold_MISSING.cdf profile=oracles-production"


class CombineCurrencyFollowsTheStamp(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out = Path(self._tmp.name)
        self.logged: list[str] = []
        real_log, real_engine = run_flight.log, run_flight.ENGINE
        run_flight.log = self.logged.append
        self.addCleanup(setattr, run_flight, "log", real_log)
        self.addCleanup(setattr, run_flight, "ENGINE", real_engine)
        # The engines name their products differently (only 3.1.4 appends ``_2``), so
        # each case computes its target under the engine it runs; ``self.target`` is
        # always the product of the most recent ``_combine``.
        self.target = self._target_for("3.1.4")

    def _target_for(self, engine: str) -> Path:
        saved = run_flight.ENGINE
        run_flight.ENGINE = engine
        try:
            return run_flight.combine_out_path(sorted(STEMS), self.out)
        finally:
            run_flight.ENGINE = saved

    def _write_sds(self, stamp: str, mtime: float) -> None:
        import numpy as np
        from tests.test_combine import _write_sd_fixture

        from arrayprobe.matlab_compat import datenum
        for k, stem in enumerate(STEMS):
            t0 = datenum(2016, 9, 6, 6 + 4 * k, 40, 17)
            time = np.array([t0, t0 + 1 / 86400])
            target = self.out / f"sd.{stem}.H.nc"
            _write_sd_fixture(
                target, time, np.array([0.01, 0.02]),
                conc_minR=np.zeros((2, 2)), conc_AreaR=np.zeros((2, 2)),
                n=np.zeros(2), reject_ratio=np.zeros(2),
                count=np.zeros((2, 2)), mean_area_ratio=np.zeros((2, 2)))
            run_flight.write_stamp(target, stamp)
            os.utime(target, (mtime, mtime))

    def _combine(self, engine: str) -> Path:
        self.target = self._target_for(engine)
        run_flight.ENGINE = engine
        self.logged.clear()
        target = run_flight.stage_combine(STEMS, self.out, borrowed=(engine == "3.5"))
        self.assertEqual(target, self.target)
        return target

    def _age_product(self, mtime: float) -> None:
        os.utime(self.target, (mtime, mtime))

    def test_a_v35_product_is_rebuilt_when_a_v314_run_rebuilds_its_inputs(self):
        """The observed case, reproduced: engine 3.5 into a directory, then engine 3.1.4."""
        self._write_sds(V35_SD, mtime=1_000_000_000)
        self._combine("3.5")
        v35_product = self.target
        self.assertTrue(run_flight.read_stamp(v35_product).startswith("engine=3.5 "))
        self._age_product(1_000_000_100)

        # The v3.1.4 run's S4 rewrites both sd files under its own engine.
        self._write_sds(V314_SD, mtime=1_000_000_200)
        self._combine("3.1.4")

        self.assertFalse(any("S4c skip" in ln for ln in self.logged), self.logged)
        stamp = run_flight.read_stamp(self.target)
        self.assertTrue(stamp.startswith("engine=3.1.4 "), stamp)
        self.assertIn(f"inputs_built_with=({V314_SD})", stamp)
        # The two engines' products have different names, so the v3.1.4 run wrote its
        # own and left the v3.5 product, with its own stamp, in place.
        self.assertNotEqual(self.target, v35_product)
        self.assertTrue(run_flight.read_stamp(v35_product).startswith("engine=3.5 "))

    def test_same_engine_but_changed_inputs_is_rebuilt(self):
        """Engine unchanged, constituents rebuilt under another configuration: the stamp's
        ``inputs_built_with`` differs, so the product is stale."""
        self._write_sds(V314_SD, mtime=1_000_000_000)
        self._combine("3.1.4")
        other = V314_SD.replace("oracles-production", "stock")
        # Deliberately NOT newer: the stamp alone must decide it.
        self._write_sds(other, mtime=1_000_000_000)
        self._age_product(1_000_000_100)
        self._combine("3.1.4")
        self.assertFalse(any("S4c skip" in ln for ln in self.logged), self.logged)
        self.assertIn(f"inputs_built_with=({other})", run_flight.read_stamp(self.target))

    def test_an_unchanged_rerun_still_skips(self):
        for engine, sd in (("3.1.4", V314_SD), ("3.5", V35_SD)):
            with self.subTest(engine=engine):
                self._target_for(engine).unlink(missing_ok=True)
                self._write_sds(sd, mtime=1_000_000_000)
                self._combine(engine)
                self._age_product(1_000_000_100)
                before = self.target.stat().st_mtime
                self._combine(engine)
                self.assertTrue(any("S4c skip" in ln for ln in self.logged), self.logged)
                self.assertEqual(self.target.stat().st_mtime, before)

    def test_a_v35_stamp_without_inputs_built_with_is_not_rebuilt_for_that_alone(self):
        """A v3.5 product written before the driver added ``inputs_built_with`` to its stamp
        carries only the combine module's own two lines. If nothing it stitched is newer, it
        is current."""
        self._write_sds(V35_SD, mtime=1_000_000_000)
        self._combine("3.5")
        stamp = run_flight.read_stamp(self.target)
        legacy = stamp.rsplit("\ninputs_built_with=", 1)[0]
        self.assertNotEqual(legacy, stamp)
        run_flight.write_stamp(self.target, legacy)
        self._age_product(1_000_000_100)
        self._combine("3.5")
        self.assertTrue(any("S4c skip" in ln for ln in self.logged), self.logged)

    def test_a_product_older_than_an_input_is_rebuilt(self):
        """Same configuration, but an sd file rewritten after the product: the stamp records
        configuration, not inputs, so the age check is what catches it."""
        self._write_sds(V314_SD, mtime=1_000_000_000)
        self._combine("3.1.4")
        self._age_product(1_000_000_100)
        self._write_sds(V314_SD, mtime=1_000_000_200)
        self._combine("3.1.4")
        self.assertFalse(any("S4c skip" in ln for ln in self.logged), self.logged)

    def test_a_mixture_is_still_refused_unless_asked(self):
        self._write_sds(V314_SD, mtime=1_000_000_000)
        run_flight.write_stamp(self.out / f"sd.{STEMS[1]}.H.nc",
                               V314_SD.replace("oracles-production", "stock"))
        run_flight.ENGINE = "3.1.4"
        with self.assertRaises(run_flight.UnverifiableProvenance):
            run_flight.stage_combine(STEMS, self.out)
        self.assertIsNotNone(run_flight.stage_combine(STEMS, self.out, allow_mixed=True))


if __name__ == "__main__":
    unittest.main()
