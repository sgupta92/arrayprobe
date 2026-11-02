# SPDX-License-Identifier: BSD-3-Clause
"""Size-dependent hollow rejection, calibrated on 480 hand-labelled particles.

**What this is.** An opt-in, default-off refinement of ``rej_hollow`` for
``arrayprobe_uiops``. Below a size threshold, the hollow test's rejection
applies exactly as stock does; at or above it, the hollow test's rejection
is bypassed for that particle -- it is treated as not-hollow for the
purpose of ``calculate_reject_unified``, so no other branch of that
function changes. The port reproduces upstream and adds no new package, so this
is new behaviour, so it ships **inside** the engine it extends rather than
as a new package, opt-in, default-off, and proven bit-identical to stock
when off (:func:`resolve_ihollow` returns ``ihollow`` unchanged whenever
the rule is missing or disabled -- see
``tests/test_hollow_size_rule.py::TestBitIdenticalWhenOff``, which checks
with ``np.array_equal``, never ``allclose``).

**The oracle is the author's own labels, not the Octave goldens** (the rule is
"its own named oracle" -- the Octave goldens validate the stock v3.5 path,
which this module never touches when off, and cannot validate a labelling
judgement in any case). 2026-09-18: 480 particles labelled across 16
cells over two rounds. Fraction of *disputed* particles (particles where
stock and an image-assisted alternative disagree) that are genuinely real,
i.e. the fraction stock's hollow test wrongly discards, by
``image_diam_minR`` size bin, with Wilson 95% intervals:

    55-105 um    0 %  [0, 13]   n=25
    105-155 um  45 %  [31, 60]  n=40
    155-205 um  60 %  [45, 74]  n=40
    205-255 um  63 %  [46, 78]  n=30
    255-305 um  87 %  [70, 95]  n=30

**That table is a rendering of :data:`LABELLED_EVIDENCE`, not a separate
statement of it.** Until 2026-09-21 it lived only here, in prose, while
:data:`DEFAULT_THRESHOLD_UM` was a typed ``155.0`` -- so the number was
machine-readable and the evidence justifying it was not, and the two could
drift apart in silence. A figure audit named that as the reason the
paper's Section 6 figure could not honestly be drawn. The counts now live in
:data:`LABELLED_EVIDENCE`, the threshold is :func:`threshold_from_evidence`
read off them, and
``tests/test_hollow_size_rule.py::TestTheDocstringTableIsTheConstant``
re-parses the five rows above and asserts every percentage, bound and ``n``
against the computed values -- so editing one without the other fails.

Monotonic; crosses 50% between the 105-155 and 155-205 bins. Pooled over
both labelling rounds, the whole 105-205 band is 53/105 = 50.5% --
break-even, which is exactly why round 1 (n=25 in that band alone) could
not resolve it. Below 105 um the labels say no threshold helps at all --
among particles both configurations already accept, 55-105 um is only 32%
real, against 78-100% in every bin above it -- so this module does not try
to buy anything below its threshold; excluding that bin from a downstream
comparison is a separate decision this module does not make.

**155 um is the best estimate, not a sharp boundary.** The 45% [31, 60] and
60% [45, 74] Wilson intervals overlap (both n=40, overlapping on
[45, 60]), so the switch point could sit anywhere the two bins' data
cannot yet distinguish. This caveat travels with the number here, in code,
because it must live in the code's docstring:
see :data:`DEFAULT_THRESHOLD_UM` and
``tests/test_hollow_size_rule.py::TestThresholdIsAnEstimateNotAClaim``,
which both greps this docstring for the caveat and independently
recomputes the two Wilson intervals from the raw counts to confirm they
still overlap -- so an edit that quietly changed the numbers, not just the
words, would also fail.

**Boundary convention.** "Below" is ``size_um < threshold_um`` (the hollow
test's rejection applies, as stock); "at or above" is
``size_um >= threshold_um`` (the hollow test's rejection is bypassed). The
threshold value itself falls on the disabled side, because it is the left
edge of the 155-205 bin, where the labels already say the hollow test is
more often wrong than right (60% real). A particle whose size cannot be
established behaves as stock (``size_um is None`` -> hollow test applies)
-- this rule only ever narrows what stock rejects for hollow; it never
invents a new rejection of its own.

**What decides ``ihollow``, and where this hooks in.**
``arrayprobe_uiops.reject.calculate_reject_unified(image_buffer, habit,
ihollow, config)`` (``reject.py:208-219``) takes hollow status as a
required argument rather than computing it -- v3.5 moved that decision to
the caller (see that module's own docstring, point 1: ``imgProc_sm.m``
decides hollow status itself in v3.5). The caller is
``arrayprobe_uiops.measure.measure_record`` (``measure.py:200-263``), which,
in order:

1. computes ``minR, ctx, cty = cgal_min_r_v35(codes, geom.tas_ratio)``
   (``measure.py:237``) *before* the reject call. ``minR`` is a raw,
   diode-scaled quantity -- the same one ``imgproc.py:1365`` later writes
   to the output netCDF as ``image_diam_minR`` via ``minR * ds`` (there in
   mm; ``ds`` is ``geom.diodesize``, mm/diode, ``measure.py:113``);
2. decides ``is_hollow`` (the ``[EXPERIMENTAL]`` override at
   ``measure.py:239-259``);
3. calls ``rj = calculate_reject_unified(codes, habit, is_hollow,
   reject_config)`` (``measure.py:262``).

So the size measure available at the decision point is exactly the
quantity ``image_diam_minR`` is made of, just not yet named that or
converted to micrometres. :func:`size_um_from_minr` does the same
``* diodesize`` step ``imgproc.py:1365`` does, then ``* 1000`` for
micrometres, to match the units the bins above are stated in. This module
does not use ``p_length``/``width`` (the diode-count geometry
``calculate_reject_unified`` computes internally, for its own aspect-ratio
tests): those are not what the labels were binned by, and unlike ``minR``
they are not available before that function is even called.

**A preserved defect this sits right next to** (``reject.py:361-375``,
documented there, not repeated or altered here): inside
``calculate_reject_unified``, whatever ``ihollow`` value the caller passes
in becomes ``hollow_status`` verbatim -- a second, "side" call to
``is_it_hollow`` on the transposed buffer computes its own status, but
that result is thrown away (assigned to a variable never read again), a
real MATLAB defect preserved rather than fixed. Practically: intercepting
``ihollow`` before it reaches ``calculate_reject_unified``, as this module
does, is equivalent to intercepting ``hollow_status`` itself -- there is
no other point upstream of ``reject_status`` where a size-dependent
override could act with a smaller blast radius.

**Integration this module does not wire in itself** (by design -- see
``_decoded/cip160906/HOLLOW_SIZE_RULE.md`` for the report this shipped
with). One line at ``measure.py:262``, replacing the ``is_hollow``
argument:

    rj = calculate_reject_unified(codes, habit, resolve_ihollow(
        is_hollow, size_um_from_minr(minR, geom.diodesize), hollow_rule),
        reject_config)

where ``hollow_rule`` is a :class:`HollowSizeRule` threaded into scope
(for example, a new ``RecordGeometry`` field defaulting to
``HollowSizeRule()``, which is off) -- so no existing call site changes
behaviour until it explicitly opts in.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

__all__ = [
    "DEFAULT_THRESHOLD_UM",
    "LABELLED_EVIDENCE",
    "HollowSizeRule",
    "LabelledBin",
    "hollow_test_applies",
    "resolve_ihollow",
    "resolve_ihollow_array",
    "size_um_from_minr",
    "threshold_from_evidence",
    "wilson_95",
]

#: Two-sided 95 % normal quantile, the one used for every interval below.
_Z95 = 1.959963984540054


def wilson_95(n_success: int, n: int) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion, two-sided 95 %.

    Wilson rather than Wald because three of the five bins below sit near an
    end of the range -- ``0/25`` among them, where Wald's interval is the
    degenerate ``[0, 0]`` and would make "no threshold helps here" look like
    a certainty rather than the ``[0, 13] %`` it is.
    """
    if n <= 0:
        raise ValueError(f"n must be positive; got {n!r}")
    if not 0 <= n_success <= n:
        raise ValueError(f"n_success must lie in [0, {n}]; got {n_success!r}")
    p = n_success / n
    z2n = _Z95 * _Z95 / n
    centre = (p + z2n / 2.0) / (1.0 + z2n)
    half = (_Z95 / (1.0 + z2n)) * math.sqrt(
        p * (1.0 - p) / n + _Z95 * _Z95 / (4.0 * n * n)
    )
    return max(0.0, centre - half), min(1.0, centre + half)


@dataclass(frozen=True)
class LabelledBin:
    """One size bin of the hand-labelled *disputed* particles.

    "Disputed" means stock's hollow test rejects the particle and the
    image-assisted alternative would accept it; the label says which side was
    right. :attr:`n_real` is how many of those were judged to be real
    particles -- i.e. how many stock's hollow test wrongly discarded.

    Only the two counts are stored. The fraction and its interval are
    **computed**, never typed, so there is exactly one place a label can move.
    """

    band_lo_um: float
    band_hi_um: float
    n_real: int
    n_artifact: int

    @property
    def n(self) -> int:
        """Labels with a usable verdict in this bin (``real`` + ``artifact``)."""
        return self.n_real + self.n_artifact

    @property
    def fraction_real(self) -> float:
        """The fraction of stock's rejections in this bin that were real."""
        return self.n_real / self.n

    @property
    def wilson_95(self) -> tuple[float, float]:
        """:func:`wilson_95` of this bin's counts."""
        return wilson_95(self.n_real, self.n)


#: The author's labelled evidence, the oracle this module's threshold rests on --
#: the five *elementary* disputed bins (the two wider round-1 bands, 105-205
#: and 205-305, are supersets of these and are deliberately not listed, so no
#: particle is counted twice).
#:
#: **Counts, not conclusions.** Every percentage and interval this project
#: quotes for the hollow rule is derived from the four integers per row here:
#: the module docstring's table, :data:`DEFAULT_THRESHOLD_UM` itself, and the
#: paper's Section 6 figure. Promoted out of the docstring 2026-09-21 (the
#: figure audit), which found the threshold machine-readable and its
#: justification prose -- the precise shape in which a number and its evidence
#: drift apart with nothing failing.
#:
#: Provenance: ``_decoded/cip160906/triage_verdicts/sea_s2.json``, the triage
#: server's own verdict store, 480 records over 16 queues. The counts are
#: pinned against a recount of that file in
#: the tracked CIP hollow-label fixture in ``tests/data``.
LABELLED_EVIDENCE: tuple[LabelledBin, ...] = (
    LabelledBin(55.0, 105.0, n_real=0, n_artifact=25),
    LabelledBin(105.0, 155.0, n_real=18, n_artifact=22),
    LabelledBin(155.0, 205.0, n_real=24, n_artifact=16),
    LabelledBin(205.0, 255.0, n_real=19, n_artifact=11),
    LabelledBin(255.0, 305.0, n_real=26, n_artifact=4),
)


def threshold_from_evidence(
    bins: tuple[LabelledBin, ...] = LABELLED_EVIDENCE,
) -> float:
    """Where the labels say the hollow test flips from right to wrong.

    The low edge of the smallest bin in which stock's hollow test is wrong at
    least as often as it is right (``fraction_real >= 0.5``), scanning upward.
    That is the whole rule: the threshold is **read off the labels**, not
    chosen and then justified, so re-labelling moves it and nothing here needs
    editing.

    Raises :class:`ValueError` if no bin crosses the half -- a state in which
    this module has no evidence for any threshold and should not silently
    supply one.
    """
    for b in sorted(bins, key=lambda x: x.band_lo_um):
        if b.fraction_real >= 0.5:
            return float(b.band_lo_um)
    raise ValueError(
        "no labelled bin reaches a real fraction of 0.5, so the labels "
        "support no threshold; do not default one"
    )


#: The best estimate of where the hollow test flips from right to wrong,
#: in the same micrometre units as ``image_diam_minR``. **Derived from
#: :data:`LABELLED_EVIDENCE`, not typed** -- it is 155.0 because that is the
#: low edge of the first bin the labels put above the half (24/40 = 60 %),
#: and it moves when a label moves.
#:
#: NOT a sharp boundary -- see the module docstring's "155 um is the best
#: estimate" section. Pass a different value to
#: ``HollowSizeRule(threshold_um=...)`` instead of editing anything here: the
#: labels cannot justify more precision than one number, and a future
#: campaign, probe, or larger label set will want to move it without touching
#: this module's logic.
DEFAULT_THRESHOLD_UM: float = threshold_from_evidence()


@dataclass(frozen=True)
class HollowSizeRule:
    """Configuration for the size-dependent hollow rejection.

    ``enabled=False`` is the default, and makes every function below a
    strict passthrough of ``ihollow`` -- see
    ``tests/test_hollow_size_rule.py::TestBitIdenticalWhenOff``.

    ``threshold_um`` is a parameter, not a constant: the labels behind
    :data:`DEFAULT_THRESHOLD_UM` (480 hand-labelled particles) cannot justify more
    precision than one estimate, and that estimate is not a sharp boundary
    -- the 45% [31, 60] and 60% [45, 74] Wilson intervals it sits between
    overlap, both at n=40. A future campaign, probe, or bigger label set
    will want to move this number without editing this module's code.
    """

    enabled: bool = False
    threshold_um: float = DEFAULT_THRESHOLD_UM

    def __post_init__(self) -> None:
        if not math.isfinite(self.threshold_um) or self.threshold_um <= 0:
            raise ValueError(
                "threshold_um must be a finite, positive number of "
                f"micrometres; got {self.threshold_um!r}"
            )


def hollow_test_applies(rule: HollowSizeRule | None, size_um: float | None) -> bool:
    """Whether the hollow test's rejection should apply, as stock does, to a
    particle of this size under this rule.

    ``True`` (apply as stock) when ``rule`` is ``None`` or ``rule.enabled``
    is ``False``, when no size could be established (``size_um is None`` --
    stock is always the conservative fallback), or when
    ``size_um < rule.threshold_um``. ``False`` (bypass the hollow test's
    rejection) only when the rule is enabled AND
    ``size_um >= rule.threshold_um`` -- the threshold value itself is on
    the disabled side; see the module docstring's "Boundary convention".
    """
    if rule is None or not rule.enabled:
        return True
    if size_um is None:
        return True
    return size_um < rule.threshold_um


def resolve_ihollow(
    ihollow: int, size_um: float | None, rule: HollowSizeRule | None = None
) -> int:
    """The ``ihollow`` value ``calculate_reject_unified`` should receive,
    with the size-dependent rule applied.

    Returns ``int(ihollow)`` unchanged whenever :func:`hollow_test_applies`
    is ``True`` (stock -- always true when ``rule`` is ``None`` or
    disabled); returns ``0`` (not hollow) otherwise. Never turns a stock
    ``0`` into a ``1``: this rule only narrows what stock rejects for
    hollow, matching the module docstring's note on the preserved
    ``hollow_status``/``ihollow`` defect at
    ``arrayprobe_uiops/reject.py:361-375`` -- the caller's ``ihollow`` is what
    decides ``hollow_status``, unchanged by anything downstream, so this is
    the only point with leverage on the outcome.
    """
    if hollow_test_applies(rule, size_um):
        return int(ihollow)
    return 0


def resolve_ihollow_array(
    ihollow: np.ndarray, size_um: np.ndarray, rule: HollowSizeRule | None = None
) -> np.ndarray:
    """Vectorised :func:`resolve_ihollow`, for retroactively applying the
    rule across an already-decoded record's ``is_hollow``/
    ``image_diam_minR`` columns, rather than one particle at a time inside
    ``arrayprobe_uiops.measure.measure_record``. Not used by the pipeline
    itself -- offered for the kind of bulk recompute this project's own
    reproducibility checks already do (e.g. the check that the habit column
    reproduces from a decoded file on disk).

    ``size_um`` entries that are NaN are treated as "no size established"
    (stock applies), matching :func:`hollow_test_applies`'s ``None`` case.
    """
    ihollow_arr = np.asarray(ihollow).astype(np.int64, copy=False)
    if rule is None or not rule.enabled:
        return ihollow_arr.copy()
    size_arr = np.asarray(size_um, dtype=np.float64)
    stock_applies = np.isnan(size_arr) | (size_arr < rule.threshold_um)
    return np.where(stock_applies, ihollow_arr, 0)


def size_um_from_minr(minr: float, diodesize_mm: float) -> float:
    """The size measure available where the hollow decision is made.

    ``arrayprobe_uiops/measure.py:237`` computes ``minR`` before the
    ``:262`` reject call; ``minr * diodesize_mm`` is exactly what
    ``arrayprobe_uiops/imgproc.py:1365`` later writes to the output netCDF as
    ``image_diam_minR`` (there in mm, ``diodesize_mm`` being
    ``RecordGeometry.diodesize``). This function does that same
    multiplication and then converts mm to micrometres (``* 1000``) to
    match the units :data:`DEFAULT_THRESHOLD_UM` and the hand labels are
    stated in. Not a new geometric computation -- the same quantity, read
    one call earlier and in different units.
    """
    return float(minr) * float(diodesize_mm) * 1000.0
