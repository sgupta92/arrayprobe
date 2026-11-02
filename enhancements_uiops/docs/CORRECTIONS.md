# The corrections — one design record per module

**One document, twenty-seven parts.** Twelve of these were a separate file of thirty to a hundred
lines, one per correction module, and they were read as a set every time: they share a structure
(the finding, what the correction does, how it is proved, what it does not claim) and an
audience. They were merged here verbatim, each under its own heading, and modules that shipped
after the merge write their part here directly.

Several corrections were first built against an earlier Python translation of UIOPS v3.1.4,
which is not part of this package; below it is called the earlier translation. "v3.1.4" on its
own names the upstream MATLAB release.

Two module docs stay separate because they are different subjects, not different instances of
this one: `ml_accept_reject_design.md` (a research module, five times the length of any of
these) and `config_file_design.md`. `applicability_matrix.md` says which correction applies to
which probe and campaign.

The measured effect of each correction, and the declaration of which ones have no measurement
yet, live in `paper/paper_numbers.json` under `correction_coverage` — asserted against this
package by `tests/test_paper_numbers.py`.

## Which enhanced file to read

A run with enhancements writes these beside the port's own files, never in place of them; the
port's `proc` and `sd` stay byte-identical to a run without enhancements.

| File | What it adds over the port's file | What it is for |
|---|---|---|
| `<stem>.enh.proc.nc` | the port's per-particle `proc` with each proc-stage correction applied, composed in order onto one copy | per-particle analysis that should not carry the upstream defects the corrections repair |
| `<stem>.enh.sd.nc` | the size distribution rebuilt by the port's own S4 from `enh.proc`, then any sd-stage correction | concentrations and moments; read this rather than the port's `sd` when enhancements ran |
| `<stem>.enh.arco.nc` | an analysis-ready export of the run's most-corrected `sd`, a small file rather than the full `proc` | handing the result to someone who needs the distribution, not the particles |
| `<stem>.enh.arm.nc` | the same most-corrected `sd` laid out to ARM's Data File Standards, carrying the run's `.call` stamp, the enhancement chain and the name of the `sd` it was built from | delivering the distribution to ARM; written only when the run config's `[arm]` table names the real site, platform and facility identifiers and the flight date can be read from the raw stem, otherwise skipped with the reason recorded |
| `<stem>.enh.cf.nc` | the same most-corrected `sd` as a CF-conventions file with a real CF time axis | reading the distribution in general CF-aware tools; skipped with the reason recorded when the flight date cannot be read from the raw stem or the export refuses the file's content (a repeated second, for example) |

Each run also writes a `.enhancements.json` naming every module that ran and a `.call` stamp. The
measured difference each correction makes is in that module's part below and in
`correction_coverage`.

---
# `conc_arear_fix.py`

*(was `conc_arear_fix_design.md`)*

## Design: recovering `conc_AreaR` from the double-scaling bug

**Status: design + implementation, 2026-08-27.** The largest and riskiest enhancement-backlog
item — unlike the swapped hole variables, the missing mean-ratio transpose and the missing decimal in spot_edge, `conc_AreaR` is not a mislabeled or scrambled
*column*, it is a fully **derived, aggregated** quantity (particles binned into a 1-second ×
128-bin grid, sample-volume normalized), so recovering it correctly means re-deriving it from
more primitive data rather than relabeling what is already on disk.

### The finding

`imgProc_sm.m` writes `image_diam_AreaR` to the proc file already converted to millimetres
(`images.AreaR * diode_size`). `sizeDist.m:668-669` then reads it and multiplies by
`diodesize` **again**, so `particle_diameter_AreaR` (the value actually binned into
`conc_AreaR`) is too small by a factor of `diodesize` — 100× on a 2D-S (10 µm diode pitch).
Measured on `base160906064403`: median `image_diam_AreaR` as written is 25.2 µm; after the
second scaling, 0.25 µm — below the first bin edge (5 µm) for all but 3 of 49,637 particles.
`conc_AreaR` comes out identically zero everywhere `conc_minR` (the primary, correctly-scaled
concentration) is finite.

### Why this is recoverable, and why it needed more care than the swapped hole variables, the missing mean-ratio transpose and the missing decimal in spot_edge

`arrayprobe.sizedist` (this port's already-validated transcription of `sizeDist.m`) has
**exactly one read site** for `image_diam_AreaR` (`sizedist.py:727`,
`particle_diameter_AreaR = gv("image_diam_AreaR") * diodesize`), immediately consumed by the
population-binning step that produces `dist_AreaR`/`conc_AreaR`. Nothing else in the module
reads it.

That isolation makes a **pre-compensation** trick sound: if the proc file's own
`image_diam_AreaR` is divided by `diodesize` before `sizedist.run()` ever reads it, the
existing (bug-preserving, already-validated) code's own re-multiplication cancels the
pre-division out, and `particle_diameter_AreaR` comes out correct — **without editing or
reimplementing a single line of `sizedist.py`'s already-validated binning logic.** This is a
materially different, and safer, kind of correction than the swapped hole variables, the missing mean-ratio transpose and the missing decimal in spot_edge: instead of a small
standalone function operating on two already-written columns, it means building a modified
*copy* of a real proc file and running the full, unmodified port pipeline on it.

**The risk that mattered here, and how it is retired**: reproducing the *exact* production
call (`d_choice=6`, `SAmethod=0`, `Pres=9e5 Pa`, `Temp=15°C`, `project='ORACLES'`,
`tree='production'`, the `ddate`/`tas`/`timehhmmss` construction from the flight's own
`.tas.csv`) has to be **exactly** right, or the "corrected" run would differ from the real one
for reasons that have nothing to do with the double-scaled area-ratio concentration. Verified by differential comparison rather than
trusted by construction: running the *unmodified* proc file through this module's own call
assembly reproduces the real production `sd.base160906064403.H.nc` **byte-for-byte on every
variable** before touching `image_diam_AreaR` at all — proof the call itself (TAS loading,
`ddate`, every constant) is reproduced exactly, independent of whether the double-scaled area-ratio concentration fix changes
anything. Only then is the pre-compensated version run and compared.

### Measured result on real data

Applying the correction to `base160906064403` and re-running `sizedist.run()`:

- **Every variable the finding's own analysis says the double-scaled area-ratio concentration does not touch** (`conc_minR`, `n`,
  `Reject_ratio`, `mean_area_ratio`, `mean_perimeter`, `sum_IntArr`, `sample_vol`, …) is
  **byte-identical** to the original (uncorrected) sd file — confirms the call reproduction is
  exact and the correction is properly isolated to `image_diam_AreaR`'s own consequences.
- **`conc_AreaR` goes from identically zero to real, finite, non-zero signal.** 40,064 finite
  cells (matching `conc_minR`'s own finite-cell count exactly — the two variables describe
  overlapping particle populations under different diameter definitions, and the corrected run
  shows that overlap where the buggy one showed nothing), 410 of them genuinely non-zero,
  ranging 0.097–3701.3 cm⁻⁴ (mean 246.7) — physically plausible concentration values, the same
  units and order of magnitude as `conc_minR`'s own non-trivial cells.

### What this module does NOT do

- **Does not touch `src/arrayprobe/`.** `sizedist.py:669` keeps the double
  scaling, per the fidelity doctrine — this module only ever runs the *unmodified* port code
  against a *modified input copy*, on disk, outside the port's own tree.
- **Does not modify the original proc file.** Works on a throwaway copy (a `tempfile`-managed
  path), never the tracked/decoded flight data.
- **Does not correct `total_area`/`mass`/anything else potentially derived from
  `particle_diameter_AreaR`.** Grep confirms `sizedist.py` has exactly one use of
  `image_diam_AreaR`/`particle_diameter_AreaR`, feeding only `dist_AreaR`/`conc_AreaR` — this
  is stated as a checked fact (see the module docstring), not assumed, but any future edit to
  `sizedist.py` that adds a second use site would need this module re-verified.

### Interface

```python
from arrayprobe_enhancements.conc_arear_fix import corrected_sd_file

corrected_path = corrected_sd_file(
    proc_path, tas_csv_path, raw_stem, out_dir,
)
```

Builds a `diodesize`-precompensated copy of the proc file, runs `arrayprobe.sizedist.run()`
on it with the validation campaign's exact production call, and returns the path to the resulting corrected
sd file (written under `out_dir`). Requires `tree="production"`'s constants (`d_choice=6`,
`SAmethod=0`, the fixed `Pres`/`Temp`, `project='ORACLES'`) — this module is specific
to the validation campaign's 2D-S products, matching every other real-data-verified correction in this package.

---

# `diode_range_fix.py`

## Design: validating the shadow-diode list against the probe width

**Shipped 2026-09-01.**

### The finding

In the nine-argument `imgProc_sm.m:290`, `c(:,shadow_diode)='1'` assigns into a char array by
column number, and MATLAB **grows** a char array on out-of-range assignment, padding with
`char(0)`:

```matlab
>> c = ['0101';'1010']; c(:,[2 6]) = '1'; size(c)
ans =    2   6
>> double(c(1,:))
ans =   48   49   48   49    0   49
```

So an entry above the probe's diode count does not raise. The image becomes too wide, and four
lines later (`:272-276`) `figsize(2)~=diodenum` prints `Not equal to doide number` and
**`return`s from `imgProc_sm` entirely**, part-way through the file. The netCDF keeps however many
particles had been written, the process exit status is success, and the only evidence is a line
on stdout. A mask generated against a 128-diode probe and applied to a 64-diode one does this on
the first particle.

The port reproduces the widening on purpose — `masks.reilluminate` pads with `char(0)` (measured
in Octave; the `_CHAR_PAD` constant) — because reproducing the growth is what lets the width guard
fire here too, instead of being pre-empted by an `IndexError` of our own invention.

### What the correction does

`validate_diodes(diodes, diodenum)` is the image-widening diode number's suggested edit —
`assert(all(shadow_diode >= 1 & shadow_diode <= diodenum))` — raising `DiodeRangeError` that names
every offending entry, the probe width, and the truncation the entry would have caused.
`out_of_range` separates the three ways an entry can be unusable, because they fail differently:
`above` is the image-widening diode number's silent widening, while a zero, negative or fractional subscript stops MATLAB at
the assignment and is already loud (the port raises `MatlabIndexError`). `reilluminate_checked`
is the drop-in for `masks.reilluminate`: it validates, then calls the port's own unmodified
function, so the assignment itself is never reimplemented here. `validate=False` delegates
straight to the port — the faithful state, widening included.

### How it is proved

`would_widen(diodes, diodenum)` is asserted against what `masks.reilluminate` *actually* returns
on six diode/width combinations, so the claim "this would add N columns" is measured against the
port's real output rather than against a description of the MATLAB. The loud MATLAB failures are
checked to still come from the port under `validate=False`, so the validator cannot disguise a
subscript error as an image-widening diode-number range error.

### What it does not claim

**No product from the validation campaign is known to have been truncated by this.** The 09/06/2016 2D-S masks
recovered here are empty, and the 09/06 HVPS mask names diodes 2 and 128 — both in range for a
128-diode probe. The module is a validated guard, not a recovery, and it makes no estimate of how
often the failure has occurred in the field.

**It cannot repair a file that was already truncated.** The evidence needed — how many records the
run got through before `return` — is not in the product. Re-running with a corrected mask is the
only remedy.

**It does not decide what the right mask is.** An out-of-range entry could mean a wrong-probe
mask, a 1-vs-0-based mix-up, or a corrupt file; the module reports the numbers and the probe width
and stops there.

---

# `hole_edge_swap.py`

*(was `hole_edge_swap_design.md`)*

## Design: correcting the `max_hole_diameter` / `edge_at_max_hole` swap

**Status: design + implementation, 2026-08-27.** Smallest item in the enhancement backlog
(the project scope plan's "Enhancement backlog" table) by construction — a
one-line MATLAB fix, no science to specify, no paper to consult. Written up properly anyway
per this project's own doctrine (design before code), because "trivial" is a claim about the
fix, not a reason to skip stating it.

### The finding

`imgProc_sm.m:919-920`: `varid29` (`edge_at_max_hole`) is written `images.max_hole_diameter`;
`varid30` (`max_hole_diameter`) is written `images.edge_at_max_hole`. Every proc file's two
variables carry each other's quantity, contradicting their own names and `Description`
attributes. Confirmed two ways in the original finding (reading the four defining/writing
lines together; the physical invariant `max_hole_diameter <= edge_at_max_hole` running
backwards on every differing particle in a 99-particle sample) and reconfirmed here on the
full real flight `base160906064403`: **845 of 49,637 particles differ, all 845 have the
inequality reversed, and swapping restores it for all 845.**

### What a correction is, precisely

There is no reprocessing to do. The raw diode data was scanned correctly — `imgProc_sm.m`
computed both quantities right, then wrote each into the other's netCDF slot at the very last
step. So the correction is a **relabeling of two already-written columns**, not a new
computation: given `max_hole_diameter` and `edge_at_max_hole` as read from any proc file this
port has ever written (or MATLAB's own, since the port reproduces the swap faithfully), the
corrected values are simply the two arrays exchanged.

```
corrected_max_hole_diameter = swapped(edge_at_max_hole)
corrected_edge_at_max_hole  = swapped(max_hole_diameter)
```

This makes it the simplest possible shape for an `enhancements_uiops/` module: pure function, no
netCDF write of its own required (a caller can apply it to already-loaded arrays, or to a
freshly-read proc file), and a validation strategy that needs no oracle at all — the physical
invariant `max_hole_diameter <= edge_at_max_hole` (a hole cannot be wider than the particle
containing it) is the check, and it is checkable on real data without reference to any MATLAB
run, corrected or not.

### What this module does NOT do

- **Does not touch `src/arrayprobe/`.** The port's own `imgproc.py` continues to
  write the swapped values exactly as MATLAB does — preserving the bug is the whole point of
  the port. This module operates strictly on the port's
  *output*, after the fact.
- **Does not reach every particle.** Only particles where the hole and edge measurements
  genuinely differ (845 of 49,637 on the one flight measured, ~1.7%) are visibly affected;
  where they're equal the swap is a no-op. `Particle_number_all`-style "how many particles does
  this touch" framing from the enhancement backlog table applies literally here: both
  variables, for every particle, but only ~1.7% show a numeric change.
- **Does not correct anything downstream that consumed the swapped values under their wrong
  names.** If `part_z`/`size_factor` (the Korolev machinery, `outoffocus.py`) or any other
  computation ever reads `max_hole_diameter` expecting the edge-distance quantity, that
  consumption is unaffected by this module — it operates on the two variables in isolation,
  not on anything derived from them. Checked: `sizeDist.m`'s hollow/Korolev block reads
  `max_hole_diameter` and `edge_at_max_hole` directly from the proc file and does not
  recompute either from more primitive data, so correcting them at read time is sufficient;
  there is no hidden intermediate that also needs correcting.

### Validation strategy

No MATLAB oracle is needed or possible here (there is no "corrected" MATLAB run to diff
against — the correction doesn't exist in any UIOOPS tree). The check is the physical
invariant itself, on real data:

1. Read `max_hole_diameter`/`edge_at_max_hole` from a real proc file.
2. Apply the swap.
3. Assert `corrected_max_hole_diameter <= corrected_edge_at_max_hole` for every particle where
   they differ (equal-valued particles trivially satisfy either direction and carry no
   information about which label is right).

This is exactly what closed the original finding and is re-run as a real-data test here
(`tests/test_hole_edge_swap.py`), against `_decoded/proc.base160906064403.H.nc` when present,
skipped gracefully when it isn't (CI / a fresh clone with no decoded flight data).

### Interface

```python
from arrayprobe_enhancements.hole_edge_swap import correct_hole_edge_swap

max_hole, edge = correct_hole_edge_swap(raw_max_hole_diameter, raw_edge_at_max_hole)
```

Takes and returns plain arrays (or scalars) — no netCDF dependency of its own, so it composes
with however a caller already has the two columns in memory (a `netCDF4.Dataset`, a `dict`
of loaded arrays, a pandas column, whatever `triage_server.py` or a notebook is already using).

**On the v3.5 engine.** Read directly against v3.5: the swap is unchanged.
`imgProc_sm.m:564-573` still `defVar`s `varid29` as `'edge_at_max_hole'` and `varid30` as
`'max_hole_diameter'`, and `:1376-1377` still `putVar`s `varid29` from `images.max_hole_diameter`
and `varid30` from `images.edge_at_max_hole` — the two are still swapped on the way to disk,
exactly as `arrayprobe_uiops/imgproc.py:43-45, :729-732` already documents. `pipeline.py`'s
`_APPLIERS` wires this module as a driver adapter, composing onto the same `.enh.proc.nc` as
`outoffocus`; on the dense v3.5 reference it swaps **40 of 240 particles**
(`docs/measurements.json`'s `v35_hole_edge_swap`, `tools/v35_ab_summary.py`). This is an A/B on a
demo file, not validation.

---

# `int16_double_fix.py`

*(was `int16_double_fix_design.md`)*

## Design: double-precision `d_choice` size definitions

**Status: design + implementation, 2026-08-27.** Second item started from the nine-item
enhancement-backlog triage table in the project scope plan, user-directed
2026-08-27: "start all the backlog items and create tests... create and save a list."

### The finding

`image_width`/`image_length` are declared `'short'` (int16) in stock UIOOPS's netCDF
(`imgProc_sm.m:295,299`). MATLAB keeps an integer operand's type across `* diodesize` and
saturates, so `particle_diameter_minR` collapses toward zero for `d_choice` 1, 2, 3 and 5;
`d_choice = 4` escapes the zero-collapse (`sqrt` promotes to double) but still saturates
*inside* the radicand above 181 diodes. Only `d_choice = 6` — the default in every UIOOPS run
script — is unaffected, which is very likely why this went unnoticed.

### The earlier translation was not bug-for-bug faithful here

An earlier translation of UIOOPS v3.1.4 (not part of this package) computed `_d_length`/`_d_width`/
`_d_mean`/`_d_hypot`/`_d_max` (its transcriptions of `sizeDist.m:756-766`) with
plain NumPy `*`/`+`/`/`/`**` on `image_width`/`image_length` as read from the proc file. NumPy
promotes an int16 array times a Python float to float64 — it does **not** reproduce MATLAB's
int-dominance-and-saturation rule. Measured directly:

```pycon
>>> np.array([37, 50, 300], dtype=np.int16) * 0.010
array([0.37, 0.5 , 3.  ])          # NumPy: no collapse
>>> # MATLAB: int16(37)*0.010 == 0, int16(50)*0.010 == 1
```

So the port was silently "fixing" the int16 diameter saturation for `d_choice` 1–5 — a genuine, if never-before-exercised,
fidelity gap (nothing in the test suite had ever checked a non-default `d_choice` against real
saturating semantics, because no real flight of the validation campaign ever used one — see below).
**Fixed** in the translation, not here: the five affected functions now route
through `arrayprobe.matlab_compat`'s `mmul`/`madd`/`mdiv`/`mpow`/`msqrt` — the exact helpers
`matlab_compat.py`'s own docstrings already named this line range for, but that had never been
wired up. Regression tests reproducing the finding's own MATLAB examples now live in
`tests/test_sizedist.py` (`test_A2_*`). This is a **core-port fidelity fix, not an
enhancement** — it makes the port reproduce the bug more faithfully, which is exactly what
the port is for; it does not belong in this package. 675/675 port tests passed
after the change; `d_choice = 6` (the only path any real product of the validation campaign used) is
byte-for-byte unaffected, since `_d_minr` was never touched.

### The int16 diameter saturation has never affected the validation campaign's data, for a second, independent reason

The campaign's processing variant sets the `imgproc_output_typing` field in `profiles.py`
differently (`imgproc.py:158-161`): stock declares every `imgProc_sm` output variable with
its documented type (`imgproc_output_typing="typed"`, `STOCK_V314`), but **the campaign's profiles
declare every one of them `'double'`** (`imgproc_output_typing="all-double"`, both campaign
profiles in `profiles.py:269,288`) — confirmed directly against a real proc file:

```pycon
>>> netCDF4.Dataset("_decoded/proc.base160906064403.H.nc")["image_width"].dtype
dtype('float64')          # not int16, on a real 2D-S proc file from the validation campaign
```

So for the validation campaign, `image_width`/`image_length` are never `int16` on disk in the first place —
the int16×double trap cannot fire regardless of which `d_choice` a run uses. Combined with
the fact that no real flight of the campaign used a non-default `d_choice`, the int16 diameter
saturation has **two independent reasons it has never touched a product of the validation
campaign**: the dtype that would trigger it does not exist in the campaign's proc files, and the
code path that would exercise it was never called. The first-midnight-only rollover and the
misreported shattering attribute are inert on real data in the same way.

**Practical consequence for this module**: its value is for anyone running the *stock*-typed
profile with a non-default `d_choice` — a real but narrow audience that excludes the
validation campaign's flights.

### What this module does

Double-precision (non-saturating) versions of the four affected `d_choice` branches that
actually multiply by `diodesize` (`length`, `width`, `mean`, `max`) plus `hypot` for
completeness (already escapes the collapse, but still benefits from not saturating the
radicand above 181 diodes):

```python
from arrayprobe_enhancements.int16_double_fix import (
    corrected_d_length, corrected_d_width, corrected_d_mean,
    corrected_d_hypot, corrected_d_max,
)

corrected = corrected_d_length(image_length, diodesize)
```

Each casts its inputs to `float64` before any arithmetic — the one-line fix the finding itself
suggests ("cast at the read, once") — so no saturation, no rounding-to-integer, ever occurs.
`d_choice = 6` (`particle_diameter_minR` read directly, no rescale) is unaffected by the int16 diameter saturation and has
no corrected counterpart here; there is nothing to correct.

### Validation strategy

1. **Synthetic, against the finding's own MATLAB examples.** `int16(37)*0.010 == 0`,
   `int16(50)*0.010 == 1`, `int16(300)^2 == 32767` — reproduced through the (now-fixed) port's
   own buggy `_d_*` functions to prove the saturating reference point is real, then shown that
   the corrected functions here give `0.37`, `0.50`, and an unsaturated `90000` respectively.
2. **Real data, showing the bug's actual (null) footprint on the validation campaign.** Real
   `image_width`/`image_length` pulled from `_decoded/proc.base160906064403.H.nc` are already
   `float64` (the campaign's `all-double` typing), so the port's own (now bug-preserving) `_d_*`
   functions and this module's corrected functions agree exactly on this file — not because the
   correction is a no-op in general, but because the campaign's data was never exposed to the bug in
   the first place. The test asserts that agreement directly, which is itself the measurement
   that closes the "does this touch real data" question for the int16 diameter saturation.

No MATLAB oracle run with a non-default `d_choice` exists anywhere on this machine (never
produced by any real campaign), so there is no "corrected sd file" to diff against — the
validation is the arithmetic identity above plus the synthetic saturation reproduction, per this
project's established "no oracle exists for corrected output" pattern (see `conc_arear_fix.py`
and `reshape_fix.py` for the same pattern applied to the double-scaled area-ratio concentration and the missing mean-ratio transpose).

---

# `int_arr_rollback_fix.py`

## The clock-rollback branch probetype 1 does not have

**Status: design + implementation, 2026-09-02.** One of three built together for findings whose
probes this project holds **no campaign data for** — built now so the
measurement is a data question rather than a code one the day 2DC/2DP/CIP/PIP data arrives.

### The finding

`sizeDist.m` corrects a backwards inter-arrival clock in a three-way branch on `probetype` with
only two branches filled (the field campaign's production variant of `sizeDist.m`, not shipped, lines 726-730; identically at stock
`sizeDist.m:852-856` — the two trees are byte-equivalent in this block, checked):

```matlab
if 2==probetype
    int_arr(int_arr<-10) = int_arr(int_arr<-10) + (2^32-1)*(res/10^6/tasMax);
elseif 0==probetype
    int_arr(int_arr<0)   = int_arr(int_arr<0)   + (2^24-1)*(res/10^6/tasMax);
end
% no clause for 1==probetype
```

Twenty lines later the uncorrected value is charged to the particle (`:748-749`, stock
`:871-872`): `auto_reject(int_arr<0) = 'I'` and `int_arr(int_arr<0) = 0`. So on a CIP/PIP run the
particle sitting at a backwards clock jump is rejected and contributes nothing.

### Two of the finding's own premises were wrong, and correcting them changed the design

The missing probetype-1 rollback correction is filed as **read, flagged for your check**, and two of its
statements came from reading rather than measuring. Both are corrected here:

1. **Probetype 1's clock is not a fixed-width counter.** `imgProc_sm.m:659-663` decodes the DMT
   record header into a 5-bit hour, 6-bit minute, 6-bit second, 10-bit millisecond and 13-bit
   microsecond field, and `:701` assembles them into a **time of day**. The rollover it can
   suffer is midnight — 86400 s — and the finding's suggested `(2^24-1)*(res/10^6/tasMax)` is
   8.39 s for a PIP. The magnitude the finding proposed would have been wrong by four orders of
   magnitude.
2. **The source's own `sum(int_arr<0)>0` diagnostic does catch it.** The finding said it would
   not. Measured: the Octave run below printed `-8.6400e+04 -8.4253e+04` from `:733`.

So the module ships **both** magnitudes as named constants — `SECONDS_PER_DAY` and
`counter_span(res, tas_max, bits)` — and makes `step` a required keyword argument. It refuses to
choose, the same stance `pressure_units_fix.py` takes on 900 hPa versus 9e5 Pa, and for the same
reason: two defensible readings that are not close together.

### How it is proved

The correction is applied to the **input** and the port then runs completely unmodified — the
`tas_grid_fix.py` / `pressure_units_fix.py` shape. `Time_in_seconds` has exactly one read site in
the port (`sizedist.py:946`) and feeds only `int_arr` and `int_arr3`, so the blast radius is the
finding's own scope.

`tools/d3c_rollback_bank.py` injects one 86400 s backwards jump at particle 700 of the project's
only probetype-1 fixture (`s7a_pip_octave_golden.nc`, a small shipped synthetic PIP fixture decoded from a seeded synthetic DMT raw file) and
runs the real unmodified `sizeDist.m` over it under Octave. Three results:

| | |
|---|---|
| **the port's faithful run vs. MATLAB's own output** | **bit-exact, all 25 variables.** This is what turns the missing probetype-1 rollback correction from *read* into *measured*: the missing branch is observed in the interpreter, not inferred from the `if`/`elseif` |
| **what the missing branch costs** | exactly the particle at the jump — total `count` 584 → **583** |
| **what the correction recovers** | exactly that particle — 583 → **584**, identical to the same fixture with no jump injected. 16 of 25 variables move |

A fourth check runs entirely inside the port and needs no Octave: a **252 s** backwards jump is
inside probetype 2's 32-bit span for a 2D-S (252.65 s) and outside every branch probetype 1 has,
because probetype 1 has none. Same file, same jump, two probe names — `PIP` loses a particle,
`2DS` does not. That is the finding stated as a differential rather than as a reading.

### What it does not claim

* **Nothing here is measured on a real CIP/PIP flight, because none exists on this machine.** The
  only probetype-1 fixture is two seconds long, so the jump is *injected*. What is measured is
  what MATLAB does with a rollback — never how often real data contains one. That frequency
  question is the one the missing probetype-1 rollback correction asks the original authors, and it is still open.
* **The corrected side cannot have a MATLAB oracle**: the branch does not exist in any UIOOPS
  version. Only the uncorrected side is checked against MATLAB, which is the half that matters
  for the A/B's honesty.
* **It does not touch `Time` or `particle_time`.** A real midnight crossing wraps those too, and
  that is the first-midnight-only rollover's site — `rollover_fix.py`, a separate correction with a separate decision behind it.

**On the v3.5 engine (2026-09-14).** The first-event-only reacceptance scan is fixed in v3.5 **only** in the
`iaThreshType == 3` branch that is new in v3.5 (`sizeDist.m:1416-1417`, a bracketed
`find(...,1)`, dated JF 11/5/25). `:1213` and `:1346` still read `for iEvent = find(rBegin):
find(rEnd)` unchanged, so the defect is intact on every path an earlier release could take —
live on v3.5 unless the run uses `iaThreshType 3`. `pipeline.py`'s `_APPLIERS` wires this module
unconditionally; on the dense v3.5 reference it applies cleanly with **0 rollbacks**
(`docs/measurements.json`'s `v35_int_arr_rollback_fix`) — vacuous, because the raw's 20-second
span has no midnight rollover, not because the engine changed anything; an input that would not
be vacuous is a raw spanning 24:00 UTC.

**Restricted to probetype 1.** Measured on the validation campaign's seven 2017
v3.5 2D-S procs (`oracles17*_v35/proc.*.nc`): every backward
`Time_in_seconds` step on the 2D-S lies between -249.8 s and about -1e-5 s — the 2D-S's 32-bit tick
counter has a period of about 250 s (`imgProc_sm.m:737`'s `-250` wrap test, port `imgproc.py:123`),
and `sizeDist.m:852-853` already corrects steps below -10 s with the 2^32 span. A one-day step is
the wrong magnitude for this clock by a factor of about 350, and turns every corrected step into an
~86,000 s inter-arrival (`Time_in_seconds` climbing to as much as 361 days on the densest file).
**Conclusion: the 2D-S does not need the probetype-1 rollback correction, and applying it there is itself a defect.**
`int_arr_rollback_fix.py` carries `AFFECTED_PROBETYPES = (1,)` and a `probetype=` keyword on
`proc_file_with_rollback_corrected` that refuses before writing outside that set;
`pipeline._apply_int_arr_rollback_fix` threads `outputs.preset_probetype` through and records a
named skip (`"probetype {n} not affected"`) rather than applying unconditionally. Until this date
the adapter ran on every probetype, including the 2D-S — measured on a 2D-S flight, this applied a
probetype-1 midnight step to a probetype-2 file and left `Time_in_seconds` ending at 17,194,735 s;
that was inert only because no sd was rebuilt from `enh.proc` before the size-distribution rebuild from the enhanced file was wired, so
the gate is what keeps a wrong correction out of every concentration. A separate, unactioned
observation: after the native branch, 1-361 particles per file (at most 2e-5 of particles) still
show a residual sub-second negative inter-arrival, rejected as `'I'` by v3.5 — not a midnight
rollover and not the missing probetype-1 rollback correction; whether it merits an upstream note is an open question.
6 new tests, `ScopedToProbetypeOne` in `test_int_arr_rollback_fix.py`.

---

# `particle_time_glitch_fix.py`

## The first-midnight-only rollover at the probetype-1 site — glitched CIP/PIP header times and the 24-hour cascade

**Protective default:** on probetype 1 (CIP/PIP), which has no archived product, `run_flight.py` applies this correction by default, with `policy="drop"` (`registry.PROTECTIVE_POLICY`), as a separate `enh` product recorded in the `.call` stamp (`--protective off` skips it). The 2D-S/HVPS lineage never gets it (`registry.py:741-757`).

Found by comparing CIP against 2D-S data.

### The finding

For probetype 1 a particle's time is the particle header's own clock, `particle_time`
(`sizeDist.m:511-514`), not the buffer's record time. A CIP header clock can glitch: isolated
headers read `0`, `202`, or `316363` (`31:63:63`, every field all-ones, not an HHMMSS at all),
mostly on the first particle of a buffer, and the clock returns to its running value on the next
particle. `sizeDist.m:544-545` (production; stock `:657-658`) then adds `240000` to **every
particle after the first decrease**, whatever its size — the same statement as the first-midnight-only rollover, reached from
the other side: the first-midnight-only rollover is a midnight crossing corrected too rarely, this is a glitch "corrected" as a
midnight crossing. On the real 2016-09-06 CIP file it moves most of session 2 past the last TAS
second, so the `sd` file is empty for the rest of the flight, silently. Independently of the
cascade, a glitched time opens its own one-second block in the sorted block table (`:549-596`)
and its garbage `Time_in_seconds` makes a negative inter-arrival that the `'S'` gate reads as
shattering (probetype 1 has no rollback clause at `:726-730`, the missing probetype-1 rollback correction).

**v3.5 has a fix and it does not hold here.** `sizeDist.m:787-806` (Finlon, 02/13/19, "ignore
corrupt particle boundary times") shifts, when there is more than one decrease, only after the
first decrease that passes a day-crossover test — previous value above `230000`, drop above
`230000` — applied to single values. An all-ones header passes it, so v3.5 cascades on the same
file from the first `316363` (measured with `arrayprobe_uiops.sizedist.fix_multiday_particle_times`;
`test_the_developers_fix_cascades_on_the_same_glitch` pins the mechanism synthetically). With
exactly one decrease v3.5 shifts unconditionally, so a single glitch cascades there too.

### What the correction does

1. **Classify.** A particle is out of sequence when its `particle_time` is not a valid HHMMSS, or is
   not in the longest non-decreasing subsequence of the valid clock — the smallest set whose
   removal makes the clock monotone. Genuine crossovers are unwrapped first with **the developers'
   own test**, applied to the medians of the 101 valid values either side of a decrease,
   so a glitch run shorter than 50 particles cannot pass it and a real crossover still does.
2. **Recover.** An out-of-sequence particle whose in-sequence neighbours (stream order) read the
   same second is set to that second — exact, at the one-second resolution `sizeDist` files at.
   Its `Time_in_seconds` is spaced evenly between its neighbours', so the two inter-arrival gaps
   it creates sum to the true gap. **That sub-second position is an estimate**, stated as such; it
   reaches only the `'S'` gate. `particle_millisec`/`particle_microsec` are left as written.
3. **Drop only the unrecoverable.** Where the neighbours straddle a second boundary (or one side
   has no in-sequence neighbour) nothing on the file places the particle: the glitched header's
   millisecond field is corrupted along with its time word (it lies between its neighbours' in a
   minority of the particles whose second *is* known), and the buffer's record time bounds a
   particle only from above, by one second more than the second it would have to exclude. Those
   particles are removed from every `time`-dimensioned variable and **counted by cause** — in the
   corrected file's `particle_time_glitch_fix` global attribute, in
   `<output>.particle_time_glitch_fix.json`, and, through the driver, under `details` in the
   run's `.enhancements.json` provenance sidecar.

The port is untouched: the corrected proc goes through the unmodified S4, whose `:544-545` then
finds no decrease that is not a genuine day boundary.

### How it is proved (`tests/test_particle_time_glitch_fix.py`)

- **Equivalence**: on the tracked, Octave-checked probetype-1 fixture (`s7a_pip_octave_golden.nc`,
  a clean clock) the corrected proc equals the source in every variable, and the port's S4 on the
  two is identical in every variable.
- **The cascade, fired and stopped**: one glitch injected into the same fixture makes the port's
  own `sizedist.run` lose the tail to the `+240000` shift; on the corrected proc the total count
  equals the clean run's. A straddling glitch is dropped and the drop is recorded in both sidecars.
- **Mutation**: with the repair replaced by the identity the tail is lost again, so the A/B has
  teeth; the median-vs-single-value crossover test is exercised on a glitch above `230000` that
  fools the single-value form.
- **Two sides from different places**: `port_cascade` is checked against the port's
  `sizedist._rollover_240000` on random glitched clocks; the v3.5 behaviour against
  `arrayprobe_uiops.sizedist.fix_multiday_particle_times`.

### Two policies, added 2026-09-18 — and why `drop` exists

The recovery above infers what a corrupt header *meant* from its neighbours. That inference is
only sound once the corruption's origin is known, and on 2016-09-06 it was not. So
`corrected_proc_file` and `apply_policy` take a `policy`:

| `policy` | what it does | what it assumes |
|---|---|---|
| `repair` (**default, unchanged**) | recover where the in-sequence neighbours bracket one second, drop the rest | the stream is time-ordered and the header is a mis-decoded *real* particle |
| `drop` | drop every particle not on the longest non-decreasing subsequence; alter no value | nothing — it invents no time and estimates no sub-second position |

Under `drop` the surviving clock is non-decreasing **by construction**, so `np.diff(x) < 0` is
empty and the midnight rollover (`fix_multiday_particle_times`) has nothing to fire on. The sidecar and the new `particle_time_glitch_fix_applied` global attribute
record the policy, how many values were **repaired** and how many **dropped**, and the rule in one
sentence: `counts` says what *could* be recovered, `applied` says what *was*, and a file carrying
only the first would read as a repair that never happened.

**Dropping only the syntactically invalid values is not enough** — measured on the
2016-09-06 CIP file, session 2, with the v3.5 engine. 347 of 3,797,537 `particle_time` values fail `hhmmss_is_valid`;
dropping exactly those leaves 839 decreases, v3.5's crossover test still fires and stage 4 still
serves 2,161 of 5,697 seconds (24.5 % of particles). The CIP clock is re-based by `+24570` s
before `sizeDist` reads it, and a glitch that is a legal HHMMSS on the raw clock can cross the
`> 230000` threshold once shifted — `316363` becomes `385333`, `38:53:33`, whose minutes and
seconds are both legal. Dropping all 1,622 out-of-sequence particles (0.043 %) is what removes the
cascade: 5,697 seconds, 3,735,961 particles, 98.4 %. **The pre-pass therefore belongs before any
clock re-basing**, on the clock in the encoding the probe wrote.

### What it does not claim

- **It treats a symptom, not a confirmed cause.** An earlier write-up here (the retracted SEA byte-grid lock) attributed the
  impossible times to a wrong byte-grid **origin** in `read_binary_SEA.m:157-180` — specifically
  that **3,443 of 23,939 records (14.4 %)** lock onto a spurious `0xAA` run and then emit **0.59
  particles each against 185.2** for aligned ones, losing ~637,000 particles. **That claim does
  not reproduce under direct measurement and is retracted**: particles per record are
  flat across the record's actual grid-origin residue, not the ~300x spread the claim requires.
  **Why the impossible
  `particle_time` values arise is therefore not established.** This module removes the stage-4
  trigger regardless of cause; it makes no claim about recovering particles from any specific
  mechanism. **The "aligned 85.6 % of records, not the flight" coverage figure that once stood
  here was arithmetic on the retracted 14.4 % split (100 − 14.4) and is withdrawn with it** — no
  measured coverage figure for this module's own output replaces it yet.
- **Not validated against a MATLAB product of a glitched CIP flight** — none exists here. The
  archived 2D-S product is probetype 2 and files on the record `Time`; this defect cannot reach it.
- **The recovered sub-second position is not a measurement.** Only the second is recovered. Under
  `policy="drop"` nothing is recovered at all, so the question does not arise.
- **It does not judge the image.** A glitched header often sits on a corrupted buffer-boundary
  image; imgProc's own reject codes still decide acceptance, unchanged.
- **Relation to `rollover_fix` and `int_arr_rollback_fix`.** `rollover_fix` must not be applied to a
  glitched clock (it would add `240000` per glitch — its own docstring names the gap). The driver
  runs this module before `int_arr_rollback_fix`, which would otherwise read a glitched
  `Time_in_seconds` as a clock rollback.

---

# `last_record_fix.py`

*(was `last_record_fix_design.md`)*

## The last record of a SPEC raw file as a primary (`last_record_fix.py`)

**Finding.** `read_binary_SPEC.m:83-160` decodes the packets that start in record *N* from
the window (*N*, *N+1*), then probes one byte for EOF and breaks. The final record is therefore
only ever a continuation; every particle beginning inside it is dropped. The port reproduces
this (`readers/spec.py` docstring point 2, `iter_record_windows` yields *n−1* windows) and
the dropped final raw record records it with an *expected-value* estimate of <1 to ~170 particles
per file — an average-rate estimate, never a trace of the actual record.

**What the enhancement does.** Decodes the final record on its own 2048-word window with the
2017 buffer guard forced on (`dataclasses.replace(profile, spec_buffer_guard=True)`). The guard
is the stock tree's own rule for a packet that would run past the window: skip it. So every
complete packet in the last record is decoded exactly as the port decodes any other packet, and
the one packet that may cross the end of the file — genuinely incomplete — is skipped, never
padded or guessed. The other *n−1* windows are untouched.

**Why forcing the guard is the right policy, not a preference.** Under the validation campaign's variant
profile (`spec_buffer_guard = False`) a crossing packet raises exactly where MATLAB's index
would (`MatlabIndexError`) — the port's crash-fidelity. That is the correct behaviour for the
*port*; for a record MATLAB never decodes at all there is no behaviour to be faithful to, and
dying on the file's last bytes would recover nothing. The stock guard is the one documented,
upstream-authored rule for this exact situation.

**Validation (no MATLAB reference exists for this record — that is the finding).**

1. Structural: with and without the enhancement, the *n−1* port windows are identical
   (headers and buffers); the extra window is the last record's data words; a one-record file
   (already a primary in the port), a file whose last whole record is followed by a partial
   one (the port makes that record a primary) and a file shorter than one record add nothing;
   an empty file raises the port's `MatlabIndexError`, as MATLAB dies at `buf(1)`.
2. Policy: a synthetic last record with a packet declaring more words than remain raises under
   the variant profile through the port's `get_img` and is skipped by the enhancement.
3. Trace: `count_last_record_packets` walks the final record by marker and classifies every
   packet (H / V / timing / crossing / housekeeping / mask). This is the direct per-file
   measurement the dropped final raw record lacked; the numbers for the real files are in `BACKLOG_STATUS.md`, row for the dropped final raw record.
4. Coupling: `arrayprobe` never imports this module (`test_no_enhancement_coupling.py`).

**API.** `iter_record_windows_with_last(path)`, `last_record_window(path)`,
`decode_last_record(path, *, profile, sidecar=None, fast=True)`,
`count_last_record_packets(path)`, and `read_binary_spec_with_last_record(...)` — the port's
reader plus the recovered record, returning `(n_h, n_v, extra_h, extra_v)` so the port's own
counts are recoverable from the result.

**v3.5 has the same defect.** Read directly against
`UIOPS-v3.5/joefinlon-UIOPS-039be82/read_binary_SPEC.m`: the outer record loop (`:145`) and the
one-byte EOF probe on the pair (*N*, *N+1*) (`:248-252`) are unchanged from earlier releases. `:297`
(`while iii+4<=2048`, four words tighter than earlier releases) is inside `get_img`'s own marker
walk, not the outer loop's EOF probe — it does not touch this finding. `decode_last_record_v35(path, *, sidecar=None, tas_prev=None, fast=True)` and
`read_binary_spec_v35_with_last_record(...)` are the v3.5 counterparts; v3.5 has no
`FidelityProfile` to force a buffer guard onto (`arrayprobe_uiops.spec.get_img_v35` takes none),
so nothing is forced — v3.5's own tighter scan bound already excludes every position this
module's `complete_prefix` would zero for running past the record, measured by
`tests/test_last_record_fix.py::TestU8BoundIsTheGuard` rather than assumed;
`last_record_window`/`complete_prefix`/`_walk` need no v3.5-specific copy. `write_provenance`'s
sidecar carries an `engine` key on both entry points, so the decode that produced a recovered
file is identifiable without opening it.

**Measured: the recovered particles are almost all in the unused bins.** Framing the dropped record with the port's own `imgProc_sm` and applying the production accept criteria: framed / accepted / in used bins (6+): `075333` 139 / 71 / **1**; `104932` 201 / 192 / **14**; `102921` 210 / 181 / **6**; `104237` 235 / 185 / **5**; `063857` 114 / 37 / **0**. Largest recovered particle 40–133 µm. So the loss is real and countable, but concentrated in bins 1–5, which the science does not use — the effect on a published size distribution is single-digit particles per file, not the hundreds the particle count alone suggests. Reproduce with `enhancements_uiops/tools/last_record_particle_sizes.py`.

### Provenance

Without a provenance record, a recovered `.H.cdf` is indistinguishable from a faithful one. It still is *inside*
the file — deliberately, because adding an attribute of our own would break the byte-fidelity the
package exists to demonstrate — so the record goes **beside** it:
`read_binary_spec_with_last_record` writes `<outfilename>.enhancements` with
`last_record_fix=applied`, the per-channel recovered counts, the profile, and a one-line note
that the final raw record is present and is not in a faithful decode. `provenance=False` opts out
for a caller writing its own record.

The **enhancement** writes it, never the port: `arrayprobe` does not know this package exists, and
`tests/test_no_enhancement_coupling.py` enforces that. This is the same reasoning that
put `run_flight.py`'s `.call` sidecar beside the `sd` file rather than in it (the misreported shattering attribute) — the
earlier note here pointed at the config-file work, but that would have required the port's driver
to learn about enhancements, which is exactly the coupling the architecture forbids.

**Not done.** Threading the recovered record through `imgProc`/`sizeDist` is automatic once the
`.H.cdf` carries it; no change downstream.

---

# `mask_presence_fix.py`

## Design: a missing or misnamed shadow-diode mask stops being silent

### The finding

The nine-argument `imgProc_sm.m:288` — the form that produced the validation campaign's products — looks the
mask up by constructed name and has an empty `else`:

```matlab
if exist([path '/' 'diode.' flight file '.' infile(end-4) '.mat'],'file')==2;
    load([...],'shadow_diode');
    c(:,shadow_diode)='1';
else
end
```

If the file is absent, or present under any other name, the run proceeds with unmodified images
and nothing anywhere records that the intended correction did not happen. The output is
byte-identical to a run where masking was never requested, and the validation campaign's variant writes no
netCDF attributes at all, so the product cannot be interrogated afterwards either.

This is not hypothetical. `find_shadow_diodes.m:104` writes `diode.<date><time>.<orientation>.mat`
while `imgProc_sm` looks for `diode.<flight><file>.<orientation>.mat`; the masks recovered for one
2016 campaign carry **no orientation letter at all** (`diode.160906064403.mat`) and would never
have been found. `find_shadow_diodes.m:103-107` additionally saves an empty mask as
`...<or>empty.mat`, a name the loader cannot construct. Determining after the fact whether a
four-year-old product had been diode-corrected took a filesystem sweep, file timestamps and a
recomputation of the selection criterion.

The port reproduces the silence on purpose: `arrayprobe.masks.find_shadow_diode_mask` returns
`None` and says in its own docstring that `None` is the honest result.

### What the correction does

`check_mask(path, flight, file, infile)` performs the same lookup — through the port's own
`orientation_from_infile` and `matlab_mask_filename`, not a second copy of the name construction
— and raises `MaskNotFoundError` naming the exact path MATLAB would have looked for. It also
lists **near misses**: files matching the `diode.<flight><file>` stem under names the loader can
never construct, which is what turns "no mask" into a diagnosis. `required=False` reproduces
MATLAB's own silence and returns the same report, for auditing a directory without failing a run.
`provenance_entry` renders the outcome as one `key=value` line to store *beside* the product —
never inside it, since the port's outputs are byte-compared against MATLAB's, the same reasoning
as `last_record_fix.write_provenance`.

### What it does not claim

**It cannot tell whether an existing product was diode-corrected.** That was never written (the silent missing mask file
and the unrecorded image pre-processing together) and no post-hoc check recovers it; the module prevents the *next* run from
having the same hole. The after-the-fact determination described above remains the only route, and
it was filesystem archaeology.

**It does not decide that a near miss is the right mask.** A `diode.160906064403.mat` with no
orientation letter may be the horizontal mask, the vertical one, or neither. The module reports
it and refuses to guess; loading it is the caller's explicit act.

**No measured effect on any validation-campaign number is claimed.** For the 09/06/2016 2D-S the recovered
masks are empty, so the block is inert for that product. This correction changes what a run
*reports*, not what it computes.

---

# `outoffocus.py`

*(was `outoffocus_design.md`)*

## Korolev out-of-focus size correction (`outoffocus.py`)

**Direction corrected**: an earlier version of the module multiplied, which runs Korolev's
correction the wrong way — see *The direction* below. Every size-distribution number in this part
marked as made with the multiply is kept as the record of that, not as a result.

**Finding.** `calculate_reject_unified.m:330-331` computes a depth estimate `part_z` and a size
factor `size_factor` for a drop whose shadow shows a Poisson spot; `sizeDist.m:793`
(`particle_diameter_minR .* size_factor`) would apply it and is dead code in every tree, inside a
`%{ … %}` comment gated on a variable assigned nowhere (the unapplied Korolev size correction). The port
reproduces the computation bit-exactly (Octave oracle) and never applies it, as MATLAB never did.
Under the validation campaign's production configuration the hollow block that computes the factor is skipped
(`rej_hollow = 0`), so every production proc carries `size_factor = 1` — measured: 0 of 49,637 on
`064403`, 80 under stock. The specification is Korolev (2007), held locally as
`developer/literature/atot-jtech1980_1.pdf`.

**Scope, measured by running v3.5.** *"Dead code in every tree"* is true of UIOOPS releases
before v3.3 and of the validation campaign's trees, but **not of current UIOOPS**: upstream
shipped the application at `imgProc_sm.m:1275-1280` in **v3.3**, and it is live in v3.5. Relative
to *stock* UIOOPS this module is therefore not new — measured there at 2.9 % of particles (200 of
6,819), size reductions 6.9–47.3 %, mean 37.2 %.

**Under `rej_hollow = 0` it is still entirely new, and that is measured rather than assumed.** The
upstream application is gated on `auto_reject == 'H'`, which `rej_hollow = 0` makes unreachable,
so under the validation campaign's production configuration **v3.5 applies no correction**:
`image_diam_minR` is unchanged across all 6,819 particles, and `korolev_particles_corrected` is
**0** on that arm. So the accurate scope is: *superseded upstream for stock users from v3.3, still
novel for anyone running `rej_hollow = 0`* — which includes every archived product of the
validation campaign. The mechanism that keeps it
unreachable is the discarded new hollow verdict; nothing in this module changes.

**What it does.**
- `hollow_diagnostics(image_ds, proc_ds, indices, config=…)` — reconstructs each particle's image
  and re-runs the port's own `calculate_reject_unified` with `rej_hollow` forced on, returning
  `part_z`, `size_factor`, `is_hollow`. The proc's accept/reject decision is neither consulted nor
  changed: this is the "diagnostics without rejecting" option the design called for.
- `correct_diameter(diam, size_factor, direction="korolev")` — `diam / size_factor` (Korolev
  2007 §2 p. 377; v3.5 `imgProc_sm.m:1276`). `direction="dead_line_v314"` is the transcribed
  `sizeDist.m:793` multiply, kept only to reproduce the A/Bs made with it. `size_factor == 1` is
  the identity in both. "Corrected", not "reconstructed" (the design's wording).
- `correct_area(area, d0, size_factor, area_mode="sphere")` — `π/4·D₀²` for corrected particles
  (the reconstruction's sphere; the paper gives no area equation), or `"keep"` the image's shaded
  area. Open question.
- `apply_outoffocus(...)` — all three, for all or selected particles; returns an
  `OutOfFocusResult` labelled with both mode values, writes nothing. Under `engine="3.5"` and
  `"korolev"` it leaves the particles v3.5 already divided (stored reject `'H'`).

**Validation.**
1. Real oracle for the diagnostics path: on the stock-reject proc of `064403` (whose hollow block
   ran), the recomputed `part_z`/`size_factor` equal the stored columns **bit-for-bit** — all 80
   particles with a non-unit factor plus 150 sampled unit ones.
2. On the production proc of the same file (all factors 1), those 80 particles regain exactly the
   stock-stored factors: identical images, identical arithmetic.
3. The correction's arithmetic is pinned (identity at 1 in both directions, Korolev divides and
   shrinks for every `edge_0` entry, the dead line multiplies, shape and sign checks).
4. **Equivalence with v3.5, which already applies it**: on the dense demo decoded
   in-test by the v3.5 engine, a second S3 with v3.5's own `size_factor` forced to 1 gives each
   particle's uncorrected diameter; `correct_diameter(direction="korolev")` of it equals v3.5's
   written `image_diam_minR` **bit-for-bit on all 40 particles v3.5 corrected**, and the dead
   line does not. A v3.5 proc is not corrected twice (tested).
5. **The test that would have caught the wrong direction**: `AreaRatioGateDiscriminatesTheDirection`
   makes three ring-like drops in a copy of the tracked `demo_flight_v314_proc.nc` (`f` = 1.53,
   area ratio 0.6) and runs `sizedist.run` at the production 0.5 gate: the dead-line multiply
   loses every counted one to `'z'`; Korolev keeps them in a smaller bin under both area modes;
   a mutation that flips the operator makes the same guard fire.

### The direction

Korolev (2007) retrieves `D₀ = D_m / η(Z_d)` with `η = D_edge/D₀ ≥ 1` for every `Z_d` (§2 p. 377,
Fig. 3 p. 378, Appendix B p. 388): an out-of-focus drop images *larger* than it is. `size_factor`
is that `D_edge/D₀` column (`calculate_reject_unified.m:21`, looked up at `:331`), so the true
diameter is the measured one **divided** by it — which is what v3.5 does
(`imgProc_sm.m:1276`, `arrayprobe_uiops/measure.py:241`). The dead `sizeDist.m:793` line, which this
module transcribed, multiplies. Under `sizeDist.m:848-849`'s 0.5 area-ratio gate the direction
decides the sign of the effect: the multiply divides a corrected particle's area ratio by `f²`
(1.15–3.64) and `'z'` removes those that fall below 0.5; the divide raises it by `f²` (area kept)
or sets it to 1.0 (sphere), so no corrected particle can be lost to `'z'`. The "every touched bin
loses" results below are what a wrong-direction correction does under that gate.

### Size-distribution consequence (`tools/outoffocus_ab.py`) — **superseded: made with the multiply, and with S4 at 1013.25 / 20 rather than the production 9e5 / 15**

Whole-file A/B on `base160906064403` under the production configuration: `hollow_diagnostics`
re-derives the factors with the hollow block forced on, the corrected diameters go into a *copy*
of the proc, and `arrayprobe.sizedist.run` runs unmodified over both.

| | |
|---|---|
| particles re-derived | 49,637 |
| with a depth estimate (`part_z ≠ -1`) | 6,968 |
| **diameters actually corrected** (`size_factor ≠ 1`) | **80 (0.16 %)** |
| correction ratio on those | 1.074 – 1.908, median **1.533** |
| grid cells changed | 20 of 526,080 (15 in used bins 6+) |
| binned particles | **−19 all-bin, −14 used-bin** |
| bins touched | 5 – 18, largest single-cell change 2 |

**Two things worth stating precisely** *(the first sentence has the
physics backwards — a Korolev correction makes particles smaller, see* The direction *above)*.
The correction makes particles *larger* (every ratio is
> 1, as an out-of-focus correction should), yet the binned total *falls* by 19 — so a handful of
particles leave the binned population rather than moving between bins. **The mechanism for that is
not yet established**; it is stated here as measured, not explained. And the effect is small
because only 80 of 6,968 depth-estimated particles get a non-unit factor at all: the Korolev
factor is 1 for the great majority even when the depth estimate exists.

**An instrument error worth recording, because it produced a plausible number.** The tool's first
run reported "4,012 diameters change (8.08 %)". That was `np.isclose(nan, nan) == False`: 3,932 of
this file's diameters are NaN, and every one counted as changed. The real answer, 80, equals the
non-unit size-factor count exactly — which is the arithmetic identity that made the discrepancy
visible. The comparison passes `equal_nan=True` and the tool prints both counts side by side
so the two can never silently disagree again.

### Does the effect hold on dense files?

The whole-file A/B is a ~10 h run on a dense file (46 M particles against `064403`'s 49,637), but
the open question was narrower — whether the *fraction* of depth-estimated particles receiving a
non-unit factor varies by cloud regime — and that is answerable by a systematic stride sample of
6,000 particles per file:

| file | particles | depth-estimated (of sample) | **non-unit factor** (of depth-estimated) | factor median |
|---|---|---|---|---|
| `064403` (sparse) | 49,637 | 830 (13.8 %) | 13 → **1.57 %** | 1.533 |
| `075333` (dense) | 46,245,555 | 80 (1.3 %) | 3 → **3.75 %** | 1.694 |
| `104932` (dense) | 38,101,897 | 613 (10.2 %) | 5 → **0.82 %** | 1.533 |

**Read this as a bound, not as three distinguishable numbers.** The non-unit events number 13, 3
and 5 — far too few to say the fraction differs between regimes, and 3.75 % on `075333` rests on
three particles. What the sample *does* support: the fraction is **small on every file measured,
of order 1–4 % of depth-estimated particles**, and the correction factor stays in the same
1.07–1.91 band. So the unapplied Korolev size correction being a small effect is not an artefact of the sparse file the whole-file
A/B happened to use.

Reproduce with `hollow_diagnostics` over a strided index array; the whole-file size-distribution
A/B on a dense file remains genuinely open, and is the run to schedule if the effect ever needs a
tighter bound than "small".

**Answered in mechanism.** Why 19 particles leave the
binned population when every correction enlarges — the enlargement divides the area ratio by
`f²` and the 0.5 `'z'` gate removes them (*The direction*; a discriminating run on `064403`).
The missing decimal in spot_edge (`spot_edge_fix`) and the swapped hole variables (`hole_edge_swap`) act on the same block's
outputs and become live here; the caller applies them explicitly — this module never applies them
silently.

**On the v3.5 engine (driver adapter).** `hollow_diagnostics`/
`apply_outoffocus` take an `engine` argument (byte-identity tested); under
`"3.5"` they call `arrayprobe_uiops.reject.calculate_reject_unified`'s four-argument form, reading
`ihollow` from the proc's own `image_hollow` column. The other value applies to products written
by UIOOPS releases before v3.3; `enhancements_uiops/tests/test_outoffocus_v35.py`
holds the v3.5 cases. `calculate_reject_unified.m:62` forces
`handles.rej_hollow = 1` unconditionally in v3.5, so the hollow block always runs under the stock
v3.5 driver (unlike the validation campaign's production configuration, where it does not) and this module's own
`rej_hollow`-forcing override is a no-op there. Equivalence oracle: the tracked v3.5 demo proc has
zero Korolev-branch particles, so the tracked dense raw (`demo_flight_dense_raw.2DS`) was decoded
and measured in-test — 240 particles, 40 in the Korolev branch, recomputed `part_z`/`size_factor`/
`image_hollow` equal the file's own columns for every one. `pipeline.py`'s `_APPLIERS` wires this
module as a driver adapter; on the dense v3.5 reference it changed **40 of 240 particles, median
`size_factor` 1.897 among the changed** *(superseded: that was the multiply undoing
v3.5's own division on exactly the 40 particles v3.5 had corrected; under `"korolev"` those 40
are left as v3.5 wrote them, so on that reference (its 40 non-unit factors are exactly its 40
`'H'` particles) the adapter changes no diameter and, under `area_mode="sphere"`, only those
40 areas — derived from the two tests above, not re-run through `tools/v35_ab_summary.py`)* (`docs/measurements.json`'s `v35_outoffocus`,
`tools/v35_ab_summary.py`). This is an A/B on a demo file, not validation — no archived product
was ever produced by v3.5 (`TWO_ENGINES.md` §1). A whole-file A/B against real v3.5 campaign
output has not been run: no whole-file v3.5 output has been produced for it.

**Excluded from the v3.5 default set.** Every registry module was already default-OFF individually, so the only "default" that
still included `outoffocus` was `[enhancements] all = true` (`registry.default_set(engine)`, the
computed stand-in for the hand-listed `v35_all_enhancements.toml`-style configs). Measured on
2D-S v3.5 runs: `outoffocus` changes **no** `image_diam_minR` on v3.5 — the engine's own
pipeline already divides every `'H'`-rejected particle by its size factor (`outoffocus.py`'s
`already` guard, consistent with the unapplied Korolev size correction finding above) — only `image_area` on 0.2-0.4% of
particles, for about 94% of an enhancement pass's wall time (roughly 1.1-10.2 h per flight).
`registry.DEFAULT_SET_EXCLUSIONS = {"3.5": {"outoffocus": ...}}` keeps it out of `all = true` on
v3.5 while leaving it in the default set for products written by UIOOPS releases before v3.3, where it does change diameters; naming it
explicitly (`outoffocus = true`) still turns it on regardless of engine. This is a config-resolution
change only — `outoffocus.py` itself, and the finding above, are unchanged.
`enhancements_uiops/tests/test_default_set.py`, 9 tests.

---

# `overload_accounting_fix.py`

*(was `overload_accounting_fix_design.md`)*

## Keep the DOF-overload accounting for seconds that accept nothing (`overload_accounting_fix.py`)

**Finding.** `sizeDist.m:813` measures per second the inter-arrival time lost to DOF overload
(`time_interval72`); if the second accepts no particles, `:1337` resets it to 0, so `:1571`
writes `sum_IntArr = 1` and `:1605` a full `sample_vol` — the opposite of the measurement.
Concentrations are unaffected. 160 of 313 particle-bearing seconds on 09/06/2016 take this
path (the no-accept second overwrite). The port reproduces the reset (`sizedist.py`, `:1327,
:1337-1340` block). It ships as an opt-in enhancement.

**What it does.** Post-processes a written `sd` file against its `proc` file, into a copy:
for every second with particles present, no accepted particles and `sum_IntArr == 1`, recompute
`:813` exactly as the port does (inter-arrival against the previous particle in the file,
probetype-2 clock rollback, negatives clipped, MATLAB-order sum over `DMT_DOF_SPEC_OVERLOAD ≠ 0`)
and write `sum_IntArr = 1 − t72`, `sample_vol × (1 − t72)`. Nothing else in the file changes;
the port's files are never modified.

**Validation.**
1. Pure-function cases: previous-particle gap, first particle of file, rollback, clipping,
   probetype 0 (no flag).
2. Real oracle: on seconds the port did **not** reset, the recomputed `1 − t72` must equal the
   port's written `sum_IntArr` to 12 places — the recomputation is checked against the port
   itself before it is trusted on the reset seconds.
3. The affected set on a real file is exactly the finding's predicate; the source file's
   mtime is unchanged.

**Caveat found on real data.** `:696-697` measures a second's first particle against the previous particle *in the file*, however many empty seconds lie between; when that particle is flagged overload, `t72` absorbs the whole gap and can exceed 1 s, so `1 − t72` goes negative (5 of 223 touched seconds on `064403`, min −4.69). The port's non-reset seconds never show it only because no such second survived the reset. Applied as `:813` defines it — clipping would be a further edit and is **deferred**; the module stays faithful to `:813`. Measured across eight files: of the seconds the reset touches, only some change at all (`064403` 159 of 223, `102921` 462 of 1,856, `124240` 49 of 3,167 — the rest had no overload-flagged particle, so `1 - t72 = 1` either way), and negatives are rare and small outside the sparse file: 5 on `064403` (min −4.69), 67 of 1,856 on `102921` (min −0.26), 22 of 271 on `102201` (min −0.19), none at all on four of the eight. The −4.69 outlier is a sparse-file artefact of measuring across empty seconds, not a general property.

**Reproduce the numbers.** `tools/overload_impact.py` prints touched / changed / negative per
file, which is the distinction that was confused once already: most touched seconds do not change
(they had no overload-flagged particle), and negatives are a small subset of the ones that do.

**Consequence (A/B).** Reported per run: number of seconds corrected and the range of
`1 − t72` written. On `064403` see `BACKLOG_STATUS.md`, row for the no-accept second overwrite.

**On the v3.5 engine.** Conditional on the run, not on the engine: v3.5's
`sizeDist.m` only `defVar`s `sum_IntArr`/`sample_vol` under `if iSaveIntArrSV == 1` (`:2363-2372`),
and `scripts/run_flight.py`'s `V35_CALL` pins `iSaveIntArrSV=0` for every default v3.5 run
(`arrayprobe_uiops/sizedist.py:706`'s write gate) — measured on the tracked `demo_flight_v35_sd.nc`,
which holds neither variable. The module names this refusal
(`overload_accounting_fix.MissingSizeDistVariables`) rather than applying vacuously; a caller who
wants the no-accept second overwrite's correction on v3.5 must re-run `sizedist.run` with `i_save_int_arr_sv=1` first (an `sd` built that way
in-test from `demo_flight_v35_proc.nc` confirms the module then runs). `pipeline.py`'s
`_APPLIERS` wires this module, but on the dense v3.5 reference's default run the A/B is
**vacuous**: `sd` lacks `sum_IntArr`/`sample_vol` (`docs/measurements.json`'s
`v35_overload_accounting_fix`). Whether the enhanced driver's v3.5 call should flip
`i_save_int_arr_sv` is not yet decided.

---

# `particle_number_all_fix.py`

## Design: making `Particle_number_all`'s definition agree with its write

### The finding

`imgProc_sm.m` guards the same variable twice with different operators:

```matlab
:265   if probetype~=0 || probetype~=3     % defVar + putAtt
:879   if probetype~=0 && probetype~=3     % putVar
```

No integer is simultaneously 0 and 3, so `:265` is true for every probetype and the definition is
unconditional; only the write is guarded. Every 2DC, 2DP and Fast2DC proc file therefore carries a
`Particle_number_all` variable of pure fill values, described in its own attribute as "Index of
particle in 2-D buffer". Both comments date the lines to the same 06/22/17 change, which suggests
a slip. The port reproduces both sides: `imgproc.py`'s spec table defines the variable, and
`imgproc.py:1312-1313` writes it only for `probetype not in (0, 3)`.

### What the correction does

`audit_proc_file(path)` reports the state of the variable in a written proc file — present or
not, how many of its values are real, and whether the file is in the defective state (present,
non-empty, every element the netCDF fill). `corrected_proc_file(src, dst)` writes a copy with the
variable omitted, which is exactly what the finding's own suggested edit (`||` → `&&` at `:265`)
produces: a consumer then gets a missing-variable error instead of a column of `-2147483647`.
Every other dimension, variable, value and attribute is copied verbatim and the source is never
modified.

### Why it removes the variable rather than filling it in

`Particle_number_all` for these probetypes comes from the raw buffer word `data(header_loc, 4)`
(`imgProc_sm.m:356`; the port at `imgproc.py:897`) — a number that exists only in the raw file,
never in the proc file. It cannot be recovered from a proc file, and a plausible 1..n index per
record would put fabricated values under a real variable name, which is worse than the defect.
So the correction makes the *definition* consistent with the write, the direction the finding
itself suggests. `corrected_proc_file` refuses outright when the variable carries any real value,
because then the file was written by a probetype the write guard allows and removing it would
delete data; `force=True` is the only way past that and the report says which happened.

### What it does not claim

**It has never been run against a real 2DC/2DP/Fast2DC product, because no UIOOPS product
exists for the real raw files held (a 1995 ACE-1 2DC/2DP file and a CAESAR 2024 Fast-2DC file).** The validation campaign flew a 2D-S/HVPS (probetype 2), where the variable is both defined and
written and this module is a no-op — asserted against a real proc file from that campaign when one is
present. The defective state is exercised on a synthetic proc file built by the tests to the
proc file's own layout, honestly labelled, the same standing as `pms_c6_routing_fix.py`.

**It does not claim the defect changes any number.** It does not: `sizeDist.m:673`/`:796` never
read `Particle_number_all` for probetype 0 or 3, so no computed quantity depends on it. The
consequence is a fill-valued variable presented to a downstream user as data.

**On the v3.5 engine.** Read directly against v3.5: the asymmetric gate is
unchanged. `imgProc_sm.m:347` still *defines* the variable under `probetype~=0 || probetype~=3`
(true for every probetype) and `:1329` still *writes* it under `probetype~=0 && probetype~=3` (an
AND that excludes probetype 0 and 3) — the same asymmetric gate the port's own docstring cites
(`arrayprobe_uiops/imgproc.py:356`, `:1329-1331`). `pipeline.py`'s `_APPLIERS` wires this module; on
the dense v3.5 reference it audits `all_fill=False` (probetype 2, the 2D-S demo, writes the
variable correctly), so the driver records a named skip rather than the module's own `ValueError`
— **vacuous** (`docs/measurements.json`'s `v35_particle_number_all_fix`). The real 2DC/2DP (ACE-1, 1995) and Fast-2DC (CAESAR, 2024) raw files held locally have
not been run through `imgProc`/`sizeDist` in a validated way, so the defective state is not yet
exercised on either engine.

---

# `particle_time_int8_fix.py`

## Recovering `particle_time` from its `int8` collapse

**Protective default:** on probetypes 0 (2DC/2DP) and 3 (Fast2DC), which have no archived product, `run_flight.py` applies this correction by default as a separate `enh` product recorded in the `.call` stamp (`--protective off` skips it). The 2D-S/HVPS lineage never gets it (`registry.py:741-757`).

Built alongside `int_arr_rollback_fix.py`, for
the same reason: the probes it applies to (2DC, 2DP, Fast2DC) are ones this project holds no
campaign data for, and being ready is the point.

### The finding

`imgProc_sm.m:886` writes `part_hour(:)*10000 + part_min(:)*100 + part_sec(:)`. For probetype 2
those accumulators are a literal `0`; for probetype 1 they come from `bin2dec`, which returns
`double` whatever its input. For probetype 0 (2DC/2DP) **and probetype 3 (Fast2DC)** they are
seeded straight from the record header at `:606-608`/`:620-622`, and `netcdf.getVar` returns the
file's own declared type — `'byte'`, i.e. int8, per `read_binary_PMS.m:53-55`. MATLAB
growth-by-indexing inherits that class and MATLAB integer arithmetic saturates, so
`particle_time` collapses to 127 for virtually every real record.

The same routine gets it right eighty lines earlier: `:726` and `:787` both write
`double(handles.hour)*10000 + ...`. That is why the file's `Time` carries the correct HHMMSS
while `particle_time`, documented in its own attribute as HHMMSS, does not.

### Why this one needed a trick to prove, and what the trick is

Every other correction in this package can be checked against something. This one destroys the
value it is meant to carry, so there is no MATLAB output anywhere holding a corrected
`particle_time` — **except** in the corner of the value space the int8 particle-time collapse itself names, where the hour is
0 and `minute*100 + second` stays under 127.

`tools/a15_particle_time_bank.py` builds **two raw 2DC files differing only in the record
header's hour/minute/second**, byte for byte identical otherwise, and runs the real unmodified
`read_binary_PMS.m` + `imgProc_sm.m` over both under Octave:

| record header | MATLAB's `particle_time` | the true value |
|---|---|---|
| `00:00:58` | `[58, 101]` | `[58, 101]` — it agrees |
| `06:06:58` | `[127, 127]` | `[60658, 60701]` |

Measured, not assumed: the two goldens differ in **exactly two variables**, `Time` (+60600,
correct in both) and `particle_time`. Everything the recovery consumes — `Time_in_seconds`,
`particle_millisec`, `particle_microsec`, `parent_rec_num` — is bit-identical. So
`corrected_particle_time` is checked against MATLAB's own arithmetic where MATLAB can be trusted,
and then applied where it cannot. The two files' corrected values differ by exactly `+60600`,
which is a second, independent way to state the same check.

`TAS2_INT = 13_200_000` gives `part_time2 = 3.3 s`, chosen so the second particle carries `58 + 3
= 61` seconds over the minute boundary (`:647-648`) while keeping `minute*100 + second = 101`
under int8's ceiling in the hour-0 file. Exercising the carry cascade was the point of picking it.

### The recovery, and why it works on an already-written file

Unexpectedly, the true value **is** recoverable from a written proc file. `Time` (`:787`) gives
each record's seed — `firstpart` resets at `:499`, inside the record loop, so every record's first
particle is seeded from that record's own header — and `Time_in_seconds`, `particle_millisec` and
`particle_microsec` are enough to replay `:627-652`'s cascade in double.

The replay is **self-checking**, which is what makes it more than a re-derivation: it recomputes
`particle_millisec` and `particle_microsec` as well, and `verify_replay` compares them against the
file's own. On every tracked PMS golden they agree to the last bit — `999.99999999982946974` on
the fixture above, not "to within a microsecond". `corrected_proc_file` refuses to rewrite
`particle_time` unless that check is exact, because a cascade that cannot reproduce the two
columns it wrote cannot be trusted to recover the one it destroyed.

The cascade is replayed rather than closed-form on purpose: `:641-652` tests each level **once**,
so it is a single conditional subtraction, not a modulo. A 130 s value lands on `1 min 70 s`, and
a test pins that.

### What it does not claim

* **It has never been run on a real 2DC, 2DP or Fast2DC file, because none exists here.** The validation campaign
  is a 2D-S/HVPS campaign — probetype 2, where `part_hour` is a literal `0` and none of this
  applies. Every figure above is from a hand-built synthetic raw file through unmodified MATLAB
  under Octave. No real-flight A/B, no recovered-particle count, no claim about any archived
  product. That is a data gap, stated, not an argument.
* **The hour-0 oracle covers 2DC only.** The port's own tracked Fast2DC golden
  (`s7e_f2dc_octave_golden.nc`) shows the same collapse to `[127, 127]`, so the *faithful* side is
  measured for probetype 3 too, and the recovery there returns `[60644, 60646]` — the values
  the int8 particle-time collapse's addendum already stated, written before this module existed. But
  the hour-0 fixture pair has not been rebuilt in Fast2DC's raw format, so the *corrected* side
  has a real MATLAB oracle for probetype 0 alone.
* **The recovery needs the probetype told to it.** A proc file does not record which wrote it,
  and `:628-632` computes `frac_time` differently for the two.
* **It does not fix the second-order oddity it reproduces.** `:636` adds `floor(part_time)` to the
  seconds for both probetypes even though probetype 3's `part_time` is an absolute since-power-on
  clock, so a Fast2DC particle's seconds and milliseconds advance on different clocks. Correcting
  *that* would move `particle_millisec` and `particle_microsec` as well, has no oracle behind it,
  and is a separate decision, not taken here.

**On the v3.5 engine — measured.** The Octave pair was rebuilt against the
unmodified v3.5 tree, with the real `CGAL_minR_v35` MEX forwarded ahead of the v3.1.4
one-argument shim (an earlier attempt had stopped at `CGAL_minR: function called with too many
inputs`, `imgProc_sm.m:1213`). **The int8 particle-time collapse survives into v3.5**: at 06:06:58 `particle_time` is
`[127, 127]` where the true value is `[60658, 60702]`; at 00:00:58 it is `[58, 102]`, which the
correction reproduces exactly, and the replay is bit-exact on both files. The values differ from
v3.1.4's `[58, 101]` by the inconsistent 2DC diode size (v3.5's 2DC diode is 0.03 mm, `:141`), not by any change to
the int8 particle-time collapse. `applicability.py` cites `imgProc_sm.m:1336` with the tag `measured-against-v35`;
`test_particle_time_int8_fix.py::AgainstTheV35OctaveOraclePair` reads the row's numbers off the
golden. The v3.5 port's own measurement block reproduces every measurement column of the same
file bit for bit (`tests/test_v35_2dc_octave_oracle.py`); its whole-file path refuses
probetype 0, so the `particle_time` write itself rests on the Octave golden. `pipeline.py`'s
`_APPLIERS` wires this module, with the probetype resolved from the run's `[run].preset` (a
private, module-registered load of `run_flight.py`). On the dense v3.5 reference (2D-S, probetype
2) probetype 2 is outside `AFFECTED_PROBETYPES = (0, 3)`, so the driver records a named skip on
both engines — **vacuous** (`docs/measurements.json`'s `v35_particle_time_int8_fix`). The real 2DC/2DP (ACE-1, 1995) and Fast-2DC (CAESAR, 2024) raw files held
locally have not been run through `imgProc` in a validated way, so the defective state is not yet
exercised on either engine.

---

# `pms_c6_routing_fix.py`

*(was `pms_c6_routing_fix_design.md`)*

## Design: correcting the `'C6'` (F2DC) file-handle bug

**Status: design + implementation.** Third item from the nine-item backlog triage
table. Originally triaged as "not viable until real data exists" — that triage was **too
pessimistic**, corrected here: like the misfiled F2DC scalar fields' own discovery (a synthetic file run under Octave, no
real campaign data needed), the correction itself needs no real data either, because the bug is
a pure file-routing error in the raw decoder, not something that depends on real physics.

### The finding

`read_binary_PMS.m:147-166`'s `'C6'` (F2DC) branch writes its image correctly to the F2DC file
handle (`f1`) but its nine scalar fields (year, month, day, hour, minute, second, millisec,
wkday, tas) to the **2DC file handle** (`f`) instead — a `f`/`f1` typo on nine of ten
`netcdf.putVar` calls, using the F2DC write-counter (`kk2-1`) rather than the 2DC file's own
(`kk-1`). Two consequences, both silent: a `'C6'` record's scalars can land at an index a real
2DC record occupies (overwriting that record's timestamp/`tas` while its image is untouched) or
extend the 2DC file with scalar-populated, image-empty rows; and the F2DC file itself gets that
record's image with no matching scalar fields (fill value on read-back).

The port (`arrayprobe.readers.pms.read_binary_PMS`) reproduces this exactly — see its module
docstring and `tests/test_pms.py`'s
`test_c6_scalars_land_in_the_2dc_file_not_f2dc`, which already demonstrates the bug on a minimal
synthetic fixture.

### Why the earlier triage ("not viable") was wrong

The original nine-item triage in the project scope plan grouped the misfiled F2DC scalar fields with the int16 diameter saturation, the sometimes-written Particle_number_all and the inconsistent 2DC diode size
as "not viable until real data exists," reasoning that no real PMS/2DC/F2DC campaign file was
held at the time (a 1995 ACE-1 2DC/2DP file and a CAESAR 2024 Fast-2DC file have since arrived;
see item 3 below). That reasoning is correct for *validating the port's PMS reader against real
physics* — but this correction doesn't need physics. The bug is **structural**: a scalar write
targets the wrong file handle, full stop, regardless of what values are in the header. The
original finding itself was established the same way — "constructing a small synthetic OAP file
with one `'C6'` record among ordinary 2DC/2DP/`'C4'` ones and tracing both output files under
Octave" — no real campaign data there either. A corrected reader can be validated the identical
way: build a synthetic file, run both the buggy and corrected readers, and confirm the routing.

### What this module does

`read_binary_PMS_corrected()` — a full reimplementation of the reader's decode loop, reusing
every private helper from `arrayprobe.readers.pms` unchanged (`_def_output`, `_write_scalars`,
`_write_image`, `_skip_xml_header`, `_reshape_matlab`, the tag constants) so the only line that
actually differs from the port's own `read_binary_PMS` is the file handle and counter on the
`'C6'` branch's scalar write:

```python
## port (preserved bug):
_write_scalars(f_2dc, v_2dc, kk2, header)   # wrong file, wrong-file's own counter reused
## here (corrected):
_write_scalars(f_f2dc, v_f2dc, kk2, header) # right file, same counter the image write already uses
```

Reusing the port's private helpers (rather than reimplementing the byte parsing, XML-header
skip, or reshape) means this module cannot silently drift from the port's own decode logic on
anything *except* the one line the finding names — the same "reuse the unmodified pipeline"
discipline `conc_arear_fix.py` used for a different reason (there, to avoid duplicating the
binning logic; here, to avoid duplicating the byte-parsing logic).

### Validation strategy

No MATLAB oracle exists for the corrected output (by construction — MATLAB never ran the fixed
line). Same pattern as every other backlog item so far: validated against the mechanism itself,
on real *and* synthetic inputs where each applies.

1. **Synthetic, reproducing the finding's own construction.** A `'C6'` record built the same way
   `test_pms.py`'s `test_c6_scalars_land_in_the_2dc_file_not_f2dc` does. Confirm the port's own
   `read_binary_PMS` still reproduces the bug (scalars in the 2DC file, fill value in F2DC); then
   confirm `read_binary_PMS_corrected` puts them in the F2DC file where the image already is —
   same index, one row, complete.
2. **Mixed-stream regression.** A file with `'C1'` (2DC), `'C4'` (F2DC, already-correct branch)
   and `'C6'` records interleaved, confirming the corrected reader's fix to `'C6'` doesn't
   perturb `'C1'`/`'C4'`'s already-correct routing or counters.
3. **No real-data test yet.** Two real raw files are held locally (not in the repository):
   a 1995 RAF-format 2DC/2DP file from NCAR/EOL's ACE-1 archive, on which only the v3.1.4 reader
   has been checked (30 of 30 variables equal to Octave), and a CAESAR 2024 Fast-2DC file, on
   which UIOOPS has not been run. Neither has been read with `read_binary_PMS_corrected`. The
   right check on them would be: does `read_binary_PMS_corrected` on a real file produce a `'C6'`-tagged
   image whose scalar metadata (timestamp, `tas`) is physically plausible for that image,
   where the buggy port's F2DC output shows fill values instead. Recorded as the concrete
   next-step check in `enhancements_uiops/BACKLOG_STATUS.md`.

### Interface

```python
from arrayprobe_enhancements.pms_c6_routing_fix import read_binary_PMS_corrected

counts = read_binary_PMS_corrected(infilename, outfilename)
## writes <outfilename>.2dc.cdf / .f2dc.cdf / .2dp.cdf, same as the port's own reader
## returns (n_2dc, n_f2dc_c6, n_f2dc_c4, n_2dp), same shape as read_binary_PMS
```

Drop-in replacement for `arrayprobe.readers.pms.read_binary_PMS` at the call site — same
signature, same three output files, same return shape — so a caller who wants the corrected
routing can swap the import without touching anything downstream.

---

# `pressure_units_fix.py`

## Design: giving `single_vt` the hPa it documents

The only finding among the twenty classified that moves a
number in an output file and had no correction anywhere.

### The finding

`single_vt.m:7` states the contract in the function's own header — *"Pressure use hPa"* — and
`single_vt.m:17` acts on it:

```matlab
T = T + 273.15;
P = P*100;
rho_a = P/(287.15*T);
```

Nothing checks the magnitude of what arrives. Both validation-campaign drivers hand it `9e5`:

| file:line | line |
|---|---|
| `old-stuff-data/…/OptArrProbDataProcessing/runSizeDist_oracles.m:5` | `pres(:)=9e5;` — on `base160906104932`, a 2016 2D-S file this project processes |
| Field campaign's production variant (not shipped), `runsizedist.m:13` | `pres(:)=9e5;` — the same line, on a 2018 HVPS file |

`:17` makes that `9e7` Pa, i.e. **900 bar**, so `rho_a` is roughly a thousand times an
atmosphere. The port passes the caller's value through faithfully (`sizedist.py:1131`, with the
condition noted in a comment) and `run_flight.py:72` reproduces the driver, `PRES_PA = 9e5`.

**The scope is unusually easy to bound, and it was bounded by grep before it was measured.**
`Pres` has exactly **one** read site in the whole of `sizeDist.m` — the field campaign's production variant's `sizeDist.m:854` (not shipped)
(`:747` in the Keeling variant), the `single_vt` call — and `sizedist.py` has exactly one. So the
argument reaches `particle_vt` and, through `particle_pr = particle_mass * particle_vt`, the two
written variables `vt` and `Prec_rate`. Concentrations, counts, mass, LWC, habit and the size
distributions do not depend on `P`.

### What the correction does

`sd_file_at_pressure` runs the port's **own, unmodified** `arrayprobe.sizedist.run()` with the
production call behind the archived product — imported from `conc_arear_fix` rather than restated, so the two modules
cannot drift — changing only the eighth argument. Called with `ORACLES_DRIVER_PRES` it reproduces
the faithful file; called with a pressure in hPa it produces the corrected one. No input file is
modified and nothing in `arrayprobe` changes.

`compare_vt` measures the difference between two such files and, equally, the *absence* of a
difference everywhere else. `vt_ratio_table` reproduces the unchecked pressure unit's own published table.

**The pressure is the caller's to supply, and that is a finding rather than caution.** The SPEC
decode writes a nine-column `.tas.csv` — `readers/spec.py`'s `tas` sidecar carries `timehhmmss,
tas, time, nTWM, nSCM, nHOL, nVOL, nVPD, nHPD` — and **no pressure and no temperature at all**.
That is why the driver hard-coded a constant. There is no pressure record in this chain to
recover, so a corrected value has to come from aircraft housekeeping the caller holds.

### `9e5` has two readings and they differ by 10×

The earlier description was inconsistent on this point, and the module keeps both.

* Read literally as Pascals, `9e5` Pa is **9000 hPa** — nine atmospheres. `AS_PASCALS_HPA`.
* Read as the "nominal 900 hPa" the unchecked pressure unit's prose describes, it is **900 hPa**, a plausible P-3 flight
  level. `NOMINAL_900_HPA`.

The unchecked pressure unit's published ratio table was computed under the *first* reading — reproduced here exactly, which
is how the ambiguity was found — so its headline "1.7×–6.7× low" is the **smaller** of the two
errors. Under the 900 hPa reading the same table runs to **13.9×** at 300 µm. Neither value is
asserted; the module refuses to choose, and `pa_to_hpa` is offered but never applied to
`ORACLES_DRIVER_PRES` internally (a test pins that, so a later edit cannot quietly adopt one).

### How it is proved

**The "before" side is the port's own output, from a different place than the correction.** A
fresh `sd_file_at_pressure(..., pressure=ORACLES_DRIVER_PRES)` run is asserted equal — every
variable, NaN for NaN — to the production `sd` file already on disk, before any corrected number is
compared against it. Measured on two real flights:

| file | proc size | fresh run == on-disk `sd` | `vt`/`Prec_rate` cells moved | other variables moved |
|---|---|---|---|---|
| `base160906064403` | 16 MB | **yes, all 25 variables** | 505 of 505 non-zero | **0 of 23** |
| `base160914093925` | 512 MB | **yes, all 25 variables** | 706 of 706 non-zero | **0 of 23** |

So the grep-derived scope claim is a whole-file measurement on two files, not a reading of the
source. Corrected-over-faithful ratio, under the Pascal reading:

| file | min | median | max |
|---|---|---|---|
| `base160906064403` | 1.75 | 3.49 | 6.05 |
| `base160914093925` | 1.75 | 2.41 | 4.97 |

and under the 900 hPa reading, 1.88–11.34 and 1.88–8.00. The minimum is 1.753 on both files —
the small-particle asymptote, reached by the bin-1 particles that dominate both — while the
maximum tracks the largest particle present, which is why it is a property of the file rather
than of the correction. **The error is monotone in size and spans a factor of 3–4 within one
file, so it does not cancel in a ratio or a mass-weighted mean.**

### What it does not claim

**No archived combined product is affected, and that is measured.**
`base160906064017.combined.H.2DS_2.cdf` holds ten variables — `Counts`, `Size Distribution cm-3`,
`Number Concentration cm-3`, `Reject Ratio`, `Mean Area Ratio`, the four bin variables and `Time
Vector` — and **`vt` and `Prec_rate` are not among them.** The combine drops both. The defect is
confined to the per-file `sd` products and to anything published from those two variables.

**It is not validated against MATLAB output at the corrected pressure**, because no such file
exists and none can be made without a licence. Only the faithful side has an external anchor.

**On the v3.5 engine.** `single_vt.m` is byte-identical between v3.1.4 and
v3.5, so the finding and its line numbers (`sizeDist.m:1167`) transfer untouched.
`pipeline.py`'s `_APPLIERS` wires this module (`_apply_pressure_units_fix`, an `sd`-stage rerun),
but it always records a named skip today: neither tracked demo `.call` sidecar carries a pressure
field, so the applier refuses rather than reach into the run's preset (`pres_pa=9e5`) and pass a
guessed value off as provenance-verified. On the dense v3.5 reference it is therefore **vacuous**
(`docs/measurements.json`'s `v35_pressure_units_fix`) — run pressure is not recoverable from the
`.call` stamp on either engine.

**It does not know the right pressure**, for the reason above: nothing in this chain recorded one.

**It corrects a unit, not the physics.** The corrected `vt` is still Heymsfield & Westbrook (2010)
over a UIOOPS habit-derived mass, with `single_vt.m:13`'s truncated `pi=3.1415926` (the truncated pi literal)
preserved. Whether that terminal velocity is right for a given particle is a separate question.

**Both measured files are 2D-S.** The HVPS driver (`runsizedist.m`) passes the same `9e5`, and the
HVPS spans a much larger size range, so its ratio range is expected to be wider — but that is
reasoning from the size dependence, not a measurement, and no HVPS A/B was run.

---

# `reshape_fix.py`

*(was `reshape_fix_design.md`)*

## Design: recovering `mean_area_ratio`'s scrambled cells

**Status: design + implementation, 2026-08-27.**

### The finding

`sizeDist.m:1981` writes `mean_area_ratio` (and, per the same code pattern, its `REJ_` twin
and the `mean_aspect_ratio_*` variables at `:2002-2004`, when `iCreateAspectRatio` is on --
see the ungated rejected aspect ratios) without the transpose every neighbouring `putVar` call has. The variable is
declared `(num_bins, length(tas))`; the array MATLAB passes is allocated the other way round,
`(length(tas), num_bins)`. MATLAB does not error on a shape mismatch with the right element
count -- it fills the variable in column-major linear order from the array's own column-major
linear order. The result is **not** a transpose (values on the wrong axis, still paired
correctly) but a **reshape**: values land at essentially arbitrary `(time, bin)` coordinates,
including seconds and bins that have no particles in them at all.

Reconfirmed here on the real `base160906064403` production sd file: 53 of 4,110 seconds show
a finite `mean_area_ratio` value, and 50 of those 53 have zero accepted particles that second
(`n == 0`) -- the values are not just misplaced, most of the visible cells are in seconds
that shouldn't have *any* value at all. `mean_perimeter` (`:1982`, correctly transposed, a
very similar per-bin accumulation) has 94 finite seconds, all of them `n > 0`.

### Is this recoverable? Yes — verified empirically, not assumed

A reshape (unlike data loss) is invertible when the reader knows both shapes: the file
contains the *same* flat sequence of numbers a correctly-shaped write would have produced,
just addressed with the wrong shape. Recovering the correct array means reinterpreting that
flat sequence with the shape it was actually computed in.

**Found by brute-force search over reshape/transpose combinations, scored against the
`n > 0` ground truth** (a second is either genuinely occupied or it is not — this is the
same oracle-free physical-invariant strategy `hole_edge_swap.py` used, since there is no
"corrected" MATLAB run to diff against anywhere):

```python
recovered = raw_array.reshape(n_bins, n_time, order="C").T
```

This is the ONLY combination tried (row-major reshape to the variable's declared
`(bin, time)` shape, then transpose to this port's `(time, bin)` convention) that matches
perfectly: **4,110 of 4,110 seconds agree with `n > 0`, and the recovered array has exactly
94 finite seconds** (matching `n > 0`'s own count, not just its pattern). Two more
independent checks, neither built into the search: the recovered array populates **exactly
26 bins**, matching `mean_perimeter`'s own bin count precisely (both accumulate over a very
similar per-bin particle mask); and every recovered value falls in a physically plausible
area-ratio range (0.50-1.27 -- area ratio is nominally bounded by 1, and a discretized,
diode-array-derived shape ratio exceeding 1 slightly is consistent with other bounded ratios
already documented elsewhere in this project as not perfectly bounded at the pixel level,
not a sign the recovery is wrong).

### What this module does NOT do

- **Does not touch `src/arrayprobe/`.** `sizedist.py` continues to reproduce the
  scrambled write exactly, per the fidelity doctrine.
- **Does not recompute anything.** Like `hole_edge_swap.py`, this is a pure relabeling of an
  already-written array -- the values MATLAB computed were correct, only the final `putVar`
  call misplaced them.
- **Only `mean_area_ratio` is validated against real data.** The finding names three more
  variables (`REJ_mean_area_ratio`, `mean_aspect_ratio_*`, `REJ_mean_aspect_ratio_*`) affected
  by the identical code pattern (`:2002-2004`), but none of them are present in any sd file
  this port has actually produced -- they are gated behind `iCreateAspectRatio` (the ungated rejected aspect ratios),
  which the archived product's production configuration leaves off. The correction function is written
  generically (any `(time, bin)`-shaped array written by the same bug) so it applies to those
  variables too if a caller ever has one, but that path is untested against real data and
  should be treated as unverified until it is.

### Interface

```python
from arrayprobe_enhancements.reshape_fix import correct_reshaped_time_bin_array

recovered = correct_reshaped_time_bin_array(raw_mean_area_ratio, n_bins=128)
```

Takes the raw `(n_time, n_bins)` array as read from the sd file (this port's/ncio's
convention) and the declared bin count (needed because the function must know the shape the
variable was declared with to reverse the reshape -- unlike the hole-variable swap, this correction
is not shape-symmetric). Returns the recovered `(n_time, n_bins)` array.

---

# `rollover_fix.py`

## Design: applying the midnight rollover at every decrease

**Shipped 2026-09-01.**

### The finding

`sizeDist.m:83-84` (the TAS-derived `timehhmmss`) and `sizeDist.m:544-545` (the proc file's own
per-particle `Time`) both write the midnight correction as

```matlab
x(find(diff(x)<0)+1:end) = x(find(diff(x)<0)+1:end) + 240000;
```

`find` returns every decrease; MATLAB's colon operator then collapses each vector operand to its
**first element** (`[3 7 9]:[4 8 10]` is `3 4`). So the statement corrects the first decrease and
no others while reading as though it were vectorised — the same trap as `sizeDist.m:1036`/`:1169`
(the shattering reacceptance loop). The port reproduces it in
`arrayprobe.sizedist._rollover_240000`, which says so in its own docstring.

### What the correction does

`corrected_rollover(x)` adds `+240000` to the tail beginning at *each* decrease, cumulatively.
Because a constant is added to a whole suffix, the set of decreases in the raw array is exactly
the set the corrected pass walks, so the one-pass form `x + 240000 * cumsum(diff(x) < 0)` (with a
leading zero) is equivalent to walking the decreases in order — asserted against a literal walk
over 20 random arrays in `test_rollover_fix.py`, not argued.

`rollover_report(x)` is the diagnostic: how many decreases the array has, how many the original
corrects (0 or 1), and how many day boundaries it leaves behind.

### The "before" side comes from the port, not from a second transcription

`matlab_rollover` exists so an A/B has a faithful side without reaching into the port's private
names at run time. It is asserted equal to `arrayprobe.sizedist._rollover_240000`, element for
element, on six cases including the empty array, a no-decrease array and a monotonically
decreasing one. That is the check drawing its two sides from different places.

### What it does not claim

**It has no effect on any data held in this repository, and that is measured.** The first-midnight-only rollover's
addendum checked both call sites directly across all six validated 2016 field-campaign flights: every
flight's TAS `timehhmmss` and every flight's per-particle `Time` are non-decreasing over their
whole span — zero decreases, six flights, both arrays. There is therefore no A/B, no recovered
particle count, and no claim that any archived product would change. The correction is for a
campaign whose flights cross midnight; none of the ones here do. It is listed under
`correction_coverage.unmeasured` in `paper/paper_numbers.json` for exactly that reason.

**It does not distinguish a midnight crossing from a clock glitch** — neither does the MATLAB.
`min_drop` is offered so a caller can require a decrease of a stated size before calling it
midnight, but it defaults to `0.0`, which is the source's own rule. Choosing a threshold is a
science call the module does not make for the user.

**On the v3.5 engine.** Read directly against v3.5: the two rollover
halves diverged. The per-second `timehhmmss` rollover this module corrects is still byte-for-byte
the original defect (`sizeDist.m:130-131`, unchanged from v3.1.4). The particle-time half
(`image_time_hhmmssall`) loops in v3.5 over every decrease via `decreasedTimeInds`
(`:788-799`) — that is the half v3.5 fixed (`arrayprobe_uiops/sizedist.py:172-215`,
`fix_multiday_particle_times`, which still stops at the first genuine crossover it finds) — so this module still corrects only the
surviving `timehhmmss` half on v3.5. Not wired as a driver adapter (an in-memory function, not a
proc/sd file pair). Not in `docs/measurements.json`'s `v35_*` keys; `docs/applicability_matrix.md`
says "not measured against v3.5 (deferred)" rather than a fabricated number — no v3.5
flight held here crosses midnight either.

---

# `spot_edge_fix.py`

*(was `spot_edge_fix_design.md`)*

## Design: correcting the `spot_edge(147)` table typo

**Status: design + implementation, 2026-08-27.**

### The finding

`calculate_reject_unified.m:54` declares the `spot_edge` lookup table with a missing decimal
point: `..., 0.751, 0757, 0.763, ...` -- MATLAB parses `0757` as the integer 757, not `0.757`.
The table is searched with `find(spot_edge < ratio, 1, 'last')`, and because 757.0 is larger
than any physical ratio, the search for any `ratio` in `(0.757, 0.763]` stops one entry short
of where a corrected table would land, so `part_z` comes out one `z_d` grid step (0.05) low
for those particles. `arrayprobe.reject.SPOT_EDGE` reproduces the literal value (`757.0` at
index 146) faithfully, per the fidelity doctrine.

### Why this needed the swapped hole variables' correction first

The table is searched with `ratio = max_hole_diameter / edge_at_max_hole` -- an internal
MATLAB/port value, never itself written to any file. But **the swapped hole variables** (already shipped,
`hole_edge_swap.py`) established that the two variables which *feed* this ratio are
written to the wrong netCDF slots: what a proc file calls `max_hole_diameter` actually holds
the true `edge_at_max_hole`, and vice versa. The internal `ratio` computation inside
`imgProc_sm`/`sizeDist` uses the correct, unswapped values (the hole-variable swap is a write-time bug, downstream
of this computation) -- so recovering `ratio` from a proc file's *raw* columns requires
undoing the hole-variable swap first, or the recomputed ratio would be the reciprocal of the true one
and every lookup would be wrong.

**Verified directly, not assumed**: recomputing `part_z` from each flight's raw
`max_hole_diameter`/`edge_at_max_hole` columns -- after applying `correct_hole_edge_swap` --
through the *unfixed* `SPOT_EDGE` table reproduces every stored `part_z` value exactly, on
every one of the 11,684 particles across all six validated flights that went through this
branch (`part_z > 0`). That is strong evidence the derivation (unswap, then ratio, then
table search) is exactly right, independent of whether the missing decimal in spot_edge fix itself changes anything.

### The result on real data: zero particles affected, and that is worth stating plainly

Running the *corrected* table (`SPOT_EDGE[146] = 0.757`) against the same 11,684 particles
finds **zero** whose `ratio` falls in the vulnerable `(0.757, 0.763]` band, on any of the six
validated flights. The bug is real, the correction mechanism is built and rigorously
verified (it reproduces the buggy output exactly when applied with the unfixed table), but it
has had **no actual consequence on any 2016 field-campaign flight validated so far** -- upgrading the
original finding's "bounded consequence" language from a theoretical bound to a measured one.
Per this project's own upstream-feedback doctrine ("include what turned out to be fine"),
that is exactly as worth recording as a confirmed instance would have been.

This module is shipped anyway, not held back for lack of a live example: the mechanism is
correct and tested, and a future flight (or a colleague's own dataset) could hit the band the
six validated flights happen not to.

### What this module does NOT do

- **Does not touch `src/arrayprobe/`.** `reject.py`'s `SPOT_EDGE` keeps the
  literal `757.0`, per the fidelity doctrine.
- **Does not recompute the full Korolev branch.** `calculate_reject_unified.m`'s hollow/
  Korolev logic has several gating conditions beyond the table lookup itself (habit-dependent
  hole-ratio caps, the diode-direction corroboration check that produces reject code `'i'`,
  etc. -- see `reject.py:1029-1066`). This module only recomputes the table-lookup step
  (`part_z`, `size_factor`) for particles the caller has already identified as having reached
  it -- in practice, particles with a stored `part_z > 0` (the branch's own signature; every
  other code path sets `part_z` to `0.0` or `-1.0`). It does not re-derive which particles
  reached the branch from more primitive data.

### Interface

```python
from arrayprobe_enhancements.spot_edge_fix import correct_part_z_size_factor

corrected_part_z, corrected_size_factor = correct_part_z_size_factor(
    raw_max_hole_diameter, raw_edge_at_max_hole, stored_part_z,
)
```

Takes the three arrays as read directly from a proc file (raw, hole variables still swapped) and returns
corrected `(part_z, size_factor)` arrays, same shape as the input: unchanged wherever
`stored_part_z <= 0` (the particle never reached the Korolev branch), corrected wherever it
did.

**On the v3.5 engine.** `classify_findings_v35.py` reports the missing decimal in spot_edge
still-present in `calculate_reject_unified.m`; the same table, verbatim, exists in
`arrayprobe_uiops/reject.py`, and the module reads its tables from there (`_Z_D`, `_EDGE_0`,
`_SPOT_EDGE`) with a local `find(..., 1, 'last')`, so it runs on the v3.5 engine and imports
nothing from the earlier translation. `enhancements_uiops/tests/test_spot_edge_fix_v35_tables.py` asserts those tables
against a parser-written golden of the vendored v3.5 MATLAB and, where the earlier translation is
installed, against its copies.
`calculate_reject_unified.m:62` forces `handles.rej_hollow = 1` unconditionally in v3.5, so unlike
v3.1.4's production config (`rej_hollow=0`) the hollow block this correction depends on always
runs under the stock v3.5 driver. Not wired as a driver adapter (an in-memory function operating
on proc columns already in hand, not a proc/sd file pair `pipeline.py` copies). Not in
`docs/measurements.json`'s `v35_*` keys; `docs/applicability_matrix.md` says "not measured
against v3.5 (deferred)" rather than a fabricated number.

---

# `tas_grid_fix.py`

*(was `tas_grid_fix_design.md`)*

## Collapse duplicated TAS seconds (`tas_grid_fix.py`)

**Shipped 2026-08-29.**

**Protective default.** On probes with no archived product (probetypes 0, 1 and 3)
`scripts/run_flight.py` applies this correction by default in stage 4 — the driver applies it,
not the enhancement pipeline, which has no adapter for it (`DRIVER_PROTECTIVE`). With a TAS source
chain (`--tas-source`) it selects the regular TAS grid, which also fills skipped seconds; without one it
passes the probe's `tas.csv` through `collapse_tas_grid`. The size-distribution stamp records
`tas_grid=regular` or `tas_grid=collapse`, and `--protective off` skips it. The archived product's 2D-S/HVPS lineage
never gets it.

**Finding.** `sizeDist.m:476` sets `one_sec_times = tas_time`; `:88` floors the housekeeping
times to whole seconds. Two housekeeping packets in one second give two identical grid entries —
the first spanning the empty interval `[t, t)` — while `:627-644` still consumes that column's
particle block. Every particle in a duplicated second is counted nowhere.
The duplicate TAS-second particle loss has the measurement and the archived product's confirmation.

**What it does.** Collapses the `(tas, timehhmmss)` pair to one row per whole second, keeping the
first row of each second (MATLAB's own `unique(..., 'first')` convention, used at `:593`). The
port is not modified: the enhancement changes the *input*, then `arrayprobe.sizedist.run` runs
unmodified over a grid whose intervals are all non-empty.

**Validation, with no oracle available** — the archived product cannot adjudicate this, because
it exhibits the loss:

1. `empty_intervals` returns none after the collapse, on the real TAS file as well as synthetic
   ones, and every second survives exactly once;
2. the first row of each second is kept with its own `tas` value; a clean grid is returned
   unchanged (a no-op where the defect is absent);
3. **A/B on real data** (`tools/tas_grid_ab.py`, `base160906104932`): the port's own `sizeDist`
   run twice, grid as read then collapsed, recovers **+4,070 used-bin particles (+5.89 %)** and
   +399,339 over all bins (+4.14 %).

**Breadth, measured 2026-08-29 with `tools/tas_grid_impact.py`** (seven files, both flights —
every one affected). **The sample has since grown to 34 files over 11 flights and both deployment
years, and "every one affected" did not survive it**: `base160925114214` duplicates 0.0 % of its
grid, making it 33 of 34, with the mean falling from 9.8 % to 7.5 %. The seven-file table below is
kept as measured; `paper/figures/fig3_duplicated_grid_seconds.py` and the `A17` entry (the duplicate TAS-second particle loss) in
`paper/paper_numbers.json` carry the current breadth.

| stem | TAS rows | unique seconds | duplicated | accepted particles in them | of which bins 6+ |
|---|---|---|---|---|---|
| `base160906064403` | 4,110 | 3,854 | 256 | 15 | 1 |
| `base160906075333` | 7,519 | 6,950 | 562 | 335,994 | 4,086 |
| `base160906104932` | 7,483 | 7,076 | 400 | 1,210,698 | 32,831 |
| `base160910071623` | 11,120 | 9,980 | 1,125 | 217,507 | 1,349 |
| `base160910102201` | 431 | 404 | 27 | 72,940 | 703 |
| `base160910102921` | 5,788 | 4,919 | 868 | 476,018 | 3,691 |
| `base160910124240` | 9,891 | 8,334 | 1,516 | 105,167 | 217 |

**A/B across four files** (`tools/tas_grid_ab.py`, the port's own `sizeDist` run twice per file):

| file | grid rows → unique | all-bin recovered | used-bin recovered | accepted particles in duplicated seconds (used bins) |
|---|---|---|---|---|
| `base160906104932` | 7,483 → 7,076 | +399,339 (+4.14 %) | **+4,070 (+5.89 %)** | 32,831 |
| `base160906095907` | 3,021 → 2,728 | +156,977 (+2.12 %) | +548 (+3.03 %) | 14,268 |
| `base160910071623` | 11,120 → 9,980 | +87,302 (+8.28 %) | +167 (+1.87 %) | 1,760 |
| `base160910124240` | 9,891 → 8,334 | +35,328 (+10.68 %) | **+2 (+0.34 %)** | 180 |

**The two columns do not track each other**, which is the point worth carrying: the file with the
largest all-bin recovery (`124240`, +10.7 %) has the smallest used-bin recovery (+0.34 %, two
particles). What a corrected grid restores is overwhelmingly small particles. And the fraction of
the pre-filter "accepted in duplicated seconds" count that survives `sizeDist`'s own cuts into the
used bins ranges from **1 % to 12 %** across these four files — an earlier note here put it "on
the order of a tenth", which was too tidy.

**The two numbers, and why both are given.** The duplicated seconds contain 32,831 accepted
particles in the used bins, but only 4,070 survive `sizeDist`'s area-ratio and inter-arrival
cuts. The first number says what the grid discards; the second says what a corrected grid adds
to a published distribution. Quoting only the first overstates the effect roughly eightfold —
the same trap the dropped final raw record set earlier the same night.


### Applying it moves the output *away* from the archived product — by design

The archived products exhibit the duplicate TAS-second particle loss themselves, so correcting the grid necessarily disagrees with
them. Measured on `base160906095907`, combined and compared against the archived product both
ways:

| | non-zero used-bin cells | agreement |
|---|---|---|
| as the port ships (faithful) | 4,524 / 4,535 | **99.7574 %** |
| with `tas_grid_fix` applied | 4,530 / 4,675 | **96.8984 %** |

Note what moved: the number of *matching* cells went **up** (4,524 → 4,530), and agreement went
**down**, because the correction restores particles into seconds where the product has none — so
the denominator grows faster than the numerator. All-bin agreement falls the same way, 99.81 % →
94.04 %.

**This is the whole reason the correction is an enhancement and not a fix.** The same output is
simultaneously more correct and less faithful, and a project whose value rests on reproducing the
software of record cannot quietly choose the first. A user re-analysing data may well want the
corrected grid; a user reproducing a published product must not have it applied silently.

### The three unexplained particles: closed as unresolvable, 2026-08-30

Across `104932`'s 400 duplicated seconds the archived product holds 3 particles where this port
holds none. The open question was whether the product's own run used a different TAS grid there.

**It cannot be answered from anything we hold, and that is a measurement rather than a
guess.** The combined product carries **10 variables and zero global attributes**; the only
time-related one is `Time Vector`. It records no TAS array, no grid, and no processing
provenance — and we do not have the product's intermediate `sd` files or the TAS input its run
used. There is no artifact on this machine that could distinguish "a different grid" from "the
same grid with a different block alignment".

So this stays open only in the sense that a fact about 2016 is unrecoverable, not in the sense
that a run would settle it. Scale, for proportion: 3 particles against `104932`'s used-bin total
of 69,117. Whoever ran the original processing could answer it in a minute; nobody else can.

**On the v3.5 engine.** Read directly against v3.5: `sizeDist.m:135`
still carries the finding, still present per the classifier and confirmed by direct read. Not
wired as a driver adapter today: `pipeline._RunOutputs` carries no `.tas.csv` path, so an sd-rerun
applier would need `locate_outputs` extended to find `<raw_stem>.tas.csv` — not built this stage
(the same gap `pressure_units_fix` documents). Not in `docs/measurements.json`'s `v35_*` keys;
`docs/applicability_matrix.md` says "not measured against v3.5 (deferred)" rather than a
fabricated number.

---

# `wide_hollow_fix.py`

*(was `wide_hollow_fix_design.md`)*

## Design: a probe-width-independent hollow test

### The finding

`is_it_hollow` and `is_it_hollow_sidescan` (`calculate_reject_unified.m:465-466`, `:283`) pack a
particle's shadow into a fixed 32-bit word before testing whether a remembered hole is still
open. Both the 2D-S and the HVPS have 128 diodes. For a particle lying entirely beyond diode 32,
every packed word is zero, `zero & zero == 0`, and the code reads a zero result as "the hole
closed over" — so the particle is ruled **hollow on no evidence**, not simply un-scanned.

**Measured real-data frequency, 2026-08-27** (the diode-32 hollow test's addendum): 75.7% of
particles on real field-campaign flights start beyond diode 32; 4.34% of those are flagged hollow, a
1.67–1.85× elevation over the within-32 control. Real and non-trivial, but the ratio alone can't
say what fraction is this bug specifically versus beyond-32 particles genuinely being more often
holed — that needs a direct before/after count, which is what this module provides.

**Also confirmed (corrected 2026-08-27): this bug was live on the real archived
product**, not neutralized by campaign configuration. An earlier read of the field campaign's production variant's
`rej_hollow=0` edit as the real campaign's configuration had it backwards — that edit is dated
over a year after the campaign, and reproducing the archived `base160906064403` product exactly
required the *default* `rej_hollow=1`. The hollow-test path was active on real field-campaign data.

### What a correction is, precisely

The packing itself is not the bug — intersecting two bit patterns to ask "does this slice's hole
share any pixel with the remembered one" is the right test. **The bug is packing only diodes
1–32 regardless of the probe's actual width.** The fix is the natural generalization: pack the
*whole* diode row, not a fixed 32-bit slice of it.

`arrayprobe.reject._pack(row, start1, stop1)` already supports an arbitrary range — the
hardcoding lives entirely in the four call sites that fix `start1`/`stop1` at `1`/`16`/`17`/`32`
(`reject.py:478-479` in `is_it_hollow`, and the `im_width2`-capped equivalents in
`is_it_hollow_sidescan`). Python integers are arbitrary-precision, so there is no MATLAB-style
32-bit word limit to work around — a single `_pack(row, 1, n_diodes)` call replaces the
split-into-two-16-bit-halves dance, for any `n_diodes`.

One second-order effect falls out of this for free: `is_it_hollow`'s `hole_size` (`:490`,
`np.count_nonzero(old)`) already counts the *whole* row, not just the first 32 diodes — a
mismatch the reject.py docstring already flags ("the two sides of `cover_size <= .65 *
hole_size` are measured over different diode ranges"). Widening the packing to the whole row
makes `cover_size` and `hole_size` measure the same range again, correcting that asymmetry as a
byproduct rather than a separate fix.

`is_it_hollow_sidescan` has a second, distinct piece of hardcoding beyond the packing width: its
own image-start/end search loop is capped at 32 (`reject.py:581`, `_is_it_hollow_sidescan_reference`),
so on the diode axis only the first 32 diode-histories are ever scanned to *find* the particle's
extent, not just to pack it. Both the packing width and this loop bound need to scale with the
real diode count for the sidescan direction to stop being width-limited.

### What this module does NOT do

- **Does not touch `arrayprobe.reject`.** The port stays bug-for-bug faithful; this is a
  standalone reimplementation in `enhancements_uiops/`, built from the same primitives
  (`arrayprobe.reject.scan_slice`, `_pack`, `_popcount`, `mask_start_end` — all already
  width-general, imported directly rather than duplicated) so the two never drift on anything
  except the packing width.
- **Does not change any UIOOPS-written file.** Like every other item in this backlog, it is a
  function a caller opts into, not a flag threaded through the core module.
- **Does not claim to know the "true" hollow/not-hollow answer for a beyond-32 particle a priori.**
  It reports what the corrected packing computes; whether that's more physically correct is
  argued from the mechanism (a genuine intersection test over the real diode range, versus a
  zero-evidence default) and from the measured before/after shift, not asserted independently.

### Validation strategy

No MATLAB oracle exists for the corrected behavior — by construction, no MATLAB run has ever
scanned beyond diode 32 correctly. Two things ARE checkable without one:

1. **Equivalence where the fix is a no-op.** For a particle whose entire shadow lies within
   diodes 1–32 (real, common on any file — most particles are small), the corrected packing
   covers exactly the same range the original did, so the two implementations must agree
   bit-for-bit. This is the primary correctness check: it proves the reimplementation is a
   faithful generalization of `is_it_hollow`/`is_it_hollow_sidescan`'s actual algorithm, not an
   independently-invented one that happens to also reject a hole.
2. **The direct before/after count the measurement addendum above calls for.** Run both
   `arrayprobe.reject.is_it_hollow` (unfixed) and this module's corrected version over the same
   real particle population, split by whether the particle's bounding box starts beyond diode
   32. Report: how many of the unfixed function's `hollow` calls beyond diode 32 flip to
   `not hollow` under the real intersection test — the number the earlier 4.34%/1.67–1.85×
   measurement could not produce on its own, since that measurement only ran the *unfixed*
   function and could not distinguish "correctly hollow" from "zero-evidence hollow."

Both directions are reported, including if the fix turns out to change little in practice — the
project's own precedent (the first-midnight-only rollover, the mismatched habit mass mask and the misreported shattering attribute all "checked, confirmed inert") is to state a null result as
plainly as a positive one.

### Interface

`enhancements_uiops/src/arrayprobe_enhancements/wide_hollow_fix.py`:

- `wide_is_it_hollow(shadow, slices, bits_per_slice)` — drop-in-shaped replacement for
  `arrayprobe.reject.is_it_hollow`, same `(status, edge_at_max_hole, max_hole_diameter)` return.
- `wide_is_it_hollow_sidescan(shadow_t, slices, bits_per_slice)` — same shape for
  `is_it_hollow_sidescan`, operating on the diode-axis-transposed array.
- Both take the real diode count from `shadow.shape[1]` (or `shadow_t.shape[1]` for the
  sidescan form) rather than assuming 32 or requiring it as a separate argument — the shadow
  array already carries the probe's real width.

---

# `zero_image_recovery.py`

*(was `zero_image_recovery_design.md`)*

## Keep scanning after a zero-image particle (`zero_image_recovery.py`)

**Finding.** `imgProc_sm.m:250` in the validation campaign's fork executes `break` when a particle has no
image, abandoning the rest of the image record; every later particle in it is lost and nothing
in the output says so. Stock v3.1.4 (`:542-544`) skips the particle and continues.
The abandoned zero-image record: 6 breaks in 700 real records, on the order of ten thousand
particles per raw file. The port reproduces both behaviours on one profile axis,
`FidelityProfile.zero_image_particle_recovery`, and counts every break it takes
(`arrayprobe.imgproc.ZERO_IMAGE_BREAKS`).

**What the enhancement is.** A composite profile, `ORACLES_PRODUCTION_RECOVER`: the production
configuration in every axis (reject thresholds, buffer guard, reader) with
`zero_image_particle_recovery=True`. `with_zero_image_recovery(profile)` builds the same for
any profile. Nothing in `arrayprobe` changes; `ORACLES_PRODUCTION` stays bug-for-bug.

**Why this is an enhancement and not a fix.** The validation campaign's products were made with the `break`;
reproducing them requires it. Recovering the particles changes the output — more particles,
different concentrations in the affected seconds — so it is opt-in, and a product made with it
is not comparable to the archive in those seconds.

**Validation — this one has a real oracle.** Stock MATLAB's own framing on the port's tracked
zero-image fixture (`tests/data/s3_zeroimg_stock_golden.nc`, Octave running the
unmodified stock `imgProc_sm.m`) frames 2 particles where the fork frames 1. Under the
composite profile the port frames 2 and takes no break; under production it frames 1 and
records one break. The profile-composition test asserts that no other axis moved.

**Magnitude, measured rather than extrapolated.** `scratch: a10_measure.py` runs `imgproc_sm`
on the first *N* records of a real dense file under both profiles and reports the particle
counts and breaks; the numbers are in `BACKLOG_STATUS.md`, row for the abandoned zero-image record.

**Measured — unlike the dropped final raw record, these particles do reach the used bins.** Over the same 2,000 records of `075333`, applying the production accept criteria to both procs: production 278,905 particles / 272,325 accepted / **7,601 in used bins (6+)**; with recovery 283,353 / 276,668 / **7,720**. So the abandoned zero-image record adds **119 used-bin particles per 2,000 records, +1.57 %** — close to its +1.6 % particle share, i.e. the loss is not size-biased and it does move a published size distribution.

**Not done.** Consequence on concentrations (sizeDist over a recovered proc vs. the production
one) — the same A/B obligation every enhancement carries; it needs a recovered proc for a
whole file, which is a ~25 h run per dense file and is queued behind the validation reruns.

# `intarr_threshold_fix.py`

**Corrects the global-minimum inter-arrival threshold** — `IntArrAnalysis_time.m:170-190` writes, as the inter-arrival threshold, the
bin centre where the *observed* counts are lowest anywhere inside
`(min(tau_std(1:2)), max(tau_std(1:2)))`. Two properties of that window make a global minimum
the wrong estimator: the window can span nearly the whole histogram when the fit puts `tau2`
below the first bin, and inside a wide window the histogram is not monotonic on either side of
the dip — it falls into the shattering/real crossover, rises through the real-particle mode,
then falls again into a sparse tail. A global `min` can land in the tail.

`crossover_threshold()` selects the **first interior local minimum** instead. Same histogram,
same fit, same window; only the estimator changes. `select_from_window()` exposes the selection
without the fit, so it can be exercised on a measured histogram shape rather than on whatever
window a fit happens to produce on synthetic data.

**Measured, on the finding's own numbers** (population 1 of `base160906064403`): the global
minimum is the sparse tail at 2.745e-3 s with 4 counts; the crossover dip is at 1.395e-6 s with
94. Three orders of magnitude apart.

**What it does not claim.**

* **No archived product of the validation campaign is affected**, and that is measured rather than hoped: the
  campaign's production call names a threshold file that does not exist, so `sizeDist.m:70` sets
  `iaThreshFile = 'NONE'` and `:874` falls back to the 6 µs per-probe default. The written
  threshold never rejected a particle in any product validated here.
* **No downstream consequence is measured**, for the same reason — measuring how many particles
  a corrected threshold accepts needs a run that consumes the threshold file, and that run has
  no oracle here.
* **It does not know the right threshold.** A first local minimum is a better estimator of a
  crossover than a global minimum over a wide window. It is still an estimator.
* **The choice is not always clean.** `n_local_minima` is reported so a caller can see when the
  histogram offered more than one candidate, rather than receiving a number that hides it. On a
  narrow window the two estimators agree and the correction is a no-op — asserted by a test, so
  the module cannot be credited with an effect it does not have.

---

# `intarr_policy.py`

New capability, not a correction. **Default OFF**, and OFF is
UIOOPS. The published basis, read from the chapter (McFarquhar et al. 2017,
*Meteor. Monogr.* 58, ch. 11, p. 11.21): the threshold between natural and shattered
inter-arrivals is defined three ways — "2 × t2", "the interarrival time between t1 and t2 with
smallest measured frequency of occurrence", and the one "with the smallest frequency of
occurrence based on fit curves" — and "when an artifact is identified through interarrival time
analysis, that particle and one or two adjacent particles are removed (depending on the selected
algorithm) … [this] can have a big impact on calculated N(Dmax)."

**UIOOPS already computes all three thresholds and writes one.** `IntArrAnalysis_time.m` (the
validation campaign's fork; `:159`, `:170-190`, writes `threshhold_ak` at `:367`) and stock v3.5
`IntArrAnalysis.m` (`:116`, `:146-147`, writes `threshhold_ak` at `:290`) both carry the three
rules as `threshhold`, `threshhold_ww` and `threshhold_ak`. So the rule switch invents no
threshold; it chooses which already-computed array `write_threshold_file()` puts in the file
`sizeDist` reads as its twelfth argument (a delegation to the port's own writer, so OFF is
byte-identical to it). Every flagging block in both engines rejects `(ix-1):ix` — the flagged
particle and its predecessor (v3.1.4 `sizeDist.m:1017`, `:1149`; v3.5 `:1194`, `:1326`,
`:1393`) — which is "one adjacent particle", so UIOOPS is `neighbours=1`.

| Option | Values | OFF (UIOOPS) |
|---|---|---|
| `rule` | `min_measured` (`threshhold_ak`), `twice_tau2` (`threshhold`), `min_fitted` (`threshhold_ww`) | `min_measured` |
| `neighbours` | 0, 1, 2 | 1 |

Turn it on explicitly: `InterArrivalPolicy(enabled=True, rule="min_fitted", neighbours=2)`.
Setting a rule or a count **without** `enabled=True` raises rather than being ignored. Entry points: `select_threshold`, `write_threshold_file`,
`flag_shattered` (one second), `flag_shattered_by_second`, `compare_policies` (the A/B).

**Two values are not quotations, and say so.** `neighbours=2` adds the *successor*: the chapter
says "one or two adjacent particles" without naming them, and a particle in a time-ordered stream
has exactly two neighbours, of which UIOOPS's one is the predecessor. `neighbours=0` is not in the
chapter ("one or two"); it is the no-neighbour baseline an A/B needs.

**Equivalence (OFF → identical).** Flagging is compared against the v3.5 engine's own
`flag_shattered_1hz` on 1,200 random seconds; the threshold file against the port's own
`write_threshold_file(threshold_ak)`, byte for byte. A mutation test shows the same comparison
fails at `neighbours=0` and `2`.

**A/B, measured on the dense demo flight** (`demo_flight_dense_raw.2DS`, v3.5 engine,
240 particles; designed gaps of 1.538 µs and 307.7 µs plus 20 record-start zeros). Particles
flagged `'S'`:

| rule \ neighbours | 0 | 1 | 2 |
|---|---|---|---|
| `min_measured` (UIOOPS) | 20 | **20** | 40 |
| `twice_tau2` | 20 | 20 | 40 |
| `min_fitted` | 68 | 116 | 184 |
| the 6 µs per-probe default (the validation campaign's production call) | 80 | **140** | 220 |

On this flight the bimodal fit is degenerate (two discrete gap values; fitted `tau(3) = 1`), so
`min_measured` and `twice_tau2` land below the 1.538 µs designed gap (1.3e-7 s and 2.4e-8 s) and
flag only the zeros, while `min_fitted` lands at 5.8e-6 s in four of five blocks and catches the
designed gaps. That is the monograph's "big impact" in miniature, on a flight built to have it —
a property of this flight, not a claim about real clouds.

**What it does not claim.** Which rule is right; the chapter itself says the impact "has not
been well documented". It changes no archived product of the validation campaign through the rule (the production
call consumed no threshold file), but the neighbour count does reach the 6 µs default path. The
A/B stops at the per-particle `'S'` flag and is not propagated to a binned concentration. The
re-acceptance floor the same page names ("most shattered particles are smaller than 500 µm
(Korolev et al. 2013b,c)") already ships in `poisson_restore.large_particle_reacceptance_floor`
and is not duplicated.

---

# `dmax_sensitivity.py`

New capability, not a correction: reports how far UIOOPS's six `d_choice` diameter definitions
disagree on the same particle, and reconfirms the preserved int16 diameter saturation on real data
(`dmax_sensitivity_design.md`, `BACKLOG_STATUS.md` new-row). Measured on 99 real particles from the
tracked S4 fixture: mean relative spread across the six definitions 227.95 %, max 351.47 %, mean
absolute spread 0.388 mm (`docs/applicability_matrix.md`).

**On the v3.5 engine.** `applicability.py`'s row cites
`sizeDist.m:941-942` (the `double` cast the int16 diameter saturation also cites) and `:1054-1066` (the `d_choice` branches)
as the v3.5 sites, read directly against the vendored v3.5 tree. Declared `APPLIES` on both
engines — a new-capability module correcting no defect, so no version axis blocks it; the read
establishes that the six `d_choice` branches it compares still exist in v3.5's `sizeDist.m`, not
that any number differs there. Not wired as a driver adapter (a reporting function over an
existing proc/sd pair, not a file it writes). Not in `docs/measurements.json`'s `v35_*` keys; the
matrix's fifth column says "opens cleanly on the v3.5 demo reference; capability, no number to A/B
this stage" rather than a fabricated spread number on v3.5 data.

---

# `particle_clustering.py`

New capability, not a correction: unsupervised k-means over per-particle image features, used by
the triage server's `/clusters` bulk-labelling route (`BACKLOG_STATUS.md`; no lettered finding —
tooling, never applied to output).

**On the v3.5 engine.** `imgProc_sm.m:455-458` in the vendored v3.5 tree,
opened directly: the whole `image_diam_circle_fit` `defVar` call is commented out, so v3.5 does
not write one of the nine proc columns `extract_features` reads by name
(`particle_clustering.py:85-95`). `applicability.py`'s row was corrected this stage to cite the
real read (`extract_features` reads nine proc columns by name) in place of an earlier, wrong claim
that the module "operates on rendered images, not on either engine's internals" (flagged by the v3.5 read).
New `feature_names_for(engine)` returns the full `FEATURE_NAMES` on `"3.1.4"` and the same set
minus `image_diam_circle_fit` on `"3.5"`; `extract_features`/`cluster_flight` take `engine=` and
thread the resolved column list through instead of the module constant. On a v3.5 proc read
without `engine="3.5"`, the module raises `MissingProcVariable` — a named refusal, deliberately
not a `KeyError` subclass, rather than a bare `KeyError` (the discriminating test `test_v35_inputs`
was flipped to assert the named refusal). Whether the v3.5 feature set should drop
`image_diam_circle_fit` (what this module ships) or substitute `sphericity`, which v3.5 does write
(`arrayprobe_uiops/imgproc.py:258`), is open. Not wired as a driver adapter: a
`cluster_flight` adapter would write a labels sidecar rather than correct a file. Declared `APPLIES` on
both engines. Not in `docs/measurements.json`'s `v35_*` keys; on the dense v3.5 reference
`cluster_flight` opens cleanly (run in-test) but the matrix's fifth column says "capability,
no number to A/B this stage" rather than a fabricated medoid comparison.

# `reaccept_every_event_fix.py`

## Shattering reacceptance over every event in the second, v3.5's way (`reaccept_every_event_fix.py`)

**Default OFF** — `default_on` is False for every enhancement module, no exceptions
(`registry.py`'s `EnhancementSpec` docstring; `test_enhancement_opt_in.py::NothingIsOnByDefault`),
and the module's Python keyword defaults to `reaccept_every_event=False`. Turn it on with
`[enhancements] reaccept_every_event_fix = true`.

### The finding

`sizeDist.m`'s reacceptance block ("experimental option to reaccept particles flagged as
shattered which may in fact be the result of diffraction fringes", Stechman 2015, modified Finlon
2017) iterates `iEvent` over a colon range from `find(rBegin)` to `find(rEnd)`
(v3.1.4 `sizeDist.m:1036`). MATLAB's colon uses only the first element
of a vector operand, so only the **first** shattering event in a second is scanned, and when the
first `rEnd` precedes the first `rBegin` (an event at a block boundary, whose first inter-arrival
is the sentinel 0) **nothing** is. Sites (read):

| Version | Site | State |
|---|---|---|
| v3.1.4 | `sizeDist.m:1036` (`iaThreshType` 1), `:1169` (2) | defect; preserved in the port (`arrayprobe.sizedist._reaccept_shattered`) |
| v3.5 | `sizeDist.m:1213` (1), `:1346` (2) | defect, **unchanged** |
| v3.5 | `sizeDist.m:1403-1427` (3, new in v3.5) | **fixed by the developers** ("JF 11/5/25"): `find(rBegin,1,'first'):find(rEnd,1,'last')`, guarded by `rEndIdx >= rBeginIdx` (`:1418`) |

### What this module does

It applies the developers' own type-3 fix to the type-1 and type-2 paths of **both** engines:
one continuous bracket from the first `rBegin` to the last `rEnd`, one `maxParticle` across it,
**at most one `'R'` per second**, and no scan when the last `rEnd` precedes the first `rBegin`.
Where the developers fixed a finding in v3.5, their fix is the one to apply.

**Interpretation.** A *per-event* scan (one `'R'` per event) is not what v3.5 does, so this
module implements v3.5's bracket instead. Consequences: every event is reached and the block-start empty range is
gone, but two qualifying events in one second still give one `'R'` — the largest qualifying
particle anywhere in the bracket; particles between events are inside the bracket (they qualify
only with an inter-arrival below `reaccptMaxIA`, as in v3.5); an event beginning after the last
`rEnd` is outside it, as in v3.5. Type 1 compares against a **per-particle** threshold vector
where the type-3 block only ever had a scalar; `rBegin`/`rEnd` are computed elementwise exactly as
`:1204-1205` compute them, and the bracket is applied unchanged.

### How it reaches the engines — no port edit

Both engines look the function up at call time (v3.1.4 in its size distribution, which this package does not include;
v3.5 `arrayprobe_uiops/sizedist.py:534`, `:556` as `v314._reaccept_shattered`).
`bracketed_reacceptance()` rebinds that one attribute inside a `with` block and restores it in
`finally`. The alternative, a `reaccept_fn=` keyword on both `run()`s, would be a port edit; the
substitution needs none. v3.5's type-3 path calls `reaccept_shattered_1hz` directly and is
therefore untouched — it already carries the fix.

### Turning it on

* **Python** — `reaccept_every_event_fix.run_sizedist(sizedist.run, <the engine's own
  arguments>, reaccept_every_event=True)` (default `False`), or `with
  reaccept_every_event_fix.bracketed_reacceptance(): sizedist.run(...)`. Either engine.
  Demonstrated in `examples/7_analysis_and_outputs/08_enhancements_on_a_product.ipynb`.
* **Config file** — `[enhancements]` `reaccept_every_event_fix = true` resolves it ON. The
  `arrayprobe-enhanced run` driver has **no adapter** for it yet and records a named skip: re-running
  `sizeDist` needs the run's pressure and threshold file, which the `.call` stamp does not carry —
  the same gap `pressure_units_fix` records.

### Measured result (`tests/test_reaccept_every_event_fix.py`)

| Check | Faithful (engine) | This module |
|---|---|---|
| Octave case `reaccept_two_events_spanned` (7 particles, two events) — `eIndex`, 1-based | 3 (= real type-1/type-2 Octave runs) | 6 (= real type-3 Octave run) |
| 2,000 random constant-threshold seconds vs `reaccept_shattered_1hz` (port of `:1403-1427`) | — | identical on all 2,000 |
| `reacceptance_proc.nc` as two events in one second (gaps Q,B,Q,B,Q; v3.1.4 stock, `iaThreshType` 1) — `sum(count)` | **1** | **2** (the second event's 1.4 mm particle) |
| v3.5 `apply_shattering`, type 2 / type 3, on the two-event case | 3 / 6 | 6 / 6 (type 3 untouched) |
| OFF vs the bare engine | — | byte-identical file |

Two mutations were run and made the tests fire (recorded in the test module's docstring).

### What this module does NOT do

* **Inert on the validation campaign**: its branch (the campaign's production variant of `sizeDist.m`, not shipped, lines 250-274) sets
  `reaccpt_shatrs = 0`, so the archived reproduction never reaches reacceptance. It is live for the
  shipped campaigns that set `reaccptShatrs = 1` (PECAN, GPM, SOCRATES).
* No dense real-flight A/B: no held campaign file both reaches reacceptance and is tracked.
* It does not implement a per-event (one `'R'` per event) reacceptance; that is not v3.5's
  semantic and would need a new decision.

# `published_dof.py`

## The 2D-S depth of field from Gurganus & Lawson (2018), default OFF (`published_dof.py`)

**Default OFF** — `default_on` is False for every enhancement module, no exceptions
(`registry.py`'s `EnhancementSpec` docstring; `test_enhancement_opt_in.py::NothingIsOnByDefault`).
`arrayprobe-enhanced run` applies it only where a config names `published_dof = true`. Every
function here keeps `enabled=False`, as written.

**What the engine does.** `calc_sa_randombins.m` is byte-identical v3.1.4 ↔ v3.5 and ported once
(`src/arrayprobe_uiops/sample_area.py:84-88`): `:42` `DOF = 20.52*radius.^2*1000` for
probetype 2 (the 2D-S *and* the HVPS), `:44` `6*radius.^2/lambda` otherwise, `:47` capped at
`armdst`. No airspeed enters.

**What the papers say — both opened.** Gurganus & Lawson (2018, JTECH 35,
doi:10.1175/JTECH-D-17-0202.1): Eq. (1), p. 1534, `DOF = ± c r²/λ`, **c = 8 ± 0.2** for the SPEC
2D-128 (single-channel 2D-S), fit on 29–67 µm drops; Fig. 2 (p. 1536) droplet fit 8.11 ± 0.19,
Zemax 8.05 ± 0.09. The ± is a half-width (Fig. 2 plots `DOF_50%/2`; Fig. A2's "±8 r²/λ" box,
p. 1552), so the total is `2 c r²/λ` — derived, and SODA-2 writes the same
(`soda2_samplearea.pro:20`). Airspeed: 2D-S data ≥ 10 µm "at airspeeds up to 190 m s⁻¹ … are not
degraded by the time response" (p. 1550). CIP: no constant determined (manufacturer c = 3; CIP17
measured at about twice it, Fig. A2). Baumgardner & Korolev (1997, JTECH 14, 1224): the airspeed
algorithm — Fresnel shadow Eqs. (2)-(5), first-order roll-off Eq. (6) with τ ≈ 0.4 µs (NCAR 260X,
p. 1227), threshold 50 % (2D) / 67 % (1D) — and its fifth-order fit Eq. (7), p. 1228, Tables 1
(67 %) and 2 (50 %) at 20–160 m/s, "only valid for DOF ≤ 61 mm"; probes PMS 260X and 2D-C, HeNe
λ = 0.6328 µm.

**What ships.** 2D-S: `min(2 c r²/λ, armdst)` with c = 8, λ = 0.785 µm, airspeed-independent,
TAS > 190 m/s refused. The ratio to the engine for an uncapped bin is `16/(0.785e-3 × 20520)` =
**0.993283** (c band 7.8–8.2: 0.968451–1.018115): the engine's constant already sits inside G&L's
band (it implies c ≈ 8.054 at 785 nm). HVPS, CIP, PIP, 2D-C: refused by name. B&K's Tables 1-2
are transcribed (`bk1997_dof_mm`, tabulated airspeeds only; the PDF text layer renders every minus
as a leading "2", so signs were read off the page image and pinned by a monotonic-in-airspeed
test).

**Choices not in either paper.** (1) The 2D-S wavelength: taken from SODA-2
`soda2_probespecs.pro:955` and the Jeju-2024 README, not a SPEC
publication; Lawson et al. (2006) gives 0.8 µm only "for the sake of example". (2) B&K give no
rule between their tabulated airspeeds, and their τ = 0.4 µs is not a 2D-C's (760 ns measured,
Lawson et al. 2006) — so the 2D-C airspeed path is transcribed but not wired. (3) Applying Eq. (6)
to a profile (the full algorithm) is not specified beyond "this profile is then modified with
Eq. (6)".

**Equivalence.** OFF: `published_sample_area` returns `calc_sa_randombins`'s list exactly (four
probetype/armdst pairs × three `sa_method`s), and `corrected_sd_file` writes every variable
byte-identical on both demo references (`test_published_dof.Equivalence`).

**A/B consequence, measured** (`test_published_dof.Consequence`, TAS 150 m/s supplied by the test,
armdst 63 mm). `demo_flight_v314_sd.nc` is **particle-free** (`count` = 0 everywhere), so its
concentration A/B is vacuous: 11 of 128 bins uncapped (bin_mid ≤ 0.11 mm), their `sample_vol`
× 0.993283, the rest byte-identical. `demo_flight_v35_sd.nc` (2D-S 128-bin ladder from 0.01 mm,
the same 11 bins uncapped) holds particles in bins 4 (minR) and 2 (area-equivalent), both
uncapped: exactly those bins move (`conc_minR` and `n` × 1/0.993283, with the other
concentration, mass, area, habit, fall-speed and precipitation-rate variables), and every capped
bin and every unbinned variable but `n` is byte-identical. The other
non-vacuous case is `s4_sizedist_octave_golden.nc` (a real-data fixture, not distributed; 6 s of the validation campaign's 2D-S,
the Octave-built v3.1.4 sd golden): particles in bins 0, 1 (10, 20 µm, uncapped) and 122 (capped);
bins 0-1 of every volume-normalised variable × 1/0.993283 (**+0.676 %**), bin 122 byte-identical,
`n` up in the 2 populated seconds; `count`, `re`, `ar` untouched (computed before `sa2` exists).
**Mutation:** with `dof_ratio` patched to 1 the populated bins do not move
(`test_published_dof.Mutation`).

**Driver.** `pipeline._apply_published_dof` (sd stage, chained after any prior `.enh.sd.nc`): TAS
from the run's `<stem>.tas.csv`, `armdst` from `arrayprobe_uiops.sizedist_tables.probe_defaults` for
the file's own project/probe and the run's engine; no TAS sidecar, HVPS or TAS > 190 m/s are named
skips. Declared `APPLIES` on both engines (`applicability.py`).

# `partial_image_habit.py`

## Design: habit for accepted partial images (Korolev & Sussman 2000)

**Source, opened for every rule:** Korolev & Sussman (2000), *A Technique for Habit
Classification of Cloud Particles*, JAOT **17**, 1048-1057. Sect. 4b (pp. 1050-1051) sorts images
into tiny / rejected partial / complete / accepted partial; Eq. 1 gives `R1` for complete images,
Eqs. 2-4 give `R2 = P / P_circ` for partials (the in-frame perimeter of the circle the partial
would be, and a five-step shift-and-sum perimeter); Eqs. 5-8 retrieve habit *fractions* of an
ensemble by inverting a retrieval matrix; Eq. 9 combines the complete and partial retrievals. The
abstract's "~50 %" is the gain in classified images from using partials at all (p. 1056: partials
are ~35 % of accepted images, ~50 % of complete ones).

**What UIOOPS does today (read).** v3.1.4 runs `holroyd.m` on the truncated silhouette
(`imgProc_sm.m:807`); v3.5 withholds a habit (`'C'`) for centre-out images
(`imgProc_sm.m:1282-1285`) and, under the Schima et al. (2024) scheme, for edge contact above half
the diameter (`holroyd_new.m:101-104`), running complete-image rules on every other partial. That
is exclusion, not the paper's method, so there is no developer fix to delegate to; the module
applies to both engines' silhouettes identically.

**What is built, and the gap that stops the rest.** RABIT classifies populations, never single
particles (p. 1049), so the module writes no habit code onto any particle and corrects no column.
Built from the paper: the four groups, both ratios, the partial-circle perimeter, the retrieval,
Eq. 9, and `build_retrieval_matrix` (Eq. 6) for a new probe. **Not buildable:** a retrieval matrix
for the 2D-S or HVPS. The paper's matrices are the NRC OAP-2DC's (32 diodes, 25 um, vertical
beam), and p. 1057 says they do not transfer and that *"new retrieval matrices should be created
for different probe configurations"*. `classify_population` therefore raises
`NoRetrievalMatrixForProbe` on any other probe geometry. **The source needed** is a hand-classified
2D-S (and separately HVPS) training set of complete and partial images in RABIT's four categories
(sphere, irregular, needle, dendrite), or a published matrix for that probe -- none is held. The
triage server's verdicts are accept/reject labels, not habits, so they do not supply one as they
stand.

**Five readings, derived rather than transcribed** (module docstring): the group rules overlap
and leave gaps, and no precedence is invented -- an image matching zero or several rules is
counted and not retrieved; `N_y == 32` is read as the probe width; Eq. 2's `x1 == 0` case takes its
limit `theta1 = 0`; Eq. 4's padding and edge exclusion; Eq. 9 reads the 3-vector complete
retrieval as a zero dendrite fraction. **Eq. 4's shift direction was settled by measurement**:
read literally, two of four diagonal quadrants count as legs, digitised discs give `N_P / 2 pi r`
of 0.79-0.85 and partial discs `R2` of 0.79-0.90 -- inside the interval where the paper's basis
puts 4.7 % of partial spheres; with both along-flight shifts in one direction every diagonal reads
3 (p. 1052, Fig. 7 F), discs give 1.06-1.09 (the 8-connected chain-code over-estimate) and partial
discs `R2` of 1.03-1.06, inside the interval holding 94.7 %.

**Equivalence.** Off or on, every port output is the bytes the port wrote: the module has no write
path (`test_the_module_has_no_write_path`), leaves its input silhouettes unmodified, and reading
the tracked demo image/proc pair through it leaves both files' SHA-256 unchanged. There is no
driver adapter; `pipeline._NO_ADAPTER_REASON_BY_NAME` records why.

**A/B, dense demo flight: vacuous, measured.** `tools/partial_habit_ab.py` builds
`build_dense_demo_flight` (defaults), runs stages 2-3 and reconstructs all 240 silhouettes:
**0 shadowed pixels on either edge diode**, `image_touching_edge` 0 for all 240, 0 habit `'C'`;
RABIT's census gives 200 complete, 40 tiny, **0 accepted partials**. The generator places every
shape at diodes 16-111 by construction (`make_demo_flight.py:346-355`), so this flight cannot
exercise the enhancement; a non-vacuous A/B needs a flight with edge-touching particles and, for
fractions, a matrix for its probe.

**Mutations (each reverted after the run):** each mutation was run against this
module's tests and reverted; the record of which test failed for each is not shipped.

# `field2006_shatter.py`

## Design: Field et al. (2006) per-second inter-arrival fit, derived from NCAR Process2D

**What it is.** The Field et al. (2006) shattering correction as NCAR's Process2D implements it.
Process2D keeps the last 400 inter-arrival times, bins them into 40 logarithmic bins each second,
fits a double Poisson by damped Gauss-Newton and sets the shattering cutoff at `0.05 / a1`, with
the constant correction factor `1 / (2 exp(-pcutoff a1) - 1)`.

**Source.** Derived from NCAR Process2D, GitHub `NCAR/aircraft_oap`, `process2d/process2d.cpp`
(Apache-2.0): the 3x3 inverse at `:188-210`, the fit at `:215-300`, the queue at `:723-726` and
`:885-887`, the bins at `:736-739`, and the per-second histogram, fit and cutoff at `:915-934`.
Every function in the module cites the lines it transcribes, and precision follows the C (bins
float32, fit parameters double). Process2D-derived processing is an enhancement, never merged
into either engine.

**Applying it.** `apply(inttime, second)` fits each second and returns the per-particle reject mask
(particle and predecessor below the cutoff) with the per-second cutoff and correction factor;
`corrected_counts()` applies the factor; `write_diagnostics()` writes a copy of an sd file with five
`field2006_*` variables and a Process2D-derived stamp, every existing variable unchanged. One choice is
this module's, not transcribed: the final second, which no later particle closes, is fitted on the
queue as it stands at the end of input.

**The fresh queue fits to NaN, as in Process2D.** Process2D's initial queue `itq = {1}` gives 399
counts in bin 0 and one in bin 34; `ysum = 400` passes the low-count test (`process2d.cpp:236`), the
near-singular normal matrix lets the third damped Gauss-Newton step drive `a1` negative, `exp(-a1*x)`
overflows, and every parameter, the cutoff and the correction factor become NaN. The compiled
harness reports the same queue as not finite, and this module, measured, returns NaN
too: no difference, so no flag. A NaN cutoff rejects no particle and the factor applies as 1
(`:1075-1079`); the next second with 10 or more counts restarts from its own first guess. Test:
`test_field2006_shatter.test_fresh_queue_fit_diverges_to_nan_as_process2d_does`.

**Selecting it in a run.** Off by default. Name it in the run configuration's `[enhancements]`
table (`field2006_shatter = true`) and `arrayprobe-enhanced run` applies it at the sd stage
(`pipeline._apply_field2006_shatter`): it reads every particle's `inter_arrival` and
`Time_in_seconds` from the proc file, fits each second, and writes `<stem>.enh.sd.nc`, a copy of
the sd with the five `field2006_*` variables, every `conc*` variable on `Time` multiplied by the
per-second `corrfac` (NaN read as 1, `process2d.cpp:1075-1079`), the `field2006_stamp` attribute
naming it Process2D-derived, and `field2006_shatter` in `enhancements_applied`. The engine's own
proc and sd are never written, and its shattering pass is left as it ran: the per-particle
Process2D mask is not re-applied to the sd. A proc without `inter_arrival`, or with particles out
of time order, is a named skip. Tests: `tests/test_pipeline_field2006_adapter.py`, on synthetic
files.

**Oracle plan.** Today: `tests/test_field2006_shatter.py` (21 tests) pins the bin edges and
midpoints, the histogram's missing lower bound and 10 s drop, the fresh-queue zeros, recovery of a
known two-mode mixture, the constant correction factor, the low-count and no-fit returns, the
queue wrap at 400, and the application: the reject mask, corrected counts, and diagnostics written
beside unchanged variables. Next: compile `process2d.cpp`'s fit and histogram as a standalone C++ harness
and assert the module against its output on the same queues, value for value, before the
enhancement is wired into any run.
