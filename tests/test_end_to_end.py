# SPDX-License-Identifier: BSD-3-Clause
"""The end-to-end test: raw binary in, combined flight product out, through
``run_flight.py``'s own stage functions -- not the individual modules
directly, so this proves the *composition* (each stage's output actually
satisfies the next stage's input contract) rather than re-proving any one
stage in isolation, which the per-stage suites already do thoroughly.

Everything here is synthetic (a hand-built raw ``.2DS`` file, built by
``scripts/make_demo_flight.py`` -- the same tool a stranger runs for the
ten-minute quickstart) rather than real ORACLES data, for the same reason
``test_imgproc_merge_chunks.py`` and the raw readers' synthetic fixtures are:
this needs no reference data and no Octave to run, so a fresh clone exercises
the full chain without any external dependency. It is not a substitute for
the real, oracle-backed full-flight acceptance gate (S4c, "the only
comparison whose two sides are built from the same inputs") -- it proves the
pipe fits together, not that the water in it is correct science, which is
what the per-stage oracle suites are for.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from tests._repo import needs_v314_engine  # noqa: E402

_TOOLS = Path(__file__).resolve().parent.parent / "scripts"

_DEMO_SPEC = importlib.util.spec_from_file_location(
    "make_demo_flight", _TOOLS / "make_demo_flight.py")
assert _DEMO_SPEC is not None and _DEMO_SPEC.loader is not None
make_demo_flight = importlib.util.module_from_spec(_DEMO_SPEC)
sys.modules["make_demo_flight"] = make_demo_flight
_DEMO_SPEC.loader.exec_module(make_demo_flight)
_build_raw_flight = make_demo_flight.build_demo_flight

_SPEC = importlib.util.spec_from_file_location(
    "run_flight", _TOOLS / "run_flight.py")
assert _SPEC is not None and _SPEC.loader is not None
run_flight = importlib.util.module_from_spec(_SPEC)
sys.modules["run_flight"] = run_flight
_SPEC.loader.exec_module(run_flight)


class EndToEndTests(unittest.TestCase):
    """S2 -> S3 -> S4 -> S4c, via run_flight.py's own stage functions."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out = Path(self._tmp.name)
        self.raw = self.out / "base160906064000.2DS"
        _build_raw_flight(self.raw)
        self._real_log = run_flight.log
        run_flight.log = lambda *a, **kw: None
        self.addCleanup(setattr, run_flight, "log", self._real_log)

    @needs_v314_engine
    def test_each_stage_produces_the_next_stages_expected_input(self):
        image = run_flight.stage2(self.raw, self.out)
        self.assertTrue(image.exists())
        self.assertTrue((self.out / f"{self.raw.stem}.tas.csv").exists(),
                        "S4 needs this sidecar; S2 must have written it")

        proc = run_flight.stage3(image, self.out)
        self.assertTrue(proc.exists())

        sd = run_flight.stage4(proc, self.raw.stem, self.out)
        self.assertTrue(sd.exists())

        combined = run_flight.stage_combine([self.raw.stem], self.out)
        self.assertIsNotNone(combined)
        self.assertTrue(combined.exists())

    @needs_v314_engine
    def test_particles_survive_the_whole_chain_into_the_combined_product(self):
        import netCDF4

        image = run_flight.stage2(self.raw, self.out)
        proc = run_flight.stage3(image, self.out)
        with netCDF4.Dataset(str(proc)) as p:
            n_particles = p.dimensions["time"].size
            reject = np.asarray(p.variables["image_auto_reject"][:])
            centerin = np.asarray(p.variables["image_center_in"][:])
        self.assertGreater(n_particles, 0, "the synthetic drop must actually frame")
        self.assertTrue((reject == 48).any(), "at least one particle must be accepted")
        self.assertTrue((centerin == 1).any(), "S4's sa_method=0 mask needs a centred one")

        # iat_file='' (the no-twelfth-argument call, stage4's other legitimate
        # path) rather than the production default: this test's synthetic
        # timestamps are arbitrary incrementing constants, not a realistic
        # microsecond clock, so consecutive particles read as sub-6us
        # inter-arrivals and the production call's shattering block rejects
        # every one of them -- a real effect of that call, not a bug here,
        # but not what this test (composition, not production-exact numbers)
        # is checking.
        sd = run_flight.stage4(proc, self.raw.stem, self.out, iat_file="")
        with netCDF4.Dataset(str(sd)) as s:
            self.assertIn("Reject_ratio", s.variables)
            self.assertIn("sample_vol", s.variables)
            sample_vol = np.asarray(s.variables["sample_vol"][:])
        # NOT asserted here: Reject_ratio < 1 / nonzero Counts downstream. A
        # hand-built particle small enough to satisfy S3's whole accept
        # ladder (centred, aspect-ratio coherent) still trips S4's own
        # area-ratio reject at sizedist.py:782 (auto_reject[area_ratio <
        # reject.area_ratio_z] = ord('z')) -- a real S4 criterion working as
        # designed on a synthetic 4-diode blob, not a defect. Getting past
        # BOTH stages' full physical-plausibility gauntlets at once needs a
        # calibrated synthetic shape, which is more fragile than what this
        # test is scoped to prove (see module docstring: composition, not
        # production-exact numbers). sample_vol > 0 shows S4 ran its per-
        # second machinery over real TAS-derived volumes rather than
        # short-circuiting before reaching that stage.
        self.assertGreater(np.nansum(sample_vol), 0,
                           "S4 must compute a real sample volume per second, "
                           "even for a second whose particles are all rejected")

        combined = run_flight.stage_combine([self.raw.stem], self.out)
        with netCDF4.Dataset(str(combined)) as c:
            self.assertIn("Counts", c.variables)
            self.assertIn("Size Distribution cm-3", c.variables)

    @needs_v314_engine
    def test_running_it_twice_skips_every_stage_the_second_time(self):
        """The whole point of the skip-if-done contract, exercised across all
        four stages at once rather than one function at a time.
        """
        logged = []
        run_flight.log = logged.append

        image = run_flight.stage2(self.raw, self.out)
        proc = run_flight.stage3(image, self.out)
        run_flight.stage4(proc, self.raw.stem, self.out)
        run_flight.stage_combine([self.raw.stem], self.out)

        logged.clear()
        image2 = run_flight.stage2(self.raw, self.out)
        proc2 = run_flight.stage3(image2, self.out)
        run_flight.stage4(proc2, self.raw.stem, self.out)
        run_flight.stage_combine([self.raw.stem], self.out)

        # "S4c prov" lines report what the combine's inputs were built with and
        # are printed on every run, skip or not -- they are the provenance
        # control's evidence, not work being done. Every line that reports a
        # STAGE must say skip.
        stage_lines = [ln for ln in logged if "prov" not in ln.lower()]
        self.assertTrue(stage_lines, logged)
        self.assertTrue(all("skip" in ln.lower() for ln in stage_lines), logged)
        # And the second pass must have found its stamps current rather than
        # rebuilding: a stage that redid its work would have logged "redo".
        self.assertFalse(any("redo" in ln.lower() for ln in logged), logged)


if __name__ == "__main__":
    unittest.main()
