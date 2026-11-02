# SPDX-License-Identifier: BSD-3-Clause
"""Put two probes' sizeDist-layout products on a common size grid and time axis.

The helpers here compare two optical array probes (for example a CIP and a 2D-S)
with statistics that survive mostly-empty 1 Hz data:

- :func:`load_sd` reads one or more sizeDist outputs, converting ``conc_minR``
  to number concentration per bin the way ``combine_sizedist.m`` does;
- :func:`rebin_weights` and :func:`rebin` apportion each native bin onto a
  common grid by the fraction of its width inside each common bin;
- :func:`align` keeps the seconds both products carry;
- :func:`scatter_stats` reports Spearman and Pearson-of-log1p on every finite
  pair and an RMA slope on a count-gated subset, never a raw Pearson;
- :func:`coincidence_vs_lag` scans the conditional detection probability over
  a range of time lags, separating a clock offset from Poisson thinning.

Nothing here changes a processing output; it reads products and returns plain
dicts and arrays. scipy is imported lazily, inside the function
that needs it.
"""

from __future__ import annotations

import math

import netCDF4
import numpy as np

#: An example common grid [um]: 55-105 um, then 100-um bins with edges 105, 205, ..., 1005 um.
#: Every edge is an edge of a 10-um bin ladder, so a probe processed onto that ladder rebins as
#: a pure sum. Callers may pass their own edges.
COMMON_EDGES_UM = np.array([55.0] + [105.0 + 100.0 * k for k in range(10)])

#: Minimum counts per second (a, b) for the dense 1 Hz subset the RMA slope is fitted on.
DEFAULT_COUNT_GATE = (20.0, 5.0)
#: Minimum summed counts per averaging window (a, b) for the window-mean RMA subset.
DEFAULT_COUNT_GATE_WINDOW = (100.0, 20.0)
#: Averaging window [s] and the minimum number of its seconds finite on both sides.
DEFAULT_WINDOW_S = 300
DEFAULT_MIN_COVER = 270
#: The +- lag magnitudes [s] added to the dense 1 s scan of :func:`build_lag_list`.
_LAG_COARSE_STEPS = (45, 60, 90, 120, 180, 300, 450, 600)


# --------------------------------------------------------------------------- readers
def _by_dims(var, want: tuple[str, str]) -> np.ndarray:
    """Return ``var`` as a ``(time, bin)`` float array whatever its on-disk order."""
    arr = np.asarray(var[:], dtype=np.float64)
    dims = var.dimensions
    if dims == want[::-1]:
        arr = arr.T
    elif dims != want:
        raise ValueError(f"{var.name}: dims {dims}, expected {want} in some order")
    return arr



def zero_empty_rows(x: np.ndarray, n_tot: np.ndarray) -> np.ndarray:
    """A NaN bin in a second whose total ``n_tot`` is finite is an empty bin, so it is 0.

    A product can write every bin of a zero-particle second as NaN. Reading those
    as missing would drop every empty second and bias a ratio toward the seconds
    one probe happened to fill, so they are zero. A second whose total is itself
    NaN (a gap) stays missing.
    """
    out = x.copy()
    valid = np.isfinite(n_tot)[:, None] & np.isnan(out)
    out[valid] = 0.0
    return out


_zero_empty_rows = zero_empty_rows


def load_sd(paths) -> dict:
    """One or more sizeDist outputs, concatenated in time order.

    ``conc_minR`` [cm-4] -> cm-3 per bin as ``combine_sizedist.m:47-50`` does.
    A repeated second keeps its first occurrence (``combine_sizedist.m:84-91``
    drops the second of each adjacent duplicate).
    """
    uts, nds, cts = [], [], []
    bmin = bmax = None
    for p in paths:
        with netCDF4.Dataset(p) as d:
            d.set_auto_mask(False)
            hhmmss = np.asarray(d["time"][:], dtype=np.int64)
            tdim = d["time"].dimensions[0]
            bdim = d["bin_min"].dimensions[0]
            dd = np.asarray(d["bin_dD"][:], dtype=np.float64)
            n_tot = np.asarray(d["n"][:], dtype=np.float64)
            conc = _by_dims(d["conc_minR"], (tdim, bdim))
            nd = _zero_empty_rows(conc / 10.0 * dd[None, :], n_tot)
            ct = _zero_empty_rows(_by_dims(d["count"], (tdim, bdim)), n_tot)
            bmin = np.asarray(d["bin_min"][:], dtype=np.float64) * 1000.0
            bmax = np.asarray(d["bin_max"][:], dtype=np.float64) * 1000.0
        ut = (hhmmss // 10000) * 3600 + ((hhmmss // 100) % 100) * 60 + hhmmss % 100
        uts.append(ut)
        nds.append(nd)
        cts.append(ct)
    ut = np.concatenate(uts)
    nd = np.concatenate(nds)
    ct = np.concatenate(cts)
    order = np.argsort(ut, kind="stable")
    ut, nd, ct = ut[order], nd[order], ct[order]
    keep = np.ones(len(ut), dtype=bool)
    keep[1:] = np.diff(ut) != 0
    return {"ut": ut[keep], "bmin": bmin, "bmax": bmax, "nd": nd[keep], "counts": ct[keep]}


# --------------------------------------------------------------------------- common grid
def rebin_weights(bmin, bmax, edges, shift_um: float = 0.0) -> np.ndarray:
    """``(n_fine, n_coarse)`` fraction of each fine bin's width inside each coarse bin."""
    lo = np.asarray(bmin, dtype=np.float64) + shift_um
    hi = np.asarray(bmax, dtype=np.float64) + shift_um
    e0, e1 = edges[:-1], edges[1:]
    overlap = np.clip(np.minimum(hi[:, None], e1[None, :]) - np.maximum(lo[:, None], e0[None, :]),
                      0.0, None)
    width = (hi - lo)[:, None]
    return overlap / width


def rebin(x: np.ndarray, w: np.ndarray) -> np.ndarray:
    """``(time, fine) @ (fine, coarse)`` with NaN kept where every contributor is NaN."""
    finite = np.isfinite(x)
    out = np.where(finite, x, 0.0) @ w
    any_finite = (finite.astype(np.float64) @ (w > 0)) > 0
    return np.where(any_finite, out, np.nan)


def align(ut_a, xa, ut_b, xb):
    """Rows of ``xa`` and ``xb`` on the seconds both carry."""
    common, ia, ib = np.intersect1d(ut_a, ut_b, return_indices=True)
    return common, xa[ia], xb[ib]


def poisson_ratio_ci(r, c_num, c_den, z=1.96):
    """95 % (default ``z``) log-normal interval on a ratio of two Poisson count totals."""
    if not (c_num > 0 and c_den > 0 and math.isfinite(r) and r > 0):
        return (None, None)
    s = math.sqrt(1.0 / c_num + 1.0 / c_den)
    return (r * math.exp(-z * s), r * math.exp(z * s))


# --------------------------------------------------------------------------- small stats helpers
def row_total(x: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    """Per-second sum across common bins; NaN only where every (unmasked) bin is NaN (a gap).
    ``mask`` (bool, one per bin column) selects the bin columns summed; ``mask=None`` sums
    every bin."""
    if mask is not None:
        x = x[:, mask]
    return np.where(np.isfinite(x).any(axis=1), np.nansum(x, axis=1), np.nan)



_row_total = row_total


def _spearman(x, y):
    """Spearman rho, or ``None`` when undefined. scipy is imported lazily."""
    from scipy.stats import spearmanr
    r = spearmanr(x, y)[0]
    r = float(r)
    return r if math.isfinite(r) else None


def _wilson_ci(k: int, n: int, z: float = 1.959964) -> tuple:
    if n == 0:
        return (None, None)
    phat = k / n
    denom = 1.0 + z * z / n
    centre = phat + z * z / (2 * n)
    half = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))
    return ((centre - half) / denom, (centre + half) / denom)




# --------------------------------------------------------------------------- coincidence vs lag
def build_lag_list(window: int) -> list[int]:
    """Every 1 s in [-30, 30], then the coarse +-magnitudes up to ``window``."""
    lags = set(range(-min(30, window), min(30, window) + 1))
    for m in _LAG_COARSE_STEPS:
        if m <= window:
            lags.add(m)
            lags.add(-m)
    return sorted(lags)


def coincidence_vs_lag(ut_a, c_a, ut_b, c_b, gate_a, gate_b, lags) -> dict:
    """P(other probe sees anything at t+L | this probe is dense at t), both directions, over a
    lag scan -- the discriminator between a clock offset (peak away from 0) and Poisson
    thinning of a shared cloud (peak at |L|<=1 s, symmetric decay back to the unconditional
    rate). Strength is reported on log1p Pearson and Spearman, never raw Pearson: on
    mostly-zero counts raw Pearson reports the leverage of a few dense seconds.
    """
    ut_a = np.asarray(ut_a)
    c_a = np.asarray(c_a, dtype=np.float64)
    ut_b = np.asarray(ut_b)
    c_b = np.asarray(c_b, dtype=np.float64)

    common0, a0, b0 = align(ut_a, c_a, ut_b, c_b)
    ok0 = np.isfinite(a0) & np.isfinite(b0)
    uncond_a = float(np.mean(a0[ok0] > 0)) if ok0.any() else None
    uncond_b = float(np.mean(b0[ok0] > 0)) if ok0.any() else None

    out_lags: list[int] = []
    p_b_given_a: list = []
    p_a_given_b: list = []
    wilson_b_given_a: list = []
    wilson_a_given_b: list = []
    n_b_given_a: list = []
    n_a_given_b: list = []
    pearson_log1p: list = []
    spearman: list = []

    for lag in lags:
        _, at, bshift = align(ut_a, c_a, ut_b - lag, c_b)   # b(t+L) beside a(t)
        ok = np.isfinite(at) & np.isfinite(bshift)
        dense = ok & (at >= gate_a)
        nb = int(dense.sum())
        kb = int((bshift[dense] > 0).sum()) if nb else 0
        p_b_given_a.append(kb / nb if nb else None)
        wilson_b_given_a.append(list(_wilson_ci(kb, nb)))
        n_b_given_a.append(nb)

        _, bt, ashift = align(ut_b, c_b, ut_a - lag, c_a)   # a(t+L) beside b(t)
        ok2 = np.isfinite(bt) & np.isfinite(ashift)
        dense2 = ok2 & (bt >= gate_b)
        na = int(dense2.sum())
        ka = int((ashift[dense2] > 0).sum()) if na else 0
        p_a_given_b.append(ka / na if na else None)
        wilson_a_given_b.append(list(_wilson_ci(ka, na)))
        n_a_given_b.append(na)

        if ok.sum() >= 2 and np.std(at[ok]) > 0 and np.std(bshift[ok]) > 0:
            l1a, l1b = np.log1p(at[ok]), np.log1p(bshift[ok])
            pearson_log1p.append(float(np.corrcoef(l1a, l1b)[0, 1]))
            spearman.append(_spearman(at[ok], bshift[ok]))
        else:
            pearson_log1p.append(None)
            spearman.append(None)
        out_lags.append(int(lag))

    peak_idx = None
    valid_p = [(i, v) for i, v in enumerate(p_b_given_a) if v is not None]
    if valid_p:
        peak_idx = max(valid_p, key=lambda iv: (iv[1], -abs(out_lags[iv[0]])))[0]
    peak_lag = out_lags[peak_idx] if peak_idx is not None else None
    peak_value = p_b_given_a[peak_idx] if peak_idx is not None else None

    half_width = None
    if peak_idx is not None and uncond_b is not None and peak_value is not None:
        half_level = uncond_b + 0.5 * (peak_value - uncond_b)
        assert peak_lag is not None  # set from out_lags whenever peak_idx is
        widths = []
        for step in (1, -1):
            i = peak_idx
            while 0 <= i + step < len(out_lags):
                i += step
                v = p_b_given_a[i]
                if v is not None and v <= half_level:
                    widths.append(abs(out_lags[i] - peak_lag))
                    break
        if widths:
            half_width = float(np.mean(widths))

    return {
        "lags_s": out_lags, "gate_a": gate_a, "gate_b": gate_b,
        "p_b_given_a": p_b_given_a, "wilson_b_given_a": wilson_b_given_a,
        "n_b_given_a": n_b_given_a,
        "p_a_given_b": p_a_given_b, "wilson_a_given_b": wilson_a_given_b,
        "n_a_given_b": n_a_given_b,
        "pearson_log1p": pearson_log1p, "spearman": spearman,
        "unconditional_a": uncond_a, "unconditional_b": uncond_b,
        "peak_lag_s": peak_lag, "peak_value": peak_value, "half_width_s": half_width,
        "n_overlap_lag0": int(len(common0)),
    }



# --------------------------------------------------------------------------- window means
NO_DATA_REASON = ("no finite value in any kept second of this window for this bin "
                  "(the chain's size ladder does not cover it, or every second is a gap there)")


def _window_bins(ut, nd, counts, window, min_cover, both_finite_mask) -> dict:
    """One product's fixed-UTC ``window``-s means.

    Called once per side of a pair with the *same* ``both_finite_mask`` -- computed by the caller
    from both chains at once as ``isfinite(tot_a) & isfinite(tot_b)`` -- so the two calls that make
    up one pair bin identical seconds on identical edges; this function has no way to pick its own.
    Zero-particle seconds are already zeros (:func:`zero_empty_rows`); a bin is kept
    when >= ``min_cover`` of its ``window`` seconds are finite on both sides.
    """
    ut = np.asarray(ut)
    if len(ut) == 0:
        return {"window_s": window, "min_cover": min_cover, "bins": []}
    edge0 = int(np.floor(ut.min() / window))
    edge1 = int(np.floor(ut.max() / window))
    out = []
    for b in range(edge0, edge1 + 1):
        t0 = b * window
        in_bin = (ut >= t0) & (ut < t0 + window)
        valid = in_bin & both_finite_mask
        n_valid = int(valid.sum())
        row = {"t0": int(t0), "n_valid": n_valid, "n_window": int(in_bin.sum()),
               "kept": n_valid >= max(min_cover, 1)}
        if row["kept"]:
            # A bin column with no finite value in any kept second has no mean: written as
            # JSON null, with the bins named and the reason stated, never a fabricated 0 and
            # never a NaN (which the allow_nan=False JSON write refuses). The usual cause is a
            # chain whose own size ladder does not reach that common bin at all.
            sub = nd[valid, :]
            n_fin = np.isfinite(sub).sum(axis=0)
            sums = np.nansum(sub, axis=0)
            row["mean_N"] = [float(sums[j] / n_fin[j]) if n_fin[j] else None
                             for j in range(sub.shape[1])]
            empty = [int(j) for j in np.flatnonzero(n_fin == 0)]
            if empty:
                row["mean_N_no_data_bins"] = empty
                row["mean_N_no_data_reason"] = NO_DATA_REASON
            row["sum_C"] = [float(v) for v in np.nansum(counts[valid, :], axis=0)]
            tot = np.nansum(nd[valid, :], axis=1)
            row["zero_frac"] = float(np.mean(tot <= 0.0))
        out.append(row)
    return {"window_s": window, "min_cover": min_cover, "bins": out}


def _combine_windows(fm_a: dict, fm_b: dict) -> dict:
    """Zip two single-side :func:`_window_bins` results (identical edges by construction)."""
    bins = []
    for ba, bb in zip(fm_a["bins"], fm_b["bins"], strict=True):
        row = {"t0": ba["t0"], "n_valid": ba["n_valid"], "n_window": ba["n_window"],
               "kept": ba["kept"]}
        if row["kept"]:
            row["mean_N_a"], row["mean_N_b"] = ba["mean_N"], bb["mean_N"]
            row["sum_C_a"], row["sum_C_b"] = ba["sum_C"], bb["sum_C"]
            row["zero_frac_a"], row["zero_frac_b"] = ba["zero_frac"], bb["zero_frac"]
            for side, src in (("a", ba), ("b", bb)):
                if "mean_N_no_data_bins" in src:
                    row[f"mean_N_{side}_no_data_bins"] = src["mean_N_no_data_bins"]
                    row[f"mean_N_{side}_no_data_reason"] = src["mean_N_no_data_reason"]
        bins.append(row)
    return {"window_s": fm_a["window_s"], "min_cover": fm_a["min_cover"], "bins": bins}



# --------------------------------------------------------------------------- scatter statistics
def scatter_stats(x, y, gate: tuple, gate_x=None, gate_y=None) -> dict:
    """Spearman + Pearson-of-log on every finite pair, RMA slope on the count-gated subset only
    (never raw Pearson).

    ``gate_x``/``gate_y`` default to ``x``/``y`` themselves (the 1 Hz layer's own reporting gate
    is on the counts it also correlates). The window-mean layer correlates *mean N* but gates on
    *summed counts* -- two different arrays over the same kept bins -- so its caller passes the
    counts here explicitly; reusing ``x``/``y`` for both would gate a concentration (order
    0.01-tens of cm-3) against a counts threshold that it can almost never cross.

    RMA (reduced major axis / standardised major axis), not OLS: both axes carry Poisson error of
    comparable size here, and OLS of y on x is attenuated toward zero by x's own error.
    ``slope = sign(r) * std(log10 y) / std(log10 x)``.
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    gvx = x if gate_x is None else np.asarray(gate_x, dtype=np.float64)
    gvy = y if gate_y is None else np.asarray(gate_y, dtype=np.float64)
    ok = np.isfinite(x) & np.isfinite(y)
    n = int(ok.sum())
    out: dict = {"n": n, "gate": [float(gate[0]), float(gate[1])],
                 "spearman": None, "pearson_log1p": None, "ratio_of_sums": None,
                 "n_gated": 0, "pearson_log_gated": None,
                 "rma_slope_log10": None, "rma_intercept_log10": None,
                 "median_ratio_gated": None}
    if n == 0:
        return out
    xf, yf = x[ok], y[ok]
    out["frac_both_zero"] = float(np.mean((xf == 0) & (yf == 0)))
    out["frac_x_zero"] = float(np.mean(xf == 0))
    out["frac_y_zero"] = float(np.mean(yf == 0))
    out["sum_x"] = float(np.sum(xf))
    out["sum_y"] = float(np.sum(yf))
    if out["sum_x"] > 0:
        out["ratio_of_sums"] = float(out["sum_y"] / out["sum_x"])
    if n >= 2 and np.std(xf) > 0 and np.std(yf) > 0:
        out["spearman"] = _spearman(xf, yf)
    lx, ly = np.log1p(xf), np.log1p(yf)
    if n >= 2 and np.std(lx) > 0 and np.std(ly) > 0:
        out["pearson_log1p"] = float(np.corrcoef(lx, ly)[0, 1])

    gx, gy = gate
    ok_gate = ok & np.isfinite(gvx) & np.isfinite(gvy)
    gated = ok_gate.copy()
    gated[ok_gate] = (gvx[ok_gate] >= gx) & (gvy[ok_gate] >= gy)
    xg_all, yg_all = x[gated], y[gated]
    pos = (xg_all > 0) & (yg_all > 0)
    xg, yg = np.log10(xg_all[pos]), np.log10(yg_all[pos])
    ng = int(len(xg))
    out["n_gated"] = int(gated.sum())
    out["n_gated_positive"] = ng
    if ng >= 2 and np.std(xg) > 0 and np.std(yg) > 0:
        r = float(np.corrcoef(xg, yg)[0, 1])
        sx, sy = float(np.std(xg, ddof=1)), float(np.std(yg, ddof=1))
        slope = math.copysign(sy / sx, r) if r != 0 else sy / sx
        out["pearson_log_gated"] = r
        out["rma_slope_log10"] = float(slope)
        out["rma_intercept_log10"] = float(np.mean(yg) - slope * np.mean(xg))
        out["median_ratio_gated"] = float(np.median(yg_all[pos] / xg_all[pos]))
    return out


# --------------------------------------------------------------------------- per-bin totals
def bin_stats(nd_a, ct_a, nd_b, ct_b, sel) -> list[dict]:
    """Per-common-bin totals and the ratio ``R_b_over_a = sum N_b / sum N_a`` over the selected
    seconds where both products are finite in that bin, with a Poisson 95 % interval."""
    rows = []
    for j in range(nd_a.shape[1]):
        ok = sel & np.isfinite(nd_a[:, j]) & np.isfinite(nd_b[:, j])
        s2, sc = float(np.sum(nd_a[ok, j])), float(np.sum(nd_b[ok, j]))
        c2, cc = float(np.nansum(ct_a[ok, j])), float(np.nansum(ct_b[ok, j]))
        r = sc / s2 if s2 > 0 else float("nan")
        lo, hi = poisson_ratio_ci(r, cc, c2)
        rows.append({"n_seconds": int(ok.sum()), "counts_a": c2, "counts_b": cc,
                     "sumN_a_cm3s": s2, "sumN_b_cm3s": sc,
                     "R_b_over_a": r if math.isfinite(r) else None,
                     "R_ci95": [lo, hi]})
    return rows


def window_means(ut, nd_a, ct_a, nd_b, ct_b, *, window_s: int = DEFAULT_WINDOW_S,
                 min_cover: int = DEFAULT_MIN_COVER, both_finite) -> dict:
    """Fixed-UTC ``window_s``-second means of both products, binned on identical seconds.

    ``both_finite`` is the per-second mask of seconds finite on both sides; a window is kept when
    at least ``min_cover`` of its seconds are in it. Each kept row carries ``mean_N_a``/``mean_N_b``
    (per common bin), ``sum_C_a``/``sum_C_b`` (summed counts) and ``zero_frac_a``/``zero_frac_b``.
    """
    fm_a = _window_bins(ut, nd_a, ct_a, window_s, min_cover, both_finite)
    fm_b = _window_bins(ut, nd_b, ct_b, window_s, min_cover, both_finite)
    return _combine_windows(fm_a, fm_b)


# --------------------------------------------------------------------------- size distributions
def size_distributions(chain: dict, edges=COMMON_EDGES_UM) -> dict:
    """Period-integrated dN/dD [cm-3 um-1] on the product's own native grid and on ``edges``: the
    sum over seconds of N per bin, divided by the count of finite seconds and by the bin width."""
    nd = chain["nd"]
    finite = np.isfinite(nd)
    n_seconds = int(finite.any(axis=1).sum())
    bmin = np.asarray(chain["bmin"], dtype=np.float64)
    bmax = np.asarray(chain["bmax"], dtype=np.float64)
    width = bmax - bmin
    counted = finite.sum(axis=0)
    summed = np.nansum(nd, axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        dndd_native = np.where(counted > 0, summed / np.maximum(counted, 1) / width, np.nan)
    bin_mid = (bmin + bmax) / 2.0

    w = rebin_weights(bmin, bmax, edges)
    nd_c = rebin(nd, w)
    finite_c = np.isfinite(nd_c)
    width_c = np.diff(edges)
    counted_c = finite_c.sum(axis=0)
    summed_c = np.nansum(nd_c, axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        dndd_common = np.where(counted_c > 0, summed_c / np.maximum(counted_c, 1) / width_c,
                               np.nan)

    return {
        "n_seconds": n_seconds,
        "native": {"bin_min_um": [float(v) for v in bmin], "bin_max_um": [float(v) for v in bmax],
                   "bin_mid_um": [float(v) for v in bin_mid],
                   "dNdD_cm3_um": [float(v) if np.isfinite(v) else None for v in dndd_native]},
        "common": {"edges_um": [float(e) for e in edges],
                   "dNdD_cm3_um": [float(v) if np.isfinite(v) else None for v in dndd_common]},
    }


# --------------------------------------------------------------------------- exclusions
def _exclusion_mask(edges, exclude_from_totals) -> np.ndarray:
    """``True`` for every common bin of ``edges`` except those whose lower edge matches the lower
    edge of an ``(lo_um, hi_um)`` entry of ``exclude_from_totals`` (within 0.5 um)."""
    edges = np.asarray(edges, dtype=np.float64)
    mask = np.ones(max(len(edges) - 1, 0), dtype=bool)
    for lo, _hi in exclude_from_totals or ():
        for j in range(len(edges) - 1):
            if abs(float(edges[j]) - float(lo)) <= 0.5:
                mask[j] = False
                break
    return mask


def _comparable_sum(values, mask) -> float:
    """Sum of ``values`` where ``mask`` is truthy, leaving out ``None`` bins; NaN when no included
    bin has data. ``mask=None`` sums everything."""
    if not values:
        return 0.0
    if mask is None:
        mask = [True] * len(values)
    have = [v for v, m in zip(values, mask, strict=True) if m and v is not None]
    return float(sum(have)) if have else float("nan")


# --------------------------------------------------------------------------- orchestration
def compare_pair(a: dict, b: dict, *, edges=COMMON_EDGES_UM, edge_shift_um: float = 12.5,
                 exclude_from_totals=None, window_s: int = DEFAULT_WINDOW_S,
                 min_cover: int = DEFAULT_MIN_COVER, count_gate: tuple = DEFAULT_COUNT_GATE,
                 count_gate_window: tuple = DEFAULT_COUNT_GATE_WINDOW, lags=None,
                 gate_a: float = 20.0, gate_b: float = 5.0) -> dict:
    """Compare two products ``a`` and ``b`` (each a :func:`load_sd` dict) on the ``edges`` grid.

    Returns the per-bin ratios ``N_b / N_a`` with a Poisson interval and an edge-shift band
    (``b`` rebinned with its edges moved by -/+ ``edge_shift_um``), ``window_s`` means, scatter
    statistics at 1 Hz and on the window means (count-gated, never raw Pearson), the
    coincidence-versus-lag curve and both size distributions. ``exclude_from_totals`` is a list of
    ``(lo_um, hi_um)`` common bins left out of every aggregate; each still appears in ``bins``,
    with ``comparable=False``. ``lags=None`` means :func:`build_lag_list` ``(600)``.
    """
    lags = build_lag_list(600) if lags is None else lags
    wa = rebin_weights(a["bmin"], a["bmax"], edges)
    wb = rebin_weights(b["bmin"], b["bmax"], edges)
    nd_a_full, ct_a_full = rebin(a["nd"], wa), rebin(a["counts"], wa)
    nd_b_full, ct_b_full = rebin(b["nd"], wb), rebin(b["counts"], wb)

    common_ut, nd_a, nd_b = align(a["ut"], nd_a_full, b["ut"], nd_b_full)
    _, ct_a, ct_b = align(a["ut"], ct_a_full, b["ut"], ct_b_full)
    keep = np.ones(len(common_ut), dtype=bool)

    mask = _exclusion_mask(edges, exclude_from_totals)
    tot_a, tot_b = row_total(nd_a, mask), row_total(nd_b, mask)
    ctot_a, ctot_b = row_total(ct_a, mask), row_total(ct_b, mask)
    both_finite = np.isfinite(tot_a) & np.isfinite(tot_b) & keep

    rows = bin_stats(nd_a, ct_a, nd_b, ct_b, keep)
    sens: dict[str, list] = {}
    for sh in (-edge_shift_um, edge_shift_um):
        wb_s = rebin_weights(b["bmin"], b["bmax"], edges, shift_um=sh)
        _, _, nd_b_s = align(a["ut"], nd_a_full, b["ut"], rebin(b["nd"], wb_s))
        _, _, ct_b_s = align(a["ut"], ct_a_full, b["ut"], rebin(b["counts"], wb_s))
        sens[f"{sh:+g}"] = [r["R_b_over_a"] for r in bin_stats(nd_a, ct_a, nd_b_s, ct_b_s, keep)]
    for k, r in enumerate(rows):
        r["bin_um"] = [float(edges[k]), float(edges[k + 1])]
        r["R_edge_shift"] = {s: v[k] for s, v in sens.items()}
        r["comparable"] = bool(mask[k])

    win = window_means(common_ut, nd_a, ct_a, nd_b, ct_b, window_s=window_s,
                       min_cover=min_cover, both_finite=both_finite)
    kept = [w for w in win["bins"] if w.get("kept")]
    sc_w = scatter_stats(np.array([_comparable_sum(w["mean_N_a"], mask) for w in kept]),
                         np.array([_comparable_sum(w["mean_N_b"], mask) for w in kept]),
                         gate=count_gate_window,
                         gate_x=np.array([_comparable_sum(w["sum_C_a"], mask) for w in kept]),
                         gate_y=np.array([_comparable_sum(w["sum_C_b"], mask) for w in kept]))
    sc1 = scatter_stats(np.where(keep, ctot_a, np.nan), np.where(keep, ctot_b, np.nan),
                        gate=count_gate)
    coinc = coincidence_vs_lag(a["ut"], row_total(ct_a_full), b["ut"], row_total(ct_b_full),
                               gate_a, gate_b, lags)
    return {
        "overlap_seconds": int(len(common_ut)), "both_finite_seconds": int(both_finite.sum()),
        "bins": rows, "windows": win, "scatter_1hz": sc1, "scatter_window": sc_w,
        "coincidence": coinc,
        "size_distributions": {"a": size_distributions(a, edges),
                               "b": size_distributions(b, edges)},
        "count_gate": list(count_gate), "count_gate_window": list(count_gate_window),
        "edges_um": [float(e) for e in edges],
        "excluded_from_totals_um": [[float(lo), float(hi)]
                                    for lo, hi in (exclude_from_totals or ())],
    }

