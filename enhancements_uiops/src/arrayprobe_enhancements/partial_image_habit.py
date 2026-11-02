# SPDX-License-Identifier: BSD-3-Clause
"""Habit for accepted partial images -- Korolev & Sussman (2000), RABIT.

Source, opened and read for every rule below: Korolev, A. and Sussman, B. (2000), *A
Technique for Habit Classification of Cloud Particles*, J. Atmos. Oceanic Technol. **17**,
1048-1057 (held by the author as ``korolov_2000.pdf``; the file
name is misspelt, the title page is not). Page numbers below are the journal's.

**What UIOOPS does with an edge-touching ("partial") image today** (read, both vendored
trees):

* **v3.1.4** runs the complete-image Holroyd rules on the truncated silhouette
  (``imgProc_sm.m:807``, ``holroyd(handles,c)``), with no partial-image branch anywhere in
  ``holroyd.m``. An accepted partial gets a habit, computed as though the cut edge were the
  particle's own outline.
* **v3.5** withholds a habit instead: ``'C'`` for every centre-out image
  (``imgProc_sm.m:1282-1285``) and, under ``iNewHabit == 1`` (the Schima et al. 2024
  scheme), for any image whose edge contact exceeds half its diameter
  (``holroyd_new.m:101-104``, ``e_d_r > 0.5``). A centre-in partial below that bound still
  gets the complete-image rules on its truncated silhouette.

So the developers did **not** fix this in v3.5 in Korolev & Sussman's sense -- they chose
exclusion, where the paper classifies partials with a ratio built for partials. There is no
upstream fix to delegate to, and this module applies to both engines'
images identically.

**RABIT is a population classifier, not a per-particle one** (p. 1049: *"the results of
habit recognition cannot be associated with features of individual images"*). It never
writes a habit code onto a particle; it retrieves the *fraction* of an ensemble in each of
four habits (sphere, irregular, needle, dendrite) from the histogram of one dimensionless
ratio, by inverting a probe-specific retrieval matrix. This module therefore changes no
per-particle number in either engine's output, and has no ``holroyd_habit`` column to
correct.

**The only published retrieval matrices are for the NRC OAP-2DC** (32 diodes, 25 um,
vertical laser beam; p. 1049 and the appendix, p. 1057), and the paper says in terms they
do not transfer: *"these results are not necessarily transferable to other PMS OAP-2D
probes ... If the laser beam is directed horizontally, the above matrices are not
applicable at all. In general, new retrieval matrices should be created for different
probe configurations"* (p. 1057). :func:`classify_population` therefore **refuses** a
matrix whose probe geometry differs from the data's -- which, for every 2D-S and HVPS this
project processes, is both shipped matrices. The half this module *can* build honestly from
the paper is built (the four image groups, both ratios, the partial-circle perimeter,
the retrieval and the complete/partial combination, and the construction of a new
matrix from a labelled training set); the half it cannot -- a 2D-S retrieval matrix --
needs a source nobody holds: a hand-classified 2D-S training set of complete and partial
images in the four RABIT categories (Sect. 4c-d), or a published 2D-S matrix. See
``enhancements_uiops/docs/CORRECTIONS.md`` Part ``partial_image_habit``.

**Readings that are derived, not transcribed** (each named where it is used):

1. The four group rules (Sect. 4b, p. 1051) neither cover every image nor exclude each
   other -- an image with ``N_total == 20`` matches none; a 181-pixel image spanning the
   whole array with ``N_edge < 4`` matches both "complete" and "accepted partial". No
   precedence is stated, so none is invented: :func:`image_groups` returns every rule an
   image matches, and only an image matching exactly one of the two retrievable groups is
   retrieved.
2. ``N_y == 32`` becomes ``N_y == n_diodes``, from the paper's own gloss (*"which is
   maximum number of pixels in the y direction"*, p. 1051). The pixel thresholds 20 and
   180 are kept at the paper's values and **not** rescaled to another pixel size -- the
   paper calls 180 empirical and says it *"can be changed either side"*; a rescaled value
   would be a number the paper does not give.
3. Eq. 2 is singular at ``x1 == 0`` (``z == 0``, so ``arctan(x1/2z)`` is ``0/0``), a case
   the paper says the equation covers. Its limit is ``theta1 = 0`` (the cap vanishes), which
   is what :func:`p_circ` uses; the complete-circle case then gives ``2 pi r`` exactly.
4. Eq. 4's five-step shift-and-sum (Sect. 4c(3), Fig. 7) does not say how the frame's
   border is padded or how the edge pixels of a partial image are *"not included in the
   perimeter"*. :func:`ks_perimeter` pads the slice axis with clear pixels and the diode
   axis by replicating the edge diode, so the cut edge produces no transition, then counts
   only inside the array. **Step 2's direction is also a reading, and a measured one.**
   Taken literally ("A shifted one pixel left", then "B shifted one pixel right"), the
   along-flight shifts run in opposite directions, and two of the four diagonal quadrants
   then read 2 (a leg) instead of 3 -- measured on digitised discs, ``N_P / 2 pi r`` falls
   to 0.79-0.85 and a partial disc's ``R2`` to 0.79-0.90, inside the interval
   ``[0, 0.94)`` that the paper's own partial-sphere basis gives only 4.7 % of spheres
   (appendix). With both shifts in the same direction every diagonal reads 3, as p. 1052
   and Fig. 7's image F state; discs then give ``N_P / 2 pi r`` of 1.06-1.09 (the known
   over-estimate of an 8-connected chain-code perimeter) and partial discs ``R2`` of
   1.03-1.06, inside ``[0.94, 1.16)`` where the paper puts 94.7 % of partial spheres. The
   second is used; ``test_partial_image_habit.py`` pins both measurements.
5. Eq. 9 sums a 3-vector (complete; no dendrite row, Sect. 5c) and a 4-vector (partial).
   The complete vector is read as having a zero dendrite fraction, which is the paper's own
   stated consequence of excluding complete dendrites (*"will not affect the result of
   recognition much"*, p. 1057).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np

__all__ = [
    "HABITS",
    "N_TOTAL_TINY",
    "N_TOTAL_PARTIAL",
    "N_EDGE_MIN",
    "RetrievalMatrix",
    "KS2000_OAP2DC_COMPLETE",
    "KS2000_OAP2DC_PARTIAL",
    "NoRetrievalMatrixForProbe",
    "ImageMeasures",
    "measure",
    "image_groups",
    "retrieval_group",
    "r1",
    "p_circ",
    "ks_perimeter",
    "r2",
    "retrieve_fractions",
    "combine",
    "build_retrieval_matrix",
    "PopulationResult",
    "census",
    "classify_population",
]

#: The four RABIT habit categories, in the order the appendix prints its vectors (p. 1057).
HABITS: tuple[str, ...] = ("sphere", "irregular", "needle", "dendrite")

#: ``N*_total`` -- below this an image is "tiny" and is not classified (Sect. 4b(1), p. 1050).
N_TOTAL_TINY: int = 20
#: The accepted/rejected partial boundary on ``N_total`` (Sect. 4b(2) and (4), p. 1051).
N_TOTAL_PARTIAL: int = 180
#: ``N_edge`` at or above which an image counts as touching the edge (Sect. 4b(2)-(4), p. 1051).
N_EDGE_MIN: int = 4


@dataclass(frozen=True)
class RetrievalMatrix:
    """One RABIT retrieval matrix: basis vectors over the intervals of one ratio.

    ``rows[i][j]`` is ``B_ij`` of Eq. 6 -- the fraction of habit ``habits[i]``'s basis
    distribution falling in interval ``[edges[j], edges[j+1])``. Each row sums to one
    (Sect. 4d: *"M(R) and B_i(R) are normalized to unity"*). ``n_diodes`` and
    ``pixel_um`` are the probe the training set came from; :func:`classify_population`
    refuses a matrix whose probe differs from the data's (p. 1057).
    """

    ratio: str
    habits: tuple[str, ...]
    edges: tuple[float, ...]
    rows: tuple[tuple[float, ...], ...]
    n_diodes: int
    pixel_um: float
    probe: str
    source: str

    def as_array(self) -> np.ndarray:
        return np.asarray(self.rows, dtype=float)


#: Appendix, p. 1057: ``R1`` over ``[0, 1.07), [1.07, 1.94), [1.94, inf)``; spheres,
#: irregulars, needles. No dendrite row (Sect. 5c).
KS2000_OAP2DC_COMPLETE = RetrievalMatrix(
    ratio="R1",
    habits=("sphere", "irregular", "needle"),
    edges=(0.0, 1.07, 1.94, math.inf),
    rows=((0.9803, 0.0197, 0.0),
          (0.2745, 0.7235, 0.0020),
          (0.0074, 0.3333, 0.6593)),
    n_diodes=32,
    pixel_um=25.0,
    probe="NRC PMS OAP-2DC, vertical laser beam",
    source="Korolev & Sussman (2000) JAOT 17, appendix p. 1057",
)

#: Appendix, p. 1057: ``R2`` over ``[0, 0.94), [0.94, 1.16), [1.16, 2.06), [2.06, inf)``;
#: spheres, irregulars, needles, dendrites/aggregates.
KS2000_OAP2DC_PARTIAL = RetrievalMatrix(
    ratio="R2",
    habits=HABITS,
    edges=(0.0, 0.94, 1.16, 2.06, math.inf),
    rows=((0.0467, 0.9467, 0.0067, 0.0),
          (0.0117, 0.1780, 0.7869, 0.0234),
          (0.3493, 0.2059, 0.3346, 0.1103),
          (0.0, 0.0, 0.0591, 0.9409)),
    n_diodes=32,
    pixel_um=25.0,
    probe="NRC PMS OAP-2DC, vertical laser beam",
    source="Korolev & Sussman (2000) JAOT 17, appendix p. 1057",
)


class NoRetrievalMatrixForProbe(ValueError):
    """The retrieval matrix was built for a different probe than the images came from.

    Korolev & Sussman (2000) p. 1057: the matrices *"are not necessarily transferable"*
    and *"new retrieval matrices should be created for different probe configurations"*.
    Raised rather than applied, because a habit fraction retrieved through another
    probe's matrix is a number with no stated meaning.
    """


# --- Per-image measures (Sect. 4a, Fig. 2) ----------------------------------------------


@dataclass(frozen=True)
class ImageMeasures:
    """Fig. 2's measurable parameters for one silhouette.

    ``nx`` slices along the flight direction, ``ny`` diodes spanned along the array,
    ``n_total`` shadowed pixels, ``n_edge1``/``n_edge2`` shadowed pixels on the first and
    last diode, and whether a clear slice sits inside the shadowed zone (Sect. 4b(2):
    such images are rejected, Fig. 3c).
    """

    nx: int
    ny: int
    n_total: int
    n_edge1: int
    n_edge2: int
    interior_empty_slice: bool

    @property
    def n_edge(self) -> int:
        return self.n_edge1 + self.n_edge2


def _as_silhouette(image) -> np.ndarray:
    img = np.asarray(image, dtype=bool)
    if img.ndim != 2:
        raise ValueError(f"a silhouette is 2-D (n_slices, n_diodes); got shape {img.shape}")
    return img


def measure(image) -> ImageMeasures:
    """Fig. 2's parameters for a boolean ``(n_slices, n_diodes)`` silhouette, True = shadowed.

    The layout is :func:`arrayprobe.render.reconstruct_particle_image`'s, so diode 1 and
    diode ``n_diodes`` -- the array's two edges -- are columns ``0`` and ``-1``.
    """
    img = _as_silhouette(image)
    n_total = int(img.sum())
    if n_total == 0:
        return ImageMeasures(0, 0, 0, 0, 0, False)
    slices = np.flatnonzero(img.any(axis=1))
    diodes = np.flatnonzero(img.any(axis=0))
    occupied = img[slices[0]:slices[-1] + 1].any(axis=1)
    return ImageMeasures(
        nx=int(slices[-1] - slices[0] + 1),
        ny=int(diodes[-1] - diodes[0] + 1),
        n_total=n_total,
        n_edge1=int(img[:, 0].sum()),
        n_edge2=int(img[:, -1].sum()),
        interior_empty_slice=bool(not occupied.all()),
    )


# --- Image groups (Sect. 4b, p. 1050-1051) -----------------------------------------------


def image_groups(m: ImageMeasures, n_diodes: int, *, n_tiny: int = N_TOTAL_TINY,
                 n_partial: int = N_TOTAL_PARTIAL, n_edge_min: int = N_EDGE_MIN
                 ) -> frozenset[str]:
    """Every Sect. 4b group rule the image satisfies, as stated on pp. 1050-1051.

    ``tiny``: ``N_total < N*_total``. ``rejected_partial``: ``N_total <= 180`` and
    ``N_edge >= 4`` and ``N_y < 32``; also any image with a clear slice inside the shadowed
    zone (Fig. 3c). ``complete``: ``N_total > N*_total`` and ``N_edge < 4``.
    ``accepted_partial``: ``N_total > 180`` and (``N_edge >= 4`` or ``N_y == 32``).
    ``32`` is read as ``n_diodes`` (module docstring, reading 2). The rules overlap and
    leave gaps; the caller sees all of them (reading 1).
    """
    groups = set()
    if m.n_total < n_tiny:
        groups.add("tiny")
    full_span = m.ny == n_diodes
    if (m.n_total <= n_partial and m.n_edge >= n_edge_min and not full_span) \
            or m.interior_empty_slice:
        groups.add("rejected_partial")
    if m.n_total > n_tiny and m.n_edge < n_edge_min:
        groups.add("complete")
    if m.n_total > n_partial and (m.n_edge >= n_edge_min or full_span):
        groups.add("accepted_partial")
    return frozenset(groups)


def retrieval_group(groups: frozenset[str]) -> str | None:
    """``"complete"`` or ``"accepted_partial"`` when the image matches that rule and no
    other; ``None`` otherwise (excluded, or ambiguous under reading 1)."""
    if len(groups) == 1:
        (only,) = groups
        if only in ("complete", "accepted_partial"):
            return only
    return None


# --- The two ratios (Sect. 4c) -------------------------------------------------------------


def r1(m: ImageMeasures) -> float:
    """Eq. 1: ``R1 = pi (N_x^2 + N_y^2) / (8 N_total)`` -- for complete images."""
    return math.pi * (m.nx ** 2 + m.ny ** 2) / (8.0 * m.n_total)


def p_circ(n_edge1: float, n_edge2: float, ny: float) -> float:
    """Eq. 2: the in-frame perimeter of a circle cut by the array's two edges, in pixels.

    ``x1``, ``x2`` are the chords on the two edges and ``y`` the distance between them
    (all in pixel units; the paper's ``delta`` cancels in ``R2``). Fig. 5's geometry:
    ``z`` is the height of the cap beyond edge 1, ``theta1``/``theta2`` the central angles
    from the circle's far pole to the two chords' ends, and the arc inside the frame is
    ``2 (theta2 - theta1) r``. ``theta1`` takes its limit ``0`` at ``x1 == 0`` (reading 3).
    """
    x1, x2, y = float(n_edge1), float(n_edge2), float(ny)
    if y <= 0:
        raise ValueError("N_y must be positive")
    r = math.sqrt(x1 ** 2 / 4.0 + (y / 2.0 + (x2 ** 2 - x1 ** 2) / (8.0 * y)) ** 2)
    z = (x1 ** 2 - x2 ** 2) / (8.0 * y) - y / 2.0 + r
    theta1 = 0.0 if x1 == 0.0 else math.pi - 2.0 * math.atan(x1 / (2.0 * z))
    theta2 = math.pi - 2.0 * math.atan(x2 / (2.0 * (z + y)))
    return 2.0 * (theta2 - theta1) * r


def ks_perimeter(image) -> float:
    """Eq. 4: ``N_P = N_2 + sqrt(2) N_3``, by the five-step shift-and-sum of Fig. 7.

    Step 1: ``B`` = the image plus itself shifted one pixel along the array, twos to zero.
    Step 2: ``C``, the same along the flight direction. Step 3: ``D = B + C``. Step 4:
    ``E`` = ``B`` shifted one pixel back along the flight direction, plus ``C``. Step 5:
    ``F = E + D``, ones to zero; horizontal and vertical legs read 2, diagonal pixels 3
    (p. 1052). Frame padding and the partial-image edge exclusion follow reading 4.
    """
    img = _as_silhouette(image).astype(np.int8)
    n_slices, n_diodes = img.shape
    a = np.pad(img, ((1, 1), (0, 0)), mode="constant")          # clear beyond the slices
    a = np.pad(a, ((0, 0), (1, 1)), mode="edge")                 # the cut edge continues
    up = np.zeros_like(a)
    up[:, :-1] = a[:, 1:]                                         # shifted along the array
    b = (a + up) % 2                                              # twos to zero
    along = np.zeros_like(a)
    along[1:, :] = a[:-1, :]                                      # shifted along the flight
    c = (a + along) % 2                                           # (direction: reading 4)
    d = b + c
    b_right = np.zeros_like(b)
    b_right[1:, :] = b[:-1, :]
    e = b_right + c
    f = e + d
    f[f == 1] = 0
    inside = f[:, 1:n_diodes + 1]                                 # the array only
    n2 = int((inside == 2).sum())
    n3 = int((inside == 3).sum())
    return n2 + math.sqrt(2.0) * n3


def r2(image) -> float:
    """Eq. 3: ``R2 = P / P_circ`` -- for accepted partial images."""
    m = measure(image)
    return ks_perimeter(image) / p_circ(m.n_edge1, m.n_edge2, m.ny)


# --- Retrieval (Sect. 4d) ------------------------------------------------------------------


def retrieve_fractions(ratios: Iterable[float], matrix: RetrievalMatrix) -> np.ndarray:
    """Eqs. 5-8: the habit fractions ``f`` whose mixture of basis rows best gives ``M``.

    ``M_j`` is the normalised histogram of ``ratios`` over the matrix's intervals (Eq. 7),
    and Eq. 5 reads ``M = sum_i f_i B_i``, i.e. ``M = B^T f`` with ``B``'s rows the habits;
    ``f`` is its exact solution (the square system Eq. 8 inverts). Individual fractions can
    come out slightly negative for a sample that the basis does not describe exactly
    (Sect. 4d names Poisson noise and local shapes); they are returned as computed, never
    clipped, so the retrieval's own residual is visible.
    """
    values = np.asarray(list(ratios), dtype=float)
    if values.size == 0:
        raise ValueError("no ratios to retrieve from")
    counts, _ = np.histogram(values, bins=np.asarray(matrix.edges, dtype=float))
    m = counts / counts.sum()
    return np.linalg.solve(matrix.as_array().T, m)


def combine(f_complete: Sequence[float] | np.ndarray, n_complete: int,
            f_partial: Sequence[float] | np.ndarray, n_partial: int) -> np.ndarray:
    """Eq. 9: ``f = (N_c f_c + N_p f_p) / (N_c + N_p)`` over :data:`HABITS`.

    A 3-element ``f_complete`` (no dendrite row) is read as a zero dendrite fraction
    (reading 5). Widened to accept ``np.ndarray`` as well as ``Sequence[float]``: every
    real caller passes :func:`retrieve_fractions`'s ``np.ndarray`` return or ``[]``, and
    ``fc[:len(f_complete)] = f_complete`` already accepts either at runtime -- the
    ``Sequence[float]``-only annotation was narrower than what the function does.
    """
    fc = np.zeros(len(HABITS))
    fc[:len(f_complete)] = f_complete
    fp = np.zeros(len(HABITS))
    fp[:len(f_partial)] = f_partial
    total = n_complete + n_partial
    if total == 0:
        raise ValueError("no complete or partial images to combine")
    return (n_complete * fc + n_partial * fp) / total


def build_retrieval_matrix(labelled: Mapping[str, Iterable[float]], edges: Sequence[float], *,
                           ratio: str, n_diodes: int, pixel_um: float, probe: str,
                           source: str) -> RetrievalMatrix:
    """Eq. 6 from a hand-classified training set: ``B_ij`` = habit ``i``'s fraction in
    interval ``j``.

    This is how a matrix for a probe other than the OAP-2DC would be made (p. 1057). The
    interval edges are an input: the paper chose its edges by minimising ``B``'s condition
    number (Sect. 4d) without giving the search, so none is invented here -- the caller
    supplies edges and can read ``numpy.linalg.cond`` of the result.
    """
    habits = tuple(labelled)
    bins = np.asarray(edges, dtype=float)
    rows = []
    for habit in habits:
        values = np.asarray(list(labelled[habit]), dtype=float)
        if values.size == 0:
            raise ValueError(f"habit {habit!r} has no training images")
        counts, _ = np.histogram(values, bins=bins)
        rows.append(tuple(float(v) for v in counts / counts.sum()))
    if len(habits) != len(edges) - 1:
        raise ValueError("RABIT's matrix is square: one interval per habit category "
                         f"(Sect. 4d); got {len(habits)} habits and {len(edges) - 1} intervals")
    return RetrievalMatrix(ratio=ratio, habits=habits, edges=tuple(float(e) for e in edges),
                           rows=tuple(rows), n_diodes=n_diodes, pixel_um=pixel_um,
                           probe=probe, source=source)


# --- The population entry point -------------------------------------------------------------


@dataclass(frozen=True)
class PopulationResult:
    """What :func:`classify_population` found for one ensemble of images.

    ``groups`` counts each distinct matched-rule set (so an ambiguous image is visible as
    such, never folded into a group); ``n_complete``/``n_partial`` are the images retrieved
    as each; ``fractions`` is Eq. 9's combined vector over :data:`HABITS`, or ``None`` when
    :func:`census` was all that was asked for.
    """

    groups: dict[str, int]
    n_complete: int
    n_partial: int
    f_complete: tuple[float, ...] | None
    f_partial: tuple[float, ...] | None
    fractions: tuple[float, ...] | None


def _group_key(groups: frozenset[str]) -> str:
    return "+".join(sorted(groups)) if groups else "unassigned"


def census(images: Iterable, n_diodes: int) -> PopulationResult:
    """Sort an ensemble into Sect. 4b's groups, without retrieving any habit.

    Needs no retrieval matrix, so it runs on any probe: it answers how many images RABIT
    would classify as partials that a complete-images-only scheme would not.
    """
    counts: dict[str, int] = {}
    n_c = n_p = 0
    for image in images:
        g = image_groups(measure(image), n_diodes)
        key = _group_key(g)
        counts[key] = counts.get(key, 0) + 1
        which = retrieval_group(g)
        n_c += which == "complete"
        n_p += which == "accepted_partial"
    return PopulationResult(dict(sorted(counts.items())), n_c, n_p, None, None, None)


def _check_probe(matrix: RetrievalMatrix, n_diodes: int, pixel_um: float) -> None:
    if matrix.n_diodes != n_diodes or not math.isclose(matrix.pixel_um, pixel_um):
        raise NoRetrievalMatrixForProbe(
            f"{matrix.ratio} matrix was built for {matrix.probe} ({matrix.n_diodes} diodes, "
            f"{matrix.pixel_um:g} um); these images are {n_diodes} diodes at {pixel_um:g} um. "
            "Korolev & Sussman (2000) p. 1057: new retrieval matrices should be created for "
            "different probe configurations -- build one with build_retrieval_matrix() from a "
            "hand-classified training set of this probe's images.")


def classify_population(images: Sequence, *, n_diodes: int, pixel_um: float,
                        complete: RetrievalMatrix = KS2000_OAP2DC_COMPLETE,
                        partial: RetrievalMatrix = KS2000_OAP2DC_PARTIAL) -> PopulationResult:
    """RABIT over one ensemble: groups, ``R1``/``R2``, both retrievals, and Eq. 9.

    Raises :class:`NoRetrievalMatrixForProbe` before reading a single image when either
    matrix's probe differs from ``(n_diodes, pixel_um)`` -- the shipped defaults are the
    OAP-2DC's, so on a 2D-S or HVPS this is a refusal until a matrix for that probe exists.
    A group with no images contributes nothing (its fraction vector is ``None``).
    """
    _check_probe(complete, n_diodes, pixel_um)
    _check_probe(partial, n_diodes, pixel_um)
    images = list(images)
    counts: dict[str, int] = {}
    r1_values: list[float] = []
    r2_values: list[float] = []
    for image in images:
        m = measure(image)
        g = image_groups(m, n_diodes)
        key = _group_key(g)
        counts[key] = counts.get(key, 0) + 1
        which = retrieval_group(g)
        if which == "complete":
            r1_values.append(r1(m))
        elif which == "accepted_partial":
            r2_values.append(r2(image))
    fc = retrieve_fractions(r1_values, complete) if r1_values else None
    fp = retrieve_fractions(r2_values, partial) if r2_values else None
    fractions = None
    if fc is not None or fp is not None:
        fractions = tuple(float(v) for v in combine(
            fc if fc is not None else [], len(r1_values),
            fp if fp is not None else [], len(r2_values)))
    return PopulationResult(
        dict(sorted(counts.items())), len(r1_values), len(r2_values),
        None if fc is None else tuple(float(v) for v in fc),
        None if fp is None else tuple(float(v) for v in fp),
        fractions)
