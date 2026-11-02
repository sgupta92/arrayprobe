# API reference: the v3.5 port -- pipeline, reader and reject
> Generated from `src/arrayprobe_uiops`'s own AST; never hand-typed. Regenerate with `docs/_build/apidoc.py`.

The **v3.5 port** -- complete, and the default for new work. Validated at layer 2 only: every routine on the **stock v3.5 path** is asserted against GNU Octave running v3.5's own sources, because no archived campaign product was ever produced by v3.5 and none can be. The ellipse fit included: `iRectEllipse=1` is goldened against the real `CGAL_EllipseSize` binary, compiled under Octave. The opt-in, default-off additions this package carries beyond any tagged UIOOPS release are each proven bit-identical to stock when off and validated against its own named oracle instead of the Octave goldens above; see `TWO_ENGINES.md` §1. One such addition, the mass dispatch in `mass_b26.py`, is not in this release.

**See also** [CLI reference](13-cli-reference.md) · [Reference](08-reference.md).

## `arrayprobe_uiops.imgproc`

v3.5 ``imgProc_sm.m`` -- the driver and writer around the measurement block.

### `PROBES_V35`

*(re-exported from elsewhere; not defined in this module)*

### `NCAR_2DC_TIMING_STAMP_ON`

*(re-exported from elsewhere; not defined in this module)*

### `NCAR_2DC_TIMING_STAMP_OFF`

*(re-exported from elsewhere; not defined in this module)*

### `STRAY_PIXEL_STAMP_ON`

*(re-exported from elsewhere; not defined in this module)*

### `STRAY_PIXEL_STAMP_OFF`

*(re-exported from elsewhere; not defined in this module)*

### `PARTICLE_NUM_MODULUS_V35`

```python
PARTICLE_NUM_MODULUS_V35: int
```

### `WRITER_GAPS`

```python
WRITER_GAPS: tuple
```

### `WRITER_CHUNKING`

*(re-exported from elsewhere; not defined in this module)*

### `POSITION_CHUNK_PARTICLES`

```python
POSITION_CHUNK_PARTICLES: int
```

### `WIDTH_MISMATCH_RETURNS`

*(re-exported from elsewhere; not defined in this module)*

### `CORRUPT_RECORDS`

*(re-exported from elsewhere; not defined in this module)*

### `SHARED_WITH_V314`

```python
SHARED_WITH_V314: tuple
```

### `PORTED_TIMINGS_V35`

```python
PORTED_TIMINGS_V35: tuple
```

### `CHUNKABLE_TIMINGS_V35`

```python
CHUNKABLE_TIMINGS_V35: tuple
```

### `PRIMABLE_TIMINGS_V35`

```python
PRIMABLE_TIMINGS_V35: tuple
```

### `ChunkingNotEquivalent`

```python
class ChunkingNotEquivalent(ValueError)
```

Raised when a chunked v3.5 S3 pass could not reproduce the serial run.

Not a capability gap to be worked around with a looser comparison: the
named quantity is genuinely a running accumulation over the whole file,
so the chunked result would be *different output*, not *the same output
computed differently*.

### `ProbeV35`

```python
class ProbeV35
```

One ``case`` of the probe ``switch`` (``:134-235``), plus the framing
constants the record loop selects on ``probetype``.

The framing fields are **not** in the ``switch``: they are the literals
``:720-726`` (the read shape), ``:755-760`` (``start_first``), ``:754``
(``boundary_needs_time``), ``:764-772`` (``image_slice_offset``, which is
also the offset in the zero-image guard) and ``:785-795`` (``image_invert``
/ ``image_word_bits``) select per probetype.  Each was read from v3.5's own
file at those lines and, for probetypes 0/1/3, **measured** byte-identical
to v3.1.4's -- the diff between the two releases touches none of
``imgProc_sm.m`` 574-686 (v3.1.4) / 855-967 (v3.5), and the framing lines
outside that span differ only in the corrupt-boundary gate (V-PT, below).
They carry the same values as `arrayprobe.constants.IMGPROC_CONFIG`,
which ``tests/test_v35_imgproc_probetypes.py`` asserts field by field
rather than trusting this comment.

### `imgproc_variables_v35`

```python
def imgproc_variables_v35(*, iRectEllipse: int, iCalcAllDiodeStats: int, iQC: int, iNewHabit: int, extended_ellipse_outputs: bool | None, probetype: int) -> tuple[VariableSpec, ...]
```

The ``netcdf.defVar`` sequence of ``:318-660`` for one configuration.

Source: the ``netcdf.defVar`` block of ``imgProc_sm.m`` (UIOOPS v3.5), from ``:317``; bare line
references here are into that file.

``extended_ellipse_outputs`` stands in for the ``persistent
hasExtendedOutputs`` probe (``:255-272``): a recorded flag, not a runtime
probe of whichever ``CGAL_EllipseSize`` binary is on the path (upstream finding:
the binary-dependent output schema).
``probetype`` is accepted for symmetry with the MATLAB but has no effect on
the table -- ``Particle_number_all``'s gate ``:356`` is
``probetype~=0 || probetype~=3``, which is true for every probetype.

### `imgproc_sm_v35`

```python
def imgproc_sm_v35(infile: Any, outfile: Any, probename: str, n: int, nEvery: int, projectname: str, *, iRectEllipse: int=0, iCalcAllDiodeStats: int=0, iQC: int=0, iNewHabit: int, reject_config: RejectConfig, tas_time: Any, tas: Any, tas_ratio: Any=None, software: str, creation_time: str | None=None, extended_ellipse_outputs: bool | None=None, progress: Any=None, jit: bool=False, prime: tuple[float, float] | None=None, stamp_profile: str | None=None, tas_qc: dict[str, Any] | None=None, shadow_diode: Sequence[int] | np.ndarray | diode_mask.ShadowDiodeMask | None=None, stray_pixel_fix: bool=False, ncar_2dc_timing_fix: bool=False) -> int
```

``imgProc_sm(infile, outfile, probename, n, nEvery, projectname, iRectEllipse,
iCalcAllDiodeStats, iQC, iNewHabit, tasTime, tas[, tasRatio])`` (v3.5).

Required, no default -- each is a fidelity decision no default may make:
``iNewHabit``; ``tas_time`` / ``tas`` (``varargin{1..2}``, arrays, the
aircraft series ``:186-188``); ``software`` (replaces ``:283-285``'s bare
relative ``fopen('version.txt')`` -- the vendored file reads
``UIOOPS_v3.5``, upstream's own spelling); and ``reject_config``.

``reject_config`` is required rather than fixed to ``STOCK_V35_REJECT_CONFIG``.
``calculate_reject_unified.m`` assigns its thresholds
unconditionally at the top of the function, and the archived production tree
ships a **modified copy of that file**, so the configuration is a fidelity
decision in exactly the sense ``profiles.py``'s header means. A fixed value
would also put one of the v3.5 port's three whole-program Octave goldens --
``oraclesprod_v35.nc``, run against the production reject tree -- out of reach entirely.

``tas_ratio`` is ``varargin{3}``: indexed by the **absolute** record ``i``
(``:709``), so a chunked run must pass the whole-file series (upstream finding: the
absolute-record tasRatio index).  ``None`` is the ``iTAS == 0`` path,
``handles.tasRatio = 1.0`` (``:711``).

``extended_ellipse_outputs`` must be given (``True``/``False``) iff
``iRectEllipse == 1``, and must be ``None`` otherwise.

``jit``
    Speed only, **default off** (space: the port). ``True`` routes
    the two v3.5 call sites whose MATLAB is unchanged from v3.1.4 --
    ``dec2bin_concat`` (this module's own framing/timing unpacks) and
    ``particle_perimeter`` (inside `arrayprobe_uiops.measure.
    measure_record`) -- through `arrayprobe_uiops.jit_kernels`, which
    reuses the earlier translation's already-proven compiled kernels rather than
    re-translating them. Exact by construction, so the file written is
    the same bytes (``tests/test_v35_imgproc_jit_identity.py`` runs both
    and compares). v3.5's OWN hot kernel, ``cgal_min_r_v35``, is not
    included -- see `arrayprobe_uiops.jit_kernels`'s module docstring
    for the measured numbers and why. Needs numba, imported only here.

``prime``
    The ``(part_time_prev, time_in_seconds_prev)`` pair a serial run holds
    at the top of this chunk's first record, from `prefix_scan_v35`.
    **Default ``None``, which is a whole-file run and changes nothing.**
    ``"spec"`` timing only: it is the state that crosses a
    probetype-2 chunk seam, and handing it over is what makes a chunked
    pass reproduce the serial one *bit for bit* rather than approximately
    -- a left-fold resumed from its own exact partial value is the same
    fold, where a post-hoc offset re-rounds every element. The other three
    timings either carry nothing across a seam or have their one crossing
    quantity repaired exactly by `merge_chunks_v35`, so passing
    ``prime`` there is refused rather than silently ignored.

``shadow_diode``
    Stuck diodes to re-illuminate: 1-based diode numbers, or a
    `arrayprobe_uiops.diode_mask.ShadowDiodeMask` (from
    ``arrayprobe tune diodes``). **Default ``None``, and an empty list,
    change nothing** (``tests/test_v35_shadow_diode.py``). Stock v3.5 has
    no masking; this is the production fork's ``c(:,shadow_diode)='1'``
    (nine-argument ``imgProc_sm``, extraction ``:286-292``), applied by
    `arrayprobe_uiops.diode_mask.reilluminate` right after the image
    is decoded into characters and before the ``iQC`` clean-up
    (``:801-846``), so ``qc_image`` sees the re-illuminated image. A diode
    number past the probe's width widens the image, as MATLAB does, and
    the ``:850-853`` width check then ends the run.

Returns the number of particles written.

### `merge_chunks_v35`

```python
def merge_chunks_v35(chunk_paths: Any, outfile: Any, *, projectname: Any, infile: Any, probename: Any, iNewHabit: Any, software: Any, iRectEllipse: Any=0, iCalcAllDiodeStats: Any=0, iQC: Any=0, extended_ellipse_outputs: Any=None, creation_time: Any=None, stopped_at: Any=None, primed: Any=False, stamp_profile: Any=None, tas_qc: dict[str, Any] | None=None, stray_pixel_fix: bool=False) -> int
```

Stitch N chunk-local v3.5 proc files into one whole-file result.

``stray_pixel_fix`` must state what every chunk worker ran with: when True the two
`STRAY_PIXEL_VARIABLES` and the ``arrayprobe_stray_pixel`` attribute are carried into
the merge exactly as a serial ``stray_pixel_fix=True`` run writes them (the correction is
per particle image, and no particle spans a record, so a record-range seam cannot split
one). A chunk whose stray-pixel variables disagree with it is refused, never dropped.

The v3.5 counterpart of the earlier translation's ``merge_chunks``, and the
same mechanism: each chunk file is an ordinary `imgproc_sm_v35` call
over a disjoint, **ordered** record range (the ``n``/``nEvery`` API a
whole-file run already uses with ``n=1``).  Chunks must be passed in the
record order the split was made in -- nothing on disk records which range a
chunk covers, so this cannot detect a reordering.

**The cross-record state audit, per quantity** (the reason this is a
fidelity function and not a plumbing one):

* ``kk`` is **record-local** -- ``:1312`` increments it per particle and
  ``:1402`` resets it to 1 for every record that wrote, so it is 1 at the
  top of every record and a seam cannot renumber anything.  ``particle_num
  = mod(kk, 66536)`` (``:858``, the preserved 65536 typo) therefore counts
  *within a record*, not across the file, and needs no merging.
* ``parent_rec_num`` (``:857``) is the **absolute** record ``i``, because
  the loop is written over absolute record numbers in both cases.
* ``tasRatio`` (``:709``) is indexed by that same absolute ``i``, so every
  chunk worker must be handed the **whole-file** series -- which
  `imgproc_sm_v35` enforces itself, raising ``IndexError`` rather
  than silently reading the wrong element.
* ``w``/``wstart`` are chunk-local write indices; concatenation in chunk
  order is what merges them.
* ``diode_stats``/``bin_stats`` accumulate per file and merge by summation.
* ``inter_arrival`` is the **one** quantity a seam genuinely breaks, and
  only on ``"dmt"`` timing -- see below.
* ``part_time_prev``/``time_in_seconds_prev`` on ``"spec"`` timing are what
  ``primed=True`` asserts were handed to every chunk after the first, as
  `imgproc_sm_v35`'s ``prime=``.  Without that assertion the merge
  still refuses ``"spec"`` -- see `CHUNKABLE_TIMINGS_V35` and
  `PRIMABLE_TIMINGS_V35`.

``primed`` is the caller's statement that it did the priming, and this
function **cannot verify it**: nothing on disk records whether a chunk was
primed, exactly as nothing records which record range it covers.  Passing
``primed=True`` over unprimed chunks produces a silently wrong file. The
driver that splits the work is the one place that knows, so it is the one
place that may pass it -- ``scripts/run_flight.py`` does, next to the
``prefix_scan_v35`` call whose result it fed in.

**The ``inter_arrival`` seam repair (probetype 1 only), and why it is
exact.**  ``:1110-1114`` writes ``t - time_in_seconds_prev`` for every
particle, where ``time_in_seconds_prev`` is the immediately preceding
particle's ``t`` -- carried across record boundaries, new in v3.5.  At the
top of a chunk that variable is ``None``, so the chunk's first particle
gets ``0.0`` where the serial run would have written a real difference.
Both operands are on disk as ``Time_in_seconds`` (``:305``, ``double``),
and ``t`` itself is record-local, so recomputing the difference here uses
**the identical pair of float64 values and the identical IEEE
subtraction** the serial run performed.  It is the same number, not a
close one -- asserted with ``np.array_equal`` on the bytes, not
``allclose``.

``stopped_at`` is the 1-based index of the first chunk whose worker hit the
``:850-853`` width-mismatch ``return``.  MATLAB exits the *whole function*
there, leaving every later record unprocessed, so the serial-equivalent
merge keeps chunks ``1..stopped_at`` (that chunk's own file already ends
where MATLAB would have stopped) and **discards the rest** -- which a
chunked run computed only because its later workers never saw the
mismatch.  ``None`` means no chunk returned early.

Returns the merged particle count.

### `prefix_scan_v35`

```python
def prefix_scan_v35(infile: Any, probename: str, stop_record: int, *, tas_time: Any, tas: Any, iQC: int=0, progress: Any=None) -> tuple[float, float] | None
```

The ``prime=`` pair a serial run holds at the top of ``stop_record``.

Replays ``imgProc_sm.m:693-1180``'s **scan** over records
``1 .. stop_record-1`` and returns ``(part_time_prev, time_in_seconds_prev)``
-- or ``None`` when no particle precedes that record, which is a chunk that
needs no priming (the first chunk of a file always).  The return value is
what `imgproc_sm_v35`'s ``prime=`` takes, unchanged.

**What it deliberately does not do.**  No ``dec2bin_concat``, no
``measure_record``, no reject pass, no habit -- that is where a run's time
goes, and none of it is read by ``:1131-1180``.  The accumulation sees only
the record header (``:1132``, the TAS lookup key), the boundary walk that
locates each particle (``:751-779``), and ``part_time`` from the particle's
own header words (``:1123``).  ``tests/test_v35_sizedist_chunk_priming.py``
spies ``measure_record`` during a full-file scan and asserts it is called
**zero** times: a scan that measured would prime correctly and save nothing.

**The width check, carried arithmetically.**  ``:850-853`` exits the whole
function when an unpacked image is not ``diodenum`` wide.  For ``iQC == 0``
that width is ``read_width * image_word_bits``, a constant of the file, so
the check cannot fire mid-file without firing on the very first particle --
and it is decided here without unpacking anything.  ``iQC == 1`` is refused
outright: ``qc_image`` can change a width mid-file, so a scan cannot know
where a serial run would have stopped without doing the work it exists to
skip.

**``tas_time``/``tas`` are required and must be the run's own series.**  The
fold is ``time_in_seconds_prev + (part_time - part_time_prev) * scale``
under both arms of ``:1131-1170``, but ``scale`` is built from the TAS
lookup, so a scan run against a different series -- or against the empty
arrays that select ``TAS_FALLBACK`` (170) -- lands on a *different* pair and
primes the chunk wrongly.  No default: this is the same fidelity decision
`imgproc_sm_v35` refuses to make for probetype 2, and a silently
wrong prime is worse than a refusal because the output still looks like a
serial run.

``progress`` is called as ``progress(i, stop_record - 1)`` per record.  Pass
one for a long scan: a chunk worker that is silent for its whole prefix is
indistinguishable from a hung one to ``--worker-stall-min``.

### `chunk_primes_v35`

```python
def chunk_primes_v35(infile: Any, probename: str, n_every: int, chunks: int, *, tas_time: Any, tas: Any, iQC: int=0, progress: Any=None) -> list[tuple[float, float] | None]
```

Every chunk's ``prime=`` pair, in **one** pass over the file.

Returns a list of length ``chunks``: element ``k-1`` is what chunk ``k``
(records ``(k-1)*n_every+1 ..``) must be given.  The first is always
``None`` -- no particle precedes record 1.

**Why the driver calls this and not `prefix_scan_v35` per chunk.**
Each worker scanning its own prefix reads ``chunks/2`` files' worth in
total and makes the last worker scan almost the whole file before it starts
processing.  One pass in the parent costs a single read, and the seam states
are then just N points along the same walk.  The arithmetic is identical
either way -- this is a scheduling choice, not a fidelity one, and
``tests/test_v35_sizedist_chunk_priming.py`` asserts the two agree.

### `particle_num_v35`

```python
def particle_num_v35(kk: int) -> int
```

``:858`` -- ``mod(kk,66536)``.  Preserved.

Source: ``imgProc_sm.m:858`` (UIOOPS v3.5).

### `gcpex_cip_offsets`

```python
def gcpex_cip_offsets(rec: Any) -> tuple[int, int, int]
```

``:976-1074`` -- ``(hour, minute, second)`` offset for one image record.

Source: ``imgProc_sm.m:976-1074`` (UIOOPS v3.5).

``rec`` is `arrayprobe_uiops.imgproc_core._read_record_header`'s dict, i.e. the
record's own ``handles.month``/``day``/``hour``/``minute``/``second``/
``millisec`` -- never a particle-level time.  A date with no entry returns
``(0, 0, 0)`` (``:1072-1073``).

## `arrayprobe_uiops.provenance`

One parser for every ``.call`` provenance sidecar this project writes -- and ``None`` when a

### `ATTR_CALL`

```python
ATTR_CALL: object
```

### `ATTR_ENGINE`

```python
ATTR_ENGINE: object
```

### `ATTR_PREFIX`

```python
ATTR_PREFIX: str
```

### `ATTR_PROFILE`

```python
ATTR_PROFILE: object
```

### `ATTR_STAGE`

```python
ATTR_STAGE: object
```

### `CALL_SUFFIX`

```python
CALL_SUFFIX: str
```

### `ENGINES`

*(re-exported from elsewhere; not defined in this module)*

### `EngineUnrecorded`

```python
class EngineUnrecorded(Exception)
```

A product *has* a stamp, and that stamp does not name an engine.

Distinct from `Unstamped` because the two call for different answers: an unstamped file
may simply predate stamping, while a stamp that exists and is silent on the engine is a format
that never had the field (every ``legacy-json`` lane stamp, and every driver stamp written
before 2026-09-15).

### `FORMATS`

*(re-exported from elsewhere; not defined in this module)*

### `PROFILE_UNSTATED`

```python
PROFILE_UNSTATED: str
```

### `PROVENANCE_ATTRS`

```python
PROVENANCE_ATTRS: frozenset
```

### `engine_attrs`

```python
def engine_attrs(*, engine: str, profile: str | None) -> dict[str, str]
```

The two global attributes every v3.5 and SODA-2 product carries.

``{ATTR_ENGINE: engine, ATTR_PROFILE: profile or PROFILE_UNSTATED}``, in that order. Written
unconditionally by those engines' writers -- a product that is copied, renamed or hardlinked
still says what wrote it. **Never written by the earlier translation**, whose products must stay
byte-faithful to MATLAB's; there the opt-in `arrayprobe_uiops.ncio.put_provenance`
remains.
``profile`` is required but may be ``None``: ``None`` writes `PROFILE_UNSTATED`.

### `ProvenanceDisagreement`

```python
class ProvenanceDisagreement(Exception)
```

The attribute inside a product and the ``.call`` sidecar beside it say different things.

**Never resolved silently.** The attribute is additive -- it does not outrank the sidecar and
the sidecar does not outrank it -- so a disagreement is a finding about the product, not a tie
to break. Picking a winner here would manufacture exactly the confident-but-wrong answer that
this module exists to stop; raising hands the question to whoever can actually settle it.

``differences`` is the list `disagreements` produced, one line per field that both
carriers state and state differently.

### `STATES`

*(re-exported from elsewhere; not defined in this module)*

### `Stamp`

```python
class Stamp
```

One parsed ``.call`` sidecar.

``engine`` is ``None`` whenever the stamp does not say. ``raw`` is the sidecar's text verbatim,
because the parsed keys are a convenience and the raw line is the record.

### `Unstamped`

```python
class Unstamped(Exception)
```

A product carries no ``.call`` sidecar, so nothing is recorded about what wrote it.

### `attrs_for`

```python
def attrs_for(*, engine: str, profile: str | None, stage: str | None=None, extra: dict[str, str] | None=None) -> dict[str, str]
```

The global attributes that record this configuration, ready for ``putAtt``.

Pure ``str`` in, pure ``dict[str, str]`` out -- no netCDF here, so this module stays
stdlib-only and a lane script can import it. `arrayprobe_uiops.ncio.put_provenance` is
what
writes them.

### `call_path`

```python
def call_path(product: Path | str) -> Path
```

Where ``product``'s stamp lives: ``<product><CALL_SUFFIX>``, beside it, never inside it.

### `disagreements`

```python
def disagreements(sidecar: Stamp | None, inside: Stamp | None) -> list[str]
```

Every field the two carriers **both state** and state differently.

**Silence is not disagreement.** A sidecar that records no engine (every ``legacy-json`` lane
stamp, and every driver stamp written before 2026-09-15) against an attribute that names one
is the attribute supplying what the sidecar lacks -- the point of carrying provenance in the
file, not a finding. Only a field both sides fill, with different values, is reported. Extra
keys on either side are
likewise not a difference: the sidecar may carry a ``reject=(...)`` fragment no attribute
holds, and saying so on every product would train the reader to ignore the check.

### `engine_of`

```python
def engine_of(product: Path | str) -> str
```

The engine that wrote ``product``, from its own stamp.

Raises `Unstamped` when there is no sidecar and `EngineUnrecorded` when there is
one that does not name an engine. It never returns a default; there is no code path here that
produces an engine name the stamp did not contain.

### `is_provenance_attr`

```python
def is_provenance_attr(name: str) -> bool
```

Whether ``name`` is one of this project's provenance global attributes.

By prefix, not by membership of `PROVENANCE_ATTRS`, so a comparison that excludes
"our provenance" keeps excluding all of it when a fourth key is added later. A check that
enumerates is a check that silently stops covering things.

### `parse`

```python
def parse(text: str) -> Stamp
```

Parse stamp ``text`` in whichever of the five formats it is written in.

Detection is by content, not by filename: a ``.pbp.call`` renamed does not stop being SODA-2
JSON, and a lane script's JSON does not become a driver stamp by sitting next to a ``proc``.

### `read`

```python
def read(product: Path | str) -> Stamp | None
```

``product``'s parsed stamp, or ``None`` when it has no sidecar.

### `read_in_file_stamp`

```python
def read_in_file_stamp(filename: str | os.PathLike[str]) -> Stamp | None
```

The stamp ``filename`` carries **in its own bytes** (its global attributes), or ``None`` if
it carries none.

Survives a rename, a copy and a hardlink, which a ``.call`` sidecar keyed by filename does not.
``netCDF4`` is imported here rather than at module load, so importing this module stays cheap.

### `read_text`

```python
def read_text(product: Path | str) -> str | None
```

``product``'s stamp text, or ``None`` if it has none.

An unreadable sidecar is ``None`` too -- no stamp and a stamp we cannot open are the same
epistemic state, and neither is an engine.

### `report`

```python
def report(paths: Iterable[Path | str], *, require: bool=False) -> tuple[str, int]
```

The ``arrayprobe provenance`` table, and an exit code.

Returns ``(text, code)``. With ``require=True`` the code is ``1`` unless every reported
product is ``stamped`` **and names an engine**. The second half is not redundant: a driver
stamp written before 2026-09-15 has no ``engine=`` key, so it is legitimately ``stamped`` --
the sidecar is there and records the whole configuration -- while still not saying what wrote
the file. Passing it would let ``--require`` green-light exactly the products of
unrecorded engine this module exists to catch.
A directory answer is never silent: an empty directory says so, which is how the two-empty-
trees reading of "there is nothing here" is prevented.

``nlink`` is printed because a sidecar is keyed by name: a product with ``nlink > 1`` has at
least one other name, and that other name has no stamp of its own.

### `require`

```python
def require(product: Path | str) -> Stamp
```

``product``'s stamp, raising `Unstamped` when there is none.

### `stamp_from_attrs`

```python
def stamp_from_attrs(attrs: dict[str, Any]) -> Stamp | None
```

The `Stamp` a product's own global attributes record, or ``None`` if it has none.

Reads through `parse`, the same parser the sidecar goes through -- there is deliberately
no second parser for the attribute form. `ATTR_CALL` is the record when present; the
discrete keys are re-assembled into the same text when it is not (a hand-annotated file, or a
future writer that sets only the engine).

Raises `ProvenanceDisagreement` when the file's own keys contradict its own
`ATTR_CALL` -- which `attrs_for` cannot produce, so it means the file was edited.

### `stamp_text`

```python
def stamp_text(*, engine: str, profile: str | None, stage: str | None=None, extra: dict[str, str] | None=None) -> str
```

The one-line driver-format stamp text, with no trailing newline.

**Both carriers are built from here** -- `write` writes this plus ``"\n"`` into the
sidecar, `attrs_for` puts this into `ATTR_CALL` -- so the attribute and the sidecar
are byte-identical by construction rather than by anyone remembering to keep them so. That is
what stops the attribute becoming a second source of truth: there is one text, stored twice.

Raises ``ValueError`` on an engine outside `ENGINES`, or on a value containing a newline
or a space-separated ``word=`` (which would re-parse as a second key and quietly change what
the stamp says).

### `state`

```python
def state(product: Path | str) -> str
```

One of `STATES`, for one product path.

``orphan-stamp`` is a sidecar whose product is gone -- five of them sit in
``_decoded/cip160906/`` alone. ``in-flight`` outranks the rest because a partial file's
missing stamp is expected, not a finding.

### `write`

```python
def write(product: Path | str, *, engine: str, profile: str | None, stage: str | None=None, extra: dict[str, str] | None=None) -> Path
```

Stamp ``product`` in the **driver text format**, partial-then-rename.

The text shape mirrors ``scripts/run_flight.py:write_stamp`` deliberately, so that a product
stamped by a single-stage CLI verb and one stamped by the driver are read by the same parser
and compare by the same string rules. Partial-then-``os.replace`` is not decoration: a kill
mid-write would otherwise leave a truncated stamp, which compares unequal and silently costs a
redo -- or, worse, compares equal to a prefix of some future label.

Returns the sidecar path. Raises ``ValueError`` on an engine outside `ENGINES`, or on a
value containing a newline or a space-separated ``word=`` (which would re-parse as a second
key and quietly change what the stamp says).

## `arrayprobe_uiops.decode_naming`

The one place that names a stage-2 decode: engine and reader decide the extension together.

*No public API declared (`__all__` empty or absent).*

## `arrayprobe_uiops.diode_mask`

Stuck-diode masking shared by both engines: the fork's rule and its re-illumination.

### `STUCK_FRACTION`

```python
STUCK_FRACTION: float
```

### `HIGH_FRACTION`

```python
HIGH_FRACTION: float
```

### `ShadowDiodeMask`

```python
class ShadowDiodeMask
```

The ``shadow_diode`` list from one ``diode.<date><time>[.<or>].mat``.

### `StuckDiodeRule`

```python
class StuckDiodeRule(NamedTuple)
```

What ``find_shadow_diodes.m:66-97`` computes from one ``bin_stats`` vector.

### `stuck_diodes`

```python
def stuck_diodes(bin_stats: npt.ArrayLike) -> StuckDiodeRule
```

The fork's stuck-diode rule on **lit** counts, ``find_shadow_diodes.m:66-97``.

* ``:66`` -- diodes above ``1.2 x mean`` (masked in flight: lit on every
  slice) are replaced by ``nanmean(a)`` (``:68-69``), and a diode is stuck
  below ``0.80 x mean`` of the replaced array (``:94``);
* otherwise a diode is stuck below ``0.80 x max`` (``:97``), int32.

``a(ill_diode)=NaN`` stores 0 on int32 ``a``, so ``nanmean`` averages those
zeros in: the replacement is diluted by ``len(ill_diode)/n``.  Reproduced.

``bin_stats`` must count lit slices (the production fork's ``imgProc_sm.m:387-388``);
a shadow count turns the rule upside down.  A non-positive mean raises
``ValueError``: ``:55``'s ``ylim([0 1.5*nanmean(a)])`` stops MATLAB first.

### `reilluminate`

```python
def reilluminate(c: np.ndarray, diodes: Sequence[int] | np.ndarray | ShadowDiodeMask, *, index_error: type[Exception]=IndexError) -> np.ndarray
```

``c(:,shadow_diode)='1'`` -- set whole diode columns to lit.

``c`` is the ``(nslices, ndiodes)`` uint8 ASCII image.  ``diodes`` is a
sequence of 1-based diode numbers, or a `ShadowDiodeMask`.

Two MATLAB behaviours are reproduced rather than tidied:

* **An empty list is a no-op.**  ``c(:,[])='1'`` changes nothing, which is
  what makes the empty-mask case identical to no mask at all.
* **An index past the last diode WIDENS the image.**  MATLAB grows the array
  and pads the new columns with ``char(0)``; measured in Octave,
  ``c=['0101';'1010']; c(:,[2 6])='1'`` returns a 2x6 char array whose fifth
  column is 0.  It does *not* error.  ``imgProc_sm.m:272-276`` then finds
  ``size(c,2) ~= diodenum``, prints ``Not equal to doide number`` and
  ``return``\ s from the whole function -- so a mask with one bad diode
  number ends the run part-way through, leaving a short proc file and no
  error status.  Reproducing the widening is what lets that guard fire here
  too, instead of being pre-empted by an IndexError of our own invention.

A zero, negative or fractional entry raises ``index_error`` (the earlier
translation passes its ``MatlabIndexError``), as MATLAB does: *"subscripts must
be either integers 1 to (2^63)-1 or logicals"*.

## `arrayprobe_uiops.export_oap`

Export decoded 2D-S images in NCAR's RAF OAP file format (``.2d``).

### `BOUNDARY_WORD`

```python
BOUNDARY_WORD: int
```

### `OapStamp`

```python
class OapStamp
```

The per-record header fields (as stored: unsigned 16-bit words).

### `OapWriteReport`

```python
class OapWriteReport
```

### `ExportParticle`

```python
class ExportParticle
```

One particle: ``shaded`` is ``(n_slices, 128)`` with 1 = shaded, S2's
convention; ``timing`` is the 32-bit counter; ``stamp`` the record time.

### `encode_slice`

```python
def encode_slice(shaded_row: np.ndarray) -> bytes
```

One 128-diode slice, 1 = shaded in, OAP bytes (1 = clear) out, diode 0 at
byte 15 bit 7 (process2d's order).

### `particles_from_canvas`

```python
def particles_from_canvas(canvas: np.ndarray) -> list[tuple[np.ndarray, int]]
```

Split one S2 record canvas into ``(shaded, timing)`` per particle.

``canvas`` is ``(8, n_columns)`` integer words, one column per slice, as the
S2 ``data`` variable holds it for one ``time`` step. A particle is the image
columns up to a boundary column (every word ``BOUNDARY_WORD``), closed by the
header column after it, whose words 7-8 are the 32-bit timing counter.
Columns after the last header column (the zero fill of the canvas) are
ignored. An image column that is itself all-alternating would be read as a
boundary; the header column that must follow is not checked further.

### `main`

```python
def main(argv: Sequence[str] | None=None) -> int
```

``python -m arrayprobe_uiops.export_oap DECODE OUT --probe 2DS``: one channel, one file.

Opt-in: writes ``OUT`` and nothing else, and changes no product.

### `particles_from_decode`

```python
def particles_from_decode(path: str | Path) -> tuple[bytes, list[ExportParticle]]
```

Read a v3.5 S2 decode (``<flight>.H.nc`` / ``.V.nc``) into export particles.

Returns the channel's probe id (``SH`` / ``SV``, from the file's
``Probe Channel_Orientation``) and every particle in file order, each
stamped with its record's time, millisecond and TAS (rounded to a uint16
word; a missing or negative TAS is written as 0). Raises ``ValueError`` on a
file that is not a v3.5 SPEC decode, or that names another probe.

### `write_oap_2ds`

```python
def write_oap_2ds(particles: Iterable[ExportParticle], out: str | Path, *, probe_id: bytes=b'SH', project: str='', platform: str='', flight_number: str='', probe_type: str='2DS', serial: str='', timing_convention: str='translate2ds') -> OapWriteReport
```

Write ``particles`` (in time order) to ``out`` as one 2D-S channel.

## `arrayprobe_uiops.oap_read`

Reader for 2D-S records in NCAR's RAF OAP file format, written from process2d's rule.

### `OAP_RECORD_BYTES`

```python
OAP_RECORD_BYTES: int
```

### `OapParticle`

```python
class OapParticle
```

One particle: the image slices before a sync slice, and that sync's timing.

``bits`` is ``(n_slices, 128)`` uint8 in process2d's diode order, values as
stored (1 = clear, the OAP convention); ``shaded`` inverts it.
``record`` is the 0-based index of the record holding the sync slice.

### `OapRecordHeader`

```python
class OapRecordHeader
```

The 20-byte record header, as stored.

### `SLICE_BYTES_2DS`

```python
SLICE_BYTES_2DS: int
```

### `UnsupportedProbeVersion`

```python
class UnsupportedProbeVersion(ValueError)
```

A RAF OAP raw file names a probe version the v3.5 engine cannot frame.

### `read_oap_2ds`

```python
def read_oap_2ds(path: str | Path, probe_id: bytes=b'SH') -> tuple[str, list[OapRecordHeader], list[OapParticle]]
```

Read every record tagged ``probe_id`` and split its slice stream at syncs.

Slices run continuously across records of the same probe, as translate2ds
writes them. Slices after the last sync (zero padding of the final record
included) belong to no particle and are not returned. Records of other
probes are skipped. Raises ``ValueError`` if the record area is not a whole
number of records.

### `refuse_unsupported_raf_probe`

```python
def refuse_unsupported_raf_probe(path: str | Path) -> None
```

Raise `UnsupportedProbeVersion` if ``path``'s preamble names a probe
type the v3.5 engine cannot frame (today: ``Fast2DC_v2``).

Reads only the head of the file. A file with no XML preamble, or whose probe
types are all framable, passes and returns ``None``.

### `split_oap_xml`

```python
def split_oap_xml(raw: bytes) -> tuple[str, int]
```

Return the XML preamble and the byte offset of the first record.

The preamble ends at ``</OAP>`` plus the newline after it. A file without a
preamble starts its records at offset 0.

## `arrayprobe_uiops.ncio`

MATLAB ``netcdf.*`` package semantics on top of netCDF4-python.

### `NC_UNLIMITED`

```python
NC_UNLIMITED: int
```

``netcdf.getConstant('NC_UNLIMITED')`` -- ``imgProc_sm.m:214``,

### `NC_GLOBAL`

```python
NC_GLOBAL: object
```

``netcdf.getConstant('NC_GLOBAL')`` -- ``imgProc_sm.m:218``,

### `MATLAB_NC_TYPES`

*(re-exported from elsewhere; not defined in this module)*

### `NC_FILL`

*(re-exported from elsewhere; not defined in this module)*

### `get_constant`

```python
def get_constant(name: str) -> int
```

``netcdf.getConstant(name)`` for the two constants UIOOPS uses.

### `NcFile`

```python
class NcFile
```

A MATLAB ``ncid``.

MATLAB identifies dimensions and variables by **integer IDs assigned in
creation order**, and UIOOPS relies on that: ``imgProc_sm.m:205-206`` reads
dimension 0 (``time``) and dimension 2 (``ImgBlocklen``) by number alone,
never by name.  A bare `netCDF4.Dataset` has no such numbering, so this
class keeps it -- along with the mask/scale policy and the define-mode state.

### `create`

```python
def create(filename: str | os.PathLike[str], mode: str='clobber', *, format: str='NETCDF3_CLASSIC') -> NcFile
```

``netcdf.create(filename,'clobber')``.

Every creation site in UIOOPS passes a bare ``'clobber'`` and no format, so
MATLAB's default ``NC_FORMAT_CLASSIC`` applies -- confirmed from the magic
bytes of the three shipped probe files (``b'CDF\x01'``).  Default preserved
here, **including its failure mode**: NETCDF3_CLASSIC caps a non-record
variable at 2 GiB and ``imgProc_sm.m`` writes ~40 record variables, so a large
flight fails at ``putVar`` exactly as MATLAB's would.  ``format=`` is the
escape hatch, never the default.

### `open`

```python
def open(filename: str | os.PathLike[str], mode: str='nowrite') -> NcFile
```

``netcdf.open(filename,'nowrite')``.

Reads both NETCDF3_CLASSIC and NETCDF3_64BIT_OFFSET: the probe files UIOOPS
writes are classic, but ``flightData_20151205.cdf`` -- an *input*, produced
outside UIOOPS and consumed at ``imgProc_sm.m:169-170`` -- is 64-bit offset.

### `def_dim`

```python
def def_dim(ncid: NcFile, name: str, length: int) -> int
```

``netcdf.defDim`` -- see `NcFile.def_dim`.

### `def_var`

```python
def def_var(ncid: NcFile, name: str, xtype: str, dimids: npt.ArrayLike, *, chunksizes: npt.ArrayLike | None=None) -> int
```

``netcdf.defVar`` with ``dimids`` (and ``chunksizes``, when given) in MATLAB
order -- see `NcFile.def_var`.

### `put_att`

```python
def put_att(ncid: NcFile, varid: int, name: str, value: Any) -> None
```

``netcdf.putAtt`` -- see `NcFile.put_att`.

### `end_def`

```python
def end_def(ncid: NcFile) -> None
```

``netcdf.endDef`` -- see `NcFile.end_def`.

### `inq_dim`

```python
def inq_dim(ncid: NcFile, dimid: int) -> tuple[str, int]
```

``netcdf.inqDim`` -- see `NcFile.inq_dim`.

### `inq_var_id`

```python
def inq_var_id(ncid: NcFile, name: str) -> int
```

``netcdf.inqVarID`` -- see `NcFile.inq_var_id`.

### `get_var`

```python
def get_var(ncid: NcFile, varid: int, start: npt.ArrayLike | None=None, count: npt.ArrayLike | None=None) -> np.ndarray
```

``netcdf.getVar`` -- see `NcFile.get_var`.  Raw, unmasked.

### `put_var`

```python
def put_var(ncid: NcFile, varid: int, *args: Any) -> None
```

``netcdf.putVar`` -- see `NcFile.put_var`.

### `close`

```python
def close(ncid: NcFile) -> None
```

``netcdf.close`` -- see `NcFile.close`.

### `ncread`

```python
def ncread(filename: str | os.PathLike[str], varname: str) -> np.ndarray
```

MATLAB ``ncread(filename,varname)``.

MATLAB dimension order, like `get_var`, but with ``_FillValue`` masking
and ``scale_factor``/``add_offset`` **applied** -- the opposite policy, which
is why this is a separate function rather than a flag.  Returns a masked array
when the file gives cause to mask.

Provenance: ``imgProc_sm.m:169-170,184-185`` (TAS and Time from the flight-data
file); ``run_imgProc_Munich.m:16-24,32-34``; ``run_sizeDist_Munich.m:25-28``.

### `read_image_record`

```python
def read_image_record(ncid: NcFile, varid: int, i: int, n_bytes: int, n_slices: int) -> np.ndarray
```

``imgProc_sm.m:489-495`` fused into one call.

MATLAB reads ``temp = netcdf.getVar(f,varid,[0,0,i-1],[8,1700,1])`` (``8x1700``)
and immediately does ``data(:,:) = temp';`` -- so what the rest of
``imgProc_sm.m`` calls ``data`` is ``1700x8``, i.e. ``ds['data'][i,:,:]`` with
no transpose at all.  ``i`` here is the **0-based** record index.

Returns ``(n_slices, n_bytes)``.  Orientation check: the 2DS boundary word
(``imgProc_sm.m:159``) fills a whole 8-element slice, so all-43690 runs lie
along the last axis.

### `write_record_block`

```python
def write_record_block(ncid: NcFile, varid: int, start: int, block: npt.ArrayLike) -> None
```

``imgProc_sm.m:873-929`` fused: append ``block`` at 0-based record ``start``.

``block`` is in **C/on-disk order** (time first) because the MATLAB ``'`` at
those call sites has already been absorbed -- that is the whole point of the
cancellation noted in the module docstring.  Passing a MATLAB-order array here
is the one easy mistake, so the shape is checked against the variable's
trailing dimensions.

### `put_provenance`

```python
def put_provenance(ncid: NcFile, *, engine: str, profile: str | None, stage: str | None=None, extra: dict[str, str] | None=None) -> dict[str, str]
```

Write `arrayprobe.provenance.attrs_for`'s global attributes into ``ncid``.

**Opt-in, and nothing in the port calls it.** Adding a global attribute changes the file's
bytes, and the layer-1 comparison is not hypothetical about that:
the image-processing oracle test asserts
``a.ncattrs() == b.ncattrs()`` against the
MATLAB-written oracle, so a writer that stamped by default would fail that test on its first
run -- and would shift every tracked ``.call`` fixture and every archived comparison in the
same commit. A writer opts in by calling this; the default stays "writes exactly what MATLAB
wrote", which is the claim the whole project rests on.

Define mode, like every other ``putAtt``: call it before `NcFile.end_def`. Returns the
attributes written, so a caller can pass the identical values to
`arrayprobe.provenance.write` and have the sidecar and the attribute agree by
construction -- both texts come from ``provenance.stamp_text``.

``alongside the .call sidecar rather than instead of it``: this does **not** write a sidecar.
The two carriers are written by two calls on purpose, because a product may legitimately have
one and not the other (an older product has only the sidecar; a hardlinked copy has only the
attribute), and `provenance_of` is what reads whichever exist.

### `read_provenance`

```python
def read_provenance(filename: str | os.PathLike[str]) -> provenance.Stamp | None
```

The stamp ``filename`` carries **in its own bytes**, or ``None`` if it carries none.

Survives a rename, a copy and a hardlink, which is the entire reason it exists: a ``.call``
sidecar is keyed by filename, so a hardlinked name carries no sidecar stamp (observed
for a 1.25 GB CIP product). One implementation, in the v3.5 engine:
`arrayprobe_uiops.provenance.read_in_file_stamp`.

### `provenance_of`

```python
def provenance_of(filename: str | Path) -> provenance.Stamp
```

Both carriers, reconciled -- raising rather than choosing when they disagree.

Reads the attribute inside ``filename`` and the ``.call`` sidecar beside it, and:

* raises `arrayprobe.provenance.ProvenanceDisagreement` when both state a field and
  state it differently -- **the guard that provenance carried in the file exists
  for**. Neither carrier outranks the other, so there is no tie to break: one of them
  describes a run that did not write these bytes;
* returns the attribute's stamp when only it exists (the hardlink case);
* returns the sidecar's stamp when only it exists (every product written before today);
* raises `arrayprobe.provenance.Unstamped` when neither exists.

Agreement is field-by-field over the fields **both** carriers state, so a sidecar that records
no engine and an attribute that names one is agreement, not conflict -- see
`arrayprobe.provenance.disagreements`.

### `engine_of`

```python
def engine_of(filename: str | Path) -> str
```

The engine that wrote ``filename``, from **either** carrier, or a refusal.

`arrayprobe.provenance.engine_of` asks the sidecar alone, so it cannot answer for a
renamed, copied or hardlinked product. This asks the bytes first and the sidecar second, and
is otherwise the same contract: it never returns a default, never infers an engine from a
date, a filename or a neighbouring file, and raises

* `~arrayprobe.provenance.ProvenanceDisagreement` when the carriers conflict,
* `~arrayprobe.provenance.Unstamped` when neither exists,
* `~arrayprobe.provenance.EngineUnrecorded` when what exists does not say --
  which is still the honest answer for every product written before 2026-09-18.

## `arrayprobe_uiops.profiles`

The fidelity-profile type and the one shared profile registry.

### `FidelityProfile`

```python
class FidelityProfile
```

A named MATLAB variant, plus the switches that distinguish it.

### `PROFILES`

*(re-exported from elsewhere; not defined in this module)*

### `profile`

```python
def profile(name: str) -> FidelityProfile
```

Look a profile up by name, listing the alternatives on a miss.

### `register_profile`

```python
def register_profile(new: FidelityProfile, *, cites_tree: str='3.1.4') -> FidelityProfile
```

Add a fork's own variant to the registry, under its own ``name``.

``cites_tree`` says **which MATLAB tree the variant's file:line citations name**
-- ``"3.1.4"`` (the default) or ``"3.5"``. It is not inferable from the field
values, because ``stock-v3.5`` was built by measuring that every field holds
the same value as ``stock-v3.1.4``: the two are field-identical and only their
citations differ. A variant registered ``cites_tree="3.5"`` becomes usable
under ``--engine 3.5`` (see `is_v35_flavoured`, which also re-checks the
behaviour fields, so declaring ``"3.5"`` over v3.1.4 behaviour is still
refused). **Defaulting to ``"3.1.4"`` fails closed**: a fork that says nothing
is refused by the v3.5 gate rather than admitted to it.

**Why this exists.**  UIOOPS is forked, edited and
re-forked -- that is how the field-campaign variant behind the archived products came
to exist -- so a group running their own tree needs to be able to say *my
fork differs here* without editing this package. Every field of a
`FidelityProfile` is required by the dataclass, so a registration
states each divergence explicitly; there is no path here that fills one in.

**What this deliberately does not open.**  A profile can be registered from
Python, where the caller constructs the object and names every field, and
**never from a configuration file**: a ``FidelityProfile`` field *is* a
threshold, and the configuration rule is that a config file selects
between documented behaviours and never sets one. ``arrayprobe.config``
will happily select a registered profile by name once it exists; it still
refuses to describe one.

A registration may not take a name already in use, shipped or registered:
``.call`` sidecars, logs and error messages record the *name*, so a name has
to keep meaning one variant. Raises `ValueError` if it does.

### `is_v35_flavoured`

```python
def is_v35_flavoured(candidate: FidelityProfile) -> bool
```

True when ``candidate`` may be used under ``--engine 3.5``.

Two conditions, both required, and the first is the one that carries the
weight:

1. The profile **declares** that its citations are to the v3.5 tree -- it is
   one of the shipped v3.5 profiles, or a fork registered it with
   ``register_profile(p, cites_tree="v3.5")``. Not inferable from the field
   values; see `_V35_TREE_PROFILES`.
2. Every field in `_BEHAVIOUR_FIELDS` equals `STOCK_V35`'s.
   ``reject_thresholds`` is deliberately excluded -- it is the one thing the
   v3.5 engine reads from a profile and the one axis a caller is entitled to
   vary. This second check catches a fork that declares ``v3.5`` while
   describing v3.1.4 behaviour.

**Fails closed in both directions.** An undeclared profile is refused however
its fields read, and a declared one is still refused if its behaviour
contradicts the declaration. A new field added to `FidelityProfile` and
not listed in `_BEHAVIOUR_FIELDS` makes this *stricter*, never laxer.

### `register_stock_v35_image_assisted`

```python
def register_stock_v35_image_assisted() -> FidelityProfile
```

Build, register and return ``stock-v3.5-image-assisted``.

**What it is.** `STOCK_V35` with exactly one field moved:
``reject_thresholds`` becomes
`arrayprobe_uiops.measure.IMAGE_ASSISTED_V35_REJECT_CONFIG` --
``rej_hollow`` off, ``max_edge_img_ar`` and ``max_comp_img_ar`` left at
stock's 6 and 5. See that constant's own docstring for the full
evidence (200 triage labels) and its honest caveat (this
configuration is not optimal at 55-105 um, where the hollow test it turns
off was correct 25/25). Built the same way as
`_build_oracles_production_v35` -- ``dataclasses.replace`` off
``STOCK_V35``, so every non-threshold field is provably identical to it and
`is_v35_flavoured` admits it without re-deriving anything.

**Why registered rather than shipped as a fourth module-level constant
like ``STOCK_V35``/``ORACLES_PRODUCTION_V35``.** Two existing tests pin the
module's *shipped, ``dir()``-visible* surface to exactly its current
members: ``tests/test_profile_registry.py
```
```
test_the_shipped_set_does_not_grow_with_registrations`` pins `SHIPPED`
to five names, and ``tests/test_cli_engine_selection.py
```
```
test_the_second_reason_names_the_v35_profiles_that_exist`` enumerates every
uppercase ``dir(profiles)`` name whose value is a `FidelityProfile`
and pins that list to ``["ORACLES_PRODUCTION_V35", "STOCK_V35"]`` --
the second test's own docstring says outright that "the next one
registered fails this again and the prose has to catch up" (``cli.py``'s
refusal message). This profile is deliberately reached the same way a
fork's own variant is -- ``profiles.PROFILES["stock-v3.5-image-assisted"]``
or ``profiles.profile(...)``, never ``profiles.STOCK_V35_IMAGE_ASSISTED`` --
which is also the more accurate description: the project's one-package-per-upstream rule already
settles this as an opt-in configuration selected per run, not a new shipped
default, and per that same decision it adds no package.

Calls `register_profile` with ``cites_tree="3.5"``, so
`is_v35_flavoured` -- and therefore the ``--engine 3.5`` gate in
``scripts/run_flight.py`` -- admits it exactly as it would a fork's own
declared variant. Idempotent and cached like `_build_stock_v35`: safe
to call from every entry point that needs the name resolvable
(``scripts/run_flight.py``-style CLI lookups, the CIP lane scripts under
``_decoded/cip160906/``) without risking ``register_profile``'s
already-registered ``ValueError`` on a second call.

## `arrayprobe_uiops.jit_kernels`

S3's opt-in accelerated kernels for the v3.5 engine --

### `V35JitKernels`

```python
class V35JitKernels
```

Wraps `arrayprobe.jit_kernels`'s already-compiled, already-proven
kernels for the two v3.5 call sites that use the identical underlying
function (``particle_perimeter``, ``dec2bin_concat``), plus this
module's own compiled kernels for ``calculate_reject_unified``'s two hot
loops, which have no earlier kernel to reuse -- v3.5's ``arrayprobe_uiops.reject`` is a
from-scratch translation of a changed MATLAB function (see its module
docstring), not the file the earlier translation accelerates.

### `load`

```python
def load() -> V35JitKernels
```

Import numba (via `arrayprobe.jit_kernels`) and compile this
module's own kernels, once per process. Raises with a v3.5-specific
message if numba is absent; the default (``jit=False``) path -- for
``imgproc_sm_v35``, ``calculate_reject_unified`` and ``is_it_hollow``
alike -- never calls this.

## `arrayprobe_uiops.stray_pixel`

Stray-pixel correction for one particle image (library default off,

*No public API declared (`__all__` empty or absent).*

## `arrayprobe_uiops.ncar_2dc_timing`

NCAR-recorded PMS 2DC timing/sync words, converted to the 0x55 form before framing.

### `STAMP_OFF`

```python
STAMP_OFF: str
```

### `STAMP_ON`

```python
STAMP_ON: str
```

### `convert_record`

```python
def convert_record(data: np.ndarray) -> tuple[np.ndarray, int]
```

``data`` with every NCAR sync/timing slice's first byte set to 0x55
(``fix2dimage.pro:23-26``: ``(w or FF000000) xor AA000000`` changes only the top byte, to
``FF xor AA = 55``), and the number of sync words converted. The input is not modified; a
record the gate passes over is returned as the same object.

### `ncar_word_slices`

```python
def ncar_word_slices(data: np.ndarray) -> np.ndarray
```

0-based indices of the NCAR sync slices (``fix2dimage.pro:20``'s ``timelines``) in
``data``; empty when the record already carries 0x55 syncs (gate) or ``fix2dimage.pro``
finds none. `convert_record` rewrites these and the slice before each.

## `arrayprobe_uiops.qc`

v3.5 ``imgProc_sm.m:801-846`` -- the ``iQC=1``

### `qc_image`

```python
def qc_image(c: np.ndarray) -> tuple[np.ndarray, int, int]
```

``imgProc_sm.m:801-846``. Returns ``(c_after, num_subparticles, dist_min)``.

``c`` is the ``(n_slices, diodenum)`` particle image in any form
`arrayprobe.particle.shadow_mask` accepts (the same convention
``measure_record`` uses downstream). ``c_after`` is returned in that same
canonical form on both branches -- the vendored file's own ``char('1' -
c_logical)`` rebuild (``:844``) is reproduced literally as a ``'0'``/``'1'``
ASCII array so a caller inspecting ``c_after``'s dtype sees the same
convention as the input, not a silently-widened boolean.

## `arrayprobe_uiops.sizedist`

v3.5's ``sizeDist.m`` DRIVER: the record/second loop, the

### `TasMaxUndefined`

```python
class TasMaxUndefined(NameError)
```

``tasMax`` read where the case never assigns it (2DP), as MATLAB dies there.

### `run`

```python
def run(infile, outfile, tas, timehhmmss, probename, d_choice, sa_method, pres, temp, ia_thresh_type, i_create_aspect_ratio, i_create_bad, i_save_int_arr_sv, projectname, ddate, *varargin, software, probe_case=None, mmethod=0, mmethod_pow=0.0, area_ratio_z=None, default_int_arr_thresh=None, pecan_params=None, tas_max=None, octave_mean_extra=False, octave_colon=False, creation_time=None, progress=None, stamp_profile=None, tas_qc=None, time_offset_s=None, time_offset_evidence=None, time_offset_tas_clock=None, zero_sv_nan=False)
```

``sizeDist(infile, outfile, tas, timehhmmss, probename, d_choice,
SAmethod, Pres, Temp, iaThreshType, iCreateAspectRatio, iCreateBad,
iSaveIntArrSV, projectname, ddate, varargin)`` -- v3.5's own positional
signature (unchanged from v3.1.4 stock; see the module docstring).

``mmethod``/``mmethod_pow`` are NOT part of stock v3.5's signature -- they
port Peter Brechner's ``Mmethod`` argument to his forked
``sizeDist_decibel3.m`` (``:1186-1211``), an opt-in flag defaulting to 0,
stock v3.5's own habit M-D and textually the same code path this function
always ran before ``mmethod`` existed --
``tests/test_held_back_modules_refuse_cleanly.py`` asserts the default never
reaches ``mass_b26``.
``mmethod`` 1, 2 or 3 reaches ``arrayprobe_uiops.mass_b26``, which this
release does not include because the method is not yet published. The
import is lazy and guarded: with the module absent, ``mmethod`` 1-3
refuses by name, so only ``mmethod=0`` runs.

``software`` is required, no default -- v3.5 reads it from a
``version.txt`` beside the MATLAB source at runtime (``:2033-2035``,
"Added dynamic software version to netCDF metadata"), the same cwd-relative,
unchecked-``fopen`` pattern already found and named an upstream finding for
``read_binary_SPEC.m`` and ``imgProc_sm.m``.  Reproducing the
cwd-dependence itself would make this port's OUTPUT depend on where Python
was started; naming the string explicitly instead makes the same fact
recordable rather than accidental, the same choice ``arrayprobe_uiops.spec``
already made for its own ``software``/``creation_time`` arguments.

``tas_qc`` is the airspeed data-quality record
(`arrayprobe.tools.tas_sources.qc_record`), not a MATLAB argument: each key is
written as an ``arrayprobe_<key>`` global attribute beside the engine attributes, so the
file itself says which seconds were sized with a substituted or default TAS.
``None`` writes nothing; no variable changes either way.

``area_ratio_z`` is NOT part of stock v3.5's signature either. ``None`` (default)
keeps ``sizeDist.m:1162``'s literal ``.2`` through `AREA_RATIO_Z`, so the path is
textually the one that always ran (``tests/test_v35_area_ratio_z.py
```
```
TestDefaultIsBitIdentical``). A value in ``[0, 1]`` replaces only that literal: a particle
whose clipped area ratio is below it is rejected as ``'z'``. ``0.0`` is the gate off (an
area ratio is ``area / (pi/4 d^2)`` with ``area >= 0``, so never below 0, and NaN compares
false; asserted against the Octave oracle, not assumed). Anything else raises. The
oracle is named: the vendored ``sizeDist.m`` with that one literal changed in a
shadowing copy (the Octave bank ``run_v35_area_ratio_z_bank.py``, dev repository only,
``tests/test_v35_area_ratio_z_oracle.py``). A run that sets it writes one global
attribute, ``arrayprobe_area_ratio_z``; a run that does not writes nothing new.

``default_int_arr_thresh`` is NOT part of stock v3.5's signature either. ``None``
(default) keeps the case's own ``defaultIntArrThresh = <literal>`` assignment
(``sizeDist.m:139-642``, e.g. ``:313`` for SOCRATES/2DS), so the path is textually the
one that always ran. A finite value ``>= 0`` (seconds) replaces only that constant in
the resolved ``ProbeDefaults``, after the switch or probe-case lookup. v3.5 reads
``defaultIntArrThresh`` in exactly one place: ``intar_threshold =
ones(size(tas_time))*defaultIntArrThresh`` (e.g. ``:318``), which is read only by the
``iaThreshType == 2 && applyIntArrThresh`` block (``:1308-1338``). So the value is
unused when ``iaThreshType`` is not 2, when the case sets ``applyIntArrThresh = 0``,
and it does not rescue a case that never assigns ``intar_threshold`` (GPM/2DS,
IMPACTS/2DS: still refused at the read site, as MATLAB dies there). A run that sets it
writes the attribute ``arrayprobe_default_int_arr_thresh`` whether or not the gate used it;
one that does not writes nothing new. Octave oracle: ``run_v35_default_int_arr_thresh_bank.py``.

``pecan_params`` is NOT part of stock v3.5's signature either. The PECAN CIP and PIP
cases call ``getPECANparams`` (``:164``, ``:195``), which ships in no release, so without
it the run is refused as MATLAB dies there. A path to a parameter file (or a
`~arrayprobe_uiops.pecan_params.PecanParams`) supplies the call's three used outputs,
and the case then runs exactly as MATLAB would with them: ``intar_threshold`` is the
case's ``defaultIntArrThresh`` every second except inside a spiral, read only under
``iaThreshType == 2``. Refused on any other case. Format: ``pecan_params.py``.

``tas_max`` is NOT part of stock v3.5's signature either. The 2DP case (``:595-617``)
assigns no ``tasMax``, which ``:771``, ``:1026-1088``, ``:1144`` and ``:1926`` read, so
without it the run is refused as MATLAB dies there (`TasMaxUndefined`). A finite
value ``> 0`` (m/s) is used as that case's ``tasMax``; there is no default. Refused on a
case that assigns its own ``tasMax``. Neither keyword writes anything when unset.

``time_offset_s`` is NOT part of stock v3.5's signature either: a whole number of seconds
ADDED to every particle's ``Time``/``particle_time`` where it is read, for a probe whose own
clock is measured off aircraft time (`TimeOffset`). It needs
``time_offset_evidence`` (how it was measured) and ``time_offset_tas_clock``: ``"probe"``
when ``timehhmmss``/``tas`` came from the probe's own record (same off clock: shifted too),
``"aircraft"`` when they came from an aircraft file (already aircraft time: left alone).
Inter-arrival times are differences of ``Time_in_seconds`` and do not move. ``None``
(default) leaves the path textually the one that always ran; a run that sets it writes
``arrayprobe_time_offset_s``, ``arrayprobe_time_offset_evidence`` and
``arrayprobe_time_offset_tas_clock``.

Probetypes 0-3 are supported -- see the module docstring's "Scope".
Everything else this function refuses is refused explicitly, as an error
naming the source line, never a silent fallback.

### `UnsupportedProbetype`

```python
class UnsupportedProbetype(NotImplementedError)
```

Raised for a (campaign, probe) resolving to a probetype outside 0-3.

No v3.5 probetype is refused here: probetypes 0-3 are all ported (probetype 1
is CIP/PIP). The class remains for a
table row that names a probetype no stock release defines.

This docstring must track the module docstring's "Scope" section: it is the
half a reader meets first -- it is what an exception class is *for*. A version
that lagged the probetype-1 port by a day was copied onto two shared artifact
pages, which told readers that v3.5 stage 4 refuses probetypes
0, 1 and 3 -- denying the engine capability the entire CIP result rests on.
It was caught by the artifact refresh, not by any test: no check compares a
docstring against the code it describes.

### `resolve_probe_case`

*(re-exported from elsewhere; not defined in this module)*

### `resolve_shipped_probe_case`

*(re-exported from elsewhere; not defined in this module)*

### `register_v35_2ds_ladder_fix`

*(re-exported from elsewhere; not defined in this module)*

### `UnknownProbeCase`

*(re-exported from elsewhere; not defined in this module)*

### `REQUIRED_IA_THRESH_TYPE`

*(re-exported from elsewhere; not defined in this module)*

### `ACCEPTED_IA_THRESH_TYPES`

*(re-exported from elsewhere; not defined in this module)*

### `AREA_RATIO_Z`

```python
AREA_RATIO_Z: object
```

### `AREA_RATIO_UPPER_CLIP`

```python
AREA_RATIO_UPPER_CLIP: float
```

### `OVERLOAD_WARN_SEC`

```python
OVERLOAD_WARN_SEC: float
```

### `OVERLOAD_CAP_SEC`

```python
OVERLOAD_CAP_SEC: float
```

### `fix_multiday_particle_times`

```python
def fix_multiday_particle_times(image_time_hhmmssall: np.ndarray) -> tuple[np.ndarray, bool]
```

v3.5's replacement for the ``image_time_hhmmssall`` midnight rollover.

v3.1.4 (``:652-654``, reused here for ``timehhmmss`` itself via
`arrayprobe_uiops.sizedist_core._rollover_240000` -- **unchanged in v3.5**, see
the module docstring) corrects a midnight crossing with
``x(find(diff(x)<0)+1:end) += 240000``, which MATLAB's first-element colon
rule collapses to only the FIRST decrease.  v3.5's own authors worked
around exactly that trap for the *particle*-time array by branching on
``numel(find(...))`` explicitly, rather than by fixing the colon idiom:

* **Zero decreases**: no-op, unchanged.
* **Exactly one decrease**: apply the same ``+240000`` shift v3.1.4 always
  applied -- identical result to the old code for this case.
* **More than one decrease**: scan the decreases in order for a genuine
  day crossover -- ``x[d] > 230000 and x[d] - x[d+1] > 230000`` -- and
  shift everything after the FIRST one found, then stop.  If none of the
  decreases looks like a real crossover (all of them look like corrupt,
  briefly-reversed particle times instead), the array is returned
  **unmodified** and a message is printed; see the v3.5 ``sizeDist`` driver design
  record for why this is a real, if narrow, gap.

Returns ``(fixed_array, crossover_applied)``.  Mutates a **copy**, unlike
`arrayprobe_uiops.sizedist_core._rollover_240000`, which mutates in place --
the v3.5 source assigns back to the same name either way, so an in-place
mutation would be equally faithful; a copy is used here so a caller
cannot be surprised by an aliased array from an earlier stage.

### `apply_flight_day_carryover`

```python
def apply_flight_day_carryover(image_time_hhmmssall: np.ndarray, timehhmmss: np.ndarray) -> np.ndarray
```

v3.5 ``sizeDist.m:806-810``: *"Fix particle times if they do not span
multiple days but the flight file does - Added by Joe Finlon - 02/09/18"*.

When any flight time exceeds 240000 but no particle time does, every
particle time is shifted by +240000 (v3.1.4 ``sizeDist.m:662-663``).

A THIRD, independent particle-time correction, not caught when this
module's `fix_multiday_particle_times` was first written from this
file's own diff/read summary -- found only by reading the source lines
immediately after it (``:786-805``) through to ``:829`` (the block-start
predicate) and noticing the ``if`` at ``:807`` does not belong to either
branch above it. It runs unconditionally after
`fix_multiday_particle_times`, regardless of what that function did:
if the per-second ``timehhmmss`` (already midnight-corrected by
`arrayprobe_uiops.sizedist_core._rollover_240000`, called before this) crossed
into the next day but the particle-time array's own ``diff`` never showed
a decrease at all -- possible when the particle stream itself starts
exactly at, or resumes after, the crossing with no reversal to detect --
then every particle time is shifted by ``+240000`` unconditionally, with
no idiom bug of its own (``numel(find(...))`` counts are scalars here,
not vectors sliced with the first-element colon rule the other two
corrections in this module inherit or avoid).

**Correction, made while writing this module's tests**: this block is
**byte-identical in v3.1.4** (``UIOPS-v3.1.4/.../sizeDist.m:661-664``,
same three lines, same comment) -- it is not new to v3.5 at all, unlike
`fix_multiday_particle_times`'s own genuine v3.5 improvement (the
``numel(find(...))`` branching). What IS new here is narrower than first
written: **the earlier translation never implemented it** -- it
reused ``_rollover_240000`` for ``image_time_hhmmssall`` (its own
``:927``) but had no code for this second, independent ``if``. That is
a gap in the earlier translation, not a v3.5 finding, and this function
is kept as v3.5's own copy of the same three lines rather than left
unported a second time.

### `resolve_particle_blocks`

```python
def resolve_particle_blocks(image_time_hhmmssall: np.ndarray, num_of_part: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]
```

v3.5's replacement for the ``start_all``/``count_all`` resolution.

v3.1.4 finds one-second block starts in file order, sorts them by time,
de-duplicates by first-occurrence, and only THEN computes ``count_all``
as ``diff(start_all)`` on the final, sorted array -- valid only if the
sort left ``start_all`` monotonic, which a corrupted/out-of-order
particle-time series need not.  A negative count from a non-monotonic
``diff`` is clamped to 1, silently under-counting the block.

v3.5 (02/13/19) computes ``count_all`` ONCE, in original file order
(where ``start_all`` is inherently increasing, since it comes from
``find`` on a monotonically-scanned buffer), and carries that same
``count_all`` through every later sort/filter/dedupe step by index --
never recomputing it from a ``diff`` that could go negative.  It also:

* widens the block-start predicate from ``diff(...)>0`` to
  ``diff(...)~=0``, so a DECREASE (as well as an increase) in particle
  time starts a new block -- corrupt/out-of-order particle times are,
  unlike v3.1.4, not silently absorbed into the previous block;
* inserts a corrupt-time-removal pass, active only when the
  chronologically-first block is not also the file-order-first block
  (``newindexofsort(1) ~= 1``): it keeps a sorted-order position only
  when the NEXT position in sorted order is exactly one more in file
  order (``newindexofsort(k+1) - newindexofsort(k) == 1``), i.e. only
  where sorting by time reproduces a genuinely contiguous run of file
  order -- dropping isolated, out-of-place blocks a real day crossing or
  clock glitch can produce.

Returns ``(starttime, start_all, count_all)`` -- ``start_all`` 0-based,
ready to index the proc file exactly as `resolve_particle_blocks`'s
caller does.

### `overload_dead_time`

```python
def overload_dead_time(int_arr: np.ndarray, dof_overload: np.ndarray, probetype: int=2) -> float
```

v3.1.4 ``:813`` / v3.5 ``:1116-1126``, the ``else`` arm's ``time_interval72``.

v3.1.4 computed the same sum and silently reset it to 0 whenever it
exceeded 1 second ("EXPERIMENTAL correction... Joe Finlon 02/09/18").
v3.5 instead warns above 0.8 s and only caps (to 1.0, not 0.0) above
1.0 s -- real overload time under 1 s reaches the file where v3.1.4
discarded it whenever the sum passed 1 s at all.

**The warn-and-cap is gated ``probetype==2`` at v3.5 ``:1118``**, inside an
``else`` arm that probetypes 1 AND 2 both reach (``:1111``'s ``if`` takes
probetypes 0 and 3 down the ``rec_start`` path instead).  So a probetype-1
(CIP/PIP) run takes the bare ``sum(int_arr(DMT_DOF_SPEC_OVERLOAD~=0))`` of
``:1116`` with **no warning and no cap** -- a probetype-1 second whose
overload sum exceeds 1 s writes that value through, where the same sum on a
2D-S is clamped to 1.  Ported as a gate, not "fixed" to apply everywhere.
``probetype`` defaults to 2 so existing probetype-2 call sites are
unchanged.

### `d_choice_diameter`

```python
def d_choice_diameter(d_choice, im_length, im_width, diodesize, minr)
```

v3.5 ``sizeDist.m:1054-1066`` (stock v3.1.4 ``:876-890``).

**What v3.5 changed.** v3.5 adds ``im_width = double(netcdf.getVar(...))`` /
``im_length = double(...)`` (``:941-942``) immediately before this
computation; stock keeps them the file's native ``int16`` and multiplies
in place -- a bug the earlier translation preserves (upstream finding: the int16 diameter
saturation): ``int16 x double``
saturation collapses ``particle_diameter_minR`` toward zero for
``d_choice`` 1, 2, 3 and 5). Casting to double first removes the integer
dominance that causes it, so **the saturation does not reproduce under v3.5**.

Implemented as exactly that precondition and nothing else:
`arrayprobe.matlab_compat.mmul`/``mpow``/``mmax`` already dispatch
on the *actual* dtype of their arguments -- integer-dominant only when an
operand really is an integer array -- so calling
the earlier translation's own ``_d_length`` &c. on ``float64`` inputs
reuses that arithmetic correctly with no new saturating-arithmetic code
of its own. ``d_choice == 6`` (the default) is unaffected either way: it
reads ``image_diam_minR`` straight from the file, untouched by the cast.

### `area_r_diameter`

```python
def area_r_diameter(image_diam_areaR: np.ndarray) -> np.ndarray
```

v3.5 ``sizeDist.m:954-956`` vs. stock v3.1.4 ``:783``.

**What v3.5 changed.** Stock v3.1.4 reads ``particle_diameter_AreaR`` from the
file and multiplies it by ``diodesize`` a SECOND time -- a bug the earlier
translation preserves (upstream finding: the double-scaled area-ratio
concentration; ``:669`` in the line numbering of the production-configuration variant of
``sizeDist.m``, not shipped): ``imgProc_sm.m`` already writes it scaled, so the second
scaling is a 100x-too-small double-scale for a 2D-S, and the consequence
is total (``conc_AreaR`` identically zero wherever finite).
v3.5 comments the multiply out (``%particle_diameter_AreaR
= particle_diameter_AreaR * diodesize; % Removed/ not needed (see
imgProc_sm variable reference) ~ Joe Finlon 3/4/19``) -- an independent
upstream fix of the exact defect this project documents, the same shape
as the habit-'C' case. **The double scaling does
not reproduce under v3.5.** This function is the identity: there is no
MATLAB operation left here to transcribe.

### `clip_area_ratio`

```python
def clip_area_ratio(area_ratio: np.ndarray) -> np.ndarray
```

v3.5 ``sizeDist.m:1161`` -- ``area_ratio(area_ratio > 1.) = 1.;``,
"Added by Joe Finlon 03/19/23". Absent from stock v3.1.4, which lets
``area_ratio`` exceed 1 (a geometrically impossible value the ``.2``
reject test never filters, since it only rejects *small* ratios). Runs
immediately before that reject test; this function is only the clip,
using `AREA_RATIO_UPPER_CLIP`.

### `apply_shattering`

```python
def apply_shattering(*, ia_thresh_type: int, cfg: ProbeDefaults, spec: InterarrivalThresholdSpec, i: int, auto_reject: np.ndarray, int_arr: np.ndarray, int_arr2: np.ndarray | None, int_arr3: np.ndarray | None, particle_diameter_minR: np.ndarray, start: int, count: int, intar_threshold: np.ndarray | None=None) -> np.ndarray
```

Dispatch to whichever of the THREE reacceptance loops this second's
``ia_thresh_type`` selects, mutating and returning ``auto_reject``.

**This function IS the trap the brief calls "the most important thing in
this brief," made explicit as code.**  v3.5's ``sizeDist.m`` carries three
structurally similar shattering blocks that do NOT all behave the same:

* ``ia_thresh_type == 1`` (``:1213``) and ``== 2`` (``:1346``) both scan
  a colon range from ``find(rBegin)`` to ``find(rEnd)`` -- MATLAB's first-element colon
  rule collapses this to the FIRST shattering event only, the same
  preserved defect documented at v3.1.4 ``sizeDist.m:1036``,
  ``:1169``.  **Reused verbatim** via
  `arrayprobe_uiops.sizedist_core._reaccept_shattered` -- not re-transcribed,
  since the block is byte-for-byte the same idiom v3.1.4 already has and
  already tests.  Regression tests:
  ``TestThreeLoopsTwoBehaviours::test_type1_and_type2_use_the_v314_preserved_bug_reaccept_shattered``.
* ``ia_thresh_type == 3`` (``:1416-1419``, "JF 11/5/25") is NEW in v3.5
  and was deliberately rewritten to scan
  from the first ``rBegin`` index to the last ``rEnd`` index
  (v3.5 ``sizeDist.m:1419``) -- one continuous bracket spanning
  EVERY shattering event in the second, not just the first.  Uses
  `~.sizedist_tables.reaccept_shattered_1hz`, which
  implements exactly this bracketed scan.  Regression test:
  ``TestThreeLoopsTwoBehaviours::test_type3_uses_the_fixed_bracketed_reaccept``.
* ``TestThreeLoopsTwoBehaviours::test_the_two_conventions_differ_on_the_same_second``
  asserts, on one synthetic second carrying two separate shattering
  events, that dispatching it through type 1/2 reaccepts nothing from the
  second event while dispatching the SAME data through type 3 does --
  the two conventions provably differing within the same file, as the
  brief requires.

### `WRITER_GAPS`

```python
WRITER_GAPS: dict
```

## `arrayprobe_uiops.sizedist_tables`

The self-contained pieces of v3.5's ``sizeDist.m``.

### `BinLadder`

```python
class BinLadder
```

``kk = diodesize/2:diodesize:(num_bins+0.6)*diodesize`` -- a colon-built ladder.

Source: the ``switch projectname`` block of ``sizeDist.m:139-642`` (UIOOPS v3.5; v3.1.4
``:107-511``).

Built with `arrayprobe.constants._colon`, which knows that MATLAB
fills a colon range from both ends and Octave does not (they differ by one
ULP in the upper half).  ``octave_colon=True`` exists only so the Octave
fixture can be compared bit-for-bit; the port targets MATLAB.

### `BinLiteral`

```python
class BinLiteral
```

``kk = [microns ...] * times / 1000`` -- a literal table, in the source's
own operation order (``*8`` then ``/1000`` for 2DP; ``/1000`` alone otherwise).

Source: the ``switch projectname`` block of ``sizeDist.m:139-642`` (UIOOPS v3.5; v3.1.4
``:107-511``).

### `ProbeDefaults`

```python
class ProbeDefaults
```

Everything one ``case`` of the inner ``switch probename`` assigns.

Source: the ``switch projectname`` block of ``sizeDist.m:139-642`` (UIOOPS v3.5; v3.1.4
``:107-511``).

``tasMax`` is ``None`` for 2DP, which assigns none in either release (the
earlier translation already ships that crash).  ``intar_threshold_defaulted`` records
whether the case runs ``intar_threshold = ones(size(tas_time))*defaultIntArrThresh``;
``calls_getPECANparams`` records the PECAN cases' call to a function that
exists in **neither** vendored tree (measured: both releases error there).

### `UndefinedProbeCase`

```python
class UndefinedProbeCase(LookupError)
```

The inner ``switch probename`` has no ``otherwise``: an unlisted probe
leaves ``num_bins``/``kk`` (and everything else) unassigned, and the driver
fails later on the first use.  The port refuses up front rather than invent
a table.

Source: the ``switch projectname`` block of ``sizeDist.m:139-642`` (UIOOPS v3.5; v3.1.4
``:107-511``).

### `V314_TABLES`

*(re-exported from elsewhere; not defined in this module)*

### `V35_TABLES`

*(re-exported from elsewhere; not defined in this module)*

### `V35_CAMPAIGNS`

```python
V35_CAMPAIGNS: tuple
```

### `V314_CAMPAIGNS`

```python
V314_CAMPAIGNS: tuple
```

### `probe_defaults`

```python
def probe_defaults(projectname: str, probename: str, *, version: str='3.5') -> ProbeDefaults
```

Resolve ``(projectname, probename)`` exactly as the ``switch`` does.

Source: the ``switch projectname`` block of ``sizeDist.m:139-642`` (UIOOPS v3.5; v3.1.4
``:107-511``).

An unlisted campaign takes the ``otherwise`` branch; an unlisted probe
*within* a branch raises `UndefinedProbeCase` (the inner switch has
no ``otherwise``).  Case-sensitive, as MATLAB's ``switch`` on strings is.

### `diff_tables`

```python
def diff_tables(campaigns: Sequence[str]=('PECAN', 'GPM', 'SOCRATES', 'IMPACTS', 'ORACLES')) -> list[TableDiff]
```

The complete v3.1.4 -> v3.5 diff over ``campaigns`` x every probe either
release names.  ``ORACLES`` (or any unlisted name) exercises ``otherwise``.

### `InterarrivalThresholdSpec`

```python
class InterarrivalThresholdSpec
```

What v3.5 ``sizeDist.m:98-110`` leaves behind.

``ia_thresh_file`` is ``None`` where MATLAB leaves ``iaThreshFile``
**unassigned** -- one argument with ``iaThreshType`` 0 or 2 (v3.1.4 assigned
``varargin{1}`` unconditionally; v3.5's inner ``if/elseif`` has no ``else``).
Latent in v3.5 because the only later read, ``:1179``, is short-circuited
behind ``iaThreshType == 1``.  ``iat_thresh`` is the per-second array, set
only for type 3 with exactly one argument.

### `select_interarrival_threshold`

```python
def select_interarrival_threshold(ia_thresh_type: int, varargin: Sequence[object]) -> InterarrivalThresholdSpec
```

v3.5 ``sizeDist.m:98-110``, as a pure function of the call's inputs.

### `flag_shattered_1hz`

```python
def flag_shattered_1hz(int_arr: Sequence[float], thresh: float, auto_reject: Sequence[str] | None=None) -> np.ndarray
```

v3.5 ``sizeDist.m:1384-1396``: the type-3 shatter flagging for one second.

``thresh`` is ``iatThresh(i)`` for that second.  A particle at or below the
threshold is ``'S'``, and so is the one immediately before it (``(ix-1):ix``).
Returns the per-particle reject codes (1-D ``<U1`` array).

### `reaccept_shattered_1hz`

```python
def reaccept_shattered_1hz(auto_reject: Sequence[str], int_arr: Sequence[float], int_arr3: Sequence[float], particle_diameter_minR: Sequence[float], thresh: float, *, reaccptD: float, reaccptMaxIA: float) -> tuple[np.ndarray, int | None]
```

v3.5 ``sizeDist.m:1398-1428``: the type-3 block's reacceptance.

**This is not the v3.1.4 reacceptance**, nor v3.5's own type-1/type-2 one.
Those iterate ``find(rBegin):find(rEnd)`` -- which, through MATLAB's
first-element colon rule, scans only the first shattering event (a preserved
v3.1.4 bug).  v3.5 rewrites the type-3 block ("JF 11/5/25")
to scan ``find(rBegin,1,'first'):find(rEnd,1,'last')``, one continuous range
spanning every event.  Returns ``(auto_reject, eIndex)`` with ``eIndex`` the
1-based index reaccepted, or ``None`` (MATLAB's ``[]``).

### `HABIT_ATTR_OLD`

```python
HABIT_ATTR_OLD: str
```

### `HABIT_ATTR_NEW`

```python
HABIT_ATTR_NEW: str
```

### `HABIT_SCHEME_SENTINEL_VARIABLE`

```python
HABIT_SCHEME_SENTINEL_VARIABLE: str
```

### `detect_habit_scheme`

```python
def detect_habit_scheme(variable_names: Sequence[str]) -> tuple[int, str]
```

v3.5 ``sizeDist.m:117-123``: ``(iNewHabit, attr_habit)`` from the input
file's variable list.  Exact, case-sensitive membership, as ``ismember`` on
a cellstr is.

## `arrayprobe_uiops.pecan_params`

A user-supplied stand-in for ``getPECANparams`` -- opt-in, required for PECAN, no default.

### `PecanParams`

```python
class PecanParams
```

The three ``getPECANparams`` outputs ``sizeDist.m`` reads, one entry per spiral.

### `load_pecan_params`

```python
def load_pecan_params(path: str | PathLike[str], *, ddate: Any=None, probename: str | None=None) -> PecanParams
```

Read the CSV described in the module docstring, filtered to ``ddate``/``probename``
where the file carries ``date``/``probe`` columns.

### `pecan_intar_threshold`

```python
def pecan_intar_threshold(tas_time: Any, params: PecanParams, default_int_arr_thresh: float) -> np.ndarray
```

``intar_threshold`` exactly as ``sizeDist.m``'s PECAN loop builds it: the default every
second, then each spiral in file order overwriting the seconds in ``[startT, endT)``, so
where spirals overlap the later one wins, as the inner loop's last assignment does.

### `resolve_pecan_params`

```python
def resolve_pecan_params(value: Any, *, ddate: Any, probename: str | None) -> PecanParams
```

A `PecanParams` from a path or an existing record.

## `arrayprobe_uiops.reject`

``calculate_reject_unified.m`` (UIOOPS v3.5) -- reject-code logic, CHANGED

### `ZeroSlicesUnassignedOutputs`

```python
class ZeroSlicesUnassignedOutputs(RuntimeError)
```

The real MATLAB leaves ``center_in`` unassigned for a zero-slice image
(measured: Octave errors "undefined in return list" on this path) --
raised to match that refusal rather than inventing a value, the same
rule already applied for ``holroyd_new``/``holroyd_new_HVPS``.

### `RejectResultV35`

```python
class RejectResultV35
```

The result of `calculate_reject_unified`. Adds ``center_in`` to
the earlier translation's ``RejectResult`` fields; ``handles``
is not a return value in v3.5 (its two fields are direct outputs
instead), so this dataclass has no ``handles`` analogue.

Source: the output list of ``calculate_reject_unified.m:1`` (UIOOPS v3.5).

### `is_it_hollow`

```python
def is_it_hollow(shadow: Any, slices: int, jit: bool=False) -> Any
```

``calculate_reject_unified.m``'s v3.5 ``is_it_hollow`` -- CHANGED from
the earlier translation's ``is_it_hollow``: no
middle-third restriction on the diameter scan, and the row-overlap test
is a direct elementwise ``bitand`` on the character rows rather than a
``bin2dec``/``bitshift`` reconstruction. See this module's docstring for
the array-truthiness defect preserved in the coverage test below.

The real MATLAB derives its own row width from ``size(image_buf)``
rather than taking it as an argument (``im_width = size(image_buf)``,
used only for ``mask_start_end``'s modulus) -- the caller passes the
*same* buffer transposed for the "side" scan, so the width genuinely
differs between the two calls this function receives, and a fixed
``bits_per_slice`` parameter (this port's first draft) breaks on the
transposed call with a shape mismatch. ``bits_per_slice`` here is
therefore read from ``shadow.shape[1]``, matching ``im_width(2))``.

``jit=True`` (opt-in, default off) dispatches to
`arrayprobe_uiops.jit_kernels.V35JitKernels.is_it_hollow`, a numba
compilation of the exact body below (same state machine, same
preserved ``bufandold.all()`` defect), fusing what would otherwise be
one Python-level ``scan_slice`` dispatch per slice
into one compiled call for the whole particle. Proven byte-identical to
this body by a JIT identity test; requires numba
(an optional extra), imported lazily only when ``jit=True`` is actually
requested.

### `calculate_reject_unified`

```python
def calculate_reject_unified(image_buffer: Any, habit: str, ihollow: int, config: Any, jit: bool=False) -> RejectResultV35
```

v3.5's ``calculate_reject_unified.m``. ``config`` is a
`arrayprobe_uiops.reject_core.RejectConfig` (the same dataclass the v3.1.4
port uses -- ``rej_zero_area``/``rej_split``/``rej_hollow``,
``shadowed_area``, ``max_edge_img_ar``, ``max_comp_img_ar`` are unchanged
fields in the v3.5 source's own ``handles.*`` defaults).

``jit=True`` (opt-in, default off;
``_decoded/cip160906/V35_REJECT_JIT.md``) fuses the per-slice scanning
loop below, and both `is_it_hollow` calls in the hollow branch,
into numba-compiled kernels (`arrayprobe_uiops.jit_kernels`) instead
of one Python-level ``scan_slice`` dispatch per
slice -- measured as this function's own dominant cost
(``_decoded/cip160906/V35_JIT.md``: 7.367 s cumulative over 3,085 real
CIP particles, 6.610 s of it inside ``scan_slice``). Writes the
identical `RejectResultV35` either way
(checked by a JIT identity test); numba is imported lazily,
only when ``jit=True`` is actually requested.

## `arrayprobe_uiops.lwc`

Liquid water content from a particle size distribution.

### `lwc_calc`

```python
def lwc_calc(conc: Iterable[Iterable[float]], bins: Iterable[float]) -> list[float]
```

Liquid water content (g/m^3) from concentration and bin diameters.

Direct port of lwc_calc.m.

conc: sequence of rows (one per time step), each a sequence of
      concentrations (cm^-3) per bin.
bins: sequence of bin (mid-point) diameters, in microns.

Returns a list of LWC values, one per row of `conc`.

Note: unlike single_vt.m, the original lwc_calc.m does NOT
override MATLAB's built-in `pi`, so it gets full double-precision
pi -- this port uses math.pi accordingly (not the 3.1415926
literal used elsewhere in the source).

## `arrayprobe_uiops.spec`

``read_binary_SPEC.m``'s record-walking driver (UIOOPS v3.5).

### `DIODE_VOLTAGE_SCALE`

```python
DIODE_VOLTAGE_SCALE: float
```

### `INITIAL_TAS`

```python
INITIAL_TAS: object
```

### `LATE_MARKER_FIRST_SKIPPED`

```python
LATE_MARKER_FIRST_SKIPPED: object
```

### `SCAN_LIMIT`

```python
SCAN_LIMIT: object
```

### `SHARED_WITH_V314`

```python
SHARED_WITH_V314: tuple
```

### `SeamRerunWarning`

```python
class SeamRerunWarning(RuntimeWarning)
```

A part of a parallel v3.5 decode started from an airspeed that did not
equal the previous part's final airspeed, and was decoded again from the
correct one. The output is unaffected; only time was lost. It means the
cheap housekeeping pass disagreed with the decoder, which is a defect in
that pass and worth reporting.

### `WRITER_GAPS`

```python
WRITER_GAPS: tuple
```

### `SidecarWriterV35`

```python
class SidecarWriterV35(SidecarWriter)
```

The v3.1.4 sidecar writer with v3.5's 15-column ``.tas.csv``.

Source: the appends of ``get_img`` in ``read_binary_SPEC.m:283-443`` (UIOOPS v3.5).

``.NV.csv`` and ``.MK.csv`` are untouched by the v3.5 diff and are inherited
unchanged, **including** the mask file's missing line terminators -- which
the Octave oracle of the SPEC reader re-measured against the v3.5 source
rather than inheriting on the strength of the diff not mentioning it.

Three things changed about ``.tas.csv`` and only one of them is visible in the
format string. The third is that ``tas`` is in the row, and its class
sets the row's: from the first accepted reading on it is a single, and
every ``%f`` column is printed at single precision (see `tas`). The
other two:

* six columns were appended (``:416``), the H and V end-diode voltages, each
  word times `DIODE_VOLTAGE_SCALE`; and
* **the second column stopped being the probe's reading.** v3.1.4 wrote the
  value it had just bit-cast out of the packet. v3.5 writes ``tas``, the
  value that survived the update gate (``:407-413``) -- so a record whose
  probe TAS was rejected as suspect is logged with the *previous* record's
  TAS, and the rejected reading is not recorded anywhere. Measured: the
  oracle's ``tasTemp = 170`` and ``nHOL = 1`` records both log ``50.0``,
  the last accepted value. Preserved, not corrected.

### `apply_time_offset`

```python
def apply_time_offset(header: RecordHeader, offset_seconds: float) -> RecordHeader
```

``:148-151`` -- shift one record's whole timestamp by ``timeOffset``.

Source: ``read_binary_SPEC.m:148-152`` (UIOOPS v3.5).

``wkday`` and ``millisec`` are **not** touched, because the MATLAB does not
touch them: it rebuilds only ``[year, month, day]`` from ``ymd`` and
``[hour, minute, second]`` from ``hms`` of a ``datetime`` constructed
*without* the milliseconds. A negative offset that crosses midnight
therefore leaves ``wkday`` naming the wrong day, and a fractional offset is
lost against a ``millisec`` field that stays where it was. Preserved.

**No Octave oracle** (doctrine layer 3): Octave 11.3.0's ``datatypes``
package has ``datetime`` but no ``plus`` for it (measured). This
is calendar arithmetic from documented semantics, pinned by tests.

### `get_img_v35`

```python
def get_img_v35(buf: Any, timehhmmss: Any, sidecar: Any=None, tas_prev: TasValue=INITIAL_TAS, *, fast: bool=True) -> Any
```

``read_binary_SPEC.m:283-442``. Returns ``(imgH, imgV, nNext, tas, tasPrev)``.

Two outputs more than v3.1.4's ``get_img``, and one fewer argument: there is
no ``FidelityProfile`` here, because **v3.5 has no profile axis for this
function**. ``spec_buffer_guard`` exists in the earlier translation to choose
between stock's 2017-03-08 bounds guards and the production variant tree that
predates them; v3.5 carries those guards unconditionally (``:322``,
``:326``, ``:333``, ``:356``, ``:360``, ``:367``), and the production variant
is a v3.1.4-era fork that was never rebased onto any later release
(see the two-engines note). There is nothing to select, so nothing is
offered; inventing a switch here would imply a v3.5 variant that does not
exist.

``buf`` is the **two-record** window (4096 words for a complete pair); only
``iii + 4 <= 2048`` is scanned. ``tas`` comes back as the value for this
record and ``tasPrev`` as the value the *next* record starts from; the
MATLAB writes ``tasPrev = tas`` only inside the accept branch, where the two
are equal by construction, so returning both is faithful rather than
redundant.

### `hk_readings_v35`

```python
def hk_readings_v35(buf: Any) -> list[tuple[TasValue, int, int]]
```

Every housekeeping reading `get_img_v35` would judge, in order.

Source: walks ``get_img`` in ``read_binary_SPEC.m:283-443`` (UIOOPS v3.5).

Each item is ``(tas_temp, n_hol, n_vol)``, exactly the first, third and
fourth arguments ``get_img_v35`` passes to `update_tas`. The walk
repeats ``get_img_v35``'s advance of ``iii`` packet for packet -- the
image-packet skip under the same two conditions, 53 words for a
housekeeping packet, 23 for a mask packet, the next marker otherwise --
but decodes no image and writes no sidecar, so it costs a small fraction
of a decode. Feeding the readings through `update_tas` from a
window's incoming airspeed gives the airspeed the next window starts from.

### `read_binary_spec_v35`

```python
def read_binary_spec_v35(infilename: Any, outfilename: Any, *, software: str, flt_time: Sequence[float] | None=None, flt_tas: Sequence[float] | None=None, time_offset: float | None=None, creation_time: str, sidecars: bool=True, output_txt: bool=False, fast: bool=True, channels: str='HV', progress: Any=None, stamp_profile: str | None=None) -> Any
```

``read_binary_SPEC.m`` (v3.5) -- raw ``.2DS``/``.HVPS`` to ``.H.nc`` + ``.V.nc``.

Returns ``(n_h, n_v)``, MATLAB's ``kk1-1`` and ``kk2-1``.

``software`` is **required and has no default**, and that is the point.
``:79-81`` opens ``version.txt`` with a bare relative path and writes its
contents as the ``Software`` global attribute, so upstream's value is a
property of the *process's working directory* -- a run launched from
somewhere else gets a different attribute, or dies, since ``fopen``'s
failure is unchecked and ``fscanf`` then receives a handle of ``-1``.
Reproducing a cwd-dependent file read would make this function's output
depend on where Python happened to be started; naming the string instead
makes the same fact explicit and recordable. The vendored v3.5 tree's own
``version.txt`` reads ``UIOOPS_v3.5``.

``creation_time`` is likewise required: ``:91`` (and ``:117`` for the V file) stamps
``datestr(now, 'yyyy/mm/dd HH:MM:SS')``, which every byte
comparison already excludes. Passing it in keeps the function
deterministic and keeps the caller honest about what it wrote.

``flt_time``/``flt_tas`` are ``varargin{1}``/``{2}``, the 1-Hz aircraft
series. Supplying them is what turns the ``tasRatio`` variable from
fill-valued into written -- see `_ImageFileV35`. They go through
`arrayprobe_uiops.tas.interp_tas` exactly once, at the top, as ``:40``
does; a TAS series with fewer than two usable nodes therefore **aborts the
decode before a single record is read**, which is the TAS port's measured behaviour
and is preserved.

``time_offset`` is ``varargin{3}``. See `apply_time_offset` and
`WRITER_GAPS` -- it is the one path with no Octave oracle.

``channels`` selects which channel files are *written*; the skipped channel
is still decoded and still counted, so the return value and every sidecar
are unchanged. Same storage rationale as the earlier translation's: on the archived
2016 2D-S the V channel is a recording of a soot-fouled mirror and is by far the
larger file.

### `read_binary_spec_v35_parallel`

```python
def read_binary_spec_v35_parallel(infilename: Any, outfilename: Any, *, jobs: int, software: str, creation_time: str, flt_time: Sequence[float] | None=None, flt_tas: Sequence[float] | None=None, time_offset: float | None=None, sidecars: bool=True, output_txt: bool=False, fast: bool=True, channels: str='HV', workdir: Any=None, progress: Any=None, spawn_retries: int=2, report_every: int=0, stamp_profile: str | None=None, stats: dict | None=None) -> Any
```

`read_binary_spec_v35` across ``jobs`` processes, byte-identical output.

Returns the same ``(n_h, n_v)``. ``jobs <= 1``, or a file with no decode
window, delegates to the serial function. Every other keyword means what it
means there, and the checks run in the same order: ``channels``, then the
flight pair, then `interp_tas`, all before any record is read.

Two pool rounds share one pool: a cheap housekeeping pass per part, whose
readings the parent replays through the serial airspeed gate to give every
part its exact starting airspeed, then the decode. Each part's final
airspeed is compared bit for bit with the next part's starting one, and a
part that disagrees is decoded again before the merge (see
`SeamRerunWarning`). ``stats``, when given a dict, receives
``parts`` and ``reruns``.

``workdir``, ``spawn_retries`` and ``report_every`` behave as in the earlier
translation's ``read_binary_SPEC_parallel``: a fresh
temporary directory per attempt, the whole pool restarted with a
`arrayprobe_uiops.spec_core.SpawnRetryWarning` when it dies before
finishing, and one liveness line per ``report_every`` windows per part.

Byte identity with the serial function, whole files with the same
``creation_time``, is asserted in ``tests/test_v35_spec_parallel.py``.

### `DATA_WORDS`

*(defined in `arrayprobe_uiops.spec_core`, the shared leaf both engines import; documented here, where it is public)*

```python
DATA_WORDS: int
```

### `DIODES`

*(defined in `arrayprobe_uiops.spec_core`, the shared leaf both engines import; documented here, where it is public)*

```python
DIODES: object
```

### `IMG_BLOCKLEN`

*(defined in `arrayprobe_uiops.spec_core`, the shared leaf both engines import; documented here, where it is public)*

```python
IMG_BLOCKLEN: int
```

### `IMG_ROWLEN`

*(defined in `arrayprobe_uiops.spec_core`, the shared leaf both engines import; documented here, where it is public)*

```python
IMG_ROWLEN: int
```

### `MARKER_2S`

*(defined in `arrayprobe_uiops.spec_core`, the shared leaf both engines import; documented here, where it is public)*

```python
MARKER_2S: int
```

### `MARKER_HK`

*(defined in `arrayprobe_uiops.spec_core`, the shared leaf both engines import; documented here, where it is public)*

```python
MARKER_HK: int
```

### `MARKER_MK`

*(defined in `arrayprobe_uiops.spec_core`, the shared leaf both engines import; documented here, where it is public)*

```python
MARKER_MK: int
```

### `RECORD_BYTES`

*(defined in `arrayprobe_uiops.spec_core`, the shared leaf both engines import; documented here, where it is public)*

```python
RECORD_BYTES: object
```

### `RECORD_WORDS`

*(defined in `arrayprobe_uiops.spec_core`, the shared leaf both engines import; documented here, where it is public)*

```python
RECORD_WORDS: object
```

### `RecordHeader`

*(defined in `arrayprobe_uiops.spec_core`, the shared leaf both engines import; documented here, where it is public)*

```python
class RecordHeader
```

The eight timestamp words of one raw record (``readRecord``, :170-182).

Source: ``readRecord`` in ``read_binary_SPEC.m:170-182`` (UIOOPS v3.1.4).

### `iter_record_windows`

*(defined in `arrayprobe_uiops.spec_core`, the shared leaf both engines import; documented here, where it is public)*

```python
def iter_record_windows(path, start: int=0, stop: int | None=None)
```

Yield ``(RecordHeader, buf)`` for each primary record, MATLAB's way.

``start``/``stop`` select a half-open range of primary records without
building the ones before it. The default is the whole file, which is what
every existing caller gets. The range exists for the parallel decode: a
worker assigned windows ``[a, b)`` must be able to reach window *a* without
paying for the *a* windows before it, and with a memory map that costs
nothing -- record *i* is at a computable offset, so no scan is needed to
find it. **These are 0-based**, unlike the rest of this port's public
surface: they index this port's own window range, added for the parallel
decode, not a MATLAB array -- so the global "every public index is
MATLAB 1-based" convention (``docs/09-conventions.md``) does
not apply to them, and this is the one place that says so explicitly.

A worker reads one record **beyond** its last window, because window
``b-1`` is built from records ``b-1`` and ``b``. That overlap is what makes
the ranges independent rather than merely adjacent.

Reproduces ``read_binary_SPEC.m:83-160``: read records *N* and *N+1*,
concatenate their 2048-word image buffers into the 4096-word decode window,
then advance by one record.  **The final record is never a primary** -- the
loop probes one byte past the pair and breaks -- so a file of *n* records
yields *n-1* windows.  Preserved; see the module docstring, point 2.

**A trailing partial record changes that count, and the window is short, not
padded.** The EOF probe fails only when the byte it reads is past the end,
so bytes after the last whole record keep the loop going for one more pair:
the last whole record becomes a primary, continued by whatever
``fread(fid,2048,'uint16')`` returns from the partial one (none at all when
fewer than 18 bytes remain). A file of *n* whole records plus any tail
therefore yields *n* windows. A file shorter than one record yields a single
window whose primary is itself short; the scan then indexes past it, and
that raises from `_at` where MATLAB's ``buf(iii)`` dies. An empty file,
or one too short to hold a data word, raises here: ``get_img`` receives an
empty ``buf`` and MATLAB dies at ``buf(1)``. All measured under Octave on
both vendored trees (a reader edge-case Octave test).

### `sixteen2int`

*(defined in `arrayprobe_uiops.spec_core`, the shared leaf both engines import; documented here, where it is public)*

```python
def sixteen2int(rows: np.ndarray) -> np.ndarray
```

``read_binary_SPEC.m:328-335`` -- pack 16 diode rows MSB-first into a word.

``rows`` is ``(16, n)``; row 1 is bit 15.  Returns ``(n,)`` int64.  The
all-alternating boundary slice packs to `BOUNDARY_WORD`, which is the
cheapest orientation check there is.

## `arrayprobe_uiops.profile`

Where every ``STOCK_V35`` field comes from, machine-readable.

### `Provenance`

```python
class Provenance
```

One cited value of ``STOCK_V35``: the profile ``field``, the ``value`` it carries, and the
``file`` (relative to `V35_TREE`, e.g. ``calculate_reject_unified.m`` or
``read_binary_SPEC.m``), ``lines`` and ``token`` it was read from.

### `STOCK_V35_PROVENANCE`

*(re-exported from elsewhere; not defined in this module)*

### `V35_TREE`

```python
V35_TREE: tuple
```

## `arrayprobe_uiops.matlab_compat`

MATLAB language semantics that NumPy does not reproduce.

### `mround`

```python
def mround(x)
```

MATLAB ``round``: half away from zero, elementwise.

Python and NumPy round half to even -- ``np.round(2.5) == 2`` but MATLAB
``round(2.5) == 3``.

``floor(abs(x) + 0.5)`` is NOT this function: the addition itself rounds, so
``0.49999999999999994`` and every odd integer above 2^52 came out one too
high (the same defect a review fixed in the v3.5 helpers, its findings
2 and 6).  ``abs(x) - floor(abs(x))`` is exact for every finite double, so the
half is tested on that instead.

Provenance: ``dropsize.m:198`` and ``dropsize.m:219``, where the result is
used directly as a 1-based lookup-table index (``dropsize.m:199-200,220-221``),
so an off-by-one changes the reported diameter.  ``dropsize`` is called from
``imgProc_sm.m:834``.

### `mint8`

```python
def mint8(x)
```

MATLAB ``int8(x)`` -- rounds half away from zero, saturates.

### `mint16`

```python
def mint16(x)
```

MATLAB ``int16(x)``.

Provenance: ``imgProc_sm.m:898`` ``int16(images.auto_reject)`` and
``imgProc_sm.m:923`` ``int16(images.holroyd_habit)``.

### `mint32`

```python
def mint32(x)
```

MATLAB ``int32(x)``.

### `mdouble`

```python
def mdouble(x)
```

MATLAB ``double(x)``.

### `madd`

```python
def madd(a, b)
```

MATLAB ``a + b`` with integer dominance and saturation.

### `msub`

```python
def msub(a, b)
```

MATLAB ``a - b`` with integer dominance and saturation.

### `mmul`

```python
def mmul(a, b)
```

MATLAB ``a .* b`` with integer dominance and saturation.

This is the integer-saturation trap.  ``sizeDist.m:770-771`` reads
``image_width``/``image_length``, declared ``'short'`` (int16) at
``imgProc_sm.m:295,299``.  With ``diodesize == 0.010`` for the 2DS
(``sizeDist.m:179,264,368``), ``sizeDist.m:882,884,886,890`` produce an
int16 array that is almost entirely ZERO.  That contaminates ``area_ratio``
at ``sizeDist.m:984`` and therefore ``auto_reject`` at ``:985``.

Only ``d_choice == 6`` (``sizeDist.m:892``) escapes -- which is exactly what
``run_sizeDist_Munich.m:16`` uses, presumably why the bug survived.  NumPy
would give float64 here and silently FIX the bug, breaking bit-for-bit
comparison against the reference output.

### `mdiv`

```python
def mdiv(a, b)
```

MATLAB ``a ./ b`` with integer dominance, rounding and saturation.

MATLAB integer division ROUNDS, it does not truncate:
``int16(5)/int16(2) == 3``.  Verified in Octave.

### `mpow`

```python
def mpow(a, b)
```

MATLAB ``a .^ b`` with integer dominance and saturation.

``int16(300)^2 == 32767``.  Relevant at ``sizeDist.m:888``, where
``im_width.^2 + im_length.^2`` saturates before the sqrt.

### `msqrt`

```python
def msqrt(x)
```

MATLAB ``sqrt`` -- PROMOTES an integer argument to double.

This does NOT follow the saturating-integer rule that mmul/mpow follow.
Verified in Octave: ``sqrt(int16(10))`` is 3.1623, class ``double``.

Consequence for ``sizeDist.m:888``
(``sqrt(im_width.^2+im_length.^2) * diodesize``): the squares and their sum
saturate as int16, sqrt then promotes to double, and the final multiply
stays double.  So ``d_choice == 4`` escapes the zero-collapse that hits
d_choice 1, 2, 3 and 5 -- but carries int16 saturation INSIDE the radicand,
which bites once im_width or im_length exceeds 181 diodes.

### `mmax`

```python
def mmax(a, b)
```

MATLAB two-argument ``max`` with integer dominance.

Provenance: ``sizeDist.m:890`` ``max(im_width, im_length) * diodesize``.

### `mcolon`

```python
def mcolon(a, b, step=1)
```

MATLAB ``a:b`` including its operand-collapsing rule.

MATLAB uses only the FIRST element of a vector operand, and yields an empty
range if either operand is empty.  Returns a 1-based integer ndarray; use
`to0` at the array boundary.

All four call sites are latent UIOOPS bugs preserved deliberately:

* ``sizeDist.m:98-99``   ``timehhmmss(find(diff(timehhmmss)<0)+1:end)``
* ``sizeDist.m:657-658`` same, on ``image_time_hhmmssall``
* ``sizeDist.m:1036``    the reacceptance loop over the shattering events,
  whose range runs from the first ``find`` of the event starts to the first
  ``find`` of the event ends
* ``sizeDist.m:1169``    same, in the fixed-threshold branch

In sites 1 and 2 an empty ``find`` makes the whole assignment a silent
no-op, so this must not raise.  In sites 3 and 4 a descending range (an
event that ends before the first one begins) yields an empty loop.

### `mfind`

```python
def mfind(condition)
```

MATLAB ``find``: 1-based indices of nonzero elements.

Orientation follows MATLAB: a row input gives a row, anything else gives a
column.  Orientation matters downstream -- ``sizeDist.m:686``
``start_all = find(startindex)-1`` and ``IntArrAnalysis.m:37-38``.

### `dec2bin`

```python
def dec2bin(v, width=None)
```

MATLAB ``dec2bin(V, N)`` -> ``(M, W)`` uint8 array of ASCII '0'/'1'.

``width`` is a MINIMUM, not a maximum: MATLAB widens rather than truncating
when a value needs more bits.  ``imgProc_sm.m:568-571`` depends on this --
it compares ``size(c,2)`` against ``diodenum`` and RETURNS from the whole
function on mismatch.  Masking to N bits would make that guard dead code.

Raises ValueError on negative input, matching MATLAB.  Reachable at
``imgProc_sm.m:562`` via ``65535 - data(start:j-1,:)``.

Returns ASCII codes so that call sites transliterate directly:
``imgProc_sm.m:802,804,805`` do ``sum(c=='0',1)``.

Provenance: ``imgProc_sm.m:556`` (2DC, 4x8), ``:559-560`` (2DS/Fast2DC, 8x8),
``:563-564`` (HVPS, 8x16), ``:582``, ``:589-590``, ``:655-656``, ``:699``;
``calculate_reject_unified.m:491,642`` call it without a width.

### `dec2bin_concat`

```python
def dec2bin_concat(columns, width)
```

The ``[dec2bin(X(:,1),w), dec2bin(X(:,2),w), ...]`` idiom, fused.

Returns the ``(nslices, ncols*width)`` char matrix MATLAB calls ``c``.
Provenance: ``imgProc_sm.m:556``, ``:559-560``, ``:563-564``.

### `dec2bin_bits`

```python
def dec2bin_bits(v, width=None)
```

Boolean form of `dec2bin` for the hot path (True == '1').

### `bin2dec`

```python
def bin2dec(chars)
```

MATLAB ``bin2dec``.  Row -> float scalar; ``(M,N)`` -> ``(M,)`` float64.

Returns double, as MATLAB does.  UIOOPS never exceeds 40 bits
(``imgProc_sm.m:591``), so double precision is exact throughout.

Provenance: ``imgProc_sm.m:583``, ``:591``, ``:658-662`` (1-based inclusive
substring slices of a 1x40 row), ``:699``;
``calculate_reject_unified.m:465-485,599-635``.

### `nansum`

```python
def nansum(x, dim=None)
```

MATLAB ``nansum``: NaNs treated as zero; all-NaN and empty both give 0.

``dim`` is 1-based; None means MATLAB's first-non-singleton rule, which
differs from NumPy's "reduce everything".  Summation order is MATLAB's --
see `msum`.

Provenance: ``sizeDist.m:1380,1398,1401,1404,1407,1410`` (accepted
particles) and ``:1535,1553,1556,1559,1562,1565`` (rejected twins);
``:1769`` and ``:1784`` pass dim=2 explicitly.

Only NaN is replaced; ``Inf`` passes through, so ``nansum([Inf NaN 1])``
is ``Inf`` and ``nansum([Inf -Inf NaN])`` is ``NaN`` (Octave-measured).
An earlier version used ``np.nan_to_num`` here, which also mapped
``+-Inf`` to ``+-realmax``, so v3.5's zero-live-time seconds wrote
``n = realmax/10`` where MATLAB writes ``Inf``.

### `nanmean`

```python
def nanmean(x, dim=None)
```

MATLAB ``nanmean``: all-NaN and empty both give NaN, silently.

NumPy emits ``RuntimeWarning: Mean of empty slice`` where MATLAB is silent;
the sizeDist loop hits this for every empty size bin, so the warning is
suppressed rather than allowed to flood the logs.

Provenance: ``sizeDist.m:1383,1388,1391,1394`` and ``:1538,1542,1545,1549``.

### `datenum`

```python
def datenum(y, mo=None, d=None, h=0, mi=0, s=0)
```

MATLAB ``datenum`` -> serial day number.

Accepts three to six scalar/array components, broadcast together, or a
single ``(N,3)`` to ``(N,6)`` date-vector array (``IntArrAnalysis.m:304-306``).

The result is written to netCDF as ``'double'`` under ``'units'`` =
``'MATLAB datetime'`` (``IntArrAnalysis.m:265-267,273-275``), so it is part
of the output contract -- a POSIX timestamp would be wrong.

Reproduces Octave's ``datenum`` bit for bit (the Octave bank
``run_datenum_bank.py``, dev repository only):
a month below 1 is set to 1; days, hours, minutes and seconds out of range
carry linearly, which ``IntArrAnalysis.m:302`` and the ``+240000`` midnight
fixes at ``sizeDist.m:98`` rely on; months above 12 roll into later years;
fractional months and years become days; year 0 and earlier are ordinary.
So MATLAB's zero-date time-of-day idiom ``datenum(0,0,0,H,M,S)`` returns
exactly the time-of-day fraction ``(H + (M + S/60)/60)/24``.

### `datestr`

```python
def datestr(dt=None, fmt=None)
```

MATLAB ``datestr``.

Default format is MATLAB's ``'dd-mmm-yyyy HH:MM:SS'``.
``'yyyy/mm/dd HH:MM:SS'`` is the only explicit format UIOOPS uses
(``imgProc_sm.m:221``, ``sizeDist.m:1810``, ``IntArrAnalysis.m:252``), where
it becomes the non-deterministic ``'Creation Time'`` global attribute --
exclude it from byte comparisons.

### `mchar`

```python
def mchar(c)
```

MATLAB's implicit char->numeric coercion.  ``mchar('S') == 83``.

``imgProc_sm.m:323`` declares ``image_auto_reject`` as ``'short'`` and
``:898`` writes ``int16(images.auto_reject)`` from a CHAR array.
``sizeDist.m:769`` reads it back as int16 and then assigns character
literals into it -- ``:809`` ='D', ``:871`` ='I', ``:985`` ='z',
``:1009,1012,1017`` ='S', ``:1042,1176`` ='R' -- and compares against them
at ``:1047,1060``.  MATLAB coerces silently; NumPy raises.

Also ``imgProc_sm.m:897`` computes ``images.image_touching_edge - '0'``.

### `REJECT_CODES`

```python
REJECT_CODES: dict
```

### `REJECT_CODE_WORDS`

```python
REJECT_CODE_WORDS: dict
```

### `UNREACHABLE_REJECT_CODES`

```python
UNREACHABLE_REJECT_CODES: dict
```

### `HOLROYD_HABITS`

```python
HOLROYD_HABITS: dict
```

### `mvertcat`

```python
def mvertcat(*arrays)
```

MATLAB ``[a; b; ...]``.

Provenance: ``sizeDist.m:815`` ``int_arr = [0;diff(Time_in_seconds)]`` and
``:713`` ``count_all = [diff(start_all); NumofPart-start_all(end)]`` -- both
only make sense because ``netcdf.getVar`` returns a COLUMN for a 1-D
variable (the column-orientation gap in the netCDF-shim design record).

### `mhorzcat`

```python
def mhorzcat(*arrays)
```

MATLAB ``[a, b, ...]``.

### `mdiff`

```python
def mdiff(x, dim=None)
```

MATLAB ``diff``: along the first non-singleton dimension by default.

### `MGrowVector`

```python
class MGrowVector
```

A 1-based MATLAB vector that auto-extends with zero fill.

MATLAB grows an array on out-of-range assignment and fills the gap with 0
(numeric).  A Python port using ``list.append`` gets this wrong whenever the
index skips.

Provenance: ``IntArrAnalysis.m:37-38`` (``intarr(1)=0`` then
``intarr(2:length(tempTime))=diff(tempTime)``), ``:106,109``;
``imgProc_sm.m:575-577,601,697-699`` (the ``images.*`` accumulators indexed
by ``kk``).

Note the companion hazard: ``imgProc_sm.m:863`` does ``clear c ind_matrix``
inside the per-particle loop.  That ``clear`` is load-bearing -- keeping
``ind_matrix`` alive across particles would leak stale rows from a longer
previous particle into ``dec2bin(ind_matrix(:,k))`` at ``:556/559/563``.

### `to0`

```python
def to0(i)
```

MATLAB 1-based index -> Python 0-based.

Convention for this port: keep MATLAB 1-based indices visible in the code
and convert only at the array boundary, so the source's deliberate +/-1
differences stay visually identical.  Several sites MIX 1-based MATLAB
indices with 0-based netCDF starts in one expression, so a uniform global
shift double-shifts them -- see ``sizeDist.m:686`` vs ``:955``,
``sizeDist.m:818,822,833``, ``imgProc_sm.m:452-453,555,558,582,589,655``.

### `to1`

```python
def to1(i)
```

Python 0-based index -> MATLAB 1-based.  See `to0`.

### `MatlabIndexError`

```python
class MatlabIndexError(IndexError)
```

Raised where MATLAB raises ``Index exceeds matrix dimensions``.

A run that would have died in MATLAB must die here too: returning a
truncated result instead would silently turn a failed run into a
plausible-looking one.

Three call sites so far.  The earlier translation's SPEC reader raises it under
`~arrayprobe.profiles.FidelityProfile.spec_buffer_guard` ``False``
(the production variant, which predates the 2017-03-08 guards);
``dropsize.py`` raises it for a negative chord, where ``dropsize.m:220-222``
indexes its lookup tables with ``round(chord * 10)`` and never checks the
sign; and the earlier translation's ``sizeDist`` raises it for a single-particle last block
under
``tree='production'``, where the production-variant ``sizeDist.m:713-716`` indexes
an empty ``diff`` result at ``end`` == 0 (an earlier port version had
been applying stock's Finlon 02/09/18 guard to a tree that has none, so it
completed where MATLAB aborts).

## `arrayprobe_uiops.time_convert`

HHMMSS <-> seconds-since-midnight time conversions.

### `hhmmss_to_insec`

```python
def hhmmss_to_insec(time_hhmmss)
```

Convert an HHMMSS-formatted time (e.g. 134502) to seconds since midnight.

Direct port of hhmmss2insec.m. Values are treated as non-negative,
matching the original's assumed domain (a time-of-day field). Every term is
floored, seconds included (Octave: ``hhmmss2insec(120000.5)`` is 43200).

### `insec_to_hhmmss`

```python
def insec_to_hhmmss(insec)
```

Convert seconds-since-midnight to HHMMSS format.

Direct port of insec2hhmmss.m, every term floored (``insec2hhmmss(43200.5)``
is 120000).

## `arrayprobe_uiops.constants`

Probe- and project-specific configuration tables, transcribed from UIOOPS.

### `MatlabUndefinedVariable`

```python
class MatlabUndefinedVariable(NameError)
```

Raised where MATLAB would raise ``Undefined function or variable``.

Transcribing an upstream omission as a Python default (``0``, ``inf``,
``None`` used silently) would turn a MATLAB *crash* into a Python *number*,
which is a behaviour change.  So the omission is preserved as an error at the
moment of use.

### `ImgProcConfig`

```python
class ImgProcConfig
```

One case of the ``imgProc_sm.m`` probe switch.

Attributes mirror the MATLAB variable names one-for-one so a transliterated
call site reads the same as its source line.

### `ProbeConfig`

```python
class ProbeConfig
```

One case of the ``sizeDist.m`` project/probe switch.

``kk`` is stored in millimetres, already divided (or multiplied) as the source
line does, so the literal here equals the MATLAB value at the end of its own
assignment.

### `IMGPROC_CONFIG`

*(re-exported from elsewhere; not defined in this module)*

### `SIZEDIST_CONFIG`

*(re-exported from elsewhere; not defined in this module)*

### `PROBE_TYPES`

```python
PROBE_TYPES: MappingProxyType
```

### `DIODESIZE_DISAGREEMENTS`

*(re-exported from elsewhere; not defined in this module)*

### `PROJECTS`

*(re-exported from elsewhere; not defined in this module)*

### `imgproc_config`

```python
def imgproc_config(probename: str) -> ImgProcConfig
```

Look up the ``imgProc_sm.m`` probe case.

Unlike ``sizeDist.m``, ``imgProc_sm.m:117`` has **no** ``otherwise`` branch:
an unrecognized probe leaves every variable unassigned and MATLAB fails at
``imgProc_sm.m:195``.  Preserved as an error.

### `sizedist_config`

```python
def sizedist_config(projectname: str, probename: str, tree: str='stock') -> ProbeConfig
```

Look up the ``sizeDist.m`` (project, probe) case in one of the two trees.

An unknown *project* falls through to the ``otherwise`` branch, exactly as
``sizeDist.m:339`` (stock) / ``:223`` (production) does.  An unknown *probe*
within a branch matches no inner case, leaving everything unassigned --
preserved as an error.

``tree`` selects the switch table: ``"stock"`` (v3.1.4) or ``"production"``
(the campaign-configured ``sizeDist.m``, the file that made the archived products).
The default is ``"stock"`` because every caller written before the size-distribution
stage was ported meant
stock and their tests assert stock numbers -- but a *pipeline* must name the
tree, so the earlier translation's ``sizedist.run`` takes ``tree`` with no default at
all.  Getting this wrong is not a rounding difference: production switches
shattering identification **on** for the 2D-S and stock does not.

### `bin_edges`

```python
def bin_edges(projectname: str, probename: str) -> np.ndarray
```

``kk`` in millimetres for a run -- ``num_bins + 1`` edges.

### `bin_width`

```python
def bin_width(projectname: str, probename: str) -> np.ndarray
```

``binwidth = diff(kk)`` -- ``sizeDist.m:523``.

### `resolution_um`

```python
def resolution_um(projectname: str, probename: str) -> float
```

``res = diodesize*1000`` -- ``sizeDist.m:522``.

## `arrayprobe_uiops.reject_core`

Reject helpers both UIOOPS engines share: RejectConfig, mask_start_end, _vertical_split.

*No public API declared (`__all__` empty or absent).*

## `arrayprobe_uiops.spec_core`

Shared leaf: the SPEC record geometry, packet markers and marker scan both engines use.

*No public API declared (`__all__` empty or absent).*

## `arrayprobe_uiops.imgproc_core`

Shared leaf: the imgProc_sm time-base constants and pure helpers both engines use.

*No public API declared (`__all__` empty or absent).*

## `arrayprobe_uiops.engine_absence`

Whether the earlier translation is installed, and the error raised when it is asked for and

*No public API declared (`__all__` empty or absent).*

## `arrayprobe_uiops.intarr`

The robust bimodal inter-arrival-time fit -- IntArrAnalysis_time.m's core numeric routine.

### `bimodal_model`

```python
def bimodal_model(tau, dt)
```

``IntArrAnalysis_time.m:132``'s ``bimodalfit`` -- a two-population exponential mixture.

``tau = (tau1, tau2, tau3)``: the two population time constants and the
mixture fraction of population 2.

### `robust_nlinfit`

```python
def robust_nlinfit(x, y, model, beta0, *, robust=True, tune=_BISQUARE_TUNE, max_iter=1000, tol=1e-08)
```

Bisquare-IRLS nonlinear least squares around ``scipy.optimize.least_squares``.

``robust=False`` is the ordinary unweighted Levenberg-Marquardt fit -- the
one case validated against a real Octave run, since Octave's own
``nlinfit(...,'Robust','on')`` silently computes exactly this (see the
module docstring). ``robust=True`` (the default, matching the MATLAB call
site) performs the iteratively-reweighted loop: fit, compute a MAD-based
robust scale of the residuals, compute bisquare weights from the scaled
residuals, refit weighted, repeat until the parameter vector stops moving
(or ``max_iter`` is reached -- MATLAB's own ``MaxIter`` cap, matched here).

### `fit_bimodal_intarr`

```python
def fit_bimodal_intarr(bins_center, hist_counts, width, beta0=_DEFAULT_BETA0)
```

``IntArrAnalysis_time.m:152-154`` -- the per-population bimodal robust fit.

``hist_counts`` is the raw histogram count array (``h`` in the source);
normalized to a density (``h/sum(h)/width``) before fitting, exactly as the
source does. Returns ``abs(tau)`` -- the source's own ``abs(nlinfit(...))``,
preserved verbatim: a fit that converges to a negative time constant is
sign-flipped, not rejected, matching MATLAB bug-for-bug.

## `arrayprobe_uiops.readers.tasinfo`

``loadTASinfo_2DS.m`` -- read a flight's true-air-speed CSV sidecar.

### `load_tas_info`

```python
def load_tas_info(path) -> tuple[np.ndarray, np.ndarray]
```

``[timehhmmss, tas] = loadTASinfo_2DS(filename)``.

Returns ``(timehhmmss, tas)``, both 1-D ``float64`` arrays. Reads only
the first two columns of the CSV; every other column (there are seven
in a real ``.tas.csv``) is discarded, matching the source's own
``'%f%f%*s...'`` format string.

## `arrayprobe_uiops.combine_fork`

``combine_sizedist.m`` -- stitch a flight's several ``sd`` files into one product.

### `combine_sizedist`

```python
def combine_sizedist(sd_files, outfile, *, flight_date, summary_time, current_year=None, creation_time=None)
```

``combine_sizedist.m`` -- stitch several ``sd`` files into one flight product.

Parameters
----------
sd_files : sequence of paths, IN ORDER
    ``:31,:37`` glob a directory and process files in ``dir`` order, which
    is alphabetical for these basenames. Passing an explicit ordered list
    turns that coincidence into a contract (the combine design record, section 8, decision 1); a
    test pins that the product-of-record's own file order is what
    alphabetical globbing of the five 09/06 raw-derived basenames gives.
outfile : path to write.
flight_date : str, ``'YYYYMMDD'``
    Full year. ``:9`` slices ``flightdate(3:8)`` (MATLAB 1-based) for the
    output stem and ``(3:4)`` for the *wrong* two-digit year used in the
    MATLAB's own cancellation trick (see ``current_year`` below) -- this
    function's default path uses the full year correctly instead.
summary_time : str, ``'YY_MM_DD_HH_MM_SS'``
    The campaign summary file's own basename, without the campaign
    extension -- e.g. ``'16_09_06_06_40_17'`` for
    ``16_09_06_06_40_17.oracles``. ``:150-154`` needs its full date and
    time for the sync step below; ``:199-200`` needs only its HH/MM/SS
    for the output filename, which this module's caller builds separately
    (the combine design record, section 3: the script uses the summary file's NAME only, never
    its contents, so there is no filesystem dependency to satisfy here).
current_year : int or None
    ``None`` (default) computes the intended time axis directly: the
    flight date plus time of day, with no dependency on when this code
    happens to run. A given int replicates ``:109-110``'s own arithmetic
    via `_timevec_matlab_replica`, for reproducing a specific
    historical mis-set run -- see that function's docstring.
creation_time : unused
    ``combine_sizedist.m`` writes no global attributes at all (measured;
    ``:202-231`` defines only variables). Accepted for interface symmetry
    with the earlier translation's ``imgproc_sm`` and ``sizedist.run``, and ignored.

Returns the path written.

## `arrayprobe_uiops.intarr_analysis`

``IntArrAnalysis_time.m`` -- per-particle inter-arrival thresholds, and the file they go in.

### `DEFAULT_THRESHOLD`

```python
DEFAULT_THRESHOLD: float
```

### `HIST_BINS`

```python
HIST_BINS: logspace
```

### `CONTOUR_BINS`

```python
CONTOUR_BINS: logspace
```

### `inter_arrival`

```python
def inter_arrival(time_in_seconds)
```

``:73-75``, ``:93``, ``:105-111`` -- the source's inter-arrival vector, in its own order.

The first particle gets 0, the rest are differences; then ``<= 0`` becomes NaN (which takes
that leading 0 with it), and anything above 0.1 s is set to **0, not dropped**. The two steps
are ordered as the source orders them: the ``< 0 -> 0`` line at ``:110`` is a no-op once the
NaN step has run, and is kept for transcription completeness.

### `population_size`

```python
def population_size(timehhmmss, n_blocks)
```

``:112-119`` -- how many particles go into each bimodal fit.

``ceil(N / n_blocks)`` unless the most crowded second holds at least that many, in which case
the block is that second's count rounded **up to the next quarter** of the base size. Coarse
by design; reproduced as written.

### `block_thresholds`

```python
def block_thresholds(counts, *, beta0=_BETA0)
```

``:139-190`` for one population: ``(threshold, threshold_ww, threshold_ak, tau)``.

``counts`` is the raw histogram of the block's inter-arrival times over `HIST_BINS`.
All three of the source's thresholds are returned; only ``threshold_ak`` is written to the
output file, as the source writes it (``:367``).

### `analyse`

```python
def analyse(int_arr, timehhmmss, *, n_blocks=5, beta0=_BETA0, collect_histograms=False)
```

Run the whole population loop.  Returns a dict of per-particle arrays.

Keys: ``threshold``, ``threshold_ww``, ``threshold_ak`` (each one value per particle, constant
within a block), ``tau`` (one row per block), ``population_size``, ``block_starts``. All
three thresholds are always returned -- the source itself computes all three and writes only
``threshold_ak`` (``:367``); returning the other two here writes nothing and changes no file,
so it needs no opt-in (see the module docstring's note on the remaining inter-arrival work).

``collect_histograms=False`` (default) leaves this function's return value byte-for-byte
identical to a call without the option: no extra key appears and nothing above is computed
differently. ``collect_histograms=True`` additionally returns ``hist2dc``
-- ``:106,148`` -- the raw 34-bin histogram counts per block (one row per block), needed only by
`write_mat_workspace`.

### `write_threshold_file`

```python
def write_threshold_file(filename, timehhmmss, threshold, *, probename, flight_date, data_source, population_size, creation_time=None)
```

``:336-368`` -- the file ``sizeDist`` reads as its twelfth argument.

Attribute names, order, units and variable names follow the source exactly; ``Creation Time``
is overridable so two runs can be compared byte for byte.

### `contour_data`

```python
def contour_data(int_arr, timehhmmss, date, size)
```

``:220-236`` -- the contour plot's own, coarser-fit-but-finer-bin per-block histogram.

A second population loop over the *same* blocks `analyse` uses (``size`` is its
``population_size``), but histogrammed into `CONTOUR_BINS` (69 bins, not 34) and
without any fitting -- the source only ever plots this one, it does not fit it.

Returns ``(hist2dc_contour, new_time2dc, new_date2dc)``. ``:235-236`` overwrites the *last*
block's own recorded start time/date with the sequence's very last particle's time/date --
reproduced here exactly, including on a single-block input.

### `overlay_time_axis`

```python
def overlay_time_axis(timehhmmss, date, *, fix_b8=False)
```

``:243-250`` -- the per-particle datenum axis for the threshold-overlay lines.

``fix_b8=False`` (default, matching every real run of the source) reproduces the upstream
finding that a mixed-width time vector puts NaN into every pre-10:00 timestamp:
``num2str`` right-justifies the whole ``timehhmmss`` column to one common width,
so in a file spanning 10:00:00 every row before it is left-padded with a space and the
``< 100000`` branch reads that pad as the hour digit -- ``str2double`` of a blank is NaN.
``fix_b8=True`` computes the same value directly from the integer,
never touching a string.

### `contour_time_axis`

```python
def contour_time_axis(new_time2dc, new_date2dc)
```

``:258-269`` -- the contour plot's own per-block ``x`` axis.

A *different* formula from `overlay_time_axis`, and -- unlike it -- not affected by that
NaN: it branches on ``size(y,2)`` (the char matrix's actual width) rather than always slicing
the same fixed columns, so the width-6 case correctly reads column 2 (a single digit) as the
hour rather than column 1 (the padding space). Kept faithfully rather than "fixed", since it
is not a bug -- the source got this one right.

### `expand_tau_per_particle`

```python
def expand_tau_per_particle(tau_blocks, block_starts, population_size, n)
```

``:162-164``'s ``tau_all(j,:) = tau_std`` -- broadcast each block's fitted ``tau`` to
every particle in that block, needed only for `write_mat_workspace`'s ``tau_all``.

The inner ``for j`` loop runs unconditionally (both the NaN and non-NaN branches reach it),
so a block whose fit failed still broadcasts its ``[NaN, NaN, NaN]`` row to every one of its
particles, exactly like a successful block broadcasts its real ``tau``.

### `write_extra_thresholds_sidecar`

```python
def write_extra_thresholds_sidecar(filename, timehhmmss, threshold, threshold_ww, *, threshold_ak=None)
```

Opt-in: persist the two thresholds the source computes but never writes (``:159``,
``:189``) alongside the ``.cdf`` -- as a plain JSON sidecar, **never** a netCDF file.

``threshold`` (``min(tau(1:2))*2``) and ``threshold_ww`` (the fitted-curve selection) sit
next to ``threshold_ak`` (the one value ``:363`` writes) purely for a user who wants to
compare the three techniques; `analyse` already returns all three unconditionally
(see the module docstring), so this function only decides where the extra two get
*persisted*, and the fidelity doctrine's "an enhancement writes a variable MATLAB never
wrote" line draws that boundary at the ``.cdf`` file specifically, not at "on disk at all".

### `write_mat_workspace`

```python
def write_mat_workspace(filename, *, timehhmmss, date, time_in_seconds, dmax, probe_name, date_string, infile, n_blocks=5, beta0=_BETA0)
```

``:331`` -- ``save([directory_2, probeName, '_IntArrAnalysis.', dateString, '_',
startTime, '_', endTime, '.mat'])``, with no variable list: MATLAB saves the function's
*entire* local workspace at that line. ``scipy.io`` is imported lazily -- opt-in, like the
plots, so nothing in this module needs it merely to be imported.

Writes the named result variables a user opening the ``.mat`` would actually want back,
under their own MATLAB names, with MATLAB's own shapes (row vectors stay ``(1, N)``, matrices
stay ``(n_blocks, n_bins)``). **Deliberately excluded**, and named here rather than silently
dropped:

* loop scratch that is only ever a *last-iteration* leftover, an artifact of MATLAB script
  scoping rather than a real result -- ``i``, ``j``, ``k``, ``h``, ``arr``, ``indicies``,
  ``dt``, ``hfit``, ``tau1``, ``tau2``, ``newDT``, ``minFit``, ``indexFit``, ``minOriginal``,
  ``indexOriginal``, ``y`` (redundant with ``NEWtime2dc`` in any case);
* ``bimodalfit``, a function handle, not data ``scipy.io.savemat`` can round-trip;
* ``ncid``, ``file`` -- an open netCDF handle and an OS ``dir()`` struct, meaningless once
  the run has finished;
* the function's own parameters (``campaign``, ``filedate``, ``startTime``, ...), which the
  source's own hardcoded "Inputs" block (``:33-40``) overwrites before first use, so what a
  caller passed is never actually what ends up in the workspace under those names.

Every OTHER named quantity the source's own workspace holds at ``:331`` is included:
``hist2dc``, ``NEWtime2dc``, ``NEWdate2dc`` (the *contour* loop's versions, since ``:231-236``
overwrite the fit loop's own same-named arrays), ``threshhold``, ``threshhold_ww``,
``threshhold_ak``, ``tau_all``, ``hist2dc_contour``, ``histsum``, ``x``, ``time``, ``bins``
and ``binsCenter`` (the *contour* loop's 70-point versions -- ``:220`` reassigns ``bins``
after the fit loop, so that is what is left in the workspace), ``width`` (the *fit* loop's
35-point value -- computed once at ``:119``, before ``:220``'s reassignment, and never
touched again), ``num_particles``, ``numparticles``, ``timehhmmss``, ``date``, ``int_arr``,
``intarr``, ``Dmax``, ``n`` (the *contour* loop's final counter, since ``:224`` resets it),
``dateString``, ``probeName``, ``infile``.

## `arrayprobe_uiops.intarr_plots`

The production-variant ``IntArrAnalysis_time.m:220-291``: the contoured inter-arrival figure.

### `plot_intarr_contour`

```python
def plot_intarr_contour(int_arr, timehhmmss, date, threshold, threshold_ww, threshold_ak, *, population_size, date_string='', fix_b8=False)
```

``:220-291`` -- draw the contoured inter-arrival-time figure with matplotlib.

``int_arr``, ``timehhmmss``, ``date`` are the same per-particle arrays
`arrayprobe.intarr_analysis.analyse` and `arrayprobe.intarr_analysis.
contour_data` take. ``threshold``, ``threshold_ww``, ``threshold_ak`` are ``analyse``'s own
per-particle outputs (all three are always returned; see that module's docstring).
``population_size`` must be the same block size used for the fit (``analyse``'s
``out["population_size"]``), since the contour loop (``:225``) reuses it rather than
re-deriving it.

Returns ``(fig, ax)``. Never called at import time; matplotlib is imported here, lazily.

## `arrayprobe_uiops.sizedist_core`

Shared leaf: the sizeDist time-conversion helpers both engines use.

*No public API declared (`__all__` empty or absent).*

## `arrayprobe_uiops.readers`

Raw-probe-file decoders both engines share: ``read_binary_PMS.m`` and the ``.MK.csv`` reader.

*No public API declared (`__all__` empty or absent).*

## `arrayprobe_uiops.readers.pms`

NCAR OAP raw decoder -- ``read_binary_PMS.m``.

### `read_binary_PMS`

```python
def read_binary_PMS(infilename, outfilename)
```

``read_binary_PMS.m`` -- raw NCAR-OAP file to three probe-type outputs.

Writes ``<outfilename>.2dc.cdf``, ``<outfilename>.f2dc.cdf`` and
``<outfilename>.2dp.cdf``. Returns ``(n_2dc, n_f2dc_c6, n_f2dc_c4, n_2dp)``
-- the four raw MATLAB write-counters (``kk``, ``kk2``, ``kk3``, ``kk1``),
kept separate rather than summed because ``'C6'`` and ``'C4'`` records
are not equivalent: see the module docstring for what each actually
writes and where.

## `arrayprobe_uiops.readers.mask_csv`

A reader for the ``.MK.csv`` sidecar ``read_binary_SPEC.m`` writes with no

### `MaskRecord`

```python
class MaskRecord
```

One automask event, in the order ``read_binary_SPEC.m:314`` writes it.

### `load_mask_csv`

```python
def load_mask_csv(path: str | Path) -> list[MaskRecord]
```

Parse a ``.MK.csv`` sidecar into its fixed-width records.

Source: reads what ``read_binary_SPEC.m:314-315`` (UIOOPS v3.1.4) writes.

Raises `ValueError` if the file's token count is not a multiple of
nineteen -- a truncated write or a file that is not actually a mask
sidecar, either of which should stop a caller rather than silently drop
a partial trailing record.

## `arrayprobe_uiops.register_image_assisted`

Import-time side effect: registers ``stock-v3.5-image-assisted`` (label-based hollow setting).

*No public API declared (`__all__` empty or absent).*

## `arrayprobe_uiops.hollow_size_rule`

Size-dependent hollow rejection, calibrated on 480 hand-labelled particles.

### `DEFAULT_THRESHOLD_UM`

*(re-exported from elsewhere; not defined in this module)*

### `LABELLED_EVIDENCE`

*(re-exported from elsewhere; not defined in this module)*

### `HollowSizeRule`

```python
class HollowSizeRule
```

Configuration for the size-dependent hollow rejection.

``enabled=False`` is the default, and makes every function below a
strict passthrough of ``ihollow`` -- see
``tests/test_hollow_size_rule.py::TestBitIdenticalWhenOff``.

``threshold_um`` is a parameter, not a constant: the labels behind
`DEFAULT_THRESHOLD_UM` (480 hand-labelled particles) cannot justify more
precision than one estimate, and that estimate is not a sharp boundary
-- the 45% [31, 60] and 60% [45, 74] Wilson intervals it sits between
overlap, both at n=40. A future campaign, probe, or bigger label set
will want to move this number without editing this module's code.

### `LabelledBin`

```python
class LabelledBin
```

One size bin of the hand-labelled *disputed* particles.

"Disputed" means stock's hollow test rejects the particle and the
image-assisted alternative would accept it; the label says which side was
right. `n_real` is how many of those were judged to be real
particles -- i.e. how many stock's hollow test wrongly discarded.

Only the two counts are stored. The fraction and its interval are
**computed**, never typed, so there is exactly one place a label can move.

### `hollow_test_applies`

```python
def hollow_test_applies(rule: HollowSizeRule | None, size_um: float | None) -> bool
```

Whether the hollow test's rejection should apply, as stock does, to a
particle of this size under this rule.

``True`` (apply as stock) when ``rule`` is ``None`` or ``rule.enabled``
is ``False``, when no size could be established (``size_um is None`` --
stock is always the conservative fallback), or when
``size_um < rule.threshold_um``. ``False`` (bypass the hollow test's
rejection) only when the rule is enabled AND
``size_um >= rule.threshold_um`` -- the threshold value itself is on
the disabled side; see the module docstring's "Boundary convention".

### `resolve_ihollow`

```python
def resolve_ihollow(ihollow: int, size_um: float | None, rule: HollowSizeRule | None=None) -> int
```

The ``ihollow`` value ``calculate_reject_unified`` should receive,
with the size-dependent rule applied.

Returns ``int(ihollow)`` unchanged whenever `hollow_test_applies`
is ``True`` (stock -- always true when ``rule`` is ``None`` or
disabled); returns ``0`` (not hollow) otherwise. Never turns a stock
``0`` into a ``1``: this rule only narrows what stock rejects for
hollow, matching the module docstring's note on the preserved
``hollow_status``/``ihollow`` defect at
``arrayprobe_uiops/reject.py:361-375`` -- the caller's ``ihollow`` is what
decides ``hollow_status``, unchanged by anything downstream, so this is
the only point with leverage on the outcome.

### `resolve_ihollow_array`

```python
def resolve_ihollow_array(ihollow: np.ndarray, size_um: np.ndarray, rule: HollowSizeRule | None=None) -> np.ndarray
```

Vectorised `resolve_ihollow`, for retroactively applying the
rule across an already-decoded record's ``is_hollow``/
``image_diam_minR`` columns, rather than one particle at a time inside
``arrayprobe_uiops.measure.measure_record``. Not used by the pipeline
itself -- offered for the kind of bulk recompute this project's own
reproducibility checks already do (e.g. the check that the habit column
reproduces from a decoded file on disk).

``size_um`` entries that are NaN are treated as "no size established"
(stock applies), matching `hollow_test_applies`'s ``None`` case.

### `size_um_from_minr`

```python
def size_um_from_minr(minr: float, diodesize_mm: float) -> float
```

The size measure available where the hollow decision is made.

``arrayprobe_uiops/measure.py:237`` computes ``minR`` before the
``:262`` reject call; ``minr * diodesize_mm`` is exactly what
``arrayprobe_uiops/imgproc.py:1365`` later writes to the output netCDF as
``image_diam_minR`` (there in mm, ``diodesize_mm`` being
``RecordGeometry.diodesize``). This function does that same
multiplication and then converts mm to micrometres (``* 1000``) to
match the units `DEFAULT_THRESHOLD_UM` and the hand labels are
stated in. Not a new geometric computation -- the same quantity, read
one call earlier and in different units.

### `threshold_from_evidence`

```python
def threshold_from_evidence(bins: tuple[LabelledBin, ...]=LABELLED_EVIDENCE) -> float
```

Where the labels say the hollow test flips from right to wrong.

The low edge of the smallest bin in which stock's hollow test is wrong at
least as often as it is right (``fraction_real >= 0.5``), scanning upward.
That is the whole rule: the threshold is **read off the labels**, not
chosen and then justified, so re-labelling moves it and nothing here needs
editing.

Raises `ValueError` if no bin crosses the half -- a state in which
this module has no evidence for any threshold and should not silently
supply one.

### `wilson_95`

```python
def wilson_95(n_success: int, n: int) -> tuple[float, float]
```

Wilson score interval for a binomial proportion, two-sided 95 %.

Wilson rather than Wald because three of the five bins below sit near an
end of the range -- ``0/25`` among them, where Wald's interval is the
degenerate ``[0, 0]`` and would make "no threshold helps here" look like
a certainty rather than the ``[0, 13] %`` it is.

## `arrayprobe_uiops.probe_cases`

Registered probe cases: a bin ladder v3.5's own ``switch`` does not have.

### `ProbeCase`

```python
class ProbeCase
```

A named ``(num_bins, kk, and the eleven constants beside them)`` bundle.

``defaults`` is a plain `ProbeDefaults` -- the same record
``probe_defaults()`` returns -- so a case reaches ``sizeDist``'s body
through the identical path a stock case does and changes no code beyond the
lookup.

### `UnknownProbeCase`

```python
class UnknownProbeCase(LookupError)
```

``--probe-case NAME`` named a case nothing has registered in this process.

### `UncitedProbeCaseField`

```python
class UncitedProbeCaseField(ValueError)
```

A `ProbeCase` left one of `ProbeDefaults`' fields uncited.

Not a style rule: the whole warrant for a case that upstream's ``switch``
does not contain is that every constant in it was **read out of a vendored
tree**, not chosen.  An uncited field is an invented one.

### `DuplicateProbeCase`

```python
class DuplicateProbeCase(ValueError)
```

Two different cases registered under one name.

Re-registering the *same* case is a no-op -- importing a registration
module twice must not explode -- but a second, different case under a name
already taken would make ``--probe-case NAME`` mean whichever import ran
last, which is the silent-wrong-output shape this project treats as serious.

### `PROBE_CASES`

*(re-exported from elsewhere; not defined in this module)*

### `register_probe_case`

```python
def register_probe_case(case: ProbeCase) -> ProbeCase
```

Add ``case`` to this process's registry and return it.

Idempotent for an identical case (so a registration module may be imported
twice); raises `DuplicateProbeCase` for a different one.

### `resolve_probe_case`

```python
def resolve_probe_case(name: str) -> ProbeCase
```

The registered case ``name``, or `UnknownProbeCase`.

### `register_v35_2ds_ladder_fix`

```python
def register_v35_2ds_ladder_fix() -> ProbeCase
```

Build, register and return ``v35-2ds-ladder-fix`` (swapped-bin-table fix).

v3.5's ``otherwise``/``'2DS'`` case with the 2D-S 128-bin ladder that upstream left
commented out at ``sizeDist.m:506-507`` in place of the HVPS table at ``:502-505``: v3.5's
own constants and v3.1.4's ``:374``/``:376`` ladder, which is the commented-out line, built
directly from the two vendored tables (`_v35_2ds_ladder_defaults`). It registers no
other case. A campaign case built on the same record sizes identically to the batch
driver's default-on bin-table correction; this is a separate name so a stamp names the
correction, not a campaign.

### `resolve_shipped_probe_case`

```python
def resolve_shipped_probe_case(name: str) -> ProbeCase
```

`resolve_probe_case`, registering a case every install carries on first use.

``v35-2ds-ladder-fix`` ships with the package, so a name quoted anywhere (``--probe-case``,
a run TOML's ``probe_case``, ``tune settings``) resolves in a fresh process without a
``--probe-case-module``. The one helper behind the batch driver's preflight and
`arrayprobe.tune.settings.resolve_probe_defaults`; any other unregistered name is
refused exactly as `resolve_probe_case` refuses it.

### `V35_2DS_LADDER_FIX`

*(re-exported from elsewhere; not defined in this module)*

### `REQUIRED_IA_THRESH_TYPE`

*(re-exported from elsewhere; not defined in this module)*

### `require_ia_thresh_type`

```python
def require_ia_thresh_type(name: str, ia_thresh_type: int) -> None
```

Record that registered case ``name`` acts only under ``ia_thresh_type``.

Called by the module that registers such a case, beside its
`register_probe_case` call, so the requirement exists wherever the case does.

### `ACCEPTED_IA_THRESH_TYPES`

*(re-exported from elsewhere; not defined in this module)*

### `accept_ia_thresh_types`

```python
def accept_ia_thresh_types(name: str, ia_thresh_types: frozenset[int]) -> None
```

Record that registered case ``name`` acts under each of ``ia_thresh_types`` and no other.

## `arrayprobe_uiops.product_sanity`

Gross-failure sanity check for size-distribution (sd) and particle (proc) netCDF files.

*No public API declared (`__all__` empty or absent).*

## `arrayprobe_uiops.combine`

The production fork's ``combine_sizedist.m``, run over v3.5 ``sd`` output -- BORROWED, OPT-IN.

### `BORROWED_FROM`

```python
BORROWED_FROM: str
```

### `CALL_STAMP`

```python
CALL_STAMP: str
```

### `BorrowedCombineNotEnabled`

```python
class BorrowedCombineNotEnabled(RuntimeError)
```

Raised when `combine_sizedist` is called without opting in.

Default OFF is the point: nothing about v3.5's own output is
touched unless a caller names ``borrowed_combine=True`` explicitly.

### `SdSchemaMismatch`

```python
class SdSchemaMismatch(ValueError)
```

An input file does not carry the 11 variables ``combine_sizedist.m``
reads at the indices it hard-codes -- see `check_sd_schema`.

### `check_sd_schema`

```python
def check_sd_schema(path: Any) -> None
```

Assert ``path`` carries every variable `arrayprobe.combine.MATLAB_VARID`
names, each at the on-disk index the MATLAB source reads by number.

``arrayprobe.combine`` itself reads by NAME (the combine stage's design rule:
"read by name, assert by index") and trusts a v3.1.4-shaped ``sd`` file to
have named things consistently with that hard-coded index table. A v3.5
file is a different writer; this is that same assertion, run explicitly
against v3.5 output before delegating, rather than assumed.

### `combine_sizedist`

```python
def combine_sizedist(sd_files: Any, outfile: Any, *, flight_date: Any, summary_time: Any, borrowed_combine: bool=False, current_year: Any=None, creation_time: Any=None) -> Any
```

The production fork's ``combine_sizedist.m``, over v3.5 ``sd`` files.

Same contract as `arrayprobe.combine.combine_sizedist` -- this
calls that function unmodified, after guarding the input schema -- plus
one addition:

Parameters
----------
borrowed_combine : bool
    Must be ``True`` or this raises `BorrowedCombineNotEnabled`
    and writes nothing. Default OFF: nothing about a v3.5
    run is touched unless a caller opts in explicitly.

Raises
------
BorrowedCombineNotEnabled
    ``borrowed_combine`` is not ``True``.
SdSchemaMismatch
    Some input in ``sd_files`` does not carry the 11 variables the fork
    combine reads at the indices it hard-codes -- see
    `check_sd_schema`.

Returns the path written, and stamps a ``<outfile>.call`` sidecar
recording the borrowing (`CALL_STAMP`) and the input file names.
