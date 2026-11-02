# SPDX-License-Identifier: BSD-3-Clause
"""Build the D3c oracle: a probetype-1 proc file whose clock runs backwards once.

**What this measures.**  ``sizeDist.m``'s inter-arrival clock-rollback correction is a
three-way branch on ``probetype`` with only two branches filled
(``uioops_testing/sizeDist.m:726-730``, ``UIOPS-v3.1.4/.../sizeDist.m:852-856`` -- the two
trees are identical here)::

    if 2==probetype
        int_arr(int_arr<-10) = int_arr(int_arr<-10) + (2^32-1)*(res/10^6/tasMax);
    elseif 0==probetype
        int_arr(int_arr<0)   = int_arr(int_arr<0)   + (2^24-1)*(res/10^6/tasMax);
    end
    % no clause for 1==probetype

Two lines later ``:748-749`` marks every remaining negative ``int_arr`` as reject ``'I'``
and zeroes it, so on probetype 1 a backwards clock costs the particle at the jump rather
than being corrected.  The missing probetype-1 rollback correction records this as **read, flagged for
your check**.  This bank turns it into a measurement by running the real, unmodified
``sizeDist.m`` under Octave over a probetype-1 proc file that actually contains one.

**The fixture is synthetic and says so.**  No CIP/PIP flight on this machine is long enough
to roll over anything -- the only probetype-1 fixture is 12 PECAN records, 1,184 particles,
two seconds.  So the rollback is *injected*: ``Time_in_seconds`` has
:data:`ROLLBACK_SECONDS` subtracted from index :data:`ROLLBACK_INDEX` onward, and nothing
else is touched.  That is the exact shape a midnight crossing gives
(``imgProc_sm.m:701`` builds probetype 1's ``Time_in_seconds`` as
``part_hour*3600 + part_min*60 + part_sec + ...`` -- a decoded **time of day**, so 23:59:59
to 00:00:00 is a drop of one day), placed at a particle index chosen to sit well inside the
second one-second block rather than on its edge.

``Time_in_seconds`` is read at exactly one place in the port
(``sizedist.py:946``) and feeds only ``int_arr`` and ``int_arr3``, so the injection has a
bounded, checkable effect and no interaction with the time axis.

**Only the golden is tracked.** The injected proc file is rebuilt on demand by
:func:`build_rollback_proc`, which the test imports from this module rather than
reimplementing -- one copy of the injection, and a bit-exact comparison against the golden
is what proves the rebuild matches the one Octave was given. Regenerating the golden needs
Octave; rebuilding the input needs three lines, so tracking it would be a redundant 282 KB
copy of a file already in the tree.

The golden lives under ``tests/data/`` rather than ``enhancements_uiops/tests/data``
because ``.gitignore``'s ``*.nc`` rule carries one deliberate exception and it names that
path; a fixture anywhere else is silently untracked and a fresh clone skips the test
instead of failing.

Usage, from ``enhancements_uiops/``::

    .venv/Scripts/python.exe scripts/d3c_rollback_bank.py [--octave PATH]

Writes ``tests/data/d3c_pip_rollback_octave_golden.nc``.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

import netCDF4
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from scrub_paths import scrub_output  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
import _upstream  # noqa: E402

HERE = Path(__file__).resolve().parent
ENH = HERE.parent
ROOT = ENH.parent
DATA = ROOT / "tests" / "data"
PORT_DATA = DATA
SHIMS = ROOT / "scripts" / "validation" / "octave" / "shims"
STOCK_TREE = _upstream.source("uiops314")
PRODUCTION_TREE = ROOT / "uioops_testing"

DEFAULT_OCTAVE = Path(os.environ.get("LOCALAPPDATA", "")) / (
    r"Programs\GNU Octave\Octave-11.3.0\mingw64\bin\octave-cli.exe"
)

SOURCE_PROC = PORT_DATA / "s7a_pip_octave_golden.nc"
GOLDEN = DATA / "d3c_pip_rollback_octave_golden.nc"

#: One particle-index into the fixture's second one-second block (which spans
#: indices 317..1183), far from both its edges.
ROLLBACK_INDEX = 700

#: One day.  ``imgProc_sm.m:701`` makes probetype 1's clock a time of day, so this is
#: what a midnight crossing subtracts.
ROLLBACK_SECONDS = 86400.0

# The s7b call, verbatim -- see scripts/validation/octave/run_s7b_sizedist_pip_bank.py
# and tests/test_sizedist_s7b_oracle.py for why each value is what it is.
TIMEHHMMSS = [0, 61338, 61339, 61340, 61341, 61342]
TAS = [95.0] * 6
PRES = [70000.0] * 6
TEMP = [-10.0] * 6

RUNNER_M = """
pkg load netcdf;
pkg load statistics;
warning('off', 'Octave:possible-matlab-short-circuit-operator');
addpath('{stock_tree}');
addpath('{production_tree}');
addpath('{shims}');
if exist('{outfile}', 'file') == 2
  delete('{outfile}');
end

timehhmmss = [0; 61338; 61339; 61340; 61341; 61342];
tas   = [95.0; 95.0; 95.0; 95.0; 95.0; 95.0];
pres  = [70000; 70000; 70000; 70000; 70000; 70000];
temp  = [-10.0; -10.0; -10.0; -10.0; -10.0; -10.0];

sizeDist('{infile}', '{outfile}', tas, timehhmmss, 'PIP', 6, 0, pres, temp, ...
         'TEST', '20150620 005009', 'NONE');
disp('done')
"""


def build_rollback_proc(dst) -> dict:
    """Copy the tracked PIP proc fixture to ``dst`` and inject one backwards clock jump.

    Imported by ``enhancements_uiops/tests/test_int_arr_rollback_fix.py`` so the injection has one
    definition. If the rebuild ever stopped matching what Octave was given, the test's
    bit-exact comparison against the tracked golden would fail.
    """
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SOURCE_PROC, dst)
    with netCDF4.Dataset(dst, "a") as ds:
        var = ds.variables["Time_in_seconds"]
        var.set_auto_mask(False)
        tis = np.asarray(var[:], dtype=np.float64).ravel()
        before = tis.copy()
        tis[ROLLBACK_INDEX:] -= ROLLBACK_SECONDS
        var[:] = tis
    return {
        "n": int(before.size),
        "index": ROLLBACK_INDEX,
        "step": ROLLBACK_SECONDS,
        "decreases_before": int(np.count_nonzero(np.diff(before) < 0)),
        "decreases_after": int(np.count_nonzero(np.diff(tis) < 0)),
        "jump": float(tis[ROLLBACK_INDEX] - tis[ROLLBACK_INDEX - 1]),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--octave", type=Path, default=DEFAULT_OCTAVE)
    args = ap.parse_args(argv)

    if not (STOCK_TREE / "sizeDist.m").is_file():
        print(f"UPSTREAM_TREE_ABSENT: no v3.1.4 tree at {STOCK_TREE} "
              "(set ARRAYPROBE_UIOPS314_TREE)", file=sys.stderr)
        return 2
    if not SOURCE_PROC.is_file():
        print(f"missing {SOURCE_PROC}", file=sys.stderr)
        return 2
    if not args.octave.is_file():
        print(f"octave-cli not found at {args.octave}", file=sys.stderr)
        return 2

    work = HERE / "_d3c_rollback_proc.nc"
    info = build_rollback_proc(work)
    print(f"built {work.name}: {info}")

    GOLDEN.unlink(missing_ok=True)
    driver = HERE / "_d3c_runner.m"
    driver.write_text(RUNNER_M.format(
        stock_tree=STOCK_TREE.as_posix(),
        production_tree=PRODUCTION_TREE.as_posix(),
        shims=SHIMS.as_posix(),
        infile=work.as_posix(),
        outfile=GOLDEN.as_posix(),
    ), encoding="ascii")
    proc = subprocess.run([str(args.octave), "--no-gui", "--quiet", str(driver)],
                          cwd=str(HERE), capture_output=True, text=True, timeout=600)
    driver.unlink(missing_ok=True)
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    if proc.returncode != 0 or not GOLDEN.is_file():
        print(f"octave failed (exit {proc.returncode})", file=sys.stderr)
        return 1

    with netCDF4.Dataset(GOLDEN) as ds:
        n = np.nansum(np.asarray(ds.variables["count"][:]))
    print(f"wrote {GOLDEN.name}: total count = {n}")
    work.unlink(missing_ok=True)
    # sizeDist.m also drops a .mat sidecar beside its output; not a fixture.
    for stray in GOLDEN.parent.glob(GOLDEN.stem + "*.mat"):
        stray.unlink()
    scrub_output(GOLDEN)  # path prefixes -> <repo>, <tmp>, ~
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
