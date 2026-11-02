# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""The IDL SAVE file ``soda2_process_2d.pro:729-731`` writes --
``save, file=fn_out, data, /compress`` -- ported as a file-format writer
Replaces the earlier ``pbp_writer.SaveFileNotPorted``.

**This is file-format porting, not algorithm porting.** The target is
*restore-equality*, not byte-identity with IDL: a zlib stream differs between
implementations, and the ``TIMESTAMP`` record carries the date, user and host.
What is asserted instead (``tests/test_soda2_save_writer.py``,
``tests/test_soda2_save_writer_gdl.py``):

- ``scipy.io.readsav`` reads the file back to the same ``data`` struct,
  field for field (IDL type, dimensions, values);
- GDL ``RESTORE`` of this file equals GDL ``RESTORE`` of GDL's own ``SAVE`` of
  the same struct (``gdl_oracle/run_soda2_save_writer_bank.py``);
- the descriptor fields that neither reader needs -- tag offsets, tag and
  variable flags, ``PREDEF`` -- follow what IDL 8.5 itself wrote, measured
  from the descriptor (structure only, never values) of an IDL-written
  SODA-2 ``.dat``. Where GDL's own ``SAVE`` writes something else (it does,
  for all four), this module follows IDL, not GDL.

**Format** (C. Markwardt's *Unofficial Format Specification of the IDL SAVE
File*, as implemented by ``scipy/io/_idl.py``; every field below was checked
against a GDL-written and an IDL-written file):

- signature ``SR``, then ``00 04`` (plain) or ``00 06`` (``/compress``);
- records, each ``RECTYPE`` (LONG), ``NEXTREC`` (two unsigned LONGs, low
  word first: the absolute file offset of the next record), 4 zero bytes,
  then the body; under ``/compress`` each body is zlib-compressed on its own
  and ``NEXTREC`` points into the compressed file;
- record sequence ``TIMESTAMP`` (10), ``VERSION`` (14), one ``VARIABLE`` (2)
  per variable, ``END_MARKER`` (6) -- the sequence IDL 8.5 wrote. IDL's
  ``END_MARKER`` is 16 bytes and ends the file; GDL appends 20 (plain) or
  hundreds (compressed) bytes of stale buffer after it, which this module
  does not reproduce;
- all numbers big-endian (XDR). INT/UINT are widened to 4 bytes on the wire
  (INT sign-extended, UINT zero-extended); a BYTE scalar is a LONG 1 then
  the byte padded to 4; a BYTE array is its byte count (LONG) then the bytes
  padded to 4; a STRING is its length, then (if non-empty) the length again
  and the bytes padded to 4 -- an empty string is one LONG 0 (measured:
  ``readsav`` and GDL agree on an IDL-written empty ``op.outdir``);
- arrays are written in IDL (column-major) order with IDL's dimensions. The
  port keeps IDL index order in its numpy shapes (``conc1d[i, j]`` is IDL's
  ``conc1d[i, j]``), so the IDL dimensions *are* the numpy shape and the
  bytes are the array in Fortran order. ``readsav`` therefore returns the
  transpose of the port's array, exactly as it does for an IDL-written file.

**Python value -> IDL type** (the port's arrays already carry their IDL
types; only native Python scalars in ``op`` need a rule):

- numpy scalars and arrays keep their dtype: ``uint8``->BYTE, ``int16``->INT,
  ``int32``->LONG, ``float32``->FLOAT, ``float64``->DOUBLE,
  ``complex64``->COMPLEX, ``complex128``->DCOMPLEX, ``uint16``->UINT,
  ``uint32``->ULONG, ``int64``->LONG64, ``uint64``->ULONG64, ``bool``->BYTE;
- a Python ``int`` follows IDL's integer-literal rule: INT if it fits
  16 bits, else LONG, else LONG64 (``soda2_update_op.pro:30``'s
  ``seatag=[33000,0,0]`` is LONG for that reason, ``update_op.py``); a list
  of ints takes the widest element's type, as an IDL array literal does;
- a Python ``float`` is **DOUBLE**. That is the port's standing convention
  (a Python float is a C double; ``process_2d.py``'s ``activetime`` rule
  reads it the same way). IDL's bare ``1.0`` is FLOAT: a caller who wants
  FLOAT passes ``np.float32``;
- ``str`` -> STRING; a ``dict`` or dataclass -> an anonymous one-element
  structure, tags in insertion / declaration order, names upper-cased.

**Refused by name** (:class:`IdlSaveUnsupported`), never silently coerced:
``int8``/``float16``/object arrays (no IDL type), a zero-length array (IDL
has none), more than 8 dimensions (IDL's limit), ``None``, arrays of
structures (the SODA-2 ``data`` has none), strings that are not Latin-1,
and a single array over 2**31-1 bytes (the 64-bit ``ARRSTART 18``
descriptor; no SODA-2 field approaches it).
"""
from __future__ import annotations

import dataclasses
import getpass
import platform
import socket
import struct
import time
import zlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

__all__ = [
    "IdlSaveUnsupported",
    "PROCESS_DATA_TAGS",
    "write_idl_save",
    "save_process_data",
    "struct_layout",
]


class IdlSaveUnsupported(ValueError):
    """A value this writer cannot represent in an IDL SAVE file."""


#: ``soda2_process_2d.pro:678-687`` -- the ``data`` tag order, transcribed
#: from the source (not from ``ProcessData``; ``test_soda2_save_writer`` checks
#: the two agree). ``Date_Processed`` is written upper-case, as IDL stores
#: every tag name.
PROCESS_DATA_TAGS: tuple[str, ...] = (
    "op", "time", "tas", "probetas", "midbins", "activetime",
    "date_processed", "sa", "intspec_all", "intspec_accepted",
    "intendbins", "intmidbins", "count_rejected",
    "total_count_rejected", "count_accepted", "count_missed",
    "missed_hist", "conc1d", "spec1d", "spec2d", "spec2d_aspr",
    "corr_fac", "poisson_fac", "intcutoff", "zdspec",
    "zdendbins", "zdmidbins", "pointer", "ind", "currentfile",
    "numbuffsaccepted", "numbuffsrejected", "dhist", "hist3d",
    "spec2d_orientation", "orientation_index", "house",
    "pbpstartindex",
)

# --- IDL type codes -------------------------------------------------------

BYTE, INT, LONG, FLOAT, DOUBLE, COMPLEX, STRING, STRUCT = 1, 2, 3, 4, 5, 6, 7, 8
DCOMPLEX, UINT, ULONG, LONG64, ULONG64 = 9, 12, 13, 14, 15

_DTYPE_TO_CODE: dict[str, int] = {
    "u1": BYTE, "b1": BYTE, "i2": INT, "i4": LONG, "f4": FLOAT, "f8": DOUBLE,
    "c8": COMPLEX, "c16": DCOMPLEX, "u2": UINT, "u4": ULONG, "i8": LONG64,
    "u8": ULONG64,
}
#: code -> big-endian wire dtype for the raw-bytes array types.
_WIRE: dict[int, str] = {
    BYTE: ">u1", INT: ">i4", LONG: ">i4", FLOAT: ">f4", DOUBLE: ">f8",
    COMPLEX: ">c8", DCOMPLEX: ">c16", UINT: ">u4", ULONG: ">u4",
    LONG64: ">i8", ULONG64: ">u8",
}
#: In-memory element size and alignment on 64-bit IDL (``IDL_STRING`` is 16
#: bytes, 8-aligned). Measured: every tag offset of an IDL 8.5-written SODA-2
#: ``data`` and its ``op`` follows these with C natural alignment
#: (``test_soda2_save_writer.TestLayoutAgainstIdlDescriptor``).
_SIZE: dict[int, int] = {
    BYTE: 1, INT: 2, LONG: 4, FLOAT: 4, DOUBLE: 8, COMPLEX: 8, STRING: 16,
    DCOMPLEX: 16, UINT: 2, ULONG: 4, LONG64: 8, ULONG64: 8,
}
_ALIGN: dict[int, int] = {
    BYTE: 1, INT: 2, LONG: 4, FLOAT: 4, DOUBLE: 8, COMPLEX: 4, STRING: 8,
    DCOMPLEX: 8, UINT: 2, ULONG: 4, LONG64: 8, ULONG64: 8,
}

#: Descriptor flag values IDL 8.5 wrote (measured from an IDL-written
#: ``.dat``'s descriptor): ``IDL_V_ARR`` 4, ``IDL_V_DYNAMIC`` 16,
#: ``IDL_V_STRUCT`` 32. GDL writes 0 / 4 / 36 and ``PREDEF`` 40 instead.
_FLAG_SCALAR, _FLAG_STRING, _FLAG_ARRAY, _FLAG_STRUCT = 0, 16, 20, 52
_PREDEF = 8

_INT16 = (-(2**15), 2**15 - 1)
_INT32 = (-(2**31), 2**31 - 1)
_MAX_ARRAY_BYTES = 2**31 - 1

# --- the value model -------------------------------------------------------


@dataclasses.dataclass
class _Scalar:
    code: int
    value: Any


@dataclasses.dataclass
class _Array:
    code: int
    dims: tuple[int, ...]      # IDL order (= the port's numpy shape)
    flat: np.ndarray           # IDL (column-major) element order


@dataclasses.dataclass
class _Struct:
    tags: list[tuple[str, _Scalar | _Array | _Struct]]


_Node = _Scalar | _Array | _Struct


def _int_code(lo: int, hi: int) -> int:
    if _INT16[0] <= lo and hi <= _INT16[1]:
        return INT
    if _INT32[0] <= lo and hi <= _INT32[1]:
        return LONG
    if -(2**63) <= lo and hi <= 2**63 - 1:
        return LONG64
    raise IdlSaveUnsupported(f"integer {lo if lo < 0 else hi} does not fit IDL LONG64")


def _code_of_dtype(dtype: np.dtype, where: str) -> int:
    key = dtype.kind + str(dtype.itemsize) if dtype.kind != "b" else "b1"
    code = _DTYPE_TO_CODE.get(key)
    if code is None:
        raise IdlSaveUnsupported(f"{where}: numpy dtype {dtype} has no IDL type")
    return code


def _latin1(s: str, where: str) -> bytes:
    try:
        return s.encode("latin1")
    except UnicodeEncodeError as exc:
        raise IdlSaveUnsupported(f"{where}: string is not Latin-1: {s!r}") from exc


def _array_node(arr: np.ndarray, where: str) -> _Array:
    if arr.size == 0:
        raise IdlSaveUnsupported(f"{where}: zero-length array (IDL has none)")
    if arr.ndim > 8:
        raise IdlSaveUnsupported(f"{where}: {arr.ndim} dimensions (IDL allows 8)")
    if arr.dtype.kind in ("U", "S"):
        flat = np.array([str(x) if arr.dtype.kind == "U" else x.decode("latin1")
                         for x in arr.flatten(order="F")], dtype=object)
        for s in flat:
            _latin1(s, where)
        return _Array(STRING, tuple(arr.shape), flat)
    if arr.dtype == object:
        items = arr.flatten(order="F").tolist()
        if all(isinstance(x, str) for x in items):
            for s in items:
                _latin1(s, where)
            return _Array(STRING, tuple(arr.shape), np.array(items, dtype=object))
        raise IdlSaveUnsupported(f"{where}: object array that is not all strings")
    code = _code_of_dtype(arr.dtype, where)
    nbytes = arr.size * _SIZE[code]
    if nbytes > _MAX_ARRAY_BYTES:
        raise IdlSaveUnsupported(
            f"{where}: {nbytes} bytes needs the 64-bit ARRSTART-18 descriptor, "
            "not written by this port")
    flat = np.asarray(arr).flatten(order="F")
    if arr.dtype.kind == "b":
        flat = flat.astype(np.uint8)
    return _Array(code, tuple(arr.shape), flat)


def _node(value: Any, where: str) -> _Node:
    """Python/numpy value -> the typed value model (module docstring rules)."""
    if value is None:
        raise IdlSaveUnsupported(f"{where}: None has no IDL value")
    if isinstance(value, (_Scalar, _Array, _Struct)):
        return value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _Struct([(f.name.upper(), _node(getattr(value, f.name), f"{where}.{f.name}"))
                        for f in dataclasses.fields(value)])
    if isinstance(value, Mapping):
        return _Struct([(str(k).upper(), _node(v, f"{where}.{k}")) for k, v in value.items()])
    if isinstance(value, str):
        _latin1(value, where)
        return _Scalar(STRING, value)
    if isinstance(value, (bool, np.bool_)):
        return _Scalar(BYTE, int(value))
    if isinstance(value, np.generic):
        code = _code_of_dtype(value.dtype, where)
        return _Scalar(code, value)
    if isinstance(value, int):
        return _Scalar(_int_code(value, value), value)
    if isinstance(value, float):
        return _Scalar(DOUBLE, value)
    if isinstance(value, np.ndarray):
        if value.ndim == 0:
            return _node(value[()], where)
        return _array_node(value, where)
    if isinstance(value, Sequence):
        items = list(value)
        if not items:
            raise IdlSaveUnsupported(f"{where}: empty list (IDL has no zero-length array)")
        if any(isinstance(x, (Mapping, list, tuple)) or dataclasses.is_dataclass(x)
               for x in items):
            raise IdlSaveUnsupported(f"{where}: nested list / array of structures")
        if all(isinstance(x, str) for x in items):
            return _array_node(np.array(items, dtype=object), where)
        if all(isinstance(x, int) and not isinstance(x, bool) for x in items):
            code = _int_code(min(items), max(items))
            dt = {INT: np.int16, LONG: np.int32, LONG64: np.int64}[code]
            return _array_node(np.array(items, dtype=dt), where)
        if all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in items):
            return _array_node(np.array(items, dtype=np.float64), where)
        return _array_node(np.asarray(items), where)
    raise IdlSaveUnsupported(f"{where}: {type(value).__name__} has no IDL mapping")


# --- in-memory layout (the descriptor's tag offsets) -----------------------


def _size_align(node: _Node) -> tuple[int, int]:
    if isinstance(node, _Struct):
        size, align, _ = _struct_layout(node)
        return size, align
    n = int(np.prod(node.dims)) if isinstance(node, _Array) else 1
    return _SIZE[node.code] * n, _ALIGN[node.code]


def _struct_layout(node: _Struct) -> tuple[int, int, list[int]]:
    offset, max_align, offsets = 0, 1, []
    for _, child in node.tags:
        size, align = _size_align(child)
        offset = (offset + align - 1) // align * align
        offsets.append(offset)
        offset += size
        max_align = max(max_align, align)
    size = (offset + max_align - 1) // max_align * max_align
    return size, max_align, offsets


def struct_layout(value: Any) -> tuple[int, list[tuple[str, int]]]:
    """``(size, [(TAG, offset), ...])`` of ``value`` as a 64-bit IDL
    structure -- the offsets this writer puts in the descriptor."""
    node = _node(value, "value")
    if not isinstance(node, _Struct):
        raise IdlSaveUnsupported("struct_layout: value is not a structure")
    size, _, offsets = _struct_layout(node)
    return size, [(name, off) for (name, _), off in zip(node.tags, offsets, strict=True)]


# --- encoding --------------------------------------------------------------


def _long(v: int) -> bytes:
    return struct.pack(">l", v)


def _pad4(b: bytes) -> bytes:
    return b + b"\x00" * (-len(b) % 4)


def _name(s: str) -> bytes:
    """A record/descriptor STRING (``_read_string``): length, bytes, pad."""
    raw = _latin1(s, "name")
    return _long(len(raw)) + _pad4(raw)


def _string_data(s: str) -> bytes:
    """A data STRING (``_read_string_data``): length twice, bytes, pad; an
    empty string is a single LONG 0."""
    raw = _latin1(s, "string")
    if not raw:
        return _long(0)
    return _long(len(raw)) + _long(len(raw)) + _pad4(raw)


def _scalar_data(code: int, value: Any) -> bytes:
    if code == BYTE:
        return _long(1) + struct.pack(">B", int(value)) + b"\x00\x00\x00"
    if code == INT:
        return struct.pack(">i", int(np.int16(value)))
    if code == UINT:
        return struct.pack(">I", int(np.uint16(value)))
    if code == STRING:
        return _string_data(value)
    return np.asarray(value, dtype=_WIRE[code]).reshape(1).tobytes()


def _array_data(node: _Array) -> bytes:
    if node.code == STRING:
        return b"".join(_string_data(s) for s in node.flat)
    if node.code == BYTE:
        raw = node.flat.astype(">u1").tobytes()
        return _long(len(raw)) + _pad4(raw)
    if node.code in (INT, UINT):
        # widened to 4 bytes per element: INT sign-extends, UINT zero-extends
        return node.flat.astype(_WIRE[node.code]).tobytes()
    return _pad4(node.flat.astype(_WIRE[node.code]).tobytes())


def _data(node: _Node) -> bytes:
    if isinstance(node, _Struct):
        return b"".join(_data(child) for _, child in node.tags)
    if isinstance(node, _Array):
        return _array_data(node)
    return _scalar_data(node.code, node.value)


def _arraydesc(code: int, dims: tuple[int, ...], elt_size: int) -> bytes:
    n = int(np.prod(dims))
    full = list(dims) + [1] * (8 - len(dims))
    return b"".join(_long(v) for v in
                    (8, elt_size, elt_size * n, n, len(dims), 0, 0, 8, *full))


def _structdesc(node: _Struct) -> bytes:
    _, _, offsets = _struct_layout(node)
    out = [_long(9), _name(""), _long(_PREDEF), _long(len(node.tags)), _long(0)]
    for (_, child), off in zip(node.tags, offsets, strict=True):
        if isinstance(child, _Struct):
            code, flags = STRUCT, _FLAG_STRUCT
        elif isinstance(child, _Array):
            code, flags = child.code, _FLAG_ARRAY
        else:
            code = child.code
            flags = _FLAG_STRING if code == STRING else _FLAG_SCALAR
        out.append(_long(off) + _long(code) + _long(flags))
    out.extend(_name(name) for name, _ in node.tags)
    for _, child in node.tags:
        if isinstance(child, _Struct):
            out.append(_arraydesc(STRUCT, (1,), _struct_layout(child)[0]))
        elif isinstance(child, _Array):
            out.append(_arraydesc(child.code, child.dims, _SIZE[child.code]))
    for _, child in node.tags:
        if isinstance(child, _Struct):
            out.append(_structdesc(child))
    return b"".join(out)


def _variable_body(name: str, node: _Node) -> bytes:
    if isinstance(node, _Struct):
        typedesc = (_long(STRUCT) + _long(_FLAG_STRUCT)
                    + _arraydesc(STRUCT, (1,), _struct_layout(node)[0])
                    + _structdesc(node))
    elif isinstance(node, _Array):
        typedesc = (_long(node.code) + _long(_FLAG_ARRAY)
                    + _arraydesc(node.code, node.dims, _SIZE[node.code]))
    else:
        typedesc = _long(node.code) + _long(
            _FLAG_STRING if node.code == STRING else _FLAG_SCALAR)
    return _name(name.upper()) + typedesc + _long(7) + _data(node)


def _timestamp_body(date: str, user: str, host: str) -> bytes:
    return b"\x00" * 1024 + _name(date) + _name(user) + _name(host)


def _version_body() -> bytes:
    # The layout reproduced is IDL 8.5's (format 12, measured); `release`
    # names that layout, not the program that wrote the file -- the
    # TIMESTAMP's user/host say who did.
    os_name = "Win32" if platform.system() == "Windows" else platform.system().lower()
    return _long(12) + _name("x86_64") + _name(os_name) + _name("8.5")


def write_idl_save(
    path: str | Path,
    variables: Mapping[str, Any],
    *,
    compress: bool = False,
    timestamp: tuple[str, str, str] | None = None,
) -> Path:
    """``save, file=path, <variables>[, /compress]``.

    ``variables`` maps each IDL variable name to its value (module docstring
    for the type rules), written in mapping order. ``timestamp`` overrides
    the ``(date, user, host)`` the ``TIMESTAMP`` record carries (default:
    now in IDL's ``systime()`` form, this user, this host) -- tests pin it so
    two writes of the same data are byte-identical."""
    if not variables:
        raise IdlSaveUnsupported("save: no variables")
    if timestamp is None:
        timestamp = (time.strftime("%a %b %d %H:%M:%S %Y"), getpass.getuser(),
                     socket.gethostname())
    bodies: list[tuple[int, bytes]] = [
        (10, _timestamp_body(*timestamp)),
        (14, _version_body()),
    ]
    for name, value in variables.items():
        bodies.append((2, _variable_body(name, _node(value, name))))

    out = bytearray(b"SR" + (b"\x00\x06" if compress else b"\x00\x04"))
    for rectype, body in bodies:
        payload = zlib.compress(body) if compress else body
        nextrec = len(out) + 16 + len(payload)
        out += _long(rectype) + struct.pack(">II", nextrec & 0xFFFFFFFF, nextrec >> 32)
        out += b"\x00" * 4 + payload
    out += _long(6) + b"\x00" * 12
    path = Path(path)
    path.write_bytes(bytes(out))
    return path


def _process_data_struct(data: Any) -> dict[str, Any]:
    """``ProcessData`` -> the ``data`` struct in ``:678-687`` tag order. The
    two port-tooling fields (``pbp_csv_path``/``pbp_ncdf_path``) are not IDL
    tags and are not written."""
    return {tag: getattr(data, tag) for tag in PROCESS_DATA_TAGS}


def save_process_data(path: str | Path, data: Any, *, compress: bool = True,
                      timestamp: tuple[str, str, str] | None = None) -> Path:
    """``soda2_process_2d.pro:731``: ``save, file=fn_out, data, /compress``."""
    return write_idl_save(path, {"data": _process_data_struct(data)},
                          compress=compress, timestamp=timestamp)
