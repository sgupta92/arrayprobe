# The attributed second output

The attributed output is a second output carrying these attributes. It is the package's final
output for new products, where byte comparison against an archived file is not needed.

Module: `src/arrayprobe/attributed_export.py`.
Tests: `tests/test_attributed_export.py` (40, correctness) and
`test_attributed_export_is_reachable.py` (10, reachability and the opt-in's two states).

**Three ways in**, all the same code path — the two command forms delegate to
`attributed_export.main` so their flag surfaces cannot drift:

| Way in | When |
|---|---|
| `arrayprobe attributed FAITHFUL.cdf [OUT.nc]` | installed package; the discoverable form (2026-09-18) |
| `python -m arrayprobe.attributed_export FAITHFUL.cdf [OUT.nc]` | no install / inside the repo |
| `run_flight.py … --attributed` | as part of a flight — **opt-in, default off**, §5 |

Library: `arrayprobe.attributed_export.export(...)`.

**Two choices in §3 and §4 (where the second file goes, and ACDD rather than CF) are the current
behaviour and may change in a later release;** either is a one-line change.

---

## 1. The tension, and the half that cannot move

`combine_sizedist.m:202-231` defines ten variables and **zero global and zero variable
attributes** — measured, not inferred: `arrayprobe.combine._write` is a line-for-line port of that
block and contains no `putAtt` call at all, and
`test_attributed_export.py::EveryVariableIsLabelled::test_the_faithful_file_really_does_carry_no_attributes`
re-measures it on a real written file every run. So `Bin Midpoints` reaches a recipient with **no
stated unit**, even though `sizeDist.m:1746` states one for the variable it was copied from.

That absence is not an oversight to fix. Byte-identity against the archived ORACLES products
compares every dimension, variable *and attribute* against a MATLAB file that has none, and fifteen
validated flights plus the whole layer-1 claim rest on that comparison. **Adding metadata to the
faithful writer would break the reproduction**, which is the one thing that cannot be traded.

So: **a second file written beside the faithful one, never a modification of it.** The faithful file
is opened read-only; its SHA-256 is asserted unchanged across an export.

## 2. Why this is not bureaucracy

Explainability is the competitive claim, and the plain fact is that
**our combined file taken alone has the same property we criticise ARM's for**: a recipient cannot
re-derive it. The run's provenance lives in the `.call` sidecar *beside* the file
(`scripts/run_flight.py:959-965`, "beside it, never inside it"), which the recipient does not
necessarily receive. This module folds the whole sidecar into the file, so the attributed output
travels alone and still answers "how was this made".

### What the export writes

**Global, from the `.call` sidecar.** The raw line verbatim as `arrayprobe_call_stamp`, *and*
exploded into one attribute per key: `arrayprobe_engine`, `arrayprobe_profile`,
`arrayprobe_iat_file`, `arrayprobe_tree`, `arrayprobe_shadow_diode`, `arrayprobe_tas_file` when
present. The verbatim line is the record — nothing can be lost to a parsing edge case; the exploded
keys are what a reader's tooling can filter on. **A key this module does not recognise is still
written under its own name**, so a stamp key added later reaches the file with no edit here.

**The nested stamp, and which level wins** (2026-09-21). The only shape this module can export is
`combined_sizedist`, so the only stamp it ever parses is the S4c combine stamp — and that stamp
**nests the whole S4 stamp inside `inputs_built_with=(...)`** (`run_flight._combine_stamp`). The
top-level keys (`engine`, `combine`, `inputs`) describe the product in hand; everything inside
`inputs_built_with` — `profile`, `iat_file`, `tree`, `reject`, the tagged thresholds — is the
provenance of the *files it was stitched from*. `engine` and `profile` therefore exist at both
levels and mean different things, so **the outer level wins and the nested fragment stays nested**:
it is written verbatim as `arrayprobe_inputs_built_with`, parens included, and its fields are not
promoted into the product's own namespace. `attributed_export.parse_nested()` is the supported way
in. The consequence, stated rather than left to be discovered: **on a combined product the
`arrayprobe_reject_*` and `arrayprobe_<threshold>_source` attributes below are not written**, because
those keys are not at the top level of that stamp — they are inside the fragment. Whether they
should also be exported under an `arrayprobe_inputs_built_with_<field>` prefix is not
decided; the omission is deliberate.

Before the 2026-09-21 fix the parser was not paren-aware, so this stamp misparsed: `inputs_built_with`
truncated to `'(engine=3.1.4'`, the inputs' `profile`/`iat_file`/`tree` were silently written under
the product's own names, and the closing paren landed on the last threshold, where
`parse_tagged_value` raised `StampParseError`. The driver logged `S4c ATTRIBUTED skipped`, printed
`ALL DONE` and exited 0 — so **`--attributed` wrote no file for any product this driver has ever
written**, and no test caught it because the round-trip test paired the S4 stamp with a
combined-shaped fixture, a pairing `run_flight.py` never writes. A requested sibling that was not written is `rc=1`.

- **The reject configuration**: `arrayprobe_reject` raw, plus `arrayprobe_reject_<field>` per field.
  Parsed off whatever the fragment holds rather than a fixed list, because `run_flight.py:873-874`
  builds it off the `RejectConfig` dataclass's own fields.
- **Every threshold with its provenance tag**, split into two attributes that are never
  blurred: `arrayprobe_area_ratio_z` (the number) and `arrayprobe_area_ratio_z_source`
  (`stock` / `regime:<name>` / `user:<path>`), same for `default_int_arr_thresh`. The two fields are
  tagged independently, because a run may mix origins and reporting both as whichever was set last
  is exactly the blurring the tag exists to prevent (`regimes.ResolvedThresholds`' own docstring).
- **The enhancements resolved ON**: `none` for the port, by construction — "the port is the faithful
  reproduction and nothing else", enforced by `tests/test_no_enhancement_coupling.py`. A non-port
  producer names what it applied through the exporter's `enhancements` argument; the basis attribute
  says which of the two you are looking at.
- **Provenance of the pair**: `arrayprobe_source_file`, `arrayprobe_source_sha256`,
  `arrayprobe_source_bytes`, `arrayprobe_source_writer` (the MATLAB block), `arrayprobe_files_stitched`
  (from the dimension no variable uses), `arrayprobe_export_time`, `arrayprobe_package_version`.
- **`arrayprobe_fidelity_note`**, which states in the file that **this is not the byte-comparison
  artefact** — use the faithful file for that, this one to read the data.

**Per variable: `units`, `long_name`, `arrayprobe_units_basis`, `arrayprobe_source_units`.**

### Units are sourced, never invented

Every unit is the string `sizeDist.m` itself writes for the `sd` variable the value was copied from,
read in the ORACLES-variant `sizeDist.m` — the tree that processed the real ORACLES products:

| Combined variable | From `sd` | `units` | Basis |
|---|---|---|---|
| `Time Vector` | `time` | `days` | **derived** — `sd` `time` is HHMMSS (`:1732`), but `combine_sizedist.m:95-120` converts it to a MATLAB datenum |
| `Bin Minimum` | `bin_min` | `mm` | read, `:1736` `millimeter` |
| `Bin Maximum` | `bin_max` | `mm` | read, `:1741` |
| `Bin Midpoints` | `bin_mid` | `mm` | read, `:1746` — the variable whose missing unit prompted this |
| `Bin Width` | `bin_dD` | `mm` | read, `:1751` |
| `Mean Area Ratio` | `mean_area_ratio` | `1` | read, `:1834` |
| `Counts` | `count` | `1` | read, `:1829` |
| `Size Distribution cm-3` | `conc_minR` | `cm-3` | **derived** — `conc_minR` is `cm-4` (`:1757`), `bin_dD` is mm (`:1751`); `combine_sizedist.m:47-50` writes `(conc_minR / 10) * bin_dD`, and `/10` *is* the mm→cm conversion, so cm-4 × cm = cm-3 |
| `Number Concentration cm-3` | `n` | `cm-3` | read, `:1772` |
| `Reject Ratio` | `Reject_ratio` | `1` | read, `:1807` writes `100/100`, kept verbatim in `arrayprobe_source_units` |

Each row's `arrayprobe_units_basis` starts with `read` or `derived` and carries the citation, so a
recipient can check the claim without this document. **A product shape with no sourced unit table is
refused by name** (`UnknownProductError`), never exported with a guessed unit — one shape ships
today, `combined_sizedist`.

`Time Vector`'s conversion is stated in the file rather than performed: `arrayprobe_time_convention`
plus `arrayprobe_datenum_unix_epoch_days = 719529.0`, **measured** from
`matlab_compat.datenum(1970, 1, 1)` and re-asserted against it by the tests.

### Value-preserving, which is the property the tests assert

Every variable is written with its source dtype, its source dimension list **in the source's own
on-disk order**, and values asserted equal by `np.array_equal(..., equal_nan=True)` — NaN padding
included. Nothing is rescaled, renamed, reordered or transposed. In particular this module takes no
view on MATLAB dimension order and **hand-rolls no transpose**: a verbatim structural
copy needs neither. No `_FillValue` is added, because adding one would change what a masking reader
returns.

NETCDF4, which adds no dependency (`netCDF4` and `numpy` are already the package's two hard
requirements). The NETCDF3_CLASSIC constraint exists to match MATLAB's bare `'clobber'` default and
does not apply to a file with no MATLAB counterpart; the tests assert the *source* is still
NETCDF3_CLASSIC afterwards.

## 3. Where the second file goes

**Current layout:** same directory, same stem, new suffix; it may change in a later release —
`base160906064017.combined.H.2DS_2.cdf` → `base160906064017.combined.H.2DS_2.cdf.attributed.nc`
(`DEFAULT_SUFFIX`, overridable per call).

Why this one: co-location makes the correspondence obvious in a directory listing and the pair sorts
adjacently; `.nc` says NETCDF4 where the ORACLES product says `.cdf`; and **nothing about the
faithful file's own name changes**, which matters because every validated comparison addresses it by
name. Rejected: a separate `attributed/` directory (the pair stops being visibly a pair, and the
sidecar is already co-located) and a replaced extension (two files then differ only by extension,
and the `.cdf`/`.nc` distinction already means engine, `_IMAGE_SUFFIX`).

An alternative is **a delivery directory**: if the attributed file is
what leaves the building, a `deliver/` tree holding only attributed files may be the better default,
precisely because the file is self-sufficient. One line in `default_output_path`.

## 4. Is the target convention formally CF?

**Current behaviour:** ACDD, not CF. Where the faithful file states none, `Conventions` is written as
`"ACDD-1.3, arrayprobe-attributed-1.0"`, and the run record is also written under the six ACDD-1.3
discovery names (`Conventions`, `history`, `source`, `processing_level`, `product_version`,
`date_created`; `attributed_export.ACDD_KEYS`), each only where the faithful file does not already
hold it. The file still declares `arrayprobe_export_convention = "arrayprobe-attributed-1.0"` and
states every unit's provenance. CF is not asserted, for the reasons below.

CF is the obvious target and `arrayprobe_enhancements.cf_export` already does the CF work for `sd`
files. Two things stopped this module asserting it:

1. **The port never imports `enhancements_uiops/`** (`tests/test_no_enhancement_coupling.py`),
   so CF logic here would be a reimplementation, not a reuse.
2. **`Conventions = "CF-1.x"` would be a claim this module cannot verify.** `Time Vector` is a MATLAB
   datenum; there is no udunits `days since <epoch>` spelling that is correct **without changing the
   value**, and changing a value is the one thing a value-preserving export must not do. CF
   compliance would need either a rewritten time axis or an added derived coordinate.

**What formalising on CF would cost**, if a later release does it: a second time variable
(`time = (Time Vector - 719529) * 86400`, `units = "seconds since 1970-01-01T00:00:00Z"`) written
*alongside* the untouched original, plus `bounds` variables built from `Bin Minimum`/`Bin Maximum`
for the size coordinate. Both are additions, so the value-preservation property survives; the export
stops being a pure copy and starts computing, which is the line this module currently does not
cross. `standard_name` would stay unwritten either way — the CF table has no entry for an OAP
size-distribution quantity, and inventing one is forbidden by CF itself.

## 5. Scope, and what is deliberately not here

- **One product shape**: the combined `sizeDist` product, which is the "final output" a user takes
  away. `sd` and `proc` shapes need their own sourced tables; `proc` in particular
  carries no `units` on any of its 41 variables, so each would have to be read out of
  `imgProc_sm.m` (the same reason `cf_export` scopes itself to `sd`).
- **Analysis-ready by default, lossless.** The export is chunked (at most 3600 along any dimension
  longer than 256, one hour of 1 Hz seconds; whole along shorter ones, such as a bin axis) and
  zlib-compressed at level 4, with the byte-shuffle filter on integer variables only. The level and
  the shuffle choice are the ones `arrayprobe_enhancements.arco_export` measured; they are cited in
  `attributed_export.py`, not imported. Every value, dtype and dimension order is the faithful
  file's. `analysis_ready=False` (`[outputs] analysis_ready = false`) writes it plain, contiguous
  and uncompressed. The file states which it is in `arrayprobe_encoding`.
- **An opt-in Zarr copy.** `export_zarr` (`[outputs] zarr = true` in a run, or
  `python -m arrayprobe.attributed_export FAITHFUL.cdf --zarr`) writes a `.attributed.zarr` store
  beside the netCDF4 file with the same chunking. It needs `pip install arrayprobe[zarr]`.
- **An opt-in Parquet copy.** `export_parquet` (`[outputs] parquet = true` in a run, or
  `python -m arrayprobe.attributed_export FAITHFUL.cdf --parquet`) writes a `.attributed.parquet`
  directory beside the netCDF4 file: one Parquet file per distinct dimension tuple in long form
  (an int64 index column per dimension, then one column per variable, dtype kept) and the scalars
  in `scalars.parquet`, with the global and per-variable attributes as JSON in each file's schema
  metadata. It needs `pip install arrayprobe[parquet]` (pyarrow).
- **A machine check.** `python -m arrayprobe.ai_ready FILE` (netCDF4 or Zarr) tests every claim
  above, each as a named check: `units`/`long_name` on every variable, the ACDD discovery block,
  `Conventions` naming ACDD, the run record, the source hash and the encoding statement.
- **Wired into `scripts/run_flight.py`, opt-in and default off.**
  `run_flight.py --attributed` writes the sibling after the combine — on the finished-combine path
  *and* on the already-current skip path, because a re-run on a finished directory is exactly when
  someone reaches for the flag. `run_flight.write_attributed` is the one call site's worth of code;
  a failure there is logged and swallowed rather than failing a flight whose faithful product is
  already written and validated. Both states are tested
  (`tests/test_attributed_export_is_reachable.py`): the flag is a `store_true` with no overridden
  default, both calls inside `stage_combine` are asserted (by AST) to sit under `if attributed`, and
  with it on the faithful file's SHA-256 is unchanged.
- **The parser's one known limit**: a stamp value containing a space-separated `word=` (a Windows
  path with a space in it) would split wrongly. That is why the raw line is always written verbatim
  — the parsed keys are a convenience, the raw line is the record.

## 6. What the tests cover

`test_attributed_export.py`, 73 tests. The fixture is built by calling `combine._write` itself, so a
rename in the faithful writer fails these tests rather than producing an exporter that silently
refuses every real product.

- **The faithful file does not move** — SHA-256 identical across an export; still NETCDF3_CLASSIC;
  writing over it is refused.
- **Values survive exactly** — per variable: dtype, on-disk dimension list, and
  `np.array_equal(equal_nan=True)`; a NaN row stays NaN with no `_FillValue`.
- **Every variable is labelled** — and the faithful file is re-measured as carrying nothing.
- **A real stamp round-trips** — *two sides from different places*: the stamp is built by
  `run_flight.sd_call_label` / `thresholds_stamp`, so a change to the stamp's shape fails here.
- **Threshold tags survive** — `stock`, `regime:<name>`, `user:<path>`, tagged independently; every
  shipped regime name round-trips through `ResolvedField.render()`.
- **The datenum epoch is measured** — against `matlab_compat.datenum`, and the conversion recovers
  the flight date.
- **Refusals** — unknown product shape, unstamped source (with `accept_unstamped` recording the gap
  rather than leaving it blank), duplicated stamp key, untagged threshold, unparenthesised reject.
- **An older stamp** with no `engine=` key (written by the earlier v3.1.4 translation, not shipped) is read as
  `engine=3.1.4`, the way `run_flight._stamps_equivalent` reads it, and says it inferred rather than read it.
