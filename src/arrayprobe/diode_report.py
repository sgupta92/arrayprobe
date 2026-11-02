# SPDX-License-Identifier: BSD-3-Clause
"""Per-diode occupancy for one flight, and SPEC's own noisy-diode test.

The brief: *"diode-uniformity report and stuck-bit repair from
neighbours (the port masks; SODA-2 repairs)"*, and a *"statistical
noisy-diode detector as a diagnostic"*.

**This reports; it repairs nothing and changes no computed number.** The port's
answer to a bad diode is `masks.py` -- exclude it and say so. Repairing one by
interpolating its neighbours is a different product, belongs in `enhancements_uiops/`,
and is **not built here**: see `NOT_BUILT` below for why, which is the same
reason the m-D registry ships three relations and five declared gaps.

## What a uniformity report is for

A diode that is stuck dark shadows every slice it appears in, so it reads as a
particle edge in every image that crosses it. Nothing in `imgProc_sm` notices:
each particle is judged on its own silhouette, and a column that is dark in
*all* of them is perfectly consistent with a stream of narrow particles. The
signature only exists at flight scale, which is why this is a flight-level
report rather than a per-particle test.

`enhancements.ml_accept_reject`'s Method A attacks the same physics from the
other end -- `max_col_occ` catches a particle whose *own* window is dominated
by one column. A diode stuck for the whole flight and a diode stuck for one
particle are the same fault at different durations, and the two measurements
are complementary rather than redundant.

## The threshold, and exactly how much of it is quoted

The 2D-S Post-Processing Software Manual rev 1.1 (Feb 2011), Appendix B
pp. 41-45, prints a statistical noisy-diode detector:

    TH = max(M + 5*sqrt(M), 1.5)

over a rolling window of **4,000 images refreshed every 100**. Those three
numbers -- the 5-sigma coefficient, the 1.5 floor, and the window parameters --
are transcribed from the manual and are recorded in
:data:`SPEC_NOISY_DIODE`.

**What the manual's own text says `M` counts has not been read here.** This
module takes it as *the mean per-diode shadowed-image count over the window*,
which is the reading the formula's shape supports (a Poisson-like count with a
sqrt-scaled tolerance and a floor for near-empty windows), and it is the only
reading under which a 1.5 floor means anything. That reading is an inference,
labelled as one: :data:`SPEC_NOISY_DIODE` carries ``m_definition_established =
"derived"`` and a note naming what would confirm it. A future reader with the
manual open should check that field first, and either promote it to
``"transcribed"`` or fix the code.

Nothing else here is inferred. The occupancy report itself is a count of lit
slices per diode, which needs no source at all.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

__all__ = [
    "DiodeReport",
    "NOT_BUILT",
    "SPEC_NOISY_DIODE",
    "SpecNoisyDiodeCriterion",
    "accumulate_occupancy",
    "flag_noisy_diodes",
    "report_from_files",
]


@dataclass(frozen=True)
class SpecNoisyDiodeCriterion:
    """The manufacturer's detector, with each number's provenance attached."""

    sigma_coefficient: float
    """The 5 in ``M + 5*sqrt(M)``. Transcribed."""

    floor: float
    """The 1.5 a threshold may not fall below. Transcribed."""

    window_images: int
    """4,000. Transcribed."""

    refresh_every: int
    """100. Transcribed."""

    source: str
    m_definition_established: str
    """``transcribed`` or ``derived``. It is ``derived``: see the note."""

    m_definition_note: str

    def threshold(self, mean_count: float) -> float:
        """``TH = max(M + 5*sqrt(M), 1.5)`` for one window's mean count.

        A negative ``mean_count`` is a caller error rather than a physical
        state, so it raises instead of returning a NaN that would quietly
        become a threshold nothing exceeds.
        """
        if mean_count < 0:
            raise ValueError(f"mean count must be >= 0, got {mean_count}")
        return max(mean_count + self.sigma_coefficient * math.sqrt(mean_count),
                   self.floor)


SPEC_NOISY_DIODE = SpecNoisyDiodeCriterion(
    sigma_coefficient=5.0,
    floor=1.5,
    window_images=4000,
    refresh_every=100,
    source="2D-S Post-Processing Software Manual rev 1.1 (Feb 2011), "
           "Appendix B pp. 41-45",
    m_definition_established="derived",
    m_definition_note=(
        "The formula, the 5-sigma coefficient, the 1.5 floor and the "
        "4,000/100 window are transcribed from the manual. What the manual "
        "says M counts is NOT read here; this module takes it as the mean "
        "per-diode shadowed-image count over the window, which is the reading "
        "the formula's shape supports and the only one under which a 1.5 floor "
        "is meaningful. Confirm against App. B's own wording and either "
        "promote this field to 'transcribed' or fix the code."),
)

#: Deliberately absent, and why. Same pattern as the m-D registry's declared
#: gaps: a capability nobody has the source for is recorded as a gap, never
#: approximated.
NOT_BUILT: dict[str, str] = {
    "stuck_bit_repair": (
        "Both briefs ask for the manufacturer's masked-diode filling (2D-S PP "
        "manual sec 1.1, p. 5) and dead-diode replacement (sec 1.2, p. 6). "
        "Those two sections' algorithms have not been read in this project -- "
        "only their existence and page numbers are recorded. Repair means "
        "writing values into a particle's silhouette, so an invented rule "
        "would put fabricated pixels into every downstream size, area and "
        "habit. Read sec 1.1-1.2, then build it in enhancements_uiops/ with an A/B "
        "against an unrepaired run."),
}


@dataclass(frozen=True)
class DiodeReport:
    """One flight's per-diode occupancy, and what it implies."""

    shadowed_slices: np.ndarray
    """Per diode: how many slices, over every particle counted, were shadowed."""

    images_present: np.ndarray
    """Per diode: how many particle images the diode was shadowed in at all.
    This, not the slice count, is what the SPEC criterion counts over."""

    total_slices: int
    total_images: int

    @property
    def occupancy(self) -> np.ndarray:
        """Shadowed fraction per diode, over every slice counted.

        The uniformity report proper. A healthy array is flat to within the
        cloud's own inhomogeneity; a stuck diode stands out as a spike that no
        particle population explains.
        """
        if self.total_slices == 0:
            return np.zeros_like(self.shadowed_slices, dtype=float)
        return self.shadowed_slices / float(self.total_slices)

    def summary(self) -> str:
        """The report in the form a person reads before deciding anything."""
        occ = self.occupancy
        if occ.size == 0 or self.total_images == 0:
            return "no particles counted -- nothing to report"
        worst = int(np.argmax(occ))
        return (f"{self.total_images:,} image(s), {self.total_slices:,} slice(s), "
                f"{occ.size} diodes\n"
                f"  occupancy  min {occ.min():.4f}  median {np.median(occ):.4f}  "
                f"max {occ.max():.4f} (diode {worst + 1}, 1-based)")


def accumulate_occupancy(shadows) -> DiodeReport:
    """Count shadowed slices and images per diode over an iterable of silhouettes.

    Each element is the boolean ``(n_slices, n_diodes)`` array
    :func:`arrayprobe.render.reconstruct_particle_image` returns. An iterable
    rather than an array because a flight's particles do not fit in memory at
    once and a report must not require that they do.

    A particle with no slices contributes nothing rather than raising: a proc
    file's own ``position`` bounds should prevent it, and a report is the wrong
    place to discover otherwise.
    """
    shadowed: np.ndarray | None = None
    present: np.ndarray | None = None
    total_slices = 0
    total_images = 0
    for shadow in shadows:
        shadow = np.asarray(shadow, dtype=bool)
        if shadow.ndim != 2 or shadow.shape[0] == 0:
            continue
        if shadowed is None:
            shadowed = np.zeros(shadow.shape[1], dtype=np.int64)
            present = np.zeros(shadow.shape[1], dtype=np.int64)
        elif shadow.shape[1] != shadowed.size:
            raise ValueError(
                f"diode count changed mid-flight: {shadow.shape[1]} after "
                f"{shadowed.size}. One report cannot span two array widths.")
        assert present is not None   # set with `shadowed`, one line apart
        shadowed = shadowed + shadow.sum(axis=0)
        present = present + shadow.any(axis=0)
        total_slices += shadow.shape[0]
        total_images += 1
    if shadowed is None or present is None:
        return DiodeReport(np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64),
                           0, 0)
    return DiodeReport(shadowed, present, total_slices, total_images)


def flag_noisy_diodes(report: DiodeReport,
                      criterion: SpecNoisyDiodeCriterion = SPEC_NOISY_DIODE):
    """Diodes whose image count exceeds the manufacturer's threshold.

    Returns ``(flagged_indices_0based, threshold, mean_count)``.

    The threshold is computed from the mean over **all** diodes, which is the
    whole-flight form of the manual's rolling window: with fewer images than
    ``criterion.window_images`` there is only one window, and with more, a
    whole-flight mean is the conservative reading -- a diode noisy for part of
    the flight is diluted, so this under-reports rather than over-reports.
    A rolling implementation needs the per-image arrival order, which this
    accumulation deliberately does not keep; say so rather than implying the
    manual's exact procedure has been reproduced.
    """
    if report.images_present.size == 0:
        return np.zeros(0, dtype=int), criterion.floor, 0.0
    mean_count = float(report.images_present.mean())
    threshold = criterion.threshold(mean_count)
    flagged = np.flatnonzero(report.images_present > threshold)
    return flagged, threshold, mean_count


def report_from_files(image_path, proc_path, *, limit: int | None = None,
                      stride: int = 1) -> DiodeReport:
    """Build a report straight from a decoded ``.cdf`` and its ``proc`` file.

    ``stride`` samples every n-th particle and ``limit`` caps the count: a dense
    flight holds tens of millions of images, and a uniformity report converges
    long before all of them. Both are recorded by the caller, not here -- a
    sampled report is still a report, but the sampling is part of the number.
    """
    import netCDF4

    from .render import reconstruct_particle_image

    with netCDF4.Dataset(str(image_path)) as image_ds, \
            netCDF4.Dataset(str(proc_path)) as proc_ds:
        proc_ds.set_auto_maskandscale(False)
        n = proc_ds.dimensions["time"].size
        indices = list(range(0, n, max(1, stride)))
        if limit is not None:
            indices = indices[:limit]

        def shadows():
            for i in indices:
                yield reconstruct_particle_image(image_ds, proc_ds, int(i))

        return accumulate_occupancy(shadows())
