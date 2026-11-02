# SPDX-License-Identifier: BSD-3-Clause
"""SPEC's own 2D-S artefact-removal algorithm, as a selectable second
rejection scheme.

**Source, read directly**: `2D-S Post Processing Software Manual rev1.1
20110228.pdf`, Appendix B, "Removing Spurious 2D-S Events", pp. 42-45. Five
quasi-independent steps across two loops: (1) roundness, (2) splash (5
criteria), (3) line-plus-dot noise (6 criteria), (4) a statistical
noisy-diode detector with 3 exception criteria, (5) an inter-event-distance
splash test in a second loop over the whole file (**not implemented here** --
it needs the previous/next event's own timing and position, a cross-particle
state this module's per-particle functions do not carry; a future
`enhancements_uiops/analysis.py`-style leg-scale pass could add it).

**This is a *selectable second* scheme, not a replacement.** UIOOPS's own
`calculate_reject_unified.m` (this port's faithful `reject.py`) is never
touched or changed by anything here. A caller who wants SPEC's own criteria
applied *in addition to* the port's own reject codes calls the functions
below on the same raw particle geometry the port already computes; the
output is an independent accept/reject verdict, and combining it with the
port's own `auto_reject` is the caller's decision, not this module's.

**The four length measures, mapped to what the port already computes**
(verified against `calculate_reject_unified.m`'s own port, `reject.py`, not
assumed):

- L1 (slices the event lasted) = `RejectResult.p_length`
- L2 (max shaded diodes in one slice) = `RejectResult.longest_y`
  (`scan_slice(...).n_lite`, maximised over slices)
- L5 (diode range across the WHOLE event) = `RejectResult.width`
  (running min/max of `scan_slice(...).min_pos_lite`/`max_pos_lite` across
  every slice)
- As (total shaded pixels) = `RejectResult.area`

**L4 has no existing equivalent and is computed fresh here.** The manual
defines it as the diode range at the *specific slice* that maximises L2 --
`reject.py`'s own `longest_y` only keeps the maximum *value*, not which
slice achieved it or that slice's own diode span. :func:`spec_lengths` below
re-scans the image (reusing `arrayprobe.reject.scan_slice`, the same
per-slice primitive `reject.py` itself uses, so this is not a second,
divergent implementation of slice-scanning) and tracks the diode range at
the argmax slice directly.

**L7 (a Korolev-corrected size) and At (an "estimate of total number of
pixels, shaded or not") have no faithful implementation here, and this
module does not invent one.** The manual states explicitly that "the
algorithm for At is part of the Korolev size correction method" without
giving the formula, and this port's own Korolev-style correction
(`enhancements_uiops/outoffocus.py`'s `size_factor`) operates on a *diameter*
(`particle_diameter_minR * size_factor`), not on a reconstructed pixel-area
count -- applying it here would not be the same quantity the manual means,
so it is not used as a substitute.

- **At is approximated as the bounding-box pixel count, `L1 * L5`** --
  literally "the total pixels, shaded or not, in the rectangle the event
  occupies" without Korolev's own out-of-focus reconstruction on top of it.
  This is a *documented under-estimate* relative to whatever SPEC's own
  Korolev-corrected At would give for an out-of-focus particle (Korolev's
  method typically reconstructs a *larger* true size from a defocused
  shadow), so criteria that compare At against a multiple of As will fire
  *less* often here than in SPEC's own software on genuinely out-of-focus
  splash/noise events. A caller with a real Korolev-reconstructed At can
  pass it directly to every function below instead of the bounding-box
  default.
- **L7-dependent splash criterion (v) is not implemented.** It is one of
  five OR'd splash criteria (i-iv are implemented, using the At
  approximation above), so :func:`is_splash` is weaker than SPEC's own five-
  criteria test by exactly this one criterion, not silently claiming to
  reproduce it. Stated in :func:`is_splash`'s own docstring, not only here.

**The noisy-diode detector's "image center"** is read from Figure B.3's own
description (a bar chart of "images centered on this diode" per diode
across the array) as the midpoint diode of the L4 range -- the diode span at
the slice where the event's shading is widest -- rounded to the nearest
diode. The manual does not spell out the centering rule in the prose
extracted here beyond the figure caption; this is a documented
interpretation, not a quoted definition.

Changes no computed number in the port. Same space as `poisson_uncertainty
.py`, `probe_uncertainty.py`, `effective_density.py` and `analysis.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from arrayprobe.particle import shadow_mask
from arrayprobe_uiops.reject_core import scan_slice

__all__ = [
    "SpecLengths",
    "spec_lengths",
    "bounding_box_at",
    "is_round",
    "is_splash",
    "is_line_or_dot_noise",
    "NoisyDiodeState",
    "update_noisy_diode_state",
    "is_center_on_bad_diode",
    "passes_noisy_diode_exception",
]


@dataclass(frozen=True)
class SpecLengths:
    """The manual's own length measures for one particle image, plus the
    documented interpretation of its center diode."""

    l1: float  #: slices the event lasted
    l2: float  #: max shaded diodes in one slice
    l4: float  #: diode range at that same (argmax) slice
    l5: float  #: diode range across the whole event
    area_s: float  #: total shaded pixels
    center_diode: float  #: midpoint of the L4 range, this module's own reading


def spec_lengths(image_buffer, bits_per_slice: int | None = None) -> SpecLengths:
    """L1, L2, L4, L5, As and a center-diode reading for one particle image.

    Re-scans ``image_buffer`` with :func:`arrayprobe.reject.scan_slice`, the
    same per-slice primitive the port's own `calculate_reject_unified` port
    uses -- this is the one extra pass `reject.py` itself does not keep
    around (it discards which slice achieved its own `longest_y` maximum).
    """
    shadow = shadow_mask(image_buffer)
    if shadow.ndim != 2:
        shadow = np.atleast_2d(shadow)
    n_slices, width = shadow.shape
    if bits_per_slice is None:
        bits_per_slice = width

    min_length = -1
    max_length = -1
    max_width = 1
    min_width = bits_per_slice
    total_area = 0
    l2 = 0
    l4_min = l4_max = 0

    for i in range(n_slices):
        scan = scan_slice(shadow[i])
        if scan.n_lite > 0:
            if min_length == -1:
                min_length = i
            max_length = i
            max_width = max(max_width, scan.max_pos_lite)
            min_width = min(min_width, scan.min_pos_lite)
            total_area += scan.n_lite
            if scan.n_lite > l2:
                l2 = scan.n_lite
                l4_min, l4_max = scan.min_pos_lite, scan.max_pos_lite

    if total_area == 0:
        return SpecLengths(l1=0.0, l2=0.0, l4=0.0, l5=0.0, area_s=0.0, center_diode=0.0)

    l1 = float(max_length - min_length + 1)
    l5 = float(max_width - min_width + 1)
    l4 = float(l4_max - l4_min + 1)
    center = (l4_min + l4_max) / 2.0
    return SpecLengths(l1=l1, l2=float(l2), l4=l4, l5=l5, area_s=float(total_area),
                       center_diode=center)


def bounding_box_at(lengths: SpecLengths) -> float:
    """``L1 * L5`` -- the documented bounding-box approximation of At. See
    the module docstring for why this is not a faithful Korolev-reconstructed
    At and how that under-estimate biases every At-using criterion."""
    return lengths.l1 * lengths.l5


def is_round(lengths: SpecLengths) -> bool:
    """Step 1, p. 43: ``L1 >= 0.5*L5 and (L5 >= 0.5*L1 or L5 > 50)``."""
    l1, l5 = lengths.l1, lengths.l5
    return l1 >= 0.5 * l5 and (l5 >= 0.5 * l1 or l5 > 50)


def is_splash(lengths: SpecLengths, at: float | None = None) -> bool:
    """Step 2, p. 43: reject (return True) if any of criteria i-iv hold.

    Criterion v (``L5 > 2.2*L7``) is NOT implemented -- see the module
    docstring for why a faithful L7 is not available here. This function is
    therefore weaker than SPEC's own five-criteria test by exactly that one
    criterion.
    """
    l1, l5, area_s = lengths.l1, lengths.l5, lengths.area_s
    if at is None:
        at = bounding_box_at(lengths)
    return (
        ((l5 > 10 or l1 > 10) and (at > 3.0 * area_s))
        or ((l5 > 15 or l1 > 15) and (at > 2.5 * area_s))
        or ((l5 > 20 or l1 > 20) and (at > 2.0 * area_s))
        or ((l5 > 35 or l1 > 35) and (at > 1.5 * area_s))
    )


def is_line_or_dot_noise(lengths: SpecLengths, at: float | None = None) -> bool:
    """Step 3, p. 44: reject (return True) if any of criteria i-vi hold."""
    l1, l2, l4, l5, area_s = lengths.l1, lengths.l2, lengths.l4, lengths.l5, lengths.area_s
    if at is None:
        at = bounding_box_at(lengths)
    return (
        (l1 == area_s and l2 == 1 and l1 > 4)
        or (area_s <= 1.35 * l1 and l4 == l5 and l1 > 4 and l2 == 2)
        or (l1 > 10 and l1 > 0.75 * area_s and l1 <= 1.5 * area_s)
        or (l4 == l5 and at > 0.9 * l1 * l5 and l2 == 2 and l2 != l4)
        or (l4 == l5 and at > 3.0 * area_s and l2 == 2)
        or (l4 == l5 and at > 4.0 * area_s)
    )


@dataclass
class NoisyDiodeState:
    """Running per-diode "image center" counts for the rolling-window
    noisy-diode detector (step 4, p. 44). Mutable by design -- a caller
    accumulates one flight's worth of :func:`spec_lengths` results into one
    state object across a rolling window, refreshed as the manual specifies
    (every 100 images, over the nearest 4000).
    """

    counts: np.ndarray  #: one entry per diode, 0-indexed by (diode_number - 1)

    @classmethod
    def new(cls, n_diodes: int) -> "NoisyDiodeState":
        return cls(counts=np.zeros(n_diodes, dtype=np.int64))


def update_noisy_diode_state(state: NoisyDiodeState, center_diodes) -> None:
    """Recount ``state.counts`` from a window of center-diode values (one per
    image in the current rolling window). Replaces the counts in place --
    the manual's window is refreshed wholesale every 100 images, not
    incremented one image at a time, so recomputation from the window's own
    contents is the faithful operation, not an incremental add.
    """
    state.counts[:] = 0
    for d in center_diodes:
        idx = int(round(d)) - 1
        if 0 <= idx < state.counts.size:
            state.counts[idx] += 1


def _bad_diode_mask(counts: np.ndarray) -> np.ndarray:
    """One iteration-to-convergence of the manual's Mt/M/TH procedure (p. 44),
    returning a boolean mask of which diodes are currently "bad".
    """
    counts = counts.astype(np.float64)
    active = np.ones(counts.size, dtype=bool)
    bad = np.zeros(counts.size, dtype=bool)
    while True:
        considered = counts[active]
        if considered.size == 0:
            break
        mt = considered.mean()
        min_count_filter = considered[considered > mt - 3 * np.sqrt(mt)]
        m = min_count_filter.mean() if min_count_filter.size >= 33 else considered.mean()
        th = max(m + 5 * np.sqrt(m), 1.5)
        newly_bad = active & (counts > th)
        if not newly_bad.any():
            break
        bad |= newly_bad
        active &= ~newly_bad
    return bad


def is_center_on_bad_diode(state: NoisyDiodeState, center_diode: float) -> bool:
    """Whether ``center_diode`` (the reading :func:`spec_lengths` computed
    for one particle) falls on a diode the current window's Mt/M/TH
    procedure flags as bad."""
    bad = _bad_diode_mask(state.counts)
    idx = int(round(center_diode)) - 1
    if not (0 <= idx < bad.size):
        return False
    return bool(bad[idx])


def passes_noisy_diode_exception(lengths: SpecLengths, at: float | None = None) -> bool:
    """The three exception criteria (p. 45) that rescue an image whose
    center falls on a bad diode from rejection. True means "keep it anyway".
    """
    l1, l2, l4, l5, area_s = lengths.l1, lengths.l2, lengths.l4, lengths.l5, lengths.area_s
    if at is None:
        at = bounding_box_at(lengths)
    return (
        (l1 >= 15 and l5 >= 15 and area_s > 0.7 * at)
        or (l1 >= 4 and l5 >= 4 and area_s >= 0.5 * at and l2 > 0.25 * l5 and l1 < 50)
        or (l2 == l4 and l2 == l5 and l2 >= 2 and area_s >= 0.5 * at)
    )
