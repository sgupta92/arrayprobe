# SPDX-License-Identifier: BSD-3-Clause
"""Build the A15 differential-oracle pair: the SAME 2DC record at two clock times.

**The trick this bank exists for.** ``imgProc_sm.m:886`` writes
``part_hour*10000 + part_min*100 + part_sec`` through ``int8`` accumulators (A15), so
for virtually every real 2DC/2DP/Fast2DC record ``particle_time`` saturates at 127 and the
true value is unrecoverable *from that variable*. There is therefore no MATLAB output
anywhere that carries a corrected ``particle_time`` to check a correction against --
except in one narrow corner of the value space. A15's own text names it: the field reads
correctly when the hour is 0 and the minute is small enough that ``minute*100 + second``
stays under 127.

So this bank builds **two raw files that differ only in the record header's
hour/minute/second**, byte for byte identical otherwise, and runs the real unmodified
``read_binary_PMS.m`` + ``imgProc_sm.m`` over both under Octave:

* ``tests/data/a15_2dc_hour0_octave_golden.nc`` -- header 00:00:58. MATLAB writes ``particle_time``
  as ``[58, 101]``: **the true values**, because nothing saturates.
* ``tests/data/a15_2dc_hour6_octave_golden.nc`` -- header 06:06:58, same particles, same TAS clock
  counts, same image bytes. MATLAB writes ``[127, 127]``.

The correction is then checked in the corner where MATLAB is right (it must reproduce
``[58, 101]`` exactly, from MATLAB's own file) and applied in the corner where it is not
(``[60658, 60701]``). The two goldens differ by exactly ``+60600`` in HHMMSS digit
arithmetic, which is a second, independent way to state the same check.

**Byte layout** is S7c's, unchanged -- see
``scripts/validation/octave/run_s7c_2dc_bank.py`` for its full derivation. The only
edits are the header's hour/minute/second and the second particle's TAS-clock count.

``TAS2_INT = 13_200_000`` with the record's ``tas = 100`` and 2DC's 0.025 mm diode pitch
gives ``part_time2 = 3.3 s`` (``imgProc_sm.m:585``), chosen so the second particle's
accumulation carries seconds over 60 (``58 + 3 = 61 -> :647-648``) and exercises the
minute carry, while keeping ``minute*100 + second = 101`` under int8's ceiling in the
hour-0 file. ``13_200_000 < 2^24``, a real 24-bit count.

**No real 2DC/2DP/Fast2DC campaign file exists on this machine**, which is why this is
synthetic. It is still a real oracle: unmodified MATLAB source, a real interpreter, real
arithmetic -- only the input is hand-built.

Usage, from ``enhancements_uiops/``::

    .venv/Scripts/python.exe scripts/a15_particle_time_bank.py [--octave PATH]

Writes ``tests/data/a15_2dc_{hour0,hour6}_raw_fixture`` and
``tests/data/a15_2dc_{hour0,hour6}_octave_golden.nc``.  All four tracked -- that
directory rather than ``enhancements_uiops/tests/data`` because ``.gitignore``'s ``*.nc`` rule carries
one deliberate exception and it names that path, so a fixture anywhere else is silently
untracked and a fresh clone skips these tests instead of failing.

``--matlab-src`` and ``--out-suffix`` (2026-09-14) let a caller re-point the same
byte layout at a different vendored tree -- e.g.
``--matlab-src UIOPS-v3.5/joefinlon-UIOPS-039be82 --out-suffix _v35`` -- and
:func:`_imgproc_sm_call` reads the tree's own ``imgProc_sm.m`` signature to build the right
call string (v3.5 added two required arguments, ``iQC``/``iNewHabit``, ahead of
``varargin``).  **Measured, not merely planned**: pointed at v3.5, this currently fails
inside ``imgProc_sm.m`` before reaching the ``particle_time`` write at all --
``CGAL_minR: function called with too many inputs`` (v3.5 added a TAS-ratio argument to
``CGAL_minR.cpp`` that the vendored Octave shim does not accept).

**Closed 2026-09-15.** That failure was the bank's own generator, not the
source: the v3.5 banks already solved it (``scripts/validation/octave/run_v35_imgproc_bank.py``,
``_FORWARDER``). For a v3.5 tree this script now does the same -- it writes a one-line
``CGAL_minR.m`` forwarder to the **real** v3.5 MEX (``CGAL_minR_v35.mex``, compiled unmodified
from ``UIOPS-v3.5/joefinlon-UIOPS-039be82/CGAL_minR.cpp`` by ``mkoctfile --mex`` -- recipe in
``scripts/validation/octave/mex_build/README.md``) into a scratch directory placed on the
Octave path ahead of both the tree and the v3.1.4 shim, and runs from that directory with a
copy of the tree's ``version.txt`` (``imgProc_sm.m:285`` opens it relative to the working
directory). So in the v3.5 goldens ``image_diam_minR`` is **MEX-derived**, not shim-derived --
the genuine v3.5 C++ running under Octave. The v3.1.4 run is byte-for-byte the driver it
always was. Writes ``a15_2dc_{hour0,hour6}_v35_octave_golden.nc`` with ``--out-suffix _v35``.
"""

from __future__ import annotations

import argparse
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from scrub_paths import scrub_output  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
import _upstream  # noqa: E402

HERE = Path(__file__).resolve().parent
ENH = HERE.parent
DATA = ENH.parent / "tests" / "data"
MATLAB_SRC = _upstream.source("uiops314")
SHIMS = ENH.parent / "scripts" / "validation" / "octave" / "shims"
MEX_DIR = ENH.parent / "scripts" / "validation" / "octave" / "mex_build"

#: The same forwarder ``run_v35_imgproc_bank.py`` uses: v3.5's ``imgProc_sm.m:1213`` calls
#: ``CGAL_minR(c, handles.tasRatio)``, and the real v3.5 MEX is built under a distinct name so
#: it cannot collide with the v3.1.4 ``CGAL_minR.mex`` in the same directory.
_V35_MINR_FORWARDER = ("function r = CGAL_minR(c, tasRatio)\n"
                       "r = CGAL_minR_v35(c, tasRatio);\nend\n")

DEFAULT_OCTAVE = Path(os.environ.get("LOCALAPPDATA", "")) / (
    r"Programs\GNU Octave\Octave-11.3.0\mingw64\bin\octave-cli.exe"
)

TAG_2DC = (67, 49)          # 'C1'
TAS_HEADER_VALUE = 100      # the record's own 'tas' field
TAS1_INT = 7_000_000        # -> part_time1 = 1.75 s (unused: particle 1 is seeded)
TAS2_INT = 13_200_000       # -> part_time2 = 3.3 s  (carries 58 s over 60)

#: ``(name, hour, minute, second)``.  Same record, two clock times.
CASES = (
    ("hour0", 0, 0, 58),
    ("hour6", 6, 6, 58),
)

#: What ``imgProc_sm.m`` is expected to write, stated here so a rerun that
#: disagrees is loud.  Derived by hand from :604-652 and :886; asserted below
#: against what Octave actually produced.
EXPECTED_PARTICLE_TIME = {
    "hour0": (58, 101),          # true values -- nothing saturates
    "hour6": (127, 127),         # A15: int8 saturation, true values 60658/60701
}
#: The correction's answer, for both files.  ``hour0``'s equals MATLAB's own output.
EXPECTED_CORRECTED = {
    "hour0": (58, 101),
    "hour6": (60658, 60701),
}

#: The same fixture under v3.5.  Not the v3.1.4 values, and the difference is
#: the upstream inconsistent 2DC diode size, not the int8 particle-time collapse: v3.5's ``imgProc_sm.m:141`` sets the 2DC diode to ``ds = 0.03`` mm
#: (v3.1.4 ``:121``: ``0.025``), so the same 13 200 000 TAS-clock count is
#: ``13.2e6/100 * 0.03e-3 = 3.96 s`` (``:866``), not 3.3 s.  Replaying ``:909-935``:
#: ``part_mil = 250 + floor(960) = 1210`` -> seconds +1, ``part_mil = 210``;
#: ``part_sec = 58 + floor(3.96) + 1 = 62`` -> minute +1, ``part_sec = 2``.  So the hour-0
#: file is right at ``[58, 102]`` and the hour-6 file, if A15 survives, reads ``[127, 127]``.
#: First measured by this script, which stopped at hour 0 on the v3.1.4 table before this
#: table existed -- the hand derivation above was then done against the file it wrote.
EXPECTED_PARTICLE_TIME_V35 = {
    "hour0": (58, 102),
    "hour6": (127, 127),         # A15 still present: true values 60658/60702
}
EXPECTED_CORRECTED_V35 = {
    "hour0": (58, 102),
    "hour6": (60658, 60702),
}


def _int24_be(value: int) -> tuple[int, int, int]:
    b = value.to_bytes(3, "big")
    return b[0], b[1], b[2]


def build_payload() -> bytes:
    """S7c's row layout, verbatim -- two particles in one 4096-byte record."""
    rows = np.zeros((1024, 4), dtype=np.uint8)
    rows[2] = [0x00, 0x00, 0x00, 0x01]          # particle 1 image (1 slice)
    rows[3] = [0xFF, 0xFF, 0xFF, 0xFF]          # boundary 1
    rows[4] = [85, *_int24_be(TAS1_INT)]        # header_loc 1
    rows[6] = [0x00, 0x00, 0x00, 0x03]          # particle 2 image slice 1
    rows[7] = [0x00, 0x00, 0x00, 0x07]          # particle 2 image slice 2
    rows[8] = [0xFF, 0xFF, 0xFF, 0xFF]          # boundary 2
    rows[9] = [85, *_int24_be(TAS2_INT)]        # header_loc 2
    payload = rows.tobytes()
    assert len(payload) == 4096
    return payload


def build_raw_fixture(hour: int, minute: int, second: int) -> bytes:
    header = (
        '<?xml version="1.0"?>\n'
        "<OAP>\n"
        "<probe>synthetic A15 2DC fixture -- see enhancements_uiops/tools/"
        "a15_particle_time_bank.py</probe>\n"
        "</OAP>\n"
    ).encode("ascii")
    # _HEADER_FIELDS order: hour, minute, second, year, month, day, tas,
    # millisec, wkday.
    fields = struct.pack(">9H", hour, minute, second, 2016, 9, 2,
                         TAS_HEADER_VALUE, 250, 5)
    record = bytes(TAG_2DC) + fields + build_payload()
    assert len(record) == 4116
    return header + record


def _imgproc_sm_call(matlab_src: Path, decode_base: Path, golden: Path) -> str:
    """The ``imgProc_sm(...)`` call string, adapted to whichever tree is on the path.

    v3.1.4's signature is ``(infile, outfile, probename, n, nEvery, projectname,
    iRectEllipse, iCalcAllDiodeStats, varargin)`` -- 8 named arguments.  v3.5 (applicability
    report; confirmed here by reading ``imgProc_sm.m:1``) added two more ahead of
    ``varargin``: ``iQC`` and ``iNewHabit``, both required with no MATLAB-side
    default.  Detected by reading the vendored tree's own signature line rather than
    assumed from a path name, so pointing ``--matlab-src`` at a third tree fails
    loudly instead of silently calling the wrong arity.
    """
    sig = (matlab_src / "imgProc_sm.m").read_text(encoding="ascii", errors="replace")
    first_line = sig.splitlines()[0]
    base = (f"imgProc_sm('{decode_base.as_posix()}.2dc.cdf', '{golden.as_posix()}', "
            "'2DC', 1, 1, 'TEST', 0, 0")
    if "iQC" in first_line and "iNewHabit" in first_line:
        # v3.5's own vendored defaults (imgProc_sm.m:20-21): 0 = do not QC image,
        # 0 = use existing Holroyd scheme -- the same values scripts/run_flight.py's
        # V35_CALL pins for every default v3.5 run.
        return base + ", 0, 0);\n"
    return base + ");\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--octave", type=Path, default=DEFAULT_OCTAVE)
    ap.add_argument("--matlab-src", type=Path, default=MATLAB_SRC,
                    help="vendored MATLAB tree to run under Octave (default: v3.1.4)")
    ap.add_argument("--out-suffix", default="",
                    help="appended to the fixture/golden stem, e.g. '_v35'")
    args = ap.parse_args(argv)

    if not args.octave.is_file():
        print(f"octave-cli not found at {args.octave}", file=sys.stderr)
        return 2
    for name in ("read_binary_PMS.m", "imgProc_sm.m"):
        if not (args.matlab_src / name).is_file():
            print(f"{name} missing under {args.matlab_src} (UPSTREAM_TREE_ABSENT: set "
                  "ARRAYPROBE_UIOPS314_TREE or pass --matlab-src)", file=sys.stderr)
            return 2
    DATA.mkdir(parents=True, exist_ok=True)
    v35 = _is_v35_tree(args.matlab_src)
    if v35 and not any(MEX_DIR.glob("CGAL_minR_v35.mex*")):
        print(f"CGAL_minR_v35.mex not found in {MEX_DIR} -- build it first "
              "(mex_build/README.md, 'v3.5's CGAL_minR')", file=sys.stderr)
        return 2

    import netCDF4  # noqa: PLC0415 -- only needed to verify, not to build

    with tempfile.TemporaryDirectory() as scratch_dir:
        scratch = Path(scratch_dir)
        if v35:
            (scratch / "CGAL_minR.m").write_text(_V35_MINR_FORWARDER, encoding="ascii")
            shutil.copy2(args.matlab_src / "version.txt", scratch / "version.txt")
        return _run_cases(args, scratch if v35 else None, netCDF4)


def _is_v35_tree(matlab_src: Path) -> bool:
    """A tree whose ``imgProc_sm`` takes ``iQC``/``iNewHabit`` -- read, not assumed from a path."""
    first = (matlab_src / "imgProc_sm.m").read_text(
        encoding="ascii", errors="replace").splitlines()[0]
    return "iQC" in first and "iNewHabit" in first


def _run_cases(args, v35_scratch: Path | None, netCDF4) -> int:
    for name, hour, minute, second in CASES:
        stem = f"a15_2dc_{name}{args.out_suffix}"
        raw = DATA / f"{stem}_raw_fixture"
        golden = DATA / f"{stem}_octave_golden.nc"
        raw.write_bytes(build_raw_fixture(hour, minute, second))

        decode_base = HERE / f"_{stem}_decode_out"
        for suffix in (".2dc.cdf", ".f2dc.cdf", ".2dp.cdf"):
            decode_base.with_name(decode_base.name + suffix).unlink(missing_ok=True)
        golden.unlink(missing_ok=True)

        driver = HERE / f"_{stem}_runner.m"
        driver.write_text(
            "pkg load netcdf;\n"
            "warning('off', 'Octave:possible-matlab-short-circuit-operator');\n"
            f"addpath('{SHIMS.as_posix()}');\n"
            f"addpath('{args.matlab_src.as_posix()}');\n"
            # v3.5 only: the real MEX, then the forwarder ahead of everything (addpath
            # prepends, so the last one added is searched first).
            + (f"addpath('{MEX_DIR.as_posix()}');\n"
               f"addpath('{v35_scratch.as_posix()}');\n" if v35_scratch else "")
            + f"read_binary_PMS('{raw.as_posix()}', '{decode_base.as_posix()}');\n"
            + _imgproc_sm_call(args.matlab_src, decode_base, golden)
            + "disp('done')\n",
            encoding="ascii",
        )
        proc = subprocess.run(
            [str(args.octave), "--no-gui", "--quiet", str(driver)],
            cwd=str(v35_scratch or HERE), capture_output=True, text=True, timeout=180,
        )
        driver.unlink(missing_ok=True)
        sys.stdout.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        for suffix in (".2dc.cdf", ".f2dc.cdf", ".2dp.cdf"):
            decode_base.with_name(decode_base.name + suffix).unlink(missing_ok=True)
        if proc.returncode != 0 or not golden.is_file():
            print(f"octave failed for {name} (exit {proc.returncode})", file=sys.stderr)
            return 1

        with netCDF4.Dataset(golden) as d:
            got = tuple(int(v) for v in np.asarray(d.variables["particle_time"][:]).ravel())
        want = (EXPECTED_PARTICLE_TIME_V35 if v35_scratch else EXPECTED_PARTICLE_TIME)[name]
        print(f"{golden.name}: particle_time = {got} (expected {want})")
        if got != want:
            print("  ** MATLAB disagreed with the hand-derived expectation **",
                  file=sys.stderr)
            return 1

    print("A15 oracle pair written and verified")
    scrub_output(*DATA.glob("a15_2dc_hour*_octave_golden.nc"))  # path prefixes -> <repo>, <tmp>, ~
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
