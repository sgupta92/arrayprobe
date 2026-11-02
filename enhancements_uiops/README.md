# arrayprobe-uiops-enhancements

Real new science that consumes `arrayprobe`'s output — never part of the faithful port itself.

## Why this is a separate package, not a flag inside `arrayprobe`

The engine translates UIOOPS faithfully, faults included, so that its output can be checked
against the original's; this package corrects the faults among that translation's findings. Importing it and calling its
documented functions must never require an opt-in decision. (The batch driver `run_flight.py` is the one place a correction runs by default: on probes with no archived product -- CIP/PIP, 2DC/2DP, Fast2DC -- it applies the data-destroying-defect corrections, `--protective off` to skip, and writes them to separate `enh` products; a 2D-S/HVPS run with an archived product to match gets none.) Anything that changes a number relative to what the original MATLAB ever actually
produced — even a genuine improvement — belongs here instead: a separate package a user
installs and imports explicitly.

The dependency arrow points one way only: this package imports `arrayprobe`'s public API and
operates on its output (a `proc*.cdf`/`sd*.cdf` file it wrote, or a value one of its functions
returned). **`arrayprobe` never imports this package, and never will** — enforced by
`tests/test_no_enhancement_coupling.py`, which fails if that boundary is ever
crossed. That one-way arrow is what makes this package genuinely optional: delete this whole
directory and the port's own build, tests, and install are unaffected.

## Which engine does an enhancement apply to?

The package ships one UIOOPS engine, **v3.5, the default**. An earlier translation of UIOOPS v3.1.4 reproduced archived products and
is not part of this package. Every enhancement here was written against that v3.1.4 translation, so that question has a real answer per module — and in four cases the
answer is *do not use this on v3.5*, because the UIOOPS developers fixed the same
defect themselves. Applying such a correction on v3.5 would not be inert; it
would correct an already-corrected value.

So the answer is **declared in code, not in prose**:
`arrayprobe_enhancements.applicability` carries one entry per shipped module,
`registry.resolve()` consults it, and an enhancement that does not apply to the
engine being run resolves **off** — or raises, if a config file switched it on
by name. Four states, and the last two are not the same thing:

| State | Meaning on v3.5 |
|---|---|
| **applies** | the defect is present in v3.5 too, or the module corrects no defect at all |
| **superseded-upstream** | the UIOOPS developers fixed it in v3.5; applying it would double-correct |
| **variant-only** | the construct exists in no stock UIOOPS release — it describes one field campaign's modified copy of UIOOPS |
| **unestablished** | not yet read against v3.5. **Not** "fixed": the classifier establishes presence only, so its "not found" is a search miss |

The full table, generated from that declaration:
the documentation site's *Enhancements by engine* page.
SODA-2 is deliberately not an engine here — a separate processing lineage rather
than a UIOOPS version, so it is out of scope for the table above. That does not mean no
enhancement was written against it: `enhancements_soda2/` (package
`arrayprobe-soda2-enhancements`) ships 18 correction modules plus one diagnostics-only module
against NCAR's IDL chain, its own installable package, built the same way as this one — see
`enhancements_soda2/README.md` and `enhancements_soda2/BACKLOG_STATUS.md`.

Cite SODA-2 as: Aaron Bansemer. (2026). abansemer/soda2: v2.26.0 (Version v2.26.0) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.18331418

### The one exception: speed work lives in both spaces

Every other category is split by whether a change is *new science*.
Performance is split by a different test, because **making something faster does not have to
change what it computes**:

| The change | Where it lives |
|---|---|
| Byte-identical, opt-in, no new dependency | the **port** |
| Changes any output, needs a dependency the port refuses, or trades accuracy for time | **here** |

So the parallel decode and the three parallel flags (`--s2-jobs`, `--chunks`, `--jobs`) are in
the **port**, not in this package. They write byte-identical output — asserted against the serial
path in `tests/test_spec_parallel.py` on every channel selection and every sidecar —
and each defaults to serial, so the rule above about never requiring an opt-in decision still
holds exactly.

**Nothing here is a speed enhancement today.** When something is, it will be because it costs a
byte, and that will be stated with it.

## Significance

**"This whole methodology and pipeline will be a major enhancement over existing stock
package."** — of `ml_accept_reject.py` + `outoffocus.py` together. Worth flagging at the top of
this file: everything the port has done up to this point is *fidelity* work (proving
`arrayprobe` reproduces UIOOPS exactly, bugs included), which is necessary but never the
project's actual end goal, which is to "become the field's standard OAP package."
These two modules are the first candidates that aren't reproducing anything; they're closing a
real capability gap manual review cannot reach at scale (measured: the per-flight manual
QA samples 50 particles against real populations in the tens of thousands to millions — see
`docs/ml_accept_reject_design.md` for the numbers). Treat this pairing as the leading edge of
what makes this package more than a compatible clone, not just another backlog item.

## What's here

**Full status, real-data validation numbers, and what's needed from the user for each
finding-correction module: `enhancements_uiops/BACKLOG_STATUS.md`.** This table is the index;
that one is the detail.

**Which of these actually change a field campaign's archived output is measured, per module, in
[`docs/applicability_matrix.md`](docs/applicability_matrix.md)** The run-configuration file format is `docs/config_file_design.md`. — three are inert there.

| Module | Status | Corrects | Detail |
|---|---|---|---|
| `outoffocus.py` | shipped, oracle-validated; runs on engine 3.5 and was validated on the earlier v3.1.4 translation (not shipped) | the unapplied Korolev size correction (Korolev out-of-focus correction — dead code in MATLAB). Re-derives the hollow diagnostics the production config never computes, bit-for-bit against the stored columns, then applies `size_factor` by **dividing** (Korolev 2007 §2 p. 377); a number computed with the earlier multiplying form is superseded | `enhancements_uiops/docs/CORRECTIONS.md`, part `outoffocus.py`, section *The direction* |
| `last_record_fix.py` | shipped, real-data-measured | the dropped final raw record (the last record of every raw file is never decoded) — 0–235 particles per file across all 24 raw files held | `enhancements_uiops/docs/CORRECTIONS.md`, part `last_record_fix.py` |
| `zero_image_recovery.py` | shipped, oracle-validated | the abandoned zero-image record (the fork abandons a whole record on a zero-image particle) — 4,448 particles (1.6 %) recovered in 2,000 records; checked against stock MATLAB's own framing | `enhancements_uiops/docs/CORRECTIONS.md`, part `zero_image_recovery.py` |
| `tas_grid_fix.py` | shipped, A/B-measured | the duplicate TAS-second particle loss (a duplicated TAS second loses every particle in that second) — +5.89 % used-bin recovered on a dense file | `enhancements_uiops/docs/CORRECTIONS.md`, part `tas_grid_fix.py` |
| `overload_accounting_fix.py` | shipped, oracle-validated | the no-accept second overwrite (`sum_IntArr`/`sample_vol` reset for seconds accepting nothing) — 223 seconds corrected on one file | `enhancements_uiops/docs/CORRECTIONS.md`, part `overload_accounting_fix.py` |
| `wide_hollow_fix.py` | shipped, real-data-validated — **inert under the production reject config** (measured: 0 of 49,637 particles) | the diode-32 hollow test (hollow test hardcodes 32 diodes) | `BACKLOG_STATUS.md`, `enhancements_uiops/docs/CORRECTIONS.md`, part `wide_hollow_fix.py` |
| `int16_double_fix.py` | shipped, confirmed inert on the validation campaign's data | the int16 diameter saturation (`int16×double` saturation) | `BACKLOG_STATUS.md`, `enhancements_uiops/docs/CORRECTIONS.md`, part `int16_double_fix.py` |
| `spot_edge_fix.py` | shipped, real-data-validated; runs on engine 3.5 and was validated on the earlier v3.1.4 translation (not shipped) | the missing decimal in spot_edge (`spot_edge(147)` typo) | `BACKLOG_STATUS.md`, `enhancements_uiops/docs/CORRECTIONS.md`, part `spot_edge_fix.py` |
| `conc_arear_fix.py` | shipped, real-data-validated (largest/riskiest item, differential pipeline comparison) | the double-scaled area-ratio concentration (`conc_AreaR` double-scaled to zero) | `BACKLOG_STATUS.md`, `enhancements_uiops/docs/CORRECTIONS.md`, part `conc_arear_fix.py` |
| `reshape_fix.py` | shipped, real-data-validated | the missing mean-ratio transpose (`mean_area_ratio` column-major reshape) | `BACKLOG_STATUS.md`, `enhancements_uiops/docs/CORRECTIONS.md`, part `reshape_fix.py` |
| `pms_c6_routing_fix.py` | shipped, validated on synthetic fixtures only | the misfiled F2DC scalar fields (F2DC scalars land in the 2DC file) | `BACKLOG_STATUS.md`, `enhancements_uiops/docs/CORRECTIONS.md`, part `pms_c6_routing_fix.py` |
| `hole_edge_swap.py` | shipped, real-data-validated | the swapped hole variables (`max_hole_diameter`/`edge_at_max_hole` swapped) | `BACKLOG_STATUS.md`, `enhancements_uiops/docs/CORRECTIONS.md`, part `hole_edge_swap.py` |
| `diode_range_fix.py` | shipped; the widening it guards against is measured against the port's own `reilluminate`, not described | the image-widening diode number (a diode number past the end of the array widens the image, and the width guard then returns from `imgProc_sm` part-way through the file with a success exit status) | `enhancements_uiops/docs/CORRECTIONS.md`, part `diode_range_fix.py` |
| `intarr_threshold_fix.py` | shipped; the faithful side is the port's own `block_thresholds`, asserted equal, so the A/B's two sides come from different places | the global-minimum inter-arrival threshold (the written inter-arrival threshold is the observed histogram's *global* minimum over a window that can span nearly the whole histogram, so it can select the sparse tail rather than the shattering/real crossover) | `enhancements_uiops/docs/CORRECTIONS.md`, part `intarr_threshold_fix.py` |
| `mask_presence_fix.py` | shipped, validated on the port's own tracked MATLAB mask fixtures | the silent missing mask file (a missing or misnamed shadow-diode mask is completely silent; the real 2016 masks carry no orientation letter and could never have been found) | `enhancements_uiops/docs/CORRECTIONS.md`, part `mask_presence_fix.py` |
| `particle_number_all_fix.py` | shipped, synthetic-fixture-validated (real 2DC/2DP/Fast-2DC raw is held, readers checked only, and no archived product); confirmed a no-op on a real proc file from the validation campaign | the sometimes-written Particle_number_all (`Particle_number_all` is defined for every probetype at `:265` and written only at `:879`, so 2DC/2DP/Fast2DC files carry it as pure fill values) | `enhancements_uiops/docs/CORRECTIONS.md`, part `particle_number_all_fix.py` |
| `pressure_units_fix.py` | shipped, A/B-measured on two real flights (the faithful side asserted equal to the on-disk `sd` file, all 25 variables, before any corrected number is quoted) | the unchecked pressure unit (`single_vt.m:7` documents pressure in hPa; both of the validation campaign's drivers pass `9e5`, which `:17` turns into 900 bar) — `vt` and `Prec_rate` move 1.75×–6.05× in every non-zero cell, and nothing else moves. The archived combined product carries neither variable | `enhancements_uiops/docs/CORRECTIONS.md`, part `pressure_units_fix.py` |
| `rollover_fix.py` | shipped; **no data here exercises it** — no flight of the validation campaign crosses midnight (measured, both arrays, six flights) | the first-midnight-only rollover (the `+240000` midnight rollover corrects only the first time decrease, because `a:b` uses a vector's first element) | `enhancements_uiops/docs/CORRECTIONS.md`, part `rollover_fix.py` |
| `particle_time_int8_fix.py` | shipped, oracle-validated on a purpose-built Octave pair; real 2DC/2DP/Fast-2DC raw is held, but only the readers have been checked on it, so no real-flight A/B | the int8 particle-time collapse (`imgProc_sm.m:886` writes `particle_time` through `int8` accumulators seeded from a `'byte'` netCDF field, so it collapses to 127 for probetypes 0 and 3). Proved by running unmodified MATLAB on two raw files differing only in the record clock — `[58, 101]` where the original is right, `[127, 127]` where it is not — and by a self-checking replay that recovers the true value from an already-written proc file | `enhancements_uiops/docs/CORRECTIONS.md`, part `particle_time_int8_fix.py` |
| `int_arr_rollback_fix.py` | shipped; the faithful side is bit-exact against unmodified `sizeDist.m` under Octave (all 25 variables), **no CIP/PIP campaign data exists here** so the rollback is injected | the missing probetype-1 rollback correction (the clock-rollback branch is a three-way `if`/`elseif` with the probetype-1 clause missing, and `:748-749` then rejects the particle at the jump). Corrects two of the finding's own premises: probetype 1's clock is a decoded time of day, not a fixed-width counter, and the source's `sum(int_arr<0)` diagnostic *does* fire | `enhancements_uiops/docs/CORRECTIONS.md`, part `int_arr_rollback_fix.py` |

**Modules that aren't finding-corrections** — new capability, not tracked in
`BACKLOG_STATUS.md`. Ten are listed here; the other nine
(`arco_export.py`, `arm_export.py`, `cf_export.py`, `poisson_uncertainty.py`,
`probe_uncertainty.py`, `effective_density.py`, `analysis.py`, `spec_artefact_filter.py`,
`probe_crossover.py`) have their own sections further down this file. These nineteen modules correct nothing.

| Module | Status | What it does |
|---|---|---|
| `ml_accept_reject.py` | Method A shipped, real-data-evaluated, reviewed by hand; Method B (CNN) not started | Per-particle accept/reject beyond UIOOPS's own ladder. Method A (`max_col_occ`, a diode-occupancy heuristic) formalizes the stuck-diode-merge signature manual QA found by eye — real cross-flight evaluation, reviewed by hand with the triage tool (`arrayprobe triage --queue-file`; 6 of 22 labels changed). Method B: Jaffeux et al. 2022's weights aren't redistributable (no usable license); trains fresh, architecture-informed only. Full review, the labeled-set before/after table, and the real-evaluation numbers: `docs/ml_accept_reject_design.md`. 10 tests. |
| `particle_clustering.py` | shipped, tested | Unsupervised k-means over proc-file shape/size fields (hand-rolled, no scipy/sklearn), medoid representatives, wired into `triage_server`'s `/clusters` route. **User assessment: the clustering isn't tight enough for bulk-apply as a labeling mechanism** — a genuinely-reviewed cluster still mislabeled non-representative members. Redesign expected, not yet started. 11 tests. |
| `distance_rejection.py` | shipped; **not yet measured on real flight data** | Inter-particle *distance* rejection from Korolev & Field (2015) §4 — a shattering criterion keyed on the along-track separation the local TAS implies, rather than on inter-arrival time alone as `sizeDist.m` does. Literature-derived: it answers no finding about UIOOPS. Changes nothing unless local TAS diverges from the reference calibration value within a shattering-fit block; whether any held flight drifts enough to matter is an open measurement, stated rather than implied. `docs/distance_rejection_design.md` |
| `poisson_restore.py` | shipped; **not yet measured on real flight data** | Statistical restoration of intact particles that the shattering filter rejected, from Korolev & Field (2015) Eq. 1–2: the rejected population contains a predictable Poisson fraction of genuine particles, and this estimates and restores it. Also literature-derived, correcting no finding. The restoration scale factor depends on the fitted `ia_thresh`/concentration/sample-area inputs a real flight supplies, so the validation step is open, not skipped. `docs/poisson_restore_design.md` |
| `intarr_policy.py` | shipped; **measured on the dense demo flight, not on real flight data** | The inter-arrival threshold rule (`min_measured` / `twice_tau2` / `min_fitted`) and the neighbour-removal count (0/1/2) McFarquhar et al. (2017) p. 11.21 name, as a **default-OFF** switch: `InterArrivalPolicy()` is UIOOPS (`min_measured`, 1 neighbour); turn it on with `InterArrivalPolicy(enabled=True, rule=..., neighbours=...)`. UIOOPS already computes all three thresholds and writes one, so the rule selects among them rather than inventing one. On the dense demo flight (240 particles) `'S'` flags go 20 → 116 under `min_fitted`, and 140 → 80 / 220 at 0 / 2 neighbours on the 6 µs default. `docs/CORRECTIONS.md`, part `intarr_policy.py` |
| `dmax_sensitivity.py` | shipped, **real-data-measured** | How far the port's six `d_choice` diameter definitions disagree for the *same* particle — calls the port's own six functions rather than re-deriving them, so the two sides come from different places. Measured on 99 real particles from the tracked S4 fixture: mean relative spread **227.95 %**, max **351.47 %**, mean absolute spread **0.388 mm**. Independently reconfirms the preserved int16 diameter saturation on real data. Corrects nothing — the six definitions are all faithfully ported; the point is that the choice is not cosmetic. `docs/dmax_sensitivity_design.md` |
| `md_relations.py` | shipped | A registry of mass-diameter relations, and a refusal to hold a number nobody can check. Four relations are registered because this repository verified them: UIOOPS's own habit-keyed `single_mass` (ported, Octave-confirmed), the Baker & Lawson area relation (the literal at `sizeDist.m:844`), DOC-0223 Table 2.1's effective densities (transcribed row by row), and Brown & Francis (1995)'s aggregate power law (`brown_francis_1995.py`, below). **Four of the five published relations the registry names remain declared gaps carrying no coefficients**: three (Heymsfield 2010, Erfani & Mitchell 2016, Leroy 2016) because the source is not held; Finlon 2019 because its source was read but its result (a chi-squared surface, not a point) has no field here to hold it. A registry is exactly where a half-remembered coefficient would become authoritative. `register()` refuses an entry with no source or no repository-level provenance, refuses to shadow a declared gap, and refuses a silent overwrite. Computes nothing itself — each entry names the code that already applies it. 17 tests. `docs/md_relations_design.md` |
| `brown_francis_1995.py` | shipped | Brown & Francis (1995) aggregate mass-diameter power law, read directly (Eq. 3 p. 411, confirmed p. 413): `M = 7.38e-11 * D**1.9`, **D in microns, M in grams** — a different unit from the port's own centimetre-based `single_mass`, stated explicitly rather than left to be assumed. Not habit-keyed: one power law for the Locatelli & Hobbs aggregate category the paper fits, not any of this port's eleven Holroyd codes — a missing-habit gap by construction, named beside the relation rather than silently implied. Opt-in: nothing in the port or any other enhancement calls it. 12 tests recompute the transcribed coefficients independently at five diameters (the paper gives no single worked example to check against) and assert the sub-100-micron sphere regime is never silently substituted. `docs/brown_francis_1995_design.md` |
| `published_dof.py` | shipped; **default OFF**, individually selectable (`published_dof = true`) | The 2D-S depth of field from Gurganus & Lawson (2018) Eq. (1) in place of `calc_sa_randombins.m:42`'s constant. Rescales the `sd` file's volume-normalised variables, so it moves numbers; OFF returns the engine's own value byte-identically. `enhancements_uiops/tests/test_published_dof.py` |
| `partial_image_habit.py` | shipped; opt-in | Korolev & Sussman (2000) RABIT: habit *fractions* for an ensemble that includes its accepted partial (edge-touching) images, from one dimensionless ratio and a probe-specific retrieval matrix. Writes no habit code onto a particle, and refuses a probe it holds no retrieval matrix for, which today is every 2D-S and HVPS. `enhancements_uiops/tests/test_partial_image_habit.py` |
| `docs/probe_crossover_design.md` | The size-crossover diagnostic between two probes on one flight: where a smaller and a larger probe's spectra should join, and what it means when they do not. |

**One design doc here describes infrastructure rather than an enhancement.**
[`docs/enhancement_registry_design.md`](docs/enhancement_registry_design.md) is the
config-file selection mechanism: every enhancement reachable by name from the run
configuration, and **opt-in, default OFF, in both pipelines** — one TOML
file, one meaning. (An earlier default-on, opt-out-by-name reading resolved a config whose
only entry was `outoffocus = false` to 31 of 40 modules ON, applying four of them;
`docs/enhancement_registry_design.md` §3–§3a records both readings and why the first was
wrong.) `registry.py` is not counted as a shipped module for
the same reason `__init__.py` is not — it decides which enhancements run rather than being
one.

**`pipeline.py` is the driver: `arrayprobe-enhanced run <config.toml>
<raw...>` runs the port (`python -m arrayprobe.cli run`, as a subprocess) and then applies
every enhancement `registry.resolve()` says is ON for the config's engine and has a driver
adapter — **13 of 42** (`pipeline._APPLIERS`; the count is checked on `README.md` and
`TWO_ENGINES.md` by `tests/test_publish_ready.py`):
`hole_edge_swap`, `particle_number_all_fix`, `particle_time_glitch_fix`, `int_arr_rollback_fix`,
`particle_time_int8_fix`, `outoffocus`, `overload_accounting_fix`, `published_dof`,
`field2006_shatter`, `pressure_units_fix`, `arco_export`, `arm_export`, `cf_export`. The rest
resolve ON but have no adapter that can apply them without knowing each module's own signature,
or are reader-stage corrections (`stage="reader"`), which act during decode and which the driver
refuses by design, naming each module's own entry point instead —
`docs/enhancement_registry_design.md` §7 has the full breakdown. It writes a `<sd>.enhancements.json` sidecar recording,
per module, whether it resolved on, was applied, or was skipped and why (an inapplicable engine,
no entry point, no driver adapter yet, or a reader-stage correction that has to run *before* the
port, not after). Not counted as a shipped module for the same reason `registry.py` is not: it
decides which enhancements run, rather than being one.**

**One design doc here has no module behind it, deliberately.**
[`docs/weigel_inter_arrival_design.md`](docs/weigel_inter_arrival_design.md) documents the Weigel
et al. (2016) ξ·µ inter-arrival correction — the paper's identity is confirmed, and the
temperature, pressure and true-airspeed inputs it needs were located in the port — but the
governing equations could not be obtained from an accessible copy, so **no code was written**
rather than a formula reconstructed from the abstract's endpoint values. The document records
what was verified, the three access attempts that failed, and what is needed before code can
exist. A stated gap, not a stub.

More enhancements land here over time, each its own module, each with the same doctrine
obligations the port itself carries: a design doc before code, an explicit statement of what
it changes and why, and a test proving the port's own output is untouched by this package's
mere presence.

## `arco_export.py` — analysis-ready export

**Answers the question**:
*"are the output data saved in ARCO formats?"* No — and `arrayprobe` itself must not. It writes
NETCDF3_CLASSIC because that is what MATLAB's bare `'clobber'` default writes, and the byte-level
fidelity claim depends on it, **including its failure modes** such as the 2 GiB non-record
variable cap that makes a large flight fail at exactly the point MATLAB's would. So the export
lives here, reads faithful output, and never modifies it.

### Measured result

| | source | export | |
|---|---|---|---|
| A flight product | 93.05 MB | **3.13 MB** | **3.4 %**, fully lossless, 1.8 s |

Every value round-trips **exactly**, verified cell by cell on all 10 variables.

### What it does beyond compression — four levers, each measured separately

**1. Dtype narrowing, and only where it is provably exact.** The production lineage declares
*every* proc variable `double`; stock declares each at its natural width. This module reads each
variable's actual values, and narrows to the smallest integer type **only if every value is
integral and the range fits**. That is lossless by construction and verified per variable, not
assumed from the declaration.

**2. Chunking — and this, not size, is what "analysis-ready" mostly means.** NETCDF3 stores a
variable contiguously: pulling one second out of a 20-million-particle file means seeking through
the whole variable. Chunked storage lets a reader fetch a slice without touching the rest, which
is the property that makes a file usable over a network or from object storage. Default 200,000
particles per chunk — large enough that per-chunk overhead is negligible, small enough that
wanting one second does not drag tens of megabytes.

**3. Compression** (zlib level 4), applied per chunk, so a reader decompresses only what it
touches. Level 4 was chosen by measurement: higher levels cost several times the write time for
a few percent.

**4. The shuffle filter, chosen per variable — and this is the counter-intuitive one.** Shuffle
reorders bytes so same-significance bytes group before compression. Measured on real data:

| variable kind | zlib4 alone | zlib4 + shuffle |
|---|---|---|
| integral (`image_length`) | 10.7 % | **8.6 %** — helps |
| float (`image_diam_minR`) | **24.9 %** | 46.4 % — *hurts, nearly double* |

So shuffle is decided per variable from the data. A contributor enabling it globally would make
every float variable roughly twice as large while believing they had optimised.

### Lossless by default, and the measurement is why

Narrowing float64 → float32 is lossy, and it buys **almost nothing** once compression is on:
23.5 % of baseline against 24.9 % for lossless float64 + zlib. A 1.4-point gain is not worth
discarding mantissa bits in a package whose entire claim is fidelity. `lossy_floats` therefore
defaults to `False`, and when enabled the **maximum relative error actually introduced is
measured per variable and written into the file** rather than described as "float32 precision".

An integral variable carrying NaN is deliberately *not* narrowed: an integer type cannot hold
NaN, and inventing a fill value would change what a reader sees. It keeps float64 and lets zlib
work — which is why the flight product's `Counts` stays `f8` above.

### Route 2 — Zarr, scoped and not built

| | |
|---|---|
| **What it adds over route 1** | A directory-of-chunks layout instead of one file, so chunks are independently addressable **objects**. That is what enables true cloud-native access (S3/GCS range reads), parallel writes from many workers, and `xarray`+`dask` lazy loading over a whole campaign at once. Route 1 gives chunked *reads*; Zarr gives chunked *objects*. |
| **What it costs** | **Three dependencies, none present**: `zarr`, `xarray`, `dask`. This package has added none so far — `particle_clustering.py` hand-rolls k-means because neither SciPy nor scikit-learn is installed. It is a real policy decision, not a switch. |
| **What it does not add** | Compression ratio. Zarr uses the same codecs (zlib/blosc/zstd) on the same chunks; the 3.4 % above would be roughly the same. **Choosing Zarr for file size would be choosing it for the wrong reason.** |
| **When it becomes right** | When the data leaves this machine — published to a bucket, read by collaborators without downloading, or analysed across many flights at once. None of those is true today. |
| **A cheaper middle step** | `xarray` alone can open the route-1 output lazily and would deliver much of the analysis ergonomics for one dependency instead of three. Worth measuring before committing to Zarr. |

**Recommendation, measured:** route 1 is built, lossless, and gives 3.4 % on a
flight product. Revisit Zarr when the data needs to be *served*, not when it needs to be smaller.

### Usage

```python
from arrayprobe_enhancements.arco_export import export
plans = export("sd.base160920063857.H.nc", "sd.base160920063857.arco.nc")
```

Every output variable records `arrayprobe_source_dtype`, `arrayprobe_lossless` and the reason for
its plan; the file records `arrayprobe_all_lossless`. 11 tests in
`enhancements_uiops/tests/test_arco_export.py`.

## `arm_export.py` — CF-1.9 + ARM Data File Standards export

ARM's own facility publishes 2D-S/HVPS datastreams (`aaf2dsh`/`aaf2dsv`
from the ARM Aerial Facility), but no public ARM page names the OAP processing software behind
them, and `ACT` (`ARM-DOE/ACT`) has no reader for any optical array probe. This writes a copy of
a port `sd`/combined output whose *structure* follows `DOE/SC-ARM-15-004` (ARM Data File
Standards, v1.3, read directly, not recalled): the required `base_time`/`time_offset`/`time`
triple (§6.1.2-6.1.3) and the §6.7.1 global attributes this export can honestly populate
(`command_line`, `Conventions`, `process_version`, `site_id`, `platform_id`, `facility_id`,
`data_level`, `datastream`, `title`, `institution`, `description`, `history`).

**Deliberately claims less than a real ARM datastream.** No DOI or `input_datastreams` (those
need an ARM Data Center registration this file never went through); no QC parallel variables
(§6.8 — the port has no per-value QC test framework yet); no `standard_name` on the physical
variables (CF's own table has no entries for `conc_minR`-style OAP quantities, and the standard's
own text forbids inventing one); and `site_id`/`facility_id`/`platform_id` are required call-time
arguments with no default, so a caller without real ARM identifiers is never handed
plausible-looking fake ones.

Changes no computed number, the same space as `arco_export.py` and `particle_clustering.py`, and
composes with `arco_export`: this covers structure and attributes, `arco_export` covers
dtype/chunking/compression — run either first.

### Usage

```python
import datetime as dt
from arrayprobe_enhancements.arm_export import export
report = export("sd.base160920063857.H.nc", "sd.base160920063857.arm.nc",
                flight_date=dt.date(2016, 9, 20), site_id="p3f",
                platform_id="oap2ds", facility_id="F1")
```

11 tests in `enhancements_uiops/tests/test_arm_export.py`, including one against the real tracked S4
Octave golden fixture (not only a synthetic stand-in). Verified against the real
`act-atmos` package (not wired into CI, a heavy optional dependency): `act.io.read_arm_netcdf`
opens the export and flags it ARM-standard.

The variable pass is `cf_export.py`'s with rescaling off: values are copied unchanged, every
`units` string is udunits-legal and says what the value is (`100/100` → `1`, and the four
corrections below), `bin_mid` carries CF bounds, and `time_hhmmss` does not carry the
non-unit `HHMMSS` as `units` — so the `CF-1.9` token in
`Conventions` is backed rather than asserted.

## `cf_export.py` — opt-in CF-1.10 export of an `sd` file

**Answers the R4 memo, Part B**: the port's `sd` files carry UIOOPS-native `units`, no
`Conventions`, no `standard_name` and an `HHMMSS` time axis. This writes a *sibling* file with a
CF time coordinate, `bin` and `area_ratio_bin` coordinates with `bounds`, SI udunits units with
the rescale factor recorded per variable (`arrayprobe_cf_scale`, source string kept as
`arrayprobe_source_units`), and provenance attributes (source file, engine from the `.call` stamp,
both package versions). The port file is only opened read-only.

**Four UIOOPS unit strings do not describe their values**, recorded
row by row in the module: `vt` (`g/cm4`) is Σ per-particle fall speed, m s⁻¹ per cm of size per
cm³ (`single_vt.m` run unmodified under Octave returns m s⁻¹; `vt/conc_minR == Prec_rate/mass` in
every single-particle bin of the Octave goldens); `Prec_rate` (`mm/hr`) is Σ mass × fall speed,
g m s⁻¹ cm⁻⁴, a mass-flux density and not a liquid-equivalent rate, so no
`lwe_precipitation_rate`; `habitmsd` (`g/cm-4`) is `g cm-4` (it sums over habit to `mass`);
`re` is micrometres although v3.5 labels it `mm`. Only `time` gets a
`standard_name`. `sd` only — `proc` variables carry no `units` at all, so they are not mapped.

**Opt-in.** The enhanced driver records a named skip (the CF time axis needs the flight date,
which the config does not carry and which is never read off a file name); run it explicitly:

```python
import datetime as dt
from arrayprobe_enhancements.cf_export import export
export("sd.base160906064017.H.nc", "sd.base160906064017.H.cf.nc", flight_date=dt.date(2016, 9, 6))
```

or `python -m arrayprobe_enhancements.cf_export SD OUT --flight-date YYYY-MM-DD`. Tests:
`enhancements_uiops/tests/test_cf_export.py`, on tracked demo `sd` files (engine 3.5's is
NETCDF4; the other was written by the earlier v3.1.4 translation, not shipped) and two Octave-written goldens with real particles.

## `poisson_uncertainty.py` — per-bin and total Poisson counting uncertainty

**The gap it fills**: nothing in UIOOPS reports an uncertainty on any written concentration. Reads
`sizeDist.m`'s own per-bin, per-second `count` variable and computes the standard Poisson
counting result — relative uncertainty `1/sqrt(N)` — citing Finlon et al. (2019, *ACP* 19,
3621-3643, Poisson sampling as one term in a processing-uncertainty decomposition) and McFarquhar
et al. (2017, ch. 11, p. 11.13, citing Hallett 2003): *"100 particles in a size bin is regarded as
statistically significant."* Both citations were already in this repository's own literature
review; this module is the first thing that computes with them. `propagate_to_total` sums `count`
along an axis and Poisson-propagates directly (`sqrt` of the sum, not quadrature of per-bin
terms — the two happen to agree exactly for Poisson variables specifically, asserted by a test
rather than assumed to be the same thing).

**Changes no computed number** — every `sizeDist` output is read verbatim; this only adds derived
arrays alongside it, the same space as `arm_export.py` and `particle_clustering.py`.

### Usage

```python
from arrayprobe_enhancements.poisson_uncertainty import (
    per_bin_relative_uncertainty, per_bin_absolute_uncertainty,
    is_statistically_significant, propagate_to_total,
)
relative = per_bin_relative_uncertainty(count)          # 1/sqrt(N), NaN where N <= 0
absolute = per_bin_absolute_uncertainty(conc_minR, count)
significant = is_statistically_significant(count)        # count >= 100, Hallett (2003)
total, total_rel, total_abs = propagate_to_total(count, axis=-1)
```

14 tests in `enhancements_uiops/tests/test_poisson_uncertainty.py`, including two against the real
tracked S4 Octave golden fixture's own `count` and `conc_minR` variables.

## `probe_uncertainty.py` — a published per-instrument-class uncertainty table

**The gap it fills**: nothing in UIOOPS's output says how far to trust a size, a concentration
or a shape classification. Read directly from Baumgardner et al. (2017, ch. 9, Table 9-2): imaging
probes (2D-S, HVPS, CIP, PIP) carry a published 10-100 % uncertainty on both size and
concentration, and need 5-12 pixels to resolve shape at all — reported as the published range,
never narrowed to an invented point estimate. `shape_floor_diameter_um` turns the pixel floor into
a real micron threshold for a given probe's diode resolution (50-120 µm for the 2D-S's 10 µm
resolution — inside this port's own excluded bins 1-5). Vaillant de Guélis et al. (2019)'s
bench-validated 2D-S sizing envelope is reported only at the two diameter bands the paper actually
measured (−23 % to +35 % at 112.8-159.6 µm for columnar particles; <10 % above 806 µm for circular
ones) — `vaillant_de_guelis_envelope` returns `None` outside them rather than interpolating a
curve the source does not draw.

**Changes no computed number** — reference data and two small computed consequences of it, the
same space as `arm_export.py` and `poisson_uncertainty.py`.

### Usage

```python
from arrayprobe_enhancements.probe_uncertainty import (
    IMAGING_UNCERTAINTY, shape_floor_diameter_um, vaillant_de_guelis_envelope,
)
IMAGING_UNCERTAINTY.size_pct              # (10.0, 100.0), Table 9-2 verbatim
shape_floor_diameter_um(10.0)             # (50.0, 120.0) um, for a 10 um-resolution probe
vaillant_de_guelis_envelope(130.0)        # (-23.0, 35.0), the measured columnar band
```

9 tests in `enhancements_uiops/tests/test_probe_uncertainty.py`.

## `effective_density.py` — a third, independent mass path

**The gap it fills — and a correction to the premise it was proposed on.** The proposal described this as filling
a gap left by "`sizeDist.m`'s only mass path", the area-based Baker & Lawson relation. **That's
wrong: the port already ships a second, genuinely habit-keyed mass path** —
`arrayprobe.particle_physics.single_mass(diameter, habit)`, a direct port of UIOOPS's own
`single_mass.m` with real per-Holroyd-habit power-law coefficients, already written to every
`sd`/combined product as the `mass` variable. This module is a **third**, independent path —
density from a published habit/area-ratio relation, not the first habit-resolved mass capability
this port has ever had — from DMT DOC-0223 Table 2.1 (Heymsfield et al. 2002, read directly,
p. 27): `ρ_e = k·A_r^n`, 17 rows transcribed verbatim, including a wind-tunnel row that turned out
to print **two** regimes (split at A_r = 0.79), not one. It gives a user a genuine choice between
UIOOPS's own native relation and this density-based one — the further literature relations the
registry names (Brown & Francis 1995, Heymsfield et al. 2010, Erfani & Mitchell 2016, Leroy et al.
2016, Finlon et al. 2019) are not yet read or built.

**Deliberately maps only one of the eleven Holroyd codes.** DOC-0223's habit categories
(`C1e-C1f`, `C2a`, `P1a-P1b-P1d`, ...) are Heymsfield's detailed crystal-habit typing; Holroyd's
codes are coarse OAP shadow-image statistics — the two schemes do not correspond one-to-one.
`M`, `C`, `t`, `o`, `g`, `s`, `i` have no matching row at all; `l` ("linear") is not asserted to
mean "column" despite the name; `h`/`d` (hexagonal/dendrite) are not force-mapped onto any of the
three "planar crystal" rows, which are keyed by *study*, not by that distinction. Only `a`
(aggregate) maps — and even then only when the caller names which of the table's **four**
different aggregate component-crystal studies applies, since this port cannot tell which from an
OAP shadow alone. The full table stays directly accessible (`lookup`) for a caller who has
independently established a real crystal habit some other way (e.g. CPI imagery).

### Usage

```python
from arrayprobe_enhancements.effective_density import effective_density, lookup
effective_density("a", 0.3, aggregate_study="kajikawa_1982")  # g/cm^3, or None outside 0.13-0.77
effective_density("d", 0.5)                                    # None -- no defensible row for 'd'
lookup("planar_surface_observations", 0.5)                     # direct table access by row name
```

16 tests in `enhancements_uiops/tests/test_effective_density.py`, including two against the real tracked
S3 proc fixture's own `holroyd_habit` codes and the same area-ratio formula `sizedist.py` itself
uses.

## `analysis.py` — a post-`sizeDist` analysis layer

**The gap it fills**: the package stops where `sizeDist` stops, one second at a time, and every
user then rewrites the same PSD-moment integrals and flight-leg summaries. Adds a general moment
function (`M_k = sum_i D_i^k * density_i * bin_width_i`, checked against the real tracked
fixture: its zeroth moment of `conc_minR` reproduces `sizeDist`'s own `n` to the last bit — the
density integration convention is verified, not assumed), the mass-weighted mean diameter D_m
(nothing in the port computes this today), and leg-scale (multi-second) aggregation with Poisson
uncertainty actually propagated through it, reusing `poisson_uncertainty.py`'s own primitives
rather than a second implementation of the same statistics.

**Does not reimplement what `sizeDist` already ships**: total number concentration (`n`), Fu
(1996) generalized effective radius (`re`, `sizeDist.m:1312`), or either existing mass path
(`mass` via UIOOPS's own habit-keyed `single_mass`, `massBL` via Baker & Lawson). `moment` and
`mass_weighted_mean_diameter` work with any density array a caller supplies — `mass`, `massBL`,
or `effective_density.py`'s output alike — so nothing here needs to change as more mass paths
land. Deliberately does not build a registry of additional published m-D relations (Brown &
Francis 1995, Heymsfield et al. 2010, Erfani & Mitchell 2016, Leroy et al. 2016) — none of those
sources has been read and verified yet (the plan's own literature pass marked them "SNIP", not
full text), and a registry around unverified coefficients would be exactly the invented-fact risk
this project's doctrine refuses.

Changes no computed number. Same space as `poisson_uncertainty.py`, `probe_uncertainty.py` and
`effective_density.py`.

### Usage

```python
from arrayprobe_enhancements.analysis import (
    moment, mass_weighted_mean_diameter, leg_mean, leg_total_count_with_uncertainty,
)
n = moment(bin_mid, bin_dD, conc_minR, order=0)              # reproduces sizeDist's own `n`
dm = mass_weighted_mean_diameter(bin_mid, bin_dD, mass)      # mm, NaN where total mass is zero
leg_n = leg_mean(n, start=120, end=340)                      # a caller-identified leg's mean N
total, rel, abs_ = leg_total_count_with_uncertainty(count, start=120, end=340)
```

15 tests in `enhancements_uiops/tests/test_analysis.py`, including three against the real tracked S4
Octave golden fixture's own `bin_mid`/`bin_dD`/`conc_minR`/`mass`/`n`/`count` variables.

## `spec_artefact_filter.py` — SPEC's own 2D-S artefact-removal algorithm

**SPEC's own artefact removal**, read directly from `2D-S Post Processing Software Manual rev1.1
20110228.pdf`, Appendix B, pp. 42-45: SPEC's own five-step spurious-event removal, as a
**selectable second** rejection scheme — never replacing, and never touching, the port's own
faithful UIOOPS `reject.py`. Roundness (`L1 >= 0.5*L5 and (L5 >= 0.5*L1 or L5 > 50)`), a
five-criterion splash test, a six-criterion line-plus-dot noise test, and an iterative
statistical noisy-diode detector (`TH = max(M + 5*sqrt(M), 1.5)`, recomputed to convergence over
a caller-maintained rolling window) with its own three rescue-exception criteria.

**L1/L2/L5/As map onto quantities `reject.py` already computes** (`p_length`, `longest_y`,
`width`, `area` — verified against `calculate_reject_unified.m`'s own port, not assumed); **L4
has no existing equivalent** and is computed fresh, reusing `reject.py`'s own `scan_slice`
primitive rather than a second, divergent slice-scanner. **Two quantities the manual defers to
"the Korolev size correction method" without giving a formula — L7 and At — are not faithfully
available here**: `outoffocus.py`'s own Korolev-style correction operates on a diameter, not a
reconstructed pixel-area count, so it is not substituted in. At is approximated as the bounding-
box pixel count (`L1 * L5`), documented as an under-estimate relative to SPEC's own
reconstruction on out-of-focus particles; the one splash criterion needing L7 specifically is not
implemented at all, stated plainly rather than faked.

**No tracked fixture in this repository carries an extractable, already-framed per-particle
image array** to validate this module against real data — proc/sd files store only the derived
scalars, and the raw S2 canvas fixtures store un-framed record buffers. Tested instead with
boundary-exact synthetic cases proving each of the ~14 boolean sub-criteria fires and does not
fire at its stated threshold, plus larger synthetic images (round, splash-shaped, line-noise-
shaped) proving the functions compose end to end.

### Usage

```python
from arrayprobe_enhancements.spec_artefact_filter import (
    spec_lengths, is_round, is_splash, is_line_or_dot_noise,
    NoisyDiodeState, update_noisy_diode_state, is_center_on_bad_diode,
    passes_noisy_diode_exception,
)
lengths = spec_lengths(image_buffer)          # L1, L2, L4, L5, As, center_diode
is_round(lengths)                             # roundness test
is_splash(lengths)                            # 4 of 5 splash criteria (L7-based v not implemented)
is_line_or_dot_noise(lengths)                 # all 6 line/dot criteria

state = NoisyDiodeState.new(n_diodes=128)
update_noisy_diode_state(state, window_of_center_diodes)   # a rolling 4000-image window
if is_center_on_bad_diode(state, lengths.center_diode):
    keep = passes_noisy_diode_exception(lengths)
```

24 tests in `enhancements_uiops/tests/test_spec_artefact_filter.py`.

## Setup

```bash
python -m pip install arrayprobe-uiops-enhancements
```

This package depends on `arrayprobe`; `arrayprobe` never depends on this package, which
`tests/test_no_enhancement_coupling.py` enforces however either is installed.

**Contributors working from a checkout of the repository** install into the root package's own venv and run this package's tests:

```bash
# From the repo root, using the root package's existing venv
# (Linux / macOS: .venv/bin/python in place of .venv/Scripts/python.exe):
.venv/Scripts/python.exe -m pip install -e enhancements_uiops
cd enhancements_uiops
../.venv/Scripts/python.exe -m unittest discover -s tests -p "test_*.py"
```

## Tools

Small measurement scripts, run from the repository root so they see both packages. Each exists
because a number in the docs should come from a script that can be re-run, not from a
transcript.

| Script | Answers |
|---|---|
| `tools/last_record_particle_sizes.py` | how big are the particles the dropped final raw record recovers, and how many reach the used size bins |
| `tools/tas_grid_ab.py` | what collapsing the TAS grid actually recovers, by running the port's own sizeDist twice |
| `tools/tas_grid_impact.py` | how many seconds a file's TAS grid duplicates, and how many particles sit in them |
| `tools/overload_impact.py` | how many seconds the no-accept second overwrite touches, how many actually change, and how many go negative |
