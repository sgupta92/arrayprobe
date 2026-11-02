# SPDX-License-Identifier: BSD-3-Clause
"""S4-q (``soda2_processbuffer.pro:296``/``:339``, frames/buffers
dropped with no count) + S5-c (``soda2_particlesort.pro:79-81``,
particles dropped at ``itime==numrecords``) --
``run_diagnostics.spec_buffer_diagnostics`` /
``.particlesort_diagnostics``. It also covers S6-b
(``process_2d.py:528-532``, date-mismatch branch) and S6-d
(``:632-636``, a flush-triggered ``None`` return) --
``.driver_date_diagnostics`` / ``.run_with_return_diagnostics``.

Fixture/golden helpers duplicated from
``test_soda2_processbuffer_spec.py`` and ``test_soda2_particlesort.py``
(the stage 2/3 convention); ``_base_op``/fixture paths duplicated from
``test_soda2_process_2d.py`` (same convention, stage 8b).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np
from arrayprobe_soda2.particlesort import ParticlesortOptions, new_accumulator
from arrayprobe_soda2.process_2d import ProcessData, soda2_process_2d
from arrayprobe_soda2.processbuffer_spec import NullBuffer, SpecMisc, SpecOp

from arrayprobe_soda2_enhancements.registry import REGISTRY, resolve
from arrayprobe_soda2_enhancements.run_diagnostics import (
    driver_date_diagnostics,
    particlesort_diagnostics,
    run_with_return_diagnostics,
    spec_buffer_diagnostics,
)

DATA = Path(__file__).resolve().parents[2] / "tests" / "data"
PB_GOLDEN = DATA / "gdl_soda2_processbuffer_spec_golden.json"
S2_RAW = DATA / "s2_spec_raw_fixture"
PS_GOLDEN = DATA / "gdl_soda2_particlesort_golden.json"
S2_FIXTURE = DATA / "s2_spec_raw_fixture"
FRAME_FIXTURE = DATA / "soda2_spec_frame_fixture"

ENDBINS = np.array([10.0, 50.0, 100.0, 200.0, 500.0])
ARENDBINS = np.array([0.0, 0.5, 1.0])


def _base_op(**overrides) -> dict:
    """Duplicated verbatim from ``test_soda2_process_2d.py``'s own
    ``_base_op`` (stage 2/3's convention: fixture/golden helpers are
    copied into each stage's own test module, never imported across
    ``tests/`` and ``enhancements_soda2/tests/``)."""
    op = dict(
        fn=str(S2_FIXTURE), date="20160906", starttime=24240.0, stoptime=24250.0,
        format="SPEC", subformat=0, probetype="2DS", res=10.0,
        endbins=[0.0, 50.0, 100.0, 200.0, 500.0], arendbins=[0.0, 0.5, 1.0],
        rate=1.0, smethod="xy", pth="", particlefile=0, inttime_reject=0,
        stuckbits=0, water=0, fixedtas=0.0, timeoffset=0.0, armwidth=6.3,
        numdiodes=128, greythresh=0, probeid="H", eawmethod="centerin",
        wavelength=0.785e-6, dofconst=8.12, ncdfparticlefile=0, asciipsdfile=0,
        # `savfile` defaults to 1 (`update_op`) and the driver now
        # writes the SAVE file, which needs `outdir`; mirrors the port test's _base_op.
        savfile=0,
    )
    op.update(overrides)
    return op


def _load_pb_golden() -> list[dict]:
    return [r for r in json.loads(PB_GOLDEN.read_text(encoding="utf-8"))
            if "oracle_shims" not in r]


def _op_and_misc(rec: dict) -> tuple[SpecOp, SpecMisc]:
    op = SpecOp(
        probetype=rec["probetype"], subformat=0, probeid=rec["probeid"],
        dofreject=rec["dofreject"], stretchcorrect=rec["stretchcorrect"],
        yres=rec["yres"], res=rec["res"],
    )
    misc = SpecMisc(
        nimages=rec["nimages"], hkpointers=rec["hkpointers"],
        imagepointers=rec["imagepointers"], probetas=0.0,
        aircrafttas=rec["aircrafttas"], lastclock=rec["lastclock"],
        lastbufftime=rec["lastbufftime"], maxsfm=rec["maxsfm"],
    )
    return op, misc


class SpecBufferEquivalence(unittest.TestCase):
    """The wrapper's own ``result`` (the first element of its tuple)
    must equal the real port's return exactly -- the diagnostic is
    additive, never a second computation of the buffer itself."""

    def test_result_matches_the_real_process_spec_buffer(self):
        from arrayprobe_soda2.processbuffer_spec import (
            SpecBufferParticles,
            process_spec_buffer,
        )

        rec = next(r for r in _load_pb_golden() if r["name"] == "s2_h_baseline")
        op_port, misc_port = _op_and_misc(rec)
        with open(S2_RAW, "rb") as f:
            port_out = process_spec_buffer(f, rec["bufftime"], op_port, misc_port)
        assert isinstance(port_out, SpecBufferParticles)

        op_fixed, misc_fixed = _op_and_misc(rec)
        with open(S2_RAW, "rb") as f:
            result, diag = spec_buffer_diagnostics(f, rec["bufftime"], op_fixed, misc_fixed)
        assert isinstance(result, SpecBufferParticles)

        self.assertEqual(list(result.time_sfm), list(port_out.time_sfm))
        self.assertEqual(result.num_images, port_out.num_images)
        self.assertEqual(misc_fixed.maxsfm, misc_port.maxsfm)

        # And the diagnostic itself: 2 pointers in, but only 1 kept
        # particle (the other frame does not survive :296's own
        # error/oversize test) -- exactly the count S4-q says the
        # port never reports on its own.
        self.assertEqual(diag["frames_in"], rec["nimages"])
        self.assertEqual(diag["frames_kept"], result.num_images)
        self.assertEqual(diag["frames_dropped"], rec["nimages"] - result.num_images)
        self.assertGreater(diag["frames_dropped"], 0,
                            "sanity: this baseline case does drop a frame")
        self.assertFalse(diag["buffer_rejected"])


class SpecBufferABConsequence(unittest.TestCase):
    def test_all_dropped_buffer_is_reported(self):
        """The golden's own ``all_dropped`` case (nimages=1, REJECT=1):
        the port's own return value (a bare ``NullBuffer``) gives no
        way to tell this apart from ``nimages0`` (no input at all)
        without the diagnostic."""
        rec = next(r for r in _load_pb_golden() if r["name"] == "all_dropped")
        op, misc = _op_and_misc(rec)
        with open(S2_RAW, "rb") as f:
            result, diag = spec_buffer_diagnostics(f, rec["bufftime"], op, misc)
        self.assertIsInstance(result, NullBuffer)
        self.assertEqual(diag["frames_in"], 1)
        self.assertEqual(diag["frames_kept"], 0)
        self.assertEqual(diag["frames_dropped"], 1)
        self.assertTrue(diag["buffer_rejected"])

    def test_no_input_is_distinguished_from_a_dropped_input(self):
        """``nimages0`` (nimages=0) is the pre-loop :267 path, not
        S4-q's own drop -- the diagnostic must not report a false
        "frame dropped" for a buffer that never had one."""
        rec = next(r for r in _load_pb_golden() if r["name"] == "nimages0")
        op, misc = _op_and_misc(rec)
        with open(S2_RAW, "rb") as f:
            result, diag = spec_buffer_diagnostics(f, rec["bufftime"], op, misc)
        self.assertEqual(diag["frames_in"], 0)
        self.assertEqual(diag["frames_dropped"], 0)


def _load_ps_golden() -> list[dict]:
    return json.loads(PS_GOLDEN.read_text(encoding="utf-8"))[1:]


def _op_from_record(rec: dict) -> ParticlesortOptions:
    op = rec["op"]
    return ParticlesortOptions(
        starttime=op["starttime"], rate=op["rate"], clusterthresh=op["clusterthresh"],
        inttime_reject=op["inttime_reject"], smethod=op["smethod"],
        apply_psc=op["apply_psc"], apply_psc_sizelimit=op["apply_psc_sizelimit"],
        water=op["water"], endbins=np.array(op["endbins"]),
        arendbins=np.array(op["arendbins"]), eawmethod=op["eawmethod"],
        res=op["res"], dofreject=op["dofreject"], format="SPEC",
        probetype=op["probetype"],
    )


def _particles_from_record(rec: dict) -> dict[str, np.ndarray]:
    ps = rec["particles"]
    keys = ps[0].keys()
    out: dict[str, np.ndarray] = {}
    float_keys = {
        "buffertime", "probetime", "reftime", "inttime", "probetas", "missed",
        "diam", "xsize", "ysize", "areasize", "xextent", "oned", "twod",
        "sizecorrection", "arearatiofilled", "arearatio", "aspectratio",
        "orientation", "zd",
    }
    for k in keys:
        vals = [p[k] for p in ps]
        if k in float_keys:
            out[k] = np.array(vals, dtype=np.float64 if k in
                               ("buffertime", "probetime", "reftime", "inttime")
                               else np.float32)
        else:
            out[k] = np.array(vals, dtype=np.uint8)
    return out


class ParticlesortEquivalence(unittest.TestCase):
    def test_matches_port_rejectionflag_and_reports_zero_when_nothing_lands_at_numrecords(self):
        from arrayprobe_soda2.particlesort import soda2_particlesort

        rec = next(r for r in _load_ps_golden() if r["name"] == "single_accepted")
        op = _op_from_record(rec)
        x = _particles_from_record(rec)
        numrecords = int(rec["op"]["numrecords"])

        d_port = new_accumulator(op, numrecords=numrecords)
        port_rf = soda2_particlesort(op, x, d_port)

        d_fixed = new_accumulator(op, numrecords=numrecords)
        rf, dropped = particlesort_diagnostics(op, x, d_fixed)

        self.assertEqual(rf.tolist(), port_rf.tolist())
        np.testing.assert_array_equal(d_fixed.count_accepted, d_port.count_accepted)
        self.assertEqual(dropped, 0)


class ParticlesortABConsequence(unittest.TestCase):
    def test_reports_the_particle_dropped_at_numrecords(self):
        """The golden's own ``at_numrecords`` case (trap 5, S5-c):
        timeindex 4 == numrecords 4, silently dropped by the port."""
        rec = next(r for r in _load_ps_golden() if r["name"] == "at_numrecords")
        op = _op_from_record(rec)
        x = _particles_from_record(rec)
        numrecords = int(rec["op"]["numrecords"])
        d = new_accumulator(op, numrecords=numrecords)

        rf, dropped = particlesort_diagnostics(op, x, d)

        self.assertEqual(dropped, 1)
        self.assertEqual(int(d.count_accepted.sum()), 0,
                          "sanity: the port's own d truly never saw this particle")


class DriverDateEquivalence(unittest.TestCase):
    """S6-b -- ``driver_date_diagnostics`` never calls
    ``soda2_process_2d``, so there is no driver return value to compare;
    equivalence here means the branch it reports agrees with what the
    port's own line does on a case where the port runs to completion."""

    def test_frame_fixture_is_within_5_days_and_startdate_used_is_requested(self):
        op = _base_op(fn=str(FRAME_FIXTURE))
        diag = driver_date_diagnostics(op)
        self.assertEqual(diag["branch"], "within_5_days")
        self.assertEqual(diag["startdate_used"], diag["requested_julday"])


class DriverDateAB(unittest.TestCase):
    """S6-b, ``TraceLine410DateMismatch``'s own two ops
    (``test_soda2_process_2d.py:176``), which already drive
    ``date_off1``/``date_off10``."""

    def test_date_off10_reports_substituted_while_the_port_still_succeeds(self):
        full = soda2_process_2d(_base_op())
        shifted_op = _base_op(date="20160827")
        shifted = soda2_process_2d(shifted_op)
        diag = driver_date_diagnostics(shifted_op)

        self.assertEqual(diag["branch"], "substituted")
        self.assertNotEqual(diag["startdate_used"], diag["requested_julday"])
        self.assertIsInstance(full, ProcessData)
        self.assertIsInstance(shifted, ProcessData)
        for field_name in ("count_accepted", "total_count_rejected",
                            "numbuffsaccepted", "numbuffsrejected", "dhist"):
            np.testing.assert_array_equal(
                getattr(full, field_name), getattr(shifted, field_name),
                err_msg=field_name)

    def test_date_off1_reports_within_5_days_while_the_port_returns_none(self):
        op = _base_op(date="20160905")
        diag = driver_date_diagnostics(op)
        result = soda2_process_2d(op)

        self.assertEqual(diag["branch"], "within_5_days")
        self.assertEqual(diag["startdate_used"], diag["requested_julday"])
        self.assertIsNone(result)


class DriverReturnEquivalence(unittest.TestCase):
    """S6-d -- ``run_with_return_diagnostics``'s own primary return value
    (the first element of its tuple) must equal calling
    ``soda2_process_2d`` directly, on a case that completes normally."""

    def test_result_matches_the_real_driver_on_s2_full(self):
        port_out = soda2_process_2d(_base_op())
        result, diag = run_with_return_diagnostics(_base_op())

        self.assertIsInstance(result, ProcessData)
        self.assertIsInstance(port_out, ProcessData)
        for field_name in ("count_accepted", "total_count_rejected",
                            "numbuffsaccepted", "numbuffsrejected", "dhist"):
            np.testing.assert_array_equal(
                getattr(result, field_name), getattr(port_out, field_name),
                err_msg=field_name)
        self.assertEqual(diag, {"returned": True, "none_reason": None})


class DriverReturnAB(unittest.TestCase):
    """S6-d -- the two ``return None`` sites the finding says are
    indistinguishable from the port's own return value alone."""

    def test_window_empty_is_no_buffers_in_window(self):
        """``DriverRunsEndToEndOnTrackedFixtures.test_window_empty_returns_none``
        (`test_soda2_process_2d.py:138`)'s own op -- `:550-551`."""
        op = _base_op(starttime=24300.0, stoptime=24310.0)
        result, diag = run_with_return_diagnostics(op)
        self.assertIsNone(result)
        self.assertEqual(diag, {"returned": False, "none_reason": "no_buffers_in_window"})

    def test_frame_fixture_num2process_6_is_flush_left_nothing(self):
        """The measured case behind this test: forcing a mid-loop
        flush on ``frame_full`` (``num2process=6``) necessarily also
        flushes the last accepted buffer, landing on `:632-636` (S6-f/S6-d)
        before a ``ProcessData`` is ever built -- confirmed here to also be
        the S6-d ``None`` site, not the S6-a empty-window one."""
        op = _base_op(fn=str(FRAME_FIXTURE))
        forced_result, forced_diag = run_with_return_diagnostics(op, num2process=6)
        self.assertIsNone(forced_result)
        self.assertEqual(forced_diag,
                          {"returned": False, "none_reason": "flush_left_nothing"})

        # Sanity: the same op's default-`num2process` run does return a
        # result (this fixture's window is not itself empty) -- so the
        # `None` above is the flush, not S6-a.
        default_result, default_diag = run_with_return_diagnostics(op)
        self.assertIsInstance(default_result, ProcessData)
        self.assertEqual(default_diag["returned"], True)


class SwitchStates(unittest.TestCase):
    def test_registered_default_off_a14(self):
        self.assertIn("run_diagnostics", REGISTRY)
        spec = REGISTRY["run_diagnostics"]
        self.assertFalse(spec.default_on)
        self.assertEqual(spec.finding, "S4-q")
        self.assertEqual(spec.reachability, "flagged")

    def test_resolve_false_by_default_true_when_opted_in(self):
        self.assertFalse(resolve({})["run_diagnostics"])
        self.assertTrue(resolve({"run_diagnostics": True})["run_diagnostics"])
        self.assertFalse(resolve({"run_diagnostics": False})["run_diagnostics"])


if __name__ == "__main__":
    unittest.main()
