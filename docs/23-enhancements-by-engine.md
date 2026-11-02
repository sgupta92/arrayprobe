# Which enhancements apply to which engine
> Generated from `arrayprobe_enhancements.applicability`, the same declaration the resolver consults; never hand-typed. Rebuilt by the documentation build.

The UIOOPS engine in this package translates UIOOPS v3.5. Every enhancement was first written against an earlier translation of UIOOPS v3.1.4, which reproduced archived products and is not part of this package; this page says what that means for each one on v3.5.

**The short version.** All 36 are listed. **31** apply on v3.5. The rest are listed below with the reason, and the reasons are not interchangeable: an enhancement fixed upstream would produce a wrong number, one not yet read against v3.5 would produce an unverified one, and one describing a campaign variant has nothing to act on.

SODA-2 is not on this page. It is a separate processing lineage rather than a UIOOPS version, and its port runs the SPEC chain, and the CIP route for SEA- and DMT-format files, end to end, raw through to `.pbp.nc`/`.pbp.csv` output. No enhancement *here* was written against it, but a separate package, `enhancements_soda2` (`arrayprobe-soda2-enhancements`, 18 correction modules plus one diagnostics-only module), was.

**See also** [Enhancements](05-enhancements.md) · [Findings](07-findings.md) · [Validation](04-validation.md) · [All-on sets, per probe and engine](41-all-on-sets.md).

**How to read the tables.** Each section is one state on the default engine (v3.5).

- **Finding** -- the title of the upstream defect the module corrects, as the upstream review records it; `—` means it corrects no recorded defect.
- **v3.5 site** -- where in the v3.5 source the reading was made.
- **How established** -- the declaration's own `basis`, quoted.

## Already fixed by the UIOOPS developers in v3.5

**Do not apply these on v3.5** -- the correction is already in the source, so applying it again changes the number rather than doing nothing. `resolve()` leaves them off there and raises if a config file switches one on by name. These are also the project's strongest external evidence: the maintainers reached the same conclusion independently.

| Enhancement | Finding | v3.5 site | How established |
|---|---|---|---|
| `int16_double_fix` | the int16 diameter saturation | `sizeDist.m:941-942` | already fixed in v3.5, established by reading the v3.5 source: im_width = double(netcdf.getVar(...)) -- the cast moved to the read, dated Joe Finlon 02/13/19, which is the edit this project's upstream feedback suggested |
| `reshape_fix` | the missing mean-ratio transpose | `sizeDist.m:2412, :2434` | already fixed in v3.5, established by reading the v3.5 source: all six variables now carry the transpose their neighbours had, same dated pass as the int16 x double cast fix. The classifier still calls this finding still-present, because a defect fixed by rewriting the code around it goes on matching -- the reading wins |

## A campaign variant, not stock UIOOPS

The construct these correct exists in no stock UIOOPS release -- it is in a campaign-specific variant tree that produced archived products. It is absent from stock v3.5 rather than fixed in it.

| Enhancement | Finding | v3.5 site | How established |
|---|---|---|---|
| `diode_range_fix` | the image-widening diode number | `imgProc_sm.m:850 (guard only; no widening construct)` | read against v3.5: the only surviving construct is the width guard (imgProc_sm.m:850, `figsize(2)~=diodenum` -> disp + return); no mask re-illumination/widening code (`shadow_diode`, `c(:,...)='1'`) exists anywhere in the file -- grepped for 'diodenum', 'figsize', 'shadow_diode' and neither the nine-argument imgProc_sm form nor masks.reilluminate's MATLAB counterpart is present. The widening this module corrects is on the mask-file path, which is FORK_ONLY per uiops.CATALOGUE and absent from stock v3.5 |
| `intarr_threshold_fix` | the global-minimum inter-arrival threshold | — | classifier: variant-only. The construct exists in no stock UIOOPS release -- it describes a field campaign's modified UIOOPS, which is what produced the archived products. Absent from stock v3.5 rather than fixed in it |
| `mask_presence_fix` | the silent missing mask file | `imgProc_sm.m:1 (signature); no mask branch found` | read against v3.5: imgProc_sm.m's signature (infile, outfile, probename, n, nEvery, projectname, iRectEllipse, iCalcAllDiodeStats, iQC, iNewHabit, varargin) carries no ninth-argument masks form, and grepping the whole file for 'exist(', 'maskfile', 'mask_file', 'reilluminate' and 'masks' returns nothing -- the 9-arg mask branch this module corrects is FORK_ONLY per uiops.CATALOGUE and does not exist in stock v3.5 |

## Apply to both engines (31)

Corrections whose defect is still present in v3.5; those in files byte-identical between the two releases, so the finding and its line numbers transfer untouched; and the new-capability and literature modules, which correct no defect and so have no version axis at all.

| Enhancement | Finding | How established |
|---|---|---|
| `analysis` | — | new capability; corrects no defect |
| `arco_export` | — | new capability; corrects no defect |
| `arm_export` | — | new capability; corrects no defect |
| `brown_francis_1995` | — | new capability; a published (1995) aggregate mass-diameter power law, read directly from the paper and registered in md_relations; corrects no defect in either engine and is not consulted by either by default |
| `cf_export` | — | new capability; corrects no defect -- reads sizeDist's variables, whose unit strings are identical in v3.1.4 and v3.5 except re (um vs mm), which the mapping accepts both ways |
| `distance_rejection` | — | Korolev & Field (2015) §4; a published method applied to either engine's output, not a correction to either |
| `dmax_sensitivity` | — | new capability; reports how far the six diameter definitions disagree |
| `effective_density` | — | new capability; corrects no defect |
| `field2006_shatter` | — | derived from NCAR Process2D (NCAR/aircraft_oap, Apache-2.0), Field et al. (2006); a published inter-arrival method applied to either engine's particle times, not a correction to either. Opt-in, selected per run |
| `hole_edge_swap` | the swapped hole variables | read against v3.5: the swap is unchanged. defVar names varid29 'edge_at_max_hole' and varid30 'max_hole_diameter' (imgProc_sm.m:564-573); putVar then writes varid29 from images.max_hole_diameter and varid30 from images.edge_at_max_hole (:1376-1377) -- the two are still swapped on the way to disk, exactly as arrayprobe_uiops/imgproc.py:43-45, :729-732 already documents |
| `int_arr_rollback_fix` | the missing probetype-1 rollback correction | read against v3.5: the inter-arrival rollback branch is unchanged -- sizeDist.m:1025-1029 corrects probetype 2 (int_arr < -10) and probetype 0 (int_arr < 0) and has no clause for probetype 1, and :1044-1045 still marks every particle left negative 'I' and zeroes its int_arr, as v3.1.4's :852-856 and :871-872 do. Live on v3.5 for probetype 1 on every iaThreshType; the shattering-reacceptance fix v3.5 made in its type-3 branch is a different finding and does not touch this branch |
| `intarr_policy` | — | McFarquhar et al. (2017) p. 11.21; selects among the three thresholds both IntArrAnalysis_time.m and stock v3.5 IntArrAnalysis.m (:116, :146-147; writes :290) already compute, and varies the neighbour count of the (ix-1):ix flagging both engines share (v3.1.4 sizeDist.m:1017, :1149; v3.5 :1194, :1326, :1393) |
| `md_relations` | — | a table of mass-diameter relations; computes nothing engine-specific |
| `ml_accept_reject` | — | new capability; operates on rendered images, not on either engine's internals |
| `outoffocus` | the unapplied Korolev size correction | classifier: still-present in sizeDist.m |
| `overload_accounting_fix` | the no-accept second overwrite | classifier: still-present in sizeDist.m. Conditional on the run, not on the engine: v3.5 sizeDist.m only defVars sum_IntArr/sample_vol under `if iSaveIntArrSV == 1` (:2363-2372), and scripts/run_flight.py's V35_CALL pins iSaveIntArrSV=0 for every default v3.5 run (arrayprobe_uiops/sizedist.py:706's write gate) -- measured on the tracked demo_flight_v35_sd.nc, which holds neither variable. The module names this refusal (overload_accounting_fix.MissingSizeDistVariables) rather than applying vacuously; a caller who wants this correction on v3.5 must re-run sizedist.run with i_save_int_arr_sv=1 first |
| `partial_image_habit` | — | Korolev & Sussman (2000) Sect. 4b-d; a published population classifier applied to either engine's silhouettes, not a correction to either. Neither engine classifies accepted partials with a partial-specific rule: v3.1.4 runs holroyd.m on the truncated image (imgProc_sm.m:807); v3.5 withholds a habit ('C') for centre-out images (imgProc_sm.m:1282-1285) and, under iNewHabit=1, for edge contact above half the diameter (holroyd_new.m:101-104), and runs the complete-image rules on the rest -- exclusion, not the paper's method, so there is no upstream fix to delegate to |
| `particle_clustering` | — | new capability; reads nine proc-file columns by name (`extract_features`, particle_clustering.py:99-157) -- v3.5 drops one of them (`image_diam_circle_fit`), so `feature_names_for('3.5')` clusters on the remaining eight plus `compactness`. Row 29 in applicability_matrix.md |
| `particle_number_all_fix` | the sometimes-written Particle_number_all | read against v3.5: the write guard still excludes probetype 0 and 3. varid104 ('Particle_number_all') is *defined* under `if probetype~=0 || probetype~=3` (:347, an OR that is true for every probetype) but *written* under `if probetype~=0 && probetype~=3` (:1329, an AND that excludes probetype 0 and 3) -- the same asymmetric gate the port's docstring already cites (arrayprobe_uiops/imgproc.py ':356' / ':1329-1331') |
| `particle_time_glitch_fix` | the first-midnight-only rollover | read and measured against v3.5: the developers met the cascade (sizeDist.m:788-806, Finlon 02/13/19, 'ignore corrupt particle boundary times') by shifting only at a decrease that passes their day-crossover test, but the test is applied to single values, so one all-ones header (316363 = 31:63:63) passes it -- on 2016-09-06 CIP session 2, 232 decreases pass and arrayprobe_uiops.sizedist.fix_multiday_particle_times shifts 2,886,521 particles from particle 910,043 on. A single glitch still cascades too (:787-789 shifts on exactly one decrease), and no version removes the glitched particles from the one-second block table. This module reuses their test (on local medians) to tell a crossover from a glitch, and repairs the proc before either engine's sizeDist reads it |
| `particle_time_int8_fix` | the int8 particle-time collapse | measured against v3.5: the Octave oracle pair for this finding, rebuilt on the unmodified v3.5 tree with the real CGAL_minR_v35 MEX, writes particle_time [127, 127] at 06:06:58 where the true value is [60658, 60702]; its 00:00:58 twin writes [58, 102], which the correction reproduces exactly. Same write expression (imgProc_sm.m:1336) over the same int8 header seed (:697, :887-889). test_particle_time_int8_fix.py::AgainstTheV35OctaveOraclePair |
| `pms_c6_routing_fix` | the misfiled F2DC scalar fields | read_binary_PMS.m is byte-identical between v3.1.4 and v3.5, so the finding and its line numbers transfer untouched. Applicable to both engines, but reader-stage (registry.py's `stage` field): `arrayprobe run --enhancements` cannot apply it after the port has already decoded, and no re-decode path is built for it -- call read_binary_PMS_corrected yourself, before the port runs, rather than through the driver |
| `poisson_restore` | — | Korolev & Field (2015) Eq. 1-2; a published method applied to either engine's output, not a correction to either |
| `poisson_uncertainty` | — | new capability; corrects no defect |
| `probe_crossover` | — | new capability; corrects no defect -- reads six sd variables both sizeDist translations write under the same names (test_probe_crossover.py runs it on a v3.1.4 and a v3.5 sd file) |
| `probe_uncertainty` | — | new capability; corrects no defect |
| `published_dof` | — | Gurganus & Lawson (2018) Eq. 1, c = 8 +/- 0.2; replaces calc_sa_randombins.m:42, which is byte-identical in v3.1.4 and v3.5 (one port, sample_area.py:84-88, shared by both engines) |
| `rollover_fix` | the first-midnight-only rollover | read against v3.5: the two rollover halves diverged. The per-second `timehhmmss` rollover is byte-for-byte the original defect -- `timehhmmss(find(diff(timehhmmss)<0)+1:end) = ... + 240000` (:130-131) still uses only the first decrease, because MATLAB's `a:b` takes only the first element of a vector operand, unchanged from v3.1.4. The particle-time half (`image_time_hhmmssall`) loops over every decrease via `decreasedTimeInds` (:788-799), which is the half v3.5 fixed (arrayprobe_uiops/sizedist.py:172-215, `fix_multiday_particle_times`, which itself stops at the first genuine crossover it finds). This module corrects only the surviving `timehhmmss` half on v3.5 |
| `spec_artefact_filter` | — | 2D-S only, per the SPEC manual; a probe restriction rather than a version one, and it applies to both engines' 2D-S output |
| `spot_edge_fix` | the missing decimal in spot_edge | classifier: still-present in calculate_reject_unified.m |
| `tas_grid_fix` | the duplicate TAS-second particle loss | classifier: still-present in sizeDist.m |
