# SPDX-License-Identifier: BSD-3-Clause
"""A PMS 2DP (probetype 0, 200 um) and a PMS 2DC (25 um) through the batch driver end to end:
``run_flight.main`` with ``--engine 3.5 --profile stock-v3.5 --stages 234`` on a synthetic
RAF/PMS ``.2d`` file, S2 ``read_binary_PMS`` -> S3 ``imgProc_sm`` (v3.5) -> S4 ``sizeDist``
(v3.5), with and without the NCAR 2DC timing-word conversion (``--ncar-2dc-timing``).

No raw data: each file is built here. A record is the 18-byte ``read_binary_PMS`` header
(tag, hour, minute, second, year, month, day, tas, millisec, wkday) and 4096 data bytes laid
out as 1024 four-byte slices, each particle framed ``[FFFFFFFF][top 12 34 p][top 00 00 00]``
then image slices -- ``top`` 0x55 is the form ``imgProc_sm.m:754`` frames, 0xFF the NCAR word
form the ACE-1 RAF records carry (``tests/test_v35_ncar_2dc_timing_words.py``).

* 0x55 form: particles are framed and sized with the conversion at its default (on), which
  leaves a 0x55 record untouched.
* NCAR form, conversion on (the engine-3.5 default): particles are framed and sized.
* NCAR form, ``--ncar-2dc-timing off``: the documented upstream behaviour -- ``imgProc_sm.m:754``
  frames no particle, so S3 writes a proc file with zero particles. S4 then fails: the v3.5
  ``sizeDist`` indexes the empty particle-time vector with ``[true; diff(...)~=0]``
  (``sizeDist.m:816``, ``:829``; ``arrayprobe_uiops.sizedist.resolve_particle_blocks``), an
  IndexError in the port and an index error in MATLAB, and the driver has no zero-particle path
  for S4. Those two tests are ``expectedFailure`` until it gets one (``ZERO_PARTICLE_GAP``).

Every completed run is checked for its proc and sd products and their ``.call`` stamps: each
names ``engine=3.5``, and the proc stamp names ``UIOOPS_v3.5`` and the timing-conversion switch.

The 2DP assigns no ``tasMax`` in ``sizeDist`` (``constants.py``), so its runs pass ``--tas-max``.
PMS S2 writes no ``<stem>.tas.csv``; S4 reads one placed in ``--out`` beforehand.
"""
from __future__ import annotations

import contextlib
import io
import struct
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

try:
    import netCDF4
except ImportError:  # pragma: no cover
    netCDF4 = None

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))
from tests._repo import needs_enhancements  # noqa: E402

import _run_flight_state  # noqa: E402
import run_flight  # noqa: E402
from arrayprobe.tools.make_tas_file import write_tas_csv  # noqa: E402

CAMPAIGNS = """
[[campaign]]
name = "TESTCAMP_2DP"
probe = "2DP"
orientation = "none"
project = "TESTCAMP"
d_choice = 6
sa_method = 0
pres_pa = 86470.0
temp_c = 14.5
provenance = "synthetic preset for tests/test_run_flight_2dp_end_to_end.py"

[[campaign]]
name = "TESTCAMP_2DC"
probe = "2DC"
orientation = "none"
project = "TESTCAMP"
d_choice = 6
sa_method = 0
pres_pa = 86470.0
temp_c = 14.5
provenance = "synthetic preset for tests/test_run_flight_2dp_end_to_end.py"
"""

STEM = "base180101120000"
HOUR, MINUTE, FIRST_SECOND, N_RECORDS = 12, 0, 0, 10
TAS = 100.0
N_PARTICLES = 8
#: Image slices: a 0 bit is a shadowed diode, so this is an 8-pixel particle clear of both
#: array edges (``test_v35_ncar_2dc_timing_words``'s mostly-zero slices touch an edge and are
#: all auto-rejected, accepting nothing in S4). No word is a fix2dimage.pro:9 candidate and
#: none starts with 0x55.
_IMAGE = ((0xFF, 0xE7, 0xFF, 0xFF), (0xFF, 0xC3, 0xFF, 0xFF), (0xFF, 0xE7, 0xFF, 0xFF))
TAGS = {"2DP": b"P1", "2DC": b"C1"}
#: Why the conversion-off tests are expected failures (see the module docstring).
ZERO_PARTICLE_GAP = (
    "driver gap: a zero-particle v3.5 proc file fails S4 with IndexError in "
    "arrayprobe_uiops.sizedist.resolve_particle_blocks (sizeDist.m:816/:829 index an empty "
    "time vector with [true]); run_flight has no zero-particle path for S4")


def _slices(top: int) -> np.ndarray:
    rows: list[tuple[int, int, int, int]] = []
    for p in range(N_PARTICLES):
        rows.append((255, 255, 255, 255))
        rows.append((top, 0x12, 0x34, p + 1))
        rows.append((top, 0, 0, 0))
        rows.extend(_IMAGE)
    rows.append((255, 255, 255, 255))
    rows.extend([(0, 0, 0, 1)] * (1024 - len(rows)))
    return np.asarray(rows, dtype=np.uint8)


def _write_raw(path: Path, tag: bytes, top: int) -> None:
    # read_binary_PMS reshapes the 4096 bytes column-major to 4 x 1024, so slice k is
    # bytes 4k..4k+3: the row-major flattening of the 1024 x 4 slice table.
    data = _slices(top).tobytes()
    with open(path, "wb") as fh:
        fh.write(b'<?xml version="1.0"?>\n<OAP>\n</OAP>\n')
        for i in range(N_RECORDS):
            fh.write(tag + struct.pack(">9H", HOUR, MINUTE, FIRST_SECOND + i, 2018, 1, 1,
                                       int(TAS), 0, 1))
            fh.write(data)


def _write_tas(out: Path) -> None:
    secs = np.arange(HOUR * 3600 + MINUTE * 60 - 5, HOUR * 3600 + MINUTE * 60 + N_RECORDS + 5,
                     dtype=np.float64)
    hhmmss = (secs // 3600) * 10000 + ((secs % 3600) // 60) * 100 + secs % 60
    write_tas_csv(out / f"{STEM}.tas.csv", hhmmss, np.full(secs.size, TAS), seconds_of_day=secs)


@unittest.skipUnless(netCDF4 is not None, "netCDF4 absent")
# Every run here is a 2DC/2DP run, whose default-on protective corrections import it.
@needs_enhancements
class PmsEndToEnd(unittest.TestCase):
    def setUp(self):
        _run_flight_state.preserve(self, run_flight)
        self._saved_presets = dict(run_flight.PRESETS)
        self.addCleanup(lambda: (run_flight.PRESETS.clear(),
                                 run_flight.PRESETS.update(self._saved_presets)))
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.presets = self.tmp / "campaigns.toml"
        self.presets.write_text(CAMPAIGNS, encoding="utf-8")

    def _run(self, probe: str, top: int, *extra: str) -> tuple[int, str, Path]:
        raw = self.tmp / f"{STEM}.2d"
        _write_raw(raw, TAGS[probe], top)
        out = self.tmp / "_decoded"
        out.mkdir()
        _write_tas(out)
        args = ["--presets", str(self.presets), "--preset", f"TESTCAMP_{probe}",
                "--engine", "3.5", "--profile", "stock-v3.5", "--stages", "234",
                "--out", str(out), "--yes", *extra, str(raw)]
        if probe == "2DP":
            args[:0] = ["--tas-max", "140"]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = run_flight.main(args)
        return rc, buf.getvalue(), out

    def _proc_and_sd(self, out: Path, probe: str) -> tuple[Path, Path]:
        procs = sorted(p for p in out.glob(f"proc*{STEM}*{probe}*") if p.suffix in (".nc", ".cdf"))
        sds = sorted(p for p in out.glob(f"sd*{STEM}*{probe}*") if p.suffix in (".nc", ".cdf"))
        self.assertEqual(len(procs), 1, sorted(p.name for p in out.iterdir()))
        self.assertEqual(len(sds), 1, sorted(p.name for p in out.iterdir()))
        return procs[0], sds[0]

    @staticmethod
    def _n_particles(proc: Path) -> int:
        with netCDF4.Dataset(str(proc)) as ds:
            return int(ds.dimensions["time"].size)

    @staticmethod
    def _accepted(sd: Path) -> float:
        with netCDF4.Dataset(str(sd)) as ds:
            ds.set_auto_maskandscale(False)
            v = np.asarray(ds.variables["count"][:], dtype=np.float64)
        return float(np.nansum(v[v > 0]))

    def _assert_stamps(self, proc: Path, sd: Path, timing: str, log: str) -> None:
        for product in (proc, sd):
            self.assertTrue(product.exists(), product)
            self.assertTrue(Path(f"{product}.call").exists(), product)
            stamp = run_flight.read_stamp(product)
            self.assertIsNotNone(stamp, product)
            self.assertTrue(stamp.startswith("engine=3.5 "), stamp)
        proc_stamp = run_flight.read_stamp(proc)
        self.assertIn(" software=UIOOPS_v3.5 ", proc_stamp)
        self.assertIn(f" ncar_2dc_timing={timing}", proc_stamp, log)

    def _assert_sized(self, probe: str, top: int, *extra: str) -> None:
        rc, log, out = self._run(probe, top, *extra)
        self.assertEqual(rc, 0, log)
        proc, sd = self._proc_and_sd(out, probe)
        self._assert_stamps(proc, sd, "on:fix2dimage", log)
        self.assertGreater(self._n_particles(proc), 0, log)
        self.assertGreater(self._accepted(sd), 0, log)

    def _assert_nothing_framed(self, probe: str) -> None:
        rc, log, out = self._run(probe, 0xFF, "--ncar-2dc-timing", "off")
        self.assertEqual(rc, 0, log)
        proc, sd = self._proc_and_sd(out, probe)
        self._assert_stamps(proc, sd, "off", log)
        self.assertEqual(self._n_particles(proc), 0, log)
        self.assertEqual(self._accepted(sd), 0, log)

    # -- 2DP (P1, 200 um) --
    def test_2dp_55_form_runs_end_to_end(self):
        self._assert_sized("2DP", 0x55)

    def test_2dp_ncar_form_with_the_conversion_on_is_sized(self):
        self._assert_sized("2DP", 0xFF)

    @unittest.expectedFailure  # ZERO_PARTICLE_GAP
    def test_2dp_ncar_form_with_the_conversion_off_frames_nothing(self):
        self._assert_nothing_framed("2DP")

    # -- 2DC (C1, 25 um) --
    def test_2dc_55_form_runs_end_to_end(self):
        self._assert_sized("2DC", 0x55)

    def test_2dc_ncar_form_with_the_conversion_on_is_sized(self):
        self._assert_sized("2DC", 0xFF)

    @unittest.expectedFailure  # ZERO_PARTICLE_GAP
    def test_2dc_ncar_form_with_the_conversion_off_frames_nothing(self):
        self._assert_nothing_framed("2DC")


if __name__ == "__main__":
    unittest.main()
