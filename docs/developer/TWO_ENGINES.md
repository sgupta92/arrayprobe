# Two UIOOPS engines: which to use and what its numbers rest on

Cite SODA-2 as: Aaron Bansemer. (2026). abansemer/soda2: v2.26.0 (Version v2.26.0) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.18331418

**Short answer.** `uiops.engine()` gives you v3.5 -- use it for new data. The v3.1.4
translation had one job, reproducing the archived ORACLES products, and is not part of this package.

**A third package, `arrayprobe_soda2`, is not a UIOOPS engine**: it ports NCAR's SODA-2 (IDL, a
separate lineage), so `uiops.engine()` never returns it and this comparison does not apply to it.

**`arrayprobe.engine()` selects the engine**: no argument for v3.5, `"soda2"` for SODA-2. It
dispatches and computes nothing. An earlier translation of UIOOPS v3.1.4 reproduced the archived
ORACLES products and is not part of this package. `uiops.engine()`, not
deprecated, is the narrower selector for *which UIOOPS release*, and refuses SODA-2.

## 1. Port validation -- what "this port is right" means for each

| | v3.1.4 engine (not part of this package; internal validation only) | v3.5 engine (`arrayprobe_uiops`) |
|---|---|---|
| Layer 1: bit-for-bit against an archived product written by the original MATLAB | Was, as internal validation: 15 ORACLES flights reproduced, 10 exactly. Not in this package. | NO, and never: no archived product was ever produced by v3.5 |
| Layer 2: every routine asserted against GNU Octave running the unmodified MATLAB | yes, per pure-`.m` file | yes, for the **stock v3.5 path**: every stage of the v3.5 port; three whole-program goldens, 6,819 particles, zero disagreeing items |
| Layer 3: documented semantics + pinned tests (MEX, the parts Octave cannot run) | yes | yes |

Layer 1 is the stronger claim: it says the whole chain, on real data, wrote what the original wrote.
Layer 2 says each piece behaves like the original piece on the inputs tried so far.

**The layer-2 row carries one qualifier.** The v3.5 engine also carries `arrayprobe_uiops.mass_b26`
(Peter Brechner's `Mmethod` mass dispatch, `mmethod` 1-3), which is in **no** tagged UIOOPS
release; the goldens validate the **stock v3.5 path only**. `mass_b26` is not in this release (the
method is unpublished), so `mmethod` 1-3 refuse by name here and only the default runs. Every such addition is **opt-in, off by default,
bit-identical to stock when off** (`tests/test_mmethod_brechner.py::TestDefaultIsBitIdentical`,
`np.array_equal`, not `allclose`), and validated against **its own named oracle** rather than the
Octave goldens: for `Mmethod`, a hand computation of `massB26.m:1-13`
(`TestMassB26Formula`), cross-checked end-to-end against the UIOOPS developers' own `Valid_Output`
netCDF (run against the developers' own test case), which found the expected
mass redistribution plus a separately tracked, unported divergence elsewhere in the chain -- a
cross-check, not a completed reconciliation. The stock-path claim does not cover everything the
engine can compute, and every non-stock path is off unless asked for.

## 2. Data processing -- what actually differs when you run them

- Same file in, different numbers out, by design. The earlier v3.1.4 translation (not shipped) found defects in that release
  (habit `'C'` dead, returning via `holroyd_new.m`; the 32-diode hollow packing; int16 sizing
  saturation; ...); v3.5 fixes them in the source. That translation reproduced them unchanged,
  because the archived products contain them.
- Outputs: the earlier v3.1.4 translation wrote NETCDF3 classic like MATLAB's `'clobber'`; v3.5 writes NETCDF4 with deflate.
- Thresholds: both stock trees use the same reject thresholds (`STOCK_V314` / `STOCK_V35` hold
  identical values, cited to different lines; measured field by field).
  Only the ORACLES production fork changes them (`ORACLES_PRODUCTION`). The S4 `'z'` threshold
  (the `.2` literal at v3.5 `sizeDist.m:1162`) has one opt-in override, default off:
  `--area-ratio-z` on the driver, `area_ratio_z=` on `arrayprobe_uiops.sizedist.run`, range
  `[0, 1]` with `0` meaning the gate is off. Unset, the output is bit-identical; set, the value
  is in the sd `.call` stamp and in an `arrayprobe_area_ratio_z` global attribute. Its oracle is
  Octave on a shadowing copy of the vendored `sizeDist.m` with that one literal changed
  (the Octave bank `run_v35_area_ratio_z_bank.py`, not included in this release). The shattering threshold has the same kind of
  override, `--default-int-arr-thresh` / `default_int_arr_thresh=`, replacing only the probe
  case's `defaultIntArrThresh`; it acts only where the case's `applyIntArrThresh` is 1 and
  `iaThreshType` is 2, and writes `arrayprobe_default_int_arr_thresh`. Its oracle has the same
  shape, on SOCRATES/2DS's literal at `sizeDist.m:313`, read at `:318`
  (the Octave bank `run_v35_default_int_arr_thresh_bank.py`, not included in this release).
- Cloud regimes (`--regime` / `[thresholds].regime`) work on engine 3.5. A regime carries eight
  thresholds: the two size-distribution ones (`area_ratio_z`, `default_int_arr_thresh`), each a
  cited value, and the six reject ones (`rej_zero_area`, `rej_split`, `rej_hollow`,
  `shadowed_area`, `max_edge_img_ar`, `max_comp_img_ar`), each a cited value or inherited from
  the profile. Per field, a value given on the command line or in `[thresholds]` wins over the
  regime, the regime over the profile, and the profile over the stock tree; with no regime and no
  override, engine 3.5 uses the probe case's own cited values.
  A regime does not carry the shattering gate (`applyIntArrThresh`), the re-acceptance constants,
  `iaThreshType` or the bin ladder: those stay in the probe case and `[shattering]`. The stamp is
  additive: the sd `.call` gains `area_ratio_z=` and `default_int_arr_thresh=` only when set,
  tagged `(regime:<name>)` when the regime supplied them, and every `proc`/`sd` `.call` gains
  `regime=<name> reject_sources=(...)` only when the regime sets a reject slot, so a run naming
  no regime writes the stamp and the bytes it always wrote.
- Two S4 inputs a case can lack, neither with a default: `--tas-max` /
  `[thresholds].tas_max` (`tas_max=` on `sizedist.run`) supplies the 2DP's `tasMax`, which no
  release assigns, and `--pecan-params` / `[thresholds].pecan_params` (`pecan_params=`) a spiral
  CSV standing in for `getPECANparams`, which no release ships (`arrayprobe_uiops.pecan_params`).
  The driver refuses a 2DP or PECAN run without its input and either input on a case that does
  not need it; each reaches the sd `.call` only when set.
- Configuration: `[fidelity].profile = "stock-v3.5"` with `[run].engine = "3.5"` runs the v3.5 engine
  end to end through `arrayprobe run`; the profile selects only the reject thresholds, and the
  v3.5-only call switches are one cited record, `run_flight.V35_CALL`, stamped in every `.call`. The
  two engines refuse each other's profile and each other's intermediate files (the stamp carries
  `engine=3.5`).
- Not stock in v3.5: the combine. A v3.5 run stitches only with `[combine].borrowed = true`, using
  the ORACLES fork's `combine_sizedist.m`, and the product's `.call` says so. Under the driver,
  `iRectEllipse`, `iQC`, `iNewHabit` and the TAS ratio are fixed at 0/off by `V35_CALL`; the library
  exposes all of them (`iQC=1` and `iRectEllipse=1` are ported and Octave-goldened).
- Hollow particles are the first thing to check when a v3.5 count disagrees with another
  engine's. v3.5 divides a hollow (`'H'`, Poisson-spot) particle's size by its Korolev factor
  before binning it; SODA-2 does not unless `apply_psc` is set. `arrayprobe view hollow
  proc.<stem>.H.nc --edges-um ...` (`arrayprobe.diagnostic_views.hollow_share`, and
  `hollow_share_at_or_above` for one threshold) reads one v3.5 proc file and reports, per bin,
  the hollow share, how many particles the division moves, the undivided/written count ratio and
  a YES/NO verdict on whether hollow sizing can explain the difference. It writes nothing.
  `examples/1_getting_started/03_choosing_an_engine.ipynb` runs it on a flight with no hollow particles (NO) and on
  one where most are hollow (YES).

### 2a. Speed -- opt-in parallelism, per engine, and what each is proven to preserve

**Opt-in parallelism, proven byte-identical to the serial path by test, default serial, no
accuracy traded.** Figures are quoted from `SPEED.md`, the source of record for speed claims.
Every flag below lives in the port, not the enhancements package, because none moves a written byte.

| Path | `arrayprobe` (v3.1.4) | `arrayprobe_uiops` | `arrayprobe_soda2` |
|---|---|---|---|
| Stage-2 decode | `--s2-jobs N`, byte-identical (the v3.1.4 engine's tests, not included in this release); **no published multiplier** | `--s2-jobs N` on SPEC probes (`readers.spec.read_binary_spec_v35_parallel`, each part primed with the running airspeed and every seam checked), byte-identical (`tests/test_v35_spec_parallel.py`, `tests/test_run_flight_v35_s2_jobs.py`); **no speed figure measured** | n/a |
| Stage-3 records | `--chunks N`, byte-identical (the v3.1.4 engine's tests, not included in this release); **no published multiplier** | `--chunks 8` on **CIP**: 269.5 s -> 103.0 s, **2.5-2.6x** (2.62x here; a repeat read 2.48x; a contended run read 5.57x and is discarded, `SPEED.md:477-483`), all **40** netCDF variables byte-equal (`tests/test_v35_imgproc_merge_chunks.py`). **2D-S/HVPS/3VCPI chunkable via prefix-priming**, refused only when `iQC=1`; `Time_in_seconds` accumulates file-wide but the seam state is primed from a header-only scan. No multiplier measured | n/a |
| Stage-2 decode, CIP/PIP `.cip` | `--s2-jobs N` through `readers.dmt.read_binary_DMT_parallel` (the driver refuses v3.1.4 on CIP/PIP), byte-identical (`tests/test_dmt_parallel.py`); **no speed figure measured** | same reader, same flag, same test | n/a |
| Whole-file loop | `--jobs N` across files, byte-identical (`tests/test_run_flight_jobs_watchdog.py`); **no published multiplier** | inherits `--jobs` | `--jobs 12` on **CIP (SEA)**: 413.1 s -> 111.7 s, **3.70x**, all **35** arrays byte-equal (`tests/test_soda2_parallel.py`) |
| Hot kernels | `--jit`, byte-identical (the v3.1.4 engine's tests, not included in this release), needs numba; **no published multiplier** | `--jit` (`arrayprobe_uiops.jit_kernels`), byte-identical on the real production CIP file (`tests/test_v35_imgproc_jit_identity.py`), needs numba; multiplier in `SPEED.md` only | n/a |

**Both measured rows are CIP**, one stage, one file, 12 logical cores otherwise idle (950 records /
82,028 particles; 949 buffers / 81,169 particles). Neither is a 2D-S or HVPS number, and no
package-wide multiplier exists.

**The refusals are part of the capability.** `arrayprobe soda2 run --jobs N` **exits 2 wherever a
substitution cannot be rebuilt inside the worker**. SODA-2's corrections and the 2016 UND emulation
replace module globals, and a spawned worker inherits no monkey-patch, so a naive parallel run
would silently drop them. The shipped corrections carry a reconstruction plan that each worker
rebuilds, byte-identical to serial with them on (`tests/test_soda2_parallel_enhancements.py`).
Refused: the UND emulation, an ad-hoc callable with no plan, `op.stuckbits`,
`op.activetimefrommissed` and more than one raw file. A first version of that refactor did drop
them -- **five tests in the 714-test SODA-2 family caught it while every byte-identity test stayed
green**, because the output was byte-identical to itself, computed without the corrections.
Byte-identity is necessary, not sufficient.

## 3. How v3.5's validation affects what you can rely on

- You can rely on: each v3.5 routine producing what v3.5 MATLAB produces, on the banked cases, and
  the whole chain matching Octave on one 2016 flight cut (three goldens).
- You cannot claim: that a v3.5 result equals any published/archived campaign product. Nobody can;
  v3.5 never wrote one. A reviewer asking "does it match the original?" gets: matches Octave running
  the original source, not a product of record.
- What would raise it: a dataset processed by real v3.5 MATLAB with its raw files. Without one,
  v3.5 is layer 2 by construction, and the package says so at the point of selection
  (`uiops.engine().validation`).
- History: the v3.1.4 translation reproduced the archived ORACLES products and is not part of this
  package. New science uses v3.5 and cites its validation as Octave-equivalence.

## 4. Enhancements on each engine

The enhancements package (`arrayprobe-uiops-enhancements`, 36 modules) corrects the defects the port
found and adds capability; v3.5 already carries the developers' own fixes for some. Which
enhancement runs on which engine is declared per module in `arrayprobe_enhancements.applicability`,
enforced when a run resolves its configuration, and rendered at
`docs/23-enhancements-by-engine.md` (generated by the documentation build). All 42 were written against the earlier v3.1.4 translation (not shipped);
**34 apply on v3.5**. The eight that do not fall into two sets:

- **Superseded upstream (4)** — `wide_hollow_fix`, `int16_double_fix`, `conc_arear_fix`,
  `reshape_fix`. The UIOOPS developers fixed these in v3.5, so applying the correction
  there would double-correct; `resolve()` leaves them off on v3.5 and raises if a config file
  names one.
- **Variant-only (4)** — `diode_range_fix`, `intarr_threshold_fix`, `zero_image_recovery` and
  `mask_presence_fix`, which correct four upstream findings: the image-widening diode number, the
  global-minimum inter-arrival threshold, the abandoned zero-image record and the silent missing
  mask file. The construct they correct exists only in the ORACLES
  production fork, in no stock release; absent from v3.5 rather than fixed in it.

A third state, *unestablished* ("not yet read against v3.5" — refused, and **not** the same as
fixed), is empty: every row the classifier could not locate was read
directly against the vendored v3.5 tree.

**Stray-pixel correction (engine 3.5, on by default).** UIOOPS sizes an image as a whole, so one real particle plus a few far-off stray pixels is sized as a much larger particle. Every `--engine 3.5` run removes pixel groups of at most 2 pixels lying more than 8 empty diodes from a single main piece of at least 9 pixels, then sizes and tests the main piece alone; each image's removed count is written to `image_stray_pixels_removed`. The earlier v3.1.4 translation (not shipped), which reproduced the archived record, never applied it. Turn it off with `--stray-pixel off` or `[enhancements] stray_pixel_fix = false` (the command line wins); the `.call` stamp records `stray_pixel=on:g8,n2,m9` or `stray_pixel=off`. Worked examples: `examples/5_data_quality/04_stray_pixel_images.ipynb`.

**2D-S bin-table correction (engine 3.5, on by default).** For a 2D-S whose project name falls to v3.5's `otherwise` branch, two swapped comment markers in `sizeDist.m:497-507` size it on the HVPS bin table. An `--engine 3.5` run sizes such a 2D-S on the 2D-S 128-bin ladder instead (probe case `v35-2ds-ladder-fix`) and logs that it did; a run naming `--probe-case` keeps that case. Turn it off with `--protective off` or `[enhancements] bin_table_fix = false`; the earlier v3.1.4 translation (not shipped) never applied it; engine 3.5 fixes upstream defects that destroy data rather than reproducing them.

**Particle-clock correction (engine 3.5, on by default).** A probetype-1 (CIP/PIP) campaign outside UIOOPS's hard-coded clock-offset table matches particles to TAS seconds on the wrong clock, so S4 dies or writes an empty product. An `--engine 3.5` run derives the offset as the mode of `Time - particle_time`, applies it only when at least 99 % of particles sit within one second of that mode and land on the TAS axis once shifted, and otherwise refuses as before; the sd `.call` stamp records `particle_clock_fix=<+N>s`. A proc already on the axis is untouched and its stamp unchanged. `--protective off` keeps the refusal, as did the earlier v3.1.4 translation (not shipped); engine 3.5 fixes upstream defects that destroy data rather than reproducing them.

**Zero-sample-volume and time-grid corrections (engine 3.5, on by default).** On a 2D-S/HVPS (probetype 2) probe, sizeDist caps a second's summed overload dead time at exactly 1 s, which makes that second's live time and sample volume zero, so its concentrations are written unflagged as `Inf` in occupied bins and `NaN` in empty ones. Separately, two records floored to the same whole second put that second twice in the 1 Hz grid; the first copy spans an empty interval, the pairing with particle blocks shifts by one, and that second's particles are counted nowhere (the upstream finding of the duplicate TAS-second particle loss). An `--engine 3.5` run writes every non-positive-volume second as `NaN` (the sample volume itself unchanged) and moves a duplicated second into the skipped second beside it, leaving a duplicate with no one-second hole beside it as it is; the sd `.call` stamp carries `time_sv_fix=on` with the counts `zero_sv_seconds`, `time_grid_fix` and `time_grid_unresolved`. A stamp made with the corrections refuses an input made without them and the reverse; a v3.5 stamp with no marker reads as `time_sv_fix=off`. `--protective off` gives the stock call, and the earlier v3.1.4 translation (not shipped) never applied them; engine 3.5 fixes upstream defects that destroy data rather than reproducing them.

**Running them.** `arrayprobe-enhanced run <config.toml> <raw> [--engine 3.5]` (`--engine`, if given, must match `[run].engine` in the config)
(`arrayprobe_enhancements.pipeline`) runs the selected engine in a subprocess, resolves the
enhancement set for that engine, applies the ones that have a driver adapter (13 of 42 today:
`hole_edge_swap`, `particle_number_all_fix`, `particle_time_glitch_fix`, `int_arr_rollback_fix`, `particle_time_int8_fix`,
`outoffocus`, `overload_accounting_fix`, `published_dof`, `pressure_units_fix`, `arco_export`, `arm_export`, `cf_export`, `field2006_shatter` —
`pipeline._APPLIERS`; every registry row, `published_dof` included, is ON by default)
onto copies named `<stem>.enh.<kind>.nc`, and writes a `<sd>.enhancements.json` sidecar recording,
per module, whether it resolved on, was applied, or was skipped and why. The port's own output is
never touched.

**What has been measured on v3.5, and what that is.** On the tracked dense demo reference
(`demo_flight_dense_raw.2DS`, 240 particles, `sd.count.sum()` 74; `enhancements_uiops/tools/v35_ab_summary.py`,
`enhancements_uiops/docs/measurements.json` `v35_*` keys): `hole_edge_swap` swaps 40 of 240;
`arco_export` 199,812 → 87,710 bytes (0.439). `outoffocus` **changes no diameter on this
reference under its corrected (default) direction**. Retracted: an earlier "40 of 240 (median
`size_factor` 1.897)" was measured with the module multiplying by `size_factor` where Korolev
(2007) divides, undoing v3.5's own division on exactly the 40 particles v3.5 had corrected; the
`"korolev"` direction leaves those 40 as v3.5 wrote them (`enhancements_uiops/docs/CORRECTIONS.md`, part `outoffocus.py`, section *The direction*). With
`area_mode="sphere"` the adapter still recomputes area for those 40 particles. Five adapters are
vacuous on that input for stated reasons (no midnight crossing; probetype 2 unaffected, twice;
pressure not in the `.call` stamp; `sd` lacks `sum_IntArr`/`sample_vol`). **This is an A/B on a
demo file, not validation**: no enhancement is "validated on v3.5", because v3.5 has no product of
record to validate against (§1). Each module without a v3.5 A/B says so in
`enhancements_uiops/docs/applicability_matrix.md`'s fifth column.

## 5. Which probes each package reads, processes and has validated

Measured from the readers, the probetype dispatch and the tests;
paths relative to the repository root. "Validated" means checked against an archived raw+product
pair -- an Octave/GDL oracle over synthetic or bare raw records is "oracle only", and a refusal
is a refusal. The v3.1.4 engine's probetype dispatch (in its image processing, not part of this package) is
keyed on the timing family (`spec` / `dmt` / `pms` / `fast2dc`); the per-probe record width is the
configuration table `src/arrayprobe_uiops/constants.py:191-222`.

The v3.1.4 column describes the v3.1.4 engine, not included in this release; its
source line references are not reproduced here because this package does not ship it.

| Probe (probetype) | `arrayprobe` (v3.1.4) | `arrayprobe_uiops` | `arrayprobe_soda2` |
|---|---|---|---|
| 2D-S (2) | reads (the v3.1.4 engine's SPEC reader), processes, **validated**: 2016 6 of 6 flights, 2017 8 of 9 exact | reads (`spec.py:528`), processes; **oracle only** -- no archived product was written by v3.5 (`spec.py:13-15`) | reads (`read2dbuffer.py:73`, SPEC only), processes; no reference `.dat` held |
| HVPS (2) | reads (the v3.1.4 engine's SPEC reader), processes; **compared, not reproduced** -- over-counts against the archive | as 2D-S: oracle only | reads and processes (HVPS3; `processbuffer_spec.py:297`); compared field by field with UND's SODA-2 `.dat` for two flights (pointer set and sample area exact, every other field given a verdict, the unexplained ones named); HVPS4/3VCPI subformats refused (`processbuffer_spec.py:213-217`) |
| CIP (1) | reads (`readers/dmt.py:243`, `readers/sea.py:159`), processes (its image processing, its size distribution); **oracle only** (`tests/test_dmt.py`, `test_sizedist_s7b_oracle.py`, shipped synthetic PIP/CIP fixtures, no archived product) | **imgProc and sizeDist yes**: imgProc (V-PT) runs under `TEST`, `PECAN` and `GCPEx`, including v3.5's own offset table (`imgProc_sm.m:976-1093`, four dated cases); **oracle only** -- no archived product was written by v3.5. sizeDist ported (five cited sites, the live-time tail Octave-goldened; no whole-file probetype-1 differential yet) | **refused** -- non-SPEC formats are out of scope (`read2dbuffer.py:73-76`) |
| PIP (1) | reads (shared DMT path), processes (its image processing); no PIP-specific test | imgProc yes (`TEST` and `PECAN` cases), sizeDist yes (the probetype-1 path CIP takes); oracle only | refused |
| 2DC (0) | reads (`readers/pms.py:151`, `readers/sea.py:267`), processes (its image processing, its size distribution); **oracle only, synthetic** -- a real 1995 ACE-1 2DC/2DP RAF file is held locally, but only its reader has been checked (30 of 30 variables equal to Octave, the ACE-1 reader check); imgProc and sizeDist have not been run on it in a validated way (stated in the header of the v3.1.4 engine's image-processing module, not included in this release) | imgProc and sizeDist yes (`tests/test_v35_sizedist_probetype03.py`). Oracle only and **synthetic** -- UIOOPS frames no particle on the ACE-1 file's NCAR timing words, and no archived UIOOPS product exists for it; checked twice, against `v35_probetype013_oracle.json` and the independent pair built for the upstream finding of the int8 particle-time collapse (`tests/test_v35_2dc_octave_oracle.py`). `ds` is 0.03 here, not v3.1.4's 0.025 (`imgProc_sm.m:141`) | refused |
| 2DP (0) | reads (`readers/pms.py:194`); `sizeDist` dies at `tasMax` by design (its size distribution); one synthetic record tested (`tests/test_pms.py`); the ACE-1 file's P1 (200 um) stream is read in the ACE-1 reader check, nothing downstream run | imgProc yes by construction -- same probetype-0 path as 2DC, but **no 2DP-specific v3.5 case was run**; sizeDist takes the 2DC path (no 2DP case run) | refused |
| Fast2DC (3) | reads (`readers/pms.py:184-189`), processes (its image processing); `sizeDist` from the stock tree only (its size distribution); oracle only, synthetic (the v3.1.4 Fast2DC image-processing and size-distribution oracle tests, not included in this release) | imgProc yes (two cases, `iNewHabit` 0 and 1), sizeDist yes (`SOCRATES`/`Fast2DC` and catch-all `F2DC`); oracle only, synthetic | RAF reader and Fast-2DC_v2 buffer processing (`processbuffer_f2dc.py`) ported and wired into the serial driver; SODA-2's own IDL run under GDL: 10 synthetic buffers exact (the SODA-2 Fast-2DC GDL golden test, not included in this release), and one real file (CAESAR 2024 rf05, probe C4, 35480-35540 s) identical in all eight output fields (`tests/test_soda2_raf_realfile_gdl.py`); no product of record held. Plain 2DC/2DP over RAF refused by name |

**Run-capability and validation depth are different axes, and this table crosses them.** Every
probe UIOOPS v3.5 supports *runs* through `arrayprobe_uiops`'s imgProc stage, asserted bit-for-bit
against the vendored MATLAB. None is *validated* in the layer-1 sense, and none can be: no archived
product was ever written by v3.5. The only cell that reproduced an archived product was the
v3.1.4 engine on the 2D-S, as internal validation during development; that engine is not part of
this package. Its non-SPEC probes were reachable and oracle-checked but never met a real
raw+product pair.

**Other campaigns.** Real 2DC/2DP (ACE-1, 1995) and Fast-2DC (CAESAR 2024) raw files are held, but UIOOPS
has not been run on either in a validated way and no product of record is held for any, so the UIOOPS
cells of those rows are checked only against Octave on synthetic input.

## Where this comes from

`STOCK_V35`'s field-by-field provenance and its Octave cross-check:
`arrayprobe_uiops.profile.STOCK_V35_PROVENANCE`, `tests/test_stock_v35_profile.py`. The version-selector mechanics (`uiops.engine()`, `uiops.CATALOGUE`,
what each classification state means): `src/uiops/__init__.py`, `tests/test_uiops_selector.py`.
