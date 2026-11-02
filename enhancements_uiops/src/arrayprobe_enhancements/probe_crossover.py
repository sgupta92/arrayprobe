# SPDX-License-Identifier: BSD-3-Clause
"""The 2D-S/HVPS crossover diagnostic: do two probes agree where their size ranges overlap?

**The gap it fills**: Schima et al. (2024) §4.2
records that over the 2D-S/HVPS overlap the two probes showed "very weak correlation"
for most habits, and draws the consequence this module implements: *ship a crossover
diagnostic instead of an unguarded crossover merge*. No UIOOPS release merges two
probes -- ``combine_sizedist.m`` (``arrayprobe.combine``, ``arrayprobe_uiops.combine``)
stitches one probe's several ``sd`` files and nothing more -- so there is no merge
in either port to guard. This module tells a user, second by second, whether the two
probes they are about to merge agree in the range they share.

**What it computes.** For each second held by both inputs, each probe's number
concentration integrated over one common size range ``[lo, hi]`` (mm):

    N_p = sum_b w_b * n_b                  (cm-3)

where ``n_b`` is the probe's per-bin number concentration (``conc_minR * bin_dD / 10``
for an ``sd`` file, ``Size Distribution cm-3`` for a combined product -- the same
quantity, ``arrayprobe.combine`` line 173) and ``w_b`` is the fraction of bin ``b``
lying inside ``[lo, hi]``. The default range is snapped to edges the two bin ladders
share, so every ``w_b`` is exactly 0 or 1 and nothing is assumed about how particles
spread inside a bin; a caller-supplied range that cuts a bin makes that bin's weight
fractional, which assumes a uniform spread within it, and the result says so
(``edges_aligned``).

**Counting statistics.** Both files carry ``count`` -- ``dist_minR * binwidth / 10``,
the same accepted-particle tally the concentration is divided out of
(the engines' size distribution, the ``"count"`` output) -- so the Poisson uncertainty on
each bin's concentration is ``n_b / sqrt(C_b)``, the relation
:func:`arrayprobe_enhancements.poisson_uncertainty.per_bin_absolute_uncertainty`
already implements and this module reuses. Summed in quadrature over the range:

    sigma_p^2 = sum_b w_b^2 * n_b^2 / C_b

The effective count ``K_p = (N_p / sigma_p)^2`` equals the plain summed count when
every bin shares one sample volume. The two probes are compared on the log ratio,
whose counting standard error is the delta-method ``sqrt(1/K_a + 1/K_b)``:

    z = ln(N_a / N_b) / sqrt(1/K_a + 1/K_b)

and a second is flagged when ``|z| > z_threshold``. Both defaults -- ``z_threshold =
3`` and ``min_count = 10`` effective particles per probe below which a second is
``insufficient`` rather than tested -- are this module's conventions, chosen so the
normal approximation to the log ratio is reasonable; they come from no paper.
Because thousands of seconds are tested per flight, :class:`CrossoverResult` also
reports how many flags counting noise alone would produce at that threshold
(``expected_false_flags``), so a flag count can be read against its chance level.

**What it does not do.** It tests counting statistics only: a sample-volume, dead-time
or sizing-convention difference between the probes shows up as disagreement, which is
the point -- it is a diagnostic, not an attribution. A second where one probe counts
nothing in the range is ``insufficient``, not ``disagree``, because a zero count carries
no sample volume from which to predict what it should have seen. It merges nothing and
writes no file.

**Engines.** Reads v3.1.4 and v3.5 ``sd`` files (the variables it reads -- ``time``,
``bin_min``, ``bin_max``, ``bin_dD``, ``conc_minR``, ``count`` -- are written by both
``sizeDist`` translations under the same names) and ORACLES combined products
(``Time Vector``, ``Bin Minimum``, ``Bin Maximum``, ``Size Distribution cm-3``,
``Counts``, as :func:`arrayprobe.combine.combine_sizedist` writes them). Arrays are
read through :mod:`arrayprobe.ncio`, which returns MATLAB-shaped arrays, and oriented
by the writer's own known shape, never by a hand-rolled transpose of the file.

**Changes no computed number** -- every input is read verbatim; this only adds derived
arrays alongside it, the same space as ``poisson_uncertainty.py`` and ``analysis.py``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from arrayprobe_uiops import ncio

from .poisson_uncertainty import per_bin_absolute_uncertainty

__all__ = [
    "DEFAULT_MIN_COUNT",
    "DEFAULT_Z_THRESHOLD",
    "STATUSES",
    "CrossoverResult",
    "ProbeSizeDistribution",
    "aggregate",
    "common_edges",
    "compare",
    "crossover_diagnostic",
    "default_size_range",
    "effective_count",
    "integrate_range",
    "overlap_weights",
    "read_probe",
]

#: This module's convention, not a published threshold: flag a second whose log
#: ratio lies more than three counting standard errors from zero.
DEFAULT_Z_THRESHOLD = 3.0
#: This module's convention: below ten effective particles in the range on either
#: probe, the normal approximation to the log ratio is not trusted and the second
#: is reported ``insufficient`` rather than tested.
DEFAULT_MIN_COUNT = 10.0

#: Per-second outcomes. ``a_higher`` / ``b_higher`` are the two directions of a
#: flagged disagreement; ``missing`` is a NaN in either input (a combined product's
#: gap-fill rows); ``insufficient`` is too few particles to test.
STATUSES = ("missing", "insufficient", "agree", "a_higher", "b_higher")

_EDGE_TOL_MM = 1e-9


@dataclass(frozen=True)
class ProbeSizeDistribution:
    """One probe's per-second, per-bin number concentration and count.

    ``time`` is the file's own time key: HHMMSS for an ``sd`` file, whole seconds of
    the MATLAB datenum (``round(datenum * 86400)``) for a combined product. Two inputs
    can only be aligned if they use the same key (``time_kind``).
    """

    time: np.ndarray        # (T,)
    time_kind: str          # "hhmmss" | "datenum_seconds"
    bin_min: np.ndarray     # (B,) mm
    bin_max: np.ndarray     # (B,) mm
    conc: np.ndarray        # (T, B) cm-3 per bin
    count: np.ndarray       # (T, B) accepted particles per bin
    source_format: str      # "sd" | "combined"
    path: str = ""


@dataclass(frozen=True)
class CrossoverResult:
    """The per-second comparison of probe ``a`` against probe ``b``."""

    time: np.ndarray
    size_range: tuple[float, float]
    edges_aligned: bool
    n_a: np.ndarray             # cm-3 in the range
    n_b: np.ndarray
    k_a: np.ndarray             # effective counts
    k_b: np.ndarray
    ratio: np.ndarray           # n_a / n_b
    z: np.ndarray               # NaN where not tested
    status: np.ndarray          # one of STATUSES per second
    z_threshold: float
    min_count: float

    def counts_by_status(self) -> dict[str, int]:
        return {s: int(np.count_nonzero(self.status == s)) for s in STATUSES}

    @property
    def n_tested(self) -> int:
        return int(np.count_nonzero(np.isin(self.status, ("agree", "a_higher", "b_higher"))))

    @property
    def n_flagged(self) -> int:
        return int(np.count_nonzero(np.isin(self.status, ("a_higher", "b_higher"))))

    @property
    def expected_false_flags(self) -> float:
        """Flags counting noise alone would give: ``n_tested * P(|Z| > z_threshold)``."""
        return self.n_tested * math.erfc(self.z_threshold / math.sqrt(2.0))

    @property
    def median_ratio(self) -> float:
        tested = np.isin(self.status, ("agree", "a_higher", "b_higher"))
        return float(np.median(self.ratio[tested])) if tested.any() else float("nan")


def _has_var(ds, name: str) -> bool:
    try:
        ncio.inq_var_id(ds, name)
    except Exception:
        return False
    return True


def _get(ds, name: str) -> np.ndarray:
    return np.asarray(ncio.get_var(ds, ncio.inq_var_id(ds, name)), dtype=np.float64)


def read_probe(path) -> ProbeSizeDistribution:
    """Read an ``sd`` file (either engine) or an ORACLES combined product.

    An ``sd`` file's ``conc_minR`` and ``count`` come back from ``ncio`` in MATLAB
    shape ``(bin, time)`` -- the shape :mod:`arrayprobe.combine` also transposes at
    its line 173 -- and a combined product's ``Size Distribution cm-3`` and
    ``Counts`` in ``(time, bin)``, the order :func:`arrayprobe.combine._write`
    declares them in.
    """
    ds = ncio.open(str(path), "nowrite")
    try:
        if _has_var(ds, "conc_minR"):
            bin_dD = _get(ds, "bin_dD").reshape(-1)
            conc = _get(ds, "conc_minR").T / 10.0 * bin_dD[None, :]
            return ProbeSizeDistribution(
                time=_get(ds, "time").reshape(-1), time_kind="hhmmss",
                bin_min=_get(ds, "bin_min").reshape(-1),
                bin_max=_get(ds, "bin_max").reshape(-1),
                conc=conc, count=_get(ds, "count").T,
                source_format="sd", path=str(path))
        if _has_var(ds, "Size Distribution cm-3"):
            tv = _get(ds, "Time Vector").reshape(-1)
            return ProbeSizeDistribution(
                time=np.round(tv * 86400.0), time_kind="datenum_seconds",
                bin_min=_get(ds, "Bin Minimum").reshape(-1),
                bin_max=_get(ds, "Bin Maximum").reshape(-1),
                conc=_get(ds, "Size Distribution cm-3"),
                count=_get(ds, "Counts"),
                source_format="combined", path=str(path))
    finally:
        ncio.close(ds)
    raise ValueError(f"{path}: neither an sd file (no 'conc_minR') nor a combined "
                     "product (no 'Size Distribution cm-3')")


def common_edges(a: ProbeSizeDistribution, b: ProbeSizeDistribution) -> np.ndarray:
    """Bin edges (mm) present in both ladders, within the two ladders' overlap."""
    ea = np.union1d(a.bin_min, a.bin_max)
    eb = np.union1d(b.bin_min, b.bin_max)
    lo = max(ea.min(), eb.min())
    hi = min(ea.max(), eb.max())
    shared = [e for e in ea
              if lo - _EDGE_TOL_MM <= e <= hi + _EDGE_TOL_MM
              and np.min(np.abs(eb - e)) <= _EDGE_TOL_MM]
    return np.asarray(shared, dtype=np.float64)


def default_size_range(a: ProbeSizeDistribution,
                       b: ProbeSizeDistribution) -> tuple[float, float]:
    """The widest range whose ends are edges of both ladders; else the raw overlap."""
    shared = common_edges(a, b)
    if shared.size >= 2:
        return float(shared[0]), float(shared[-1])
    lo = max(a.bin_min.min(), b.bin_min.min())
    hi = min(a.bin_max.max(), b.bin_max.max())
    if hi <= lo:
        raise ValueError("the two probes' bin ladders do not overlap")
    return float(lo), float(hi)


def overlap_weights(bin_min, bin_max, lo: float, hi: float) -> np.ndarray:
    """Fraction of each bin inside ``[lo, hi]`` -- exactly 0 or 1 when edges align."""
    bin_min = np.asarray(bin_min, dtype=np.float64)
    bin_max = np.asarray(bin_max, dtype=np.float64)
    inside = np.clip(np.minimum(bin_max, hi) - np.maximum(bin_min, lo), 0.0, None)
    w = inside / (bin_max - bin_min)
    w[np.abs(w) < _EDGE_TOL_MM] = 0.0
    w[np.abs(w - 1.0) < _EDGE_TOL_MM] = 1.0
    return w


def integrate_range(conc, count, weights):
    """``(N, var)`` per second: range-integrated concentration and its counting variance.

    ``N = sum w n``; ``var = sum w^2 (n / sqrt(C))^2`` over bins with ``C > 0``.
    A second with any NaN in a weighted bin gives NaN for both.
    """
    conc = np.asarray(conc, dtype=np.float64)
    count = np.asarray(count, dtype=np.float64)
    w = np.asarray(weights, dtype=np.float64)
    used = w > 0
    c, k, wu = conc[:, used], count[:, used], w[used]
    n = (c * wu).sum(axis=1)
    sigma_b = per_bin_absolute_uncertainty(c, k)            # NaN where C <= 0
    var = np.where(k > 0, (wu * sigma_b) ** 2, 0.0).sum(axis=1)
    missing = np.isnan(c).any(axis=1) | np.isnan(k).any(axis=1)
    return np.where(missing, np.nan, n), np.where(missing, np.nan, var)


def effective_count(n, var):
    """``K = N^2 / var`` -- the plain summed count when every bin shares one sample
    volume; 0 where nothing was counted, NaN where the input is missing."""
    n = np.asarray(n, dtype=np.float64)
    var = np.asarray(var, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        k = np.where(var > 0, n * n / var, 0.0)
    return np.where(np.isnan(n) | np.isnan(var), np.nan, k)


def _seconds(time, time_kind: str) -> np.ndarray:
    t = np.asarray(time, dtype=np.float64)
    if time_kind == "hhmmss":
        t = np.floor(t)
        return (np.floor_divide(t, 10000) * 3600 + np.mod(np.floor_divide(t, 100), 100) * 60
                + np.mod(t, 100))
    return t


def aggregate(seconds, n_a, var_a, n_b, var_b, window_s: int):
    """Average both probes over ``window_s``-second blocks of the time axis.

    A block holds the seconds whose ``floor((s - s0) / window_s)`` agree, and uses
    only the seconds where *both* probes are present, so the two averages cover the
    same instants. Mean concentration over ``m`` seconds has variance
    ``sum(var) / m^2``. Returns the block's first second and the four arrays.
    """
    seconds = np.asarray(seconds, dtype=np.float64)
    if window_s < 1:
        raise ValueError(f"window_s must be a positive number of seconds, not {window_s}")
    block = np.floor((seconds - seconds.min()) / window_s).astype(np.int64)
    both = ~(np.isnan(n_a) | np.isnan(n_b))
    keys = np.unique(block)
    out = np.full((4, keys.size), np.nan)
    starts = np.empty(keys.size)
    for j, key in enumerate(keys):
        sel = block == key
        starts[j] = seconds[sel].min()
        use = sel & both
        m = int(use.sum())
        if m:
            out[:, j] = (n_a[use].mean(), var_a[use].sum() / m ** 2,
                         n_b[use].mean(), var_b[use].sum() / m ** 2)
    return starts, out[0], out[1], out[2], out[3]


def compare(n_a, k_a, n_b, k_b, *, z_threshold: float = DEFAULT_Z_THRESHOLD,
            min_count: float = DEFAULT_MIN_COUNT):
    """Per-second ``(ratio, z, status)`` from two probes' ``(N, K)``."""
    n_a, k_a, n_b, k_b = (np.asarray(x, dtype=np.float64) for x in (n_a, k_a, n_b, k_b))
    missing = np.isnan(n_a) | np.isnan(n_b) | np.isnan(k_a) | np.isnan(k_b)
    enough = ~missing & (k_a >= min_count) & (k_b >= min_count) & (n_a > 0) & (n_b > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(~missing & (n_b > 0), n_a / n_b, np.nan)
        z = np.where(enough, np.log(n_a / n_b) / np.sqrt(1.0 / k_a + 1.0 / k_b), np.nan)
    status = np.full(n_a.shape, "insufficient", dtype=object)
    status[missing] = "missing"
    status[enough] = "agree"
    status[enough & (z > z_threshold)] = "a_higher"
    status[enough & (z < -z_threshold)] = "b_higher"
    return ratio, z, status.astype(str)


def crossover_diagnostic(probe_a, probe_b, *, size_range=None, window_s: int = 1,
                         z_threshold: float = DEFAULT_Z_THRESHOLD,
                         min_count: float = DEFAULT_MIN_COUNT) -> CrossoverResult:
    """Compare two probes second by second over their shared size range.

    ``probe_a`` / ``probe_b`` are paths or :class:`ProbeSizeDistribution` objects
    (conventionally ``a`` = 2D-S, ``b`` = HVPS, so ``b_higher`` is an HVPS excess).
    ``size_range`` is ``(lo, hi)`` in mm; ``None`` uses :func:`default_size_range`.
    Only seconds present in both inputs are compared. ``window_s > 1`` averages
    both probes over blocks of that many seconds first (:func:`aggregate`) -- the
    way to test a range where one probe sees too few particles per second; the
    result's ``time`` is then each block's first second, in seconds of day (sd
    input) or datenum seconds (combined input).
    """
    a = probe_a if isinstance(probe_a, ProbeSizeDistribution) else read_probe(Path(probe_a))
    b = probe_b if isinstance(probe_b, ProbeSizeDistribution) else read_probe(Path(probe_b))
    if a.time_kind != b.time_kind:
        raise ValueError(f"cannot align a {a.time_kind} time axis with a {b.time_kind} "
                         "one: compare two sd files, or two combined products")
    lo, hi = default_size_range(a, b) if size_range is None else map(float, size_range)
    if hi <= lo:
        raise ValueError(f"empty size range ({lo}, {hi})")
    wa = overlap_weights(a.bin_min, a.bin_max, lo, hi)
    wb = overlap_weights(b.bin_min, b.bin_max, lo, hi)
    if not (wa > 0).any() or not (wb > 0).any():
        raise ValueError(f"size range ({lo}, {hi}) mm holds no bin of one probe")
    aligned = bool(np.isin(wa, (0.0, 1.0)).all() and np.isin(wb, (0.0, 1.0)).all())

    t, ia, ib = np.intersect1d(a.time, b.time, assume_unique=False, return_indices=True)
    n_a, var_a = integrate_range(a.conc[ia], a.count[ia], wa)
    n_b, var_b = integrate_range(b.conc[ib], b.count[ib], wb)
    if window_s != 1:
        t, n_a, var_a, n_b, var_b = aggregate(_seconds(t, a.time_kind),
                                              n_a, var_a, n_b, var_b, int(window_s))
    k_a, k_b = effective_count(n_a, var_a), effective_count(n_b, var_b)
    ratio, z, status = compare(n_a, k_a, n_b, k_b,
                               z_threshold=z_threshold, min_count=min_count)
    return CrossoverResult(time=t, size_range=(lo, hi), edges_aligned=aligned,
                           n_a=n_a, n_b=n_b, k_a=k_a, k_b=k_b, ratio=ratio, z=z,
                           status=status, z_threshold=float(z_threshold),
                           min_count=float(min_count))
