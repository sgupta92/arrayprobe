# SODA-2 enhancement backlog: status

Cite SODA-2 as: Aaron Bansemer. (2026). abansemer/soda2: v2.26.0 (Version v2.26.0) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.18331418

Tier A of the 2026-09-14 triage -- 20 findings,
18 correction modules plus one diagnostics-only module. One row per candidate; "planned" until a
module ships, then updated with its finding, its test module and its reachability.

| Module (config key) | Finding(s) | Port module | Reachability | Status |
|---|---|---|---|---|
| `aspr_nan_fix` | the non-finite aspect-ratio collapse | `aspect_ratio.py:105` | live | shipped, `tests/test_aspr_nan_fix.py` |
| `den_clamp_fix` | the misplaced den clamp | `aspect_ratio.py:66` | live | shipped, `tests/test_den_clamp_fix.py` |
| `rollover_modulus_fix` | the short 2D-S rollover constant | `processbuffer_spec.py:301` | live | shipped, `tests/test_rollover_modulus_fix.py` |
| `zero_area_return_fix` | the zero-area default measurements | `findsize.py` | flagged | shipped, `tests/test_zero_area_return_fix.py` |
| `last_buffer_index_fix` | the unindexed last buffer | `spec_index.py` | live | shipped, `tests/test_last_buffer_index_fix.py` |
| `same_time_buffer_fix` | the previous-buffer first-particle time | `processbuffer_spec.py` | live | shipped, `tests/test_same_time_buffer_fix.py` |
| `poisson_fill_guard` | the fill-area Poisson error | `poisson_spot_correct.py` | live | shipped, changes no written value -- see note below, `tests/test_poisson_fill_guard.py`; measured on real data 2026-09-15: UND 0914 HVPS-3, 600 s window, 191 particles reached `poisson_spot_correct` (190 degenerate, 1 not), all 32 `ProcessData` fields identical OFF vs ON -- `CORRECTIONS.md` |
| `fillholes_int_labels` | the modulo-256 fillholes labels | `fillholes.py` | latent | shipped, `tests/test_fillholes_int_labels.py` |
| `label_blobs_int_count` | the wrapping label_blobs count | `label_blobs.py` | latent | shipped, `tests/test_label_blobs_int_count.py` |
| `dilation_clamp_fix` | the misclamped dilation kernel | `label_blobs.py` | live | shipped, `tests/test_dilation_clamp_fix.py` |
| `blank_roi_dof_fix` | the accepted blank ROI | `binary_dof.py` | flagged | shipped, `tests/test_blank_roi_dof_fix.py` |
| `no_stuck_diode_fix` | the wide-probe stuck-diode index + the stuckbits column corruption | `fixstuckbits.py` | live | shipped, `tests/test_no_stuck_diode_fix.py` |
| `empty_roi_diodegaps_fix` | the empty-ROI diodegaps sentinel | `processbuffer_tail.py` | flagged | shipped, `tests/test_empty_roi_diodegaps_fix.py` |
| `rejection_tally_fix` | the uncounted depth-of-field rejects + the first-reason-only reject count | `particlesort.py` | live | shipped, `tests/test_rejection_tally_fix.py` |
| `hk_probeid_columns` | the horizontal-default HK columns | `process_hk.py` | flagged | shipped, `tests/test_hk_probeid_columns.py` |
| `pbp_inttime_consistent` | the two inttime values | `pbp_writer.py` (CSV) | live | shipped, `tests/test_pbp_inttime_consistent.py` |
| `pbp_rejectionflag_ubyte` | the signed rejectionflag byte | `pbp_writer.py` (netCDF) | live | shipped, `tests/test_pbp_rejectionflag_ubyte.py` |
| `run_diagnostics` | the uncounted dropped frames, the silently dropped last-record particle, the date-offset empty run, the silent memory-flush discard | `process_2d.py` | flagged | shipped for all four, `tests/test_run_diagnostics.py` -- see note below |
| `double_pi_fix` | the single-precision pi corner count | `min_circle_fast.py` | live | shipped, opt-in -- see note below, `tests/test_double_pi_fix.py` |

The 14 findings that need a design decision or a measurement first are recorded, each row with
what unblocks it, in `docs/DEFERRED.md`. The 36 that are documentation-only, IDL-only or
unreachable are not tracked here.

## `aspr_nan_fix` + `den_clamp_fix` on real 2D-S data: not a null, and not on `conc1d` either

The question, on seeing the whole enhancement set produce an apparently unchanged
2D-S 1 Hz product: *"if soda2 on and off provide no changes, what was the impact or need
of the enhancement... which is it"* Measured 2026-09-16
(every field compared on and off): of 35 numeric `.dat` fields, 33 are
byte-identical on and off; **`SPEC2D_ASPR`** and **`HIST3D`** differ, both aspect-ratio-derived --
the same two fields, same direction, as the ORACLES four-way. Per particle,
from the two `.pbp.nc` files (490,291 particles, all 38 variables swept): **`aspectratio` differs
in 114,379 (23.3%)**, almost entirely `den_clamp_fix` correcting an inflated divisor
(`aspect_ratio.pro:66`) upward -- a systematic ~16% understatement of `aspr` otherwise (measured
case, `docs/CORRECTIONS.md`'s `den_clamp_fix` section).

**The size distribution (`conc1d`) is genuinely unaffected** -- aspect ratio is not one of its
inputs, which is why the original three-field comparison (`conc1d`/`activetime`/`count_accepted`
only) looked like a total null and was not. **Anyone histogramming aspect ratio for habit or
ice/water-phase work on a SODA-2 run needs `den_clamp_fix` on** (opt-in): the effect is
not a degenerate-input edge case, it fires on ordinary 2D-S particles. Nine of the fourteen
correction modules checked this way *are* correctly inert on this file -- their preconditions
(a zero-area ROI, >255 regions, a DOF-reject flag, `stuckbits` on, an unrecognised `probeid`) never
occur in this file -- which is itself a result about this file, not evidence the corrections do
nothing.

## Applied by `arrayprobe soda2 run`: the driver adapter

`registry.apply(resolved)` routes every resolved-ON correction it can through
`arrayprobe_soda2.enhancement_hooks` (a port-side table of twelve module-global bindings the
driver already reads) for the duration of the `soda2_process_2d` call. **14 of 19 are applied**;
five are not, each for a recorded reason (`_adapter.NOT_ROUTED`; `tests/test_adapter.py` checks
routed + not-routed partition the registry):

| Not applied through the driver | Why |
|---|---|
| `rollover_modulus_fix` | inline arithmetic in `process_spec_buffer` (`processbuffer_spec.py:305`); no function boundary |
| `empty_roi_diodegaps_fix` | inline arithmetic in `process_buffer_tail` (`processbuffer_tail.py:283`); no function boundary |
| `pbp_inttime_consistent` | its writer needs `interarrival`, which the driver's `write_pbp_csv_buffer` call (`process_2d.py:389`) does not pass |
| `rejection_tally_fix` | returns a separate corrected tally beside the port's; substitutes no driver call |
| `run_diagnostics` | a diagnostic; changes no output |

Two pairs share a binding and are composed, not stacked: `aspr_nan_fix` + `den_clamp_fix`
(`axis_and_ratio`), `label_blobs_int_count` + `dilation_clamp_fix` (`label_blobs`);
`double_pi_fix` (`aspect_ratio`) reads `axis_and_ratio` through the port module at call time so
it composes with the first pair. Measured on the tracked frame fixture: every correction OFF is
byte-identical to the port (`.pbp.csv` minus its wall-clock line, every `.pbp.nc` variable and
dtype, every `ProcessData` field); `pbp_rejectionflag_ubyte` alone changes exactly the written
`rejectionflag` dtype (`int8` -> `uint8`); the full all-ON table runs and leaves every
binding pristine.

## `poisson_fill_guard` (the fill-area Poisson error) shipped -- a correction that changes no written value

Decided by the SODA-2 port plan: ship, with an equivalence test that documents the no-input
case. `tests/test_poisson_fill_guard.py` sweeps every integer area pair 0-120 and the GDL bank's
degenerate cases: `correction` and `zd` equal the port's everywhere. The only difference is the
route -- the port-tooling `PoissonCorrection.ip` is `-1` (branch at `:26` not taken) instead of
`0` (taken, clamped), and no `0/0` or negative square root is evaluated. The driver reads only
`correction` and `zd` (`processbuffer_tail.py:290-291`), so applying it is byte-identical by
construction. Registered opt-in (`default_on=False`) as is every
SODA-2 correction except the protective set (`registry.PROTECTIVE`);
it had been default ON under the earlier every-correction-on ruling. The stage-3 deferral note it supersedes follows, kept because its
analysis is what the equivalence test proves:

Checked directly against `poisson_spot_correct.py:169-174` before writing anything: for
**every** input the guard's suggested edit (`img_fill gt img_orig` / `img_fill gt 0`) would
route around, the port's *existing* NaN/clamp path already lands on the identical output the
guard would produce by construction -- `ratio` non-finite -> `where(...)` empty -> `ip`
clamped to `0` -> `(correction, zd) = (DEDGE_D0[0], ZEED[0]) = (1.0, 0.0)`, which is exactly
`poisson_spot_correct`'s own no-spot default (`:24-25`). The upstream finding says this
plainly ("the exact values it would return for a particle with no spot at all, arrived at by a
different route"). So there is no input on which an opt-in guard would change `sizecorrection`
or `zd` -- the doctrine's required A/B-consequence test ("ON changes exactly what the finding
says, on an input that exercises it") cannot be written honestly for this finding as stated,
because the finding itself establishes there is no output difference to demonstrate. Shipping a
module here would mean either a test that asserts nothing changes (failing the doctrine's own
requirement) or a test disguising that fact. Left open whether
this belongs in Tier A at all, or moves to the "turned out fine" register alongside
the findings that turned out to be fine.

## `run_diagnostics` covers the uncounted dropped frames + the silently dropped last-record particle only, stage 6 -- the date-offset empty run/the silent memory-flush discard deferred, scope not defect

The plan groups four findings (the uncounted dropped frames, the silently dropped last-record particle, the date-offset empty run, the silent memory-flush discard) under one config key: "One module,
returns a diagnostics dict beside `ProcessData`". The uncounted dropped frames (`soda2_processbuffer.pro:296`/`:339`,
dropped frames/buffers) and the silently dropped last-record particle (`soda2_particlesort.pro:79-81`, a particle dropped at
`itime==numrecords`) each wrap one already-ported function (`process_spec_buffer`,
`soda2_particlesort`) and ship this stage, each with its own honest equivalence and
A/B-consequence proof (`tests/test_run_diagnostics.py`).

## `double_pi_fix` (the single-precision pi corner count) shipped, opt-in

Plan section 2.4 wrote the decision in advance: default ON iff the population-3 (whole-driver)
changed-particle fraction `f` is 0 on both tracked fixtures *and* the min_circle_fast bank shows
only corner-count changes with `|Δdiam| <= 1e-9` relative; default OFF iff `f > 0` with `m >=
1e-6` or `|Δorientation| >= 0.01°`; undecided only for `f > 0` with `m < 1e-6`.

**Measured** (`enhancements_soda2/tools/double_pi_ab.py`), at both an equal (`yres == xres`,
the base op) and an unequal (`stretchcorrect=1, fixedtas=120.0`, tas_adjust measured at 2.4 and
0.93 respectively -- confirmed genuinely non-unit, not a no-op override) resolution ratio, per
the plan's own top-ranked uncertainty (the changed fraction might be governed by
`findsize.py:247`'s float32 `tas_adjust` path rather than by which branch `min_circle_fast`
takes):

| Fixture | yres:xres | n particles | n changed | max &#124;Δaspr&#124; | max &#124;Δorientation&#124; |
|---|---|---|---|---|---|
| S2 (`s2_spec_raw_fixture`) | equal (1.0) | 1 | 0 | 0.0 | 0.0 |
| S2 | unequal (2.4) | 1 | 0 | 0.0 | 0.0 |
| frame (`soda2_spec_frame_fixture`) | equal (1.0) | 13 | 0 | 0.0 | 0.0 |
| frame | unequal (0.93) | 13 | 0 | 0.0 | 0.0 |

`f == 0` on all four runs (28 pooled real particles, 0 changed). The 20-case
`min_circle_fast` bank: 4 cases change corner **count** (`block_5x3`, `disc_outline_r12`,
`rect_tas_1p037`, `L_shape`), `diam` agreeing to `1.2176439171466038e-16` relative in the worst
case -- well inside `1e-9`. Two more cases (`rect_4`, `outline_20x8`, both on the port's own
`:107` "rectangle-like" list) keep the same corner count and the same `diam` but land on a
different P/Q/R identity/order -- the mid-loop obtuse-angle tests (`:37`/`:41`) reroute the walk
even when the final branch is unchanged; this doesn't threaten the criterion (`diam` still
agrees), but it means "only corner-count changes" undersells what actually differs on the bank.

**Mechanically, this lands in the Default-ON branch** -- even though the plan itself flagged
that outcome as unlikely ("every axis-aligned block is rectangle-like"). By default it is
registered `default_on=False`: a measured no-op is not a data-destroying
defect, so it is not in `registry.PROTECTIVE`.

**Caveat, stated plainly rather than left implicit**: 28 particles across two small tracked
fixtures is a thin sample. `f == 0` here is not evidence that no real ORACLES particle ever has
an exact right angle at min_circle_fast's R vertex -- it says the two tracked fixtures happen
not to contain one at either resolution ratio tested. A future stage with access to a longer,
denser real flight file could re-run `double_pi_ab.py` and revisit the default if `f` turns out
to be nonzero there.

**the date-offset empty run** (a probe-reported date substituting `startdate`) and **the silent memory-flush discard** (a memory-limit flush
that can discard an in-progress record) both live inside `soda2_process_2d.pro`'s ~550-line
driver (`process_2d.py`), which this stage's ~25-minute time box does not reach -- unlike
`poisson_fill_guard` above, this is **not** a "no honest A/B test is possible" case: both
findings are concrete, reachable defects with a clear suggested edit, and a driver-level wrapper
analogous to this stage's other two functions would let an A/B proof be written the same way.
Left for a later stage (or a dedicated pass, given the driver's size) rather than shipped
with a rushed or shallow proof.

## `run_diagnostics` -- the date-offset empty run/the silent memory-flush discard shipped, stage 8b (supersedes the stage 6 `run_diagnostics` note above)

`driver_date_diagnostics(op) -> dict` (the date-offset empty run) and `run_with_return_diagnostics(op, **kw) ->
tuple[ProcessData | None, dict]` (the silent memory-flush discard) reach both findings **without modifying the port**, by
wrapping `arrayprobe_soda2.process_2d.soda2_process_2d` and, only where needed, re-running the
driver's own preamble (`update_op` -> `buildindex` -> the date check -> the window arithmetic,
`process_2d.py:404-548`) on the side -- the same approach the note above anticipated. Neither
function calls the driver's per-buffer loop a second time, mutates its accumulator, or changes
what `soda2_process_2d` itself returns.

- `driver_date_diagnostics` reports `{"requested_julday", "file_julday", "branch":
  "within_5_days"|"substituted", "startdate_used"}` -- equivalence on `soda2_spec_frame_fixture`
  (`within_5_days`, `startdate_used == requested_julday`); A/B on `TraceLine410DateMismatch`'s own
  ops (`test_soda2_process_2d.py:176`): `date_off10` (`date="20160827"`) reports `substituted`
  while the port still returns a `ProcessData` identical to `s2_full`'s; `date_off1`
  (`date="20160905"`) reports `within_5_days` while the port returns `None` -- the exact
  "silently-empty vs silently-correct" pair the finding describes, distinguished
  before the fact.
- `run_with_return_diagnostics` reports `{"returned": bool, "none_reason": None|
  "no_buffers_in_window"|"flush_left_nothing"}` -- equivalence on `s2_full` (`returned=True`,
  `none_reason=None`, primary return value field-for-field equal to the direct `soda2_process_2d`
  call); A/B on `DriverRunsEndToEndOnTrackedFixtures`'s own `window_empty` op
  (`test_soda2_process_2d.py:138`, `:550-551`) reporting `no_buffers_in_window`, and
  the measured `frame_full` + `num2process=6` case (`:632-636`, the unclosed PBP files)
  reporting `flush_left_nothing`.
- **Cannot be done without modifying the port** (as the note above anticipated): attributing a
  `flush_left_nothing` return to a *specific* buffer, or reporting the count of particles already
  flushed to disk before it -- both require the driver's own loop locals (`istop`, the per-buffer
  index), which are not visible from outside `soda2_process_2d`.

Tests: `tests/test_run_diagnostics.py::DriverDateEquivalence`, `::DriverDateAB`,
`::DriverReturnEquivalence`, `::DriverReturnAB` (6 tests). Full `enhancements_soda2` suite: 97
tests, OK (up from 91).
