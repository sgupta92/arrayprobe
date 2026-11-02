# Central configuration file — design (drafted 2026-08-28, implemented the same day)

**Status: implemented.** `arrayprobe.config.load_config` and `scripts/run_flight.py --config`
ship in the port; see the documentation site's *Configuration* page
for the user-facing description. **This document is the design record**, since the inventory, precedence rules and the tests each
parameter had to pass before landing are still the accurate account of *why* the shipped shape
is what it is — read it for that, not for whether the feature exists.

User-directed 2026-08-20 ("a recommendation for a
central config file for a future enhanced UIOOPS") and reaffirmed 2026-08-28 ("there will be
need for a config file eventually where users can opt in to the various enhancements_uiops/fixes and
the different export file options"). This document is the inventory of record for the candidate list of enhancements.

## 1. What the file is for, and what it must never do

- **It never changes what the port computes by default.** `arrayprobe` (the bug-for-bug port)
  stays callable without any config; a config file *selects a `FidelityProfile`* and *opts
  into* enhancements and export options. Absent file ⇒ profile must still be passed explicitly
  (the "no default silently picks a side" rule is unchanged).
- **Every fidelity-changing key maps to a named `FidelityProfile` axis** with `file:line`
  provenance on both sides. A config cannot set a raw threshold on the port; it can only pick
  a profile or an enhancement. This keeps "the port" and "the enhanced output" separable, which
  is a standing design rule: show the bug-for-bug port first and provide the enhanced output
  separately.
- **Enhancements default OFF**, and each opt-in key names the enhancement module that owns it
  (`enhancements_uiops/BACKLOG_STATUS.md` IDs), so the output can say exactly what was applied.
  **Superseded 2026-09-10 for this package only, see
  [`enhancement_registry_design.md`](enhancement_registry_design.md):** the default belongs to
  the pipeline, not the file. The *port* still defaults every enhancement OFF, exactly as this
  bullet says and for the reason it gives. The *enhancements package* defaults them ON,
  opt-out by name, because installing and calling into it is itself the opt-in.
- **The output records the resolved configuration.** The `.call` sidecar `run_flight.py`
  writes today is the seed; the combined product should carry the resolved config verbatim as a
  global attribute (the misreported shattering attribute shows why: the MATLAB output cannot be asked which call made it).

## 2. Inventory of parameters (the candidate list)

| Group | Parameter | Today | Config role | Provenance |
|---|---|---|---|---|
| Fidelity | `profile` | explicit argument | **required** key; `STOCK_V314`, `ORACLES_2016`, `ORACLES_PRODUCTION` | `profiles.py` |
| Fidelity | reject thresholds (`rej_hollow`, `max_edge_img_ar`, `max_comp_img_ar`) | on the profile | via profile only | `calculate_reject_unified.m:73-77` (field-campaign variant) |
| Fidelity | `spec_buffer_guard` | on the profile | via profile only | `read_binary_SPEC.m` (Finlon 2017-03-08) |
| Run | probe/project `(project, probe)` tables (`diodesize`, `armdst`, `tasMax`, `res`, `SAmethod`) | literals in `sizedist.py`/`imgproc.py` per source | selectable by `project`/`probe` keys; overrides only in an enhancement layer | `sizeDist.m` header tables |
| Run | `d_choice` (=6), `SAmethod`, `iRectEllipse` (=0), `iCreateBad`, `iCreateAspectRatio`, `iSaveIntArrSV`, `reaccptShatrs` (=0) | positional/keyword arguments | run keys, defaults = the call that wrote the archived product; changing `iRectEllipse` is unsafe on real 2D-S data | `sizeDist.m:271`, `imgProc_sm.m` |
| Run | the twelfth `sizeDist` argument (`iaThreshFile`) | `run_flight.py` passes a missing-file name | `shattering.threshold_file` key; absent ⇒ block skipped (58 % more particles) — must be explicit, never defaulted | `sizeDist.m:70,866-874` |
| Run | `area_ratio` cut (0.5), `defaultIntArrThresh` (6e-6) | literals, dated field-campaign edits | via profile only | `sizeDist.m:849,874` (field-campaign variant) |
| Run | `Pres`, `Temp` (flight-data sources) | file paths | `inputs.flight_data` | `sizeDist.m` |
| Masking | shadow-diode overrides (`SHADOW_DIODE_OVERRIDES`: 124240→[95], 071623→[77]) | literal table + `--diode-corrected` | `masking.diodes = {file: [diodes]}`; an opt-in correction, recorded in the output | `SHADOW_DIODE_OVERRIDES` table |
| Combine | `flightdate`, `campaign`, `orientation`, `current_year`, `summary_time` | CLI arguments | `combine.*` keys | `combine` port |
| Export | netCDF3 classic vs netCDF4, sidecars (`.MK.csv`, `.call`), which variables | fixed today | `export.*` keys; **format changes are export options, never fidelity changes** | `ncio.py` |
| Enhancements | Korolev out-of-focus, hole/edge swap, `spot_edge` fix, clustering, CNN accept/reject (#27) | separate package, each opt-in | `enhancements.<id> = true` | `enhancements_uiops/BACKLOG_STATUS.md` |

## 3. Shape

TOML (stdlib `tomllib`, no new dependency), one file per campaign or run:

```toml
[fidelity]
profile = "ORACLES_PRODUCTION"          # required; no default

[run]
engine = "3.1.4"
preset = "ORACLES_2016_2DS_H"
raw = ["../raw/base1609*.2DS"]
out = "../_decoded"
stages = "234"
# tas_file = "../aircraft/flightData_160906.cdf"   # only under a profile that reads one (STOCK_V314)

[shattering]
threshold_file = "2DS_intArrThreshold_MISSING.cdf"   # explicit: the twelfth argument

[masking]
diodes = { base160910124240 = [95], base160910071623 = [77] }

[combine]
flight_date = "20160910"; summary_time = "16_09_10_07_14_00"

[export]
format = "NETCDF3_CLASSIC"; write_call_sidecar = true

[enhancements]                          # everything here defaults to false
korolev_out_of_focus = false

[tas]                                   # 2026-09-23: the TAS source chain,
source = "auto"                         # config-file half. "auto" walks merge -> aircraft ->
search = ["../merge"]                   # probe; a pinned tier refuses rather than falling
# cutoff_mps = 300.0                    # through. search dirs are resolved relative to this
# default_mps = 170.0                   # file. cutoff_mps/default_mps default to 300/170 m/s
                                        # (arrayprobe.tools.make_tas_file.TasPolicy).

[arm]                                   # the real ARM identifiers arm_export needs
site_id = "ena"                         # and never invents. site_id/platform_id/facility_id
platform_id = "aaf2dsh"                 # are required TOGETHER -- a 2-of-3 table is refused at
facility_id = "F1"                      # load time -- because a file carrying a guessed ARM id
# data_level = "c1"                     # is indistinguishable from a real one. data_level is
                                        # optional (defaults to export()'s own "c1"). Absent
                                        # [arm] is not an error: arm_export names a skip
                                        # instead, exactly as it did with no [arm] at all.

[outputs]                               # which artefacts the run owes; faithful_attributed and
                                        # enhanced_attributed are true/false, arm is "faithful"/false
faithful_attributed = true              # true = --attributed (the self-describing sibling beside
                                        # the faithful file); false = explicit opt-out; the command
                                        # line wins. Absent section = the run as it is without one.
enhanced_attributed = true              # true = apply the [enhancements] above and export the
                                        # enhanced combined; refused before any stage runs if no
                                        # enhancement is switched on, the stages leave out c, or
                                        # this package is not installed
arm = "faithful"                        # "faithful" = <stem>.arm.nc from the port's own sd, with
                                        # arrayprobe_lineage = "faithful"; needs [arm], else a
                                        # logged skip. false = opt-out. "enhanced" is refused:
                                        # use [enhancements] arm_export = true
analysis_ready = true                   # OUTPUT 2 chunked + compressed (default); false = plain
zarr = false                            # true = also a Zarr store per attributed file ([zarr] extra);
                                        # refused at exit 2 when no attributed output is selected
```

`cf_export`'s own driver adapter needs only the flight date, which travels a different
route: read off the raw stem (`base170707102822` -> `20170707`) rather than out of the config,
the same derivation `run_flight.stage4` uses for sizeDist's own `ddate` argument. No config key
supplies it and none is planned -- a wrong date guessed from a stem would put an incorrect CF
time axis on a file that otherwise looks standards-conformant, so an unrecognised stem yields a
skip instead.

Precedence: CLI argument > config file > profile value; a key that would change a fidelity axis
outside `[fidelity]` is rejected at load time with the message naming the profile axis to use.

## 4. Test obligations before anything lands

1. Loading a config with only `[fidelity]` set reproduces the product-of-record run exactly
   (the existing whole-file gate), i.e. the config layer is invisible to fidelity.
2. Every `[enhancements]` key defaults to false and, when false, the output is byte-identical
   (minus `Creation Time`) to a run without the config.
3. The resolved config is written to the output and round-trips.
4. `arrayprobe` never imports the config loader from `enhancements` (extend
   `test_no_enhancement_coupling.py`); the loader lives in the enhancements package or a small
   `arrayprobe.config` module that only *selects* profiles.

## 5. Open decisions (user)

- ~~Where the loader lives (core `arrayprobe.config` selecting profiles, vs. enhancements-only).~~
  **Closed 2026-09-10: both, split by job.** The core loads and validates the file
  (`arrayprobe.config.load_config`) and carries `[enhancements]` verbatim without interpreting
  it; this package resolves that table into on/off decisions
  (`arrayprobe_enhancements.registry.resolve`) and is the only side that knows what names
  exist. Neither could do the other's half: the core cannot enumerate enhancements without
  importing this package, and this package cannot validate `[fidelity]` without duplicating the
  profile registry. See [`enhancement_registry_design.md`](enhancement_registry_design.md) §3.
- Whether per-file diode masks belong in a config or in a data-driven sidecar next to the raw
  file (they are per-file facts, not choices).
- Whether the twelfth-argument behaviour (absent file ⇒ shattering skipped) should be
  reproduced as-is or made a loud error in the config layer (the port itself must keep it).

## 6. `[fidelity].authordefaults` (minimal form, 2026-09-28)

**Status: implemented, minimal form only.** The recommendation adopted:
*"Minimal version: base profile plus the six reject thresholds, name carrying a content hash,
stamp `authordefaults:<path>#<sha>`, reached by `[fidelity].authordefaults`."* This section
records that design as built, in `arrayprobe.authordefaults`; it does not reopen §5's other open
decisions or the wider free-form file (option B in the archived planning notes) -- the recommendation scoped
this to one axis.

**Shape.** A separate, content-hashed TOML file, e.g. `authordefaults-3f9a1c2b4d5e6f70.toml`:

```toml
[fidelity]
base_profile = "STOCK_V314"          # any shipped profile, either spelling

[thresholds.rej_hollow]
value = false
citation = "S. Gupta, 2026-09-28: matches this instrument's production reject config."

[thresholds.max_edge_img_ar]
value = 4
citation = "S. Gupta, 2026-09-28: same rationale as rej_hollow."
```

Named `authordefaults-<first 16 hex chars of the file's own SHA-256>.toml`
(`arrayprobe.authordefaults.content_hash`/`expected_filename`). A file whose name does not match
its own bytes is refused at load time -- the same "a check must draw its two sides from
different places" shape as every other guard in this project: an edit without a rename is
caught rather than silently changing a run's reject thresholds.

**Why this does not reopen the selection-only rule.** The file is not read by the port. It is TOML input
to a generator (`arrayprobe.authordefaults.resolve_profile`) that builds a full, fully-specified
`FidelityProfile` -- base profile plus `dataclasses.replace` on its `reject_thresholds` -- and
hands it to `profiles.register_profile()`, exactly the completeness and uniqueness rules a
fork's own hand-written registration already enforces. Every override carries a **citation**
(who chose the value, and why), refused if missing -- the same "never invent a fact" discipline
this project applies to a literature claim, applied here to a threshold.

**Reached from a run config** through `[fidelity].authordefaults`, mutually exclusive with
`[fidelity].profile` (a run selects exactly one). Absent, `arrayprobe.config.load_config`
behaves exactly as it did before this key existed (`tests/test_authordefaults.py`'s
`ConfigIntegration.test_absent_key_changes_nothing`). Present, `RunConfig.authordefaults_stamp`
carries `authordefaults:<path>#<sha>`, which `scripts/run_flight.py` appends to every
`config_label()`-based `.call` stamp (proc/sd) through its own `AUTHORDEFAULTS_STAMP` global.

**With `--chunks`** (author-editable thresholds file, 2026-10-05): the chunk guard admits the file, and each
`--_run-chunk` worker receives its path as an `authordefaults=<path>` tail token, re-loads it,
refuses one whose hash differs from the parent's `authordefaults-<hash>` profile, and carries
the same stamp. A `--chunks 2` run writes output identical to `--chunks 1`
(`tests/test_authordefaults_chunks_e2e.py`).

**Test obligations, all met**: loads a valid file; refuses an unknown section, an unknown
threshold key (anything outside the six `RejectConfig` fields), a missing citation, a
type-mismatched value (a number where a boolean is required or vice versa), an unknown base
profile, and a file/content hash mismatch; resolves to a profile whose overridden fields differ
from the base and whose other fields (including the other five reject thresholds) are the
base's, unchanged; is idempotent within one process (a config loaded twice, or by two
`--chunks`/`--jobs` workers, resolves to the same registered profile rather than raising on the
second `register_profile()` call); and the `.call` stamp reaches `config_label()` when present
and leaves it byte-identical when absent.
