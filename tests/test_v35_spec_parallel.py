# SPDX-License-Identifier: BSD-3-Clause
"""The parallel v3.5 decode must be byte-identical to the serial one.

The v3.5 record loop carries one value across record windows, the running
airspeed ``tas_prev``, so a split decode is correct only if every part starts
from the airspeed the serial loop would have carried into it.
``read_binary_spec_v35_parallel`` finds those values with a cheap housekeeping
pass replayed through the serial gate, then checks every seam by bit pattern
and re-decodes any part that started wrong. These tests compare whole files:
``.H.nc`` and ``.V.nc`` (NETCDF4, so HDF5 underneath) by SHA-256 with the same
``creation_time`` on both sides, and the three sidecars byte for byte.

Pool decodes run in a subprocess with a timeout, for the reason
``tests/test_spec_parallel.py``'s ``_decode_parallel_in_subprocess`` gives: a
pool whose workers die at spawn on Windows makes ``map`` wait forever, and only
owning the process bounds that.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import textwrap
import unittest
import warnings
from pathlib import Path
from unittest import mock

import numpy as np
from tests._slow import slow

from arrayprobe_uiops import spec as v35
from arrayprobe_uiops.tas import InterpTasError

DATA = Path(__file__).resolve().parent / "data"
MAIN_FIXTURE = DATA / "v35_spec_raw_fixture"
BOUND_FIXTURE = DATA / "v35_spec_bound_raw_fixture"
GOLDEN_PATH = DATA / "v35_spec_oracle.json"
PORT = Path(__file__).resolve().parents[1]

SOFTWARE = "UIOOPS_v3.5"
CREATION_TIME = "2026/09/25 00:00:00"
SUFFIXES = (".H.nc", ".V.nc", ".tas.csv", ".NV.csv", ".MK.csv")

#: Bounds a hang, not performance; see tests/test_spec_parallel.py.
PARALLEL_TIMEOUT_S = 300


def _flight_series() -> dict:
    va = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))["cases"]["main_with_tas"]["varargin"]
    return {"flt_time": va["fltTime"], "flt_tas": va["fltTAS"]}


def _digests(stem) -> dict:
    out = {}
    for suffix in SUFFIXES:
        path = Path(str(stem) + suffix)
        out[suffix] = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    return out


def _serial(fixture, stem, **kwargs):
    counts = v35.read_binary_spec_v35(fixture, stem, software=SOFTWARE,
                                      creation_time=CREATION_TIME, **kwargs)
    return counts, _digests(stem)


def _n_windows(fixture) -> int:
    return max(0, os.path.getsize(fixture) // v35.RECORD_BYTES - 1)


def _split(fixture, stem, edges, workdir, *, flight=None, time_offset=None, channels="HV",
           stats=None, report_every=0):
    """One in-process split decode over explicit ``edges``, no pool."""
    return v35._split_decode_v35(
        fixture, stem, edges, map, workdir, flight=flight, time_offset=time_offset,
        software=SOFTWARE, creation_time=CREATION_TIME, sidecars=True, output_txt=False,
        fast=True, channels=channels, report_every=report_every, stamp_profile=None,
        stats=stats)


# ------------------------------------------------------------------------------------------
# A synthetic multi-window file whose seams land on the hard cases.
# ------------------------------------------------------------------------------------------

#: 701 records give 700 windows, so ``jobs=7`` puts seams at windows 100, 200, ..., 600.
SYNTH_RECORDS = 701
SYNTH_JOBS = 7
NAN_F32 = float(np.float32(np.nan))

#: window -> (tas, n_hol). Chosen against the seams at 100, 200, ..., 600:
#:   10, 50   clean readings in part 0; 50's value is what part 1 inherits, and the
#:            seam-check test drops it;
#:   99       a suspect 170 immediately before the seam at 100;
#:   150      a clean reading that resets the chain inside part 1;
#:   180-220  no readings at all, across the seam at 200;
#:   298, 299 a clean +0.0 then a clean -0.0 just before the seam at 300: the gate
#:            keeps +0.0 (they compare equal), so the carried value is +0.0, not the
#:            last clean reading's bits;
#:   350      a reading with a hold-over count, rejected;
#:   499      a clean NaN just before the seam at 500, carried across it;
#:   550      a clean reading after the NaN, which replaces it.
SYNTH_READINGS = {
    10: (80.0, 0),
    50: (90.0, 0),
    99: (170.0, 0),
    150: (110.0, 0),
    298: (0.0, 0),
    299: (-0.0, 0),
    350: (120.0, 1),
    499: (NAN_F32, 0),
    550: (130.0, 0),
    640: (170.0, 0),
    699: (140.0, 0),
}


def _build_synthetic(path: Path) -> Path:
    oracle = str(PORT / "scripts" / "validation" / "octave")
    if oracle not in sys.path:
        sys.path.insert(0, oracle)
    from run_s2_spec_bank import build_raw_fixture, image_packet, mask_packet, run_word
    from run_v35_spec_bank import housekeeping_packet

    runs_h = [run_word(10, 5, new_slice=True), run_word(8, 3)]
    runs_v = [run_word(4, 2, new_slice=True), run_word(6, 1)]
    records = []
    for i in range(SYNTH_RECORDS):
        # Hour 23 then 24-25 near the end, so the V-only day-rollover clamp is crossed.
        hour = 6 if i < 600 else 24 + (i - 600) // 60
        header = [2016, 9, 2, 6, hour, (i // 60) % 60, i % 60, (i * 7) % 1000]
        data = image_packet(runs_h, 2, channel="H", t_particle=0x0001_0000 + i)
        if i % 3 == 0:
            data = data + image_packet(runs_v, 2, channel="V", t_particle=0x0002_0000 + i)
        if i in SYNTH_READINGS:
            tas, n_hol = SYNTH_READINGS[i]
            data = data + housekeeping_packet(tas, n_hol=n_hol)
        if i % 97 == 5:
            data = data + mask_packet()
        records.append((header, data))
    path.write_bytes(build_raw_fixture(records))
    return path


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v35par_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)


# ------------------------------------------------------------------------------------------
# 1. Through a real pool, in a subprocess.
# ------------------------------------------------------------------------------------------

_POOL_SCRIPT = textwrap.dedent("""
    import faulthandler, hashlib, json, os, sys
    from pathlib import Path
    from arrayprobe_uiops import spec as v35
    cases_path, timeout_s = sys.argv[1:3]
    faulthandler.dump_traceback_later(max(1.0, float(timeout_s) - 15), exit=False,
                                      file=sys.stderr)
    results = []
    for case in json.loads(Path(cases_path).read_text()):
        stats = {}
        counts = v35.read_binary_spec_v35_parallel(
            case["fixture"], case["stem"], jobs=case["jobs"], software=case["software"],
            creation_time=case["creation_time"], channels=case["channels"],
            workdir=case["workdir"], report_every=case.get("report_every", 0),
            stats=stats, **case.get("kwargs", {}))
        results.append({"counts": list(counts), "stats": stats})
    print(json.dumps(results))
""")


def _pool_decodes(cases: list[dict], workdir: Path) -> list[dict]:
    """Run every case's parallel decode in ONE subprocess, bounded by a timeout."""
    cases_path = workdir / "cases.json"
    cases_path.write_text(json.dumps(cases), encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(PORT / "src"), str(PORT), env.get("PYTHONPATH", "")])
    argv = [sys.executable, "-c", _POOL_SCRIPT, str(cases_path), str(PARALLEL_TIMEOUT_S)]
    try:
        done = subprocess.run(argv, capture_output=True, text=True, env=env,
                              timeout=PARALLEL_TIMEOUT_S, cwd=str(workdir))
        if done.returncode != 0 and "WinError 6" in done.stderr:
            done = subprocess.run(argv, capture_output=True, text=True, env=env,
                                  timeout=PARALLEL_TIMEOUT_S, cwd=str(workdir))
    except subprocess.TimeoutExpired as exc:
        tail = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode()
        raise AssertionError(
            f"the parallel v3.5 decodes did not finish in {PARALLEL_TIMEOUT_S}s; every hang "
            "of this kind so far has been pool workers dying at spawn (WinError 6). Re-run "
            "this module alone before reading it as a break in the decoder.\n"
            + tail[-3000:]) from exc
    if done.returncode != 0:
        raise AssertionError(f"parallel decode subprocess exited {done.returncode}\n"
                             f"stdout: {done.stdout[-2000:]}\nstderr: {done.stderr[-3000:]}")
    return json.loads(done.stdout.strip().splitlines()[-1])


@slow
class ParallelMatchesSerial(_Tmp):
    """Every job count, every channel selection, both fixtures, and the flight-series and
    time-offset paths: whole-file digests equal to the serial decode's.

    Gated for the reason ``tests/test_spec_parallel.py``'s class of the same name is: a
    real pool that hangs takes the whole suite with it. The default run proves the same
    code in process (the classes below differ only in using the builtin ``map``)."""

    def test_pool_decodes_are_byte_identical_to_serial(self):
        # Each case is a pool start (seconds on Windows), so the channel selections ride on
        # one job count; every job count runs both channels. The bound fixture has a
        # single window, so it exercises the delegation to the serial path.
        n = _n_windows(MAIN_FIXTURE)
        configs = [(MAIN_FIXTURE, jobs, "HV", {}) for jobs in (2, 3, n + 3)]
        configs += [(MAIN_FIXTURE, 3, channels, {}) for channels in ("H", "V")]
        configs += [(BOUND_FIXTURE, 2, channels, {}) for channels in ("HV", "H")]
        configs.append((MAIN_FIXTURE, 3, "HV", _flight_series()))
        configs.append((MAIN_FIXTURE, 4, "HV", {"time_offset": 3605.0}))
        configs.append((MAIN_FIXTURE, 3, "HV", {"time_offset": -21600.0, **_flight_series()}))

        cases, serial = [], []
        for idx, (fixture, jobs, channels, kwargs) in enumerate(configs):
            sdir = self.tmp / f"s{idx}"
            pdir = self.tmp / f"p{idx}"
            sdir.mkdir()
            pdir.mkdir()
            counts, digests = _serial(fixture, sdir / "out", channels=channels, **kwargs)
            serial.append((counts, digests))
            cases.append({"fixture": str(fixture), "stem": str(pdir / "out"), "jobs": jobs,
                          "channels": channels, "software": SOFTWARE,
                          "creation_time": CREATION_TIME, "workdir": str(pdir),
                          "report_every": 1 if idx == 0 else 0, "kwargs": kwargs})
        results = _pool_decodes(cases, self.tmp)
        for idx, ((fixture, jobs, channels, kwargs), result) in enumerate(zip(configs, results,
                                                                             strict=True)):
            with self.subTest(fixture=fixture.name, jobs=jobs, channels=channels,
                              kwargs=sorted(kwargs)):
                counts, digests = serial[idx]
                self.assertEqual(tuple(result["counts"]), tuple(counts))
                self.assertEqual(_digests(self.tmp / f"p{idx}" / "out"), digests)
                self.assertEqual(result["stats"].get("reruns", 0), 0)

    def test_the_hdf5_files_are_compared_whole(self):
        """Guard against the comparison going vacuous: the digests are of real HDF5 files,
        and a different creation_time changes them, so the files are hashed whole, with
        that attribute inside."""
        _, a = _serial(MAIN_FIXTURE, self.tmp / "a")
        v35.read_binary_spec_v35(MAIN_FIXTURE, self.tmp / "b", software=SOFTWARE,
                                 creation_time=CREATION_TIME.replace("00:00:00", "00:00:01"))
        b = _digests(self.tmp / "b")
        self.assertIsNotNone(a[".H.nc"])
        self.assertNotEqual(a[".H.nc"], b[".H.nc"])
        head = Path(str(self.tmp / "a") + ".H.nc").read_bytes()[:8]
        self.assertEqual(head, b"\x89HDF\r\n\x1a\n")


# ------------------------------------------------------------------------------------------
# 2. Every split of the ten-record fixture, in process.
# ------------------------------------------------------------------------------------------

class _Splits(_Tmp):

    def _splits(self, masks, **kwargs):
        _, want = _serial(MAIN_FIXTURE, self.tmp / "serial", **kwargs)
        n = _n_windows(MAIN_FIXTURE)
        self.assertEqual(n, 9)
        flight = None
        if "flt_time" in kwargs:
            flight = (kwargs["flt_time"], v35.interp_tas(kwargs["flt_tas"]))
        for mask in masks(n):
            edges = [0, *[k + 1 for k in range(n - 1) if mask >> k & 1], n]
            work = self.tmp / f"w{mask}"
            work.mkdir()
            stats: dict = {}
            _split(MAIN_FIXTURE, work / "out", edges, str(work), flight=flight,
                   time_offset=kwargs.get("time_offset"), stats=stats)
            with self.subTest(edges=edges):
                self.assertEqual(_digests(work / "out"), want)
                self.assertEqual(stats["reruns"], 0)
            shutil.rmtree(work, ignore_errors=True)


def _single_seams_and_all(n):
    """One seam at each of the n-1 places, then every seam at once: a seam falls straight
    after every housekeeping reading the fixture holds, the suspect 170 and the nHOL=1 one
    included."""
    return [1 << k for k in range(n - 1)] + [2 ** (n - 1) - 1]


def _every_mask(n):
    return range(2 ** (n - 1))


class SeamAtEveryWindowOfTheFixture(_Splits):
    """In process, no pool: each of the eight seam positions alone, and all of them."""

    def test_each_seam_without_a_flight_series(self):
        self._splits(_single_seams_and_all)

    def test_each_seam_with_a_flight_series_and_an_offset(self):
        self._splits(_single_seams_and_all, time_offset=7.0, **_flight_series())


@slow
class EverySplitOfTheFixture(_Splits):
    """All 2**8 ways to cut the nine windows (about 150 s each on this machine, which is
    why the default run takes the single-seam set above)."""

    def test_every_split_without_a_flight_series(self):
        self._splits(_every_mask)

    def test_every_split_with_a_flight_series_and_an_offset(self):
        self._splits(_every_mask, time_offset=7.0, **_flight_series())


# ------------------------------------------------------------------------------------------
# 3. The housekeeping pass sees exactly what the decoder's gate sees.
# ------------------------------------------------------------------------------------------

def _bits(x) -> bytes:
    return struct.pack("<d", float(x))


class HkReadingsMatchTheDecoder(_Tmp):

    def _windows(self):
        synth = _build_synthetic(self.tmp / "synthetic.2DS")
        for fixture in (MAIN_FIXTURE, BOUND_FIXTURE, synth):
            for i, (header, buf) in enumerate(v35.iter_record_windows(fixture)):
                yield f"{fixture.name}[{i}]", header, buf

    def test_the_argument_tuples_agree_window_by_window(self):
        real = v35.update_tas
        checked = 0
        for label, header, buf in self._windows():
            calls = []

            def record(tas_temp, tas_prev, n_hol, n_vol, _calls=calls):
                _calls.append((tas_temp, n_hol, n_vol))
                return real(tas_temp, tas_prev, n_hol, n_vol)

            with mock.patch.object(v35, "update_tas", record):
                v35.get_img_v35(buf, header.timehhmmss, None, v35.INITIAL_TAS)
            got = v35.hk_readings_v35(buf)
            with self.subTest(window=label):
                self.assertEqual(len(got), len(calls))
                for (a, ah, av), (b, bh, bv) in zip(got, calls, strict=True):
                    self.assertEqual(_bits(a), _bits(b))
                    self.assertEqual((int(ah), int(av)), (int(bh), int(bv)))
            checked += len(calls)
        # Not vacuous: the fixtures and the synthetic file carry readings.
        self.assertGreaterEqual(checked, 4 + len(SYNTH_READINGS))


# ------------------------------------------------------------------------------------------
# 4. A long synthetic file with seams on the hard cases.
# ------------------------------------------------------------------------------------------

class SyntheticMultiWindow(_Tmp):

    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tempfile.mkdtemp(prefix="v35synth_"))
        cls.addClassCleanup(shutil.rmtree, cls.dir, True)
        cls.raw = _build_synthetic(cls.dir / "synthetic.2DS")
        cls.counts, cls.want = _serial(cls.raw, cls.dir / "serial")
        n = _n_windows(cls.raw)
        cls.edges = [round(k * n / SYNTH_JOBS) for k in range(SYNTH_JOBS + 1)]

    def test_the_file_exercises_what_it_claims(self):
        self.assertEqual(self.edges, [0, 100, 200, 300, 400, 500, 600, 700])
        # More than one 256-record flush on the H file.
        self.assertGreater(self.counts[0], 2 * 256)
        # The carried value at the +0/-0 seam is +0.0, and the shortcut would say -0.0.
        incoming = v35._replay_incoming(
            [v35._hk_range_v35((str(self.raw), lo, hi))
             for lo, hi in zip(self.edges, self.edges[1:], strict=False)])
        self.assertEqual(_bits(incoming[3]), _bits(0.0))
        self.assertNotEqual(_bits(incoming[3]), _bits(-0.0))
        self.assertTrue(np.isnan(incoming[5]))
        self.assertEqual(incoming[1], 90.0)  # the suspect 170 just before the seam is kept out
        self.assertEqual(incoming[2], 110.0)  # carried across a stretch with no readings

    def test_in_process_split_is_byte_identical(self):
        stats: dict = {}
        _split(self.raw, self.tmp / "out", self.edges, str(self.tmp), stats=stats)
        self.assertEqual(_digests(self.tmp / "out"), self.want)
        self.assertEqual(stats["reruns"], 0)


@slow
class SyntheticMultiWindowThroughAPool(_Tmp):
    """The synthetic file through a real seven-worker pool; gated as above."""

    @classmethod
    def setUpClass(cls):
        SyntheticMultiWindow.setUpClass.__func__(cls)

    def test_pool_decode_is_byte_identical(self):
        results = _pool_decodes(
            [{"fixture": str(self.raw), "stem": str(self.tmp / "out"), "jobs": SYNTH_JOBS,
              "channels": "HV", "software": SOFTWARE, "creation_time": CREATION_TIME,
              "workdir": str(self.tmp)}], self.tmp)
        self.assertEqual(tuple(results[0]["counts"]), tuple(self.counts))
        self.assertEqual(results[0]["stats"], {"parts": SYNTH_JOBS, "reruns": 0})
        self.assertEqual(_digests(self.tmp / "out"), self.want)


# ------------------------------------------------------------------------------------------
# 5. A wrong start value is caught and repaired.
# ------------------------------------------------------------------------------------------

class SeamCheckCatchesAWrongPrime(_Tmp):

    def test_a_dropped_reading_costs_one_rerun_and_no_byte(self):
        raw = _build_synthetic(self.tmp / "synthetic.2DS")
        _, want = _serial(raw, self.tmp / "serial")
        n = _n_windows(raw)
        edges = [round(k * n / SYNTH_JOBS) for k in range(SYNTH_JOBS + 1)]
        real = v35.hk_readings_v35

        def drop_ninety(buf):
            return [r for r in real(buf) if r[0] != 90.0]

        stats: dict = {}
        with mock.patch.object(v35, "hk_readings_v35", drop_ninety), \
                warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _split(raw, self.tmp / "out", edges, str(self.tmp), stats=stats)
        self.assertEqual(stats["reruns"], 1)
        self.assertEqual(sum(issubclass(w.category, v35.SeamRerunWarning) for w in caught), 1)
        self.assertEqual(_digests(self.tmp / "out"), want)


# ------------------------------------------------------------------------------------------
# 6. Delegation and early refusals.
# ------------------------------------------------------------------------------------------

class Delegation(_Tmp):

    def test_one_job_calls_the_serial_function(self):
        with mock.patch.object(v35, "read_binary_spec_v35", return_value=(1, 2)) as serial:
            got = v35.read_binary_spec_v35_parallel(
                MAIN_FIXTURE, self.tmp / "o", jobs=1, software=SOFTWARE,
                creation_time=CREATION_TIME)
        self.assertEqual(got, (1, 2))
        serial.assert_called_once()

    def test_one_job_is_byte_identical_to_serial(self):
        _, want = _serial(MAIN_FIXTURE, self.tmp / "s")
        v35.read_binary_spec_v35_parallel(MAIN_FIXTURE, self.tmp / "p", jobs=1,
                                          software=SOFTWARE, creation_time=CREATION_TIME)
        self.assertEqual(_digests(self.tmp / "p"), want)

    def test_bad_channels_raise_before_the_file_is_touched(self):
        with self.assertRaisesRegex(ValueError, "channels"):
            v35.read_binary_spec_v35_parallel(
                self.tmp / "absent.2DS", self.tmp / "o", jobs=2, software=SOFTWARE,
                creation_time=CREATION_TIME, channels="X")

    def test_a_one_sided_flight_series_raises_before_the_file_is_touched(self):
        with self.assertRaisesRegex(ValueError, "together"):
            v35.read_binary_spec_v35_parallel(
                self.tmp / "absent.2DS", self.tmp / "o", jobs=2, software=SOFTWARE,
                creation_time=CREATION_TIME, flt_time=[1, 2])

    def test_an_unusable_flight_series_aborts_before_any_pool_or_output(self):
        with mock.patch("concurrent.futures.ProcessPoolExecutor") as pool, \
                self.assertRaises(InterpTasError):
            v35.read_binary_spec_v35_parallel(
                MAIN_FIXTURE, self.tmp / "o", jobs=2, software=SOFTWARE,
                creation_time=CREATION_TIME, flt_time=[1, 2, 3], flt_tas=[0.0, 0.0, 0.0])
        pool.assert_not_called()
        self.assertFalse(list(self.tmp.glob("o.*")))

    def test_progress_lines_name_the_part_and_change_no_byte(self):
        _, want = _serial(MAIN_FIXTURE, self.tmp / "s")
        n = _n_windows(MAIN_FIXTURE)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _split(MAIN_FIXTURE, self.tmp / "p", [0, 4, n], str(self.tmp), report_every=2)
        self.assertEqual(_digests(self.tmp / "p"), want)
        self.assertIn("...part p000 2/4 windows", buf.getvalue())
        self.assertIn("...part p001 4/5 windows", buf.getvalue())


# ------------------------------------------------------------------------------------------
# 7. A real file, when one is named.
# ------------------------------------------------------------------------------------------

@slow
class RealFileSpotCheck(_Tmp):
    """The first records of a real raw 2D-S file, serial against a pool. Point
    ``ARRAYPROBE_V35_REAL_2DS`` at a raw file to run it; skipped otherwise. The slice is
    copied to a temporary file, never written beside the data."""

    N_RECORDS = 3000

    def test_real_slice_pool_equals_serial(self):
        src = os.environ.get("ARRAYPROBE_V35_REAL_2DS")
        if not src or not Path(src).is_file():
            self.skipTest("set ARRAYPROBE_V35_REAL_2DS to a raw 2D-S file to run this")
        raw = self.tmp / "slice.2DS"
        with open(src, "rb") as fh:
            raw.write_bytes(fh.read(self.N_RECORDS * v35.RECORD_BYTES))
        counts, want = _serial(raw, self.tmp / "serial")
        results = _pool_decodes(
            [{"fixture": str(raw), "stem": str(self.tmp / "out"), "jobs": 6, "channels": "HV",
              "software": SOFTWARE, "creation_time": CREATION_TIME,
              "workdir": str(self.tmp)}], self.tmp)
        self.assertEqual(tuple(results[0]["counts"]), tuple(counts))
        self.assertEqual(results[0]["stats"]["reruns"], 0)
        self.assertEqual(_digests(self.tmp / "out"), want)


if __name__ == "__main__":
    unittest.main()
