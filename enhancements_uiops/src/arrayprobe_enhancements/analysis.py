# SPDX-License-Identifier: BSD-3-Clause
"""A post-``sizeDist`` analysis layer: PSD moments, mass-weighted mean
diameter, and leg-scale aggregation with propagated Poisson uncertainty.

**The gap it fills**: the package currently stops where UIOOPS stops, one
second at a time, and every user then rewrites the same handful of moment
integrals and flight-leg summaries. This module reads a `sizeDist`/combine
output's own arrays and adds derived quantities alongside them; it writes
nothing back and changes no existing computed number.

**What is genuinely new here, and what is not.** ``sizeDist`` already ships a
total number concentration (`n`), a Fu (1996) generalized effective radius
(`re`, `sizeDist.m:1312`), and *two* independent habit- or area-resolved mass
paths (`mass` via `particle_physics.single_mass` -- UIOOPS's own habit-keyed
m-D power law, `single_mass.m` -- and `massBL` via the Baker & Lawson (2006)
area-based method). This module does not reimplement any of those. What it
adds: a *general* PSD moment function usable for quantities `sizeDist` does
not ship (e.g. a reflectivity-relevant sixth moment, or verifying `n` and
`re` against an independent computation); the mass-weighted mean diameter
D_m, which nothing in this port computes; and leg-scale (multi-second)
aggregation with Poisson uncertainty actually propagated through it, using
:mod:`arrayprobe_enhancements.poisson_uncertainty`'s own primitives rather
than a second implementation of the same statistics.

**The density convention, checked against the real tracked fixture, not
assumed.** `sizeDist`'s per-bin arrays (`conc_minR`, `mass`, `massBL`, ...)
are written as *densities* -- units `cm-4`/`g cm-4`, i.e. per unit size
interval -- not as absolute per-bin counts. Confirmed directly:
``nansum(conc_minR * bin_dD_cm, axis=bin)`` reproduces the file's own ``n``
variable exactly, to the last bit, on `tests/data/s4_sizedist_octave_golden
.nc`. Every moment computed here integrates over `bin_dD` for the same
reason -- omitting that factor would silently produce a quantity with the
wrong dimensions, off by whatever the (non-uniform, in general) bin width
happens to be.

**Deliberately not built here**: LWC/IWC via a *registry* of published m-D
relations beyond what the port and `effective_density.py` already provide
(Brown & Francis 1995, Heymsfield et al. 2010, Erfani & Mitchell 2016, Leroy
et al. 2016) -- none of those five sources has been read and verified yet
(the plan's own literature pass marked them "SNIP", not full text), and
building a registry around unverified coefficients would be exactly the
kind of invented-fact risk this project's doctrine refuses. `moment` and
`mass_weighted_mean_diameter` below work with *any* mass density array a
caller supplies -- `mass`, `massBL`, or a future registry's output alike --
so nothing here needs to change when that registry lands.
"""

from __future__ import annotations

import numpy as np

from .poisson_uncertainty import propagate_to_total

__all__ = [
    "moment",
    "mass_weighted_mean_diameter",
    "leg_mean",
    "leg_total_count_with_uncertainty",
]


def moment(bin_mid_mm, bin_dD_mm, density, order: int, axis: int = -1):
    """The ``order``-th moment of a per-bin density array along ``axis``.

    :math:`M_k = \\sum_i D_i^k \\cdot \\rho_i \\cdot \\Delta D_i`, with
    ``bin_dD_mm`` converted from millimetres to centimetres to match
    `sizeDist`'s own density units (``cm-4``/``g cm-4``). ``density`` may be
    a number-concentration density (``conc_minR``) or a mass density
    (``mass``/``massBL``) -- the integral is the same operation either way;
    only the physical meaning of the result differs (a number moment vs. an
    IWC-like mass moment). ``order=0`` on a number-concentration density
    reproduces `sizeDist`'s own ``n`` exactly (verified in this module's
    tests against the real tracked fixture).

    ``bin_mid_mm``/``bin_dD_mm`` are 1-D, one value per bin; ``density`` may
    be 1-D (one second) or N-D with the bin dimension along ``axis``, e.g.
    the (time, bin) shape `sizeDist` itself writes.
    """
    bin_mid_mm = np.asarray(bin_mid_mm, dtype=np.float64)
    bin_dD_cm = np.asarray(bin_dD_mm, dtype=np.float64) / 10.0
    density = np.asarray(density, dtype=np.float64)

    weight = (bin_mid_mm ** order) * bin_dD_cm
    # Broadcast the 1-D per-bin weight against `density`'s bin axis, whichever
    # position `axis` names -- np.moveaxis puts the bin axis last for the
    # multiply, then the result is summed along it.
    density_binlast = np.moveaxis(density, axis, -1)
    return np.nansum(density_binlast * weight, axis=-1)


def mass_weighted_mean_diameter(bin_mid_mm, bin_dD_mm, mass_density, axis: int = -1):
    """:math:`D_m = M_1(\\text{mass}) / M_0(\\text{mass})` -- the diameter at
    which the mass distribution's first moment balances its zeroth, a
    standard mass-weighted-mean-diameter definition (e.g. Ulbrich 1983 for a
    gamma-fitted PSD; used here directly on the port's own binned mass
    density, no distribution fit assumed).

    ``NaN`` where the total mass (the denominator) is zero -- a second with
    no mass has no mass-weighted mean diameter to report, not a diameter of
    zero.
    """
    m1 = moment(bin_mid_mm, bin_dD_mm, mass_density, order=1, axis=axis)
    m0 = moment(bin_mid_mm, bin_dD_mm, mass_density, order=0, axis=axis)
    with np.errstate(invalid="ignore", divide="ignore"):
        dm = m1 / m0
    return np.where(m0 != 0, dm, np.nan)


def leg_mean(per_second_array, start: int | None = None, end: int | None = None,
            axis: int = 0):
    """The NaN-aware mean of a per-second array (or a (time, bin) array,
    reduced over ``axis``) across the second-index slice ``[start:end)``.

    A "leg" here is any caller-chosen contiguous run of seconds -- a level
    flight leg, an ascent, or a whole flight (the default, ``start=None,
    end=None``, is the entire array). This deliberately does not identify
    legs itself (no altitude or attitude data is available at this layer);
    it aggregates a leg the caller has already identified.
    """
    per_second_array = np.asarray(per_second_array, dtype=np.float64)
    sl = [slice(None)] * per_second_array.ndim
    sl[axis] = slice(start, end)
    return np.nanmean(per_second_array[tuple(sl)], axis=axis)


def leg_total_count_with_uncertainty(count, start: int | None = None,
                                     end: int | None = None):
    """The total particle count over a leg, and its Poisson uncertainty.

    ``count`` is `sizeDist`'s own (time, bin) ``count`` array. The whole
    leg's bin-seconds are summed as *one* Poisson process (not per-bin then
    combined in quadrature) -- the same reasoning
    :func:`arrayprobe_enhancements.poisson_uncertainty.propagate_to_total`
    already implements and is reused here rather than re-derived, since a
    sum of independent Poisson counts is itself Poisson regardless of how
    many axes it was summed across.

    Returns ``(total, relative_uncertainty, absolute_uncertainty)``, each a
    plain float.
    """
    count = np.asarray(count, dtype=np.float64)[start:end]
    total, relative, absolute = propagate_to_total(count.reshape(-1), axis=0)
    return float(total), float(relative), float(absolute)
