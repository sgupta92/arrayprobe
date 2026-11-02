# API reference: the size-distribution pipeline
> Generated from `src/arrayprobe`'s own AST; never hand-typed. Regenerate with `docs/_build/apidoc.py`.

Shared tooling, readers and the command line. An earlier translation of UIOOPS v3.1.4 reproduced archived products and is not part of this package; its engine modules are not shipped.

**See also** [CLI reference](13-cli-reference.md) · [Reference](08-reference.md).

## `arrayprobe.jit_kernels`

Opt-in accelerated kernels for the particle-image stage -- ``imgproc_sm(..., jit=True)``.

### `JitKernels`

```python
class JitKernels
```

The compiled kernels, and the drop-in functions imgproc calls through.

### `load`

```python
def load() -> JitKernels
```

Import numba and compile (or load from cache) the kernels, once per process.

### `FALLBACKS`

```python
FALLBACKS: dict
```

## `arrayprobe.sizing`

The size-definition registry -- an extensibility seam.

### `SizeDefinition`

```python
class SizeDefinition
```

One named way of reducing a particle image to a diameter.

Parameters
----------
key:
    The registry name.  Stamped into output provenance, so it is part of the
    file contract once the framing stage writes it: treat renames as breaking changes.
func:
    The callable.  Signatures deliberately differ between definitions -- a
    chord-table definition and a min-enclosing-circle definition do not take
    the same arguments -- so the registry carries no signature contract.
phase:
    ``"any"``, ``"liquid"`` or ``"ice"``.  Anything but ``"any"`` is barred
    from `universal_size_definition`.
description:
    One line, shown by `available_size_definitions`.
provenance:
    ``file:line`` in the MATLAB source, or the literature reference.
outputs:
    The names this definition produces, in order.

### `PhaseValidity`

```python
PhaseValidity: object
```

### `register_size_definition`

```python
def register_size_definition(definition: SizeDefinition) -> SizeDefinition
```

Add a definition to the registry.  Re-registering a key is an error.

### `get_size_definition`

```python
def get_size_definition(key: str) -> SizeDefinition
```

Look a definition up by name, phase restrictions and all.

This is the accessor that *does* reach liquid-only definitions -- naming one
is an explicit act, which is the whole point.

### `available_size_definitions`

```python
def available_size_definitions() -> dict[str, SizeDefinition]
```

Every registered definition, keyed by name.

### `universal_size_definition`

```python
def universal_size_definition(key: str) -> SizeDefinition
```

Look up a definition for use on particles of unknown phase.

Raises `PhaseMismatchError` for anything that declared a phase.  A
generic pipeline stage -- one that does not know what it is looking at --
calls this, so a liquid-tuned definition cannot become the default path by
accident.

### `PhaseMismatchError`

```python
class PhaseMismatchError(ValueError)
```

Raised when a phase-restricted definition is asked to serve universally.

Not a MATLAB behaviour -- MATLAB has no such check.  This is the executable
form of the phase-neutrality directive, and it can only *refuse* a call; it
never changes a number.

## `arrayprobe.attributed_export`

The attributed second output -- a self-describing sibling of a faithful port product.

### `EXPORT_CONVENTION`

```python
EXPORT_CONVENTION: str
```

### `AttributedExportError`

```python
class AttributedExportError(RuntimeError)
```

Base class for every refusal this module raises.

### `MissingStampError`

```python
class MissingStampError(AttributedExportError)
```

The faithful file carries no ``.call`` sidecar, so its configuration is unknown.

Refused rather than exported with the provenance block left blank, for exactly the reason
``scripts/run_flight.py``'s `UnverifiableProvenance` refuses an unstamped input: a file
that *looks* attributed but states nothing about how it was made is worse than no file, because
a reader cannot tell the difference. ``accept_unstamped=True`` overrides, and then the export
says so in ``arrayprobe_call_stamp`` rather than staying silent about it.

### `StampParseError`

```python
class StampParseError(AttributedExportError, ValueError)
```

A ``.call`` line that does not parse as ``key=value`` pairs.

### `UnknownProductError`

```python
class UnknownProductError(AttributedExportError, ValueError)
```

A netCDF file whose variables match no `SHAPES` entry.

Refused rather than copied with guessed units. Adding a shape means sourcing each variable's
unit from the MATLAB that writes it, at ``file:line`` -- see `COMBINED_SIZEDIST`.

### `VariableAttributes`

```python
class VariableAttributes
```

One variable's attributes, and where each came from.

``units`` is a udunits-legal spelling of what the value *is*. ``source_units`` is the string
``sizeDist.m`` itself writes for the variable this one was copied from, kept verbatim where it
differs from ``units`` -- the string is the thing under suspicion (the same reason
``arrayprobe_enhancements.cf_export`` keeps ``arrayprobe_source_units``), and dropping it would
hide the discrepancy rather than record it. ``basis`` says how the unit was established:
*read* (quoted from a cited line) or *derived* (computed from cited lines, with the arithmetic
shown).

### `ProductShape`

```python
class ProductShape
```

One recognised faithful-product shape and its sourced attribute table.

### `COMBINED_SIZEDIST`

*(re-exported from elsewhere; not defined in this module)*

### `SHAPES`

*(re-exported from elsewhere; not defined in this module)*

### `identify_shape`

```python
def identify_shape(names: Iterable[str]) -> ProductShape
```

Which `SHAPES` entry a file's variable names are, or `UnknownProductError`.

### `parse_stamp`

```python
def parse_stamp(stamp: str) -> dict[str, str]
```

A ``.call`` line -> its **top-level** ``key=value`` pairs, in the order written.

Values may contain spaces (``area_ratio_z=0.5 (default)``), nested ``=`` signs
(``reject=(rej_hollow=0,...)``) and a whole nested stamp
(``inputs_built_with=(engine=3.1.4 profile=... default_int_arr_thresh=6e-06 (default))``), so
this is not a ``split()``: each key's value runs to the start of the next key **at paren depth
zero**. A duplicated key is refused rather than resolved by a last-wins rule --
``sd_call_label``'s own docstring (``src/arrayprobe/driver/run_flight.py:1667-1670``) records a
doubled ``engine=`` as a real defect class, and silently keeping one of two contradictory
values is how a stamp stops meaning anything.

**The nested stamp stays nested, and the outer level wins.** ``engine`` and ``profile`` appear
both at the top level and inside ``inputs_built_with``; they are different facts and must not
collide. The top-level keys describe *this* product; ``inputs_built_with`` is the provenance of
the files it was stitched from (``run_flight._combine_stamp``), so it is returned as one value
-- parenthesised, exactly as written; strip the outer ``()`` and call this function again if
you want the inputs' own fields (``parse_nested`` does that). Promoting the inner keys
would either overwrite the outer ones or trip the duplicate guard; both are wrong, and in an
earlier version that promotion is exactly what happened: ``inputs_built_with`` truncated to
``'(engine=3.1.4'``, ``iat_file``/``profile``/``tree`` were silently the *inputs'* values under
the product's own names, and the closing paren landed on the last value, where
`parse_tagged_value` finally raised and ``--attributed`` skipped every real product.

A value that itself contains a space-separated ``word=`` (a Windows path with a space in it,
say) would split wrongly here. That is why `global_attributes` writes the raw line
verbatim as well: the parsed keys are a convenience, the raw line is the record.

### `parse_reject`

```python
def parse_reject(value: str) -> dict[str, str]
```

``"(rej_hollow=0,max_edge_img_ar=4)"`` -> ``{"rej_hollow": "0", ...}``.

The fragment is built off the `~arrayprobe_uiops.reject_core.RejectConfig` dataclass's
fields
(``src/arrayprobe/driver/run_flight.py:1552-1554``, "read off the dataclass, so a field
added later enters the stamp without anyone remembering to add it"), so this parses whatever
is there rather than a fixed field list -- a field added upstream reaches the exported file
with no edit here.

### `parse_tagged_value`

```python
def parse_tagged_value(value: str) -> tuple[float, str]
```

``"0.5 (regime:liquid-warm)"`` -> ``(0.5, "regime:liquid-warm")``.

Both halves are returned because both are needed and neither implies the other: the number
without the tag cannot be told apart from a value someone typed, and the tag without the number
says nothing about what ran (``regimes.ResolvedField``'s own docstring: "three different
epistemic objects that must never be blurred").

### `default_output_path`

```python
def default_output_path(source: Path | str) -> Path
```

``<source><DEFAULT_SUFFIX>`` -- beside the faithful file, same stem, new suffix.

This is the current layout and may change in a later release
(``docs/developer/ATTRIBUTED_EXPORT.md`` §3). Co-location keeps the
correspondence obvious in a directory listing and makes the pair sort adjacently; the ``.nc``
ending says NETCDF4 where the faithful archived product says ``.cdf``; and nothing about the
faithful file's own name changes, which matters because every validated comparison addresses it
by name.

### `global_attributes`

```python
def global_attributes(stamp: str | None, *, source_path: Path | str, source_sha256: str, source_bytes: int, shape: ProductShape, files_stitched: int | None=None, enhancements: Sequence[str]=(), export_time: str | None=None, enhancements_record: str | None=None, tas_qc: dict | None=None, existing_attributes: Mapping[str, object] | None=None) -> dict[str, object]
```

Every global attribute the export writes, as a plain dict.

``existing_attributes`` are the faithful file's own global attributes. Each name in
`ACDD_KEYS` that it holds is carried over verbatim rather than replaced
(`acdd_attributes`).

Separated from `export` so the block can be asserted without writing a file, and so a
caller assembling a product by another route can write the identical block. The run-level
part is `shared_attributes`, placed here so the set and order of keys is unchanged; the
rest (source file and hash, product shape, fidelity note, time and missing-value
conventions, the exploded stamp) belongs to this file alone.

``stamp`` is the raw ``.call`` line. It is written **verbatim** as
``arrayprobe_call_stamp`` *and* exploded into one attribute per key: the verbatim line is the
record (nothing can be lost to a parsing edge case), the exploded keys are what a reader's
tooling can actually filter on. Any key this module does not recognise is still written, under
its own name -- so a stamp key added later reaches the file without an edit here.

### `shared_attributes`

```python
def shared_attributes(*, engine: str | None, engine_basis: str | None=None, sd_configuration: str | None=None, enhancements: Sequence[str]=(), enhancements_record: str | None=None, tas_qc: dict | None=None) -> dict[str, object]
```

The run-level block every product of one run carries, identical in each.

The attributed combined (`global_attributes`) and the faithful ARM copy of the port's
``sd`` (`stamp_shared_attributes`) each keep their own ``arrayprobe_call_stamp`` and
``arrayprobe_stage``; what they share is this: the engine, the ``sd``-level configuration
(``arrayprobe_inputs_built_with``, the ``sd`` stamp in parentheses -- a combined's stamp
carries it under that key, the ARM copy reads it from its ``sd``), the enhancements applied
and their record, the airspeed QC summary and the package version. ``engine=None`` (an
unstamped source) and ``sd_configuration=None`` leave those keys out rather than invent them.

### `stamp_shared_attributes`

```python
def stamp_shared_attributes(target: Path | str, sd: Path | str, combined: Path | str | None=None, *, enhancements: Sequence[str]=(), enhancements_record: str | None=None) -> dict[str, object]
```

Write `shared_attributes` into ``target``, a product made from the port's ``sd``.

``target`` is opened read-write and only global attributes are set. With ``combined`` (the
run's combined product, OUTPUT 2's source), the block is the combined's -- its ``.call`` and
its ``.tasqc.json``, including the merged-parts key the per-``sd`` record lacks -- so OUTPUT 3
carries exactly OUTPUT 2's run-level block. Without
it, the block is read from ``sd``. Either source is only read. ``enhancements`` and
``enhancements_record`` name the corrections the run applied (a stamp does not), so the
enhanced lineage's block is built whole rather than patched afterwards. Returns the block
written.

### `storage_options`

```python
def storage_options(dtype: np.dtype, sizes: Sequence[int], *, analysis_ready: bool=True) -> StorageOptions
```

``createVariable`` storage keywords for one variable: empty (contiguous, uncompressed) when
``analysis_ready`` is off, and for a variable that cannot be compressed losslessly here -- a
scalar, a zero-length dimension, or a non-numeric type. Storage only: no keyword returned here
changes a value, a dtype or a dimension order.

### `export`

```python
def export(source: Path | str, out: Path | str | None=None, *, stamp: str | None=None, accept_unstamped: bool=False, enhancements: Sequence[str]=(), export_time: str | None=None, enhancements_record: str | None=None, analysis_ready: bool=True) -> Path
```

Write the attributed sibling of the faithful product ``source``. Returns the path written.

``source`` is opened read-only and is never modified -- asserted by
``tests/test_attributed_export.py`` hashing it either side of this call. ``stamp`` defaults to
the ``.call`` sidecar beside it; absent, the export is refused unless ``accept_unstamped``.

``enhancements`` names what a non-port producer applied. Empty (the default) writes
``enhancements_applied = "none"``, which is the port's own case by construction.

``export_time`` pins the timestamp, for tests that compare two exports byte for byte -- the same
reason ``creation_time=`` exists on the faithful writers.

``analysis_ready`` (default on) writes each variable chunked and losslessly compressed
(`storage_options`), so the file is the cloud-optimised form as well as the attributed
one; ``False`` writes it contiguous and uncompressed. Either way every value is unchanged, and
the file states which under ``arrayprobe_encoding``.

### `main`

```python
def main(argv: Sequence[str] | None=None) -> int
```

``python -m arrayprobe.attributed_export FAITHFUL.cdf [OUT.nc] [--zarr] [--parquet]``.

## `arrayprobe.ai_ready`

A machine check that a file is "AI-ready" in exactly the sense this package claims.

*No public API declared (`__all__` empty or absent).*

## `arrayprobe.lwc`

Liquid water content from a particle size distribution.

### `lwc_calc`

*(re-exported from elsewhere; not defined in this module)*

## `arrayprobe.compare`

Diff-triage: align two UIOOPS output files, then compare them by tolerance class.

### `ToleranceClass`

```python
class ToleranceClass
```

One of the A-G comparison regimes, and whether a difference in it fails.

A class bundles two things that must travel together: *how* two values are
judged equal, and *what a difference means*. Splitting them is how a
comparison stops meaning anything -- a bit-equality assertion on an
accumulated float fails for reasons nobody can act on, and a loose
tolerance on an integer count throws away the strongest evidence in the
file.

``rule`` is prose because it is written for the person reading a report,
not consumed by code; the executable half lives in
`compare_variables`, which switches on ``key``. ``asserts`` is the
part that decides a verdict: a class with ``asserts=False`` is reported and
never blocks acceptance (see `ComparisonReport.accepted`).

Instances are the values of `CLASSES`; nothing else constructs one.

### `CLASSES`

*(re-exported from elsewhere; not defined in this module)*

### `PROC_CLASSES`

*(re-exported from elsewhere; not defined in this module)*

### `PROC_CLASSES_V35`

*(re-exported from elsewhere; not defined in this module)*

### `SD_CLASSES`

*(re-exported from elsewhere; not defined in this module)*

### `JOIN_KEY`

```python
JOIN_KEY: tuple
```

### `SD_JOIN_KEY`

```python
SD_JOIN_KEY: tuple
```

### `JoinResult`

```python
class JoinResult
```

Which rows of two files are the same thing, decided before any value is read.

Produced by `join_particles` (proc files, joined on the identity
tuple `JOIN_KEY`) or `join_seconds` (sd files, joined
positionally on the ``Time`` index). Everything in
`compare_variables` is indexed through ``left_index``/``right_index``,
so a bad join makes every subsequent verdict meaningless -- which is why
the join statistics are reported above the value table rather than below
it.

The unmatched rows are kept as index arrays, not counts, so
`unmatched_runs` can distinguish one abandoned record from a
systematic framing difference.

### `VariableVerdict`

```python
class VariableVerdict
```

The comparison outcome for one netCDF variable, in its tolerance class.

``verdict`` is the coarse answer and ``detail`` the class-appropriate
evidence behind it -- a drift slope for an accumulator, the worst absolute
difference for a closed-form float, a per-value breakdown for a
categorical. ``confusion`` is populated only for the categorical classes,
mapping ``(left_value, right_value)`` to how often that substitution
happened; for a reject-code or habit-code variable that table is the whole
diagnosis, where ``n_diff`` alone would say only that something moved.

Whether the verdict *counts against* the run is not stored here: it is
`failed`, which asks the variable's `ToleranceClass`.

### `ComparisonReport`

```python
class ComparisonReport
```

One whole file-against-file comparison: the alignment, then every variable.

Returned by `compare_proc_files`, `compare_sd_files` and
`compare_files`, and rendered for a human by `format_report`.
The ordering of the fields is the ordering of the report on purpose: a
reader must see how well the two files aligned, and any ``notes`` about
that alignment, before a single value verdict -- a 98 % join makes the
value table describe a different population on each side.

`accepted` is the gate; `failures` and `unclassified` are
the two ways it can be closed.

### `join_particles`

```python
def join_particles(ds_a, ds_b) -> JoinResult
```

Align two per-particle files on particle identity.

Returns index arrays into each side. Order is A's order, so a report can be
read against the left-hand file.

### `join_seconds`

```python
def join_seconds(ds_a, ds_b) -> tuple[JoinResult, list[str]]
```

Align two size-distribution files on their ``Time`` index.

A sd file has no particle identity left in it -- ``sizeDist`` reduces every
particle to a per-second row -- and, crucially, **the HHMMSS stamp in
``time`` does not identify a row.**  Measured on an archived 2D-S flight's TAS
sidecar: 4,110 rows carry 3,854 distinct stamps, because 256 rows are exact
duplicates of their predecessor down to the millisecond (``64923.4`` twice,
and so on).  ``sizeDist`` processes such a second twice and advances to the
*next* particle block on the repeat, so the duplication is real in the
output too.

So the join is **positional**: row *i* of one file is row *i* of the other,
because both were produced from the same TAS vector and ``Time`` is that
vector's index.  That is not a weaker join than a keyed one here -- it is the
only correct one -- and it is checked rather than assumed: ``time`` is itself
a compared variable in class A, so a positional misalignment shows up as a
``time`` mismatch before anything else is believed.

Returns the join and any notes worth printing above the table.

### `compare_variables`

```python
def compare_variables(ds_a, ds_b, join: JoinResult, classes: dict[str, str] | None=None) -> list[VariableVerdict]
```

Compare every variable of A against B over the joined particles.

### `compare_proc_files`

```python
def compare_proc_files(path_a, path_b, classes=None) -> ComparisonReport
```

Join and compare two imgProc per-particle files. Requires ``netCDF4``.

### `compare_sd_files`

```python
def compare_sd_files(path_a, path_b, classes=None) -> ComparisonReport
```

Join and compare two ``sizeDist`` size-distribution files.

### `compare_files`

```python
def compare_files(path_a, path_b, classes=None) -> ComparisonReport
```

Compare two UIOOPS files, choosing the join from what they are.

### `file_kind`

```python
def file_kind(path) -> str
```

``"proc"`` or ``"sd"``, from the dimensions rather than the filename.

A filename is not evidence -- the standing rule from the decode stage, and the reason this
reads the structure instead.  A proc file dimensions its particle axis
``time`` (lower case, one row per particle); a sd file dimensions its
one-second axis ``Time`` alongside ``CIPcorrlen``.

### `format_report`

```python
def format_report(report: ComparisonReport, verbose: bool=False, accepted: bool | None=None) -> str
```

Render a report.

``accepted`` overrides the verdict line. The CLI passes the decision it
computed over the WHOLE file, so that filtering the table with ``--var``
cannot turn a failing comparison into a green one.

## `arrayprobe.timing_closure`

The interarrival closure check -- McFarquhar et al. (2017) ch. 11 p. 11.20.

### `ClosureResult`

```python
class ClosureResult
```

The two independent measurements of one file's time span, and their disagreement.

Neither field is a verdict. ``ratio`` near 1.0 is closer agreement; how far from 1.0
is acceptable is not defined by the source this check implements, and is not defined
here either.

### `check_closure`

```python
def check_closure(decoded_path: str, proc_path: str, *, day_rollover_h: float=24.0) -> ClosureResult
```

Compare a proc file's particle-clock time span against its decoded file's own
record-clock time span (McFarquhar et al. 2017, p. 11.20).

``decoded_path`` is the decode stage's output (``.H.nc``/``.V.nc`` from engine 3.5)
the particles in
``proc_path`` were framed from -- the caller is responsible for pairing them
correctly; this function does not check that ``proc_path``'s ``parent_rec_num``
range is consistent with ``decoded_path``'s record count, though a caller who wants
that assurance can read both and compare.

``day_rollover_h`` corrects a single midnight crossing between the decoded file's
first and last record (added once if the raw difference is negative). Two valid
``hour``/``minute``/``second``/``millisec`` readings are always less than 24h
apart, so the default always suffices; the check that the correction actually
fixed the sign exists so a caller who overrides ``day_rollover_h`` to something
too small gets a clear error rather than a silently wrong, still-negative span.

## `arrayprobe.validate_by_condition`

Per-second agreement against an archived product, stratified by cloud condition.

### `BANDS`

```python
BANDS: tuple
```

### `BandResult`

```python
class BandResult
```

One condition band's totals. Ratios are left to the caller.

``all_*`` covers every bin; ``used_*`` drops the first ``drop_bins``, which
is what the project's headline figures quote -- the low bins are where the
probe's own response, not the port, dominates the disagreement.

### `Stratification`

```python
class Stratification
```

One comparison: the bands, the whole-window total, and how it was scoped.

Carries ``drop_bins`` and both second counts as well as the numbers,
because a band table read without them is ambiguous -- "used" means
nothing until you know how many bins the band drops, and a window's totals
read as a whole flight's unless the two second counts are visible side by
side.

### `find_product`

```python
def find_product(path: str, product_dir: str | None=DEFAULT_PRODUCTS) -> str | None
```

The archived product whose stem's date matches ``path``'s, if one exists.

Matched on the six-digit date in ``base<YYMMDD>``, not on the whole stem: a
product's stem is the flight's summary-file timestamp and ours is a raw
file's, so the two agree on the date and generally not on the time.
``product_dir`` falls back to `resolve_product_dir`.

### `stratify`

```python
def stratify(ours_path: str, ref_path: str, window: str | None=None, drop_bins: int=5) -> Stratification
```

Compare ``ours_path`` against ``ref_path`` second by second, by band.

``window`` is ``HHMMSS-HHMMSS``, inclusive-exclusive, so a partially
processed flight can be compared only where every contributing raw file is
present -- otherwise its missing hours land in the clear band and inflate
the agreement.

## `arrayprobe.validation_report`

Typed results for comparing a port output against a reference product.

*No public API declared (`__all__` empty or absent).*

## `arrayprobe.diode_report`

Per-diode occupancy for one flight, and SPEC's own noisy-diode test.

### `DiodeReport`

```python
class DiodeReport
```

One flight's per-diode occupancy, and what it implies.

### `NOT_BUILT`

*(re-exported from elsewhere; not defined in this module)*

### `SPEC_NOISY_DIODE`

```python
SPEC_NOISY_DIODE: SpecNoisyDiodeCriterion
```

### `SpecNoisyDiodeCriterion`

```python
class SpecNoisyDiodeCriterion
```

The manufacturer's detector, with each number's provenance attached.

### `accumulate_occupancy`

```python
def accumulate_occupancy(shadows) -> DiodeReport
```

Count shadowed slices and images per diode over an iterable of silhouettes.

Each element is the boolean ``(n_slices, n_diodes)`` array
`arrayprobe.render.reconstruct_particle_image` returns. An iterable
rather than an array because a flight's particles do not fit in memory at
once and a report must not require that they do.

A particle with no slices contributes nothing rather than raising: a proc
file's own ``position`` bounds should prevent it, and a report is the wrong
place to discover otherwise.

### `flag_noisy_diodes`

```python
def flag_noisy_diodes(report: DiodeReport, criterion: SpecNoisyDiodeCriterion=SPEC_NOISY_DIODE)
```

Diodes whose image count exceeds the manufacturer's threshold.

Returns ``(flagged_indices_0based, threshold, mean_count)``.

The threshold is computed from the mean over **all** diodes, which is the
whole-flight form of the manual's rolling window: with fewer images than
``criterion.window_images`` there is only one window, and with more, a
whole-flight mean is the conservative reading -- a diode noisy for part of
the flight is diluted, so this under-reports rather than over-reports.
A rolling implementation needs the per-image arrival order, which this
accumulation deliberately does not keep; say so rather than implying the
manual's exact procedure has been reproduced.

### `report_from_files`

```python
def report_from_files(image_path, proc_path, *, limit: int | None=None, stride: int=1) -> DiodeReport
```

Build a report straight from a decoded ``.cdf`` and its ``proc`` file.

``stride`` samples every n-th particle and ``limit`` caps the count: a dense
flight holds tens of millions of images, and a uniformity report converges
long before all of them. Both are recorded by the caller, not here -- a
sampled report is still a report, but the sampling is part of the number.

## `arrayprobe.count_closure`

Count closure: do a size-distribution product's binned counts sum to the particles S3 holds?

*No public API declared (`__all__` empty or absent).*

## `arrayprobe.reproduce_report`

Reproduction report: compare a product against an archived product, cell by cell.

*No public API declared (`__all__` empty or absent).*
