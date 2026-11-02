# Conventions and terms
> The file names, stage names and measurement terms used throughout this documentation, defined once.

**In short:** the rules that make the port auditable — visible MATLAB indices, netCDF semantics, fidelity profiles, and which MATLAB findings are fixed (in the v3.5 engine or the opt-in enhancements) versus preserved as written.

**See also** [Findings](07-findings.md) for what reproducing those preserved bugs revealed about
the original · [Glossary](11-glossary.md).

Every name below comes from UIOOPS: the file naming is `combine_sizedist.m`'s, the stage
boundaries the original scripts', the size bins `sizeDist.m`'s. A campaign's files substitute into
the placeholders.

## Placeholders

| | |
|---|---|
| `<stem>` | a raw file's name without its extension. SPEC probes write `base<YYMMDDhhmmss>`, e.g. a file that opened at 06:44:03 on 6 September 2016 is `base160906064403`. Other manufacturers' formats have their own conventions; nothing in the pipeline requires this one. |
| `<channel>` | `H` or `V` — the probe's horizontal or vertical array. Both are decoded; which is *usable* is a per-campaign question about the instrument. |
| `<probe>` | the probe name as the project/probe table spells it: `2DS`, `HVPS`, `CIP`, `PIP`, `2DC`, `2DP`, `F2DC`. |

## The pipeline's files

| Stage | Produces | Contents |
|---|---|---|
| **Decode** (`read-binary`) | `<stem>.<channel>.cdf` | one record per image record: the eight timestamp fields and the packed 8 × 1700 image block |
| | `<stem>.tas.csv` | one row per housekeeping packet: time, true airspeed, and six counters. **The one-second grid every later stage uses is built from these times** |
| | `<stem>.NV.csv`, `<stem>.MK.csv` | the vertical-count and mask sidecars, written verbatim as the original writes them (including its missing line terminators in `.MK.csv`) |
| **Frame and describe** (`imgproc`) | `proc.<stem>.<channel>.nc` | one row per particle: sizes under six definitions, habit, reject code, area, perimeter, hollow diagnostics, and the record/position bookkeeping that lets any particle be reconstructed |
| **Size distributions** (`sizedist`) | `sd.<stem>.<channel>.nc` | one column per second: counts and concentrations per size bin, sample volume, mean area ratio |
| | `sd.<stem>.<channel>.nc.call` | which call produced it — the output itself cannot be asked (see [User guide](02-user-guide.md), step 3) |
| **Combine** (`combine`) | `<stem₁>.combined.<channel>.<probe>.cdf` | a flight's `sd` files on one time axis, named after the flight's **first** raw file — the product a paper is written from |

UIOOPS ships no canonical combine output name: each group's script writes its own, and one field campaign's
scripts append `_2` for a second processing pass, so the products validated here are
`…combined.H.2DS_2.cdf`. `arrayprobe.cli combine` takes the output path explicitly. The batch driver writes
`…combined.H.2DS.cdf`, and does not append `_2`.

Opt-in variants never overwrite the faithful output; they take a suffix before the extension,
e.g. `proc.<stem>.<channel>.diodecorrected.nc`. Engine 3.5 writes its `proc` and `sd` files, and its SPEC (2D-S/HVPS)
decode, **NETCDF4**, as v3.5's own `netcdf.create(..., 'NETCDF4')` calls do; its DMT, PMS and SEA
decodes and its combined product stay NETCDF3_CLASSIC.

## Stage names

The design documents number the original's stage boundaries:

| | |
|---|---|
| **S2** | raw binary → decoded image records (`read_binary_*`) |
| **S3** | image records → per-particle file (`imgProc_sm`) |
| **S4** | per-particle file → one-second size distributions (`sizeDist`) |
| **S4c** | a flight's size distributions → one combined product (`combine_sizedist`) |

## Measurement terms

| Term | Definition |
|---|---|
| **Size bin** | `sizeDist`'s ladder of 128 bins, 10 µm wide, the first centred at 5 µm. |
| **Used bins** | bins 6–128. The first five are at or below the diode pitch and are not used scientifically, though they hold 99.4-100.0 % of all particles. Headline agreement figures are quoted over the used bins. |
| **Both-present denominator** | every (second, bin) cell where both files have a value, **including 0 = 0**. Dominated by agreement about emptiness. |
| **Non-zero denominator** | only cells where at least one side is non-zero. The demanding figure. Both are always reported; see [Validation](04-validation.md). |
| **Accepted particle** | one whose reject code is in `0 H h u R` and whose centre is in the sample volume. `sizeDist` then applies its own area-ratio and inter-arrival cuts, so "accepted" at the per-particle stage is always more than what reaches a distribution. |
| **Fidelity profile** | a named set of the axes on which two MATLAB lineages provably differ — bounds guards, reject thresholds, the zero-image branch. Never defaulted; see [Configuration](06-configuration.md). |
| **Tree** | which `sizeDist.m` lineage's project/probe table to use: `stock` (UIOOPS as released) or `production` (the lineage that produced the reference products validated here). |

### Version anchors

An earlier translation of UIOOPS v3.1.4 reproduced archived products and is not part of this package. Findings about UIOOPS are anchored on **v3.5**, the version people run.
See [findings](07-findings.md).

## Deprecation policy

This package ships two engines — the v3.5-based UIOOPS engine (`arrayprobe_uiops`, the one
`uiops.engine()` returns) and SODA-2 (`arrayprobe_soda2`) — and **neither is deprecated**.

The selector cannot change a number: `uiops` dispatches and computes nothing
(`tests/test_uiops_selector.py` asserts no arithmetic and no module-level engine import).

**Not decided:** whether changing a scientific default (a profile's threshold, which tree a stock
configuration reads) counts as a breaking change, and any formal support window.

## Preserved bugs

Porting UIOOPS line by line surfaced the findings below; each is fixed in the v3.5 engine or the
opt-in enhancements (see [Findings](07-findings.md)). Each entry has a
regression test named after the line it protects; any deviation is an opt-in flag, default off,
tested both ways. **The mapping is checked, not transcribed**: `test_preserved_bugs_have_tests.py`
verifies every named test still exists. Entries marked **(v3.5)** are bugs of v3.5 itself,
translated as written by the v3.5 engine for the same reason.

- `imgProc_sm.m:577` — `mod(kk, 66536)`, almost certainly a typo for 65536.
  Test: `test_matlab_compat.py::TestPreservedBugs::test_imgProc_577_particle_num_modulus_is_66536`.
- `sizeDist.m:98-99`, `:657-658` — the midnight `+240000` rollover applies only to the *first*
  decrease, because MATLAB's `a:b` uses only the first element of a vector operand.
  Test: `test_sizedist.py::TestPreservedDefects::test_line_83_and_544_correct_only_the_first_midnight_crossing`.
- `sizeDist.m:1036`, `:1169` — the reacceptance loop scans only the first shattering event, same cause.
  Test: `test_sizedist_reacceptance.py::TheEmptyRangeBug::test_an_event_at_the_block_start_reaccepts_nothing`.
- `read_binary_SPEC.m` — **the last record of every raw file is never a primary**: the loop decodes
  the pair (*N*, *N+1*), probes one byte for EOF and breaks. `readers/spec.iter_record_windows`
  yields *n-1* windows.
  Test: `test_spec_reader.py::TestTwoRecordWindow::test_final_record_is_never_a_primary`.
- `read_binary_SPEC.m:313-315` — twenty `%d` conversions for nineteen values, so `fprintf` drops
  the trailing `' \n'` and **`.MK.csv` has no line terminators at all**.
  Test: `test_spec_reader.py::TestHousekeepingPackets::test_mask_records_have_no_line_terminator`.
- `sizeDist.m:882-890` — `int16 × double` collapses `particle_diameter_minR` toward zero for
  `sizeMethod` 1, 2, 3 and 5. `sizeMethod == 4` escapes because `sqrt` promotes to double, but its
  radicand saturates at 32767 above 181 diodes; only 6 (the default) is clean. `mmul`/`mpow`
  saturate while `msqrt` promotes — a uniform "integers saturate" rule is wrong.
  Test: `test_sizedist.py::TestScopeAndRefusals::test_A2_int16_double_saturation_is_preserved_for_d_choice_1_2_3_5`.
- `holroyd.m:283-290` — `parabola_fit_center_is_in` is a stub returning 1, so **habit `'C'` is
  never emitted** by the release that contains it.
  Test: `test_habit_reject_oracle.py::TestUnreachableByConstruction::test_habit_C_is_dead_because_the_parabola_fit_is_a_stub`.
- `calculate_reject_unified.m:269,272` — **reject code `'t'` is unreachable**: `:269` rejects `'a'`
  above `max_comp_img_ar = 5`, `:272` then tests `'t'` above `max_edge_img_ar = 6`, the looser
  threshold tested second. `image_auto_reject` never contains 116. The netCDF `Description` at
  `imgProc_sm.m:325-329` states the thresholds the other way round. Both preserved verbatim.
  Test: `test_habit_reject_oracle.py::TestUnreachableByConstruction::test_reject_t_is_dead_because_the_thresholds_are_ordered_wrong`.
- `calculate_reject_unified.m:54` — `spot_edge(147)` is the literal `0757`, i.e. **757**, a missing
  decimal point. For hole/edge ratios in (0.757, 0.763] the table search stops one entry short, so
  `part_z` is one 0.05 step low.
  Test: `test_reject.py::TestKorolevTables::test_spot_edge_147_is_757_not_0_point_757`.
- `calculate_reject_unified.m:465` — the hollow test packs **diodes 1-32 only**, whatever the
  probe's width; a particle beyond diode 32 gives two zero operands and is ruled hollow on no
  evidence. Reaches `auto_reject` and the Korolev correction.
  Test: `test_reject.py::TestHollowScanQuirks::test_a_particle_beyond_diode_32_is_always_read_as_hollow`.
- `calculate_reject_unified.m:108` — `touching_edge` is initialised numerically and made a
  character only later, so the zero-slice path returns `0` and `imgProc_sm.m:897`'s
  `touching_edge - '0'` yields **-48**. The written variable takes {-48, 0, 68}.
  Test: `test_reject.py::TestTouchingEdgeIsTriState::test_no_slices_returns_the_numeric_initialiser`.
- `sizeDist.m:845-859` **(v3.5)** — when a file holds an earlier-stamped block, the corrupt-time
  pass keeps a time-sorted block only if its time-order successor is its file-order successor, and
  its loop stops one short (`:847`), so **the latest second is always discarded**, and so is the
  clean second just before each corrupt block. The v3.5 engine translates it, as it translates
  every other line of v3.5.
  Test: `test_v35_sizedist.py::TestResolveParticleBlocks::test_sizeDist_845_859_last_time_sorted_block_is_never_examined`.
- `read_binary_SPEC.m:96-97` — an image record that decodes past 1700 slices is cut to the
  1700-column canvas, so **the particles past the cut are lost**, with no message, in both
  releases (reported upstream as the 1700-slice tail drop).
  Test: `test_spec_reader.py::TestCanvasGrowth::test_read_binary_SPEC_96_97_particles_past_slice_1700_are_dropped`.
- `imgProc_sm.m:1384`, `:1387`, `:1390` **(v3.5)** — three Schima habit metrics come back from
  `holroyd_new.m:78-81` in micrometres and are multiplied by `diode_size` again when written under
  `Units = 'mm'`, so the file holds **1000 × diodesize** times the labelled value (reported upstream as the double-scaled habit metrics).
  Test: `test_v35_u1_double_scaling_preserved.py::TestImgProc1384HabitMetricsAreScaledTwice::test_imgProc_1390_written_perimeter_is_1000_ds_times_the_mm_value`.

See [Findings](07-findings.md) for what these revealed about the original MATLAB.

## Friendly views of the preserved contracts

Four raw contracts trip Python callers: `iter_record_windows` yielding *n-1* windows,
`RejectResult.touching_edge`'s tri-state `{0, "0", "t"}`, the terminator-less `.MK.csv`, and
MATLAB's 1-based indices. `arrayprobe.friendly` re-views each — same data, friendlier shape — off
the reproduction path (`tests/test_friendly.py` fails if any pipeline stage under `src/` imports it). See the
[API reference](31-api-friendly.md) and the [user guide](02-user-guide.md#reading-the-output).

**Every public index is MATLAB's 1-based convention** unless a function says otherwise;
`arrayprobe.matlab_compat.to0`/`to1` are the only crossing to Python's 0-based indices. The one
exception is `readers.spec.iter_record_windows`'s `start`/`stop`, which index the parallel
decode's own window range and are 0-based, as its docstring states.

## Bit-exactness classes

"Identical" is not one question. Each compared variable has a class that decides how a difference
is judged, so a report says *what kind* of disagreement it found. The assignment lives in
`arrayprobe.compare` and is part of the comparison's output.

| Class | What it holds | How a difference is judged |
|---|---|---|
| **A** — bit-exact | integers, ASCII codes, counts, bin edges | any difference fails; no floating-point slack, so a mismatch is a real disagreement |
| **B** — closed-form float | floats from a short expression with no accumulation | a few ULP (`rtol` 1e-12). Larger than that is a different formula, not a different rounding order |
| **C** — accumulated float | values summed along the record, where error grows with index | reported as drift against index (first divergence, slope, endpoint), since one maximum cannot separate steady accumulation from one bad element. Informational |
| **D** — algorithm substitution | the smallest enclosing circle, computed by a different implementation of the same mathematical object | agreement is a theorem, so the tolerance is real but loose (`atol` 1e-9) |

**A class is a claim about the variable, and it is revisable on measurement.** `massBL` and `vt`
sat in A until the first cross-platform run showed them differing in the last bit between glibc,
Apple's libm and Microsoft's UCRT — both resolve to the platform's `pow()`. They were moved to B,
where the ~1e-15 relative differences sit four orders of magnitude inside the tolerance — a
correction, not a relaxation, since class A names integers and counts. `mass`, `re`, `Prec_rate`
and `Calcd_area` stay in A on single-platform evidence, under the same suspicion.

## Reference campaigns

Each fidelity claim is tied to a **reference pair**: raw files plus the products a MATLAB run
made from them.

| Campaign | Probe | Pair held | Used for |
|---|---|---|---|
| Field campaign, 2016 | 2D-S (`H` channel) | raw + processed | six flights; the whole-file fidelity numbers |
| Same campaign, 2017 | 2D-S (`H` and `V`) | raw + processed | nine flights, in a year whose configuration this project did not set |
| Same campaign, 2016 | HVPS | raw + processed | reader and framing checks |

A number that names a flight or file is **evidence from a reference pair, not a property of the
package**. The pipeline is campaign- and probe-agnostic: the readers cover SPEC, DMT, PMS and SEA raw formats, and probe types 0, 1, 2 and
3 are ported and oracle-validated.

**Adding a campaign or probe** adds a row above, not pipeline code: supply the raw files and
MATLAB-written products, name the profile and tree used, and `validate_combined_product.py`,
`validate_by_condition.py` and `replay_reject_configs.py` apply unchanged. A probe with no MATLAB
product is validated against the original code under Octave, and that limit is stated wherever it
applies.
