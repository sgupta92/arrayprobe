# SPDX-License-Identifier: BSD-3-Clause
"""Build a tracked S2 (``read_binary_SPEC.m``) oracle -- the stage that had none.

WHY THIS EXISTS.  Every other ported stage is checked against the real MATLAB
program running unmodified: the pure-``.m`` stages under Octave, the rest against
tracked Octave goldens, and S4's whole-flight output against the archived
product of record.  **S2 was the exception.**  ``tests/test_spec_reader.py``
pins every documented decision, but it pins them against *hand-built packets
and a reading of the source* -- both sides of that check come from the same
place, so the check is testing nothing.  S2 is also the stage
every other validation inherits from: it is the entry point for all raw data,
so an error here is invisible downstream because everything downstream is
compared against products that were themselves made from a correct decode.

The design note "No end-to-end S2 oracle exists" is about the
*reference pair*: the minimal working example ships decompressed output but no
raw file, so there is no MATLAB-written decode of a raw file we hold.  That is
still true.  It does not rule out the **differential** route, which is what
this bank takes -- the same route the SEA and DMT reader banks took when no real 2DC/2DP file
existed anywhere on the machine.

WHY THE FIXTURE IS SYNTHETIC, and it is not only a convenience.  A slice of a
real ``.2DS`` is campaign data, and this project's standing rule is that no raw
data ever enters a public repository.  A hand-built file is the only kind that
can be tracked -- and it is also the only kind that can be made to exercise the
rare packets on purpose (a mask packet appears a handful of times in a
gigabyte).  ``read_binary_SPEC.m`` is plain ``fread``/``netcdf.*`` with no MEX
and no toolbox -- ``readRecord``, ``get_img`` and ``sixteen2int`` are all local
functions in the one file -- so Octave runs it unmodified.

THE RECORD LAYOUT, read from ``readRecord`` (``read_binary_SPEC.m:164-176``):
eight ``uint16`` header fields (year, month, wkday, day, hour, minute, second,
millisec), 2048 ``uint16`` of data, one ``uint16`` discarded = 2057 words =
**4114 bytes**, little-endian.

THE PACKETS, read from ``get_img`` (``:178-315``).  Three markers matter and
all three are built here:

* ``12883`` (``'2S'``) -- an image packet.  ``buf(iii+1)`` is the H word,
  ``buf(iii+2)`` the V word (low 12 bits a payload length, bit 4096 a timing
  flag), ``buf(iii+3)`` the particle count, ``buf(iii+4)`` the slice count,
  then the run-length words and a two-word particle timestamp.
* ``18507`` (``'KH'``) -- housekeeping.  Consumes 53 words and appends a row to
  ``<out>.tas.csv``: the true air speed is a ``single`` bit-cast out of two
  words at offsets 50/51, which is exactly the kind of detail a transcription
  can get subtly wrong and a differential oracle catches for free.
* ``19787`` (``'KM'``) -- the diode mask.  Consumes 23 words and appends to
  ``<out>.MK.csv`` -- **the file whose format string declares twenty ``%d``
  conversions for nineteen values** (``:313-315``), so MATLAB stops output at
  the twentieth and the trailing ``' \\n'`` never reaches the file.  The port
  reproduces that as a preserved bug, but until now the claim
  rested on *reading* the format string.  This bank makes the interpreter write
  the file, so the claim becomes measured.

Usage, from the repository root:

    .venv/Scripts/python.exe octave_oracle/run_s2_spec_bank.py [--octave PATH]

Writes, all tracked and all small:

  tests/data/s2_spec_raw_fixture           the synthetic .2DS (6 records, 24 KB)
  tests/data/s2_spec_octave_golden.H.cdf   read_binary_SPEC.m's own H output
  tests/data/s2_spec_octave_golden.V.cdf   ... and its V output
  tests/data/s2_spec_octave_golden.tas.csv the housekeeping sidecar
  tests/data/s2_spec_octave_golden.MK.csv  the mask sidecar (terminators and all)

The bank REFUSES to write a golden whose images are entirely empty, for the
reason ``run_s7f_2dc_accepted_bank.py`` gives: an oracle that agrees on nothing
but zeros validates the plumbing and none of the arithmetic, and that failure
is silent unless something checks for it.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import _upstream  # noqa: E402
from scrub_paths import scrub_output  # noqa: E402

HERE = Path(__file__).resolve().parent
PORT = HERE.parents[2]
DATA = PORT / "tests" / "data"

DEFAULT_OCTAVE = Path(os.environ.get("LOCALAPPDATA", "")) / (
    r"Programs\GNU Octave\Octave-11.3.0\mingw64\bin\octave-cli.exe"
)

#: The ORACLES lineage's reader -- the one that decoded the campaign, and the
#: one the port's ORACLES_2016 profile reproduces.  Stock's differs by the
#: 2017-03-08 buffer guards (S2 design doc), which this fixture stays clear of
#: so the two trees decode it identically; a guard-tripping fixture is a
#: separate case worth adding once this one is in place.  Not distributed: read
#: from ``ARRAYPROBE_ORACLES_UIOPS_SRC`` (the directory holding that tree's
#: ``read_binary_SPEC.m``); None when unset, and ``main`` then exits 2.
_ORACLES_SRC_ENV = os.environ.get("ARRAYPROBE_ORACLES_UIOPS_SRC")
MATLAB_SRC = Path(_ORACLES_SRC_ENV) if _ORACLES_SRC_ENV else None

#: Stock UIOOPS v3.1.4's reader -- the same program plus Joe Finlon's 2017-03-08
#: buffer guards, which is the ONE substantive difference between the two trees
#: at this stage (S2 design doc §2).  Used only by the guard case below.
STOCK_SRC = _upstream.source("uiops314")

RAW_FIXTURE = DATA / "s2_spec_raw_fixture"
GOLDEN_STEM = DATA / "s2_spec_octave_golden"

#: The buffer-guard case: a second fixture, and a record of what each tree does
#: with it.  Stock skips the malformed packet; the ORACLES lineage indexes past
#: the buffer and dies.  Both are fidelity targets -- see `build_guard_records`.
GUARD_FIXTURE = DATA / "s2_spec_guard_raw_fixture"
GUARD_STOCK_STEM = DATA / "s2_spec_guard_stock_golden"
GUARD_RESULT = DATA / "s2_spec_guard_octave_result.json"

HEADER_WORDS = 8
DATA_WORDS = 2048
RECORD_WORDS = HEADER_WORDS + DATA_WORDS + 1

MARKER_2S = 12883
MARKER_HK = 18507
MARKER_MK = 19787


def run_word(aa: int, bb: int, new_slice: bool = False) -> int:
    """One run-length word: ``aa`` shadowed diodes after ``bb`` clear ones.

    ``get_img``'s inner loop reads ``aa`` from bits 7-13 and ``bb`` from bits
    0-6, and treats bit 14 as "this word starts a new slice".
    """
    assert 0 <= aa < 128 and 0 <= bb < 128
    return (0x4000 if new_slice else 0) | (aa << 7) | bb


def image_packet(runs, n_s, *, channel="H", pc=7, t_particle=0x1234ABCD):
    """A ``'2S'`` image packet with its two-word particle timestamp appended."""
    payload = [*runs, (t_particle >> 16) & 0xFFFF, t_particle & 0xFFFF]
    n = len(payload)
    if channel == "H":
        return [MARKER_2S, n, 0, pc, n_s, *payload]
    return [MARKER_2S, 0, n, pc, n_s, *payload]


def housekeeping_packet():
    """A ``'KH'`` packet: 53 words, of which ``get_img`` reads eight plus a
    two-word ``single`` TAS at offsets 50/51 (0-based 49/50 from the marker).

    The TAS bit pattern is chosen to be an exactly representable float --
    ``50.0`` -- so a transcription error in the bit-cast shows up as a wrong
    number rather than as float noise that could be argued away.
    """
    words = [0] * 53
    words[0] = MARKER_HK
    tas_bits = int(np.float32(50.0).view(np.uint32))
    words[49] = (tas_bits >> 16) & 0xFFFF          # buf(iii-1+50)
    words[50] = tas_bits & 0xFFFF                  # buf(iii-1+51)
    words[51] = 0x0001                             # time, high word
    words[52] = 0x86A0                             # time, low word
    words[40] = 11    # nStereo   (buf(iii-1+41))
    words[41] = 22    # nTWM
    words[42] = 33    # nSCM
    words[43] = 44    # nHOL
    words[44] = 55    # nVOL
    words[33] = 66    # nVPD      (buf(iii-1+34))
    words[34] = 77    # nHPD
    return words


def mask_packet():
    """A ``'KM'`` packet: 23 words -- marker, a two-word time, sixteen mask
    words, and two two-word times.  Values are distinct so a mis-ordered
    transcription is visible in the sidecar rather than hidden by repeats."""
    words = [0] * 23
    words[0] = MARKER_MK
    words[1] = 0x0002      # timeWord high
    words[2] = 0x0003      # timeWord low
    for i in range(16):    # MaskBits, buf(iii-1+4 .. iii-1+19)
        words[3 + i] = 0x1000 + i
    words[19] = 0x0004     # timeStart high
    words[20] = 0x0005     # timeStart low
    words[21] = 0x0006     # timeEnd high
    words[22] = 0x0007     # timeEnd low
    return words


def build_records():
    """Six records, each (header words, data words).

    Chosen so the fixture exercises what the port's own docstring claims about
    this reader, rather than only its happy path:

    0. an H image packet with two slices;
    1. a V image packet -- the shared ``iSlice`` counter is the reason H and V
       cannot be decoded independently;
    2. an H packet followed by the housekeeping packet, so a record with two
       packet kinds is covered;
    3. the mask packet, alone;
    4. an H packet with more runs, spanning more slices;
    5. a final H packet -- **the record whose particles are never emitted**,
       because the loop reads a pair, probes for EOF and breaks (the preserved
       "last record is never a primary" bug).
    """
    base = [2016, 9, 2, 6, 6, 44, 0, 0]  # year, month, wkday, day, h, m, s, ms

    def header(second, millisec):
        h = list(base)
        h[6], h[7] = second, millisec
        return h

    runs_a = [run_word(10, 5, new_slice=True), run_word(8, 3)]
    runs_b = [run_word(4, 2, new_slice=True), run_word(6, 1),
              run_word(12, 0, new_slice=True)]
    runs_c = [run_word(20, 10, new_slice=True), run_word(15, 5),
              run_word(9, 9, new_slice=True), run_word(3, 40)]

    return [
        (header(3, 250), image_packet(runs_a, 2, channel="H", t_particle=0x0001_0000)),
        (header(4, 100), image_packet(runs_b, 3, channel="V", t_particle=0x0002_0000)),
        (header(5, 500), image_packet(runs_a, 2, channel="H", t_particle=0x0003_0000)
                          + housekeeping_packet()),
        (header(6, 750), mask_packet()),
        (header(7, 125), image_packet(runs_c, 4, channel="H", t_particle=0x0004_0000)),
        (header(8, 875), image_packet(runs_b, 3, channel="H", t_particle=0x0005_0000)),
    ]


def build_guard_records():
    """A fixture that trips the 2017-03-08 buffer guards, and only those.

    THE DIVERGENCE THIS EXERCISES. Stock's ``read_binary_SPEC.m`` guards each
    image branch with ``iii+nH-1 <= length(buf)`` (and two more inside the run
    loops), added by Joe Finlon on 2017-03-08 "to prevent termination during
    rare instance when attempting to decode beyond the image buffer". The
    ORACLES lineage predates them and indexes straight past the end. So on the
    same bytes, **stock skips the packet and the ORACLES tree dies** — which is
    exactly what ``FidelityProfile.spec_buffer_guard`` selects between, and
    until now the port's two sides of that axis were checked only against
    hand-built expectations.

    How the trip is built: ``get_img`` scans ``while iii <= 2048`` over a
    **two-record** window of 4096 words, so a marker placed at the very last
    scanned position with a large declared length reads past the window's end.
    ``nH`` is a 12-bit field, so 4,000 words from ``iii = 2048`` reaches word
    6,047 against a 4,096-word buffer — comfortably out of bounds, and reached
    on the first branch rather than deep inside a run loop.

    The first record also carries an ordinary packet at its start, so stock's
    output is non-empty: "skipped the bad packet" and "produced nothing at all"
    are different behaviours and the golden has to be able to tell them apart.
    """
    base = [2016, 9, 2, 6, 6, 44, 0, 0]

    def header(second, millisec):
        h = list(base)
        h[6], h[7] = second, millisec
        return h

    good = image_packet(
        [run_word(10, 5, new_slice=True), run_word(8, 3)], 2,
        channel="H", t_particle=0x0007_0000)

    # The malformed packet sits at the last position the scan visits. Its
    # payload is absent by construction -- that is the point.
    runt = [MARKER_2S, 4000, 0, 7, 2]

    r0 = list(good) + [0] * (DATA_WORDS - len(good) - 1) + [MARKER_2S]
    # The marker lands on the final word; nH/nV/PC/nS are read from the NEXT
    # record's words, so put the declared-too-long length there.
    r1 = runt[1:] + [0] * (DATA_WORDS - len(runt) + 1)
    assert len(r0) == DATA_WORDS and len(r1) == DATA_WORDS
    return [(header(11, 0), r0), (header(12, 0), r1)]


def build_raw_fixture(records=None) -> bytes:
    if records is None:
        records = build_records()
    out = np.zeros((len(records), RECORD_WORDS), dtype="<u2")
    for i, (header, data) in enumerate(records):
        out[i, :HEADER_WORDS] = header
        assert len(data) <= DATA_WORDS, f"record {i} overflows the data block"
        out[i, HEADER_WORDS:HEADER_WORDS + len(data)] = data
    raw = out.tobytes()
    assert len(raw) == len(records) * RECORD_WORDS * 2
    return raw


def _run_octave(octave: Path, source_dir: Path, raw: Path, out_stem: Path,
                driver_name: str):
    """Run one tree's ``read_binary_SPEC`` on ``raw``. Returns (ok, stdout, stderr).

    ``ok`` is False when the program died -- which for the guard case is the
    expected, and interesting, outcome.
    """
    driver = HERE / driver_name
    shims = HERE / "shims"
    driver.write_text(
        "pkg load netcdf;\n"
        "warning('off', 'Octave:possible-matlab-short-circuit-operator');\n"
        f"addpath('{shims.as_posix()}');\n"
        f"addpath('{source_dir.as_posix()}');\n"
        f"read_binary_SPEC('{raw.as_posix()}', '{out_stem.as_posix()}');\n"
        "disp('BANK-OK')\n",
        encoding="ascii",
    )
    proc = subprocess.run(
        [str(octave), "--no-gui", "--quiet", str(driver)],
        cwd=str(HERE), capture_output=True, text=True, timeout=600,
    )
    driver.unlink(missing_ok=True)
    return ("BANK-OK" in proc.stdout), proc.stdout, proc.stderr


def _build_guard_case(octave: Path) -> bool:
    """Run BOTH trees on the guard fixture and record what each one does.

    The stock run's output is kept as an ordinary golden. The ORACLES run's
    *failure* is kept as a golden too -- ``status: ERROR`` plus the
    interpreter's own message -- because "MATLAB dies here" is a fidelity claim
    like any other, and the port reproduces it by raising. That is the dropsize bank's
    pattern: a case that makes the original crash belongs in the bank, so
    crash-fidelity is measured rather than argued.
    """
    import json

    if not (STOCK_SRC / "read_binary_SPEC.m").is_file():
        print(f"stock read_binary_SPEC.m missing under {STOCK_SRC}", file=sys.stderr)
        return False

    GUARD_FIXTURE.write_bytes(build_raw_fixture(build_guard_records()))
    scrub_output(GUARD_FIXTURE)  # path prefixes -> <repo>, <tmp>, ~
    print(f"\nwrote {GUARD_FIXTURE.name} "
          f"({GUARD_FIXTURE.stat().st_size} bytes, 2 records, one malformed packet)")

    for suffix in (".H.cdf", ".V.cdf", ".tas.csv", ".MK.csv", ".NV.csv"):
        stale = GUARD_STOCK_STEM.with_name(GUARD_STOCK_STEM.name + suffix)
        if stale.exists():
            stale.unlink()

    stock_ok, _, stock_err = _run_octave(
        octave, STOCK_SRC, GUARD_FIXTURE, GUARD_STOCK_STEM, "_s2_guard_stock.m")
    print(f"  stock tree      : {'completed' if stock_ok else 'DIED'}")

    variant_stem = HERE / "_s2_guard_variant_out"
    variant_ok, _, variant_err = _run_octave(
        octave, MATLAB_SRC, GUARD_FIXTURE, variant_stem, "_s2_guard_variant.m")
    print(f"  ORACLES lineage : {'completed' if variant_ok else 'DIED'}")
    for leftover in HERE.glob("_s2_guard_variant_out*"):
        leftover.unlink(missing_ok=True)

    # THE BANK ASSERTS ITS OWN PREMISE. If the fixture stopped tripping the
    # guard -- a padding change, a different marker position -- both trees would
    # simply agree, every test below would still pass, and the axis would be
    # untested while looking tested. Refuse to write that.
    if not stock_ok:
        print("REFUSING: stock died too; the fixture is not a guard case",
              file=sys.stderr)
        print(stock_err[-1500:], file=sys.stderr)
        return False
    if variant_ok:
        print("REFUSING: the ORACLES lineage survived; the fixture no longer "
              "reaches past the buffer", file=sys.stderr)
        return False

    message = next((ln.strip() for ln in variant_err.splitlines()
                    if "error:" in ln), variant_err.strip()[:200])
    GUARD_RESULT.write_text(json.dumps({
        "fixture": GUARD_FIXTURE.name,
        "stock": {"status": "OK", "output": GUARD_STOCK_STEM.name + ".H.cdf"},
        "oracles_variant": {"status": "ERROR", "message": message},
        "why": ("stock guards each image branch with iii+nH-1 <= length(buf) "
                "(Finlon, 2017-03-08); the ORACLES lineage predates the guards "
                "and indexes past the two-record window"),
    }, indent=2) + "\n", encoding="utf-8")
    scrub_output(GUARD_RESULT)  # path prefixes -> <repo>, <tmp>, ~
    print(f"  recorded        : {message}")
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--octave", type=Path, default=DEFAULT_OCTAVE)
    ap.add_argument("--keep-driver", action="store_true",
                    help="leave the generated .m driver in place for inspection")
    args = ap.parse_args(argv)

    if not args.octave.is_file():
        print(f"octave-cli not found at {args.octave}", file=sys.stderr)
        return 2
    if MATLAB_SRC is None:
        print("ARRAYPROBE_ORACLES_UIOPS_SRC is not set: point it at the ORACLES UIOPS tree "
              "(the directory holding read_binary_SPEC.m)", file=sys.stderr)
        return 2
    source = MATLAB_SRC / "read_binary_SPEC.m"
    if not source.is_file():
        print(f"read_binary_SPEC.m missing under {MATLAB_SRC}", file=sys.stderr)
        return 2

    RAW_FIXTURE.write_bytes(build_raw_fixture())
    scrub_output(RAW_FIXTURE)  # path prefixes -> <repo>, <tmp>, ~
    print(f"wrote {RAW_FIXTURE.name} ({RAW_FIXTURE.stat().st_size} bytes, "
          f"{len(build_records())} records)")

    # The sidecars are opened with 'a' (append) by get_img, so a stale file from
    # an earlier run would silently accumulate rows and the golden would grow
    # every time the bank ran. Clear them first, deliberately and visibly.
    #
    # THIS LIST WAS SHORT BY ONE, and the miss is instructive: `.NV.csv` was
    # omitted on the first pass, so the second run of the bank doubled that
    # golden's rows. The byte-for-byte sidecar test caught it on the next run --
    # which is the argument for comparing bytes rather than parsed values, since
    # a parser would have read eight plausible rows and said nothing.
    for suffix in (".H.cdf", ".V.cdf", ".tas.csv", ".MK.csv", ".NV.csv"):
        stale = GOLDEN_STEM.with_name(GOLDEN_STEM.name + suffix)
        if stale.exists():
            stale.unlink()

    driver = HERE / "_s2_spec_bank_runner.m"
    shims = HERE / "shims"
    driver.write_text(
        "pkg load netcdf;\n"
        "warning('off', 'Octave:possible-matlab-short-circuit-operator');\n"
        f"addpath('{shims.as_posix()}');\n"
        f"addpath('{MATLAB_SRC.as_posix()}');\n"
        f"read_binary_SPEC('{RAW_FIXTURE.as_posix()}', "
        f"'{GOLDEN_STEM.as_posix()}');\n"
        "disp('BANK-OK')\n",
        encoding="ascii",
    )
    proc = subprocess.run(
        [str(args.octave), "--no-gui", "--quiet", str(driver)],
        cwd=str(HERE), capture_output=True, text=True, timeout=600,
    )
    if not args.keep_driver:
        driver.unlink(missing_ok=True)
    if "BANK-OK" not in proc.stdout:
        print("octave failed:", file=sys.stderr)
        print(proc.stdout[-4000:], file=sys.stderr)
        print(proc.stderr[-4000:], file=sys.stderr)
        return 1

    import netCDF4

    written = []
    for suffix in (".H.cdf", ".V.cdf", ".tas.csv", ".MK.csv"):
        p = GOLDEN_STEM.with_name(GOLDEN_STEM.name + suffix)
        written.append((suffix, p.exists(), p.stat().st_size if p.exists() else 0))
    for suffix, exists, size in written:
        print(f"  {suffix:10s} {'ok ' if exists else 'MISSING':8s} {size:8d} bytes")

    if not _build_guard_case(args.octave):
        return 1

    h_path = GOLDEN_STEM.with_name(GOLDEN_STEM.name + ".H.cdf")
    if not h_path.exists():
        print("no H output written -- the fixture decoded to nothing", file=sys.stderr)
        return 1
    with netCDF4.Dataset(str(h_path)) as ds:
        n_records = len(ds.dimensions["time"])
        total = int(np.asarray(ds.variables["data"][:]).astype(np.int64).sum())
    print(f"  H: {n_records} image record(s), data checksum {total}")
    if n_records == 0 or total == 0:
        # The failure this bank exists to prevent: a golden of all zeros agrees
        # with anything and validates nothing (see run_s7f_2dc_accepted_bank.py).
        print("REFUSING: the golden holds no image data", file=sys.stderr)
        return 1
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
