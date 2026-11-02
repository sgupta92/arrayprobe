# True airspeed (TAS) in arrayprobe

This page defines TAS, why it matters, its per-probe issues and how the package uses it. Each statement is **measured** (read off a real file), **read** (in source, with
`file:line`) or **derived** (from the other two, not yet measured). Builder mechanics:
[TAS_BUILDER.md](TAS_BUILDER.md).

## 1. What it is

The speed of the air relative to the aircraft, in m/s. An optical array probe records nothing about
distance along the beam: it samples the photodiode array at a fixed rate and records particles in
clock ticks. **TAS is the only thing that turns ticks into time and time into volume.**

## 2. Where it enters the chain, and what it changes

| Stage | What TAS does | Source it reads | Consequence if wrong |
|---|---|---|---|
| **S3, `imgProc_sm`** (probetype 2: 2D-S, HVPS, 3V-CPI) | converts the probe clock into `Time_in_seconds` per particle. That fixes each particle's inter-arrival time, and the inter-arrival time drives shattering rejection in S4 | the aircraft file named by `--tas-file`: `TAS`/`Time`, or ARM's `true_airspeed`/`time` (`run_flight.py` `_TAS_VARIANTS`) | wrong inter-arrival times, so the shattering block accepts or rejects different particles (derived) |
| **S4, `sizeDist`** | sample volume per second. The sample area is scaled when `tas > tasMax` (`arrayprobe_uiops/sizedist.py:1175-1176`) | the probe's own housekeeping series `<stem>.tas.csv` from S2 (`run_flight.py:2478`) | concentration scales as 1/TAS |
| **SODA-2** | sample volume and particle timing | the probe housekeeping `house.tas`, interpolated (`arrayprobe_soda2/process_2d.py:558`); a `pth` file when given (`:340-371`, accepted `0 < tas < 400`); or `fixedtas` when > 0 (`:793-796`). The buffer reader defaults to 100 m/s when `fixedtas` is 0 (`read2dbuffer.py:66-67`) | as for S4 |

**Lookup rules differ between the two UIOOPS stages, and this is the root of the worked case in
§5.** Both are read:

- **S3 uses exact equality**: `tas(tas_time == hhmmss)` (`imgProc_sm.m:727`, `src/arrayprobe_uiops/imgproc_core.py:32`).
  - No match falls back silently to **170 m/s** (`imgProc_sm.m:365`/`:763`, `TAS_FALLBACK`, `src/arrayprobe_uiops/imgproc_core.py:14`).
  - Two matches make MATLAB fail at `:738`; the port raises the same error.
- **S4 converts to whole seconds the way MATLAB's integer conversion does**, so a fractional time such as 164128.6 becomes second 164129 (in the v3.1.4 engine, not included in this release). A NaN takes the last valid value.

## 3. `tasMax`, per probe

`tasMax` is the airspeed above which the probe's electronics cannot keep up; above it, UIOOPS scales
the sample area rather than the speed. Per probe, in `arrayprobe/constants.py` (read): 125, 170,
200 or 300 m/s depending on the probe. The v3.5 2D-S value is 170 (`sizeDist.m:509`).

`tasMax` is not the same thing as `TAS_FALLBACK`, although both are 170 for the 2D-S. The fallback is
what S3 substitutes when it has no airspeed.

## 4. Per-source and per-probe issues known today

| Source | Issue | Status |
|---|---|---|
| S2 `.tas.csv` (2D-S housekeeping) | **Times are sub-second** (e.g. `124834.999`), so the S3 exact-match lookup almost never hits. Measured 2026-09-23: seven of eight 2017 aircraft files had 0-2 whole-second rows out of 7,700-22,700 | fixed in the builder (below) |
| S2 `.tas.csv` | **Duplicated seconds**: two rows round to the same second, and sometimes an adjacent second is absent, which reads as a mislabelled time. 117 across the eight 2017 files are left ambiguous by the current rule | an unsettled second takes the default (§6) |
| S2 `.tas.csv` | **Corrupt values**: 36 rows above 300 m/s in one 2017 flight file (29 of 38 at 163120 read 241,403 m/s). `-999` marks a missing value | above 300 m/s, at or below 0 m/s and non-finite values take the 170 m/s default, never dropped (§6, §7) |
| Aircraft file with a seconds-since-`base_time` axis | `true_airspeed` on a `time` axis in seconds since `base_time`. Passed through unconverted as the S3 lookup key, it never equals an HHMMSS value, so S3 falls back to 170 m/s | the builder's whole-second check is required on this path |
| CIP (a delivery from another processing group) | knots versus m/s. That delivery's airspeed read as knots, against the 2D-S series, is 1.833 over 23,914 in-flight seconds, against the exact 1.9438: a 5.8 % disagreement between two airspeed measurements on one platform | carried as an uncertainty band |
| A 2016 campaign, earlier v3.1.4 translation (not shipped) | the product of record reproduces under a call with **no aircraft file**, so S3 runs at 170 m/s throughout (derived from the call; the archived file has not been measured for it) | faithful by construction; not a defect of the port |
| A 2017 campaign, earlier v3.1.4 translation (not shipped) | No `.call` sidecar of the nine validated 2017 flights carries `tas_file=`, which the stamp appends only when the profile sets `time_in_seconds_from_tas` (`scripts/run_flight.py:1288-1294`); `oracles-production` does not, so every 2017 v3.1.4 flight ran S3 at the 170 m/s fallback, as in 2016 (read) | faithful by construction; not a defect of the port |

## 5. Worked case: sub-second times in a `.tas.csv`

One 2017 flight failed in S3 (stage S3, image processing) with `imgProc_sm.m:727 matched 2 TAS samples at time 124838`. The
cause was wider:

- `make-tas-file --from-tas-csv` copied the sub-second S2 times unchanged.
- **Every finished 2017 v3.5 product therefore ran S3 at 170 m/s.** Measured: the implied speed is 170.00 for 100 % of particle pairs.
- S4 read the probe's own series, so sample volume was not on the fallback; the error reaches concentrations only through inter-arrival times and shattering rejection (derived).

The superseded 2017 products are on the external drive (listed in an archive manifest not included in this release),
kept for the before/after comparison.

## 6. Decisions, and where each is announced

| Decision | Announced |
|---|---|
| Whole seconds by **rounding** | log line; `aircraft.cdf` global attributes |
| Duplicate resolved by the **adjacent** second: keep the copy whose TAS equals the second before or after | one log line per resolved second; global attributes |
| Physically impossible rows are never dropped: a value above the cutoff, at or below 0 m/s (including the `-999` marker) or non-finite, and a duplicated second the adjacent-second rule cannot settle, take the default, 170 m/s (`make_tas_file.py:134-135`, `TasPolicy` at `:148`; `reason()` names above-cutoff, non-positive or non-finite) | one log line per substituted second; global attributes (`tas_policy`, `tas_substituted_*`) |
| Impossible means **> 300 m/s**, the largest `tasMax` in UIOOPS's probe table (`constants.py:492`, `:559`) | `tas_cutoff_mps` attribute |
| Cutoff and default are options, not constants: `[tas]` `cutoff_mps` and `default_mps` in a run configuration, `--cutoff-mps` and `--default-mps` on `make-tas-file` (`DEFAULT_CUTOFF_MPS = 300.0`, `DEFAULT_FALLBACK_MPS = 170.0`) | `tas_cutoff_mps`, `tas_default_mps` attributes |
| Seconds the rule cannot settle take the default (`AUTHOR_UNSETTLED_RULE = "default"`, `make_tas_file.py`); `--on-unsettled refuse` keeps the stop-and-list behaviour | log line `TAS substituted: <HHMMSS> ... unsettled-duplicate` |

Owed: the stage-3 log should also echo these decisions when it reads an aircraft file, and the
`.call` stamp should record them. Both are deferred until `_stamps_equivalent` accepts a new key
without invalidating existing products.

## 7. The TAS source chain

No value is dropped: a cutoff and a default, both selectable in the configuration, replace what
cannot be used. The airspeed comes from a campaign merge file where one exists, otherwise from
another reliable aircraft source, and otherwise from the probe file itself; the output's metadata
records which source was followed. Code:
`src/arrayprobe/tools/tas_sources.py`; tests: `tests/test_tas_sources.py`.

### The tiers and the registry

The source is a chain of tiers, tried in order (`TIERS`): **`merge`** (a campaign merge file), then
**`aircraft`** (another reliable aircraft source), then **`probe`** (the probe's own
`<stem>.tas.csv`, reduced under the rules in [TAS_BUILDER.md](TAS_BUILDER.md)). Only sources read
off a real file are registered, each recording the file it came from (`SOURCES`):

| Name | Tier | Variables | Time axis | Units | File pattern |
|---|---|---|---|---|---|
| `uiops-flightdata` | aircraft | `TAS`/`Time` | HHMMSS | m/s (UIOOPS convention) | none -- only when named outright |
| `oracles-p3-merge` | merge | `True_Air_Speed`/`Start_UTC` | seconds of day | read from the `units` attribute | `mrg1_P3_{yyyymmdd}_R*.nc` |
| `arm-aaf-merged` | aircraft | `true_airspeed`/`time` (+ `base_time`) | seconds since `base_time` | read from the `units` attribute | `enaaafmergedF1.c1.{yyyymmdd}.*.nc` |

A file matching no entry's two variable names raises (`identify`), naming what it tried and what
the file carries, rather than guessing.

### Modes

`mode="auto"` walks the tiers and uses the first that is available and passes its checks.
`"merge"` / `"aircraft"` / `"probe"` **pin** one tier and refuse rather than fall through when it
is absent, ambiguous (more than one candidate file) or fails a check -- a pinned source never
falls through silently. Every tier tried is recorded as used, skipped (with the reason it was not
available) or failed (naming the check), in the chain's `steps` and in the file's global
attributes.

### Units are read, not assumed

A source registered as reading its units from the file must carry a `units` attribute naming one
of `UNIT_FACTORS` (`"kts"` = 1852/3600 m/s exactly, the international nautical mile; `"m/s"` =
1.0); an unknown or missing `units` attribute is refused, never guessed. The UIOOPS `TAS`/`Time`
convention carries no `units` attribute and is m/s by definition.

### Policy: never dropped

Every value the chain reads passes through the same `TasPolicy` the builder uses (see
[TAS_BUILDER.md](TAS_BUILDER.md)): a value above `cutoff_mps` (default 300 m/s, the largest
`tas_max` in UIOOPS's probe table), at or below 0 m/s, or non-finite is
substituted with `default_mps` (default 170 m/s, `imgProc_sm.m:365`/`:763`'s own S3 fallback) --
never dropped. A probe second an aircraft source does not cover is *added* at the default rather
than left unset, and listed as `no-aircraft-sample` ranges. Both values are configurable
(`[tas]` in a run configuration; `--cutoff-mps`/`--default-mps` on `make-tas-file`).

### Metadata attributes

The chosen chain's file carries: `tas_chain_mode`, `tas_chain_used` (`<tier>:<source>`),
`tas_chain_steps` (every tier tried and its outcome), `tas_chain_note`, `tas_source`,
`tas_source_evidence`, `tas_units_read`, `tas_unit_factor_to_mps`, `tas_conversions`, the policy
attributes (`tas_policy`, `tas_cutoff_mps`, `tas_default_mps`, `tas_policy_note`),
`tas_substituted_count`, `tas_substituted_seconds` and, when the source is an aircraft file
checked against the probe's own clock, `tas_probe_seconds_covered` / `tas_probe_seconds_total`.

### Midnight: HHMMSS is unwrapped throughout

A flight crossing midnight counts HHMMSS
past 235959 as 240000, 240001, ... rather than wrapping to 000000 -- UIOOPS's own convention, the
one `sizeDist.m`'s `+240000` rollover (`arrayprobe_uiops.sizedist._rollover_240000`) gives particle
times. The TAS chain follows it: `check_tas_series` accepts hours 24-47; `read_aircraft` converts
a seconds-of-day or seconds-since-`base_time` axis to HHMMSS without folding at 86400 s, as the
probe's housekeeping clock is read. A particle time and an aircraft `Time` that both crossed
midnight meet at the same unwrapped HHMMSS, as S3's exact-match lookup needs
(`imgProc_sm.m:727`). The SODA-2 `pth` writer below converts any HHMMSS to seconds of day
without wrapping, so a 240000 sample lands at 86400 s, past every pre-midnight second.

### The S4 rule: the axis stays the probe's

`series_for_sizedist()` builds the series `sizeDist` reads. It keeps the probe's own floored time
axis, because `sizeDist`'s output time base *is* its TAS axis (in the v3.1.4 engine, not included in this release), and swapping the
axis too would move or remove seconds of the product. Only the **values** are replaced: by the
aircraft TAS at the same whole second where one exists and passes the policy, and by
`policy.default_mps` everywhere else (never dropped).

### Floor versus round: which seconds take the default

The chain rounds a fractional probe second half up (`tas_sources.py:263`) and the S4 series
floors it (`tas_sources.py:446`), so a probe second whose fraction is 0.5 or more is keyed one
second later by the chain than by S4. This is reported in the quality record below, not
corrected, because correcting it would change sd values
(established by the 2026-09-23 TAS verification). What the code does (read):

- **The chain rounds.** `resolve_chain` takes the probe's seconds from `<stem>.tas.csv` through
  `_probe_seconds`, which rounds half up in seconds of day, `floor(sod + 0.5)`
  (`tas_sources.py:263`, called at `:332`). An aircraft or merge series is extended over those
  rounded seconds: a rounded probe second the aircraft file lacks is added at
  `policy.default_mps` and listed as substituted, `no-aircraft-sample` (`:285-298`). The probe
  tier reduces the same csv under make-tas-file's second rule, `round` by default
  (`make_tas_file.py:126`, `:365`).
- **S4 floors.** `series_for_sizedist` floors the probe axis (`tas_sources.py:446`) and looks each
  floored second up in the chain by exact key. A second the chain lacks, or whose value fails the
  policy, takes `policy.default_mps` and is returned in `missing` (`:451-457`). `--tas-grid
  regular` floors the same way (`:474`). The driver floors again when it calls `sizeDist`
  (`run_flight.py:3134`, `:3153`) and `sizeDist` floors its `tas_time` (in the v3.1.4 engine, not included in this release, and in
  v3.5 at `arrayprobe_uiops/sizedist.py:1204-1206`); both are no-ops on an axis already whole.
- **The consequence.** A probe sample in the upper half of a second is keyed to the next second
  by the chain and to its own second by S4. When the aircraft series has no sample at the floored
  second, S4 sizes that second with the default, although the chain covers the sample's rounded
  second. On flight 2017-08-12, 13 floored probe seconds were missing from the chain file this way.
- **S3 is keyed differently.** It looks TAS up by the image record's own whole second (hour,
  minute and second from the record header) with exact equality (`src/arrayprobe_uiops/imgproc_core.py:32`), so no
  floor or round of the probe csv enters it. A record second absent from the chain file takes
  `TAS_FALLBACK`, 170 m/s (`src/arrayprobe_uiops/imgproc_core.py:14`; reused by v3.5), not `policy.default_mps`.
  S3 and S4 agree on those seconds only while the default is 170.
- **What the quality record counts.** Every floored second S4 defaulted is in `tas_missing_*`;
  those absent from the chain altogether are in `tas_missing_absent_*` (`tas_sources.py:551`).
  `tas_floor_round_residual_*` is the subset whose sample, rounded, is a chain second
  (`:553-554`). That test applies `np.round` to the HHMMSS value, which rounds half to even and
  does not carry into the next minute, so it counts fewer seconds than `_probe_seconds` moves:
  120010.5 rounds to 120010 where the chain keys it 120011, and 120059.7 rounds to 120060, not a
  clock second, where the chain keys it 120100. Both stay in `tas_missing_absent_*` and out of
  the residual. Measured on those synthetic samples (2026-09-26): of three floored seconds absent
  from a chain built this way, the residual counted one. The residual is a lower bound on seconds
  lost to floor versus round, and `tas_missing_absent_count` an upper one.
- **The legacy path has none of this.** Without a chain (`--tas-file` alone, or no TAS source), S4
  sizes on the probe csv's own values on its own floored axis. There is no lookup, so this rule
  changes no second's value.

### Run-time selection

`[tas]` keys `source`, `search`, `cutoff_mps` and `default_mps`, and flags
`--tas-source {auto,merge,aircraft,probe}`, `--tas-search DIR` (repeatable),
`--tas-cutoff-mps` and `--tas-default-mps` on `run_flight.py` select the chain for a run in place
of a fixed `--tas-file`.

### The run's TAS quality record: which seconds took a default

A run records which of its seconds were sized with a substituted or default airspeed, and the
record travels with the products, not only in the log. `tas_sources.qc_record()` builds it and
`write_qc_sidecar()` writes it as `<product>.tasqc.json`, beside the product:

| Key | Meaning |
|---|---|
| `tas_chain_used`, `tas_policy` | the tier that supplied the series, and the cutoff/default in force |
| `tas_seconds_total` | probe seconds on the product's time axis |
| `tas_substituted_count` / `_ranges` / `_reasons` | seconds whose value the policy replaced, by reason |
| `tas_missing_count` / `_ranges`, `tas_missing_absent_*` | seconds no tier covered, sized with the default |
| `tas_floor_round_residual_count` / `_ranges` | seconds lost between the probe's floored clock and the chain's rounded one (13 on 2017-08-12) |
| `tas_defaulted_fraction`, `tas_uncertainty` | the share sized with the default, and a sentence on what it does to concentration |

Where it goes:

- **S4** writes `<sd>.tasqc.json` whenever a run names a TAS source (`--tas-file` or the chain);
  a probe-only run writes none and removes a stale one. **The combine** merges its parts' records
  (counts summed, ranges joined, `tas_qc_parts` listing the parts) and refuses a mix of parts with
  and without one.
- **The attributed export** folds every key in as `arrayprobe_<key>`, or writes
  `arrayprobe_tas_qc = "absent: …"` when the source has no record.
- **The CF export** adds the same globals and a per-second `tas_quality_flag` (0 measured,
  1 substituted by policy, 2 absent and defaulted) named by every data variable's
  `ancillary_variables`. **The ARM export** adds the globals and a bit-packed `qc_tas` (bit 1
  substituted, bit 2 defaulted; both assessed "Indeterminate").
- **Inside the sd file, by default on engine 3.5.** When a run names a TAS source, every key
  above is written as an `arrayprobe_<key>` global attribute beside `arrayprobe_engine` and
  `arrayprobe_profile`, which that engine always writes (`arrayprobe_uiops.sizedist.run(tas_qc=...)`).
  No variable changes (`tests/test_v35_sd_tas_qc_attrs.py`).
- **Inside the proc file, by default on engine 3.5.** When S3 reads an aircraft series, the
  driver counts the image records whose HHMMSS has no sample in it, which `imgProc_sm.m:727`'s
  exact-match lookup therefore times at 170 m/s (`:730-733`, `:763`), and the proc file carries
  `arrayprobe_tas_s3_source`, `_records_total`, `_fallback_records`, `_fallback_seconds` and
  `_uncertainty` (`run_flight._s3_tas_qc_v35`; the same record on every chunk and the merged file).
  No variable changes (`tests/test_v35_s3_tas_qc_attrs.py`).
- **Inside the SODA-2 export, by default.** `soda2_export_ncdf` writes `arrayprobe_tas_source`
  (the `op.pth` file, `fixedtas` or the probe's own airspeed, the branch `process_2d.py:796-824`
  takes), the seconds total, and the count and `HHMMSS` ranges of seconds whose `TAS` is not
  positive, which SODA-2 leaves at zero concentration (`process_2d.py:1095`). No variable
  changes (`tests/test_soda2_export_ncdf.py::TestTasQualityRecord`).
- **Inside the sd file, in the earlier v3.1.4 translation (not shipped), only when asked.**
  `run_flight.py --write-provenance` (serial) stamped the sd file with `arrayprobe_engine`, `arrayprobe_profile` and `arrayprobe_stage = S4`
  and, when the run names a TAS source, every key above as `arrayprobe_<key>`
  (`sizedist.run(write_provenance=..., provenance_profile=..., provenance_tas_qc=...)`), as it
  stamps S3's proc file. The combined product carries none: `combine_sizedist.m` writes no global
  attributes.
- **By default that translation's products did not change**: no attribute is added to a proc, sd or
  combined file (off, the sd equals the tracked demo reference written before the flag existed in
  every variable, bit for bit, and every attribute but the non-deterministic `Creation Time`,
  measured by a test in the development suite), and the `.call` stamp is untouched, because
  `.call` equality decides staleness.

### The SODA-2 `pth` file

`write_soda2_pth_csv()` writes the same series as a SODA-2 `op.pth` ASCII file: one
`<seconds of day>,<tas>` line per sample, since SODA-2's `op.starttime` is seconds from midnight
(`soda2_process_2d.pro:147-162`, ported as `arrayprobe_soda2.pth_readers.read_pth_ascii`, which
forward-fills each accepted row and accepts `0 < tas < 500`). `make-tas-file ... --soda2-pth
<file>.csv` writes it alongside the aircraft netCDF file. Name it in a SODA-2 run configuration as
`[soda2].pth = "<file>.csv"`.

**If a flight's 2D-S housekeeping TAS is stuck**, build the airspeed from the aircraft file: produce
its `pth` file with `arrayprobe make-tas-file ... --chain aircraft --soda2-pth <file>.csv` (or
`--from-aircraft` naming the aircraft file outright) and set `[soda2].pth = "<file>.csv"` in that
flight's SODA-2 configuration, so SODA-2's own sample volume and particle timing use the aircraft
`true_airspeed` instead of the stuck probe series.
