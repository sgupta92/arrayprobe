# Which enhancements act at which processing-chain stage
> Generated from `arrayprobe_enhancements.registry` (each module's declared `stage`) and `.pipeline` (which are wired to the automatic driver); never hand-typed. Rebuilt by the documentation build.

The chain (`09-conventions.md`): **decode** (raw binary to per-record images) -> **framing**, `imgProc_sm` (images to a `proc` file) -> **size distribution**, `sizeDist` (a `proc` file to an `sd` file) -> **combine** (a flight's `sd` files to one product) -> an optional post-combine export. Two workflows hang off this spine rather than sitting on it, and are the model for "when does this become relevant":

- **Diode testing.** The diode report, `arrayprobe.diode_report.report_from_files(decode, proc)`, needs a first decode-and-framing pass to already exist -- a stuck diode is invisible per particle and only shows up at flight scale. A confirmed mask then drives a *second* decode-and-framing pass, with the diodes declared in `[run].diode_masks`, which writes a separately-named masked output. Automatic stuck-bit repair from the report itself is not built.
- **Inter-arrival work.** `arrayprobe intarr-threshold` reads an existing `proc` file and writes the threshold file that `sizedist` (the size-distribution stage) optionally consumes as its twelfth argument -- the threshold is derived *before* the stage that uses it, not computed inside it.

**See also** [Enhancements](05-enhancements.md) · [Which enhancements apply to which engine](23-enhancements-by-engine.md) · [User guide](02-user-guide.md) for the commands themselves · [All-on sets, per probe and engine](41-all-on-sets.md).

## UIOOPS enhancements (`arrayprobe-uiops-enhancements`), by stage

**42** modules, each declaring one `stage` in `arrayprobe_enhancements.registry`. `arrayprobe run --enhancements` (`enhancements_uiops/src/arrayprobe_enhancements/pipeline.py`) applies **13 of 42** automatically once its `[enhancements]` table resolves them ON; the rest need the reason column below read before they do anything.

**How to read the tables.** Each row carries at most two tags:

- `auto` -- `arrayprobe run --enhancements` applies it once its `[enhancements]` table resolves it ON. Nothing more to do.
- `manual` -- the driver skips it; call the module yourself. The *Why manual* column quotes the driver's own skip reason.
- `needs work` -- manual only because a piece is not built yet: the driver's reason is its generic `no driver adapter yet` or `no entry_point`.
- `stated limit` -- manual for a reason the driver names (decode-time, no file stage, or a module-specific reason such as an analysis that writes no corrected file); read *Why manual*.

Each **Finding** is the title of the defect the module corrects, as recorded in the review of the UIOOPS or SODA-2 source; `—` means it corrects no recorded defect.

### The decode stage (raw binary to per-record images)

Replaces the decode itself. Cannot be bolted on after the decode stage has already written its file -- there is nothing post hoc to correct, because the particles it would recover were never decoded. A user reaches these by running the corrected reader directly, or via a raw-format reader override; `arrayprobe run --enhancements` records them as skipped with a reason naming the correction, never silently drops them.

| Enhancement | Finding | Tags | Why manual | Consumes | What to check |
|---|---|---|---|---|---|
| `last_record_fix` | the dropped final raw record | `manual` `stated limit` | — | `raw` | `enhancements_uiops/docs/CORRECTIONS.md` (its own `last_record_fix.py` section) |
| `pms_c6_routing_fix` | the misfiled F2DC scalar fields | `manual` `stated limit` | — | `raw` | `enhancements_uiops/docs/CORRECTIONS.md` (its own `pms_c6_routing_fix.py` section) |

### The framing stage (`imgProc_sm`, per-record images to a `proc` file)

Acts on a `proc` file (or the per-particle image array the framing stage holds in memory while building one). Relevant once the framing stage has run at least once -- the diode workflow's first pass is exactly this file.

| Enhancement | Finding | Tags | Why manual | Consumes | What to check |
|---|---|---|---|---|---|
| `diode_range_fix` | the image-widening diode number | `manual` `needs work` | no driver adapter yet | `images` | `enhancements_uiops/docs/CORRECTIONS.md` (its own `diode_range_fix.py` section) |
| `dmax_sensitivity` | — | `manual` `stated limit` | no driver adapter: reports a spread across definitions, writes no corrected file | `image_diam_minR`, `image_length`, `image_width` | `enhancements_uiops/docs/CORRECTIONS.md` (its own `dmax_sensitivity.py` section) |
| `effective_density` | — | `manual` `stated limit` | no driver adapter: needs area_ratio, not a stored proc/sd column | `holroyd_habit`, `image_area`, `image_diam_minR` | module docstring -- “A published, habit-dependent ice effective-density relation, from a table.” |
| `hole_edge_swap` | the swapped hole variables | `auto` | — | `edge_at_max_hole`, `max_hole_diameter` | `enhancements_uiops/docs/CORRECTIONS.md` (its own `hole_edge_swap.py` section) |
| `int_arr_rollback_fix` | the missing probetype-1 rollback correction | `auto` | — | `Time_in_seconds` | `enhancements_uiops/docs/CORRECTIONS.md` (its own `int_arr_rollback_fix.py` section) |
| `mask_presence_fix` | the silent missing mask file | `manual` `needs work` | no driver adapter yet | — | `enhancements_uiops/docs/CORRECTIONS.md` (its own `mask_presence_fix.py` section) |
| `ml_accept_reject` | — | `manual` `stated limit` | no driver adapter: an analysis (CNN suggestion), writes no corrected file | `images` | module docstring -- “Per-particle accept/reject classification beyond UIOOPS's own rule-based ladder.” |
| `outoffocus` | the unapplied Korolev size correction | `auto` | — | `image_diam_minR`, `images` | `enhancements_uiops/docs/CORRECTIONS.md` (its own `outoffocus.py` section) |
| `partial_image_habit` | — | `manual` `stated limit` | no driver adapter: a population analysis that writes no corrected file, and no retrieval matrix is held for any probe this driver runs -- Korolev & Sussman (2000)'s are the OAP-2DC's and do not transfer (p. 1057) | `images` | `enhancements_uiops/docs/CORRECTIONS.md` (its own `partial_image_habit.py` section) |
| `particle_clustering` | — | `manual` `stated limit` | no driver adapter: an analysis, writes a labels sidecar rather than a corrected proc/sd file; whether the driver should run analyses at all is not yet decided | `area_hole_ratio`, `edge_at_max_hole`, `image_area`, `image_auto_reject`, `image_diam_circle_fit`, `image_diam_minR`, `image_length`, `image_perimeter`, `image_width`, `max_hole_diameter`, `percent_shadow_area` | `enhancements_uiops/docs/CORRECTIONS.md` (its own `particle_clustering.py` section) |
| `particle_number_all_fix` | the sometimes-written Particle_number_all | `auto` | — | `Particle_number_all` | `enhancements_uiops/docs/CORRECTIONS.md` (its own `particle_number_all_fix.py` section) |
| `particle_time_glitch_fix` | the first-midnight-only rollover | `auto` | — | `Time_in_seconds`, `particle_time` | `enhancements_uiops/docs/CORRECTIONS.md` (its own `particle_time_glitch_fix.py` section) |
| `particle_time_int8_fix` | the int8 particle-time collapse | `auto` | — | `Time`, `Time_in_seconds`, `parent_rec_num`, `particle_microsec`, `particle_millisec` | `enhancements_uiops/docs/CORRECTIONS.md` (its own `particle_time_int8_fix.py` section) |
| `spec_artefact_filter` | — | `manual` `needs work` | no entry_point | `images` | module docstring -- “SPEC's own 2D-S artefact-removal algorithm, as a selectable second rejection scheme.” |
| `spot_edge_fix` | the missing decimal in spot_edge | `manual` `stated limit` | no driver adapter: needs area_ratio, not a stored proc/sd column | `edge_at_max_hole`, `max_hole_diameter`, `part_z` | `enhancements_uiops/docs/CORRECTIONS.md` (its own `spot_edge_fix.py` section) |
| `wide_hollow_fix` | the diode-32 hollow test | `manual` `stated limit` | no driver adapter: needs a reconstructed particle image, not a proc/sd column | `images` | `enhancements_uiops/docs/CORRECTIONS.md` (its own `wide_hollow_fix.py` section) |
| `zero_image_recovery` | the abandoned zero-image record | `manual` `needs work` | no driver adapter yet | `images` | `enhancements_uiops/docs/CORRECTIONS.md` (its own `zero_image_recovery.py` section) |

### The size-distribution stage and the combine step (`sizeDist`, a `proc` file to an `sd` file, then a flight's `sd` files to one combined product)

Acts on an `sd` file, or on a value the size-distribution stage (`sizeDist`) itself reads or computes -- including a flight's already-combined product, which `EnhancementSpec.stage`'s own docstring folds into this same value. Relevant once the size-distribution stage has run, or, for the inter-arrival modules, once a threshold file exists to feed the size-distribution stage's optional twelfth argument.

| Enhancement | Finding | Tags | Why manual | Consumes | What to check |
|---|---|---|---|---|---|
| `analysis` | — | `manual` `needs work` | no entry_point | `bin_dD`, `bin_mid`, `conc_minR`, `count`, `mass`, `massBL` | module docstring -- “A post-`sizeDist` analysis layer: PSD moments, mass-weighted mean diameter, and leg-scale aggregation with propagated Poisson uncertainty.” |
| `conc_arear_fix` | the double-scaled area-ratio concentration | `manual` `needs work` | no driver adapter yet | `image_diam_AreaR` | `enhancements_uiops/docs/CORRECTIONS.md` (its own `conc_arear_fix.py` section) |
| `distance_rejection` | — | `manual` `stated limit` | no driver adapter: needs tas and a threshold_distance, neither a proc/sd column | `Time_in_seconds` | module docstring -- “Inter-particle *distance* rejection, as an alternative to a fixed time threshold.” |
| `field2006_shatter` | — | `auto` | — | `Time_in_seconds` | `enhancements_uiops/docs/CORRECTIONS.md` (its own `field2006_shatter.py` section) |
| `int16_double_fix` | the int16 diameter saturation | `manual` `needs work` | no entry_point | `image_length`, `image_width` | `enhancements_uiops/docs/CORRECTIONS.md` (its own `int16_double_fix.py` section) |
| `intarr_policy` | — | `manual` `stated limit` | no driver adapter: the rule acts on the threshold file sizeDist reads (write_threshold_file) and the neighbour count inside sizeDist's per-second flagging, both before any sd file exists | `int_arr` | `enhancements_uiops/docs/CORRECTIONS.md` (its own `intarr_policy.py` section) |
| `intarr_threshold_fix` | the global-minimum inter-arrival threshold | `manual` `needs work` | no driver adapter yet | `int_arr` | `enhancements_uiops/docs/CORRECTIONS.md` (its own `intarr_threshold_fix.py` section) |
| `overload_accounting_fix` | the no-accept second overwrite | `auto` | — | `DMT_DOF_SPEC_OVERLOAD`, `Time_in_seconds`, `sample_vol`, `sum_IntArr` | `enhancements_uiops/docs/CORRECTIONS.md` (its own `overload_accounting_fix.py` section) |
| `poisson_restore` | — | `manual` `stated limit` | no driver adapter: needs false_rejection_fraction from a separate inter-arrival analysis | `conc_minR` | module docstring -- “Korolev & Field (2015) Eq. 2 -- statistically restore intact particles the inter-arrival-time shattering rejection removes as false positives.” |
| `poisson_uncertainty` | — | `manual` `needs work` | no entry_point | `count` | module docstring -- “Per-bin and total Poisson counting uncertainty on `sizeDist` output.” |
| `pressure_units_fix` | the unchecked pressure unit | `auto` | — | — | `enhancements_uiops/docs/CORRECTIONS.md` (its own `pressure_units_fix.py` section) |
| `probe_crossover` | — | `manual` `needs work` | no entry_point | `bin_dD`, `bin_max`, `bin_min`, `conc_minR`, `count`, `time` | module docstring -- “The 2D-S/HVPS crossover diagnostic: do two probes agree where their size ranges overlap?” |
| `published_dof` | — | `auto` | — | `bin_dD`, `bin_mid`, `conc_minR`, `n` | `enhancements_uiops/docs/CORRECTIONS.md` (its own `published_dof.py` section) |
| `reaccept_every_event_fix` | the first-event-only reacceptance scan | `manual` `stated limit` | no driver adapter: re-running sizeDist needs the run's own call arguments (pressure, threshold file), not recoverable from the .call stamp -- same gap as pressure_units_fix; use reaccept_every_event_fix.run_sizedist(..., reaccept_every_event=True) from Python | `Time_in_seconds`, `image_auto_reject`, `image_diam_minR` | `enhancements_uiops/docs/CORRECTIONS.md` (its own `reaccept_every_event_fix.py` section) |
| `reshape_fix` | the missing mean-ratio transpose | `manual` `needs work` | no driver adapter yet | `mean_area_ratio` | `enhancements_uiops/docs/CORRECTIONS.md` (its own `reshape_fix.py` section) |
| `rollover_fix` | the first-midnight-only rollover | `manual` `stated limit` | no driver adapter: in-memory time-array correction, no proc/sd file shape to copy-then-correct | `timehhmmss` | `enhancements_uiops/docs/CORRECTIONS.md` (its own `rollover_fix.py` section) |
| `tas_grid_fix` | the duplicate TAS-second particle loss | `manual` `stated limit` | no chain adapter: run_flight.py applies it inside S4 itself (DRIVER_PROTECTIVE; regular grid with a TAS chain, collapsed probe grid without), stamped tas_grid= in the sd .call | — | `enhancements_uiops/docs/CORRECTIONS.md` (its own `tas_grid_fix.py` section) |

### post-combine (an export or copy of an already-written port output file)

Acts on a finished port output file, any stage's. Relevant last, once there is a file to export or restructure.

| Enhancement | Finding | Tags | Why manual | Consumes | What to check |
|---|---|---|---|---|---|
| `arco_export` | — | `auto` | — | `*` | module docstring -- “Analysis-ready export of a port output file — lossless by default.” |
| `arm_export` | — | `auto` | — | `time` | module docstring -- “A CF-1.9 + ARM Data File Standards structural copy of a port output file.” |
| `cf_export` | — | `auto` | — | `*` | module docstring -- “An opt-in CF-1.10 copy of a port `sd` (`sizeDist`) output file.” |

### no file stage (a reference table or pure function)

No proc/sd/product file to act on -- a lookup table or a function that takes call arguments the run configuration supplies rather than anything read from a file.

| Enhancement | Finding | Tags | Why manual | Consumes | What to check |
|---|---|---|---|---|---|
| `brown_francis_1995` | — | `manual` `stated limit` | no file stage | — | module docstring -- “Brown & Francis (1995) mass-diameter power law -- closing the `brown_francis_1995` gap in `arrayprobe_enhancements.md_relations`.” |
| `md_relations` | — | `manual` `stated limit` | no file stage | — | module docstring -- “A registry of mass-diameter relations -- the mechanism, and only what has actually been read.” |
| `probe_uncertainty` | — | `manual` `stated limit` | no file stage | — | module docstring -- “A published per-instrument-class uncertainty table, shipped with the outputs.” |

## SODA-2 corrections (`arrayprobe-soda2-enhancements`) -- no per-stage split

**19** modules. SODA-2 is a single processing lineage with one source tree, not staged decode/imgProc/sizeDist/combine like UIOOPS -- `arrayprobe_soda2_enhancements.registry`'s own docstring gives the reason there is no engine matrix, and the same fact means there is no stage matrix either: a correction here applies or it does not, judged by `reachability` (`live`/`latent`/`flagged`, the SODA-2 review's own classification of how often the defect fires on real data), not by where in a chain it sits.

**How to read this table.** The same tags as the UIOOPS tables, read from `arrayprobe_soda2_enhancements._adapter`'s `ROUTES` and `NOT_ROUTED`:

- `auto` -- `arrayprobe soda2 run` substitutes it for the port function it corrects once it resolves ON (SODA-2 corrections are opt-in, except the five in `registry.PROTECTIVE`, which run by default because SODA-2 has no archived product); the run's `.pbp.call` sidecar records it as applied.
- `manual` `stated limit` -- the adapter names why it cannot substitute it, and *Why manual* quotes that reason. Call its entry point yourself.
- `manual` `needs work` -- no entry point, or no adapter decision yet.

*Reachability* is the SODA-2 review's own classification of how often the defect fires on real data. Each **Finding** is the title of the defect, as that review records it.

| Correction | Finding | Tags | Why manual | Reachability | Entry point | What to check |
|---|---|---|---|---|---|---|
| `aspr_nan_fix` | `aspr < 1.0` is MIN, and it maps every non-finite result onto exactly 1.0 | `auto` | — | live | `corrected_aspr` | `enhancements_soda2/docs/CORRECTIONS.md` (its own `aspr_nan_fix.py` section) |
| `blank_roi_dof_fix` | A blank ROI is accepted as within depth of field | `auto` | — | flagged | `corrected_binary_dof` | `enhancements_soda2/docs/CORRECTIONS.md` (its own `blank_roi_dof_fix.py` section) |
| `den_clamp_fix` | The `den` clamp guards a 0/0 that cannot happen, and bites one that can | `auto` | — | live | `corrected_aspr` | `enhancements_soda2/docs/CORRECTIONS.md` (its own `den_clamp_fix.py` section) |
| `dilation_clamp_fix` | The dilation kernel clamps against the roi's own slice count, not the padded array it dilates | `auto` | — | live | `corrected_label_blobs_dilation` | `enhancements_soda2/docs/CORRECTIONS.md` (its own `dilation_clamp_fix.py` section) |
| `double_pi_fix` | `!pi` is single precision, and it silently changes `min_circle_fast`'s corner count | `auto` | — | live | `corrected_aspect_ratio` | `enhancements_soda2/docs/CORRECTIONS.md` (its own `double_pi_fix.py` section) |
| `empty_roi_diodegaps_fix` | The empty-ROI `diodegaps` value is `1`, not `0`, through the same no-match `where()` sentinel S4-t and S5-f both reach by different routes | `manual` `stated limit` | inline arithmetic inside process_buffer_tail (processbuffer_tail.py:283); no function boundary to substitute | flagged | `corrected_diodegaps` | `enhancements_soda2/docs/CORRECTIONS.md` (its own `empty_roi_diodegaps_fix.py` section) |
| `fillholes_int_labels` | `fillholes` wraps its hole labels modulo 256, so region 256 is never filled and region 257 shares region 1's fate | `auto` | — | latent | `corrected_fillholes` | `enhancements_soda2/docs/CORRECTIONS.md` (its own `fillholes_int_labels.py` section) |
| `hk_probeid_columns` | `spec_process_hk`'s voltage/count columns default to the horizontal-channel set for every `probeid` but `'V'` | `auto` | — | flagged | `corrected_process_hk` | `enhancements_soda2/docs/CORRECTIONS.md` (its own `hk_probeid_columns.py` section) |
| `label_blobs_int_count` | `label_blobs`'s default byte return wraps at 256 blobs | `auto` | — | latent | `corrected_label_blobs` | `enhancements_soda2/docs/CORRECTIONS.md` (its own `label_blobs_int_count.py` section) |
| `last_buffer_index_fix` | The last buffer of every file is never indexed, and its own header is never range-checked | `auto` | — | live | `corrected_spec_index` | `enhancements_soda2/docs/CORRECTIONS.md` (its own `last_buffer_index_fix.py` section) |
| `no_stuck_diode_fix` | The no-stuck-diode case is a silent scalar-index bug on wide probes, and halts only on a narrow one | `auto` | — | live | `corrected_fixstuckbits` | `enhancements_soda2/docs/CORRECTIONS.md` (its own `no_stuck_diode_fix.py` section) |
| `pbp_inttime_consistent` | `.pbp.csv` and `.pbp.nc` write two different values for the same `inttime` column | `manual` `stated limit` | its writer needs `interarrival`, which the driver's write_pbp_csv_buffer call (process_2d.py:389) does not pass | live | `corrected_write_pbp_csv_buffer` | `enhancements_soda2/docs/CORRECTIONS.md` (its own `pbp_inttime_consistent.py` section) |
| `pbp_rejectionflag_ubyte` | `.pbp.nc`'s `rejectionflag` is a signed byte | `auto` | — | live | `corrected_open_pbp_ncdf` | `enhancements_soda2/docs/CORRECTIONS.md` (its own `pbp_rejectionflag_ubyte.py` section) |
| `poisson_fill_guard` | A zero or shrinking fill area drives the Poisson correction through a floating-point error, then silently down the "no spot" path | `auto` | — | live | `guarded_poisson_spot_correct` | `enhancements_soda2/docs/CORRECTIONS.md` (its own `poisson_fill_guard.py` section) |
| `rejection_tally_fix` | Bit 128 (depth-of-field) is never counted in `soda2_particlesort`'s per-reason tally | `manual` `stated limit` | returns a separate corrected tally beside the port's own; call it on the run's arrays, it substitutes no driver call | live | `corrected_count_rejected` | `enhancements_soda2/docs/CORRECTIONS.md` (its own `rejection_tally_fix.py` section) |
| `rollover_modulus_fix` | The 2D-S rollover constant is 2³²−1, one tick short of the true modulus | `manual` `stated limit` | inline arithmetic inside process_spec_buffer (processbuffer_spec.py:305); no function boundary to substitute | live | `corrected_inttime` | `enhancements_soda2/docs/CORRECTIONS.md` (its own `rollover_modulus_fix.py` section) |
| `run_diagnostics` | A ≥1000-slice frame or a >10 000-line buffer is dropped with no count kept | `manual` `stated limit` | a diagnostic: reports on a run and changes no output | flagged | `spec_buffer_diagnostics` | `enhancements_soda2/docs/CORRECTIONS.md` (its own `run_diagnostics.py` section) |
| `same_time_buffer_fix` | A same-time buffer stamps its first particle with the previous buffer's last time | `auto` | — | live | `corrected_process_spec_buffer` | `enhancements_soda2/docs/CORRECTIONS.md` (its own `same_time_buffer_fix.py` section) |
| `zero_area_return_fix` | The zero-area return hands back defaults that read as measurements | `auto` | — | flagged | `corrected_soda2_findsize` | `enhancements_soda2/docs/CORRECTIONS.md` (its own `zero_area_return_fix.py` section) |
