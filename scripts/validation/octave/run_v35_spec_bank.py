# SPDX-License-Identifier: BSD-3-Clause
"""Octave oracle for v3.5's ``read_binary_SPEC.m`` **driver**.

The TAS bank took the TAS machinery, the pure half of this file, and validated it on a
case grid.  What is left is the half a case grid cannot reach: the record loop,
``readRecord``, ``get_img``'s packet walk, the three ``.csv`` sidecar writers and
the netCDF output.  All of it needs a real binary file and a real netCDF writer.

**It does not need a shim, a slice, or a transcription.**  ``read_binary_SPEC.m``
is plain ``fread``/``netcdf.*`` with no MEX and no toolbox, and Octave 11.3.0's
``netcdf`` package (1.0.20) was measured on 2026-09-11 to support everything
v3.5 newly asks of it — ``netcdf.create(..., 'NETCDF4')``, ``defVarDeflate`` and
``defVarFill`` all succeed.  So this bank runs **the whole vendored v3.5 program,
unmodified**, exactly as ``run_s2_spec_bank.py`` does for the v3.1.4 lineage, and
records what it wrote.  That is oracle layer 2 at full strength for this stage.

Two things the harness has to arrange, and both are findings in their own right:

* ``:76-78`` opens ``version.txt`` with a **bare relative path**, so the
  ``Software`` global attribute is a property of the process's working
  directory, not of the installation.  The harness therefore copies the
  vendored ``version.txt`` into a scratch cwd rather than ``cd``-ing into
  ``UIOPS-v3.5/`` — nothing is written into either vendored tree.
* ``:211-213``'s ``system('echo nH nV >> output.txt')`` fires only when an image
  packet declares **both** ``nH~=0`` and ``nV~=0``.  Every packet this bank
  builds is single-channel, so no subprocess is spawned and no stray
  ``output.txt`` appears.  That is the same choice ``run_s2_spec_bank.py`` made.

WHY THE FIXTURE IS SYNTHETIC.  Same two reasons as the v3.1.4 bank: a slice of a
real ``.2DS`` is campaign data and never enters the repository, and a hand-built
file is the only kind that can be made to exercise the rare paths on purpose.
Here that matters more than it did at S2, because the v3.5 deltas live almost
entirely on paths a random gigabyte hits by accident if at all — the TAS gate's
two rejection arms, a record whose hour is >= 24, and a packet marker in the
last four words of a record.

THE CASES
---------

``main``      the whole v3.5 delta surface except the buffer bound, run twice:
              once with no ``varargin`` (no aircraft TAS) and once with
              ``(fltTime, fltTAS)``, which is the only difference between them.
              Ten records; see :func:`build_records` for what each one is for.
``bound``     a second, two-record fixture whose only packet of interest sits at
              word 2045 — inside v3.1.4's ``while iii<=2048`` and outside v3.5's
              ``while iii+4<=2048``.  Run under **both** vendored trees, so the
              bound change is measured as a difference between two real programs
              rather than read off a diff.

Run:  .venv/Scripts/python.exe octave_oracle/run_v35_spec_bank.py
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from netCDF4 import Dataset

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dewrap import OctaveUnavailable, octave_binary  # noqa: E402
from run_s2_spec_bank import (  # noqa: E402
    DATA_WORDS,
    MARKER_2S,
    MARKER_HK,
    build_raw_fixture,
    image_packet,
    mask_packet,
    run_word,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import _upstream  # noqa: E402
from scrub_paths import scrub_output  # noqa: E402

HERE = Path(__file__).resolve().parent
PORT = HERE.parents[2]
ROOT = PORT
DATA = PORT / "tests" / "data"

V35_SRC = _upstream.source("uiops35")
V314_SRC = _upstream.source("uiops314")

MAIN_FIXTURE = DATA / "v35_spec_raw_fixture"
BOUND_FIXTURE = DATA / "v35_spec_bound_raw_fixture"
GOLDEN = DATA / "v35_spec_oracle.json"

#: The aircraft series handed to the second ``main`` run.  Deliberately NOT a
#: superset of the record timestamps: 254410 (the hour-25 record) is absent, so
#: the ``fltTimeInd`` empty branch is exercised, and index 1 is a zero so
#: ``interp_tas``'s repair is exercised end to end rather than only in the TAS bank's
#: own case grid.
FLT_TIME = [64403, 64404, 64405, 64406, 64407, 64408, 64409, 64411, 64412]
FLT_TAS = [100.0, 0.0, 120.0, 130.0, 140.0, 150.0, 160.0, 170.0, 180.0]


def housekeeping_packet(tas, *, n_hol=0, n_vol=0):
    """A v3.5 ``'KH'`` packet: 53 words, of which v3.5 reads **fifteen**.

    v3.1.4 read nine values out of this packet; v3.5 reads six more — the H and
    V end-diode voltages at offsets 2-7, each scaled by ``0.00244140625``
    (``:400-405``).  That literal is exactly ``10 / 4096`` -- a 12-bit converter
    over a 10 V full scale -- so a word that is a small multiple of 512 gives a
    voltage with an exact decimal representation and a formatting difference
    cannot hide behind float noise.

    ``tas`` is bit-cast from a ``single`` at offsets 50/51 exactly as
    ``:389`` does.  ``n_hol``/``n_vol`` drive the new TAS-update gate.
    """
    words = [0] * 53
    words[0] = MARKER_HK
    tas_bits = int(np.float32(tas).view(np.uint32))
    words[49] = (tas_bits >> 16) & 0xFFFF  # buf(iii-1+50)
    words[50] = tas_bits & 0xFFFF  # buf(iii-1+51)
    words[51] = 0x0001  # time, high word
    words[52] = 0x86A0  # time, low word
    words[40] = 11  # nStereo -- READ AT :393 AND NEVER USED, in both releases
    words[41] = 22  # nTWM
    words[42] = 33  # nSCM
    words[43] = n_hol  # nHOL   -- feeds the v3.5 TAS gate
    words[44] = n_vol  # nVOL   -- feeds the v3.5 TAS gate
    words[33] = 66  # nVPD
    words[34] = 77  # nHPD
    words[1] = 512  # vHE1 -> 1.25 V
    words[2] = 1024  # vHE2 -> 2.5  V
    words[3] = 1536  # vHE3 -> 3.75 V
    words[4] = 2048  # vVE1 -> 5.0  V
    words[5] = 2560  # vVE2 -> 6.25 V
    words[6] = 3072  # vVE3 -> 7.5  V
    return words


def build_records():
    """Ten records, each ``(header words, data words)``.

    Every one of them exists to reach a specific v3.5 behaviour:

    0. an H image packet -- the ordinary path, and the reason no golden here is
       all zeros;
    1. a V image packet -- the shared ``iSlice`` counter means H and V cannot be
       decoded independently;
    2. an H packet plus a clean housekeeping packet, TAS 50 -- the TAS gate's
       accept arm, and the first record whose ``tas`` output is not the -999
       initialiser;
    3. the mask packet alone -- ``.MK.csv``, whose nineteen-values-into-twenty
       ``%d`` conversions bug the port preserves for v3.1.4 and which this
       run re-measures against the v3.5 source rather than inferring from the
       diff's silence;
    4. housekeeping with TAS **exactly 170** -- the gate's first reject arm;
    5. housekeeping with a clean-looking TAS 75 but ``nHOL = 1`` -- the gate's
       second reject arm;
    6. housekeeping with TAS 90 and nothing wrong -- the gate accepting a
       *second* time, so "it only ever updates once" would fail;
    7. an H packet **and** a V packet, in a record whose ``hour`` is 25 -- the
       day-rollover clamp at ``:223-225``, which is applied inside the V write
       block only.  Two single-channel packets rather than one dual-channel
       packet, so ``:214``'s ``system('echo ...')`` never fires;
    8. an H packet -- an ordinary record after the clamp, to show ``hour``'s
       mutation does not persist;
    9. an H packet that is **never decoded**, because the loop reads the pair
       (N, N+1), probes one byte for EOF and breaks.  The preserved "last
       record is never a primary" bug, unchanged in v3.5.
    """
    base = [2016, 9, 2, 6, 6, 44, 0, 0]  # year, month, wkday, day, h, m, s, ms

    def header(second, millisec, hour=6):
        h = list(base)
        h[4], h[6], h[7] = hour, second, millisec
        return h

    runs_a = [run_word(10, 5, new_slice=True), run_word(8, 3)]
    runs_b = [run_word(4, 2, new_slice=True), run_word(6, 1),
              run_word(12, 0, new_slice=True)]
    runs_c = [run_word(20, 10, new_slice=True), run_word(15, 5),
              run_word(9, 9, new_slice=True), run_word(3, 40)]

    def h_img(t):
        return image_packet(runs_a, 2, channel="H", t_particle=t)

    return [
        (header(3, 250), h_img(0x0001_0000)),
        (header(4, 100), image_packet(runs_b, 3, channel="V", t_particle=0x0002_0000)),
        (header(5, 500), h_img(0x0003_0000) + housekeeping_packet(50.0)),
        (header(6, 750), mask_packet()),
        (header(7, 125), h_img(0x0004_0000) + housekeeping_packet(170.0)),
        (header(8, 875), h_img(0x0005_0000) + housekeeping_packet(75.0, n_hol=1)),
        (header(9, 0), h_img(0x0006_0000) + housekeeping_packet(90.0)),
        (header(10, 0, hour=25),
         h_img(0x0007_0000)
         + image_packet(runs_c, 4, channel="V", t_particle=0x0008_0000)),
        (header(11, 0), h_img(0x0009_0000)),
        (header(12, 0), h_img(0x000A_0000)),
    ]


#: 1-based word position of the bound fixture's late marker.  v3.1.4 scans
#: ``iii <= 2048`` and reaches it; v3.5 scans ``iii + 4 <= 2048`` and stops four
#: words short, at 2044.  2045 is therefore the FIRST position the two releases
#: disagree about, which is what makes it the right place to put the packet.
LATE_MARKER_POS = 2045


def build_bound_records():
    """Two records whose only difference between releases is the loop bound.

    Record 0 carries an ordinary H packet at its start -- so v3.5's output is
    non-empty and "skipped the late packet" is distinguishable from "produced
    nothing" -- and a second H packet whose marker sits at word
    :data:`LATE_MARKER_POS`.  The late packet's header words and payload run on
    into record 1, which is legitimate: ``get_img`` scans a **two-record**
    4096-word window, so words 2049+ are record 1's data block.

    Record 1 is the file's last, so it is never itself a primary -- the whole
    fixture yields exactly one decode window, and any difference in the output
    is the bound and nothing else.
    """
    base = [2016, 9, 2, 6, 6, 44, 0, 0]

    def header(second):
        h = list(base)
        h[6] = second
        return h

    lead = image_packet(
        [run_word(10, 5, new_slice=True), run_word(8, 3)], 2,
        channel="H", t_particle=0x00B0_0000)

    late_runs = [run_word(30, 20, new_slice=True), run_word(25, 10)]
    late_payload = [*late_runs, 0x00C0, 0x0000]  # runs + the 2-word timestamp
    n_h = len(late_payload)

    # Record 0: lead packet, zero padding, then MARKER at 2045 and the packet's
    # nH / nV / PC words at 2046 / 2047 / 2048 -- the last three words of the
    # record.  nS and the payload spill into record 1.
    r0 = list(lead) + [0] * (DATA_WORDS - len(lead) - 4)
    r0 += [MARKER_2S, n_h, 0, 7]
    assert len(r0) == DATA_WORDS
    assert r0[LATE_MARKER_POS - 1] == MARKER_2S

    r1 = [2] + late_payload  # nS = 2, then the runs and the timestamp
    r1 += [0] * (DATA_WORDS - len(r1))
    assert len(r1) == DATA_WORDS
    return [(header(20), r0), (header(21), r1)]


_DRIVER = """\
pkg load netcdf;
warning('off', 'Octave:possible-matlab-short-circuit-operator');
warning('off', 'all');
addpath('{shims}');
addpath('{src}');
{varargs}
read_binary_SPEC('{raw}', '{stem}'{call_tail});
disp('BANK-OK')
"""


def _run(octave: str, src: Path, raw: Path, stem: Path, *, with_tas: bool):
    """Run one vendored tree's ``read_binary_SPEC`` on ``raw``.

    The scratch cwd holds only a copy of that tree's ``version.txt``; see the
    module docstring for why the cwd is what decides the ``Software`` attribute.
    Returns ``(ok, stdout, stderr)``; ``ok`` false is itself a fidelity fact and
    is recorded, not swallowed.
    """
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        version = src / "version.txt"
        if version.is_file():
            shutil.copy2(version, cwd / "version.txt")
        varargs, call_tail = "", ""
        if with_tas:
            varargs = (
                "fltTime = [" + ", ".join(str(t) for t in FLT_TIME) + "];\n"
                "fltTAS = [" + ", ".join(repr(t) for t in FLT_TAS) + "];\n"
            )
            call_tail = ", fltTime, fltTAS"
        script = cwd / "bank.m"
        script.write_text(
            _DRIVER.format(
                shims=(HERE / "shims").as_posix(),
                src=src.as_posix(),
                raw=raw.as_posix(),
                stem=stem.as_posix(),
                varargs=varargs,
                call_tail=call_tail,
            ),
            encoding="ascii",
        )
        proc = subprocess.run(  # noqa: S603 - fixed binary, generated script
            [octave, "--no-gui", "--quiet", str(script)],
            cwd=str(cwd), capture_output=True, text=True, timeout=900,
        )
    return ("BANK-OK" in proc.stdout), proc.stdout, proc.stderr


def _read_nc(path: Path) -> dict:
    """Everything the file says about itself, in a form a test can compare.

    ``data`` is stored **sparsely** -- the nonzero entries only, as
    ``[time, block, row, value]`` -- because it is 8x1700 per record and
    essentially empty.  Nothing is lost: the shape is recorded alongside it.
    ``filters`` is recorded per variable because v3.5's ``defVarDeflate`` call is
    a claim this bank can measure rather than repeat.
    """
    with Dataset(path, "r") as ds:
        ds.set_auto_maskandscale(False)
        out = {
            "data_model": ds.data_model,
            "dimensions": {n: (len(d), bool(d.isunlimited())) for n, d in ds.dimensions.items()},
            "global_attributes": {n: str(ds.getncattr(n)) for n in ds.ncattrs()},
            "variables": {},
        }
        for name, var in ds.variables.items():
            values = np.asarray(var[:])
            entry = {
                "dtype": str(values.dtype),
                "dimensions": list(var.dimensions),
                "shape": list(values.shape),
                "filters": {k: (bool(v) if isinstance(v, bool) else v)
                            for k, v in (var.filters() or {}).items()},
            }
            if name == "data":
                nz = np.argwhere(values != 0)
                entry["nonzero"] = [[int(i) for i in idx] + [int(values[tuple(idx)])]
                                    for idx in nz]
            else:
                entry["values"] = [float(v) for v in np.atleast_1d(values).ravel()]
            out["variables"][name] = entry
    return out


def _collect(stem: Path, suffixes) -> dict:
    """Read back everything one run wrote: the netCDF files and the sidecars."""
    out: dict = {"netcdf": {}, "sidecars": {}}
    for suffix in suffixes:
        path = Path(str(stem) + suffix)
        if not path.exists():
            continue
        if suffix.endswith(".nc") or suffix.endswith(".cdf"):
            out["netcdf"][suffix] = _read_nc(path)
        else:
            # Read as bytes and decode explicitly: `.MK.csv` has NO line
            # terminator at all, and a text-mode read would hide that.
            out["sidecars"][suffix] = path.read_bytes().decode("ascii")
    return out


_SUFFIXES_V35 = (".H.nc", ".V.nc", ".tas.csv", ".MK.csv", ".NV.csv")
_SUFFIXES_V314 = (".H.cdf", ".V.cdf", ".tas.csv", ".MK.csv", ".NV.csv")


def _clear(stem: Path, suffixes) -> None:
    """The sidecars are opened with ``'a'``; a stale one would silently double.

    ``run_s2_spec_bank.py`` learned this the expensive way -- its first clear
    list was short by ``.NV.csv`` and the next run doubled that golden.
    """
    for suffix in suffixes:
        Path(str(stem) + suffix).unlink(missing_ok=True)


def main() -> int:
    try:
        octave = octave_binary()
    except OctaveUnavailable as exc:
        print(exc, file=sys.stderr)
        return 2
    for src in (V35_SRC, V314_SRC):
        if not (src / "read_binary_SPEC.m").is_file():
            print(f"read_binary_SPEC.m missing under {src}", file=sys.stderr)
            return 2

    MAIN_FIXTURE.write_bytes(build_raw_fixture(build_records()))
    scrub_output(MAIN_FIXTURE)  # path prefixes -> <repo>, <tmp>, ~
    BOUND_FIXTURE.write_bytes(build_raw_fixture(build_bound_records()))
    scrub_output(BOUND_FIXTURE)  # path prefixes -> <repo>, <tmp>, ~
    print(f"wrote {MAIN_FIXTURE.name} ({MAIN_FIXTURE.stat().st_size} B, "
          f"{len(build_records())} records)")
    print(f"wrote {BOUND_FIXTURE.name} ({BOUND_FIXTURE.stat().st_size} B, 2 records)")

    cases: dict[str, dict] = {}
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)

        for name, fixture, with_tas in (
            ("main_no_tas", MAIN_FIXTURE, False),
            ("main_with_tas", MAIN_FIXTURE, True),
        ):
            stem = work / name
            _clear(stem, _SUFFIXES_V35)
            ok, out, err = _run(octave, V35_SRC, fixture, stem, with_tas=with_tas)
            print(f"  {name:16s} v3.5 : {'completed' if ok else 'DIED'}")
            if not ok:
                print(err[-2000:], file=sys.stderr)
                return 1
            cases[name] = {
                "release": "v3.5",
                "fixture": MAIN_FIXTURE.name,
                "varargin": ({"fltTime": FLT_TIME, "fltTAS": FLT_TAS} if with_tas else None),
                **_collect(stem, _SUFFIXES_V35),
            }

        for name, src, suffixes in (
            ("bound_v35", V35_SRC, _SUFFIXES_V35),
            ("bound_v314", V314_SRC, _SUFFIXES_V314),
        ):
            stem = work / name
            _clear(stem, suffixes)
            ok, out, err = _run(octave, src, BOUND_FIXTURE, stem, with_tas=False)
            print(f"  {name:16s}      : {'completed' if ok else 'DIED'}")
            if not ok:
                print(err[-2000:], file=sys.stderr)
                return 1
            cases[name] = {
                "release": "v3.5" if src is V35_SRC else "v3.1.4",
                "fixture": BOUND_FIXTURE.name,
                "varargin": None,
                **_collect(stem, suffixes),
            }

    # THE BANK ASSERTS ITS OWN PREMISE, twice.  Both of these would pass
    # silently while testing nothing if the fixture drifted.
    h35 = cases["bound_v35"]["netcdf"].get(".H.nc", {}).get("variables", {})
    h314 = cases["bound_v314"]["netcdf"].get(".H.cdf", {}).get("variables", {})
    nz35 = h35.get("data", {}).get("nonzero", [])
    nz314 = h314.get("data", {}).get("nonzero", [])
    if not nz35:
        print("REFUSING: v3.5 decoded nothing from the bound fixture; the lead "
              "packet is not reaching the image", file=sys.stderr)
        return 1
    if nz35 == nz314:
        print("REFUSING: both releases decoded the bound fixture identically; "
              f"the marker at word {LATE_MARKER_POS} is no longer in the gap "
              "between the two loop bounds", file=sys.stderr)
        return 1
    if cases["main_no_tas"] == cases["main_with_tas"]:
        print("REFUSING: the aircraft-TAS argument changed nothing; the "
              "tasRatio path is untested", file=sys.stderr)
        return 1

    GOLDEN.write_text(
        json.dumps(
            {
                "fixtures": {
                    MAIN_FIXTURE.name: hashlib.sha256(MAIN_FIXTURE.read_bytes()).hexdigest(),
                    BOUND_FIXTURE.name: hashlib.sha256(BOUND_FIXTURE.read_bytes()).hexdigest(),
                },
                "cases": cases,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    scrub_output(GOLDEN)  # path prefixes -> <repo>, <tmp>, ~
    print(f"wrote {GOLDEN.name} — {len(cases)} cases, "
          f"{len(nz35)} / {len(nz314)} nonzero image words on the bound case")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
