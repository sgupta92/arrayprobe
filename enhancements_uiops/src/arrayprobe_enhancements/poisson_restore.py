# SPDX-License-Identifier: BSD-3-Clause
"""Korolev & Field (2015) Eq. 2 -- statistically restore intact particles the
inter-arrival-time shattering rejection removes as false positives.

**What the paper actually describes, verified against the real text (AMT 8,
761-777, 2015, doi:10.5194/amt-8-761-2015), not a secondary summary.** Section
3.1, "Naturally occurring particles with inter-arrival times shorter than the
cut-off-time interval": two intact particles that happen to arrive within the
shattering cut-off time tau* of each other are indistinguishable from a real
shattering pair, and get rejected as one. Assuming intact-particle arrivals
follow a Poisson process (Eq. 1, p. 764: dP(dt)/dt = exp(-dt/tau)/tau, with
tau = 1/(n*S*u) the mean inter-arrival time -- n the intact concentration, S
the probe sample area, u the true air speed), the probability that a pair of
intact particles arrives closer together than tau* is

    P2(dt < tau*) = (1/2) * (tau*/tau)**2 * exp(-tau*/tau)          -- Eq. 2

The paper's own proposed use of this (last paragraph of Sect. 3.1, citing
Field et al. 2006): "It is possible to attempt to correct for the removal of
intact particles using Poisson statistics to estimate the fraction of intact
particles rejected and then scale the remaining intact size distribution."
That is a POPULATION-LEVEL scaling correction, not a rule for picking which
specific rejected particles to re-accept -- the paper does not describe a
per-particle restoration method, so this module does not invent one.

**The >500 micron re-acceptance floor named in the plan row this module
answers is NOT in Korolev & Field (2015) -- confirmed by reading the paper,
2026-09-10.** The paper's own size-based argument, p. 768 (the closing
paragraph of Sect. 4.2.1, immediately above the "4.2.2 Large particles"
heading), gives a different number: "Experimental studies indicate that the
fragments of ice particles shattered at the aircraft speed have
characteristic size from tens to hundreds of micrometers (Vidaurre and
Hallett, 2009). Therefore, it is hypothesized that rejected particles larger
than approximately 1mm (Fig. 7) are likely related to the cases depicted in
Fig. 2b, d, e and f." That is a size-based argument for why LARGE rejected
particles are probably intact, independent of the Poisson pair-arrival
estimate above -- and it says ~1 mm, not 500 micron.

So the 500 micron figure comes from somewhere else. The plan's citation lists
Field et al. (2006) and the McFarquhar/Baumgardner monograph ch. 11 p. 11.21
as alternative sources for it; neither has been checked. Per this project's
"never invent a fact to fill a gap" rule,
:func:`large_particle_reacceptance_floor` below takes the threshold as a
REQUIRED, caller-supplied argument -- there is no default, and 500e-6 m is not
hardcoded anywhere in this module -- until that citation is confirmed.

**The monograph page was read on 2026-09-14** (for ``intarr_policy``): p. 11.21
says "some algorithms (but not all) reaccept these particles when their size
is above a selected threshold since most shattered particles are smaller than
500 um (Korolev et al. 2013b,c)". The 500 micron figure is there, as the
fragment size motivating "a selected threshold", not as the threshold itself,
so ``floor`` still has no default. Field et al. (2006) remains unread.

**Separately: this paper's Sect. 4 prints its time-to-distance conversion
wrongly** (``Delta-x = Delta-t/u`` p. 765, ``chi* = tau*/u`` p. 766; both
dimensionally impossible, the intended operation being multiplication). That
does not touch anything in this module, which uses only Eqs. 1-2 above, but
it is the same paper -- see
``enhancements_uiops/docs/distance_rejection_design.md`` for the full finding
before quoting any other equation from it.
"""
from __future__ import annotations

import math

import numpy as np

__all__ = [
    "mean_intact_interarrival_time",
    "poisson_pair_false_rejection_probability",
    "restoration_scale_factor",
    "scale_size_distribution",
    "large_particle_reacceptance_floor",
]


def mean_intact_interarrival_time(concentration, sample_area, true_air_speed):
    """``tau = 1 / (n * S * u)`` -- Korolev & Field (2015) Eq. 1's parameter,
    p. 764. ``concentration`` (n) in the same length unit as ``sample_area``
    (S) and ``true_air_speed`` (u): SI throughout (m^-3, m^2, m/s) gives tau
    in seconds, matching every other inter-arrival time in this port.
    """
    return 1.0 / (concentration * sample_area * true_air_speed)


def poisson_pair_false_rejection_probability(tau, tau_star):
    """``P2(dt < tau*) = (1/2)(tau*/tau)**2 * exp(-tau*/tau)`` -- Korolev &
    Field (2015) Eq. 2, p. 764: the probability that two intact particles,
    arriving as an ordinary Poisson process with mean spacing ``tau``, land
    within the shattering cut-off time ``tau_star`` of each other and are
    therefore misclassified as a shattered pair.

    Increases with concentration (smaller ``tau``) and with ``tau_star`` --
    both directions the paper states explicitly, and both are asserted by
    this module's tests.
    """
    ratio = tau_star / tau
    return 0.5 * ratio**2 * math.exp(-ratio)


def restoration_scale_factor(false_rejection_fraction):
    """The multiplicative correction Korolev & Field (2015) attribute to
    Field et al. (2006): if a fraction ``f`` of the true intact population
    was removed, the surviving accepted population is ``(1 - f)`` of the
    truth, so scaling it by ``1 / (1 - f)`` restores the total (not which
    particles were removed -- see this module's docstring for why no
    per-particle rule is implemented).

    Raises :class:`ValueError` for ``f >= 1`` -- the model breaks down there
    (it would imply everything was rejected), and returning ``inf`` silently
    would propagate into a concentration nothing downstream could sanity-check.
    """
    if not (0.0 <= false_rejection_fraction < 1.0):
        raise ValueError(
            f"false_rejection_fraction must be in [0, 1); got {false_rejection_fraction}")
    return 1.0 / (1.0 - false_rejection_fraction)


def scale_size_distribution(concentration_by_bin, false_rejection_fraction):
    """Apply :func:`restoration_scale_factor` to every bin of a size
    distribution -- "scale the remaining intact size distribution", the
    paper's own phrase for this correction. A uniform scale, because the
    Poisson estimate above is a population-level fraction, not a per-bin one;
    a size-dependent correction would need a size-dependent tau*, which this
    module does not compute (the port's own threshold-fitting,
    ``arrayprobe.intarr_analysis.fit_bimodal_intarr``, is not size-resolved
    either).
    """
    scale = restoration_scale_factor(false_rejection_fraction)
    return np.asarray(concentration_by_bin, dtype=float) * scale


def large_particle_reacceptance_floor(diameters, floor, *, rejected_mask=None):
    """Particles at or above ``floor`` among ``diameters`` are candidates for
    re-acceptance regardless of the inter-arrival verdict, on the reasoning
    Korolev & Field (2015) p. 768 give for a DIFFERENT number (approximately
    1 mm, confirmed by reading the page; NOT the plan's cited 500 micron
    figure, which is not in that paper -- see this module's docstring):
    shattered fragments are characteristically small (Vidaurre & Hallett,
    2009), so a large rejected particle is more likely a real intact particle
    than a shattering artifact.

    ``floor`` has **no default** -- the exact value is an unverified citation
    (see module docstring) and this project's convention is that an
    unconfirmed threshold is never silently assumed. Pass it explicitly,
    e.g. from a config the caller has independently confirmed.

    Returns a boolean mask over ``diameters``, restricted to
    ``rejected_mask`` when given (only particles the shattering rejection
    actually removed are candidates for re-acceptance; a particle already
    accepted has nothing to restore).
    """
    diameters = np.asarray(diameters, dtype=float)
    candidates = diameters >= floor
    if rejected_mask is not None:
        candidates &= np.asarray(rejected_mask, dtype=bool)
    return candidates
