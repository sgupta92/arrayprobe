# SPDX-License-Identifier: BSD-3-Clause
"""A friendly re-view of four raw contracts, each a finding the port keeps rather than fixes.

Four fidelity-forced raw contracts, re-viewed without changing them.

The port's public functions stay exactly as they are;
this module adds documented wrappers for the contracts
a Python user will trip on.
This module is that boundary layer, and nothing else -- **rename/re-view
only**: every function below calls the raw port function unchanged and
repackages what comes back. None of them computes a number the raw function
did not already compute; none of them is on the reproduction path
(``tests/test_friendly.py::TestPipelineStagesDoNotImportFriendly`` sweeps
every pipeline-stage module and fails if one of them imports this one). This
is not an opt-in in the ``enhancements_uiops/`` sense -- there is no
behaviour to turn on, only a friendlier view of behaviour that already
happened -- so it ships in the port rather than in ``enhancements_uiops/``.

**Why a separate module, and not `readers/spec.py`/`reject.py`/
`readers/mask_csv.py` themselves, and not `uiops`.**

1. Keeping the wrappers physically apart from the raw functions they re-view
   makes "the pipeline never imports the friendly module" a real, swept
   property rather than a promise about code sitting next to what it wraps.
   A stray ``from .reject import touching_edge_flag`` inside ``imgproc.py``
   would be one refactor away from pulling a friendly view onto the
   reproduction path if this lived inside ``reject.py`` itself.
2. ``uiops`` dispatches between the v3.1.4 and v3.5 *engines* and asserts it
   "contains no arithmetic" (``tests/test_uiops_selector.py``). The four
   contracts here are v3.1.4-specific findings about *this* engine's raw
   output shape -- which engine to run is a different question -- so a
   re-view of one engine's internals does not belong there.

**The four contracts, each cited to the
regression test that pins the raw behaviour this module only re-views:**

1. :func:`all_record_headers` -- ``readers.spec.iter_record_windows`` yields
   *n-1* windows for a file of *n* records (the last record is never a
   primary). Test pinning the raw contract:
   ``test_spec_reader.py::TestTwoRecordWindow::test_final_record_is_never_a_primary``.
2. :func:`touching_edge_flag` / :class:`TouchingEdge` --
   the earlier translation's reject result carries a ``touching_edge`` field that takes
   the numeric ``0`` or the characters ``"0"``/``"t"``. Test pinning the raw
   contract:
   ``test_reject.py::TestTouchingEdgeIsTriState::test_no_slices_returns_the_numeric_initialiser``.
3. :data:`load_mask_csv` / :data:`MaskRecord` -- re-exported, not
   reimplemented: ``readers.mask_csv.load_mask_csv`` already parses the
   terminator-less ``.MK.csv`` into ordinary records; it is named here only
   so a reader who starts at this module finds it. Test pinning the raw
   contract:
   ``test_spec_reader.py::TestHousekeepingPackets::test_mask_records_have_no_line_terminator``.
4. Every public integer index this port exposes is MATLAB's own 1-based
   convention, stated once rather than at each of the dozens of call sites
   that already say so inline (``docs/09-conventions.md``,
   "Every public index is MATLAB 1-based" -- ``matlab_compat.to0``/``to1``
   are the only place the boundary is crossed). There is no wrapper
   function for this one: the convention already holds, so the deliverable
   is the one central statement plus
   ``tests/test_friendly.py::TestOneBasedConventionIsDocumented``'s sweep of
   the source tree, not new code.
"""

from __future__ import annotations

import enum
import os

import numpy as np

from arrayprobe_uiops.spec_core import (
    HEADER_WORDS,
    RECORD_BYTES,
    RECORD_WORDS,
    RecordHeader,
    iter_record_windows,
)

from .readers.mask_csv import MaskRecord, load_mask_csv

__all__ = [
    "all_record_headers",
    "TouchingEdge",
    "touching_edge_flag",
    "load_mask_csv",
    "MaskRecord",
]


# --------------------------------------------------------------------------
# Contract 1: iter_record_windows yields n-1 windows
# --------------------------------------------------------------------------


def all_record_headers(path: str | os.PathLike) -> list[RecordHeader]:
    """Every record's header, in file order -- *n* headers for *n* records.

    The earlier translation's record-window iterator (kept in the development
    repository) reproduces
    ``read_binary_SPEC.m``'s raw decode loop exactly: the loop reads records
    *N* and *N+1* as a pair, so for a file of two or more records the very
    last record is never fed through it as a primary (preserved bug,
    the v3.1.4 SPEC reader's module docstring, point 2; regression test
    ``test_spec_reader.py::TestTwoRecordWindow::test_final_record_is_never_a_primary``).
    A file of *n* >= 2 records therefore yields *n-1* windows from that
    function, and the header of record *n-1* (0-based) never appears in its
    output. (A one-record file is the degenerate case: with no second
    record to pair against, that lone record already comes back as a single
    short window -- see
    ``test_spec_reader.py::TestTwoRecordWindow::test_single_record_file_yields_one_short_window``
    -- so there is nothing left for this function to add there.)

    A caller who wants "every record that exists in this file", rather than
    "every record MATLAB's pairwise scan reached", should not have to
    rediscover that gap. This function re-plays the same *n-1* windows
    unchanged -- one call to the earlier translation's record-window iterator,
    nothing reimplemented -- and appends the one header that function
    structurally cannot produce: the last record's own eight timestamp
    words, read directly with the same :func:`numpy.memmap` shape the raw
    function uses. No window is built for it (matching MATLAB: that record
    was never fed through the two-record decode that produces particles),
    so this adds a header, never a particle.

    Always ``len(all_record_headers(path)) == n_records`` (whole records), and
    for *n* >= 2 whole records with nothing after them,
    ``all_record_headers(path) == [h for h, _ in iter_record_windows(path)]
    + [<last record's header>]`` -- the identity
    ``tests/test_friendly.py::TestAllRecordHeaders`` checks.
    """
    n_records, tail = divmod(os.path.getsize(path), RECORD_BYTES)
    if n_records == 0:
        # No whole record exists. (The decoder still builds a window from a
        # partial one, and raises where MATLAB dies on it; listing headers
        # has no reason to.)
        return []
    headers = [header for header, _ in iter_record_windows(path)]
    # With a partial record after the last whole one, the scan already made
    # that last record a primary (``iter_record_windows``), so its header is in
    # ``headers``; the partial record itself is not a record.
    if n_records >= 2 and not tail:
        words = np.memmap(path, dtype="<u2", mode="r", shape=(n_records, RECORD_WORDS))
        last = words[n_records - 1, :HEADER_WORDS]
        headers.append(RecordHeader(*(int(v) for v in last)))
    return headers


# --------------------------------------------------------------------------
# Contract 2: RejectResult.touching_edge is a tri-state {0, "0", "t"}
# --------------------------------------------------------------------------


class TouchingEdge(enum.Enum):
    """The three values ``imgProc_sm.m:897``'s ``touching_edge - '0'`` writes.

    Member values are the **written** integers -- what a ``touching_edge``
    variable in a processed netCDF file actually holds, so
    ``TouchingEdge(nc_value)`` reads one straight back. See
    :func:`touching_edge_flag` for the raw
    raw ``RejectResult`` field (the earlier translation's reject result, which is not part of
    this package) these come from, which is
    a different, un-subtracted domain.
    """

    #: The zero-slice path (``calculate_reject_unified.m:108``'s numeric
    #: initialiser, never overwritten because the function returns before
    #: :108-216 runs). Raw ``RejectResult.touching_edge`` field: the int ``0``.
    NO_SLICES = -48
    #: The particle's shadow reaches neither diode 1 nor the last diode. Raw field: the str ``"0"``.
    CONTAINED = 0
    #: The particle's shadow reaches diode 1 or the last diode. Raw field: the str ``"t"``.
    TOUCHING = 68


def touching_edge_flag(raw_field: object) -> TouchingEdge:
    """The v3.1.4 reject result's raw ``touching_edge`` -> :class:`TouchingEdge`.

    ``calculate_reject_unified.m:108`` initialises ``touching_edge``
    numerically and only ``:213-216`` makes it a character, so
    the reject result's ``touching_edge`` field is a
    genuine three-value union rather than one Python type: the int ``0``
    (no slices at all -- the branch returns before the character
    assignment; regression test
    ``test_reject.py::TestTouchingEdgeIsTriState::test_no_slices_returns_the_numeric_initialiser``),
    or the one-character strings ``"0"`` (contained) and ``"t"`` (touching
    diode 1 or the last diode; ``test_contained_and_touching_particles_return_characters``).

    This maps that raw field onto the same ``{-48, 0, 68}`` domain
    ``imgProc_sm.m:897``'s ``touching_edge - '0'`` writes to the product
    file (``test_the_three_values_imgproc_would_write``), losslessly and
    without changing ``RejectResult`` itself -- the raw field is untouched,
    as this module promises.

    Raises :class:`ValueError` on anything outside the three accepted raw
    values, deliberately: a fourth value would mean the raw contract this
    wraps has changed underneath it, not that the caller should guess what
    it means.
    """
    if isinstance(raw_field, str):
        if raw_field in ("0", "t"):
            return TouchingEdge(ord(raw_field) - ord("0"))
        raise ValueError(
            f"not a touching_edge character RejectResult ever carries: {raw_field!r}")
    if isinstance(raw_field, int) and not isinstance(raw_field, bool) and raw_field == 0:
        return TouchingEdge.NO_SLICES
    raise ValueError(
        f"not a touching_edge value RejectResult ever carries (expected the int 0, "
        f"or the str '0' or 't'): {raw_field!r}")
