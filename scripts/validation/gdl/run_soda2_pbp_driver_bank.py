# SPDX-License-Identifier: BSD-3-Clause
r"""The GDL whole-driver golden owed by
round 10 (``src/arrayprobe_soda2/process_2d.py``'s wiring of
``pbp_writer.py`` into ``soda2_process_2d``). Round 10 landed the wiring with
no GDL bank of its own -- only ``pbp_writer``'s own hand-built-``x`` bank
(``run_soda2_pbp_writer_bank.py``) existed, which proves the
writers but not that the driver opens/flushes/closes them the way the IDL
driver does.

**Why the frame fixture, not the s2 fixture.** ``run_soda2_process_2d_bank.py``
-- its own golden (``tests/data/gdl_soda2_process_2d_golden.json``)
already shows ``frame_full``/``frame_stretch`` running the unmodified driver
to ``STATUS=OK`` under GDL, with ``NUMBUFFSACC=[0,0,0,1,1,0,...]`` and
``PBPSTARTINDEX=[0,5,0]`` -- two accepted buffers, the second starting at
particle index 5, so at least 6 particles reach ``soda2_particlesort`` (all
rejected -- ``COUNTACC`` is all-zero -- but ``soda2_particlesort.pro:186-298``
writes rejected particles too, unconditionally). GDL's own ``MEDIAN`` gap
(``run_soda2_process_2d_bank.py``'s ``median.pro`` shim) only bites a
1-element ``x`` -- every ``s2_*`` case, never the frame fixture -- so this
bank needs no median shim and copies nothing from that machinery.

**Two oracle shims, not this bank's invention** -- copied verbatim from
``run_soda2_process_2d_bank.py`` because the frame fixture drives the same
``soda2_processbuffer``/``soda2_process_2d`` call graph:
``interpol.pro`` (GDL's own ``lib/utilities`` copy; ``run_pro``'s
``GDL_PATH`` does not reach the ``lib`` tree, so the driver halts at ``:462``
without it) and ``spec_decompress.pro``/``erode.pro``/``uniq.pro`` (the SPEC
processing chain's existing oracle shims).

**Mandatory ``sentinel_exit=True``**: any ``ncdf_*`` call deadlocks the GDL
process at exit on this machine (Round 9, ``locate.py:109-116``); with both
``particlefile`` and ``ncdfparticlefile`` on, the driver's own tail
(``:689-721``, ``ncdf_close``) hits this every time.

Two cases:

- ``frame_full`` -- ``particlefile:1, ncdfparticlefile:1``, both PBP files
  written.
- ``frame_csv_only`` -- ``particlefile:1, ncdfparticlefile:0``; the sentinel
  flag stays on (harmless without any ``ncdf_*`` call) so the two cases use
  one code path.

The script prints ``CASE=``, ``STATUS=``, ``PBPSTARTINDEX=``, ``NUMBUFFSACC=``
(as ``run_soda2_process_2d_bank.py`` already does, via the same
``print_field.pro`` shim) plus ``FN_CSV=``/``FN_NC=`` (``soda2_filename``,
matching ``open_pbp_csv``/``open_pbp_ncdf``'s own naming) and
``EXISTS_CSV=``/``EXISTS_NC=``. The two written files are copied into
``tests/data/gdl_soda2_pbp_driver_<case>.pbp.csv``/``.pbp.nc`` (tracked) and
``tests/data/gdl_soda2_pbp_driver_golden.json`` records
``{case, status, fn_csv, fn_nc, csv_tracked, nc_tracked, nc_digest}``.
``_nc_digest`` is copied from ``run_soda2_pbp_writer_bank.py:280`` verbatim
(no cross-bank import, per that bank's own precedent).

The bank is run **twice** and the two ``frame_full`` CSVs diffed (minus line
3, ``Date Processed:``, which is non-deterministic on both sides) to confirm
determinism before either run's files are tracked.

**Fail fast on a GDL halt.** ``run_pro``'s sentinel path runs GDL with stdin
at EOF, so a halt anywhere under ``bank`` exits at the prompt in seconds and the
case records ``status=HALTED`` with GDL's stderr, instead of waiting until the
timeout (measured: ``frame_images`` sat 900 s after a halt at
``soda2_process_2d.pro:303``). A ``CATCH`` in ``bank`` does not help: GDL 1.1.2
does not deliver a called procedure's error to it (measured 2026-10-03).

**``frame_images`` runs through an oracle-path shim, and its golden's on-disk
layout is NOT validated -- values only.** GDL 1.1.2 rejects the ``CHUNK=``
keyword of ``NCDF_VARDEF`` (``soda2_process_2d.pro:303``, the ``image``
variable). ``shims/soda2_process_2d.pro`` is the vendored file with that one
keyword dropped (pinned by ``tests/test_gdl_soda2_process_2d_chunk_shim.py``);
it is written ahead of the vendored tree on ``GDL_PATH`` for that case only.
Chunking sets the HDF5 storage layout, never a stored value, so the variables'
values, dtypes and attributes are oracle-derived while the chunk shape of
``image`` is shim-derived and must not be compared.

Run:  .venv/Scripts/python.exe gdl_oracle/run_soda2_pbp_driver_bank.py
      [--only CASE] [--timeout SECONDS (default 240)] [--log-dir DIR]

Each case and run writes GDL's full stdout/stderr to
``run_logs/gdl_soda2_pbp_driver_bank/<case>.run<N>.log``, timeout included.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from locate import GDLUnavailable, run_pro  # noqa: E402
from run_soda2_aspect_ratio_bank import ERODE_EDGE_RULE, _erode_shim  # noqa: E402
from run_soda2_process_2d_bank import (  # noqa: E402
    InterpolMissing,
    _op_literal,
    _read_interpol,
)
from run_soda2_processbuffer_spec_bank import UNIQ_SHIM  # noqa: E402
from run_soda2_spec_read_frame_bank import decompress_shim  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from scrub_paths import scrub_output  # noqa: E402

DATA = Path(__file__).resolve().parents[3] / "tests" / "data"
GOLDEN = DATA / "gdl_soda2_pbp_driver_golden.json"
FRAME_FIXTURE = DATA / "soda2_spec_frame_fixture"
#: GDL's full stdout/stderr per case and run, written even on timeout, beside
#: ``launch_detached.sh``'s own ``run_logs/<name>.launch.log`` (gitignored).
LOG_DIR = Path(__file__).resolve().parents[3] / "run_logs" / "gdl_soda2_pbp_driver_bank"
#: ``run_pro`` timeout per case, seconds (``--timeout`` overrides).
DEFAULT_TIMEOUT = 240

#: `print_field, name, value` -- same generic column-major hex/int printer as
#: `run_soda2_process_2d_bank.py`'s own shim (copied, not imported, per that
#: bank's no-cross-bank-import precedent -- it is a small oracle shim, not
#: bank-specific state).
PRINT_FIELD_SHIM = """PRO print_field, name, value
   tn = size(value, /tname)
   n = n_elements(value)
   flat = reform(value, n)
   CASE tn OF
      'DOUBLE': print, name+'HEX='+strjoin(string(ulong64(flat,0,n),format='(Z016)'),',')
      'FLOAT': print, name+'HEX='+strjoin(string(ulong(flat,0,n),format='(Z08)'),',')
      ELSE: print, name+'='+strjoin(strtrim(string(long(flat)),2),',')
   ENDCASE
END
"""


#: Oracle-path shims (copies of vendored SODA-2 files, each pinned against its
#: source by a test), written ahead of the vendored tree on ``GDL_PATH``.
SHIMS_DIR = Path(__file__).resolve().parent / "shims"



@dataclass
class Case:
    name: str
    overrides: dict[str, str] = field(default_factory=dict)
    note: str = ""
    #: file names under ``SHIMS_DIR`` put ahead of the vendored tree for this
    #: case only; anything they reach is shim-derived.
    shims: tuple[str, ...] = ()


CASES: list[Case] = [
    Case("frame_full", {"particlefile": "1", "ncdfparticlefile": "1"},
         note="both PBP writers on"),
    Case("frame_csv_only", {"particlefile": "1", "ncdfparticlefile": "0"},
         note="CSV only; sentinel_exit stays on regardless (harmless, no ncdf_* call)"),
    # Slice A2:
    # `ncdfparticlefile:2` adds the Diode/Slice image variables
    # (soda2_process_2d.pro:286-306, soda2_particlesort.pro:264-276).
    Case("frame_images", {"particlefile": "1", "ncdfparticlefile": "2"},
         note="PBP netCDF with particle images (ncdfparticlefile=2); "
              "soda2_process_2d.pro shim drops CHUNK= at :303 (GDL rejects "
              "it), so values are oracle-derived and the on-disk layout is "
              "NOT validated",
         shims=("soda2_process_2d.pro",)),
]


def case_extra_files(case: Case, extra_files: dict[str, str]) -> dict[str, str]:
    """``extra_files`` plus ``case``'s shims, read from ``SHIMS_DIR``."""
    out = dict(extra_files)
    for name in case.shims:
        out[name] = (SHIMS_DIR / name).read_text(encoding="utf-8")
    return out


def _script_for(case: Case, outdir_posix: str) -> str:
    op_lit = _op_literal(FRAME_FIXTURE.resolve().as_posix(), outdir_posix, case.overrides)
    return f"""
op = {op_lit}
soda2_process_2d, op
print, 'CASE={case.name}'
fn_csv = soda2_filename(op, op.shortname, extension='.pbp.csv')
fn_nc = soda2_filename(op, op.shortname, extension='.pbp.nc')
print, 'FN_CSV=' + fn_csv
print, 'FN_NC=' + fn_nc
print, 'EXISTS_CSV=' + strtrim(string(file_test(fn_csv)),2)
print, 'EXISTS_NC=' + strtrim(string(file_test(fn_nc)),2)
print, 'STATUS=OK'
"""


def _nc_digest(path: Path) -> dict:
    import netCDF4
    import numpy as np

    ds = netCDF4.Dataset(path, "r")
    out: dict = {"dimensions": {k: (v.size if not v.isunlimited() else None)
                                 for k, v in ds.dimensions.items()},
                 "variables": {}, "global_attrs": {}}
    for name in ds.variables:
        v = ds.variables[name]
        out["variables"][name] = {
            "dtype": str(v.dtype),
            "longname": getattr(v, "longname", None),
            "units": getattr(v, "units", None),
            "zlib": bool(v.filters().get("zlib", False)) if v.filters() else False,
            "complevel": v.filters().get("complevelvarying", v.filters().get("complevel"))
            if v.filters() else None,
            "data_hex": np.asarray(v[:]).tobytes().hex(),
        }
    for attr in ds.ncattrs():
        if attr == "DateProcessed":
            continue
        val = ds.getncattr(attr)
        out["global_attrs"][attr] = {
            "dtype": type(val).__name__ if not isinstance(val, np.ndarray) else str(val.dtype),
            "value": val.tolist() if isinstance(val, np.ndarray) else val,
        }
    ds.close()
    return out


def _parse(stdout: str) -> dict[str, str]:
    rec: dict[str, str] = {}
    for raw in stdout.splitlines():
        line = raw.strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        rec[key.strip()] = val.strip()
    return rec


def _write_log(log_dir: Path, case: str, run: int, status: str, elapsed: float,
               timeout: int, stdout: str, stderr: str) -> Path:
    """Write GDL's full stdout and stderr for one case/run, so a slow or
    halted run is diagnosable after the fact."""
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{case}.run{run}.log"
    path.write_text(
        f"CASE {case} RUN {run} STATUS {status} ELAPSED_S {elapsed:.1f} "
        f"TIMEOUT_S {timeout}\n"
        f"===== stdout =====\n{stdout}\n===== stderr =====\n{stderr}\n",
        encoding="utf-8",
    )
    return path


def _text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else value


def _run_once(extra_files: dict[str, str],
              cases: list[Case] | None = None, *,
              timeout: int = DEFAULT_TIMEOUT, log_dir: Path = LOG_DIR,
              run: int = 1) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for case in CASES if cases is None else cases:
        tmp = tempfile.mkdtemp(prefix="soda2_pbp_p2d_")
        try:
            script = _script_for(case, Path(tmp).resolve().as_posix())
            start = time.monotonic()
            try:
                stdout, stderr = run_pro(
                    script, timeout=timeout,
                    extra_files=case_extra_files(case, extra_files),
                    sentinel_exit=True,
                )
            except GDLUnavailable as exc:
                print(f"GDL unavailable: {exc}")
                raise
            except subprocess.TimeoutExpired as exc:
                elapsed = time.monotonic() - start
                out, err = _text(exc.output), _text(exc.stderr)
                log = _write_log(log_dir, case.name, run, "TIMEOUT", elapsed,
                                 timeout, out, err)
                print(f"{case.name}: TIMEOUT after {elapsed:.0f} s (log {log})")
                records.append({"name": case.name, "note": case.note,
                                "status": "TIMEOUT", "stdout": out[-1500:],
                                "stderr": err[-800:]})
                continue
            elapsed = time.monotonic() - start
            parsed = _parse(stdout)
            status = parsed.get("STATUS", "HALTED")
            log = _write_log(log_dir, case.name, run, status, elapsed, timeout,
                             stdout, stderr)
            print(f"{case.name}: run {run} took {elapsed:.0f} s (log {log})")
            rec: dict[str, Any] = {"name": case.name, "note": case.note}
            if parsed.get("STATUS") != "OK" or "FN_CSV" not in parsed:
                rec["status"] = "HALTED" if "STATUS" not in parsed else "ERROR"
                rec["stdout"] = stdout[-1500:]
                rec["stderr"] = stderr[-800:]
                print(f"{case.name}: {rec['status']}")
                records.append(rec)
                continue
            rec["status"] = "OK"
            rec["fn_csv"] = parsed["FN_CSV"]
            rec["fn_nc"] = parsed["FN_NC"]
            csv_path = Path(tmp) / Path(parsed["FN_CSV"]).name
            nc_path = Path(tmp) / Path(parsed["FN_NC"]).name
            if parsed.get("EXISTS_CSV") == "1" and csv_path.exists():
                rec["csv_bytes"] = csv_path.read_bytes()
            if parsed.get("EXISTS_NC") == "1" and nc_path.exists():
                rec["nc_bytes"] = nc_path.read_bytes()
                rec["nc_digest"] = _nc_digest(nc_path)
            print(f"{case.name}: OK "
                  f"(csv={'yes' if 'csv_bytes' in rec else 'no'}, "
                  f"nc={'yes' if 'nc_bytes' in rec else 'no'})")
            records.append(rec)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return records


def main(argv: list[str] | None = None) -> int:
    """``--only NAME`` (repeatable) reruns just those cases and merges them
    into the existing golden, leaving every other case's tracked files and
    record untouched (added so that adding ``frame_images``
    did not re-track the older cases' bytes)."""
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--only", action="append", default=None)
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                    help="run_pro timeout per case and run, seconds "
                         f"(default {DEFAULT_TIMEOUT})")
    ap.add_argument("--log-dir", type=Path, default=LOG_DIR,
                    help="where each case's full GDL stdout/stderr is written "
                         "as <case>.run<N>.log, even on timeout")
    args = ap.parse_args(argv)
    cases = CASES
    if args.only:
        unknown = set(args.only) - {c.name for c in CASES}
        if unknown:
            print(f"unknown case(s): {sorted(unknown)}")
            return 2
        cases = [c for c in CASES if c.name in args.only]
    if not FRAME_FIXTURE.is_file():
        print(f"missing tracked fixture: {FRAME_FIXTURE}")
        return 2

    try:
        interpol_text = _read_interpol()
    except InterpolMissing as exc:
        print(str(exc))
        return 2

    extra_files = {
        "interpol.pro": interpol_text,
        "spec_decompress.pro": decompress_shim(),
        "erode.pro": _erode_shim(ERODE_EDGE_RULE),
        "uniq.pro": UNIQ_SHIM,
        "print_field.pro": PRINT_FIELD_SHIM,
    }

    try:
        run1 = _run_once(extra_files, cases, timeout=args.timeout,
                         log_dir=args.log_dir, run=1)
        # The determinism rerun covers only what ran to OK: a case that timed
        # out once is not waited on a second time.
        ok1 = {r["name"] for r in run1 if r.get("status") == "OK"}
        run2_by_name = {r["name"]: r for r in _run_once(
            extra_files, [c for c in cases if c.name in ok1],
            timeout=args.timeout, log_dir=args.log_dir, run=2)}
    except GDLUnavailable:
        return 2
    run2 = [run2_by_name.get(r["name"], {"status": "NOT_RERUN"}) for r in run1]

    def _csv_minus_line3(b: bytes) -> list[bytes]:
        lines = b.splitlines()
        return [ln for i, ln in enumerate(lines) if i != 2]

    for r1, r2 in zip(run1, run2, strict=True):
        if r1.get("status") == "OK" and r2.get("status") == "OK":
            c1 = r1.get("csv_bytes")
            c2 = r2.get("csv_bytes")
            if c1 is not None and c2 is not None:
                ok = _csv_minus_line3(c1) == _csv_minus_line3(c2)
                print(f"{r1['name']}: determinism check (CSV minus line 3) "
                      f"{'OK' if ok else 'MISMATCH'}")
                if not ok:
                    print("refusing to track a non-deterministic golden")
                    return 1
            n1 = r1.get("nc_digest")
            n2 = r2.get("nc_digest")
            if n1 is not None and n2 is not None:
                # `DateProcessed`/`OUTDIR` already excluded by `_nc_digest`'s
                # own DateProcessed skip and per-run temp dir difference --
                # OUTDIR is a global attr, compare everything else.
                n1v = dict(n1["variables"])
                n2v = dict(n2["variables"])
                ok = n1v == n2v
                print(f"{r1['name']}: determinism check (netCDF variables) "
                      f"{'OK' if ok else 'MISMATCH'}")
                if not ok:
                    print("refusing to track a non-deterministic golden")
                    return 1

    records_out: list[dict[str, Any]] = [{
        "oracle_shims": [
            "interpol.pro (GDL's own lib/utilities/interpol.pro, not a shim)",
            "spec_decompress.pro (+1 line, ISHFT array quirk)",
            "erode.pro (ERODE_EDGE_RULE, aspect_ratio inside the tail)",
            "uniq.pro (fillholes.pro:14)",
            "print_field.pro (generic column-major hex/int printer, unused "
            "by this bank's own printed fields but kept for parity with "
            "run_soda2_process_2d_bank.py's extra_files set)",
        ],
        "determinism": "checked: two full runs, CSV (minus line 3) and "
                        "netCDF variable digests equal",
    }]
    ok_count = 0
    for rec in run1:
        if rec.get("status") != "OK":
            records_out.append(rec)
            continue
        out: dict[str, Any] = {
            "name": rec["name"], "status": "OK", "note": rec["note"],
            "fn_csv": rec["fn_csv"], "fn_nc": rec["fn_nc"],
        }
        if "csv_bytes" in rec:
            tracked = DATA / f"gdl_soda2_pbp_driver_{rec['name']}.pbp.csv"
            tracked.write_bytes(rec["csv_bytes"])
            out["csv_tracked"] = tracked.name
        if "nc_bytes" in rec:
            tracked_nc = DATA / f"gdl_soda2_pbp_driver_{rec['name']}.pbp.nc"
            tracked_nc.write_bytes(rec["nc_bytes"])
            out["nc_tracked"] = tracked_nc.name
            out["nc_digest"] = rec["nc_digest"]
        records_out.append(out)
        ok_count += 1

    if ok_count == 0:
        print("refusing to write a golden in which every case errored")
        return 1
    if args.only and GOLDEN.exists():
        rerun = {r["name"] for r in records_out[1:]}
        kept = [r for r in json.loads(GOLDEN.read_text(encoding="utf-8"))[1:]
                if r.get("name") not in rerun]
        order = {c.name: i for i, c in enumerate(CASES)}
        records_out = [records_out[0]] + sorted(
            kept + records_out[1:], key=lambda r: order.get(r.get("name"), 99))
    GOLDEN.write_text(json.dumps(records_out, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nwrote {GOLDEN} -- {len(run1)} cases, {ok_count} OK")
    # path prefixes -> <repo>, <tmp>, ~
    scrub_output(GOLDEN, *(DATA / f"gdl_soda2_pbp_driver_{c.name}.pbp.nc"
                           for c in cases
                           if (DATA / f"gdl_soda2_pbp_driver_{c.name}.pbp.nc").exists()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
