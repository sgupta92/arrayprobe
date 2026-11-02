# SPDX-License-Identifier: BSD-3-Clause
r"""`soda2_process_2d.pro:147-172` -- the ASCII/CSV and netCDF PTH
(true-airspeed) readers -- under GDL, **verbatim**, against tiny synthetic
fixtures tracked in `tests/data/` (no campaign data; every file < 1 KB).

The block is not a function of its own: it sits inline in the 742-line
driver. Running the whole driver per case would need a raw SPEC file and
drag every other stage in, so this bank lifts the lines **out of the
vendored file at run time** (`_vendored_block()`: lines 126-127, 129 and
147-172, asserted against their first tokens so a re-vendor that moves them
fails loudly instead of banking the wrong code) into a one-purpose procedure
`pth_block`, written into the temporary directory `run_pro` puts ahead of
the tree. Nothing is edited; the only lines this bank writes itself are the
`op`/`numrecords` set-up (`:49` verbatim) and the prints.

One procedure per case and one GDL process per case, for two measured
reasons: `:150`'s `on_ioerror, bad` needs a label unique in its procedure,
and every `ncdf_*` call leaves GDL 1.1.2 Windows deadlocked in teardown
(`locate.run_pro(sentinel_exit=True)`), so a netCDF case that halts would
otherwise take every later case down with it.

GDL library routines: `STRSPLIT` (`:129`, `:153`) is a library `.pro` in
this build, and `<IDL_DEFAULT>` puts no library directory on `!PATH` (Y3's
finding) -- so it is passed verbatim from the install through
`extra_files`, as `probe_pthdat_hang.py` established.

`op.starttime`/`op.stoptime`/`op.rate` are DOUBLE literals (`idl_double`),
the convention every SODA-2 driver bank uses. `example_batch.pro:7,31` passes
INT `starttime`/`rate`; for the non-negative numerators these readers can
index with, LONG division and DOUBLE-then-truncate give the same subscript
(derived, recorded in the module docstring of `pth_readers.py`).

Run:  .venv/Scripts/python.exe gdl_oracle/run_soda2_pth_readers_bank.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from locate import SODA2_TREE, GDLUnavailable, idl_double, run_pro  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from scrub_paths import scrub_output  # noqa: E402

DATA = Path(__file__).resolve().parents[3] / "tests" / "data"
GOLDEN = DATA / "gdl_soda2_pth_readers_golden.json"
PROCESS_2D = SODA2_TREE / "soda2_process_2d.pro"
GDL_LIB = (Path(os.environ.get("USERPROFILE", "")) / "tools" / "gdl" / "share"
           / "gnudatalanguage" / "lib")

#: Every fixture's bytes, the single source of truth. Text fixtures are
#: written in binary so the line terminators are exactly what is named here.
TEXT_FIXTURES: dict[str, bytes] = {
    # Space-separated, one row a second with a gap at 103: `:156`'s `i:*`
    # forward fill carries 102's value over the gap.
    "soda2_pth_plain.txt":
        b"100 150.5\n101 151.25\n102 152\n104 154.75\n",
    # Header row (a type-conversion error), a non-numeric TAS field on an
    # otherwise good row, TAS 450 (accepted: `:156` bounds at 500, not the
    # 400 the SAVE and netCDF branches use), TAS 0 and -5 (rejected),
    # a single-field row, a blank line, a tab-separated row, an exponent.
    "soda2_pth_mixed.csv":
        b"Time,TAS\n100,150\n101,abc\n102,450\n103,0\n103,-5\n104\n\n"
        b"104\t160\n1.05e2,1.7e2\n",
    # A row before starttime: `:154`'s `> 0` clamps its index to 0 instead of
    # rejecting it, so it overwrites from record 0 -- and a row after the
    # window (`i ge numrecords`) is dropped. Rows out of time order: the
    # last one read wins from its own index onward.
    "soda2_pth_window.csv":
        b"90,111\n102,122\n101,133\n200,144\n",
    # float32 trap: `:153`'s `float()` turns 36001.4999 into 36001.5, which
    # `round()` takes to 36002 -- a DOUBLE parse would give 36001.
    "soda2_pth_float32.txt":
        b"36000 100\n36001.4999 200\n36003.2 300\n",
    # CRLF line terminators.
    "soda2_pth_crlf.csv":
        b"100,150\r\n101,160\r\n102,170\r\n",
    # No terminator on the last line, and leading whitespace.
    "soda2_pth_noeol.txt":
        b"  100 150\n   102   170",
    # Empty file: the first `readf` is an end-of-file I/O error.
    "soda2_pth_empty.txt":
        b"",
    # High-rate rows (several per second): `round()` of each time.
    "soda2_pth_hirate.csv":
        b"100.2,150\n100.5,155\n100.7,160\n101.4,165\n101.5,170\n",
    # NaN / Inf strings in the TAS field.
    "soda2_pth_nan.csv":
        b"100,NaN\n101,150\n102,Inf\n103,160\n",
    # A non-numeric TIME field with a good TAS: does `float('abc')` jump to
    # `bad:` (row skipped) or yield 0 (row clamped to index 0)? And a
    # numeric prefix with trailing junk (`102x`).
    "soda2_pth_badtime.csv":
        b"abc,150\n101,160\n102x,170\n",
    # Every row rejected: `got_pth` is still set to 1 (`:161`).
    "soda2_pth_allbad.csv":
        b"Time,TAS\n100,0\n101,600\n",
    # Number spellings: IDL's `d` exponent, a sign, a leading `.`, a trailing
    # delimiter, a junk THIRD field (does it cost the whole row?), and a
    # C-style hex literal.
    "soda2_pth_exotic.csv":
        b"1.00d2,150\n+101,1.6E2,\n.102e3,-0\n102,175,abc\n"
        b"103 ,  1.7e+2 \n0x68,190\n",
    # `csv_exotic`'s `1.00d2` cannot tell a `d` exponent (100) from a bare
    # prefix (1, clamped to record 0) -- this one can.
    "soda2_pth_dexp.csv":
        b"100,150\n1.02d2,160\n",
    # A NaN time with a good TAS, last: where does `round(NaN)` index?
    "soda2_pth_nantime.csv":
        b"100,150\n102,160\nNaN,155\n",
}


def _write_nc_fixtures() -> dict[str, bytes]:
    """NETCDF3_CLASSIC files built with netCDF4-python, returned as bytes.
    Written to a temporary file then read back, so the bytes (and not a
    library version's choice of padding) are what get tracked."""
    import tempfile

    import numpy as np
    from netCDF4 import Dataset

    out: dict[str, bytes] = {}

    def build(name: str, fill) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / name
            ds = Dataset(p, "w", format="NETCDF3_CLASSIC")
            fill(ds, np)
            ds.close()
            out[name] = p.read_bytes()

    def plain(ds, np):
        # NCAR RAF style: `Time` INT seconds, `TASX` FLOAT. 0, 450 (> 400)
        # and the -32767 fill are all rejected by `:167`; 105 is past stoptime.
        ds.title = "S6 synthetic PTH"
        ds.createDimension("Time", 7)
        t = ds.createVariable("Time", "i4", ("Time",))
        t.units = "seconds since 2016-09-14 00:00:00 +0000"
        v = ds.createVariable("TASX", "f4", ("Time",))
        v.units = "m/s"
        t[:] = np.array([99, 100, 101, 102, 103, 104, 105], dtype=np.int32)
        v[:] = np.array([140, 150, 0, 450, -32767, 170, 180], dtype=np.float32)

    def lowercase(ds, np):
        # `ncdf2sav.pro` upper-cases `varlist` and each variable's name
        # before comparing (its own comment says "case sensitive"), so
        # `time`/`TasX` are read. DOUBLE times on .5: `round()` half away.
        ds.createDimension("time", 4)
        t = ds.createVariable("time", "f8", ("time",))
        v = ds.createVariable("TasX", "f4", ("time",))
        t[:] = np.array([100.5, 101.49, 102.5, 103.0])
        v[:] = np.array([150, 160, 170, 180], dtype=np.float32)

    def packed(ds, np):
        # `ncdf_varget` returns RAW values: `scale_factor` is not applied,
        # so SHORT 1500 is read as TAS 1500 (> 400, rejected) and 150 as 150.
        ds.createDimension("Time", 3)
        t = ds.createVariable("Time", "i4", ("Time",))
        v = ds.createVariable("TASX", "i2", ("Time",))
        v.scale_factor = 0.1
        t[:] = np.array([100, 101, 102], dtype=np.int32)
        v.set_auto_maskandscale(False)
        v[:] = np.array([1500, 150, 1700], dtype=np.int16)

    def duplicate(ds, np):
        # `Time` then `TIME`: the second upper-cases to a tag that already
        # exists and is skipped (`ncdf2sav.pro`, "Skipped duplicate").
        ds.createDimension("n", 3)
        t1 = ds.createVariable("Time", "i4", ("n",))
        t2 = ds.createVariable("TIME", "i4", ("n",))
        v = ds.createVariable("TASX", "f4", ("n",))
        t1[:] = np.array([100, 101, 102], dtype=np.int32)
        t2[:] = np.array([102, 103, 104], dtype=np.int32)
        v[:] = np.array([150, 160, 170], dtype=np.float32)

    def nogood(ds, np):
        # No sample passes `:167` (every TAS >= 400): `where` returns -1
        # with no count checked, so `data.time[good]`/`data.tasx[good]`
        # subscript with -1 -- which element of the out-of-range TAS lands
        # in `pth_tas`, and from which record, is what this case measures.
        ds.createDimension("Time", 3)
        t = ds.createVariable("Time", "i4", ("Time",))
        v = ds.createVariable("TASX", "f4", ("Time",))
        t[:] = np.array([101, 102, 103], dtype=np.int32)
        v[:] = np.array([450, 500, 600], dtype=np.float32)

    def notasx(ds, np):
        # No TASX variable at all: `data.tasx` is not a tag.
        ds.createDimension("Time", 2)
        t = ds.createVariable("Time", "i4", ("Time",))
        t[:] = np.array([100, 101], dtype=np.int32)

    def mismatch(ds, np):
        # TIME (5) and TASX (3) on different dimensions: `:167`'s `and`
        # of arrays of unequal length.
        ds.createDimension("Time", 5)
        ds.createDimension("m", 3)
        t = ds.createVariable("Time", "i4", ("Time",))
        v = ds.createVariable("TASX", "f4", ("m",))
        t[:] = np.array([100, 101, 102, 103, 104], dtype=np.int32)
        v[:] = np.array([150, 160, 170], dtype=np.float32)

    build("soda2_pth_mismatch.nc", mismatch)
    build("soda2_pth_plain.nc", plain)
    build("soda2_pth_lowercase.nc", lowercase)
    build("soda2_pth_packed.nc", packed)
    build("soda2_pth_duplicate.nc", duplicate)
    build("soda2_pth_nogood.nc", nogood)
    build("soda2_pth_notasx.nc", notasx)
    return out


def write_fixtures() -> None:
    """Write every fixture; refuse to overwrite a tracked one that differs."""
    fixtures = dict(TEXT_FIXTURES)
    for name, blob in _write_nc_fixtures().items():
        path = DATA / name
        # netCDF bytes from a library can legitimately differ run to run
        # only if the library changes; a tracked file that reads back the
        # same variables is kept as is (the golden was made from it).
        if path.is_file():
            continue
        fixtures[name] = blob
    for name, blob in fixtures.items():
        path = DATA / name
        if path.is_file() and path.read_bytes() != blob:
            raise SystemExit(f"{path} exists and differs -- fixture drifted; "
                             "investigate before regenerating")
        if not path.is_file():
            path.write_bytes(blob)


@dataclass
class Case:
    name: str
    fixture: str
    starttime: float
    stoptime: float
    rate: float
    note: str = ""


CASES: list[Case] = [
    Case("txt_plain", "soda2_pth_plain.txt", 100, 105, 1,
         "space-separated, gap at 103 carried forward by `:156`'s `i:*`."),
    Case("csv_mixed", "soda2_pth_mixed.csv", 100, 106, 1,
         "header row, a non-numeric TAS field, TAS 450 accepted (bound 500), "
         "0/-5 rejected, a 1-field row, a blank line, a tab, an exponent."),
    Case("csv_window", "soda2_pth_window.csv", 100, 104, 1,
         "a row before starttime clamps to index 0 (`> 0`); one past the "
         "window is dropped; out-of-order rows: last read wins."),
    Case("csv_window_rate2", "soda2_pth_window.csv", 100, 104, 2,
         "the same file at rate 2: (102-100)/2 = 1, (101-100)/2 = 0.5 "
         "truncates to subscript 0."),
    Case("txt_float32", "soda2_pth_float32.txt", 36000, 36004, 1,
         "36001.4999 parses to FLOAT 36001.5, rounds to 36002."),
    Case("csv_crlf", "soda2_pth_crlf.csv", 100, 103, 1,
         "CRLF terminators: does the trailing CR reach `float()`?"),
    Case("txt_noeol", "soda2_pth_noeol.txt", 100, 103, 1,
         "leading whitespace; last line without a terminator."),
    Case("txt_empty", "soda2_pth_empty.txt", 100, 102, 1,
         "empty file: first `readf` hits end of file inside `on_ioerror`."),
    Case("csv_hirate", "soda2_pth_hirate.csv", 100, 102, 1,
         "several rows a second; `round()` half away from zero."),
    Case("csv_nan", "soda2_pth_nan.csv", 100, 104, 1,
         "NaN and Inf TAS strings."),
    Case("csv_badtime", "soda2_pth_badtime.csv", 100, 103, 1,
         "`abc` time with good TAS; `102x` numeric prefix plus junk."),
    Case("csv_allbad", "soda2_pth_allbad.csv", 100, 102, 1,
         "no row accepted, yet `got_pth=1` with an all-zero `pth_tas`."),
    Case("csv_exotic", "soda2_pth_exotic.csv", 100, 104, 1,
         "`d` exponent, sign, leading `.`, trailing comma, junk third "
         "field, hex literal."),
    Case("csv_dexp", "soda2_pth_dexp.csv", 100, 103, 1,
         "`1.02d2`: 102 if `d` is an exponent, clamped to 0 if a prefix."),
    Case("csv_nantime", "soda2_pth_nantime.csv", 100, 104, 1,
         "a NaN time with TAS 155 read last."),
    Case("nc_mismatch", "soda2_pth_mismatch.nc", 100, 104, 1,
         "TIME (5) and TASX (3) of unequal length."),
    Case("nc_plain", "soda2_pth_plain.nc", 100, 104, 1,
         "NCAR-style Time/TASX; 0, 450, -32767 and a past-stoptime sample "
         "rejected by `:167`."),
    Case("nc_lowercase", "soda2_pth_lowercase.nc", 100, 104, 1,
         "`time`/`TasX` still matched (upper-cased compare); DOUBLE .5 times."),
    Case("nc_packed", "soda2_pth_packed.nc", 100, 103, 1,
         "SHORT TASX with scale_factor 0.1: read raw, 1500/1700 rejected."),
    Case("nc_duplicate", "soda2_pth_duplicate.nc", 100, 104, 1,
         "`Time` then `TIME`: the first is kept."),
    Case("nc_nogood", "soda2_pth_nogood.nc", 100, 104, 1,
         "no sample passes `:167` (TAS 450/500/600); `where` returns -1 "
         "unchecked and an out-of-range TAS still reaches `pth_tas`."),
    Case("nc_notasx", "soda2_pth_notasx.nc", 100, 104, 1,
         "no TASX variable: `data.tasx` is not a tag."),
]


def _vendored_block() -> str:
    """Lines 126-127, 129 and 147-172 of the vendored driver, verbatim."""
    lines = PROCESS_2D.read_text(encoding="utf-8", errors="replace").splitlines()
    got = {n: lines[n - 1] for n in (126, 127, 129, 147, 164, 172)}
    assert got[126].strip() == "got_pth=0", got[126]
    assert got[127].strip() == "pth_tas=fltarr(numrecords)", got[127]
    assert got[129].strip().startswith("suffix=(strsplit(op.pth"), got[129]
    assert got[147].strip().startswith("IF (suffix eq 'txt') or (suffix eq 'csv')"), got[147]
    assert got[164].strip().startswith("IF (suffix eq 'nc')"), got[164]
    assert got[172].strip() == "ENDIF", got[172]
    body = [lines[125], lines[126], lines[128], *lines[146:172]]
    return "\n".join(body)


def _block_pro() -> str:
    return ("pro pth_block, op, numrecords, pth_tas, got_pth\n"
            + _vendored_block() + "\nend\n")


_CASE_SCRIPT = """
op={{pth:'{path}', starttime:{st}, stoptime:{sp}, rate:{rate}}}
numrecords=long((op.stoptime-op.starttime)/op.rate + 1)
print, 'BEGIN={name}', format='(A)'
pth_block, op, numrecords, pth_tas, got_pth
print, 'GOT=', got_pth, format='(A,I0)'
print, 'TAS=' + strjoin(string(ulong(pth_tas,0,numrecords), format='(Z08)'), ','), format='(A)'
print, 'TN=' + size(pth_tas,/tname) + ',' + strtrim(string(n_elements(pth_tas)),2), format='(A)'
"""


def _parse(stdout: str) -> dict:
    rec: dict = {}
    for raw in stdout.splitlines():
        line = raw.strip()
        if line.startswith("BEGIN="):
            rec["BEGIN"] = True
        elif line.startswith("GOT="):
            rec["GOT"] = int(line[len("GOT="):])
        elif line.startswith("TAS="):
            rec["TAS"] = line[len("TAS="):].split(",")
        elif line.startswith("TN="):
            rec["TN"] = line[len("TN="):]
    return rec


def main() -> int:
    write_fixtures()
    strsplit = (GDL_LIB / "strsplit.pro").read_text(encoding="utf-8")
    extra = {"pth_block.pro": _block_pro(), "strsplit.pro": strsplit}
    records: list[dict] = []
    for case in CASES:
        path = (DATA / case.fixture).resolve().as_posix()
        script = _CASE_SCRIPT.format(
            path=path, name=case.name, st=idl_double(case.starttime),
            sp=idl_double(case.stoptime), rate=idl_double(case.rate))
        rec: dict = {"name": case.name, "fixture": case.fixture,
                     "starttime": case.starttime, "stoptime": case.stoptime,
                     "rate": case.rate, "note": case.note}
        is_nc = case.fixture.endswith(".nc")
        try:
            stdout, stderr = run_pro(script, timeout=40, extra_files=extra,
                                     sentinel_exit=is_nc)
            timed_out = False
        except GDLUnavailable as exc:
            print(f"GDL unavailable: {exc}")
            return 2
        except subprocess.TimeoutExpired as exc:
            stdout = exc.output or ""
            stderr = exc.stderr or ""
            stdout = stdout if isinstance(stdout, str) else stdout.decode()
            stderr = stderr if isinstance(stderr, str) else stderr.decode()
            timed_out = True
        vals = _parse(stdout)
        if all(k in vals for k in ("GOT", "TAS", "TN")):
            rec.update(status="OK", GOT=vals["GOT"], TAS=vals["TAS"], TN=vals["TN"])
        else:
            rec.update(status="HALTED", timed_out=timed_out,
                       stdout=stdout[-800:], stderr=stderr[-800:])
        print(f"{case.name}: {rec['status']} {rec.get('GOT', '')} {rec.get('TAS', '')}"
              f" {'' if rec['status'] == 'OK' else rec['stderr'][-300:]}")
        records.append(rec)
    ok = sum(1 for r in records if r["status"] == "OK")
    if ok == 0:
        print("refusing to write a golden in which every case failed")
        return 1
    GOLDEN.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {GOLDEN} -- {len(records)} cases, {ok} OK")
    scrub_output(GOLDEN)  # path prefixes -> <repo>, <tmp>, ~
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
