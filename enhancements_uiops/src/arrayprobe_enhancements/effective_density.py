# SPDX-License-Identifier: BSD-3-Clause
"""A published, habit-dependent ice effective-density relation, from a table.

**The gap it fills, contributing to the m-D registry -- and a correction to the
premise it was proposed on.** The proposal described this as filling a
gap left by "`sizeDist.m`'s only mass path", the area-based Baker & Lawson
relation (``0.115/1000 * Area**1.218``, ``:844``). **That premise is wrong: the
port already ships a second, genuinely habit-keyed mass path.**
``arrayprobe.particle_physics.single_mass(diameter, habit)`` (a direct port
of ``single_mass.m``) already applies UIOOPS's own per-habit power law
(``a * diameter**b`` with real Holroyd-habit-keyed coefficients -- e.g.
``a=0.00294, b=1.9`` for ``s``/``t``, two diameter-dependent regimes for
``l``/``o``, ``a=0.00739, b=2.45`` for ``h``, and so on for ``i``/``a``, ``g``,
``d``), and its output is already written to every ``sd``/combined product as
the ``mass`` variable ("mass using m-D relations", ``sizedist.py:1702``).

**So this module is a genuinely independent, third mass path -- density
times volume from a published habit/area-ratio relation -- not the first
habit-resolved mass path this port has ever had.** What it adds that
``single_mass`` does not have is a *density*, not a mass formula per se, and
a route through *area ratio* rather than diameter alone; a user gains a
choice between UIOOPS's own native relation, this density-based one, and
(not yet built) the further literature relations the m-D registry names (Brown &
Francis 1995, Heymsfield et al. 2010, Erfani & Mitchell 2016, Leroy et al.
2016, Finlon et al. 2019 -- none of which have been read and verified here
yet, unlike the source below). The "m-D registry" plan item is really about
giving a user that choice among several established relations, not about
creating habit-resolved mass capability from nothing.

**The source, read directly**: DMT DOC-0223 Rev A, *Data Analysis User's
Guide -- Chapter II: Single Particle Imaging*, Table 2.1 (attributed there to
Heymsfield et al. 2002), p. 27. The relation is effective density
:math:`\\rho_e = k \\cdot A_r^{\\,n}`, with :math:`k` and :math:`n` fitted per
crystal habit and study. Every row is transcribed verbatim in
:data:`EFFECTIVE_DENSITY_TABLE`, keyed by the table's own row label -- not by
this port's Holroyd codes, for the reason below.

**Why this module does not map most Holroyd codes onto a table row.**
DOC-0223's habit categories (``C1e-C1f``, ``C2a``, ``P1a-P1b-P1d``, ...) are
Heymsfield's own detailed crystal-habit typing, built from photographed
particles; Holroyd's eleven single-character codes (``habit.py``) are coarse
shape *statistics* from an OAP shadow image (aspect ratio, a fine-detail
fraction, a fill-ratio threshold) -- a different classification scheme,
built for a different purpose, and the two do not correspond one-to-one.
Forcing a mapping where the two schemes do not agree would be exactly the
kind of invented fact this project's doctrine refuses. Concretely:

* ``M`` (zero image), ``C`` (never emitted), ``t`` (tiny), ``o`` (oriented),
  ``g`` (graupel), ``s`` (sphere), ``i`` (irregular) have **no corresponding
  row at all** -- Table 2.1 covers specific ice-crystal habits (columns,
  rosettes, planar crystals, aggregates), not degenerate shapes, riming, or
  a residual "irregular" catch-all. :func:`effective_density` returns
  ``None`` for all seven.
* ``l`` ("linear") is **not** mapped to "Columns (theory)" despite the
  surface similarity -- Holroyd's ``l`` fires on an aspect-ratio /
  correlation test on the *shadow*, not on a photographed crystal habit; an
  elongated shadow can be a genuine column, a needle, a bar, or an artifact,
  and asserting it means "column" would be a claim this project cannot
  support. Returns ``None``.
* ``h`` (hexagonal) and ``d`` (dendrite) are **not** mapped to any of the
  three "Planar crystals" rows, even though both are, informally, planar ice
  habits -- Table 2.1's planar-crystal rows are keyed by *study*
  (synthetic wind tunnel vs. real surface observations vs. thick plates),
  not by a hexagonal/dendrite distinction the table does not draw. Holroyd's
  own ``h``/``d`` split (a fine-detail-fraction threshold) has no known
  correspondence to which *study's* crystals a given particle resembles.
  Returns ``None`` for both, and the caller who has independently
  established a real crystal habit (e.g. from CPI imagery) can look the
  right row up directly in :data:`EFFECTIVE_DENSITY_TABLE`.
* ``a`` (aggregate) is the **one code this module does map**, because
  "aggregate" is an unambiguous category in both schemes -- but the table
  gives *four* different aggregate studies with materially different
  ``k``/``n`` (component-crystal-dependent: planar crystals, 2-6 planar
  crystals, side planes, rosettes), and this port cannot tell which
  component crystal a real aggregate is built from. :func:`effective_density`
  therefore requires the caller to name an ``aggregate_study`` explicitly
  for ``'a'``; passing none returns ``None`` rather than silently picking one
  of the four, which would understate the real spread between them (0.010 to
  0.18 in ``k`` alone).

**Two other things in the source, and why they are excluded here.** The
"wind tunnel" planar-crystal row (Takahashi et al. 1991) actually prints
*two* regimes on the source page, split by area ratio -- ``k=0.084, n=2.38``
for :math:`A_r < 0.79` and ``k=11.96, n=22.64`` for :math:`A_r \\geq 0.79`,
both under the same habit code and study; both are carried in
:data:`EFFECTIVE_DENSITY_TABLE` as separate entries, selected by
:func:`lookup` on ``area_ratio`. The "thick plates" row
(:math:`\\rho_e = 0.043 \\cdot d^{-0.238}`) and the separate "Aggregate
:math:`\\rho` vs :math:`D`" and "aggregate hybrid" sub-tables use a
*diameter* power law, :math:`\\rho_e = \\chi D^\\kappa` (or a mixed
:math:`k A_r^n D^\\alpha` form), not the area-ratio relation this item asks
for -- a materially different physical model (needs a real diameter, not
just an area ratio) that the original proposal does not name. Left out of this
module; a diameter-keyed density module would be a separate, later item, not
folded in here to avoid mixing two different functional forms behind one
name.

**Changes no computed number** -- reference data and one small computed
function, the same space as `poisson_uncertainty.py` and
`probe_uncertainty.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "ICE_DENSITY_G_CM3",
    "DensityRelation",
    "EFFECTIVE_DENSITY_TABLE",
    "effective_density",
    "lookup",
]

#: Bulk density of solid ice, g/cm^3 -- the standard value (e.g. Pruppacher &
#: Klett), and the same figure the HVPS Post-Processing manual's own IWC
#: formula uses (rho_i = 0.917).
#: Not previously defined anywhere in this port; DOC-0223's "Columns
#: (theory)" row needs it (k = 0.97 * rho_ice).
ICE_DENSITY_G_CM3 = 0.917


@dataclass(frozen=True)
class DensityRelation:
    """One row of DOC-0223 Table 2.1, transcribed verbatim.

    ``rho_e = k * area_ratio**n`` over ``area_ratio_range`` (a ``(low, high)``
    bound, or ``None`` where the source gives only a one-sided bound, e.g.
    "< 0.79"). ``r_squared`` is ``None`` where the source prints no fit
    quality (the two "Aggregates (Magono and Nakamura 1965)" and "Kajikawa
    1982" rows).
    """

    study: str
    habit_code: str | None
    k: float
    n: float
    r_squared: float | None
    area_ratio_range: tuple[float | None, float | None]


#: DOC-0223 Table 2.1, p. 27, "Effective density relations" (Heymsfield et
#: al. 2002), transcribed row by row. Keys are the table's own row labels,
#: not this port's habit codes -- see the module docstring for why.
EFFECTIVE_DENSITY_TABLE: dict[str, DensityRelation] = {
    "columns_theory": DensityRelation(
        study="Columns (theory)", habit_code="C1e-C1f",
        k=0.97 * ICE_DENSITY_G_CM3, n=2.10, r_squared=1.00,
        area_ratio_range=(0.05, 0.64)),
    "rosettes_theory_1_bullet": DensityRelation(
        study="Rosettes (theory), 1 bullet", habit_code="C2a",
        k=0.60, n=1.94, r_squared=0.99, area_ratio_range=(0.22, 0.98)),
    "rosettes_theory_2_bullets": DensityRelation(
        study="Rosettes (theory), 2 bullets", habit_code="C2a",
        k=0.65, n=2.11, r_squared=0.99, area_ratio_range=(0.11, 0.55)),
    "rosettes_theory_3_bullets": DensityRelation(
        study="Rosettes (theory), 3 bullets", habit_code="C2a",
        k=0.54, n=2.11, r_squared=0.99, area_ratio_range=(0.16, 0.68)),
    "rosettes_theory_4_bullets": DensityRelation(
        study="Rosettes (theory), 4 bullets", habit_code="C2a",
        k=0.47, n=2.16, r_squared=0.99, area_ratio_range=(0.20, 0.87)),
    "rosettes_theory_5_bullets": DensityRelation(
        study="Rosettes (theory), 5 bullets", habit_code="C2a",
        k=0.49, n=2.16, r_squared=0.99, area_ratio_range=(0.22, 0.87)),
    "rosettes_theory_6_bullets": DensityRelation(
        study="Rosettes (theory), 6 bullets", habit_code="C2a",
        k=0.49, n=2.25, r_squared=0.99, area_ratio_range=(0.26, 0.99)),
    "rosettes_theory_7_bullets": DensityRelation(
        study="Rosettes (theory), 7 bullets", habit_code="C2a",
        k=0.50, n=2.35, r_squared=1.00, area_ratio_range=(0.29, 1.00)),
    "rosettes_theory_8_bullets": DensityRelation(
        study="Rosettes (theory), 8 bullets", habit_code="C2a",
        k=0.52, n=2.52, r_squared=0.99, area_ratio_range=(0.32, 1.00)),
    "side_planes_observatory": DensityRelation(
        study="Side planes, S1-S3 (Observatory)", habit_code=None,
        k=0.35, n=2.34, r_squared=0.79, area_ratio_range=(0.18, 0.88)),
    "planar_wind_tunnel_low_ar": DensityRelation(
        study="Planar crystals, wind tunnel (Takahashi et al. 1991), Ar<0.79",
        habit_code="P1a-P1b-P1d",
        k=0.084, n=2.38, r_squared=0.97, area_ratio_range=(None, 0.79)),
    "planar_wind_tunnel_high_ar": DensityRelation(
        study="Planar crystals, wind tunnel (Takahashi et al. 1991), Ar>=0.79",
        habit_code="P1a-P1b-P1d",
        k=11.96, n=22.64, r_squared=0.48, area_ratio_range=(0.79, None)),
    "planar_surface_observations": DensityRelation(
        study="Planar crystals, surface observations "
              "(Heymsfield and Kajikawa 1987), many types",
        habit_code=None,
        k=0.102, n=3.29, r_squared=0.86, area_ratio_range=(None, 0.81)),
    "aggregates_magono_nakamura_1965": DensityRelation(
        study="Aggregates (Magono and Nakamura 1965), planar-crystal components",
        habit_code=None,
        k=0.010, n=1.50, r_squared=None, area_ratio_range=(None, 0.28)),
    "aggregates_kajikawa_1982": DensityRelation(
        study="Aggregates (Kajikawa 1982), 2-6 planar-crystal components",
        habit_code=None,
        k=0.015, n=1.50, r_squared=None, area_ratio_range=(0.13, 0.77)),
    "aggregates_side_planes_surface": DensityRelation(
        study="Aggregates, side planes S1-S3 (surface observations)",
        habit_code=None,
        k=0.18, n=1.52, r_squared=0.97, area_ratio_range=(0.21, 0.65)),
    "aggregates_cpi_rosettes": DensityRelation(
        study="Aggregates, CPI observations (ARM), rosette components",
        habit_code=None,
        k=0.16, n=1.48, r_squared=0.99, area_ratio_range=(0.16, 0.56)),
}

#: The four aggregate rows, keyed by the ``aggregate_study`` name
#: :func:`effective_density` accepts for Holroyd's ``'a'`` -- the one code
#: this module maps, and only when the caller names which component-crystal
#: study applies (see the module docstring for why none is a silent default).
_AGGREGATE_STUDIES = {
    "magono_nakamura_1965": "aggregates_magono_nakamura_1965",
    "kajikawa_1982": "aggregates_kajikawa_1982",
    "side_planes_surface": "aggregates_side_planes_surface",
    "cpi_rosettes": "aggregates_cpi_rosettes",
}


def _in_range(value: float, bounds: tuple[float | None, float | None]) -> bool:
    lo, hi = bounds
    if lo is not None and value < lo:
        return False
    if hi is not None and value > hi:
        return False
    return True


def effective_density(holroyd_habit: str, area_ratio: float, *,
                      aggregate_study: str | None = None) -> float | None:
    """Effective ice density (g/cm^3) for a particle with the given Holroyd
    habit code and area ratio, or ``None`` where DOC-0223 Table 2.1 has no
    defensible row for that habit code -- see the module docstring for the
    reasoning behind every code's treatment.

    ``aggregate_study`` selects among the four component-crystal studies
    Table 2.1 gives for Holroyd's ``'a'`` (one of
    ``"magono_nakamura_1965"``, ``"kajikawa_1982"``,
    ``"side_planes_surface"``, ``"cpi_rosettes"``); required for ``'a'``,
    ignored for every other code. ``None`` is also returned if
    ``area_ratio`` falls outside the matched row's own measured range,
    honestly reporting "outside what was measured" rather than
    extrapolating a fitted power law past its own data.
    """
    if holroyd_habit != "a":
        return None
    if aggregate_study is None or aggregate_study not in _AGGREGATE_STUDIES:
        return None
    return lookup(_AGGREGATE_STUDIES[aggregate_study], area_ratio)


def lookup(table_key: str, area_ratio: float) -> float | None:
    """Effective density (g/cm^3) from a named row of
    :data:`EFFECTIVE_DENSITY_TABLE` directly, for a caller who has
    independently established a real crystal habit (e.g. from CPI imagery)
    that this port's own Holroyd classification cannot distinguish --
    ``'planar_surface_observations'`` for a hexagonal plate or dendrite, for
    instance, rather than going through :func:`effective_density`, which
    refuses those codes for the reasons in the module docstring.

    Returns ``None`` if ``area_ratio`` falls outside the row's own measured
    range, rather than extrapolating a fitted power law past its own data.
    """
    row = EFFECTIVE_DENSITY_TABLE[table_key]
    if not _in_range(area_ratio, row.area_ratio_range):
        return None
    return row.k * area_ratio ** row.n
