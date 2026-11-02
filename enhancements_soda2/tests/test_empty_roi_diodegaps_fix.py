# SPDX-License-Identifier: BSD-3-Clause
"""S5-h (``soda2_processbuffer.pro:707-709``'s empty-ROI ``diodegaps``) --
``empty_roi_diodegaps_fix.corrected_diodegaps``.

Proved against the real, unmodified ``process_buffer_tail`` end to end
on the tracked ``s2_spec_raw_fixture`` (the ``s2_h_baseline`` golden
case), the same construction
``test_soda2_processbuffer_spec.py::TheTailTraps::
test_line_709_diodegaps_is_1_not_0_on_a_synthetic_empty_roi`` uses --
``_run_case``/``_tail_op`` duplicated here rather than imported across
the package boundary (the stage 2/3 convention).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np
from arrayprobe_soda2.processbuffer_spec import (
    NullBuffer,
    SpecBufferParticles,
    SpecMisc,
    SpecOp,
    process_spec_buffer,
)
from arrayprobe_soda2.processbuffer_tail import TailOp, process_buffer_tail

from arrayprobe_soda2_enhancements.empty_roi_diodegaps_fix import corrected_diodegaps
from arrayprobe_soda2_enhancements.registry import REGISTRY, resolve

DATA = Path(__file__).resolve().parents[2] / "tests" / "data"
GOLDEN = DATA / "gdl_soda2_processbuffer_spec_golden.json"
S2_RAW = DATA / "s2_spec_raw_fixture"


def _load_golden() -> list[dict]:
    records = json.loads(GOLDEN.read_text(encoding="utf-8"))
    return [r for r in records if "oracle_shims" not in r]


def _run_case(rec: dict) -> tuple[SpecBufferParticles | NullBuffer, SpecMisc]:
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
    with open(S2_RAW, "rb") as f:
        result = process_spec_buffer(f, rec["bufftime"], op, misc)
    return result, misc


def _tail_op(rec: dict) -> TailOp:
    return TailOp(
        stuckbits=rec["stuckbits"], rakefix=rec["rakefix"],
        greythresh=rec["greythresh"], dioderange=tuple(rec["dioderange"]),
        numdiodes=128, keeplargest=rec["keeplargest"],
        res=rec["res"], yres=rec["yres"],
    )


class Equivalence(unittest.TestCase):
    """A real (nonempty) particle's own ``roihist`` -- rebuilt exactly
    as ``process_buffer_tail`` builds it -- must give the same
    ``diodegaps`` the real port function returned."""

    def test_matches_port_diodegaps_on_a_real_particle(self):
        rec = next(r for r in _load_golden() if r["name"] == "s2_h_baseline")
        result, _misc = _run_case(rec)
        assert isinstance(result, SpecBufferParticles)
        op = _tail_op(rec)
        port_out = process_buffer_tail(result, op, np.zeros(128, dtype=np.int32))

        s, e = int(result.startline[0]), int(result.stopline[0])
        fp, lp = op.dioderange
        roi_orig = result.bitimage[s:e + 1, fp:lp + 1]
        roihist = roi_orig.sum(axis=0).astype(np.float64) if roi_orig.ndim == 2 else roi_orig
        self.assertGreater(int(np.count_nonzero(roihist)), 0,
                            "sanity: this particle's ROI is not empty")

        got = corrected_diodegaps(roihist)
        self.assertEqual(int(got), int(port_out.diodegaps[0]))


class ABConsequence(unittest.TestCase):
    """An artificially blanked ROI (same construction as the port's own
    ``test_line_709_diodegaps_is_1_not_0_on_a_synthetic_empty_roi``):
    the real port returns ``diodegaps=1``; the correction returns 0."""

    def test_empty_roi_gets_diodegaps_zero_not_one(self):
        rec = next(r for r in _load_golden() if r["name"] == "s2_h_baseline")
        result, _misc = _run_case(rec)
        assert isinstance(result, SpecBufferParticles)
        s, e = int(result.startline[0]), int(result.stopline[0])
        result.bitimage = result.bitimage.copy()
        result.bitimage[s:e + 1, :] = 0
        op = _tail_op(rec)
        port_out = process_buffer_tail(result, op, np.zeros(128, dtype=np.int32))
        self.assertEqual(int(port_out.diodegaps[0]), 1, "the port's own S5-h value")

        # The same all-zero roihist the tail would have built for this particle.
        fp, lp = op.dioderange
        roihist = np.zeros(lp - fp + 1, dtype=np.float64)
        got = corrected_diodegaps(roihist)
        self.assertEqual(int(got), 0)


class SwitchStates(unittest.TestCase):
    def test_registered_default_off_a14(self):
        self.assertIn("empty_roi_diodegaps_fix", REGISTRY)
        spec = REGISTRY["empty_roi_diodegaps_fix"]
        self.assertFalse(spec.default_on)
        self.assertEqual(spec.finding, "S5-h")
        self.assertEqual(spec.reachability, "flagged")

    def test_resolve_false_by_default_true_when_opted_in(self):
        self.assertFalse(resolve({})["empty_roi_diodegaps_fix"])
        self.assertTrue(resolve({"empty_roi_diodegaps_fix": True})["empty_roi_diodegaps_fix"])
        self.assertFalse(resolve({"empty_roi_diodegaps_fix": False})["empty_roi_diodegaps_fix"])


if __name__ == "__main__":
    unittest.main()
