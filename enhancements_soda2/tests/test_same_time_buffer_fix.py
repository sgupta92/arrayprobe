# SPDX-License-Identifier: BSD-3-Clause
"""S4-o (``soda2_processbuffer.pro:362-365``'s same-time-buffer
overwrite) -- ``same_time_buffer_fix.corrected_process_spec_buffer``.

``_run_case`` is duplicated from ``test_soda2_processbuffer_spec.py``
rather than imported across the package boundary (the stage 2/3
convention). Golden cases: ``s2_h_baseline`` (``lastbufftime=0.0 !=
bufftime=24243.25``, the non-same-time equivalence case) and
``s2_sametime`` (``lastbufftime == bufftime``, the S4-o A/B case) from
``gdl_soda2_processbuffer_spec_golden.json``.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from arrayprobe_soda2.processbuffer_spec import (
    SpecBufferParticles,
    SpecMisc,
    SpecOp,
    process_spec_buffer,
)

from arrayprobe_soda2_enhancements.registry import PROTECTIVE, REGISTRY, resolve
from arrayprobe_soda2_enhancements.same_time_buffer_fix import (
    corrected_process_spec_buffer,
)

DATA = Path(__file__).resolve().parents[2] / "tests" / "data"
GOLDEN = DATA / "gdl_soda2_processbuffer_spec_golden.json"
S2_RAW = DATA / "s2_spec_raw_fixture"
FRAME_RAW = DATA / "soda2_spec_frame_fixture"


def _load_golden() -> list[dict]:
    records = json.loads(GOLDEN.read_text(encoding="utf-8"))
    return [r for r in records if "oracle_shims" not in r]


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


def _fixture(rec: dict) -> Path:
    return S2_RAW if rec["fixture"] == "s2" else FRAME_RAW


class Equivalence(unittest.TestCase):
    """A buffer whose time does NOT match the previous one's never
    takes the :362-365 branch -- corrected and port must agree bit
    for bit."""

    def test_matches_port_when_times_differ(self):
        rec = next(r for r in _load_golden() if r["name"] == "s2_h_baseline")
        self.assertNotEqual(rec["lastbufftime"], rec["bufftime"])

        op, misc_port = _op_and_misc(rec)
        with open(_fixture(rec), "rb") as f:
            port_out = process_spec_buffer(f, rec["bufftime"], op, misc_port)
        assert isinstance(port_out, SpecBufferParticles)

        op2, misc_fixed = _op_and_misc(rec)
        with open(_fixture(rec), "rb") as f:
            fixed_out = corrected_process_spec_buffer(f, rec["bufftime"], op2, misc_fixed)
        assert isinstance(fixed_out, SpecBufferParticles)

        self.assertEqual(list(fixed_out.time_sfm), list(port_out.time_sfm))
        self.assertEqual(misc_fixed.maxsfm, misc_port.maxsfm)


class ABConsequence(unittest.TestCase):
    """A same-time buffer: the port's own time_sfm[0] never adds
    inttime[0] (S4-o); the correction shifts the whole array (and
    misc.maxsfm) by exactly that amount."""

    def test_same_time_buffer_shifts_time_sfm_by_inttime_0(self):
        rec = next(r for r in _load_golden() if r["name"] == "s2_sametime")
        self.assertEqual(rec["lastbufftime"], rec["bufftime"])

        op, misc_port = _op_and_misc(rec)
        with open(_fixture(rec), "rb") as f:
            port_out = process_spec_buffer(f, rec["bufftime"], op, misc_port)
        assert isinstance(port_out, SpecBufferParticles)
        self.assertEqual(float(port_out.time_sfm[0]), rec["maxsfm"],
                          "the port's own S4-o value: inttime[0] not added")

        op2, misc_fixed = _op_and_misc(rec)
        with open(_fixture(rec), "rb") as f:
            fixed_out = corrected_process_spec_buffer(f, rec["bufftime"], op2, misc_fixed)
        assert isinstance(fixed_out, SpecBufferParticles)

        shift = float(port_out.inttime[0])
        self.assertGreater(shift, 0.0, "sanity: there is something to add")
        for i in range(len(port_out.time_sfm)):
            self.assertAlmostEqual(
                float(fixed_out.time_sfm[i]), float(port_out.time_sfm[i]) + shift,
                places=6, msg=f"index {i}")
        self.assertAlmostEqual(misc_fixed.maxsfm,
                                float(fixed_out.time_sfm.max()), places=6)

    def test_hvps3_same_time_buffer_also_shifts(self):
        """The register's second measured case, on the frame fixture."""
        rec = next(r for r in _load_golden() if r["name"] == "frame_hvps3_sametime")
        self.assertEqual(rec["lastbufftime"], rec["bufftime"])

        op, misc_port = _op_and_misc(rec)
        with open(_fixture(rec), "rb") as f:
            port_out = process_spec_buffer(f, rec["bufftime"], op, misc_port)
        assert isinstance(port_out, SpecBufferParticles)

        op2, misc_fixed = _op_and_misc(rec)
        with open(_fixture(rec), "rb") as f:
            fixed_out = corrected_process_spec_buffer(f, rec["bufftime"], op2, misc_fixed)
        assert isinstance(fixed_out, SpecBufferParticles)

        shift = float(port_out.inttime[0])
        self.assertAlmostEqual(float(fixed_out.time_sfm[0]),
                                float(port_out.time_sfm[0]) + shift, places=6)


class SwitchStates(unittest.TestCase):
    def test_registered_default_off_a14(self):
        self.assertIn("same_time_buffer_fix", REGISTRY)
        spec = REGISTRY["same_time_buffer_fix"]
        self.assertFalse(spec.default_on)
        self.assertEqual(spec.finding, "S4-o")
        self.assertEqual(spec.reachability, "live")

    def test_resolve_on_through_the_protective_set_false_when_opted_out(self):
        self.assertFalse(resolve({})["same_time_buffer_fix"])
        self.assertTrue(resolve({}, protective=PROTECTIVE)["same_time_buffer_fix"])
        self.assertFalse(
            resolve({"same_time_buffer_fix": False}, protective=PROTECTIVE)["same_time_buffer_fix"])
        self.assertFalse(resolve({"same_time_buffer_fix": False})["same_time_buffer_fix"])


if __name__ == "__main__":
    unittest.main()
