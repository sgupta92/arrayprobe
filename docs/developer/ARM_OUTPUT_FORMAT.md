# A fourth output category: ARM-convention netCDF

What it takes to treat ARM Data File Standards conformant output as a first-class output
category, `arm_output`, beside (1) files reproducing original UIOOPS output, (2) SODA-2 output and
(3) the port's own files carrying `arrayprobe`-native provenance (`.call` sidecars, `arco_export`,
etc.). The implementation is `enhancements_uiops/`'s `arm_export.py`; this document reads it against the
standard and names the gaps and the design for closing them.

Every claim cites the standard, by section, or a repository `file:line`; what neither settles is
listed in §4.

---

## 0. The standard, verified from the primary document

**Title (cover page, verified):** *ARM Data File Standards*
**Version: 1.3**, ARM Standards Committee, **September 2020**
**Document number: DOE/SC-ARM-15-004**
**URL: https://www.arm.gov/publications/programdocs/doe-sc-arm-15-004.pdf**

Read from the PDF itself, page by page (front matter, §1–§6.8, the table of contents), not from a
secondary source or `arm_export.py`'s citations. The module's citation, "DOE/SC-ARM-15-004, ARM
Data File Standards, v1.3, September 2020" (`enhancements_uiops/src/arrayprobe_enhancements/arm_export.py:10-11`),
matches its title, version and date. A prior version, *DOE/SC-ARM-14-010, ARM Data File
Standards, Version 1.0/1.2* (2016), is at arm.gov/OSTI, superseded and not read.

### 0.1 Datastream / file naming grammar (§5.0–5.1.3, document pp. 4–9)

The netCDF filename grammar (§5.1, p. 4), quoted:

> `(sss)(inst)(qualifier)(temporal)(Fn).(dl).(yyyymmdd).(hhmmss).nc`

where **all characters are lowercase except the facility indicator**, and only `a-z`, `A-Z`,
`0-9` and `.` are allowed (§5.1, p. 4). Components:

- **`sss`** — three-letter ARM site identifier (e.g. `sgp`, `ena`). For ARM Aerial Facility (AAF)
  deployments, chosen from the departure airport unless a geographic area is more appropriate
  (§5.1, p. 4).
- **`inst`** — the ARM instrument abbreviation or VAP name (§5.1, p. 4).
- **`qualifier`** — optional, distinguishes the file from others from the same instrument (§5.1,
  p. 4).
- **`temporal`** — optional data-temporal-resolution descriptor with a required units suffix
  (`ns`/`us`/`ms`/`s`/`m`/`h`/`d`/`mo`/`yr`) (§5.1, p. 4).
- **`Fn`** — the two- or three-character facility designation: a capital letter followed by one
  or two digits (e.g. `S1`, `C1`, `E13`, `F1`); `F` = ARM Aerial Facility manned aircraft, `U` =
  AAF unmanned aircraft (§5.1.2, pp. 6, 8).
- **`dl`** — the two-character data level: one lowercase letter + one digit, except RAW which is
  two digits (`00`) (§5.1.3, p. 8). Levels relevant to a derived product: `a1` = calibrated,
  geophysical units; `b1` = QC applied; `c1` = derived/calculated VAP output (§5.1.3, pp. 9).
- **`yyyymmdd`**, **`hhmmss`** — UTC start date/time of the first data point, exactly 8 and 6
  digits, zero-padded (§5.1, p. 5).

**Length limits (§5.1.1, p. 5, required):** total filename ≤ 60 characters; the **datastream**
portion `(sss)(inst)(qualifier)(temporal)(Fn).(dl)` ≤ **33 characters**; the instrument-description
portion `(inst)(qualifier)(temporal)` ≤ 24 characters.

**The `datastream` global attribute's formula** (§6.7.1, p. 33, worked example on the same page):

> `datastream: definition: Datastream identifier. This will equal site_id + platform_id +
> facility_id + "." + data_level`, example `"sgpmfrsrE32.b1"`.

### 0.2 Time: `base_time` / `time_offset` / `time` (§6.1.2–6.1.3, document pp. 15–16)

Quoted in full, because the implementation is checked against the exact wording:

- `base_time` — a scalar `int`/long integer, epoch seconds ("seconds since January 1, 1970
  00:00:00", UTC by default); carries `long_name = "Base time in Epoch"`, `units = "seconds since
  1970-1-1 0:00:00 0:00"`, a `string` attribute giving the human-readable date (worked example:
  `"18-Sep-2012,00:00:00 GMT"`), and `ancillary_variables = "time_offset"` (§6.1.2, p. 15).
- `time_offset` — double-precision, one value per time step, `units = "seconds since <base_time's
  date> 00:00:00 0:00"`, `ancillary_variables = "base_time"` (§6.1.2, p. 15).
- `time` — a CF coordinate variable, `units = "seconds since <date>"`, `standard_name = "time"`,
  optional `calendar` (Gregorian is the default and need not be declared) (§6.1.3, p. 15).
- Epoch time for sample `i` is `base_time + time_offset[i]`; `base_time + time_offset[0]` must
  equal the timestamp encoded in the filename (§6.1.2, p. 15).

### 0.3 Variable attributes, `missing_value`/`_FillValue` (§6.6, document pp. 26–29)

- **Required (§6.6.1, p. 26):** `long_name` (unique within the file) and `units` (a udunits
  string; `"1"` for unitless — not `"unitless"`, changed from v1.2, §3.1, p. 3).
- **Required with conditions (§6.6.2, p. 27):** *"If the data variable uses a single specific
  value to represent no data, a `missing_value` or `_FillValue` variable attribute must be
  declared... If more than one value is used to represent missing value or non-valid data, use
  `valid_range`... instead."* No required numeric value; `-9999` is the recommended default if a
  new one is picked, and the attribute type must match the variable's type. `standard_name` is
  required only if the variable is a primary variable **and** a CF standard name exists for it
  (§6.6.2, p. 27) — inventing one when none exists is explicitly disallowed (§6.6.4, p. 27,
  linking to the CF standard-name table).
- **§6.6.3 (p. 27) discussion:** CF and NCO have moved from `missing_value` to `_FillValue`; if
  both are defined, use the same value for both.

### 0.4 Required and recommended global attributes (§6.7.1, document pp. 30–34)

The document's convention: *"Required global attributes are **bold-underline**"* (§6.7.1,
p. 30), read from the rendered PDF at full page resolution, not from OCR text:

**Required (bold-underlined in the source):** `command_line`, `Conventions`, `site_id`,
`platform_id`, `facility_id`, `data_level`, `datastream`, `title`, `institution`, `description`,
`history` (§6.7.1, pp. 31–34).

**Recommended or conditionally required (underlined only, not bold — i.e. *not* required by the
document's own typographic convention), with the condition stated where the text gives one:**

| Attribute | Condition, as stated (§6.7.1) |
|---|---|
| `doi` | "required in all baseline and evaluation datastreams, with two [named radar/LASSO] exceptions" (p. 30) — required in practice for ADC-published baseline data, but not part of the bold-underlined set on p. 34, and unreachable without an ADC registration |
| `doi_url` | follows from `doi` |
| `command_line_comment` | records exceptional switches only |
| `process_version` | records the ingest/VAP software version (p. 31) — **underlined, not bold**: recommended, not required |
| `dod_version` | records the ARM DOD version (p. 31) |
| `input_datastreams` | "VAP or ingest reading ARM datastream only; required with conditions" (p. 31) — n/a to this project, which reads no ARM datastream as input |
| `input_source` | "ingest only; required only if reading RAW data" (p. 32) — n/a, same reason |
| `location_description` | p. 32 |
| `serial_number` | "ingest only, required with stipulation" (p. 33) |
| `sampling_interval`, `averaging_interval`, `sensor_height` | p. 33 |
| `references` | p. 34 |

**Conventions attribute format (§6.7.1, p. 31):** `"ARM"` prepended to the standards-document
version, joined with a hyphen, ARM listed first when combined with other conventions; worked
example `"ARM-1.0 Cf/Radial-1.6 instrument_parameters radar_parameters radar_calibration"`.

### 0.5 Quality control parallel variables (§6.8, document p. 34)

QC variables are **optional** (§3.0, p. 3: *"quality control... variable[s]... [are]... optional
and up to the discretion of the developer/mentor/translator"*). When used: named `qc_<varname>`,
`flag_method = "bit"`, required attributes `long_name = "Quality check results on variable:
<long_name>"`, `units = "1"`, a `description` explaining the bit-packing, and the data variable
gets `ancillary_variables = "<qc varname>"` (§6.8.2, p. 35).

### 0.6 Variable-naming conventions (§6.4, document pp. 22–23, all *recommended*, none *required*)

First character a letter; words joined by `_`; ≤ 64 characters; singular, not plural; no
single-character names; sparing use of upper case; no Greek letters. A ten-level name hierarchy
(`[qc/source/be prefix][interpolation prefix][measurement][subcategory][medium][height/depth]
[enumeration][source name][algorithm][quantity]`) resolves naming conflicts (§6.4.1, p. 22).

---

## 1. What `arm_export.py` already satisfies

The module is `enhancements_uiops/src/arrayprobe_enhancements/arm_export.py` (244 lines), with tests in
`enhancements_uiops/tests/test_arm_export.py` (222 lines). It writes a structural ARM/CF copy of a port
`sd` output, never modifying the source file. `file:line` throughout:

- **Cites the right document, correctly.** `arm_export.py:10-11` names "DOE/SC-ARM-15-004 (ARM
  Data File Standards, v1.3, September 2020)" — verified correct against §0 above.
- **`base_time`/`time_offset`/`time` triple**, matching §6.1.2/6.1.3 attribute-for-attribute:
  `arm_export.py:164-185`. The `base_time.string` format `flight_date.strftime("%d-%b-%Y,00:00:00
  GMT")` (`:168`) reproduces the standard's own worked example format exactly ("18-Sep-2012,
  00:00:00 GMT", §6.1.2 p. 15). `ancillary_variables` is set both directions (`:169`, `:177`),
  matching §6.1.2.
- **Datastream identifier formula.** `build_datastream_id()` (`arm_export.py:117-126`) implements
  `site_id + platform_id + facility_id + "." + data_level`, lower-casing everything except the
  caller-supplied facility case — matching §6.7.1's formula and §5.1's "all lowercase except
  facility" rule. `test_arm_export.py:70-73` checks it against the standard's own worked example
  (`sgpmfrsrE32.b1`) verbatim.
- **All eleven required (bold-underlined) global attributes are written**:
  `command_line`, `Conventions`, `site_id`, `platform_id`, `facility_id`, `data_level`,
  `datastream`, `title`, `institution`, `description`, `history` — `arm_export.py:216-236`.
  `test_arm_export.py:122-133` (`test_required_global_attributes_are_present`) asserts all eleven
  by name and asserts `Conventions` contains both `"ARM-1.3"` and `"CF-1.9"` tokens.
  (The module also writes `process_version`, `:219-220`, which §0.4 shows is *recommended*; the
  docstring at `:19-22` lists it among the required attributes — §2.4.)
- **`Conventions` format.** `CONVENTIONS = f"ARM-{ARM_STANDARDS_VERSION} CF-1.9"` (`:72-77`)
  matches §6.7.1's "ARM" + hyphen + version, ARM listed first, space-joined with other
  conventions.
- **Explicit non-claims**, each justified against the standard: no
  `doi`/`doi_url` (`:27-29` — §0.4, ADC-registration-gated); no QC parallel variables (`:30-32` —
  §0.5, optional, and the port has no QC framework); no invented `standard_name` (`:33-38`,
  `test_arm_export.py:111-120` asserts `n` gets no `standard_name` — applying
  §6.6.2/§6.6.4's "creating a new string value... is not allowed" rule, quoted in the docstring at
  `:36`); no invented `site_id`/`facility_id`/`platform_id` — all three are required call-time
  arguments with no default (`:129-134`).
- **Never touches the source file**, copying every value unchanged when `rescale=False`
  (`:209-210`), delegated to `cf_export.write_variables`/`write_bin_bounds`
  (`enhancements_uiops/src/arrayprobe_enhancements/cf_export.py`), itself the source of the udunits-legal
  `units` strings (`cf_export.py` module docstring, `:1-72`) and CF §7.1 bin `bounds`
  (`arm_export.py:211-214`).
- **Preserves the original HHMMSS time series rather than discarding it** (`time_hhmmss`,
  `arm_export.py:190-200`).
- **Exercised against a real port-shaped file**, not only a synthetic one:
  `test_arm_export.py:145-171` runs `export()` against a real-data fixture,
  `s4_sizedist_octave_golden.nc`, which is not distributed (the package ships no measured
  data), so the test skips without it and checks every non-time variable
  survives byte-for-byte.
- **Checked against an independent ARM/CF reader.** `test_arm_export.py:174-217`
  (`ReadableByRealArmTools`) reads the output with ACT's `act.io.read_arm_netcdf` and asserts
  ACT's `_arm_standards_flag == 1`. Skipped when `act-atmos` is not installed (`:180-184`); not in
  CI or any declared extra, a heavy optional dependency (`:11-13`).

## 2. Gaps against the standard

In order of how much each blocks treating `arm_output` as a fourth category rather than a
demonstration module; §2.1, §2.2 and §2.5 are closed.

### 2.1 Running it from the pipeline

`arm_export` runs from the enhancements driver as a product export
(`enhancements_uiops/src/arrayprobe_enhancements/pipeline.py`, `_apply_arm_export`) on the run's most-corrected
`sd` output. It needs the real ARM `site_id`, `platform_id` and `facility_id` from the run
configuration's `[arm]` table (take the ids from ARM's own datastream name for your site and platform)
and the flight's UTC date from the raw stem; without either it is a named skip, never a placeholder
identifier. `data_level` defaults to `c1`. Calling `arrayprobe_enhancements.arm_export.export(...)` from
Python works as well.

### 2.2 File-naming grammar (§5.1): opt-in builder and check

`build_filename(site_id, platform_id, facility_id, data_level, start)` returns
`(sss)(inst)(Fn).(dl).(yyyymmdd).(hhmmss).nc` (§0.1) for the UTC time of the first data point,
with `platform_id` carrying the instrument description and any qualifier/temporal suffix (24
characters at most). `check_filename(name)` raises `ArmFilenameError` on a character outside
`a-z A-Z 0-9 .`, a name over 60 characters, or a datastream portion over 33 (§5.1.1).
`export(..., check_name=True)` applies the check to `outfile`; by default `outfile` is any
caller-supplied path and is not checked. Tests: `enhancements_uiops/tests/test_arm_export_standard.py`.

### 2.3 `missing_value` is opt-in; `_FillValue` (§6.6.2) is open

`cf_export.py:206-210` (`_values()`, which `arm_export` uses for every non-time variable via
`write_variables`) fills masked source values with `NaN` (floats) or the source's own
`fill_value` (non-floats). Per §6.6.2 (§0.3), an attribute naming that value is required *with a
condition* -- "if the data variable uses a single specific value to represent no data" -- and the
port's `sd` output variables meet the condition.

- **`missing_value`**: `export(..., declare_missing_value=True)` writes it on every copied data
  variable, naming the value the variable pass already writes. It is off by default because what
  value, if any, the port's `sd` variables use for missing data at the source has not been
  checked against `sizeDist.m`'s own convention; that check decides whether the default turns on.
- **`_FillValue`**: not written. netCDF4 accepts it only when a variable is created, so it needs
  `cf_export.write_variables` to set it at creation.

### 2.4 `process_version` documentation mischaracterization

The docstring (`arm_export.py:19-22`) lists `process_version` with the eleven required attributes
as "read directly from the standard... global attribute definitions." Per §0.4 its heading is
underlined but **not bold**: recommended. The module writes it (`:219-220`), so nothing is
missing; the citation should say "recommended", so a reader does not take it as evidence the
required/recommended line was drawn correctly elsewhere.

### 2.5 Recommended attributes: written when supplied

Six §6.7.1 recommended (not required) attributes -- `sampling_interval`, `averaging_interval`,
`sensor_height`, `location_description`, `references`, `dod_version` -- are written through
`export(..., recommended_attributes={...})`, which refuses any other key. Nothing in a port output
states them, so by default they are absent, with no "not provided" placeholder (the standard asks
for none); the module docstring names the omission.

### 2.6 Variable names are not remapped to §6.4's naming convention

Every physical variable is copied under its UIOOPS-native name (`conc_minR`, `habitsd`, `Prec_rate`,
etc. — `cf_export.py`'s `CfMapping` table keys on these exact source names). §6.4 is guidance, not
a required standard (§0.6), and several UIOOPS names already violate its "sparing" use of upper
case (`Prec_rate`) and its preference for full words over abbreviations. The module's design is
"changes no computed number... every value copied unchanged", and renaming would break tooling
that reads the port's variable names downstream. An accepted scope boundary, not yet stated in the
module, rather than a defect.

### 2.7 QC parallel variables and DOI/`input_datastreams` — correctly scoped, not gaps

Per §0.4/§0.5, these are blocked on things outside this project's
control (an ARM Data Center registration for a DOI; a per-value QC test framework this port does
not have) or inapplicable (`input_datastreams`/`input_source` are ingest/VAP-reading-ARM-
data attributes; this project produces ARM-*shaped* output from its own, non-ARM processing, so
neither applies). The module's disclaimers are accurate.

---

## 3. Design for `arm_output` as a fourth output category

`arm_export.py` already gets the error-prone parts right: the `base_time`/`time_offset` encoding,
the datastream formula, the required-attribute set and, alone among this project's export paths,
a check against an independent ARM/CF reader. The design makes ARM-convention output something a
run asks for, as it asks for UIOOPS-shaped or SODA-2 output.

1. **An `[arm]` configuration table** (site_id, platform_id, facility_id, data_level,
   institution), selection-only by the rule that no thresholds in a config file), carrying real
   ARM identifiers, never invented ones (`arm_export.py:39-44`). Built (§2.1).
2. **A driver adapter and a CLI entry point**, the latter mirroring `cf_export.py`'s
   `if __name__ == "__main__"` block (`cf_export.py:68-71`). The adapter is built (§2.1; the
   blocker in `pipeline.py`'s `_NO_ADAPTER_REASON_BY_NAME` closed 2026-09-21); `arm_export.py` has
   no `__main__` block.
3. **A §5.1 filename builder and check**, validated against the 60- and 33-character limits
   (§5.1.1) and the allowed characters (§5.1); `export()` still accepts an explicit `outfile`.
   Built (§2.2).
4. **`missing_value`/`_FillValue` on every copied variable**, once what value, if any,
   `sizeDist.m`'s output uses for missing data is read from the source rather than assumed — the
   one item that needs a measurement, not wiring. `missing_value` is opt-in; `_FillValue` is open
   (§2.3).
5. **Correct the docstring's required/recommended citation** for `process_version` (§2.4), a
   documentation fix with no behaviour change. Open.
6. **Populate or disclaim the six recommended attributes** (§2.5), as `doi` and QC are
   disclaimed. Built: written when supplied, named in the docstring otherwise.
7. **Keep the category's shape**: opt-in, default-off, changes no computed number (the class of
   `arco_export`/`cf_export`, `arm_export.py:46-57`), lives in `enhancements_uiops/` (never imported by
   the faithful port), and keeps its own oracle, `ReadableByRealArmTools` against `act-atmos`, as
   the evidence that a generic ARM/CF reader accepts the file.
8. **Leave QC parallel variables, `doi` and `input_datastreams`/`input_source` out** (§2.7): the
   standard requires none of them of a product not ingested by ARM, and no ARM Data Center
   registration backs a DOI.

---

## 4. What is not verified

- **Whether `sizeDist.m`'s output ever uses a specific missing-data value** (§2.3, §3 item 4) —
  needs a reading of `sizeDist.m`'s write path.
- **Whether any later ARM Data File Standards version than 1.3 (September 2020) exists.** A web
  search found only 1.0 (2016), 1.2 (2016) and 1.3 (September 2020) at arm.gov/OSTI, and no
  reference to a 1.4 or 2.0. arm.gov's documentation index was not searched exhaustively, so
  1.3 being current is what was found, not a claim.
