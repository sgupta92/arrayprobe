# SPDX-License-Identifier: BSD-3-Clause
"""``soda2_particlesort`` on exactly one particle: the GDL golden, and the port's divergence.

Golden: ``tests/data/soda2_particlesort_one_particle_gdl_golden.json``, written by
``gdl_oracle/run_soda2_particlesort_one_particle_bank.py`` (FO) from a direct call
to the **unmodified** vendored ``soda2_particlesort.pro`` under GDL -- no copy, no shim.
What it measured:

* one particle, ``basestruct`` verbatim -> halts at ``SODA2_PARTICLESORT:12``
  (``MEDIAN: Expression must be an array``: GDL collapses a one-element struct field);
* the same call with the three time tags declared ``dblarr(1)`` (an input-shape variant,
  so ``:12`` passes) -> halts at ``:13``, ``Subscript out of range [s:*]``;
* ``:13``'s bare expression on a DOUBLE ``Array[1]`` -> the same message;
* the two-particle twin -> runs, and the port matches it exactly.

**The port does not reproduce the halt** (``particlesort.py`` evaluates ``:12`` but never
``:13`` for SPEC, because ``:28`` overrides ``truetime``): on one particle it returns.
That divergence is pinned here in both directions rather than fixed -- the port is not
changed by an evidence lane -- ``ThePortDoesNotHalt`` is an ``expectedFailure`` that
becomes an unexpected success (a suite failure) the day the port is made to halt, so the
documentation cannot silently go stale; ``TheHaltCheckHasPower`` shows the same check
passes on a port mutant that does halt.
"""
from __future__ import annotations

import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from arrayprobe_soda2 import particlesort
from arrayprobe_soda2.particlesort import (
    ParticlesortOptions,
    new_accumulator,
    soda2_particlesort,
)

GOLDEN = (Path(__file__).resolve().parent / "data"
          / "soda2_particlesort_one_particle_gdl_golden.json")
_DOUBLE_TAGS = ("buffertime", "probetime", "reftime", "inttime")
_BYTE_TAGS = ("overloadflag", "allin", "centerin", "dofflag")


def _records() -> dict[str, dict]:
    return {r["name"]: r for r in json.loads(GOLDEN.read_text(encoding="utf-8"))[1:]}


def _op(rec: dict) -> ParticlesortOptions:
    op = rec["op"]
    return ParticlesortOptions(
        starttime=op["starttime"], rate=op["rate"], clusterthresh=op["clusterthresh"],
        inttime_reject=op["inttime_reject"], smethod=op["smethod"],
        apply_psc=op["apply_psc"], apply_psc_sizelimit=op["apply_psc_sizelimit"],
        water=op["water"], endbins=np.array(op["endbins"]),
        arendbins=np.array(op["arendbins"]), eawmethod=op["eawmethod"], res=op["res"],
        dofreject=op["dofreject"], format="SPEC", probetype=op["probetype"])


def _particles(rec: dict) -> dict[str, np.ndarray]:
    ps = rec["particles"]
    out = {}
    for k in ps[0]:
        vals = [p[k] for p in ps]
        dtype = (np.float64 if k in _DOUBLE_TAGS else np.uint8 if k in _BYTE_TAGS
                 else np.float32)
        out[k] = np.array(vals, dtype=dtype)
    return out


def _nz(spec: str, shape: tuple[int, ...]) -> np.ndarray:
    arr = np.zeros(shape)
    idx, _, val = spec.partition(";")
    if idx.strip() == "-1":
        return arr
    arr[np.unravel_index([int(v) for v in idx.split(",")], shape, order="F")] = [
        float(v) for v in val.split(",")]
    return arr


def twin_mismatches(rec: dict, module=particlesort) -> list[str]:
    """Run ``module``'s port on an OK record and name every field that differs from GDL."""
    op = _op(rec)
    n = int(rec["op"]["numrecords"])
    d = module.new_accumulator(op, numrecords=n)
    rf = module.soda2_particlesort(op, _particles(rec), d)
    bad = []
    if rf.tolist() != rec["RF"]:
        bad.append("RF")
    if d.count_accepted.tolist() != [int(v) for v in rec["COUNT_ACCEPTED"].split(",")]:
        bad.append("count_accepted")
    rej = np.array([int(v) for v in rec["COUNT_REJECTED"].split(",")]).reshape((n, 7), order="F")
    if not np.array_equal(d.count_rejected, rej):
        bad.append("count_rejected")
    for key, arr in (("SPEC2D_NZ", d.spec2d), ("INTSPEC_ALL_NZ", d.intspec_all),
                     ("INTSPEC_ACC_NZ", d.intspec_accepted), ("HIST3D_NZ", d.hist3d)):
        if not np.array_equal(arr, _nz(rec[key], arr.shape)):
            bad.append(key)
    return bad


def halts_on_one_particle(module=particlesort) -> bool:
    """True when ``module``'s port raises on the golden's one-particle input, as GDL halts."""
    rec = _records()["one_particle"]
    op = _op(rec)
    d = module.new_accumulator(op, numrecords=int(rec["op"]["numrecords"]))
    try:
        module.soda2_particlesort(op, _particles(rec), d)
    except IndexError:
        return True
    return False


def mutant(old: str, new: str):
    """``arrayprobe_soda2.particlesort`` with one source substring replaced, as a sibling module."""
    path = Path(particlesort.__file__)
    src = path.read_text(encoding="utf-8")
    assert src.count(old) == 1, f"mutation anchor occurs {src.count(old)} times: {old!r}"
    mod = types.ModuleType("arrayprobe_soda2._particlesort_one_particle_mutant")
    mod.__package__ = "arrayprobe_soda2"
    mod.__file__ = str(path)
    with mock.patch.dict(sys.modules, {mod.__name__: mod}):
        exec(compile(src.replace(old, new), str(path), "exec"), mod.__dict__)
    return mod


#: The behaviour-matching change the porting report named ("raise on numparticles == 1 at that
#: point"), applied to a mutant only. The anchor is the port's own ``:12`` line.
_HALT_ANCHOR = "    _ = idl_median(buffertime - reftime)\n"
_HALT_MUTATION = _HALT_ANCHOR + (
    "    if numparticles == 1:\n"
    "        raise IndexError('soda2_particlesort.pro:13 -- Subscript out of range [s:*]')\n")


@unittest.skipUnless(GOLDEN.is_file(), "One-particle GDL golden is not distributed with the "
                                       "package")
class TheGoldenPinsTheHalt(unittest.TestCase):
    def test_line_12_halts_the_unmodified_routine_on_one_particle_under_gdl(self):
        r = _records()["one_particle"]
        self.assertEqual((r["kind"], r["status"]), ("unmodified_routine", "HALTED"))
        self.assertEqual((r["halt_routine"], r["halt_line"]), ("SODA2_PARTICLESORT", 12))
        self.assertIn("MEDIAN: Expression must be an array", r["error"])
        self.assertEqual(len(r["particles"]), 1)

    def test_line_13_halts_the_unmodified_routine_once_line_12_is_passed(self):
        r = _records()["one_particle_array1_tags"]
        self.assertEqual(r["kind"], "unmodified_routine_input_shape_variant")
        self.assertEqual((r["status"], r["halt_routine"], r["halt_line"]),
                         ("HALTED", "SODA2_PARTICLESORT", 13))
        self.assertIn("Subscript out of range [s:*]", r["error"])

    def test_line_13_expression_alone_halts_on_a_one_element_double(self):
        r = _records()["bare_line13_expression"]
        self.assertEqual((r["kind"], r["status"]), ("bare_expression", "HALTED"))
        self.assertIn("Subscript out of range [s:*]", r["error"])

    def test_the_two_particle_twin_runs(self):
        r = _records()["two_particle_twin"]
        self.assertEqual((r["kind"], r["status"], r["RF"]), ("unmodified_routine", "OK", [0, 0]))
        self.assertEqual(r["COUNT_ACCEPTED"].split(",")[0], "2")
        # Same particle as the one-particle case, plus one: the count is the only cause.
        self.assertEqual(r["particles"][0], _records()["one_particle"]["particles"][0])


@unittest.skipUnless(GOLDEN.is_file(), "One-particle GDL golden is not distributed with the "
                                       "package")
class TheTwinAgrees(unittest.TestCase):
    def test_the_port_matches_gdl_on_the_two_particle_twin(self):
        self.assertEqual(twin_mismatches(_records()["two_particle_twin"]), [])


@unittest.skipUnless(GOLDEN.is_file(), "One-particle GDL golden is not distributed with the "
                                       "package")
class ThePortDoesNotHalt(unittest.TestCase):
    @unittest.expectedFailure
    def test_port_halts_on_one_particle_as_line_13_does(self):
        """Documented divergence: GDL halts, the
        port returns. An unexpected success here means the port was changed to halt --
        update the design note and remove this marker."""
        self.assertTrue(halts_on_one_particle())

    def test_port_returns_one_accepted_particle_where_gdl_halts(self):
        rec = _records()["one_particle"]
        op = _op(rec)
        d = new_accumulator(op, numrecords=int(rec["op"]["numrecords"]))
        rf = soda2_particlesort(op, _particles(rec), d)
        self.assertEqual((rf.tolist(), d.count_accepted.tolist()), ([0], [1, 0, 0, 0]))


@unittest.skipUnless(GOLDEN.is_file(), "One-particle GDL golden is not distributed with the "
                                       "package")
class TheHaltCheckHasPower(unittest.TestCase):
    def test_a_port_mutant_that_halts_passes_the_halt_check_and_still_matches_the_twin(self):
        m = mutant(_HALT_ANCHOR, _HALT_MUTATION)
        self.assertTrue(halts_on_one_particle(m))
        self.assertEqual(twin_mismatches(_records()["two_particle_twin"], m), [])

    def test_a_mutated_golden_fails_the_twin_comparison(self):
        rec = dict(_records()["two_particle_twin"])
        rec["COUNT_ACCEPTED"] = "1,0,0,0"
        rec["SPEC2D_NZ"] = "24;1"
        self.assertEqual(twin_mismatches(rec), ["count_accepted", "SPEC2D_NZ"])

    def test_a_port_mutant_that_drops_a_particle_fails_the_twin_comparison(self):
        m = mutant("    numparticles = probetime.size\n",
                   "    numparticles = probetime.size\n"
                   "    x = {k: v[:1] for k, v in x.items()}\n"
                   "    probetime, buffertime = probetime[:1], buffertime[:1]\n"
                   "    reftime, overloadflag = reftime[:1], overloadflag[:1]\n"
                   "    numparticles = 1\n")
        self.assertNotEqual(twin_mismatches(_records()["two_particle_twin"], m), [])


if __name__ == "__main__":
    unittest.main()
