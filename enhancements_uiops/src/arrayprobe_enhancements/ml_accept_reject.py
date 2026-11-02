# SPDX-License-Identifier: BSD-3-Clause
"""Per-particle accept/reject classification beyond UIOOPS's own rule-based ladder.

**Method A — diode-occupancy heuristic — implemented and evaluated on real data.**
Not a trained model: a single hand-derived statistic, `max_col_occ`, that formalizes the
signature this project's own manual QA work found by
eye across four independent flights before any code existed for it. A stuck photodiode makes
one column of the particle's shadow image dark for essentially the particle's *entire* span --
unlike a real drop's transient, sparse shadow -- so the maximum per-column occupancy fraction is
close to 1.0 for most stuck-diode-merge artifacts and usually lower for a real particle.
**The real evaluation finds genuine overlap, not a clean separator** (12 of 16 confirmed
artifacts caught at the chosen threshold; zero confirmed-real particles false-positive). The
labeled set is the reviewed one: review changed six of the original 22 labels, among them
idx 965074, which is a confirmed artifact that Method A calls correctly. See the design doc's
"Method A: real evaluation" for the full before/after.

**Method B — the labeled-data pipeline and a numpy-only trained baseline.**
The CNN itself is *not* here, and the reason is stated plainly rather than worked around: no
deep-learning framework is installed in this project's venv (checked directly -- no `torch`, no
`tensorflow`, no `keras`, and `scikit-learn` is absent too), and adding one is a dependency
decision for the user, not something an autonomous pass should make. What is genuinely blocking
a CNN is *not* the framework anyway -- it is the labeled set, which is **21 usable particles**.
So this module ships the two parts that are real work and are prerequisites for any model at
all, framework or not:

1. **The data pipeline** -- `human_labeled_particles` reads the triage tool's own verdict
   sidecars (read-only, never written), `load_shadows` renders each labeled particle through
   `arrayprobe.render.reconstruct_particle_image`, and `particle_features` turns a shadow image
   into a fixed-length vector regardless of the particle's own size. Swap the last step for a
   convolutional stack and the rest is unchanged.
2. **A numpy-only trained baseline** -- L2-regularised logistic regression
   (`fit_logistic`) on pooled-occupancy features, evaluated by leave-one-out cross-validation
   (`leave_one_out`), which is the only honest held-out protocol at n=21. Reported against a
   majority-class baseline every time, because at 16-vs-5 class balance a model can score 76%
   by predicting one class forever, and a number quoted without that comparison is meaningless.

**Jaffeux weights are not usable**: the Jaffeux et al. 2022
(AMT 15, 5141) release has no LICENSE file in its GitHub repo and Zenodo lists only "Other
(Open)" with no terms, so their trained weights are not something this BSD-3-Clause project can
redistribute or fine-tune from. Their published *architecture* is legitimate to read and be
informed by (ideas aren't copyrightable); `TORCH_CNN_REQUIREMENTS` below records exactly what a
fresh-trained CNN would need, so that decision can be made on facts rather than re-derived.

`src/arrayprobe/` never imports this module. Read-only with respect to the port's
own output -- like `particle_clustering.py`, this never changes what `arrayprobe` computes or
writes; it reads a proc/image file pair and returns its own, separate opinion. It is also
read-only with respect to **human labels**: nothing in this file opens a verdict sidecar for
writing, and `test_ml_accept_reject_methodb.py` asserts that by hashing the file across a load.
That is deliberate -- a bulk-labeling pass on 2026-08-27 mass-mislabeled ~2.69M particles
across three flights, and those files are evidence now, not a scratch pad.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

__all__ = [
    # Method A
    "max_col_occ",
    "ArtifactCall",
    "classify_stuck_diode_artifact",
    "DEFAULT_THRESHOLD",
    # Method B -- labeled data
    "LabeledParticle",
    "BULK_LABEL_NOTE_PREFIX",
    "REVIEWED_LABELS",
    "read_verdict_sidecar",
    "human_labeled_particles",
    "load_shadows",
    # Method B -- features
    "DEFAULT_GRID",
    "SCALAR_FEATURE_NAMES",
    "pool_to_grid",
    "particle_features",
    "feature_names",
    "build_dataset",
    # Method B -- model + evaluation
    "LogisticModel",
    "fit_logistic",
    "LooResult",
    "leave_one_out",
    "majority_class_accuracy",
    "evaluate_labeled_set",
    "TORCH_CNN_REQUIREMENTS",
]

#: Measured against the full reviewed real labeled set (22 particles across 6
#: flights, one excluded as a mixed/complex detection -- see docs/ml_accept_reject_design.md's
#: "Method A: real evaluation" for every value). NOT a clean separator: at 0.90, Method A
#: catches 12 of 16 confirmed artifacts (the 4 missed range 0.75-0.86) with ZERO confirmed-real
#: false positives -- the highest confirmed-real (0.80) and lowest confirmed-artifact (0.75)
#: genuinely overlap. 0.90 is kept as
#: the default because it is the best single-feature trade-off found (clean precision, 75%
#: recall), not because it separates cleanly; a caller that cares more about recall than
#: precision should lower it toward 0.75 and accept more false positives.
DEFAULT_THRESHOLD = 0.90


def max_col_occ(shadow: np.ndarray) -> float:
    """The stuck-diode-merge signature: the most-occupied diode column's shadow fraction.

    ``shadow`` is the boolean ``(n_slices, n_diodes)`` array
    :func:`arrayprobe.render.reconstruct_particle_image` returns (``True`` = shadowed).
    Returns the maximum, over diode columns, of the fraction of slices that column is
    shadowed in. A real particle's shadow moves across diodes as it crosses the array, so
    no single column stays dark for the whole detection; a diode stuck permanently dark
    (or dark for the particle's whole window) drives one column's occupancy to ~1.0
    regardless of what the rest of the shadow looks like.

    Returns ``0.0`` for a particle with no slices (should not occur in practice; a proc
    file's own ``position`` bounds guarantee at least one row, but this keeps the function
    total rather than raising on a malformed input).
    """
    if shadow.shape[0] == 0:
        return 0.0
    return float(shadow.mean(axis=0).max())


@dataclass(frozen=True)
class ArtifactCall:
    """One particle's Method-A verdict, with the number the call was made from."""

    max_col_occ: float
    is_artifact: bool
    threshold: float


def classify_stuck_diode_artifact(
    shadow: np.ndarray, threshold: float = DEFAULT_THRESHOLD,
) -> ArtifactCall:
    """Method A's whole contract: one shadow image in, one call out.

    Deliberately narrow -- this catches the *stuck-diode-merge* failure mode specifically
    (at 0.90 it catches 12 of the 16 particles labeled ``artifact`` in ``REVIEWED_LABELS``,
    the 22-particle reviewed set less its one ``mixed`` case). Two real particles
    merged in one frame are a different mechanism this heuristic is not expected to catch,
    see the design doc's "What Method A does not catch" section.
    It is not a general accept/reject classifier and does not claim to replace the
    false-reject side of this module's scope, which has no implementation yet.
    """
    occ = max_col_occ(shadow)
    return ArtifactCall(max_col_occ=occ, is_artifact=occ >= threshold, threshold=threshold)


# ---------------------------------------------------------------------------
# Method B, part 1: the labeled-data pipeline
# ---------------------------------------------------------------------------

#: Every verdict written by ``triage_server``'s ``/verdict_bulk`` route carries this note
#: prefix. **Those labels are excluded by default and that is not a stylistic choice.** On
#: 2026-08-27 an autonomous bulk-labeling pass wrote ~2.69 million such verdicts across three
#: flights -- 99.9%+ of each flight's particles labeled "artifact" from a single click per
#: k-means cluster, without the medoid being inspected. That incident led to a
#: standing ban on further bulk labeling. Loading them as training data would train a model to
#: reproduce that mistake, so `human_labeled_particles` drops them unless a caller explicitly
#: asks for them (`exclude_bulk=False`) knowing what they are.
BULK_LABEL_NOTE_PREFIX = "cluster bulk label"


@dataclass(frozen=True)
class LabeledParticle:
    """One human verdict: which flight, which 0-based proc-file particle index, what label."""

    flight: str
    particle_index: int
    label: str
    note: str = ""


#: The 22-particle set reviewed one particle at a time through
#: ``triage_server.py --queue-file`` (`docs/method_a_review_queue.json`); review changed six of
#: the original labels -- see `docs/ml_accept_reject_design.md`'s "Method A: real evaluation"
#: for the full before/after table.
#:
#: **This registry is the authoritative copy, and it has to be**, which is itself a finding.
#: Only 14 of these 22 verdicts survive in `_decoded/triage_verdicts/*.json` today: the
#: 2026-08-27 bulk pass overwrote the individually-reviewed entries for `base160910102201`
#: (all four of them) and four more elsewhere. Recovering the
#: labeled set from the sidecars alone recovers 14 of 22; this list is where the other 8 live.
REVIEWED_LABELS: tuple[LabeledParticle, ...] = tuple(
    LabeledParticle(flight, idx, label)
    for flight, idx, label in [
        ("base160906064403", 1, "real"),
        ("base160906064403", 5404, "real"),
        # "mixed": one real droplet plus a stuck diode plus other artifacts in one detection,
        # as labelled by the reviewer. Not one of the tool's three buttons (a real
        # taxonomy gap, see the design doc) and excluded from every binary metric below.
        ("base160906064403", 40860, "mixed"),
        ("base160910102201", 292254, "artifact"),      # re-review: was "real"
        ("base160914093925", 965074, "artifact"),      # re-review: was "real"
        ("base160906064403", 7319, "real"),
        # A14 mechanism (two real particles merged by imgProc_sm's boundary scan) -- "real"
        # is the closest of the three buttons, not a plain accept.
        ("base160910124240", 5716830, "real"),
        ("base160914124937", 320959, "artifact"),
        ("base160910102201", 1047966, "artifact"),
        ("base160910102201", 1974577, "artifact"),
        ("base160914093925", 737247, "artifact"),
        ("base160920135030", 2741517, "artifact"),
        ("base160920135030", 2615049, "artifact"),
        ("base160920135030", 2886543, "artifact"),
        ("base160914093925", 697667, "artifact"),
        ("base160920135030", 3340354, "artifact"),
        ("base160914093925", 737894, "artifact"),
        ("base160910124240", 5718294, "artifact"),     # re-review: was "unsure"
        ("base160910124240", 5715466, "artifact"),     # re-review: was "unsure"
        ("base160914124937", 2109304, "real"),         # re-review: was "unsure"
        ("base160914093925", 982873, "artifact"),
        ("base160910102201", 2598801, "artifact"),
    ]
)


def read_verdict_sidecar(path: Path | str) -> dict[str, dict]:
    """The raw contents of one ``triage_verdicts/<flight>.json``, **read-only**.

    Deliberately a thin, obvious function rather than an import from
    ``arrayprobe.triage_server``: that module's ``_load_verdicts`` sits beside
    ``_save_verdict``/``_save_verdicts_bulk`` in the same file, and this package must not
    have a code path that can reach a writer at all. Missing file returns ``{}``, matching
    the tool's own behaviour for a flight nobody has labeled yet.
    """
    p = Path(path)
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def human_labeled_particles(
    verdicts_dir: Path | str,
    *,
    flights: list[str] | None = None,
    exclude_bulk: bool = True,
    labels: tuple[str, ...] = ("artifact", "real"),
) -> list[LabeledParticle]:
    """Every individually-reviewed verdict in a ``triage_verdicts/`` directory.

    ``flights`` restricts to named flights (default: every ``*.json`` present). ``labels``
    keeps only the verdicts in that set -- ``"unsure"`` and ``"mixed"`` are dropped by
    default because neither is a training target, not because they are uninteresting.
    ``exclude_bulk`` drops every verdict whose note starts with
    :data:`BULK_LABEL_NOTE_PREFIX`; see that constant for why the default is ``True``.

    Nothing here opens a file for writing.
    """
    root = Path(verdicts_dir)
    if not root.is_dir():
        return []
    out: list[LabeledParticle] = []
    for path in sorted(root.glob("*.json")):
        flight = path.stem
        if flights is not None and flight not in flights:
            continue
        for key, entry in read_verdict_sidecar(path).items():
            note = str(entry.get("note", ""))
            if exclude_bulk and note.startswith(BULK_LABEL_NOTE_PREFIX):
                continue
            verdict = str(entry.get("verdict", ""))
            if verdict not in labels:
                continue
            out.append(LabeledParticle(flight, int(key), verdict, note))
    return out


def load_shadows(
    labeled: list[LabeledParticle], decoded_dir: Path | str,
) -> list[tuple[LabeledParticle, np.ndarray]]:
    """Render each labeled particle's shadow image from the decoded flight files.

    ``decoded_dir`` holds ``proc.<flight>.H.nc`` and ``<flight>.H.cdf`` pairs. Both are
    opened in netCDF's read mode explicitly; every image comes from
    :func:`arrayprobe.render.reconstruct_particle_image`, never a reimplementation. Labeled
    particles whose flight has no decoded pair on disk are skipped silently -- a fresh clone
    has none of them, and that must not be an error.
    """
    import netCDF4  # noqa: PLC0415  (heavy, only needed here
    from arrayprobe.render import reconstruct_particle_image  # for the real-data path)

    root = Path(decoded_dir)
    by_flight: dict[str, list[LabeledParticle]] = {}
    for item in labeled:
        by_flight.setdefault(item.flight, []).append(item)

    out: list[tuple[LabeledParticle, np.ndarray]] = []
    for flight, items in sorted(by_flight.items()):
        proc_path = root / f"proc.{flight}.H.nc"
        image_path = root / f"{flight}.H.cdf"
        if not proc_path.exists() or not image_path.exists():
            continue
        proc = netCDF4.Dataset(proc_path, mode="r")
        image = netCDF4.Dataset(image_path, mode="r")
        try:
            for item in items:
                out.append((item, reconstruct_particle_image(image, proc, item.particle_index)))
        finally:
            image.close()
            proc.close()
    return out


# ---------------------------------------------------------------------------
# Method B, part 2: fixed-length features from a variable-size shadow image
# ---------------------------------------------------------------------------

#: Pooled-occupancy grid shape, ``(rows, cols)`` = ``(slices, diodes)``. 4x4 = 16 pooled
#: features, chosen against n=21 labeled particles: a finer grid is trivially available
#: (``pool_to_grid`` takes any shape) and equally trivially overfits -- at 8x8 the feature
#: count is three times the sample count. The grid is a parameter precisely so that raising it
#: is a decision made when the labeled set grows, not a default nobody revisits.
DEFAULT_GRID = (4, 4)

#: The six size/shape scalars appended to the pooled grid. ``max_col_occ`` is Method A's whole
#: statistic, included so Method B is measured on a feature set that *contains* Method A rather
#: than on a disjoint one -- if the trained model cannot beat the single threshold, that is a
#: real result about the labeled set's size, not about the features being different.
SCALAR_FEATURE_NAMES = (
    "max_col_occ",
    "max_row_occ",
    "fill_fraction",
    "n_slices",
    "n_diodes_spanned",
    "aspect_ratio",
)


def _overlap_matrix(n_in: int, n_out: int) -> np.ndarray:
    """``(n_out, n_in)`` area-resampling weights, each row summing to 1.

    Exact 1-D area resampling: output cell ``g`` covers the input interval
    ``[g*n_in/n_out, (g+1)*n_in/n_out)``, and its weight on input cell ``i`` is the length
    of the overlap with ``[i, i+1)``. Handles ``n_in < n_out`` (one input row spread across
    several output rows) without a special case, which a floor-division index map does not --
    that map leaves output rows empty and would divide by zero.
    """
    edges_in = np.arange(n_in + 1, dtype=float)
    edges_out = np.linspace(0.0, float(n_in), n_out + 1)
    lo = np.maximum(edges_out[:-1, None], edges_in[None, :-1])
    hi = np.minimum(edges_out[1:, None], edges_in[None, 1:])
    w = np.clip(hi - lo, 0.0, None)
    return w / w.sum(axis=1, keepdims=True)


def pool_to_grid(shadow: np.ndarray, grid: tuple[int, int] = DEFAULT_GRID) -> np.ndarray:
    """A particle's shadow resampled to a fixed ``grid`` of occupancy fractions in [0, 1].

    This is the whole reason a variable-size particle can enter a fixed-width model at all.
    The value in each output cell is the area-weighted mean of the boolean shadow over the
    input region that maps to it -- a genuine occupancy fraction, not a subsample, so a
    one-pixel-wide feature is attenuated rather than either duplicated or dropped.

    An empty shadow (no slices) returns a zero grid.
    """
    if shadow.shape[0] == 0 or shadow.shape[1] == 0:
        return np.zeros(grid, dtype=float)
    wr = _overlap_matrix(shadow.shape[0], grid[0])
    wc = _overlap_matrix(shadow.shape[1], grid[1])
    return wr @ shadow.astype(float) @ wc.T


def _crop(shadow: np.ndarray) -> np.ndarray:
    """The shadow's own bounding box, via the port's own cropper (``pad=0``).

    ``reconstruct_particle_image`` returns the full inter-boundary slice window, which for a
    particle just after a record reset can be hundreds of slices of background around a
    handful of lit ones (``render.crop_to_content``'s docstring documents this). Pooling that
    window would put nearly all of the particle in one grid cell, so the crop is not cosmetic
    here the way it is for display -- it is what makes the grid comparable between particles.
    """
    from arrayprobe.render import crop_to_content  # noqa: PLC0415  (real-data path only)

    return crop_to_content(shadow, pad=0)


def particle_features(shadow: np.ndarray, grid: tuple[int, int] = DEFAULT_GRID) -> np.ndarray:
    """One particle's fixed-length feature vector: pooled grid, then the scalars.

    Length is ``grid[0] * grid[1] + len(SCALAR_FEATURE_NAMES)``. The scalars are computed on
    the **uncropped** shadow, which matters for ``max_col_occ``: it is defined over the
    particle's whole detection window (that is the stuck-diode signature -- a column dark for
    the entire span) and cropping would change its value.
    """
    scalars = np.array(
        [
            max_col_occ(shadow),
            float(shadow.mean(axis=1).max()) if shadow.shape[0] else 0.0,
            float(shadow.mean()) if shadow.size else 0.0,
            float(shadow.shape[0]),
            float(np.count_nonzero(shadow.any(axis=0))),
            float(shadow.shape[0]) / float(max(shadow.shape[1], 1)),
        ],
        dtype=float,
    )
    return np.concatenate([pool_to_grid(_crop(shadow), grid).ravel(), scalars])


def feature_names(grid: tuple[int, int] = DEFAULT_GRID) -> list[str]:
    """Human-readable names, in the exact order :func:`particle_features` emits them."""
    pooled = [f"occ[{r},{c}]" for r in range(grid[0]) for c in range(grid[1])]
    return pooled + list(SCALAR_FEATURE_NAMES)


def build_dataset(
    pairs: list[tuple[LabeledParticle, np.ndarray]],
    *,
    grid: tuple[int, int] = DEFAULT_GRID,
    positive_label: str = "artifact",
    binary_labels: tuple[str, ...] = ("artifact", "real"),
) -> tuple[np.ndarray, np.ndarray, list[LabeledParticle]]:
    """``(X, y, kept)`` from ``(label, shadow)`` pairs.

    ``y`` is 1 for ``positive_label`` ("artifact" -- the thing we want to *find*), 0
    otherwise. Anything whose label is not in ``binary_labels`` is dropped and reported in
    ``kept``'s absence rather than folded into either class; the one "mixed" particle in
    :data:`REVIEWED_LABELS` is exactly that case, and forcing it into a bucket would be
    inventing a label the human declined to give.
    """
    kept = [item for item, _ in pairs if item.label in binary_labels]
    rows = [
        particle_features(shadow, grid)
        for item, shadow in pairs
        if item.label in binary_labels
    ]
    if not rows:
        n_features = grid[0] * grid[1] + len(SCALAR_FEATURE_NAMES)
        return np.zeros((0, n_features)), np.zeros(0, dtype=int), []
    x = np.vstack(rows)
    y = np.array([1 if item.label == positive_label else 0 for item in kept], dtype=int)
    return x, y, kept


# ---------------------------------------------------------------------------
# Method B, part 3: the numpy-only trained baseline
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LogisticModel:
    """A fitted logistic regression, carrying the standardisation it was fitted under.

    The mean/std travel *with* the weights on purpose: standardising against statistics
    computed over a set that includes the point being predicted is the classic
    cross-validation leak, and keeping them here makes it structurally impossible for
    :func:`leave_one_out` to do that by accident.
    """

    weights: np.ndarray
    bias: float
    mean: np.ndarray
    std: np.ndarray
    n_train: int
    threshold: float = 0.5

    def decision(self, x: np.ndarray) -> np.ndarray:
        z = (np.atleast_2d(x) - self.mean) / self.std
        return z @ self.weights + self.bias

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        d = self.decision(x)
        # Numerically stable logistic: exp() of a large positive argument overflows.
        out = np.empty_like(d)
        pos, neg = d >= 0, d < 0
        out[pos] = 1.0 / (1.0 + np.exp(-d[pos]))
        ex = np.exp(d[neg])
        out[neg] = ex / (1.0 + ex)
        return out

    def predict(self, x: np.ndarray) -> np.ndarray:
        return (self.predict_proba(x) >= self.threshold).astype(int)


def fit_logistic(
    x: np.ndarray,
    y: np.ndarray,
    *,
    l2: float = 1.0,
    lr: float = 0.5,
    n_iter: int = 2000,
) -> LogisticModel:
    """L2-regularised logistic regression by full-batch gradient descent, numpy only.

    Deterministic: weights start at zero, the whole batch is used every step, and there is
    no sampling anywhere -- the same ``(x, y)`` always produces the same model, which is what
    lets the tests pin real numbers instead of ranges.

    ``l2`` is deliberately non-trivial by default. At n=21 with 22 features the unregularised
    problem is separable and the maximum-likelihood weights diverge; shrinkage is not a
    tuning nicety here, it is what makes the fit defined at all. The bias is not penalised.
    """
    x = np.atleast_2d(np.asarray(x, dtype=float))
    y = np.asarray(y, dtype=float)
    mean = x.mean(axis=0)
    std = x.std(axis=0)
    std[std == 0] = 1.0                      # a constant column carries no information
    z = (x - mean) / std
    n, d = z.shape
    w = np.zeros(d)
    b = 0.0
    for _ in range(n_iter):
        t = z @ w + b
        p = np.where(t >= 0, 1.0 / (1.0 + np.exp(-np.abs(t))),
                     np.exp(-np.abs(t)) / (1.0 + np.exp(-np.abs(t))))
        err = p - y
        w -= lr * ((z.T @ err) / n + l2 * w / n)
        b -= lr * err.mean()
    return LogisticModel(weights=w, bias=float(b), mean=mean, std=std, n_train=n)


@dataclass(frozen=True)
class LooResult:
    """Leave-one-out cross-validation: the only honest held-out protocol at n=21."""

    accuracy: float
    predictions: np.ndarray
    truth: np.ndarray
    n: int

    @property
    def confusion(self) -> dict[str, int]:
        p, t = self.predictions, self.truth
        return {
            "tp": int(np.sum((p == 1) & (t == 1))),
            "fp": int(np.sum((p == 1) & (t == 0))),
            "tn": int(np.sum((p == 0) & (t == 0))),
            "fn": int(np.sum((p == 0) & (t == 1))),
        }


def leave_one_out(x: np.ndarray, y: np.ndarray, **fit_kw) -> LooResult:
    """Fit on every point but one, predict that one, repeat. No leakage of any kind.

    Standardisation happens inside :func:`fit_logistic`, i.e. inside each fold, so the held-
    out point contributes nothing -- not even its mean and variance -- to the model that
    scores it. This is the single most common way a small-sample accuracy number gets
    inflated, and the split is structured to make it impossible rather than to be careful
    about it.
    """
    x = np.atleast_2d(np.asarray(x, dtype=float))
    y = np.asarray(y, dtype=int)
    n = len(y)
    preds = np.empty(n, dtype=int)
    for i in range(n):
        keep = np.ones(n, dtype=bool)
        keep[i] = False
        model = fit_logistic(x[keep], y[keep], **fit_kw)
        preds[i] = int(model.predict(x[i:i + 1])[0])
    return LooResult(
        accuracy=float(np.mean(preds == y)) if n else 0.0,
        predictions=preds, truth=y, n=n,
    )


def majority_class_accuracy(y: np.ndarray) -> float:
    """What you get by ignoring the features and always predicting the commoner class.

    Reported alongside every model number in this module. With 16 artifacts and 5 reals this
    is 0.762, so any classifier scoring in the seventies has demonstrated nothing.
    """
    y = np.asarray(y, dtype=int)
    if len(y) == 0:
        return 0.0
    return float(max(np.mean(y == 1), np.mean(y == 0)))


def evaluate_labeled_set(
    pairs: list[tuple[LabeledParticle, np.ndarray]],
    *,
    grid: tuple[int, int] = DEFAULT_GRID,
    threshold: float = DEFAULT_THRESHOLD,
    **fit_kw,
) -> dict:
    """The whole honest report for one labeled set: Method B, Method A, and the floor.

    Returns a dict with ``n``, ``n_positive``, ``majority_accuracy``, ``loo_accuracy``,
    ``loo_confusion``, ``method_a_accuracy`` and ``method_a_confusion``. All three numbers
    are computed on the identical set of particles so they are actually comparable; quoting
    a model's accuracy without the majority floor beside it is the failure mode this
    function exists to make impossible.
    """
    x, y, kept = build_dataset(pairs, grid=grid)
    loo = leave_one_out(x, y, **fit_kw)
    a_pred = np.array(
        [
            1 if classify_stuck_diode_artifact(shadow, threshold).is_artifact else 0
            for item, shadow in pairs
            if item.label in ("artifact", "real")
        ],
        dtype=int,
    )
    a_res = LooResult(
        accuracy=float(np.mean(a_pred == y)) if len(y) else 0.0,
        predictions=a_pred, truth=y, n=len(y),
    )
    return {
        "n": len(y),
        "n_positive": int(y.sum()),
        "n_features": x.shape[1] if x.size else 0,
        "flights": sorted({item.flight for item in kept}),
        "majority_accuracy": majority_class_accuracy(y),
        "loo_accuracy": loo.accuracy,
        "loo_confusion": loo.confusion,
        "method_a_accuracy": a_res.accuracy,
        "method_a_confusion": a_res.confusion,
    }


#: What a real CNN would need, recorded so the decision is made on facts. Nothing here is a
#: guess about difficulty -- each line is either measured in this repo or a direct consequence
#: of the numbers above.
TORCH_CNN_REQUIREMENTS = """\
A convolutional accept/reject model for this project needs four things, in this order:

1. LABELS, and this is the binding constraint, not the framework. The reviewed set is 22
   particles (21 binary after the one "mixed" detection is excluded), 16 artifact / 5 real.
   Published comparables train on 10^4-10^6 images (Jaffeux 2022: four campaigns; Przybylo
   2022: >10M). A CNN on 21 examples cannot be evaluated, let alone trained -- leave-one-out
   on 21 points has a standard error of roughly 0.09 on the accuracy itself, so two models
   nine points apart are indistinguishable. Order of magnitude needed before a CNN is worth
   the dependency: 10^3 reviewed particles, class-balanced far better than 16:5.

2. A LABELING PATH THAT SCALES AND IS TRUSTWORTHY. The one that was tried -- k-means cluster
   bulk-apply -- produced the 2026-08-27 incident (~2.69M particles labeled from unreviewed
   medoids) and, separately, the user has since found the clustering itself not tight enough
   for bulk-apply even when the medoid IS reviewed correctly. So this is an open design
   problem, not a solved step: `triage_server.py --queue-file` is the working per-particle
   path and is honest but slow.

3. A FRAMEWORK DECISION, which is the user's to make. Neither torch nor tensorflow is
   installed; `enhancements_uiops/`'s declared dependencies are arrayprobe, numpy and netCDF4.
   Adding torch is ~2.5GB and this project's own convention (opt-in extras in `pyproject.toml`) keeps
   heavy optional deps out unless a stage genuinely needs one.

4. THE INPUT REPRESENTATION, which is already solved and is what this module ships:
   `load_shadows` + `pool_to_grid` turn any variable-size particle into a fixed tensor.
   A CNN would take the cropped shadow at a fixed resolution (e.g. 64x64) instead of the
   4x4 pooled grid -- the same call chain with the last step replaced. Jaffeux 2022's
   published architecture is a legitimate reference for the stack; their weights are not
   redistributable (no license), so training is from scratch on this project's own labels.

Aircraft-state side-input (temperature/pressure/altitude, located 2026-08-27 in
UND's 2016 delivery (`<flight>/.../PostProcessing/<stem>.physical.1Hz.gz`), same UT-seconds key the
proc files use) is a genuine extension over both published papers, but it is a second-order
question until item 1 is answered.
"""


def _main(argv: list[str] | None = None) -> int:
    """``python -m arrayprobe_enhancements.ml_accept_reject --decoded-dir ../_decoded``."""
    import argparse  # noqa: PLC0415  (CLI path only)

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--decoded-dir", required=True, type=Path)
    parser.add_argument("--grid", type=int, nargs=2, default=list(DEFAULT_GRID))
    parser.add_argument(
        "--from-sidecars", action="store_true",
        help="use the triage_verdicts/ sidecars instead of the committed REVIEWED_LABELS "
             "registry (recovers only 14 of the 22 -- the rest were overwritten by the "
             "2026-08-27 bulk pass)",
    )
    args = parser.parse_args(argv)

    if args.from_sidecars:
        labeled = human_labeled_particles(args.decoded_dir / "triage_verdicts")
    else:
        labeled = list(REVIEWED_LABELS)
    pairs = load_shadows(labeled, args.decoded_dir)
    if not pairs:
        print(f"no decoded flights found under {args.decoded_dir}")
        return 1
    report = evaluate_labeled_set(pairs, grid=tuple(args.grid))
    for key, value in report.items():
        print(f"{key:22s} {value}")
    return 0


if __name__ == "__main__":       # pragma: no cover
    raise SystemExit(_main())
