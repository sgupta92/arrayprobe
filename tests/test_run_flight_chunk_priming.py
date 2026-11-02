# SPDX-License-Identifier: BSD-3-Clause
"""The ``prime=`` token, proven across the REAL subprocess boundary.

``tests/test_v35_sizedist_chunk_priming.py`` proves priming exact
**in-process**: it calls ``imgproc_sm_v35`` directly, in the same interpreter
that computed the priming pair. That cannot see a bug in
``scripts/run_flight.py``'s own argv encode/decode -- exactly the class of
defect where a ``--chunks`` worker is a fresh subprocess
whose own state differs from the parent's. ``stage3`` computes each chunk's
``(part_time_prev, time_in_seconds_prev)`` pair in the parent and ships it to
the worker as a trailing ``prime=<hex>,<hex>`` token (``float.hex()``, which
round-trips exactly); the worker's ``--_run-chunk`` branch parses it with
``float.fromhex`` and forwards it to ``imgproc_sm_v35``. This module spawns
that real subprocess -- the one ``--chunks`` actually launches -- and checks
the round trip end to end, instead of asserting on the parsed tuple in
memory.

Argv shape read from ``scripts/run_flight.py``'s ``--_run-chunk`` branch
(``main()``), not guessed: ten positionals --
``image_file probe project profile_name profile_module tas_file
worker_stall_min out_path n n_every`` -- then order-independent trailing
tokens, of which this module uses ``engine=<v>`` (required; a fresh
subprocess otherwise starts at the module's import-time default ``3.1.4``)
and ``prime=<hex>,<hex>``.

Runs on the tracked 25-record 2DS fixture, ``engine=3.5``, profile
``stock-v3.5`` -- no reference data, no Octave. Does not modify
``scripts/run_flight.py`` or ``src/arrayprobe_uiops/imgproc.py``; both are owned
by another lane.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

import numpy as np

from arrayprobe_uiops.imgproc import chunk_primes_v35

try:
    import netCDF4
except ImportError:  # pragma: no cover -- the suite skips instead
    netCDF4 = None

RUN_FLIGHT = Path(__file__).resolve().parent.parent / "scripts" / "run_flight.py"
DATA = Path(__file__).resolve().parent / "data"
SPEC_INPUT = DATA / "2DS_s3_input_fixture.nc"     # 25 records, probetype 2
PROBE = "2DS"
PROJECT = "ORACLES"
PROFILE_NAME = "stock-v3.5"    # shipped, so profile_module ("") resolves in the worker
N_CHUNKS = 3

#: Two elements is deliberate, not minimal-for-minimal's-sake: with exactly one
#: sample in the series, imgProc_sm.m:727's ``tas2d = tas(tas_time==temp_time)``
#: can only ever match 0 or 1 times, so ``_one()``'s ">1 match" refusal can never
#: fire regardless of whether the fixture's record times happen to collide with
#: it. The values (Time=0.0 HHMMSS, TAS=900.0) are arbitrary -- almost certainly
#: outside the fixture's real record times -- and are NOT chosen to make
#: anything pass: byte-identity between the serial and chunked arms holds
#: because both read the exact same file, whichever branch (matched sample vs.
#: TAS_FALLBACK) that file sends them down.
_TAS_TIME = np.array([0.0])
_TAS = np.array([900.0])


from pathlib import Path as _P  # noqa: E402

# _release_fixture_guard: 2DS_s3_input_fixture.nc is excluded from the release
if not (_P(__file__).resolve().parent / "data" / "2DS_s3_input_fixture.nc").exists():
    raise unittest.SkipTest(
        "2DS_s3_input_fixture.nc is not distributed with the package")


def _make_tas_file(path: Path) -> None:
    """A real aircraft-TAS file: ``_aircraft_series()`` requires a path under
    engine 3.5 / probetype 2 (unlike the engine-level priming test, which
    hands ``imgproc_sm_v35`` empty ``tas_time``/``tas`` arrays directly)."""
    with netCDF4.Dataset(str(path), "w") as ds:
        ds.createDimension("time", _TAS_TIME.size)
        tas_var = ds.createVariable("TAS", "f8", ("time",))
        time_var = ds.createVariable("Time", "f8", ("time",))
        tas_var[:] = _TAS
        time_var[:] = _TAS_TIME


def _time_len(path: Path) -> int:
    with netCDF4.Dataset(str(path)) as ds:
        return len(ds.dimensions["time"])


def _run_chunk(image_file, tas_file, out_path, n, n_every, *,
              prime=None, malformed_prime=None):
    """One real ``--_run-chunk`` subprocess -- the same re-exec ``stage3``'s
    ``--chunks`` path performs. Returns the finished ``CompletedProcess``."""
    cmd = [sys.executable, str(RUN_FLIGHT), "--_run-chunk",
          str(image_file), PROBE, PROJECT, PROFILE_NAME, "", str(tas_file),
          "0", str(out_path), str(n), str(n_every), "engine=3.5"]
    if malformed_prime is not None:
        cmd.append(f"prime={malformed_prime}")
    elif prime is not None:
        ptp, tisp = prime
        cmd.append(f"prime={float(ptp).hex()},{float(tisp).hex()}")
    return subprocess.run(cmd, capture_output=True, text=True)


def _concat_differs_from_serial(serial_path: Path, chunk_paths: list[Path]) -> list[str]:
    """Variables where concatenating ``chunk_paths`` disagrees with
    ``serial_path``, bit for bit (``np.array_equal``, ``equal_nan=True`` --
    several measured quantities are NaN by construction). Mirrors
    ``test_v35_sizedist_chunk_priming.py``'s ``assert_concat_matches_serial``.
    """
    differing = []
    with netCDF4.Dataset(str(serial_path)) as s:
        for name in s.variables:
            dims = s.variables[name].dimensions
            sv = np.asarray(s.variables[name][:]).astype(np.float64)
            parts = []
            for p in chunk_paths:
                with netCDF4.Dataset(str(p)) as c:
                    parts.append(np.asarray(c.variables[name][:]).astype(np.float64))
            if "time" in dims:
                merged = np.concatenate(parts, axis=dims.index("time"))
            else:
                merged = np.sum(parts, axis=0)
            if merged.shape != sv.shape or not np.array_equal(merged, sv, equal_nan=True):
                differing.append(name)
    return differing


def _fail_from(label: str, result: subprocess.CompletedProcess) -> str:
    return (f"{label} exited {result.returncode}\n--- stdout ---\n{result.stdout}\n"
           f"--- stderr ---\n{result.stderr}")


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
class TestRunFlightChunkPrimingArgvRoundTrip(unittest.TestCase):


    n_every: Any  # assigned in setUpClass/setUp; see there for the value
    n_records: Any  # assigned in setUpClass/setUp; see there for the value
    primes: Any  # assigned in setUpClass/setUp; see there for the value
    tas_file: Any  # assigned in setUpClass/setUp; see there for the value
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmp.name)
        cls.tas_file = tmp / "tas.nc"
        _make_tas_file(cls.tas_file)
        cls.n_records = _time_len(SPEC_INPUT)
        cls.n_every = -(-cls.n_records // N_CHUNKS)  # ceil division, mirrors stage3

        # The SAME series the subprocess run below reads from cls.tas_file --
        # a scan against a different one would prime from a fold the run never
        # performs (prefix_scan_v35's own guard).
        cls.primes = chunk_primes_v35(SPEC_INPUT, PROBE, cls.n_every, N_CHUNKS,
                                      tas_time=_TAS_TIME, tas=_TAS)

        serial_out = tmp / "serial.nc"
        r = _run_chunk(SPEC_INPUT, cls.tas_file, serial_out, 1, cls.n_records)
        if r.returncode != 0:
            raise RuntimeError(_fail_from("serial --_run-chunk worker", r))
        cls.serial = serial_out

        def _make_chunks(primed: bool) -> list[Path]:
            out_dir = tmp / ("primed" if primed else "bare")
            out_dir.mkdir()
            paths = []
            for i in range(1, N_CHUNKS + 1):
                start = (i - 1) * cls.n_every + 1
                if start > cls.n_records:
                    continue
                out = out_dir / f"chunk{i}.nc"
                prime = cls.primes[i - 1] if primed else None
                res = _run_chunk(SPEC_INPUT, cls.tas_file, out, i, cls.n_every, prime=prime)
                if res.returncode != 0:
                    raise RuntimeError(_fail_from(f"chunk {i} worker (primed={primed})", res))
                paths.append(out)
            return paths

        cls.primed_chunks = _make_chunks(True)
        cls.bare_chunks = _make_chunks(False)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_primed_chunks_concatenate_to_the_serial_run_bit_for_bit(self):
        differing = _concat_differs_from_serial(self.serial, self.primed_chunks)
        self.assertEqual(differing, [],
                         "primed --_run-chunk subprocess workers must reproduce the serial "
                         f"worker exactly; differing variables: {differing}")

    def test_the_unprimed_control_actually_disagrees(self):
        """The control this module rests on: without a real seam to prime
        across, the test above would pass on a driver that silently drops the
        prime= token, proving nothing."""
        differing = set(_concat_differs_from_serial(self.serial, self.bare_chunks))
        self.assertTrue(
            differing,
            "an UNPRIMED chunked subprocess run agreed with serial on every variable -- "
            "the fixture has no seam and this module's comparison is not measuring anything")
        self.assertLessEqual(
            differing, {"Time_in_seconds", "int_arrival"},
            f"an unprimed seam changed more than the time accumulation: {sorted(differing)}")

    def test_a_malformed_prime_token_makes_the_worker_exit_nonzero(self):
        out = Path(self.tmp.name) / "malformed.nc"
        res = _run_chunk(SPEC_INPUT, self.tas_file, out, 2, self.n_every,
                         malformed_prime="notafloat,1.0")
        self.assertNotEqual(
            res.returncode, 0,
            "a malformed prime= token must be validated and refused, not fall through to "
            "prime=None and silently write a file indistinguishable from a real primed chunk:\n"
            f"{_fail_from('malformed-prime worker', res)}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
