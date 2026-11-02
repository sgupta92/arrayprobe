# API reference: the CLI and visualisation tool
> Generated from `src/arrayprobe`'s own AST; never hand-typed. Regenerate with `docs/_build/apidoc.py`.

Shared tooling, readers and the command line. An earlier translation of UIOOPS v3.1.4 reproduced archived products and is not part of this package; its engine modules are not shipped.

**See also** [CLI reference](13-cli-reference.md) · [Reference](08-reference.md).

## `arrayprobe.cli`

``arrayprobe`` -- the command-line front door.

### `build_parser`

```python
def build_parser() -> argparse.ArgumentParser
```

The whole command surface: one subcommand per pipeline stage.

Separate from `main` so the argument surface can be inspected and
tested without running anything -- the fidelity-sensitive defaults are the
part worth pinning, and the tests assert what is *required* rather than what
a run produces.

**Every fidelity-sensitive argument is required, never defaulted**, and that
is the CLI's one real design decision. A default profile, tree or
``d_choice`` would let someone process a campaign under a configuration
nobody chose, and a wrong reject threshold applied that way changes every
concentration without a warning. Convenience defaults belong in a
config file the user writes, not in the front door.

### `main`

```python
def main(argv=None) -> int
```

Entry point for the ``arrayprobe`` console script (see ``pyproject.toml``).

Returns a process exit status rather than raising, so a shell pipeline can
branch on it; each subcommand's own handler returns 0 for success. ``argv``
is accepted explicitly so tests drive the real parser instead of patching
``sys.argv``.

## `arrayprobe.__main__`

``python -m arrayprobe`` -- the same front door as the ``arrayprobe`` console script.

*No public API declared (`__all__` empty or absent).*

## `arrayprobe.triage_server`

Mass particle visualization and triage GUI -- browse, inspect, and label

### `TriageServer`

```python
class TriageServer(BaseHTTPRequestHandler)
```

The whole HTTP surface: routing, rendering and verdict storage in one handler.

**Read this before adding a route.** Two properties are load-bearing and both
came from real failures rather than from design taste:

* **Every flight name is validated against discovered flights before it
  reaches a path** -- see `_valid_flight`. Names arrive from URL
  segments and POST bodies, and ``Path``'s ``/`` neither sanitises ``..``
  nor refuses an absolute right-hand side.
* **Rendering and netCDF reads are serialised**, because ``matplotlib.pyplot``
  and ``netCDF4``/HDF5 are both thread-unsafe. That is two separate crashes
  under real use, each diagnosed with a concurrent-load stress test rather
  than argued.

Class attributes rather than instance state because
``BaseHTTPRequestHandler`` constructs a new handler per request; `run`
sets them once before the server starts.

### `run`

```python
def run(decoded_dir: Path, port: int=8765, queue_file: Path | None=None, reviewer: str | None=None, accept_unstamped: bool=False, met_dir: Path | None=None, state_file: Path | None=None, state_var: str | None=None, run_root: Path | None=None)
```

Start the server on localhost and block until interrupted.

``run_root`` is the folder whose ``_runs/`` the Run page lists at ``/runs``. Left ``None``,
the first run launched from ``/run`` sets it to the output folder typed on the form.

``accept_unstamped`` indexes products whose provenance is unrecorded. Default False: they
are refused and named on the index page instead (`_discover_flights`). The banner
below says which way this server is running, because "my flight is missing" and "my flight
was refused" need different answers and the terminal is where the user looks first.

``reviewer`` is recorded with every label this server writes. It is
validated here, before the socket is bound, so a malformed id fails at
startup rather than on the first save in the middle of a pass. Left
``None``, the server starts but refuses every label save with HTTP 400 --
stated in the banner, never filled in from the OS username.

Binds ``127.0.0.1`` explicitly, never ``0.0.0.0``: this is a local review
tool with no authentication, and it reads whatever is under
``decoded_dir``. The banner it prints names the URL, that directory, and
which optional pieces are present, so a session's context is visible in the
terminal rather than assumed.

### `main`

```python
def main(argv=None) -> int
```

``python -m arrayprobe.triage_server`` -- parse options and start the server.

Not a console script in ``pyproject.toml``, deliberately: it is a review
tool that needs a decoded directory to point at, and the module form keeps
that explicit rather than making it look like a command that works anywhere.

## `arrayprobe.triage_context`

What the triage pages show beside a particle that its product does not state outright.

### `REJECT_OUTCOMES`

*(re-exported from elsewhere; not defined in this module)*

### `LATER_SCREENS_NOTE`

```python
LATER_SCREENS_NOTE: str
```

### `reject_outcome`

```python
def reject_outcome(code) -> tuple[str, str] | None
```

``(kind, words)`` for an automatic reject code; ``kind`` is ``"kept"``,
``"corrected"`` or ``"rejected"``. ``None`` when there is no code to describe.

### `shape_test_habit`

```python
def shape_test_habit(c, diode_mm: float) -> str
```

Holroyd's habit letter from the shape test alone, on the boolean silhouette ``c``
(``(n_slices, n_diodes)``, the whole record width as ``imgProc_sm`` passes it).

Uses the v3.5 port's ``holroyd`` (``holroyd.m:7-89`` of v3.5), whose decision tree has
no stub, so it answers the shape question for files of either engine.

### `particle_parts`

```python
def particle_parts(c, gap: int=PIECE_GAP_DIODES, scale: str='constant') -> list[dict]
```

The separate pieces of shadow in ``c``, numbered 1, 2, … in order along the flight.

A piece is a group of 8-connected components whose nearest pixels are at most ``gap``
empty diodes apart (`piece_groups`; ``gap=0`` is plain 8-connectivity), so one
fragmented crystal is one piece. Order is by first slice, then first diode, so piece 1 is
the one the probe met first. Each entry: ``n``, ``pixels``, ``row``/``col`` (centroid, in
pixels), ``rows``/``cols`` (inclusive first and last). Display only. ``scale`` is passed
to `piece_groups` (``"larger"``: size-scaled gap, ``gap`` the cap).

### `piece_groups`

```python
def piece_groups(c, gap: int=0, scale: str='constant') -> list[np.ndarray]
```

The 8-connected pieces of ``c`` grouped single-linkage when the gap between their
nearest pixels is at most ``gap`` diodes; one boolean mask per group.

The gap is the Chebyshev distance between the nearest pixels less one, i.e. the number of
empty pixels between them, so ``gap=0`` is plain 8-connectivity. Exact: dilating every
pixel by a ``(gap+1)``-square makes two pixels 8-adjacent iff their Chebyshev distance
is at most ``gap + 1``, so the dilation's components are the single-linkage groups.

``scale="larger"`` (opt-in) makes the allowed gap size-scaled: two 8-connected
components join when their gap is at most ``min(gap, extent of the larger of the two)``,
extent being ``max(bbox height, bbox width)`` in pixels, single linkage; ``gap`` is then
the cap. Measured on 441 hand labels of 2018-02-15 with cap 12 it agrees with 393
against 388 for the best constant gap. The default, ``"constant"``, is unchanged.

### `PIECE_GAP_DIODES`

```python
PIECE_GAP_DIODES: int
```

### `MetFolder`

```python
class MetFolder
```

ARM AAF merged files in one folder, read once each, for the temperature at a second.

``temperature_at(yyyymmdd, hhmmss)`` returns ``(degC, file name)`` for the row at that
second, or ``None`` when no file of that date holds a valid value there. A value is
invalid when masked, not finite, or at or below -9990 (the files' missing-value
convention). The time axis is checked,
not assumed: ``time``'s units must be "seconds since <the file's date> 00:00:00".

### `PIECE_COUNT_CLASSES`

```python
PIECE_COUNT_CLASSES: tuple
```

### `PIECE_COUNT_WORDS`

```python
PIECE_COUNT_WORDS: dict
```

### `count_class`

```python
def count_class(n: int) -> str | None
```

A piece count as its `PIECE_COUNT_CLASSES` entry; ``None`` for no pieces.

### `piece_count_class`

```python
def piece_count_class(c, gap: int=PIECE_GAP_DIODES, scale: str='larger') -> str | None
```

How many particles ``c`` shows under the particle-count schema: ``"one"``, ``"two"`` or
``"three_or_more"`` (``None`` for an empty image).

Pieces are `piece_groups` with the size-scaled gap by default (``scale="larger"``:
two components join when the empty diodes between them are at most
``min(gap, extent of the larger)``), so specks much smaller than ``gap`` stay separate.
The gap is counted in diodes, so the rule reads the same at every probe resolution; its
physical width is ``gap`` times the diode size. Display only.

## `arrayprobe.run_page`

The triage server's Run page: the pure core (form -> TOML -> argv).

### `ENGINES`

```python
ENGINES: tuple
```

### `PROTECTIVE_MODES`

```python
PROTECTIVE_MODES: tuple
```

### `preset_choices`

```python
def preset_choices() -> tuple[str, ...]
```

``run_flight.PRESETS`` keys, through the CLI's one loader of the driver.

### `profile_choices`

```python
def profile_choices() -> tuple[str, ...]
```

Every profile name a config file may select (``config.PROFILES``).

### `probe_choices_v35`

```python
def probe_choices_v35() -> tuple[str, ...]
```

``arrayprobe_uiops.imgproc.PROBES_V35`` keys -- the UIOOPS ``[run].probe`` names.

### `probe_choices_soda2`

```python
def probe_choices_soda2() -> tuple[str, ...]
```

SODA-2's probe table: ``arrayprobe_soda2.probespecs.PROBE_NAMES``
(``soda2_probespecs.pro``'s ``probename`` column).

### `build_toml`

```python
def build_toml(form: Mapping[str, Any]) -> str
```

The configuration file a validated form describes. Pure; raw and out are written
resolved and absolute, so the file reads the same wherever it is saved.

### `build_argv`

```python
def build_argv(form: Mapping[str, Any], toml_path: Path | str, *, dry_run: bool) -> list[str]
```

The documented entry point's argv for a validated form. Always a list, program
``sys.executable``; run-shape flags (``--jobs`` and friends) ride on the argv, not the file,
exactly as ``arrayprobe run`` treats them.

SODA-2 has no ``--dry-run``; its preflight is ``arrayprobe soda2 enhancements <config>``,
which loads and checks the file (and its enhancement table) and runs nothing.

### `validate_form`

```python
def validate_form(form: Mapping[str, Any], *, presets: Iterable[str] | None=None, profiles: Iterable[str] | None=None, probes_v35: Iterable[str] | None=None, soda2_probes: Iterable[str] | None=None) -> list[str]
```

Every whitelist and shape problem with ``form``, empty when the form may be written.
The tables default to the discovered ones; tests inject their own.

### `raw_list`

```python
def raw_list(value: Any) -> list[str]
```

The form's raw field -- a list, or one path per line -- as a list of non-blank strings.

### `dry_run`

```python
def dry_run(argv: list[str], cwd: Path | str, *, timeout: float=120, launcher: Any=None) -> tuple[int, str]
```

Run the driver's preflight (``argv`` from ``build_argv(..., dry_run=True)``) in the
foreground and return ``(returncode, combined output)`` verbatim. A timeout is reported as
returncode -1 with what was captured. ``launcher`` defaults to ``subprocess.run``.

### `launch_detached`

```python
def launch_detached(argv: list[str], log_path: Path | str, cwd: Path | str, *, run_id: str, popen: Any=None) -> int
```

Start ``argv`` so it outlives the server: its own
session (Windows: a new process group, detached from the console), stdin from the null
device, stdout and stderr straight to ``log_path`` (never a pipe: it can hang), and
a wrapper that writes ``=== <run_id> exited <code> <date> ===`` as the log's last line.
Returns the wrapper's PID; the wrapper lives exactly as long as the run.
``popen`` defaults to ``subprocess.Popen``.

### `new_run_id`

```python
def new_run_id(name: str, now: Any=None) -> str
```

``<YYYYMMDD-HHMMSS>-<name>``; ``name`` must satisfy the form's whitelist.

### `start_run`

```python
def start_run(form: Mapping[str, Any], *, cwd: Path | str | None=None, popen: Any=None, now: Any=None) -> dict[str, Any]
```

Write the form's TOML into a new run folder, launch it detached and record it. The form
must already have passed ``validate_form``; the run name is checked again here because it
becomes a path.

### `write_record`

```python
def write_record(out: Path | str, record: Mapping[str, Any]) -> Path
```

Write ``record`` as ``<out>/_runs/<run_id>/run.json``; returns the path.

### `read_record`

```python
def read_record(out: Path | str, run_id: str) -> dict[str, Any] | None
```

The record for ``run_id``, or None. ``run_id`` reaches a path only after it matched an
entry ``list_runs`` found on disk (the ``_valid_flight`` doctrine).

### `list_runs`

```python
def list_runs(out: Path | str) -> list[str]
```

Run ids recorded under ``out``, newest first: folders whose name has the run-id shape
and which hold a ``run.json``.

### `run_status`

```python
def run_status(record: Mapping[str, Any], *, tail_lines: int=40, alive: Any=None) -> dict[str, Any]
```

What the page shows for one run: state, exit code (from the wrapper's exit line), the
log's tail, verdict lines (OK / FAILED / Traceback / refused), the ``.call`` stamps written
under ``out`` since the start, and the newest output file's mtime -- a chunked or ``--jobs``
run is silent in its log for long stretches, so that mtime is the heartbeat.
``alive`` defaults to a process-table check of ``record['pid']``.

## `arrayprobe.diagnostic_views`

Two diagnostic views: the record strip and the one-second comparison.

### `BOUNDARY_WORD`

```python
BOUNDARY_WORD: int
```

### `SLICES_PER_RECORD`

```python
SLICES_PER_RECORD: int
```

### `StripParticle`

```python
class StripParticle
```

One proc row, placed in its record. Slices are 1-based and inclusive, as ``position`` is.

### `RecordStrip`

```python
class RecordStrip
```

``n`` consecutive image records with their particles in place.

``shadow`` is ``(n_records, 1700, n_diodes)``, ``True`` where a diode was shadowed -- the
same convention as `arrayprobe.render.reconstruct_particle_image`. ``boundary`` is
``(n_records, 1700)``, ``True`` on a slice whose every word is the boundary word.

### `record_strip`

```python
def record_strip(image_ds, proc_ds, first_record: int, n_records: int=6, *, colour_by: str='reject', boundary_word: int=BOUNDARY_WORD) -> RecordStrip
```

Records ``first_record`` .. ``first_record + n_records - 1`` (1-based) with their particles.

``image_ds``/``proc_ds`` are open ``netCDF4.Dataset`` handles on one flight's decoded image
file and its proc file. The last record shown is clipped to the file's own length, and a
``first_record`` outside the file raises, naming the file's range -- a strip of nothing would
look like an empty buffer, which is a different finding.

### `strip_index_image`

```python
def strip_index_image(strip: RecordStrip) -> tuple[np.ndarray, list[tuple[int, int, int]]]
```

The strip as a palette-index image and its palette -- what `record_strip_png` encodes.

Layout: for each record, a band of ``_SEPARATOR_ROWS`` rows (the tick row: red at the first
slice of every fifth particle, counted across the whole strip from 1) then one row per diode;
one column per slice. Pixel roles: background, boundary slice, shadow inside no particle
window, and one colour per category (``strip.categories``, accepted always black).

### `record_strip_png`

```python
def record_strip_png(strip: RecordStrip) -> bytes
```

The strip as PNG bytes. Deterministic: the same strip always gives the same bytes.

### `record_strip_html`

```python
def record_strip_html(strip: RecordStrip, *, title: str='', link_particle=None) -> str
```

An HTML fragment: the PNG inline, a legend with counts, and the particle table.

``link_particle`` (``index -> href``) makes each particle row a link; the triage server passes
its own particle page, a file written by the CLI passes nothing.

### `SecondComparison`

```python
class SecondComparison
```

One second of two size-distribution files, bin by bin.

``ours``/``theirs`` are the named variable's per-bin values at that second, read from each
file unscaled. ``differing`` marks the bins where they are not equal within ``rtol`` (exact
by default; NaN equals NaN). ``particles`` are the proc rows of that second whose
``diameter_var`` falls in a differing bin, ``[bin_min, bin_max)`` -- a guide to where to look,
not the binning itself: ``count`` additionally requires the particle's codes, centre-in flag
and time window to pass,
which is why each listed particle carries its reject code and centre-in flag.

### `compare_second`

```python
def compare_second(ours_sd, theirs_sd, second: int, *, variable: str='count', proc=None, diameter_var: str='image_diam_minR', rtol: float=0.0) -> SecondComparison
```

Compare one second (``HHMMSS``) of two ``sd`` files; list the particles behind the cells.

``ours_sd``/``theirs_sd`` and ``proc`` are paths. ``proc``, when given, is the per-particle
file behind ``ours_sd``; without it no particles are listed. The two files must share a bin
ladder, or the comparison raises rather than setting two different bins side by side.
``diameter_var`` is stated in every rendering because the ``sd`` file does not record which
size definition its run chose -- the ``.call`` sidecar does.

### `second_comparison_html`

```python
def second_comparison_html(cmp: SecondComparison, *, ours_label: str='ours', theirs_label: str='theirs') -> str
```

An HTML fragment: every bin where either file is non-zero, differing rows marked.

### `per_second_counts`

```python
def per_second_counts(hhmmss) -> tuple[np.ndarray, np.ndarray]
```

Particles per second from a proc file's ``Time`` (``HHMMSS``): ``(seconds, counts)``.

``seconds`` are seconds of day, floored; non-finite times are dropped. The counts sum to the
number of finite particle times -- the triage server's rate panel draws exactly this.

### `HOLLOW_ACCEPTED_CODES`

```python
HOLLOW_ACCEPTED_CODES: str
```

### `HOLLOW_VERDICT_MIN_FRACTION`

```python
HOLLOW_VERDICT_MIN_FRACTION: float
```

### `HollowShare`

```python
class HollowShare
```

Per-bin hollow census of one v3.5 proc file. Every array has one entry per bin.

``moved_out[b]``: accepted 'H' particles whose undivided size is in bin ``b`` and whose
written (divided) size is not -- the correction takes them out of ``b``.
``moved_in[b]``: accepted 'H' particles whose written size is in ``b`` and whose undivided
size is not -- the correction brings them into ``b``.
So ``accepted = accepted_undivided - moved_out + moved_in`` in every bin.

### `hollow_share`

```python
def hollow_share(proc_path, bin_edges_um, *, min_fraction: float=HOLLOW_VERDICT_MIN_FRACTION) -> HollowShare
```

Per-bin hollow census of one v3.5 proc file (see `HollowShare`).

``bin_edges_um`` are ascending edges in micrometres; a bin is ``[lo, hi)``, sizeDist's
``bin_index`` rule. Accepted means ``image_auto_reject`` in `HOLLOW_ACCEPTED_CODES`
with ``image_center_in == 1``. The written size is ``image_diam_minR`` (mm) and the undivided
size of an 'H' particle is ``image_diam_minR * size_factor``, the rebin
``compare_ena_threeway.py --uiops-h-undivided`` uses. sizeDist's own reject stage (area
ratio, interarrival) is not applied, so the counts are the proc file's accepted particles,
not the product's ``Counts``. Reads the file; writes nothing.

### `hollow_share_text`

```python
def hollow_share_text(share: HollowShare) -> str
```

The census as a plain-text table, one row per bin, ending with the verdict.

## `arrayprobe.review_sampling`

Stratified review samples that state their own coverage.

### `COVERAGE_KEY`

```python
COVERAGE_KEY: str
```

### `SIZE_EDGES`

```python
SIZE_EDGES: tuple
```

### `STRATIFIERS`

```python
STRATIFIERS: dict
```

### `Sample`

```python
class Sample
```

A stratified draw over one flight's ``proc`` file.

``by`` names strata from `STRATIFIERS`; the sample is the cross-product
of their values, ``n_per_stratum`` particles from each, drawn with a seeded
RNG so the same arguments give the same queue on any machine.

### `Stratum`

```python
class Stratum
```

One cell of the cross-product, and what it actually yielded.

``available`` is what the flight holds; ``taken`` is what the sample got.
They differ whenever a stratum is thinner than ``n_per_stratum``, and that
difference is the coverage statement's most useful line.

### `full_axis`

```python
def full_axis(name: str) -> list[str] | None
```

Every label a stratifier can take, or ``None`` when that is unknowable.

This is the difference between a coverage statement that can say *"this
flight has no particle above 1 mm"* and one that can only say what it
happened to see. ``size_bin`` has a closed vocabulary -- the edges are right
here -- so its axis is complete and an unrepresented bin appears with a
count of zero.

``reject_code`` and ``habit`` do not: their vocabularies live in
``calculate_reject_unified.m`` and ``holroyd.m``, and a code that no
version emits would be a permanently empty row in every coverage statement
ever written. For those the axis is what the flight shows, and
`Sample.coverage` says which kind each stratifier was.

### `stratum_labels`

```python
def stratum_labels(name: str, values: np.ndarray) -> np.ndarray
```

Turn one ``proc`` variable into per-particle stratum labels.

Kept separate from `Sample` so the labelling can be tested on arrays
without a netCDF file anywhere near it.

## `arrayprobe.review_agreement`

Label agreement for the triage server -- Track V phase 2, item 3.

*No public API declared (`__all__` empty or absent).*

## `arrayprobe.tools`

Tooling that ships *inside* the installed package.

*No public API declared (`__all__` empty or absent).*

## `arrayprobe.tools.make_demo_flight`

Build a synthetic raw ``.2DS`` file with no campaign data required.

*No public API declared (`__all__` empty or absent).*

## `arrayprobe.tools.make_tas_file`

Write the aircraft TAS file stock ``imgProc_sm.m`` reads as ``varargin{1}``.

### `write_tas_file`

```python
def write_tas_file(path, time_hhmmss, tas_mps, *, provenance: dict | None=None) -> Path
```

Write ``path`` as NETCDF3_CLASSIC with ``Time`` (HHMMSS) and ``TAS`` (m/s), f8.

NETCDF3_CLASSIC for the same reason every other file this package writes is
(MATLAB's bare ``'clobber'`` default). Both arrays must be 1-D and the
same length -- ``imgProc_sm`` indexes them together, so a mismatch here would be a
silently misaligned time base rather than an error at read time.

### `check_tas_series`

```python
def check_tas_series(time_hhmmss, tas_mps) -> tuple[np.ndarray, np.ndarray]
```

Refuse a ``(Time, TAS)`` series that ``imgProc_sm.m:727``'s exact-match lookup cannot use.

The one check every aircraft series passes before the engine sees it -- the file this
tool writes, and an aircraft file ``run_flight.py`` is handed
directly, such as ARM's merged file. Returns the two arrays as 1-D float64.

### `tas_from_csv`

```python
def tas_from_csv(csv_path) -> tuple[np.ndarray, np.ndarray]
```

``(Time, TAS)`` from a ``<stem>.tas.csv`` the decode wrote.

Delegates to `arrayprobe.readers.tasinfo.load_tas_info` -- the port of
``loadTASinfo_2DS.m`` -- rather than parsing the CSV again here, so the two columns
this tool copies are the two columns the MATLAB lineage reads.

### `constant_tas`

```python
def constant_tas(start_hhmmss: float, seconds: int, tas_mps: float) -> tuple[np.ndarray, np.ndarray]
```

A flat 1-Hz series. ``Time`` steps by 1 in HHMMSS, which is only valid inside one
minute -- so the tool refuses a span that would run past :59 rather than writing a
time axis that jumps backwards at the minute boundary.

### `whole_second_series`

```python
def whole_second_series(time_hhmmss, tas, *, second_rule: str=AUTHOR_SECOND_RULE, neighbour: str=AUTHOR_NEIGHBOUR_RULE, policy: TasPolicy | None=None, unsettled: str=AUTHOR_UNSETTLED_RULE)
```

Reduce a sub-second ``(Time, TAS)`` series to one sample per whole second.

``second_rule`` (``"round"`` = ``floor(sod + 0.5)``, ``"floor"`` = ``floor(sod)``) and
``neighbour`` (``"adjacent"`` = s-1 / s+1 only, ``"nearest-present"`` = the nearest
second present on each side) default to round and adjacent.

Rows out of range under ``policy`` (above its cutoff, at/below 0 m/s, non-finite) are set
aside before grouping, one ``class="out-of-range"`` record per second: ``remaining`` says
whether in-range rows keep that second; if not, the second **takes ``policy.default_mps``**
(``fallback``). A duplicated second the rule cannot settle (``class="ambiguous"``) takes the
default too under ``unsettled="default"``; under ``"refuse"`` it is left out of the series and
the caller must refuse to write. Nothing is dropped under the default.

Returns ``(time, tas, report)``. One record (a dict) per second with more than one sample or
an out-of-range row: ``second`` (HHMMSS int), ``class`` (``identical`` / ``unambiguous`` /
``ambiguous`` / ``out-of-range``), ``candidates`` (every TAS, row order), ``prev`` / ``next``
(the neighbour's TAS; ``None`` when absent, substituted, or itself holding several distinct
values), ``prev_missing`` / ``next_missing``, ``kept`` (``None`` when ambiguous),
``fallback`` (the default value the second took, else ``None``), ``reasons``.

### `reduce_probe_csv`

```python
def reduce_probe_csv(csv_path, *, policy: TasPolicy | None=None, second_rule: str=AUTHOR_SECOND_RULE, neighbour: str=AUTHOR_NEIGHBOUR_RULE, unsettled: str=AUTHOR_UNSETTLED_RULE) -> ProbeReduction
```

The probe path end to end: ``<stem>.tas.csv`` -> whole seconds under the TAS rules,
one log line per decision. Shared by ``make-tas-file --from-tas-csv`` and the run driver's
TAS source chain (`arrayprobe.tools.tas_sources`), so the two cannot disagree.

### `TasPolicy`

```python
class TasPolicy
```

The TAS policy pair: a cutoff above which a TAS is not believed, and the value a second
falls to when its TAS is out of range or unsettled. Both configurable (``[tas]`` in a run
configuration, ``--cutoff-mps``/``--default-mps`` on the command line).

### `DEFAULT_CUTOFF_MPS`

```python
DEFAULT_CUTOFF_MPS: float
```

### `DEFAULT_FALLBACK_MPS`

```python
DEFAULT_FALLBACK_MPS: float
```

### `SECOND_RULES`

```python
SECOND_RULES: tuple
```

### `NEIGHBOUR_RULES`

```python
NEIGHBOUR_RULES: tuple
```

### `UNSETTLED_RULES`

```python
UNSETTLED_RULES: tuple
```

### `TAS_DUPLICATE_RULE`

```python
TAS_DUPLICATE_RULE: str
```

### `build_parser`

```python
def build_parser() -> argparse.ArgumentParser
```

The tool's parser -- also the list ``arrayprobe make-tas-file`` must mirror
(``tests/test_make_tas_file.py`` compares the two option sets).

### `main`

```python
def main(argv=None) -> int
```

``arrayprobe make-tas-file`` -- write the aircraft TAS file the pipeline requires.

Measured sources (``--from-tas-csv``, ``--from-merge``, ``--from-aircraft``, ``--chain``)
are converted under the TAS rules and a `TasPolicy`; ``--constant-tas``
fabricates a series and says so in the file's own provenance (``constant <v> m/s (NOT a
measurement)``). It refuses to guess a flight's clock or duration. Returns an exit code.

## `arrayprobe.tools.probe_comparison`

Put two probes' sizeDist-layout products on a common size grid and time axis.

*No public API declared (`__all__` empty or absent).*

## `arrayprobe.tools.synthetic_truth`

Known-truth synthetic 2D-S flights: raw ``.2DS`` bytes plus a manifest of every particle.

### `KOROLEV_2007_APPENDIX_B`

*(re-exported from elsewhere; not defined in this module)*

### `KOROLEV_2007_ZDMAX_50`

*(re-exported from elsewhere; not defined in this module)*

### `korolev_dimensions`

```python
def korolev_dimensions(zd: float) -> tuple[float, float] | None
```

``(D_edge/D0, D_spot/D_edge)`` at ``zd`` -- the nearest Appendix B row; ``None`` beyond
``Z_dmax`` (no image). Never interpolated (see the module docstring).

### `OpticalModel`

```python
class OpticalModel
```

How a droplet becomes a binary image on a 2D-S-like array. Defaults: the 2D-S.

### `render_droplet`

```python
def render_droplet(d0_um: float, zd: float, x_um: float, y_phase: float, model: OpticalModel) -> tuple[np.ndarray, bool] | None
```

The binary image of one droplet, ``(rows=slices, cols=num_diodes)`` bool, and whether it
touches an array end; ``None`` if nothing on the array is shadowed.

``x_um`` is the centre across the array, measured from the outer edge of diode 1 (so the
array spans ``[0, num_diodes * pixel_um)``); ``y_phase`` in ``[0, 1)`` places the centre
within a slice. Diodes outside the array are simply absent -- that is the edge clipping.

### `image_runs`

```python
def image_runs(img: np.ndarray) -> list[int]
```

Run-length words for a binary image, one slice per row, in the encoding
the earlier translation's SPEC decoder reads (``read_binary_SPEC.m:223-241``): a
slice's first word carries the absolute clear count, later words the clear gap from the
previous run's end (the same rule `arrayprobe.tools.make_demo_flight.ring_runs`
documents). An empty interior slice is ``run_word(0, 0)``, which the decoder writes as
nothing; a run longer than 127 diodes is split, since a run field is seven bits.

### `PSD`

```python
class PSD
```

The true droplet size distribution the flight draws from.

``kind="lognormal"``: ``median_um`` and geometric standard deviation ``gsd``, truncated to
``[d_min_um, d_max_um]``. ``kind="discrete"``: ``diameters_um`` drawn uniformly (e.g. one
diameter per bin centre, for a flat-in-count test).

### `FlightSpec`

```python
class FlightSpec
```

Everything that determines a synthetic flight. Same spec + same seed = same bytes.

### `TruthManifest`

```python
class TruthManifest
```

The truth: the spec, the optical model, and one entry per drawn particle (columnar).

### `build_truth_flight`

```python
def build_truth_flight(path, flight: FlightSpec | None=None, model: OpticalModel | None=None) -> TruthManifest
```

Write the raw ``.2DS`` file at ``path`` and its manifest at ``path + MANIFEST_SUFFIX``.

``path``'s stem should follow SPEC's ``base<YYMMDDhhmmss>`` convention if the combine stage
is to run on it (see `arrayprobe.tools.make_demo_flight`). Returns the manifest.

### `MANIFEST_SUFFIX`

```python
MANIFEST_SUFFIX: str
```

### `write_aircraft_tas`

```python
def write_aircraft_tas(path, flight: FlightSpec) -> Path
```

The aircraft file a TAS-reading ``imgProc_sm`` takes as ``varargin{1}``
(``imgProc_sm.m:183-185``; the v3.1.4 image processing reads ``Time`` as HHMMSS and
``TAS`` in m/s): one
sample per second of the flight, at the flight's constant TAS.

## `arrayprobe.tools.tas_sources`

Where a run's true airspeed comes from: an ordered, recorded chain.

### `AircraftSource`

```python
class AircraftSource
```

One registered aircraft TAS source, read off a real file before being added.

### `SOURCES`

```python
SOURCES: tuple
```

### `TIERS`

```python
TIERS: tuple
```

### `MODES`

```python
MODES: tuple
```

### `UNIT_FACTORS`

```python
UNIT_FACTORS: dict
```

### `AircraftSeries`

```python
class AircraftSeries
```

An aircraft file read and converted: HHMMSS whole seconds, TAS in m/s (not yet
policy-checked).

### `read_aircraft`

```python
def read_aircraft(path, source: AircraftSource | None=None) -> AircraftSeries
```

Read ``path`` as ``source`` (identified by its variables when not given), convert its
time axis to UTC HHMMSS and its TAS to m/s by the units attribute. Read through
``ncio.ncread`` -- the call the engine makes -- so masking and scaling apply the same way.

### `substitute`

```python
def substitute(time_hhmmss, tas, policy: TasPolicy)
```

Every out-of-range TAS -> ``policy.default_mps``. Returns ``(tas, subs)``, ``subs`` one
``(HHMMSS, original, reason)`` per substituted sample. Nothing is dropped.

### `ChainResult`

```python
class ChainResult
```

What the chain decided for one flight file. ``tier``/``source`` name what was used;
``steps`` is every tier tried, in order, as ``(tier, source, outcome, detail)`` with outcome
``used`` / ``skipped`` / ``failed``.

### `resolve_chain`

```python
def resolve_chain(mode: str, *, yyyymmdd: str | None, search_dirs=(), probe_csv=None, policy: TasPolicy | None=None, second_rule: str=_mtf.AUTHOR_SECOND_RULE, neighbour: str=_mtf.AUTHOR_NEIGHBOUR_RULE, explicit: dict | None=None) -> ChainResult
```

Walk the chain (``mode="auto"``) or pin one tier, and return what was used and why.

``yyyymmdd`` names the flight's date (a raw stem ``base170812080701`` is ``20170812``) and
fills each registered source's file-name pattern in ``search_dirs``; ``explicit`` maps a tier
to a file named outright (``make-tas-file --from-merge``/``--from-aircraft``), which is then
that tier's only candidate. ``probe_csv`` is the decode's ``<stem>.tas.csv``: the ``probe``
tier's input, and for the other tiers the clock they must share at least one second with.

Raises ``ValueError`` -- listing every step -- when no tier is usable, or when a pinned tier
is absent or fails: a pinned source never falls through silently.

### `write_chain_file`

```python
def write_chain_file(path, result: ChainResult) -> Path
```

The aircraft file for the framing stage, in UIOOPS's ``TAS``/``Time`` convention, carrying
the whole decision record in its global attributes.

### `series_for_sizedist`

```python
def series_for_sizedist(probe_time_hhmmss, aircraft_time, aircraft_tas, policy: TasPolicy)
```

The TAS array the size-distribution stage (``sizeDist``) gets when a run picks aircraft TAS.

**The time axis stays the probe's own** (the ``<stem>.tas.csv`` times, floored exactly as
the probe path floors them), because ``sizeDist``'s output time base *is* its TAS series'
time axis (the earlier translation's ``sizeDist`` port, at its output time base): swapping the
axis too would move or remove seconds of the
product. Only the values are replaced -- by the aircraft TAS at the same whole second, and
by ``policy.default_mps`` where the aircraft series has none (never dropped).
Returns ``(time, tas, missing_seconds)``.

### `regular_grid_hhmmss`

```python
def regular_grid_hhmmss(probe_time_hhmmss) -> np.ndarray
```

A one-second HHMMSS grid from the probe axis's first second to its last, every second once.

The probe's own ``<stem>.tas.csv`` axis repeats a second when two housekeeping packets
fall in it and skips one when none does. ``sizeDist``'s block walk
(v3.5 ``sizeDist.m:913-927``; v3.1.4 ``:745-754``) files no particle of a skipped second
and none of a repeated one -- measured
under Octave on the unmodified v3.5 source.
This grid has
neither. Midnight is unwrapped before the span is taken and wrapped back after, so a
grid crossing it reads ``235959, 0, 1`` as the probe's own does. Returned as float64,
the dtype the probe axis has.

### `regular_series_for_sizedist`

```python
def regular_series_for_sizedist(probe_time_hhmmss, aircraft_time, aircraft_tas, policy: TasPolicy)
```

`series_for_sizedist` on `regular_grid_hhmmss`'s grid instead of the probe's
own axis: the same aircraft-value lookup and the same policy default for a second the
aircraft series lacks, over a time vector with every second of the probe's span once.

The opt-in behind ``run_flight.py --tas-grid regular``. It is how UIOOPS's own worked example
calls ``sizeDist`` with aircraft airspeed
(``UIOPS-v3.5/joefinlon-UIOPS-039be82/minimal_working_example/run_sizeDist_Munich.m:25-26``
and ``:40`` hand it the flight file's ``Time`` and ``TAS`` together), with the span kept to the
probe's so the product covers the seconds it covered before. Returns
``(time, tas, missing_seconds)``.

### `write_soda2_pth_csv`

```python
def write_soda2_pth_csv(path, time_hhmmss, tas_mps) -> Path
```

The same series as a SODA-2 ``op.pth`` ASCII file (``soda2_process_2d.pro:147-162``,
ported as ``arrayprobe_soda2.pth_readers.read_pth_ascii``): one ``<seconds of day>,<tas>``
line per sample, since SODA-2's ``op.starttime`` is seconds from midnight. SODA-2 fills each
accepted row forward and accepts ``0 < tas < 500`` (``:156``), so a series that has been
through `TasPolicy` passes whole when the cutoff is below 500 m/s.

## `arrayprobe.driver`

The flight driver: ``run_flight`` (the per-flight batch driver), ``reprocess``,

*No public API declared (`__all__` empty or absent).*

## `arrayprobe.driver.run_flight`

Take raw ``.2DS`` files through S2 -> S3 -> S4, one flight at a time.

*No public API declared (`__all__` empty or absent).*

## `arrayprobe.driver.reprocess`

``arrayprobe reprocess <product> --preset NAME`` -- re-run a product's stage from its own stamp.

*No public API declared (`__all__` empty or absent).*

## `arrayprobe.driver._load_record`

What else the machine was doing while a timing ran.

*No public API declared (`__all__` empty or absent).*

## `arrayprobe.driver.preflight_inputs`

Open every input a long run needs, before the long run starts.

*No public API declared (`__all__` empty or absent).*

## `arrayprobe.driver.tas_from_probe_housekeeping`

Build one aircraft TAS sidecar from another probe's housekeeping on the same aircraft.

*No public API declared (`__all__` empty or absent).*
