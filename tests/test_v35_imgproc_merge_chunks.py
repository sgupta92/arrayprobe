# SPDX-License-Identifier: BSD-3-Clause
"""Acceptance: a chunked v3.5 S3 pass equals the serial one, bit for bit.

The v3.5 counterpart of ``test_imgproc_merge_chunks.py``.  ``imgproc_sm_v35``'s
``n``/``nEvery`` already select a record range; splitting one file across
several such calls and stitching them with
:func:`arrayprobe_uiops.imgproc.merge_chunks_v35` must reproduce the
single-chunk result exactly.

**What makes this a fidelity test and not a plumbing one.**  v3.5 added a
cross-record dependency v3.1.4 does not have (``imgProc_sm.m:1110-1115``, Joe
Finlon 02/13/19): ``inter_arrival`` is differenced against
``time_in_seconds_prev``, which ``:1402``'s ``clear`` does not touch, so it
carries across record boundaries.  At a chunk seam that variable is unset and
the chunk's first particle gets ``0.0`` where the serial run wrote a real
difference.  ``merge_chunks_v35`` repairs exactly those elements, and
:class:`TestTheSeamRepairIsLoadBearing` asserts **both** states: without the
repair the files differ at precisely the seams, with it they are identical.

The **narrowed claim**, asserted rather than assumed by
:class:`TestSpecTimingIsRefusedBecauseItAccumulates`: probetype 2
(2DS/HVPS/3VCPI) is *not* chunkable.  ``:1131-1180`` accumulates
``Time_in_seconds`` over the whole file, so a chunk restarts the running sum
and every particle after a seam carries a different absolute time.  That is
different output, not the same output computed differently, and it is refused
rather than compared loosely.

Runs on tracked fixtures only -- the 12-record CIP decode
(``s6_dmt_synthetic_octave_golden.nc``,
probetype 1), the single-record 2DC and Fast2DC decodes (probetypes 0 and 3)
and the synthetic 20-record 2DS input -- so this needs no reference data and no Octave.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import netCDF4
except ImportError:  # pragma: no cover
    netCDF4 = None

import numpy as np
from tests import _run_flight_state
from tests._slow import slow

from arrayprobe import profiles
from arrayprobe_uiops.imgproc import (
    CHUNKABLE_TIMINGS_V35,
    PROBES_V35,
    ChunkingNotEquivalent,
    _repair_inter_arrival_seams,
    imgproc_sm_v35,
    merge_chunks_v35,
)
from arrayprobe_uiops.measure import STOCK_V35_REJECT_CONFIG

# ``scripts/`` is not a package; loaded by path, exactly as test_run_flight.py does.
_SPEC = importlib.util.spec_from_file_location(
    "run_flight", Path(__file__).resolve().parent.parent / "scripts" / "run_flight.py")
assert _SPEC is not None and _SPEC.loader is not None
run_flight = importlib.util.module_from_spec(_SPEC)
sys.modules["run_flight"] = run_flight
_SPEC.loader.exec_module(run_flight)

DATA = Path(__file__).resolve().parent / "data"
CIP_INPUT = DATA / "s6_dmt_synthetic_octave_golden.nc"      # 12 records, probetype 1
TWODC_INPUT = DATA / "s7c_2dc_octave_decoded.nc"  # 1 record, probetype 0
F2DC_INPUT = DATA / "s7e_f2dc_octave_decoded.nc"  # 1 record, probetype 3
SPEC_INPUT = DATA / "2DS_decoded_synthetic.nc"    # 20 records, probetype 2 (synthetic)
#: Written by ``data/make_2ds_decoded_synthetic.py`` (the port's SPEC decoder on the shipped
#: synthetic ``demo_flight_dense_raw.2DS``).

PROJECT = "ORACLES"
SOFTWARE = "UIOOPS_v3.5"
#: ``:297`` is a wall clock and ``:302`` is the input path as the caller spelled
#: it -- the same two ``test_v35_imgproc.py`` excludes, for the same reasons.
#: Every other global attribute, and every value, IS compared.
NON_COMPARABLE_ATTRS = frozenset({"Creation Time", "Image Source",
                                  "arrayprobe_engine", "arrayprobe_profile"})
FIXED_CREATION_TIME = "2000/01/01 00:00:00"


def _time_len(path: Path) -> int:
    """The ``time`` dimension: image records on an input file, particles on a
    proc file -- the same unlimited dimension in both cases."""
    with netCDF4.Dataset(str(path)) as ds:
        return len(ds.dimensions["time"])


#: Every S3 pass below is deterministic in its inputs, and the same
#: (input, probe, range) recurs across several tests -- a serial CIP run is the
#: baseline for four of them.  Without this cache the module re-ran ~260
#: record-passes and took 107 s, which is a sixth of the whole default suite
#: (589 s, 2026-09-14) for one acceptance check.  Memoised into one
#: module-scoped directory instead; the files are read-only to every caller.
_CACHE: dict[tuple, Path] = {}
_CACHE_DIR: tempfile.TemporaryDirectory | None = None


def setUpModule():  # noqa: N802 -- unittest's name
    global _CACHE_DIR
    _CACHE_DIR = tempfile.TemporaryDirectory()


def tearDownModule():  # noqa: N802 -- unittest's name
    _CACHE.clear()
    if _CACHE_DIR is not None:
        _CACHE_DIR.cleanup()


def _run(inp: Path, out: Path, probename: str, n: int, n_every: int) -> int:
    """One ordinary ``imgproc_sm_v35`` call over records ``(n-1)*n_every+1 ..``."""
    probe = PROBES_V35[probename]
    needs_tas = probe.probetype == 2
    return imgproc_sm_v35(
        str(inp), str(out), probename, n, n_every, PROJECT,
        iNewHabit=0, reject_config=STOCK_V35_REJECT_CONFIG,
        tas_time=np.array([]) if needs_tas else None,
        tas=np.array([]) if needs_tas else None,
        software=SOFTWARE, creation_time=FIXED_CREATION_TIME,
    )


def _cached_run(inp: Path, probename: str, n: int, n_every: int) -> Path:
    """:func:`_run` into the module cache, returning the file. Callers must treat
    the result as read-only -- several tests share the same file."""
    key = (str(inp), probename, n, n_every)
    if key not in _CACHE:
        out = Path(_CACHE_DIR.name) / f"{probename}_{inp.stem}_{n}_{n_every}.nc"
        _run(inp, out, probename, n, n_every)
        _CACHE[key] = out
    return _CACHE[key]


def _serial(inp: Path, probename: str) -> Path:
    """The whole-file, single-chunk run every comparison below is against."""
    return _cached_run(inp, probename, 1, _time_len(inp))


def _chunk_files(inp: Path, probename: str, n_chunks: int) -> list[Path]:
    """Split ``inp`` into ``n_chunks`` ordered record ranges, one file each.

    A chunk whose range starts past the end of the file is not created at all,
    exactly as ``stage3`` does it -- so ``n_chunks`` larger than the record
    count yields fewer files, which the callers below rely on.
    """
    n_records = _time_len(inp)
    n_every = -(-n_records // n_chunks)  # ceil division
    return [_cached_run(inp, probename, k, n_every)
            for k in range(1, n_chunks + 1)
            if (k - 1) * n_every < n_records]


def _merge(chunk_paths, out: Path, inp: Path, probename: str, **kw) -> int:
    return merge_chunks_v35(
        [str(p) for p in chunk_paths], str(out), projectname=PROJECT,
        infile=str(inp), probename=probename, iNewHabit=0, software=SOFTWARE,
        creation_time=FIXED_CREATION_TIME, **kw)


def _values(path: Path, name: str) -> np.ndarray:
    with netCDF4.Dataset(str(path)) as ds:
        return np.asarray(ds.variables[name][:])


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
class _Compare(unittest.TestCase):
    """Bit-for-bit file comparison -- ``np.array_equal``, never ``allclose``."""

    def assert_files_identical(self, path_a: Path, path_b: Path, msg_prefix: str):
        with netCDF4.Dataset(str(path_a)) as a, netCDF4.Dataset(str(path_b)) as b:
            self.assertEqual(
                list(a.variables), list(b.variables),
                f"{msg_prefix}: variable set or definition order differs")
            self.assertEqual(
                len(a.dimensions["time"]), len(b.dimensions["time"]),
                f"{msg_prefix}: particle count differs")
            for name in a.variables:
                with self.subTest(variable=name):
                    va = np.asarray(a.variables[name][:])
                    vb = np.asarray(b.variables[name][:])
                    self.assertEqual(
                        a.variables[name].dtype, b.variables[name].dtype,
                        f"{msg_prefix}/{name}: netCDF type differs")
                    # equal_nan=True: several measured quantities are NaN for
                    # e.g. an all-lit image, and NaN != NaN under plain ==,
                    # which would misreport agreement as a difference.
                    self.assertTrue(
                        np.array_equal(va.astype(np.float64), vb.astype(np.float64),
                                       equal_nan=True),
                        f"{msg_prefix}/{name}: values differ")
            for attr in a.ncattrs():
                if attr in NON_COMPARABLE_ATTRS:
                    continue
                with self.subTest(attribute=attr):
                    self.assertEqual(getattr(a, attr), getattr(b, attr),
                                     f"{msg_prefix}/@{attr}: global attribute differs")


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
class TestCipChunkedEqualsSerial(_Compare):
    """Probetype 1, the engine the CIP flight runs on. This must never differ."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.n_records = _time_len(CIP_INPUT)
        self.serial = _serial(CIP_INPUT, "CIP")
        self.assertGreater(_time_len(self.serial), 0,
                           "fixture must produce at least one particle")

    def _merged(self, n_chunks: int, probename: str = "CIP") -> Path:
        paths = _chunk_files(CIP_INPUT, probename, n_chunks)
        merged = self.tmp / f"merged_{probename}_{n_chunks}.nc"
        _merge(paths, merged, CIP_INPUT, probename)
        return merged

    def test_two_chunks_match_single_chunk(self):
        self.assert_files_identical(self.serial, self._merged(2), "CIP 2 chunks")

    def test_five_uneven_chunks_match_single_chunk(self):
        # 12 records / 5 -> n_every 3, so only FOUR chunk files exist and the
        # fifth range starts past the end: the tail case stage3 also hits.
        self.assert_files_identical(self.serial, self._merged(5), "CIP 5 uneven chunks")

    def test_one_chunk_per_record_matches_single_chunk(self):
        # The extreme case: as many chunks as records, maximising the number of
        # seams the inter_arrival repair has to get right.
        self.assert_files_identical(
            self.serial, self._merged(self.n_records), "CIP one chunk per record")

    def test_pip_shares_the_branch_and_matches_too(self):
        # PIP is the other probetype-1 probe; same timing branch, different ds.
        self.assert_files_identical(
            _serial(CIP_INPUT, "PIP"), self._merged(4, "PIP"), "PIP 4 chunks")

    def test_every_variable_matches_at_the_raw_byte_level(self):
        """Stronger than :meth:`assert_files_identical`'s value comparison: the
        stored bytes themselves, with masking and scaling **off** and no float64
        cast, so a differing NaN payload or fill region would show up too.

        Kept alongside the value comparison rather than replacing it, because
        that one carries ``equal_nan=True`` and so states the weaker claim the
        v3.1.4 test states; this states the strongest one the format allows.
        **What it deliberately does not claim:** that the two *files* are
        identical byte strings. They are not, and cannot be -- ``:289`` creates
        NETCDF4, and an HDF5 container records allocation and B-tree metadata
        that depends on the order the writes arrived in (measured on the real
        950-record CIP file: 782,400 of 19,713,909 container bytes differ while
        all 40 variables' raw bytes match exactly). The product is the data and
        the attributes, and those are what must be equal.
        """
        merged = self._merged(4)
        with netCDF4.Dataset(str(self.serial)) as a, netCDF4.Dataset(str(merged)) as b:
            a.set_auto_maskandscale(False)
            b.set_auto_maskandscale(False)
            self.assertEqual(len(a.variables), len(b.variables))
            for name in a.variables:
                with self.subTest(variable=name):
                    va = np.asarray(a.variables[name][:])
                    vb = np.asarray(b.variables[name][:])
                    self.assertEqual(va.dtype, vb.dtype, f"{name}: dtype")
                    self.assertEqual(va.shape, vb.shape, f"{name}: shape")
                    self.assertEqual(va.tobytes(), vb.tobytes(),
                                     f"{name}: stored bytes differ")


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
class TestTheSeamRepairIsLoadBearing(_Compare):
    """Both states: the repair must be doing something, and the right something.

    A merge that happened to agree because the fixture has no cross-seam
    inter-arrival would prove nothing, so this asserts the *unrepaired*
    concatenation differs first -- at precisely the chunk-start indices and
    nowhere else -- and then that the repair closes exactly that gap.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.serial = _serial(CIP_INPUT, "CIP")
        self.paths = _chunk_files(CIP_INPUT, "CIP", 4)
        self.counts = [_time_len(p) for p in self.paths]

    def test_unrepaired_concatenation_differs_at_the_seams_and_only_there(self):
        serial_ia = _values(self.serial, "inter_arrival").reshape(-1)
        raw = np.concatenate([_values(p, "inter_arrival").reshape(-1) for p in self.paths])
        self.assertEqual(raw.size, serial_ia.size)

        seams = np.cumsum(self.counts)[:-1]          # first row of chunks 2..N
        differing = set(np.flatnonzero(raw != serial_ia).tolist())
        self.assertEqual(
            differing, set(seams.tolist()),
            "the unrepaired seams must be exactly the chunk-start particles: "
            "if this set is empty the fixture exercises nothing, and if it is "
            "larger then something other than inter_arrival crosses a seam")
        for i in seams:
            self.assertEqual(raw[i], 0.0, "an unrepaired seam is :1110-1114's `None` branch")
            self.assertNotEqual(serial_ia[i], 0.0,
                                "the serial run wrote a real inter-arrival there")

    def test_the_repair_restores_the_identical_bytes(self):
        # Not "close to": the repair re-performs :1114's own float64 subtraction
        # on the same two operands, so the bytes must match exactly.
        merged = self.tmp / "merged.nc"
        _merge(self.paths, merged, CIP_INPUT, "CIP")
        serial_ia = _values(self.serial, "inter_arrival").reshape(-1)
        merged_ia = _values(merged, "inter_arrival").reshape(-1)
        self.assertEqual(serial_ia.dtype, np.float64)
        self.assertEqual(serial_ia.tobytes(), merged_ia.tobytes(),
                         "inter_arrival is not byte-identical after the seam repair")
        self.assert_files_identical(self.serial, merged, "CIP 4 chunks, repaired")

    def test_an_empty_chunk_is_stepped_over_not_treated_as_a_seam(self):
        """A chunk that wrote nothing leaves ``time_in_seconds_prev`` at the last
        particle of the previous non-empty chunk, so the next real particle's
        difference must reach back past it."""
        arrays = [
            {"Time_in_seconds": np.array([[1.0], [2.0]]),
             "inter_arrival": np.array([[0.0], [1.0]])},
            {"Time_in_seconds": np.zeros((0, 1)),
             "inter_arrival": np.zeros((0, 1))},
            {"Time_in_seconds": np.array([[5.0]]),
             "inter_arrival": np.array([[0.0]])},
        ]
        _repair_inter_arrival_seams(arrays, [2, 0, 1])
        self.assertEqual(float(arrays[2]["inter_arrival"].reshape(-1)[0]), 3.0,
                         "5.0 - 2.0: the empty chunk must not become the previous value")
        self.assertEqual(float(arrays[0]["inter_arrival"].reshape(-1)[0]), 0.0,
                         "the very first particle of the file keeps :1110's zero")


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
class TestRecordLocalProbetypesNeedNoRepair(_Compare):
    """Probetypes 0 and 3 read no ``time_in_seconds_prev`` at all, so concatenation
    alone is exact -- including across chunks that wrote nothing."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def _case(self, inp: Path, probename: str, n_extra_empty: int):
        """The file's one record as chunk 1, plus ``n_extra_empty`` chunks whose
        record range lies past the end of the file.

        A chunk that wrote nothing leaves ``bin_stats`` at the netCDF fill value
        rather than 0 -- ``:1394`` is only reached by a record that found a
        particle -- so summing it in unconditionally would corrupt the merge.
        That is the path this exercises, and it is reachable on a real flight by
        any record range that happens to hold no particle.
        """
        paths = [_cached_run(inp, probename, k, 1) for k in range(1, 2 + n_extra_empty)]
        self.assertEqual([_time_len(p) for p in paths[1:]], [0] * n_extra_empty,
                         "the extra chunks must really be empty")
        merged = self.tmp / f"{probename}_merged.nc"
        _merge(paths, merged, inp, probename)
        self.assert_files_identical(_serial(inp, probename), merged,
                                    f"{probename} + {n_extra_empty} empty chunks")

    def test_2dc_probetype_0(self):
        self._case(TWODC_INPUT, "2DC", 2)

    def test_2dp_probetype_0(self):
        # The 2DC decode read as a 2DP: the same probetype-0 record layout and timing
        # branch, with the 2DP's own resolution, so the one probe with no fixture of its
        # own is still run chunked against serial.
        self._case(TWODC_INPUT, "2DP", 2)

    def test_fast2dc_probetype_3(self):
        self._case(F2DC_INPUT, "Fast2DC", 1)


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
class TestSpecTimingIsRefusedBecauseItAccumulates(_Compare):
    """The narrowed claim, established by measurement rather than asserted.

    ``:1131-1180`` builds ``Time_in_seconds`` as a running sum from the first
    particle of the file, so a chunked probetype-2 run is *different output*.
    The refusal is therefore correct, and this proves the divergence is real
    rather than defending a limitation nobody checked.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_spec_is_not_in_the_chunkable_set(self):
        self.assertNotIn("spec", CHUNKABLE_TIMINGS_V35)
        for probename in ("2DS", "HVPS", "3VCPI_H", "3VCPI_V"):
            with self.subTest(probe=probename):
                self.assertEqual(PROBES_V35[probename].timing, "spec")
        for probename in ("CIP", "PIP", "2DC", "2DP", "Fast2DC"):
            with self.subTest(probe=probename):
                self.assertIn(PROBES_V35[probename].timing, CHUNKABLE_TIMINGS_V35)

    def test_merge_refuses_a_spec_probe_naming_the_accumulating_line(self):
        with self.assertRaises(ChunkingNotEquivalent) as cm:
            _merge([self.tmp / "unused.nc"], self.tmp / "out.nc", SPEC_INPUT, "2DS")
        self.assertIn("1131-1180", str(cm.exception))

    def test_a_chunked_spec_run_really_does_diverge(self):
        serial = _serial(SPEC_INPUT, "2DS")
        written = _time_len(serial)
        paths = _chunk_files(SPEC_INPUT, "2DS", 3)
        counts = [_time_len(p) for p in paths]
        self.assertEqual(sum(counts), written, "the split must lose no particle")

        serial_t = _values(serial, "Time_in_seconds").reshape(-1)
        raw_t = np.concatenate([_values(p, "Time_in_seconds").reshape(-1) for p in paths])
        differing = int(np.sum(raw_t != serial_t))
        # Every particle after the first seam, not a rounding-level handful --
        # which is why no post-hoc repair can restore the bytes.
        self.assertEqual(differing, written - counts[0])
        self.assertGreater(differing, 0)


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
class TestMergeRefusals(_Compare):
    """The merge's own argument checks."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_rejects_empty_input(self):
        with self.assertRaises(ValueError):
            _merge([], self.tmp / "out.nc", CIP_INPUT, "CIP")

    def test_rejects_an_unknown_probe(self):
        with self.assertRaises(ValueError):
            _merge([self.tmp / "a.nc"], self.tmp / "out.nc", CIP_INPUT, "NOSUCH")

    def test_stopped_at_out_of_range_is_refused(self):
        paths = _chunk_files(CIP_INPUT, "CIP", 2)
        with self.assertRaises(ValueError):
            _merge(paths, self.tmp / "out.nc", CIP_INPUT, "CIP", stopped_at=9)

    def test_stopped_at_drops_the_chunks_matlab_would_never_have_written(self):
        """``:850-853`` exits the whole function, so a chunked run's later
        workers computed records MATLAB never reaches."""
        paths = _chunk_files(CIP_INPUT, "CIP", 4)
        truncated = self.tmp / "truncated.nc"
        kept = _merge(paths, truncated, CIP_INPUT, "CIP", stopped_at=2)
        expected = sum(_time_len(p) for p in paths[:2])
        self.assertEqual(kept, expected)
        self.assertEqual(_time_len(truncated), expected)
        # And it equals the merge of just those two chunks, with no trace of
        # the dropped ones.
        head = self.tmp / "head.nc"
        _merge(paths[:2], head, CIP_INPUT, "CIP")
        self.assert_files_identical(head, truncated, "stopped_at=2")


@slow  # real subprocess chunk workers under engine 3.5 (measured 2026-09-17: ~8 s)
@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
class TestChunkedStage3UnderEngine35(_Compare):
    """The claim through the code path the CIP run actually takes.

    The v3.5 counterpart of ``test_run_flight_chunk_watchdog.py``'s
    ``ChunkedStage3ByteIdentityTests``, and the strongest form of the
    byte-identity claim here: real ``--_run-chunk`` subprocesses, the real
    ``engine=3.5`` token, the real ``.done`` handshake, the real
    :func:`merge_chunks_v35` -- not a lower-level stand-in for any of them.
    This
    change moves no written byte, and that is a test, not a sentence.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        _run_flight_state.preserve(self, run_flight)
        run_flight.ENGINE = "3.5"
        run_flight.PROBE = "CIP"
        run_flight.PROJECT = PROJECT
        run_flight.PROFILE = profiles.ORACLES_PRODUCTION_V35
        run_flight.PROFILE_MODULE = ""
        run_flight.TAS_FILE = None
        run_flight.JIT = False
        real_log = run_flight.log
        run_flight.log = lambda *a, **kw: None
        self.addCleanup(setattr, run_flight, "log", real_log)
        # stage3 names its output after the input, so the fixture is copied under
        # a `.cdf` name in a scratch directory rather than processed in place.
        self.image = self.tmp / "s1.CIP.cdf"
        self.image.write_bytes(CIP_INPUT.read_bytes())

    def _chunked_vs_serial(self, stray_pixel):
        run_flight.STRAY_PIXEL = stray_pixel
        tag = "on" if stray_pixel else "off"
        serial_dir = self.tmp / f"serial_{tag}"
        chunked_dir = self.tmp / f"chunked_{tag}"
        serial_dir.mkdir()
        chunked_dir.mkdir()
        serial = run_flight.stage3(self.image, serial_dir, chunks=1, worker_stall_min=5.0)
        chunked = run_flight.stage3(self.image, chunked_dir, chunks=3, worker_stall_min=5.0)
        self.assertGreater(_time_len(serial), 0, "the fixture must produce particles")
        self.assert_files_identical(serial, chunked,
                                    f"stage3 engine=3.5 stray_pixel={tag}, 3 chunks")
        with netCDF4.Dataset(chunked) as ds:
            self.assertEqual("image_stray_pixels_removed" in ds.variables, stray_pixel)

    def test_chunked_equals_serial_with_the_stray_pixel_correction_on(self):
        """The engine-3.5 default since 2026-10-03: merge_chunks_v35 must carry
        image_stray_pixels_removed / image_diam_minR_uncorrected, which it once dropped."""
        self._chunked_vs_serial(True)

    def test_chunked_equals_serial_with_the_stray_pixel_correction_off(self):
        self._chunked_vs_serial(False)

    def test_chunked_stage3_is_byte_identical_to_a_single_chunk(self):
        run_flight.STRAY_PIXEL = True
        serial_dir = self.tmp / "serial"
        chunked_dir = self.tmp / "chunked"
        serial_dir.mkdir()
        chunked_dir.mkdir()
        serial = run_flight.stage3(self.image, serial_dir, chunks=1, worker_stall_min=5.0)
        chunked = run_flight.stage3(self.image, chunked_dir, chunks=3, worker_stall_min=5.0)
        self.assertGreater(_time_len(serial), 0, "the fixture must produce particles")
        self.assert_files_identical(serial, chunked, "stage3 engine=3.5, 3 chunks")

    def test_a_probetype_2_probe_is_no_longer_refused_because_stage3_primes_it(self):
        """**This test asserted the opposite until 2026-09-19, and was wrong from the
        moment chunk priming landed on 2026-09-18.**

        It used to assert that ``stage3`` raises ``ChunkingNotEquivalent`` on a
        probetype-2 probe, on the reasoning that the gate sits in
        ``merge_chunks_v35`` as well as in ``main()``.  Chunk priming made that gate
        *conditional*: ``stage3`` now computes ``chunk_primes_v35`` first and
        passes ``primed=True``, so the refusal correctly does not fire and the run
        proceeds -- and this test then died further downstream with
        ``FileNotFoundError: ... 'None'`` (no TAS file), which is not a refusal at
        all.  It went unnoticed because the class is ``@slow``-gated and so runs
        only under ``ARRAYPROBE_SLOW=1``; the 2026-09-19 gate run surfaced it.

        **The refusal itself is not lost and is not retested here.**
        ``test_v35_sizedist_chunk_priming.py``'s
        ``test_merge_refuses_every_probetype_2_probe_by_name_when_unprimed`` covers
        it better, over all four probetype-2 names, at the engine boundary where the
        gate actually lives.  What belongs *here* is the driver-level contract that
        replaced it.

        Asserted by which error arrives, not by "does not raise": a test that only
        checked ``ChunkingNotEquivalent`` was absent would pass if the refusal moved
        one line later.  This fixture has no TAS sidecar, so a run that genuinely
        gets past the gate must fail on the missing aircraft series instead.
        """
        run_flight.PROBE = "2DS"
        image = self.tmp / "s1.H.cdf"
        image.write_bytes(SPEC_INPUT.read_bytes())
        out = self.tmp / "spec"
        out.mkdir()
        with self.assertRaises(Exception) as caught:
            run_flight.stage3(image, out, chunks=2, worker_stall_min=5.0)
        self.assertNotIsInstance(
            caught.exception, ChunkingNotEquivalent,
            "stage3 refused to chunk a probetype-2 probe; since 2026-09-18 it primes the "
            "seam state instead, so a refusal here means the priming path is gone")
        # **The accepted type widened on 2026-09-21, and the assertion got stronger, not
        # weaker.** This used to require FileNotFoundError/OSError, which was a proxy for "it
        # died on the missing aircraft series". Since `_TAS_VARIANTS` landed, an input with no
        # recognised true-airspeed pair raises `KeyError` carrying the names it tried and a
        # refusal to guess a new one -- a better error for a user and the same event for this
        # test. So the contract is now asserted directly, by what the message says, rather than
        # by an exception class that happened to correlate with it.
        self.assertIsInstance(caught.exception, (FileNotFoundError, OSError, KeyError))
        self.assertRegex(
            str(caught.exception), r"(?i)no such file|cannot find|true-?airspeed|TAS",
            "stage3 got past the chunking gate and then failed for some reason OTHER than the "
            "missing aircraft series, so this fixture is no longer testing what it says: "
            f"{caught.exception!r}")


class TestTheChunkWorkerCarriesTheEngine(unittest.TestCase):
    """``--_run-chunk`` is a fresh subprocess that re-imports ``run_flight`` and so
    starts at ``ENGINE``'s import-time default ``"3.1.4"``.

    Unreachable until 2026-09-17, because ``--chunks`` was refused under
    engine 3.5 outright; wiring the two together makes it live, and an
    unthreaded ``ENGINE`` would have had v3.5 chunk workers writing **v3.1.4
    output** into a merge stamped ``engine=3.5``.  Both ends are asserted: the
    token ``stage3`` builds, and the branch that consumes it.
    """

    def setUp(self):
        self.run_flight = run_flight
        _run_flight_state.preserve(self, run_flight)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def _stub_chunk(self, record=None):
        """Replace ``_imgproc_sm_chunk`` for the duration of one test, optionally
        recording the ``ENGINE`` in force when the worker actually dispatches --
        which is the moment that decides which engine writes the chunk."""
        real = run_flight._imgproc_sm_chunk

        def stub(*_args, **_kw):
            if record is not None:
                record.setdefault("engine", run_flight.ENGINE)
            return 0

        run_flight._imgproc_sm_chunk = stub
        self.addCleanup(setattr, run_flight, "_imgproc_sm_chunk", real)

    def test_the_run_chunk_branch_sets_engine_from_the_trailing_token(self):
        run_flight.ENGINE = "3.1.4"
        seen: dict[str, str] = {}
        self._stub_chunk(seen)
        rc = run_flight.main(
            ["--_run-chunk", "img.cdf", "CIP", "ORACLES", "oracles-production",
             "", "", "0", str(self.tmp / "out.chunk1"), "1", "500", "engine=3.5"])
        self.assertEqual(rc, 0)
        self.assertEqual(seen.get("engine"), "3.5",
                         "the chunk worker dispatched under the parent's engine, not the default")

    def test_an_engine_314_parent_sends_its_own_value(self):
        """The token is always sent, so the worker is never left guessing -- and a
        stale value in this process must be overwritten by it, not merged with."""
        run_flight.ENGINE = "3.5"          # the stale value the token must overwrite
        self._stub_chunk()
        run_flight.main(
            ["--_run-chunk", "img.cdf", "CIP", "ORACLES", "oracles-production",
             "", "", "0", str(self.tmp / "out.chunk2"), "1", "500", "engine=3.1.4"])
        self.assertEqual(run_flight.ENGINE, "3.1.4")

    def test_jit_and_engine_tokens_are_order_independent(self):
        self._stub_chunk()
        for tail in (["jit", "engine=3.5"], ["engine=3.5", "jit"]):
            with self.subTest(tail=tail):
                run_flight.ENGINE, run_flight.JIT = "3.1.4", False
                run_flight.main(
                    ["--_run-chunk", "img.cdf", "CIP", "ORACLES", "oracles-production",
                     "", "", "0", str(self.tmp / "out.chunk3"), "1", "500", *tail])
                self.assertEqual(run_flight.ENGINE, "3.5")
                self.assertTrue(run_flight.JIT)

    def test_stage3_builds_the_token_from_the_live_engine(self):
        """The other end: what ``stage3`` actually puts on a worker's command line.
        Intercepted at ``subprocess.Popen`` so no worker is spawned."""
        import subprocess  # noqa: PLC0415 -- only this test patches it

        seen_cmds = []

        class _FakePopen:
            def __init__(self, cmd, **_kw):
                seen_cmds.append(cmd)

            def poll(self):
                return 0

            returncode = 0

        real_popen = subprocess.Popen
        subprocess.Popen = _FakePopen
        self.addCleanup(setattr, subprocess, "Popen", real_popen)
        run_flight.ENGINE = "3.5"
        run_flight.PROBE = "CIP"
        try:
            # It will fail later (the fake workers write no chunk files); all this
            # test needs is the command stage3 built before that.
            run_flight.stage3(CIP_INPUT, self.tmp, chunks=2, worker_stall_min=0)
        except Exception:  # noqa: BLE001 -- the failure after the spawn is not the subject
            pass
        self.assertTrue(seen_cmds, "stage3 spawned no chunk worker")
        for cmd in seen_cmds:
            self.assertIn("engine=3.5", cmd,
                          "stage3 must tell the worker which engine to run")

if __name__ == "__main__":
    unittest.main()
