# SPDX-License-Identifier: BSD-3-Clause
"""The vectorised v3.5 prefix scan is bit-identical to the slice-by-slice walk.

``_scan_seam_states`` (production) reads the record headers in bulk, finds a
record's boundary rows with one array comparison and selects the TAS samples once
per record.  ``_scan_seam_states_reference`` is the literal walk that shipped
before.  The seam state is a floating-point running sum, so "close" is not a
result: every comparison here is on the float64 bit pattern (``struct.pack``),
never ``allclose``, and ``np.array_equal`` is not used because it treats a NaN
as unequal to itself.

Runs on the tracked 25-record 2DS fixture and on synthetic record files that
reach each branch of the walk.  No reference data, no Octave.
"""

from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np

try:
    import netCDF4
except ImportError:  # pragma: no cover -- the suite skips instead
    netCDF4 = None

from arrayprobe_uiops import imgproc as v35_imgproc
from arrayprobe_uiops import ncio
from arrayprobe_uiops.imgproc import (
    _RECORD_HEADER_NAMES,
    PROBES_V35,
    _scan_seam_states,
    _scan_seam_states_reference,
)
from arrayprobe_uiops.imgproc_core import ROLLBACK_SECONDS, _read_record_header

FIXTURE = Path(__file__).resolve().parent / "data" / "2DS_s3_input_fixture.nc"
PROBE = PROBES_V35["2DS"]
BOUNDARY = 43690
NROW = 1700


from pathlib import Path as _P  # noqa: E402

# _release_fixture_guard: 2DS_s3_input_fixture.nc is excluded from the release
if not (_P(__file__).resolve().parent / "data" / "2DS_s3_input_fixture.nc").exists():
    raise unittest.SkipTest(
        "2DS_s3_input_fixture.nc is not distributed with the package")


def _bits(pair):
    """``None`` or the two float64 bit patterns of a seam state."""
    return None if pair is None else struct.pack("<dd", pair[0], pair[1])


def _same(a, b) -> bool:
    return [_bits(p) for p in a] == [_bits(p) for p in b]


def _scan_both(path, stops, tas, tas_time):
    tas = np.asarray(tas, dtype=float)
    tas_time = np.asarray(tas_time, dtype=float)
    new = _scan_seam_states(path, PROBE, stops, tas, tas_time, None)
    ref = _scan_seam_states_reference(path, PROBE, stops, tas, tas_time, None)
    return new, ref


def _record_seconds(path):
    """Each record's HHMMSS lookup key, as ``_time_in_seconds_from_tas`` builds it."""
    src = ncio.open(path, "nowrite")
    try:
        keys = []
        for i in range(1, _time_len(path) + 1):
            rec = _read_record_header(src, i)
            keys.append(float(rec["hour"]) * 10000 + float(rec["minute"]) * 100
                        + float(rec["second"]))
        return keys
    finally:
        ncio.close(src)


def _time_len(path) -> int:
    with netCDF4.Dataset(str(path)) as ds:
        return len(ds.dimensions["time"])


def _varying_tas(keys, *, drop=(), nan=()):
    """One distinct, non-round speed per second of the file.

    ``drop`` leaves a second out (the ``TAS_FALLBACK`` arm) and ``nan`` makes its
    sample NaN.  Returns ``(tas_time, tas)``.
    """
    seconds = sorted(set(keys))
    times, values = [], []
    for k, sec in enumerate(seconds):
        if k in drop:
            continue
        times.append(sec)
        values.append(float("nan") if k in nan else 141.3 + 0.137 * k + 1 / (k + 7))
    return np.array(times), np.array(values)


class _CallSpy:
    """Record every ``_time_in_seconds_from_tas`` call the scan makes."""

    def __enter__(self):
        self.calls = []
        self._real = v35_imgproc._time_in_seconds_from_tas
        real = self._real

        def wrapper(part_time, ds, rec, tas, tas_time, ptp, tisp):
            self.calls.append((part_time, ptp))
            return real(part_time, ds, rec, tas, tas_time, ptp, tisp)

        v35_imgproc._time_in_seconds_from_tas = wrapper
        return self

    def __exit__(self, *exc):
        v35_imgproc._time_in_seconds_from_tas = self._real
        return False


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
class TestFixtureIsBitIdentical(unittest.TestCase):
    """The 25-record fixture the chunk-priming tests use, a stop at every record."""

    @classmethod
    def setUpClass(cls):
        cls.n = _time_len(FIXTURE)
        cls.stops = list(range(1, cls.n + 2))   # tops of records 1..n and the end
        cls.keys = _record_seconds(FIXTURE)

    def test_empty_tas_takes_the_fallback_arm(self):
        new, ref = _scan_both(FIXTURE, self.stops, [], [])
        self.assertEqual(len(new), len(self.stops))
        self.assertIsNone(new[0])
        self.assertGreater(sum(p is not None for p in new), 20)
        self.assertTrue(_same(new, ref))

    def test_a_varying_series_with_a_gap_and_a_nan(self):
        tas_time, tas = _varying_tas(self.keys, drop={1}, nan={2})
        new, ref = _scan_both(FIXTURE, self.stops, tas, tas_time)
        self.assertGreater(sum(p is not None for p in new), 20)
        self.assertTrue(_same(new, ref))
        # The series must matter, or this test would equal the empty-TAS one.
        empty, _ = _scan_both(FIXTURE, self.stops, [], [])
        self.assertFalse(_same(new, empty))

    def test_a_single_stop_matches_a_single_stop(self):
        tas_time, tas = _varying_tas(self.keys)
        for stop in (1, 2, 13, self.n, self.n + 1):
            new, ref = _scan_both(FIXTURE, [stop], tas, tas_time)
            self.assertTrue(_same(new, ref), f"stop {stop}")

    def test_the_header_bulk_read_returns_the_stored_values(self):
        src = ncio.open(FIXTURE, "nowrite")
        try:
            bulk = {name: np.ravel(ncio.get_var(src, ncio.inq_var_id(src, name), 0, self.n))
                    for name in _RECORD_HEADER_NAMES}
            for i in range(1, self.n + 1):
                per_record = _read_record_header(src, i)
                self.assertEqual(set(per_record), set(_RECORD_HEADER_NAMES))
                for name in _RECORD_HEADER_NAMES:
                    self.assertEqual(_bits((float(bulk[name][i - 1]), 0.0)),
                                     _bits((per_record[name], 0.0)), (i, name))
        finally:
            ncio.close(src)

    def test_the_comparison_sees_one_ulp(self):
        tas_time, tas = _varying_tas(self.keys)
        new, ref = _scan_both(FIXTURE, self.stops, tas, tas_time)
        self.assertTrue(_same(new, ref))
        for k in (1, len(ref) // 2, len(ref) - 1):
            for slot in (0, 1):
                bumped = list(ref)
                pair = list(bumped[k])
                pair[slot] = float(np.nextafter(pair[slot], np.inf))
                bumped[k] = tuple(pair)
                self.assertFalse(_same(new, bumped), (k, slot))


def _row(*, col0=1, time_words=(0, 0)):
    row = np.ones(8, dtype=np.int32)
    row[0] = col0
    row[6], row[7] = time_words
    return row


def _particle(data, r, clock):
    """A boundary word at row ``r`` and its header row (col 0 == boundarytime) below."""
    data[r, :] = BOUNDARY
    data[r + 1, :] = _row(col0=0, time_words=(clock >> 16, clock & 0xFFFF))


def _records():
    """One record per branch of the walk, as ``(name, rows-builder)`` pairs."""
    out = []

    def rec(name):
        def register(fn):
            out.append((name, fn))
            return fn
        return register

    @rec("ordinary: a skipped first boundary, then three particles")
    def _(d):
        d[0, :] = BOUNDARY          # j=1: start_first + 0 > 0, the skip branch
        d[1, :] = _row(col0=0)
        _particle(d, 10, 1_000_000)
        _particle(d, 20, 1_250_000)
        _particle(d, 30, 1_700_000)

    @rec("a -1 terminator mid-record hides a later boundary, and a boundary before it "
         "whose header row is the terminator fails the time test")
    def _(d):
        _particle(d, 8, 2_000_000)
        d[11, :] = BOUNDARY
        d[12, :] = -1
        _particle(d, 13, 2_050_000)     # the row just past the terminator
        _particle(d, 15, 2_100_000)

    @rec("no terminator; the last boundary the walk can see, its header on the final row")
    def _(d):
        _particle(d, 50, 3_000_000)
        _particle(d, NROW - 2, 3_100_000)   # j = 1699 < nrow: seen

    @rec("no terminator; a boundary word on the final row is never visited")
    def _(d):
        _particle(d, NROW - 3, 3_200_000)
        d[NROW - 1, :] = BOUNDARY           # j = 1700 == nrow: the walk has stopped

    @rec("a boundary word whose next row fails boundarytime, then a valid one")
    def _(d):
        d[40, :] = BOUNDARY
        d[41, :] = _row(col0=5, time_words=(9, 9))
        _particle(d, 60, 4_000_000)

    @rec("the skip branch: boundaries closer than start + offset allows, and one exactly at it")
    def _(d):
        _particle(d, 10, 5_000_000)     # j = 11, so start = 13
        _particle(d, 13, 5_050_000)     # j - 1 == start: not skipped
        for r in (15, 17):              # start = 16, then 18: both skipped
            d[r, :] = BOUNDARY
            d[r + 1, :] = _row(col0=0, time_words=(77, 77))
        _particle(d, 30, 5_200_000)

    @rec("no boundary at all")
    def _(d):
        pass

    @rec("a 32-bit clock wrap: a smaller clock than the previous particle's")
    def _(d):
        _particle(d, 10, (65535 << 16) | 65535)
        _particle(d, 20, 100)
        _particle(d, 30, 400)

    @rec("a boundary word that differs in one diode column")
    def _(d):
        d[70, :] = BOUNDARY
        d[70, 7] = BOUNDARY - 1
        d[71, :] = _row(col0=0, time_words=(5, 5))
        _particle(d, 80, 6_000_000)

    return out


def _write_synthetic(path, seconds, builders):
    """A NETCDF4 file with the fixture's variables, one record per builder."""
    with netCDF4.Dataset(str(path), "w", format="NETCDF4") as ds:
        ds.createDimension("time", None)
        ds.createDimension("ImgBlocklen", NROW)
        ds.createDimension("ImgRowlen", 8)
        dtypes = {"year": "i2", "month": "i1", "day": "i1", "hour": "i1", "minute": "i1",
                  "second": "i1", "millisec": "i2"}
        for name, dt in dtypes.items():
            ds.createVariable(name, dt, ("time",))
        data = ds.createVariable("data", "i4", ("time", "ImgBlocklen", "ImgRowlen"))
        for k, build in enumerate(builders):
            hh, mm, ss = 16, 41, seconds[k]
            for name, value in zip(dtypes, (2016, 9, 6, hh, mm, ss, 100 + k), strict=True):
                ds.variables[name][k] = value
            block = np.ones((NROW, 8), dtype=np.int32)
            build(block)
            data[k, :, :] = block


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
class TestSyntheticRecordsAreBitIdentical(unittest.TestCase):
    """Every branch of the walk, in one file, a stop at every record."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.builders = [b for _, b in _records()]
        cls.names = [n for n, _ in _records()]
        cls.seconds = [10 + k for k in range(len(cls.builders))]
        cls.path = Path(cls._tmp.name) / "synthetic.nc"
        _write_synthetic(cls.path, cls.seconds, cls.builders)
        cls.stops = list(range(1, len(cls.builders) + 2))
        cls.keys = [164100.0 + s for s in cls.seconds]

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_empty_tas(self):
        new, ref = _scan_both(self.path, self.stops, [], [])
        self.assertTrue(_same(new, ref))
        self.assertGreater(sum(p is not None for p in new), 4)

    def test_varying_tas_with_a_gap_and_a_nan(self):
        tas_time, tas = _varying_tas(self.keys, drop={3}, nan={4})
        new, ref = _scan_both(self.path, self.stops, tas, tas_time)
        self.assertTrue(_same(new, ref))

    def test_every_branch_is_reached(self):
        """Without this the file could pass vacuously; count what the scan does."""
        tas_time, tas = _varying_tas(self.keys)
        with _CallSpy() as spy:
            _scan_seam_states(self.path, PROBE, self.stops, tas, tas_time, None)
        # 3 + 1 + 2 + 1 + 1 + 3 + 0 + 3 + 1 folded particles; the skipped ones never fold.
        self.assertEqual(len(spy.calls), 15)
        self.assertIsNone(spy.calls[0][1])                       # first of the file
        self.assertEqual(sum(ptp is None for _, ptp in spy.calls), 1)
        wraps = [pt for pt, ptp in spy.calls if ptp is not None and pt - ptp < -4.2e9]
        self.assertEqual(len(wraps), 1)
        scale = PROBE.ds / 10 ** 3 / 170.0
        self.assertLess((wraps[0] - ((65535 << 16) | 65535)) * scale, ROLLBACK_SECONDS)

    def test_each_record_on_its_own(self):
        """A stop at one record at a time, so no record's state leans on another's."""
        tas_time, tas = _varying_tas(self.keys)
        for stop in self.stops:
            new, ref = _scan_both(self.path, [stop], tas, tas_time)
            self.assertTrue(_same(new, ref), f"stop {stop}")

    def test_two_tas_samples_at_one_second_raise_the_same_error(self):
        tas_time, tas = _varying_tas(self.keys)
        dup_time = np.append(tas_time, tas_time[2])
        dup_tas = np.append(tas, tas[2] + 1.0)
        messages = []
        for scan in (_scan_seam_states, _scan_seam_states_reference):
            with self.assertRaises(ValueError) as caught:
                scan(self.path, PROBE, self.stops, dup_tas, dup_time, None)
            messages.append(str(caught.exception))
        self.assertEqual(messages[0], messages[1])
        self.assertIn("matched 2 TAS samples", messages[0])

    def test_a_duplicate_second_nobody_reaches_raises_in_neither(self):
        """The record with no particle never looks its second up, in either scan."""
        no_boundary = self.names.index("no boundary at all")
        tas_time, tas = _varying_tas(self.keys)
        # the record's own second now carries two samples, but it writes no particle
        dup_time = np.append(tas_time, self.keys[no_boundary])
        dup_tas = np.append(tas, 150.0)
        stop = [no_boundary + 2]                     # scans records 1 .. no_boundary + 1
        plain_new, plain_ref = _scan_both(self.path, stop, tas, tas_time)
        dup_new, dup_ref = _scan_both(self.path, stop, dup_tas, dup_time)
        self.assertTrue(_same(plain_new, plain_ref))
        self.assertTrue(_same(dup_new, dup_ref))
        self.assertTrue(_same(dup_new, plain_new))

    def test_progress_and_stop_order_contract_is_unchanged(self):
        seen_new, seen_ref = [], []
        tas_time, tas = _varying_tas(self.keys)
        _scan_seam_states(self.path, PROBE, self.stops, tas, tas_time,
                          lambda i, n: seen_new.append((i, n)))
        _scan_seam_states_reference(self.path, PROBE, self.stops, tas, tas_time,
                                    lambda i, n: seen_ref.append((i, n)))
        self.assertEqual(seen_new, seen_ref)
        self.assertEqual(seen_new[-1][0], len(self.builders))
        with self.assertRaises(ValueError):
            _scan_seam_states(self.path, PROBE, [3, 2], tas, tas_time, None)

    def test_a_stop_past_the_end_fails_in_both(self):
        # A stop two past the end of the file. The reference scan fails on the read
        # (IndexError); the fast scan refuses first, naming the chunk plan, so a bad
        # plan is a message rather than a traceback. Neither returns a state.
        tas_time, tas = _varying_tas(self.keys)
        beyond = [len(self.builders) + 3]
        with self.assertRaisesRegex(ValueError, "past the end of the file"):
            _scan_seam_states(self.path, PROBE, beyond, tas, tas_time, None)
        with self.assertRaises(IndexError):
            _scan_seam_states_reference(self.path, PROBE, beyond, tas, tas_time, None)

    def test_the_end_state_is_still_a_legal_stop(self):
        # n + 1, the state after the last record, is what the identity checks above
        # compare; only chunk_primes_v35 (whose stops are chunk starts) refuses it.
        tas_time, tas = _varying_tas(self.keys)
        end = [len(self.builders) + 1]
        new, ref = _scan_both(self.path, end, tas, tas_time)
        self.assertTrue(_same(new, ref))
        self.assertIsNotNone(new[0])


if __name__ == "__main__":
    unittest.main()
