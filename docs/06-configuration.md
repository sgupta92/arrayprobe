# Configuration
> One TOML file per run. It can select, never set.

**In short:** write one TOML file, run one command, then read the `.call` sidecar beside each
output to see exactly what wrote it. The triage server's `/run` page
([Visualisation](03-visualisation.md)) writes the same file from a form and runs that command.

```text
  you                     one TOML file                 one command
  ---                     -------------                 -----------
  raw files  --------->   [fidelity].profile   ----->   arrayprobe run run.toml raw/*.2DS
  (.2DS / .HVPS)          [run].engine, .preset
                          [run].out, .stages
                                  |
                                  v
        decode              framing               size distribution    combine ('c' in stages)
        <stem>.H.cdf  --->  proc.<stem>.H.nc --->  sd.<stem>.H.nc --->  <flight>.combined.H.2DS.cdf
        + .call             + .call                + .call              + .call
        (3.5: .H.nc)

  every output has a <name>.call sidecar beside it saying exactly which call wrote it
```

**See also** [User guide](02-user-guide.md) · [Conventions](09-conventions.md).

## Step 1 — install

Follow [Installation](01-installation.md). The editable install gives you one console script,
`arrayprobe`, used for everything below.

## Step 2 — know what you have

Before writing anything, answer three questions:

- **What are your raw files?** `.2DS` or `.HVPS`, one probe and channel per file.
- **What campaign call do they belong to?** Probe, channel, project, size definition, sample-area
  method, pressure and temperature, chosen together as one *preset* (Step 4). If one channel was faulty
  for a whole campaign (a soot-fouled receive mirror, for example), use only the other.
- **Do you have the aircraft TAS file?** It is required under `stock-v3.5`
  (`time_in_seconds_from_tas` is set on that profile) and refused under every `oracles-*` profile,
  which hard-wires the aircraft speed instead. **Its schema is below** — and if you do not have
  one, `arrayprobe make-tas-file` writes it.

### The aircraft TAS file: what is in it, and how to make one

Stock `imgProc_sm.m:183-185` takes this file as `varargin{1}` and builds every particle's
`Time_in_seconds` from it. The port reads exactly two variables, by these exact names
(two bare `ncread` calls):

| Variable | Shape | Type | Units | What it is |
|---|---|---|---|---|
| `Time` | 1-D, length *n* | `f8` | **HHMMSS as a number** — 06:06:38 is `60638.0` | time of day on the same clock the probe's housekeeping records use. **Not** seconds since an epoch. |
| `TAS` | 1-D, length *n* | `f8` | m s⁻¹ | aircraft true air speed at that time |

Nothing else is read: no units attribute, no global attribute, and the dimension may be called
anything. Typically 1 Hz, and the two arrays must be the same length — `imgProc_sm` indexes them
together, so a mismatch is a silently misaligned time base rather than an error.

Two ways to produce one:

```bash
# from the .tas.csv sidecar the decode already wrote beside your raw file
arrayprobe make-tas-file aircraft.cdf --from-tas-csv _decoded/<stem>.tas.csv

# or a flat series, when the speed is held outside the probe file
arrayprobe make-tas-file aircraft.cdf --constant-tas 130 --start-hhmmss 60600 --seconds 30
```

The first copies the two columns the probe recorded; the second writes a constant and says so in
its output, so it cannot be mistaken for a measurement. The shipped fixture
`tests/data/demo_flight_v35_aircraft.cdf` is one of these files if you would rather
read an example.

## Step 3 — choose the engine and profile

**First, what a profile actually is.** UIOOPS is not one program. Groups fork it, edit it and
re-fork it, and an archived product was written by one
such fork. So "faithful" is ambiguous until you say *faithful to which* — and a **profile is that
answer**. Every field names one place where two MATLAB sources demonstrably differ, with
`file:line` on both sides; none of them is a tuning knob, and none has a default that quietly picks
a side. The **engine** is which translated codebase runs; the **profile** is which variant of that
codebase's behaviour and thresholds it runs under. You choose both, always explicitly.

```text
engine = "3.5"                        the package default, for new data
tas_file = <aircraft TAS file>        v3.5's imgProc_sm reads the aircraft series
[combine].borrowed = true             only if you want one stitched product per flight
  |
  +-- profile = "stock-v3.5"               UIOOPS v3.5 as shipped.  The default.
  |
  +-- profile = "oracles-production-v3.5"  same engine, a campaign's reject thresholds
                                           (rej_hollow off, edge/comp aspect 4/4)
```

**Two spellings, one profile.** The tree above writes the hyphenated names `"stock-v3.5"` and
`"oracles-production-v3.5"`, but every shipped profile answers both to its hyphenated
name and to the spelling `profiles.py` binds it to — `stock-v3.5` **or** `STOCK_V35`,
`oracles-production` **or** `ORACLES_PRODUCTION`. The alias table is derived from the shipped
profiles, so a profile added later cannot miss one. An unknown name lists every accepted spelling.

`scripts/run_flight.py --profile <name>` takes the same names from a command line, so a v3.5 run
needs no file to start. The file is the better record:
it is what the `.call` sidecar names, and it is the only place a fork's own registered profile can
be made reachable in every worker process (`[fidelity].profile_module`).

v3.5 is the package default: use it for new data. The engine and the profile are chosen together;
the preset names the campaign call on top of them.

### When you would want `oracles-production-v3.5`

Only for one job: **holding the engine fixed while the thresholds vary**, so that a difference
between two runs is attributable to one or the other. Run a flight under `stock-v3.5` and again
under `oracles-production-v3.5` and the only thing that changed is the three reject thresholds.

**It is a synthetic configuration and reproduces nothing.** No MATLAB tree has ever run the v3.5
engine under these thresholds — the campaign's fork was never rebased onto v3.5 — so
a product made this way is **not** a reproduction of any archived file, and must not be cited as
one. The `.call` sidecar records the profile name, which is how a later reader tells the two apart.

**One consequence worth knowing before you run it.** `stock-v3.5` leaves the hollow test **on**;
`oracles-production-v3.5` turns it **off**. On a probe wider than 32 diodes that is not a small
difference — the hollow test packs diodes 1–32 only, whatever the probe's width, so on a 64-diode
CIP half the array sits beyond the packing. See [Known gaps](10-known-gaps.md).

### Your own fork's variant

If you run an edited tree, register it rather than editing this package — see
**Advanced: naming your own fork's variant** below. One thing to know here: a variant is usable
under `engine = "3.5"` only if you register it with `cites_tree="3.5"`, because the two stock
profiles are *field-identical* (measured to hold the same values) and only
a declaration can say which tree your `file:line` citations point at. Saying nothing keeps you out
of the v3.5 gate, deliberately.

## Step 4 — write the file

**Producing new science (engine 3.5, the package default):**

```toml
[fidelity]
profile = "stock-v3.5"
[run]
engine = "3.5"
preset = "MY_CAMPAIGN_2DS_H"     # your campaign's call: probe, channel, project, sizing, pressure, temperature
out = "./_decoded_v35"          # one output directory per engine: file names match, the .call differs
stages = "234c"
tas_file = "./aircraft/<flight>.cdf"   # v3.5's imgProc_sm always takes the aircraft series
[combine]
borrowed = true                  # a campaign fork's combine, borrowed and labelled; no stock v3.5 has one
```

The shipped presets are one field campaign's calls and a synthetic demo, so new data needs a preset of its
own: declare it in a presets file (**Advanced: a campaign the driver does not ship**, below) and
name the file in the run file's `[run].presets` (or pass `--presets <file>` to
`scripts/run_flight.py`) beside `[run].preset = "<name>"`.

A complete v3.5 run with the optional tables looks like this:

```toml
[fidelity]
profile = "stock-v3.5"             # required; nothing is ever assumed

[export]
format = "NETCDF4"                 # validated and recorded only: no writer reads it (below)

[enhancements]                      # opt-in, both drivers: absent = off, except stray_pixel_fix and ncar_2dc_timing_fix (below)
tas_grid_fix = true                 # name the ones you want; everything unnamed stays off
zero_image_recovery = true

[outputs]                           # which artefacts the run owes; absent section = today's run
faithful_attributed = true          # also write the self-describing sibling (same as --attributed)
enhanced_attributed = true          # apply the [enhancements] named above and export the enhanced combined
arm = "faithful"                    # write <stem>.arm.nc from the port's own sd (needs an [arm] table)
analysis_ready = true               # OUTPUT 2 chunked + compressed (the default); false = plain netCDF4
zarr = false                        # true = also a Zarr store beside each attributed file (needs [zarr])
parquet = false                     # true = also a Parquet directory beside each attributed file (needs [parquet])

[run]
engine = "3.5"
preset = "MY_CAMPAIGN_2DS_H"       # the call, chosen whole by name
out = "./_decoded"
stages = "234c"
tas_file = "./aircraft/<flight>.cdf"
```

Three keys are always required for `arrayprobe run`: `[fidelity].profile`, `[run].engine`,
`[run].preset`. Everything else in `[run]` — `raw`, `out`, `stages`, `tas_file` — is optional and
is resolved relative to the config file. Without `out`, `arrayprobe run` writes to `output/`
beside the config file.

Two more `[run]` keys serve a CIP or PIP. `probe` names the probe the run follows, which matters
for a SEA file holding several; it must be the preset's probe, or the run is refused by name.
`tas_from_probe` is a list of paths or globs to the `<stem>.tas.csv` airspeed files a 2D-S on the
same aircraft wrote, because the CIP decode writes none; each entry must match a file.
`examples/configs/cip_uiops/cip_run.toml` uses both.

Three more `[run]` keys forward the driver's `--presets`, `--probe-case` and `--probe-case-module`,
each only when set. `presets` is a TOML file of `[[campaign]]` tables, resolved relative to the
config file, registered before `preset` is read. `probe_case` names a registered probe case (engine
3.5) that fixes the size-distribution bin table, and `probe_case_module` is the module whose import
registers it. A 2D-S run with no archived product and no campaign preset needs a 2D-S probe case,
for example a case of your own, with `probe_case_module` naming the module that registers it;
without one, and with the batch driver's default-on bin-table correction turned off, it sizes on
the HVPS bin table. The correction is itself the shipped case `v35-2ds-ladder-fix`.

## Step 5 — run it

```bash
arrayprobe run run.toml ./raw/<stem>*.2DS
```

Raw files given on the command line win over `[run].raw` in the file. Add `--dry-run` to preflight
without decoding anything. A run that will take more than a few minutes belongs in the background.

### The run is confirmed before it starts

Before any stage runs, the driver prints the whole configuration in force: engine, profile,
preset, stages, the framing stage's reject set, and the two size-distribution thresholds *each tagged with where its value
came from* — `stock`, `regime:<name>` or `user:<path>` — followed by the enhancement policy and
pointers to the documents behind each. Then, for a run that **states no threshold policy of its
own**, it asks before starting.

Which runs are asked, and which are not:

| The run | What happens |
|---|---|
| `[thresholds]` declared in the config file | starts — the policy is written down, which is the confirmation |
| `--regime`, `--area-ratio-z` or `--default-int-arr-thresh` on the command line | starts — same reason |
| nothing stated, **terminal** | prints the block and asks `[y/N]`; anything but `y` runs nothing |
| nothing stated, **no terminal** (detached, CI, a script) | prints the block and **refuses**, exit 2 |
| `--yes` | starts, having printed the block |
| `--engine 3.5` | never asked — with nothing stated, v3.5 runs the probe case's own cited values, not an inherited fallback |

The last two rows are the design, not a compromise. A detached run (in the background, from a
scheduler or in CI) has no terminal on stdin: a blocking prompt there would hang the
run until somebody noticed, which is a **worse** failure than the silent default the question
exists to catch. So assent is declared in the command line instead, where the launch log keeps it.

**What a `stock` tag actually means**, and why the question is worth asking: it is not a neutral
default. It is the historical hard-coded fallback, and for a project/probe row with no entry of
its own (`arrayprobe.constants`'s `otherwise` branch) that fallback is *one field campaign's own
warm-liquid tuning* — `area_ratio_z = 0.5`, `default_int_arr_thresh = 6e-6`, both dated edits for
that campaign, and correct for it. Declaring a regime,
or the raw values, is the answer; being asked is the reminder that there is a question.

### What a regime carries

A regime (`--regime ice|liquid-warm|mixed`, or `[thresholds].regime`; a fork registers its own
from Python with `register_regime()`) works on both engines and carries eight thresholds:

| Threshold | Stage | In a regime |
|---|---|---|
| `area_ratio_z` | size distribution, reject `z` | always a cited value |
| `default_int_arr_thresh` | size distribution, shattering | always a cited value |
| `rej_zero_area`, `rej_split`, `rej_hollow`, `shadowed_area`, `max_edge_img_ar`, `max_comp_img_ar` | image stage, reject | a cited value, or inherited from the profile |

Each field is resolved on its own: a value on the command line or in `[thresholds]` wins over the
regime, the regime over the profile (or a defaults file), and the profile over
the stock tree. With no regime and no override, engine 3.5 uses the probe case's own cited values.
On engine 3.5 the shattering threshold acts only where the
probe case's gate (`applyIntArrThresh`) is on and `iaThreshType` is 2; elsewhere the panel and the
stamp say it was unused.

A regime does not carry the shattering gate, the re-acceptance constants, `iaThreshType` or the
bin ladder. Those describe the probe, not the cloud, and stay in the probe case and
`[shattering]`.

The stamp is additive. The sd `.call` gains `area_ratio_z=` and `default_int_arr_thresh=` only
when a value is set, tagged `(regime:<name>)` when the regime supplied it; every `proc` and `sd`
`.call` gains `regime=<name> reject_sources=(...)` only when the regime sets a reject threshold.
A run naming no regime writes the same stamp and the same bytes as before.

### Two inputs a probe case can lack: `tas_max` and `pecan_params`

Two size-distribution cases cannot run as UIOOPS ships them, on either engine, so the run must
supply the missing input itself. Neither has a default.

| Key (command line) | Needed by | What it supplies |
|---|---|---|
| `[thresholds].tas_max` (`--tas-max`) | the 2DP, whose `sizeDist.m` case assigns no `tasMax` in any release | the probe's own `tasMax`, m/s, finite and > 0 |
| `[thresholds].pecan_params` (`--pecan-params`) | the PECAN CIP and PIP cases, which call `getPECANparams`, a function no release ships | a CSV of spiral `start_s,end_s,intar_threshold_s` (`arrayprobe_uiops.pecan_params`), resolved relative to the config file |

```toml
[thresholds]
tas_max = 140.0                       # 2DP only: your instrument's value
# pecan_params = "pecan_spirals.csv"  # PECAN CIP/PIP only
```

The command line wins per field, as for the other `[thresholds]` keys. Both are checked when the
file loads (a bad value or an unparseable parameter file is an error) and again before stage 4: a
2DP run without `tas_max`, a PECAN case without `pecan_params`, `tas_max` on a case that assigns
its own and `pecan_params` off PECAN are all refused. Either reaches the sd `.call` only when set
(`pecan_params` by name and content hash), so every other run's stamp is unchanged. A
`[thresholds]` section holding only these keys is valid.

## Step 6 — check what was written

Every output has a name that says which engine wrote it (`.nc` for 3.5) and a
`<output name>.call` sidecar beside it recording exactly which call produced it — engine, profile,
reject thresholds, shadow-diode handling, TAS file. A run refuses an input whose sidecar is
missing or disagrees with the current call (`--accept-unstamped` overrides; `--allow-mixed-config`
allows a deliberate mixture, logged either way). See [User guide](02-user-guide.md) for how to read
the output files and [Validation](04-validation.md) for what has been checked against the archive.

## What the file can select, and what it refuses

```text
  [fidelity].profile  ---> one named FidelityProfile (registry + 3 aliases)   never a raw threshold
  [fidelity].profile_module -> a Python module imported first, so a fork's register_profile() is seen
  [fidelity].authordefaults -> a content-hashed file: base profile + cited overrides for the six
                              reject thresholds only, generated into a registered FidelityProfile;
                              mutually exclusive with [fidelity].profile
  [run].engine        ---> "3.5", or "soda2" (a SODA-2 file, run by arrayprobe soda2 run)
  [run].preset        ---> one CampaignPreset, whole, by name (shipped, or from the [run].presets file)
  [run].raw/out/stages/tas_file -> where files are, which stages run          the command line wins
  [shattering].threshold_file -> the 12th sizeDist argument, spelt out        absent section = a different call
  [thresholds].tas_max / .pecan_params -> a 2DP's tasMax / PECAN's spiral file   required where the case lacks it
  [masking].diodes    ---> declared only; applied only with --diode-corrected
  [export].format     ---> NETCDF3_CLASSIC (default) or NETCDF4; validated, recorded, read by no writer
  [enhancements].*    ---> opt-in switches: ON only where a key says true       absent name = off (stray_pixel_fix, ncar_2dc_timing_fix: on)
  [combine].borrowed  ---> engine 3.5 only: stitch with a campaign fork's combine, labelled in .call
  [outputs].faithful_attributed -> true = write the attributed sibling beside the faithful file
                              (--attributed); false = explicit opt-out; the command line wins
  [outputs].enhanced_attributed -> true = turn enhancements on and export the enhanced combined;
                              refused before any stage runs if nothing is switched on
  [outputs].arm       ---> "faithful" = <stem>.arm.nc from the port's own sd; false = opt-out

  refused at load: rej_hollow, max_edge_img_ar, max_comp_img_ar, spec_buffer_guard, area_ratio,
  z_threshold, defaultIntArrThresh, iat_threshold, zero_image_particle_recovery, hvps_reader
```

| Situation | Result |
|---|---|
| no `[fidelity].profile` | error — no profile is ever assumed |
| a raw threshold key anywhere (`rej_hollow`, `spec_buffer_guard`, `area_ratio`, …) | error naming the profile axis to use instead |
| `[shattering]` present without `threshold_file` | error — an absent threshold file is itself an output-changing call, so it must be written down |
| an enhancement key that is not `true`/`false` | error — enhancements are opt-in switches |
| a diode number outside 1–128, or an unknown section | error |
| `[export].format` not `NETCDF3_CLASSIC` or `NETCDF4` | error |
| `[export].format` the named `[run].engine` does not write (`NETCDF3_CLASSIC` under `3.5`) | error — no writer reads the key |
| an unknown key in `[fidelity]`, `[shattering]`, `[masking]` or `[export]` (a mistyped `[masking.diode]`, say) | error naming the key |
| a file saved as UTF-16 | error naming the encoding; a UTF-8 byte-order mark is accepted |
| `[run]` has an unknown key, or `engine` is not `"3.5"`/`"soda2"` | error |
| `[combine].borrowed` not a boolean | error |
| `[combine]` has any other key (a typo'd `borrowd = true`, say) | error naming the key; the key is never silently ignored, so a typo cannot change how the run stitches |
| `[outputs]` has a key other than `faithful_attributed`, `enhanced_attributed`, `arm`, `analysis_ready`, `zarr` or `parquet` | error naming the key and listing the accepted ones |
| `[outputs].faithful_attributed`, `.enhanced_attributed`, `.analysis_ready`, `.zarr` or `.parquet` not a boolean (`"yes"`, `1`) | error; a value is never coerced to `true` |
| `[outputs].arm` anything but `"faithful"` or `false` (`"enhanced"`, `true`) | error; `"enhanced"` points at `[enhancements] arm_export = true`, the one switch for the enhanced ARM file |
| `[outputs].enhanced_attributed = true` with no enhancement switched on, a stage list without `c`, or the enhancements package not installed | the run is refused before any stage runs, each reason logged |

| `[outputs].zarr = true` or `.parquet = true` with no attributed output selected | the run is refused before any stage runs (exit 2) |

**A run can write three versions of its result.** Each is a separate file; the later two are
derived from the first and never change it.

| Output | File | What it is |
|---|---|---|
| 1. Original | `<base>.combined.*.cdf`, with its `.call` sidecar | the faithful product: `NETCDF3_CLASSIC`, the format of the combine step the v3.5 engine runs (its decode, image-processing and size-distribution files are `NETCDF4`), carrying only the attributes the MATLAB writes. It is the file validation compares, and every run writes it. |
| 2. Attributed | `<base>.combined.*.attributed.nc`, optionally `.attributed.zarr` and `.attributed.parquet` | the same values in a self-describing netCDF4 file: `units` and `long_name` on every variable, ACDD-1.3 discovery attributes, the run record from the `.call` stamp and the SHA-256 of the original it came from. Chunked and losslessly compressed by default. `python -m arrayprobe.ai_ready FILE` checks each of these claims and exits non-zero on a failure. |
| 3. ARM format | `<stem>.arm.nc` (faithful), `<stem>.enh.arm.nc` (enhanced) | the size distribution in the layout of ARM's processed product, carrying the attributed file's run-level attributes. |

When a run writes any OUTPUT 2 or 3 file it also writes `<base>.outputs.json`, a manifest listing
every file above with its path, `role` (`original`, `attributed` or `arm`), `lineage` (`faithful` or
`enhanced`), `encoding` for an attributed file, SHA-256, size in bytes and the text of its `.call`
stamp. A default run writes neither the manifest nor anything beyond OUTPUT 1. Reading each output,
and how many bytes a single variable or time window costs in each, is worked through in
`examples/7_analysis_and_outputs/04_output_formats_and_tables.ipynb`; the attributed export is described in full in
`docs/developer/ATTRIBUTED_EXPORT.md`.

**`[outputs]` selects which artefacts the run writes.** Six keys are accepted.

- `faithful_attributed`: `true` turns on `--attributed`, so the run writes the self-describing
  NETCDF4 sibling beside each faithful combined product; the faithful file itself is not touched.
- `enhanced_attributed`: `true` turns enhancements on (as `--enhancements` does) and exports the
  enhanced combined with its attributes. It is refused before any stage runs when the
  `[enhancements]` table switches no enhancement on, when the stages leave out `c` (no combine,
  nothing to export), or when the enhancements package is not installed.
- `arm`: `"faithful"` writes `<stem>.arm.nc` from the port's own size distribution, with the global
  attribute `arrayprobe_lineage = "faithful"`. It needs an `[arm]` table; without one the run logs a
  skip for that stem and writes no file. `"enhanced"` is refused: the enhanced ARM file is selected
  by `[enhancements] arm_export = true`. `false` is an explicit opt-out.
- `analysis_ready`: absent or `true` writes each attributed file (OUTPUT 2) as chunked, compressed
  netCDF4; `false` writes it plain (contiguous, uncompressed). Values are identical either way.
- `zarr`: `true` also writes a Zarr store (`.attributed.zarr`) beside each attributed file the run
  wrote, faithful and enhanced, listed in the run's `.outputs.json` with `"encoding": "zarr"`. It
  needs the `[zarr]` extra; without it the run logs a skip and still succeeds. Absent or `false`
  writes none.
- `parquet`: `true` also writes a directory of Parquet files (`.attributed.parquet`) beside each
  attributed file the run wrote, one file per dimension tuple in long form and the scalars in
  `scalars.parquet`, listed in `.outputs.json` with `"encoding": "parquet"`. It needs the
  `[parquet]` extra (pyarrow); without it the run logs a skip and still succeeds. Absent or `false`
  writes none. Reading the Parquet files back as tables is worked through in
  `examples/7_analysis_and_outputs/04_output_formats_and_tables.ipynb`.

`false` on any key is an opt-out, and the command line always wins over the file: a command-line
`--attributed` or `--enhancements` overrides a `false`, and the run logs that it did. A file with no
`[outputs]` section runs exactly as it would without one, and every output is off when the section
sets none.

**`[export].format` does not choose the output format.** It is validated (anything but
`NETCDF3_CLASSIC` or `NETCDF4` is an error) and stored on the loaded config as `export_format`, but
no writer reads it: the engine fixes the format. The v3.5 engine writes `NETCDF4`, as v3.5's own `netcdf.create`
calls do. `tests/test_config_keys_are_consumed.py` fails if another documented key goes unread.

An enhancement not mentioned in the file is **off** to the port (`arrayprobe run`,
`scripts/run_flight.py`) and **on** to `arrayprobe run --enhancements`, which reads the same table with every
registered enhancement on unless it is named `false`. The loader lives in the core
package but only *selects*: it hands back a named `FidelityProfile` and a set of flags, and it never constructs a
configuration of its own.

---

The rest of this page is for cases past the first successful run.

## Advanced: the command line still carries some things

`run_flight.py` also reads a config directly, without the `arrayprobe run` wrapper — useful when
you want the script's own flags (`--jobs`, `--s2-jobs`, `--chunks`, `--worker-stall-min`) alongside
a config file:

```bash
scripts/run_flight.py --config run.toml --preset DEMO_2DS_H --engine 3.5 ./raw/<stem>*.2DS
```

`--preset` is required on every invocation, including this one — `--config` selects a fidelity
profile and shattering-threshold argument, never a campaign preset, so a direct `run_flight.py
--config ...` call (unlike `arrayprobe run`, whose config file's `[run].preset` is required and
always forwarded) still has to name `--preset` on the command line itself. It reads the file's other `[run]` keys too: `preset` and `probe` must agree with `--preset`, and `out`, `stages` and `tas_file` apply when their flag is absent (the flag wins when given).

Three rules the driver enforces, each with a test:

- **the command line wins** over the config, and every override is logged;
- **a config cannot enable masking by itself** — declared diode masks stay unused until
  `--diode-corrected` is also given;
- **any registered profile actually runs** — every stage call reads the switch live, not just the
  provenance stamp, so a fork's `register_profile()` variant reaches the decode, framing and size-distribution stages through this same
  driver rather than needing the library API. `--tas-file` (or `[run].tas_file` through
  `arrayprobe run`) supplies the aircraft file a `time_in_seconds_from_tas` profile needs; the
  driver refuses it under a profile that never reads it, and refuses to run the framing stage without it under
  one that does.

Enhancement switches can be applied by `run_flight.py` itself: pass `--enhancements` (needs
`--config`) and it runs the port, then applies what `[enhancements]` names to the products this run
wrote, staged and chained (a proc-stage correction rebuilds the port's
own size-distribution and combine steps onto its own `enh.*` files rather than falling back to the faithful sd). Without the
flag, switches are read and reported only; `arrayprobe run --enhancements` is the other path to the same
package. Paths, job counts and output locations otherwise stay on the command line — the config
carries the decisions that change results.

### `[enhancements]` means the same thing to both drivers

**Every enhancement is OFF unless a key names it `true`.** That holds for `arrayprobe run`, which
never applies one at all, and for `arrayprobe run --enhancements`, which applies the ones it can. A
config whose only entry is `outoffocus = true` runs exactly `outoffocus` and nothing else.

The `<sd>.enhancements.json` sidecar beside each output records exactly which modules were
applied. `arrayprobe run --enhancements` also prints
the resolved-ON set to the terminal before it does anything, and refuses a config with no
`[enhancements]` section at all rather than choosing a policy for you. An empty table is how you
say "the port, unmodified":

```toml
[enhancements]
```

`all = true` is the one `[enhancements]` key that does not name a module: it turns on
`registry.default_set(engine)` — every registered enhancement applicable to the run's engine, minus
`registry.DEFAULT_SET_EXCLUSIONS` — and an explicit `<name> = true` or `<name> = false` beside it
still wins over the default, so the set need not be spelt out module by module. On the v3.5 engine the
default set excludes `outoffocus` (opt-in by name only): measured on v3.5 runs, it
changes no diameter there — v3.5 already divides every `'H'`-rejected particle by its size factor —
only `image_area` on 0.2-0.4% of particles, for about 94% of an enhancement pass's time.

**`stray_pixel_fix` and `ncar_2dc_timing_fix`** (the full default-on list is in [Choosing an engine](27-choosing-an-engine.md#corrections-engine-35-applies-by-default)). `stray_pixel_fix` is not an enhancement module but a correction inside engine 3.5, and absent means on. UIOOPS sizes an image as a whole, so one real particle plus a few far-off stray pixels is sized as a much larger particle. Every `--engine 3.5` run removes pixel groups of at most 2 pixels lying more than 8 empty diodes from a single main piece of at least 9 pixels, then sizes and tests the main piece alone; each image's removed count is written to `image_stray_pixels_removed`. Turn it off with `--stray-pixel off` or `[enhancements] stray_pixel_fix = false` (the command line wins); the `.call` stamp records `stray_pixel=on:g8,n2,m9` or `stray_pixel=off`. Worked examples: `examples/5_data_quality/04_stray_pixel_images.ipynb`.

`ncar_2dc_timing_fix` is likewise a correction inside engine 3.5, absent means on, and it reaches 2DC and 2DP data only. NCAR's 2DC records mark particle boundaries with timing/sync words UIOOPS does not recognise, so `imgProc_sm.m:754`, which frames on the 0x55 boundary, frames no particles at all. The correction converts those words to the 0x55 form before framing. Turn it off with `--ncar-2dc-timing off` or `[enhancements] ncar_2dc_timing_fix = false` (the command line wins); a 2DC/2DP `.call` stamp records `ncar_2dc_timing=on:fix2dimage` or `ncar_2dc_timing=off`.

`arrayprobe enhancements` lists every module a config may name.

## Advanced: a campaign the driver does not ship

A campaign is one call of seven values — probe, channel, project, size definition, sample-area
method, pressure, temperature — chosen together, because a wrong one gives a plausible wrong
answer, not an error. One field campaign's presets ship with the driver, for example:

```bash
scripts/run_flight.py --preset ORACLES_2017_2DS_V --engine 3.5 ./raw/<stem>*.2DS
```

A campaign the driver does not ship is declared in a file you own, rather than by editing the
driver:

```toml
[[campaign]]
name = "MY_CAMPAIGN_2DS_H"
probe = "2DS"
orientation = "H"
project = "MY_CAMPAIGN"
d_choice = 6
sa_method = 0
pres_pa = 9e5
temp_c = 15.0
provenance = "transcribed from <script>; not yet validated against a product"
```

```bash
scripts/run_flight.py --presets my_campaigns.toml \
    --preset MY_CAMPAIGN_2DS_H --engine 3.5 ./raw/<stem>*.2DS
```

The terms are the same ones the built-in presets are held to, and each is refused rather than
worked around:

| Situation | Result |
|---|---|
| a missing field, or an unknown key | error — a campaign is stated whole, so a typo cannot leave a real field unset |
| an empty `provenance` | error — a preset whose origin nobody can name is a set of numbers somebody guessed |
| a name a built-in already uses | error — logs and `.call` stamps record the *name*, so it has to keep meaning one call |
| `orientation` other than `H` or `V` | error — the decode stage writes `.H.cdf` and `.V.cdf`, so nothing would write the file `HV` names |
| a probe this driver cannot decode | error — its decode stage is `read_binary_SPEC` (the SPEC probes); `arrayprobe.readers.dmt` and `.pms` exist for the others, and this driver does not call them |

A shipped preset carries the same `provenance` line, and it is allowed to say that it has never
been validated: `ORACLES_2017_2DS_V` reaches the vertical channel and says in its own provenance
that no V product has been reproduced with it. **A preset claims reach, not evidence.** See
[Validation](04-validation.md) for the driver these presets came out of.

## Advanced: naming your own fork's variant

UIOOPS is forked, edited and re-forked; field campaigns often run an edited tree. The shipped variants are in the table below; a group running its own tree
registers theirs:

```python
import dataclasses
from arrayprobe.profiles import FidelityProfile, STOCK_V35, register_profile

register_profile(dataclasses.replace(
    STOCK_V35,
    name="my-group-2024",
    description="Our tree at <url or path>, <date>; stock plus the change below.",
    spec_buffer_guard=False,      # our read_binary_SPEC has no bounds guards
))
```

A config file can then select it by name like any other. Two properties are deliberate:

- **Every field is required**, because `FidelityProfile` has no defaults. A variant cannot be
  half-described, and each field names a divergence with `file:line` on both sides.
- **Registration is Python, never a config file.** A profile field *is* a threshold, and a
  configuration file here selects between documented behaviours rather than setting one — the same
  rule that makes `rej_hollow` an error anywhere in a run file. Registering constructs the object
  where the divergence is named; the file only picks one that already exists.

A name may not be taken twice, shipped or registered: `.call` sidecars and error messages record
the name, so it has to keep meaning one variant.

`[fidelity].profile_module = "my_lab.profiles"` in a config file imports that module before the
profile is resolved, so a registration reaches every fresh process — including each `--jobs` or
`--chunks` worker, which otherwise never re-runs whatever registered the profile in the parent.

## Advanced: a defaults file

`[fidelity].profile` names a profile someone already wrote and reviewed as Python. Some labs want
less than that: a base profile plus a few cited threshold choices of their own, editable without
touching code. `[fidelity].authordefaults` is that file, in its minimal form (base profile plus the six `calculate_reject_unified.m:71-77` reject thresholds,
nothing else):

```toml
[fidelity]
authordefaults = "authordefaults-3f9a1c2b4d5e6f70.toml"   # mutually exclusive with `profile`
```

and, in that separate, content-hashed file:

```toml
[fidelity]
base_profile = "stock-v3.5"          # any shipped profile, either spelling

[thresholds.rej_hollow]
value = false
citation = "<who set this value, and why>"
```

**The file name carries a content hash** — `authordefaults-<16 hex chars of its own SHA-256>.toml`
— so an edit without a rename is refused rather than silently changing what a run reproduces.
Every override needs a **citation**: who chose the value and why, refused if missing. Nothing but
the six reject thresholds (`rej_zero_area`, `rej_split`, `rej_hollow`, `shadowed_area`,
`max_edge_img_ar`, `max_comp_img_ar`) may appear under `[thresholds]` — every other
`FidelityProfile` field stays a Python registration, same as **Advanced: naming your own fork's
variant** above; this is the same mechanism (`register_profile()`), generated from TOML instead of
typed by hand. A run using it stamps `authordefaults:<path>#<sha>` into every `proc`/`sd` `.call`
sidecar, alongside the reject thresholds it produced. Absent, nothing here changes: `[fidelity]`
still requires exactly one of `profile` or `authordefaults`, and a config predating this feature
behaves byte-for-byte as it always did.

The file works with `--chunks`: every chunk worker re-loads it, refuses it if its hash has
changed since the run started, and carries the same `authordefaults:<path>#<sha>` stamp, so a
chunked run writes the same output as a serial one.

## Corrections engine 3.5 applies by default

Every correction on by default, the engine and probes it reaches and how to turn it off are listed once, in [Choosing an engine](27-choosing-an-engine.md#corrections-engine-35-applies-by-default); `--accept-implausible` keeps a product the empty-size-distribution check refused. `--accept-preset-mismatch` runs a raw file whose extension names another probe than the preset's, which the preflight otherwise refuses. The table is in
[Choosing an engine](27-choosing-an-engine.md); detail in
`docs/developer/TWO_ENGINES.md`.

## Advanced: the two choices that change the science

**These are the two settings a user of *this package* most needs**, and getting either wrong
produces a plausible number rather than an error. Both are required arguments to `sizedist`:
neither has a default, deliberately, so a run cannot silently inherit someone else's convention.

### `d_choice` — how a particle's size is defined

Six definitions, and the choice changes derived concentration by up to a factor of six at the
smallest and largest sizes. Read from `arrayprobe_uiops.sizedist_core.D_CHOICE`, which is also what writes
the product's `Dmax Definition` attribute, so a file always records the definition it was made
with.

| `d_choice` | Definition | Registry key |
|---|---|---|
| 1 | `L_x` — extent along the photodiode array | `sizedist_length` |
| 2 | `L_y` — extent along the direction of flight | `sizedist_width` |
| 3 | `mean(L_x, L_y)` | `sizedist_mean` |
| 4 | `hypotenuse(L_x, L_y)` | `sizedist_hypot` |
| 5 | `max(L_x, L_y)` | `sizedist_max` |
| **6** | **diameter of the minimum enclosing circle** — the default in every UIOOPS run script | `sizedist_minR` |

The port found that four of the six definitions pass through an integer-arithmetic path in the
original UIOOPS that collapses the result toward zero, and a fifth saturates above 181 diodes —
only `d_choice = 6` is clean of both (reported to the UIOOPS developers). The v3.5 engine does not carry it (the
cast to double moved earlier in the maintainers' own later revision). An earlier translation of
UIOOPS v3.1.4 reproduced archived products and is not part of this package. See the *Known gaps* and *Conventions* pages.

### `sa_method` — which particles the sample area counts

Three conventions, not two. Read from `arrayprobe.sample_area.calc_sa_randombins`, which refuses
any other value rather than leaving the effective array width undefined.

| `sa_method` | Convention | What it means |
|---|---|---|
| 0 | **centre-in** | a particle counts if its centre lies within the array |
| 1 | **entire-in** | it counts only if wholly within the array |
| 2 | **with correction** | the array is widened by 0.72 × particle diameter, following the reconstruction result of Heymsfield and Parrish — attributed by McFarquhar et al. (2017, Eqs. 11-7/11-8) to the pair's separate 1979 NCAR technical note (TN-137+IA), not their 1978 *J. Appl. Meteorol.* method paper |

This is the axis on which packages most visibly disagree, so a figure quoted without it is not
comparable: SODA-2 defaults to centre-in and offers an all-in variant, NCAR's `process2d` offers
`-centerin`, `-allin` and a reconstruction option, and an archived product is made with one specific choice. Every run records its own in a `.call`
sidecar beside the output.

## Reference — the shipped profiles, field by field

Generated from the `PROFILES` registry in `arrayprobe_uiops.profiles` itself — never hand-typed, so it cannot drift from
what a run actually does. Regenerate with `docs/_build/profiledoc.py` (needs the venv); `--check`
fails if this table has gone stale.

<!-- PROFILEDOC:START -->

| Field | What it means |
|---|---|
| `spec_buffer_guard` | Whether `read_binary_SPEC`'s image decoder carries the 2017 bounds guards. |
| `hvps_reader` | Which decoder handles a raw `.HVPS` file: `'spec'` or `'hvps'`. |
| `diode_stats_counts_shadowed` | Whether `bin_stats` counts shadowed diodes or lit ones. |
| `zero_image_particle_recovery` | What happens when a particle frames to zero slices. |
| `time_in_seconds_from_tas` | How `Time_in_seconds` is built for probetype 2 (2D-S / HVPS). |
| `inter_arrival_in_seconds` | The units of the written `inter_arrival` variable, for probetype 2. |
| `shadow_diode_reillumination` | Whether `imgProc_sm` re-illuminates stuck photodiodes before measuring. |
| `imgproc_output_typing` | The proc-file variable contract: `'typed'` or `'all-double'`. |
| `nan_tas_substitution` | Whether `sizeDist` replaces a NaN TAS before the sample volume. |
| `reject_thresholds` | The `calculate_reject_unified.m:71-77` thresholds this tree runs with. |

**How to read the values table.** One row per field (meanings above), one column per shipped profile. `reject_thresholds` is split into one row per threshold, written `reject_thresholds.<name>`. A value is the field's literal Python value (`True`/`False`, a string in quotes, a number).

| Field | `oracles-production-v3.5` | `stock-v3.5` |
|---|---|---|
| `spec_buffer_guard` | `True` | `True` |
| `hvps_reader` | `'spec'` | `'spec'` |
| `diode_stats_counts_shadowed` | `True` | `True` |
| `zero_image_particle_recovery` | `True` | `True` |
| `time_in_seconds_from_tas` | `True` | `True` |
| `inter_arrival_in_seconds` | `True` | `True` |
| `shadow_diode_reillumination` | `False` | `False` |
| `imgproc_output_typing` | `'typed'` | `'typed'` |
| `nan_tas_substitution` | `True` | `True` |
| `reject_thresholds.rej_zero_area` | `True` | `True` |
| `reject_thresholds.rej_split` | `True` | `True` |
| `reject_thresholds.rej_hollow` | `False` | `True` |
| `reject_thresholds.shadowed_area` | `25` | `25` |
| `reject_thresholds.max_edge_img_ar` | `4` | `6` |
| `reject_thresholds.max_comp_img_ar` | `4` | `5` |

**`oracles-production-v3.5`** — The v3.5 engine run under the reject thresholds a field campaign's modified UIOOPS v3.1.4 used. SYNTHETIC: no MATLAB tree ever ran this combination -- that modified UIOOPS was never moved onto v3.5 -- so this profile reproduces NO archived product and must not be cited as reproducing one. It exists to hold the engine fixed while the threshold axis varies, so a difference between two runs is attributable. Behaviour fields are stock-v3.5's, unchanged and still cited to the v3.5 tree. Only reject_thresholds differ, taking that modified UIOOPS's calculate_reject_unified.m:72 (rej_hollow 1->0), :76 (max_edge_img_ar 6->4) and :77 (max_comp_img_ar 5->4), against v3.5's stock 1/1/1/25/6/5 at calculate_reject_unified.m:60-66. NOTE for a 64-diode probe: this profile leaves rej_hollow OFF, so unlike stock-v3.5 it does not exercise the 32-diode hollow packing defect.

**`stock-v3.5`** — joefinlon/UIOPS v3.5 as shipped. Every field holds the same value as UIOOPS v3.1.4 as released -- measured field by field against the v3.5 sources, not assumed -- and cites v3.5 lines instead: buffer guards read_binary_SPEC.m:322-367, shadowed-diode stats imgProc_sm.m:1208-1211, zero-image recovery :773/:1311, TAS-based Time_in_seconds :1133-1172, seconds-valued inter_arrival :1176, no shadow_diode block anywhere, typed output (:1352, :1380), NaN-TAS substitution sizeDist.m:1959-1971, reject thresholds calculate_reject_unified.m:60-66. Provenance table and test: arrayprobe_uiops.profile, tests/test_stock_v35_profile.py. The v3.5 engine consumes only reject_thresholds (its readers and driver take no profile, because v3.5 has one source tree); the rest records which source tree a run translates. v3.5 also writes NETCDF4 with deflate (read_binary_SPEC.m:81, imgProc_sm.m:289) where v3.1.4 writes classic; that is the engine's own contract, not a profile axis.

<!-- PROFILEDOC:END -->
