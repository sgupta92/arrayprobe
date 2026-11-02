# SPDX-License-Identifier: BSD-3-Clause
"""A5 -- apply the midnight ``+240000`` rollover at *every* time decrease, not only the first.

**What it corrects.**  ``sizeDist.m:83-84`` (the TAS-derived ``timehhmmss``) and
``sizeDist.m:544-545`` (the proc file's own per-particle ``Time``) both write the midnight
correction as::

    x(find(diff(x)<0)+1:end) = x(find(diff(x)<0)+1:end) + 240000;

``find`` returns a *vector* of every decrease, but MATLAB's colon operator collapses a vector
operand to its **first element** (``[3 7 9]:[4 8 10]`` is ``3 4``).  The statement therefore
corrects the first decrease and no others, while reading as though it were vectorised.  The port
reproduces that exactly in ``arrayprobe.sizedist._rollover_240000``; this module is the
opt-in correction, outside the port, per the fidelity doctrine.

**What it changes.**  :func:`corrected_rollover` adds ``240000`` to the tail beginning at *each*
decrease, cumulatively -- which is what the source's ``find``-over-all-decreases plainly intends.
Because a constant is added to a whole suffix, the set of decreases in the raw array is the same
set the corrected pass walks, so the result is ``x + 240000 * cumsum(diff(x) < 0)`` with a leading
zero.  Nothing in ``arrayprobe`` changes: a caller applies this to the time array *before* handing
it to ``sizedist.run``, or uses :func:`rollover_report` purely as a diagnostic.

**What this module does NOT claim.**

* **It is unexercised on any data held in this repository, and that is measured, not assumed.**
  A 2026-08-27 check examined both call sites directly across all six
  validated ORACLES 2016 flights: every flight's TAS ``timehhmmss`` and every flight's
  per-particle ``Time`` are non-decreasing over their whole span -- **zero decreases, six
  flights, both arrays**.  So there is no A/B on real data, no recovered-particle count, and no
  claim that any archived ORACLES product would change.  The correction matters for a campaign
  whose flights cross midnight; none of the ones here do.
* **It does not distinguish a midnight crossing from a clock glitch.**  Neither does the MATLAB:
  both treat *any* decrease as a day boundary, so a housekeeping packet arriving out of order, or
  a sub-second backward jitter, buys a spurious 24 hours.  ``min_drop`` is offered so a caller can
  require a decrease of a stated size before calling it midnight, but it defaults to ``0.0``,
  which is exactly the source's own rule.  Choosing a threshold is a science call this module
  deliberately does not make for the user.
* **It is not validated against MATLAB output for a midnight-crossing flight**, because no such
  file exists here.  What *is* checked, in ``test_rollover_fix.py``, is that
  :func:`matlab_rollover` agrees with the port's own faithful implementation element for element
  on every case tested -- so the "before" side of the A/B is the port's, not a second
  transcription of the same MATLAB.
"""

from __future__ import annotations

import numpy as np

__all__ = [
    "ROLLOVER",
    "decrease_indices",
    "matlab_rollover",
    "corrected_rollover",
    "rollover_report",
    "halves_for_engine",
]

#: ``+240000`` -- one day in HHMMSS "digit" arithmetic, as the source writes it.
ROLLOVER = 240000.0

#: The two rollover sites this module can correct, and their state per engine
#: (read against v3.5, 2026-09-14 -- ``applicability.py``'s
#: ``rollover_fix`` row carries the same split).  ``timehhmmss`` is
#: ``sizeDist.m:130-131`` (v3.1.4 and v3.5, byte-for-byte identical): still
#: collapses to the first decrease only, because MATLAB's ``a:b`` takes only the
#: first element of a vector operand -- this module's correction is needed on
#: both engines.  ``particle_time`` is ``image_time_hhmmssall``,
#: ``sizeDist.m:788-799``: unchanged in v3.1.4, but v3.5's own authors rewrote it
#: to loop over every decrease via ``decreasedTimeInds`` -- superseded there by
#: ``arrayprobe_uiops.sizedist.fix_multiday_particle_times`` (which itself has a
#: narrower residual gap: its ``break`` at ``sizeDist.m:795-800`` stops at the
#: FIRST genuine crossover it finds rather than correcting every one -- see ``test_rollover_fix.py``'s
#: ``EngineSplitOnV35`` for a two-crossing case that shows the difference).
_HALVES = {
    "3.1.4": {"timehhmmss": "APPLIES", "particle_time": "APPLIES"},
    "3.5": {"timehhmmss": "APPLIES", "particle_time": "SUPERSEDED"},
}


def halves_for_engine(engine: str) -> dict:
    """Which of the two rollover sites this module still needs to correct.

    ``"APPLIES"`` means this module's correction is still needed there;
    ``"SUPERSEDED"`` means the engine already corrects it (better or worse --
    see the module-level comment) and applying this module's correction on top
    would double-correct.  Raises :class:`ValueError` naming the engine for
    anything not in :data:`_HALVES`, never a silent default.
    """
    try:
        return dict(_HALVES[engine])
    except KeyError:
        raise ValueError(
            f"rollover_fix.halves_for_engine: unknown engine {engine!r}; "
            f"expected one of {sorted(_HALVES)}"
        ) from None


def _as_float(x) -> np.ndarray:
    return np.asarray(x, dtype=np.float64).ravel()


def decrease_indices(x, *, min_drop: float = 0.0) -> np.ndarray:
    """0-based indices ``i`` where ``x[i] < x[i-1]`` -- the starts of each rolled-over tail.

    These are the ``find(diff(x)<0)+1`` positions of the source, converted to 0-based at the
    array boundary in the porting convention's style.  ``min_drop`` (default ``0.0``, the
    source's own rule) requires the decrease to be at least that large before it counts.
    """
    v = _as_float(x)
    if v.size < 2:
        return np.empty(0, dtype=np.int64)
    drop = v[:-1] - v[1:]
    return np.flatnonzero(drop > min_drop) + 1


def matlab_rollover(x):
    """The faithful behaviour: correct the **first** decrease only.

    Kept here so the module can state its own "before" side without importing a private name
    out of the port.  ``test_rollover_fix.py`` asserts this equals
    ``arrayprobe.sizedist._rollover_240000`` on every case it tests, so the equality is measured
    rather than argued.  Returns a new array; the MATLAB statement mutates in place, and the
    port reproduces that -- the copy here is a convenience for A/B use, not a semantic change.
    """
    v = _as_float(x).copy()
    idx = decrease_indices(v)
    if idx.size:
        v[idx[0]:] += ROLLOVER
    return v


def corrected_rollover(x, *, min_drop: float = 0.0):
    """The correction: add ``+240000`` to the tail at **every** decrease, cumulatively.

    A flight crossing midnight twice (a >24 h ferry, or a concatenated multi-day file) ends up
    monotonic; under the source's behaviour its second discontinuity survives.
    """
    v = _as_float(x).copy()
    if v.size < 2:
        return v
    steps = np.zeros(v.size, dtype=np.float64)
    idx = decrease_indices(v, min_drop=min_drop)
    for i in idx:
        steps[i:] += ROLLOVER
    return v + steps


def rollover_report(x, *, min_drop: float = 0.0) -> dict:
    """What the two behaviours do to one array -- the diagnostic, changing nothing.

    ``uncorrected_decreases_remaining`` is the number of decreases still present after the
    faithful pass, i.e. how many day boundaries the source leaves in the array.  It is ``0`` for
    every real ORACLES flight measured (A5's addendum), which is why this module has no
    real-data effect to quote.
    """
    v = _as_float(x)
    idx = decrease_indices(v, min_drop=min_drop)
    faithful = matlab_rollover(v)
    corrected = corrected_rollover(v, min_drop=min_drop)
    return {
        "n": int(v.size),
        "decreases": int(idx.size),
        "decrease_indices": idx.tolist(),
        "corrected_by_matlab": 1 if idx.size else 0,
        "uncorrected_decreases_remaining": int(decrease_indices(faithful,
                                                               min_drop=min_drop).size),
        "monotonic_after_correction": bool(
            decrease_indices(corrected, min_drop=min_drop).size == 0),
        "changed": bool(idx.size > 1),
    }
