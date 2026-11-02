# API reference: I/O and MATLAB compatibility
> Generated from `src/arrayprobe`'s own AST; never hand-typed. Regenerate with `docs/_build/apidoc.py`.

Shared tooling, readers and the command line. An earlier translation of UIOOPS v3.1.4 reproduced archived products and is not part of this package; its engine modules are not shipped.

**See also** [CLI reference](13-cli-reference.md) · [Reference](08-reference.md).

## `arrayprobe.__init__`

arrayprobe -- a Python port of UIOOPS. Porting v3.1.4 line by line surfaced a

### `__version__`

```python
__version__: str
```

### `read_binary_SPEC`

*(re-exported from elsewhere; not defined in this module)*

### `read_binary_hvps`

*(re-exported from elsewhere; not defined in this module)*

### `read_binary_DMT`

*(re-exported from elsewhere; not defined in this module)*

### `read_binary_PMS`

*(re-exported from elsewhere; not defined in this module)*

### `read_binary_SEA`

*(re-exported from elsewhere; not defined in this module)*

### `load_tas_info`

*(re-exported from elsewhere; not defined in this module)*

### `imgproc_sm`

*(re-exported from elsewhere; not defined in this module)*

### `size_dist`

*(re-exported from elsewhere; not defined in this module)*

### `combine_sizedist`

*(re-exported from elsewhere; not defined in this module)*

### `FidelityProfile`

*(re-exported from elsewhere; not defined in this module)*

### `STOCK_V314`

*(re-exported from elsewhere; not defined in this module)*

### `ORACLES_2016`

*(re-exported from elsewhere; not defined in this module)*

### `ORACLES_PRODUCTION`

*(re-exported from elsewhere; not defined in this module)*

### `PROFILES`

*(re-exported from elsewhere; not defined in this module)*

### `profile`

*(re-exported from elsewhere; not defined in this module)*

### `register_profile`

*(re-exported from elsewhere; not defined in this module)*

### `RunConfig`

*(re-exported from elsewhere; not defined in this module)*

### `ConfigError`

*(re-exported from elsewhere; not defined in this module)*

### `load_config`

*(re-exported from elsewhere; not defined in this module)*

### `compare_files`

*(re-exported from elsewhere; not defined in this module)*

### `format_report`

*(re-exported from elsewhere; not defined in this module)*

### `ComparisonReport`

*(re-exported from elsewhere; not defined in this module)*

### `compare_to_product`

*(re-exported from elsewhere; not defined in this module)*

### `ProductComparisonReport`

*(re-exported from elsewhere; not defined in this module)*

### `CellAgreement`

*(re-exported from elsewhere; not defined in this module)*

### `check_closure`

*(re-exported from elsewhere; not defined in this module)*

### `ClosureResult`

*(re-exported from elsewhere; not defined in this module)*

### `engine`

*(re-exported from elsewhere; not defined in this module)*

### `Engine`

*(re-exported from elsewhere; not defined in this module)*

### `ENGINES`

*(re-exported from elsewhere; not defined in this module)*

### `DEFAULT_ENGINE`

*(re-exported from elsewhere; not defined in this module)*

### `UnknownEngine`

*(re-exported from elsewhere; not defined in this module)*

### `open_product`

*(re-exported from elsewhere; not defined in this module)*

## `arrayprobe.config`

A run configuration file (TOML) -- selection only, never a silent default.

### `RunConfig`

```python
class RunConfig
```

A validated run configuration -- everything a TOML file is allowed to select.

Frozen, and every fidelity-relevant field is filled by `load_config`
from an explicit key: there is no constructor path that infers a profile or
supplies a threshold. That is the rule that a config file may select a named variant but
never set a threshold, expressed in the type -- a config file selects between
documented MATLAB behaviours, it never invents one, so a caller reading this object can
trust that anything affecting a computed number was named in the file.

``enhancements`` is a bag of booleans the core deliberately does not
interpret; it is read only through `enabled`, by the separately
installed ``arrayprobe-uiops-enhancements`` layer. ``source`` is the path the
config was read from, carried so a provenance stamp can name it.

### `ConfigError`

```python
class ConfigError(ValueError)
```

A config that would pick a side silently, or names something the port cannot honour.

Raised by `load_config` once for the whole file: its first line is the first problem
and the file's path, any further problems follow numbered, and ``.problems`` lists them all.

### `PROFILES`

*(re-exported from elsewhere; not defined in this module)*

### `load_config`

```python
def load_config(path) -> RunConfig
```

Read a run-configuration TOML file into a validated `RunConfig`.

Not a MATLAB behaviour: UIOOPS has no config file, it has driver scripts
with the constants written in. This loader exists so a run can be
*described* without editing code, and it is bounded so that description
can never become a fidelity decision.

Every rejection below is a case where accepting the file would let it pick
a side silently:

* an unknown top-level section (a typo'd ``[fidelty]`` would otherwise be
  ignored and the run would use different settings than the file says);
* any key in `_FORBIDDEN` anywhere -- ``rej_hollow``,
  ``max_edge_img_ar`` and the rest are chosen by naming a profile, never by
  a raw value, because their correct values are a measured property of a
  MATLAB tree;
* a missing ``[fidelity].profile``, since no profile is ever assumed -- except under
  ``[run].engine = "soda2"``, which reads no profile and may not name one
  (`_load_soda2_config`, by design);
* ``[shattering]`` present without ``threshold_file``, because an absent
  twelfth ``sizeDist`` argument is itself an output-changing call
  (``sizeDist.m:70``, ``:866``) and must be stated rather than defaulted;
* a diode number outside 1..128, or a non-boolean enhancement switch.

Returns a `RunConfig`. Raises `ConfigError` for all of the
above; ``FileNotFoundError`` and ``tomllib.TOMLDecodeError`` propagate.
Every problem in the file is reported at once in that one error, which names the file and
lists them on ``.problems``; a file that cannot be read as TOML at all fails at once.

## `arrayprobe.profiles`

Which MATLAB variant a run is reproducing.

### `FidelityProfile`

*(re-exported from elsewhere; not defined in this module)*

### `STOCK_V314`

```python
STOCK_V314: FidelityProfile
```

### `ORACLES_2016`

```python
ORACLES_2016: FidelityProfile
```

### `ORACLES_PRODUCTION`

```python
ORACLES_PRODUCTION: FidelityProfile
```

### `STOCK_V35`

*(re-exported from elsewhere; not defined in this module)*

### `ORACLES_PRODUCTION_V35`

*(re-exported from elsewhere; not defined in this module)*

### `PROFILES`

*(re-exported from elsewhere; not defined in this module)*

### `SHIPPED`

*(re-exported from elsewhere; not defined in this module)*

### `profile`

*(re-exported from elsewhere; not defined in this module)*

### `register_profile`

*(re-exported from elsewhere; not defined in this module)*

### `is_v35_flavoured`

*(re-exported from elsewhere; not defined in this module)*

### `register_stock_v35_image_assisted`

*(re-exported from elsewhere; not defined in this module)*

## `arrayprobe.regimes`

Named, evidence-based size-distribution (``sizeDist``) thresholds -- cloud-regime defaults.

### `Regime`

```python
class Regime
```

One named, evidence-based bundle of size-distribution-stage threshold defaults.

Both fields are cited individually -- ``area_ratio_z`` and ``default_int_arr_thresh`` are
independent MATLAB literals (the campaign-configured ``sizeDist.m:849`` and ``:269``) with
no shared history, so a regime that could justify one and not the other is expected, not an
oversight.

### `ResolvedField`

```python
class ResolvedField
```

One resolved threshold value, tagged with WHERE it came from and why.

``source`` is one of ``"regime:<name>"``, ``"user:<path>"`` or ``"default"`` (the built-in
fallback nobody chose -- see `resolve_thresholds`'s no-argument case) -- three
different epistemic objects that must never be blurred: a value someone typed into a TOML is
not the same claim as a named regime's cited default.

``"default"`` is the built-in fallback nobody chose, and its meaning depends on the tree: for
the production tree it is ``ORACLES_REJECT`` (area_ratio_z 0.5, the 2017 production edit,
``sizedist_core.py``); for the stock tree it is ``STOCK_REJECT`` (0.2, unmodified UIOOPS). It
does NOT mean "unmodified UIOOPS uses this value". Stamps written before 2026-10-16 spell it
``"stock"``; every reader accepts both (`LEGACY_DEFAULT_SOURCE`).

### `ResolvedThresholds`

```python
class ResolvedThresholds
```

The two size-distribution threshold fields in force for one run, each with its provenance.

Returned by `resolve_thresholds` and consumed by ``scripts/run_flight.py`` in three
places that must never disagree: the startup print, the confirmation panel and the
``.call`` stamp. The two fields are kept separate rather than collapsed into one "source"
because a run may mix origins -- a regime for one and a raw override for the other -- and
reporting both as whichever was set last is exactly the blurring this module exists to prevent.

### `LIQUID_WARM`

```python
LIQUID_WARM: Regime
```

### `ICE`

```python
ICE: Regime
```

### `MIXED`

```python
MIXED: Regime
```

### `REGIMES`

*(re-exported from elsewhere; not defined in this module)*

### `register_regime`

```python
def register_regime(new: Regime) -> Regime
```

Register a fork's own `Regime`, the same way
`arrayprobe.profiles.register_profile` registers a fork's
`~arrayprobe.profiles.FidelityProfile`.

Registering constructs the object in Python, where every field's justification is named; a
config file may only *select* the name afterwards, never describe the numbers.

### `ThresholdValidationError`

```python
class ThresholdValidationError(ValueError)
```

A user-supplied raw threshold value that fails a physically-grounded bound.

Bounds are asserted only where the repository holds a reason to assert one (area ratio is
bounded to (0, 1] by its own definition -- image area divided by an enclosing shape's area);
where no such reason exists (``default_int_arr_thresh``'s upper end -- no evidence here bounds
a plausible inter-arrival threshold), nothing is asserted, and that is stated rather than an
invented limit being enforced silently.

### `resolve_thresholds`

```python
def resolve_thresholds(regime_name: str | None=None, area_ratio_z_override: float | None=None, default_int_arr_thresh_override: float | None=None, override_source: str='user', *, area_ratio_z_source: str | None=None, default_int_arr_thresh_source: str | None=None, projectname: str='ORACLES', probename: str='2DS', tree: str='production') -> ResolvedThresholds
```

Resolve the two size-distribution threshold fields, tagging where each value came from.

**No arguments** (the default): reproduces exactly what ``run_flight.py`` has always
hard-coded for every project, named rather than silently applied --
``arrayprobe_uiops.sizedist_core.ORACLES_REJECT.area_ratio_z`` (0.5) and the production
``otherwise/2DS``
row's ``default_int_arr_thresh`` (6e-6, ``constants.py:674-680``). This is the production-tuned
pair an unrecognised project was found silently inheriting -- kept as the literal
no-argument default so nothing about an already-validated run changes, but tagged
``"default"`` (meaning: the historical hard-coded fallback, not a regime anyone chose) rather
than arriving with no name at all.

``regime_name``: one of `REGIMES`. Supplies both fields unless overridden below.

``*_override``: a raw value from a config file or the command line -- the rule that a
config file may only select, never set a threshold, is lifted for exactly these two fields
Validated before being accepted:
``area_ratio_z`` must fall in (0, 1] (an area ratio's own definition bounds it there); no bound
is asserted on ``default_int_arr_thresh`` beyond being a positive, finite number of seconds,
because no evidence this repository holds justifies an upper limit -- said here rather than an
invented one being silently enforced.

``override_source`` names where an override came from (typically a config file path or
``"cli"``), embedded in the returned field's ``source`` as ``"user:<override_source>"``.
``area_ratio_z_source``/``default_int_arr_thresh_source`` (keyword-only) override it per
field -- needed because a run may mix sources (one field from ``--area-ratio-z``, the other
from ``[thresholds]``), which the coordinating driver must tag distinctly rather than
reporting both as coming from wherever the last one was set.

``projectname``/``probename``/``tree`` (keyword-only) matter only for the no-regime,
no-override "default" fallback: ``default_int_arr_thresh`` is looked up from
``constants.sizedist_config(projectname, probename, tree)`` exactly as ``sizedist.run`` itself
would, so the fallback stays probe-correct rather than a single literal borrowed from the 2D-S
case (HVPS and CIP take a different value in the same ``otherwise`` row --
constants.py:663-688). Default to ``"ORACLES"``/``"2DS"``/``"production"``, which
reproduces exactly the call every validated flight has used to date.

### `Inherit`

```python
class Inherit
```

The explicit "this regime does not set this reject field" marker, with its reason.

A regime slot holding an `Inherit` takes the run's profile value for that field
(`resolve_reject`). The reason is required: an inherited slot is a decision like any
other and says
why it was made.

### `INHERIT`

```python
INHERIT: Inherit
```

The sentinel the three shipped regimes carry on all six reject slots, so every ``--regime``

### `REJECT_FIELDS`

*(re-exported from elsewhere; not defined in this module)*

### `UncitedRegimeField`

```python
class UncitedRegimeField(ValueError)
```

A `Regime` reject slot set to a value with no citation, or of the wrong type.

The shape of ``arrayprobe_uiops.probe_cases.UncitedProbeCaseField``: refused at construction,
so a regime that types a threshold without naming the vendored ``file:line`` or measurement
record it came from never exists (the never-invent-a-threshold rule).

### `resolve_reject`

```python
def resolve_reject(regime: Regime | None, profile_reject: RejectConfig) -> RejectConfig
```

The `~arrayprobe_uiops.reject_core.RejectConfig` a run uses: the regime's cited
values over the profile's.

Each of the six slots the regime marks `Inherit` takes ``profile_reject``'s value; each
it sets replaces it. ``regime=None`` returns ``profile_reject`` itself, unchanged. With the
three shipped regimes (all six INHERIT) the result equals ``profile_reject`` field for field,
so a ``--regime`` run keeps its profile's reject set (``tests/test_regimes_reject_slots.py``).
Precedence above the regime (a ``user:`` override) is the driver's, not this function's.

### `regime_reject_values`

```python
def regime_reject_values(regime: Regime) -> dict[str, bool | float]
```

The reject slots the regime sets, ``{field: value}``; the Inherit slots are left out.

### `regime_reject_sources`

```python
def regime_reject_sources(regime: Regime | None) -> dict[str, str]
```

``{field: "regime:<name>"}`` for each reject slot the regime sets; empty when it sets none.

Lists only the fields the regime supplied, so a stamp built from it stays absent when unused
(design record section 3's ``reject_sources=`` key).

## `arrayprobe.products`

Open a product file as an `xarray.Dataset`, read exactly as written.

*No public API declared (`__all__` empty or absent).*

## `arrayprobe.authordefaults`

The author-editable defaults file -- minimal form.

### `THRESHOLD_KEYS`

*(re-exported from elsewhere; not defined in this module)*

### `AuthorDefaultsError`

```python
class AuthorDefaultsError(ValueError)
```

An ``authordefaults*.toml`` file that cannot be trusted as written.

### `AuthorDefaults`

```python
class AuthorDefaults
```

One validated ``authordefaults*.toml`` file: a base profile plus cited overrides.

### `content_hash`

```python
def content_hash(data: bytes) -> str
```

The filename's hash segment: the first 16 hex chars of the file's own SHA-256.

### `expected_filename`

```python
def expected_filename(data: bytes) -> str
```

What this file's name must be, given its bytes.

### `load_authordefaults`

```python
def load_authordefaults(path) -> AuthorDefaults
```

Read and validate an author-editable defaults file.

Raises `AuthorDefaultsError` for anything that would let the file describe a
threshold without a citation, name a key that is not one of the six, or run under a
name that does not match its own content.

### `resolve_profile`

```python
def resolve_profile(defaults: AuthorDefaults) -> FidelityProfile
```

Build (and register, once per interpreter) the profile this file selects.

The name is derived from the file's own content hash (``authordefaults-<hash>``), so a
config loaded twice in one process -- or by a ``--jobs``/``--chunks`` worker that has
never seen this file before -- resolves to the same registration rather than raising on
the second call: idempotent by construction, the same property
``[fidelity].profile_module`` relies on for a fork's own registered variant.

## `arrayprobe.tune`

Tune loop: what a user can change, and whether a change reaches the output.

*No public API declared (`__all__` empty or absent).*

## `arrayprobe.tune.settings`

Every setting a user can change for the v3.5 engine, and whether it reaches the output.

### `Cite`

```python
class Cite
```

``path:line`` (repository-relative, 1-based) and a substring that line contains.

### `Effect`

```python
class Effect
```

Whether a setting changes the output on one probe case, and why.

### `Setting`

```python
class Setting
```

One row of `SETTINGS`.

### `SETTINGS`

*(re-exported from elsewhere; not defined in this module)*

### `settings_by_name`

```python
def settings_by_name() -> dict[str, Setting]
```

`SETTINGS` keyed by row name.

### `resolve_probe_defaults`

```python
def resolve_probe_defaults(probe_case: Any) -> Any
```

The ``ProbeDefaults`` record behind ``probe_case`` (see `Setting.effect`).

## `arrayprobe.tune.sample`

Review queues drawn from one proc file: particles inside time windows, per size bin.

*No public API declared (`__all__` empty or absent).*

## `arrayprobe.tune.distributions`

Per-particle distributions inside time windows of one proc file, active thresholds marked.

### `SIZE_EDGES_MM`

*(re-exported from elsewhere; not defined in this module)*

### `IA_EDGES_S`

```python
IA_EDGES_S: logspace
```

### `PERCENTILES`

```python
PERCENTILES: tuple
```

### `PER_SECOND_LIMIT`

```python
PER_SECOND_LIMIT: int
```

### `NONFINITE_LABEL`

```python
NONFINITE_LABEL: str
```

### `BELOW_FLOOR_LABEL`

```python
BELOW_FLOOR_LABEL: str
```

### `COLUMNS`

```python
COLUMNS: tuple
```

### `threshold_marks`

```python
def threshold_marks(probe_case: Any=None, area_ratio_z: float | None=None) -> dict
```

The thresholds that act on the reported quantities, each with where its value came from.

``area_ratio_z`` is a run's ``--area-ratio-z``; ``None`` takes v3.5's stock cut.  The
shattering mark comes from ``probe_case`` through
`arrayprobe.tune.settings.resolve_probe_defaults`; ``None`` marks none.

### `size_bins`

```python
def size_bins(diam_mm, edges: Sequence[float]=SIZE_EDGES_MM) -> tuple[np.ndarray, list[str]]
```

Bin index per particle and the labels; the last two bins are below-floor and non-finite.

``np.digitize`` alone would put NaN and inf in the top bin; here they get their own.

### `reject_code_counts`

```python
def reject_code_counts(codes) -> dict[str, dict]
```

``{code: {"n", "meaning"}}``, the meaning from `REJECT_CODE_WORDS`.

### `habit_code_counts`

```python
def habit_code_counts(codes) -> dict[str, int]
```

``{habit code: n}``.

### `per_second_counts`

```python
def per_second_counts(sod, windows: Sequence[tuple[int, int]]) -> np.ndarray
```

Particles in each distinct window second, in order (a second in two windows counts once).

### `area_ratio`

```python
def area_ratio(image_area, diam_mm) -> np.ndarray
```

``image_area / (pi/4 * d^2)``, clipped at 1 by v3.5's own ``clip_area_ratio``.

### `report`

```python
def report(cols: dict[str, np.ndarray], *, windows: Sequence[tuple[int, int]], marks: dict, edges: Sequence[float]=SIZE_EDGES_MM, proc_name: str='') -> dict
```

The distributions for the particles of ``cols`` (the `COLUMNS`) inside ``windows``.

### `read_proc_columns`

```python
def read_proc_columns(path: Path) -> dict[str, np.ndarray]
```

The `COLUMNS` of a proc file, flattened, raw (no masking or scaling).

### `summary_lines`

```python
def summary_lines(rep: dict) -> list[str]
```

A few lines for the terminal: counts, the marks and, per size bin, the cut fractions.

## `arrayprobe.tune.score`

Score a reviewer's labels against what the run decided, per reject code and size bin.

*No public API declared (`__all__` empty or absent).*

## `arrayprobe.tune.diodes`

Stuck diodes in one proc file: ``bin_stats`` as lit counts, run through the fork's rule.

### `RULE_SOURCE`

```python
RULE_SOURCE: dict
```

### `DiodeReportError`

```python
class DiodeReportError(ValueError)
```

A proc file whose ``bin_stats`` convention or slice total cannot be established.

### `counting_convention`

```python
def counting_convention(path: Path | str, profile: str | None=None) -> dict[str, Any]
```

Which slices ``path``'s ``bin_stats`` counts, and how that was established.

Returns ``{"engine", "engine_source", "profile", "shadowed", "convention_source"}``.
``profile`` names the v3.1.4 profile when the stamp names none; when the stamp names one,
a different ``profile`` is refused.

### `slice_offset`

```python
def slice_offset(n_diodes: int, probe: str | None=None) -> tuple[int, str]
```

The probe's ``image_slice_offset`` and where it came from.

With ``probe`` given, its `~arrayprobe_uiops.imgproc.PROBES_V35` entry.  Without, the
offset shared by every probe of ``n_diodes`` diodes; refused when those probes differ.

### `lit_counts`

```python
def lit_counts(bin_stats, *, shadowed: bool, position=None, offset: int=0, total: int | None=None) -> tuple[np.ndarray, int | None]
```

``bin_stats`` as lit counts, and ``S`` (``None`` when the counts were already lit).

``S`` comes from ``position`` (an ``(n, 2)`` start/end array) or, already summed, ``total``.

### `position_slice_total`

```python
def position_slice_total(path: Path | str, offset: int, *, block_rows: int=POSITION_BLOCK_ROWS, jobs: int | None=None) -> int | None
```

``S = sum(end - start + 1 - offset)`` over ``path``'s ``position``, ``None`` if absent.

Read in contiguous blocks of ``block_rows`` rows and summed in int64, so the result equals
the whole-array sum exactly.  A proc file written before the v3.5 writer chunked
``position`` in ``[1024, 2]`` blocks stores it one particle per HDF5 chunk, and reading
it costs ~20 us a row (measured on a 17.8 M-particle file), so
``jobs`` worker processes each read a share of the rows; ``None`` picks
``min(cpu_count, 8)`` above `PARALLEL_MIN_ROWS` rows and one process below.

### `report`

```python
def report(path: Path | str, *, profile: str | None=None, probe: str | None=None, jobs: int | None=None) -> dict[str, Any]
```

The stuck-diode report for one proc file (see the module docstring).

### `report_from_counts`

```python
def report_from_counts(lit) -> dict[str, Any]
```

The rule's verdict on lit counts, per diode and overall.

### `toml_line`

```python
def toml_line(stem: str, flagged) -> str
```

The run-file entry declaring ``flagged`` for raw stem ``stem``: a ``[masking.diodes]``
table row, which ``arrayprobe.config`` loads into ``RunConfig.diode_masks`` and a run
applies under ``--diode-corrected``.

### `summary_lines`

```python
def summary_lines(rep: dict[str, Any]) -> list[str]
```

A short printed form of `report`'s output.

## `arrayprobe.selector`

The project-level engine selector -- ``arrayprobe.engine()``.

### `DEFAULT_ENGINE`

*(re-exported from elsewhere; not defined in this module)*

### `ENGINES`

*(re-exported from elsewhere; not defined in this module)*

### `Engine`

```python
class Engine
```

A chosen engine, and what a reader needs to know about it.

### `UnknownEngine`

```python
class UnknownEngine(ValueError)
```

Raised for a name that is not one of this project's engines.

### `engine`

```python
def engine(name: str | None=None) -> Engine
```

The engine called ``name``, or the default if none is named.

Accepts the engine's version (``"3.5"``), its lineage
(``"soda2"``), or a small set of obvious spellings. Anything else raises
`UnknownEngine` naming what is available -- a selector that falls
through to a default would silently run the wrong lineage.

## `arrayprobe._v314_lazy`

Lazy access to the v3.1.4 validation engine, which the public distribution omits.

### `ABSENT_MESSAGE`

*(re-exported from elsewhere; not defined in this module)*

### `V314EngineAbsent`

*(re-exported from elsewhere; not defined in this module)*

### `engine_present`

*(re-exported from elsewhere; not defined in this module)*

### `lazy_module`

```python
def lazy_module(name: str, message: str=ABSENT_MESSAGE) -> _Lazy
```

A stand-in for module ``name`` that imports it on first use, or raises V314EngineAbsent
carrying ``message``.

## `arrayprobe.ncio`

Alias of `arrayprobe_uiops.ncio`, the MATLAB ``netcdf.*`` layer both engines write through.

*No public API declared (`__all__` empty or absent).*

## `arrayprobe.matio`

Reading the MATLAB ``.mat`` sidecars the UIOOPS processing chain leaves behind.

### `UnsupportedMatFeature`

```python
class UnsupportedMatFeature(MatFileError)
```

A Level 5 MAT-file feature this reader deliberately does not handle.

### `MatFileError`

```python
class MatFileError(ValueError)
```

The file is not a readable Level 5 MAT-file.

### `MatFile`

```python
class MatFile
```

A loaded MAT-file: its variables plus the header MATLAB stamped on it.

### `loadmat`

```python
def loadmat(path) -> MatFile
```

Read a Level 5 (v5/v6/v7) MAT-file.

Returns a `MatFile`.  Numeric arrays come back in MATLAB's shape and
presented class; char arrays come back as `str` when they are a
single row (which is every char variable UIOOPS writes) and as an array of
rows otherwise.

### `savemat`

```python
def savemat(path, variables: dict, *, header_text: str | None=None) -> Path
```

Write a Level 5 MAT-file, uncompressed (MATLAB's ``-v6`` container).

The write side of the one requirement this module has: ``find_shadow_diodes.m``'s
``save([path ...])`` (``:103-107``), which saves the whole workspace --
``a``, ``date``, ``orientation``, ``path``, ``shadow_diode``, ``time``.
Variables are written in the order given; MATLAB's bare ``save`` writes
them in ``who`` order, which is alphabetical, and the caller passes them so.

Supports exactly what that file holds: double and int32 arrays (1-D taken
as a column, the shape ``find`` and ``ncread`` return) and single-row char.
MATLAB's default ``save`` is ``-v7`` (zlib-compressed); the container is
not a computed number, `loadmat` and MATLAB's ``load`` read both, and
the 116-byte header text carries a creation time in any case, so no
``.mat`` file is byte-reproducible across two ``save`` calls.

## `arrayprobe.provenance`

Alias of `arrayprobe_uiops.provenance`, the one ``.call`` sidecar parser.

*No public API declared (`__all__` empty or absent).*
