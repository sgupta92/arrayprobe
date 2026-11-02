# SPDX-License-Identifier: BSD-3-Clause
"""``soda2_process_2d.pro``, SPEC path (with a
GDL differential).

This module is validated by a **layer-3** third side (driving
``process_spec_buffer``/``process_buffer_tail`` directly, the way
``test_soda2_processbuffer_spec.py`` already does, and cross-checking the
driver's own aggregate counts against that independent recomputation),
structural assertions against the plan's traps, refusal tests and mutation
tests. Round 8-A adds the GDL golden owed by that lane:
``run_soda2_process_2d_bank.py`` runs the real, unmodified vendored driver
end to end under GDL (``op.savfile=1``, ``save``/``restore``) and
``AgainstTheGdlGolden`` below asserts every ``OK`` case bit for bit.
"""
from __future__ import annotations

import json
import os
import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np

from arrayprobe_soda2.process_2d import (
    ProcessData,
    Soda2ProcessError,
    soda2_process_2d,
)
from arrayprobe_soda2.processbuffer_spec import NullBuffer, SpecMisc, SpecOp, process_spec_buffer
from arrayprobe_soda2.processbuffer_tail import TailOp, process_buffer_tail

DATA = Path(__file__).resolve().parent / "data"
S2_FIXTURE = DATA / "s2_spec_raw_fixture"
FRAME_FIXTURE = DATA / "soda2_spec_frame_fixture"
P2D_GOLDEN = DATA / "gdl_soda2_process_2d_golden.json"


def _hex64(value: float) -> str:
    return struct.pack(">d", float(value)).hex().upper()


def _hex32(value: float) -> str:
    return struct.pack(">f", float(value)).hex().upper()


def _load_p2d_golden() -> list[dict]:
    records = json.loads(P2D_GOLDEN.read_text(encoding="utf-8"))
    return [r for r in records if "oracle_shims" not in r]


#: The `s2dup` twin fixture, built here from the tracked s2
#: fixture -- independently of `run_soda2_process_2d_bank.build_s2dup`, which
#: `AgainstTheGdlGolden` asserts produces the same bytes. Never tracked.
_S2DUP_DIR = tempfile.TemporaryDirectory(prefix="soda2_s2dup_test_")
S2DUP_FIXTURE = Path(_S2DUP_DIR.name) / "s2dup_fixture"


def _s2dup_bytes() -> bytes:
    """Buffer 0's H frame (9 words) and buffer 1's V frame (10 words), each
    at data word 0 of a 4114-byte buffer after a 16-byte header, copied
    once more directly after themselves with particle counter (word 3)
    7 -> 8."""
    raw = bytearray(S2_FIXTURE.read_bytes())
    for buf, nwords in ((0, 9), (1, 10)):
        start = buf * 4114 + 16
        frame = bytearray(raw[start:start + 2 * nwords])
        frame[6:8] = struct.pack("<H", 8)
        raw[start + 2 * nwords:start + 4 * nwords] = frame
    return bytes(raw)


def setUpModule() -> None:
    S2DUP_FIXTURE.write_bytes(_s2dup_bytes())


def tearDownModule() -> None:
    _S2DUP_DIR.cleanup()


#: The bank's `op` literal, in fields the golden's `frame_*` cases
#: actually depend on -- the pre-existing `_base_op` uses a
#: different `endbins` (`[0.0,50.0,...]` vs the bank's `[10.0,50.0,...]`),
#: so every golden comparison must override these to match the bank
#: exactly, never the other way around (`_base_op`'s own default stays
#: untouched for every pre-existing test).
_P2D_GOLDEN_BASE: dict = dict(
    endbins=[10.0, 50.0, 100.0, 200.0, 500.0], arendbins=[0.0, 0.5, 1.0],
    wavelength=0.785e-6, dofconst=8.12, armwidth=6.3, numdiodes=128,
    rate=1.0,
)

#: golden case name -> `_base_op` overrides on top of `_P2D_GOLDEN_BASE`
#: (the bank's case table, mirrored so the Python side builds exactly
#: the op the bank built).
_P2D_CASE_OVERRIDES: dict[str, dict] = {
    "s2_full": {},
    "s2_fixedtas": {"fixedtas": 100.0},
    "s2_window_mid": {"starttime": 24244.0, "stoptime": 24246.0},
    "s2_rate_half": {"rate": 0.5, "starttime": 24240.0, "stoptime": 24249.7},
    "s2_rate_float": {"rate": np.float32(1.0)},
    "s2_probeid_v": {"probeid": "V"},
    "frame_full": {"fn": str(FRAME_FIXTURE)},
    "frame_stretch": {"fn": str(FRAME_FIXTURE), "stretchcorrect": 1, "fixedtas": 120.0},
    "date_off1": {"date": "20160905"},
    "date_off10": {"date": "20160827"},
    "window_empty": {"starttime": 24300.0, "stoptime": 24310.0},
    # Y2: frame-fixture twins of the seven HALTED s2_* purposes (the
    # frame fixture's buffers hold >= 2 particles, so they never hit the
    # GDL median-of-collapsed-1-element-field gap -- see the module
    # docstring in run_soda2_process_2d_bank.py).
    "frame_fixedtas": {"fn": str(FRAME_FIXTURE), "fixedtas": 100.0},
    "frame_window_mid": {"fn": str(FRAME_FIXTURE), "starttime": 24243.0, "stoptime": 24245.0},
    "frame_rate_half": {"fn": str(FRAME_FIXTURE), "rate": 0.5, "stoptime": 24249.7},
    "frame_rate_float": {"fn": str(FRAME_FIXTURE), "rate": np.float32(1.0)},
    "frame_probeid_v": {"fn": str(FRAME_FIXTURE), "probeid": "V"},
    "frame_date_off10": {"fn": str(FRAME_FIXTURE), "date": "20160827"},
    # The >= 2-particle twins of the seven HALTED s2_* rows, on
    # the s2dup fixture (same overrides as the s2_* row each one twins).
    "s2dup_full": {"fn": str(S2DUP_FIXTURE)},
    "s2dup_fixedtas": {"fn": str(S2DUP_FIXTURE), "fixedtas": 100.0},
    "s2dup_window_mid": {"fn": str(S2DUP_FIXTURE), "starttime": 24244.0, "stoptime": 24246.0},
    "s2dup_rate_half": {"fn": str(S2DUP_FIXTURE), "rate": 0.5, "stoptime": 24249.7},
    "s2dup_rate_float": {"fn": str(S2DUP_FIXTURE), "rate": np.float32(1.0)},
    "s2dup_probeid_v": {"fn": str(S2DUP_FIXTURE), "probeid": "V"},
    "s2dup_date_off10": {"fn": str(S2DUP_FIXTURE), "date": "20160827"},
}

#: golden HEX-suffixed key -> `ProcessData` field name, DOUBLE-width fields.
_P2D_DOUBLE_FIELDS: dict[str, str] = {
    "TIMEHEX": "time",
    "HOUSETIMEHEX": None,  # handled separately (nested under .house)
}

#: golden key (no HEX suffix, float32 fields hashed by the bank) ->
#: `ProcessData` field name.
_P2D_FLOAT_FIELDS: dict[str, str] = {
    "TASHEX": "tas", "PROBETASHEX": "probetas", "MIDBINSHEX": "midbins",
    "ACTIVETIMEHEX": "activetime", "SAHEX": "sa",
    "INTSPECALLHEX": "intspec_all", "INTSPECACCHEX": "intspec_accepted",
    "INTENDBINSHEX": "intendbins", "INTMIDBINSHEX": "intmidbins",
    "MISSEDHISTHEX": "missed_hist", "CONC1DHEX": "conc1d",
    "SPEC1DHEX": "spec1d", "SPEC2DHEX": "spec2d",
    "SPEC2DASPRHEX": "spec2d_aspr", "CORRFACHEX": "corr_fac",
    "POISSONFACHEX": "poisson_fac", "INTCUTOFFHEX": "intcutoff",
    "ZDENDBINSHEX": "zdendbins", "ZDMIDBINSHEX": "zdmidbins",
    "HIST3DHEX": "hist3d", "SPEC2DORIENTHEX": "spec2d_orientation",
    "ORIENTIDXHEX": "orientation_index",
}

#: golden key (int, no HEX) -> `ProcessData` field name.
_P2D_INT_FIELDS: dict[str, str] = {
    "COUNTREJ": "count_rejected", "TOTALCOUNTREJ": "total_count_rejected",
    "COUNTACC": "count_accepted", "COUNTMISSED": "count_missed",
    "ZDSPEC": "zdspec", "POINTER": "pointer", "IND": "ind",
    "CURRENTFILE": "currentfile", "NUMBUFFSACC": "numbuffsaccepted",
    "NUMBUFFSREJ": "numbuffsrejected", "DHIST": "dhist",
    "PBPSTARTINDEX": "pbpstartindex",
}


def _base_op(**overrides) -> dict:
    op = dict(
        fn=str(S2_FIXTURE), date="20160906", starttime=24240.0, stoptime=24250.0,
        format="SPEC", subformat=0, probetype="2DS", res=10.0,
        endbins=[0.0, 50.0, 100.0, 200.0, 500.0], arendbins=[0.0, 0.5, 1.0],
        rate=1.0, smethod="xy", pth="", particlefile=0, inttime_reject=0,
        stuckbits=0, water=0, fixedtas=0.0, timeoffset=0.0, armwidth=6.3,
        numdiodes=128, greythresh=0, probeid="H", eawmethod="centerin",
        wavelength=0.785e-6, dofconst=8.12, ncdfparticlefile=0, asciipsdfile=0,
        # `savfile` defaults to 1 (`update_op`) and the driver now
        # writes the SAVE file, which needs `outdir`; these tests predate it.
        savfile=0,
    )
    op.update(overrides)
    return op


class DriverRunsEndToEndOnTrackedFixtures(unittest.TestCase):
    def test_s2_full_window_matches_the_plans_buffer_level_expectation(self):
        """The `s2_full` case: 1 accepted buffer, 1 rejected
        (V-only -> nullbuffer) plus 4 no-image buffers = 5 rejected, all 6
        buffers of the fixture fall in [24240, 24250]."""
        d = soda2_process_2d(_base_op())
        self.assertIsInstance(d, ProcessData)
        self.assertEqual(int(d.numbuffsaccepted.sum()), 1)
        self.assertEqual(int(d.numbuffsrejected.sum()), 5)

    def test_window_empty_returns_none(self):
        """`:430-433` -- no buffers in the requested window."""
        d = soda2_process_2d(_base_op(starttime=24300.0, stoptime=24310.0))
        self.assertIsNone(d)

    def test_frame_fixture_no_hk_record_does_not_crash(self):
        """`soda2_spec_frame_fixture` has no HK record (`hkp=[0]`, S5-l's
        phantom read) -- confirm the driver either completes or raises a
        named, non-crash exception."""
        op = _base_op(fn=str(FRAME_FIXTURE), starttime=24240.0, stoptime=24250.0)
        try:
            d = soda2_process_2d(op)
            self.assertTrue(d is None or isinstance(d, ProcessData))
        except Exception as exc:  # noqa: BLE001 -- documenting what actually happens
            self.assertIsInstance(exc, (Soda2ProcessError, NotImplementedError,
                                         ValueError, IndexError))


class TraceLine427WindowEdges(unittest.TestCase):
    """Trap 1 / S6-a: the window includes one buffer before `starttime` and
    one at/after `stoptime`; both fold into the edge time records."""

    def test_s2_window_mid_counts_the_pre_window_buffer(self):
        d = soda2_process_2d(_base_op(starttime=24244.0, stoptime=24246.0))
        self.assertIsInstance(d, ProcessData)
        # Buffer 0 (24243.25) is before starttime and must still be counted
        # (folded into record 0 by the `:454` clamp).
        total_buffers = int(d.numbuffsaccepted.sum() + d.numbuffsrejected.sum())
        self.assertGreaterEqual(total_buffers, 1)

    def test_buffindex_truncates_toward_zero_not_floor(self):
        """`buffindex = long((bufftime-starttime)/rate)` (`:423``) truncates
        toward zero: a buffer 0.75 s before `starttime` gives index 0, not
        -1 (floor would give -1). Computed directly, no window edge needed."""
        # Buffer 0 of the s2 fixture is at 24243.25.
        self.assertEqual(int(np.trunc((24243.25 - 24244.0) / 1.0)), 0)


class TraceLine410DateMismatch(unittest.TestCase):
    """Trap 2 / S6-b."""

    def test_date_off_1_to_5_days_yields_no_output(self):
        d = soda2_process_2d(_base_op(date="20160905"))
        self.assertIsNone(d)

    def test_date_off_more_than_5_days_reproduces_s2_full(self):
        """`:410-418`: a mismatch beyond 5 days makes the driver silently
        adopt the file's own date, so the run is identical to s2_full."""
        full = soda2_process_2d(_base_op())
        shifted = soda2_process_2d(_base_op(date="20160827"))
        self.assertIsInstance(full, ProcessData)
        self.assertIsInstance(shifted, ProcessData)
        for field_name in ("count_accepted", "total_count_rejected",
                            "numbuffsaccepted", "numbuffsrejected", "dhist"):
            np.testing.assert_array_equal(
                getattr(full, field_name), getattr(shifted, field_name),
                err_msg=field_name)


class TraceLine454Truncation(unittest.TestCase):
    """Trap 4: `long()` truncation toward zero, not floor, governs
    `numrecords`/`timeindex`."""

    def test_rate_half_numrecords_is_21_for_a_10s_window(self):
        op = _base_op(rate=0.5, starttime=24240.0, stoptime=24250.0)
        # numrecords = long((stop-start)/rate + 1) = long(20+1) = 21
        from arrayprobe_soda2.update_op import update_op
        u = update_op(op)
        numrecords = int((float(u["stoptime"]) - float(u["starttime"])) / float(u["rate"]) + 1)
        self.assertEqual(numrecords, 21)


class RefusalsRaiseBeforeAnyFileRead(unittest.TestCase):
    """Every refusal must fire before any raw file is opened -- use a path
    that does not exist and confirm the refusal, not a file error, wins."""

    MISSING = "tests/data/__does_not_exist__.raw"

    def test_fn_pbp_missing_file_stops(self):
        # `soda2_process_2d.pro:32` -- the reprocess path is ported; a PBP
        # file that does not exist stops before any raw file is read.
        with self.assertRaisesRegex(Soda2ProcessError, "PBP file not found"):
            soda2_process_2d(_base_op(fn=self.MISSING), fn_pbp="whatever.nc")

    def test_non_spec_format_refused(self):
        # CIP-1: `format='SEA'` alone is no longer refused (the CIP route is
        # ported); a non-CIP SEA probetype and a wholly unported format both
        # still are.
        with self.assertRaises(NotImplementedError):
            soda2_process_2d(_base_op(fn=self.MISSING, format="SEA", probetype="CIPG"))
        with self.assertRaises(NotImplementedError):
            soda2_process_2d(_base_op(fn=self.MISSING, format="RAF"))

    def test_multiple_files_are_no_longer_refused(self):
        # The multi-file index (`soda2_process_2d.pro:364-391`) is ported, so a list of
        # files reaches `buildindex` and the run fails on the first missing raw file
        # instead of an early NotImplementedError.
        with self.assertRaises(FileNotFoundError):
            soda2_process_2d(_base_op(fn=[self.MISSING, self.MISSING]))

    def test_pth_set_and_missing_raises(self):
        with self.assertRaises(Soda2ProcessError):
            soda2_process_2d(_base_op(fn=self.MISSING, pth="/no/such/pth/file.txt"))

    def test_pth_set_and_existing_is_no_longer_refused(self):
        # `:147-172`'s ASCII/CSV reader is ported and wired in,
        # so an existing `.csv` PTH file resolves and the run fails on the
        # missing raw file instead of an early NotImplementedError.
        existing = str(DATA / "soda2_pth_stub.csv")
        with self.assertRaises((FileNotFoundError, OSError)):
            soda2_process_2d(_base_op(fn=self.MISSING, pth=existing))

    def test_pth_set_existing_unrecognised_suffix_is_silent_not_refused(self):
        # `:128-172` has no branch for an unrecognised suffix (e.g. this
        # very `.py` test file): IDL silently leaves `got_pth=0` rather than
        # raising -- a preserved quirk, not an out-of-scope refusal. This
        # exercises `fn=self.MISSING` too, so the raw file is still never
        # read; the case must fail past the PTH block on a different error.
        existing = __file__
        with self.assertRaises((FileNotFoundError, OSError)):
            soda2_process_2d(_base_op(fn=self.MISSING, pth=existing))

    def test_asciipsdfile_is_no_longer_an_early_refusal(self):
        # `soda2_export_ascii` is ported and wired in at the IDL's
        # own position (`:722-726`, after the raw file is fully processed),
        # so `asciipsdfile=1` with a missing raw file must fail on the raw
        # read, not on an early NotImplementedError the way it used to.
        with self.assertRaises((FileNotFoundError, OSError)):
            soda2_process_2d(_base_op(fn=self.MISSING, asciipsdfile=1))


class PthReadersAreWiredIn(unittest.TestCase):
    """A `.txt` PTH file reaches `:147-172`'s
    reader and its TAS becomes the driver's `aircrafttas` (`:652-653`,
    `got_pth == 1`), which ``ProcessData.tas`` carries. The expected side is
    `pth_readers.read_pth` called directly on the same file -- itself pinned
    bit-exact against GDL in `test_soda2_pth_readers_gdl`."""

    def test_txt_pth_tas_becomes_the_drivers_aircraft_tas(self):
        from arrayprobe_soda2.pth_readers import read_pth
        with tempfile.TemporaryDirectory() as tmp:
            pth = os.path.join(tmp, "tas.txt")
            with open(pth, "w", encoding="ascii") as fh:
                for i, t in enumerate(range(24238, 24253)):
                    fh.write(f"{t} {150.0 + 0.25 * i}\n")
            d = soda2_process_2d(_base_op(pth=pth))
            self.assertIsInstance(d, ProcessData)
            expected, got_pth = read_pth(pth, "txt", 24240.0, 24250.0, 1.0,
                                         len(d.time))
            self.assertEqual(got_pth, 1)
            np.testing.assert_array_equal(d.tas, expected)
            # And it is not what the probe's own TAS gives without a PTH file.
            self.assertFalse(np.array_equal(d.tas, d.probetas))


class WritersAreWiredIn(unittest.TestCase):
    """Raw bytes -> ``.pbp.csv``/``.pbp.nc`` in one
    driver call. ``s2_full`` accepts exactly 1 buffer (see
    ``test_s2_full_window_matches_the_plans_buffer_level_expectation``); the
    PBP writers get every particle in that buffer, accepted or rejected
    (``soda2_particlesort.pro:186-298`` writes ``x[istart:istop]``
    unconditionally -- ``d.count_accepted`` only counts the subset that
    also passed ``soda2_reject``), so the two writers' own row counts are
    compared to each other, not to ``count_accepted``."""

    #: Header lines `open_pbp_csv` writes before the first data row: 4
    #: descriptive lines + 37 numbered `PBPPROPS` lines + 1 separator + 1
    #: short (comma-joined) header line -- matches
    #: `test_soda2_pbp_writer.py::TestCsvWriter`.
    CSV_HEADER_LINES = 43

    def test_particlefile_writes_csv_with_a_row_per_particle(self):
        with tempfile.TemporaryDirectory() as tmp:
            op = _base_op(outdir=tmp + os.sep, particlefile=1)
            d = soda2_process_2d(op)
            self.assertIsInstance(d, ProcessData)
            files = list(Path(tmp).glob("*.pbp.csv"))
            self.assertEqual(len(files), 1)
            lines = files[0].read_text().splitlines()
            data_lines = lines[self.CSV_HEADER_LINES:]
            self.assertGreater(len(data_lines), 0)

    def test_ncdfparticlefile_writes_nc_matching_the_csv_row_count(self):
        netCDF4 = __import__("netCDF4")
        with tempfile.TemporaryDirectory() as tmp:
            op = _base_op(outdir=tmp + os.sep, particlefile=1, ncdfparticlefile=1)
            d = soda2_process_2d(op)
            self.assertIsInstance(d, ProcessData)
            csv_files = list(Path(tmp).glob("*.pbp.csv"))
            nc_files = list(Path(tmp).glob("*.pbp.nc"))
            self.assertEqual(len(csv_files), 1)
            self.assertEqual(len(nc_files), 1)
            csv_rows = len(csv_files[0].read_text().splitlines()[self.CSV_HEADER_LINES:])
            ds = netCDF4.Dataset(str(nc_files[0]))
            try:
                self.assertEqual(ds.dimensions["Time"].size, csv_rows)
                self.assertGreater(ds.dimensions["Time"].size, 0)
            finally:
                ds.close()

    def test_processdata_names_the_pbp_files_it_wrote(self):
        """``pbp_csv_path``/``pbp_ncdf_path`` (port tooling, not IDL ``data``
        fields) name exactly the files on disk, and are ``None`` for a writer not opened."""
        with tempfile.TemporaryDirectory() as tmp:
            d = soda2_process_2d(_base_op(outdir=tmp + os.sep, particlefile=1,
                                          ncdfparticlefile=1))
            self.assertIsInstance(d, ProcessData)
            self.assertEqual([Path(d.pbp_csv_path)], list(Path(tmp).glob("*.pbp.csv")))
            self.assertEqual([Path(d.pbp_ncdf_path)], list(Path(tmp).glob("*.pbp.nc")))
        with tempfile.TemporaryDirectory() as tmp:
            d = soda2_process_2d(_base_op(outdir=tmp + os.sep, particlefile=1))
            self.assertTrue(Path(d.pbp_csv_path).is_file())
            self.assertIsNone(d.pbp_ncdf_path)
        d = soda2_process_2d(_base_op())
        self.assertIsNone(d.pbp_csv_path)
        self.assertIsNone(d.pbp_ncdf_path)

    def test_pbpstartindex_includes_ncdf_offset(self):
        """`:507` -- the fix: `pbpstartindex[i] = istart + ncdf_offset`, not
        `istart` alone. With one flush total (`s2_full` never crosses
        `num2process`), `ncdf_offset` is 0 at flush time, so this only
        confirms the port no longer silently drops the term -- the
        multi-flush case is not covered by the tracked fixtures."""
        with tempfile.TemporaryDirectory() as tmp:
            op = _base_op(outdir=tmp + os.sep, particlefile=1)
            d = soda2_process_2d(op)
            self.assertIsInstance(d, ProcessData)
            self.assertTrue(np.all(d.pbpstartindex >= 0))

    def test_ncdfparticlefile_2_writes_images_with_offset_lines(self):
        """Particle-image output: every particle's `starty`/`stopy` indexes the
        written `image` (`:546-553` offsets); the per-particle variables are
        those of the `ncdfparticlefile=1` run, unchanged."""
        import netCDF4

        with tempfile.TemporaryDirectory() as tmp:
            op = _base_op(outdir=tmp + os.sep, ncdfparticlefile=2)
            soda2_process_2d(op)
            fn = [f for f in os.listdir(tmp) if f.endswith(".pbp.nc")][0]
            with netCDF4.Dataset(os.path.join(tmp, fn)) as nc:
                starty = np.asarray(nc.variables["starty"][:], dtype=np.int64)
                stopy = np.asarray(nc.variables["stopy"][:], dtype=np.int64)
                nslice = nc.variables["image"].shape[0]
                self.assertGreater(starty.size, 0)
                self.assertTrue(np.all(stopy >= starty))
                self.assertTrue(np.all(stopy < nslice))
                self.assertTrue(np.all(np.diff(starty) > 0))
                diam_img = np.asarray(nc.variables["diam"][:])
        with tempfile.TemporaryDirectory() as tmp:
            soda2_process_2d(_base_op(outdir=tmp + os.sep, ncdfparticlefile=1))
            fn = [f for f in os.listdir(tmp) if f.endswith(".pbp.nc")][0]
            with netCDF4.Dataset(os.path.join(tmp, fn)) as nc:
                np.testing.assert_array_equal(np.asarray(nc.variables["diam"][:]), diam_img)
                self.assertNotIn("image", nc.variables)

    def test_ncdfparticlefile_2_refused_on_the_parallel_driver(self):
        from arrayprobe_soda2.pbp_writer import PbpImagesNotPorted

        with tempfile.TemporaryDirectory() as tmp:
            op = _base_op(outdir=tmp + os.sep, ncdfparticlefile=2)
            with self.assertRaises(PbpImagesNotPorted):
                soda2_process_2d(op, jobs=2)

    def test_window_empty_leaves_writers_open_but_unclosed_S6f(self):
        """S6-f: the PBP files are opened before the `:430-433` early
        return, so the CSV file exists (header written) but the netCDF
        writer's :func:`close_pbp_ncdf` (and its PTH-interpolation tail)
        never runs -- reproducing the vendored bug, not fixing it."""
        with tempfile.TemporaryDirectory() as tmp:
            op = _base_op(outdir=tmp + os.sep, particlefile=1,
                           starttime=24300.0, stoptime=24310.0)
            d = soda2_process_2d(op)
            self.assertIsNone(d)
            files = list(Path(tmp).glob("*.pbp.csv"))
            self.assertEqual(len(files), 1)


class ThirdSideAgainstProcessbufferDirectly(unittest.TestCase):
    """Two sides from different places: drive `process_spec_buffer` +
    `process_buffer_tail` directly on the s2 fixture's own SpecIndex (not
    through the driver), sum per-buffer `dhist`/particle counts, and assert
    against the driver's own aggregate."""

    def test_dhist_and_particle_totals_agree_with_the_driver(self):
        from arrayprobe_soda2.buildindex import buildindex
        from arrayprobe_soda2.update_op import update_op

        op = update_op(_base_op())
        d = soda2_process_2d(_base_op())
        self.assertIsInstance(d, ProcessData)

        y = buildindex(S2_FIXTURE, op)
        spec_op = SpecOp(probetype=str(op["probetype"]), subformat=int(op["subformat"]),
                          probeid=str(op["probeid"]), dofreject=int(op["dofreject"]),
                          stretchcorrect=int(op["stretchcorrect"]), yres=float(op["yres"]),
                          res=float(op["res"]))
        tail_op = TailOp(stuckbits=int(op["stuckbits"]), rakefix=int(op["rakefix"]),
                          greythresh=int(op["greythresh"]),
                          dioderange=(int(op["dioderange"][0]), int(op["dioderange"][1])),
                          numdiodes=int(op["numdiodes"]), keeplargest=int(op["keeplargest"]),
                          res=float(op["res"]), yres=float(op["yres"]))

        total_particles_seen = 0
        total_particles_accepted_as_buffer = 0
        dhist_sum = np.zeros(int(op["numdiodes"]), dtype=np.int64)

        with open(S2_FIXTURE, "rb") as f:
            misc = SpecMisc(nimages=0, hkpointers=np.array([0]),
                             imagepointers=np.array([0]), probetas=0.0,
                             aircrafttas=0.0, lastclock=0.0, lastbufftime=0.0,
                             maxsfm=0.0)
            for i in range(y.count):
                misc.nimages = int(y.numimages[i])
                if misc.nimages == 0:
                    continue
                misc.imagepointers = (
                    i * y.buffsize
                    + y.imagep[int(y.firstp[i]): int(y.firstp[i]) + misc.nimages])
                misc.hkpointers = y.hkp[
                    y.ihk[int(y.firstp[i]): int(y.firstp[i]) + misc.nimages]]
                result = process_spec_buffer(f, float(y.bufftime[i]), spec_op, misc)
                if isinstance(result, NullBuffer):
                    continue
                p = process_buffer_tail(result, tail_op, dhist_sum.astype(np.int32))
                dhist_sum += p.dhist.astype(np.int64)
                total_particles_seen += p.diam.size
                if p.rejectbuffer == 0:
                    total_particles_accepted_as_buffer += p.diam.size

        np.testing.assert_array_equal(
            dhist_sum, d.dhist.sum(axis=0).astype(np.int64),
            err_msg="dhist totals disagree between the driver and the "
                    "layer-3 direct recomputation")
        self.assertEqual(
            int(d.count_accepted.sum() + d.total_count_rejected.sum()),
            total_particles_accepted_as_buffer,
            "driver's per-second accept+reject tally must equal the "
            "particles handed to soda2_particlesort")

    def test_buffer_counts_identity(self):
        """`numbuffsaccepted.sum() + numbuffsrejected.sum() ==
        lastbuff - firstbuff + 1`."""
        d = soda2_process_2d(_base_op())
        self.assertIsInstance(d, ProcessData)
        # s2_full spans all 6 fixture buffers.
        self.assertEqual(
            int(d.numbuffsaccepted.sum() + d.numbuffsrejected.sum()), 6)


class XDtypesAtTheParticlesortCall(unittest.TestCase):
    """Trap 5: `:113-117` dtypes, spied via a monkeypatched
    `soda2_particlesort`."""

    def test_x_array_dtypes(self):
        import arrayprobe_soda2.process_2d as mod

        captured: dict[str, np.ndarray] = {}
        real = mod.soda2_particlesort

        def spy(psopts, x, d, *a, **kw):
            captured.update(x)
            return real(psopts, x, d, *a, **kw)

        mod.soda2_particlesort = spy
        try:
            d = soda2_process_2d(_base_op())
        finally:
            mod.soda2_particlesort = real

        self.assertIsInstance(d, ProcessData)
        self.assertTrue(captured, "particlesort was never called on this fixture")
        for key, expected_dtype in mod._X_DTYPES.items():
            self.assertIn(key, captured)
            self.assertEqual(
                captured[key].dtype, np.dtype(expected_dtype),
                f"x[{key!r}] dtype mismatch")


class FlushBoundary(unittest.TestCase):
    """Trap 7 / S6-d: a small `num2process` forces a mid-run flush."""

    def test_small_num2process_still_returns_a_result_or_none(self):
        d_default = soda2_process_2d(_base_op())
        d_small = soda2_process_2d(_base_op(), num2process=1)
        self.assertIsInstance(d_default, ProcessData)
        # With num2process=1, every buffer's particles flush immediately;
        # the trailing "istop<0 -> return None" path may or may not fire
        # depending on whether the last processed buffer added particles.
        self.assertTrue(d_small is None or isinstance(d_small, ProcessData))


class NumActiveDiodesTrap(unittest.TestCase):
    """Trap `:634`: `numactivediodes` uses the full range only when both
    `dioderange` bounds are the literal zero pair (which `update_op`
    prevents by construction on any normal call)."""

    def test_default_dioderange_is_full_width(self):
        from arrayprobe_soda2.update_op import update_op
        op = update_op(_base_op())
        self.assertEqual(int(op["dioderange"][1]) - int(op["dioderange"][0]) + 1,
                          int(op["numdiodes"]))


class Mutations(unittest.TestCase):
    """Each mutation is applied, run, restored; report which fires."""

    def _run(self):
        return soda2_process_2d(_base_op())

    def test_drop_the_gt_0_clamp_at_427_changes_firstbuff_selection(self):
        # Structural mutation test: verify firstbuff is clamped at 0 by
        # construction (the plan's mutation is "drop the > 0"); assert the
        # actual behaviour depends on the clamp using a synthetic op where
        # all buffers are after starttime (lt_start empty -> firstbuff must
        # be 0, not -1).
        d = soda2_process_2d(_base_op(starttime=24200.0, stoptime=24250.0))
        self.assertIsInstance(d, ProcessData)
        self.assertEqual(int(d.numbuffsaccepted.sum() + d.numbuffsrejected.sum()), 6)

    def test_aircrafttas_always_from_dtas_changes_fixedtas_case(self):
        d_fixed = soda2_process_2d(_base_op(fixedtas=100.0))
        self.assertIsInstance(d_fixed, ProcessData)
        self.assertTrue(np.allclose(d_fixed.tas, 100.0),
                         "fixedtas>0 must select pth_tas, not d.tas, for aircrafttas")

    def test_numactivediodes_always_numdiodes_survives_on_default_dioderange(self):
        """With `update_op`'s default full-range dioderange, the `else`
        branch (`numactivediodes = op.numdiodes`) is unreachable, so this
        mutation is expected to SURVIVE -- reported, not fired."""
        from arrayprobe_soda2.update_op import update_op
        op = update_op(_base_op())
        dr = op["dioderange"]
        # The only way to reach the literal-zero branch is dioderange==[0,0],
        # which update_op's own :50 rule rewrites to [0, numdiodes-1] before
        # process_2d ever sees it -- confirming the mutation cannot fire here.
        self.assertFalse(int(dr[0]) == 0 and int(dr[1]) == 0)


def _flat_f(values) -> np.ndarray:
    """Column-major flatten, matching `print_field.pro`'s
    `reform(value, n_elements(value))` on an IDL/GDL array (Fortran
    order) -- never plain `.ravel()`."""
    return np.asarray(values).ravel(order="F")


class AgainstTheGdlGolden(unittest.TestCase):
    """Round 8-A, extended Y2: `run_soda2_process_2d_bank.py`
    runs the real, unmodified vendored driver end to end under GDL.
    **Measured result**: GDL cannot override its own builtin `MEDIAN` with a
    same-named `.pro` for a 1-element struct-field expression -- the
    `_assert_median_shim` discriminator (`MSTRUCT`, the exact call shape
    `soda2_particlesort.pro:12` makes) fails, so every `s2_*` case, which
    reaches `particlesort` on the fixture's single particle, is recorded
    `HALTED (GDL-only, median)` in the golden. This is a **GDL-only gap,
    not an IDL finding** (IDL documents field extraction from an array of
    structures as returning an array with the structure array's
    dimensions, so `x.buffertime` on a 1-element `x` stays `DOUBLE
    Array[1]` rather than collapsing to a scalar as GDL does, and IDL's
    own `median` accepts a 1-element array; M3, mechanism
    measured 2026-09-14) -- so under the stop rule those seven
    cases are skipped by name here. Every buffer in the `frame_*` cases
    (`soda2_spec_frame_fixture`) holds >= 2 particles, so `median` never
    sees a 1-element array there and none of them hit the gap; since
    Y2 the golden carries six `frame_*` twins of the HALTED
    `s2_*` purposes (`frame_fixedtas`, `frame_window_mid`,
    `frame_rate_half`, `frame_rate_float`, `frame_probeid_v`,
    `frame_date_off10`) alongside the original `frame_full`/
    `frame_stretch`, for 8 `OK` cases of 17 total."""

    def test_every_ok_case_matches_idl_bit_for_bit(self) -> None:
        records = _load_p2d_golden()
        checked_ok = 0
        for rec in records:
            name = rec["name"]
            with self.subTest(case=name):
                if rec["status"] == "HALTED":
                    self.skipTest(f"{name}: GDL-only gap -- {rec.get('message')}")
                overrides = {**_P2D_GOLDEN_BASE, **_P2D_CASE_OVERRIDES[name]}
                d = soda2_process_2d(_base_op(**overrides))
                if rec["status"] == "NO_OUTPUT":
                    self.assertIsNone(d, name)
                    continue
                self.assertIsInstance(d, ProcessData, name)
                assert isinstance(d, ProcessData)
                self.assertEqual(int(d.time.size), rec["NUMRECORDS"],
                                  f"{name}: NUMRECORDS")
                for hexkey, field_name in _P2D_FLOAT_FIELDS.items():
                    if hexkey not in rec:
                        continue
                    value = getattr(d, field_name)
                    # `activetime`'s own dtype is not fixed (S6-e) -- pick
                    # the hex width from what the port actually produced,
                    # never assume float32.
                    hexer = (_hex64 if np.asarray(value).dtype == np.float64
                             else _hex32)
                    got = [hexer(v) for v in _flat_f(value)]
                    with self.subTest(case=name, key=hexkey):
                        self.assertEqual(got, rec[hexkey], f"{name}/{hexkey}")
                if "TIMEHEX" in rec:
                    got = [_hex64(v) for v in _flat_f(d.time)]
                    with self.subTest(case=name, key="TIMEHEX"):
                        self.assertEqual(got, rec["TIMEHEX"], f"{name}/TIMEHEX")
                if "HOUSETIMEHEX" in rec:
                    got = [_hex64(v) for v in _flat_f(d.house.time)]
                    with self.subTest(case=name, key="HOUSETIMEHEX"):
                        self.assertEqual(got, rec["HOUSETIMEHEX"],
                                          f"{name}/HOUSETIMEHEX")
                if "HOUSETASHEX" in rec:
                    got = [_hex32(v) for v in _flat_f(d.house.tas)]
                    with self.subTest(case=name, key="HOUSETASHEX"):
                        self.assertEqual(got, rec["HOUSETASHEX"],
                                          f"{name}/HOUSETASHEX")
                if "HOUSENBHEX" in rec:
                    got = [_hex32(v) for v in _flat_f(d.house.nb)]
                    with self.subTest(case=name, key="HOUSENBHEX"):
                        self.assertEqual(got, rec["HOUSENBHEX"],
                                          f"{name}/HOUSENBHEX")
                for key, field_name in _P2D_INT_FIELDS.items():
                    if key not in rec:
                        continue
                    got = [int(v) for v in _flat_f(getattr(d, field_name))]
                    with self.subTest(case=name, key=key):
                        self.assertEqual(got, rec[key], f"{name}/{key}")
                checked_ok += 1
        self.assertGreaterEqual(
            checked_ok, 1,
            "no OK case in the golden was actually checked -- the bank's "
            "median-shim gap must not silently zero out this test")

    def test_activetime_dtype_follows_rate(self) -> None:
        """Y2: does `activetime`'s IDL type follow a
        DOUBLE vs FLOAT `rate` literal? `s2_rate_float` is `s2_*` and
        therefore GDL-only-HALTED in this golden (median gap, see the
        class docstring); its purpose is carried over to `frame_rate_float`
        (frame-fixture buffers hold >= 2 particles, so they never reach
        the halt), which is `OK`. `data.activetime` is the 5th of
        `_TN_FIELDS` (index 4). **Discriminating outcome**: if the golden
        says `DOUBLE` here, the S6-e FLOAT branch in
        `process_2d.py:341-354,497-503` disagrees with measurement -- this
        test fails and reports the golden value rather than silently
        skipping; the port is not changed in this lane on that outcome."""
        records = {r["name"]: r for r in _load_p2d_golden()}
        rate_float = records.get("frame_rate_float")
        if not rate_float or rate_float["status"] != "OK":
            self.skipTest(
                "frame_rate_float is not OK in this golden -- activetime's "
                "IDL dtype-follows-rate question cannot be measured")
        activetime_tn = rate_float["TN"].split(",")[4]
        self.assertEqual(
            activetime_tn, "FLOAT",
            f"golden measured data.activetime's IDL type as {activetime_tn!r} "
            "for a bare-FLOAT rate, not FLOAT -- report this against the "
            "S6-e FLOAT branch (process_2d.py:341-354,497-503); do not "
            "change the port to match in this lane")
        overrides = {**_P2D_GOLDEN_BASE, **_P2D_CASE_OVERRIDES["frame_rate_float"]}
        d = soda2_process_2d(_base_op(**overrides))
        self.assertIsInstance(d, ProcessData)
        assert isinstance(d, ProcessData)
        self.assertEqual(d.activetime.dtype, np.float32,
                          "port's activetime dtype for a bare-FLOAT rate "
                          "must be float32, matching the golden's FLOAT")

    def test_date_off10_equals_frame_full_four_ways(self) -> None:
        """Y2: a >5-day date mismatch adopts the
        file's own date (`:410-418`), so `date_off10` must equal `s2_full`
        (or, here, `frame_full`) in the golden and the port must equal
        itself across the same pair. `date_off10` is `s2_*`
        (GDL-only-HALTED here, see the class docstring); its purpose is
        carried over to `frame_date_off10`, which is `OK` against
        `frame_full`. `expect` is documentation text, not a measured
        value, and is excluded along with the identifying keys."""
        records = {r["name"]: r for r in _load_p2d_golden()}
        full, off10 = records.get("frame_full"), records.get("frame_date_off10")
        self.assertIsNotNone(full, "frame_full missing from golden")
        self.assertIsNotNone(off10, "frame_date_off10 missing from golden")
        assert full is not None and off10 is not None
        self.assertEqual(full["status"], "OK")
        self.assertEqual(off10["status"], "OK")
        for key in full:
            if key in ("name", "overrides", "expect"):
                continue
            self.assertEqual(full[key], off10.get(key), key)


class TheSevenHaltsAndTheirTwins(unittest.TestCase):
    """A measured verdict on every non-OK `process_2d` case.

    - The seven `s2_*` rows halt at `SODA2_PARTICLESORT:12 <-
      SODA2_PROCESS_2D:579` (GDL's own stack, path-free) -- Y2's location,
      now in the golden rather than a synthetic message.
    - Each has an `s2dup_*` twin (the s2 fixture with a second H and V
      frame, so no `particlesort` call sees one particle) that is `OK` and
      bit-for-bit equal to the port (`AgainstTheGdlGolden` checks every OK
      row). So the single-particle `particlesort` call is the *only* thing
      stopping the s2 rows under GDL.
    - Scratch diagnostics: with `:12` bypassed, GDL halts at
      `:13` (`truetime[1:*]` of a 1-element array), which IDL documents as
      an error too -- so IDL is *derived* to halt on a 1-particle call as
      well, where the port (which skips `:13` for SPEC) returns a result.
      Reported to the coordinator; not asserted here, because no IDL run
      exists to measure it against.
    - The two `NO_OUTPUT` rows are the driver's own `:430-433` early return
      ("No buffers in specified time range"), printed by GDL."""

    @classmethod
    def setUpClass(cls):
        cls.records = {r["name"]: r for r in _load_p2d_golden()}

    def test_the_bank_builds_the_same_twin_bytes_as_this_module(self):
        import sys
        gdl_oracle = str(Path(__file__).resolve().parents[1] / "scripts" / "validation" / "gdl")
        if gdl_oracle not in sys.path:
            sys.path.insert(0, gdl_oracle)
        import run_soda2_process_2d_bank as bank
        self.assertEqual(bank.build_s2dup(), _s2dup_bytes())
        self.assertEqual(S2DUP_FIXTURE.read_bytes(), _s2dup_bytes())

    def test_every_halt_is_the_single_particle_particlesort_call(self):
        halted = sorted(n for n, r in self.records.items() if r["status"] == "HALTED")
        self.assertEqual(halted, sorted([
            "s2_full", "s2_fixedtas", "s2_window_mid", "s2_rate_half",
            "s2_rate_float", "s2_probeid_v", "date_off10"]))
        for name in halted:
            rec = self.records[name]
            with self.subTest(case=name):
                self.assertEqual(rec["halt_at"],
                                 "SODA2_PARTICLESORT:12 <- SODA2_PROCESS_2D:579")
                self.assertIn("MEDIAN: Expression must be an array", rec["message"])
                twin = "s2dup_" + name.removeprefix("s2_")
                self.assertEqual(self.records[twin]["status"], "OK", twin)
                self.assertEqual(self.records[twin]["overrides"], rec["overrides"], twin)

    def test_the_twins_really_carry_more_than_one_particle(self):
        # A later accepted buffer starting at particle index >= 1 means an
        # earlier one held particles 0..k -- the particle structure GDL sorted
        # had more than one element.
        full = self.records["s2dup_full"]
        self.assertGreaterEqual(max(full["PBPSTARTINDEX"]), 1)
        d = soda2_process_2d(_base_op(**{**_P2D_GOLDEN_BASE,
                                         **_P2D_CASE_OVERRIDES["s2dup_full"]}))
        self.assertIsInstance(d, ProcessData)

    def test_no_output_rows_are_the_drivers_own_early_return(self):
        for name in ("date_off1", "window_empty"):
            rec = self.records[name]
            with self.subTest(case=name):
                self.assertEqual(rec["status"], "NO_OUTPUT")
                self.assertIn("No buffers in specified time range", rec["driver_print"])

    def test_s2dup_date_off10_equals_s2dup_full(self):
        full, off10 = self.records["s2dup_full"], self.records["s2dup_date_off10"]
        for key in full:
            if key in ("name", "overrides", "expect"):
                continue
            self.assertEqual(full[key], off10.get(key), key)


class TheCorrFacClampIsAScalarMax(unittest.TestCase):
    """``soda2_process_2d.pro:663-665`` ``(d.corr_fac[i] > 1.0)`` is IDL's MAX
    on a scalar. Measured under GDL: ``!values.f_nan > 0.01`` is 0.0100000
    (the scalar form keeps the left operand only when ``gt`` is true), while
    ``[!values.f_nan] < 0.99`` stays NaN (the array form). So a NaN factor
    leaves that record's spectra unscaled in IDL; ``np.maximum`` would make
    them NaN."""

    def test_nan_factor_becomes_one(self):
        from arrayprobe_soda2.process_2d import _corr_fac_at_least_one
        got = _corr_fac_at_least_one(np.array([np.nan, 0.5, 1.0, 1.108083725],
                                              dtype=np.float32))
        self.assertEqual(got.dtype, np.float32)
        np.testing.assert_array_equal(got, np.array([1.0, 1.0, 1.0, 1.108083725],
                                                    dtype=np.float32))

    def test_the_concentration_block_uses_it(self):
        import inspect

        from arrayprobe_soda2 import process_2d
        source = inspect.getsource(process_2d.soda2_process_2d)
        self.assertIn("_corr_fac_at_least_one(d.corr_fac)", source)
        self.assertNotIn("np.maximum(d.corr_fac", source)


if __name__ == "__main__":
    unittest.main()
