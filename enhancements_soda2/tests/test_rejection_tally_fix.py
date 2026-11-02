# SPDX-License-Identifier: BSD-3-Clause
"""S5-a/S5-q (``soda2_particlesort.pro:177-178``'s reject tally) --
``rejection_tally_fix.corrected_count_rejected``.

Golden loading, ``_op_from_record`` and ``_particles_from_record`` are
duplicated from ``test_soda2_particlesort.py`` rather than imported
across the package boundary (the stage 2/3 convention). Golden cases:
``size_below_first_bin`` (a single, unambiguous reject bit --
equivalence) and ``multi_bit_reject`` (bits 1+8,
S5-q's own measured case -- A/B). S5-a's bit-128-only case has no
tracked GDL bank (the register says so explicitly), so it is
constructed directly from the port's own ``soda2_reject`` rule
(``dofreject>=1 and dofflag==0`` sets bit 128, ``reject.py:220-221``).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np
from arrayprobe_soda2.particlesort import ParticlesortOptions, new_accumulator

from arrayprobe_soda2_enhancements.registry import REGISTRY, resolve
from arrayprobe_soda2_enhancements.rejection_tally_fix import corrected_count_rejected

GOLDEN = (Path(__file__).resolve().parents[2] / "tests" / "data"
          / "gdl_soda2_particlesort_golden.json")

ENDBINS = np.array([10.0, 50.0, 100.0, 200.0, 500.0])
ARENDBINS = np.array([0.0, 0.5, 1.0])


def _load_golden() -> list[dict]:
    records = json.loads(GOLDEN.read_text(encoding="utf-8"))
    return records[1:]  # records[0] is {"oracle_shims": []}


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


def _default_op(**overrides) -> ParticlesortOptions:
    kwargs = dict(
        starttime=0.0, rate=1.0, clusterthresh=0.0, inttime_reject=0,
        smethod="diam", apply_psc=0, apply_psc_sizelimit=0.0, water=0,
        endbins=ENDBINS, arendbins=ARENDBINS, eawmethod="allin",
        dofreject=1, probetype="", format="SPEC",
    )
    kwargs.update(overrides)
    return ParticlesortOptions(**kwargs)


def _particle_batch(n: int, **overrides) -> dict[str, np.ndarray]:
    base = dict(
        probetime=np.zeros(n), buffertime=np.zeros(n), reftime=np.zeros(n),
        inttime=np.full(n, 0.01), overloadflag=np.zeros(n, dtype=np.uint8),
        probetas=np.full(n, 50.0, dtype=np.float32), missed=np.zeros(n),
        xsize=np.full(n, 100.0), ysize=np.full(n, 100.0), areasize=np.full(n, 100.0),
        xextent=np.full(n, 100.0), oned=np.full(n, 100.0), twod=np.full(n, 100.0),
        diam=np.full(n, 100.0), sizecorrection=np.ones(n),
        arearatiofilled=np.full(n, 0.8), arearatio=np.full(n, 0.8),
        aspectratio=np.full(n, 0.8), orientation=np.zeros(n), zd=np.zeros(n),
        allin=np.ones(n, dtype=np.uint8), centerin=np.ones(n, dtype=np.uint8),
        dofflag=np.ones(n, dtype=np.uint8),
    )
    base.update(overrides)
    return base


class Equivalence(unittest.TestCase):
    """A single, unambiguous reject bit (no multi-bit, no bit-128) --
    the corrected tally's first 7 columns must agree with the port's
    own ``d.count_rejected`` exactly, and the new 8th column must be 0."""

    def test_matches_port_count_rejected_on_a_single_bit_reject(self):
        rec = next(r for r in _load_golden() if r["name"] == "size_below_first_bin")
        op = _op_from_record(rec)
        x = _particles_from_record(rec)
        numrecords = int(rec["op"]["numrecords"])
        d = new_accumulator(op, numrecords=numrecords)

        corrected = corrected_count_rejected(op, x, d)

        np.testing.assert_array_equal(corrected[:, :7], d.count_rejected)
        np.testing.assert_array_equal(corrected[:, 7], np.zeros(numrecords, dtype=np.int32))
        self.assertEqual(int(d.count_rejected[0, 2]), 1, "sanity: bit 4 -> column 2")


class ABConsequence(unittest.TestCase):
    """S5-q: a particle rejected on two bits (1 and 8) -- the port's
    own tally counts only the lowest-numbered column; the correction
    counts both."""

    def test_multi_bit_reject_counts_every_matching_column(self):
        rec = next(r for r in _load_golden() if r["name"] == "multi_bit_reject")
        op = _op_from_record(rec)
        x = _particles_from_record(rec)
        numrecords = int(rec["op"]["numrecords"])
        d = new_accumulator(op, numrecords=numrecords)

        corrected = corrected_count_rejected(op, x, d)

        self.assertEqual(int(d.count_rejected[0, 0]), 1, "the port's own S5-q value")
        self.assertEqual(int(d.count_rejected[0, 3]), 0)

        self.assertEqual(int(corrected[0, 0]), 1, "bit 1 -> column 0")
        self.assertEqual(int(corrected[0, 3]), 1, "bit 8 -> column 3, now also counted")

    def test_bit_128_only_reject_gets_its_own_column(self):
        """S5-a: dofreject=1 with dofflag=0 and every other criterion
        passing rejects on bit 128 alone -- the port's own tally wraps
        this into column 6 (the bit-64 column) via IDL's negative-index
        convention (ireject=[-1] -> ireject[0] == -1 == the last of 7
        columns); the correction gives it its own 8th column and
        leaves column 6 untouched."""
        op = _default_op(dofreject=1)
        x = _particle_batch(1, dofflag=np.zeros(1, dtype=np.uint8))
        d = new_accumulator(op, numrecords=1)

        corrected = corrected_count_rejected(op, x, d)

        self.assertEqual(int(d.count_rejected[0, 6]), 1,
                          "the port's own S5-a mistally: bit-64 column")
        self.assertEqual(int(corrected[0, 6]), 0, "no longer misattributed")
        self.assertEqual(int(corrected[0, 7]), 1, "bit 128 -> its own column")


class SwitchStates(unittest.TestCase):
    def test_registered_default_off_a14(self):
        self.assertIn("rejection_tally_fix", REGISTRY)
        spec = REGISTRY["rejection_tally_fix"]
        self.assertFalse(spec.default_on)
        self.assertEqual(spec.finding, "S5-a")
        self.assertEqual(spec.reachability, "live")

    def test_resolve_false_by_default_true_when_opted_in(self):
        self.assertFalse(resolve({})["rejection_tally_fix"])
        self.assertTrue(resolve({"rejection_tally_fix": True})["rejection_tally_fix"])
        self.assertFalse(resolve({"rejection_tally_fix": False})["rejection_tally_fix"])


if __name__ == "__main__":
    unittest.main()
