# SPDX-License-Identifier: BSD-3-Clause
"""The production fork's ``combine_sizedist.m``, run over v3.5 ``sd`` output -- BORROWED, OPT-IN.

No stock UIOOPS release, v3.5 included, ships a combine step: ``combine_sizedist.m``
is in neither vendored tree (measured building ``uiops.CATALOGUE`` -- see
``uiops/__init__.py``'s ``"combine"`` entry).
It survives only as the ORACLES
production fork, held as the ORACLES-variant ``combine_sizedist.m`` (delivered 2026-08-20)
and ported for v3.1.4 as :mod:`arrayprobe.combine`.

The author's decision (2026-09-13): v3.5 does not stop at ``sd``.
It gets the ORACLES fork's combine too, **labelled as borrowed and opt-in**
("an option needs to be there for opt in" -- default OFF). This module adds
**no arithmetic of its own** (``tests/test_v35_combine.py``'s
``ReuseNotCopy`` group asserts that by walking its AST): it guards the input
schema, then delegates to :func:`arrayprobe.combine.combine_sizedist` --
reused, never copied -- and records the borrowing beside the product.

**Why the v3.1.4 combine can be pointed at v3.5 output at all.** It reads
exactly 11 variables, all by NAME (``arrayprobe.combine._READ_VARS``), and
reads no global attribute. Measured against the two Octave-written goldens
(``tests/data/v35_sizedist/main.nc``, v3.5; ``tests/data/s4_sizedist_octave_golden.nc``,
v3.1.4): every one of those 11 names resolves to the same on-disk variable
INDEX in both files (:func:`check_sd_schema` asserts exactly this), and the
one candidate for a silent mis-read -- whether v3.5's ``mean_area_ratio``
(the fixed area-ratio double scaling: v3.5 writes it WITH the transpose its
sibling variables already carry, see ``arrayprobe_uiops/sizedist.py``'s
``NOT_TRANSPOSED``-adjacent comment and the earlier translation's
``NOT_TRANSPOSED`` set) -- lands on disk with a different dimension order
than v3.1.4's, measured **false**: both goldens declare ``mean_area_ratio``
with identical on-disk dims (``Time``, ``CIPcorrlen``), so
``ncio.get_var`` returns it in the identical MATLAB shape ``(bin, time)`` for
both engines, which is exactly what ``arrayprobe.combine``'s own ``.T`` step
already expects. **No adapter arithmetic is needed**; this module is a guard,
a label and a delegation, nothing else.

**Validation, stated honestly.** Layer 2 at best, and it is *identity*, not
an oracle: the borrowed combine on v3.5 output can only be shown
byte-identical to :func:`arrayprobe.combine.combine_sizedist` on the
identical inputs, because it is the same function. No archived product was
ever combined from v3.5 ``sd`` files, so no layer-1 claim exists or can
exist for this module.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from arrayprobe_uiops import combine_fork as _fork_combine

from . import ncio

__all__ = [
    "BORROWED_FROM",
    "CALL_STAMP",
    "BorrowedCombineNotEnabled",
    "SdSchemaMismatch",
    "check_sd_schema",
    "combine_sizedist",
]

#: One line, checkable without reading source: what this delegates to and why.
BORROWED_FROM = (
    "combine_sizedist.m from a campaign variant of UIOOPS "
    "(in no stock UIOOPS release, v3.5 included); one translation, "
    "reused here, never copied"
)

#: The one-line ``.call`` sidecar stamp -- written beside the product so the
#: borrowing is recorded even when this is called from Python directly
#: rather than through ``scripts/run_flight.py`` (which has its own stamping
#: convention for the v3.1.4 engine; see ``run_flight.py``'s
#: ``call_path``/``write_stamp``, mirrored, not imported, below).
CALL_STAMP = (
    "engine=3.5 combine=borrowed-oracles-fork:combine_sizedist.m "
    "opt_in=borrowed_combine=True"
)


class BorrowedCombineNotEnabled(RuntimeError):
    """Raised when :func:`combine_sizedist` is called without opting in.

    Default OFF is the point: nothing about v3.5's own output is
    touched unless a caller names ``borrowed_combine=True`` explicitly.
    """


class SdSchemaMismatch(ValueError):
    """An input file does not carry the 11 variables ``combine_sizedist.m``
    reads at the indices it hard-codes -- see :func:`check_sd_schema`."""


def check_sd_schema(path: Any) -> None:
    """Assert ``path`` carries every variable :data:`arrayprobe.combine.MATLAB_VARID`
    names, each at the on-disk index the MATLAB source reads by number.

    ``arrayprobe.combine`` itself reads by NAME (the combine stage's design rule:
    "read by name, assert by index") and trusts a v3.1.4-shaped ``sd`` file to
    have named things consistently with that hard-coded index table. A v3.5
    file is a different writer; this is that same assertion, run explicitly
    against v3.5 output before delegating, rather than assumed.
    """
    ds = ncio.open(str(path), "nowrite")
    try:
        for name, expected_idx in _fork_combine.MATLAB_VARID.items():
            try:
                got_idx = ncio.inq_var_id(ds, name)
            except KeyError:
                raise SdSchemaMismatch(
                    f"{path}: combine_sizedist.m reads a variable named "
                    f"{name!r} (its index {expected_idx}), but this file has "
                    f"none"
                ) from None
            if got_idx != expected_idx:
                raise SdSchemaMismatch(
                    f"{path}: {name!r} is variable {got_idx} here, but "
                    f"combine_sizedist.m reads index {expected_idx} for it -- "
                    f"the fork combine would silently read the wrong column"
                )
    finally:
        ncio.close(ds)


def _write_call_sidecar(outfile: Path, sd_files: Any) -> None:
    """Mirrors ``scripts/run_flight.py``'s ``call_path``/``write_stamp`` shape
    (partial-write-then-rename) without importing ``tools`` -- this module
    must be usable with no dependency on the CLI driver.
    """
    names = ",".join(Path(p).name for p in sd_files)
    content = f"{CALL_STAMP}\ninputs={names}\n"
    sidecar = outfile.with_name(f"{outfile.name}.call")
    partial = sidecar.with_name(f"{sidecar.name}.partial")
    partial.write_text(content, encoding="utf-8")
    os.replace(partial, sidecar)


def combine_sizedist(
    sd_files: Any,
    outfile: Any,
    *,
    flight_date: Any,
    summary_time: Any,
    borrowed_combine: bool = False,
    current_year: Any = None,
    creation_time: Any = None,
) -> Any:
    """The production fork's ``combine_sizedist.m``, over v3.5 ``sd`` files.

    Same contract as :func:`arrayprobe.combine.combine_sizedist` -- this
    calls that function unmodified, after guarding the input schema -- plus
    one addition:

    Parameters
    ----------
    borrowed_combine : bool
        Must be ``True`` or this raises :class:`BorrowedCombineNotEnabled`
        and writes nothing. Default OFF: nothing about a v3.5
        run is touched unless a caller opts in explicitly.

    Raises
    ------
    BorrowedCombineNotEnabled
        ``borrowed_combine`` is not ``True``.
    SdSchemaMismatch
        Some input in ``sd_files`` does not carry the 11 variables the fork
        combine reads at the indices it hard-codes -- see
        :func:`check_sd_schema`.

    Returns the path written, and stamps a ``<outfile>.call`` sidecar
    recording the borrowing (:data:`CALL_STAMP`) and the input file names.
    """
    if not borrowed_combine:
        raise BorrowedCombineNotEnabled(
            "arrayprobe_uiops.combine.combine_sizedist refuses to run unless "
            "borrowed_combine=True is passed explicitly (the "
            "variant's combine_sizedist.m is opt-in for v3.5, default "
            f"OFF). {BORROWED_FROM}"
        )
    for p in sd_files:
        check_sd_schema(p)
    out = _fork_combine.combine_sizedist(
        sd_files,
        outfile,
        flight_date=flight_date,
        summary_time=summary_time,
        current_year=current_year,
        creation_time=creation_time,
    )
    _write_call_sidecar(Path(outfile), sd_files)
    return out
