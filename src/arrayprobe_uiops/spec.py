# SPDX-License-Identifier: BSD-3-Clause
"""``read_binary_SPEC.m``'s record-walking driver (UIOOPS v3.5).

An earlier stage took this file's **pure** half -- `interp_tas`, the TAS-update gate and the
probe/aircraft TAS ratio -- into :mod:`arrayprobe_uiops.tas` and validated it on a
case grid. This module is the other half: the record loop, ``readRecord``,
``get_img``'s packet walk, the three ``.csv`` sidecars and the netCDF writer.
It needs a real binary file and a real netCDF writer, so it was validated the
way the earlier translation's reader was -- by running **the whole vendored v3.5 program,
unmodified**, under Octave 11.3.0 on a synthetic raw fixture and comparing what
each program wrote (``octave_oracle/run_v35_spec_bank.py``,
``tests/test_v35_spec.py``).

**Oracle layer 2 only.** No archived product was ever written by v3.5 -- v3.5
postdates every campaign this project holds -- so nothing here has the
archived-product (layer 1) validation the earlier translation's reader has.

Reuse
-----

Everything the two releases share is imported from
:mod:`arrayprobe.readers.spec` rather than re-translated: the record iterator,
the image canvas, the run-length decoders, the header-slice writer and the
packed-image conversion. Only what the diff actually changed is written again
here. ``tests/test_v35_spec.py::TestReuseIsNotAccidental`` names each borrowed
helper, so a rename in the earlier translation fails here loudly instead of silently
falling back to a local copy.

What v3.5 changed, and what this module does about each
------------------------------------------------------

1. **The scan bound**, ``while iii<=2048`` -> ``while iii+4<=2048``
   (``:297``, Finlon 04/17/20, "Watch for index outside of image buffer"). It
   is a safety fix *and* a behaviour change: words 2045-2048 are no longer
   examined at all, so a packet whose marker lands there is silently dropped.
   Measured against both vendored trees on the same bytes -- see
   :data:`LATE_MARKER_FIRST_SKIPPED`.
2. **The TAS output and its gate** (``:294``, ``:407-413``). ``get_img`` now
   returns the record's TAS, carried forward from the previous record when the
   current reading is missing or suspect. The gate itself is
   :func:`arrayprobe_uiops.tas.update_tas`; this module supplies the housekeeping
   values it judges.
3. **The 15-column ``.tas.csv``** (``:400-405``, ``:416-418``): six end-diode
   voltages joined the nine v3.1.4 columns, each word scaled by
   ``0.00244140625``. The column that was already there changed meaning -- see
   :class:`SidecarWriterV35`.
4. **NETCDF4 output**, ``.H.cdf``/``.V.cdf`` -> ``.H.nc``/``.V.nc``, with two
   new variables (``tas``, ``tasRatio``), three new global attributes, per-
   variable deflate and a ``_FillValue`` on ``tas``. See
   :data:`WRITER_GAPS` for the two parts of that this port does **not**
   reproduce and why.
5. **The day-rollover clamp** (``:224-226``), applied inside the V-channel
   write block only. Preserved exactly, asymmetry included.
6. **An optional whole-record time offset** (``:148-151``). Implemented from
   documented semantics, not from an Octave run -- see :data:`WRITER_GAPS`.

Preserved defects
-----------------

Every one of these was measured on the v3.5 source, not carried over on the
assumption that "the diff did not touch it":

* **The last record of a file is never a primary.** Unchanged from v3.1.4:
  ``iter_record_windows`` yields *n-1* windows -- *n* when a partial record
  follows the last whole one, which keeps the EOF probe from failing once more.
* **``.MK.csv`` has no line terminators.** ``:429-431`` still declares twenty
  ``%d`` conversions for nineteen values, so ``fprintf`` drops the trailing
  ``' \n'``. This was first inferred from the
  diff's *silence*; the oracle then ran the v3.5 program and measured it.
* **The housekeeping walk advances by 53 for a 53-word packet** (``:421``),
  one short, so the final word is re-examined. Unchanged.
* **``nStereo`` is read and never used** (``:393``), in both releases.
* **``daystart`` is dead machinery.** ``:140`` sets ``daystart = 99999999`` and
  nothing ever reads it; ``readRecord`` declares it as both an input and an
  eleventh output (``:269``) and assigns it nowhere, and both call sites pass
  one argument and request ten outputs. The day handling that reached
  production is the V-only ``hour>=24`` clamp, nothing more.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import os
import struct
import time as _time
import warnings
from collections.abc import Sequence
from typing import Any

import numpy as np

from arrayprobe_uiops.spec_core import (
    _MASK_COUNT,
    _MASK_TIMING,
    DATA_WORDS,
    DIODES,
    IMG_BLOCKLEN,
    IMG_ROWLEN,
    MARKER_2S,
    MARKER_HK,
    MARKER_MK,
    RECORD_BYTES,
    RECORD_WORDS,
    RecordHeader,
    SidecarWriter,
    SpawnRetryWarning,
    _at,
    _decode_runs_auto,
    _decode_runs_scalar,
    _ImageCanvas,
    _marker_positions,
    _merge_sidecars,
    _next_marker,
    _pack_image,
    _report_part_progress,
    _write_header_slice,
    iter_record_windows,
    record_window_count,
    sixteen2int,
)
from arrayprobe_uiops.tas import Series, TasValue, interp_tas, tas_ratio, update_tas

from . import ncio, provenance

#: Names re-exported from the v3.1.4 port unchanged, so a v3.5 caller does not
#: have to reach into the other package for the pieces the two releases share.
#: ``tests/test_v35_spec.py::TestReuseIsNotAccidental`` asserts each is the SAME
#: object as the v3.1.4 port's, so this stays a re-export and never drifts into
#: a second copy.
SHARED_WITH_V314 = (
    "DATA_WORDS",
    "DIODES",
    "IMG_BLOCKLEN",
    "IMG_ROWLEN",
    "MARKER_2S",
    "MARKER_HK",
    "MARKER_MK",
    "RECORD_BYTES",
    "RECORD_WORDS",
    "RecordHeader",
    "iter_record_windows",
    "sixteen2int",
)

__all__ = [
    # This module's own surface.
    "DIODE_VOLTAGE_SCALE",
    "INITIAL_TAS",
    "LATE_MARKER_FIRST_SKIPPED",
    "SCAN_LIMIT",
    "SHARED_WITH_V314",
    "SeamRerunWarning",
    "WRITER_GAPS",
    "SidecarWriterV35",
    "apply_time_offset",
    "get_img_v35",
    "hk_readings_v35",
    "read_binary_spec_v35",
    "read_binary_spec_v35_parallel",
    # Re-exports, listed literally so a linter can see they are deliberate;
    # SHARED_WITH_V314 above is the same list in a form a test can iterate.
    "DATA_WORDS",
    "DIODES",
    "IMG_BLOCKLEN",
    "IMG_ROWLEN",
    "MARKER_2S",
    "MARKER_HK",
    "MARKER_MK",
    "RECORD_BYTES",
    "RECORD_WORDS",
    "RecordHeader",
    "iter_record_windows",
    "sixteen2int",
]

#: ``read_binary_SPEC.m:297``. The scan visits ``iii`` while ``iii + 4 <= 2048``,
#: so the last position examined is 2044 -- four short of v3.1.4's 2048.
SCAN_LIMIT = DATA_WORDS - 4

#: The first word position v3.5 declines to examine and v3.1.4 does examine.
#: A marker here is decoded by v3.1.4 and dropped by v3.5, measured on the same
#: bytes by ``octave_oracle/run_v35_spec_bank.py``'s ``bound_*`` cases.
LATE_MARKER_FIRST_SKIPPED = SCAN_LIMIT + 1  # 2045

#: ``:137``. ``previousTAS`` before any housekeeping packet has been seen. It is
#: written to the netCDF as-is for every record up to the first accepted
#: reading, and ``:185-186`` reads it back as "uncorrectable" when forming the
#: TAS ratio.
INITIAL_TAS = -999.0

#: ``:400-405``. Each end-diode voltage word is scaled by this. The literal is
#: exactly ``10 / 4096`` -- a 12-bit converter over a 10 V full scale -- which
#: upstream writes as the decimal 0.00244140625 with no comment saying so.
#: Derived, then checked: the decimal is exact in binary, so the two are the
#: same number and not merely close.
DIODE_VOLTAGE_SCALE = 0.00244140625

#: What this port does NOT reproduce about v3.5's output file, stated rather
#: than left to be discovered. Both are properties of the netCDF *encoding*,
#: not of any value the file carries.
#:
#: ``deflate``
#:     ``:96-106`` calls ``netcdf.defVarDeflate(f, varid, true, true, 9)`` on
#:     every variable. This port's files are NETCDF4 and uncompressed. The
#:     project's single netCDF encoder, ``arrayprobe_uiops.ncio``, owns the MATLAB
#:     dimension reversal and the MATLAB type map and exposes no deflate
#:     parameter, and forking it -- or hand-rolling the transpose beside it --
#:     is what the project's NetCDF-axis convention forbids. Deflate is lossless and
#:     invisible to every reader: the arrays read back are identical either way,
#:     which ``tests/test_v35_spec.py::TestWriterGaps`` measures rather than
#:     asserts. Closing it properly is a ``deflate=`` keyword on
#:     ``ncio.def_var``.
#: ``tas_fill_value``
#:     ``:105`` calls ``netcdf.defVarFill(f, varid9, false, -999.)``, giving the
#:     ``tas`` variable a ``_FillValue`` of -999. netCDF4-python can only set
#:     ``_FillValue`` at variable-creation time, which ``ncio.def_var`` does not
#:     expose either. The attribute is never *exercised* by this program --
#:     ``tas`` is written for every record on both channels, measured in the
#:     oracle -- so no value differs; the attribute is simply absent.
#: ``time_offset``
#:     ``:148-151``'s ``varargin{3}`` path builds a MATLAB ``datetime`` and adds
#:     ``seconds(timeOffset)``. Octave 11.3.0's ``datatypes`` package supplies
#:     ``datetime`` but **not** ``plus`` for it ("plus method not defined for
#:     datetime class", measured 2026-09-11), so this one path has no Octave
#:     oracle. It is implemented from documented calendar semantics and pinned
#:     by tests, doctrine layer 3.
WRITER_GAPS = ("deflate", "tas_fill_value", "time_offset")


class SidecarWriterV35(SidecarWriter):
    """The v3.1.4 sidecar writer with v3.5's 15-column ``.tas.csv``.

    Source: the appends of ``get_img`` in ``read_binary_SPEC.m:283-443`` (UIOOPS v3.5).

    ``.NV.csv`` and ``.MK.csv`` are untouched by the v3.5 diff and are inherited
    unchanged, **including** the mask file's missing line terminators -- which
    the Octave oracle of the SPEC reader re-measured against the v3.5 source
    rather than inheriting on the strength of the diff not mentioning it.

    Three things changed about ``.tas.csv`` and only one of them is visible in the
    format string. The third is that ``tas`` is in the row, and its class
    sets the row's: from the first accepted reading on it is a single, and
    every ``%f`` column is printed at single precision (see :meth:`tas`). The
    other two:

    * six columns were appended (``:416``), the H and V end-diode voltages, each
      word times :data:`DIODE_VOLTAGE_SCALE`; and
    * **the second column stopped being the probe's reading.** v3.1.4 wrote the
      value it had just bit-cast out of the packet. v3.5 writes ``tas``, the
      value that survived the update gate (``:407-413``) -- so a record whose
      probe TAS was rejected as suspect is logged with the *previous* record's
      TAS, and the rejected reading is not recorded anywhere. Measured: the
      oracle's ``tasTemp = 170`` and ``nHOL = 1`` records both log ``50.0``,
      the last accepted value. Preserved, not corrected.
    """

    def tas(  # type: ignore[override]  # v3.5 widens the row; see the docstring
        self,
        timehhmmss: Any,
        tas: Any,
        time: Any,
        n_twm: Any,
        n_scm: Any,
        n_hol: Any,
        n_vol: Any,
        n_vpd: Any,
        n_hpd: Any,
        v_he1: Any = 0.0,
        v_he2: Any = 0.0,
        v_he3: Any = 0.0,
        v_ve1: Any = 0.0,
        v_ve2: Any = 0.0,
        v_ve3: Any = 0.0,
    ) -> None:
        """``:416-418`` -- fifteen fields, nine ``%f`` and six ``%d``... almost.

        The real format is
        ``'%f, %f, %f, %d, %d, %d, %d, %d, %d, %f, %f, %f, %f, %f, %f\\n'``:
        three ``%f``, six ``%d``, six ``%f``. Fifteen conversions for fifteen
        values, so -- unlike ``.MK.csv`` -- this writer is well formed and the
        line terminator is written.
        """
        if not self.enabled:
            return
        # :418 builds the row as ONE array, [timehhmmss tas time ...]. Once
        # `tas` is a single -- from the first accepted probe reading on -- that
        # concatenation is single, so every %f column is printed after
        # rounding to float32: 123454.999 prints as 123455.000000 and a
        # 32-bit `time` counter above 2^24 loses its low bits. Before any
        # reading is accepted `tas` is the double -999 and nothing is rounded.
        # Measured under Octave on the vendored v3.5 tree
        # (tests/test_reader_edge_octave.py::SpecAgainstOctave). The %d columns are
        # 16-bit words, exact in either class.
        cast = _as_single if isinstance(tas, np.float32) else float
        self._tas.append(
            f"{_matlab_f(cast(timehhmmss))}, {_matlab_f(float(tas))}, "
            f"{_matlab_f(cast(time))}, "
            f"{int(n_twm):d}, {int(n_scm):d}, {int(n_hol):d}, "
            f"{int(n_vol):d}, {int(n_vpd):d}, {int(n_hpd):d}, "
            + ", ".join(_matlab_f(cast(v)) for v in (v_he1, v_he2, v_he3, v_ve1, v_ve2, v_ve3))
            + "\n"
        )


def _as_single(value: Any) -> float:
    """``single(value)``, returned as the exactly equal Python float."""
    return float(np.float32(value))


def _matlab_f(value: float) -> str:
    """MATLAB's ``%f``: C's for finite values, ``NaN``/``Inf``/``-Inf`` otherwise.

    A housekeeping TAS is a bit-cast of two raw words, so a corrupt packet can
    carry a NaN or infinite single; MATLAB prints those capitalised, where
    Python's ``%f`` prints ``nan``/``inf``.
    """
    if value != value:
        return "NaN"
    if value in (float("inf"), float("-inf")):
        return "Inf" if value > 0 else "-Inf"
    return f"{value:f}"


def get_img_v35(buf: Any, timehhmmss: Any, sidecar: Any = None, tas_prev: TasValue = INITIAL_TAS, *,
                fast: bool = True) -> Any:
    """``read_binary_SPEC.m:283-442``. Returns ``(imgH, imgV, nNext, tas, tasPrev)``.

    Two outputs more than v3.1.4's ``get_img``, and one fewer argument: there is
    no ``FidelityProfile`` here, because **v3.5 has no profile axis for this
    function**. ``spec_buffer_guard`` exists in the earlier translation to choose
    between stock's 2017-03-08 bounds guards and the production variant tree that
    predates them; v3.5 carries those guards unconditionally (``:322``,
    ``:326``, ``:333``, ``:356``, ``:360``, ``:367``), and the production variant
    is a v3.1.4-era fork that was never rebased onto any later release
    (see the two-engines note). There is nothing to select, so nothing is
    offered; inventing a switch here would imply a v3.5 variant that does not
    exist.

    ``buf`` is the **two-record** window (4096 words for a complete pair); only
    ``iii + 4 <= 2048`` is scanned. ``tas`` comes back as the value for this
    record and ``tasPrev`` as the value the *next* record starts from; the
    MATLAB writes ``tasPrev = tas`` only inside the accept branch, where the two
    are equal by construction, so returning both is faithful rather than
    redundant.
    """
    buf = np.asarray(buf)
    decode = _decode_runs_auto if fast else _decode_runs_scalar
    markers = _marker_positions(buf) if fast else None

    img_h = _ImageCanvas()
    img_v = _ImageCanvas()
    i_slice = 0
    iii = 1
    # :294 -- the record's TAS is the previous record's until a packet in THIS
    # record replaces it. A record with no housekeeping packet at all therefore
    # still reports a TAS, and it is the carried one.
    tas = tas_prev
    while iii + 4 <= DATA_WORDS:
        if _at(buf, iii) == MARKER_2S:
            n_h = _at(buf, iii + 1) & _MASK_COUNT
            b_h_timing = _at(buf, iii + 1) & _MASK_TIMING
            n_v = _at(buf, iii + 2) & _MASK_COUNT
            b_v_timing = _at(buf, iii + 2) & _MASK_TIMING
            pc = _at(buf, iii + 3)
            n_s = _at(buf, iii + 4)
            nh_word = _at(buf, iii + 1)
            nv_word = _at(buf, iii + 2)

            if sidecar is not None:
                sidecar.nv(timehhmmss, _at(buf, iii + 2))
                if n_h != 0 and n_v != 0:
                    sidecar.output_txt(n_h, n_v)

            iii += 5
            if b_h_timing != 0 or b_v_timing != 0:
                iii += n_h + n_v
            elif n_h != 0 and iii + n_h - 1 <= buf.size:
                decode(buf, iii, n_h, n_s, img_h, i_slice, True)
                i_slice += n_s + 2
                t_particle = _at(buf, iii + n_h - 2) * 65536 + _at(buf, iii + n_h - 1)
                _write_header_slice(
                    img_h, i_slice, t_particle, nh_word, pc, n_s, with_metadata=True
                )
                iii += n_h
            elif n_v != 0 and iii + n_v - 1 <= buf.size:
                decode(buf, iii, n_v, n_s, img_v, i_slice, True)
                i_slice += n_s + 2
                t_particle = _at(buf, iii + n_v - 2) * 65536 + _at(buf, iii + n_v - 1)
                _write_header_slice(
                    img_v, i_slice, t_particle, nv_word, pc, n_s, with_metadata=True
                )
                iii += n_v

        elif _at(buf, iii) == MARKER_HK:
            # :389 -- two words concatenated MSB-first and reinterpreted as an
            # IEEE single. The result stays float32 all the way to the netCDF
            # and to the TAS ratio; see read_binary_spec_v35.
            raw = (_at(buf, iii - 1 + 50) << 16) | _at(buf, iii - 1 + 51)
            tas_temp = np.uint32(raw).view(np.float32)
            time = _at(buf, iii - 1 + 52) * 65536 + _at(buf, iii - 1 + 53)
            n_hol = _at(buf, iii - 1 + 44)
            n_vol = _at(buf, iii - 1 + 45)
            # :407-413, the TAS gate. `tasPrev` follows `tas` because the MATLAB
            # updates it only where the two already agree.
            # tas_temp stays a numpy float32 and the gate returns whichever of
            # its two inputs it keeps, so `tas` carries MATLAB's CLASS as well
            # as its value: single from the first accepted reading on (and
            # through every later record, via tasPrev), double -999 before
            # that. The class is observable -- :418 concatenates `tas` with
            # doubles, which makes the whole .tas.csv row single (see
            # SidecarWriterV35). The comparisons are unaffected: every value
            # here is exactly representable as a float32.
            tas = update_tas(tas_temp, tas_prev, n_hol, n_vol)
            tas_prev = tas
            if sidecar is not None:
                sidecar.tas(
                    timehhmmss,
                    tas,  # the GATED value, not tas_temp -- see SidecarWriterV35
                    time,
                    _at(buf, iii - 1 + 42),  # nTWM
                    _at(buf, iii - 1 + 43),  # nSCM
                    n_hol,
                    n_vol,
                    _at(buf, iii - 1 + 34),  # nVPD
                    _at(buf, iii - 1 + 35),  # nHPD
                    *(_at(buf, iii - 1 + k) * DIODE_VOLTAGE_SCALE for k in range(2, 8)),
                )
            # :421 advances by 53 for a 53-word packet, one short, so the final
            # word is re-examined on the next pass. Unchanged from v3.1.4.
            iii += 53

        elif _at(buf, iii) == MARKER_MK:
            time_word = _at(buf, iii - 1 + 2) * 65536 + _at(buf, iii - 1 + 3)
            mask_bits = [_at(buf, k) for k in range(iii - 1 + 4, iii - 1 + 19 + 1)]
            time_start = _at(buf, iii - 1 + 20) * 65536 + _at(buf, iii - 1 + 21)
            time_end = _at(buf, iii - 1 + 22) * 65536 + _at(buf, iii - 1 + 23)
            if sidecar is not None:
                sidecar.mask(time_word, mask_bits, time_start, time_end)
            iii += 23

        else:
            iii = _next_marker(markers, iii, buf.size)

    # :441. nNext is measured from 2048 whatever the scan bound is, so the v3.5
    # bound makes it smaller by up to four as well.
    return img_h.result(), img_v.result(), iii - DATA_WORDS, tas, tas_prev


def apply_time_offset(header: RecordHeader, offset_seconds: float) -> RecordHeader:
    """``:148-151`` -- shift one record's whole timestamp by ``timeOffset``.

    Source: ``read_binary_SPEC.m:148-152`` (UIOOPS v3.5).

    ``wkday`` and ``millisec`` are **not** touched, because the MATLAB does not
    touch them: it rebuilds only ``[year, month, day]`` from ``ymd`` and
    ``[hour, minute, second]`` from ``hms`` of a ``datetime`` constructed
    *without* the milliseconds. A negative offset that crosses midnight
    therefore leaves ``wkday`` naming the wrong day, and a fractional offset is
    lost against a ``millisec`` field that stays where it was. Preserved.

    **No Octave oracle** (doctrine layer 3): Octave 11.3.0's ``datatypes``
    package has ``datetime`` but no ``plus`` for it (measured). This
    is calendar arithmetic from documented semantics, pinned by tests.
    """
    base = dt.datetime(
        header.year, header.month, header.day,
        header.hour % 24, header.minute, header.second,
    ) + dt.timedelta(days=header.hour // 24, seconds=float(offset_seconds))
    return RecordHeader(
        year=base.year, month=base.month, wkday=header.wkday, day=base.day,
        hour=base.hour, minute=base.minute, second=base.second,
        millisec=header.millisec,
    )


_TIME_VARS = (
    ("year", "short"),
    ("month", "byte"),
    ("day", "byte"),
    ("hour", "byte"),
    ("minute", "byte"),
    ("second", "byte"),
    ("millisec", "short"),
    ("wkday", "byte"),
)
_TIME_FIELDS = ("year", "month", "day", "hour", "minute", "second", "millisec", "wkday")


class _ImageFileV35:
    """One v3.5 output file: ``.H.nc`` / ``.V.nc``.

    Differs from the earlier translation's ``_ImageFile`` in four ways, all read off the
    diff: the NETCDF4 format, the ``.nc`` extension, three global attributes,
    and the two new record variables ``tas`` and ``tasRatio``. See
    :data:`WRITER_GAPS` for the two encoding details it does not carry.

    ``tasRatio`` is written **only** when the caller supplied an aircraft TAS
    series (``:208-211``, ``:236-239``), exactly as the MATLAB gates it -- so a
    run without one leaves the variable defined and entirely unwritten, and a
    reader gets netCDF's default double fill, ``9.969209968386869e+36``, with
    nothing in the file to say it was never populated. Measured in the oracle's
    ``main_no_tas`` case; preserved rather than papered over with a real value.
    """

    def __init__(self, filename: Any, orientation: str, software: str, *,
                 write_tas_ratio: bool, creation_time: str, block: int = 256,
                 stamp_profile: str | None = None) -> None:
        self.ncid = ncio.create(filename, "clobber", format="NETCDF4")
        dim_time = self.ncid.def_dim("time", ncio.NC_UNLIMITED)
        dim_row = self.ncid.def_dim("ImgRowlen", IMG_ROWLEN)
        dim_block = self.ncid.def_dim("ImgBlocklen", IMG_BLOCKLEN)
        # :90-93 / :116-119. The attribute name carries BOTH a space and an
        # underscore ('Probe Channel_Orientation'); written verbatim, as the
        # output contract requires.
        self.ncid.put_att(ncio.NC_GLOBAL, "Software", software)
        self.ncid.put_att(ncio.NC_GLOBAL, "Creation Time", creation_time)
        self.ncid.put_att(ncio.NC_GLOBAL, "Probe Channel_Orientation", orientation)
        # In-file provenance: arrayprobe_engine / arrayprobe_profile, not MATLAB output.
        for name, value in provenance.engine_attrs(engine="3.5", profile=stamp_profile).items():
            self.ncid.put_att(ncio.NC_GLOBAL, name, value)
        self.varids = [self.ncid.def_var(n, t, dim_time) for n, t in _TIME_VARS]
        self.varid_data = self.ncid.def_var("data", "int", [dim_row, dim_block, dim_time])
        self.varid_tas = self.ncid.def_var("tas", "double", dim_time)
        self.varid_tas_ratio = self.ncid.def_var("tasRatio", "double", dim_time)
        self.ncid.end_def()
        self.count = 0
        self._write_tas_ratio = write_tas_ratio
        self._block = block
        self._times: list[tuple[int, ...]] = []
        self._images: list[np.ndarray] = []
        self._tas: list[float] = []
        self._ratios: list[float] = []

    def append(self, header: RecordHeader, packed: np.ndarray,
               tas: float, tas_ratio_value: float) -> None:
        self._times.append(tuple(getattr(header, f) for f in _TIME_FIELDS))
        self._images.append(packed)
        self._tas.append(float(tas))
        self._ratios.append(float(tas_ratio_value))
        self.count += 1
        if len(self._images) >= self._block:
            self.flush()

    def flush(self) -> None:
        if not self._images:
            return
        start = self.count - len(self._images)
        times = np.asarray(self._times, dtype=np.int64)
        for k, varid in enumerate(self.varids):
            self.ncid.put_var(varid, start, times.shape[0], times[:, k])
        block = np.stack(self._images).transpose(0, 2, 1)  # (n, 1700, 8), on-disk order
        ncio.write_record_block(self.ncid, self.varid_data, start, block)
        self.ncid.put_var(self.varid_tas, start, len(self._tas),
                          np.asarray(self._tas, dtype=np.float64))
        if self._write_tas_ratio:
            self.ncid.put_var(self.varid_tas_ratio, start, len(self._ratios),
                              np.asarray(self._ratios, dtype=np.float64))
        self._times.clear()
        self._images.clear()
        self._tas.clear()
        self._ratios.clear()

    def close(self) -> None:
        self.flush()
        self.ncid.close()


class _CountingSinkV35:
    """A channel counted but not written; see the earlier translation's ``_CountingSink``."""

    def __init__(self) -> None:
        self.count = 0

    def append(self, header: Any, packed: Any, tas: Any, tas_ratio_value: Any) -> None:  # noqa: ARG002
        """Count the record and discard it. The arguments exist only so this
        class is substitutable for :class:`_ImageFileV35` at the call site."""
        self.count += 1

    def flush(self) -> None:
        """Nothing is buffered, so nothing is written."""

    def close(self) -> None:
        """No file was opened; present so the caller can close both channels."""


def read_binary_spec_v35(
    infilename: Any,
    outfilename: Any,
    *,
    software: str,
    flt_time: Sequence[float] | None = None,
    flt_tas: Sequence[float] | None = None,
    time_offset: float | None = None,
    creation_time: str,
    sidecars: bool = True,
    output_txt: bool = False,
    fast: bool = True,
    channels: str = "HV",
    progress: Any = None,
    stamp_profile: str | None = None,
) -> Any:
    """``read_binary_SPEC.m`` (v3.5) -- raw ``.2DS``/``.HVPS`` to ``.H.nc`` + ``.V.nc``.

    Returns ``(n_h, n_v)``, MATLAB's ``kk1-1`` and ``kk2-1``.

    ``software`` is **required and has no default**, and that is the point.
    ``:79-81`` opens ``version.txt`` with a bare relative path and writes its
    contents as the ``Software`` global attribute, so upstream's value is a
    property of the *process's working directory* -- a run launched from
    somewhere else gets a different attribute, or dies, since ``fopen``'s
    failure is unchecked and ``fscanf`` then receives a handle of ``-1``.
    Reproducing a cwd-dependent file read would make this function's output
    depend on where Python happened to be started; naming the string instead
    makes the same fact explicit and recordable. The vendored v3.5 tree's own
    ``version.txt`` reads ``UIOOPS_v3.5``.

    ``creation_time`` is likewise required: ``:91`` (and ``:117`` for the V file) stamps
    ``datestr(now, 'yyyy/mm/dd HH:MM:SS')``, which every byte
    comparison already excludes. Passing it in keeps the function
    deterministic and keeps the caller honest about what it wrote.

    ``flt_time``/``flt_tas`` are ``varargin{1}``/``{2}``, the 1-Hz aircraft
    series. Supplying them is what turns the ``tasRatio`` variable from
    fill-valued into written -- see :class:`_ImageFileV35`. They go through
    :func:`arrayprobe_uiops.tas.interp_tas` exactly once, at the top, as ``:40``
    does; a TAS series with fewer than two usable nodes therefore **aborts the
    decode before a single record is read**, which is the TAS port's measured behaviour
    and is preserved.

    ``time_offset`` is ``varargin{3}``. See :func:`apply_time_offset` and
    :data:`WRITER_GAPS` -- it is the one path with no Octave oracle.

    ``channels`` selects which channel files are *written*; the skipped channel
    is still decoded and still counted, so the return value and every sidecar
    are unchanged. Same storage rationale as the earlier translation's: on the archived
    2016 2D-S the V channel is a recording of a soot-fouled mirror and is by far the
    larger file.
    """
    if channels not in ("HV", "H", "V"):
        raise ValueError(f"channels must be 'HV', 'H' or 'V'; got {channels!r}")
    if (flt_time is None) != (flt_tas is None):
        # :37-39 reads varargin{1} and varargin{2} together; one without the
        # other is an index error there, not a partial mode.
        raise ValueError(
            "flt_time and flt_tas are varargin{1} and varargin{2} of "
            "read_binary_SPEC.m and are supplied together or not at all"
        )
    # :40 -- interpolated once for the whole flight, before any record is read.
    flight: tuple[Series, np.ndarray] | None = (
        None if flt_time is None or flt_tas is None
        else (flt_time, interp_tas(flt_tas))
    )

    def make(suffix: Any, orientation: Any) -> Any:
        return _ImageFileV35(
            f"{outfilename}.{suffix}.nc", orientation, software,
            write_tas_ratio=flight is not None, creation_time=creation_time,
            stamp_profile=stamp_profile,
        )

    out_h = make("H", "Horizontal") if "H" in channels else _CountingSinkV35()
    out_v = make("V", "Vertical") if "V" in channels else _CountingSinkV35()
    sidecar = SidecarWriterV35(outfilename, enabled=sidecars, output_txt=output_txt)
    tas_prev: TasValue = INITIAL_TAS
    try:
        for i, (raw_header, buf) in enumerate(iter_record_windows(infilename)):
            header = (apply_time_offset(raw_header, time_offset)
                      if time_offset is not None else raw_header)
            img_h, img_v, _, tas, tas_prev = get_img_v35(
                buf, header.timehhmmss, sidecar, tas_prev, fast=fast
            )
            ratio = 1.0
            if flight is not None:
                # :176-193. `tas` is a float32 all the way from the packet's
                # `typecast(...,'single')`, and MATLAB's single/double division
                # is computed in single -- measured: 50/120 comes back as
                # 0.4166666567325592. `tas_ratio` already divides in float32
                # (pass 6), so this outer np.float32 is a no-op kept as a guard.
                ratio = float(np.float32(tas_ratio(
                    float(tas), flight[0], flight[1],
                    header.hour, header.minute, header.second,
                )))
            if img_h[:, :IMG_BLOCKLEN].any():
                out_h.append(header, _pack_image(img_h), tas, ratio)
            if img_v[:, :IMG_BLOCKLEN].any():
                # :224-226. The clamp lives INSIDE the V write block and mutates
                # `hour`, so the same physical record is stamped 25:mm:ss in
                # .H.nc and 01:mm:ss in .V.nc. Preserved, asymmetry and all.
                v_header = (header if header.hour < 24
                            else dataclasses.replace(header, hour=header.hour - 24))
                out_v.append(v_header, _pack_image(img_v), tas, ratio)
            if progress is not None:
                progress(i, out_h.count, out_v.count)
    finally:
        sidecar.flush()
        out_h.close()
        out_v.close()
    return out_h.count, out_v.count


# --------------------------------------------------------------------------
# Parallel decode
# --------------------------------------------------------------------------
#
# The v3.5 record loop carries exactly one value from one window to the next:
# ``tas_prev``, the running airspeed the update gate judges each housekeeping
# reading against. Everything else ``get_img_v35`` touches is reset per window,
# the aircraft series is a pure function computed once, and the outputs are
# append-only in window order. So the file can be decoded in ranges, each range
# started from the airspeed the serial loop would have carried into it.
#
# Those start values come from a cheap first pass (:func:`hk_readings_v35`,
# which walks each window's packets without decoding images) replayed through
# the serial gate itself. The first pass is a second copy of the packet walk,
# so it is never trusted on its own: every part reports the airspeed it ended
# on, and a part whose start value does not equal its predecessor's end value,
# bit for bit, is decoded again from the correct one before anything is
# merged. Part 0 starts from INITIAL_TAS, as the serial loop does, and each
# part runs the serial code, so agreement at every seam means the merged output
# is the serial output; a wrong first pass costs time, never bytes.


class SeamRerunWarning(RuntimeWarning):
    """A part of a parallel v3.5 decode started from an airspeed that did not
    equal the previous part's final airspeed, and was decoded again from the
    correct one. The output is unaffected; only time was lost. It means the
    cheap housekeeping pass disagreed with the decoder, which is a defect in
    that pass and worth reporting."""


def _tas_bits(value: float) -> tuple[bool, bytes]:
    """The IEEE bit pattern of an airspeed, and whether it is MATLAB single.
    Seams are compared by bits, not ``==``, because ``+0.0 == -0.0`` and
    ``nan != nan``, and the update gate can keep either sign of zero. The class
    is compared too: a part started from a double where the serial loop carries
    a single would write different ``.tas.csv`` rows (see
    :class:`SidecarWriterV35`)."""
    return isinstance(value, np.float32), struct.pack("<d", float(value))


def hk_readings_v35(buf: Any) -> list[tuple[TasValue, int, int]]:
    """Every housekeeping reading :func:`get_img_v35` would judge, in order.

    Source: walks ``get_img`` in ``read_binary_SPEC.m:283-443`` (UIOOPS v3.5).

    Each item is ``(tas_temp, n_hol, n_vol)``, exactly the first, third and
    fourth arguments ``get_img_v35`` passes to :func:`update_tas`. The walk
    repeats ``get_img_v35``'s advance of ``iii`` packet for packet -- the
    image-packet skip under the same two conditions, 53 words for a
    housekeeping packet, 23 for a mask packet, the next marker otherwise --
    but decodes no image and writes no sidecar, so it costs a small fraction
    of a decode. Feeding the readings through :func:`update_tas` from a
    window's incoming airspeed gives the airspeed the next window starts from.
    """
    buf = np.asarray(buf)
    markers = _marker_positions(buf)
    readings: list[tuple[TasValue, int, int]] = []
    iii = 1
    while iii + 4 <= DATA_WORDS:
        word = _at(buf, iii)
        if word == MARKER_2S:
            n_h = _at(buf, iii + 1) & _MASK_COUNT
            b_h_timing = _at(buf, iii + 1) & _MASK_TIMING
            n_v = _at(buf, iii + 2) & _MASK_COUNT
            b_v_timing = _at(buf, iii + 2) & _MASK_TIMING
            iii += 5
            if b_h_timing != 0 or b_v_timing != 0:
                iii += n_h + n_v
            elif n_h != 0 and iii + n_h - 1 <= buf.size:
                iii += n_h
            elif n_v != 0 and iii + n_v - 1 <= buf.size:
                iii += n_v
        elif word == MARKER_HK:
            raw = (_at(buf, iii - 1 + 50) << 16) | _at(buf, iii - 1 + 51)
            tas_temp = np.uint32(raw).view(np.float32)
            # Kept float32, as get_img_v35 keeps it: the class the gate carries
            # forward is part of the state a part must start from.
            readings.append((tas_temp, _at(buf, iii - 1 + 44), _at(buf, iii - 1 + 45)))
            iii += 53
        elif word == MARKER_MK:
            iii += 23
        else:
            iii = _next_marker(markers, iii, buf.size)
    return readings


def _hk_range_v35(args: Any) -> list[tuple[TasValue, int, int]]:
    """The housekeeping readings of windows ``[lo, hi)``, flattened in window
    order. Runs in a worker process; module level for pickling."""
    infilename, lo, hi = args
    out: list[tuple[TasValue, int, int]] = []
    for _header, buf in iter_record_windows(infilename, lo, hi):
        out.extend(hk_readings_v35(buf))
    return out


def _replay_incoming(readings_by_part: Any) -> list[TasValue]:
    """Each part's incoming airspeed, by running the serial gate over every
    earlier part's readings from :data:`INITIAL_TAS`."""
    incoming: list[TasValue] = []
    tas: TasValue = INITIAL_TAS
    for readings in readings_by_part:
        incoming.append(tas)
        for tas_temp, n_hol, n_vol in readings:
            tas = update_tas(tas_temp, tas, n_hol, n_vol)
    return incoming


def _decode_range_v35(args: Any) -> dict:
    """Decode windows ``[lo, hi)`` into part files, starting from ``tas_in``.

    Runs in a worker process. The loop body is :func:`read_binary_spec_v35`'s,
    unchanged, with the netCDF writer replaced by flat part files the parent
    merges: per written record and channel, the packed image (int32, lossless
    because each packed word holds sixteen bits), the eight time fields with
    the V-channel clamp already applied, the airspeed and the ratio.
    """
    (infilename, prefix, lo, hi, tas_in, flight, time_offset, sidecars, output_txt,
     fast, channels, report_every) = args
    label = os.path.basename(prefix)
    span = hi - lo
    sidecar = SidecarWriterV35(prefix + ".sc", enabled=sidecars, output_txt=output_txt,
                               output_txt_path=prefix + ".sc.txt")
    counts = {"H": 0, "V": 0}
    handles: dict = {}
    times: dict = {"H": [], "V": []}
    tas_rows: dict = {"H": [], "V": []}
    ratio_rows: dict = {"H": [], "V": []}
    dtypes: dict = {}
    tas_prev: TasValue = tas_in
    try:
        for channel in ("H", "V"):
            if channel in channels:
                handles[channel] = open(prefix + "." + channel + ".img", "wb")
        windows = iter_record_windows(infilename, lo, hi)
        for n, (raw_header, buf) in enumerate(windows, start=1):
            header = (apply_time_offset(raw_header, time_offset)
                      if time_offset is not None else raw_header)
            img_h, img_v, _, tas, tas_prev = get_img_v35(
                buf, header.timehhmmss, sidecar, tas_prev, fast=fast
            )
            ratio = 1.0
            if flight is not None:
                ratio = float(np.float32(tas_ratio(
                    float(tas), flight[0], flight[1],
                    header.hour, header.minute, header.second,
                )))
            for channel, img in (("H", img_h), ("V", img_v)):
                if not img[:, :IMG_BLOCKLEN].any():
                    continue
                counts[channel] += 1
                if channel not in handles:
                    continue
                stamped = header
                if channel == "V" and header.hour >= 24:
                    # The serial loop's V-only day-rollover clamp.
                    stamped = dataclasses.replace(header, hour=header.hour - 24)
                packed = _pack_image(img)
                dtypes[channel] = packed.dtype.str
                packed.astype(np.int32).tofile(handles[channel])
                times[channel].append(tuple(getattr(stamped, f) for f in _TIME_FIELDS))
                tas_rows[channel].append(float(tas))
                ratio_rows[channel].append(float(ratio))
            if report_every > 0 and n % report_every == 0:
                _report_part_progress(label, n, span)
    finally:
        for fh in handles.values():
            fh.close()
        sidecar.flush()

    for channel in handles:
        np.save(prefix + "." + channel + ".times.npy",
                np.asarray(times[channel], dtype=np.int64).reshape(-1, len(_TIME_FIELDS)))
        np.save(prefix + "." + channel + ".tas.npy",
                np.asarray(tas_rows[channel], dtype=np.float64))
        np.save(prefix + "." + channel + ".ratio.npy",
                np.asarray(ratio_rows[channel], dtype=np.float64))
    return {"lo": lo, "hi": hi, "prefix": prefix, "counts": counts, "dtypes": dtypes,
            "tas_in": tas_in, "tas_out": tas_prev}


def _merge_parts_v35(parts: Any, outfilename: Any, channels: Any, *, software: str,
                     creation_time: str,
                     write_tas_ratio: bool, stamp_profile: str | None) -> Any:
    """Write the real ``.H.nc``/``.V.nc`` from the parts, in range order.

    NETCDF4 is HDF5, whose on-disk layout can depend on the sizes of the
    writes that built it, so the parts are not block-written. Every record goes
    through :meth:`_ImageFileV35.append`, one at a time, into files made by the
    same constructor in the same order as the serial path: the library sees the
    serial path's call sequence, including its 256-record flushes.
    """
    parts = sorted(parts, key=lambda p: p["lo"])

    def make(suffix: Any, orientation: Any) -> Any:
        return _ImageFileV35(
            f"{outfilename}.{suffix}.nc", orientation, software,
            write_tas_ratio=write_tas_ratio, creation_time=creation_time,
            stamp_profile=stamp_profile,
        )

    out = {
        "H": make("H", "Horizontal") if "H" in channels else _CountingSinkV35(),
        "V": make("V", "Vertical") if "V" in channels else _CountingSinkV35(),
    }
    try:
        for part in parts:
            for channel in ("H", "V"):
                n = part["counts"][channel]
                handle = out[channel]
                if channel not in channels:
                    handle.count += n
                    continue
                if n == 0:
                    continue
                prefix = part["prefix"] + "." + channel
                images = np.memmap(prefix + ".img", dtype=np.int32, mode="r",
                                   shape=(n, IMG_ROWLEN, IMG_BLOCKLEN))
                stamps = np.load(prefix + ".times.npy")
                tas = np.load(prefix + ".tas.npy")
                ratio = np.load(prefix + ".ratio.npy")
                dtype = np.dtype(part["dtypes"][channel])
                for i in range(n):
                    header = RecordHeader(**{f: int(stamps[i, k])
                                             for k, f in enumerate(_TIME_FIELDS)})
                    handle.append(header, np.array(images[i], dtype=dtype),
                                  float(tas[i]), float(ratio[i]))
                # Release the map before the part directory is removed (Windows
                # refuses to delete a mapped file).
                del images
    finally:
        for handle in out.values():
            handle.close()
    return out["H"].count, out["V"].count


def _split_decode_v35(infilename: Any, outfilename: Any, edges: Any, mapper: Any, tmp: Any, *,
                      flight: Any, time_offset: Any,
                      software: str, creation_time: str, sidecars: bool, output_txt: bool,
                      fast: bool, channels: str, report_every: int,
                      stamp_profile: str | None, progress: Any = None, stats: Any = None) -> Any:
    """Both rounds, the seam check and the merge, for one set of ``edges``.

    ``mapper`` is a pool's ``map`` or the builtin ``map``; the tests drive every
    split of a small fixture through the builtin one, in process.
    """
    infilename = os.fspath(infilename)
    spans = [(edges[k], edges[k + 1]) for k in range(len(edges) - 1)
             if edges[k + 1] > edges[k]]
    readings = list(mapper(_hk_range_v35, [(infilename, lo, hi) for lo, hi in spans]))
    incoming = _replay_incoming(readings)
    tasks = [
        (infilename, os.path.join(tmp, f"p{k:03d}"), lo, hi, incoming[k], flight,
         time_offset, sidecars, output_txt, fast, channels, report_every)
        for k, (lo, hi) in enumerate(spans)
    ]
    parts = []
    for done, part in enumerate(mapper(_decode_range_v35, tasks), start=1):
        parts.append(part)
        if progress is not None:
            progress(done, len(tasks), part["counts"])
    parts.sort(key=lambda p: p["lo"])

    if parts and _tas_bits(parts[0]["tas_in"]) != _tas_bits(INITIAL_TAS):
        raise AssertionError("the first part of a parallel v3.5 decode did not start "
                             "from INITIAL_TAS")
    reruns = 0
    for k in range(1, len(parts)):
        want = parts[k - 1]["tas_out"]
        if _tas_bits(want) == _tas_bits(parts[k]["tas_in"]):
            continue
        warnings.warn(
            f"parallel v3.5 decode: part {k} started from airspeed "
            f"{parts[k]['tas_in']!r} but part {k - 1} ended on {want!r}; decoding part "
            f"{k} again from the correct value",
            SeamRerunWarning, stacklevel=3)
        task = list(tasks[k])
        task[1] = os.path.join(tmp, f"p{k:03d}_rerun{reruns}")
        task[4] = want
        parts[k] = _decode_range_v35(tuple(task))
        reruns += 1
    if stats is not None:
        stats["parts"] = len(parts)
        stats["reruns"] = reruns

    n_h, n_v = _merge_parts_v35(
        parts, os.fspath(outfilename), channels, software=software,
        creation_time=creation_time, write_tas_ratio=flight is not None,
        stamp_profile=stamp_profile)
    _merge_sidecars(parts, os.fspath(outfilename), output_txt=output_txt)
    return n_h, n_v


def read_binary_spec_v35_parallel(
    infilename: Any,
    outfilename: Any,
    *,
    jobs: int,
    software: str,
    creation_time: str,
    flt_time: Sequence[float] | None = None,
    flt_tas: Sequence[float] | None = None,
    time_offset: float | None = None,
    sidecars: bool = True,
    output_txt: bool = False,
    fast: bool = True,
    channels: str = "HV",
    workdir: Any = None,
    progress: Any = None,
    spawn_retries: int = 2,
    report_every: int = 0,
    stamp_profile: str | None = None,
    stats: dict | None = None,
) -> Any:
    """:func:`read_binary_spec_v35` across ``jobs`` processes, byte-identical output.

    Returns the same ``(n_h, n_v)``. ``jobs <= 1``, or a file with no decode
    window, delegates to the serial function. Every other keyword means what it
    means there, and the checks run in the same order: ``channels``, then the
    flight pair, then :func:`interp_tas`, all before any record is read.

    Two pool rounds share one pool: a cheap housekeeping pass per part, whose
    readings the parent replays through the serial airspeed gate to give every
    part its exact starting airspeed, then the decode. Each part's final
    airspeed is compared bit for bit with the next part's starting one, and a
    part that disagrees is decoded again before the merge (see
    :class:`SeamRerunWarning`). ``stats``, when given a dict, receives
    ``parts`` and ``reruns``.

    ``workdir``, ``spawn_retries`` and ``report_every`` behave as in the earlier
    translation's ``read_binary_SPEC_parallel``: a fresh
    temporary directory per attempt, the whole pool restarted with a
    :class:`arrayprobe_uiops.spec_core.SpawnRetryWarning` when it dies before
    finishing, and one liveness line per ``report_every`` windows per part.

    Byte identity with the serial function, whole files with the same
    ``creation_time``, is asserted in ``tests/test_v35_spec_parallel.py``.
    """
    import concurrent.futures
    import concurrent.futures.process
    import shutil
    import tempfile

    if channels not in ("HV", "H", "V"):
        raise ValueError(f"channels must be 'HV', 'H' or 'V'; got {channels!r}")
    if (flt_time is None) != (flt_tas is None):
        raise ValueError(
            "flt_time and flt_tas are varargin{1} and varargin{2} of "
            "read_binary_SPEC.m and are supplied together or not at all"
        )
    outfilename = os.fspath(outfilename)
    n_windows = record_window_count(infilename)
    if jobs <= 1 or n_windows <= 1:
        return read_binary_spec_v35(
            infilename, outfilename, software=software, flt_time=flt_time,
            flt_tas=flt_tas, time_offset=time_offset, creation_time=creation_time,
            sidecars=sidecars, output_txt=output_txt, fast=fast, channels=channels,
            progress=progress, stamp_profile=stamp_profile)
    flight: tuple[Series, np.ndarray] | None = (
        None if flt_time is None or flt_tas is None
        else (flt_time, interp_tas(flt_tas))
    )

    jobs = min(jobs, n_windows)
    edges = [round(k * n_windows / jobs) for k in range(jobs + 1)]
    n_tasks = sum(1 for k in range(jobs) if edges[k + 1] > edges[k])
    for attempt in range(spawn_retries + 1):
        tmp = tempfile.mkdtemp(prefix="s2parallel_v35_", dir=workdir)
        try:
            try:
                with concurrent.futures.ProcessPoolExecutor(max_workers=n_tasks) as pool:
                    return _split_decode_v35(
                        infilename, outfilename, edges, pool.map, tmp, flight=flight,
                        time_offset=time_offset, software=software,
                        creation_time=creation_time, sidecars=sidecars,
                        output_txt=output_txt, fast=fast, channels=channels,
                        report_every=report_every, stamp_profile=stamp_profile,
                        progress=progress, stats=stats)
            except concurrent.futures.process.BrokenProcessPool:
                # Only a pool that died is retried; an exception raised inside a
                # part comes back through the result queue and propagates. A
                # fresh directory each attempt, because part sidecars append.
                if attempt >= spawn_retries:
                    raise
                warnings.warn(
                    f"parallel v3.5 decode of {os.path.basename(os.fspath(infilename))}: "
                    f"the worker pool died before completing (attempt {attempt + 1} of "
                    f"{spawn_retries + 1}); restarting it from a fresh temporary directory",
                    SpawnRetryWarning, stacklevel=2)
                _time.sleep(2.0 * (attempt + 1))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    raise AssertionError("unreachable")  # pragma: no cover
