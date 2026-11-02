# SPDX-License-Identifier: BSD-3-Clause
"""A chunk worker *is* primed, so probetype 2 is chunkable.

**Status, 2026-09-18.**  This module began as the feasibility proof, written
before any production line existed: it did the priming itself by substituting
``_time_in_seconds_from_tas``, because ``imgproc_sm_v35`` had no ``prime=``
parameter to give it to.  The parameter landed the same day, together with
:func:`~arrayprobe_uiops.imgproc.prefix_scan_v35`,
:func:`~arrayprobe_uiops.imgproc.chunk_primes_v35`,
:data:`~arrayprobe_uiops.imgproc.PRIMABLE_TIMINGS_V35` and
``merge_chunks_v35(primed=True)``, and this module now exercises the real API.
What it proves is unchanged; what it proves it *about* is now the shipped path.
The driver half -- ``run_flight.py --chunks`` computing the pairs and shipping
them to its workers -- has its own subprocess test, because an in-process test
cannot see an argv round-trip.


**The citation this file corrects first.**  ``SPEED.md``'s refusal row
names ``sizeDist.m:1131-1180``
as what makes a chunked v3.5 pass differ on 2D-S/HVPS/3VCPI.  It is
``imgProc_sm.m:1131-1180`` -- stage **3**, not stage 4.  The port's own refusal
says so in both places it is written (``arrayprobe_uiops.imgproc``'s
``CHUNKABLE_TIMINGS_V35`` docstring and ``merge_chunks_v35``'s
``ChunkingNotEquivalent`` message), and the vendored source settles it:
``UIOPS-v3.5/joefinlon-UIOPS-039be82/imgProc_sm.m:1131-1180`` is Joe Finlon's
2017-03-03 TAS accumulation, while ``sizeDist.m:1131-1180`` is the
area-ratio/terminal-velocity block and accumulates nothing.  The module name
this file carries is the one the task named; the mechanism it tests is
``arrayprobe_uiops.imgproc``'s.

**What crosses a chunk seam on ``"spec"`` timing -- the complete list.**
Read off ``_process_records`` (``src/arrayprobe_uiops/imgproc.py:960-1080``)
against ``imgProc_sm.m:1117-1185``, and then *measured* by the tests below:

* ``part_time_prev``  (``:1178``) -- the previous particle's raw clock count,
  ``data(header_loc-1, 7)*2^16 + data(header_loc-1, 8)`` (``:1123``).
* ``time_in_seconds_prev``  (``:1180``) -- the previous particle's accumulated
  float64 time.

and nothing else.  Everything else the seam touches is already handled or is
provably record-local:

* ``kk`` resets to 1 at ``:1402`` for every record that wrote, so
  ``int_arrival = t - time_in_seconds(kk-1)`` (``:1172-1176``) is **within a
  record**.  The first particle of a record gets ``0.0`` in a serial run too.
  This is the one real difference from ``"dmt"`` timing, whose ``:1110-1114``
  carries ``time_in_seconds_prev`` into ``int_arrival`` and therefore needs
  ``merge_chunks_v35``'s seam repair.
* ``w``/``wstart`` are chunk-local write indices; ``bin_stats``/``diode_stats``
  accumulate per file.  Concatenation and summation merge both exactly --
  ``merge_chunks_v35`` already does this for the three chunkable timings.
* ``parent_rec_num`` and ``tasRatio`` are indexed by the **absolute** record
  number in both runs (V20).

**Why priming is exact, where post-hoc repair is not.**  The refusal's own
reasoning is right about repair and wrong about priming.  Adding an offset to a
chunk's already-computed times re-rounds every element, because float64
addition is not associative -- that is why ``merge_chunks_v35`` refuses to
patch this up afterwards.  Priming does not re-round anything: it hands the
worker the two scalars the serial run held at that instant, and the worker then
performs the *identical* sequence of IEEE-754 operations on the identical
operands.  A left-fold resumed from its own exact partial value is the same
fold.

**And the priming values are reachable without processing.**  The accumulation
reads only the record header (``:1132``, for the TAS lookup key), the boundary
scan that locates each particle (``:751-779``), and ``part_time`` from the
particle's own header words (``:1123``).  It never reads a measured quantity --
not ``measure_record``, not ``holroyd``, not the reject pass, which is where
the run's time goes.  :func:`~arrayprobe_uiops.imgproc.prefix_scan_v35` is that
scan alone, and ``TestPrefixScanReachesTheSeamState`` asserts it lands on the
serial run's own float64 bit pattern.  So the old refusal's "it cannot be
primed without having already processed every earlier record" was too strong by
one word: every earlier record must be **scanned**, not processed.

Runs on the tracked 25-record 2DS fixture -- no reference data, no Octave.
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
from arrayprobe_uiops.imgproc import (
    CHUNKABLE_TIMINGS_V35,
    PRIMABLE_TIMINGS_V35,
    PROBES_V35,
    ChunkingNotEquivalent,
    chunk_primes_v35,
    imgproc_sm_v35,
    merge_chunks_v35,
    prefix_scan_v35,
)
from arrayprobe_uiops.measure import STOCK_V35_REJECT_CONFIG

DATA = Path(__file__).resolve().parent / "data"
SPEC_INPUT = DATA / "2DS_s3_input_fixture.nc"     # 25 records, probetype 2
PROBE = "2DS"
PROJECT = "ORACLES"
SOFTWARE = "UIOOPS_v3.5"
FIXED_CREATION_TIME = "2000/01/01 00:00:00"
N_CHUNKS = 3

#: ``:297`` is a wall clock; ``:302`` is the input path as the caller spelled it.
NON_COMPARABLE_ATTRS = frozenset({"Creation Time", "Image Source",
                                  "arrayprobe_engine", "arrayprobe_profile"})


from pathlib import Path as _P  # noqa: E402

# _release_fixture_guard: 2DS_s3_input_fixture.nc is excluded from the release
if not (_P(__file__).resolve().parent / "data" / "2DS_s3_input_fixture.nc").exists():
    raise unittest.SkipTest(
        "2DS_s3_input_fixture.nc is not distributed with the package")


def _time_len(path: Path) -> int:
    with netCDF4.Dataset(str(path)) as ds:
        return len(ds.dimensions["time"])


def _run(inp: Path, out: Path, n: int, n_every: int, prime=None) -> int:
    """One ordinary ``imgproc_sm_v35`` call over records ``(n-1)*n_every+1 ..``.

    ``tas``/``tas_time`` are empty, so every particle takes the ``isempty(tas2d)``
    arm and ``TAS_FALLBACK`` (170) -- which still exercises the accumulation in
    full: the fold is ``time_in_seconds_prev + (part_time - part_time_prev)*scale``
    either way, and only ``scale`` differs between the arms.
    """
    return imgproc_sm_v35(
        str(inp), str(out), PROBE, n, n_every, PROJECT,
        iNewHabit=0, reject_config=STOCK_V35_REJECT_CONFIG,
        tas_time=np.array([]), tas=np.array([]),
        software=SOFTWARE, creation_time=FIXED_CREATION_TIME,
        prime=prime,
    )


def _scan(stop_record: int):
    """:func:`prefix_scan_v35` against the same empty TAS series ``_run`` uses.

    The series must match the run's: the accumulation's ``scale`` comes from the
    TAS lookup, so a scan against a different one primes the chunk with a number
    no serial run ever held.  That is why the production signature requires it.
    """
    return prefix_scan_v35(SPEC_INPUT, PROBE, stop_record,
                           tas_time=np.array([]), tas=np.array([]))


class _FirstParticleBranchSpy:
    """Count how often ``imgProc_sm.m:1136``'s first-particle branch fires.

    ``_time_in_seconds_from_tas`` receives ``part_time_prev is None`` exactly
    when ``exist('part_time_prev','var')`` is false -- the branch that restarts
    the accumulation at ``part_time * scale`` (``:763-765``).  In a whole-file
    run it fires once, at the file's first particle.  In a **primed** chunk it
    must fire **zero** times: that is what ``prime=`` is for, and counting it is
    how this module proves the parameter is actually consumed rather than
    accepted and dropped.

    Until 2026-09-18 this class did the priming itself, by substitution, because
    no ``prime=`` parameter existed; the proof came before the production line.
    It now observes the real one.
    """

    def __init__(self):
        self.restarts = 0
        self._real = None

    def __enter__(self):
        self._real = v35_imgproc._time_in_seconds_from_tas
        real = self._real

        def wrapper(part_time, ds, rec, tas, tas_time, ptp, tisp):
            if ptp is None:
                self.restarts += 1
            return real(part_time, ds, rec, tas, tas_time, ptp, tisp)

        v35_imgproc._time_in_seconds_from_tas = wrapper
        return self

    def __exit__(self, *exc):
        v35_imgproc._time_in_seconds_from_tas = self._real
        return False


def _seam_state_from(path: Path, first_record: int):
    """The ``(part_time_prev, time_in_seconds_prev)`` a finished run leaves at
    the top of ``first_record``, read off its own output.

    ``part_micro`` **is** ``part_time`` for probetype 2 (``:1124`` assigns it
    unchanged) and is written as ``particle_microsec``, declared ``double``
    (``imgproc_variables_v35``, ``:321``), so it round-trips at full precision;
    ``Time_in_seconds`` is the accumulator itself (``:1131``), also ``double``.
    Both operands of the fold are therefore on disk exactly.
    """
    with netCDF4.Dataset(str(path)) as ds:
        rec_num = np.asarray(ds.variables["parent_rec_num"][:]).astype(np.int64)
        part_micro = np.asarray(ds.variables["particle_microsec"][:]).astype(np.float64)
        tis = np.asarray(ds.variables["Time_in_seconds"][:]).astype(np.float64)
    before = np.flatnonzero(rec_num < first_record)
    if before.size == 0:
        return None, None
    last = int(before[-1])
    return float(part_micro[last]), float(tis[last])


def _bits(x: float) -> bytes:
    """The float64 bit pattern -- ``tobytes()``, so 'equal' means equal."""
    return struct.pack("<d", x)


#: Module-scoped, not class-scoped: four test classes want the same serial
#: baseline and the same two chunk sets, and each S3 pass over the fixture costs
#: seconds.  Built once in :func:`setUpModule`.
_CHUNK_CACHE: dict[bool, list[Path]] = {}
_TMPDIR: tempfile.TemporaryDirectory | None = None
_STATE: dict = {}


def setUpModule():  # noqa: N802 -- unittest's name
    global _TMPDIR
    if netCDF4 is None:  # pragma: no cover -- the classes skip anyway
        return
    _TMPDIR = tempfile.TemporaryDirectory()
    n_records = _time_len(SPEC_INPUT)
    serial = Path(_TMPDIR.name) / "serial.nc"
    _run(SPEC_INPUT, serial, 1, n_records)
    _STATE.update(n_records=n_records, n_every=-(-n_records // N_CHUNKS),
                  serial=serial)


def tearDownModule():  # noqa: N802 -- unittest's name
    _CHUNK_CACHE.clear()
    _STATE.clear()
    if _TMPDIR is not None:
        _TMPDIR.cleanup()


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
class _Base(unittest.TestCase):
    """Shared serial baseline and chunk geometry, built once for the module."""

    @property
    def serial(self) -> Path:
        return _STATE["serial"]

    @property
    def tmpdir(self) -> tempfile.TemporaryDirectory:
        assert _TMPDIR is not None
        return _TMPDIR

    @property
    def n_records(self) -> int:
        return _STATE["n_records"]

    @property
    def n_every(self) -> int:
        return _STATE["n_every"]

    def chunk_start(self, k: int) -> int:
        return (k - 1) * self.n_every + 1

    def chunk_files(self, primed: bool) -> list[Path]:
        """One file per chunk, each primed (or not) at its own first particle.

        Memoised: five of the tests below want one of these two chunk sets, and
        an S3 pass is not cheap -- without the cache this module re-ran the
        fixture five times over and cost ~190 s, a third of the whole default
        suite (589 s, W6) for one acceptance check.  Callers treat the files as
        read-only.
        """
        if primed in _CHUNK_CACHE:
            return _CHUNK_CACHE[primed]
        out_dir = Path(self.tmpdir.name) / ("primed" if primed else "bare")
        out_dir.mkdir(exist_ok=True)
        paths = []
        for k in range(1, N_CHUNKS + 1):
            if self.chunk_start(k) > self.n_records:
                continue
            out = out_dir / f"chunk{k}.nc"
            if primed:
                ptp, tisp = _seam_state_from(self.serial, self.chunk_start(k))
                # Chunk 1 has no preceding particle; prime= refuses n=1.
                _run(SPEC_INPUT, out, k, self.n_every,
                     prime=None if ptp is None else (ptp, tisp))
            else:
                _run(SPEC_INPUT, out, k, self.n_every)
            paths.append(out)
        _CHUNK_CACHE[primed] = paths
        return paths

    def assert_concat_matches_serial(self, chunk_paths, *, expect_equal: bool):
        """Compare chunk-concatenation against the serial run, bit for bit.

        ``np.array_equal`` on the float64 view of every variable -- never
        ``allclose``.  ``equal_nan=True`` because several measured quantities
        are NaN by construction (an all-lit image), and NaN != NaN would report
        agreement as difference.
        """
        differing = []
        with netCDF4.Dataset(str(self.serial)) as s:
            names = list(s.variables)
            for name in names:
                dims = s.variables[name].dimensions
                sv = np.asarray(s.variables[name][:]).astype(np.float64)
                parts = []
                for p in chunk_paths:
                    with netCDF4.Dataset(str(p)) as c:
                        parts.append(np.asarray(c.variables[name][:]).astype(np.float64))
                if "time" in dims:
                    merged = np.concatenate(parts, axis=dims.index("time"))
                else:
                    merged = np.sum(parts, axis=0)      # bin_stats, per-file counts
                if merged.shape != sv.shape or not np.array_equal(merged, sv, equal_nan=True):
                    differing.append(name)
        if expect_equal:
            self.assertEqual(differing, [],
                             "primed chunks must reproduce the serial run exactly; "
                             f"these variables differ: {differing}")
        else:
            self.assertNotEqual(
                differing, [],
                "the comparison does not discriminate: an UNPRIMED chunked run "
                "agreed with serial on every variable, so a passing primed run "
                "would prove nothing")
        return differing


class TestTheRefusalStandsForUnprimedMerges(_Base):
    """The boundary after priming landed (2026-09-18), and it MOVED rather than lifted.

    ``"spec"`` is still not chunkable by concatenation alone -- everything the
    original refusal said about the accumulation is true, and an unprimed merge
    must go on refusing.  What changed is that a second, narrower door exists,
    and it is opened only by a caller that states it did the priming.
    """

    def test_spec_timing_is_still_not_chunkable_without_priming(self):
        self.assertNotIn("spec", CHUNKABLE_TIMINGS_V35)
        self.assertIn("spec", PRIMABLE_TIMINGS_V35)
        self.assertEqual(PROBES_V35[PROBE].timing, "spec")

    def test_merge_refuses_every_probetype_2_probe_by_name_when_unprimed(self):
        for probename in ("2DS", "HVPS", "3VCPI_H", "3VCPI_V"):
            with self.subTest(probe=probename):
                with self.assertRaises(ChunkingNotEquivalent):
                    merge_chunks_v35(["unused.nc"], "out.nc", projectname=PROJECT,
                                     infile=str(SPEC_INPUT), probename=probename,
                                     iNewHabit=0, software=SOFTWARE)

    def test_merge_gets_past_the_refusal_when_the_caller_states_it_primed(self):
        """``primed=True`` must reach the *merge*, not be rejected at the door.

        Asserted by the failure mode: with a nonexistent chunk file the call now
        fails on the file, never on ``ChunkingNotEquivalent``.  A test that only
        asserted "does not raise ChunkingNotEquivalent" would pass if the
        function raised it one line later, so this pins which error arrives.
        """
        with self.assertRaises(Exception) as caught:
            merge_chunks_v35([str(Path(self.tmpdir.name) / "no_such_chunk.nc")],
                             str(Path(self.tmpdir.name) / "merged.nc"),
                             projectname=PROJECT, infile=str(SPEC_INPUT),
                             probename=PROBE, iNewHabit=0, software=SOFTWARE,
                             primed=True)
        self.assertNotIsInstance(caught.exception, ChunkingNotEquivalent)

    def test_primed_true_is_refused_where_priming_is_meaningless(self):
        """A ``"dmt"`` merge with ``primed=True`` asserts what no worker could do.

        ``imgproc_sm_v35`` refuses ``prime=`` for probetype 1, so a caller
        claiming to have primed its chunks there is describing a run that cannot
        exist -- and silently accepting the claim would let a real mistake
        (wrong probe, wrong branch) through as a no-op.
        """
        with self.assertRaises(ValueError) as caught:
            merge_chunks_v35(["unused.nc"], "out.nc", projectname=PROJECT,
                             infile=str(SPEC_INPUT), probename="CIP",
                             iNewHabit=0, software=SOFTWARE, primed=True)
        self.assertNotIsInstance(caught.exception, ChunkingNotEquivalent)


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
class TestPrimeRefusesWhatItCannotReproduce(unittest.TestCase):
    """The four refusals on ``prime=`` -- each a case where a silently accepted
    pair would produce a file that looks like a serial run and is not."""

    def _call(self, **over):
        kw = dict(probename=PROBE, n=2, prime=(1.0, 2.0), iQC=0,
                  tas_time=np.array([]), tas=np.array([]))
        kw.update(over)
        return imgproc_sm_v35(
            str(SPEC_INPUT), str(Path(tempfile.gettempdir()) / "unwritten.nc"),
            kw.pop("probename"), kw.pop("n"), 5, PROJECT,
            iNewHabit=0, reject_config=STOCK_V35_REJECT_CONFIG,
            software=SOFTWARE, creation_time=FIXED_CREATION_TIME, **kw)

    def test_prime_on_a_non_spec_probe_is_refused(self):
        with self.assertRaises(ValueError) as c:
            self._call(probename="CIP", tas_time=None, tas=None)
        self.assertIn("prime=", str(c.exception))

    def test_prime_with_n_equal_1_is_refused(self):
        with self.assertRaises(ValueError) as c:
            self._call(n=1)
        self.assertIn("no preceding particle", str(c.exception))

    def test_prime_with_iqc_1_is_refused(self):
        with self.assertRaises(ValueError) as c:
            self._call(iQC=1)
        self.assertIn("iQC=1", str(c.exception))

    def test_a_half_pair_is_refused_rather_than_completed(self):
        with self.assertRaises(ValueError):
            self._call(prime=(1.0, None))

    def test_the_scan_refuses_to_run_against_a_tas_series_it_was_not_given(self):
        """The bug this signature exists to prevent: scanning with no TAS.

        An empty series is legal (it selects TAS_FALLBACK) and must match the
        run; ``None`` is the caller having no series in mind at all, which would
        silently prime from a fold the run never performs.
        """
        with self.assertRaises(ValueError) as c:
            prefix_scan_v35(SPEC_INPUT, PROBE, 5, tas_time=None, tas=None)
        self.assertIn("tas", str(c.exception).lower())

    def test_the_scan_refuses_a_timing_that_needs_no_priming(self):
        with self.assertRaises(ValueError):
            prefix_scan_v35(SPEC_INPUT, "CIP", 5,
                            tas_time=np.array([]), tas=np.array([]))


class TestUnprimedChunksDiffer(_Base):
    """The measurement the refusal rests on, reproduced here as the control.

    Without this the priming test proves nothing: a comparison that passes on
    an unprimed run is not measuring the seam.
    """

    def test_an_unprimed_chunked_run_disagrees_with_serial(self):
        differing = self.assert_concat_matches_serial(
            self.chunk_files(primed=False), expect_equal=False)
        self.assertIn("Time_in_seconds", differing,
                      "the accumulator itself must be among the differences")

    def test_the_disagreement_is_confined_to_the_two_time_variables(self):
        """Which variables a seam actually breaks -- measured, not assumed.

        Nothing measured (``image_length``, the habit, the reject code) may
        appear here: those are functions of the particle's own image and cannot
        see a seam.  If one ever does, priming is not the whole story and this
        test is where that shows up.
        """
        differing = set(self.assert_concat_matches_serial(
            self.chunk_files(primed=False), expect_equal=False))
        self.assertTrue(
            differing <= {"Time_in_seconds", "int_arrival"},
            f"a chunk seam changed more than the time accumulation: {sorted(differing)}")


class TestPrimingReproducesTheSerialRunExactly(_Base):
    """The question, answered by measurement on every written variable."""

    def test_primed_chunks_concatenate_to_the_serial_run_bit_for_bit(self):
        self.assert_concat_matches_serial(self.chunk_files(primed=True),
                                          expect_equal=True)

    def test_the_two_scalars_are_the_complete_carried_state(self):
        """Same measurement, stated as the claim it licenses.

        Every chunk after the first was given exactly two float64 values and
        nothing else, and the whole file came back identical -- so no third
        quantity crosses a ``"spec"`` seam.
        """
        primings = []
        out_dir = Path(self.tmpdir.name) / "audit"
        out_dir.mkdir(exist_ok=True)
        for k in range(2, N_CHUNKS + 1):
            if self.chunk_start(k) > self.n_records:
                continue
            ptp, tisp = _seam_state_from(self.serial, self.chunk_start(k))
            self.assertIsNotNone(ptp, f"chunk {k} has no preceding particle; the "
                                      "fixture does not exercise a seam")
            with _FirstParticleBranchSpy() as spy:
                _run(SPEC_INPUT, out_dir / f"chunk{k}.nc", k, self.n_every,
                     prime=(ptp, tisp))
            self.assertEqual(spy.restarts, 0,
                             "a primed chunk must never take imgProc_sm.m:1136's "
                             "first-particle branch: prime= was accepted and then "
                             "dropped, so the accumulation restarted anyway")
            primings.append((ptp, tisp))
        self.assertTrue(primings, "no seam was primed; the fixture proves nothing")

    def test_time_in_seconds_is_identical_as_bytes_not_merely_close(self):
        chunk_paths = self.chunk_files(primed=True)
        parts = []
        for p in chunk_paths:
            # Closed explicitly: an open handle keeps the file locked on Windows
            # and the module's TemporaryDirectory then fails to clean up.
            with netCDF4.Dataset(str(p)) as c:
                parts.append(np.asarray(c.variables["Time_in_seconds"][:],
                                        dtype=np.float64))
        merged = np.concatenate(parts)
        with netCDF4.Dataset(str(self.serial)) as s:
            serial = np.asarray(s.variables["Time_in_seconds"][:], dtype=np.float64)
        self.assertEqual(merged.tobytes(), serial.tobytes(),
                         "Time_in_seconds must match as BYTES; 'close' is not the claim")

    def test_a_one_ulp_error_in_the_priming_value_is_detected(self):
        """The mutation test: perturb the primed accumulator by one ULP.

        If this still passes, the byte comparison above is not discriminating
        and every result in this module is worthless.
        """
        out_dir = Path(self.tmpdir.name) / "mutant"
        out_dir.mkdir(exist_ok=True)
        k = 2
        good = self.chunk_files(primed=True)[k - 1]
        ptp, tisp = _seam_state_from(self.serial, self.chunk_start(k))
        self.assertIsNotNone(tisp)
        mutant = float(np.nextafter(np.float64(tisp), np.float64(np.inf)))
        self.assertNotEqual(_bits(mutant), _bits(tisp))
        _run(SPEC_INPUT, out_dir / "chunk.nc", k, self.n_every, prime=(ptp, mutant))
        with netCDF4.Dataset(str(out_dir / "chunk.nc")) as m, netCDF4.Dataset(str(good)) as g:
            mv = np.asarray(m.variables["Time_in_seconds"][:], dtype=np.float64)
            gv = np.asarray(g.variables["Time_in_seconds"][:], dtype=np.float64)
        self.assertNotEqual(mv.tobytes(), gv.tobytes(),
                            "a one-ULP error in the priming value produced an identical "
                            "file -- the comparison is not measuring the accumulator")


class TestPrefixScanReachesTheSeamState(_Base):
    """The feasibility half: the priming values without the processing cost."""

    def test_the_scan_lands_on_the_serial_run_s_own_bit_pattern(self):
        seams = 0
        for k in range(2, N_CHUNKS + 1):
            first = self.chunk_start(k)
            if first > self.n_records:
                continue
            with self.subTest(chunk=k):
                scanned = _scan(first)
                self.assertIsNotNone(scanned, "the scan found no preceding particle "
                                              "where the serial run has one")
                scanned_pt, scanned_t = scanned
                truth_pt, truth_t = _seam_state_from(self.serial, first)
                self.assertIsNotNone(truth_t)
                self.assertEqual(_bits(scanned_pt), _bits(truth_pt),
                                 "part_time_prev differs from the serial run's")
                self.assertEqual(_bits(scanned_t), _bits(truth_t),
                                 "time_in_seconds_prev differs from the serial run's -- "
                                 "a prefix scan that is not bit-exact cannot prime")
                seams += 1
        self.assertGreater(seams, 0, "no seam was scanned; the fixture proves nothing")

    def test_one_pass_over_the_file_gives_the_same_pairs_as_n_separate_scans(self):
        """The driver takes the one-pass form; it must be the same arithmetic.

        ``chunk_primes_v35`` exists only so a chunked run reads the file once
        instead of ``chunks/2`` times over. If it ever disagreed with the
        per-chunk scan, the scheduling shortcut would have become a fidelity
        difference -- so the equality is asserted on the float64 *bytes*.
        """
        one_pass = chunk_primes_v35(SPEC_INPUT, PROBE, self.n_every, N_CHUNKS,
                                    tas_time=np.array([]), tas=np.array([]))
        self.assertEqual(len(one_pass), N_CHUNKS)
        self.assertIsNone(one_pass[0], "record 1 has no preceding particle")
        for k in range(1, N_CHUNKS + 1):
            first = self.chunk_start(k)
            if first > self.n_records:
                continue
            with self.subTest(chunk=k):
                separate = _scan(first)
                got = one_pass[k - 1]
                if separate is None:
                    self.assertIsNone(got)
                    continue
                self.assertIsNotNone(got)
                self.assertEqual(_bits(got[0]), _bits(separate[0]))
                self.assertEqual(_bits(got[1]), _bits(separate[1]))

    def test_the_scan_reads_no_measured_quantity(self):
        """A prefix scan that called ``measure_record`` would prime correctly and
        save nothing. Assert it never reaches the measurement path."""
        called = []
        real = v35_imgproc.measure_record

        def spy(*a, **kw):
            called.append(1)
            return real(*a, **kw)

        v35_imgproc.measure_record = spy
        try:
            _scan(self.n_records)
        finally:
            v35_imgproc.measure_record = real
        self.assertEqual(called, [],
                         "the prefix scan invoked measure_record; it is then just a "
                         "serial run and priming buys nothing")

    def test_priming_from_the_scan_alone_reproduces_the_serial_run(self):
        """End to end with no serial run in the loop: the scan supplies the pair."""
        out_dir = Path(self.tmpdir.name) / "scan_primed"
        out_dir.mkdir(exist_ok=True)
        paths = []
        for k in range(1, N_CHUNKS + 1):
            first = self.chunk_start(k)
            if first > self.n_records:
                continue
            out = out_dir / f"chunk{k}.nc"
            _run(SPEC_INPUT, out, k, self.n_every, prime=_scan(first))
            paths.append(out)
        self.assert_concat_matches_serial(paths, expect_equal=True)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
