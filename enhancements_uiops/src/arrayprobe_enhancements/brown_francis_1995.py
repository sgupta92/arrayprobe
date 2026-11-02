# SPDX-License-Identifier: BSD-3-Clause
"""Brown & Francis (1995) mass-diameter power law -- closing the
``brown_francis_1995`` gap in :mod:`arrayprobe_enhancements.md_relations`.

**The source, read directly (2026-09-14)**: Brown, P. R. A. and
Francis, P. N., *Improved Measurements of the Ice Water Content in Cirrus
Using a Total-Water Probe*, J. Atmos. Oceanic Technol., **12**, 410-414, 1995. Eq. (3),
p. 411, and the confirming sentence on p. 413 ("using the standard
coefficients a = 7.38e-11 and b = 1.9 ... give the best estimate of IWC from
the 2D probe data"):

    M(D) = a * D**b,   a = 7.38e-11,   b = 1.9

with **M in grams and D in MICRONS** -- stated explicitly because this is a
different diameter unit from the port's own ``single_mass.m`` translation
(:func:`arrayprobe.particle_physics.single_mass`), which takes centimetres.
Applying this module's coefficients to a centimetre-valued diameter (or vice
versa) silently produces a mass wrong by many orders of magnitude with no
error raised -- the unit is part of the fidelity of the number, not a detail.

**What the paper actually fits, and what it does not.** The M(D) = aD^b form
is *derived from* Locatelli and Hobbs (1974), "appropriate to aggregates of
unrimed bullets, columns and side-planes" (p. 411) -- so despite the common
"Brown & Francis" shorthand, the crystal habit behind the coefficients is a
Locatelli & Hobbs aggregate category, not a habit this project's Holroyd
codes (``habit.py``) classify. The fit was evaluated against total-water-probe
IWC from two UK C-130 cirrus flights (A189, A193, April 1992), for particles
in the 25-400 micron range dominating the IWC (p. 413, "over the whole range
of D* from 25 to 400 microns, the expression given by (3) with the standard
coefficients ... appears to give the best estimate"); D is "the mean of the
maximum chord lengths measured parallel and perpendicular to the probe
photodiode array" (p. 411) -- the port's own D_max convention differs from
this in general (see ``dmax_sensitivity.py``), so a caller selecting this
relation is combining a coefficient fit to one diameter definition with a
port-measured diameter under a different one; that mismatch is not corrected
here, only named, per the same convention ``md_relations.py`` documents for
``uiops_single_mass``'s unstated diameter range.

**The sub-100-micron regime, also in the paper and included here for
completeness, but excluded from :mod:`md_relations`' registered relation.**
For D < 100 microns the paper assumes crystals are solid ice spheres
(p. 411): a = 4.82e-13, b = 3.0 exactly (rho_ice, not a fit). It is exposed
below as :data:`SMALL_CRYSTAL_SPHERE_A`/:data:`SMALL_CRYSTAL_SPHERE_B` for a
caller who wants it, but the *registered* relation
(``md_relations.get("brown_francis_1995")``) is the D >= 100 micron branch
only -- the paper's own headline result and the one the "standard
coefficients" sentence above names. Mixing regimes at one D=100 boundary is a
design decision for whoever builds the full two-regime callable; this module
does not make it silently (see :func:`mass_bf95`'s ``ValueError`` for
D < 100).

**Habit.** Not habit-keyed: one power law for the aggregate category the
paper fits, applied uniformly. It says nothing about columns, plates,
rosettes, or graupel -- for those, ``md_relations.get("uiops_single_mass")``
(habit-keyed) or ``doc0223_effective_density`` (habit/area-ratio-keyed,
itself missing seven of eleven Holroyd codes, see that module's docstring)
are the registry's other options. This is the missing-habit gap that
belongs beside this relation's entry, not a defect in it: Brown & Francis
was never meant to be habit-resolved.

**Opt-in, never a default.** This module is not imported by
``arrayprobe`` and is not consulted by ``sizedist.py``'s own mass
computation (``arrayprobe.particle_physics.single_mass``, UIOOPS's native
per-habit relation) or by ``massBL`` (Baker & Lawson 2006, ``sizeDist.m``'s
own area-based path). A caller must explicitly import this module or select
``"brown_francis_1995"`` from the m-D registry; nothing in the port or in any
other enhancement calls it. Selecting it changes every mass, IWC and
mass-weighted diameter computed from its output, so it carries the same
"opt-in, defaulting OFF" status as any other behaviour-changing enhancement
(fidelity doctrine).
"""
from __future__ import annotations

__all__ = [
    "A_COEFFICIENT_G_UM",
    "B_EXPONENT",
    "SMALL_CRYSTAL_SPHERE_A",
    "SMALL_CRYSTAL_SPHERE_B",
    "VALID_DIAMETER_RANGE_UM",
    "mass_bf95",
]

#: Eq. (3), p. 411: M(D) = a * D**b, M in grams, D in MICRONS. "the standard
#: coefficients a = 7.38e-11 and b = 1.9" (p. 413).
A_COEFFICIENT_G_UM: float = 7.38e-11
B_EXPONENT: float = 1.9

#: The paper's own sub-100-micron solid-ice-sphere regime (p. 411), exposed
#: but not part of the registered relation -- see the module docstring.
SMALL_CRYSTAL_SPHERE_A: float = 4.82e-13
SMALL_CRYSTAL_SPHERE_B: float = 3.0

#: p. 413: "over the whole range of D* from 25 to 400 microns" is where the
#: paper states the standard coefficients were shown to perform best -- the
#: bound this module enforces for :func:`mass_bf95`'s upper flag is the
#: D >= 100 micron regime split (p. 411), not this narrower "best" range,
#: which is recorded here only as documentation, not as a raised error: the
#: paper does not say the fit is invalid outside 25-400 microns, only that it
#: was evaluated there.
VALID_DIAMETER_RANGE_UM: tuple[float, float] = (100.0, None)  # type: ignore[assignment]


def mass_bf95(diameter_um: float) -> float:
    """Particle mass (grams) from the Brown & Francis (1995) power law.

    ``diameter_um`` must be in MICRONS (the port's own diameter fields are
    usually centimetres or millimetres -- convert before calling). Raises
    ``ValueError`` for ``diameter_um < 100``: that is the paper's own solid-
    ice-sphere regime (:data:`SMALL_CRYSTAL_SPHERE_A`/``_B``), a different
    physical assumption this function does not silently switch to, so a
    caller who has not decided how to handle the boundary gets an error
    rather than a quietly wrong branch.
    """
    if diameter_um < 100.0:
        raise ValueError(
            f"mass_bf95 is the D >= 100 micron aggregate regime "
            f"(Brown & Francis 1995, Eq. 3, p. 411); got diameter_um="
            f"{diameter_um!r} < 100. The paper's own sub-100-micron regime "
            "is solid-ice-sphere mass (SMALL_CRYSTAL_SPHERE_A/_B), a "
            "different assumption -- call that explicitly rather than "
            "having this function silently switch branches.")
    return A_COEFFICIENT_G_UM * diameter_um ** B_EXPONENT
