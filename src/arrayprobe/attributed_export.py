# SPDX-License-Identifier: BSD-3-Clause
"""The attributed second output -- a self-describing sibling of a faithful port product.

**Author instruction, 2026-09-17, verbatim:** *"you can create a second output with these
attributes - this will be the final output from our package once we are out of testing/validation -
and for new products like arm data where file byte comparisons are not needed at all."*

**The tension this resolves, and the half that must not move.** ``combine_sizedist.m:202-231``
defines ten variables and **zero global and zero variable attributes** -- measured, not assumed:
:func:`arrayprobe.combine._write` is a line-for-line port of that block and writes no
``putAtt`` call at all, so ``Bin Midpoints`` reaches a recipient with no stated unit even though
``sizeDist.m:1746`` states one for the variable it was copied from. That absence is part of the
output contract: byte-identity against the archived ORACLES products compares every dimension,
variable *and attribute* against a MATLAB file that has none, and fifteen validated flights plus the
whole layer-1 claim rest on that comparison. **Adding metadata to the faithful writer would break
the reproduction.** So this module never touches it. It opens the faithful file **read-only**,
copies every value verbatim into a new file beside it, and puts the metadata there.

**Why this is not bureaucracy.** This project's central criticism of ARM's own product is that a
recipient cannot re-derive it -- and *our*
combined file taken alone has the same property: it carries no engine, no profile, no threshold and
no reject configuration, because it carries nothing at all. The run's provenance lives in the
``.call`` sidecar beside it (``src/arrayprobe/driver/run_flight.py:1855-1861``, "beside it,
never inside it"), which a recipient does not necessarily receive. This module folds the whole
sidecar into the file, so the attributed output travels alone and still answers "how was this
made".

**Value-preserving, and that is the property the tests assert.** Every variable is written with its
source dtype, its source dimension list in the source's own on-disk order, and values compared equal
by ``np.array_equal(..., equal_nan=True)``. Nothing is rescaled, renamed, reordered or transposed --
in particular this module takes no view on MATLAB dimension order and hand-rolls no
transpose (the port never hand-rolls a netCDF axis transpose): a verbatim structural
copy needs neither.
A derived quantity (a CF-decodable time coordinate, say) would be a *computed* addition and is
deliberately not written; see ``docs/developer/ATTRIBUTED_EXPORT.md`` §4 for what that would cost.

**No new dependency.** ``netCDF4`` and ``numpy`` are already this package's two hard requirements
(``pyproject.toml:32-35``). The output is NETCDF4: the NETCDF3_CLASSIC constraint exists to
match MATLAB's bare ``'clobber'`` default and does not apply to a
file with no MATLAB counterpart.

**ACDD, not CF; CF is not asserted.** The run record is also written under the six
ACDD-1.3 discovery names (:data:`ACDD_KEYS`: ``Conventions``, ``history``, ``source``,
``processing_level``, ``product_version``, ``date_created``), each only where the faithful file
holds no attribute of that name, so a generic catalogue finds the engine and the stamp without
knowing the ``arrayprobe_`` prefix. ``Conventions`` claims ACDD-1.3 and this module's own
convention, never CF. CF is the obvious target and ``arrayprobe_enhancements.cf_export``
already does the CF work
for ``sd`` files -- but the port never imports ``enhancements_uiops/`` (enforced by
``tests/test_no_enhancement_coupling.py``), and a ``Conventions = "CF-1.x"`` token this module
cannot verify would be a claim, not a fact: ``Time Vector`` is a MATLAB datenum, which has no
udunits ``days since <epoch>`` spelling that is correct without changing the value. So the file
declares its own versioned local convention (:data:`EXPORT_CONVENTION`) and states every
unit's provenance per variable. Formalising on CF is the author's call --
``docs/developer/ATTRIBUTED_EXPORT.md`` §4.

**Nothing here is invented.** Every unit is the string ``sizeDist.m`` itself writes for the variable
the value was copied from, cited at ``file:line`` and re-asserted against
``arrayprobe.sizedist._VARS`` from the other side by ``tests/test_attributed_export.py``. A product
shape this module has no sourced unit table for is **refused by name**, never exported with a
guessed unit.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as _dt
import hashlib
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Literal, TypedDict

import numpy as np
from netCDF4 import Dataset

from . import ncio
from .tools.tas_sources import read_qc_sidecar

__all__ = [
    "EXPORT_CONVENTION",
    "AttributedExportError",
    "MissingStampError",
    "StampParseError",
    "UnknownProductError",
    "VariableAttributes",
    "ProductShape",
    "COMBINED_SIZEDIST",
    "SHAPES",
    "identify_shape",
    "parse_stamp",
    "parse_reject",
    "parse_tagged_value",
    "default_output_path",
    "global_attributes",
    "shared_attributes",
    "stamp_shared_attributes",
    "storage_options",
    "export",
    "main",
]

#: This module's own output convention, versioned so a reader can tell which vintage of attribute
#: names it holds. Deliberately **not** ``CF-1.x``: see the module docstring, and
#: ``docs/developer/ATTRIBUTED_EXPORT.md`` §4 for why CF is not asserted.
EXPORT_CONVENTION = "arrayprobe-attributed-1.0"

#: Every attribute this module adds carries this prefix, so a reader can separate what the export
#: asserted from anything the source file already held (today: nothing -- the faithful combined
#: writer defines no attributes at all). The two exceptions are ``units`` and ``long_name``, which
#: are the variable attributes a recipient's tooling actually reads, and which are quoted from
#: ``sizeDist.m`` rather than asserted here.
ATTR_PREFIX = "arrayprobe_"

#: The ``Conventions`` value written when the faithful file states none. ACDD-1.3 is claimed
#: because the six discovery attributes in :data:`ACDD_KEYS` are written under ACDD's own names;
#: CF is still not claimed, for the reason the module docstring gives (``Time Vector`` has no
#: correct udunits spelling without changing its value).
ACDD_CONVENTIONS = f"ACDD-1.3, {EXPORT_CONVENTION}"

#: The unprefixed ACDD/CF global attributes the export adds, each only where the faithful file
#: does not already carry one under the same name. A name the faithful file does carry is copied
#: from it verbatim instead, so an attribute the engine wrote is never overwritten.
ACDD_KEYS = ("Conventions", "history", "source", "processing_level", "product_version",
             "date_created")

#: ``src/arrayprobe/driver/run_flight.py:1855-1861``'s sidecar naming: ``<output>.call``.
CALL_SUFFIX = ".call"

#: What :func:`default_output_path` appends. See ``docs/developer/ATTRIBUTED_EXPORT.md``
#: §3 -- the current layout; it may change in a later release.
DEFAULT_SUFFIX = ".attributed.nc"

#: Analysis-ready encoding (the attributed output is also the cloud-optimised one). zlib
#: level 4 is the level ``arrayprobe_enhancements.arco_export`` chose by measurement (levels above
#: it cost time for little size); cited, not imported -- the port never imports
#: ``enhancements_uiops/``.
ANALYSIS_READY_COMPLEVEL: Literal[4] = 4

#: A dimension longer than this is chunked; a shorter one (a bin axis) is kept whole in each chunk.
ANALYSIS_READY_WHOLE_DIM = 256

#: Chunk length along a long dimension: one hour of the products' 1 Hz seconds, so a reader
#: pulling one leg of a flight decompresses about an hour of data rather than the whole variable.
ANALYSIS_READY_CHUNK = 3600

#: What the file says about its own encoding, under ``arrayprobe_encoding``.
ENCODING_ANALYSIS_READY = (
    "analysis-ready: netCDF4/HDF5, every numeric variable zlib-compressed at level "
    f"{ANALYSIS_READY_COMPLEVEL}, the byte-shuffle filter on integer variables only (measured to "
    "hurt float data, arrayprobe_enhancements.arco_export), chunked to at most "
    f"{ANALYSIS_READY_CHUNK} along any dimension longer than {ANALYSIS_READY_WHOLE_DIM} (one hour "
    "of 1 Hz seconds) and whole along shorter ones. Lossless: every value, dtype and dimension "
    "order is the faithful file's, so a chunk can be read over a network without the rest.")
ENCODING_PLAIN = "plain: netCDF4, contiguous and uncompressed (analysis_ready=False)"

#: What a Zarr store written by :func:`export_zarr` says about its own encoding.
ENCODING_ZARR = (
    "zarr: a Zarr store converted from the analysis-ready netCDF4 export, every numeric variable "
    f"chunked to at most {ANALYSIS_READY_CHUNK} along any dimension longer than "
    f"{ANALYSIS_READY_WHOLE_DIM} (one hour of 1 Hz seconds) and whole along shorter ones, with "
    "zarr's default lossless compressor; every value, dtype, dimension order and attribute is the "
    "netCDF4 export's, and no _FillValue is added.")

#: The install extra :func:`export_zarr` needs; named in its error when zarr or xarray is missing.
ZARR_EXTRA = "zarr"

#: What a Parquet directory written by :func:`export_parquet` says about its own encoding.
ENCODING_PARQUET = (
    "parquet: a directory of Parquet files converted from the netCDF4 export, one file per "
    "distinct dimension tuple in long form (one int64 index column per dimension, values "
    "flattened in C order) and scalars in scalars.parquet; every value, dtype and attribute is "
    "the netCDF4 export's, in a tabular layout rather than the same layout.")

#: The install extra :func:`export_parquet` needs; named in its error when pyarrow is missing.
PARQUET_EXTRA = "parquet"

#: ``matlab_compat.datenum(1970, 1, 1)``, measured 2026-09-17 in this environment, not looked up:
#: a ``Time Vector`` value ``v`` is ``(v - 719529.0) * 86400`` seconds since 1970-01-01T00:00:00Z.
#: Written into the file so a recipient can convert without knowing MATLAB's calendar, and asserted
#: against :func:`arrayprobe.matlab_compat.datenum` itself -- a different place -- by the tests.
DATENUM_UNIX_EPOCH_DAYS = 719529.0


class AttributedExportError(RuntimeError):
    """Base class for every refusal this module raises."""


class MissingStampError(AttributedExportError):
    """The faithful file carries no ``.call`` sidecar, so its configuration is unknown.

    Refused rather than exported with the provenance block left blank, for exactly the reason
    ``scripts/run_flight.py``'s :class:`UnverifiableProvenance` refuses an unstamped input: a file
    that *looks* attributed but states nothing about how it was made is worse than no file, because
    a reader cannot tell the difference. ``accept_unstamped=True`` overrides, and then the export
    says so in ``arrayprobe_call_stamp`` rather than staying silent about it.
    """


class StampParseError(AttributedExportError, ValueError):
    """A ``.call`` line that does not parse as ``key=value`` pairs."""


class UnknownProductError(AttributedExportError, ValueError):
    """A netCDF file whose variables match no :data:`SHAPES` entry.

    Refused rather than copied with guessed units. Adding a shape means sourcing each variable's
    unit from the MATLAB that writes it, at ``file:line`` -- see :data:`COMBINED_SIZEDIST`.
    """


@dataclasses.dataclass(frozen=True)
class VariableAttributes:
    """One variable's attributes, and where each came from.

    ``units`` is a udunits-legal spelling of what the value *is*. ``source_units`` is the string
    ``sizeDist.m`` itself writes for the variable this one was copied from, kept verbatim where it
    differs from ``units`` -- the string is the thing under suspicion (the same reason
    ``arrayprobe_enhancements.cf_export`` keeps ``arrayprobe_source_units``), and dropping it would
    hide the discrepancy rather than record it. ``basis`` says how the unit was established:
    *read* (quoted from a cited line) or *derived* (computed from cited lines, with the arithmetic
    shown).
    """

    units: str
    long_name: str
    basis: str
    source_units: str | None = None


@dataclasses.dataclass(frozen=True)
class ProductShape:
    """One recognised faithful-product shape and its sourced attribute table."""

    name: str
    writer: str
    """The MATLAB block that writes this product, ``file:line``."""
    variables: Mapping[str, VariableAttributes]
    time_convention: str = ""
    """How this shape's time variable is encoded, written as ``arrayprobe_time_convention``."""
    missing_value_convention: str = ""
    """How this shape marks a missing value, written as ``arrayprobe_missing_value_convention``."""

    def matches(self, names: Iterable[str]) -> bool:
        """Whether ``names`` is exactly this shape's variable set.

        Set equality, not a subset test: a file holding a variable this shape has no sourced unit
        for must be refused, not exported with that one variable silently unlabelled.
        """
        return set(names) == set(self.variables)


# Named by file and lineage, never by a repository path: these strings are written into every
# attributed file, and no user's install holds the source tree they were read in.
_UIOOPS_SD = "ORACLES-variant sizeDist.m"
_COMBINE = "ORACLES-variant combine_sizedist.m"

#: The ten variables ``combine_sizedist.m:202-231`` writes (``arrayprobe.combine._write``), each
#: with the unit of the ``sd`` variable it is built from.
#:
#: **Every row is sourced, none is guessed.** ``sizeDist.m``'s own
#: ``netcdf.putAtt(...,'units',...)`` lines were read directly in the ORACLES-variant ``sizeDist.m``
#: (the tree that processed the real ORACLES products), and
#: the variable-to-variable correspondence is ``arrayprobe.combine._READ_VARS`` /
#: ``MATLAB_VARID``, itself pinned against the MATLAB's hard-coded ``netcdf.getVar`` indices by
#: ``tests/test_combine.py``.
COMBINED_SIZEDIST: dict[str, VariableAttributes] = {
    "Time Vector": VariableAttributes(
        units="days",
        long_name="MATLAB datenum time vector",
        basis=(
            "derived. The sd `time` this is built from is HHMMSS (sizeDist.m:1732), but "
            "combine_sizedist.m:95-120 converts it to a MATLAB datenum in days "
            "(arrayprobe.combine:214-223: `datenum(year, month, day) + time_of_day`), so the "
            "source unit string does not describe this variable. Measured in this environment: "
            f"matlab_compat.datenum(1970,1,1) == {DATENUM_UNIX_EPOCH_DAYS!r}; see the global "
            "attribute arrayprobe_datenum_unix_epoch_days for the conversion."
        ),
        source_units="HHMMSS (sd `time`; NOT this variable -- see basis)",
    ),
    "Bin Minimum": VariableAttributes(
        units="mm", long_name="bin minimum size",
        basis=f"read. {_UIOOPS_SD}:1736 'millimeter', on sd `bin_min`, copied unchanged by "
              f"{_COMBINE}:62-65 (arrayprobe.combine:162).",
        source_units="millimeter"),
    "Bin Maximum": VariableAttributes(
        units="mm", long_name="bin maximum size",
        basis=f"read. {_UIOOPS_SD}:1741 'millimeter', on sd `bin_max`, copied unchanged by "
              f"{_COMBINE}:62-65 (arrayprobe.combine:163).",
        source_units="millimeter"),
    "Bin Midpoints": VariableAttributes(
        units="mm", long_name="bin midpoint size",
        basis=f"read. {_UIOOPS_SD}:1746 'millimeter', on sd `bin_mid`, copied unchanged by "
              f"{_COMBINE}:62-65 (arrayprobe.combine:164). This is the variable whose missing unit "
              f"in the faithful file is the reason this attributed export exists.",
        source_units="millimeter"),
    "Bin Width": VariableAttributes(
        units="mm", long_name="bin width",
        basis=f"read. {_UIOOPS_SD}:1751 'millimeter', on sd `bin_dD`, copied unchanged by "
              f"{_COMBINE}:62-65 (arrayprobe.combine:165).",
        source_units="millimeter"),
    "Mean Area Ratio": VariableAttributes(
        units="1", long_name="mean area ratio per size bin",
        basis=f"read. {_UIOOPS_SD}:1834 '1', on sd `mean_area_ratio` (varid21), concatenated "
              f"unchanged by {_COMBINE}:70-71 (arrayprobe.combine:178).",
        source_units="1"),
    "Counts": VariableAttributes(
        units="1", long_name="accepted particle count per size bin",
        basis=f"read. {_UIOOPS_SD}:1829 '1', on sd `count` (varid20), concatenated unchanged by "
              f"{_COMBINE}:70-71 (arrayprobe.combine:177).",
        source_units="1"),
    "Size Distribution cm-3": VariableAttributes(
        units="cm-3", long_name="number concentration per size bin",
        basis=(
            f"derived, and the arithmetic checks out to the name the MATLAB gave the variable. "
            f"sd `conc_minR` is 'cm-4' ({_UIOOPS_SD}:1757), i.e. cm-3 per cm of size; `bin_dD` is "
            f"'millimeter' ({_UIOOPS_SD}:1751). {_COMBINE}:47-50 (arrayprobe.combine:173) writes "
            f"(conc_minR / 10) * bin_dD, and dividing by 10 is exactly the mm->cm conversion "
            f"(0.1 cm/mm), so cm-4 * cm = cm-3."),
        source_units="cm-4 (sd `conc_minR`, before the bin-width multiplication)"),
    "Number Concentration cm-3": VariableAttributes(
        units="cm-3", long_name="total number concentration",
        basis=f"read. {_UIOOPS_SD}:1772 'cm-3', on sd `n` (varid8), concatenated unchanged by "
              f"{_COMBINE}:66-69 (arrayprobe.combine:179).",
        source_units="cm-3"),
    "Reject Ratio": VariableAttributes(
        units="1", long_name="fraction of particles rejected",
        basis=(
            f"read, with the spelling corrected. {_UIOOPS_SD}:1807 writes '100/100' on sd "
            f"`Reject_ratio` (varid15), concatenated unchanged by {_COMBINE}:66-69 "
            f"(arrayprobe.combine:180). '100/100' is not udunits-legal and is UIOPS's own spelling "
            f"of a dimensionless ratio; it is kept verbatim in arrayprobe_source_units rather than "
            f"discarded."),
        source_units="100/100"),
}

COMBINED_SHAPE = ProductShape(
    name="combined_sizedist",
    writer=f"{_COMBINE}:202-231 (arrayprobe.combine._write)",
    variables=COMBINED_SIZEDIST,
    time_convention=(
        "Time Vector is a MATLAB datenum in days (combine_sizedist.m:95-120), not the HHMMSS "
        "the sd files carry. Seconds since 1970-01-01T00:00:00Z = "
        "(Time Vector - arrayprobe_datenum_unix_epoch_days) * 86400."),
    missing_value_convention=(
        "Missing seconds are IEEE-754 NaN in the float64 payload, with no _FillValue attribute "
        "-- the faithful writer's own convention (combine_sizedist.m:124-148 pads the 1 Hz "
        "grid with NaN; arrayprobe.combine:245-250). No _FillValue is added here, because "
        "adding one would change what a masking reader returns."),
)

#: Every product shape this module can attribute. One today. A shape is added by sourcing each
#: variable's unit from the MATLAB that writes it -- never by copying a neighbouring table.
SHAPES: tuple[ProductShape, ...] = (COMBINED_SHAPE,)

#: The SODA-2 engine's citation, exactly as its author provided it.
SODA2_CITATION = (
    "Aaron Bansemer. (2026). abansemer/soda2: v2.26.0 (Version v2.26.0) [Computer software]. "
    "Zenodo. https://doi.org/10.5281/zenodo.18331418")

_SODA2_WRITER = "arrayprobe_soda2/export_ncdf.py"
#: The three time variables every SODA-2 PSD file carries (export_ncdf.py:490-499).
SODA2_TIME_VARIABLES = ("elapsed_time", "base_time", "time")


def is_soda2_psd(names: Iterable[str],
                 global_attrs: Mapping[str, object] | None = None) -> bool:
    """Whether a file is a SODA-2 size-distribution netCDF: the writer's ``Source`` global
    (export_ncdf.py:464), or its three time variables together (export_ncdf.py:490-499)."""
    if global_attrs is not None and global_attrs.get("Source") == "SODA-2 OAP Processing Software":
        return True
    return set(SODA2_TIME_VARIABLES) <= set(names)


def _soda2_variable(name: str, source_attrs: Mapping[str, object]) -> VariableAttributes:
    """One SODA-2 variable's attributes, from ``export_ncdf.py``'s own tables (imported, never
    retyped). A variable the writer labels inline (the time block, ``bin_atts``) keeps the writer's
    own text, cited to that block. A tag the writer marks ``Unknown`` is refused."""
    from arrayprobe_soda2 import export_ncdf as w

    units = source_attrs.get("units")
    long_name = source_attrs.get("long_name")
    if name in w._MAIN_SIMPLE:
        ln, un, _ = w._MAIN_SIMPLE[name]
        return VariableAttributes(un, ln, f"read: {_SODA2_WRITER}:251-261 (_MAIN_SIMPLE)")
    if name in w._BULK_SIMPLE:
        ln, un = w._BULK_SIMPLE[name]
        return VariableAttributes(un, ln, f"read: {_SODA2_WRITER}:263-278 (_BULK_SIMPLE)")
    if name in w._LWC:
        return VariableAttributes(str(units), w._LWC[name],
                                  f"read: {_SODA2_WRITER}:280-284 (_LWC); units as written")
    if name in w._IWC:
        return VariableAttributes(str(units), w._IWC[name],
                                  f"read: {_SODA2_WRITER}:281-284 (_IWC); units as written")
    if units is None or long_name is None or "Unknown" in (units, long_name):
        raise UnknownProductError(
            f"SODA-2 variable {name!r} carries no sourced unit (the writer labels an unrecognised "
            f"numeric tag 'Unknown', {_SODA2_WRITER}:573-576); refusing rather than exporting a "
            f"guessed unit")
    if name in SODA2_TIME_VARIABLES:
        basis = f"read: {_SODA2_WRITER}:490-499 (the time block, soda2_export_ncdf.pro:74-91)"
    else:
        basis = f"read: {_SODA2_WRITER}:527-576 (bin_atts and the per-bin tags, as written)"
    return VariableAttributes(str(units), str(long_name), basis)


def soda2_shape(variables: Mapping[str, Mapping[str, object]]) -> ProductShape:
    """The shape of one SODA-2 PSD file. Its variable set depends on the run's tags and options
    (export_ncdf.py:540-630), so the shape is built per file rather than fixed."""
    return ProductShape(
        name="soda2_psd",
        writer=f"{_SODA2_WRITER}:389-660 (soda2_export_ncdf)",
        variables={n: _soda2_variable(n, a) for n, a in variables.items()},
        time_convention=(
            "time is 'seconds from midnight of start date'; elapsed_time is 'seconds since "
            "<flight date> <start time> +0000'; base_time is 'seconds since 01/01/1970' -- the "
            "writer's own units strings (arrayprobe_soda2/export_ncdf.py:491-499)."),
        missing_value_convention=(
            "The SODA-2 writer sets no _FillValue (arrayprobe_soda2/export_ncdf.py creates every "
            "variable without one); values are copied verbatim."),
    )


def identify_shape(names: Iterable[str]) -> ProductShape:
    """Which :data:`SHAPES` entry a file's variable names are, or :class:`UnknownProductError`."""
    names = list(names)
    for shape in SHAPES:
        if shape.matches(names):
            return shape
    known = ", ".join(s.name for s in SHAPES)
    missing = sorted(set(COMBINED_SIZEDIST) - set(names))
    extra = sorted(set(names) - set(COMBINED_SIZEDIST))
    raise UnknownProductError(
        f"no sourced attribute table for a file holding {sorted(names)!r}; known shapes: {known}. "
        f"Against {COMBINED_SHAPE.name} this file is missing {missing!r} and holds {extra!r} "
        f"besides. Refusing rather than exporting with guessed units -- add a ProductShape whose "
        f"every unit is quoted from the MATLAB that writes it, at file:line "
        f"(arrayprobe.attributed_export.COMBINED_SIZEDIST is the worked example).")


# ---------------------------------------------------------------------------
# The .call sidecar
# ---------------------------------------------------------------------------

#: A stamp key: an identifier at the start of the line or after whitespace, followed by ``=``.
#: The whitespace requirement is what keeps ``reject=(rej_hollow=0,max_edge_img_ar=4)`` one value
#: instead of three keys -- the inner ``=`` signs are preceded by ``(`` or ``,``, never by a space
#: (``src/arrayprobe/driver/run_flight.py:1571-1574`` builds that fragment with
#: ``",".join(...)``). It is **not** sufficient on its own: the S4c combine stamp nests a whole
#: space-separated stamp inside ``inputs_built_with=(...)``
#: (``src/arrayprobe/driver/run_flight.py:3600-3603``), whose inner keys *are* preceded by
#: spaces. :func:`_paren_depths` is what tells those apart from real keys.
_STAMP_KEY = re.compile(r"(?:^|\s)([A-Za-z_][A-Za-z0-9_.]*)=")

#: ``regimes.ResolvedField.render()``'s output: ``"<value> (<source>)"`` where ``<source>`` is
#: ``default`` (``stock`` in stamps written before 2026-10-16; both are read), ``regime:<name>``
#: or ``user:<path>`` (``regimes.py:196-199``). The value half has no
#: space, the tag half is parenthesised, which is why a threshold survives :func:`parse_stamp`
#: as one value and is split here rather than there.
_TAGGED = re.compile(r"^(?P<value>\S+)\s+\((?P<source>[^)]*)\)$")

#: The stamp keys whose value is a ``ResolvedField.render()`` string (see
#: ``src/arrayprobe/driver/run_flight.py:1063-1073``). Each becomes two attributes: the
#: number, and the provenance tag -- never blurred into one, which is the blurring this split exists
#: to prevent.
TAGGED_KEYS: tuple[str, ...] = ("area_ratio_z", "default_int_arr_thresh")


def _paren_depths(text: str) -> list[int]:
    """``depths[i]`` = how many ``(`` are still open immediately **before** ``text[i]``.

    Unbalanced parentheses are refused rather than guessed at: a stray ``)`` or an unclosed ``(``
    means the nesting this function exists to read cannot be read, and a depth map computed from
    it would silently make every key after the imbalance part of somebody else's value. Every
    fragment the driver writes is balanced (``run_flight._combine_stamp``, ``thresholds_stamp``,
    ``reject=(...)``), so an imbalance is a defect somewhere, not a shape to accommodate.
    """
    depths: list[int] = []
    level = 0
    for i, ch in enumerate(text):
        depths.append(level)
        if ch == "(":
            level += 1
        elif ch == ")":
            level -= 1
            if level < 0:
                raise StampParseError(
                    f".call stamp has a ')' with no matching '(' at offset {i} in {text!r}; "
                    f"refusing to parse a stamp whose nesting cannot be read")
    if level:
        raise StampParseError(
            f".call stamp leaves {level} '(' unclosed in {text!r}; refusing to parse a stamp "
            f"whose nesting cannot be read")
    return depths


def parse_stamp(stamp: str) -> dict[str, str]:
    """A ``.call`` line -> its **top-level** ``key=value`` pairs, in the order written.

    Values may contain spaces (``area_ratio_z=0.5 (default)``), nested ``=`` signs
    (``reject=(rej_hollow=0,...)``) and a whole nested stamp
    (``inputs_built_with=(engine=3.1.4 profile=... default_int_arr_thresh=6e-06 (default))``), so
    this is not a ``split()``: each key's value runs to the start of the next key **at paren depth
    zero**. A duplicated key is refused rather than resolved by a last-wins rule --
    ``sd_call_label``'s own docstring (``src/arrayprobe/driver/run_flight.py:1667-1670``) records a
    doubled ``engine=`` as a real defect class, and silently keeping one of two contradictory
    values is how a stamp stops meaning anything.

    **The nested stamp stays nested, and the outer level wins.** ``engine`` and ``profile`` appear
    both at the top level and inside ``inputs_built_with``; they are different facts and must not
    collide. The top-level keys describe *this* product; ``inputs_built_with`` is the provenance of
    the files it was stitched from (``run_flight._combine_stamp``), so it is returned as one value
    -- parenthesised, exactly as written; strip the outer ``()`` and call this function again if
    you want the inputs' own fields (``parse_nested`` does that). Promoting the inner keys
    would either overwrite the outer ones or trip the duplicate guard; both are wrong, and in an
    earlier version that promotion is exactly what happened: ``inputs_built_with`` truncated to
    ``'(engine=3.1.4'``, ``iat_file``/``profile``/``tree`` were silently the *inputs'* values under
    the product's own names, and the closing paren landed on the last value, where
    :func:`parse_tagged_value` finally raised and ``--attributed`` skipped every real product.

    A value that itself contains a space-separated ``word=`` (a Windows path with a space in it,
    say) would split wrongly here. That is why :func:`global_attributes` writes the raw line
    verbatim as well: the parsed keys are a convenience, the raw line is the record.
    """
    text = stamp.strip()
    if not text:
        raise StampParseError("empty .call stamp")
    depths = _paren_depths(text)
    hits = [hit for hit in _STAMP_KEY.finditer(text) if depths[hit.start()] == 0]
    if not hits:
        raise StampParseError(f"no key=value pair in .call stamp {text!r}")
    if hits[0].start() != 0:
        raise StampParseError(
            f".call stamp begins with {text[:hits[0].start()]!r}, which is not a key=value pair")
    out: dict[str, str] = {}
    for i, hit in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
        key = hit.group(1)
        if key in out:
            raise StampParseError(
                f"key {key!r} appears twice in .call stamp {text!r}; refusing to pick one")
        out[key] = text[hit.end():end].strip()
    return out


def parse_nested(value: str) -> dict[str, str]:
    """``"(engine=3.1.4 profile=X ...)"`` -> that nested stamp's own key=value pairs.

    The one nested stamp today is ``inputs_built_with`` (``run_flight._combine_stamp``). This is
    offered so a reader can get at the inputs' configuration **deliberately**, under its own name,
    instead of having those fields silently promoted into the product's own namespace -- which is
    the defect this whole paren-aware pass exists to undo. Nothing in :func:`global_attributes`
    calls it: the export writes the fragment verbatim, because which of the two ``profile=`` values
    a downstream reader wants is the reader's decision, not this module's.
    """
    inner = value.strip()
    if not (inner.startswith("(") and inner.endswith(")")):
        raise StampParseError(f"nested stamp {value!r} is not parenthesised")
    return parse_stamp(inner[1:-1])


def parse_reject(value: str) -> dict[str, str]:
    """``"(rej_hollow=0,max_edge_img_ar=4)"`` -> ``{"rej_hollow": "0", ...}``.

    The fragment is built off the :class:`~arrayprobe_uiops.reject_core.RejectConfig` dataclass's
    fields
    (``src/arrayprobe/driver/run_flight.py:1552-1554``, "read off the dataclass, so a field
    added later enters the stamp without anyone remembering to add it"), so this parses whatever
    is there rather than a fixed field list -- a field added upstream reaches the exported file
    with no edit here.
    """
    inner = value.strip()
    if not (inner.startswith("(") and inner.endswith(")")):
        raise StampParseError(f"reject fragment {value!r} is not parenthesised")
    inner = inner[1:-1].strip()
    if not inner:
        return {}
    fields: dict[str, str] = {}
    for part in inner.split(","):
        if "=" not in part:
            raise StampParseError(f"reject field {part!r} is not key=value")
        k, v = part.split("=", 1)
        fields[k.strip()] = v.strip()
    return fields


def parse_tagged_value(value: str) -> tuple[float, str]:
    """``"0.5 (regime:liquid-warm)"`` -> ``(0.5, "regime:liquid-warm")``.

    Both halves are returned because both are needed and neither implies the other: the number
    without the tag cannot be told apart from a value someone typed, and the tag without the number
    says nothing about what ran (``regimes.ResolvedField``'s own docstring: "three different
    epistemic objects that must never be blurred").
    """
    hit = _TAGGED.match(value.strip())
    if hit is None:
        raise StampParseError(
            f"threshold value {value!r} is not ResolvedField.render()'s '<value> (<source>)' shape")
    try:
        number = float(hit.group("value"))
    except ValueError as exc:  # pragma: no cover -- a non-numeric threshold is not reachable today
        raise StampParseError(f"threshold value {value!r} has a non-numeric value half") from exc
    return number, hit.group("source")


def read_stamp(source: Path) -> str | None:
    """The ``.call`` line beside ``source``, or ``None``. Mirrors ``run_flight.read_stamp``."""
    sidecar = Path(str(source) + CALL_SUFFIX)
    if not sidecar.exists():
        return None
    return sidecar.read_text().strip()


# ---------------------------------------------------------------------------
# The export
# ---------------------------------------------------------------------------

def default_output_path(source: Path | str) -> Path:
    """``<source><DEFAULT_SUFFIX>`` -- beside the faithful file, same stem, new suffix.

    This is the current layout and may change in a later release
    (``docs/developer/ATTRIBUTED_EXPORT.md`` §3). Co-location keeps the
    correspondence obvious in a directory listing and makes the pair sort adjacently; the ``.nc``
    ending says NETCDF4 where the faithful archived product says ``.cdf``; and nothing about the
    faithful file's own name changes, which matters because every validated comparison addresses it
    by name.
    """
    return Path(str(source) + DEFAULT_SUFFIX)


def sha256_of(path: Path | str, *, chunk: int = 1 << 20) -> str:
    """The file's SHA-256, streamed. Written into the export so the attributed file names the
    exact faithful bytes it describes -- the pair can be separated and still re-associated."""
    digest = hashlib.sha256()
    # `Path.open`, never a bare `open`: `arrayprobe.ncio` defines an `open` of its own (MATLAB's
    # `netcdf.open`, carrying a ruff A001 exemption), and this module imports that module, so a
    # later `from .ncio import open` would silently turn a byte read into a netCDF call.
    with Path(path).open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _package_version() -> str:
    from . import __version__ as version  # local import: keeps module import cheap and cycle-free
    return str(version)


# The basis written beside an engine read from a stamp that does not name one.
ENGINE_INFERRED_BASIS = (
    "inferred, not stamped: this .call predates 2026-09-15, when every v3.1.4 stamp "
    "began naming its own engine (run_flight._engine_prefix). "
    "run_flight._stamps_equivalent reads the absence of engine= as engine=3.1.4; "
    "this export reads it the same way.")


def shared_attributes(
    *,
    engine: str | None,
    engine_basis: str | None = None,
    sd_configuration: str | None = None,
    enhancements: Sequence[str] = (),
    enhancements_record: str | None = None,
    tas_qc: dict | None = None,
) -> dict[str, object]:
    """The run-level block every product of one run carries, identical in each.

    The attributed combined (:func:`global_attributes`) and the faithful ARM copy of the port's
    ``sd`` (:func:`stamp_shared_attributes`) each keep their own ``arrayprobe_call_stamp`` and
    ``arrayprobe_stage``; what they share is this: the engine, the ``sd``-level configuration
    (``arrayprobe_inputs_built_with``, the ``sd`` stamp in parentheses -- a combined's stamp
    carries it under that key, the ARM copy reads it from its ``sd``), the enhancements applied
    and their record, the airspeed QC summary and the package version. ``engine=None`` (an
    unstamped source) and ``sd_configuration=None`` leave those keys out rather than invent them.
    """
    atts: dict[str, object] = {
        f"{ATTR_PREFIX}package_version": _package_version(),
        f"{ATTR_PREFIX}enhancements_applied": ",".join(enhancements) if enhancements else "none",
        f"{ATTR_PREFIX}enhancements_basis": (
            "none by construction when the producer is the port: 'the port is the faithful "
            "reproduction and nothing else' (the package's rule that enhancements live outside "
            "the port), "
            "enforced by tests/test_no_enhancement_coupling.py. scripts/run_flight.py applies "
            "corrections only to SEPARATE <stem>.enh.* products (named in their own .call), "
            "never to the faithful file this export reads. A non-port chain must name what it "
            "applied through this exporter's `enhancements` argument."),
    }
    if enhancements_record is not None:
        # The producing chain's own record, verbatim text read from its sidecar by the
        # caller -- nothing here imports the enhancements package.
        atts[f"{ATTR_PREFIX}enhancements_record"] = enhancements_record
    if tas_qc is not None:
        # Which seconds were sized with a substituted or default TAS, read from the source's
        # <product>.tasqc.json -- the run log is not the only record of it.
        for key, value in tas_qc.items():
            atts[f"{ATTR_PREFIX}{key}"] = value
    else:
        atts[f"{ATTR_PREFIX}tas_qc"] = (
            "absent: the source carries no .tasqc.json, either because the run named no TAS "
            "source (probe housekeeping TAS throughout) or because it predates the record "
            "(2026-09-23). Which seconds took a default TAS is not established here.")
    if engine is not None:
        atts[f"{ATTR_PREFIX}engine"] = engine
        if engine_basis is not None:
            atts[f"{ATTR_PREFIX}engine_basis"] = engine_basis
    if sd_configuration is not None:
        atts[f"{ATTR_PREFIX}inputs_built_with"] = f"({sd_configuration})"
    return atts


def _shared_from_stamp(stamp: str | None, *, nested: bool, **kw) -> dict[str, object]:
    """:func:`shared_attributes` for a product whose ``.call`` is ``stamp``. ``nested``: the
    ``sd`` configuration is the stamp's ``inputs_built_with=(...)`` (a combined); otherwise it
    is the stamp itself (the stamp of an ``sd``, or of a copy of one)."""
    if stamp is None:
        return shared_attributes(engine=None, **kw)
    keys = parse_stamp(stamp)
    sd_configuration: str | None = stamp.strip()
    if nested:
        inner = keys.get("inputs_built_with", "").strip()
        sd_configuration = (inner[1:-1] if inner.startswith("(") and inner.endswith(")")
                            else None)
    return shared_attributes(engine=keys.get("engine", "3.1.4"),
                             engine_basis=None if "engine" in keys else ENGINE_INFERRED_BASIS,
                             sd_configuration=sd_configuration, **kw)


def global_attributes(
    stamp: str | None,
    *,
    source_path: Path | str,
    source_sha256: str,
    source_bytes: int,
    shape: ProductShape,
    files_stitched: int | None = None,
    enhancements: Sequence[str] = (),
    export_time: str | None = None,
    enhancements_record: str | None = None,
    tas_qc: dict | None = None,
    existing_attributes: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Every global attribute the export writes, as a plain dict.

    ``existing_attributes`` are the faithful file's own global attributes. Each name in
    :data:`ACDD_KEYS` that it holds is carried over verbatim rather than replaced
    (:func:`acdd_attributes`).

    Separated from :func:`export` so the block can be asserted without writing a file, and so a
    caller assembling a product by another route can write the identical block. The run-level
    part is :func:`shared_attributes`, placed here so the set and order of keys is unchanged; the
    rest (source file and hash, product shape, fidelity note, time and missing-value
    conventions, the exploded stamp) belongs to this file alone.

    ``stamp`` is the raw ``.call`` line. It is written **verbatim** as
    ``arrayprobe_call_stamp`` *and* exploded into one attribute per key: the verbatim line is the
    record (nothing can be lost to a parsing edge case), the exploded keys are what a reader's
    tooling can actually filter on. Any key this module does not recognise is still written, under
    its own name -- so a stamp key added later reaches the file without an edit here.
    """
    shared = _shared_from_stamp(stamp, nested=True, enhancements=enhancements,
                                enhancements_record=enhancements_record, tas_qc=tas_qc)
    now = export_time or _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")
    p = ATTR_PREFIX
    atts: dict[str, object] = {
        f"{p}export_convention": EXPORT_CONVENTION,
        f"{p}export_module": "arrayprobe.attributed_export",
        f"{p}package_version": shared[f"{p}package_version"],
        f"{p}export_time": now,
        f"{p}source_file": Path(source_path).name,
        f"{p}source_sha256": source_sha256,
        f"{p}source_bytes": int(source_bytes),
        f"{p}source_writer": shape.writer,
        f"{p}product_shape": shape.name,
        f"{p}fidelity_note": (
            "This file is NOT the byte-comparison artefact. The faithful file named in "
            "arrayprobe_source_file is: it carries zero attributes because the MATLAB that defines "
            "its format writes zero attributes (combine_sizedist.m:202-231, measured), and every "
            "validated-flight comparison is made against it. This file holds the same values and "
            "adds metadata; use it to read the data, use the faithful file to compare bytes."),
        f"{p}time_convention": shape.time_convention,
        f"{p}datenum_unix_epoch_days": DATENUM_UNIX_EPOCH_DAYS,
        f"{p}missing_value_convention": shape.missing_value_convention,
        f"{p}enhancements_applied": shared[f"{p}enhancements_applied"],
        f"{p}enhancements_basis": shared[f"{p}enhancements_basis"],
    }
    if files_stitched is not None:
        atts[f"{p}files_stitched"] = int(files_stitched)
    placed_later = (f"{p}engine", f"{p}engine_basis", f"{p}inputs_built_with")
    for key, value in shared.items():      # the enhancements record and the airspeed QC
        if key not in atts and key not in placed_later:
            atts[key] = value

    if stamp is None:
        atts[f"{p}call_stamp"] = (
            "ABSENT -- the faithful file carried no .call sidecar and the export was run with "
            "accept_unstamped=True. The engine, profile, thresholds and reject configuration that "
            "produced it are NOT established. Stated rather than left blank.")
        atts.update(acdd_attributes(atts, stamp=None, source_path=source_path,
                                    source_sha256=source_sha256, shape=shape, created=now,
                                    existing=existing_attributes))
        return atts

    atts[f"{p}call_stamp"] = stamp
    keys = parse_stamp(stamp)
    for key, value in keys.items():
        if key == "reject":
            atts[f"{p}reject"] = value
            for field, field_value in parse_reject(value).items():
                atts[f"{p}reject_{field}"] = field_value
        elif key in TAGGED_KEYS:
            number, tag = parse_tagged_value(value)
            atts[f"{p}{key}"] = number
            atts[f"{p}{key}_source"] = tag
        else:
            atts[f"{p}{key}"] = value
    # src/arrayprobe/driver/run_flight.py:1925-1928: a v3.1.4 stamp written before 2026-09-15 has
    # no `engine=` key, and `_stamps_equivalent` reads that absence as engine=3.1.4; the shared
    # block reads it the same way and says so. The update adds only that inferred engine and its
    # basis, at the end; every other shared key is already in place with an equal value.
    for key, value in shared.items():
        atts.setdefault(key, value)
    atts.update(acdd_attributes(atts, stamp=stamp, source_path=source_path,
                                source_sha256=source_sha256, shape=shape, created=now,
                                existing=existing_attributes))
    return atts


def acdd_attributes(
    atts: Mapping[str, object],
    *,
    stamp: str | None,
    source_path: Path | str,
    source_sha256: str,
    shape: ProductShape,
    created: str,
    existing: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """The ACDD/CF discovery attributes (:data:`ACDD_KEYS`), built from the run record.

    ``atts`` is the prefixed block :func:`global_attributes` has already assembled; every value
    here is read from it or from the stamp, never asserted afresh. A name present in ``existing``
    (the faithful file's own globals) is returned with the faithful file's value, unchanged.
    """
    p = ATTR_PREFIX
    version = str(atts[f"{p}package_version"])
    name = Path(source_path).name
    engine = atts.get(f"{p}engine")
    if stamp is None:
        record = "run record ABSENT (no .call sidecar beside the faithful file)"
        source = ("arrayprobe; the engine that produced the faithful file is not established "
                  "(no .call sidecar)")
    else:
        record = f"run record (.call, verbatim): {stamp}"
        source = (f"arrayprobe engine={engine}; the full run record is the attribute "
                  f"{p}call_stamp")
    ours: dict[str, object] = {
        "Conventions": ACDD_CONVENTIONS,
        "history": (f"{created} arrayprobe.attributed_export {version}: attributed copy of "
                    f"{name} (sha256 {source_sha256}), values unchanged; {record}"),
        "source": source,
        "processing_level": f"{shape.name}, as written by {shape.writer}",
        "product_version": version,
        "date_created": created,
    }
    held = dict(existing or {})
    return {key: (held[key] if key in held else ours[key]) for key in ACDD_KEYS}


def stamp_shared_attributes(target: Path | str, sd: Path | str,
                            combined: Path | str | None = None, *,
                            enhancements: Sequence[str] = (),
                            enhancements_record: str | None = None) -> dict[str, object]:
    """Write :func:`shared_attributes` into ``target``, a product made from the port's ``sd``.

    ``target`` is opened read-write and only global attributes are set. With ``combined`` (the
    run's combined product, OUTPUT 2's source), the block is the combined's -- its ``.call`` and
    its ``.tasqc.json``, including the merged-parts key the per-``sd`` record lacks -- so OUTPUT 3
    carries exactly OUTPUT 2's run-level block. Without
    it, the block is read from ``sd``. Either source is only read. ``enhancements`` and
    ``enhancements_record`` name the corrections the run applied (a stamp does not), so the
    enhanced lineage's block is built whole rather than patched afterwards. Returns the block
    written.
    """
    enh = {"enhancements": tuple(enhancements), "enhancements_record": enhancements_record}
    if combined is not None:
        combined = Path(combined)
        block = _shared_from_stamp(read_stamp(combined), nested=True,
                                   tas_qc=read_qc_sidecar(combined), **enh)
    else:
        sd = Path(sd)
        block = _shared_from_stamp(read_stamp(sd), nested=False, tas_qc=read_qc_sidecar(sd),
                                   **enh)
    with Dataset(str(target), "r+") as ds:
        for key, value in block.items():
            ds.setncattr(key, value)
    return block


class StorageOptions(TypedDict, total=False):
    """The ``createVariable`` keywords :func:`storage_options` may return, typed as netCDF4's own
    signature takes them, so a call site needs no cast."""

    zlib: bool
    complevel: Literal[0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
    shuffle: bool
    chunksizes: list[int]


def storage_options(dtype: np.dtype, sizes: Sequence[int], *,
                    analysis_ready: bool = True) -> StorageOptions:
    """``createVariable`` storage keywords for one variable: empty (contiguous, uncompressed) when
    ``analysis_ready`` is off, and for a variable that cannot be compressed losslessly here -- a
    scalar, a zero-length dimension, or a non-numeric type. Storage only: no keyword returned here
    changes a value, a dtype or a dimension order."""
    dtype = np.dtype(dtype)
    if (not analysis_ready or not sizes or any(n == 0 for n in sizes)
            or dtype.kind not in "biuf"):
        return {}
    chunks = [n if n <= ANALYSIS_READY_WHOLE_DIM else min(n, ANALYSIS_READY_CHUNK)
              for n in sizes]
    return {"zlib": True, "complevel": ANALYSIS_READY_COMPLEVEL,
            "shuffle": dtype.kind in "biu", "chunksizes": chunks}


def export(
    source: Path | str,
    out: Path | str | None = None,
    *,
    stamp: str | None = None,
    accept_unstamped: bool = False,
    enhancements: Sequence[str] = (),
    export_time: str | None = None,
    enhancements_record: str | None = None,
    analysis_ready: bool = True,
) -> Path:
    """Write the attributed sibling of the faithful product ``source``. Returns the path written.

    ``source`` is opened read-only and is never modified -- asserted by
    ``tests/test_attributed_export.py`` hashing it either side of this call. ``stamp`` defaults to
    the ``.call`` sidecar beside it; absent, the export is refused unless ``accept_unstamped``.

    ``enhancements`` names what a non-port producer applied. Empty (the default) writes
    ``enhancements_applied = "none"``, which is the port's own case by construction.

    ``export_time`` pins the timestamp, for tests that compare two exports byte for byte -- the same
    reason ``creation_time=`` exists on the faithful writers.

    ``analysis_ready`` (default on) writes each variable chunked and losslessly compressed
    (:func:`storage_options`), so the file is the cloud-optimised form as well as the attributed
    one; ``False`` writes it contiguous and uncompressed. Either way every value is unchanged, and
    the file states which under ``arrayprobe_encoding``.
    """
    source = Path(source)
    out = Path(out) if out is not None else default_output_path(source)
    if out.resolve() == source.resolve():
        raise AttributedExportError(
            f"refusing to write the attributed export over the faithful file {source}; the whole "
            f"point of this module is that the faithful bytes do not move")

    # A SODA-2 run's record is the JSON stamp `<stem>.pbp.call` beside its `<stem>.nc`.
    soda2_call = source.with_suffix(".pbp.call")
    soda2_record = (soda2_call.read_text(encoding="utf-8") if soda2_call.is_file() else None)
    if stamp is None:
        stamp = read_stamp(source)
        if stamp is None and soda2_record is None and not accept_unstamped:
            raise MissingStampError(
                f"{source.name} carries no {CALL_SUFFIX} sidecar, so the engine, profile, "
                f"thresholds and reject configuration that produced it are unknown. An attributed "
                f"file that states nothing about its own provenance is worse than none, because a "
                f"reader cannot tell the difference. Pass accept_unstamped=True to export anyway "
                f"(the file then says so), or restore the sidecar.")

    src = Dataset(str(source), "r")
    try:
        src.set_auto_maskandscale(False)  # raw values, ncio.get_var's policy -- NaN stays NaN
        src_globals = {k: src.getncattr(k) for k in src.ncattrs()}
        soda2 = is_soda2_psd(src.variables, src_globals)
        if soda2:
            shape = soda2_shape({n: {k: v.getncattr(k) for k in v.ncattrs()}
                                 for n, v in src.variables.items()})
        else:
            shape = identify_shape(src.variables)
        files_stitched = (len(src.dimensions["files_stitched"])
                          if "files_stitched" in src.dimensions else None)
        atts = global_attributes(
            stamp,
            source_path=source,
            source_sha256=sha256_of(source),
            source_bytes=source.stat().st_size,
            shape=shape,
            files_stitched=files_stitched,
            enhancements=enhancements,
            export_time=export_time,
            enhancements_record=enhancements_record,
            tas_qc=read_qc_sidecar(source),
            existing_attributes={k: src.getncattr(k) for k in src.ncattrs()},
        )
        # Before the ACDD discovery block, which stays the last thing written (the order
        # tests/test_config_outputs.py pins).
        if soda2:
            atts[f"{ATTR_PREFIX}engine"] = "soda2"
            atts[f"{ATTR_PREFIX}engine_citation"] = SODA2_CITATION
            if soda2_record is not None:
                atts[f"{ATTR_PREFIX}run_record"] = soda2_record
            atts["references"] = SODA2_CITATION
            atts["source"] = f"arrayprobe engine=soda2; {SODA2_CITATION}"
        acdd = {key: atts.pop(key) for key in ACDD_KEYS if key in atts}
        atts[f"{ATTR_PREFIX}encoding"] = (ENCODING_ANALYSIS_READY if analysis_ready
                                          else ENCODING_PLAIN)
        atts.update(acdd)
        dst = Dataset(str(out), "w", format="NETCDF4")
        try:
            dst.set_auto_maskandscale(False)
            dst.setncatts(atts)
            for name, dim in src.dimensions.items():
                # `files_stitched` is used by no variable -- "the only record of how many files
                # went into the product" (arrayprobe.combine:332-333). Carried over as a dimension
                # *and* surfaced as an attribute above, because a bare dimension is easy to miss.
                dst.createDimension(name, None if dim.isunlimited() else len(dim))
            for name, var in src.variables.items():
                spec = shape.variables[name]
                # Verbatim: same dtype, same dimension list, same order. No transpose is performed
                # or implied -- see the module docstring.
                new = dst.createVariable(
                    name, var.dtype, var.dimensions,
                    **storage_options(var.dtype, [len(src.dimensions[d]) for d in var.dimensions],
                                      analysis_ready=analysis_ready))
                new.set_auto_maskandscale(False)
                # ncio's own helper, not a second suppression invented here: netCDF4 1.7.4's
                # Variable.__setitem__ sets .shape on the incoming array in place, which NumPy 2.5
                # deprecates, and it fires for a perfectly shaped input (ncio.py:118-138).
                with ncio._quiet_netcdf4_setitem():
                    new[...] = np.asarray(var[...])
                new.units = spec.units
                new.long_name = spec.long_name
                new.setncattr(f"{ATTR_PREFIX}units_basis", spec.basis)
                if spec.source_units is not None:
                    new.setncattr(f"{ATTR_PREFIX}source_units", spec.source_units)
                # Any attribute the source variable carries that this export does not itself set
                # is copied verbatim, after the ones it does set. `_FillValue` can only be set at
                # creation; it is skipped here rather than re-created with a different meaning.
                written = set(new.ncattrs())
                for key in var.ncattrs():
                    if key not in written and key != "_FillValue":
                        new.setncattr(key, var.getncattr(key))
        finally:
            dst.close()
    finally:
        src.close()
    return out


def default_zarr_path(attributed_nc: Path | str) -> Path:
    """``<attributed_nc>`` with a trailing ``.nc`` replaced by ``.zarr`` (appended otherwise)."""
    attributed_nc = Path(attributed_nc)
    if attributed_nc.suffix == ".nc":
        return attributed_nc.with_suffix(".zarr")
    return attributed_nc.with_name(attributed_nc.name + ".zarr")


def export_zarr(attributed_nc: Path | str, store: Path | str | None = None) -> Path:
    """Opt-in: copy the attributed netCDF4 export ``attributed_nc`` into a Zarr store.

    netCDF4 stays the default output; this is a second, optional encoding of the same file. Every
    variable's values, dtype and dimension order are carried unchanged, and every global and
    variable attribute verbatim, except the global ``arrayprobe_encoding``, which is overwritten
    with :data:`ENCODING_ZARR`. The file is read with CF decoding, masking, scaling and time
    decoding all off, so no value is reinterpreted: NaN stays NaN and no ``_FillValue`` is added.
    Chunks follow :func:`storage_options`' rule. Needs the ``[zarr]`` extra (zarr and xarray),
    imported here and nowhere at module level. Refuses to write over an existing ``store``.
    """
    try:
        import xarray as xr
        import zarr  # noqa: F401 -- imported only to fail early with the extra's name
    except ImportError as exc:
        raise AttributedExportError(
            f"the Zarr writer needs zarr and xarray, which are not installed ({exc}). Install "
            f"them with `pip install arrayprobe[{ZARR_EXTRA}]`; netCDF4, the default output, "
            f"needs neither.") from exc
    attributed_nc = Path(attributed_nc)
    store = Path(store) if store is not None else default_zarr_path(attributed_nc)
    if store.exists():
        raise AttributedExportError(
            f"refusing to write the Zarr store over an existing path {store}; remove or rename "
            f"it first")
    with xr.open_dataset(attributed_nc, engine="netcdf4", decode_cf=False, mask_and_scale=False,
                         decode_times=False, decode_coords=False) as ds:
        ds = ds.load()
    encoding: dict[str, dict[str, object]] = {}
    for name, var in ds.variables.items():
        var.encoding = {}
        enc: dict[str, object] = {}
        chunks = storage_options(var.dtype, list(var.shape)).get("chunksizes")
        if isinstance(chunks, list):
            enc["chunks"] = tuple(chunks)
        if "_FillValue" not in var.attrs:
            # xarray otherwise writes a NaN fill for floats; ``None`` adds no _FillValue. One the
            # source itself wrote stays in the attributes, verbatim.
            enc["_FillValue"] = None
        encoding[str(name)] = enc
    ds.attrs[f"{ATTR_PREFIX}encoding"] = ENCODING_ZARR
    ds.to_zarr(store, mode="w-", encoding=encoding, consolidated=False)
    return store


def default_parquet_path(attributed_nc: Path | str) -> Path:
    """``<attributed_nc>`` with a trailing ``.nc`` replaced by ``.parquet`` (appended otherwise);
    the path is a directory holding one Parquet file per dimension tuple."""
    attributed_nc = Path(attributed_nc)
    if attributed_nc.suffix == ".nc":
        return attributed_nc.with_suffix(".parquet")
    return attributed_nc.with_name(attributed_nc.name + ".parquet")


#: The per-particle dimension of a proc (S3, ``imgProc_sm``) file: one entry per particle.
PARTICLE_DIM = "time"


def _export_particles_parquet(proc_nc: Path, out: Path | None, pa, pq) -> Path:
    """``layout="particles"``: one Parquet file, one row per particle of a proc file.

    Every variable on ``(time,)`` is a column; a variable on ``(time, k)`` becomes ``k`` columns
    ``name[1]`` .. ``name[k]`` (MATLAB's 1-based column index). Variables on no particle axis
    (``bin_count``) are not particle columns and are left out. Values are read with masking and
    scaling off, dtypes kept. Schema metadata carries the source's SHA-256, its ``.call`` stamp
    (``None`` when it has none) and every variable's attributes as JSON."""
    import json

    import netCDF4
    import numpy as np

    out = out if out is not None else proc_nc.with_name(proc_nc.name + ".particles.parquet")
    if out.exists():
        raise AttributedExportError(
            f"refusing to write the Parquet particle table over an existing path {out}")
    columns: dict[str, object] = {}
    var_attrs: dict[str, object] = {}
    with netCDF4.Dataset(proc_nc, "r") as ds:
        ds.set_auto_maskandscale(False)
        if PARTICLE_DIM not in ds.dimensions:
            raise AttributedExportError(
                f"{proc_nc} has no {PARTICLE_DIM!r} dimension; layout='particles' needs a proc "
                f"(per-particle) file")
        n = len(ds.dimensions[PARTICLE_DIM])
        for name, var in ds.variables.items():
            if not var.dimensions or var.dimensions[0] != PARTICLE_DIM:
                continue
            values = np.asarray(var[...])
            if values.ndim == 1:
                columns[name] = values
            elif values.ndim == 2:
                for j in range(values.shape[1]):
                    columns[f"{name}[{j + 1}]"] = values[:, j]
            else:
                raise AttributedExportError(
                    f"variable {name!r} has {values.ndim} dimensions; a particle row holds at "
                    f"most a 2-D (particle, k) variable")
            var_attrs[name] = {k: (lambda v: v.tolist() if hasattr(v, "tolist") else v)(
                var.getncattr(k)) for k in var.ncattrs()}
    table = pa.table(columns)
    assert table.num_rows == n, (table.num_rows, n)
    meta = {
        f"{ATTR_PREFIX}layout": "particles",
        f"{ATTR_PREFIX}source_sha256": sha256_of(proc_nc),
        f"{ATTR_PREFIX}source_name": proc_nc.name,
        f"{ATTR_PREFIX}call_stamp": json.dumps(read_stamp(proc_nc)),
        f"{ATTR_PREFIX}var_attrs": json.dumps(var_attrs),
    }
    pq.write_table(table.replace_schema_metadata(meta), out)
    return out


def export_parquet(attributed_nc: Path | str, out: Path | str | None = None, *,
                   layout: str = "dimensions") -> Path:
    """Opt-in: copy the attributed netCDF4 export ``attributed_nc`` into Parquet files.

    ``layout="particles"`` (opt-in; the default ``"dimensions"`` is unchanged) instead takes a
    proc (S3, per-particle) file and writes one Parquet file, default
    ``<proc>.particles.parquet``, with one row per particle: see
    :func:`_export_particles_parquet`.

    netCDF4 stays the default output. Parquet is tabular, so ``out`` is a directory with one
    file per distinct dimension tuple, ``<dimA>__<dimB>.parquet``, in long form: one int64 index
    column per dimension, named after it, then one column per variable on that tuple, its values
    flattened in C order with the dtype kept. Scalars go to ``scalars.parquet`` (one row). Global
    and per-variable attributes are JSON in each file's schema metadata
    (``arrayprobe_global_attrs``, ``arrayprobe_var_attrs``), with ``arrayprobe_encoding`` set to
    :data:`ENCODING_PARQUET`. The file is read with masking and scaling off. A dtype pyarrow
    cannot hold raises, naming the variables. Needs the ``[parquet]`` extra (pyarrow), imported
    here and nowhere at module level. Refuses to write over an existing ``out``.
    """
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise AttributedExportError(
            f"the Parquet writer needs pyarrow, which is not installed ({exc}). Install it with "
            f"`pip install arrayprobe[{PARQUET_EXTRA}]`; netCDF4, the default output, needs "
            f"neither.") from exc
    if layout == "particles":
        return _export_particles_parquet(Path(attributed_nc),
                                         Path(out) if out is not None else None, pa, pq)
    if layout != "dimensions":
        raise AttributedExportError(
            f"unknown Parquet layout {layout!r}; use 'dimensions' (default) or 'particles'")
    import json

    import netCDF4
    import numpy as np

    attributed_nc = Path(attributed_nc)
    out = Path(out) if out is not None else default_parquet_path(attributed_nc)
    if out.exists():
        raise AttributedExportError(
            f"refusing to write the Parquet directory over an existing path {out}; remove or "
            f"rename it first")

    def _jsonable(value: object) -> object:
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, np.generic):
            return value.item()
        return value

    groups: dict[tuple[str, ...], dict[str, tuple[np.ndarray, dict[str, object]]]] = {}
    with netCDF4.Dataset(attributed_nc, "r") as ds:
        ds.set_auto_maskandscale(False)
        global_attrs = {k: _jsonable(ds.getncattr(k)) for k in ds.ncattrs()}
        global_attrs[f"{ATTR_PREFIX}encoding"] = ENCODING_PARQUET
        sizes = {name: len(dim) for name, dim in ds.dimensions.items()}
        for name, var in ds.variables.items():
            attrs = {k: _jsonable(var.getncattr(k)) for k in var.ncattrs()}
            groups.setdefault(tuple(var.dimensions), {})[name] = (np.asarray(var[...]), attrs)
    out.mkdir(parents=True)
    for dims, members in groups.items():
        shape = tuple(sizes[d] for d in dims)
        columns: dict[str, object] = {}
        if dims:
            index = np.indices(shape, dtype=np.int64).reshape(len(dims), -1)
            for d, col in zip(dims, index, strict=True):
                columns[d] = col
        for name, (values, _attrs) in members.items():
            if name in columns:
                if dims == (name,):
                    # A coordinate variable (``time`` on ``time``): its values replace the
                    # int64 index column, whose position the row order already carries.
                    columns[name] = values.reshape(-1)
                    continue
                raise AttributedExportError(
                    f"variable {name!r} has the same name as one of its dimensions' index "
                    f"columns; the Parquet layout cannot hold both")
            columns[name] = values.reshape(-1) if dims else values.reshape(1)
        try:
            table = pa.table(columns)
        except (pa.ArrowInvalid, pa.ArrowNotImplementedError, pa.ArrowTypeError) as exc:
            raise AttributedExportError(
                f"pyarrow cannot hold a variable on dimensions {dims} "
                f"({', '.join(members)}): {exc}") from exc
        meta = {
            f"{ATTR_PREFIX}global_attrs": json.dumps(global_attrs),
            f"{ATTR_PREFIX}var_attrs": json.dumps({n: a for n, (_v, a) in members.items()}),
            f"{ATTR_PREFIX}dims": json.dumps(list(dims)),
            f"{ATTR_PREFIX}encoding": ENCODING_PARQUET,
        }
        table = table.replace_schema_metadata(meta)
        fname = ("__".join(dims) if dims else "scalars") + ".parquet"
        pq.write_table(table, out / fname)
    return out


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m arrayprobe.attributed_export FAITHFUL.cdf [OUT.nc] [--zarr] [--parquet]``."""
    parser = argparse.ArgumentParser(
        prog="python -m arrayprobe.attributed_export",
        description=("Write a self-describing sibling of a faithful port product: same values, "
                     "plus the whole .call sidecar and a sourced unit on every variable. The "
                     "faithful file is opened read-only and never modified."))
    parser.add_argument("source", help="the faithful product (its .call sidecar is read too)")
    parser.add_argument("out", nargs="?", default=None,
                        help=f"output path (default: <source>{DEFAULT_SUFFIX})")
    parser.add_argument("--accept-unstamped", action="store_true",
                        help="export a product with no .call sidecar; the file records that its "
                             "provenance is not established")
    parser.add_argument("--enhancements", default="",
                        help="comma-separated names of enhancements the producing chain applied; "
                             "empty (the default) means none, which is the port's own case")
    parser.add_argument("--plain", action="store_true",
                        help="write contiguous, uncompressed variables instead of the default "
                             "analysis-ready (chunked, losslessly compressed) encoding; the "
                             "values are identical either way")
    parser.add_argument("--zarr", action="store_true",
                        help="also write a Zarr store beside the netCDF4 export (<out> with .nc "
                             "replaced by .zarr), same values and attributes; needs the [zarr] "
                             "extra")
    parser.add_argument("--parquet", action="store_true",
                        help="also write a directory of Parquet files beside the netCDF4 export "
                             "(<out> with .nc replaced by .parquet), one long-form file per "
                             "dimension tuple, attributes as schema metadata; needs the "
                             "[parquet] extra")
    args = parser.parse_args(argv)
    names = tuple(n.strip() for n in args.enhancements.split(",") if n.strip())
    if not Path(args.source).is_file():
        # Checked first: a mistyped path otherwise failed as "carries no .call sidecar".
        print(f"{parser.prog}: not a file: {args.source}", file=sys.stderr)
        return 2
    try:
        written = export(args.source, args.out, accept_unstamped=args.accept_unstamped,
                         enhancements=names, analysis_ready=not args.plain)
        netcdf = written
        if args.zarr:
            print(f"wrote {written}")
            written = export_zarr(netcdf)
        if args.parquet:
            print(f"wrote {written}")
            written = export_parquet(netcdf)
    except AttributedExportError as exc:
        # One line, exit 2, as every other refusal on the command line; the library keeps
        # raising. MissingStampError's text names the keyword, so the flag is added here.
        hint = (" On the command line that is --accept-unstamped."
                if isinstance(exc, MissingStampError) else "")
        print(f"{parser.prog}: {exc}{hint}", file=sys.stderr)
        return 2
    print(f"wrote {written}")
    return 0


if __name__ == "__main__":  # pragma: no cover -- exercised through main() in the tests
    raise SystemExit(main())
