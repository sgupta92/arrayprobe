# SPDX-License-Identifier: BSD-3-Clause
"""``count`` is invertible to raw per-bin particle counts.

**What the row asked.** Σ of the 1-Hz binned ``count`` against accepted particle
images: *"invert ``count = dist_minR·binwidth/10``, state the identity or the
non-identity"*. The scaling has to be undone before the two sides can even be
compared, and the inversion was the blocking unknown.

**The identity, established here.** It is not merely invertible -- it is an
exact algebraic round trip, and no inversion is needed at all. ``sizedist.py``
divides at ``:1645``::

    store["dist_minR"][i, :] = b.dist_minR / binwidth * 10

and multiplies the same two factors back at ``:1501``::

    out["count"] = (store["dist_minR"] * binwidth[None, :] / 10).T

so the written variable *is* ``b.dist_minR``, the integer count of particles
that reached binning in that second. The 1-Hz ``count`` needs no scaling
applied to it by a consumer, which is the opposite of what the queue row
assumed and the reason it is worth pinning: a reader who "inverts" it once more
divides every count by its own bin width.

**Why a test rather than a note.** The round trip survives only while both
sites keep the same two factors. Either one changing alone -- a bin-width
convention, a cm/mm factor -- turns every count into a plausible non-integer
that nothing else would flag, because the concentrations derived beside it stay
self-consistent. Integrality is the property that fails loudly, so that is what
is asserted.

**The non-identity is documented, not asserted.** Σ ``count`` does NOT equal the
number of particles ``imgProc_sm`` accepted; on a real flight it is about a
sixth of it, size-dependently. That measurement needs a multi-GB decoded flight
and is not part of this test.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import netCDF4
import numpy as np
from netCDF4 import Dataset
from tests._repo import needs_v314_engine

from arrayprobe._v314_lazy import lazy_module
from arrayprobe.count_closure import CAUSES, NOT_AVAILABLE, count_closure

sizedist = lazy_module("arrayprobe.sizedist")

PROC = Path(__file__).resolve().parent / "data" / "s4_aspectratio_proc.nc"


def _seconds() -> np.ndarray:
    with Dataset(str(PROC)) as d:
        return np.unique(np.floor(np.asarray(d.variables["Time"][:], float)))


@unittest.skipUnless(PROC.is_file(), "The tracked proc fixture is not distributed with the "
                                     "package; the test needs files that are not part of this "
                                     "release")
@needs_v314_engine
class CountIsAnExactRoundTrip(unittest.TestCase):
    """Run the real stage, then read its own output back."""

    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.TemporaryDirectory()
        out = Path(cls._dir.name) / "sd.nc"
        secs = _seconds()
        sizedist.run(
            str(PROC), str(out), np.full(secs.size, 95.0), secs, "2DS", 6, 0,
            np.full(secs.size, 9e5), np.full(secs.size, 15.0),
            "TEST", "20151205 164129", "NONE",
            tree="stock", ia_thresh_type=0, create_aspect_ratio=True,
            create_bad=True, save_int_arr_sv=True,
            creation_time="2026/01/01 00:00:00")
        with Dataset(str(out)) as d:
            cls.count = np.asarray(d.variables["count"][:], float)
            cls.binwidth = (np.asarray(d.variables["bin_max"][:], float)
                            - np.asarray(d.variables["bin_min"][:], float))

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    def test_every_written_count_is_a_whole_number_of_particles(self):
        """The round trip's observable consequence.

        Float64 carries the divide-then-multiply exactly for counts this size,
        so the tolerance is ULP-scale rather than a fudge factor: a real
        convention change moves a count by a factor of its bin width -- 0.01 to
        1.0 -- not by 1e-9.
        """
        finite = self.count[np.isfinite(self.count)]
        self.assertGreater(finite.size, 0, "the fixture wrote no finite counts")
        self.assertLess(float(np.max(np.abs(finite - np.round(finite)))), 1e-6,
                        "count is no longer a whole particle count -- the "
                        "binwidth/10 division at sizedist.py:1645 and the "
                        "multiplication at :1501 have stopped cancelling")

    def test_counts_are_never_negative(self):
        finite = self.count[np.isfinite(self.count)]
        self.assertGreaterEqual(float(finite.min()), 0.0)

    def test_dividing_count_by_binwidth_is_what_a_consumer_must_not_do(self):
        """The failure mode this file exists to prevent, stated as a test.

        ``count`` is already raw counts, so applying the documented scaling a
        second time yields non-integers. Asserting that it *does* is what keeps
        the docstring above honest: if a future change made the second division
        harmless, the module docstring's advice would be wrong and this
        test would say so.
        """
        finite_rows = np.isfinite(self.count).any(axis=1)
        scaled = self.count[finite_rows] * self.binwidth[None, :] / 10
        scaled = scaled[np.isfinite(scaled) & (scaled > 0)]
        self.assertTrue(
            np.any(np.abs(scaled - np.round(scaled)) > 1e-6),
            "scaling count a second time left it integral, so the variable is "
            "not the raw per-bin count this file documents it to be")


# --------------------------------------------------------------------------
# Where the other 85 % of the accepted particles go -- the open half,
# measured 2026-09-10 on `base170831075525.H` (12,428,061 particles) and pinned
# here.
# --------------------------------------------------------------------------
#
# A proc-side census could bound that gap but not reach it: every measurement
# made read the *proc* file's stored fields, and the two terms that dominate are
# written by `sizeDist` itself, into a local `auto_reject` that no file ever
# carries.  Both were therefore invisible to a proc-side census, which is why
# four candidates that between them explained under 4 % looked like the whole
# field.
#
# The census at the good/bad split (`sizedist.py:1372`), over 1,500 seconds of
# that flight, centre-in particles only:
#
#     '0'  accepted   397,978   53.15 %
#     'S'  shattering 267,303   35.70 %     :1297-1335
#     'z'  area ratio  83,532   11.16 %     :1227, ORACLES threshold 0.5
#
# Both are strongly size-selective, which is what the per-bin table
# said the real cause had to be: the accepted share falls
# from 63 % in the first bin to 0 % above 405 um, and above ~100 um it is 'S'
# that removes almost everything.  The proc-side inter-arrival test the doc
# tried measured only the particles a threshold flags *directly* (0.5 %); the
# ladder at :1297-1335 marks the neighbour as well, once per event.
#
# What is asserted here is the accounting, not the percentages -- a fixture of
# 99 particles cannot pin a flight's rates, and a test that tried would be
# pinning noise.  The identity below is what makes the attribution complete:
# after the reject codes, centre-in, the one-second window and the bin range,
# there is nothing else left to find.  A new filter anywhere in the per-second
# path breaks it.


def _instrumented_run(tmpdir, **kw):
    """Run the real stage, recording the per-second accounting as it goes.

    ``_process_population`` is wrapped rather than the port edited, so the run
    is the ordinary one.  ``auto_reject`` is read from the calling frame: it is
    a local of the block the split runs in, reaching no argument list and no
    file, and the alternative -- patching ``numpy.isin``, which the split calls
    -- mutates numpy for every other test in the process.
    """
    import sys as _sys

    rows, census = [], Counter()
    original = sizedist._process_population

    def wrapped(i, mask, entirein, image_time, one_sec_times, kk, num_bins,
                binwidth, *rest, **kwargs):
        store = rest[11]
        out = original(i, mask, entirein, image_time, one_sec_times, kk,
                       num_bins, binwidth, *rest, **kwargs)
        caller = _sys._getframe(1).f_locals
        auto_reject, centerin = caller.get("auto_reject"), caller.get("centerin")
        if auto_reject is not None and centerin is not None:
            # strict=True: `np.unique` returns the values and their counts
            # as one pair of identically shaped arrays, by construction.
            for code, n in zip(*np.unique(auto_reject[centerin == 1],
                                          return_counts=True), strict=True):
                census[chr(int(code))] += int(n)
        diameter = rest[0][mask]
        times = image_time[mask]
        in_window = ((times >= one_sec_times[i])
                     & (times < one_sec_times[i + 1]))
        in_range = (diameter >= kk[0]) & (diameter < kk[-1])
        rows.append((int(np.count_nonzero(in_window & in_range)),
                     float(np.nansum(store["dist_minR"][i, :] * binwidth / 10))))
        return out

    secs = _seconds()
    varargin = kw.pop("varargin", ())
    sizedist._process_population = wrapped
    try:
        sizedist.run(
            str(PROC), str(Path(tmpdir) / "sd.nc"), np.full(secs.size, 95.0),
            secs, "2DS", 6, 0, np.full(secs.size, 9e5),
            np.full(secs.size, 15.0), "TEST", "20151205 164129", *varargin,
            creation_time="2026/01/01 00:00:00", **kw)
    finally:
        sizedist._process_population = original
    return rows, census


ORACLES_CALL = dict(tree="production",
                    varargin=("2DS_intArrThreshold_MISSING.cdf",))


@unittest.skipUnless(PROC.is_file(), "The tracked proc fixture is not distributed with the "
                                     "package; the test needs files that are not part of this "
                                     "release")
@needs_v314_engine
class NothingElseRemovesAParticle(unittest.TestCase):
    """``count`` is exactly the reject codes, centre-in, the window, the range.

    Asserted per second and under both calls, because the two reach binning
    through different gates: the ORACLES production call applies the shattering
    block, ``ia_thresh_type=0`` skips it entirely.
    """

    def _assert_identity(self, **kw):
        with tempfile.TemporaryDirectory() as tmp:
            rows, census = _instrumented_run(tmp, **kw)
        self.assertTrue(rows, "the fixture drove no seconds")
        for expected, written in rows:
            self.assertEqual(float(expected), written)
        return census

    def test_the_oracles_production_call_accounts_for_every_particle(self):
        self._assert_identity(**ORACLES_CALL)

    def test_the_stock_call_without_shattering_accounts_for_every_particle(self):
        self._assert_identity(tree="stock", ia_thresh_type=0,
                              create_aspect_ratio=True, create_bad=True)


@unittest.skipUnless(PROC.is_file(), "The tracked proc fixture is not distributed with the "
                                     "package; the test needs files that are not part of this "
                                     "release")
@needs_v314_engine
class TheGapIsWrittenInsideSizeDist(unittest.TestCase):
    """The two dominant terms are ``sizeDist``'s own, not the proc file's.

    This is what four proc-side measurements failed
    to reach.  The fixture holds 99 centre-in particles, so what is asserted is
    that both terms *are* those sizeDist-side codes and that they dominate --
    never their rates, which are a property of the flight.
    """

    def test_shattering_and_area_ratio_take_most_of_the_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            _rows, census = _instrumented_run(tmp, **ORACLES_CALL)
        total = sum(census.values())
        self.assertGreater(total, 0)
        self.assertGreater(
            census["S"] + census["z"], total // 2,
            f"the two sizeDist-side codes no longer dominate: {dict(census)}")
        self.assertGreater(census["S"], 0, "the shattering block wrote no 'S'")
        self.assertGreater(census["z"], 0, "the area-ratio test wrote no 'z'")

    def test_skipping_the_shattering_block_removes_the_S_term(self):
        """The other half of the same claim: 'S' comes from that block alone.

        Without it the fixture keeps far more particles -- the same difference
        between the two calls, ~58 % more accepted
        particles, seen here as the code simply never being written.
        """
        with tempfile.TemporaryDirectory() as tmp:
            _rows, census = _instrumented_run(tmp, tree="stock",
                                              ia_thresh_type=0)
        self.assertEqual(census["S"], 0)
        self.assertGreater(census["0"], 0)


# --------------------------------------------------------------------------
# The closure itself: binned counts against the particles the proc file holds,
# per second, with every excluded particle attributed to a named cause.
# --------------------------------------------------------------------------

DATA = os.path.join(os.path.dirname(__file__), "data")


def _pair(tag):
    return (os.path.join(DATA, f"demo_flight_{tag}_sd.nc"),
            os.path.join(DATA, f"demo_flight_{tag}_proc.nc"))


class TestCountClosureOnFixtures(unittest.TestCase):
    # Measured on the tracked demo flights.  Each fixture holds five
    # one-particle seconds 60640..60644 in the proc file and a four-second TAS
    # axis 60640..60643 in the sd file.  Closure is exact per second once every
    # excluded particle is attributed:
    #   v35:  binned 4 = accepted 4; particle 5 is past the TAS axis.
    #   v314: binned 0 = accepted 0; particles 1-4 are shattered (int_arr 0 and
    #         5.9e-8 s <= 6e-6, sizedist.py:1217/1221), particle 5 past the axis.
    EXPECTED = {
        "v35": (4.0, 4, 5, [(5, "outside-tas-axis")]),
        "v314": (0.0, 0, 5, [(1, "shattered-interarrival"), (2, "shattered-interarrival"),
                             (3, "shattered-interarrival"), (4, "shattered-interarrival"),
                             (5, "outside-tas-axis")]),
    }

    def test_closure_is_exact_with_every_exclusion_attributed(self):
        for tag, (binned, acc, tot, causes) in self.EXPECTED.items():
            with self.subTest(tag=tag):
                r = count_closure(*_pair(tag))
                self.assertEqual(r["total_binned"], binned)
                self.assertEqual(r["total_accepted"], acc)
                self.assertEqual(r["total_in_proc"], tot)
                self.assertEqual(r["residual"], 0.0)
                np.testing.assert_array_equal(r["residual_per_second"], 0.0)
                self.assertEqual([(e["parent_rec_num"], e["cause"]) for e in r["excluded"]],
                                 causes)
                for e in r["excluded"]:
                    self.assertIn(e["cause"], CAUSES)
                self.assertEqual(len(r["excluded"]) + acc, tot)

    def test_shattering_threshold_read_from_the_stamp(self):
        self.assertEqual(count_closure(*_pair("v314"))["shattering_threshold"], 6e-6)
        self.assertIsNone(count_closure(*_pair("v35"))["shattering_threshold"])

    def test_probe_total_is_not_available(self):
        r = count_closure(*_pair("v35"))
        self.assertIsNone(r["probe_reported"])
        self.assertEqual(r["probe_reported_note"], NOT_AVAILABLE)

    def test_must_fire_tampered_counts(self):
        sd, proc = _pair("v35")
        base = count_closure(sd, proc)
        tmp = tempfile.mkdtemp()
        try:
            bad = os.path.join(tmp, "sd.nc")
            shutil.copy(sd, bad)
            with netCDF4.Dataset(bad, "r+") as ds:
                c = ds["count"][:]
                c = np.ma.filled(c, 0.0)
                c[0, 0] += 7.0
                ds["count"][:] = c
            r = count_closure(bad, proc)
        finally:
            shutil.rmtree(tmp)
        self.assertEqual(r["total_binned"], base["total_binned"] + 7.0)
        self.assertEqual(r["residual"], 7.0)
        self.assertEqual(r["residual_per_second"][0], 7.0)
        self.assertNotEqual(r["residual"], base["residual"])


class TheProductsTheDriverWritesAreRead(unittest.TestCase):
    """Edge inputs a driver-written product reaches (fold code review, 2026-10-28)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_the_driver_named_sidecar_is_found(self):
        # The driver writes ``<file>.nc.call``; only ``<stem>.call`` was looked for, so every
        # shattering-applied product raised FileNotFoundError.
        sd, proc = _pair("v314")
        target = self.tmp / "sd.base160101000000.H.nc"
        shutil.copy(sd, target)
        shutil.copy(os.path.splitext(sd)[0] + ".call", str(target) + ".call")
        self.assertEqual(count_closure(target, proc)["shattering_threshold"], 6e-6)

    def test_an_sd_not_built_center_in_is_refused(self):
        sd, proc = _pair("v35")
        target = self.tmp / "sd.nc"
        shutil.copy(sd, target)
        with netCDF4.Dataset(target, "r+") as ds:
            ds.setncattr("SA Method", "Entire-in")
        with self.assertRaises(NotImplementedError):
            count_closure(target, proc)

    def test_a_zero_second_sd_puts_every_particle_off_the_axis(self):
        _, proc = _pair("v35")
        target = self.tmp / "sd.nc"
        with netCDF4.Dataset(target, "w") as ds:
            ds.createDimension("Time", None)
            ds.createDimension("bins", 2)
            ds.createVariable("count", "f8", ("Time", "bins"))
            ds.createVariable("time", "f8", ("Time",))
            ds.createVariable("bin_min", "f8", ("bins",))[:] = [0.0, 0.1]
            ds.createVariable("bin_max", "f8", ("bins",))[:] = [0.1, 0.2]
            ds.setncattr("Shattering Algorithm", "Not applied")
        r = count_closure(target, proc)
        self.assertEqual((r["total_binned"], r["total_accepted"], r["residual"]), (0.0, 0, 0.0))
        self.assertEqual({e["cause"] for e in r["excluded"]}, {"outside-tas-axis"})
        self.assertEqual(len(r["excluded"]), r["total_in_proc"])

    def test_a_fill_valued_parent_rec_num_is_none(self):
        sd, proc = _pair("v35")
        target = self.tmp / "proc.nc"
        shutil.copy(proc, target)
        with netCDF4.Dataset(target, "r+") as ds:
            v = ds["parent_rec_num"]
            v[4] = netCDF4.default_fillvals[v.dtype.str[1:]]  # particle 5, past the TAS axis
        r = count_closure(sd, target)
        self.assertEqual([(e["parent_rec_num"], e["cause"]) for e in r["excluded"]],
                         [(None, "outside-tas-axis")])


class MaskedIntegerVariablesAreReadable(unittest.TestCase):
    """A masked int16/int32 particle variable (a netCDF fill value) widens to float, not a crash."""

    def test_masked_int16_fills_with_nan(self):
        from arrayprobe.count_closure import _var

        class _V:
            def __getitem__(self, _):
                return np.ma.masked_array(np.array([1, 2, 3], dtype=np.int16),
                                          mask=[False, True, False])

        class _DS:
            variables = {"image_auto_reject": _V()}

        got = _var(_DS(), "image_auto_reject")
        self.assertEqual(got.dtype, np.float64)
        self.assertTrue(np.isnan(got[1]))
        self.assertEqual(list(got[[0, 2]]), [1.0, 3.0])


if __name__ == "__main__":
    unittest.main()
