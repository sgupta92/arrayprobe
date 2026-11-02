# SPDX-License-Identifier: BSD-3-Clause
"""Reading the MATLAB ``.mat`` sidecars the UIOOPS processing chain leaves behind.

UIOOPS itself writes netCDF, but the ORACLES production chain hangs two MATLAB
``save`` files off the side of it, and the port has to read at least one of them
to reproduce the reference product:

* ``diode.<date><time>[.<orientation>].mat`` -- the stuck-diode mask that
  ``find_shadow_diodes.m:104`` writes and the production ``imgProc_sm.m:289``
  loads.  See :mod:`arrayprobe.masks`.

That is the whole requirement: a handful of small, flat, real numeric and char
arrays.  No cells, no structs, no objects, no sparse, no complex -- MATLAB's
``save`` of a workspace containing three plain variables.

**Why this is not ``scipy.io.loadmat``.**  SciPy would do the job in one line,
and it is already declared in the ``arrayprobe[extra]`` extra.  Pulling it into
the *runtime* requirements to read three hundred bytes would make a 30 MB
numerical stack a hard dependency of ``import arrayprobe``, which is a poor
trade for a package whose reason to exist is that it runs where the heavyweight
alternative does not.  The subset below is small enough to read in one sitting
and is checked against Octave's own ``load`` on the real ORACLES files
(``tests/test_matio.py``), so the shortcut is measured rather than assumed.

Anything outside the supported subset raises :class:`UnsupportedMatFeature`
naming what it found.  A reader that guessed would be worse than one that stops:
these files decide which photodiodes get re-illuminated before every downstream
size and habit calculation.

Format reference: *MAT-File Format*, MathWorks, the Level 5 chapter.  Both the
uncompressed (v5/``-v6``) and zlib-wrapped (v7) containers are handled; v7.3 is
HDF5 and is rejected explicitly, since a v7.3 file would otherwise look like a
corrupt v5 one.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np

__all__ = [
    "UnsupportedMatFeature",
    "MatFileError",
    "MatFile",
    "loadmat",
    "savemat",
]


class MatFileError(ValueError):
    """The file is not a readable Level 5 MAT-file."""


class UnsupportedMatFeature(MatFileError):
    """A Level 5 MAT-file feature this reader deliberately does not handle."""


# -- Data types (Table 1-1) -------------------------------------------------

_MI_INT8 = 1
_MI_UINT8 = 2
_MI_INT16 = 3
_MI_UINT16 = 4
_MI_INT32 = 5
_MI_UINT32 = 6
_MI_SINGLE = 7
_MI_DOUBLE = 9
_MI_INT64 = 12
_MI_UINT64 = 13
_MI_MATRIX = 14
_MI_COMPRESSED = 15
_MI_UTF8 = 16
_MI_UTF16 = 17
_MI_UTF32 = 18

_MI_NAMES = {
    _MI_INT8: "miINT8", _MI_UINT8: "miUINT8", _MI_INT16: "miINT16",
    _MI_UINT16: "miUINT16", _MI_INT32: "miINT32", _MI_UINT32: "miUINT32",
    _MI_SINGLE: "miSINGLE", _MI_DOUBLE: "miDOUBLE", _MI_INT64: "miINT64",
    _MI_UINT64: "miUINT64", _MI_MATRIX: "miMATRIX",
    _MI_COMPRESSED: "miCOMPRESSED", _MI_UTF8: "miUTF8", _MI_UTF16: "miUTF16",
    _MI_UTF32: "miUTF32",
}

#: Storage type -> numpy dtype *code*, resolved against the file's byte order.
_MI_DTYPE = {
    _MI_INT8: "i1", _MI_UINT8: "u1", _MI_INT16: "i2", _MI_UINT16: "u2",
    _MI_INT32: "i4", _MI_UINT32: "u4", _MI_SINGLE: "f4", _MI_DOUBLE: "f8",
    _MI_INT64: "i8", _MI_UINT64: "u8",
    # The UTF types carry character data; treat them as their code units and
    # let the char branch decode.
    _MI_UTF8: "u1", _MI_UTF16: "u2", _MI_UTF32: "u4",
}

# -- Array classes (Table 1-3) ----------------------------------------------

_MX_CELL = 1
_MX_STRUCT = 2
_MX_OBJECT = 3
_MX_CHAR = 4
_MX_SPARSE = 5
_MX_DOUBLE = 6
_MX_SINGLE = 7
_MX_INT8 = 8
_MX_UINT8 = 9
_MX_INT16 = 10
_MX_UINT16 = 11
_MX_INT32 = 12
_MX_UINT32 = 13
_MX_INT64 = 14
_MX_UINT64 = 15

_MX_NAMES = {
    _MX_CELL: "cell", _MX_STRUCT: "struct", _MX_OBJECT: "object",
    _MX_CHAR: "char", _MX_SPARSE: "sparse", _MX_DOUBLE: "double",
    _MX_SINGLE: "single", _MX_INT8: "int8", _MX_UINT8: "uint8",
    _MX_INT16: "int16", _MX_UINT16: "uint16", _MX_INT32: "int32",
    _MX_UINT32: "uint32", _MX_INT64: "int64", _MX_UINT64: "uint64",
}

#: The class a value is *presented* as, independent of how it was stored.
#: MATLAB compresses on write -- a double array whose values all fit in int8 is
#: stored as miINT8 and must still come back as float64, or a mask of diode
#: numbers would arrive as int8 and silently wrap at 127.
_MX_NUMERIC_DTYPE = {
    _MX_DOUBLE: np.float64, _MX_SINGLE: np.float32,
    _MX_INT8: np.int8, _MX_UINT8: np.uint8,
    _MX_INT16: np.int16, _MX_UINT16: np.uint16,
    _MX_INT32: np.int32, _MX_UINT32: np.uint32,
    _MX_INT64: np.int64, _MX_UINT64: np.uint64,
}

_FLAG_COMPLEX = 0x0800
_FLAG_LOGICAL = 0x0200

_HEADER_LEN = 128


@dataclass(frozen=True)
class MatFile:
    """A loaded MAT-file: its variables plus the header MATLAB stamped on it."""

    variables: dict[str, np.ndarray | str]
    header: str
    """The 116-byte descriptive text, e.g. ``'MATLAB 5.0 MAT-file, Platform:
    GLNXA64, Created on: Tue Oct 31 21:09:47 2017'``.  Kept because it is the
    only provenance a ``save`` file carries -- platform and creation time -- and
    for the ORACLES masks it is what establishes them as 2017 Linux output of
    record rather than something regenerated later."""

    version: int
    byte_order: str
    """``'<'`` or ``'>'``."""

    def __getitem__(self, name: str):
        return self.variables[name]

    def __contains__(self, name: str) -> bool:
        return name in self.variables

    def keys(self):
        """The variable names in the file, in the order MATLAB wrote them.

        MAT-file elements are stored sequentially, so this is write order and
        not sorted -- ``dict`` preserves it. That matters for a ``diode.*.mat``
        mask, where the ORACLES files carry one variable and a second name
        appearing would be the signal that the file is not what it claims.
        """
        return self.variables.keys()


def loadmat(path) -> MatFile:
    """Read a Level 5 (v5/v6/v7) MAT-file.

    Returns a :class:`MatFile`.  Numeric arrays come back in MATLAB's shape and
    presented class; char arrays come back as :class:`str` when they are a
    single row (which is every char variable UIOOPS writes) and as an array of
    rows otherwise.
    """
    raw = Path(path).read_bytes()
    if len(raw) < _HEADER_LEN:
        raise MatFileError(
            f"{path}: {len(raw)} bytes is shorter than the 128-byte Level 5 header"
        )

    if raw[:8] == b"\x89HDF\r\n\x1a\n":
        raise UnsupportedMatFeature(
            f"{path} is a MAT-file v7.3, which is HDF5, not Level 5. Re-save it "
            "with `save(..., '-v7')` or read it with h5py."
        )

    endian_tag = raw[126:128]
    if endian_tag == b"IM":
        order = "<"
    elif endian_tag == b"MI":
        order = ">"
    else:
        raise MatFileError(
            f"{path}: bytes 126-127 are {endian_tag!r}, expected b'IM' or b'MI'. "
            "This is not a Level 5 MAT-file."
        )

    header = raw[:116].rstrip(b"\x00 ").decode("latin-1")
    version = int(np.frombuffer(raw[124:126], dtype=order + "u2")[0])

    variables: dict[str, np.ndarray | str] = {}
    for mi_type, payload in _iter_elements(raw[_HEADER_LEN:], order):
        if mi_type == _MI_COMPRESSED:
            inner = zlib.decompress(payload)
            for inner_type, inner_payload in _iter_elements(inner, order):
                _collect(inner_type, inner_payload, order, variables)
        else:
            _collect(mi_type, payload, order, variables)

    return MatFile(variables=variables, header=header, version=version,
                   byte_order=order)


#: numpy dtype -> (mxClass, miType) for the subset :func:`savemat` writes.
_SAVE_CLASSES = {
    np.dtype(np.float64): (_MX_DOUBLE, _MI_DOUBLE),
    np.dtype(np.int32): (_MX_INT32, _MI_INT32),
}


def _element(mi_type: int, payload: bytes) -> bytes:
    """One tagged data element, padded to the 8-byte boundary Level 5 requires."""
    tag = np.array([mi_type, len(payload)], dtype="<u4").tobytes()
    pad = (-len(payload)) % 8
    return tag + payload + b"\x00" * pad


def _matrix_element(name: str, value) -> bytes:
    if isinstance(value, str):
        mx_class, mi_type = _MX_CHAR, _MI_UINT16
        dims = (1, len(value)) if value else (0, 0)
        data = np.array([ord(ch) for ch in value], dtype="<u2").tobytes()
    else:
        arr = np.asarray(value)
        if arr.dtype not in _SAVE_CLASSES:
            raise UnsupportedMatFeature(
                f"savemat writes double and int32 arrays and char rows only; "
                f"{name!r} is {arr.dtype}")
        mx_class, mi_type = _SAVE_CLASSES[arr.dtype]
        if arr.ndim == 0:
            arr = arr.reshape(1, 1)
        elif arr.ndim == 1:
            arr = arr.reshape(-1, 1)      # MATLAB has no 1-D arrays; a column
        dims = arr.shape
        data = arr.astype(arr.dtype.newbyteorder("<")).tobytes(order="F")
    flags = np.array([mx_class, 0], dtype="<u4").tobytes()
    body = (_element(_MI_UINT32, flags)
            + _element(_MI_INT32, np.array(dims, dtype="<i4").tobytes())
            + _element(_MI_INT8, name.encode("latin-1"))
            + _element(mi_type, data))
    return _element(_MI_MATRIX, body)


def savemat(path, variables: dict, *, header_text: str | None = None) -> Path:
    """Write a Level 5 MAT-file, uncompressed (MATLAB's ``-v6`` container).

    The write side of the one requirement this module has: ``find_shadow_diodes.m``'s
    ``save([path ...])`` (``:103-107``), which saves the whole workspace --
    ``a``, ``date``, ``orientation``, ``path``, ``shadow_diode``, ``time``.
    Variables are written in the order given; MATLAB's bare ``save`` writes
    them in ``who`` order, which is alphabetical, and the caller passes them so.

    Supports exactly what that file holds: double and int32 arrays (1-D taken
    as a column, the shape ``find`` and ``ncread`` return) and single-row char.
    MATLAB's default ``save`` is ``-v7`` (zlib-compressed); the container is
    not a computed number, :func:`loadmat` and MATLAB's ``load`` read both, and
    the 116-byte header text carries a creation time in any case, so no
    ``.mat`` file is byte-reproducible across two ``save`` calls.
    """
    path = Path(path)
    if header_text is None:
        import time as _time
        header_text = ("MATLAB 5.0 MAT-file, Platform: arrayprobe, Created on: "
                       + _time.strftime("%a %b %d %H:%M:%S %Y"))
    text = header_text.encode("latin-1")[:116].ljust(116, b" ")
    header = text + b"\x00" * 8 + np.array([0x0100], dtype="<u2").tobytes() + b"IM"
    body = b"".join(_matrix_element(k, v) for k, v in variables.items())
    path.write_bytes(header + body)
    return path


def _collect(mi_type, payload, order, variables):
    if mi_type != _MI_MATRIX:
        # Level 5 permits only miMATRIX (and miCOMPRESSED wrapping one) at the
        # top level.  Anything else means the parse has lost alignment, and
        # continuing would invent variables.
        raise MatFileError(
            f"top-level element is {_MI_NAMES.get(mi_type, mi_type)}, "
            "expected miMATRIX"
        )
    name, value = _read_matrix(payload, order)
    variables[name] = value


def _iter_elements(buf, order):
    """Yield ``(type, payload)`` for each data element, honouring 8-byte padding."""
    pos = 0
    n = len(buf)
    u4 = np.dtype(order + "u4")
    while pos + 8 <= n:
        first = int(np.frombuffer(buf, dtype=u4, count=1, offset=pos)[0])
        if first == 0:
            # A zero type tag is not a legal element; it is the zero padding
            # that follows the last one.  Stop rather than inventing a variable.
            break
        # Small Data Element Format: if the upper two bytes of the first word
        # are non-zero they hold the byte count and the lower two the type, and
        # the payload is the next four bytes.  Missing this is the classic way
        # a hand-rolled reader desynchronises.
        if first >> 16:
            nbytes = first >> 16
            mi_type = first & 0xFFFF
            payload = buf[pos + 4:pos + 4 + nbytes]
            pos += 8
        else:
            mi_type = first
            nbytes = int(np.frombuffer(buf, dtype=u4, count=1, offset=pos + 4)[0])
            payload = buf[pos + 8:pos + 8 + nbytes]
            if len(payload) < nbytes:
                raise MatFileError(
                    f"element of type {_MI_NAMES.get(mi_type, mi_type)} declares "
                    f"{nbytes} bytes but only {len(payload)} remain"
                )
            pos += 8 + nbytes
            # Every element is padded out to an 8-byte boundary EXCEPT
            # miCOMPRESSED, which the format leaves unpadded.  Padding a
            # compressed element anyway walks the cursor two bytes past the
            # start of the next one, and the parse then reads a garbage tag --
            # which is exactly how this reader failed first time round.
            if mi_type != _MI_COMPRESSED and pos % 8:
                pos += 8 - (pos % 8)
        yield mi_type, payload
    # Trailing bytes shorter than a tag are padding, not an error.


def _read_matrix(payload, order):
    """Parse one miMATRIX element into ``(name, value)``."""
    subs = list(_iter_elements(payload, order))
    if len(subs) < 3:
        raise MatFileError(
            f"miMATRIX has {len(subs)} subelements; expected at least "
            "array flags, dimensions and name"
        )

    flags_words = _as_array(subs[0], order)
    flags = int(flags_words[0])
    mx_class = flags & 0xFF

    if mx_class in (_MX_CELL, _MX_STRUCT, _MX_OBJECT, _MX_SPARSE):
        raise UnsupportedMatFeature(
            f"{_MX_NAMES[mx_class]} arrays are not supported. The UIOPS sidecars "
            "this reader exists for contain only flat numeric and char arrays; "
            "guessing at a container type would be worse than stopping."
        )
    if flags & _FLAG_COMPLEX:
        raise UnsupportedMatFeature("complex arrays are not supported")

    dims = tuple(int(d) for d in _as_array(subs[1], order))
    name_bytes = _as_array(subs[2], order).astype(np.uint8).tobytes()
    name = name_bytes.decode("latin-1")

    if len(subs) < 4:
        # An empty array still carries a (possibly zero-length) data element in
        # every file MATLAB writes; treat its absence as empty rather than an
        # error, since `shadow_diode = []` is a case that genuinely occurs.
        data = np.zeros(0, dtype=np.uint8)
    else:
        data = _as_array(subs[3], order)

    if mx_class == _MX_CHAR:
        return name, _to_char(data, dims)

    dtype = _MX_NUMERIC_DTYPE.get(mx_class)
    if dtype is None:
        raise UnsupportedMatFeature(f"array class {mx_class} is not supported")
    if flags & _FLAG_LOGICAL:
        dtype = np.bool_

    # MATLAB stores column-major; reshape in Fortran order so the array keeps
    # the shape and element order it had in the workspace.
    return name, np.asarray(data, dtype=dtype).reshape(dims, order="F")


def _as_array(element, order):
    mi_type, payload = element
    code = _MI_DTYPE.get(mi_type)
    if code is None:
        raise UnsupportedMatFeature(
            f"data element type {_MI_NAMES.get(mi_type, mi_type)} is not supported"
        )
    return np.frombuffer(payload, dtype=np.dtype(order + code))


def _to_char(data, dims):
    """Char arrays: one row comes back as ``str``, several as an array of rows."""
    codes = np.asarray(data).astype(np.uint32).reshape(dims, order="F")
    if codes.ndim <= 1 or (codes.ndim == 2 and codes.shape[0] <= 1):
        return "".join(chr(int(c)) for c in codes.ravel(order="F"))
    return np.array(
        ["".join(chr(int(c)) for c in row) for row in codes],
        dtype=object,
    )
