# SPDX-License-Identifier: BSD-3-Clause
"""Export decoded 2D-S images in NCAR's RAF OAP file format (``.2d``).

Opt-in tooling inside the v3.5 engine: it re-packs images the S2 stage already
decoded and computes no number used by any product. The format follows
translate2ds's writer (NCAR/aircraft_oap ``translate2ds/UCAR_Writer.h``); the
reader it is checked against, :mod:`arrayprobe_uiops.oap_read`, was written from
process2d's rule instead, so the round trip draws its two sides from different
places.

What is written
---------------
* An XML preamble (``<OAP version="1">`` ... ``</OAP>``) naming the project,
  platform, flight and one ``<probe>`` element per channel written.
* 4116-byte records: a 2-byte probe id (``SH``/``SV``), nine big-endian uint16
  (hour, minute, second, year, month, day, TAS, msec, overload = 0), then 4096
  data bytes = 256 slices of 16 bytes. The slice stream runs across record
  boundaries; the final record is zero-padded.
* Image slices: one bit per diode, **1 = clear** (the OAP convention). The S2
  canvas stores 1 = shaded, so every pixel is inverted on the way out. Diode
  row ``r`` of the S2 canvas (1-based, word 1 bit 15 = row 1) is written as
  process2d's diode ``r - 1`` (byte 15 bit 7 = diode 0).
* After each particle's image slices, one sync slice: the timing value in bytes
  0-7 little-endian, then ``0xAAAAAA0000000000`` little-endian.

Timing
------
The S2 header slice holds the particle's timing counter as a **32-bit** value
(words 7-8 of the header slice; see :mod:`arrayprobe_uiops.oap_read`'s storage
notes), so that is what is written: bytes 0-3 of the sync slice, bytes 4-7
zero. The counter survives the round trip exactly. translate2ds writes the
2D-S's own 48-bit word; the upper 16 bits are not stored at S2 and are not
reconstructed.

translate2ds writes the sync that closes particle *k* with particle *k + 1*'s
time and closes the stream with a final sync repeating the last time.
``timing_convention="translate2ds"`` (the default) copies that; ``"own"``
writes each particle's own time in the sync that closes it, which is how
process2d attributes a sync's time. Which convention xpms2d and process2d
expect of a 2D-S file is not settled here.

Open question: diode order
--------------------------
process2d unpacks diode 0 from byte 15 bit 7 (``process2d.cpp:997-1002``);
translate2ds packs diode 0 into byte 0 bit 0 (``UCAR_Writer.h`` ``ToBits``,
LSB-first). The two pack diode 0 at opposite ends of the slice, so one of
them reads the other's images mirrored across the array. This module follows
process2d's order, so its own reader sees the images unmirrored; whether a
translate2ds-written file and this one agree byte for byte stays unresolved
until Process2D builds and the two can be compared on the same raw file.

Lossy, and stated
-----------------
Record-header time is per record (the stamp of the particle whose slices open
the record), not per particle; TAS is a uint16 word; overload is 0;
housekeeping and mask packets are not carried; particles the S2 canvas cut at
column 1700 never reach this module.
"""

from __future__ import annotations

import dataclasses
import struct
from collections.abc import Iterable, Sequence
from pathlib import Path

import numpy as np

__all__ = [
    "BOUNDARY_WORD",
    "OapStamp",
    "OapWriteReport",
    "ExportParticle",
    "encode_slice",
    "particles_from_canvas",
    "main",
    "particles_from_decode",
    "write_oap_2ds",
]

OAP_RECORD_BYTES = 4116
DATA_BYTES = 4096
SLICE_BYTES = 16
N_DIODES = 128
BOUNDARY_WORD = 0b1010101010101010  # the S2 canvas's alternating boundary slice, per word
SYNC_TAIL_WORD = 0xAAAAAA0000000000
TIMING_MASK_32 = 0xFFFFFFFF
_HEADER = struct.Struct(">2s9H")
_SUFFIX = {b"SH": "_2H", b"SV": "_2V"}


@dataclasses.dataclass(frozen=True)
class OapStamp:
    """The per-record header fields (as stored: unsigned 16-bit words)."""

    year: int
    month: int
    day: int
    hour: int
    minute: int
    second: int
    msec: int = 0
    tas: int = 0


@dataclasses.dataclass(frozen=True)
class ExportParticle:
    """One particle: ``shaded`` is ``(n_slices, 128)`` with 1 = shaded, S2's
    convention; ``timing`` is the 32-bit counter; ``stamp`` the record time."""

    shaded: np.ndarray
    timing: int
    stamp: OapStamp


@dataclasses.dataclass(frozen=True)
class OapWriteReport:
    particles: int
    records: int
    slices: int
    timing_convention: str


def encode_slice(shaded_row: np.ndarray) -> bytes:
    """One 128-diode slice, 1 = shaded in, OAP bytes (1 = clear) out, diode 0 at
    byte 15 bit 7 (process2d's order)."""
    row = np.asarray(shaded_row, dtype=np.uint8)
    if row.shape != (N_DIODES,):
        raise ValueError(f"a 2D-S slice has {N_DIODES} diodes, got shape {row.shape}")
    clear = (1 - row).astype(np.uint8)
    return np.packbits(clear, bitorder="big").tobytes()[::-1]


def _sync_slice(timing: int) -> bytes:
    return (int(timing) & TIMING_MASK_32).to_bytes(8, "little") + SYNC_TAIL_WORD.to_bytes(
        8, "little")


def _unpack_words(col: np.ndarray) -> np.ndarray:
    """Eight 16-bit words, MSB-first, to 128 diode bits (row 1 = word 1 bit 15)."""
    words = np.asarray(col, dtype=np.int64).astype(">u2")
    return np.unpackbits(words.view(np.uint8), bitorder="big")


def particles_from_canvas(canvas: np.ndarray) -> list[tuple[np.ndarray, int]]:
    """Split one S2 record canvas into ``(shaded, timing)`` per particle.

    ``canvas`` is ``(8, n_columns)`` integer words, one column per slice, as the
    S2 ``data`` variable holds it for one ``time`` step. A particle is the image
    columns up to a boundary column (every word ``BOUNDARY_WORD``), closed by the
    header column after it, whose words 7-8 are the 32-bit timing counter.
    Columns after the last header column (the zero fill of the canvas) are
    ignored. An image column that is itself all-alternating would be read as a
    boundary; the header column that must follow is not checked further.
    """
    arr = np.asarray(canvas)
    if arr.ndim != 2 or arr.shape[0] != 8:
        raise ValueError(f"canvas must be (8, n_columns), got {arr.shape}")
    out: list[tuple[np.ndarray, int]] = []
    start = 0
    col = 0
    n = arr.shape[1]
    while col + 1 < n:
        if (arr[:, col] == BOUNDARY_WORD).all():
            header = arr[:, col + 1]
            timing = (int(header[6]) << 16) | int(header[7])
            image = (np.vstack([_unpack_words(arr[:, c]) for c in range(start, col)])
                     if col > start else np.zeros((0, N_DIODES), dtype=np.uint8))
            out.append((image, timing))
            col += 2
            start = col
        else:
            col += 1
    return out


def _xml(probe_id: bytes, project: str, platform: str, flight_number: str,
         first: OapStamp | None, probe_type: str, serial: str) -> bytes:
    date = (f"{first.month:02d}/{first.day:02d}/{first.year:04d}" if first else "")
    tag = probe_id.decode("ascii")
    lines = [
        '<?xml version="1.0" encoding="ISO-8859-1"?>',
        '<OAP version="1">',
        " <Source>arrayprobe_uiops.export_oap</Source>",
        " <FormatURL>http://www.eol.ucar.edu/raf/software/OAPfiles.html</FormatURL>",
        f" <Project>{project}</Project>",
        f" <Platform>{platform}</Platform>",
        f" <FlightNumber>{flight_number}</FlightNumber>",
        f" <FlightDate>{date}</FlightDate>",
        f' <probe id="{tag}" type="{probe_type}" resolution="10" nDiodes="{N_DIODES}"'
        f' serialnumber="{serial}" suffix="{_SUFFIX[probe_id]}"/>',
        "</OAP>",
    ]
    return ("\n".join(lines) + "\n").encode("latin-1")


def write_oap_2ds(particles: Iterable[ExportParticle], out: str | Path, *,
                  probe_id: bytes = b"SH", project: str = "", platform: str = "",
                  flight_number: str = "", probe_type: str = "2DS", serial: str = "",
                  timing_convention: str = "translate2ds") -> OapWriteReport:
    """Write ``particles`` (in time order) to ``out`` as one 2D-S channel."""
    if probe_id not in _SUFFIX:
        raise ValueError(f"not a 2D-S probe id: {probe_id!r}")
    if timing_convention not in ("translate2ds", "own"):
        raise ValueError(f"unknown timing_convention {timing_convention!r}")
    parts: Sequence[ExportParticle] = list(particles)
    stream: list[bytes] = []
    owner: list[OapStamp] = []  # the stamp of the particle each slice belongs to
    for k, p in enumerate(parts):
        shaded = np.asarray(p.shaded)
        if shaded.ndim != 2 or shaded.shape[1] != N_DIODES:
            raise ValueError(f"particle {k}: shaded must be (n, {N_DIODES}), got {shaded.shape}")
        if timing_convention == "own":
            sync_t = p.timing
        else:
            sync_t = parts[k + 1].timing if k + 1 < len(parts) else p.timing
        for row in shaded:
            stream.append(encode_slice(row))
            owner.append(p.stamp)
        stream.append(_sync_slice(sync_t))
        owner.append(p.stamp)
    per_record = DATA_BYTES // SLICE_BYTES
    records: list[bytes] = []
    for i in range(0, len(stream), per_record):
        data = b"".join(stream[i : i + per_record]).ljust(DATA_BYTES, b"\x00")
        s = owner[i]
        records.append(_HEADER.pack(probe_id, s.hour, s.minute, s.second, s.year, s.month,
                                    s.day, s.tas, s.msec, 0) + data)
    first = parts[0].stamp if parts else None
    xml = _xml(probe_id, project, platform, flight_number, first, probe_type, serial)
    Path(out).write_bytes(xml + b"".join(records))
    return OapWriteReport(particles=len(parts), records=len(records), slices=len(stream),
                          timing_convention=timing_convention)


#: Probe names a v3.5 SPEC decode can come from; only the 2D-S is this format's subject here.
_OTHER_SPEC_PROBES = ("HVPS", "3VCPI", "CPI", "CIP", "PIP", "2DC", "2DP")
_CHANNEL_IDS = {"Horizontal": b"SH", "Vertical": b"SV"}


def particles_from_decode(path: str | Path) -> tuple[bytes, list[ExportParticle]]:
    """Read a v3.5 S2 decode (``<flight>.H.nc`` / ``.V.nc``) into export particles.

    Returns the channel's probe id (``SH`` / ``SV``, from the file's
    ``Probe Channel_Orientation``) and every particle in file order, each
    stamped with its record's time, millisecond and TAS (rounded to a uint16
    word; a missing or negative TAS is written as 0). Raises ``ValueError`` on a
    file that is not a v3.5 SPEC decode, or that names another probe.
    """
    import netCDF4

    p = Path(path)
    with netCDF4.Dataset(p) as ds:
        attrs = {k: ds.getncattr(k) for k in ds.ncattrs()}
        orient = attrs.get("Probe Channel_Orientation")
        if orient not in _CHANNEL_IDS or "data" not in ds.variables:
            raise ValueError(f"{p.name}: not a v3.5 2D-S decode (no 'data' variable or no "
                             "'Probe Channel_Orientation' of Horizontal/Vertical)")
        named = " ".join([p.name, *(str(v) for v in attrs.values())]).upper()
        other = [n for n in _OTHER_SPEC_PROBES if n in named]
        if other:
            raise ValueError(f"{p.name}: names probe {other[0]}; export-oap writes 2D-S "
                             "decodes only")
        ds.set_auto_mask(False)
        data = np.asarray(ds.variables["data"][:])
        if data.ndim != 3 or data.shape[2] != 8:
            raise ValueError(f"{p.name}: 'data' is {data.shape}, expected (time, columns, 8)")
        fields = {n: np.asarray(ds.variables[n][:]).astype(np.int64)
                  for n in ("year", "month", "day", "hour", "minute", "second", "millisec")}
        tas = (np.asarray(ds.variables["tas"][:], dtype=float) if "tas" in ds.variables
               else np.zeros(data.shape[0]))
    out: list[ExportParticle] = []
    for t in range(data.shape[0]):
        v = tas[t]
        tas_word = int(min(round(v), 0xFFFF)) if np.isfinite(v) and v > 0 else 0
        stamp = OapStamp(year=int(fields["year"][t]), month=int(fields["month"][t]),
                         day=int(fields["day"][t]), hour=int(fields["hour"][t]),
                         minute=int(fields["minute"][t]), second=int(fields["second"][t]),
                         msec=int(fields["millisec"][t]), tas=tas_word)
        for shaded, timing in particles_from_canvas(data[t].T):
            out.append(ExportParticle(shaded, timing, stamp))
    return _CHANNEL_IDS[orient], out


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m arrayprobe_uiops.export_oap DECODE OUT --probe 2DS``: one channel, one file.

    Opt-in: writes ``OUT`` and nothing else, and changes no product.
    """
    import argparse

    ap = argparse.ArgumentParser(
        prog="python -m arrayprobe_uiops.export_oap",
        description="Write a v3.5 2D-S stage-2 decode (<flight>.H.nc or .V.nc) as an NCAR "
                    "RAF OAP (.2d) file. Writes OUT only; no product changes.")
    ap.add_argument("decode", help="the v3.5 decoder's output file for one channel")
    ap.add_argument("out", help="the .2d file to write (refused if it exists)")
    ap.add_argument("--probe", required=True,
                    help="the probe the decode came from; only 2DS is accepted")
    ap.add_argument("--timing-convention", choices=("translate2ds", "own"),
                    default="translate2ds")
    ap.add_argument("--project", default="")
    ap.add_argument("--platform", default="")
    ap.add_argument("--flight-number", default="")
    ap.add_argument("--serial", default="")
    args = ap.parse_args(argv)
    if args.probe.upper() not in ("2DS", "2D-S"):
        ap.error(f"--probe {args.probe}: export-oap writes 2D-S decodes only")
    out = Path(args.out)
    if out.exists():
        ap.error(f"{out} exists; refusing to overwrite")
    try:
        probe_id, parts = particles_from_decode(args.decode)
    except ValueError as exc:
        ap.error(str(exc))
    report = write_oap_2ds(parts, out, probe_id=probe_id, project=args.project,
                           platform=args.platform, flight_number=args.flight_number,
                           serial=args.serial, timing_convention=args.timing_convention)
    print(f"{out}: {report.particles} particles, {report.records} records "
          f"({probe_id.decode()}, timing {report.timing_convention})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
