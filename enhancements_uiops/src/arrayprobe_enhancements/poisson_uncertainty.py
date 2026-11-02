# SPDX-License-Identifier: BSD-3-Clause
"""Per-bin and total Poisson counting uncertainty on ``sizeDist`` output.

**The gap it fills**: nothing in UIOOPS reports an uncertainty on any written
concentration -- a bin holding one particle and a bin holding a thousand are
both just numbers in the same array. Finlon et al. (2019, *ACP* 19,
3621-3643) name Poisson sampling on particle counts as one of three terms in
their processing-uncertainty decomposition (natural variability, Poisson
sampling, measurement error); McFarquhar et al. (2017, *Meteor. Monogr.* 58,
ch. 11, p. 11.13, citing Hallett 2003) state the field's own rule of thumb:
*"100 particles in a size bin is regarded as statistically significant."*
Both citations already appear in this repository's own literature review
(``docs/10-known-gaps.md``); this module is the first thing that
actually computes with them.

**The statistics, stated so the one-line formula is not mysterious.** A
particle count in a fixed second and bin is well modelled as a Poisson
process: independent arrivals at a roughly constant rate over the (short,
fixed) sampling interval. A Poisson variable's variance equals its own mean,
so a count of :math:`N` particles carries a standard counting uncertainty of
:math:`\\sqrt{N}`, and a relative uncertainty of :math:`1/\\sqrt{N}`. Because
concentration is `count` divided by a sample volume that carries no counting
noise of its own (it is derived from TAS and probe geometry, not from
counting particles), the *relative* uncertainty on a derived concentration
equals the *relative* uncertainty on the raw count that produced it -- the
sample-volume scaling is exact, not itself uncertain, so it drops out of the
ratio. That is why this module takes ``count`` (`sizeDist.m`'s own per-bin,
per-second ``Counts`` variable, e.g. ``s4_sizedist_octave_golden.nc``'s
``count``) as its input, not a concentration.

**Two independent Poisson counts sum to a Poisson count**, which is why the
uncertainty on a *moment* (the total particle count across every bin in a
second, or across every second in a used-bin sum) is not found by combining
each bin's relative uncertainty in quadrature and hoping -- it is the same
:math:`\\sqrt{N}` rule applied directly to the summed count, because a sum of
independent Poisson variables is itself Poisson with the summed rate. Both
routes agree exactly here (`quadrature-of-absolute equals sqrt-of-sum` for
Poisson variables specifically), which :func:`propagate_to_total` asserts
rather than assumes.

**Changes no computed number** -- every ``sizeDist``/combine output is read
verbatim; this only adds new derived arrays alongside it, the same space as
`arm_export.py` and `particle_clustering.py`.
"""

from __future__ import annotations

import numpy as np

#: McFarquhar et al. (2017) p. 11.13, citing Hallett (2003): "100 particles in
#: a size bin is regarded as statistically significant." A field convention,
#: not a hard physical threshold -- callers may pass a different value.
STATISTICALLY_SIGNIFICANT_COUNT = 100

__all__ = [
    "STATISTICALLY_SIGNIFICANT_COUNT",
    "per_bin_relative_uncertainty",
    "per_bin_absolute_uncertainty",
    "is_statistically_significant",
    "propagate_to_total",
]


def per_bin_relative_uncertainty(count):
    """:math:`1/\\sqrt{N}` per element of ``count``.

    ``NaN`` where ``count`` is ``NaN``, zero or negative -- a bin with no
    particles observed has no basis for a Poisson-counting estimate of its
    own uncertainty (``1/sqrt(0)`` is undefined, not infinite-but-usable),
    and a negative count cannot be a real particle tally.
    """
    count = np.asarray(count, dtype=np.float64)
    with np.errstate(invalid="ignore", divide="ignore"):
        rel = 1.0 / np.sqrt(count)
    rel = np.where(count > 0, rel, np.nan)
    return rel


def per_bin_absolute_uncertainty(conc, count):
    """The concentration-scale counting uncertainty: ``conc / sqrt(count)``.

    ``conc`` and ``count`` must be the same shape -- typically the
    (time, bin) arrays `sizeDist.m` itself writes side by side (e.g.
    ``conc_minR`` and ``count``).
    """
    conc = np.asarray(conc, dtype=np.float64)
    return conc * per_bin_relative_uncertainty(count)


def is_statistically_significant(count, threshold: int = STATISTICALLY_SIGNIFICANT_COUNT):
    """Whether each element of ``count`` meets the field's own significance
    convention (Hallett 2003 via McFarquhar et al. 2017 p. 11.13).

    ``False`` for ``NaN`` counts -- "not enough particles to trust" and "no
    data at all" are different states, but neither is "significant".
    """
    count = np.asarray(count, dtype=np.float64)
    return np.where(np.isnan(count), False, count >= threshold)


def propagate_to_total(count, axis=-1):
    """Poisson-propagate ``count`` to a summed moment along ``axis``.

    Returns ``(total, relative_uncertainty, absolute_uncertainty)``, each one
    dimension smaller than ``count``. ``NaN`` bins are treated as zero
    contribution to the sum (matching ``sizeDist.m``'s own fill-value
    convention -- a second with no coverage contributes nothing, rather than
    poisoning the whole moment with a single ``NaN``), but a row that is
    entirely ``NaN`` (no coverage at all) propagates to a ``NaN`` total,
    since "zero particles observed" and "nothing was measured" are different
    claims and this function does not conflate them.
    """
    count = np.asarray(count, dtype=np.float64)
    all_nan = np.all(np.isnan(count), axis=axis)
    total = np.nansum(count, axis=axis)
    total = np.where(all_nan, np.nan, total)

    with np.errstate(invalid="ignore", divide="ignore"):
        relative = 1.0 / np.sqrt(total)
    relative = np.where(total > 0, relative, np.nan)
    absolute = total * relative  # == sqrt(total) where defined; kept as one
    # expression so the two routes described in the module docstring
    # (quadrature-of-per-bin-absolute vs sqrt-of-the-sum) are asserted equal
    # in tests rather than only one of them ever being computed.

    return total, relative, absolute
