# API reference: geometry and per-particle description
> Generated from `src/arrayprobe`'s own AST; never hand-typed. Regenerate with `docs/_build/apidoc.py`.

Shared tooling, readers and the command line. An earlier translation of UIOOPS v3.1.4 reproduced archived products and is not part of this package; its engine modules are not shipped.

**See also** [CLI reference](13-cli-reference.md) · [Reference](08-reference.md).

## `arrayprobe.geometry`

Computational geometry on particle images -- the CGAL MEX replacements.

### `cgal_ellipse_size`

*(defined in `arrayprobe_uiops.geometry_core`, the shared leaf both engines import; documented here, where it is public)*

```python
def cgal_ellipse_size(c) -> tuple[float, float, float]
```

``CGAL_EllipseSize(c)`` -- ``(major, minor, angle)``, diode units / radians.

Same empty-image convention as
`arrayprobe.geometry.min_rectangle.cgal_rect_size` (``CGAL_EllipseSize.cpp:82-89``):
no shadowed pixel returns ``(0.0, 0.0, 0.0)`` directly, not NaN like
`arrayprobe_uiops.geometry_core.cgal_min_r`.

### `cgal_min_r`

*(defined in `arrayprobe_uiops.geometry_core`, the shared leaf both engines import; documented here, where it is public)*

```python
def cgal_min_r(c) -> float
```

``CGAL_minR(c)`` -- the enclosing-circle diameter in diode units.

Two edge cases, both taken from the C++ rather than invented:

* **An empty matrix returns 0.0.**  ``CGAL_minR.cpp:47-52`` tests ``0 == m*n``
  and returns before touching Miniball.
* **A non-empty matrix with no shadowed pixel returns NaN.**  That case falls
  through to Miniball with an empty point range.  The constructor's
  ``assert(points_begin != points_end)`` is compiled out -- MATLAB's ``mex``
  defines ``NDEBUG`` -- so ``pivot_mb`` runs its loop over nothing, leaves
  ``current_sqr_r`` at its initial ``-1`` (``Miniball.hpp:183``), and the
  caller takes ``sqrt(-1)``.  Preserved as NaN rather than "fixed" to 0: a
  zero would be a plausible diameter and would flow silently into
  ``area_ratio`` and the size distribution, where NaN is at least loud.

### `cgal_rect_size`

*(re-exported from elsewhere; not defined in this module)*

### `min_area_ellipse`

*(defined in `arrayprobe_uiops.geometry_core`, the shared leaf both engines import; documented here, where it is public)*

```python
def min_area_ellipse(points)
```

The minimum-area enclosing ellipse of a 2D point set.

Returns ``(major, minor, angle)``: full axis lengths (diameters, not
semi-axes -- matching ``CGAL_EllipseSize.cpp``'s own ``2*sqrt(...)``
convention) with ``major >= minor``, and ``angle`` the major axis's
direction in radians, wrapped to ``(-pi/2, pi/2]`` the way
``CGAL_EllipseSize.cpp:120-124`` does. ``None`` for fewer than 3 points.

**Degenerate point sets -- derived, not measured** (no CGAL to run):

* **All points collinear**: the Khachiyan iteration cannot converge (the
  lifted covariance is singular), so this returns the same "degenerate
  ellipse is the spanning line segment" answer
  `arrayprobe.geometry.min_rectangle.min_area_rectangle` already
  documents for its own 2-point-hull case -- ``minor = 0``, ``major``
  spans the two extreme points, ``angle`` along the line.

### `min_area_rectangle`

*(re-exported from elsewhere; not defined in this module)*

### `min_enclosing_circle`

*(defined in `arrayprobe_uiops.geometry_core`, the shared leaf both engines import; documented here, where it is public)*

```python
def min_enclosing_circle(points)
```

`min_enclosing_circle_exact` as floats: ``(cx, cy, radius)``.

Source: stands in for the Miniball call in ``CGAL_minR.cpp:81-89`` (UIOOPS v3.1.4).

``None`` for an empty point set.

## `arrayprobe.geometry.min_rectangle`

Minimum-area enclosing rectangle -- the replacement for ``CGAL_RectSize.mexa64``.

### `cgal_rect_size`

*(re-exported from elsewhere; not defined in this module)*

### `min_area_rectangle`

*(re-exported from elsewhere; not defined in this module)*

## `arrayprobe.particle`

The canonical in-memory particle image, and the MATLAB char matrix it replaces.

### `SHADOWED`

*(re-exported from elsewhere; not defined in this module)*

### `LIT`

*(re-exported from elsewhere; not defined in this module)*

### `shadow_mask`

*(re-exported from elsewhere; not defined in this module)*

### `as_char`

```python
def as_char(shadow) -> np.ndarray
```

The MATLAB char matrix for a boolean shadow array -- the fidelity view.

Inverse of `shadow_mask` for boolean input.  Serves to read ported code
against the MATLAB it came from, and by tests that need to hand a literal
``'0'``/``'1'`` matrix to a routine.

## `arrayprobe.masks`

Stuck-diode masks: an archived production chain's diode re-illumination.

### `STUCK_FRACTION`

*(re-exported from elsewhere; not defined in this module)*

### `HIGH_FRACTION`

*(re-exported from elsewhere; not defined in this module)*

### `ShadowDiodeMask`

*(re-exported from elsewhere; not defined in this module)*

### `MaskFileError`

```python
class MaskFileError(ValueError)
```

A ``diode.*.mat`` file that cannot be used as a shadow-diode mask.

### `load_shadow_diode_mask`

```python
def load_shadow_diode_mask(path) -> ShadowDiodeMask
```

Read a ``diode.*.mat`` written by ``find_shadow_diodes.m:104``.

### `matlab_mask_filename`

```python
def matlab_mask_filename(flight: str, file: str, orientation: str) -> str
```

``['diode.' flight file '.' orientation '.mat']`` -- imgProc_sm ``:288``.

### `orientation_from_infile`

```python
def orientation_from_infile(infile) -> str
```

``infile(end-4)`` -- the orientation letter in ``...<H|V>.cdf``.

MATLAB indexes the *fifth character from the end*, which for
``base160906064403.V.cdf`` is ``'V'``.  It is a positional index, not a
parse: on any name whose last five characters are not ``X.cdf`` it returns
whatever sits there, and the lookup then quietly finds no file.

### `find_shadow_diode_mask`

```python
def find_shadow_diode_mask(path, flight: str, file: str, infile) -> ShadowDiodeMask | None
```

Reproduce ``if exist([...],'file')==2`` -- returning ``None`` when absent.

``None`` is the honest result: MATLAB's ``else`` branch is empty, so a
missing file means the image is used exactly as decoded and **nothing is
recorded anywhere** to say masking was skipped.  Callers that care must
check for themselves; the archived products cannot be interrogated after the
fact, because the variant writes no attributes.

### `reilluminate`

```python
def reilluminate(c: np.ndarray, diodes) -> np.ndarray
```

``c(:,shadow_diode)='1'`` (extraction ``:290``), through
`arrayprobe_uiops.diode_mask.reilluminate`.

A zero, negative or fractional entry raises `MatlabIndexError`, as
MATLAB does; an index past the last diode widens the image, so
``imgProc_sm.m:272-276``'s width guard fires as in MATLAB.

### `ShadowDiodeSearch`

```python
class ShadowDiodeSearch
```

What one ``find_shadow_diodes(date,time,orientation)`` call computed.

### `ShadowDiodeSearchError`

```python
class ShadowDiodeSearchError(RuntimeError)
```

A ``bin_stats`` input on which ``find_shadow_diodes.m`` dies before saving.

### `find_shadow_diodes`

```python
def find_shadow_diodes(date: str, time: str, orientation: str, *, path, infile=None, write: bool=True, counts: str='lit', slice_total: int | None=None) -> ShadowDiodeSearch
```

Port of ``find_shadow_diodes.m``: find stuck diodes from a first-pass proc.

MATLAB-order arguments -- ``date`` ``'YYMMDD'``, ``time`` ``'HHMMSS'``,
``orientation`` ``'H'``/``'V'`` -- and the MATLAB-order result: 1-based
diode numbers in `ShadowDiodeSearch.shadow_diode`, ready for
``[run].diode_masks`` and `reilluminate`.

``path`` stands in for ``:31``'s hard-coded
``/condo/mcfarq/sid/b/oracles/oracles_20<date>/`` (see
`MATLAB_FIND_SHADOW_DIODES_PATH`), and is used exactly as MATLAB uses
it: glued by string concatenation, so it should end in a separator.  The
input defaults to ``[path 'base' date time '.' orientation '_1.cdf']``
(``:40``); ``infile`` overrides it, for this port's ``proc.*.nc`` names.

**The rule is not the one the file's own header states.**  The header says
"<80% of max count"; the 06/20/2018 note says "<80% of mean count".  The
code does both, depending on a third test:

* ``:66`` -- if any diode reads **above 1.2 x mean** (a diode masked
  in-flight, which reads lit on every slice), those diodes are replaced by
  the array's ``nanmean`` (``:68-69``) and a diode is stuck when it is
  below **0.80 x mean** of the replaced array (``:94``);
* otherwise a diode is stuck when it is below **0.80 x max** (``:97``).

**Polarity.**  The rule is written for **lit** counts (``counts="lit"``, the
default and the production fork's ``bin_stats``).  Stock UIOOPS (v3.1.4 stock
and every v3.5 proc file) writes **shadowed** counts instead
(``imgProc_sm.m`` v3.5 ``:1208,1210``); a caller holding such a file passes
``counts="shadowed"`` and ``slice_total`` (the slice total ``S`` every
diode saw, ``tune.diodes.position_slice_total``) and the counts are
converted as ``lit = S - shadowed`` before the rule runs.  Fed unconverted,
the rule reads the stuck diode as the busiest one and flags nearly
everything else.  ``counts="shadowed"`` without ``slice_total`` raises.

Quirks reproduced, each pinned by a test:

1. **The NaN does not survive.**  ``a`` is int32 (``bin_stats`` is
   ``'int'``), and ``a(ill_diode)=NaN`` stores 0 -- MATLAB's int32(NaN).
   ``nanmean`` therefore sees no NaN and averages the zeros in: the
   replacement value is diluted by ``len(ill_diode)/n`` rather than being
   the mean of the other diodes the comment promises.  Octave does the same.
2. **``0.80*max(a)`` is int32**, rounded half away from zero (integer
   dominance).  For integer ``a`` this can never change a comparison, but
   it is kept as MATLAB computes it.
3. **An empty result is saved as ``diode.<date><time>.<or>empty.mat``**
   (``:105-106``), a name ``imgProc_sm.m:288`` never constructs.
4. **A non-positive array mean kills the run before any save.**  ``:55``'s
   ``ylim([0 1.5*nanmean(a)])`` needs increasing limits, so a proc whose
   ``bin_stats`` is all zero (no particles) or never written ends in an
   error, not an empty mask.  Raised here as
   `ShadowDiodeSearchError`.

Not reproduced: the two ``.jpeg`` figures (``:44-63``, ``:72-91``) -- a
picture is not a computed number; ``arrayprobe diode-masks`` and
``examples/5_data_quality/01_find_stuck_diodes.ipynb`` draw the same counts.

The ``.mat`` holds the whole workspace left by ``:100``'s ``clearvars
-except path orientation shadow_diode date time a``, in MATLAB's ``who``
(alphabetical) order.  ``path`` is saved as the string passed here.

## `arrayprobe.render`

Track V -- particle visualisation. Not a port stage: new capability UIOOPS

### `DRAWABLE_PROBES`

```python
DRAWABLE_PROBES: tuple
```

### `reconstruct_particle_image`

```python
def reconstruct_particle_image(image_ds, proc_ds, particle_index: int, *, probe: str='2DS') -> np.ndarray
```

The boolean ``(n_slices, n_diodes)`` silhouette for one particle.

``image_ds``/``proc_ds`` are open ``netCDF4.Dataset`` handles for the
image file and ``proc.*.nc`` (the *same* flight -- nothing here
checks that they match, since the caller already has both open and a
mismatch would show up immediately as garbage).

``particle_index`` is 0-based into the proc file's particle axis, i.e.
the row index the rest of the proc file's per-particle variables use
directly (``image_width[particle_index]`` etc.).

``probe`` selects the framing ``imgproc`` uses for that probe, read from
`arrayprobe.constants.IMGPROC_CONFIG` rather than restated: 2D-S and
HVPS invert 16-bit words (``65535 - data``, ``:562``); CIP/PIP/Fast2DC use
8-bit words as stored (``:556,:559``). The default is the 2D-S framing, so
a call without ``probe`` draws a 2D-S image; a CIP image needs
``probe="CIP"``, or it comes back as an inverted 128-column picture.

### `particle_info`

```python
def particle_info(proc_ds, particle_index: int) -> dict
```

The per-particle scalars worth showing alongside the image.

### `crop_to_content`

```python
def crop_to_content(c: np.ndarray, pad: int=3) -> np.ndarray
```

``c`` (or its shadowed bounding box plus ``pad`` slices/diodes of
margin on each side), for **display only**.

``reconstruct_particle_image`` is deliberately faithful to what
``imgProc_sm.m:266-268`` actually builds: the full slice window between
consecutive boundary markers, which for a particle immediately after a
fresh record (``position`` resets to 1) or after an unusually large gap
can run hundreds of slices while the particle's own shadow -- what
``image_width``/``image_length`` measure -- occupies a handful of them
near one end. At full scale that renders correctly; shrunk into a
thumbnail, the shadow can fall below a pixel and the particle looks
blank, which is misleading for visual verification even though nothing
about the reconstruction or the accept/reject decision is wrong.

Cropping is presentation only: it never touches ``reconstruct_particle_image``
or any value read from the proc file, and every rejected pixel outside the
returned window was never anything but background in the full array either.
An all-lit (no shadowed pixel) input is returned unchanged, since there is
no content to crop to.

### `render_particle`

```python
def render_particle(image_ds, proc_ds, particle_index: int, ax=None, *, crop: bool=False)
```

One particle's silhouette on a matplotlib Axes, labeled with its reject
code, habit, and min-enclosing-circle diameter. Returns the Figure (a
fresh one if ``ax`` is None) -- so this is equally usable from a CLI
(save the Figure), a notebook (let it auto-display), or assembled into a
contact sheet / HTML gallery (pass an existing ``ax``).

``crop`` (default off, so single-particle/CLI use is unaffected): display
only the shadow's own bounding box plus a small margin, via
`crop_to_content`, for the thumbnail-legibility reason documented
there. Off by default because the full window is sometimes exactly what a
reader wants (e.g. to see how much of a record a particle actually used).

### `render_contact_sheet`

```python
def render_contact_sheet(image_ds, proc_ds, particle_indices, ncols: int=5, *, crop: bool=False)
```

A grid of several particles' silhouettes, one Axes each -- the broader
eyeballed sanity check the plan names as track V's second rendering mode.

``crop``: see `render_particle` -- worth turning on here specifically,
since a contact sheet's whole point is many particles at thumbnail scale,
where an uncropped large-window particle is the most likely to look blank.

### `render_gallery_html`

```python
def render_gallery_html(image_ds, proc_ds, particle_indices, out_path, *, title='Particle gallery', crop: bool=False)
```

A self-contained HTML page, one rendered particle per card, base64-
embedded PNGs -- the third avenue named in the plan (published-artifact
page), usable without a Python environment to view.

``crop``: see `render_particle`.

### `particle_thumbnail_png`

```python
def particle_thumbnail_png(image_ds, proc_ds, particle_index: int, *, crop: bool=True, scale: int=1, probe: str='2DS') -> bytes
```

One particle's shadow as a matplotlib-free PNG.

Wraps `reconstruct_particle_image` and `crop_to_content`
around `_png_bytes`, the same standard-library writer
`render_flight_to_disk` already uses for a whole flight -- pulled
out to a public function so ``arrayprobe.triage_server``'s ``/thumb`` and
``/sheet`` routes can call it directly instead of the much slower
``matplotlib`` path `render_particle` uses (a private ``Figure`` per
request, ~50-75 ms measured -- fine for one particle, the reason a
contact sheet of 200 costs ~10 s).  Byte-for-byte what
``render_flight_to_disk`` writes to disk for the same particle and the
same ``crop``/``scale``.

### `unverified_placeholder_png`

```python
def unverified_placeholder_png(size: int=48) -> bytes
```

A small placeholder PNG for a probe outside `DRAWABLE_PROBES`.

``arrayprobe.triage_server`` serves this from its ``/thumb`` and grid
routes instead of calling `reconstruct_particle_image` (and raising
``ValueError``) for a probe this module has not verified -- see
``DRAWABLE_PROBES``'s own docstring for exactly what is unchecked.
Matplotlib-free, the same as `particle_thumbnail_png`'s own writer
and for the same reason: a flight's contact sheet can ask for hundreds of
these on one page. Text does not fit a bytes-only PNG writer, so this
carries only a visual "this is not the real image" signal (an X in a
bordered box); the actual explanation is text in the surrounding page,
beside wherever this is embedded.

### `grid_shape`

```python
def grid_shape(n: int, max_cols: int=GRID_MAX_COLS) -> tuple[int, int]
```

``(rows, cols)`` for ``n`` panels: 1 x 1 for one, two columns up to four (2 x 2), three
columns beyond. Never one row of more than two panels, so particles stay large.

### `wrap_title`

```python
def wrap_title(text: str, width: int) -> str
```

``text`` with every line wrapped to at most ``width`` characters, keeping the caller's own
line breaks, so a panel title never runs past its panel.

### `record_slice_um`

```python
def record_slice_um(image_ds, proc_ds, particle_index: int, diode_um: float) -> float | None
```

Along-track length of one slice, in micrometres, for the record a particle came from:
``diode_um / tasRatio``, the convention v3.5's own shape statistics use
(``holroyd_new.m`` via ``arrayprobe_uiops.habit.calc_stat_new``: ``tx = i / tas_ratio``).
``None`` when the image file has no usable ``tasRatio`` for that record, so the caller draws
the slice as one diode and says the aspect is not true.

### `particle_grid`

```python
def particle_grid(images, titles=None, *, diode_um: float=10.0, slice_um=None, title_colors=None, suptitle: str | None=None, panel_in: float=3.2, fontsize: float=10.0, crop_pad: int=3, max_cols: int=GRID_MAX_COLS, ring_small: int=0)
```

A review figure: one large panel per particle in a grid (`grid_shape`), each image
cropped to its shadowed pixels plus ``crop_pad`` (`crop_to_content`), drawn with
nearest-neighbour pixels, a scale bar in micrometres and a wrapped title of ``fontsize`` pt.

``images``: boolean ``(n_slices, n_diodes)`` arrays, as `reconstruct_particle_image`
returns. ``slice_um``: the along-track length of one slice, a scalar or one value per image
(see `record_slice_um`); where it is ``None`` a slice is drawn one diode long and the
panel title says "aspect not true". ``ring_small``: circle every 8-connected group of at
most this many pixels, so a single shadowed pixel stays visible at page scale (0: none).
Returns the Figure.

## `arrayprobe.dropsize`

Drop sizing by chord lookup -- a port of ``dropsize.m`` (243 lines).

### `MAX_HORIZONTAL_CHORDS`

```python
MAX_HORIZONTAL_CHORDS: int
```

### `MAX_VERTICAL_CHORDS`

```python
MAX_VERTICAL_CHORDS: int
```

### `HORIZONTAL_CHORDS`

```python
HORIZONTAL_CHORDS: array
```

### `HORIZONTAL_CHORD_ESD`

```python
HORIZONTAL_CHORD_ESD: array
```

### `VERTICAL_CHORDS`

```python
VERTICAL_CHORDS: array
```

### `VERTICAL_CHORD_ESD`

```python
VERTICAL_CHORD_ESD: array
```

### `DIODES_ADDED_TO_LENGTH`

```python
DIODES_ADDED_TO_LENGTH: float
```

### `DIODES_ADDED_TO_HEIGHT`

```python
DIODES_ADDED_TO_HEIGHT: float
```

### `OVERSIZE`

```python
OVERSIZE: float
```

### `DropSize`

```python
class DropSize
```

The seven returns of ``dropsize.m:1``, in MATLAB's order.

Which of them are set depends entirely on how many array edges the image
touches -- an image that touches an edge has an unknown true width, so the
chords that need one are left at their ``:103-108`` initialisers.  Measured
under Octave, with ``.`` for "left at zero":

====================  ======  ==========  ========  =======  ==========  ========
branch                axis_r  circle_fit  horiz_ch  vert_ch  horiz_mean  spheroid
====================  ======  ==========  ========  =======  ==========  ========
``image_area < 1``    1.0     .           .         .        .           .
2 edges, centre in    .       set         set       .        .           .
2 edges, centre out   .       set         .         .        .           .
1 edge, centre in     .       set         set       .        .           .
1 edge, centre out    .       set         .         .        .           .
0 edges               set     set         set       set      set         set
====================  ======  ==========  ========  =======  ==========  ========

So ``axis_ratio`` is zero for every particle that touches an edge, and 1.0
-- not zero -- for a particle too small to size.  Downstream code that reads
it as a shape statistic is reading a branch indicator most of the time.

### `dropsize`

```python
def dropsize(max_horizontal_length, max_vertical_length, image_area, largest_edge_touching, smallest_edge_touching, diode_size, corrected_horizontal_diode_size, number_diodes_in_array)
```

``dropsize.m:1-187``.  Equivalent-volume-sphere sizing for liquid drops.

Parameters mirror MATLAB's argument order exactly.  All are doubles at the
call site -- they come from ``calculate_reject_unified``'s returns, which are
counts and sums over a char matrix -- so none of the int16 traps that bite
``sizeDist.m:882-890`` apply here.

Parameters
----------
max_horizontal_length:
    ``images.image_length`` -- slices spanned, i.e. along-flight extent.
max_vertical_length:
    ``images.longest_y_within_a_slice`` -- the longest run of shadowed
    diodes inside any one slice.
image_area:
    Shadowed pixel count.  Below 1 the function returns early.
largest_edge_touching, smallest_edge_touching:
    ``max`` and ``min`` of the top- and bottom-edge contact lengths
    (``imgProc_sm.m:828-829``).  The ordering is what makes ``:143`` dead.
diode_size, corrected_horizontal_diode_size:
    Both ``handles.diodesize`` at both call sites, so their ratio is 1.0 in
    every real run.  See "Latent defects" in the module docstring for what
    happens when it is not.
number_diodes_in_array:
    ``diodenum``.  Used only by the two-edge circle fit.

Returns
-------
DropSize
    Unpackable in MATLAB's return order.

### `horizontal_chord_to_spherical_dia`

```python
def horizontal_chord_to_spherical_dia(horizontal_chord)
```

``dropsize.m:212-229``.  See `_chord_to_spherical_dia`.

### `vertical_chord_to_spherical_dia`

```python
def vertical_chord_to_spherical_dia(vertical_chord)
```

``dropsize.m:192-209``.  See `_chord_to_spherical_dia`.
