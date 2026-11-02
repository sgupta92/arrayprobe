# `brown_francis_1995.py` — a published m–D relation, read and transcribed

Closing one of the
five gaps `md_relations.py` declared for the published relations it names.

## 1. The source, read directly

Brown, P. R. A. and Francis, P. N. (1995), *Improved Measurements of the Ice Water Content in
Cirrus Using a Total-Water Probe*, J. Atmos. Oceanic Technol. **12**, 410–414.

Eq. (3), p. 411, confirmed by the paper's own summary sentence, p. 413:

    M(D) = a * D**b,   a = 7.38e-11,   b = 1.9

**M in grams, D in MICRONS.** Stated explicitly because it is a different diameter unit from
this port's own `single_mass.m` translation (`arrayprobe.particle_physics.single_mass`), which
takes centimetres — passing a centimetre-valued diameter into this module's coefficients (or
vice versa) produces a mass wrong by many orders of magnitude with no error raised.

## 2. What the fit actually is

The M(D) = aD^b form is *derived from* Locatelli and Hobbs (1974), "appropriate to aggregates
of unrimed bullets, columns and side-planes" (p. 411) — the coefficients describe a Locatelli &
Hobbs aggregate category, not any of this port's Holroyd habit codes (`habit.py`). It was
evaluated against total-water-probe IWC from two UK C-130 cirrus flights (p. 413, "over the
whole range of D* from 25 to 400 microns … appears to give the best estimate"), for particles
25–400 microns dominating the IWC. D is "the mean of the maximum chord lengths measured
parallel and perpendicular to the probe photodiode array" (p. 411) — not necessarily this port's
own D_max convention (see `dmax_sensitivity.py`); that mismatch is named, not corrected.

The paper also gives a sub-100-micron regime (solid ice spheres, p. 411: a = 4.82e-13, b = 3.0
exactly — a physical constant, not a fit). It is exposed as
`SMALL_CRYSTAL_SPHERE_A`/`SMALL_CRYSTAL_SPHERE_B` but is **not** part of the registered relation;
`md_relations.get("brown_francis_1995")` is the D ≥ 100 micron aggregate branch only, matching
the "standard coefficients" sentence the paper itself uses as its headline result.

## 3. Missing habits — a gap by construction, not an omission

Not habit-keyed: one power law, applied uniformly, for the aggregate category the paper fits.
It says nothing about columns, plates, rosettes, or graupel. This is not a defect to fix — the
paper was never meant to be habit-resolved — but it is worth stating plainly beside the
relation's registry entry, the same way `effective_density.py`'s docstring states which seven of
eleven Holroyd codes its own table cannot map. A user who needs a habit-resolved mass has two
other registry entries: `uiops_single_mass` (habit-keyed, the port's own native relation, what
the archived products were actually made with) or `doc0223_effective_density` (habit/area-ratio
keyed, itself incomplete — see that module's docstring).

## 4. Units, tested

`tests/test_brown_francis_1995.py` (12 tests) checks:

- the transcribed coefficients (`A_COEFFICIENT_G_UM = 7.38e-11`, `B_EXPONENT = 1.9`,
  `SMALL_CRYSTAL_SPHERE_A = 4.82e-13`, `SMALL_CRYSTAL_SPHERE_B = 3.0`) against the paper's
  printed values;
- masses computed independently from those same printed coefficients at five diameters
  (100, 200, 500, 1000, 2000 microns), asserted against values computed offline from the
  equation as printed — the paper gives no single worked (D, M) example to check against
  (its own validation is an IWC ratio over a size distribution, Figs. 3–4, not a lookup value),
  so this is a transcription check, not a reproduction of a value the authors themselves quote;
- that `mass_bf95` raises rather than silently switching to the sub-100-micron sphere regime
  for D < 100 microns, and that D = 100 itself is the aggregate branch's lower edge;
- that `md_relations.get("brown_francis_1995")` points at this module and that
  `brown_francis_1995` is not in `md_relations.DECLARED_GAPS`.

## 5. Opt-in, never a default

Not imported by `arrayprobe`, not consulted by `sizedist.py`'s own mass computation
(`arrayprobe.particle_physics.single_mass`) or by `massBL` (Baker & Lawson 2006). A caller must
explicitly import this module or select `"brown_francis_1995"` from the m-D registry. Selecting
it changes every mass, IWC and mass-weighted diameter computed from its output, so it carries
the same "opt-in, defaulting OFF" status as any other behaviour-changing enhancement — there is no flag to toggle because there is no default path
that calls it in the first place; turning it "on" is the act of calling it.

**PROPAGATE**: any example notebook that demonstrates the m-D registry (none currently do) must
show this relation as one explicit, opt-in choice among four, not a default — noted for the
example-notebook rule that every opt-in is shown in the example notebooks.

## 6. What remains open in `md_relations.py`

Three of the plan's five published relations (Heymsfield 2010, Erfani & Mitchell 2016, Leroy
2016) remain gaps because **the source is not held** — searched across a personal
literature library and this repository's own `developer/literature/`
(searched 2026-09-14): no matching PDF found for any of the three. The fourth, Finlon 2019, was found
and read in full: its result is a chi-squared surface of equally plausible (a, b)
pairs per flight leg from one field campaign (MC3E), not a single coefficient pair (Figs. 7–8,
pp. 3630–3631), so its gap is a missing registry field, not a missing source — see
`md_relations_design.md` §4 for the design decision it still needs.
