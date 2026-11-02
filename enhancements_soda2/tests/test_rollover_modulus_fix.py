# SPDX-License-Identifier: BSD-3-Clause
"""S4-n (rollover constant, ``soda2_processbuffer.pro:318``) --
``rollover_modulus_fix.corrected_inttime``.

Both cases run the real ``arrayprobe_soda2.processbuffer_spec.process_spec_buffer`` against
the tracked ``s2_spec_raw_fixture`` and the golden's own recorded per-case ``lastclock`` /
``yres`` / ``probetype`` -- the same fixture and the same golden
(``gdl_soda2_processbuffer_spec_golden.json``) ``test_soda2_processbuffer_spec.py`` uses, and
the exact `s2_rollover` case finding S4-n cites as "measured".
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np
from arrayprobe_soda2.processbuffer_spec import SpecMisc, SpecOp, process_spec_buffer

from arrayprobe_soda2_enhancements.registry import REGISTRY, resolve
from arrayprobe_soda2_enhancements.rollover_modulus_fix import (
    ROLLOVER_FIXED,
    corrected_inttime,
)

DATA = (Path(__file__).resolve().parents[2] / "tests" / "data")
GOLDEN = DATA / "gdl_soda2_processbuffer_spec_golden.json"
S2_RAW = DATA / "s2_spec_raw_fixture"

#: The port's own literal (processbuffer_spec.py:301) -- passing this reproduces the port
#: exactly, whatever the input; it is the "OFF" value for this correction.
ROLLOVER_PORT = 4294967295.0


def _load_records() -> dict[str, dict]:
    records = json.loads(GOLDEN.read_text(encoding="utf-8"))
    return {r["name"]: r for r in records if "oracle_shims" not in r}


def _run(rec: dict):
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
    initial_lastclock = misc.lastclock
    with open(S2_RAW, "rb") as f:
        result = process_spec_buffer(f, rec["bufftime"], op, misc)
    return op, result, initial_lastclock


class Equivalence(unittest.TestCase):
    """s2_h_baseline's lastclock (0.0) never triggers the wrap branch -- the rollover
    constant cannot matter, so corrected_inttime(..., rollover_constant=ROLLOVER_PORT) must
    equal the real port's own inttime bit for bit."""

    def test_matches_port_inttime_with_the_ports_own_constant(self):
        records = _load_records()
        rec = records["s2_h_baseline"]
        op, result, initial_lastclock = _run(rec)

        got = corrected_inttime(
            result.rawtime, result.clocktas, op.probetype, op.yres,
            initial_lastclock, rollover_constant=ROLLOVER_PORT,
        )
        np.testing.assert_array_equal(got, result.inttime)


class ABConsequence(unittest.TestCase):
    """s2_rollover (finding S4-n's own measured case, lastclock=70000.0) is
    constructed to trigger the wrap branch. The corrected constant must differ from the
    port's own inttime on exactly the wrapped frame(s), by exactly one extra clock tick's
    worth of freq (rollover_constant differs from the port's by 1.0, so the wrap-branch's
    ((xtime + rollover) - lastclock) grows by exactly 1 * freq)."""

    def test_recovers_the_missing_tick_on_the_named_golden_case(self):
        records = _load_records()
        rec = records["s2_rollover"]
        op, result, initial_lastclock = _run(rec)

        port_inttime = corrected_inttime(
            result.rawtime, result.clocktas, op.probetype, op.yres,
            initial_lastclock, rollover_constant=ROLLOVER_PORT,
        )
        np.testing.assert_array_equal(port_inttime, result.inttime)

        fixed_inttime = corrected_inttime(
            result.rawtime, result.clocktas, op.probetype, op.yres,
            initial_lastclock, rollover_constant=ROLLOVER_FIXED,
        )

        diff = fixed_inttime - port_inttime
        changed = np.flatnonzero(diff != 0)
        self.assertGreaterEqual(
            len(changed), 1,
            "s2_rollover is SODA-2 finding S4-n's own measured wrap case -- it must "
            "exercise the defect, or this is not testing what it claims to.")

        from arrayprobe_soda2.processbuffer_spec import _freq
        lastclock = initial_lastclock
        for i in range(len(result.rawtime)):
            xtime = int(result.rawtime[i])
            if xtime < lastclock:
                freq = _freq(op.yres, float(result.clocktas[i]))
                self.assertAlmostEqual(float(diff[i]), 1.0 * freq, places=12,
                                        msg=f"frame {i}: expected exactly one extra tick")
            else:
                self.assertEqual(float(diff[i]), 0.0)
            lastclock = xtime

    def test_hvps3_refuses_because_it_cannot_be_recomputed(self):
        with self.assertRaises(ValueError):
            corrected_inttime([1, 2], [1.0, 1.0], "HVPS3", 10.0, 0.0)


class SwitchStates(unittest.TestCase):
    def test_registered_default_off_a14(self):
        self.assertIn("rollover_modulus_fix", REGISTRY)
        spec = REGISTRY["rollover_modulus_fix"]
        self.assertFalse(spec.default_on)
        self.assertEqual(spec.finding, "S4-n")
        self.assertEqual(spec.reachability, "live")

    def test_resolve_false_by_default_true_when_opted_in(self):
        self.assertFalse(resolve({})["rollover_modulus_fix"])
        self.assertTrue(resolve({"rollover_modulus_fix": True})["rollover_modulus_fix"])
        self.assertFalse(resolve({"rollover_modulus_fix": False})["rollover_modulus_fix"])


if __name__ == "__main__":
    unittest.main()
