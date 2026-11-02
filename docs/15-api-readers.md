# API reference: raw-format readers
> Generated from `src/arrayprobe`'s own AST; never hand-typed. Regenerate with `docs/_build/apidoc.py`.

Shared tooling, readers and the command line. An earlier translation of UIOOPS v3.1.4 reproduced archived products and is not part of this package; its engine modules are not shipped.

**See also** [CLI reference](13-cli-reference.md) · [Reference](08-reference.md).

## `arrayprobe.readers`

Raw-probe-file decoders: ``read_binary_*.m``.

*No public API declared (`__all__` empty or absent).*

## `arrayprobe.readers.dmt`

DMT probe raw decoder -- ``read_binary_DMT.m``.

### `DecompressionError`

```python
class DecompressionError(ValueError)
```

A record's decompressed stream has no run of eight sync bytes.

MATLAB's search (``:147-160``) has no exit for this case: it runs on
through the low hex digits of its char array and dies indexing past the
array, or, if it finds a run there, at ``:177`` (Octave-measured).

### `NonconformantAssignmentError`

```python
class NonconformantAssignmentError(ValueError)
```

``read_binary_DMT.m:177`` dies: a record reassembles to 1-7 groups.

``length`` of an *n*-by-8 matrix is ``max(n, 8)``, so for *n* < 8 the
assignment ``decomp_convert1(1:8,:) = decomp_convert`` puts *n* rows into
eight (Octave 11.3: ``=: nonconformant arguments (op1 is 8x8, op2 is 3x8)``).
Zero groups dies the same way under Octave, whose ``hex2dec`` of an empty
selection returns a scalar 0 and so makes a 1-by-8 row.

### `read_binary_DMT`

```python
def read_binary_DMT(infilename, outfilename, *, progress=None, exact_sync: bool=False)
```

``read_binary_DMT.m`` -- raw DMT probe file to ``<outfilename>``.

Unlike ``read_binary_SPEC`` in the earlier translation (not included in this package), DMT
writes one
output file (no H/V channel split -- the format has none) and the input
is a flat sequence of fixed 4112-byte records with no sliding window: the
MATLAB's ``while feof(fid)==0`` reads and decodes every record until end
of file, checked by trial-reading (and rewinding) the next 20 bytes
(``:212-219``) rather than by a record-count computed up front. The first
record is read unconditionally, so a file too short to hold one raises;
so does a tail of 20 bytes or more that is not a whole record (see
`_tail_after`).

``exact_sync`` (default ``False``, MATLAB's behaviour) makes the boundary
search count only the byte ``0xAA`` rather than every byte whose high hex
digit is ``A`` -- see `_sync_bytes`.

Returns the number of records written.

### `read_binary_DMT_parallel`

```python
def read_binary_DMT_parallel(infilename, outfilename, *, jobs: int, workdir=None, progress=None, spawn_retries: int=2, report_every: int=0, block: int=256, exact_sync: bool=False) -> int
```

`read_binary_DMT` across ``jobs`` processes, byte-identical output.

Every DMT record decodes from its own 4112 bytes, so records split at any
multiple of 4112 with no priming; the one thing carried from record to
record, the image a record of 1700 groups or more repeats, is resolved in
the merge (`_STALE`), and the bytes after the last whole record are
handled there too. ``jobs <= 1`` or a file of at most one
record delegates to the serial function. ``progress(count)`` is called
from the parent per record, the same sequence as serial. A decode failure
leaves the same partial file and raises the same exception as serial.
``spawn_retries`` restarts a pool that died (``BrokenProcessPool``) from a
fresh temporary directory with ``spec.SpawnRetryWarning``, as
``spec.read_binary_SPEC_parallel`` does. ``report_every`` (default 0,
silent) prints a liveness line per part every that many records.

## `arrayprobe.readers.sea`

SEA (CIP/2DC) raw decoder -- ``read_binary_SEA.m``.

### `read_binary_SEA`

```python
def read_binary_SEA(infilename, outfilename, *, exact_sync: bool=False)
```

``read_binary_SEA.m`` -- raw SEA file to ``.CIP.cdf`` and ``.2DC.cdf``.

Returns ``(n_cip, n_weird_cip, n_2dc)`` -- ``n_weird_cip`` counts CIP
records silently dropped for lack of a boundary run (MATLAB's
``nWierdTotal``). Raises `SeaUndefinedVariableError` if a
5000/4096-tagged record is ever reached, matching the MATLAB crash.

``exact_sync`` (default ``False``, MATLAB's behaviour) makes the boundary
search count only the byte ``0xAA`` rather than every byte whose high hex
digit is ``A`` -- see `_find_boundary_or_none`.

### `SeaUndefinedVariableError`

```python
class SeaUndefinedVariableError(RuntimeError)
```

``read_binary_SEA.m:270`` references ``varid91``, never assigned.

MATLAB errors here the first time a 5000/4096-tagged record is reached;
see the module docstring for the full trace.

## `arrayprobe.inventory`

Raw-file inventory: flag empty and truncated raw probe files before processing.

### `RECORD_BYTES`

*(re-exported from elsewhere; not defined in this module)*

### `guess_format`

```python
def guess_format(path: str | os.PathLike) -> str
```

A guess, not a reader decision: ``pms_2d``, ``spec``, ``dmt`` or ``unknown``.

### `inventory`

```python
def inventory(paths: str | os.PathLike | Iterable[str | os.PathLike], fmt: str | None=None) -> list[dict]
```

Rows for every regular file in a directory (sorted, non-recursive) or for a list.

### `inventory_row`

```python
def inventory_row(path: str | os.PathLike, fmt: str | None=None) -> dict
```

One inventory row for ``path``; ``fmt`` overrides the guess.

### `write_inventory`

```python
def write_inventory(rows: list[dict], out_stem: str | os.PathLike) -> tuple[Path, Path]
```

Write ``<out_stem>.json`` and ``<out_stem>.csv``; return both paths.
