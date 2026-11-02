# SPDX-License-Identifier: BSD-3-Clause
"""Stuck-diode masking shared by both engines: the fork's rule and its re-illumination.

The ORACLES production chain found stuck diodes with ``find_shadow_diodes.m`` (a
dissertation Appendix-B extraction) and re-illuminated them in the nine-argument
``imgProc_sm`` (extraction ``:286-292``)::

    c(:,shadow_diode)='1';

This module holds the parts both engines use: the stuck-diode rule
(:func:`stuck_diodes`, ``find_shadow_diodes.m:66-97``), the mask record
(:class:`ShadowDiodeMask`) and the re-illumination (:func:`reilluminate`).
The earlier translation's ``arrayprobe.masks`` imports them and keeps the file-level
wrapper (``bin_stats`` reading, ``.mat`` I/O, the nine-argument lookup).

It imports only the standard library and NumPy, because ``import arrayprobe``
loads it (``tests/test_lazy_numba_and_v35_import.py``'s ``V35_SHARED``) and the
v3.5 engine must not import the v3.1.4 package (``tests/test_no_dependence_on_v314.py``).
The two MATLAB integer semantics the rule needs -- ``int32`` of a double and
``find`` -- are therefore written here for the non-negative operands the rule
produces, and the rule is asserted against the fork's file run under Octave
(``tests/test_find_shadow_diodes.py``, golden
``tests/data/find_shadow_diodes_octave_golden.json``).

Line numbers are those of the promoted ``find_shadow_diodes.m`` (raw extraction
``archive/staging_variant_raw/find_shadow_diodes.m.raw.txt`` = promoted + 1).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import numpy as np
import numpy.typing as npt

__all__ = [
    "STUCK_FRACTION",
    "HIGH_FRACTION",
    "ShadowDiodeMask",
    "StuckDiodeRule",
    "stuck_diodes",
    "reilluminate",
]

#: ``:94`` and ``:97`` -- a diode is stuck below this fraction of the mean or max.
#: (The recovered ORACLES masks also exist at 75%, ``S3o`` §3; the code says 0.80.)
STUCK_FRACTION = 0.80

#: ``:66`` -- a diode above this fraction of the mean was masked in flight.
HIGH_FRACTION = 1.2

#: ``'1'`` marks a lit diode in the char image (``imgProc_sm.m:266`` inverts
#: through ``65535 - data``); the same character as ``arrayprobe.particle.LIT``.
_LIT_ORD = ord("1")

#: What MATLAB pads a widened char array with (``char(0)``), measured in Octave:
#: ``c=['0101';'1010']; c(:,[2 6])='1'`` gives column 5 the value 0.
_CHAR_PAD = 0

_INT32 = np.iinfo(np.int32)


def _int32(x: npt.ArrayLike) -> np.ndarray:
    """MATLAB ``int32(x)`` for a double: half away from zero, NaN to 0, saturating.

    ``x - floor(x)`` is exact for every finite double, so the half is tested
    without a rounding of its own (the defect ``floor(x + 0.5)`` carries).
    """
    a = np.asarray(x, dtype=np.float64)
    m = np.abs(a)
    f = np.floor(m)
    with np.errstate(invalid="ignore"):
        r = np.sign(a) * (f + (m - f >= 0.5))
    r = np.where(np.isnan(r), 0.0, r)
    return np.clip(r, _INT32.min, _INT32.max).astype(np.int32)


def _find(condition: np.ndarray) -> np.ndarray:
    """MATLAB ``find`` on a vector: 1-based indices, float64 (the class MATLAB stores)."""
    return (np.flatnonzero(np.asarray(condition).reshape(-1)) + 1).astype(np.float64)


def _mean(x: np.ndarray) -> float:
    """MATLAB ``mean`` of an integer array: double, ``sum(double(x))/n``, summed in
    order as MATLAB does (``np.cumsum``; NumPy's ``sum`` is pairwise)."""
    if not x.size:
        return float("nan")
    return float(np.cumsum(x.astype(np.float64))[-1]) / x.size


def _replace_high_counts(a: np.ndarray, idx: np.ndarray,
                         mean: Callable[[np.ndarray], float]) -> np.ndarray:
    """``:68-69``: ``a(ill_diode)=NaN; a(ill_diode)=nanmean(a);`` on int32 ``a``.

    int32(NaN) is 0, so the first line stores zeros and ``nanmean`` then has no
    NaN to skip: the replacement is the mean *including* those zeros.
    """
    a = a.copy()
    a[idx] = _int32(np.nan)          # :68 -- stores 0
    a[idx] = _int32(mean(a))         # :69 -- nanmean == mean here
    return a


class StuckDiodeRule(NamedTuple):
    """What ``find_shadow_diodes.m:66-97`` computes from one ``bin_stats`` vector."""

    shadow_diode: np.ndarray
    """1-based stuck diodes, float64, sorted (``sort(find(...))``, ``:94-98``)."""

    a: np.ndarray
    """The counts as saved: int32, after ``:66-69``'s high-count replacement."""

    ill_diode: np.ndarray
    """1-based diodes over ``1.2*mean(a)`` (``:66``), float64; usually empty."""

    branch: str
    """``"mean"`` when ``ill_diode`` was non-empty (``:94``), else ``"max"`` (``:97``)."""

    threshold: float
    """``0.80*mean(a)`` (double) or ``0.80*max(a)`` (int32, as a float)."""


def stuck_diodes(bin_stats: npt.ArrayLike) -> StuckDiodeRule:
    """The fork's stuck-diode rule on **lit** counts, ``find_shadow_diodes.m:66-97``.

    * ``:66`` -- diodes above ``1.2 x mean`` (masked in flight: lit on every
      slice) are replaced by ``nanmean(a)`` (``:68-69``), and a diode is stuck
      below ``0.80 x mean`` of the replaced array (``:94``);
    * otherwise a diode is stuck below ``0.80 x max`` (``:97``), int32.

    ``a(ill_diode)=NaN`` stores 0 on int32 ``a``, so ``nanmean`` averages those
    zeros in: the replacement is diluted by ``len(ill_diode)/n``.  Reproduced.

    ``bin_stats`` must count lit slices (the production fork's ``imgProc_sm.m:387-388``);
    a shadow count turns the rule upside down.  A non-positive mean raises
    ``ValueError``: ``:55``'s ``ylim([0 1.5*nanmean(a)])`` stops MATLAB first.
    """
    a = np.asarray(bin_stats).astype(np.int32).reshape(-1)
    if not 1.5 * _mean(a) > 0:
        raise ValueError(
            "find_shadow_diodes.m:55 ylim([0 1.5*nanmean(a)]) is not increasing: "
            f"bin_stats is all zero or empty (n={a.size}); MATLAB saves nothing")

    ill = _find(a.astype(np.float64) > HIGH_FRACTION * _mean(a))     # :66
    if ill.size:
        a = _replace_high_counts(a, ill.astype(np.int64) - 1, _mean)
        threshold = STUCK_FRACTION * _mean(a)                        # :94
        diode = _find(a.astype(np.float64) < threshold)
        branch = "mean"
    else:
        threshold_i = _int32(STUCK_FRACTION * float(a.max()))       # :97, int32
        threshold = float(threshold_i)
        diode = _find(a < threshold_i)
        branch = "max"
    return StuckDiodeRule(shadow_diode=np.sort(diode), a=a, ill_diode=ill,
                          branch=branch, threshold=threshold)


@dataclass(frozen=True)
class ShadowDiodeMask:
    """The ``shadow_diode`` list from one ``diode.<date><time>[.<or>].mat``."""

    diodes: np.ndarray
    """1-based diode numbers, in file order, as float64 -- the class MATLAB
    stores them in.  Kept unrounded so that a non-integer entry is caught at use
    rather than silently floored here."""

    date: str | None
    """The ``date`` variable, ``'YYMMDD'``.  ``None`` if the file lacks it."""

    time: str | None
    """The ``time`` variable, ``'HHMMSS'``."""

    source: Path | None
    """Where it was read from, for provenance in error messages."""

    header: str = ""
    """The MAT-file's own creation stamp.  For the ORACLES masks this is what
    distinguishes 2017 Linux output of record from a later regeneration."""

    def __len__(self) -> int:
        return int(self.diodes.size)

    def __bool__(self) -> bool:
        # Deliberately mirrors MATLAB's `isempty(shadow_diode)==0` test rather
        # than "a mask object exists": an empty mask is a real, common outcome
        # and must behave as no masking at all.
        return bool(self.diodes.size)

    def matches(self, date: str, time: str) -> bool:
        """Whether the file's own stamp agrees with the flight it is being used for.

        MATLAB never checks this -- it locates the file by name and trusts it.
        The check is available so a caller can refuse a mask from the wrong
        file, which is worth having given the ORACLES masks were kept in
        threshold-named directories with several vintages side by side.
        """
        return self.date == date and self.time == time


def reilluminate(c: np.ndarray, diodes: Sequence[int] | np.ndarray | ShadowDiodeMask, *,
                 index_error: type[Exception] = IndexError
                 ) -> np.ndarray:
    """``c(:,shadow_diode)='1'`` -- set whole diode columns to lit.

    ``c`` is the ``(nslices, ndiodes)`` uint8 ASCII image.  ``diodes`` is a
    sequence of 1-based diode numbers, or a :class:`ShadowDiodeMask`.

    Two MATLAB behaviours are reproduced rather than tidied:

    * **An empty list is a no-op.**  ``c(:,[])='1'`` changes nothing, which is
      what makes the empty-mask case identical to no mask at all.
    * **An index past the last diode WIDENS the image.**  MATLAB grows the array
      and pads the new columns with ``char(0)``; measured in Octave,
      ``c=['0101';'1010']; c(:,[2 6])='1'`` returns a 2x6 char array whose fifth
      column is 0.  It does *not* error.  ``imgProc_sm.m:272-276`` then finds
      ``size(c,2) ~= diodenum``, prints ``Not equal to doide number`` and
      ``return``\\ s from the whole function -- so a mask with one bad diode
      number ends the run part-way through, leaving a short proc file and no
      error status.  Reproducing the widening is what lets that guard fire here
      too, instead of being pre-empted by an IndexError of our own invention.

    A zero, negative or fractional entry raises ``index_error`` (the earlier
    translation passes its ``MatlabIndexError``), as MATLAB does: *"subscripts must
    be either integers 1 to (2^63)-1 or logicals"*.
    """
    if isinstance(diodes, ShadowDiodeMask):
        diodes = diodes.diodes
    idx = np.asarray(diodes, dtype=np.float64).ravel(order="F")
    if idx.size == 0:
        return c

    bad = idx[(idx < 1) | (idx != np.floor(idx))]
    if bad.size:
        raise index_error(
            f"c(_,{bad[0]:g}): subscripts must be either integers 1 to (2^63)-1 "
            "or logicals -- shadow_diode carries a non-positive or fractional "
            "diode number, which stops MATLAB at imgProc_sm.m:290"
        )

    idx = idx.astype(np.int64)
    need = int(idx.max())
    if need > c.shape[1]:
        pad = np.full((c.shape[0], need - c.shape[1]), _CHAR_PAD, dtype=c.dtype)
        c = np.hstack([c, pad])
    c[:, idx - 1] = _LIT_ORD
    return c
