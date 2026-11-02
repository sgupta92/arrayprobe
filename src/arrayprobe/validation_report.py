# SPDX-License-Identifier: BSD-3-Clause
"""Typed results for comparing a port output against a reference product.

The acceptance gate (S4c's product against the archived product)
prints its result; nothing
returned a value a caller could hold onto, so a notebook wanting to plot
per-bin agreement or list the seconds that disagree had to re-parse stdout.
This module computes the same two-denominator, used-bin comparison and
returns dataclasses instead -- same conventions, same used-bin cut, same
"always report both denominators" rule (a `both-present` figure and a
`non-zero` figure have both been quoted under the same headline before, and
they are not comparable).

Deliberately duplicates the gate's small helpers (``_seconds_of``,
``_oriented``) rather than importing them: this is the core package, and the
core package does not depend on the scripts around it -- they may import
from the core package, not the reverse. The gate itself is untouched by
this module and keeps
printing exactly as
it always has.
"""
from __future__ import annotations

from dataclasses import dataclass

import netCDF4
import numpy as np

#: The 2D-S's first five bins sit at the diode-pitch noise floor and are
#: excluded from every headline this project publishes -- see
#: ``docs/11-glossary.md``.
UNUSED_BINS = 5

#: The two variables ``validate_combined_product.py`` compares.
COMPARED_VARIABLES = ("Size Distribution cm-3", "Counts")


def _seconds_of(ds) -> np.ndarray:
    """``Time Vector`` is a MATLAB datenum; the shared key is the whole second."""
    tv = np.asarray(ds.variables["Time Vector"][:], float)
    return np.round((tv - np.floor(tv[0])) * 86400.0).astype(np.int64)


def _oriented(ds, name: str, n_time: int) -> np.ndarray:
    """Return the variable as ``(bins, time)``, whichever way it is stored."""
    a = np.asarray(ds.variables[name][:], float)
    if a.ndim != 2:
        return a
    return a if a.shape[1] == n_time else a.T


@dataclass(frozen=True)
class CellAgreement:
    """Agreement for one variable, one bin scope ("all bins" or "used bins").

    Two denominators, always both, for the reason ``validate_combined_product.py``
    exists: ``both_present`` counts every cell neither side left as fill,
    zero-equals-zero included; ``non_zero`` (the headline figure this project
    publishes) excludes cells where both sides agree only because neither saw
    a particle.
    """
    variable: str
    scope: str
    both_present_n: int
    both_present_agree: int
    both_zero_n: int
    non_zero_n: int
    non_zero_agree: int

    @property
    def both_present_pct(self) -> float:
        """Agreement over every cell neither side left as fill, zero-equals-zero
        included -- the looser of the two denominators."""
        return (100.0 * self.both_present_agree / self.both_present_n
                if self.both_present_n else float("nan"))

    @property
    def non_zero_pct(self) -> float:
        """Agreement excluding cells where both sides agree only because
        neither recorded a particle -- the headline figure this project
        publishes."""
        return (100.0 * self.non_zero_agree / self.non_zero_n
                if self.non_zero_n else float("nan"))


@dataclass(frozen=True)
class ProductComparisonReport:
    """The result of :func:`compare_to_product`."""
    ours_path: str
    ref_path: str
    ours_seconds: int
    ref_seconds: int
    shared_seconds: int
    uncovered_ref_seconds: int
    uncovered_ours_seconds: int
    cells: tuple[CellAgreement, ...]
    #: Shared seconds holding at least one differing used-bin non-zero cell,
    #: pooled over every compared variable -- plottable as a residual-over-time
    #: view; empty when every used-bin non-zero cell agrees.
    residual_seconds: tuple[int, ...]

    def cell(self, variable: str, scope: str) -> CellAgreement:
        """The :class:`CellAgreement` for one compared variable and bin scope
        (``"all bins"`` or ``"used bins N-128"``); raises :class:`KeyError` if
        that combination was not computed (the variable was absent from one
        side)."""
        for c in self.cells:
            if c.variable == variable and c.scope == scope:
                return c
        raise KeyError((variable, scope))


def compare_to_product(our_path: str, ref_path: str,
                        drop: int = UNUSED_BINS) -> ProductComparisonReport:
    """The same comparison the acceptance gate prints, as
    typed results a caller can hold onto -- e.g. from a notebook::

        report = validation_report.compare_to_product(ours, theirs)
        report.cell("Counts", "used bins 6-128").non_zero_pct
        report.residual_seconds
    """
    ours = netCDF4.Dataset(our_path)
    ref = netCDF4.Dataset(ref_path)
    try:
        ours_s, ref_s = _seconds_of(ours), _seconds_of(ref)
        shared, oi, ri = np.intersect1d(ours_s, ref_s, return_indices=True)

        cells = []
        residual_mask = np.zeros(len(shared), dtype=bool)
        for name in COMPARED_VARIABLES:
            if name not in ours.variables or name not in ref.variables:
                continue
            a = _oriented(ours, name, len(ours_s))[:, oi]
            b = _oriented(ref, name, len(ref_s))[:, ri]

            for lo, label in ((0, "all bins"), (drop, f"used bins {drop + 1}-128")):
                x, y = a[lo:], b[lo:]
                present = ~np.isnan(x) & ~np.isnan(y)
                both_zero = present & (x == 0) & (y == 0)
                eq = x == y

                n_p, e_p = int(present.sum()), int((eq & present).sum())
                strict = present & ~both_zero
                n_s, e_s = int(strict.sum()), int((eq & strict).sum())
                cells.append(CellAgreement(
                    variable=name, scope=label,
                    both_present_n=n_p, both_present_agree=e_p,
                    both_zero_n=int(both_zero.sum()),
                    non_zero_n=n_s, non_zero_agree=e_s,
                ))
                if lo == drop:
                    differing = strict & ~eq
                    residual_mask |= differing.any(axis=0)

        return ProductComparisonReport(
            ours_path=str(our_path), ref_path=str(ref_path),
            ours_seconds=len(ours_s), ref_seconds=len(ref_s),
            shared_seconds=len(shared),
            uncovered_ref_seconds=len(ref_s) - len(shared),
            uncovered_ours_seconds=len(ours_s) - len(shared),
            cells=tuple(cells),
            residual_seconds=tuple(int(s) for s in shared[residual_mask]),
        )
    finally:
        ours.close()
        ref.close()
