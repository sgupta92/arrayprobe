# SPDX-License-Identifier: BSD-3-Clause
"""Build the tracked SEA-reader oracle: run the real ``read_binary_SEA.m`` under
Octave on a real prefix of a 2016 ORACLES ``.sea`` file, and freeze the result.

WHY THE FIXTURE IS LARGER THAN DMT'S OR PMS'S. Real ``.sea`` raw files exist
for every 2016 flight (``2016-und-data/<flight>/.../PostProcessing/*.sea``),
unlike PMS. But the format's own structure puts roughly 12 MB of
administrative/system-status records before the first CIP (image) record
ever appears in this file -- there is no way to reach real image coverage
with a KB-scale prefix the way DMT's fixed-record format allows. 13.64 MB
is the smallest **outer-loop-boundary-aligned** prefix (see below) that
reaches eleven real CIP records.

WHY THE TRUNCATION POINT MATTERS. ``read_binary_SEA.m`` has no guard against
a directory record read landing past EOF mid-inner-loop -- MATLAB errors on
``datatemp(1)`` against an empty array if the file is cut at an arbitrary
byte offset. The source's own EOF handling (the trailing 16-byte
peek-and-rewind, ``:290-297``) only fires cleanly at the *outer* loop's own
boundary. So the prefix length here is not an arbitrary round number: it is
the exact byte offset ``arrayprobe.readers.sea``'s own (bug-fixed) navigation
lands on after completing outer iteration 1951 -- found by running the port
itself over the full real file and recording every outer-loop boundary,
since replicating that arithmetic by hand would just be re-deriving what the
port already computes correctly.

A SECOND, OCTAVE-SPECIFIC ISSUE, SHIMMED. ``read_binary_SEA.m:65`` calls
``netcdf.endDef(f)`` a second time (probably meant ``f1``, which otherwise
never leaves define mode) -- harmless under the real netCDF C library, which
documents a redundant ``nc_enddef`` as a no-op, but Octave's ``netcdf``
package (1.0.20) enforces a stricter check and raises. Confirmed by isolated
repro (two ``endDef`` calls, nothing else, reproduces the identical error).
``octave_oracle/shims/+netcdf/endDef.m`` swallows only that one message from
that one function; every other ``netcdf.*`` call reaches the real package
unmodified. This is flagged, not silently worked around: see the shim's own
docstring for the open MATLAB-vs-Octave
question it leaves unresolved without a MATLAB licence to check against.

Usage, from the repository root:

    .venv/Scripts/python.exe octave_oracle/run_s6_sea_bank.py [--octave PATH]

Writes ``tests/data/s6_sea_raw_fixture`` and
``tests/data/s6_sea_octave_golden.{cip,2dc}.nc``. All tracked.

EDGE CASES (``--edge-cases``, pass 7 item 1). Three synthetic files built from
the tracked ``tests/data/soda2_sea_cip_fixture.sea`` (no UND bytes, so no
local data is needed), each run through the unmodified ``read_binary_SEA.m``:

- ``f1_short_payload``: the fixture cut at byte 39,395, so the last CIP
  payload is 4,085 bytes. MATLAB dies at ``:110`` (``data1(1:4096)``).
- ``f2_seek_before_bof``: a two-record buffer ``[tag 0, offset 0xFFFF]
  [tag 999, offset 0]`` prepended to the fixture, so ``:285``'s
  ``fseek(fid,doffset2+doffset1,0)`` targets byte 32 - 65535. MATLAB's
  ``fseek`` returns -1 and stays put; the walk continues into the fixture.
- ``f2_seek_past_eof``: the same with ``[tag 0, offset 0][tag 999, offset
  0xFFFF]``, a target past EOF. Same outcome.
- ``f5_*`` (pass 8 item 3): an end of file inside the inner directory loop,
  where ``readDir`` returns a short vector: at a record boundary, mid-record,
  after a 33000/4098 record, and inside a tag-999 record before and after
  its offset field. MATLAB dies in the first four; the last leaves the loop
  normally and finishes with no records.

Writes ``tests/data/s6_sea_edge_octave_golden.npz``: per case the input's
sha256, Octave's exit status, its error line (if any) and, where it finished,
the ``.CIP.cdf`` variables. ``tests/test_sea.py`` rebuilds the bytes with
``edge_case_bytes`` and asserts the port against it. Run on Linux with
``--octave /usr/bin/octave --edge-cases``.

SYNTHETIC (``--synthetic``). The unmodified ``read_binary_SEA.m`` run over the
tracked ``tests/data/sea_raw_synthetic.sea`` (``make_sea_raw_synthetic.py``,
no real input), writing ``tests/data/s6_sea_synthetic_octave_golden.{cip,2dc}.nc``.
Both files are kept because the MATLAB writes both on every run, the ``.2DC``
one empty when the input holds no 2DC records, as this one does.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import _upstream  # noqa: E402
from scrub_paths import scrub_output  # noqa: E402

HERE = Path(__file__).resolve().parent
PORT = HERE.parents[2]
DATA = PORT / "tests" / "data"

DEFAULT_OCTAVE = Path(os.environ.get("LOCALAPPDATA", "")) / (
    r"Programs\GNU Octave\Octave-11.3.0\mingw64\bin\octave-cli.exe"
)

SOURCE_SEA = (
    PORT / "arrayprobe-local-data" / "2016-und-data" / "20160906_1" / "20160906_064017_1"
    / "PostProcessing" / "2016_09_06_06_40_17.sea"
)

# The exact byte offset arrayprobe.readers.sea's own navigation lands on
# after outer-loop iteration 1951 of the real file above -- see the module
# docstring for why this cannot be a round number.
SAFE_PREFIX_BYTES = 13_640_007

RAW_FIXTURE = DATA / "s6_sea_raw_fixture"
GOLDEN_BASE = DATA / "s6_sea_octave_golden"
SYNTHETIC_RAW = DATA / "sea_raw_synthetic.sea"
SYNTHETIC_GOLDEN_BASE = DATA / "s6_sea_synthetic_octave_golden"
SUFFIXES = (".CIP.cdf", ".2DC.cdf")


EDGE_SEED = DATA / "soda2_sea_cip_fixture.sea"
EDGE_GOLDEN = DATA / "s6_sea_edge_octave_golden.npz"
EDGE_CASES = ("f1_short_payload", "f2_seek_before_bof", "f2_seek_past_eof",
              "f5_eof_at_dir_boundary", "f5_eof_mid_dir", "f5_eof_after_cip_dir",
              "f5_eof_mid_999_offset_read", "f5_eof_mid_999_after_offset")
_CIP_VARS = ("year", "month", "day", "hour", "minute", "second", "millisec",
             "wkday", "data")


def _dir(tag: int, offset: int) -> bytes:
    """A 16-byte SEA directory record (``readDir``, ``:305-316``)."""
    return struct.pack("<5H", tag, offset, 0, 0, 0) + bytes(6)


def edge_seed() -> bytes:
    """The zero-time fixture body the edge-case golden was measured on.

    The tracked ``EDGE_SEED`` gained nonzero CIP-1D time fields on 2026-10-04
    for the GDL golden; the edge cases keep the earlier bytes, rebuilt here.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "make_soda2_sea_cip_fixture", DATA / "make_soda2_sea_cip_fixture.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.build(cip1d_time=False)


def edge_case_bytes(case: str, seed: bytes) -> bytes:
    """The synthetic input for one edge case; imported by ``tests/test_sea.py``."""
    if case == "f1_short_payload":
        return seed[:39_395]
    if case == "f2_seek_before_bof":
        return _dir(0, 0xFFFF) + _dir(999, 0) + seed
    if case == "f2_seek_past_eof":
        return _dir(0, 0) + _dir(999, 0xFFFF) + seed
    # F5 (pass 8 item 3): EOF inside the inner directory loop (:86-288).
    # seed[:16] is the fixture's first record, tag 0, read by :78's outer readDir.
    if case == "f5_eof_at_dir_boundary":
        return seed[:16]
    if case == "f5_eof_mid_dir":
        return seed[:16] + _dir(0, 0)[:8]
    if case == "f5_eof_after_cip_dir":
        return seed[:32]  # the fixture's second record is 33000/4098
    if case == "f5_eof_mid_999_offset_read":
        return seed[:16] + _dir(999, 0)[:2]
    if case == "f5_eof_mid_999_after_offset":
        return seed[:16] + _dir(999, 0)[:4]
    raise ValueError(case)


def run_edge_cases(octave: Path, src_m: Path) -> int:
    import netCDF4
    import numpy as np

    seed = edge_seed()
    out: dict = {}
    work = HERE / "_s6_sea_edge_tmp"
    work.mkdir(exist_ok=True)
    try:
        for case in EDGE_CASES:
            body = edge_case_bytes(case, seed)
            infile = work / f"{case}.sea"
            infile.write_bytes(body)
            base = work / f"oct_{case}"
            driver = work / "driver.m"
            driver.write_text(
                "pkg load netcdf\n"
                f"addpath('{(HERE / 'shims').as_posix()}');\n"
                f"addpath('{src_m.parent.as_posix()}');\n"
                f"read_binary_SEA('{infile.as_posix()}', '{base.as_posix()}');\n",
                encoding="ascii",
            )
            proc = subprocess.run([str(octave), "--no-gui", "--quiet", str(driver)],
                                  cwd=str(work), capture_output=True, text=True,
                                  timeout=180)
            lines = proc.stderr.splitlines()
            first = next((i for i, ln in enumerate(lines) if ln.startswith("error:")), None)
            err = [] if first is None else [lines[first]]
            where = [] if first is None else [
                ln.strip() for ln in lines[first:] if "read_binary_SEA at line" in ln]
            out[f"{case}__sha256"] = np.array(hashlib.sha256(body).hexdigest())
            out[f"{case}__exit"] = np.array(proc.returncode)
            out[f"{case}__error"] = np.array(" | ".join(err[:1] + where[:1]))
            print(f"{case}: exit {proc.returncode} {' | '.join(err[:1] + where[:1])}")
            if proc.returncode == 0:
                with netCDF4.Dataset(str(base) + ".CIP.cdf") as ds:
                    for v in _CIP_VARS:
                        out[f"{case}__{v}"] = np.asarray(ds.variables[v][:])
    finally:
        shutil.rmtree(work, ignore_errors=True)
    np.savez_compressed(EDGE_GOLDEN, **out)
    scrub_output(EDGE_GOLDEN)  # path prefixes -> <repo>, <tmp>, ~
    print(f"wrote {EDGE_GOLDEN} ({EDGE_GOLDEN.stat().st_size / 1024:.1f} KiB)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--octave", type=Path, default=DEFAULT_OCTAVE)
    ap.add_argument("--edge-cases", action="store_true",
                    help="build only the synthetic edge-case golden")
    ap.add_argument("--synthetic", action="store_true",
                    help="build only the golden for tests/data/sea_raw_synthetic.sea")
    args = ap.parse_args(argv)

    if not args.octave.is_file():
        print(f"octave-cli not found at {args.octave}", file=sys.stderr)
        return 2
    src_m = _upstream.source("uiops314") / "read_binary_SEA.m"
    if not src_m.is_file():
        print(f"read_binary_SEA.m missing: {src_m}", file=sys.stderr)
        return 2
    if args.edge_cases:
        return run_edge_cases(args.octave, src_m)
    if args.synthetic:
        return run_oracle(args.octave, src_m, SYNTHETIC_RAW, SYNTHETIC_GOLDEN_BASE)
    if not SOURCE_SEA.is_file():
        print(f"source .sea file missing: {SOURCE_SEA}", file=sys.stderr)
        return 2

    with open(SOURCE_SEA, "rb") as fh:
        raw = fh.read(SAFE_PREFIX_BYTES)
    if len(raw) != SAFE_PREFIX_BYTES:
        print("source .sea file shorter than the safe prefix", file=sys.stderr)
        return 2
    RAW_FIXTURE.write_bytes(raw)
    scrub_output(RAW_FIXTURE)  # path prefixes -> <repo>, <tmp>, ~
    rc = run_oracle(args.octave, src_m, RAW_FIXTURE, GOLDEN_BASE)
    if rc == 0:
        print(f"wrote {RAW_FIXTURE} ({RAW_FIXTURE.stat().st_size / 1024:.0f} KiB)")
    return rc


def run_oracle(octave: Path, src_m: Path, raw_path: Path, golden_base: Path) -> int:
    """Run ``read_binary_SEA.m`` on ``raw_path``; move both outputs to ``golden_base``."""
    octave_base = HERE / "_s6_sea_oracle_out"
    for suffix in SUFFIXES:
        p = octave_base.with_name(octave_base.name + suffix)
        if p.exists():
            p.unlink()

    driver = HERE / "_run_s6_sea_oracle_tmp.m"
    driver.write_text(
        "pkg load netcdf\n"
        f"addpath('{(HERE / 'shims').as_posix()}');\n"
        f"addpath('{src_m.parent.as_posix()}');\n"
        f"read_binary_SEA('{raw_path.as_posix()}', '{octave_base.as_posix()}');\n"
        "disp('done')\n",
        encoding="ascii",
    )
    cmd = [str(octave), "--no-gui", "--quiet", str(driver)]
    proc = subprocess.run(cmd, cwd=str(HERE), capture_output=True, text=True, timeout=180)
    driver.unlink()
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)

    missing = [s for s in SUFFIXES if not octave_base.with_name(octave_base.name + s).exists()]
    if proc.returncode != 0 or missing:
        print(f"octave failed (exit {proc.returncode}), missing: {missing}", file=sys.stderr)
        return 1

    for suffix in SUFFIXES:
        src_path = octave_base.with_name(octave_base.name + suffix)
        dst_path = golden_base.with_name(golden_base.name + suffix[:-4].lower() + ".nc")
        shutil.move(str(src_path), str(dst_path))
        print(f"wrote {dst_path} ({dst_path.stat().st_size / 1024:.1f} KiB)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
