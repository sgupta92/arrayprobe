# SPDX-License-Identifier: BSD-3-Clause
"""Inter-arrival shattering policy as explicit options: which threshold rule, and how many
neighbours a flagged particle takes with it. **Default OFF** -- off reproduces UIOOPS exactly.

**The published basis, read from the chapter itself** (McFarquhar et al. 2017, *Meteor.
Monogr.* 58, ch. 11, doi:10.1175/AMSMONOGRAPHS-D-16-0007.1, p. 11.21, read 2026-09-14):

    "The different methodologies used to define this threshold include the following:
    2 x t2 (gray), the interarrival time between t1 and t2 with smallest measured frequency of
    occurrence (red, minimum of raw frequency), and the interarrival time between t1 and t2
    with the smallest frequency of occurrence based on fit curves to the frequency of
    occurrence for the two Gaussian distributions (cyan, minimum of fitted curves). [...] In
    addition, when an artifact is identified through interarrival time analysis, that particle
    and one or two adjacent particles are removed (depending on the selected algorithm). The
    impact of such differences has not been well documented over a range of conditions, but
    can have a big impact on calculated N(Dmax)."

**UIOOPS already computes all three thresholds and writes one.** Both threshold writers --
the ORACLES fork's ``IntArrAnalysis_time.m`` (ported as
:func:`arrayprobe.intarr_analysis.block_thresholds`: ``:159`` ``threshhold``, ``:170-190``
``threshhold_ww``/``threshhold_ak``, ``:367`` writes ``threshhold_ak``) and stock v3.5's
``IntArrAnalysis.m`` (``:116``, ``:146``, ``:147``; ``:127`` "Determine thresholds using 3
different techniques"; ``:290`` writes ``threshhold_ak``) -- carry the monograph's three rules
under those three names. So the rule switch invents no threshold: it chooses which of three
already-computed arrays goes into the file ``sizeDist`` reads.

=================  ==================  ===========================================
``rule``           source variable     monograph p. 11.21
=================  ==================  ===========================================
``min_measured``   ``threshhold_ak``   minimum of raw frequency -- **UIOOPS writes this**
``twice_tau2``     ``threshhold``      2 x t2 (``min(tau(1:2))*2``)
``min_fitted``     ``threshhold_ww``   minimum of fitted curves
=================  ==================  ===========================================

**The neighbour count.** Every flagging block in all three trees rejects the particle whose
inter-arrival is at or below the threshold *and the particle before it*:
``auto_reject((ix-1):ix) = 'S'`` -- v3.1.4 ``sizeDist.m:1017``, ``:1149``; v3.5
``sizeDist.m:1194``, ``:1326``, ``:1393`` (ported as
:func:`arrayprobe_uiops.sizedist_tables.flag_shattered_1hz`). That is the monograph's "that
particle and one adjacent particle", so UIOOPS is ``neighbours=1``.

* ``neighbours=2`` adds the particle *after* the flagged one. **This is a reading, not a
  quotation**: the monograph says "one or two adjacent particles" without naming which two.
  In a time-ordered stream a particle has exactly two adjacent particles, its predecessor
  and its successor, and UIOOPS's one is the predecessor -- so the second is the successor.
* ``neighbours=0`` flags the short-inter-arrival particle alone. **The monograph does not
  describe it** ("one or two"); it is offered as the no-neighbour baseline an A/B needs, and
  documented as such rather than as a published variant.

The first particle of a second has no predecessor in the per-second block ``sizeDist``
flags, so every tree flags it alone (``int_arr(1) <= thresh``); that line is kept identical
under every neighbour count except that ``neighbours=2`` also takes its successor.

**The re-acceptance floor** the same page names ("some algorithms (but not all) reaccept
these particles when their size is above a selected threshold since most shattered particles
are smaller than 500 um (Korolev et al. 2013b,c)") already ships as
:func:`arrayprobe_enhancements.poisson_restore.large_particle_reacceptance_floor`, with the
floor a required argument; this module does not duplicate it.

**Opt-in, per the author's rule for all opt-ins (2026-09-14):** *"add a
parameter, default off with option to turn on"*. :class:`InterArrivalPolicy` defaults to
``enabled=False``, which is UIOOPS: ``min_measured`` and ``neighbours=1``. Setting a rule or a
neighbour count **without** ``enabled=True`` raises rather than being silently ignored.

**What this module does not claim.** Which rule is right is the open question the monograph
itself states ("has not been well documented"); this module makes the choice explicit and
measurable, it does not settle it. It changes no archived ORACLES product: that production
call names a threshold file that does not exist, so ``sizeDist`` fell back to the 6 us
per-probe default and no rule was ever consumed (``intarr_threshold_fix``'s docstring). The
neighbour count *does* reach that default path.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
from arrayprobe import intarr_analysis

__all__ = [
    "RULES",
    "NEIGHBOUR_COUNTS",
    "InterArrivalPolicy",
    "UIOPS_POLICY",
    "select_threshold",
    "write_threshold_file",
    "flag_shattered",
    "flag_shattered_by_second",
    "compare_policies",
]

#: rule name -> the variable name both ``IntArrAnalysis_time.m`` and v3.5 ``IntArrAnalysis.m``
#: compute it under (the port's :func:`arrayprobe.intarr_analysis.analyse` keys drop the
#: source's doubled ``h``).
RULES: dict[str, str] = {
    "min_measured": "threshold_ak",
    "twice_tau2": "threshold",
    "min_fitted": "threshold_ww",
}

NEIGHBOUR_COUNTS = (0, 1, 2)

_UIOPS_RULE = "min_measured"
_UIOPS_NEIGHBOURS = 1


@dataclass(frozen=True)
class InterArrivalPolicy:
    """The switch. ``InterArrivalPolicy()`` is OFF and reproduces UIOOPS.

    Turn it on explicitly: ``InterArrivalPolicy(enabled=True, rule="min_fitted",
    neighbours=2)``.
    """

    enabled: bool = False
    rule: str = _UIOPS_RULE
    neighbours: int = _UIOPS_NEIGHBOURS

    def __post_init__(self):
        if self.rule not in RULES:
            raise ValueError(f"unknown rule {self.rule!r}; known: {sorted(RULES)}")
        if self.neighbours not in NEIGHBOUR_COUNTS:
            raise ValueError(f"neighbours must be one of {NEIGHBOUR_COUNTS}; "
                             f"got {self.neighbours!r}")
        if not self.enabled and (self.rule, self.neighbours) != (_UIOPS_RULE,
                                                                 _UIOPS_NEIGHBOURS):
            raise ValueError(
                "a non-UIOPS rule or neighbour count was set with enabled=False, which "
                "would silently do nothing; pass enabled=True to turn the policy on")


#: The OFF state, named.
UIOPS_POLICY = InterArrivalPolicy()


def _policy(policy: InterArrivalPolicy | None) -> InterArrivalPolicy:
    return UIOPS_POLICY if policy is None else policy


def select_threshold(thresholds: Mapping, policy: InterArrivalPolicy | None = None
                     ) -> np.ndarray:
    """The per-particle threshold array the policy's rule selects.

    ``thresholds`` is anything with the three source keys -- the dict
    :func:`arrayprobe.intarr_analysis.analyse` returns. OFF returns ``threshold_ak``,
    the array the source writes.
    """
    p = _policy(policy)
    return np.asarray(thresholds[RULES[p.rule]], dtype=float)


def write_threshold_file(filename, timehhmmss, thresholds: Mapping, *,
                         policy: InterArrivalPolicy | None = None, **kwargs):
    """Write the file ``sizeDist`` reads as its twelfth argument, carrying the selected rule.

    Delegates to :func:`arrayprobe.intarr_analysis.write_threshold_file` unchanged -- same
    variable, attributes and layout -- so OFF is byte-identical to the port's own write of
    ``threshold_ak`` (asserted in ``tests/test_intarr_policy.py``).
    """
    return intarr_analysis.write_threshold_file(
        filename, timehhmmss, select_threshold(thresholds, policy), **kwargs)


def flag_shattered(int_arr, thresh, *, policy: InterArrivalPolicy | None = None
                   ) -> np.ndarray:
    """Boolean mask of the particles one second's shattering block rejects as ``'S'``.

    ``int_arr`` is that second's inter-arrival times, ``thresh`` a scalar or a per-particle
    array (the type-1 file path). OFF is ``sizeDist``'s ladder exactly: the first particle
    alone when ``int_arr(1) <= thresh``, then ``(ix-1):ix`` for every later hit.
    """
    p = _policy(policy)
    ia = np.asarray(int_arr, dtype=float).ravel()
    th = np.broadcast_to(np.asarray(thresh, dtype=float), ia.shape)
    flags = np.zeros(ia.size, dtype=bool)
    if ia.size == 0:
        return flags
    if ia[0] <= th[0]:
        flags[0] = True
        if p.neighbours == 2 and ia.size > 1:
            flags[1] = True
    for ix in np.flatnonzero(ia[1:] <= th[1:]) + 1:
        flags[ix] = True
        if p.neighbours >= 1:
            flags[ix - 1] = True
        if p.neighbours == 2 and ix + 1 < ia.size:
            flags[ix + 1] = True
    return flags


def flag_shattered_by_second(int_arr, thresh, seconds, *,
                             policy: InterArrivalPolicy | None = None) -> np.ndarray:
    """:func:`flag_shattered` applied to each run of equal ``seconds`` values, as
    ``sizeDist``'s per-second loop applies it -- a neighbour never crosses a second."""
    ia = np.asarray(int_arr, dtype=float).ravel()
    th = np.broadcast_to(np.asarray(thresh, dtype=float), ia.shape)
    sec = np.asarray(seconds).ravel()
    if sec.shape != ia.shape:
        raise ValueError(f"seconds and int_arr must match: {sec.shape} vs {ia.shape}")
    out = np.zeros(ia.size, dtype=bool)
    if ia.size == 0:
        return out
    edges = np.flatnonzero(np.diff(sec) != 0) + 1
    for lo, hi in zip(np.r_[0, edges], np.r_[edges, ia.size], strict=True):
        out[lo:hi] = flag_shattered(ia[lo:hi], th[lo:hi], policy=policy)
    return out


def compare_policies(int_arr, thresholds: Mapping, seconds) -> dict[tuple[str, int], int]:
    """The A/B: particles flagged under every (rule, neighbours) pair, OFF included."""
    out = {}
    for rule in RULES:
        for n in NEIGHBOUR_COUNTS:
            p = (UIOPS_POLICY if (rule, n) == (_UIOPS_RULE, _UIOPS_NEIGHBOURS)
                 else InterArrivalPolicy(enabled=True, rule=rule, neighbours=n))
            th = select_threshold(thresholds, p)
            out[(rule, n)] = int(flag_shattered_by_second(int_arr, th, seconds,
                                                          policy=p).sum())
    return out
