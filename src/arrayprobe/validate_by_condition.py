# SPDX-License-Identifier: BSD-3-Clause
"""Per-second agreement against an archived product, stratified by cloud condition.

**Why stratify at all.** A single headline percentage can hide a whole regime.
Written 2026-08-28 for the author's ask that validation be checked *"on multiple
samples, in and out of cloud, and over different conditions"*, and its first run
earned that ask immediately: the used-bin deficit was 70 % / 62 % / 62 % across
sparse / moderate / dense, which one number over the whole flight would have
averaged into something that looked merely disappointing rather than
regime-dependent.

**Condition is taken from the REFERENCE, never from ours.** The band for each
second is decided by the *product's* own per-second particle total across all
bins -- its measure of how much cloud the probe was in. Using our own total
would make the stratification depend on the thing being tested: a second we
under-count would be filed as sparser than it was, and the sparse band would
then flatter us with a second that belongs in the dense one.

**In ``src/`` since 2026-09-10.** This was 131 lines inside
a script and every number it computed went straight
into a ``print``, so nothing could assert on any of it -- the one part of the
validation story with no test was the part that answers the author's own
question. :func:`stratify` returns the numbers; formatting is the caller's.
"""

from __future__ import annotations

import dataclasses
import glob
import os
import re

import netCDF4
import numpy as np

__all__ = ["BANDS", "BandResult", "Stratification", "find_product", "stratify"]

#: Lower bound (inclusive), upper bound (exclusive), label. The boundaries are
#: the author's, from the 2026-08-28 run, and are deliberately round: they are
#: a way of slicing a flight for inspection, not a published classification, so
#: nothing downstream should read them as a definition of "dense cloud".
BANDS = (
    (0, 1, "clear   (0/s)"),
    (1, 100, "sparse  (1-100/s)"),
    (100, 5000, "moderate(100-5k/s)"),
    (5000, 10 ** 9, "dense   (>5k/s)"),
)

#: No built-in products directory, and no assumption about how one is laid out:
#: pass ``product_dir`` (``--product-dir``) or set ``ARRAYPROBE_PRODUCT_DIR`` to the
#: directory that holds the products of record.
DEFAULT_PRODUCTS: str | None = None

#: The environment variable naming the directory that holds the products of record.
PRODUCT_DIR_ENV = "ARRAYPROBE_PRODUCT_DIR"


def resolve_product_dir(product_dir: str | None = None) -> str:
    """``product_dir`` if given, else ``$ARRAYPROBE_PRODUCT_DIR``, used as given.

    Raises ``ValueError`` when neither is given, rather than guessing a location.
    """
    if product_dir:
        return product_dir
    env = os.environ.get(PRODUCT_DIR_ENV)
    if env:
        return env
    raise ValueError(
        "no products-of-record directory: pass --product-dir (product_dir=) or set "
        f"{PRODUCT_DIR_ENV} to the directory that holds the products of record")


@dataclasses.dataclass(frozen=True)
class BandResult:
    """One condition band's totals. Ratios are left to the caller.

    ``all_*`` covers every bin; ``used_*`` drops the first ``drop_bins``, which
    is what the project's headline figures quote -- the low bins are where the
    probe's own response, not the port, dominates the disagreement.
    """

    label: str
    seconds: int
    all_ours: float
    all_ref: float
    used_ours: float
    used_ref: float
    #: Seconds where every bin matches exactly, in that band.
    exact_seconds: int


@dataclasses.dataclass(frozen=True)
class Stratification:
    """One comparison: the bands, the whole-window total, and how it was scoped.

    Carries ``drop_bins`` and both second counts as well as the numbers,
    because a band table read without them is ambiguous -- "used" means
    nothing until you know how many bins the band drops, and a window's totals
    read as a whole flight's unless the two second counts are visible side by
    side.
    """

    ours_path: str
    ref_path: str
    shared_seconds: int
    #: Seconds inside ``--window``; equal to ``shared_seconds`` without one.
    window_seconds: int
    drop_bins: int
    bands: tuple[BandResult, ...]
    #: Every second in the window, as one band. Not the sum of ``bands``: a
    #: band with no seconds is omitted from that tuple, and this is computed
    #: over the mask directly either way.
    overall: BandResult


def _seconds_of(ds) -> np.ndarray:
    """``Time Vector`` is a MATLAB datenum; the shared key is the whole second."""
    tv = np.asarray(ds.variables["Time Vector"][:], float)
    return np.round((tv - np.floor(tv[0])) * 86400).astype(np.int64)


def _counts_of(ds) -> np.ndarray:
    """``Counts`` as (bins, time), whichever way the file stores it.

    **The orientation is decided by looking for 128**, the 2D-S/HVPS bin
    count, because a combined product stores the array either way round and
    its dimension names cannot be relied on across the two trees. That makes
    128 a hard assumption rather than a convention: an array with any other
    bin count is transposed unconditionally, so its seconds and bins swap
    silently. Every real product has 128 bins; a synthetic fixture with fewer
    does not, and one written that way put four seconds spanning four
    condition bands into a single band without error (2026-09-10).
    """
    a = np.nan_to_num(np.asarray(ds.variables["Counts"][:], float))
    return a if a.shape[0] == 128 else a.T


def parse_hhmmss(x: str) -> int:
    """``HHMMSS`` as seconds since midnight.

    ``int(x)`` first, so ``"070000"`` is 7 h and not an octal-looking string;
    the fields are then split arithmetically rather than by slicing, which
    keeps a malformed length a ``ValueError`` from ``int`` rather than a
    silently wrong time.
    """
    v = int(x)
    return (v // 10000) * 3600 + ((v // 100) % 100) * 60 + v % 100


def find_product(path: str, product_dir: str | None = DEFAULT_PRODUCTS) -> str | None:
    """The archived product whose stem's date matches ``path``'s, if one exists.

    Matched on the six-digit date in ``base<YYMMDD>``, not on the whole stem: a
    product's stem is the flight's summary-file timestamp and ours is a raw
    file's, so the two agree on the date and generally not on the time.
    ``product_dir`` falls back to :func:`resolve_product_dir`.
    """
    m = re.search(r"base(\d{6})", os.path.basename(path))
    if not m:
        return None
    product_dir = resolve_product_dir(product_dir)
    hits = sorted(glob.glob(os.path.join(
        product_dir, f"base{m.group(1)}*.combined.H.2DS_2.cdf")))
    return hits[0] if hits else None


def stratify(ours_path: str, ref_path: str, window: str | None = None,
             drop_bins: int = 5) -> Stratification:
    """Compare ``ours_path`` against ``ref_path`` second by second, by band.

    ``window`` is ``HHMMSS-HHMMSS``, inclusive-exclusive, so a partially
    processed flight can be compared only where every contributing raw file is
    present -- otherwise its missing hours land in the clear band and inflate
    the agreement.
    """
    with netCDF4.Dataset(ours_path) as ours, netCDF4.Dataset(ref_path) as ref:
        os_, rs = _seconds_of(ours), _seconds_of(ref)
        shared, oi, ri = np.intersect1d(os_, rs, return_indices=True)
        x, y = _counts_of(ours)[:, oi], _counts_of(ref)[:, ri]

    win = np.ones(shared.size, bool)
    if window:
        lo, hi = (parse_hhmmss(v) for v in window.split("-"))
        win = (shared >= lo) & (shared < hi)
    density = y.sum(0)

    def band(label: str, mask: np.ndarray) -> BandResult:
        return BandResult(
            label=label,
            seconds=int(mask.sum()),
            all_ours=float(x[:, mask].sum()),
            all_ref=float(y[:, mask].sum()),
            used_ours=float(x[drop_bins:, mask].sum()),
            used_ref=float(y[drop_bins:, mask].sum()),
            exact_seconds=int(
                (np.abs(x[:, mask] - y[:, mask]).sum(0) == 0).sum()),
        )

    bands = tuple(
        band(label, mask)
        for lo, hi, label in BANDS
        if (mask := win & (density >= lo) & (density < hi)).any()
    )
    return Stratification(
        ours_path=ours_path, ref_path=ref_path, shared_seconds=int(shared.size),
        window_seconds=int(win.sum()), drop_bins=drop_bins, bands=bands,
        overall=band("ALL", win),
    )
