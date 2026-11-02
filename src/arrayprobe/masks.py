# SPDX-License-Identifier: BSD-3-Clause
"""Stuck-diode masks: an archived production chain's diode re-illumination.

The ORACLES products were not made by either MATLAB tree this port had on disk
when S3 was written.  They were made by a **nine-argument** ``imgProc_sm`` that
exists here only as a dissertation Appendix-B extraction, and the whole
substantive difference between it and the six-argument variant tree file is one
guarded block (extraction ``:286-292``)::

    if exist([path '/' 'diode.' flight file '.' infile(end-4) '.mat'],'file')==2;
        load([path '/' 'diode.' flight file '.' infile(end-4) '.mat'],'shadow_diode');
        c(:,shadow_diode)='1';
    else
    end

``c`` is the particle's char image with ``'1'`` marking a **lit** diode
(``imgProc_sm.m:266`` inverts through ``65535 - data``), so the assignment
declares the listed photodiodes illuminated no matter what the probe recorded.
It runs *before* habit classification, rejection, sizing and the smallest
enclosing circle, so it reaches every one of the 41 written variables -- the
widest blast radius of any divergence found in this port.

The masks come from ``find_shadow_diodes.m``, ported here as
:func:`find_shadow_diodes`, which reads ``bin_stats`` back out of a first-pass
proc file, calls a diode "stuck" when it is lit for less than 80% of the array
**max** -- or of the **mean**, when some diode reads above 1.2 x mean (the
inconsistent shadow-diode selection rule) -- and saves the list.  Processing is therefore a
two-pass affair: process, find the stuck diodes, process again with them re-illuminated
(``examples/5_data_quality/01_find_stuck_diodes.ipynb``).

Three behaviours of the MATLAB are reproduced here deliberately, because each
can decide whether a product is reproducible:

1. **A missing or differently-named file is silent.**  ``exist(...)==2`` simply
   fails and the run proceeds unmasked, with nothing in the output recording
   that masking did not happen -- and the ORACLES variant writes no netCDF
   attributes at all, so the product cannot be interrogated afterwards either.
2. **An empty result is given a name the loader cannot find.**
   ``find_shadow_diodes.m:103-107`` writes ``diode.<date><time>.<or>.mat`` when
   the mask is non-empty and ``diode.<date><time>.<or>empty.mat`` when it is
   empty.  ``empty`` is glued straight onto the orientation letter, so the file
   the loader looks for does not exist, and the branch is skipped.  Equivalent
   in effect to an empty mask, and much harder to notice.
3. **An out-of-range diode number widens the image instead of erroring.**  See
   :func:`reilluminate`.

For the 09/06/2016 2D-S flight the recovered masks are empty, so this block is
inert for that product.
It is *not* inert in general: the 09/06 HVPS mask names
diodes 2 and 128, and later flights name others.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from arrayprobe_uiops.diode_mask import (
    HIGH_FRACTION,
    STUCK_FRACTION,
    ShadowDiodeMask,
    stuck_diodes,
)
from arrayprobe_uiops.diode_mask import reilluminate as _reilluminate

from .matio import loadmat
from .matlab_compat import MatlabIndexError

__all__ = [
    "STUCK_FRACTION",
    "HIGH_FRACTION",
    "ShadowDiodeMask",
    "MaskFileError",
    "load_shadow_diode_mask",
    "matlab_mask_filename",
    "orientation_from_infile",
    "find_shadow_diode_mask",
    "reilluminate",
    "ShadowDiodeSearch",
    "ShadowDiodeSearchError",
    "find_shadow_diodes",
]

class MaskFileError(ValueError):
    """A ``diode.*.mat`` file that cannot be used as a shadow-diode mask."""


def load_shadow_diode_mask(path) -> ShadowDiodeMask:
    """Read a ``diode.*.mat`` written by ``find_shadow_diodes.m:104``."""
    path = Path(path)
    mat = loadmat(path)
    if "shadow_diode" not in mat:
        raise MaskFileError(
            f"{path} has no 'shadow_diode' variable (found: "
            f"{', '.join(sorted(mat.keys())) or 'nothing'}). "
            "imgProc_sm.m loads that name specifically."
        )
    raw = mat["shadow_diode"]
    if isinstance(raw, str):
        raise MaskFileError(f"{path}: 'shadow_diode' is char data, expected numeric")
    diodes = np.asarray(raw, dtype=np.float64).ravel(order="F")

    def _text(name):
        v = mat.variables.get(name)
        return v if isinstance(v, str) else None

    return ShadowDiodeMask(
        diodes=diodes,
        date=_text("date"),
        time=_text("time"),
        source=path,
        header=mat.header,
    )


def orientation_from_infile(infile) -> str:
    """``infile(end-4)`` -- the orientation letter in ``...<H|V>.cdf``.

    MATLAB indexes the *fifth character from the end*, which for
    ``base160906064403.V.cdf`` is ``'V'``.  It is a positional index, not a
    parse: on any name whose last five characters are not ``X.cdf`` it returns
    whatever sits there, and the lookup then quietly finds no file.
    """
    name = Path(infile).name if not isinstance(infile, str) else infile
    name = Path(name).name
    if len(name) < 5:
        raise MaskFileError(
            f"{name!r} is shorter than five characters, so MATLAB's "
            "infile(end-4) would be an index error"
        )
    return name[-5]


def matlab_mask_filename(flight: str, file: str, orientation: str) -> str:
    """``['diode.' flight file '.' orientation '.mat']`` -- imgProc_sm ``:288``."""
    return f"diode.{flight}{file}.{orientation}.mat"


def find_shadow_diode_mask(path, flight: str, file: str, infile) -> ShadowDiodeMask | None:
    """Reproduce ``if exist([...],'file')==2`` -- returning ``None`` when absent.

    ``None`` is the honest result: MATLAB's ``else`` branch is empty, so a
    missing file means the image is used exactly as decoded and **nothing is
    recorded anywhere** to say masking was skipped.  Callers that care must
    check for themselves; the archived products cannot be interrogated after the
    fact, because the variant writes no attributes.
    """
    orientation = orientation_from_infile(infile)
    candidate = Path(path) / matlab_mask_filename(flight, file, orientation)
    if not candidate.is_file():
        return None
    return load_shadow_diode_mask(candidate)


#: Where the source of :func:`find_shadow_diodes` lives: a dissertation
#: Appendix-B extraction, promoted to a runnable ``.m`` by
#: ``octave_oracle/recover_dissertation_sources.py`` (PDF artifacts only).
FIND_SHADOW_DIODES_SOURCE = "archive/staging_variant_raw/find_shadow_diodes.m.raw.txt"

#: ``find_shadow_diodes.m:30-31`` -- the directory is hard-coded, not an input.
MATLAB_FIND_SHADOW_DIODES_PATH = "/condo/mcfarq/sid/b/{campaign}/{campaign}_20{date}/"


#: ``STUCK_FRACTION`` (0.80, ``:94``/``:97``) and ``HIGH_FRACTION`` (1.2, ``:66``) live in
#: :mod:`arrayprobe_uiops.diode_mask` with the rule; imported above.


def _saved_mask_filename(date: str, time: str, orientation: str, empty: bool) -> str:
    """``:103-107``: ``diode.<date><time>.<or>.mat``, or ``...<or>empty.mat``.

    Upstream quirk: ``empty`` is glued onto the orientation
    letter, so :func:`find_shadow_diode_mask` -- ``imgProc_sm.m:288`` -- never
    finds an empty mask.  Preserved.
    """
    return f"diode.{date}{time}.{orientation}{'empty' if empty else ''}.mat"


class ShadowDiodeSearchError(RuntimeError):
    """A ``bin_stats`` input on which ``find_shadow_diodes.m`` dies before saving."""


@dataclass(frozen=True)
class ShadowDiodeSearch:
    """What one ``find_shadow_diodes(date,time,orientation)`` call computed."""

    shadow_diode: np.ndarray
    """1-based diode numbers, float64, sorted -- ``sort(find(...))`` (``:94-98``)."""

    a: np.ndarray
    """``bin_stats`` as saved: int32, after ``:66-69``'s high-count replacement."""

    bin_stats: np.ndarray
    """``bin_stats`` as read at ``:41``, before any replacement (int32)."""

    ill_diode: np.ndarray
    """1-based diodes over ``1.2*mean(a)`` (``:66``), float64; usually empty."""

    branch: str
    """``"mean"`` when ``ill_diode`` was non-empty (``:94``), else ``"max"`` (``:97``)."""

    threshold: float
    """The value ``a`` was compared against: ``0.80*mean(a)`` (double) or
    ``0.80*max(a)`` (int32, returned here as a float)."""

    written: Path | None
    """The ``.mat`` written, or ``None`` when the caller asked for no write."""


def _read_bin_stats(infile) -> np.ndarray:
    """``a=ncread(infile,'bin_stats')`` (``:41``): an int32 column vector.

    Read raw.  ``bin_stats`` is defined ``'int'`` with no ``_FillValue`` or
    scale attributes (``imgProc_sm.m:438``), so MATLAB's ``ncread`` returns the
    stored values unconverted, as int32 -- and the class matters below.
    netCDF4-python would mask a value equal to the library's *default* fill
    even without the attribute, which MATLAB does not do.
    """
    import netCDF4

    with netCDF4.Dataset(str(infile)) as ds:
        var = ds.variables["bin_stats"]
        var.set_auto_maskandscale(False)
        raw = np.asarray(var[...])
    return raw.astype(np.int32).reshape(-1)


def find_shadow_diodes(date: str, time: str, orientation: str, *, path,
                       infile=None, write: bool = True, counts: str = "lit",
                       slice_total: int | None = None) -> ShadowDiodeSearch:
    """Port of ``find_shadow_diodes.m``: find stuck diodes from a first-pass proc.

    MATLAB-order arguments -- ``date`` ``'YYMMDD'``, ``time`` ``'HHMMSS'``,
    ``orientation`` ``'H'``/``'V'`` -- and the MATLAB-order result: 1-based
    diode numbers in :attr:`ShadowDiodeSearch.shadow_diode`, ready for
    ``[run].diode_masks`` and :func:`reilluminate`.

    ``path`` stands in for ``:31``'s hard-coded
    ``/condo/mcfarq/sid/b/oracles/oracles_20<date>/`` (see
    :data:`MATLAB_FIND_SHADOW_DIODES_PATH`), and is used exactly as MATLAB uses
    it: glued by string concatenation, so it should end in a separator.  The
    input defaults to ``[path 'base' date time '.' orientation '_1.cdf']``
    (``:40``); ``infile`` overrides it, for this port's ``proc.*.nc`` names.

    **The rule is not the one the file's own header states.**  The header says
    "<80% of max count"; the 06/20/2018 note says "<80% of mean count".  The
    code does both, depending on a third test:

    * ``:66`` -- if any diode reads **above 1.2 x mean** (a diode masked
      in-flight, which reads lit on every slice), those diodes are replaced by
      the array's ``nanmean`` (``:68-69``) and a diode is stuck when it is
      below **0.80 x mean** of the replaced array (``:94``);
    * otherwise a diode is stuck when it is below **0.80 x max** (``:97``).

    **Polarity.**  The rule is written for **lit** counts (``counts="lit"``, the
    default and the production fork's ``bin_stats``).  Stock UIOOPS (v3.1.4 stock
    and every v3.5 proc file) writes **shadowed** counts instead
    (``imgProc_sm.m`` v3.5 ``:1208,1210``); a caller holding such a file passes
    ``counts="shadowed"`` and ``slice_total`` (the slice total ``S`` every
    diode saw, ``tune.diodes.position_slice_total``) and the counts are
    converted as ``lit = S - shadowed`` before the rule runs.  Fed unconverted,
    the rule reads the stuck diode as the busiest one and flags nearly
    everything else.  ``counts="shadowed"`` without ``slice_total`` raises.

    Quirks reproduced, each pinned by a test:

    1. **The NaN does not survive.**  ``a`` is int32 (``bin_stats`` is
       ``'int'``), and ``a(ill_diode)=NaN`` stores 0 -- MATLAB's int32(NaN).
       ``nanmean`` therefore sees no NaN and averages the zeros in: the
       replacement value is diluted by ``len(ill_diode)/n`` rather than being
       the mean of the other diodes the comment promises.  Octave does the same.
    2. **``0.80*max(a)`` is int32**, rounded half away from zero (integer
       dominance).  For integer ``a`` this can never change a comparison, but
       it is kept as MATLAB computes it.
    3. **An empty result is saved as ``diode.<date><time>.<or>empty.mat``**
       (``:105-106``), a name ``imgProc_sm.m:288`` never constructs.
    4. **A non-positive array mean kills the run before any save.**  ``:55``'s
       ``ylim([0 1.5*nanmean(a)])`` needs increasing limits, so a proc whose
       ``bin_stats`` is all zero (no particles) or never written ends in an
       error, not an empty mask.  Raised here as
       :class:`ShadowDiodeSearchError`.

    Not reproduced: the two ``.jpeg`` figures (``:44-63``, ``:72-91``) -- a
    picture is not a computed number; ``arrayprobe diode-masks`` and
    ``examples/5_data_quality/01_find_stuck_diodes.ipynb`` draw the same counts.

    The ``.mat`` holds the whole workspace left by ``:100``'s ``clearvars
    -except path orientation shadow_diode date time a``, in MATLAB's ``who``
    (alphabetical) order.  ``path`` is saved as the string passed here.
    """
    from .matio import savemat
    from .matlab_compat import msum

    path_s = str(path)
    if infile is None:
        infile = f"{path_s}base{date}{time}.{orientation}_1.cdf"
    if counts not in ("lit", "shadowed"):
        raise ValueError(f"counts must be 'lit' or 'shadowed', not {counts!r}")
    bin_stats = _read_bin_stats(infile)
    if counts == "shadowed":
        if slice_total is None:
            raise ValueError("counts='shadowed' needs slice_total, the slice total S "
                             "(lit = S - shadowed)")
        if bin_stats.size and int(bin_stats.max()) > int(slice_total):
            raise ValueError(f"a shadow count ({int(bin_stats.max())}) exceeds "
                             f"slice_total={int(slice_total)}")
        bin_stats = (int(slice_total) - bin_stats.astype(np.int64)).astype(bin_stats.dtype)
    a = bin_stats.copy()
    n = a.size

    def mean(x):
        # MATLAB `mean` of an integer array: double, sum(double(x))/n.  Exact
        # here -- integer counts sum exactly in double below 2^53.
        return float(msum(x.astype(np.float64))) / x.size if x.size else float("nan")

    first_ylim = 1.5 * mean(a)             # :55, nanmean of a NaN-free array
    if not first_ylim > 0:
        raise ShadowDiodeSearchError(
            f"{infile}: find_shadow_diodes.m:55 ylim([0 1.5*nanmean(a)]) = "
            f"[0 {first_ylim:g}] is not increasing -- MATLAB stops here and saves "
            "nothing. bin_stats is all zero, empty or unwritten "
            f"(n={n}, sum={int(a.astype(np.int64).sum()) if n else 0}).")

    rule = stuck_diodes(a)                 # :66-97, shared with the v3.5 engine
    a, ill, branch, threshold = rule.a, rule.ill_diode, rule.branch, rule.threshold
    shadow_diode = rule.shadow_diode

    written = None
    if write:
        written = Path(path_s + _saved_mask_filename(date, time, orientation,
                                                     not shadow_diode.size))
        savemat(written, {"a": a, "date": date, "orientation": orientation,
                          "path": path_s, "shadow_diode": shadow_diode,
                          "time": time})
    return ShadowDiodeSearch(shadow_diode=shadow_diode, a=a, bin_stats=bin_stats,
                             ill_diode=ill, branch=branch, threshold=threshold,
                             written=written)


def reilluminate(c: np.ndarray, diodes) -> np.ndarray:
    """``c(:,shadow_diode)='1'`` (extraction ``:290``), through
    :func:`arrayprobe_uiops.diode_mask.reilluminate`.

    A zero, negative or fractional entry raises :class:`MatlabIndexError`, as
    MATLAB does; an index past the last diode widens the image, so
    ``imgProc_sm.m:272-276``'s width guard fires as in MATLAB.
    """
    return _reilluminate(c, diodes, index_error=MatlabIndexError)
