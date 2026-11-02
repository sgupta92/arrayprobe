# SPDX-License-Identifier: BSD-3-Clause
"""B9 -- pick the crossover dip, not the histogram's global minimum.

**What it corrects.** ``IntArrAnalysis_time.m:170-190`` selects the written
inter-arrival threshold as the bin centre where the *observed* counts are lowest
anywhere inside ``(min(tau_std(1:2)), max(tau_std(1:2)))``::

    newDT = dt(dt<tau1 & dt>tau2);
    [minOriginal, indexOriginal] = min( h(dt<tau1 & dt>tau2) );
    threshhold_ak = newDT(indexOriginal);     % :363 writes this one

Two properties of that window make a global ``min`` the wrong estimator. The
window can span nearly the whole histogram -- when the fit puts ``tau2`` below
the first bin the window is effectively ``(0, tau1)``. And inside a wide window
the observed histogram is not monotonic on either side of the dip: it falls into
the shattering/real crossover, rises through the real-particle mode, then falls
again into a sparse tail. A global ``min`` can therefore land in the tail.

Measured on ``base160906064403`` (49,637 particles, five populations), the
written value is **6.6e-4 to 2.7e-3 s -- 110x to 460x** the 6 microsecond
per-probe default that ``sizeDist.m:874`` falls back to. A threshold that large
classifies most real particles as shattered.

**What this module does.** :func:`crossover_threshold` selects the **first local
minimum** inside the same window -- the crossover dip the algorithm is reaching
for -- instead of the global one. Everything else is untouched: the same
histogram, the same fit, the same window. Only the estimator changes.

:func:`compare` runs both on the same input and returns them side by side, which
is how the effect is meant to be reported: the faithful value, the corrected
value, and the ratio.

**The faithful side is the port's own code**, not a re-derivation. This module
imports ``arrayprobe.intarr_analysis`` and calls it; a test asserts the two agree
element-for-element on real data, so the A/B's two sides come from different
places.

**What this module does NOT claim.**

* **It does not know the right threshold.** The first local minimum is a better
  estimator of a crossover than a global minimum over a wide window, and it is
  what the surrounding code's own comments describe reaching for. It is still an
  estimator. The physically correct threshold for a given probe and cloud is a
  science question this module does not settle.
* **It changes no archived ORACLES product.** The campaign's production call
  names a threshold file that does not exist, so ``sizeDist.m:70`` sets
  ``iaThreshFile = 'NONE'`` and ``:874`` falls back to the per-probe 6
  microsecond default. The written threshold this finding concerns is therefore
  **not** what rejected particles in the products this project validates
  against. It matters wherever a threshold file IS used, which is a
  configuration this project holds no reference product for.
* **It offers no measured downstream consequence**, for the same reason: to
  measure how many particles a corrected threshold accepts or rejects, one needs
  a run that actually consumes the threshold file. That run has no oracle here.
* **The local minimum can be ambiguous.** Where the histogram is flat or noisy
  near the crossover, "first local minimum" is sensitive to binning. The
  function reports how many local minima it found so a caller can see when the
  choice was not clean, rather than returning a number that hides it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from arrayprobe.intarr_analysis import (
    _WIDTH,
    DEFAULT_THRESHOLD,
    HIST_BINS,
    fit_bimodal_intarr,
)

__all__ = ["ThresholdPair", "crossover_threshold", "compare",
           "select_from_window"]


@dataclass(frozen=True)
class ThresholdPair:
    """One population's faithful and corrected thresholds, with the evidence."""

    faithful: float
    corrected: float
    n_local_minima: int
    window: tuple[float, float]
    n_bins_in_window: int

    @property
    def ratio(self) -> float:
        """How many times larger the faithful value is. inf if corrected is 0."""
        return float("inf") if self.corrected == 0 else self.faithful / self.corrected

    @property
    def is_clean(self) -> bool:
        """One unambiguous local minimum inside the window."""
        return self.n_local_minima == 1


def _local_minima(y: np.ndarray) -> np.ndarray:
    """Indices of interior strict local minima, left to right.

    Endpoints are excluded deliberately: a minimum at the window edge is what a
    global ``min`` already finds, and it is the failure mode being corrected.
    """
    if y.size < 3:
        return np.empty(0, dtype=int)
    return np.flatnonzero((y[1:-1] < y[:-2]) & (y[1:-1] <= y[2:])) + 1


def select_from_window(window_centres, window_counts) -> tuple[float, float, int]:
    """The two estimators over an explicit window: ``(faithful, corrected, n_minima)``.

    Separated from the fit so the selection can be tested on the histogram shape
    the finding actually measured, without depending on where a fit happens to
    put the window on synthetic data. On a narrow window the two estimators
    agree -- the global minimum IS the crossover -- and the finding is about the
    wide-window case, which is the one worth being able to construct directly.
    """
    c = np.asarray(window_centres, dtype=float)
    y = np.asarray(window_counts, dtype=float)
    faithful = float(c[int(np.argmin(y))])
    minima = _local_minima(y)
    corrected = float(c[minima[0]]) if minima.size else faithful
    return faithful, corrected, int(minima.size)


def crossover_threshold(counts, *, beta0=None) -> ThresholdPair:
    """Both thresholds for one population's histogram.

    ``counts`` is the raw histogram over :data:`arrayprobe.intarr_analysis.HIST_BINS`
    -- the same input the faithful path takes.
    """
    centres = HIST_BINS[:-1] + np.diff(HIST_BINS) / 2
    h = np.asarray(counts, dtype=float)
    if h.sum() == 0:
        return ThresholdPair(DEFAULT_THRESHOLD, DEFAULT_THRESHOLD, 0, (0.0, 0.0), 0)

    tau = (fit_bimodal_intarr(centres, h, _WIDTH) if beta0 is None
           else fit_bimodal_intarr(centres, h, _WIDTH, beta0=beta0))
    if np.isnan(tau).any():
        return ThresholdPair(DEFAULT_THRESHOLD, DEFAULT_THRESHOLD, 0, (0.0, 0.0), 0)

    hi, lo = float(np.max(tau[:2])), float(np.min(tau[:2]))
    between = (centres < hi) & (centres > lo)
    if not between.any():
        # The faithful path has its own guard here; outside the window there is
        # no crossover to find, so the correction declines rather than invents.
        return ThresholdPair(DEFAULT_THRESHOLD, DEFAULT_THRESHOLD, 0, (lo, hi), 0)

    new_dt, h_win = centres[between], h[between]
    faithful, corrected, n_minima = select_from_window(new_dt, h_win)
    return ThresholdPair(faithful, corrected, n_minima, (lo, hi), int(h_win.size))


def compare(counts_per_population) -> list[ThresholdPair]:
    """:func:`crossover_threshold` for each population's histogram, in order."""
    return [crossover_threshold(c) for c in counts_per_population]
