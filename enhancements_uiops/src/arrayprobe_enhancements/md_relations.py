# SPDX-License-Identifier: BSD-3-Clause
"""A registry of mass-diameter relations -- the mechanism, and only what has
actually been read.

**The brief:** *"an m-D registry keyed by
campaign/temperature with bounds (Brown & Francis, Heymsfield 2010, Erfani &
Mitchell 2016, Leroy 2016, Finlon 2019), replacing hard-coded buckets."*

**What is built here, and what deliberately is not.** The registry, its
provenance requirement and the four relations this repository has genuinely
verified are here. **Updated 2026-09-14**: of the five published
relations the plan names, ``brown_francis_1995`` has now been read
(Brown and Francis, J. Atmos. Oceanic Technol., 12, 410-414, 1995, Eq. 3
p. 411) and is registered below, delegating to the new
:mod:`arrayprobe_enhancements.brown_francis_1995`. The remaining four are
still **not** read against their papers in this project --
``effective_density.py``'s own docstring records exactly that for three of
them. Typing their coefficients from recollection would put four plausible
numbers into a registry whose entire value is that a user can trust what it
says a relation is. The project rule: *never invent a fact to fill a gap; a
plausible invention is worse than a stated gap, because it survives review.*

**A literature search for the remaining four was carried out**
(the author's literature folder and its ``Literature_Probes``/``Manuals_Probes``
subfolders, and this repository's own ``developer/literature/``), not merely assumed
unread: ``heymsfield_2010``, ``erfani_mitchell_2016`` and ``leroy_2016`` were
not found anywhere in the held library (searched by author-name glob); the
PDF for ``finlon_2019`` *was* found and was read in full
(Finlon et al., Atmos. Chem. Phys., 19, 3621-3643, 2019) -- its gap is not a missing source
but a missing registry field, now confirmed rather than assumed: the paper's
own result is a chi-squared surface of equally plausible (a, b) pairs per
flight leg and temperature from one field campaign (MC3E, its Figs. 7-8),
not a single coefficient pair, so "source not held" does not apply to it --
"source held and read; no field here can express what it found" does.

So the unread/unrepresentable ones are listed in :data:`DECLARED_GAPS` --
named, with what is needed to close each, and carrying no coefficients at
all. A gap is a row in the registry's own accounting, not an absence.

**Why a provenance field is required rather than encouraged.** An m-D relation
is a set of numbers that changes every mass, IWC and mass-weighted diameter
downstream of it, and the difference between two published relations is
routinely a factor of two. A registry that will accept an entry whose source is
unstated is a registry that will, eventually, be the place a half-remembered
coefficient goes to become authoritative. :func:`register` refuses one, and
``tests/test_md_relations.py`` mutates that refusal to be sure it fires.

**This module computes nothing on its own.** It is a table with a lookup: each
entry names the callable or formula that already exists elsewhere, so
registering a relation never means reimplementing it. ``single_mass`` stays the
port's; ``massBL`` stays ``sizeDist``'s; the DOC-0223 densities stay
``effective_density``'s.
"""
from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "DECLARED_GAPS",
    "Gap",
    "MassRelation",
    "REGISTRY",
    "available",
    "get",
    "register",
]


@dataclass(frozen=True)
class MassRelation:
    """One mass-diameter (or mass-area) relation a user may select.

    Every field below the first three exists because some downstream number
    depends on it and would otherwise be chosen silently.
    """

    key: str
    """The name a config file or a caller selects it by."""

    description: str
    """What the relation computes, in one line."""

    form: str
    """``power_law_diameter``, ``power_law_area``, or ``density_area_ratio`` --
    what the coefficients mean, so a reader never has to guess whether
    ``a * x**b`` is being applied to a diameter or an area."""

    source: str
    """The citation. Required, and checked non-empty."""

    provenance: str
    """**How it was established in THIS repository**, not merely where it came
    from originally: a ``file:line`` for something ported, or a document,
    table and page for something transcribed. This is the field that makes the
    registry checkable rather than merely attributed."""

    established: str
    """``ported`` (transcribed from MATLAB this project runs and tests against),
    ``transcribed`` (read from a document and typed in), or ``derived``. A
    relation this project has only *heard of* does not get an entry -- it gets
    a :class:`Gap`."""

    diameter_range_mm: tuple[float | None, float | None] = (None, None)
    """Validity bounds as the source states them; ``None`` where it gives
    none. An unstated bound is recorded as unstated, never as infinity."""

    temperature_range_c: tuple[float | None, float | None] = (None, None)
    """As above. The plan asks for a registry *keyed by campaign/temperature*;
    a relation whose paper states no temperature range must not acquire one
    here by implication."""

    campaign: str | None = None
    """The campaign the relation was fitted on, when the source names one."""

    habit_keyed: bool = False
    """Whether the relation varies by particle habit."""

    implementation: str = ""
    """Dotted path to the code that already applies it, so registering a
    relation never means writing a second copy of it."""

    notes: str = ""


@dataclass(frozen=True)
class Gap:
    """A relation the plan names that this project has NOT read.

    It carries no coefficients, by construction -- there is nowhere to put
    them. What it carries is what closing it requires, so the gap is a task
    rather than a shrug.
    """

    key: str
    citation: str
    why_not_yet: str
    to_close: str
    fields: tuple = field(default=(), repr=False)


#: The relations this repository has verified. Four, not eight.
REGISTRY: dict[str, MassRelation] = {}


def register(relation: MassRelation, *, replace: bool = False) -> MassRelation:
    """Add a relation, refusing one that cannot say where it came from.

    ``replace`` must be asked for explicitly: silently overwriting a registered
    relation would change every mass downstream of it with no trace, which is
    the same class of failure as an unstated source.
    """
    for required in ("key", "description", "form", "source", "provenance",
                     "established"):
        if not str(getattr(relation, required, "")).strip():
            raise ValueError(
                f"an m-D relation needs a non-empty {required!r}; refusing to "
                f"register {relation.key!r}. A relation whose origin is "
                "unstated becomes authoritative by being in a table, which is "
                "exactly what this registry exists to prevent.")
    if relation.established not in ("ported", "transcribed", "derived"):
        raise ValueError(
            f"{relation.key!r}: `established` must be one of ported, "
            f"transcribed, derived -- got {relation.established!r}. "
            "'Remembered' is not an option on purpose.")
    if relation.key in REGISTRY and not replace:
        raise ValueError(
            f"{relation.key!r} is already registered; pass replace=True to "
            "mean it. Overwriting silently would change every mass computed "
            "downstream with nothing in the record to say so.")
    if relation.key in {g.key for g in DECLARED_GAPS}:
        raise ValueError(
            f"{relation.key!r} is listed in DECLARED_GAPS as not yet read. "
            "Registering it means the paper has now been read -- remove the "
            "gap entry in the same change, so the two cannot disagree.")
    REGISTRY[relation.key] = relation
    return relation


def get(key: str) -> MassRelation:
    """One relation by key, with the available ones named if it is missing."""
    try:
        return REGISTRY[key]
    except KeyError:
        gap = next((g for g in DECLARED_GAPS if g.key == key), None)
        if gap is not None:
            raise KeyError(
                f"{key!r} is a declared gap, not a registered relation: "
                f"{gap.why_not_yet} To close it: {gap.to_close}") from None
        raise KeyError(f"unknown m-D relation {key!r}; registered: "
                       f"{sorted(REGISTRY)}") from None


def available() -> list[str]:
    return sorted(REGISTRY)


# --------------------------------------------------------------------------
# The gaps, declared before the entries so `register` can refuse to shadow one.
# --------------------------------------------------------------------------
DECLARED_GAPS: tuple[Gap, ...] = (
    Gap(key="heymsfield_2010",
        citation="Heymsfield, A. J. et al., J. Atmos. Sci., 2010",
        why_not_yet="source not held: no copy of the paper was found to read. "
                    "`effective_density.py` records the same absence for its "
                    "own DOC-0223 cross-reference.",
        to_close="obtain the paper (AMS/journal access, not this project's "
                 "held library), read it, transcribe with the temperature "
                 "range the fit was made over -- the plan asks the registry "
                 "to be keyed by temperature and this is one of the "
                 "relations that has one."),
    Gap(key="erfani_mitchell_2016",
        citation="Erfani, E. and Mitchell, D. L., Atmos. Chem. Phys., 2016",
        why_not_yet="source not held: same search as heymsfield_2010 above "
                    "(2026-09-14), no matching PDF found in the held library.",
        to_close="obtain and read; note that this one is a second-order fit "
                 "in log-log space rather than a single power law, so `form` "
                 "will need a value this module does not yet define."),
    Gap(key="leroy_2016",
        citation="Leroy, D. et al., J. Atmos. Oceanic Technol., 2016",
        why_not_yet="source not held: same search as heymsfield_2010 above "
                    "(2026-09-14), no matching PDF found in the held library.",
        to_close="obtain and read; it is a per-particle area-and-perimeter "
                 "method rather than an m-D power law, so decide first "
                 "whether it belongs in this registry at all or beside "
                 "`effective_density`."),
    Gap(key="finlon_2019",
        citation="Finlon, J. A. et al., Atmos. Chem. Phys., 19, 3621-3643, 2019",
        why_not_yet="source held and READ IN FULL (2026-09-14, "
                    "Finlon et al. 2019), unlike "
                    "the other three gaps above -- this is not a missing "
                    "source, it is a missing registry field. Confirmed by "
                    "reading: the paper's method (Sect. 3, p. 3623) derives a "
                    "surface of equally plausible (a, b) pairs per near-"
                    "constant-temperature flight leg by minimizing chi-square "
                    "between OAP-derived and directly measured TWC/Z (Figs. "
                    "7-8, pp. 3630-3631), from one field campaign (MC3E, "
                    "Table 1, mesoscale convective systems over Oklahoma, "
                    "2011) -- not a single coefficient pair, and not shown to "
                    "generalize to other cloud types or campaigns (Sect. 1, "
                    "p. 3622: 'a universal m-D relationship has not been "
                    "found'). The 'modified BF95' relation the paper uses as "
                    "its own comparison baseline (Sect. 5.3.1, D_mm in Fig. "
                    "12) is a variant of `brown_francis_1995`, now registered "
                    "above, not of this gap.",
        to_close="decide what a registry entry means for a relation whose "
                 "result is a surface rather than a point, bounded to one "
                 "campaign's temperature/leg conditions -- probably a bound "
                 "pair plus the chi-squared contour, which no field on "
                 "`MassRelation` expresses yet, plus a `campaign`-scoping "
                 "decision about whether an MC3E-fitted surface may be "
                 "offered for ORACLES data at all."),
)


# --------------------------------------------------------------------------
# What this repository has actually verified.
# --------------------------------------------------------------------------
register(MassRelation(
    key="uiops_single_mass",
    description="UIOPS's own habit-keyed m-D power law, per Holroyd habit, "
                "with two diameter regimes for the 'l'/'o' codes",
    form="power_law_diameter",
    source="UIOPS v3.1.4 single_mass.m (McFarquhar group)",
    provenance="ported and Octave-oracle-confirmed: "
               "the v3.1.4 engine's single_mass(), against "
               "UIOPS-v3.1.4/joefinlon-UIOPS-ba5e67c/single_mass.m; its output "
               "is the `mass` variable of every sd product "
               "(the v3.1.4 engine's size distribution)",
    established="ported",
    habit_keyed=True,
    implementation="arrayprobe.particle_physics.single_mass",
    notes="The default. This is what the archived ORACLES products were made "
          "with, so any comparison against them starts here."))

register(MassRelation(
    key="brown_francis_1995",
    description="Aggregate mass-diameter power law (Locatelli & Hobbs "
                "unrimed-bullet/column/side-plane aggregates), D >= 100 "
                "microns; the D < 100 micron solid-ice-sphere regime is "
                "exposed separately, not registered here",
    form="power_law_diameter",
    source="Brown, P. R. A. and Francis, P. N., J. Atmos. Oceanic Technol., "
           "12, 410-414, 1995",
    provenance="read directly, Eq. (3) p. 411 and the confirming sentence "
               "p. 413 ('using the standard coefficients a = 7.38e-11 and "
               "b = 1.9 ... give the best estimate of IWC'); transcribed "
               "into arrayprobe_enhancements.brown_francis_1995 "
               "(A_COEFFICIENT_G_UM, B_EXPONENT)",
    established="transcribed",
    habit_keyed=False,
    diameter_range_mm=(0.1, None),
    implementation="arrayprobe_enhancements.brown_francis_1995.mass_bf95",
    notes="D is grams-per-MICRON in the source, not the port's usual "
          "centimetres -- see the implementation module's docstring. The "
          "coefficients were fitted to Locatelli & Hobbs's aggregate "
          "category, not to any of this port's Holroyd habit codes -- a "
          "missing-habit gap by construction, not an omission: the paper "
          "never claims habit resolution. Not the relation the ORACLES "
          "products were written with (that is uiops_single_mass, above); "
          "selecting this one is opt-in and changes every downstream mass."))

register(MassRelation(
    key="baker_lawson_2006_area",
    description="Area-based mass, m = 0.115/1000 * A**1.218",
    form="power_law_area",
    source="Baker, B. and Lawson, R. P., J. Appl. Meteorol. Climatol., 2006",
    provenance="the literal at uioops_testing/sizeDist.m:844, ported in "
               "the v3.1.4 engine (`particle_massbl`); written to every "
               "sd product as `massBL`",
    established="ported",
    habit_keyed=False,
    implementation="arrayprobe.sizedist (particle_massbl, inline)",
    notes="Area rather than diameter, so it is not interchangeable with the "
          "two above without deciding which area definition is meant."))

register(MassRelation(
    key="doc0223_effective_density",
    description="Habit/area-ratio effective density, rho_e = k * Ar**n, "
                "times volume -- a density relation, not a mass formula",
    form="density_area_ratio",
    source="DMT DOC-0223 Rev A, Table 2.1, p. 27 (attributed there to "
           "Heymsfield et al. 2002)",
    provenance="transcribed row by row into EFFECTIVE_DENSITY_TABLE in "
               "enhancements_uiops/src/arrayprobe_enhancements/effective_density.py, "
               "keyed by the table's own row labels; that module's docstring "
               "records why most Holroyd codes are deliberately left unmapped",
    established="transcribed",
    habit_keyed=True,
    implementation="arrayprobe_enhancements.effective_density.effective_density",
    notes="Maps only 25 of 99 real particles in the measured audit "
          "(enhancements_uiops/docs/applicability_matrix.md) -- the unmapped ones "
          "are habits DOC-0223's crystal typing does not correspond to."))
