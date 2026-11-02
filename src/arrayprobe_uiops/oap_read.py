# SPDX-License-Identifier: BSD-3-Clause
"""Reader for 2D-S records in NCAR's RAF OAP file format, written from process2d's rule.

This reader exists so that an OAP export of this repository's decoded 2D-S images
can be round-tripped against a decoder that does not share the writer's code.
:func:`arrayprobe.readers.pms.read_binary_PMS` cannot serve: it knows the tags
``C1``, ``C6``, ``C4`` and ``P*`` only, and skips a 2D-S record (tag ``SH`` or
``SV``) without a word. Computes no number used by any product.

How this repository stores a decoded 2D-S image (read from source, layout pinned in tests)
------------------------------------------------------------------------
The S2 file (``<stem>.H.cdf`` / ``.V.cdf``), written by
``arrayprobe_uiops.spec._ImageFileV35`` with helpers shared from
``arrayprobe.readers.spec``:

* ``data`` is ``int``, MATLAB shape ``(ImgRowlen=8, ImgBlocklen=1700, time)``;
  one ``time`` step per raw 4096-byte record decoded (``spec.py:147-148``).
  Per-record ``year, month, day, hour, minute, second, millisec, wkday`` (from
  the raw record header), ``tas`` and ``tasRatio`` ride beside it.
* Each column is one slice of 128 diodes, packed into eight 16-bit words,
  **MSB-first**: diode row 1 is bit 15 of word 1, row 128 bit 0 of word 8
  (``sixteen2int``, ``readers/spec.py:599-608``).
* Polarity: **1 = shaded**. The decoder sets rows ``bb+1 .. bb+aa`` to 1, where
  ``aa`` is the shaded-run field and ``bb`` the clear-run field of each
  run-length word (``readers/spec.py:161-162``, ``:262-290``). The OAP format is
  the opposite (1 = clear), so an exporter inverts.
* Particles are laid end to end from column 1: ``n_s`` image slices, then one
  **boundary slice** (alternating 1010..., every word 43690), then one **header
  slice** (``_write_header_slice``, ``readers/spec.py:393-414``). The header
  slice holds the particle timing counter MSB-first in rows 1-128 and again in
  rows 97-128, overwritten in rows 49-64 by the packet's count word, 65-80 by
  the particle count and 81-96 by ``n_s``. So the timing counter is
  recoverable exactly from words 7-8 of the header slice: it is the **32-bit**
  value of the particle's last two raw words (``arrayprobe_uiops/spec.py``,
  ``get_img_v35``), not a 48-bit word.
* No boundary precedes the first particle. Particles whose packet sets the
  timing flag are skipped, not stored. A record whose particles run past
  column 1700 loses them (the canvas cut, inherited from the upstream reader).
  An image slice that happens to be all-alternating would read as a boundary;
  the header slice that must follow it is what disambiguates.
* Per-record time is the raw record's, not the particle's: a particle's own time
  is only its 32-bit counter.

The OAP side (process2d, NCAR/aircraft_oap ``process2d/process2d.cpp`` at
commit b46dd43)
-----------------------------------------------------------------------------
* A file is an XML preamble ending ``</OAP>`` and a newline, then 4116-byte
  records: a 2-byte probe id, nine big-endian uint16 (hour, minute, second,
  year, month, day, TAS, msec, overload), 4096 data bytes.
* Slice width is ``nDiodes / 8`` = 16 bytes for 2D-S (``:680-681``), 256 slices
  per record.
* A slice is a **sync slice** when its last three bytes are ``AA AA AA``
  (``:815-822``, "Stored little-endian, check far side of 16 bytes"); its
  timing value is the slice's first eight bytes read little-endian, masked
  with the probe's timing mask (``:818``, ``:821``).
* Any other slice is image: diode 0 is byte 15 bit 7, counting down through
  bit 0 and then to byte 14, ..., diode 127 is byte 0 bit 0 (``:997-1002``).
  translate2ds packs diode 0 into byte 0 bit 0 (LSB-first), so process2d sees
  translate2ds's image mirrored across the array -- recorded, not resolved here.
* At a sync slice process2d closes the slices accumulated since the previous
  sync as one particle, with the sync's timing value (``:852-993``). translate2ds
  writes each sync carrying the *next* particle's time, so attribution differs
  by one particle; this reader reports what the file says and leaves that to
  the writer's tests.
"""

from __future__ import annotations

import dataclasses
import re
import struct
from pathlib import Path

import numpy as np

__all__ = [
    "OAP_RECORD_BYTES",
    "OapParticle",
    "OapRecordHeader",
    "SLICE_BYTES_2DS",
    "UnsupportedProbeVersion",
    "read_oap_2ds",
    "refuse_unsupported_raf_probe",
    "split_oap_xml",
]

OAP_RECORD_BYTES = 4116
DATA_BYTES = 4096
SLICE_BYTES_2DS = 16  # 128 diodes / 8, process2d.cpp:680
SYNC_TAIL = b"\xaa\xaa\xaa"  # process2d.cpp:44, :820
TIMING_MASK_48 = 0x0000FFFFFFFFFFFF  # the six low bytes translate2ds writes
_HEADER = struct.Struct(">2s9H")
_TAGS_2DS = (b"SH", b"SV")


@dataclasses.dataclass(frozen=True)
class OapRecordHeader:
    """The 20-byte record header, as stored."""

    probe_id: bytes
    hour: int
    minute: int
    second: int
    year: int
    month: int
    day: int
    tas: int
    msec: int
    overload: int


@dataclasses.dataclass(frozen=True)
class OapParticle:
    """One particle: the image slices before a sync slice, and that sync's timing.

    ``bits`` is ``(n_slices, 128)`` uint8 in process2d's diode order, values as
    stored (1 = clear, the OAP convention); ``shaded`` inverts it.
    ``record`` is the 0-based index of the record holding the sync slice.
    """

    probe_id: bytes
    timing: int
    bits: np.ndarray
    record: int

    @property
    def shaded(self) -> np.ndarray:
        return (1 - self.bits).astype(np.uint8)


def split_oap_xml(raw: bytes) -> tuple[str, int]:
    """Return the XML preamble and the byte offset of the first record.

    The preamble ends at ``</OAP>`` plus the newline after it. A file without a
    preamble starts its records at offset 0.
    """
    end = raw.find(b"</OAP>")
    if end < 0:
        return "", 0
    stop = end + len(b"</OAP>")
    if raw[stop : stop + 1] == b"\n":
        stop += 1
    return raw[:stop].decode("latin-1"), stop


class UnsupportedProbeVersion(ValueError):
    """A RAF OAP raw file names a probe version the v3.5 engine cannot frame."""


#: Bytes read from the head of a raw file to find the XML preamble; a preamble
#: is a few hundred bytes, so this is generous.
_PREAMBLE_SCAN_BYTES = 65536
_PROBE_TYPE = re.compile(r"<probe\b[^>]*\btype\s*=\s*\"([^\"]*)\"")
_UNSUPPORTED_RAF_TYPES = {
    "Fast2DC_v2": (
        "the v3.5 engine frames only Fast-2DC v1 (a three-byte AA AA AA particle "
        "boundary and a 12 MHz clock); a Fast-2DC v2 file marks each particle with a "
        "two-byte AA AA word and a 33.333 MHz 44-bit clock, so the engine would find "
        "no particle and write an empty product. Process this file with --engine soda2."
    ),
}


def refuse_unsupported_raf_probe(path: str | Path) -> None:
    """Raise :class:`UnsupportedProbeVersion` if ``path``'s preamble names a probe
    type the v3.5 engine cannot frame (today: ``Fast2DC_v2``).

    Reads only the head of the file. A file with no XML preamble, or whose probe
    types are all framable, passes and returns ``None``.
    """
    with open(path, "rb") as fh:
        head = fh.read(_PREAMBLE_SCAN_BYTES)
    xml, _ = split_oap_xml(head)
    for probe_type in _PROBE_TYPE.findall(xml):
        reason = _UNSUPPORTED_RAF_TYPES.get(probe_type)
        if reason is not None:
            raise UnsupportedProbeVersion(
                f"{Path(path).name}: probe type {probe_type!r}: {reason}")


def _slice_bits(slice_bytes: bytes) -> np.ndarray:
    """process2d.cpp:997-1002: diode 0 is byte 15 bit 7, diode 127 byte 0 bit 0."""
    arr = np.frombuffer(slice_bytes[::-1], dtype=np.uint8)
    return np.unpackbits(arr, bitorder="big")


def read_oap_2ds(path: str | Path, probe_id: bytes = b"SH",
                 ) -> tuple[str, list[OapRecordHeader], list[OapParticle]]:
    """Read every record tagged ``probe_id`` and split its slice stream at syncs.

    Slices run continuously across records of the same probe, as translate2ds
    writes them. Slices after the last sync (zero padding of the final record
    included) belong to no particle and are not returned. Records of other
    probes are skipped. Raises ``ValueError`` if the record area is not a whole
    number of records.
    """
    if probe_id not in _TAGS_2DS:
        raise ValueError(f"not a 2D-S probe id: {probe_id!r}")
    raw = Path(path).read_bytes()
    xml, offset = split_oap_xml(raw)
    body = raw[offset:]
    if len(body) % OAP_RECORD_BYTES:
        raise ValueError(
            f"{len(body)} bytes after the XML is not a whole number of "
            f"{OAP_RECORD_BYTES}-byte records"
        )
    headers: list[OapRecordHeader] = []
    particles: list[OapParticle] = []
    pending: list[np.ndarray] = []
    n_records = len(body) // OAP_RECORD_BYTES
    for rec in range(n_records):
        start = rec * OAP_RECORD_BYTES
        fields = _HEADER.unpack_from(body, start)
        if fields[0] != probe_id:
            continue
        headers.append(OapRecordHeader(*fields))
        data = body[start + _HEADER.size : start + OAP_RECORD_BYTES]
        for s in range(DATA_BYTES // SLICE_BYTES_2DS):
            sl = data[s * SLICE_BYTES_2DS : (s + 1) * SLICE_BYTES_2DS]
            if sl[-3:] == SYNC_TAIL:
                timing = int.from_bytes(sl[:8], "little") & TIMING_MASK_48
                bits = (np.vstack(pending) if pending
                        else np.zeros((0, 8 * SLICE_BYTES_2DS), dtype=np.uint8))
                particles.append(OapParticle(probe_id, timing, bits, len(headers) - 1))
                pending = []
            else:
                pending.append(_slice_bits(sl))
    return xml, headers, particles
