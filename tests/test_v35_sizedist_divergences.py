# SPDX-License-Identifier: BSD-3-Clause
"""GL7's stock-only ``sizeDist.m`` behaviours, re-asked of the v3.5 engine under Octave.

**What this closes (V35).** GL7 fixed seven stock-v3.1.4 ``sizeDist.m``
behaviours on the v3.1.4 port's ``tree="stock"`` path and flagged, read but not run, two
that ``arrayprobe_uiops.sizedist`` might share. ``octave_oracle/run_v35_divergence_bank.py``
ran the **unmodified** v3.5 ``sizeDist.m`` on GL7's fixtures; the goldens are tracked
(``tests/data/v35_div_*``). Result per behaviour:

========== ============================================ =======================================
case       v3.5 site                                    before the check -> now
========== ============================================ =======================================
tasgap     ``:918`` ``while`` with no ``jjj`` bound      completed (fork's bound) -> raises, as
                                                         Octave dies: ``starttime(3): out of
                                                         bound 2``
nantas     ``:1959-1971`` NaN TAS -> last valid, else    NaN sample volume -> filled
           100 m/s
fractime   ``:914``/``:918`` ``int32()`` comparisons     ``int()`` truncated -> MATLAB rounding
midnight   ``:806-810`` flight-day carryover             already matched (44 variables exact)
iamissing  ``:1179-1181`` open of a missing file         already raised ``FileNotFoundError``
iatwo      ``:105-107``/``:1179`` two varargin -> skip   already matched
iafile     type-1 control (one varargin)                 already matched -- the first end-to-end
                                                         v3.5 type-1 golden
tasskip    ``:918``, the ``tasgap`` control              already matched
========== ============================================ =======================================

``clamp`` (``:1950-1953``) and ``pt1abs`` (``:757``) are probetype-1 cases that this bank
does not run -- they need a CIP/PIP proc fixture the bank does not have -- and are an open
follow-up, not a refusal (probetype 1 has been admitted by this engine since 2026-09-17;
probetypes 0 and 3 were added 2026-09-23; see ``test_v35_sizedist_probetype03.py``).

Comparison is **exact**: every variable, ``array_equal`` with NaN equal, with
``octave_colon=True`` (the bin ladder's documented Octave/MATLAB colon difference). Each fix
carries two mutants, and each already-matching case at least one, so every golden is shown
to discriminate.
"""

from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from netCDF4 import Dataset

from arrayprobe.matlab_compat import MatlabIndexError
from arrayprobe_uiops import sizedist as v35s

DATA = Path(__file__).resolve().parent / "data"
SRC = Path(v35s.__file__)
ERRORS = DATA / "v35_div_errors_octave_golden.json"
# seeded synthetic procs, tests/data/make_stock_div_synthetic.py
BASE = DATA / "v35_div_synthetic_base_proc.nc"
MIDNIGHT = DATA / "v35_div_synthetic_midnight_proc.nc"
REACCEPT_PROC = DATA / "reacceptance_proc.nc"
REACCEPT_THRESH = DATA / "reacceptance_threshold.cdf"
_MISSING = str(Path(tempfile.gettempdir()) / "v35_div_threshold_MISSING_nowhere.cdf")
_REACCEPT_T = [60642, 60643, 60644, 60645, 60646]
_2DS = "20151205 164129"
_REACCEPT_START = "20180124 005009"

#: The bank's inputs, restated rather than imported: the goldens came from Octave and these
#: must reproduce the call that made them.
#: (proc, timehhmmss, tas, pres, temp, probe, project, ddate, iaThreshType, varargin)
CALLS = {
    "nantas": (BASE, [164129, 164130, 164131], [np.nan, 95.0, np.nan], [9e5] * 3, [15.0] * 3,
               "2DS", "TEST", _2DS, 0, ()),
    "midnight": (MIDNIGHT, [235959, 0, 1], [95.0] * 3, [9e5] * 3, [15.0] * 3,
                 "2DS", "TEST", _2DS, 0, ()),
    "tasgap": (BASE, [164129, 164135], [95.0] * 2, [9e5] * 2, [15.0] * 2,
               "2DS", "TEST", _2DS, 0, ()),
    "tasskip": (BASE, [164128, 164130], [95.0] * 2, [9e5] * 2, [15.0] * 2,
                "2DS", "TEST", _2DS, 0, ()),
    "fractime": (BASE, [164128.5, 164129.4, 164129.6], [95.0] * 3, [9e5] * 3, [15.0] * 3,
                 "2DS", "TEST", _2DS, 0, ()),
    "iamissing": (REACCEPT_PROC, _REACCEPT_T, [95.0] * 5, [70000.0] * 5, [-10.0] * 5,
                  "2DS", "SOCRATES", _REACCEPT_START, 1, (_MISSING,)),
    "iatwo": (REACCEPT_PROC, _REACCEPT_T, [95.0] * 5, [70000.0] * 5, [-10.0] * 5,
              "2DS", "SOCRATES", _REACCEPT_START, 1, (str(REACCEPT_THRESH), "EXTRA")),
    "iafile": (REACCEPT_PROC, _REACCEPT_T, [95.0] * 5, [70000.0] * 5, [-10.0] * 5,
               "2DS", "SOCRATES", _REACCEPT_START, 1, (str(REACCEPT_THRESH),)),
}
DIED = ("iamissing", "tasgap")
COMPLETED = sorted(set(CALLS) - set(DIED))


def golden(case):
    return DATA / f"v35_div_{case}_octave_golden.nc"


_HAVE = (BASE.is_file() and MIDNIGHT.is_file() and REACCEPT_PROC.is_file() and ERRORS.is_file()
         and all(golden(c).is_file() for c in COMPLETED))


def run(case, outfile, module=v35s):
    proc, t, tas, pres, temp, probe, project, ddate, ia_type, varargin = CALLS[case]
    with mock.patch.object(module._logger, "warning"):
        module.run(str(proc), str(outfile), np.array(tas, float), np.array(t, float), probe,
                   6, 0, np.array(pres, float), np.array(temp, float), ia_type, 0, 1, 1,
                   project, ddate, *varargin, software="UIOOPS_v3.5",
                   creation_time="2026/09/15 00:00:00", octave_colon=True,
                   # Octave's mean() sums with compensation, MATLAB's does not; the goldens
                   # are Octave's, so compare against Octave's accumulator here (production
                   # keeps MATLAB's). Seconds with ~50 particles differ in the last bit of ar.
                   octave_mean_extra=True)


def differing(port, gold):
    """Names of variables that are not exactly equal (NaN == NaN), plus a set mismatch."""
    bad = []
    with Dataset(port) as a, Dataset(gold) as b:
        if set(a.variables) != set(b.variables):
            bad.append("<variable set>")
        for name in sorted(set(a.variables) & set(b.variables)):
            x = np.asarray(a.variables[name][:], float)
            y = np.asarray(b.variables[name][:], float)
            if x.shape != y.shape or not np.array_equal(x, y, equal_nan=True):
                bad.append(name)
    return bad


def binned(path):
    with Dataset(path) as d:
        return float(np.nansum(np.asarray(d.variables["count"][:], float)))


def mutant(old, new):
    """``arrayprobe_uiops.sizedist`` with one source substring replaced, as a sibling module.

    Fails closed: the anchor must occur exactly once.
    """
    src = SRC.read_text(encoding="utf-8")
    assert src.count(old) == 1, f"mutation anchor occurs {src.count(old)} times: {old!r}"
    mod = types.ModuleType("arrayprobe_uiops._sizedist_v35_div_mutant")
    mod.__package__ = "arrayprobe_uiops"
    mod.__file__ = str(SRC)
    with mock.patch.dict(sys.modules, {mod.__name__: mod}):
        exec(compile(src.replace(old, new), str(SRC), "exec"), mod.__dict__)
    return mod


class _Tmp(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.out = Path(self._dir.name) / "sd.nc"

    def assert_broken(self, case, module):
        """The mutant must make this case's exact comparison fail -- or raise where it did not."""
        try:
            run(case, self.out, module=module)
        except (MatlabIndexError, FileNotFoundError):
            return
        self.assertNotEqual(differing(self.out, golden(case)), [],
                            f"mutant left {case} matching its golden")


@unittest.skipUnless(_HAVE, "v3.5 divergence Octave reference fixtures are not distributed with "
                            "the package")
class EveryCaseMatchesTheV35Octave(_Tmp):
    def test_every_case_that_completes_matches_its_golden_exactly(self):
        for case in COMPLETED:
            with self.subTest(case=case):
                run(case, self.out)
                self.assertEqual(differing(self.out, golden(case)), [])
                with Dataset(golden(case)) as g:
                    self.assertEqual(len(g.variables), 44)

    def test_the_port_dies_where_octave_died(self):
        errors = json.loads(ERRORS.read_text())
        self.assertEqual(sorted(errors), list(DIED))
        self.assertTrue(all(e["status"] == "ERROR" for e in errors.values()))
        # :918's unbounded while -- the index Octave named.
        self.assertIn("starttime(3): out of bound 2", errors["tasgap"]["message"])
        with self.assertRaisesRegex(MatlabIndexError, r":918 reads starttime\(3\).*2 particle"):
            run("tasgap", self.out)
        # :1181's netcdf.open on the name :100 kept without an existence test.
        self.assertIn("No such file", errors["iamissing"]["message"])
        with self.assertRaises(FileNotFoundError):
            run("iamissing", self.out)


@unittest.skipUnless(_HAVE, "v3.5 divergence Octave reference fixtures are not distributed with "
                            "the package")
class TheGoldensSayWhatTheyShould(unittest.TestCase):
    def test_nantas_fills_100_then_the_last_valid_tas(self):
        with Dataset(golden("nantas")) as d:
            sv = np.asarray(d.variables["sample_vol"][:], float)
        sv = np.moveaxis(sv, sv.shape.index(3), 0)
        self.assertTrue(np.isfinite(sv).all())
        # second 1 at 100 m/s (no earlier valid TAS), second 3 at 95 m/s (the last valid).
        np.testing.assert_allclose(sv[0] / sv[2], 100.0 / 95.0, rtol=1e-12)

    def test_two_varargin_skip_the_type1_block_that_one_varargin_runs(self):
        # :105-107 sets iaThreshFile = 'NONE' and :1179 needs length(varargin) == 1.
        self.assertEqual(binned(golden("iatwo")), 6.0)
        self.assertEqual(binned(golden("iafile")), 1.0)

    def test_midnight_places_particles(self):
        self.assertGreater(binned(golden("midnight")), 0.0)


@unittest.skipUnless(_HAVE, "v3.5 divergence Octave reference fixtures are not distributed with "
                            "the package")
class TheTestsFailOnTheMutants(_Tmp):
    """Guards must be executed, not read: two mutants per fix, one per already-matching case."""

    def test_tasgap_bound_restored_no_longer_dies(self):
        on = "            while t_int32 > int(mint32(starttime[jjj - 1])):\n"
        m = mutant(on, on.replace("):\n", ") and jjj < n_blocks:\n"))
        with self.assertRaises(AssertionError):
            with self.assertRaises(MatlabIndexError):
                run("tasgap", self.out, module=m)

    def test_tasgap_raise_one_block_early_breaks_the_control(self):
        self.assert_broken("tasskip", mutant("                if jjj > n_blocks:\n",
                                             "                if jjj >= n_blocks:\n"))

    def test_nantas_fill_removed(self):
        self.assert_broken("nantas", mutant(
            "    for k in np.flatnonzero(np.isnan(tas)):\n",
            "    for k in np.flatnonzero(np.isnan(tas))[:0]:\n"))

    def test_nantas_always_100(self):
        self.assert_broken("nantas", mutant(
            "        tas[k] = prev[-1] if prev.size else 100.0\n",
            "        tas[k] = 100.0\n"))

    def test_fractime_truncation(self):
        self.assert_broken("fractime", mutant(
            "        t_int32 = int(mint32(timehhmmss[i]))\n",
            "        t_int32 = int(timehhmmss[i])\n"))

    def test_fractime_round_half_to_even(self):
        self.assert_broken("fractime", mutant(
            "        t_int32 = int(mint32(timehhmmss[i]))\n",
            "        t_int32 = int(np.round(timehhmmss[i]))\n"))

    def test_midnight_carryover_removed(self):
        self.assert_broken("midnight", mutant(
            "    image_time_hhmmssall = apply_flight_day_carryover("
            "image_time_hhmmssall, timehhmmss)\n",
            "    pass\n"))

    def test_iatwo_second_varargin_honoured(self):
        # The port's gate on 'NONE' is what skips :1179's block for two varargin.
        self.assert_broken("iatwo", mutant(
            'if not (cfg.applyIntArrThresh and spec.ia_thresh_file not in (None, "NONE")):',
            "if not (cfg.applyIntArrThresh):"))


if __name__ == "__main__":
    unittest.main()
