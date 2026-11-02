# The corrections -- one design record per module

Same structure as `enhancements_uiops/docs/CORRECTIONS.md`: one section per shipped module, each
naming the finding it corrects, the port line it wraps or re-derives, its
equivalence proof (OFF reproduces the port bit for bit) and its A/B-consequence proof (ON
changes exactly what the finding describes, on an input that exercises it).

---

# `aspr_nan_fix.py`

**Finding**: the non-finite aspect-ratio collapse, `aspect_ratio.pro:105`. `return, aspr < 1.0` is IDL's MIN, and for a
non-finite `aspr` it returns the *other*, finite operand -- measured under GDL,
`!values.d_nan < 1.0d` is `1.0`. `aspect_ratio.py`'s `axis_and_ratio` faithfully reproduces
this, so a circle-fit that never converged is silently indistinguishable from a genuinely
round particle.

**Correction**: `aspr_nan_fix.corrected_aspr` re-derives `axis_and_ratio` (via the shared
`_aspect_ratio_recompute.recompute`) and returns NaN instead of 1.0 when the pre-clamp `aspr`
is non-finite.

**Equivalence** (`tests/test_aspr_nan_fix.py::Equivalence`): on golden case
`den_clamp_bites_tas025_float` (a genuinely finite `aspr`), `corrected_aspr` matches the real
`arrayprobe_soda2.aspect_ratio.axis_and_ratio` bit for bit.

**A/B consequence** (`::ABConsequence`): a synthetic circle with `diam=NaN` drives the port's
own `axis_and_ratio` to `aspr == 1.0` (matching
`test_soda2_aspect_ratio.py::TheMinMaxOperatorsAreClamps::
test_a_nonfinite_diameter_clamps_to_one_with_no_warning`); `corrected_aspr` returns NaN on the
same input.

**Switch states** (`::SwitchStates`): registered `default_on=False` (opt-in), `finding="S2-d"`,
`reachability="live"`; `resolve({})["aspr_nan_fix"]` is `True`,
`resolve({"aspr_nan_fix": False})["aspr_nan_fix"]` is `False`.

---

# `den_clamp_fix.py`

**Finding**: the misplaced den clamp, `aspect_ratio.pro:66`. `den = sqrt(a^2+b^2) > 1` is IDL's MAX, written to
guard the single-point-outline 0/0 at `:68`. It also fires for any real 3-point circle whose
radius is merely below one pixel (reachable when `yres < xres`), inflating the divisor and
understating `aspr` with no warning.

**Correction**: `den_clamp_fix.corrected_aspr` clamps `den` to 1 only when it is exactly 0,
never merely `< 1`.

**Equivalence** (`tests/test_den_clamp_fix.py::Equivalence`): on golden case
`two_slice_tas0p1_float` (`den` already `> 1` unclamped), `corrected_aspr` matches the real
`axis_and_ratio` bit for bit.

**A/B consequence** (`::ABConsequence`): on `den_clamp_bites_tas025_float` (the finding's own case), the port's own `axis_and_ratio` returns `ASPR =
0.6136363636363636`; `corrected_aspr` recovers `0.7272727272727273`, matching the golden's own
`den_unclamped_tas025_float.ASPR_UNCLAMPED` -- a 16% understatement corrected.

**Switch states** (`::SwitchStates`): registered `default_on=False` (opt-in), `finding="S2-f"`,
`reachability="live"`; both `resolve()` states checked.

---

# `rollover_modulus_fix.py`

**Finding**: the short 2D-S rollover constant, `soda2_processbuffer.pro:318` (ported at `processbuffer_spec.py:301`). The
non-HVPS3 SPEC branch's rollover constant is `4294967295.` (2**32 - 1), one tick short of the
true 32-bit modulus (2**32) the slice counter actually wraps at.

**Correction**: `rollover_modulus_fix.corrected_inttime` re-derives `inttime` from
`SpecBufferParticles.rawtime`/`.clocktas` (already exactly `x.time`/`hk.tas` per kept frame
for every non-HVPS3 probe) plus `op.probetype`/`op.yres` and the caller's own starting
`lastclock`, reusing the port's own `_freq` helper, with `rollover_constant` defaulting to
`ROLLOVER_FIXED = 4294967296.0`. Raises on `probetype == "HVPS3"` -- that branch's `xtime` is
`x.timetrunc`, not carried in the port's return value, so it cannot be recomputed from
`rawtime` alone (and the short 2D-S rollover constant is about the other branch's constant regardless).

**Equivalence** (`tests/test_rollover_modulus_fix.py::Equivalence`): on the tracked
`s2_spec_raw_fixture`'s `s2_h_baseline` case (`lastclock=0.0`, no wrap reachable),
`corrected_inttime(..., rollover_constant=4294967295.0)` -- the port's own literal --
reproduces the real `process_spec_buffer`'s `inttime` bit for bit.

**A/B consequence** (`::ABConsequence`): on `s2_rollover`, the finding's own
measured wrap case (`lastclock=70000.0`), the corrected constant changes `inttime` on exactly
the frame(s) where `xtime < lastclock` fires, and the change on each such frame equals exactly
`1.0 * freq` for that frame (the one-tick difference between the two constants) -- every other
frame is unchanged.

**Switch states** (`::SwitchStates`): registered `default_on=False` (opt-in), `finding="S4-n"`,
`reachability="live"`; both `resolve()` states checked.

---

# `label_blobs_int_count.py`

**Finding**: the wrapping label_blobs count, `label_blobs.pro:29`. The default (non-`/integer`) return path casts the
label array to BYTE, wrapping modulo 256 -- blob 256 becomes background (label 0), blob 257
aliases blob 1.

**Correction**: `label_blobs_int_count.corrected_label_blobs` is a thin wrapper calling the
port's own `arrayprobe_soda2.label_blobs.label_blobs(..., integer=True)` -- a keyword the port
already implements; nothing is re-derived.

**Equivalence** (`tests/test_label_blobs_int_count.py::Equivalence`): on a 25-isolated-blob
synthetic image (below the wrap boundary), `corrected_label_blobs(...).astype(uint8)` matches
the port's own default byte output exactly.

**A/B consequence** (`::ABConsequence`): on a 400-isolated-blob synthetic image, exactly one
pixel (the one carrying raster label 256) wraps to byte 0 under the port's default return and
is recovered (label 256, `uint32`) under the correction.

**Switch states**: registered `default_on=False` (opt-in), `finding="S4-y"`, `reachability="latent"`.

---

# `dilation_clamp_fix.py`

**Finding**: the misclamped dilation kernel, `label_blobs.pro:20`. `kerneldim = (dilatelength*2+1) < (s[1]+2)` clamps
against the roi's own slice count plus 2, not the padded array it actually dilates
(`s[1]+2*pad`) -- a 1- or 2-slice roi with `dilatelength=2` (the production call) gets a
3-wide kernel instead of the intended 5-wide one, in both directions.

**Correction**: `dilation_clamp_fix.corrected_label_blobs_dilation` re-derives
`label_blobs`'s dilation branch with the clamp corrected to `s1 + 2*pad`, reusing the port's
own `_label_region`/`_dilate_square` primitives so only the kernel-size formula can differ.
Raises for `dilatelength == 0` (the port's own `label_blobs` already covers that path exactly;
nothing to correct there).

**Equivalence** (`tests/test_dilation_clamp_fix.py::Equivalence`): with slice-axis length 3
(`dilatelength=2`), neither clamp binds (`s1+2 == s1+2*pad == 5`) -- two fragments separated
by a 3-diode gap merge identically under the port's own `label_blobs` and under the
correction.

**A/B consequence** (`::ABConsequence`): the same two fragments on a slice-axis length 1
ROI -- the port's own clamp (`s1+2 == 3`) keeps them as two separate blobs; the correction's
clamp (`s1+2*pad == 5`) bridges the gap, merging them into one, matching
the finding's own measured "1-slice roi stays separate, 3-slice roi merges"
result.

**Switch states**: registered `default_on=False`, default ON through `registry.PROTECTIVE`, `finding="S4-z"`, `reachability="live"`.

---

# `fillholes_int_labels.py`

**Finding**: the modulo-256 fillholes labels, `fillholes.pro:9`. `label_blobs(img xor 1b)` is called with no keywords
(BYTE-wrapping default, the wrapping label_blobs count), and `fillholes.pro:9` casts the already-byte result to byte
again -- an ROI whose negative decomposes into more than 255 4-connected regions wraps hole
labels modulo 256, losing exactly one hole's fill.

**Correction**: `fillholes_int_labels.corrected_fillholes` re-derives `fillholes`'s
orchestration calling the port's own `label_blobs(..., integer=True)` for the intermediate
hole labelling; everything downstream (border-vector edge removal, the final `<1b` clip) is
dtype-agnostic and unchanged.

**Equivalence** (`tests/test_fillholes_int_labels.py::Equivalence`): a single interior hole
(far below the wrap boundary) fills identically under `corrected_fillholes` and the port's
own `fillholes`.

**A/B consequence** (`::ABConsequence`): a 279-isolated-interior-hole synthetic ROI (none
touching an edge, mirroring the finding's own 400-hole construction) -- the
port's own `fillholes` fills all but exactly one hole (`total_cells - 1`); the correction
fills every hole (`total_cells`).

**Switch states**: registered `default_on=False` (opt-in), `finding="S4-u"`, `reachability="latent"`.

---

# `poisson_fill_guard.py`

**Finding**: the fill-area Poisson error, `poisson_spot_correct.pro:26-28`. A zero or shrinking fill area drives
`:27` to `0/0` or the square root of a negative; `:28`'s `where`/clamp then lands on index 0,
`(correction, zd) = (1.0, 0.0)` -- the no-spot default, by a different route.

**Correction**: `poisson_fill_guard.guarded_poisson_spot_correct` guards `:26` with
`img_fill > img_orig >= 0` and `img_fill > 0` (the finding's suggested edit) and returns
`:24-25`'s defaults directly; any other input is the port's own call.

**Equivalence** (`tests/test_poisson_fill_guard.py::Equivalence`) -- the documented no-input
case: `correction` and `zd` equal the port's on every integer area pair 0-120 (14,641 pairs),
on the GDL bank's degenerate cases, and on a real spot (`ip > 0`). They cannot differ, because
the clamp's landing entry `DEDGE_D0[0], ZEED[0]` is `(1.0, 0.0)`, which the test also pins.

**A/B consequence** (`::ABConsequence`): the route only. On the three degenerate bank cases the
port-tooling `PoissonCorrection.ip` is `0` (branch taken, clamped) in the port and `-1` (not
taken) under the guard, and the guarded call evaluates no invalid arithmetic under
`np.errstate(all="raise")`. The driver reads only `correction` and `zd`
(`processbuffer_tail.py:290-291`), so this correction moves no written byte.

**Switch states**: registered `default_on=False` (opt-in),
`finding="S4-t"`, `reachability="live"`. Decided by the SODA-2 port plan, closing an earlier deferral.

**Measured on real data (2026-09-15)**: the equivalence claim above rested on a sweep
plus synthetic GDL-bank cases; this measures it on the UND 2016-09-14 HVPS-3 raw file
(`09142016_075310_HVPS3.dat`, UND's 2016 delivery in the local reference-data directory -- not shipped, aggregate
counts only), a 600 s window (`op.starttime=28390.0`, `op.stoptime=28990.0`) run through
`soda2_process_2d` twice with the real adapter path
(`arrayprobe_soda2_enhancements.registry.apply`, the same mechanism `arrayprobe soda2 run`
uses), once with every correction resolved OFF and once with only `poisson_fill_guard` resolved
ON (isolated from the other 18 registered corrections). All 32 compared `ProcessData` fields
(`time`, `count_accepted`, `spec1d`, `conc1d`, `dhist`, ... the full `soda2_und_reference.FIELD_MAP`
set) were exactly equal between the two runs -- no written value differed, confirming the
byte-identity claim on real data rather than only on the sweep and the GDL bank. Instrumenting
`poisson_spot_correct` with a counting wrapper (installed the same way, through
`enhancement_hooks.overridden`, no package source changed) over the same window: **191**
particles reached `poisson_spot_correct`, of which **190** hit the guard's degenerate condition
(`img_fill <= img_orig` or `img_fill <= 0`, so the guard would set `ip = -1`) and **1** did not
(a real spot, the port's own call, `ip > 0`). So on this window the vast majority of particles
take the no-hole path (`img_fill == img_orig`, which is degenerate under the guard's strict
`>`), and only a single particle in 600 s exercised the correction's non-degenerate branch --
consistent with holes being rare, and small enough that a longer or denser window would be
needed to see many real spots. Script: scratch, not committed (per session instructions).

---

# `no_stuck_diode_fix.py`

**Finding**: the wide-probe stuck-diode index + the stuckbits column corruption, `fixstuckbits.pro:17-20`. IDL's `where()` sentinel `-1` minus the
routine's own `pad=7` is the scalar `-8`, a valid negative index on any probe with 8+ diodes
(every SPEC probe): when no diode's histogram deviation crosses the threshold, the routine
silently zeroes and reconstructs diode column `n-8` as though it *had* been flagged, rather
than leaving `image` unchanged. Reached in production (the stuckbits column corruption) through
`soda2_processbuffer.pro:615`'s always-defined `h=sbhist` whenever `stuckbits=1`.

**Correction**: `no_stuck_diode_fix.corrected_fixstuckbits` re-derives only
`fixstuckbits.pro:8-17`'s own `where()` test (reusing the port's own `_median_filter_7`) to
decide whether any diode crosses the threshold; when none does, it returns `image` unchanged
instead of calling the port's own corrupting/halting path.

**Equivalence** (`tests/test_no_stuck_diode_fix.py::Equivalence`): on the tracked golden case
`one_stuck_interior` (a real, GDL-confirmed stuck diode), `corrected_fixstuckbits` matches the
real `arrayprobe_soda2.fixstuckbits.fixstuckbits` bit for bit.

**A/B consequence** (`::ABConsequence`): a 24-diode image with a distinctive pixel at column
`n-8` and a uniform `h` (no diode crosses the threshold) -- the port's own `fixstuckbits`
corrupts column `n-8` (measured, matching the port's own
`test_wide_image_with_no_stuck_diode_corrupts_n_minus_8`); the correction returns the image
unchanged. A 5-diode image under the same no-match condition: the port raises
`NoStuckBitsHalt`; the correction again returns the image unchanged.

**Switch states**: registered `default_on=False`, default ON through `registry.PROTECTIVE`, `finding="S4-x"`, `reachability="live"`.

---

# `blank_roi_dof_fix.py`

**Finding**: the accepted blank ROI, `binary_dof.pro:21-31`. `area = total(bitimage)` is 0.0 for an all-zero
image, matching none of the named `CASE` values (1-6) and falling to `ELSE`, where
`neighbor_count ge (area*3)` is `0 ge 0` -- true in IDL -- so a blank image is accepted as
within depth of field.

**Correction**: `blank_roi_dof_fix.corrected_binary_dof` calls the real, unmodified
`binary_dof` and overrides only `dof` to 0 when the returned `area == 0`.

**Equivalence** (`tests/test_blank_roi_dof_fix.py::Equivalence`): a single-pixel image has
`area == 1`, which the port's own `CASE` accepts unconditionally (`dof=1`) -- never the `ELSE`
branch this finding is about; `corrected_binary_dof` matches the port bit for bit.

**A/B consequence** (`::ABConsequence`): a blank (all-zero) image -- the port's own
`binary_dof` returns `dof=1` (the `ELSE` branch's `0 ge 0` acceptance); the correction returns
`dof=0`, leaving `area`/`neighbor_count` unchanged.

**Switch states**: registered `default_on=False` (opt-in), `finding="S4-v"`, `reachability="flagged"`.

---

# `empty_roi_diodegaps_fix.py`

**Finding**: the empty-ROI diodegaps sentinel, `soda2_processbuffer.pro:707-709`. On an all-zero `roihist`, `:707`'s
search for shaded diodes returns the scalar sentinel `-1` with a count of 0; `:708`'s span is then
`1`, so `:709`'s gap (span minus count) is `1`, not the `0` a caller would expect from "no shaded
diodes, so no gap". This finding lives inside `process_buffer_tail`'s per-particle loop, not
behind a callable of its own, so the correction re-derives exactly the four-line computation
rather than wrapping the whole tail.

**Correction**: `empty_roi_diodegaps_fix.corrected_diodegaps(roihist)` returns `0` when
`roihist` has no positive entry, and reproduces the port's own `xspan - nw` formula otherwise.

**Equivalence** (`tests/test_empty_roi_diodegaps_fix.py::Equivalence`): on the tracked
`s2_spec_raw_fixture`'s `s2_h_baseline` case, `roihist` rebuilt exactly as
`process_buffer_tail` builds it for particle 0 (a real, nonempty ROI) gives
`corrected_diodegaps(roihist)` equal to the real `process_buffer_tail`'s own
`diodegaps[0]`.

**A/B consequence** (`::ABConsequence`): the same fixture with particle 0's ROI artificially
blanked (the port's own `test_line_709_diodegaps_is_1_not_0_on_a_synthetic_empty_roi`
construction) -- the real `process_buffer_tail` returns `diodegaps[0] == 1`; the correction,
given the matching all-zero `roihist`, returns `0`.

**Switch states**: registered `default_on=False` (opt-in), `finding="S5-h"`, `reachability="flagged"`.

---

# `zero_area_return_fix.py`

**Finding**: the zero-area default measurements, `soda2_findsize.pro:9-13`. The predefined output structure declares
`centerin:1b`/`allin:0b`, and the zero-area early return hands it back unchanged -- an
unmeasured particle reports *centre-in true*, an assertion the routine never checked, which
then feeds `soda2_reject.pro:15`'s acceptance test.

**Correction**: `zero_area_return_fix.corrected_soda2_findsize` calls the real, unmodified
`soda2_findsize` and overrides only `centerin` to 0 when `:11-12`'s own `area_original`
(re-derived with the port's own `_idl_div`) is 0.

**Equivalence** (`tests/test_zero_area_return_fix.py::Equivalence`): a real particle
(`"..###....", "..###...."`, FLOAT resolutions) never takes the zero-area early return --
`corrected_soda2_findsize` matches the real `soda2_findsize` on every checked field.

**A/B consequence** (`::ABConsequence`): an all-zero image -- the port's own `soda2_findsize`
returns `centerin=1` (its own zero-area default measurements default); the correction returns `centerin=0`, with every
other field unchanged. A second case confirms the integer-resolution zero sizes' own reachability path (a real particle
with INTEGER resolutions, which also zeroes `area_original` via `:11`'s integer division)
triggers the same correction.

**Switch states**: registered `default_on=False` (opt-in), `finding="S3-e"`, `reachability="flagged"`.

---

# `last_buffer_index_fix.py`

**Finding**: the unindexed last buffer, `spec_index.pro:71`. `FOR i=0L, numbuffs-2` walks buffers `0..numbuffs-2`
only -- the file's final buffer is read once, as `nextbuffer` on the loop's last pass, but its
own 2048 data words are never scanned for `'2S'`/`'HK'`/`'MK'` markers, and its header's year
is never range-checked at `:72`.

**Correction**: `last_buffer_index_fix.corrected_spec_index` duplicates `spec_index`'s whole
walk (the driver-loop range being the defect itself, per the plan's named borderline case) with
the loop extended to `range(numbuffs)`, a zero-filled `nextbuffer` on the final pass (there is
nothing past the file's last buffer to read), and the `:72` year check applied to the last
buffer's header too. Every other line (the first-buffer-only pointerstart/the fragile buffer-size autodetection/the misattributed pre-housekeeping images/the unbounded maskp and hkp arrays, none corrected here) is unchanged;
`julday`, `_read_header` and `_trim` are imported from the port rather than retranscribed.
`lite=True` is refused by name -- no vendored caller uses it.

**Equivalence** (`tests/test_last_buffer_index_fix.py::Equivalence`): a minimal, self-built
two-buffer file whose last buffer is blank -- the extra scan finds nothing, so
`corrected_spec_index` matches the real `spec_index` on every field.

**A/B consequence** (`::ABConsequence`): the same construction with a real frame planted in the
last buffer -- the port's own `spec_index` never scans it (`numimages[last]=0`,
`firstp[last]=-1`); the correction recovers it (`numimages[last]=1`, the frame's particle
counter present in `particlecounter`), with buffer 0's own indexing unchanged.

**Switch states**: registered `default_on=False`, default ON through `registry.PROTECTIVE`, `finding="S4-i"`, `reachability="live"`.

---

# `same_time_buffer_fix.py`

**Finding**: the previous-buffer first-particle time, `soda2_processbuffer.pro:362-365`. When consecutive buffers carry the same
time stamp, `:363` sets the first particle's time to the previous buffer's `maxsfm` without adding its own `inttime[0]`, and
every later `time_sfm[i]` (built by repeatedly adding `inttime[i]` onto `time_sfm[i-1]`)
inherits the same shortfall.

**Correction**: `same_time_buffer_fix.corrected_process_spec_buffer` calls the real,
unmodified `process_spec_buffer` and, only when `buffer_time == misc.lastbufftime` (read
*before* the call, since the port itself overwrites that field), shifts the entire returned
`time_sfm` array by `inttime[0]` and updates `misc.maxsfm` to match -- exploiting the fact that
a uniform shift of `time_sfm[0]` reproduces the port's own cascading `:365` loop exactly,
without re-deriving it.

**Equivalence** (`tests/test_same_time_buffer_fix.py::Equivalence`): golden case
`s2_h_baseline` (`lastbufftime=0.0 != bufftime=24243.25`) never takes the `:362-365` branch --
`corrected_process_spec_buffer` matches the real `process_spec_buffer`'s `time_sfm` and
`misc.maxsfm` exactly.

**A/B consequence** (`::ABConsequence`): golden cases `s2_sametime` and
`frame_hvps3_sametime` (both `lastbufftime == bufftime`, the finding's own
measured cases) -- the port's own `time_sfm[0]` equals `maxsfm` with `inttime[0]` never added;
the correction shifts every `time_sfm[i]` by exactly `inttime[0]`, and `misc.maxsfm` with it.

**Switch states**: registered `default_on=False`, default ON through `registry.PROTECTIVE`, `finding="S4-o"`, `reachability="live"`.

---

# `rejection_tally_fix.py`

**Finding**: the uncounted depth-of-field rejects + the first-reason-only reject count, `soda2_particlesort.pro:177-178`. `ireject=where(reject and
[1,2,4,8,16,32,64])` tests only the first seven reject bits (the uncounted depth-of-field rejects: bit 128, depth-of-field,
wraps to the last of `d.count_rejected`'s 7 columns via IDL's negative-index convention), and
`d.count_rejected[itime,ireject[0]]++` counts only the lowest-numbered matching column (the first-reason-only reject count:
the line's own comment, "Increment for each reason", says every matching reason should be
counted).

**Correction**: `rejection_tally_fix.corrected_count_rejected` runs the real, unmodified
`soda2_particlesort` (which still mutates `d`'s own 7-column tally exactly as written) and
returns a **separate** `(numrecords, 8)` array built from that call's own returned
`rejectionflag`, incrementing every matching bit (1-128) at the particle's own time index --
re-derived with the identical formula and bound check `:60`/`:81` already use, never
re-deriving the accept/reject decision `soda2_reject` already made.

**Equivalence** (`tests/test_rejection_tally_fix.py::Equivalence`): golden case
`size_below_first_bin` (a single, unambiguous reject bit) -- the corrected tally's first 7
columns match `d.count_rejected` exactly, and the new 8th column is 0.

**A/B consequence** (`::ABConsequence`): golden case `multi_bit_reject` (bits 1+8,
the finding's own measured case) -- the port counts only column 0; the correction
counts both columns 0 and 3. A synthetic bit-128-only reject (`dofreject=1`, `dofflag=0`,
`soda2_reject.py:220-221`'s own rule) -- the port mistallies into column 6 (bit-64); the
correction gives it column 7 and leaves column 6 at 0.

**Switch states**: registered `default_on=False` (opt-in), `finding="S5-a"`, `reachability="live"`.

---

# `hk_probeid_columns.py`

**Finding**: the horizontal-default HK columns, `spec_process_hk.pro:84-94`. Every `probeid` other than the literal string
`'V'` -- including the default `'A0'` and any misspelling of `'V'` -- silently takes the
horizontal channel's `volts`/`counts`/`overloads`/`laservolts` columns, with no error.

**Correction**: `hk_probeid_columns.corrected_process_hk` refuses (`UnrecognizedProbeid`)
before calling the port at all when `probeid` is not one of `{'V', 'H', 'A0'}` -- the set this
project's own test bank (`test_soda2_preloop.py::test_line_84_probeid_A0_and_H_agree`) measured
as actually equivalent to the horizontal branch, never an invented list.

**Equivalence** (`tests/test_hk_probeid_columns.py::Equivalence`): `probeid='H'` and
`probeid='V'` both match the real `process_hk` exactly.

**A/B consequence** (`::ABConsequence`): `probeid='v'` (lowercase) -- measured directly that
the port's own `process_hk` gives it the identical columns as `probeid='H'`; the correction
raises instead. An unrelated string (`'XYZ'`) is refused too.

**Switch states**: registered `default_on=False` (opt-in), `finding="S5-k"`, `reachability="flagged"`.

---

# `run_diagnostics.py`

**Findings shipped**: the uncounted dropped frames (`soda2_processbuffer.pro:296`/`:339`, a dropped frame or rejected
buffer keeps no count), the silently dropped last-record particle (`soda2_particlesort.pro:79-81`, a particle whose own time
index lands exactly on `numrecords` is silently skipped), and, since **stage 8b**, the date-offset empty run and
the silent memory-flush discard (both `soda2_process_2d.pro`, the driver) -- see below. All four ship in this one module.

**Correction**: `spec_buffer_diagnostics` calls the real, unmodified `process_spec_buffer` and
returns `(result, diagnostics)`, where `diagnostics` reports `frames_in`/`frames_kept`/
`frames_dropped`/`buffer_rejected` -- `:296`'s own `continue` is the per-image loop's only
frame-skip path, so `frames_in - result.num_images` is exactly the count. `particlesort_diagnostics`
calls the real, unmodified `soda2_particlesort` (mutating `d` as always) and returns
`(rejectionflag, dropped_at_numrecords)`, re-deriving each particle's `timeindex` with the
port's own `:60` formula, never the accept/reject decision.

**Equivalence** (`tests/test_run_diagnostics.py::SpecBufferEquivalence`,
`::ParticlesortEquivalence`): both wrappers' own primary return value (`result` /
`rejectionflag`, and `d`'s own mutated fields) match the real port functions called directly,
on golden cases `s2_h_baseline` and `single_accepted`.

**A/B consequence** (`::SpecBufferABConsequence`, `::ParticlesortABConsequence`): golden case
`all_dropped` (nimages=1, REJECT=1) reports `frames_dropped=1`, `buffer_rejected=True` --
indistinguishable from `nimages0` (no input at all, correctly reported as `frames_dropped=0`)
without the diagnostic. Golden case `at_numrecords` (the silently dropped last-record particle's own named trap) reports
`dropped_at_numrecords=1` for the particle the port's own accumulator never saw.

**Switch states**: registered `default_on=False` (opt-in), `finding="S4-q"`, `reachability="flagged"`
(one `EnhancementSpec` covers all four findings -- the dataclass has one `finding` field).

## The date-offset empty run/the silent memory-flush discard (stage 8b) -- driver-level, observed without modifying the port

`driver_date_diagnostics(op) -> dict` (the date-offset empty run, `process_2d.py:528-532`) and
`run_with_return_diagnostics(op, **kw) -> tuple[ProcessData | None, dict]` (the silent memory-flush discard,
`process_2d.py:632-636`) do not call `process_spec_buffer`/`soda2_particlesort` directly; they
wrap `arrayprobe_soda2.process_2d.soda2_process_2d` itself. Both correction functions reach their
finding by re-running the driver's own preamble (`update_op` -> `buildindex` -> the date check ->
the sort/window-edge arithmetic, `process_2d.py:404-548`) a second time, on the side -- never the
per-buffer loop, never the accumulator, never the actual return value the caller receives.

- `driver_date_diagnostics` returns `{"requested_julday", "file_julday", "branch":
  "within_5_days"|"substituted", "startdate_used"}`. **Equivalence**
  (`::DriverDateEquivalence`): on `soda2_spec_frame_fixture`, `branch == "within_5_days"` and
  `startdate_used == requested_julday`. **A/B** (`::DriverDateAB`), on
  `TraceLine410DateMismatch`'s own two ops (`test_soda2_process_2d.py:176`): `date_off10`
  (`date="20160827"`) reports `"substituted"` while `soda2_process_2d` still returns a
  `ProcessData` field-for-field identical to `s2_full`'s; `date_off1` (`date="20160905"`) reports
  `"within_5_days"` while `soda2_process_2d` returns `None` -- the "silently-empty vs
  silently-correct" pair the finding names, now distinguishable before the fact.
- `run_with_return_diagnostics` returns `(result, {"returned": bool, "none_reason": None|
  "no_buffers_in_window"|"flush_left_nothing"})`. **Equivalence** (`::DriverReturnEquivalence`):
  on `s2_full`, `result` matches the direct `soda2_process_2d(op)` call field-for-field and
  `diagnostics == {"returned": True, "none_reason": None}`. **A/B** (`::DriverReturnAB`): the
  `window_empty` op (`DriverRunsEndToEndOnTrackedFixtures`, `test_soda2_process_2d.py:138`,
  `:550-551`) reports `"no_buffers_in_window"`; the measured case --
  `frame_full` with `num2process=6`, which necessarily flushes the last accepted buffer and lands
  on `:632-636` (the unclosed PBP files) before a `ProcessData` is built -- reports `"flush_left_nothing"`, and the
  same op's default-`num2process` run (sanity check) does return a `ProcessData`, confirming the
  forced-flush `None` is the silent memory-flush discard's own path, not the widened processing window's empty window.

**Cannot be observed this way** (recorded in the module docstring too): attributing a
`"flush_left_nothing"` return to a *specific* buffer, or reporting how many particles were
already flushed to disk before it -- both require the driver's own loop locals (`istop`, the
per-buffer index `i`), invisible from outside `soda2_process_2d`. The finding's own
suggested edit asks only that the two `None` sites be distinguished, which the function
above does.

Tests: `tests/test_run_diagnostics.py::DriverDateEquivalence`, `::DriverDateAB`,
`::DriverReturnEquivalence`, `::DriverReturnAB` (6 tests, all against the real, unmodified
`soda2_process_2d`).

---

# `pbp_inttime_consistent.py`

**Finding**: the two inttime values, `soda2_particlesort.pro:198` vs `:279-298`. The netCDF writer's `inttime`
variable is populated from `interarrival[0:istop]` (the `:22` `x.inttime > 0` clamp already
applied); the CSV writer's `inttime` column falls through to the generic `nw eq 1` branch and
prints the raw, unclamped `x[i].inttime` tag -- a negative interarrival time reads as the true
negative value in the CSV and as `0` in the netCDF file, for the same particle.

**Correction**: `pbp_inttime_consistent.corrected_write_pbp_csv_buffer` re-derives
`write_pbp_csv_buffer`'s per-row loop with one extra parameter, `interarrival`, printed for the
`inttime` column instead of `x['inttime']` -- reusing the port's own `PBPPROPS`/
`_idl_format_scalar`.

**Equivalence** (`tests/test_pbp_inttime_consistent.py::Equivalence`): a non-negative `inttime`
(where `interarrival == x['inttime']`, since `MAX(x,0)` changes nothing) -- the corrected CSV is
byte-identical to the port's own `write_pbp_csv_buffer` output.

**A/B consequence** (`::ABConsequence`): `inttime=-0.5` (the port's own two inttime values test case) -- the
port's CSV prints `-5.00000e-01`; the correction prints `0.00000e+00`, matching what the netCDF
writer already writes for the same particle; every other column is unchanged.

**Switch states**: registered `default_on=False` (opt-in), `finding="S6-i"`, `reachability="live"`.

---

# `pbp_rejectionflag_ubyte.py`

**Finding**: the signed rejectionflag byte, `soda2_process_2d.pro:236`/`:277`. `pbpprops` declares `rejectionflag` as
`'byte'`, and `ncdf_vardef(..., /byte, ...)` creates a netCDF `NC_BYTE` -- **signed** 8-bit. A
`rejectionflag` value of 128 (the depth-of-field bit, the uncounted depth-of-field rejects) does not fit the signed range and
reads back as -128 through any type-honouring reader; the CSV writer's bare `(i0)` format shows
`128` unaffected, so the two on-path files disagree on this one flag's sign.

**Correction**: `pbp_rejectionflag_ubyte.corrected_open_pbp_ncdf` re-derives
`open_pbp_ncdf`'s whole dataset-creation orchestration (a netCDF variable's declared type
cannot be changed after creation, so nothing smaller can be wrapped), declaring `rejectionflag`
as `u1` (`NC_UBYTE`) instead of `i1` -- every other variable, global attribute and the `pthdat`
extras are unchanged.

**Equivalence** (`tests/test_pbp_rejectionflag_ubyte.py::Equivalence`): a `rejectionflag` value
that fits the signed range (bit 128 not set) reads back identically under both declarations;
every other variable's dtype (`diam`, checked directly) is unaffected.

**A/B consequence** (`::ABConsequence`): `rejectionflag=128` (the port's own
`test_line_236_rejectionflag_byte_is_signed` construction) -- the port's own signed byte reads
back `-128`; the correction's unsigned byte reads back `128`.

**Switch states**: registered `default_on=False`, default ON through `registry.PROTECTIVE`, `finding="S6-k"`, `reachability="live"`.

---

# `double_pi_fix.py`

**Finding**: the single-precision pi corner count, `min_circle_fast.pro:34, :37, :41, :51`. IDL's `!pi` is single-precision
(`3.1415927410125732`), not `!dpi` (`3.141592653589793`) -- `!dpi` never appears in the SODA-2
tree. Consequence, measured directly: an exact right angle at the routine's third point (`R`)
never satisfies `:51`'s obtuse test, so rectangles, axis-aligned blocks and digitised disc
outlines take the 3-point circle branch where the exact geometry needs only 2. The circle
(`diam`, `center`) is unaffected to double-precision rounding; only `corners` changes, and
since `aspect_ratio.pro:27` branches on `n_elements(circle.corners)`, the changed count can
change the reported `orientation`/`aspr`.

**Correction**: `double_pi_fix.corrected_min_circle_fast` re-derives
`min_circle_fast_traced` with `PI_SINGLE` -> `math.pi` and `HALF_PI_SINGLE` -> `math.pi / 2` at
the four cited sites, reusing the port's own `find_angle`, `find_angle_array`, `find_radius`,
`_two_point_circle`, `MinCircle`, `ITERATION_CAP` and `EmptyInput` -- nothing else is copied.
`corrected_aspect_ratio` composes it with the port's own unmodified `outline_indices` and
`axis_and_ratio`. Only `min_circle_fast`'s four `!pi` uses are widened; `orientation_deg`'s own
`!pi` (the mixed-precision aspect ratio, `aspect_ratio.pro:53`) and `soda2_findsize.pro`'s `_PI` (the position-dependent area precision) are untouched --
`tests/test_double_pi_fix.py::Scope` pins this by AST, not by a docstring claim.

**Equivalence** (`tests/test_double_pi_fix.py::Equivalence`): on the 14 of 20
`gdl_soda2_min_circle_fast_golden.json`/`run_soda2_min_circle_fast_bank.CASES` cases with no
exact right angle at any candidate R (measured directly, not read off the port's own
`:107` "rectangle-like" list), `corrected_min_circle_fast` matches the port bit for bit
(`diam`, `center`, `corners`, `area`).

**A/B consequence** (`::ABConsequence`): 4 bank cases (`block_5x3`, `disc_outline_r12`,
`rect_tas_1p037`, and `L_shape` -- not on the port's own five-case list) change corner count
3 -> 2 with `diam` agreeing to `1.2176439171466038e-16` relative worst case. 2 more
(`rect_4`, `outline_20x8`, both on the port's list) keep the same count and `diam` but change
which point is P/Q/R (a mid-loop reroute, `:37`/`:41`, not only the final `:51` test) -- a
distinct effect the "only corners changes" phrasing undersells; documented, not hidden.
On the whole driver (`soda2_process_2d`, both tracked fixtures, both an equal and an unequal
`yres:xres`, 28 pooled real particles): `f == 0` on every run -- not one particle's
`aspr`/`orientation` changed.

**Default state**: the plan's own written criterion (BACKLOG_STATUS.md's section has the full
numbers), applied mechanically, lands in Default-ON (`f == 0` and the bank changes only
`corners` at double-rounding `diam`), even though the plan itself expected the opposite
outcome. It is opt-in (`default_on=False`): a measured no-op is not a
data-destroying defect, so it is not in the protective set. **Caveat**: 28 particles across two small fixtures is a
thin sample; it shows the two tracked fixtures don't exercise this branch, not that no real
field-campaign particle ever does.

**Switch states** (`::SwitchStates`): registered `default_on=False` (opt-in), `finding="S2-c"`,
`reachability="live"`; both `resolve()` states checked.

---
