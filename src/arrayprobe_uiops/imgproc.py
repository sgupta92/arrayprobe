# SPDX-License-Identifier: BSD-3-Clause
"""v3.5 ``imgProc_sm.m`` -- the driver and writer around the measurement block.

``imgProc_sm.m`` v3.5 (``UIOPS-v3.5/joefinlon-UIOPS-039be82/imgProc_sm.m``,
1417 lines) is 23 hunks away from v3.1.4's.  The per-particle measurement
block ``:1204-1291`` is already ported and Octave-validated as
:func:`arrayprobe_uiops.measure.measure_record`.  This module is everything
around it: the signature, the probe table, the output-file definition, the
record loop, the particle loop (image extraction, particle time), the writer.
It calls ``measure_record`` and re-translates nothing that it does.

**Scope, extended by V-PT (2026-09-16).**  The first port covered probetype 2 alone and
raised :class:`~arrayprobe.imgproc.UnportedProbeType` for the rest.  All four
probetypes now run -- 0 (2DC/2DP), 1 (CIP/PIP), 2 (2DS/HVPS/3VCPI) and 3
(Fast2DC) -- each asserted against its own Octave golden built by
``octave_oracle/run_v35_probetype013_bank.py`` (thirteen cases,
``tests/data/v35_probetype013_oracle.json``, ``tests/test_v35_imgproc_probetypes.py``)
and, for 2DC, against the independent A15 pair as well
(``tests/test_v35_2dc_octave_oracle.py``).  The refusal is **narrowed, not
deleted**: it now fires on an unported *timing branch*
(:data:`PORTED_TIMINGS_V35`) and names what a new probetype would need.

What V-PT had to translate afresh is small, because the two releases' probe
framing and the probetype-0/3 timing blocks are byte-identical (v3.1.4
``:574-686`` == v3.5 ``:855-967``; ``read_binary_PMS.m`` / ``read_binary_DMT.m``
/ ``read_binary_SEA.m`` byte-identical too -- all measured).  New in v3.5 and
therefore newly written here: the **GCPEx CIP clock-offset table**
(``:976-1074``, :data:`_GCPEX_CIP_TABLE`) with its whole-vector carry fixup
(``:1081-1093``, :func:`_normalise_part_time`); the probetype-1
``int_arrival`` carry-over across record boundaries (``:1110-1115``); and the
corrupt-boundary scan's narrowing to ``(PECAN or GCPEx) AND probetype==1``
(``:685``, ``:736`` -- v3.1.4 gated on the project name alone).

**The probetype-2 stage, as first ported:** both ``iRectEllipse``
values (``iRectEllipse=1``, ``:1293-1301``/``:1361-1374``, ported as
:func:`arrayprobe_uiops.rect_ellipse.rect_ellipse_for_image` -- doctrine layer 2,
real compiled ``CGAL_RectSize``/``CGAL_EllipseSize`` MEX oracles, both
``hasExtendedOutputs`` schemas), both ``iQC`` values (``iQC=1``, the
``:801-846`` denoise pass, ported as
:func:`arrayprobe_uiops.qc.qc_image`), both ``iNewHabit`` values, both
``iCalcAllDiodeStats`` values, and the optional ``tasRatio`` series
(``varargin{3}``).

**Reuse from the earlier translation**, allowed because the corresponding MATLAB is
unchanged between the two releases and guarded by
``tests/test_v35_imgproc.py::TestReuseIsNotAccidental``:
:func:`arrayprobe_uiops.imgproc_core._read_record_header`,
:func:`arrayprobe.imgproc._time_in_seconds_from_tas` (the probetype-2 time
block ``:1117-1185`` is byte-identical to v3.1.4's -- the first-particle
``int_arrival`` carry-over ``:1102-1115`` is CIP/PIP only),
:data:`arrayprobe.imgproc.TAS_FALLBACK`, :data:`arrayprobe.imgproc.ROLLBACK_SECONDS`,
:class:`arrayprobe.imgproc.UnportedProbeType`,
:class:`arrayprobe.imgproc.VariableSpec`, :func:`arrayprobe.matlab_compat.dec2bin_concat`
and :mod:`arrayprobe_uiops.ncio`.  Not reused: :class:`arrayprobe.imgproc.ImageWidthMismatch` --
the earlier translation raises it in place of MATLAB's silent ``return``; this port keeps the MATLAB
behaviour instead (see the ``:850-853`` entry below), so the exception is never thrown here.

**Oracle: layer 2 only.**  No archived product was ever written by v3.5, so the
only ground truth is the vendored program itself run under Octave
(``octave_oracle/run_v35_imgproc_bank.py``, Part B of the stage plan).

Preserved as written (each with a regression test named after its line):

* ``:858`` -- ``particle_num = mod(kk, 66536)``, the 65536 typo, unchanged
  from v3.1.4;
* ``:1376-1377`` -- ``varid29`` (``edge_at_max_hole``) receives
  ``max_hole_diameter`` and ``varid30`` (``max_hole_diameter``) receives
  ``edge_at_max_hole``: the two variables are swapped on the way to disk;
* ``:356`` / ``:1329`` -- ``Particle_number_all`` is *defined* under
  ``probetype~=0 || probetype~=3`` (always true) and *written* under ``&&``;
* ``:1394`` -- ``bin_stats`` is rewritten whole every record, no start/count;
* ``:709`` -- ``tasRatio(i)`` is indexed by the absolute record number, so a
  chunked run must pass the whole-file series (the absolute-record tasRatio index);
* ``:850-853`` -- an image not ``diodenum`` wide makes MATLAB ``return`` from
  the whole function, silently, with the file holding whatever was written so
  far.  Reproduced here as a close-and-return that also appends to
  :data:`WIDTH_MISMATCH_RETURNS`, so the loss is measurable after the fact.
"""

from __future__ import annotations

import contextlib
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np

from arrayprobe_uiops.imgproc_core import (
    ROLLBACK_SECONDS,
    TAS_FALLBACK,
    UnportedProbeType,
    VariableSpec,
    _particle_time_fast2dc,
    _particle_time_pms,
    _pecan_pip_hour_offset,
    _read_record_header,
    _time_in_seconds_from_tas,
)
from arrayprobe_uiops.matlab_compat import (
    MGrowVector,
    bin2dec,
    dec2bin_concat,
    madd,
    mint8,
    mmul,
)
from arrayprobe_uiops.reject_core import RejectConfig

from . import diode_mask, ncio, provenance
from . import ncar_2dc_timing as _ncar_2dc
from . import stray_pixel as _stray_pixel
from .habit import _matlab_round
from .measure import (
    HolroydNewResult,
    ParticleMeasurement,
    RecordGeometry,
    measure_record,
)

# Re-exported deliberately, as sizedist re-exports probe_cases: the driver
# reaches `arrayprobe_uiops` only through the `uiops` selector, which is keyed by the v3.1.4
# port's module names, and `stray_pixel` has none. Naming the two stamp strings here makes them
# reachable as `_v35().module("imgproc").STRAY_PIXEL_STAMP_ON` for the `.call` stamp.
from .ncar_2dc_timing import STAMP_OFF as NCAR_2DC_TIMING_STAMP_OFF
from .ncar_2dc_timing import STAMP_ON as NCAR_2DC_TIMING_STAMP_ON
from .qc import qc_image
from .rect_ellipse import RectEllipse, rect_ellipse_for_image
from .stray_pixel import STAMP_OFF as STRAY_PIXEL_STAMP_OFF
from .stray_pixel import STAMP_ON as STRAY_PIXEL_STAMP_ON

__all__ = [
    "PROBES_V35",
    "NCAR_2DC_TIMING_STAMP_ON",
    "NCAR_2DC_TIMING_STAMP_OFF",
    "STRAY_PIXEL_STAMP_ON",
    "STRAY_PIXEL_STAMP_OFF",
    "PARTICLE_NUM_MODULUS_V35",
    "WRITER_GAPS",
    "WRITER_CHUNKING",
    "POSITION_CHUNK_PARTICLES",
    "WIDTH_MISMATCH_RETURNS",
    "CORRUPT_RECORDS",
    "SHARED_WITH_V314",
    "PORTED_TIMINGS_V35",
    "CHUNKABLE_TIMINGS_V35",
    "PRIMABLE_TIMINGS_V35",
    "ChunkingNotEquivalent",
    "ProbeV35",
    "imgproc_variables_v35",
    "imgproc_sm_v35",
    "merge_chunks_v35",
    "prefix_scan_v35",
    "chunk_primes_v35",
    "particle_num_v35",
    "gcpex_cip_offsets",
]

#: Names imported unchanged from the v3.1.4 port -- the guard test asserts
#: identity for each, so a silent copy cannot drift.
SHARED_WITH_V314 = (
    "ROLLBACK_SECONDS",
    "TAS_FALLBACK",
    "UnportedProbeType",
    "VariableSpec",
    # V-PT.  The probetype-0/3 particle-time blocks (v3.5 :861-934) are
    # byte-identical to v3.1.4's :580-652 -- measured, not assumed: the diff
    # between the two releases touches no line of v3.1.4's 574-686 span.
    "_particle_time_pms",
    "_particle_time_fast2dc",
    # v3.5 :946-973 == v3.1.4 :665-693, the PECAN/PIP hour offset.
    "_pecan_pip_hour_offset",
)

# Re-exported so the reuse guard can see them by name on this module.
_REUSED = (ROLLBACK_SECONDS, TAS_FALLBACK)

#: ``imgProc_sm.m:858`` (v3.5) -- ``mod(kk,66536)``.  The same typo as v3.1.4's
#: ``:577``; the literal is kept here, in the v3.5 module, so the module
#: describes its own source line and the test can mutate it in one place.
PARTICLE_NUM_MODULUS_V35 = 66536

#: Encoding details of v3.5's writer this port does not reproduce, in the same
#: shape as :data:`arrayprobe_uiops.spec.WRITER_GAPS`.
#:
#: ``deflate``
#:     Every ``defVar`` is followed by ``netcdf.defVarDeflate(f, varid, true,
#:     true, 9)`` (shuffle + zlib level 9).  :func:`arrayprobe_uiops.ncio.def_var`
#:     exposes no deflate parameter, so the port's file is uncompressed.  This
#:     is invisible to every reader: the arrays read back are identical either
#:     way, which ``tests/test_v35_imgproc.py::TestWriterGaps`` measures rather
#:     than asserts.
#:
#: ``chunking``
#:     v3.5's ``imgProc_sm.m`` sets no chunking, so netCDF-C's default stores
#:     ``position`` as ``[1, 2]`` on disk, one HDF5 chunk per particle.  By the
#:     author's decision (2026-09-30) the port stores it in
#:     :data:`WRITER_CHUNKING`'s ``[1024, 2]`` blocks instead, because that
#:     per-chunk cost dominated the measured write and read of the variable
#:     (measured).  Every
#:     value read back is identical, which
#:     ``tests/test_v35_position_chunking.py`` measures.
WRITER_GAPS = ("deflate", "chunking")

#: Particles per ``position`` chunk: 1,024 x 2 ``short`` = 4,096 bytes, the
#: chunk size in bytes netCDF-C gives ``Date`` and ``Time_in_seconds`` by default.
POSITION_CHUNK_PARTICLES = 1024

#: Chunk sizes the writer sets, in MATLAB order like each variable's dims
#: (``position`` is ``(pos_count, time)``, so ``[1024, 2]`` on disk).  A variable
#: not named keeps the library default.  :data:`WRITER_GAPS` ``chunking``.
WRITER_CHUNKING: dict[str, tuple[int, ...]] = {"position": (2, POSITION_CHUNK_PARTICLES)}

#: ``(record, slice)`` of every ``:850-853`` return taken -- see the module
#: docstring.  Cleared at the start of every :func:`imgproc_sm_v35` call.
WIDTH_MISMATCH_RETURNS: list[tuple[int, int]] = []

#: ``(record, n_corrupt, n_good)`` per record the ``:736-747`` scan rejected.
#: MATLAB only ``fprintf``\\ s this and drops the record's particles silently
#: from the product, so the loss is recorded here to stay measurable after the
#: fact.  Cleared at the start of every :func:`imgproc_sm_v35` call.
CORRUPT_RECORDS: list[tuple[int, int, int]] = []

#: ``{record: n_sync_words_converted}`` for a ``ncar_2dc_timing_fix=True`` probetype-0 run
#: (module ``ncar_2dc_timing``; 0 where the gate or ``fix2dimage.pro`` left a record unchanged).
#: Not UIOOPS state. Cleared at the start of every :func:`imgproc_sm_v35` call.
NCAR_2DC_SYNCS_CONVERTED: dict[int, int] = {}


class ProbeV35:
    """One ``case`` of the probe ``switch`` (``:134-235``), plus the framing
    constants the record loop selects on ``probetype``.

    The framing fields are **not** in the ``switch``: they are the literals
    ``:720-726`` (the read shape), ``:755-760`` (``start_first``), ``:754``
    (``boundary_needs_time``), ``:764-772`` (``image_slice_offset``, which is
    also the offset in the zero-image guard) and ``:785-795`` (``image_invert``
    / ``image_word_bits``) select per probetype.  Each was read from v3.5's own
    file at those lines and, for probetypes 0/1/3, **measured** byte-identical
    to v3.1.4's -- the diff between the two releases touches none of
    ``imgProc_sm.m`` 574-686 (v3.1.4) / 855-967 (v3.5), and the framing lines
    outside that span differ only in the corrupt-boundary gate (V-PT, below).
    They carry the same values as :data:`arrayprobe.constants.IMGPROC_CONFIG`,
    which ``tests/test_v35_imgproc_probetypes.py`` asserts field by field
    rather than trusting this comment.
    """

    __slots__ = ("boundary", "boundarytime", "ds", "diodenum", "probetype",
                 "read_width", "read_slices", "start_first", "boundary_needs_time",
                 "image_slice_offset", "image_invert", "image_word_bits", "timing")

    def __init__(self, boundary: Any, boundarytime: Any, ds: Any, diodenum: Any, probetype: Any, *,
                 read_width: Any = 8, read_slices: Any = 1700, start_first: Any = 1,
                 boundary_needs_time: Any = True, image_slice_offset: Any = 0,
                 image_invert: Any = False, image_word_bits: Any = 16,
                 timing: Any = "spec") -> None:
        self.boundary = tuple(boundary)
        self.boundarytime = boundarytime
        self.ds = ds
        self.diodenum = diodenum
        self.probetype = probetype
        self.read_width = read_width
        self.read_slices = read_slices
        self.start_first = start_first
        self.boundary_needs_time = boundary_needs_time
        self.image_slice_offset = image_slice_offset
        self.image_invert = image_invert
        self.image_word_bits = image_word_bits
        self.timing = timing


_SPEC_BOUNDARY = (43690,) * 8
_DMT_BOUNDARY = (170,) * 8

_PMS_FRAMING = dict(read_width=4, read_slices=1024, start_first=2,          # :721
                    boundary_needs_time=True, image_slice_offset=1,          # :754, :765
                    image_invert=False, image_word_bits=8, timing="pms")     # :785-787
_DMT_FRAMING = dict(read_width=8, read_slices=1700, start_first=2,           # :726
                    boundary_needs_time=False, image_slice_offset=0,         # :754
                    image_invert=False, image_word_bits=8, timing="dmt")     # :788-791
_F2DC_FRAMING = dict(_DMT_FRAMING, read_slices=512, timing="fast2dc")        # :723
_SPEC_FRAMING = dict(read_width=8, read_slices=1700, start_first=1,          # :725, :759
                     boundary_needs_time=True, image_slice_offset=0,
                     image_invert=True, image_word_bits=16, timing="spec")   # :792-795

#: ``:134-235``, every case, verbatim.  ``2DC``'s v3.5 change (``ds`` 0.025 ->
#: 0.03, ``:141``) is recorded here where a reader of the v3.1.4 table would
#: look for it.
PROBES_V35: dict[str, ProbeV35] = {
    "2DC": ProbeV35((255, 255, 255, 255), 85, 0.03, 32, 0, **_PMS_FRAMING),
    "2DP": ProbeV35((255, 255, 255, 255), 85, 0.200, 32, 0, **_PMS_FRAMING),
    "CIP": ProbeV35(_DMT_BOUNDARY, float("nan"), 0.025, 64, 1, **_DMT_FRAMING),
    "PIP": ProbeV35(_DMT_BOUNDARY, float("nan"), 0.100, 64, 1, **_DMT_FRAMING),
    "HVPS": ProbeV35(_SPEC_BOUNDARY, 0, 0.150, 128, 2, **_SPEC_FRAMING),
    "2DS": ProbeV35(_SPEC_BOUNDARY, 0, 0.010, 128, 2, **_SPEC_FRAMING),
    "3VCPI_H": ProbeV35(_SPEC_BOUNDARY, 0, 0.050, 128, 2, **_SPEC_FRAMING),
    "3VCPI_V": ProbeV35(_SPEC_BOUNDARY, 0, 0.010, 128, 2, **_SPEC_FRAMING),
    "Fast2DC": ProbeV35((170, 170, 170), float("nan"), 0.025, 64, 3, **_F2DC_FRAMING),
}

#: ``:725`` -- the probetype-2 read is a literal ``[8,1700,1]``.
_READ_WIDTH_PT2 = 8
_READ_SLICES_PT2 = 1700

#: Which timing branches this port has transcribed for v3.5.  Every entry here
#: is asserted against its own Octave golden; :class:`UnportedProbeType` still
#: fires for anything outside it, naming what is missing.
PORTED_TIMINGS_V35 = ("spec", "pms", "dmt", "fast2dc")


def particle_num_v35(kk: int) -> int:
    """``:858`` -- ``mod(kk,66536)``.  Preserved.

    Source: ``imgProc_sm.m:858`` (UIOOPS v3.5)."""
    return kk % PARTICLE_NUM_MODULUS_V35


# --------------------------------------------------------------------------
# The output variable table (:318-660), in the file's own definition order
# --------------------------------------------------------------------------

def _v(name: Any, xtype: Any, units: Any, description: Any, dims: Any = ("time",)) -> Any:
    return VariableSpec(name=name, xtype=xtype, dims=tuple(dims),
                        units=units, description=description)


_HOLROYD_HABIT_DESCRIPTION = {
    # :587-590
    1: ('ASCII habit code following the Holroyd (1987) algorithm '
        '("M" or 77: zero image; "C" or 67: center-out image; "t" or 116: tiny; '
        '"o" or 111: bad/split; "l" or 108: linear; "a" or 97: aggregate; '
        '"g" or 103: graupel; "s" or 115: sphere; '
        '"h" or 104: hexagonal; "i" or 105: irregular; "d" or 100: dendrite)'),
    # :592-595
    0: ('ASCII habit code following the Holroyd (1987) algorithm '
        '("M" or 77: zero image; "C" or 67: center-out image; "t" or 116: tiny; '
        '"o" or 111: oriented; "l" or 108: linear; "a" or 97: aggregate; '
        '"g" or 103: graupel; "s" or 115: sphere; '
        '"h" or 104: hexagonal; "i" or 105: irregular; "d" or 100: dendrite)'),
}


def imgproc_variables_v35(*, iRectEllipse: int, iCalcAllDiodeStats: int, iQC: int,  # noqa: N803
                          iNewHabit: int, extended_ellipse_outputs: bool | None,  # noqa: N803
                          probetype: int) -> tuple[VariableSpec, ...]:
    """The ``netcdf.defVar`` sequence of ``:318-660`` for one configuration.

    Source: the ``netcdf.defVar`` block of ``imgProc_sm.m`` (UIOOPS v3.5), from ``:317``; bare line
    references here are into that file.

    ``extended_ellipse_outputs`` stands in for the ``persistent
    hasExtendedOutputs`` probe (``:255-272``): a recorded flag, not a runtime
    probe of whichever ``CGAL_EllipseSize`` binary is on the path (upstream finding:
    the binary-dependent output schema).
    ``probetype`` is accepted for symmetry with the MATLAB but has no effect on
    the table -- ``Particle_number_all``'s gate ``:356`` is
    ``probetype~=0 || probetype~=3``, which is true for every probetype.
    """
    del probetype  # :356's `||` makes the gate unconditional; see the docstring
    out: list[VariableSpec] = [
        _v("Date", "int", "YYYYMMDD", "Date of image record in which the particle resides"),
        _v("Time", "int", "HHMMSS", "Time (UTC) of image record in which the particle resides"),
        _v("msec", "short", "ms", "Sub-second time of image record in which the particle resides"),
        _v("Time_in_seconds", "double", "sec", "Time since probe was activated"),
        _v("SliceCount", "short", "--", "Number of slices containing particle"),
        _v("DMT_DOF_SPEC_OVERLOAD", "double", "ms (Fast2DC/2DC/2DP only)",
           "Unitless flag denoting out-of-focus (DMT) or overloaded (SPEC) particles. "
           "Dead time for corresponding image record for PMS probes."),
        _v("Particle_number_all", "int", "--", "Index of particle in 2-D buffer"),
        _v("position", "short", "--",
           "Slice within image record where particle is first sampled", ("pos_count", "time")),
        _v("particle_time", "int", "HHMMSS", "Particle time (not available for 2DS/HVPS/3VCPI)"),
        # :369 -- the unclosed parenthesis is the file's.
        _v("particle_millisec", "short", "ms",
           "Sub-second particle time (not available for 2DS/HVPS/3VCPI"),
        _v("particle_microsec", "double", "microsec",
           "Sub-second particle time (unitless clock count for 2DS/HVPS/3VCPI)"),
        _v("parent_rec_num", "int", "--", "Index of image record in which the particle resides"),
        _v("particle_num", "short", "--", "Particle index within current image record"),
    ]
    if iQC == 1:                                                    # :401-411
        out += [
            _v("subparticle_num", "short", "--", "Number of subparticles in image"),
            _v("subparticle_mindist", "short", "--",
               "Minimum distance between subparticles in image"),
        ]
    out += [
        _v("image_length", "short", "--",
           "Particle length in time direction using # photodiodes"),
        _v("image_width", "short", "--",
           "Particle length in photodiode direction using # photodiodes"),
        _v("image_area", "double", "mm^2", "Projected area using the # shadowed photodiodes"),
        _v("image_longest_y", "short", "--",
           "Longest vertically-oriented chord through particle in time direction"),
        _v("image_max_top_edge_touching", "short", "--",
           "Maximum # of times the bottom diode is shadowed in succession"),
        _v("image_max_bottom_edge_touching", "short", "--",
           "Maximum # of times the top diode is shadowed in succession"),
        _v("image_touching_edge", "byte", "--",
           "0 denotes image entirely in array; 1 denotes image touching edge"),
        _v("image_auto_reject", "short", "--",
           'ASCII reject code ("0" or 48: accepted; "a" or 97: aspect ratio > 6; '
           '"t" or 116: aspect ratio > 5 + image touching edge; '
           '"p" or 112: < 25% shadowed diodes in rectangle encompassing particle; '
           '"h" or 104 or 72 or 117: hollow particle; "s" or 115: split image; '
           '"z" or 122: zero area image; "f" or 102: zero area image)'),
        _v("image_hollow", "byte", "--", "0 denotes not hollow; 1 denotes a hollow image"),
        _v("image_center_in", "byte", "--",
           "0 denotes center of particle outside array; 1 denotes center is inside"),
        _v("image_axis_ratio", "double", "--",
           "Ratio between maximum vertical length and maximum horizontal length"),
        # :455-479 -- the five chord/circle-fit diameters are commented out in v3.5.
        _v("image_diam_minR", "double", "mm", "Dmax of smallest circle enclosing the particle"),
        _v("image_diam_AreaR", "double", "mm", "Area equivalent diameter"),
        _v("image_xpos", "double", "--",
           "Particle center x (time) position of minimum enclosing circle"),
        _v("image_ypos", "double", "--",
           "Particle center y (diode) position of minimum enclosing circle"),
        _v("image_perimeter", "double", "mm", "Perimeter following the particle boundary"),
    ]
    if iRectEllipse == 1:                                           # :506-557
        out += [
            _v("image_RectangleL", "double", "mm",
               "Length of smallest rectangle enclosing the particle"),
            _v("image_RectangleW", "double", "mm",
               "Width of smallest rectangle enclosing the particle"),
            _v("image_RectangleAngle", "double", "radians",
               "Angle of rectangle with respect to the time direction"),
            _v("image_EllipseL", "double", "mm",
               "Length of smallest ellipse enclosing the particle"),
            _v("image_EllipseW", "double", "mm",
               "Width of smallest ellipse enclosing the particle"),
            # :543 -- 'rectangle', in the ellipse variable's own description.
            _v("image_EllipseAngle", "double", "radians",
               "Angle of rectangle with respect to the time direction"),
        ]
        if extended_ellipse_outputs:                                # :547-557
            out += [
                _v("image_EllipseX", "double", "--",
                   "Center position of ellipse with respect to the time direction"),
                _v("image_EllipseY", "double", "--",
                   "Center position of ellipse with respect to the photodiode direction"),
            ]
    out += [
        _v("percent_shadow_area", "double", "percent",
           "Ratio between the projected area and L*W"),
        _v("edge_at_max_hole", "short", "--",
           "# diodes between edges of the particle for the slice "
           "containing the largest gap inside the particle"),
        _v("max_hole_diameter", "short", "--",
           "Diameter of the largest hole inside the particle"),
        _v("part_z", "double", "--",
           "Particle depth in object plane calculated via lookup table"),
        _v("size_factor", "double", "--",
           "Dmax reduction factor folowing Korolev (2007) correction"),
        _v("holroyd_habit", "short", "--", _HOLROYD_HABIT_DESCRIPTION[1 if iNewHabit == 1 else 0]),
        _v("fine_detail_ratio", "double", "--", "Perim*Diam/Area following Holroyd (1987)"),
        _v("sphericity", "double", "--", "sqrt(area)/perim following McFarquhar et al. (2005)"),
    ]
    if iNewHabit == 1:                                              # :610-645
        out += [
            _v("width_length_percentile", "double", "mm",
               "Minimum difference between the 25th and 75th percentiles of particle "
               "length and width"),
            _v("circle_area_ratio", "double", "--",
               "Ratio between particle area and that of the approximated smallest circle "
               "enclosing the particle"),
            _v("edge_maximum_dimension_ratio", "double", "--",
               "Ratio between number of diodes illuminated along the frame edge with the "
               "most illuminated diodes and the particle maximum dimension"),
            _v("maximum_gap", "double", "mm",
               "Maximum gap between any two separate illuminated areas along the x or y axes"),
            _v("opacity_coefficient", "double", "--",
               "Fraction (0-1) approximating the transparency of a particle"),
            _v("aspect_ratio", "double", "--",
               "Ratio between length of longest axis and length of shortest axis of particle"),
            _v("holroyd_perimeter", "double", "mm",
               "Particle perimeter following Holroyd (1987) including perimeter added by "
               "holes within particle"),
        ]
    out += [
        _v("area_hole_ratio", "double", "--",
           "Ratio between the projected area and the area of hole inside particle"),
        _v("inter_arrival", "double", "sec",
           "Inter-arrival time between particles "
           "(use diff(time_in_seconds) for all but 2DC/2DP)"),
        _v("bin_stats", "int", "--",
           "# times specified photodiode is shadowed for particles in this file", ("bin_count",)),
    ]
    if iCalcAllDiodeStats:                                          # :652-657
        out.append(_v("image_bin_stats", "int", "--",
                      "# times specified photodiode is shadowed for each particle",
                      ("bin_count", "time")))
    return tuple(out)


# --------------------------------------------------------------------------
# The driver
# --------------------------------------------------------------------------


@contextlib.contextmanager
def _patched_measure_perimeter(kernels: Any) -> Any:
    """Route :func:`arrayprobe_uiops.measure.measure_record`'s per-particle
    ``particle_perimeter`` call through the numba kernel, for the duration of
    one ``imgproc_sm_v35(jit=True)`` call.

    ``measure.py`` is out of this change's file scope, so
    this is the only way to reach the call without editing its source:
    ``measure.py`` does ``from arrayprobe.particle_perimeter import
    particle_perimeter``, which binds the name in **measure's own** module
    namespace at import time -- patching ``arrayprobe.particle_perimeter``
    itself afterward would not reach that already-bound name. So the target
    is ``arrayprobe_uiops.measure.particle_perimeter``, restored unconditionally
    on the way out (including on an exception), and reentrant only in the
    sense that a ``None`` ``kernels`` is a no-op -- ``imgproc_sm_v35`` does
    not call itself recursively, so nested patching is not a real case.

    Fails loudly rather than silently skipping the speedup if the target is
    ever gone: a JIT flag that quietly does nothing is exactly the original
    bug (``--jit`` on v3.5 accepted and ignored), and this module exists to
    not repeat it.
    """
    if kernels is None:
        yield
        return
    from arrayprobe_uiops import measure as _measure_mod

    if not hasattr(_measure_mod, "particle_perimeter"):
        raise AttributeError(
            "arrayprobe_uiops.measure no longer imports particle_perimeter by that "
            "name -- imgproc_sm_v35(jit=True)'s monkeypatch target is gone, so the "
            "speedup would silently stop applying. Update _patched_measure_perimeter "
            "in imgproc.py to match."
        )
    original = _measure_mod.particle_perimeter
    _measure_mod.particle_perimeter = kernels.particle_perimeter
    try:
        yield
    finally:
        _measure_mod.particle_perimeter = original


def imgproc_sm_v35(
    infile: Any,
    outfile: Any,
    probename: str,
    n: int,
    nEvery: int,  # noqa: N803 -- MATLAB's name
    projectname: str,
    *,
    iRectEllipse: int = 0,  # noqa: N803
    iCalcAllDiodeStats: int = 0,  # noqa: N803
    iQC: int = 0,  # noqa: N803
    iNewHabit: int,  # noqa: N803
    reject_config: RejectConfig,
    tas_time: Any,
    tas: Any,
    tas_ratio: Any = None,
    software: str,
    creation_time: str | None = None,
    extended_ellipse_outputs: bool | None = None,
    progress: Any = None,
    jit: bool = False,
    prime: tuple[float, float] | None = None,
    stamp_profile: str | None = None,
    tas_qc: dict[str, Any] | None = None,
    shadow_diode: Sequence[int] | np.ndarray | diode_mask.ShadowDiodeMask | None = None,
    stray_pixel_fix: bool = False,
    ncar_2dc_timing_fix: bool = False,
) -> int:
    """``imgProc_sm(infile, outfile, probename, n, nEvery, projectname, iRectEllipse,
    iCalcAllDiodeStats, iQC, iNewHabit, tasTime, tas[, tasRatio])`` (v3.5).

    Required, no default -- each is a fidelity decision no default may make:
    ``iNewHabit``; ``tas_time`` / ``tas`` (``varargin{1..2}``, arrays, the
    aircraft series ``:186-188``); ``software`` (replaces ``:283-285``'s bare
    relative ``fopen('version.txt')`` -- the vendored file reads
    ``UIOOPS_v3.5``, upstream's own spelling); and ``reject_config``.

    ``reject_config`` is required rather than fixed to ``STOCK_V35_REJECT_CONFIG``.
    ``calculate_reject_unified.m`` assigns its thresholds
    unconditionally at the top of the function, and the archived production tree
    ships a **modified copy of that file**, so the configuration is a fidelity
    decision in exactly the sense ``profiles.py``'s header means. A fixed value
    would also put one of the v3.5 port's three whole-program Octave goldens --
    ``oraclesprod_v35.nc``, run against the production reject tree -- out of reach entirely.

    ``tas_ratio`` is ``varargin{3}``: indexed by the **absolute** record ``i``
    (``:709``), so a chunked run must pass the whole-file series (upstream finding: the
    absolute-record tasRatio index).  ``None`` is the ``iTAS == 0`` path,
    ``handles.tasRatio = 1.0`` (``:711``).

    ``extended_ellipse_outputs`` must be given (``True``/``False``) iff
    ``iRectEllipse == 1``, and must be ``None`` otherwise.

    ``jit``
        Speed only, **default off** (space: the port). ``True`` routes
        the two v3.5 call sites whose MATLAB is unchanged from v3.1.4 --
        ``dec2bin_concat`` (this module's own framing/timing unpacks) and
        ``particle_perimeter`` (inside :func:`arrayprobe_uiops.measure.
        measure_record`) -- through :mod:`arrayprobe_uiops.jit_kernels`, which
        reuses the earlier translation's already-proven compiled kernels rather than
        re-translating them. Exact by construction, so the file written is
        the same bytes (``tests/test_v35_imgproc_jit_identity.py`` runs both
        and compares). v3.5's OWN hot kernel, ``cgal_min_r_v35``, is not
        included -- see :mod:`arrayprobe_uiops.jit_kernels`'s module docstring
        for the measured numbers and why. Needs numba, imported only here.

    ``prime``
        The ``(part_time_prev, time_in_seconds_prev)`` pair a serial run holds
        at the top of this chunk's first record, from :func:`prefix_scan_v35`.
        **Default ``None``, which is a whole-file run and changes nothing.**
        ``"spec"`` timing only: it is the state that crosses a
        probetype-2 chunk seam, and handing it over is what makes a chunked
        pass reproduce the serial one *bit for bit* rather than approximately
        -- a left-fold resumed from its own exact partial value is the same
        fold, where a post-hoc offset re-rounds every element. The other three
        timings either carry nothing across a seam or have their one crossing
        quantity repaired exactly by :func:`merge_chunks_v35`, so passing
        ``prime`` there is refused rather than silently ignored.

    ``shadow_diode``
        Stuck diodes to re-illuminate: 1-based diode numbers, or a
        :class:`arrayprobe_uiops.diode_mask.ShadowDiodeMask` (from
        ``arrayprobe tune diodes``). **Default ``None``, and an empty list,
        change nothing** (``tests/test_v35_shadow_diode.py``). Stock v3.5 has
        no masking; this is the production fork's ``c(:,shadow_diode)='1'``
        (nine-argument ``imgProc_sm``, extraction ``:286-292``), applied by
        :func:`arrayprobe_uiops.diode_mask.reilluminate` right after the image
        is decoded into characters and before the ``iQC`` clean-up
        (``:801-846``), so ``qc_image`` sees the re-illuminated image. A diode
        number past the probe's width widens the image, as MATLAB does, and
        the ``:850-853`` width check then ends the run.

    Returns the number of particles written.
    """
    try:
        probe = PROBES_V35[probename]
    except KeyError:
        raise ValueError(f"unknown probename {probename!r}; v3.5 knows "
                         f"{sorted(PROBES_V35)}") from None
    if probe.timing not in PORTED_TIMINGS_V35:
        raise UnportedProbeType(  # pragma: no cover -- every shipped probe is ported
            f"{probename!r} is probetype {probe.probetype} ({probe.timing!r} timing): "
            f"this port transcribes {sorted(PORTED_TIMINGS_V35)} only. A new probetype "
            "needs its own particle-time branch (imgProc_sm.m:861-1116) and its own "
            "Octave golden before it can run here."
        )
    # :167-234 -- tasTime/tas are ``varargin{1,2}`` and are read ONLY in the
    # probetype-2 ``case`` arms.  Requiring them for a 2DC run would invent an
    # input the MATLAB never reads; accepting them silently would hide that.
    if probe.probetype == 2:
        if tas_time is None or tas is None:
            raise ValueError(
                f"{probename!r} is probetype 2: imgProc_sm.m:167-170/:180-185 read "
                "tasTime=varargin{1} and tas=varargin{2}, so both are required."
            )
    elif tas_time is not None or tas is not None:
        raise ValueError(
            f"{probename!r} is probetype {probe.probetype}: imgProc_sm.m's probe switch "
            "assigns tasTime/tas only in the probetype-2 cases (:167-170, :180-185, "
            ":196-199, :211-214), so this run would read neither. Pass tas_time=None, "
            "tas=None."
        )
    # ``tas_ratio`` (``varargin{3}``) is deliberately NOT gated on probetype:
    # ``:229-234``'s ``length(varargin)==3`` is probe-independent and ``:709``
    # sets ``handles.tasRatio`` for every probetype, even though the header
    # documents it as 2DS/HVPS-only and ``:1347`` is its one consumer.
    if prime is not None:
        if probe.timing != "spec":
            raise ValueError(
                f"prime= is {probe.timing!r} timing's to refuse: only probetype 2 "
                "accumulates across a chunk seam (imgProc_sm.m:1131-1180). "
                f"{probename!r} is probetype {probe.probetype}; 'pms'/'fast2dc' carry "
                "nothing across, and 'dmt' carries inter_arrival alone, which "
                "merge_chunks_v35 repairs exactly. Pass prime=None."
            )
        if len(prime) != 2 or any(p is None for p in prime):
            raise ValueError(
                "prime= must be the two floats (part_time_prev, time_in_seconds_prev); "
                "a chunk with no preceding particle -- the first chunk of a file -- "
                "takes prime=None, which is what prefix_scan_v35 returns for it."
            )
        if n == 1:
            raise ValueError(
                "prime= with n=1: the first chunk has no preceding particle, so a "
                "serial run holds part_time_prev unset there (imgProc_sm.m:1136). "
                "Priming it would start the accumulation from a state the reference "
                "run never had. Pass prime=None for n=1."
            )
        if iQC == 1:
            raise ValueError(
                "prime= with iQC=1 is refused: qc_image (:801-846) can change an "
                "image's width, so the :850-853 width-mismatch return can fire "
                "mid-file, and prefix_scan_v35 cannot know where a serial run would "
                "have stopped without doing the QC pass it exists to skip. Run "
                "iQC=1 serially."
            )
    if iRectEllipse == 1 and extended_ellipse_outputs is None:
        raise ValueError(
            "iRectEllipse=1 needs extended_ellipse_outputs=True/False: imgProc_sm.m:255-272 "
            "decides the output schema by probing whichever CGAL_EllipseSize is on the "
            "path (persistent hasExtendedOutputs) and records the outcome nowhere; here "
            "it is a recorded flag."
        )
    if iRectEllipse != 1 and extended_ellipse_outputs is not None:
        raise ValueError(
            "extended_ellipse_outputs is meaningful only with iRectEllipse=1 (:255, "
            ":547); passing it otherwise would describe a schema the file cannot have."
        )
    if tas is not None:
        tas = np.asarray(tas, dtype=float).ravel()
        tas_time = np.asarray(tas_time, dtype=float).ravel()
    ratios = None if tas_ratio is None else np.asarray(tas_ratio, dtype=float).ravel()

    kernels = None
    if jit:
        # Imported here, never at module level: numba costs seconds to import
        # and the default (jit=False) path must not pay for it.
        from . import jit_kernels as _v35_jit_kernels
        kernels = _v35_jit_kernels.load()

    diodenum = probe.diodenum
    boundary = np.asarray(probe.boundary)
    boundarytime = probe.boundarytime

    WIDTH_MISMATCH_RETURNS.clear()
    CORRUPT_RECORDS.clear()
    NCAR_2DC_SYNCS_CONVERTED.clear()

    src = ncio.open(infile, "nowrite")
    try:
        # :275-277 -- `size_mat = dimlen` is read and never used; the read stays.
        ncio.inq_dim(src, 2)
        _, img_count = ncio.inq_dim(src, 0)
        diode_stats = np.zeros(diodenum, dtype=np.float64)

        out = _create_output(outfile, diodenum, projectname, infile, probename,
                             iRectEllipse, iCalcAllDiodeStats, iQC, iNewHabit,
                             extended_ellipse_outputs, software, creation_time,
                             stamp_profile, tas_qc, stray_pixel_fix,
                             ncar_2dc_timing_fix=ncar_2dc_timing_fix)
        try:
            with _patched_measure_perimeter(kernels):
                return _process_records(
                    src, out, probe, n, nEvery, int(img_count), boundary, boundarytime,
                    diode_stats, tas, tas_time,
                    RunOptions(
                        ratios=ratios, projectname=projectname, probename=probename,
                        iCalcAllDiodeStats=iCalcAllDiodeStats, iQC=iQC,
                        iNewHabit=iNewHabit, iRectEllipse=iRectEllipse,
                        extended_ellipse_outputs=extended_ellipse_outputs,
                        reject_config=reject_config, kernels=kernels,
                        shadow_diode=shadow_diode, stray_pixel_fix=stray_pixel_fix,
                        ncar_2dc_timing_fix=ncar_2dc_timing_fix,
                    ),
                    progress, prime,
                )
        finally:
            ncio.close(out)
    finally:
        ncio.close(src)


def _create_output(outfile: Any, diodenum: Any, projectname: Any, infile: Any,
                   probename: Any, iRectEllipse: Any,  # noqa: N803
                   iCalcAllDiodeStats: Any, iQC: Any, iNewHabit: Any,  # noqa: N803
                   extended_ellipse_outputs: Any,
                   software: Any, creation_time: Any, stamp_profile: Any,
                   tas_qc: dict[str, Any] | None = None,
                   stray_pixel_fix: bool = False,
                   ncar_2dc_timing_fix: bool = False) -> Any:
    """``:289-660``, plus the in-file provenance attributes (not MATLAB output): the engine
    and profile always, and ``tas_qc``'s keys as ``arrayprobe_<key>`` when a caller passes the
    stage's airspeed record. No variable depends on either."""
    f = ncio.create(outfile, "clobber", format="NETCDF4")             # :289
    ncio.def_dim(f, "time", ncio.get_constant("NC_UNLIMITED"))        # :290
    ncio.def_dim(f, "pos_count", 2)                                    # :291
    ncio.def_dim(f, "bin_count", diodenum)                             # :292

    nc_global = ncio.get_constant("NC_GLOBAL")
    ncio.put_att(f, nc_global, "Software", software)                   # :295
    # :296 -- 'Institution' is commented out in v3.5.
    ncio.put_att(f, nc_global, "Creation Time",
                 creation_time if creation_time is not None
                 else datetime.now().strftime("%Y/%m/%d %H:%M:%S"))    # :297
    ncio.put_att(f, nc_global, "Description",
                 "Contains size, morphological, and other particle properties "
                 "from an uncompressed image file.")                    # :298
    ncio.put_att(f, nc_global, "Project", projectname)                 # :300
    ncio.put_att(f, nc_global, "Image Source", str(infile))            # :301
    ncio.put_att(f, nc_global, "Probe Type", probename)                # :302
    if iRectEllipse and iCalcAllDiodeStats:                            # :303-314
        active = "Rectangle & elliptical fits & per-particle diode statistics"
    elif iRectEllipse:
        active = "Rectangle & elliptical fits"
    elif iCalcAllDiodeStats:
        active = "Per-particle diode statistics"
    else:
        active = "None"
    ncio.put_att(f, nc_global, "Optional parameters active", active)
    # In-file provenance: arrayprobe_engine / arrayprobe_profile, not MATLAB output. The
    # Octave-golden comparisons exclude both, as they exclude 'Creation Time'.
    for name, value in provenance.engine_attrs(engine="3.5", profile=stamp_profile).items():
        ncio.put_att(f, nc_global, name, value)
    # Sorted, as the .tasqc.json sidecar is, so a re-run from the sidecar writes the same order.
    for key, value in sorted((tas_qc or {}).items()):
        ncio.put_att(f, nc_global, f"{provenance.ATTR_PREFIX}{key}", value)
    if stray_pixel_fix:
        # Only when on, so a correction-off file is byte-identical to one written before it.
        ncio.put_att(f, nc_global, "arrayprobe_stray_pixel", _stray_pixel.STAMP_ON)
    if ncar_2dc_timing_fix:
        # Only when on, as above: a correction-off file is byte-identical to upstream's.
        ncio.put_att(f, nc_global, "arrayprobe_ncar_2dc_timing", _ncar_2dc.STAMP_ON)

    dimid = {"time": 0, "pos_count": 1, "bin_count": 2}
    for spec in imgproc_variables_v35(
        iRectEllipse=iRectEllipse, iCalcAllDiodeStats=iCalcAllDiodeStats, iQC=iQC,
        iNewHabit=iNewHabit, extended_ellipse_outputs=extended_ellipse_outputs, probetype=2,
    ):
        # chunksizes: not MATLAB's (it sets none) -- WRITER_GAPS["chunking"].
        varid = ncio.def_var(f, spec.name, spec.xtype, [dimid[d] for d in spec.dims],
                             chunksizes=WRITER_CHUNKING.get(spec.name))
        ncio.put_att(f, varid, "Units", spec.units)
        ncio.put_att(f, varid, "Description", spec.description)
        # defVarDeflate(f, varid, true, true, 9) -- WRITER_GAPS["deflate"]
    if stray_pixel_fix:
        # Not MATLAB output; defined after every MATLAB variable, so their ids are unchanged.
        for name, xtype, units, desc in STRAY_PIXEL_VARIABLES:
            varid = ncio.def_var(f, name, xtype, [dimid["time"]])
            ncio.put_att(f, varid, "Units", units)
            ncio.put_att(f, varid, "Description", desc)
    ncio.end_def(f)                                                    # :660
    return f


class ChunkingNotEquivalent(ValueError):
    """Raised when a chunked v3.5 S3 pass could not reproduce the serial run.

    Not a capability gap to be worked around with a looser comparison: the
    named quantity is genuinely a running accumulation over the whole file,
    so the chunked result would be *different output*, not *the same output
    computed differently*.
    """


#: Which v3.5 timing branches a chunked S3 pass reproduces **bit for bit**.
#:
#: The discriminator is whether a particle's own written values depend on state
#: that survives ``:1402``'s ``clear`` and therefore crosses a chunk seam.
#: Measured per branch, not assumed (``tests/test_v35_imgproc_merge_chunks.py``):
#:
#: ``"dmt"`` (probetype 1, CIP/PIP)
#:     ``time_in_seconds`` is built from the record's own header bits alone
#:     (``:1100``), so it is record-local.  Only ``inter_arrival`` reaches
#:     across, as the single subtraction ``t - time_in_seconds_prev``
#:     (``:1110-1114``, new in v3.5), and :func:`merge_chunks_v35` repairs
#:     exactly that -- see its ``inter_arrival`` note.
#: ``"pms"`` (probetype 0, 2DC/2DP) and ``"fast2dc"`` (probetype 3)
#:     ``_particle_time_pms`` / ``_particle_time_fast2dc`` are called without
#:     ``time_in_seconds_prev`` and never read it; every written quantity is
#:     record-local, so concatenation alone is exact.
#:
#: ``"spec"`` (probetype 2, 2DS/HVPS/3VCPI) is **deliberately absent**.
#: ``:1131-1180`` accumulates: ``Time_in_seconds = time_in_seconds_prev +
#: (part_time - part_time_prev) * scale``, a running sum from the first
#: particle of the file (:func:`arrayprobe.imgproc._time_in_seconds_from_tas`).
#: A chunk that starts with ``part_time_prev is None`` restarts that sum at
#: ``part_time * scale`` (``:763-765``), so every particle after the first seam
#: carries a different absolute time -- **measured**: 53 of 99 particles on the
#: 25-record 2DS fixture, split three ways.  The offset cannot be repaired
#: bit-exactly afterwards, because re-adding it re-rounds every element
#: (floating-point addition is not associative), and it cannot be primed
#: without having already processed every earlier record.  Refused rather than
#: approximated.
CHUNKABLE_TIMINGS_V35 = ("dmt", "pms", "fast2dc")

#: Which timings are chunkable **only when each chunk is primed**.
#:
#: ``"spec"``'s accumulation is real -- the paragraph above is accurate about
#: what crosses the seam and about why a post-hoc offset cannot repair it.  What
#: it got wrong was one word: it said the seam state "cannot be primed without
#: having already **processed** every earlier record".  Every earlier record
#: must be **scanned**, which is a different and much cheaper thing: the two
#: scalars are functions of the record header and the particle's own header
#: words (``:1123``) alone, and :func:`prefix_scan_v35` reaches them without
#: unpacking a single image or calling ``measure_record``.
#:
#: Measured on the tracked 25-record 2DS fixture
#: (``tests/test_v35_sizedist_chunk_priming.py``): primed chunks concatenate to
#: the serial run with **all 40 variables** equal by ``np.array_equal``,
#: ``Time_in_seconds`` equal as *bytes*, and a one-ULP perturbation of the
#: primed accumulator detected -- so the comparison discriminates.  The unprimed
#: control disagrees in ``Time_in_seconds`` alone (53 of 99 particles, at most
#: 2 ULP; re-measured 2026-09-27 by ``paper/figures/fig14_chunk_priming.py``) and
#: on no measured variable.  This comment said ``{Time_in_seconds, int_arrival}``
#: until then: ``inter_arrival`` is record-local for ``"spec"`` timing and never
#: differs, and the test asserts only a subset of that pair.
PRIMABLE_TIMINGS_V35 = ("spec",)


def prefix_scan_v35(infile: Any, probename: str, stop_record: int, *,  # noqa: N803
                    tas_time: Any, tas: Any, iQC: int = 0,  # noqa: N803
                    progress: Any = None) -> tuple[float, float] | None:
    """The ``prime=`` pair a serial run holds at the top of ``stop_record``.

    Replays ``imgProc_sm.m:693-1180``'s **scan** over records
    ``1 .. stop_record-1`` and returns ``(part_time_prev, time_in_seconds_prev)``
    -- or ``None`` when no particle precedes that record, which is a chunk that
    needs no priming (the first chunk of a file always).  The return value is
    what :func:`imgproc_sm_v35`'s ``prime=`` takes, unchanged.

    **What it deliberately does not do.**  No ``dec2bin_concat``, no
    ``measure_record``, no reject pass, no habit -- that is where a run's time
    goes, and none of it is read by ``:1131-1180``.  The accumulation sees only
    the record header (``:1132``, the TAS lookup key), the boundary walk that
    locates each particle (``:751-779``), and ``part_time`` from the particle's
    own header words (``:1123``).  ``tests/test_v35_sizedist_chunk_priming.py``
    spies ``measure_record`` during a full-file scan and asserts it is called
    **zero** times: a scan that measured would prime correctly and save nothing.

    **The width check, carried arithmetically.**  ``:850-853`` exits the whole
    function when an unpacked image is not ``diodenum`` wide.  For ``iQC == 0``
    that width is ``read_width * image_word_bits``, a constant of the file, so
    the check cannot fire mid-file without firing on the very first particle --
    and it is decided here without unpacking anything.  ``iQC == 1`` is refused
    outright: ``qc_image`` can change a width mid-file, so a scan cannot know
    where a serial run would have stopped without doing the work it exists to
    skip.

    **``tas_time``/``tas`` are required and must be the run's own series.**  The
    fold is ``time_in_seconds_prev + (part_time - part_time_prev) * scale``
    under both arms of ``:1131-1170``, but ``scale`` is built from the TAS
    lookup, so a scan run against a different series -- or against the empty
    arrays that select ``TAS_FALLBACK`` (170) -- lands on a *different* pair and
    primes the chunk wrongly.  No default: this is the same fidelity decision
    :func:`imgproc_sm_v35` refuses to make for probetype 2, and a silently
    wrong prime is worse than a refusal because the output still looks like a
    serial run.

    ``progress`` is called as ``progress(i, stop_record - 1)`` per record.  Pass
    one for a long scan: a chunk worker that is silent for its whole prefix is
    indistinguishable from a hung one to ``--worker-stall-min``.
    """
    probe = _primable_probe(probename, iQC)
    if tas is None or tas_time is None:
        raise ValueError(
            "prefix_scan_v35 needs the run's own tas_time/tas: the accumulation's "
            "scale comes from the TAS lookup (:1131-1170), so scanning with empty "
            "arrays takes the TAS_FALLBACK arm and primes the chunk with a number "
            "no serial run ever held. Pass the same series the run will use."
        )
    tas = np.asarray(tas, dtype=float).ravel()
    tas_time = np.asarray(tas_time, dtype=float).ravel()

    return _scan_seam_states(infile, probe, [int(stop_record)], tas, tas_time,
                             progress)[0]


def chunk_primes_v35(infile: Any, probename: str, n_every: int, chunks: int, *,  # noqa: N803
                     tas_time: Any, tas: Any, iQC: int = 0,  # noqa: N803
                     progress: Any = None) -> list[tuple[float, float] | None]:
    """Every chunk's ``prime=`` pair, in **one** pass over the file.

    Returns a list of length ``chunks``: element ``k-1`` is what chunk ``k``
    (records ``(k-1)*n_every+1 ..``) must be given.  The first is always
    ``None`` -- no particle precedes record 1.

    **Why the driver calls this and not :func:`prefix_scan_v35` per chunk.**
    Each worker scanning its own prefix reads ``chunks/2`` files' worth in
    total and makes the last worker scan almost the whole file before it starts
    processing.  One pass in the parent costs a single read, and the seam states
    are then just N points along the same walk.  The arithmetic is identical
    either way -- this is a scheduling choice, not a fidelity one, and
    ``tests/test_v35_sizedist_chunk_priming.py`` asserts the two agree.
    """
    chunks = int(chunks)
    if chunks < 1:
        raise ValueError(f"chunks must be >= 1, got {chunks}")
    probe = _primable_probe(probename, iQC)
    stops = [(k - 1) * int(n_every) + 1 for k in range(1, chunks + 1)]
    if tas is None or tas_time is None:
        raise ValueError(
            "chunk_primes_v35 needs the run's own tas_time/tas -- see prefix_scan_v35.")
    # Each stop is a chunk's first record, so one past the file's last record is a
    # chunk with no records (the scan itself accepts n_file + 1, the end state).
    src = ncio.open(infile, "nowrite")
    try:
        _, n_file = ncio.inq_dim(src, 0)
    finally:
        ncio.close(src)
    # Chunk 1 is always allowed: a run of an empty file holds one chunk and no seam,
    # and a refusal advising fewer chunks could not be followed.
    if chunks > 1 and stops[-1] > n_file:
        raise ValueError(
            f"chunk {chunks} would start at record {stops[-1]}, past the file's {n_file} "
            "records: that chunk would be empty. Use no more chunks than ceil(records / "
            "n_every) (arrayprobe.driver.run_flight._chunk_plan).")
    return _scan_seam_states(infile, probe, stops, np.asarray(tas, dtype=float).ravel(),
                             np.asarray(tas_time, dtype=float).ravel(), progress)


def _primable_probe(probename: str, iQC: int) -> Any:  # noqa: N803
    """Shared validation for the two scan entry points."""
    try:
        probe = PROBES_V35[probename]
    except KeyError:
        raise ValueError(f"unknown probename {probename!r}; v3.5 knows "
                         f"{sorted(PROBES_V35)}") from None
    if probe.timing not in PRIMABLE_TIMINGS_V35:
        raise ValueError(
            f"prefix scanning is for {sorted(PRIMABLE_TIMINGS_V35)} timing; {probename!r} "
            f"is probetype {probe.probetype} ({probe.timing!r}), which carries no "
            "whole-file accumulation and is already in CHUNKABLE_TIMINGS_V35."
        )
    if iQC == 1:
        raise ValueError(
            "prefix scanning refuses iQC=1: qc_image (:801-846) can change an image's "
            "width, so :850-853's return can fire mid-file and a scan cannot locate it "
            "without unpacking every image. Run iQC=1 serially."
        )
    if probe.read_width * probe.image_word_bits != probe.diodenum:
        raise ValueError(
            f"{probename!r}: an unpacked image is {probe.read_width * probe.image_word_bits} "
            f"wide against diodenum={probe.diodenum}, so imgProc_sm.m:850-853 returns at the "
            "first particle and a serial run writes nothing. Nothing to prime."
        )
    return probe


#: The seven per-record time fields :func:`arrayprobe_uiops.imgproc_core._read_record_header`
#: reads (``:206-212``), in its order.
_RECORD_HEADER_NAMES = ("year", "month", "day", "hour", "minute", "second", "millisec")


def _scan_seam_states(infile: Any, probe: Any, stop_records: Any, tas: Any, tas_time: Any,
                      progress: Any) -> Any:
    """One boundary walk; the seam state captured at each of ``stop_records``.

    ``stop_records`` must be ascending.  Returns one entry per stop, each the
    ``(part_time_prev, time_in_seconds_prev)`` pair held at the *top* of that
    record, or ``None`` when no particle precedes it.

    Byte-identical to :func:`_scan_seam_states_reference` and faster by three
    changes that alter no arithmetic and no visited state:

    * the seven record-header fields are read once for every record, where the
      reference makes seven one-element reads per record;
    * the boundary walk is one array comparison per record.  The reference's
      ``while`` loop (``:751``) advances ``j`` by one on every path and changes
      ``start`` only at a boundary row, so the boundary rows alone carry the state;
      they are found with ``flatnonzero`` and the ``start`` bookkeeping and the
      fold then run, unchanged and in the same order, over those rows only;
    * the TAS samples at the record's own second are selected once per record.
      ``_time_in_seconds_from_tas`` selects ``tas_time == temp_time`` itself, and
      ``temp_time`` is fixed for a record, so handing it the pre-selected samples
      gives it the same elements in the same order.
    """
    stops = [int(s) for s in stop_records]
    # strict=False, and deliberately: the two operands differ in length by one by
    # construction (adjacent-pair scan), so strict=True would raise on every call.
    if any(b < a for a, b in zip(stops, stops[1:], strict=False)):
        raise ValueError(f"stop_records must be ascending, got {stops}")
    out: list[tuple[float, float] | None] = []
    part_time_prev: float | None = None
    time_in_seconds_prev: float | None = None
    boundary = np.asarray(probe.boundary)
    boundary_words = boundary.size
    pending = list(stops)
    last_record = max(stops) if stops else 1

    def _capture(record: int) -> None:
        """Record the state held at the *top* of every stop at or below ``record``."""
        while pending and pending[0] <= record:
            pending.pop(0)
            # Both Optionals are set together (:1178, :1180) and start out None, so
            # the second test only makes that invariant visible to the type checker.
            out.append(None if part_time_prev is None or time_in_seconds_prev is None
                       else (part_time_prev, float(time_in_seconds_prev)))

    src = ncio.open(infile, "nowrite")
    try:
        data_varid = ncio.inq_var_id(src, "data")                       # :719
        header: dict[str, Any] = {}
        if last_record > 1:                                             # records 1 .. last-1
            for name in _RECORD_HEADER_NAMES:                           # :695-701, in bulk
                header[name] = np.ravel(
                    ncio.get_var(src, ncio.inq_var_id(src, name), 0, last_record - 1))
            # The file's own record count (dimension 0, as :277 reads it), not the
            # size of the read above. A stop at n_file + 1 is the state after the last
            # record, which a scan may ask for; a chunk *starting* there is empty, and
            # chunk_primes_v35, whose stops are chunk starts, refuses that itself.
            _, n_file = ncio.inq_dim(src, 0)
            if last_record > n_file + 1:
                raise ValueError(
                    f"seam stop at record {last_record} is past the end of the file's "
                    f"{n_file} records. Use no more chunks than ceil(records / n_every) "
                    "(arrayprobe.driver.run_flight._chunk_plan).")
        for i in range(1, last_record):                                 # :693
            _capture(i)
            if progress is not None:
                progress(i, last_record - 1)
            rec = {name: float(header[name][i - 1]) for name in _RECORD_HEADER_NAMES}
            data = ncio.read_image_record(src, data_varid, i - 1,
                                          probe.read_width, probe.read_slices)
            nrow = data.shape[0]
            # The walk visits every j from 1 until data[j-1, 0] == -1 or j == nrow (:751).
            neg = np.flatnonzero(data[:nrow - 1, 0] == -1)
            jstop = int(neg[0]) + 1 if neg.size else nrow               # walk is j in [1, jstop)
            if boundary_words > data.shape[1]:
                continue        # array_equal of unequal lengths is False at every j
            is_boundary = (data[:jstop - 1, :boundary_words] == boundary).all(axis=1)
            if probe.boundary_needs_time:                               # :754
                is_boundary &= data[1:jstop, 0] == probe.boundarytime
            start = 0                                                   # :730
            tas_rec: Any = None
            for j in (np.flatnonzero(is_boundary) + 1).tolist():        # 1-based, ascending
                if start == 0:                                          # :755-761
                    start = probe.start_first
                if (start + probe.image_slice_offset) > (j - 1):        # :764-777
                    start = j + 2
                    continue
                h = j                                                   # header_loc - 1, :779
                part_time = float(data[h, 6]) * 2 ** 16 + float(data[h, 7])   # :1123
                if tas_rec is None:
                    # :727's key, built as _time_in_seconds_from_tas builds it, once.
                    temp_time = (float(rec["hour"]) * 10000 + float(rec["minute"]) * 100
                                 + float(rec["second"]))
                    at_second = tas_time == temp_time
                    tas_rec = (tas[at_second], tas_time[at_second])
                t = _time_in_seconds_from_tas(
                    part_time, probe.ds, rec, tas_rec[0], tas_rec[1],
                    part_time_prev, time_in_seconds_prev)               # :1131-1170
                part_time_prev = part_time                              # :1178
                time_in_seconds_prev = t                                # :1180
                start = j + 2                                           # :1311
        _capture(last_record)
    finally:
        ncio.close(src)

    assert not pending, f"seam states not captured for records {pending}"
    return out


def _scan_seam_states_reference(infile: Any, probe: Any, stop_records: Any, tas: Any,
                                tas_time: Any, progress: Any) -> Any:
    """The literal slice-by-slice walk, kept as the oracle for :func:`_scan_seam_states`.

    Not called in production; ``tests/test_v35_prefix_scan_fast.py`` compares the
    production scan against it bit for bit.  Its logic is untouched from the version
    that shipped before the vectorised walk.
    """
    stops = [int(s) for s in stop_records]
    # strict=False, and deliberately: the two operands differ in length by one by
    # construction (adjacent-pair scan), so strict=True would raise on every call.
    if any(b < a for a, b in zip(stops, stops[1:], strict=False)):
        raise ValueError(f"stop_records must be ascending, got {stops}")
    out: list[tuple[float, float] | None] = []
    part_time_prev: float | None = None
    time_in_seconds_prev: float | None = None
    boundary = np.asarray(probe.boundary)
    boundary_words = boundary.size
    pending = list(stops)
    last_record = max(stops) if stops else 1

    def _capture(record: int) -> None:
        """Record the state held at the *top* of every stop at or below ``record``."""
        while pending and pending[0] <= record:
            pending.pop(0)
            # part_time_prev and time_in_seconds_prev are always set together
            # (:965-966 below) and start out both None (:921-922), so this is
            # a single invariant, not two independent Optionals -- the extra
            # `or time_in_seconds_prev is None` only makes that visible to the
            # type checker; it never changes which branch executes.
            out.append(None if part_time_prev is None or time_in_seconds_prev is None
                       else (part_time_prev, float(time_in_seconds_prev)))

    src = ncio.open(infile, "nowrite")
    try:
        data_varid = ncio.inq_var_id(src, "data")                       # :719
        for i in range(1, last_record):                                 # :693
            _capture(i)
            if progress is not None:
                progress(i, last_record - 1)
            rec = _read_record_header(src, i)                           # :695-701
            data = ncio.read_image_record(src, data_varid, i - 1,
                                          probe.read_width, probe.read_slices)
            j = 1                                                       # :729
            start = 0                                                   # :730
            while data[j - 1, 0] != -1 and j < data.shape[0]:           # :751
                is_boundary = np.array_equal(data[j - 1, :boundary_words], boundary)
                if probe.boundary_needs_time:                           # :754
                    is_boundary = bool(is_boundary) and data[j, 0] == probe.boundarytime
                if not is_boundary:
                    j += 1
                    continue
                if start == 0:                                          # :755-761
                    start = probe.start_first
                if (start + probe.image_slice_offset) > (j - 1):        # :764-777
                    start = j + 2
                    j += 1
                    continue
                h = j                                                   # header_loc - 1, :779
                part_time = float(data[h, 6]) * 2 ** 16 + float(data[h, 7])   # :1123
                t = _time_in_seconds_from_tas(
                    part_time, probe.ds, rec, tas, tas_time,
                    part_time_prev, time_in_seconds_prev)               # :1131-1170
                part_time_prev = part_time                              # :1178
                time_in_seconds_prev = t                                # :1180
                start = j + 2                                           # :1311
                j += 1                                                  # :1316
        _capture(last_record)
    finally:
        ncio.close(src)

    assert not pending, f"seam states not captured for records {pending}"
    return out


def merge_chunks_v35(chunk_paths: Any, outfile: Any, *, projectname: Any, infile: Any,
                     probename: Any,  # noqa: N803
                     iNewHabit: Any, software: Any, iRectEllipse: Any = 0,  # noqa: N803
                     iCalcAllDiodeStats: Any = 0,  # noqa: N803
                     iQC: Any = 0, extended_ellipse_outputs: Any = None,  # noqa: N803
                     creation_time: Any = None,
                     stopped_at: Any = None, primed: Any = False, stamp_profile: Any = None,
                     tas_qc: dict[str, Any] | None = None,
                     stray_pixel_fix: bool = False) -> int:
    """Stitch N chunk-local v3.5 proc files into one whole-file result.

    ``stray_pixel_fix`` must state what every chunk worker ran with: when True the two
    :data:`STRAY_PIXEL_VARIABLES` and the ``arrayprobe_stray_pixel`` attribute are carried into
    the merge exactly as a serial ``stray_pixel_fix=True`` run writes them (the correction is
    per particle image, and no particle spans a record, so a record-range seam cannot split
    one). A chunk whose stray-pixel variables disagree with it is refused, never dropped.

    The v3.5 counterpart of the earlier translation's ``merge_chunks``, and the
    same mechanism: each chunk file is an ordinary :func:`imgproc_sm_v35` call
    over a disjoint, **ordered** record range (the ``n``/``nEvery`` API a
    whole-file run already uses with ``n=1``).  Chunks must be passed in the
    record order the split was made in -- nothing on disk records which range a
    chunk covers, so this cannot detect a reordering.

    **The cross-record state audit, per quantity** (the reason this is a
    fidelity function and not a plumbing one):

    * ``kk`` is **record-local** -- ``:1312`` increments it per particle and
      ``:1402`` resets it to 1 for every record that wrote, so it is 1 at the
      top of every record and a seam cannot renumber anything.  ``particle_num
      = mod(kk, 66536)`` (``:858``, the preserved 65536 typo) therefore counts
      *within a record*, not across the file, and needs no merging.
    * ``parent_rec_num`` (``:857``) is the **absolute** record ``i``, because
      the loop is written over absolute record numbers in both cases.
    * ``tasRatio`` (``:709``) is indexed by that same absolute ``i``, so every
      chunk worker must be handed the **whole-file** series -- which
      :func:`imgproc_sm_v35` enforces itself, raising ``IndexError`` rather
      than silently reading the wrong element.
    * ``w``/``wstart`` are chunk-local write indices; concatenation in chunk
      order is what merges them.
    * ``diode_stats``/``bin_stats`` accumulate per file and merge by summation.
    * ``inter_arrival`` is the **one** quantity a seam genuinely breaks, and
      only on ``"dmt"`` timing -- see below.
    * ``part_time_prev``/``time_in_seconds_prev`` on ``"spec"`` timing are what
      ``primed=True`` asserts were handed to every chunk after the first, as
      :func:`imgproc_sm_v35`'s ``prime=``.  Without that assertion the merge
      still refuses ``"spec"`` -- see :data:`CHUNKABLE_TIMINGS_V35` and
      :data:`PRIMABLE_TIMINGS_V35`.

    ``primed`` is the caller's statement that it did the priming, and this
    function **cannot verify it**: nothing on disk records whether a chunk was
    primed, exactly as nothing records which record range it covers.  Passing
    ``primed=True`` over unprimed chunks produces a silently wrong file. The
    driver that splits the work is the one place that knows, so it is the one
    place that may pass it -- ``scripts/run_flight.py`` does, next to the
    ``prefix_scan_v35`` call whose result it fed in.

    **The ``inter_arrival`` seam repair (probetype 1 only), and why it is
    exact.**  ``:1110-1114`` writes ``t - time_in_seconds_prev`` for every
    particle, where ``time_in_seconds_prev`` is the immediately preceding
    particle's ``t`` -- carried across record boundaries, new in v3.5.  At the
    top of a chunk that variable is ``None``, so the chunk's first particle
    gets ``0.0`` where the serial run would have written a real difference.
    Both operands are on disk as ``Time_in_seconds`` (``:305``, ``double``),
    and ``t`` itself is record-local, so recomputing the difference here uses
    **the identical pair of float64 values and the identical IEEE
    subtraction** the serial run performed.  It is the same number, not a
    close one -- asserted with ``np.array_equal`` on the bytes, not
    ``allclose``.

    ``stopped_at`` is the 1-based index of the first chunk whose worker hit the
    ``:850-853`` width-mismatch ``return``.  MATLAB exits the *whole function*
    there, leaving every later record unprocessed, so the serial-equivalent
    merge keeps chunks ``1..stopped_at`` (that chunk's own file already ends
    where MATLAB would have stopped) and **discards the rest** -- which a
    chunked run computed only because its later workers never saw the
    mismatch.  ``None`` means no chunk returned early.

    Returns the merged particle count.
    """
    if not chunk_paths:
        raise ValueError("merge_chunks_v35: no chunk files given")

    try:
        probe = PROBES_V35[probename]
    except KeyError:
        raise ValueError(f"unknown probename {probename!r}; v3.5 knows "
                         f"{sorted(PROBES_V35)}") from None
    if probe.timing not in CHUNKABLE_TIMINGS_V35:
        if not (primed and probe.timing in PRIMABLE_TIMINGS_V35):
            raise ChunkingNotEquivalent(
                f"{probename!r} is probetype {probe.probetype} ({probe.timing!r} timing): an "
                "UNPRIMED chunked v3.5 S3 pass cannot reproduce the serial run. "
                "imgProc_sm.m:1131-1180 accumulates Time_in_seconds across the WHOLE file "
                "(time_in_seconds_prev + (part_time - part_time_prev) * scale), so a chunk "
                "restarts that sum at :763-765 and every particle after a seam differs. "
                f"Chunkable without priming: {sorted(CHUNKABLE_TIMINGS_V35)}. "
                f"Chunkable WITH priming: {sorted(PRIMABLE_TIMINGS_V35)} -- give each chunk "
                "after the first the prefix_scan_v35 pair as imgproc_sm_v35(prime=...), "
                "then merge with primed=True. Otherwise run this probe serially."
            )
    elif primed:
        raise ValueError(
            f"primed=True with {probename!r} ({probe.timing!r} timing): that timing is "
            "chunkable without priming and imgproc_sm_v35 refuses prime= for it, so "
            "primed=True here asserts something no chunk worker could have done."
        )

    chunk_paths = list(chunk_paths)
    if stopped_at is not None:
        if not 1 <= stopped_at <= len(chunk_paths):
            raise ValueError(
                f"stopped_at={stopped_at} is not a 1-based index into {len(chunk_paths)} chunks")
        chunk_paths = chunk_paths[:stopped_at]

    specs = imgproc_variables_v35(
        iRectEllipse=iRectEllipse, iCalcAllDiodeStats=iCalcAllDiodeStats, iQC=iQC,
        iNewHabit=iNewHabit, extended_ellipse_outputs=extended_ellipse_outputs,
        probetype=probe.probetype,
    )
    # "time" is not always dims[0] -- `position` (:311, ("pos_count","time")) and
    # `image_bin_stats` (:649, ("bin_count","time")) are MATLAB-order, reversed
    # from every other time-indexed variable.
    time_specs = [s for s in specs if "time" in s.dims]
    other_specs = [s for s in specs if "time" not in s.dims]

    stray_names = [name for name, *_ in STRAY_PIXEL_VARIABLES]
    readers = [ncio.open(p, "nowrite") for p in chunk_paths]
    try:
        for path, ds in zip(chunk_paths, readers, strict=True):
            has = [name in ds._ds.variables for name in stray_names]
            if any(has) != bool(stray_pixel_fix) or len(set(has)) != 1:
                raise ValueError(
                    f"merge_chunks_v35: chunk {path} has stray-pixel variables {has} but the "
                    f"merge was called with stray_pixel_fix={bool(stray_pixel_fix)}; every chunk "
                    "must be computed with the run's stray-pixel setting")
        chunk_arrays = [
            {spec.name: ncio.get_var(ds, ncio.inq_var_id(ds, spec.name)) for spec in specs}
            for ds in readers
        ]
        if stray_pixel_fix:
            for arrays, ds in zip(chunk_arrays, readers, strict=True):
                for name in stray_names:
                    arrays[name] = ncio.get_var(ds, ncio.inq_var_id(ds, name))
    finally:
        for ds in readers:
            ncio.close(ds)

    diodenum = probe.diodenum
    counts = [int(arrays[time_specs[0].name].shape[
        time_specs[0].dims.index("time")]) for arrays in chunk_arrays]

    if probe.timing == "dmt":
        _repair_inter_arrival_seams(chunk_arrays, counts)

    out = _create_output(outfile, diodenum, projectname, infile, probename,
                         iRectEllipse, iCalcAllDiodeStats, iQC, iNewHabit,
                         extended_ellipse_outputs, software, creation_time,
                         stamp_profile, tas_qc, stray_pixel_fix=bool(stray_pixel_fix))
    try:
        var = {spec.name: ncio.inq_var_id(out, spec.name) for spec in specs}
        if stray_pixel_fix:
            var.update({name: ncio.inq_var_id(out, name) for name in stray_names})
        wstart = 0
        for arrays, count in zip(chunk_arrays, counts, strict=True):
            if count == 0:
                continue
            for spec in time_specs:
                data = arrays[spec.name]
                if spec.dims[0] != "time":
                    # get_var hands back MATLAB shape (<other>, time);
                    # write_record_block wants on-disk/C order (time, <other>).
                    # Keyed on the dims, not the name, so a new MATLAB-order
                    # variable could not be added without being handled.
                    ncio.write_record_block(out, var[spec.name], wstart, data.T)
                else:
                    ncio.put_var(out, var[spec.name], wstart, count, data)
            if stray_pixel_fix:
                for name in stray_names:
                    ncio.put_var(out, var[name], wstart, count, arrays[name])
            wstart += count

        for spec in other_specs:
            # `bin_stats` is rewritten whole every record (:1394, no start/count)
            # inside the particle-write block, which a record that found no
            # particle never reaches. A chunk with zero particles therefore
            # leaves it at the netCDF fill value, not 0, and summing that in
            # would corrupt the merge. A chunk with count > 0 ends with the
            # write from its last particle-bearing record, whose value is
            # already that chunk's complete total (diode_stats accumulates over
            # every particle in the chunk, not just that record), so skipping
            # the zero-count chunks is exact, not approximate.
            merged = np.zeros(diodenum)
            for arrays, count in zip(chunk_arrays, counts, strict=True):
                if count == 0:
                    continue
                merged = merged + np.asarray(arrays[spec.name]).reshape(-1)
            ncio.put_var(out, var[spec.name], merged)
    finally:
        ncio.close(out)

    return wstart


def _repair_inter_arrival_seams(chunk_arrays: Any, counts: Any) -> None:
    """``:1110-1114`` across a chunk seam -- see :func:`merge_chunks_v35`.

    Rewrites element 0 of every non-empty chunk's ``inter_arrival`` except the
    first, in place, to the difference the serial run computed.  Empty chunks
    are stepped over rather than treated as a seam: they wrote nothing, so the
    serial run's ``time_in_seconds_prev`` at the next particle is still the
    last particle of the previous *non-empty* chunk.
    """
    prev_last_t = None
    for arrays, count in zip(chunk_arrays, counts, strict=True):
        if count == 0:
            continue
        # get_var hands a 1-D netCDF variable back as a MATLAB column vector,
        # shape (time, 1) -- flatten to index it, and put the original shape
        # back so the writer below still sees what it expects.
        t = np.asarray(arrays["Time_in_seconds"]).reshape(-1)
        if prev_last_t is not None:
            ia = np.array(arrays["inter_arrival"])   # explicit copy, never a view
            shape = ia.shape
            flat = ia.reshape(-1)
            # The identical float64 subtraction :1114 performs, on the identical
            # pair of operands -- not a reconstruction of it.
            flat[0] = t[0] - prev_last_t
            arrays["inter_arrival"] = flat.reshape(shape)
        prev_last_t = t[-1]


class _Record:
    """The per-record accumulators MATLAB ``clear``\\ s at ``:1402``."""

    def __init__(self) -> None:
        self.images: list[np.ndarray] = []
        self.position: list[tuple[int, int]] = []
        self.parent_rec_num: list[int] = []
        self.particle_num: list[int] = []
        self.rec_time: list[float] = []
        self.rec_date: list[float] = []
        self.rec_millisec: list[float] = []
        self.num_subparticles: list[int] = []
        self.dist_min: list[int] = []
        # The ten accumulators MATLAB indexes by ``kk`` and that a later
        # particle -- or, for the GCPEx-CIP wraparound ``:1081-1093``, a WHOLE-
        # VECTOR assignment -- reads back.  A plain list cannot express either,
        # so these are 1-based :class:`MGrowVector`\\ s, the same type the
        # v3.1.4 port uses and the same type its reused timing helpers write to.
        self.particle_DOF = MGrowVector()
        self.particle_partNum = MGrowVector()
        self.particle_sliceCount = MGrowVector()
        self.part_hour = MGrowVector()
        self.part_min = MGrowVector()
        self.part_sec = MGrowVector()
        self.part_mil = MGrowVector()
        self.part_micro = MGrowVector()
        self.time_in_seconds = MGrowVector()
        self.int_arrival = MGrowVector()


#: The two per-particle variables a ``stray_pixel_fix=True`` run adds
#: (absent when off).
STRAY_PIXEL_VARIABLES = (
    ("image_stray_pixels_removed", "short", "count",
     "Stray pixels zeroed before sizing (arrayprobe correction, 0 when untouched)"),
    ("image_diam_minR_uncorrected", "double", "mm",
     "image_diam_minR before the stray-pixel correction (NaN when untouched)"),
)


@dataclass(frozen=True)
class RunOptions:
    """The run-invariant flags :func:`_process_records` reads (2026-09-25 code review).

    Plumbing only: each field is the object the caller passed, held by reference (``ratios`` is
    not copied), and ``_process_records`` rebinds every field to the local of the same name
    before its first statement, so its body reads exactly what it read when these were ten
    positional parameters.
    """
    ratios: Any
    projectname: str
    probename: str
    iCalcAllDiodeStats: int  # noqa: N815
    iQC: int  # noqa: N815
    iNewHabit: int  # noqa: N815
    iRectEllipse: int  # noqa: N815
    extended_ellipse_outputs: Any
    reject_config: Any
    kernels: Any = None
    shadow_diode: Any = None
    stray_pixel_fix: bool = False
    ncar_2dc_timing_fix: bool = False


def _process_records(src: Any, out: Any, probe: Any, n: Any, nEvery: Any,  # noqa: N803
                     img_count: Any, boundary: Any, boundarytime: Any,
                     diode_stats: Any, tas: Any, tas_time: Any, opts: RunOptions, progress: Any,
                     prime: Any = None) -> int:
    """``:663-1405`` -- the record loop and the particle loop, all four probetypes.

    The ten run-invariant flags arrive bundled in ``opts`` (:class:`RunOptions`) and are
    unpacked to locals of their former names first thing below.

    ``kernels`` is ``None`` (the reference ``dec2bin_concat``) or an
    :class:`arrayprobe_uiops.jit_kernels.V35JitKernels`, whose ``dec2bin_concat``
    is a drop-in returning identical values.

    ``prime`` is ``None`` or the ``(part_time_prev, time_in_seconds_prev)`` pair
    a serial run holds at the top of record ``(n-1)*nEvery+1`` -- see
    :func:`prefix_scan_v35`.  It seeds the two locals below instead of
    ``None``/``None``, which is the whole of prefix-priming: ``:1136``'s
    ``exist('part_time_prev','var')`` is then true at the chunk's first
    particle, exactly as it is mid-file in a serial run.
    """
    ratios = opts.ratios
    projectname = opts.projectname
    probename = opts.probename
    iCalcAllDiodeStats = opts.iCalcAllDiodeStats  # noqa: N806
    iQC = opts.iQC  # noqa: N806
    iNewHabit = opts.iNewHabit  # noqa: N806
    iRectEllipse = opts.iRectEllipse  # noqa: N806
    extended_ellipse_outputs = opts.extended_ellipse_outputs
    reject_config = opts.reject_config
    kernels = opts.kernels
    shadow_diode = opts.shadow_diode
    ds = probe.ds
    diodenum = probe.diodenum
    probetype = probe.probetype
    to_chars = dec2bin_concat if kernels is None else kernels.dec2bin_concat
    var = {spec.name: k for k, spec in enumerate(imgproc_variables_v35(
        iRectEllipse=iRectEllipse, iCalcAllDiodeStats=iCalcAllDiodeStats, iQC=iQC,
        iNewHabit=iNewHabit, extended_ellipse_outputs=extended_ellipse_outputs,
        probetype=probetype,
    ))}
    stray_fix = bool(opts.stray_pixel_fix)
    # The NCAR 2DC timing-word correction applies to probetype 0 only (imgProc_sm.m:137-139).
    ncar_fix = bool(opts.ncar_2dc_timing_fix) and probetype == 0
    if stray_fix:
        for name, *_ in STRAY_PIXEL_VARIABLES:
            var[name] = len(var)
    data_varid = ncio.inq_var_id(src, "data")                          # :719

    kk = 1          # :663
    w = -1          # :664
    wstart = 0      # :665
    # Not in the :1402 clear list: persist across records within the chunk.
    # ``prime`` seeds them at a chunk boundary; ``None`` is a whole-file run and
    # is what ``n == 1`` always gets.
    part_time_prev: float | None = None if prime is None else float(prime[0])
    time_in_seconds_prev: float | None = None if prime is None else float(prime[1])
    total = 0

    # :685-688 / :736-749 -- v3.5 narrowed v3.1.4's project-only gate to
    # ``(PECAN or GCPEx) AND probetype==1``: a 2DS run under projectname
    # 'PECAN' scanned for corrupt DMT boundaries in v3.1.4 and does not here.
    corrupt_scan = projectname in ("PECAN", "GCPEx") and probetype == 1
    boundary_words = boundary.size                                      # :754

    last = min(n * nEvery, img_count)
    for i in range(int((n - 1) * nEvery + 1), int(last) + 1):          # :693
        if progress is not None:
            progress(i, int(last))
        rec = _read_record_header(src, i)                               # :695-701
        if ratios is not None:                                          # :707-712
            if i > ratios.size:
                raise IndexError(
                    f"imgProc_sm.m:709: tasRatio({i}) is out of range for a series of "
                    f"length {ratios.size}. varargin{{3}} is indexed by the ABSOLUTE record "
                    "number, so a chunked run must pass the whole-file series (V20)."
                )
            tas_ratio_i = float(ratios[i - 1])
        else:
            tas_ratio_i = 1.0
        data = ncio.read_image_record(src, data_varid, i - 1,
                                      probe.read_width, probe.read_slices)  # :720-727
        if ncar_fix:
            # Not UIOOPS: NCAR 2DC sync/timing words -> 0x55 before :754 frames (ncar_2dc_timing).
            data, n_conv = _ncar_2dc.convert_record(data)
            NCAR_2DC_SYNCS_CONVERTED[i] = n_conv

        j = 1           # :729
        start = 0       # :730
        num_crpt_bnds = 0                                               # :748
        if corrupt_scan:                                                # :736-747
            member_sum = np.isin(data, boundary).sum(axis=1)
            num_good_bnds = int(np.sum(member_sum == 8))
            num_crpt_bnds = int(np.sum((member_sum > 4) & (member_sum < 8)))
            if num_crpt_bnds > 0:
                CORRUPT_RECORDS.append((i, num_crpt_bnds, num_good_bnds))

        acc = _Record()
        # :751
        while data[j - 1, 0] != -1 and j < data.shape[0] and num_crpt_bnds < 1:
            # :754 -- probetypes 0/2 need BOTH the boundary row and the
            # boundarytime word at the head of the next row; probetypes 1 and 3
            # take the `|| probetype==1 || probetype==3` disjunct, which exists
            # precisely because their boundarytime is NaN and isequal(NaN,NaN)
            # is false.  Do not "fix" that into a NaN-tolerant compare.
            is_boundary = np.array_equal(data[j - 1, :boundary_words], boundary)
            if probe.boundary_needs_time:
                is_boundary = bool(is_boundary) and data[j, 0] == boundarytime
            if not is_boundary:
                j += 1
                continue
            if start == 0:                                              # :755-761
                start = probe.start_first
            # :764-777 -- probetype 0 tests `start+1 > j-1`, the others
            # `start > j-1`; the offset is the same one the image slice uses.
            if (start + probe.image_slice_offset) > (j - 1):
                start = j + 2
                j += 1
                continue
            header_loc = j + 1                                          # :779
            w += 1                                                      # :780

            # :785-795
            ind_matrix = data[start - 1 + probe.image_slice_offset:j - 1, :]
            if probe.image_invert:
                ind_matrix = 65535 - ind_matrix
            c = to_chars(ind_matrix, probe.image_word_bits)
            if shadow_diode is not None:                    # fork :286-292, before iQC
                c = diode_mask.reilluminate(c, shadow_diode)

            if iQC == 1:                                                 # :801-846
                c, n_sub, d_min = qc_image(c)
                acc.num_subparticles.append(n_sub)
                acc.dist_min.append(d_min)

            if c.shape[1] != diodenum:                                  # :850-853
                # MATLAB prints a width-mismatch message and returns -- the
                # whole function exits, the current record unwritten.
                WIDTH_MISMATCH_RETURNS.append((i, j))
                return total

            acc.images.append(c)
            acc.position.append((start, j - 1))                         # :856
            acc.parent_rec_num.append(i)                                # :857
            acc.particle_num.append(particle_num_v35(kk))               # :858

            if probe.timing == "spec":
                # :1117-1185 -- byte-identical to v3.1.4's probetype-2 block.
                h = header_loc - 1
                acc.particle_DOF[kk] = float(int(data[h, 3]) & 32768)   # :1119
                acc.particle_partNum[kk] = float(data[h, 4])            # :1120
                acc.particle_sliceCount[kk] = float(data[h, 5])         # :1121
                part_time = float(data[h, 6]) * 2 ** 16 + float(data[h, 7])  # :1123
                acc.part_micro[kk] = part_time                          # :1124
                # :1125-1128 -- the other four are literal zeros, which is why
                # :1336's particle_time is a column of zeros for probetype 2.
                acc.part_mil[kk] = 0.0
                acc.part_sec[kk] = 0.0
                acc.part_min[kk] = 0.0
                acc.part_hour[kk] = 0.0
                t = _time_in_seconds_from_tas(part_time, ds, rec, tas, tas_time,
                                              part_time_prev, time_in_seconds_prev)
                acc.time_in_seconds[kk] = t                             # :1131-1170
                # :1172-1176 -- kk>1 ? diff : 0.  Per record; NOT carried across
                # records (that change, :1110-1115, is probetype 1 only).
                acc.int_arrival[kk] = (t - acc.time_in_seconds[kk - 1]) if kk > 1 else 0.0
                part_time_prev = part_time                              # :1178
                time_in_seconds_prev = t                                # :1180
            elif probe.timing == "pms":
                # :861-868 + :901-934 -- byte-identical to v3.1.4's, so the
                # v3.1.4 translation is reused rather than re-transcribed.
                _particle_time_pms(acc, kk, data, header_loc, src, i, probe, ind_matrix)
            elif probe.timing == "fast2dc":
                # :869-878 + :901-934 -- likewise byte-identical.
                _particle_time_fast2dc(acc, kk, data, header_loc, src, i, ind_matrix)
            else:                                                       # :935-1115
                time_in_seconds_prev = _particle_time_dmt_v35(
                    acc, kk, data, start, rec, projectname, probename, time_in_seconds_prev,
                    to_chars)

            acc.rec_time.append(rec["hour"] * 10000 + rec["minute"] * 100 + rec["second"])  # :1193
            acc.rec_date.append(rec["year"] * 10000 + rec["month"] * 100 + rec["day"])      # :1194
            acc.rec_millisec.append(rec["millisec"])                    # :1195

            start = j + 2                                               # :1311
            kk += 1                                                     # :1312
            j += 1                                                      # :1316

        if kk > 1:                                                      # :1320
            count = w - wstart + 1
            geom = RecordGeometry(diodesize=ds, diodenum=diodenum, tas_ratio=tas_ratio_i,
                                  i_new_habit=iNewHabit, probename=probename,
                                  i_calc_all_diode_stats=iCalcAllDiodeStats)
            # `jit=jit`, NOT omitted: measure_record forwards it to
            # calculate_reject_unified, whose compiled scan pass measured 6.33x on a
            # real production pass. Leaving it off here is what made --jit reach the
            # framing kernels and silently skip the reject path -- the same defect
            # shape, recreated on 2026-09-18 and caught by asking whether the number
            # was reachable rather than whether the kernel existed.
            stray_removed: list[int] = []
            stray_uncorrected: list[float] = []
            if stray_fix:
                # Not MATLAB: the opt-in stray-pixel correction, before :1204 so the kept
                # piece is re-sized and re-tested by the unchanged code below.
                fixed = [_stray_pixel.correct_engine_image(c) for c in acc.images]
                for k, (c_new, removed) in enumerate(fixed):
                    stray_removed.append(removed)
                    if removed:
                        # What a correction-off run writes as image_diam_minR (:1356).
                        orig = measure_record([acc.images[k]], geom, reject_config,
                                              jit=kernels is not None)
                        stray_uncorrected.append(orig.particles[0].minR * ds)
                        acc.images[k] = c_new
                    else:
                        stray_uncorrected.append(np.nan)
            res = measure_record(acc.images, geom, reject_config,
                                 jit=kernels is not None)  # :1204-1291
            diode_stats += res.diode_stats_total                        # :1210
            rect_ellipse: list[RectEllipse] | None = (                  # :1293-1301
                [rect_ellipse_for_image(c, extended=bool(extended_ellipse_outputs))
                 for c in acc.images]
                if iRectEllipse == 1 else None
            )
            _write_block(out, var, acc, res.particles, wstart, count, ds, tas_ratio_i,
                         diode_stats, diodenum, iNewHabit, iCalcAllDiodeStats, iQC,
                         rect_ellipse, extended_ellipse_outputs, probe.timing, probetype)
            if stray_fix:
                ncio.put_var(out, var["image_stray_pixels_removed"], wstart, count,
                             np.asarray(stray_removed, dtype=np.int16)[:count])
                ncio.put_var(out, var["image_diam_minR_uncorrected"], wstart, count,
                             np.asarray(stray_uncorrected, dtype=np.float64)[:count])
            total += count
            wstart = w + 1                                              # :1401
            kk = 1                                                      # :1402
        # :1405 `clear images` -- acc goes out of scope either way.

    return total


#: ``:976-1074`` -- the GCPEx CIP clock-offset table, **new in v3.5** (Joe
#: Finlon, 02/13/19); v3.1.4 has no GCPEx branch at all.  Each entry is
#: ``(month, day) -> (threshold, (hour, minute, second)) ...``, read in order,
#: the first threshold the record's seconds-from-midnight falls under winning,
#: with ``None`` as the final catch-all.  Transcribed line by line from the
#: vendored file; every value cites its own line.
_GCPEX_CIP_TABLE: dict[tuple[int, int], tuple[tuple[float | None, tuple[int, int, int]], ...]] = {
    (1, 19): ((55660.09, (14, 40, 53)),       # :980-981
              (62372.095, (15, 27, 46)),      # :982-984
              (None, (17, 19, 33))),          # :985-986
    (1, 28): ((57830.0, (15, 46, 36)),        # :991-992
              (None, (16, 3, 50))),           # :993-994
    (1, 30): ((None, (22, 36, 48)),),         # :996-997
    (1, 31): ((4989.0, (-1, -23, -11)),       # :1001-1002
              (5977.0, (1, 23, 9)),           # :1003-1004
              (None, (1, 39, 37))),           # :1005-1006
    (2, 12): ((13679.0, (2, 59, 0)),          # :1011-1012
              (13733.0, (3, 47, 59)),         # :1013-1014
              (17575.0, (3, 48, 53)),         # :1015-1016
              (17693.0, (4, 52, 55)),         # :1017-1018
              (18138.0, (4, 54, 53)),         # :1019-1020
              (19843.0, (5, 2, 18)),          # :1021-1022
              (19903.0, (5, 30, 43)),         # :1023-1024
              (19942.0, (5, 31, 43)),         # :1025-1026
              (20850.0, (5, 32, 22)),         # :1027-1028
              (20994.0, (5, 47, 30)),         # :1029-1030
              (21028.0, (5, 49, 54)),         # :1031-1032
              (21642.0, (5, 50, 28)),         # :1033-1034
              (None, (6, 0, 42))),            # :1035-1036
    (2, 18): ((44534.0, (9, 38, 33)),         # :1041-1042
              (57000.0, (12, 22, 14)),        # :1043-1044
              (None, (15, 37, 35))),          # :1045-1046
    (2, 24): ((48513.0, (11, 32, 3)),         # :1051-1052
              (48868.0, (13, 28, 3)),         # :1053-1054
              (49743.0, (13, 34, 28)),        # :1055-1056
              (50088.0, (13, 49, 3)),         # :1057-1058
              (52887.0, (13, 54, 48)),        # :1059-1060
              (52958.0, (14, 41, 27)),        # :1061-1062
              (53045.0, (14, 42, 38)),        # :1063-1064
              (60000.0, (14, 44, 5)),         # :1065-1066
              (71047.0, (16, 38, 49)),        # :1067-1068
              (None, (19, 43, 38))),          # :1069-1070
}

#: ``:980-985`` -- the 01/19 chain is the ONE date whose thresholds are tested
#: against ``recTime_secFromMidnight + handles.millisec/1000``; every other
#: date tests the whole-second value alone.  Read from the source, not
#: generalised: applying the millisecond term to the other dates would move
#: particles across a boundary at the sub-second level.
_GCPEX_USES_MILLISEC = frozenset({(1, 19)})


def _matlab_int16(x: float) -> float:
    """MATLAB's conversion of a double result to ``int16``: round half away
    from zero, then saturate to ``[-32768, 32767]``. Returned as a float.
    The rounding is :func:`arrayprobe_uiops.habit._matlab_round`, not
    ``floor(abs(x) + 0.5)``, which rounds ``0.49999999999999994`` up."""
    if math.isnan(x):
        return 0.0  # int16(NaN) is 0
    r = float(_matlab_round(x))
    return float(min(max(r, -32768.0), 32767.0))


def gcpex_cip_offsets(rec: Any) -> tuple[int, int, int]:
    """``:976-1074`` -- ``(hour, minute, second)`` offset for one image record.

    Source: ``imgProc_sm.m:976-1074`` (UIOOPS v3.5).

    ``rec`` is :func:`arrayprobe_uiops.imgproc_core._read_record_header`'s dict, i.e. the
    record's own ``handles.month``/``day``/``hour``/``minute``/``second``/
    ``millisec`` -- never a particle-level time.  A date with no entry returns
    ``(0, 0, 0)`` (``:1072-1073``).
    """
    key = (int(rec["month"]), int(rec["day"]))
    chain = _GCPEX_CIP_TABLE.get(key)
    if chain is None:
        return (0, 0, 0)                                              # :1072-1073
    t = rec["hour"] * 3600 + rec["minute"] * 60 + rec["second"]       # :978-979
    if key in _GCPEX_USES_MILLISEC:
        # :980-985 -- `handles.millisec` comes from `netcdf.getVar` on a
        # `'short'` variable (read_binary_DMT.m:41), so it is int16:
        # `millisec/1000.` is int16 and `recTime + (...)` is int16 too, both
        # rounded half away from zero and saturated. The sum therefore never
        # exceeds 32767, every 01/19 record takes the first branch, and
        # :982-986 are dead (Octave golden tests/data/
        # v35_gcpex_time_octave_golden.json, "nc" rows). Pass 6.
        t = _matlab_int16(t + _matlab_int16(float(rec["millisec"]) / 1000.0))
    for threshold, offsets in chain:
        if threshold is None or t < threshold:
            return offsets
    raise AssertionError(  # pragma: no cover -- every chain ends with None
        f"imgProc_sm.m:976-1074: no GCPEx branch matched {key} at t={t}"
    )


def _normalise_part_time(acc: _Record) -> None:
    """``:1081-1093`` -- the carry/borrow fixup, **new in v3.5** and GCPEx-CIP only.

    Three things about it are load-bearing and easy to get wrong:

    * it is a **whole-vector** assignment, not an ``(kk)`` one, so every
      particle accumulated so far in the current record is re-normalised on
      every subsequent particle;
    * the masks are recomputed between the ``>= 60`` pair and the ``< 0`` pair
      (``part_sec`` has moved in between), but *not* within a pair;
    * the hour wrap (``:1089``, ``:1093``) reads the hour that ``:1087`` /
      ``:1091`` has just written.
    """
    ph = acc.part_hour.asarray()
    pm = acc.part_min.asarray()
    ps = acc.part_sec.asarray()
    n = ph.size
    if n == 0:  # pragma: no cover -- called only after part_hour(kk) is set
        return

    m = ps >= 60                                                       # :1081-1082
    pm[m] += 1
    ps[m] -= 60
    m = ps < 0                                                         # :1084-1085
    pm[m] -= 1
    ps[m] += 60
    m = pm >= 60                                                       # :1087-1088
    ph[m] += 1
    pm[m] -= 60
    ph[ph >= 24] -= 24                                                 # :1089
    m = pm < 0                                                         # :1091-1092
    ph[m] -= 1
    pm[m] += 60
    ph[ph < 0] += 24                                                   # :1093

    acc.part_hour[1:n] = ph
    acc.part_min[1:n] = pm
    acc.part_sec[1:n] = ps


def _particle_time_dmt_v35(acc: _Record, kk: Any, data: Any, start: Any, rec: Any,
                           projectname: Any, probename: Any,
                           time_in_seconds_prev: Any, to_chars: Any = dec2bin_concat) -> Any:
    """``:935-1115`` -- the probetype-1 (CIP/PIP) branch.

    ``to_chars`` is ``dec2bin_concat`` (the reference) or a JIT drop-in
    (see :func:`_process_records`).

    **This is the one probetype whose timing v3.5 genuinely changed**, in two
    ways, both dated 02/13/19 by Joe Finlon and both absent from v3.1.4:

    * the GCPEx CIP offset table :data:`_GCPEX_CIP_TABLE` and its
      :func:`_normalise_part_time` fixup (``:976-1093``);
    * ``images.int_arrival`` is now differenced against
      ``time_in_seconds_prev``, which is never cleared at ``:1402`` and so
      **carries across record boundaries** inside a chunk -- v3.1.4 reset it to
      0 for the first particle of every record (``:704-708``).  So the first
      particle of every record but the first now gets a real inter-arrival
      time instead of a zero.  Returns the new ``time_in_seconds_prev``.

    Everything else here (``:936-943``, ``:946-973``, ``:1096-1100``) is
    byte-identical to v3.1.4's ``:654-701``.  Reads from ``start-1`` (MATLAB
    1-based), not ``header_loc``.
    """
    s = start - 2  # data(start-1, ...) MATLAB 1-based -> Python row index.

    bin_convert = to_chars(data[s:s + 1, 1:6], 8)                      # :936-937
    acc.part_hour[kk] = bin2dec(bin_convert[:, 0:5])                   # :939
    acc.part_min[kk] = bin2dec(bin_convert[:, 5:11])                   # :940
    acc.part_sec[kk] = bin2dec(bin_convert[:, 11:17])                  # :941
    acc.part_mil[kk] = bin2dec(bin_convert[:, 17:27])                  # :942
    # :943.  Despite the name and the 'microsec' netCDF attribute, this is
    # SECONDS -- a 13-bit count times 125e-9 (A13).  Preserved, not rescaled.
    acc.part_micro[kk] = bin2dec(bin_convert[:, 27:40]) * 125e-9

    if projectname == "PECAN" and probename == "PIP":                  # :946-973
        # Byte-identical to v3.1.4 :665-693, so its translation is reused.
        # Only the hour offset is ever non-zero in the table.
        acc.part_hour[kk] = _pecan_pip_hour_offset(rec, acc.part_hour[kk])
    elif projectname == "GCPEx" and probename == "CIP":                # :976-1093
        d_h, d_m, d_s = gcpex_cip_offsets(rec)
        acc.part_hour[kk] = acc.part_hour[kk] + d_h                    # :1077
        acc.part_min[kk] = acc.part_min[kk] + d_m                      # :1078
        acc.part_sec[kk] = acc.part_sec[kk] + d_s                      # :1079
        _normalise_part_time(acc)                                      # :1081-1093

    acc.particle_sliceCount[kk] = float(int(data[s, 0]) & 127)         # :1096
    acc.particle_DOF[kk] = float(int(data[s, 0]) & 128)                # :1097
    # :1098 -- the same dec2bin(_,8)/bin2dec idiom, not a plain 256*hi+lo.
    acc.particle_partNum[kk] = bin2dec(to_chars(data[s:s + 1, 6:8], 8))

    t = float(acc.part_hour[kk] * 3600 + acc.part_min[kk] * 60 + acc.part_sec[kk]
              + acc.part_mil[kk] / 1000 + acc.part_micro[kk])          # :1100
    acc.time_in_seconds[kk] = t
    # :1110-1114 -- `exist('time_in_seconds_prev','var')` is false only for the
    # very first particle of the whole chunk.
    acc.int_arrival[kk] = 0.0 if time_in_seconds_prev is None else t - time_in_seconds_prev
    return t                                                           # :1115


def _percent_shadow(p: ParticleMeasurement) -> float:
    """``:1303-1309`` -- overwrites the reject function's value with the
    area-equivalent circle ratio, real pi."""
    if p.image_length > p.image_width:
        return p.image_area / (np.pi * p.image_length ** 2 / 4)
    if p.image_width != 0:
        return p.image_area / (np.pi * p.image_width ** 2 / 4)
    return 0.0


def _touching_edge_minus_zero(v: Any) -> int:
    """``:1351`` -- ``images.image_touching_edge - '0'``: a char ``'0'``/``'t'``,
    or the numeric initialiser 0 from the zero-slice path, which writes -48."""
    if isinstance(v, str):
        return ord(v) - ord("0")
    return int(v) - ord("0")


def _particle_time_write_v35(acc: _Record, timing: str) -> Any:
    """``:1336`` -- ``part_hour(:)*10000+part_min(:)*100+part_sec(:)``.

    The A15 int8 saturation is v3.1.4's finding and survives unchanged into
    v3.5, because the lines that cause it are byte-identical: ``:906-908``
    seeds ``part_hour``/``part_min``/``part_sec`` from ``handles.hour``/
    ``minute``/``second``, which ``netcdf.getVar`` returns as int8 for the
    PMS raw format (``read_binary_PMS.m``, itself byte-identical between the
    two releases -- **measured**), MATLAB array-growth inherits the class, and
    MATLAB integer arithmetic saturates.  So probetypes 0 and 3 write 127 for
    virtually every real record, exactly as they do under v3.1.4.  Probetype 1
    escapes because ``bin2dec`` returns double; probetype 2 because
    ``:1125-1128`` assigns literal zeros.
    """
    ph, pm, ps = acc.part_hour.asarray(), acc.part_min.asarray(), acc.part_sec.asarray()
    if timing not in ("pms", "fast2dc"):
        return ph * 10000 + pm * 100 + ps
    return madd(madd(mmul(mint8(ph), 10000), mmul(mint8(pm), 100)), mint8(ps))


def _write_block(out: Any, var: Any, acc: _Record, parts: list[ParticleMeasurement],
                 wstart: Any, count: Any,
                 ds: Any, tas_ratio_i: Any, diode_stats: Any, diodenum: Any,
                 iNewHabit: Any, iCalcAllDiodeStats: Any,  # noqa: N803
                 iQC: Any, rect_ellipse: list[RectEllipse] | None,  # noqa: N803
                 extended_ellipse_outputs: bool | None, timing: str, probetype: int) -> None:
    """``:1323-1398`` -- one record's particles, in **putVar order**."""
    def put(name: Any, values: Any) -> None:
        ncio.put_var(out, var[name], wstart, count, np.asarray(values)[:count])

    def col(attr: Any) -> Any:
        return [getattr(p, attr) for p in parts]

    put("Time", acc.rec_time)                                           # :1323
    put("Date", acc.rec_date)                                           # :1324
    put("Time_in_seconds", acc.time_in_seconds.asarray())               # :1326
    put("SliceCount", acc.particle_sliceCount.asarray())                # :1327
    put("DMT_DOF_SPEC_OVERLOAD", acc.particle_DOF.asarray())            # :1328
    if probetype not in (0, 3):                                         # :1329-1331
        put("Particle_number_all", acc.particle_partNum.asarray())
    put("msec", acc.rec_millisec)                                       # :1333
    ncio.write_record_block(out, var["position"], wstart,
                            np.asarray(acc.position, dtype=np.int64)[:count])  # :1335
    put("particle_time", _particle_time_write_v35(acc, timing))         # :1336
    put("particle_millisec", acc.part_mil.asarray())                    # :1337
    put("particle_microsec", acc.part_micro.asarray())                  # :1338
    put("parent_rec_num", acc.parent_rec_num)                           # :1339
    put("particle_num", acc.particle_num)                               # :1340
    if iQC == 1:                                                        # :1341-1344
        put("subparticle_num", acc.num_subparticles)
        put("subparticle_mindist", acc.dist_min)
    put("image_length", col("image_length"))                            # :1345
    put("image_width", col("image_width"))                              # :1346
    put("image_area", np.asarray(col("image_area")) * ds * ds / tas_ratio_i)  # :1347
    put("image_longest_y", col("longest_y_within_a_slice"))             # :1348
    put("image_max_top_edge_touching", col("max_top_edge_touching"))    # :1349
    put("image_max_bottom_edge_touching", col("max_bottom_edge_touching"))  # :1350
    put("image_touching_edge",  # :1351
        [_touching_edge_minus_zero(p.image_touching_edge) for p in parts])
    put("image_auto_reject", [ord(p.auto_reject) for p in parts])       # :1352
    put("image_hollow", col("is_hollow"))                               # :1353
    put("image_center_in", col("center_in"))                            # :1354
    put("image_axis_ratio", col("axis_ratio"))                          # :1355
    put("image_diam_minR", np.asarray(col("minR")) * ds)                # :1356
    put("image_diam_AreaR", np.asarray(col("AreaR")) * ds)              # :1357
    put("image_perimeter", np.asarray(col("Perimeter")) * ds)           # :1358
    put("image_xpos", col("ctx"))                                       # :1359 -- unscaled
    put("image_ypos", col("cty"))                                       # :1360 -- unscaled
    if rect_ellipse is not None:                                        # :1361-1374
        put("image_RectangleL", [ds * r.rect_l for r in rect_ellipse])
        put("image_RectangleW", [ds * r.rect_w for r in rect_ellipse])
        put("image_RectangleAngle", [r.rect_angle for r in rect_ellipse])
        if extended_ellipse_outputs:                                    # :1367-1370
            put("image_EllipseX", [r.ell_x for r in rect_ellipse])       # unscaled
            put("image_EllipseY", [r.ell_y for r in rect_ellipse])       # unscaled
        put("image_EllipseL", [ds * r.ell_l for r in rect_ellipse])
        put("image_EllipseW", [ds * r.ell_w for r in rect_ellipse])
        put("image_EllipseAngle", [r.ell_angle for r in rect_ellipse])
    put("percent_shadow_area", [_percent_shadow(p) for p in parts])     # :1375
    # :1376-1377 -- THE SWAP, unchanged from v3.1.4.  varid29 is
    # edge_at_max_hole and receives max_hole_diameter; varid30 is
    # max_hole_diameter and receives edge_at_max_hole.  Preserved.
    put("edge_at_max_hole", col("max_hole_diameter"))
    put("max_hole_diameter", col("edge_at_max_hole"))
    put("part_z", col("part_z"))                                        # :1378
    put("size_factor", col("sf"))                                       # :1379
    put("holroyd_habit", [ord(p.holroyd_habit) for p in parts])         # :1380
    put("fine_detail_ratio", col("FS"))                                 # :1381
    put("sphericity", col("sphericity"))                                # :1382
    if iNewHabit == 1:                                                  # :1383-1391
        nh: list[HolroydNewResult] = []
        for p in parts:
            # geom.i_new_habit == 1 (the caller of measure_record, above)
            # guarantees :func:`arrayprobe_uiops.measure._habit_call` always
            # returns a populated ``HolroydNewResult`` -- ``new_habit`` is
            # ``None`` only on the ``i_new_habit == 0`` path.
            assert p.new_habit is not None
            nh.append(p.new_habit)
        put("width_length_percentile", np.asarray([r.w_l_p for r in nh]) * ds)
        put("circle_area_ratio", [r.c_r for r in nh])
        put("edge_maximum_dimension_ratio", [r.e_d_r for r in nh])
        put("maximum_gap", np.asarray([r.m_g for r in nh]) * ds)
        put("opacity_coefficient", [r.O for r in nh])
        put("aspect_ratio", [r.a_r for r in nh])
        put("holroyd_perimeter", np.asarray([r.p for r in nh]) * ds)
    put("area_hole_ratio", col("area_hole_ratio"))                      # :1392
    put("inter_arrival", acc.int_arrival.asarray())                     # :1393
    ncio.put_var(out, var["bin_stats"], diode_stats)  # :1394 -- whole, every record
    if iCalcAllDiodeStats:                                              # :1396-1398
        block = np.asarray([p.diode_stats for p in parts], dtype=np.float64)[:count]
        ncio.write_record_block(out, var["image_bin_stats"], wstart,
                                block.reshape(count, diodenum))
