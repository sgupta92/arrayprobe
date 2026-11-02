# API reference: the friendly boundary layer
> Generated from `src/arrayprobe`'s own AST; never hand-typed. Regenerate with `docs/_build/apidoc.py`.

Shared tooling, readers and the command line. An earlier translation of UIOOPS v3.1.4 reproduced archived products and is not part of this package; its engine modules are not shipped.

**See also** [CLI reference](13-cli-reference.md) · [Reference](08-reference.md).

## `arrayprobe.friendly`

A friendly re-view of four raw contracts, each a finding the port keeps rather than fixes.

### `all_record_headers`

```python
def all_record_headers(path: str | os.PathLike) -> list[RecordHeader]
```

Every record's header, in file order -- *n* headers for *n* records.

The earlier translation's record-window iterator (kept in the development
repository) reproduces
``read_binary_SPEC.m``'s raw decode loop exactly: the loop reads records
*N* and *N+1* as a pair, so for a file of two or more records the very
last record is never fed through it as a primary (preserved bug,
the v3.1.4 SPEC reader's module docstring, point 2; regression test
``test_spec_reader.py::TestTwoRecordWindow::test_final_record_is_never_a_primary``).
A file of *n* >= 2 records therefore yields *n-1* windows from that
function, and the header of record *n-1* (0-based) never appears in its
output. (A one-record file is the degenerate case: with no second
record to pair against, that lone record already comes back as a single
short window -- see
``test_spec_reader.py::TestTwoRecordWindow::test_single_record_file_yields_one_short_window``
-- so there is nothing left for this function to add there.)

A caller who wants "every record that exists in this file", rather than
"every record MATLAB's pairwise scan reached", should not have to
rediscover that gap. This function re-plays the same *n-1* windows
unchanged -- one call to the earlier translation's record-window iterator,
nothing reimplemented -- and appends the one header that function
structurally cannot produce: the last record's own eight timestamp
words, read directly with the same `numpy.memmap` shape the raw
function uses. No window is built for it (matching MATLAB: that record
was never fed through the two-record decode that produces particles),
so this adds a header, never a particle.

Always ``len(all_record_headers(path)) == n_records`` (whole records), and
for *n* >= 2 whole records with nothing after them,
``all_record_headers(path) == [h for h, _ in iter_record_windows(path)]
+ [<last record's header>]`` -- the identity
``tests/test_friendly.py::TestAllRecordHeaders`` checks.

### `TouchingEdge`

```python
class TouchingEdge(enum.Enum)
```

The three values ``imgProc_sm.m:897``'s ``touching_edge - '0'`` writes.

Member values are the **written** integers -- what a ``touching_edge``
variable in a processed netCDF file actually holds, so
``TouchingEdge(nc_value)`` reads one straight back. See
`touching_edge_flag` for the raw
raw ``RejectResult`` field (the earlier translation's reject result, which is not part of
this package) these come from, which is
a different, un-subtracted domain.

### `touching_edge_flag`

```python
def touching_edge_flag(raw_field: object) -> TouchingEdge
```

The v3.1.4 reject result's raw ``touching_edge`` -> `TouchingEdge`.

``calculate_reject_unified.m:108`` initialises ``touching_edge``
numerically and only ``:213-216`` makes it a character, so
the reject result's ``touching_edge`` field is a
genuine three-value union rather than one Python type: the int ``0``
(no slices at all -- the branch returns before the character
assignment; regression test
``test_reject.py::TestTouchingEdgeIsTriState::test_no_slices_returns_the_numeric_initialiser``),
or the one-character strings ``"0"`` (contained) and ``"t"`` (touching
diode 1 or the last diode; ``test_contained_and_touching_particles_return_characters``).

This maps that raw field onto the same ``{-48, 0, 68}`` domain
``imgProc_sm.m:897``'s ``touching_edge - '0'`` writes to the product
file (``test_the_three_values_imgproc_would_write``), losslessly and
without changing ``RejectResult`` itself -- the raw field is untouched,
as this module promises.

Raises `ValueError` on anything outside the three accepted raw
values, deliberately: a fourth value would mean the raw contract this
wraps has changed underneath it, not that the caller should guess what
it means.

### `load_mask_csv`

*(re-exported from elsewhere; not defined in this module)*

### `MaskRecord`

*(re-exported from elsewhere; not defined in this module)*
