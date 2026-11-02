# `md_relations.py` — a registry of mass–diameter relations

Requirement: *"an m–D registry keyed by campaign/temperature with
bounds (Brown & Francis, Heymsfield 2010, Erfani & Mitchell 2016, Leroy 2016,
Finlon 2019), replacing hard-coded buckets."*

## 1. What shipped, and what deliberately did not

**Shipped:** the registry, its provenance requirement, and the four relations
this repository has actually verified.

| Key | What it is | How it was established here |
|---|---|---|
| `uiops_single_mass` | UIOOPS's own habit-keyed m–D power law | **ported** and Octave-confirmed: the earlier translation's `single_mass` against `single_mass.m`; its output is the `mass` variable of every `sd` product (`sizedist.py:1702`) |
| `baker_lawson_2006_area` | area-based mass, `0.115/1000 · A^1.218` | **ported**: the literal at `sizeDist.m:844` of the field-campaign variant, written to every `sd` product as `massBL` |
| `doc0223_effective_density` | habit / area-ratio effective density `ρ_e = k·Ar^n` | **transcribed** row by row from DMT DOC-0223 Rev A, Table 2.1, p. 27, into `effective_density.py::EFFECTIVE_DENSITY_TABLE` |
| `brown_francis_1995` | aggregate mass-diameter power law, `M = a·D^b`, D >= 100 microns | **transcribed 2026-09-14**, Eq. 3 p. 411 and the confirming sentence p. 413, `a = 7.38e-11`, `b = 1.9`, D in microns, M in grams; `arrayprobe_enhancements/brown_francis_1995.py::mass_bf95` |

**Not shipped, on purpose:** the remaining four published relations the plan
names. Three (Heymsfield 2010, Erfani & Mitchell 2016, Leroy 2016) are
unread because **the source is not held** — a 2026-09-14 search of
a personal literature library and this repository's own `developer/literature/` by author-name
found no matching PDF for any of the three; `effective_density.py`'s
docstring already recorded the same absence for its own cross-reference to
these three. The fourth, Finlon 2019, is different: the source **was**
found and read in full — its own method (Sect. 3, p. 3623)
derives a chi-squared surface of equally plausible `(a, b)` pairs per
near-constant-temperature flight leg from one field campaign (MC3E), not a
single coefficient pair (Figs. 7-8, pp. 3630-3631) — so its gap is a missing
registry field (nothing on `MassRelation` can hold a bounded surface, only a
point), not a missing paper. All four are `DECLARED_GAPS`: named, citation
given, carrying **no coefficients**, each stating what closing it requires.

This is the whole design decision, and it is worth being blunt about why.
An m–D relation is three or four numbers that move every mass, IWC and
mass-weighted diameter downstream of them, and published values for the *same*
relation are quoted inconsistently second-hand. A registry is therefore exactly
the place where a half-remembered coefficient would stop being a recollection
and start being authoritative — it would be in a table, with a citation beside
it, and nothing in the artefact would distinguish it from the three that were
actually read. *A plausible invention is worse than a stated gap,
because it survives review.*

## 2. The controls

`register()` refuses:

- an entry with an empty `source` (where it was published) **or** empty
  `provenance` (how *this repository* established it — a `file:line`, or a
  document, table and page). They are different questions and both are required;
  a provenance that cannot be followed is decoration, and a test checks each
  names something openable;
- `established` outside `{ported, transcribed, derived}` — "remembered" is not
  an option, by construction;
- a key already registered, unless `replace=True` is passed: silently replacing
  a relation changes every mass downstream with nothing in the record to say so;
- a key that is a **declared gap**. Reading the paper means deleting the gap in
  the same change, so the registry and its own list of what it lacks cannot
  drift apart.

`get()` on a declared gap raises with the gap's reason and what closing it
needs, rather than a bare `KeyError` — the difference between "not here" and
"here is the task".

`tests/test_md_relations.py` (17 tests) exercises each refusal, asserts the
five relations the plan names are each either registered or a declared gap,
asserts `Gap` has nowhere to put a coefficient, and asserts an unstated
validity bound is recorded as `None` rather than as infinity — `single_mass.m`
states no diameter range, and recording `(0, inf)` would claim the source
says something it does not. `tests/test_brown_francis_1995.py` (12 tests)
checks the newly-registered relation's own transcription against the paper's
printed coefficients.

## 3. What it does not do

It computes nothing itself. Each entry names the code that already applies
the relation (`implementation`), so registering one never means writing a
second copy: `single_mass` stays the port's, `massBL` stays `sizeDist`'s, the
DOC-0223 densities stay `effective_density`'s, and Brown & Francis (1995)
stays its own small module (`brown_francis_1995.py`) — a computed function,
unlike the other three's re-use of existing code, because nothing in this
port or its enhancements already applied this particular power law. The
impact of *selecting* a relation is whatever that relation does, measured in
its own row of `docs/applicability_matrix.md`.

The `campaign` and `temperature_range_c` fields exist because the plan asks for
a registry keyed by them — but none of the four verified relations states a
temperature range, so all four leave it unset. A relation must not acquire a
range here by implication; that is the same failure as inventing a coefficient,
one field over.

## 4. Closing a gap

1. Read the paper. Not a review of it, not a table quoting it.
2. Transcribe the coefficients **with the diameter definition they were fitted
   against** — the common failure is applying `a·D^b` to a different `D` than
   the fit used, which changes the answer without changing anything visible.
3. Register with `established="transcribed"` and a provenance naming the
   equation or table number.
4. Delete the `Gap` in the same commit. `register()` will refuse the entry
   otherwise, which is the ratchet working.

`brown_francis_1995` followed exactly this path 2026-09-14: read,
transcribed into its own module with D stated explicitly as microns (not this
port's usual centimetres), registered, gap deleted in the same change.

Of the four gaps that remain, three (`heymsfield_2010`, `erfani_mitchell_2016`,
`leroy_2016`) are blocked at step 1 — **the source is not held**, searched and
confirmed absent 2026-09-14. `finlon_2019` is the one gap that is not a
source problem: the paper is held and was read in full, and its
result is a χ² surface of equally plausible `(a, b)` pairs bounded to one
field campaign's flight legs (Figs. 7-8), not a single coefficient pair —
closing it needs a design decision about what field(s) `MassRelation` would
need to hold a bounded surface, plus a decision about whether an MC3E-fitted
surface may be offered for other campaigns' data at all, before any transcription.
`erfani_mitchell_2016` carries the same "no field for this shape" problem in
advance, for whenever its source is obtained: it is a second-order log-log
fit rather than a power law, so `form` needs a value this module does not
yet define.
