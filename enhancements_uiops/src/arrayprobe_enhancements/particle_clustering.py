# SPDX-License-Identifier: BSD-3-Clause
"""Unsupervised clustering of particle populations -- group similar particles
so one human verdict on a cluster's medoid covers every particle in it,
instead of reviewing particles one at a time.

Why this exists, user-directed 2026-08-27: task #24's manual re-screen and
the "Particle Triage" tool (`arrayprobe.triage_server`) both operate one
particle at a time. A proc file routinely holds 10^4-10^6 particles --
one-at-a-time labeling can never reach that population, and it hadn't:
"if further labelling wont help, you are not doing your job, find out
clusters using whatever tool you can." Clustering is that tool: it turns
"label N particles" into "label K clusters," where K is small enough for a
human to actually review in one sitting.

This is real new science, not a port-fidelity concern -- UIOOPS never
clustered particles -- so it lives here, not in `arrayprobe`. The GUI that
calls it (`arrayprobe.triage_server`'s `/clusters/<flight>` route) is core,
through one optional try/except import, exactly like the existing
`ml_accept_reject.predict` CNN-suggestion hook.

Design choices, and why:

- **Features are scalar fields S3/S4 already wrote to every proc file**
  (image_length, image_width, image_diam_minR, image_diam_circle_fit,
  image_perimeter, percent_shadow_area, max_hole_diameter, area_hole_ratio)
  -- never a fresh image reconstruction per particle. Reading eight netCDF
  arrays and standardizing them is seconds even at 10^5-10^6 particles; the
  per-particle image reconstruction `render.py` does is the expensive step
  this module avoids doing per-particle. `image_axis_ratio` is deliberately
  excluded: it is documented elsewhere as a degenerate
  branch indicator, not a real shape statistic, and would only add noise.

- **k-means, hand-rolled in numpy.** No new dependency: neither scipy nor
  scikit-learn is installed in either venv (checked 2026-08-27), and this
  project's own convention (opt-in extras in `pyproject.toml`) is to keep heavy
  optional deps out unless a stage genuinely needs them. k-means++ seeding
  plus a few restarts is small and exactly reproducible.

- **Fit on a bounded subsample, then assign the full population in one
  pass.** Lloyd's iteration is the expensive part; a single nearest-center
  assignment (no iteration) is cheap at any n. This is what makes
  `cluster_flight` tractable on an entire flight's population rather than
  the few-hundred-particle samples used so far.

- **Representative = medoid, never a pixel-averaged composite.** Averaging
  particle images washes out exactly the shape detail (holes, ragged edges,
  diode dropouts) a human needs to make the artifact/real call -- this was
  the "super images" question, resolved in
  favor of medoid. The medoid is the real particle (by proc index) nearest
  its cluster's centroid in standardized feature space; only that one
  particle is ever rendered as an image, so cost stays independent of
  cluster size.

- **k chosen by an elbow heuristic on inertia**, computed on the same fit
  subsample, not silhouette (O(n^2), infeasible past a few thousand points)
  and not a fixed constant (accepted/rejected populations differ enormously
  in size and shape diversity across flights).
"""

from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from pathlib import Path

import netCDF4
import numpy as np

from .hole_edge_swap import correct_hole_edge_swap

__all__ = [
    "FEATURE_NAMES",
    "MissingProcVariable",
    "feature_names_for",
    "ClusterResult",
    "extract_features",
    "choose_k",
    "kmeans",
    "cluster_flight",
]

#: Scalar per-particle fields read directly from every proc file. Chosen for
#: shape/size discrimination; image_axis_ratio is excluded (degenerate, see
#: module docstring). "compactness" is not a netCDF field -- it is derived
#: below from image_perimeter and image_area -- but is listed here too so it
#: gets the same log-transform/standardize/cluster_stats treatment as
#: everything else without a second bookkeeping path.
#:
#: 2026-09-14: ``image_diam_circle_fit`` is v3.1.4-only -- v3.5's
#: ``imgProc_sm.m`` comments the whole ``defVar`` call out
#: (``UIOPS-v3.5/joefinlon-UIOPS-039be82/imgProc_sm.m:455-458``, confirmed by
#: opening the lines) and ``arrayprobe_uiops/imgproc.py:262`` never writes the
#: column, so a v3.5 proc file genuinely has no such variable. This constant
#: keeps its v3.1.4 shape for backward compatibility (the triage server does
#: not import it, but external callers may); use :func:`feature_names_for`
#: for the per-engine list, which :func:`extract_features` and
#: :func:`cluster_flight` now use instead of this module-level constant.
_NC_FEATURE_NAMES = (
    "image_length",
    "image_width",
    "image_diam_minR",
    "image_diam_circle_fit",
    "image_perimeter",
    "image_area",
    "percent_shadow_area",
    "max_hole_diameter",
    "area_hole_ratio",
)
FEATURE_NAMES = _NC_FEATURE_NAMES + ("compactness",)

#: v3.5 has no ``image_diam_circle_fit`` column -- see the constant above.
_V35_DROPPED = frozenset({"image_diam_circle_fit"})


class MissingProcVariable(Exception):
    """A feature column ``extract_features`` needs is not in this proc file.

    Raised instead of letting a bare ``netCDF4``/dict ``KeyError`` propagate,
    so a caller can tell "this proc file is missing a column the current
    engine never writes" from any other ``KeyError`` in its own code.
    this is the discriminating refusal for the v3.5 ``image_diam_circle_fit``
    gap.
    """

    def __init__(self, name: str, detail: str):
        super().__init__(f"{name}: {detail}")
        self.name = name


def feature_names_for(engine: str = "3.1.4") -> tuple[str, ...]:
    """The public feature-column order for ``engine`` -- ``FEATURE_NAMES`` on
    v3.1.4, the same list minus ``image_diam_circle_fit`` on v3.5 (see
    ``_V35_DROPPED``'s docstring above). Any other ``engine`` value is a
    caller error -- refused rather than silently defaulting."""
    if engine == "3.1.4":
        return FEATURE_NAMES
    if engine == "3.5":
        return tuple(n for n in _NC_FEATURE_NAMES if n not in _V35_DROPPED) + ("compactness",)
    raise ValueError(f"unknown engine {engine!r}, expected '3.1.4' or '3.5'")


def _nc_names_for(engine: str) -> tuple[str, ...]:
    """The netCDF-column subset of :func:`feature_names_for` (no
    ``compactness``, which is derived, never read)."""
    return feature_names_for(engine)[:-1]


def extract_features(
    proc_path: Path, group: str = "accepted", nc_lock: AbstractContextManager | None = None,
    *, engine: str = "3.1.4",
) -> tuple[np.ndarray, np.ndarray]:
    """Return (particle_indices, raw_feature_matrix) for `group` particles.

    group: "accepted" (image_auto_reject in "0HhuR"), "rejected", or "all".
    Vectorized: reads each of the netCDF fields once, no per-particle loop,
    so this is cheap regardless of population size.

    ``engine`` selects the column list via :func:`feature_names_for`
    -- default ``"3.1.4"`` keeps every prior caller's behaviour byte-for-byte
    (same columns, same order). Pass ``engine="3.5"`` against a v3.5 proc
    file, which does not carry ``image_diam_circle_fit``. Reading a column
    this engine's proc file genuinely lacks raises :class:`MissingProcVariable`
    naming the column, never a bare ``KeyError``.

    ``nc_lock``, if given, is held only around the ``netCDF4.Dataset`` open and
    read below -- not around this whole function, and never around
    :func:`cluster_flight`'s k-means fit. A caller running under a
    multi-threaded server (`arrayprobe.triage_server`) needs this: netCDF4's
    underlying HDF5 C library is not guaranteed thread-safe for concurrent
    opens/reads across threads (see `triage_server.py`'s `_NC_LOCK` and
    the lock it guards, for the real crash this
    caused). Locking the WHOLE clustering call, as a first fix here did, is
    also safe but serializes every flight's ~20s k-means fit behind one
    global lock -- a real, measured usability regression (a real concurrent
    stress test against 4 real flights went from crashing to 90+s timeouts).
    Scoping the lock to just the I/O below keeps the fix's safety without
    that cost: the netCDF4 read is fast (a handful of whole-flight arrays),
    so multiple flights' clustering can still make real concurrent progress
    on the numpy-only work that follows.
    """
    from arrayprobe_uiops.sizedist_core import GOOD_REJECT_CODES

    def is_accepted_code(codes):
        return np.isin(codes, [ord(c) for c in GOOD_REJECT_CODES])

    nc_names = _nc_names_for(engine)
    lock_cm = nc_lock if nc_lock is not None else nullcontext()
    with lock_cm, netCDF4.Dataset(proc_path) as ds:
        rc = np.asarray(ds.variables["image_auto_reject"][:])
        if group == "accepted":
            idx = np.where(is_accepted_code(rc))[0]
        elif group == "rejected":
            idx = np.where(~is_accepted_code(rc))[0]
        elif group == "all":
            idx = np.arange(len(rc))
        else:
            raise ValueError(f"group must be 'accepted', 'rejected', or 'all', got {group!r}")
        cols = []
        for name in nc_names:
            if name not in ds.variables:
                raise MissingProcVariable(
                    name, f"not written by the {engine} engine "
                          "(arrayprobe_uiops/imgproc.py:262); pass engine='3.5'"
                          if engine == "3.5" else
                          "not present in this proc file")
            cols.append(np.asarray(ds.variables[name][:], dtype=np.float64)[idx])
        # The upstream swapped hole variables: max_hole_diameter and edge_at_max_hole are
        # written into each other's netCDF slot (imgProc_sm.m:919-920). Read
        # the sibling and unswap before using max_hole_diameter as a
        # clustering feature -- about 1.7% of particles differ (measured,
        # enhancements_uiops/docs/CORRECTIONS.md, part `hole_edge_swap.py`), and there is no reason to cluster on
        # the mislabeled value when the correction is one function call away.
        raw_edge_at_max_hole = np.asarray(ds.variables["edge_at_max_hole"][:], dtype=np.float64)[idx]
        mh_i = nc_names.index("max_hole_diameter")
        cols[mh_i], _ = correct_hole_edge_swap(cols[mh_i], raw_edge_at_max_hole)
        X = np.stack(cols, axis=1)
    # A field can carry a non-finite value for a particle the relevant
    # computation never ran for (e.g. max_hole_diameter with no hole).
    # Treat that as 0 rather than dropping the particle -- "no hole" is
    # itself informative for clustering, not missing data.
    X = np.where(np.isfinite(X), X, 0.0)

    area_i = nc_names.index("image_area")
    perim_i = nc_names.index("image_perimeter")
    area = np.clip(X[:, area_i], 1e-9, None)
    compactness = (X[:, perim_i] ** 2) / (4 * np.pi * area)
    X = np.concatenate([X, compactness[:, None]], axis=1)
    return idx, X


#: Size-like fields span decades (a proc file's accepted population is
#: dominated by particles near the detection floor -- physically expected,
#: OAP size distributions are steeply decreasing). Clustering on raw values
#: lets k-means slice through that single dense near-zero peak instead of
#: separating genuinely different populations elsewhere in the range, so
#: these columns are log1p-transformed before standardizing. Ratio-like
#: fields (percent_shadow_area, area_hole_ratio) are already bounded and are
#: left alone.
_LOG_FEATURES = frozenset({
    "image_length", "image_width", "image_diam_minR", "image_diam_circle_fit",
    "image_perimeter", "image_area", "max_hole_diameter", "compactness",
})


def _feature_space(X: np.ndarray, names: tuple[str, ...] = FEATURE_NAMES) -> np.ndarray:
    """Raw feature matrix -> the space clustering distance is computed in
    (log1p on size-like columns). Kept separate from the raw matrix so
    cluster_stats can still report physically interpretable means.

    ``names`` is the column order the matrix was built with --
    defaults to the v3.1.4 ``FEATURE_NAMES`` for backward compatibility;
    :func:`cluster_flight` always passes its own resolved list."""
    Xt = X.copy()
    for i, name in enumerate(names):
        if name in _LOG_FEATURES:
            Xt[:, i] = np.log1p(np.clip(Xt[:, i], 0, None))
    return Xt


def _standardize(X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mean = X.mean(axis=0)
    std = X.std(axis=0)
    std = np.where(std == 0, 1.0, std)
    return (X - mean) / std, mean, std


def _sq_dists_to_centers(Xs: np.ndarray, centers: np.ndarray) -> np.ndarray:
    """(n, k) squared-distance matrix, computed one center at a time so peak
    memory is O(n*k) rather than O(n*k*d)."""
    n, k = Xs.shape[0], centers.shape[0]
    d2 = np.empty((n, k))
    for j in range(k):
        diff = Xs - centers[j]
        d2[:, j] = np.einsum("ij,ij->i", diff, diff)
    return d2


def _kmeans_once(Xs: np.ndarray, k: int, max_iter: int, rng: np.random.Generator):
    n = Xs.shape[0]
    centers = np.empty((k, Xs.shape[1]))
    centers[0] = Xs[rng.integers(n)]
    closest_sq = np.sum((Xs - centers[0]) ** 2, axis=1)
    for i in range(1, k):
        total = closest_sq.sum()
        probs = closest_sq / total if total > 0 else None
        nxt = rng.choice(n, p=probs) if probs is not None else rng.integers(n)
        centers[i] = Xs[nxt]
        d = np.sum((Xs - centers[i]) ** 2, axis=1)
        closest_sq = np.minimum(closest_sq, d)

    labels = np.full(n, -1, dtype=np.int64)
    for it in range(max_iter):
        d2 = _sq_dists_to_centers(Xs, centers)
        new_labels = np.argmin(d2, axis=1)
        if it > 0 and np.array_equal(new_labels, labels):
            labels = new_labels
            break
        labels = new_labels
        for j in range(k):
            mask = labels == j
            if mask.any():
                centers[j] = Xs[mask].mean(axis=0)
    d2 = _sq_dists_to_centers(Xs, centers)
    inertia = float(np.sum(np.min(d2, axis=1)))
    return labels, centers, inertia


def kmeans(X: np.ndarray, k: int, max_iter: int = 100, n_init: int = 5, seed: int = 0):
    """Lloyd's algorithm with k-means++ seeding and n_init restarts; returns
    the (labels, centers, inertia) of the lowest-inertia restart."""
    if k < 1:
        raise ValueError("k must be >= 1")
    if k > X.shape[0]:
        raise ValueError(f"k={k} exceeds population {X.shape[0]}")
    rng = np.random.default_rng(seed)
    best = None
    for _ in range(n_init):
        result = _kmeans_once(X, k, max_iter, rng)
        if best is None or result[2] < best[2]:
            best = result
    return best


def choose_k(X: np.ndarray, k_range: range = range(4, 21), n_init: int = 2, seed: int = 0) -> int:
    """Elbow-detect k from inertia(k) over k_range: the k whose (k, inertia)
    point is farthest, perpendicular, from the line joining the range's
    first and last points. Deterministic, no scipy/sklearn needed."""
    ks = list(k_range)
    if len(ks) <= 2:
        return ks[0] if ks else 1
    ks = [k for k in ks if k <= X.shape[0]]
    inertias = [kmeans(X, k, n_init=n_init, seed=seed)[2] for k in ks]
    pts = np.array(list(zip(ks, inertias)), dtype=np.float64)
    # normalize both axes to [0, 1] so "perpendicular distance" isn't
    # dominated by inertia's much larger numeric range
    span = pts.max(axis=0) - pts.min(axis=0)
    span = np.where(span == 0, 1.0, span)
    norm = (pts - pts.min(axis=0)) / span
    p0, p1 = norm[0], norm[-1]
    line = p1 - p0
    line_len = np.linalg.norm(line)
    if line_len == 0:
        return ks[0]
    line_unit = line / line_len
    diffs = norm - p0
    proj_len = diffs @ line_unit
    proj = p0 + np.outer(proj_len, line_unit)
    dist = np.linalg.norm(norm - proj, axis=1)
    return ks[int(np.argmax(dist))]


@dataclass
class ClusterResult:
    proc_path: Path
    group: str
    k: int
    feature_names: tuple
    particle_indices: np.ndarray  # original proc-file indices, full filtered population
    labels: np.ndarray  # cluster id per entry of particle_indices
    medoid_particle_index: dict = field(default_factory=dict)  # cluster id -> proc index
    cluster_size: dict = field(default_factory=dict)  # cluster id -> count
    cluster_stats: dict = field(default_factory=dict)  # cluster id -> {feature: mean}

    def members(self, cluster_id: int) -> np.ndarray:
        """Original proc-file particle indices belonging to `cluster_id`."""
        return self.particle_indices[self.labels == cluster_id]

    def clusters_by_size(self) -> list[int]:
        return sorted(self.cluster_size, key=lambda c: -self.cluster_size[c])


def cluster_flight(
    proc_path: Path,
    group: str = "accepted",
    k: int | None = None,
    k_range: range = range(4, 21),
    max_fit_n: int = 50_000,
    seed: int = 0,
    nc_lock: AbstractContextManager | None = None,
    engine: str = "3.1.4",
) -> ClusterResult:
    """Cluster every `group` particle in `proc_path`.

    Fits k-means on a bounded subsample (`max_fit_n`) for tractability, then
    assigns the FULL filtered population to the nearest fitted center in one
    pass -- so this scales to an entire flight, not just a few hundred
    particles. Picks its own k via `choose_k` if `k` is not given.

    ``nc_lock`` passes straight through to :func:`extract_features` -- see its
    docstring. It guards only the netCDF4 read at the very top of this
    function, never the k-means fit that follows, which is what lets multiple
    flights' calls make real concurrent progress under a threaded caller.

    ``engine`` selects the feature-column list via
    :func:`feature_names_for`; default ``"3.1.4"`` is unchanged from before
    this parameter existed.
    """
    names = feature_names_for(engine)
    idx, X = extract_features(proc_path, group, nc_lock=nc_lock, engine=engine)
    if len(idx) == 0:
        raise ValueError(f"no {group!r} particles in {proc_path}")
    Xs, _mean, _std = _standardize(_feature_space(X, names))

    rng = np.random.default_rng(seed)
    fit_n = min(max_fit_n, len(idx))
    fit_sel = rng.choice(len(idx), size=fit_n, replace=False)
    Xfit = Xs[fit_sel]

    if k is None:
        k = choose_k(Xfit, k_range=range(k_range.start, min(k_range.stop, fit_n + 1)), seed=seed)
    _labels_fit, centers, _inertia = kmeans(Xfit, k, seed=seed)

    d2_full = _sq_dists_to_centers(Xs, centers)
    labels_full = np.argmin(d2_full, axis=1)

    medoids, sizes, stats = {}, {}, {}
    for j in range(k):
        mask = labels_full == j
        n = int(mask.sum())
        sizes[j] = n
        if n == 0:
            continue
        medoids[j] = int(idx[mask][np.argmin(d2_full[mask, j])])
        stats[j] = {name: float(X[mask, i].mean()) for i, name in enumerate(names)}

    return ClusterResult(
        proc_path=proc_path,
        group=group,
        k=k,
        feature_names=names,
        particle_indices=idx,
        labels=labels_full,
        medoid_particle_index=medoids,
        cluster_size=sizes,
        cluster_stats=stats,
    )
