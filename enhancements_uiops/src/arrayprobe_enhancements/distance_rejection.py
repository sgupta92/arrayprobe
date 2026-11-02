# SPDX-License-Identifier: BSD-3-Clause
"""Inter-particle *distance* rejection, as an alternative to a fixed time threshold.

Korolev & Field 2015, *AMT* 8, 761-777, doi:10.5194/amt-8-761-2015 -- Sect. 4, pp. 765-766.
**Read directly from the published open-access PDF on 2026-09-10**, which resolved the
dimensional question this module previously carried unanswered; see "The paper's printed
equation is wrong" below, and ``enhancements_uiops/docs/distance_rejection_design.md`` for the full
finding. Nothing in this module's arithmetic changed as a result -- it was already correct.

The port's own shattering test (``sizeDist.m:894-912``/``:1155-1173``, ported in
``arrayprobe.sizedist._reaccept_shattered``) flags two particles as one shattering event when
their inter-arrival TIME falls below a fitted threshold ``ia_thresh``. Korolev & Field's point:
a fixed time threshold implicitly assumes a fixed true airspeed. At high TAS the same physical
separation between fragments passes in less time, so a fixed ``ia_thresh`` over-rejects at high
TAS and under-rejects at low TAS -- "the TAS drift of a fixed time threshold" the paper's own
framing (per the verified citation above) names directly.

**What this module does**: converts a time-domain inter-arrival threshold into a distance
threshold using TAS, ``Δx = Δt · u`` (``u`` = true airspeed), and re-tests each inter-arrival
against that distance instead of against time. Additive only -- it does not touch
``arrayprobe.sizedist`` or its own time-based decision; a caller applies this after the fact,
the same way ``outoffocus.py`` applies its correction to data the port already wrote.

**The paper's printed equation is wrong, and this module deliberately does not reproduce it.**
Korolev & Field 2015 prints the time-to-distance conversion as a *division* by airspeed, twice:
p. 765 ("the inter-particle distance ``Δx = Δt/u`` will be used instead of ``Δt``") and p. 766
("``χ* = τ*/u`` will be used instead of ``φ(Δt)`` and ``τ*``, respectively"). Read literally
that is dimensionally impossible -- a time divided by a speed has units of time²/length, not
length. The intended operation is **multiplication**, ``Δx = Δt·u``, which is what this module
implements. Three independent confirmations, all from the paper itself:

1. **Dimensions.** ``Δx`` is introduced as a distance and plotted in metres; ``Δt/u`` is not a
   distance under any reading of ``u``, which p. 764 defines unambiguously as "the sampling
   speed" in ``τ = 1/nSu`` (that expression is itself only dimensionally consistent -- seconds --
   with ``u`` a speed).
2. **The paper writes the same relation correctly in the inverse direction**, p. 764:
   ``Δt_sh = L_sh/u`` is "the duration of the shattering event", where ``L_sh`` is explicitly
   "the spatial length of the shattering event along the flight direction". So dividing by ``u``
   converts distance → time; the conversion time → distance must therefore multiply.
3. **The paper's own Fig. 5 axes**, p. 766: inter-particle distance is plotted over roughly
   10⁻³-10² m, with ``χ*`` drawn on the same axis. For OAP inter-arrival times (~10⁻⁶-10⁻² s) at
   aircraft speed (~100 m/s), ``Δt·u`` lands at ~10⁻⁴-10⁰ m -- on the plotted scale. ``Δt/u``
   would land at ~10⁻⁸-10⁻⁴ m, off it entirely.

``χ*`` is simply the cut-off *distance*: the distance analogue of the cut-off time ``τ*``, which
is exactly what :func:`threshold_to_distance` computes. **Do not "correct" this module to match
the printed form** -- ``tests/test_distance_rejection.py`` pins the direction against the
magnitudes of the paper's own Fig. 5 so that such a change fails rather than silently shifting
every distance by eight orders of magnitude.
"""
from __future__ import annotations

import numpy as np

__all__ = ["distance_from_time", "threshold_to_distance", "is_shattered_by_distance"]


def distance_from_time(int_arr: np.ndarray, tas: np.ndarray) -> np.ndarray:
    """Inter-particle distance, ``Δx = Δt · u``, elementwise.

    ``int_arr`` is an inter-arrival TIME array (seconds) in the same shape ``sizeDist.m``
    computes it in (``arrayprobe.sizedist``'s own ``int_arr``); ``tas`` is true airspeed
    (m/s) at the same indices -- EACH particle's own local TAS, which is the quantity that
    makes this differ from a time-only test as airspeed varies. Neither array's shape is
    asserted beyond what NumPy broadcasting allows, since callers read both from the same
    proc/TAS-sidecar source and are expected to already agree.
    """
    return np.asarray(int_arr, dtype=float) * np.asarray(tas, dtype=float)


def threshold_to_distance(ia_thresh: float, reference_tas: float) -> float:
    """Convert the port's fitted TIME threshold to a fixed DISTANCE threshold, once.

    Calibrated at ``reference_tas`` (a single true-airspeed value -- typically the mean
    TAS of the block ``ia_thresh`` was itself fitted over) and then held FIXED: this is
    the whole point of the distance form. A fixed time threshold implicitly means a
    variable physical separation as TAS drifts within a flight; converting once to a
    distance and holding IT fixed instead means a fragment pair separated by the same
    physical distance is flagged consistently regardless of how fast the aircraft was
    going when it happened -- "removing the TAS drift of a fixed Δt" (Korolev & Field
    2015, cited in this module's docstring).
    """
    return float(ia_thresh) * float(reference_tas)


def is_shattered_by_distance(int_arr: np.ndarray, tas: np.ndarray,
                             threshold_distance: float) -> np.ndarray:
    """Whether each inter-arrival is "close" by a FIXED distance threshold.

    ``threshold_distance`` comes from :func:`threshold_to_distance`, calibrated once at
    a reference TAS; ``tas`` here is each particle's own LOCAL airspeed, so the
    comparison genuinely diverges from the time-only test (``int_arr < ia_thresh``,
    ``sizeDist.m:905`` et seq.) whenever local TAS differs from the reference value it
    was calibrated at -- exactly the case a TAS-drifting flight leg produces, and the
    case a fixed time threshold cannot adapt to.
    """
    distance = distance_from_time(int_arr, tas)
    return distance < float(threshold_distance)
