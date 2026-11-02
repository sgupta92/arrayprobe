# API reference: the v3.5 port -- geometry, habit and measurement
> Generated from `src/arrayprobe_uiops`'s own AST; never hand-typed. Regenerate with `docs/_build/apidoc.py`.

The **v3.5 port** -- complete, and the default for new work. Validated at layer 2 only: every routine on the **stock v3.5 path** is asserted against GNU Octave running v3.5's own sources, because no archived campaign product was ever produced by v3.5 and none can be. The ellipse fit included: `iRectEllipse=1` is goldened against the real `CGAL_EllipseSize` binary, compiled under Octave. The opt-in, default-off additions this package carries beyond any tagged UIOOPS release are each proven bit-identical to stock when off and validated against its own named oracle instead of the Octave goldens above; see `TWO_ENGINES.md` §1. One such addition, the mass dispatch in `mass_b26.py`, is not in this release.

**See also** [CLI reference](13-cli-reference.md) · [Reference](08-reference.md).

## `arrayprobe_uiops.__init__`

arrayprobe_uiops -- a Python port of UIOOPS carrying the developers' own fixes

*No public API declared (`__all__` empty or absent).*

## `arrayprobe_uiops.min_circle`

Smallest enclosing circle, v3.5's version -- ``CGAL_minR.cpp`` gained a

### `cgal_min_r_v35`

```python
def cgal_min_r_v35(c: Any, tas_ratio: float) -> tuple[float, float, float]
```

``CGAL_minR(c, tasRatio)`` -- v3.5's 3-output form.

Returns ``(diameter, ctx, cty)`` matching ``imgProc_sm.m``'s own
``tempreturn(1)``/``(2)``/``(3)`` unpacking: ``ctx`` is the enclosing
circle's centre along the (tas-ratio-scaled) **row** axis, ``cty`` along
the (unscaled) **column** axis. ``c`` must be given in the orientation
the MEX itself sees -- rows are diodes, columns are slices; passing the
transpose silently returns the two centres swapped and, whenever
``tas_ratio != 1``, a wrong diameter.

Two edge cases, both taken from the C++ rather than invented -- see the
module docstring for the full derivation:

* **An empty matrix returns (0.0, 0.0, 0.0).** ``CGAL_minR.cpp`` (v3.5)
  tests ``0 == m*n`` and zeroes all three outputs before touching
  Miniball -- the same test v3.1.4 has, extended to the wider output.
* **A non-empty matrix with no shadowed pixel returns
  ``(nan, 0.0, 0.0)``.** Measured on the real ``CGAL_minR.cpp`` rebuilt
  with ``-DNDEBUG``, MATLAB's own ``mex`` release default: ``[NaN 0 0]``,
  exit code 0. The same value the earlier translation returns. A non-NDEBUG
  build halts instead; `NoShadowedPixelsError` stays defined
  for importers and is never raised here (see the module docstring).

### `NoShadowedPixelsError`

```python
class NoShadowedPixelsError(RuntimeError)
```

**Not raised by this module.** It names the
abort a ``CGAL_minR`` built WITHOUT ``-DNDEBUG`` performs on a non-empty
matrix with no shadowed pixel. Built WITH ``-DNDEBUG`` -- MATLAB's own
``mex`` release default -- the same source returns NaN and exits 0, so
`cgal_min_r_v35` returns ``(nan, 0.0, 0.0)`` there instead. Kept
defined so existing importers still resolve. See the module docstring.

## `arrayprobe_uiops.min_ellipse`

``CGAL_EllipseSize(c)`` for v3.5 -- gains centre x/y outputs, drops the

### `cgal_ellipse_size`

```python
def cgal_ellipse_size(c: Any) -> tuple[float, float, float, float, float]
```

``CGAL_EllipseSize(c)`` -- ``(major, minor, angle, x, y)``, v3.5.

No shadowed pixel: ``(0.0, 0.0, 0.0, 0.0, 0.0)``, matching v3.5's own
zero-initialization of all five outputs before the early return
(``CGAL_EllipseSize.cpp:63-64,100-101``) -- unlike v3.1.4's Python port,
which only zero-initializes three outputs because v3.1.4 only computes
three.

## `arrayprobe_uiops.min_rectangle`

Minimum-area enclosing rectangle -- the replacement for ``CGAL_RectSize.mexa64``.

### `cgal_rect_size`

```python
def cgal_rect_size(c: Any) -> tuple[float, float, float]
```

``CGAL_RectSize(c)`` -- ``(length, width, angle)``, diode units / radians.

``length >= width`` always; ``angle`` is the direction of whichever of
the two actual rectangle edges is the longer one -- computed directly
from ``min_area_rectangle``'s own two candidate directions, so this
never needs to reproduce CGAL's internal polygon-edge numbering, only
the final ``(L, W, angle)`` relationship ``CGAL_RectSize.cpp`` itself
exposes.

**A different empty-image convention from** `arrayprobe_uiops.geometry_core.cgal_min_r`:
``CGAL_RectSize.cpp:81-89`` returns ``(0.0, 0.0, 0.0)`` for no shadowed
pixel, not NaN -- confirmed by reading both C++ sources side by side
rather than assuming the two MEX functions agree on this.

### `min_area_rectangle`

```python
def min_area_rectangle(points: Any) -> Any
```

The minimum-area bounding rectangle of an integer point set, exact.

Source: stands in for ``CGAL::min_rectangle_2`` in ``CGAL_RectSize.cpp:96`` (UIOOPS v3.1.4).

Returns ``(along_dx, along_dy, along_len, perp_len)``: ``along_dx``/
``along_dy`` is the (unnormalized) direction of the winning orientation,
``along_len`` the extent along it, ``perp_len`` the extent perpendicular
to it -- both plain floats, the one place a square root happens.
``None`` for an empty point set.

## `arrayprobe_uiops.rect_ellipse`

``imgProc_sm.m:1293-1301,1361-1374`` (v3.5) -- the ``iRectEllipse`` unit (Part D).

### `RectEllipse`

```python
class RectEllipse
```

One particle's ``:1293-1301`` outputs, diode units / radians (unscaled
by ``diode_size`` -- the caller applies that at the ``:1364-1373`` writer,
the same split `arrayprobe_uiops.measure.ParticleMeasurement` uses for
``minR``/``AreaR``/``Perimeter``).

Source: ``imgProc_sm.m:1293-1301`` (UIOOPS v3.5).

### `rect_ellipse_for_image`

```python
def rect_ellipse_for_image(c: Any, *, extended: bool) -> RectEllipse
```

``:1293-1301`` for one particle image ``c``.

Source: ``imgProc_sm.m:1293-1301`` (UIOOPS v3.5).

``extended`` is the recorded ``hasExtendedOutputs`` flag (module
docstring) -- ``True`` selects the 5-output v3.5 ``CGAL_EllipseSize``
schema, ``False`` the 3-output v3.1.4-binary schema a v3.5 run gets when
an old ``.mex`` is on the MATLAB path.

## `arrayprobe_uiops.particle_physics`

Single-particle area, mass, and terminal-velocity relations (UIOOPS v3.5).

### `single_area`

```python
def single_area(diameter: Any, habit: Any, i_new_habit: Any) -> Any
```

Particle cross-sectional area (mm^2) from diameter (cgs, cm), habit code,
and the v3.5 habit-scheme selector.

Direct port of v3.5's single_area.m. Unrecognized habit codes return 0.0,
matching the original's uninitialized-`area`-stays-0 behavior.

### `single_mass`

```python
def single_mass(diameter: Any, habit: Any, i_new_habit: Any) -> Any
```

Particle ice water content / mass (cgs) from diameter, habit code, and
the v3.5 habit-scheme selector.

Direct port of v3.5's single_mass.m. Unrecognized habit codes return 0.0.

### `single_vt`

```python
def single_vt(diameter: Any, area_ratio: Any, mass: Any, pressure_hpa: Any, temp_c: Any, use_mitchell: Any=False) -> Any
```

Terminal fall velocity for a single particle.

Direct port of single_vt.m. Default method is Heymsfield & Westbrook
(2010); pass use_mitchell=True for the Mitchell (1996) method (a
special case of Heymsfield & Westbrook with k=0, drag C=0.6,
epsilon=5.83).

Units, matching the original: diameter/mass in metric (m, kg),
pressure in hPa, temperature in Celsius.

Note: the original hardcodes `pi=3.1415926` as a local variable
(shadowing MATLAB's built-in, full-precision `pi`), rather than
using the built-in constant. That literal is preserved here
deliberately -- swapping in math.pi would be a (tiny) numerical
behavior change from the original, not a pure translation.

## `arrayprobe_uiops.particle`

The particle-image coercion shared by both UIOOPS ports.

### `SHADOWED`

```python
SHADOWED: str
```

### `LIT`

```python
LIT: str
```

### `shadow_mask`

```python
def shadow_mask(c) -> np.ndarray
```

Coerce a particle image to the canonical boolean array (``True`` = shadowed).

Four input forms are recognised, covering everything the pipeline produces:

* a boolean array -- returned as-is (already canonical);
* a string/bytes array -- compared against ``'0'``, the MATLAB char matrix;
* an integer array containing values above 1 -- treated as raw ASCII codes,
  the char matrix as it arrives from a netCDF ``short``/``byte`` variable;
* any other integer array -- treated as 0/1 truth values.

The "above 1" test is what separates the last two cases, and it is decidable
because the two encodings share no values: an ASCII image contains only 48
and 49, a truth image only 0 and 1.  An all-shadowed ASCII image is all 48s,
so its maximum is 48; an all-lit truth image is all 0s.  The one genuinely
ambiguous input is an *empty* array, which both readings send to the same
empty result.

## `arrayprobe_uiops.habit`

Holroyd-family habit classification -- UIOOPS v3.5 (``holroyd.m``,

### `MAX_TWOD_DATA_LENGTH`

```python
MAX_TWOD_DATA_LENGTH: int
```

### `ShapeStatsNew`

```python
class ShapeStatsNew
```

The 16 outputs of the new scheme's ``calc_stat``
(``holroyd_new.m:211-674`` / ``holroyd_new_HVPS.m:172-635``, identical).

Field order follows the MATLAB return list.

### `HolroydNewResult`

```python
class HolroydNewResult
```

The 9 outputs of ``holroyd_new``/``holroyd_new_hvps``, MATLAB order.

Source: the output list of ``holroyd_new.m:7`` (UIOOPS v3.5).

### `ZeroSlicesUnassignedOutputs`

```python
class ZeroSlicesUnassignedOutputs(ValueError)
```

Raised where real MATLAB/Octave errors: a zero-slice call to
``holroyd_new``/``holroyd_new_HVPS`` requesting all 9 outputs.

See the module docstring's "latent arity bug" note. Not a deviation --
MATLAB itself refuses this call with "element number 9 undefined in
return list" (measured under Octave 11.3.0); this is that refusal.

### `holroyd`

```python
def holroyd(image_buffer: Any, probe_resolution: Any, bits_per_slice: Any=None) -> tuple[str, float]
```

``holroyd.m:7-89`` (v3.5) -- classify one particle. Returns
``(holroyd_habit, F_fine_detail)``.

``probe_resolution`` is MATLAB's ``handles.diodesize`` (mm/diode) --
required, no default: v3.5 made this probe-generic where v3.1.4 hardcoded
it, and silently picking a value would be a fidelity decision this module
does not get to make.
``bits_per_slice`` behaves as in
the earlier translation's ``holroyd``: MATLAB's ``handles.bits_per_slice``,
defaulting to the image's own width.

Unlike v3.1.4's ``holroyd.m``, there is no
``parabola_fit_center_is_in`` gate to reproduce -- v3.5 deleted it, so
this function's decision tree runs unconditionally, matching the source.

### `holroyd_new`

```python
def holroyd_new(image_buffer: Any, *, probe_resolution: Any, tas_ratio: Any, bits_per_slice: Any=None) -> HolroydNewResult
```

``holroyd_new.m:7-208`` -- the 2D-S "modified Holroyd" (Schima et al.
2024, doi:10.1029/2024JD040895) scheme. See `holroyd_new_hvps` for the HVPS
variant -- the two are separate MATLAB files with real algorithmic differences, not one
function parameterized by probe (module docstring).

Every keyword is required -- see `holroyd_new_hvps`.

### `holroyd_new_hvps`

```python
def holroyd_new_hvps(image_buffer: Any, *, probe_resolution: Any, tas_ratio: Any, bits_per_slice: Any=None) -> HolroydNewResult
```

``holroyd_new_HVPS.m:7-169`` -- the HVPS "modified Holroyd" scheme.

Every keyword is required -- see `holroyd_new`.

### `calc_stat_new`

```python
def calc_stat_new(image_buffer: Any, bits_per_slice: Any, tas_ratio: Any) -> ShapeStatsNew
```

``holroyd_new.m:211-674`` / ``holroyd_new_HVPS.m:172-635``, identical
(diffed directly to zero) -- the new scheme's shape statistics.

A literal scalar transcription, matching this port's own
``calc_stat_scalar`` in style and intent: correctness first, no
vectorized twin (a future speed-work candidate --
not
attempted here). Python's IEEE-754 float arithmetic reproduces MATLAB's
NaN propagation and NaN-comparisons-are-false semantics directly in a
scalar loop, the same reasoning the v3.1.4 habit module's ``_finish``
documents for its vectorized path; the risky divisions (by ``n_count``,
which is legitimately 0 for an all-background image reaching this
function before the caller's ``area == 0`` guard) are done in
``numpy.float64`` under an ``errstate`` that allows ``0/0 = nan`` and
``c/0 = inf`` rather than Python's ``ZeroDivisionError``.

## `arrayprobe_uiops.measure`

v3.5 ``imgProc_sm.m:1204-1291`` -- the per-particle measurement block.

### `RecordGeometry`

```python
class RecordGeometry
```

The record-level inputs the block reads. Every field is required -- no
default picks a probe or a ``tasRatio`` (no default silently
picks a side).

### `ParticleMeasurement`

```python
class ParticleMeasurement
```

One ``kk`` row of the ``images`` struct, MATLAB field names kept.

Source: the ``images`` fields filled in ``imgProc_sm.m:1204-1291`` (UIOOPS v3.5).

### `RecordMeasurements`

```python
class RecordMeasurements
```

What one record's pass through ``imgProc_sm.m:1204-1291`` (UIOOPS v3.5) leaves behind: the
per-particle measurements, the accumulated ``diode_stats``, the last ``csum`` and the console
warnings. Returned by `measure_record`.

### `STOCK_V35_REJECT_CONFIG`

```python
STOCK_V35_REJECT_CONFIG: RejectConfig
```

### `IMAGE_ASSISTED_V35_REJECT_CONFIG`

```python
IMAGE_ASSISTED_V35_REJECT_CONFIG: RejectConfig
```

### `measure_record`

```python
def measure_record(images: Any, geom: RecordGeometry, reject_config: RejectConfig, *, jit: bool=False) -> RecordMeasurements
```

Run ``:1204-1291`` over the particles of one record, in order.

Source: ``imgProc_sm.m:1204-1291`` (UIOOPS v3.5); bare line references here are into that file.

``images`` is the sequence of per-particle ``c`` matrices (any form
`arrayprobe.particle.shadow_mask` accepts; ``'0'`` / 48 / ``True`` is
shadowed), each ``n_slices x diodenum``. State that persists across ``kk``
-- ``diode_stats``, and the growing ``image_area``/``Perimeter`` vectors
that ``sphericity`` reads -- lives here, which is why the unit is a record
and not a particle.

### `sphericity_mrdivide`

```python
def sphericity_mrdivide(image_area: Any, perimeter: Any, tas_ratio: float) -> float
```

``:1272`` -- ``sqrt(images.image_area/handles.tasRatio)/images.Perimeter``
with BOTH operands the whole 1 x kk row vectors of the record so far.

Source: ``imgProc_sm.m:1272`` (UIOOPS v3.5).

``/`` between two row vectors is MATLAB ``mrdivide``: it solves
``x * b = a`` for the scalar ``x`` in the least-squares sense, i.e. the
slope of ``a`` on ``b`` through the origin. For ``kk == 1`` that is the
plain per-particle ratio; for every later ``kk`` it is not. Preserved.

## `arrayprobe_uiops.tas`

True-airspeed repair and the probe/aircraft TAS ratio (UIOOPS v3.5).

### `AmbiguousFlightTimeError`

```python
class AmbiguousFlightTimeError(ValueError)
```

More than one flight-time row matched one record's timestamp.

Upstream builds a vector ``tasRatio`` here and writes it with a count of
one; what MATLAB does with that is unestablished, so this port refuses
rather than inventing the answer. See `tas_ratio`.

### `Series`

```python
Series: object
```

### `InterpTasError`

```python
class InterpTasError(ValueError)
```

``interp1`` could not run: fewer than two usable TAS nodes.

MATLAB's message is ``interp1: minimum of 2 points required in each
dimension``; Octave's is identical, which is how it was measured.

### `interp_tas`

```python
def interp_tas(tas_values: Series) -> np.ndarray
```

Repair zero/NaN TAS values by linear interpolation over index position.

``read_binary_SPEC.m:453-461``. See this module's docstring for the three
preserved behaviours -- negatives untouched, ends unrepaired, and a raise
below two good nodes.

### `tas_ratio`

```python
def tas_ratio(img_tas: float, flt_time: Series, flt_tas_fixed: Series, hour: int, minute: int, second: int) -> float
```

Probe-to-aircraft TAS ratio for one record, ``read_binary_SPEC.m:176-193``.

``flt_tas_fixed`` is the aircraft TAS series already passed through
`interp_tas`. Returns ``1.0`` -- "assume the probe TAS is correct" --
whenever the aircraft series has nothing usable at this record's time, and
likewise when the probe's own TAS is the ``-999.`` uncorrectable sentinel.

**The date-crossover dummy** (``:177-181``, Finlon 5/13/22): when the flight
time series runs past 240000 and this record's hour is before noon, the
record is looked up at ``hour + 24``. The shifted hour is used for the
lookup only and is never written.

### `update_tas`

```python
def update_tas(tas_temp: TasValue, tas_prev: TasValue, n_hol: int, n_vol: int) -> TasValue
```

The per-record TAS update gate, ``read_binary_SPEC.m:406-414``.

A new reading replaces the running value only when it differs from it and is
not itself suspect: a reading of exactly `SUSPECT_TAS`, or any holdover
or overload count on either channel, keeps the previous value instead.

Returns the TAS to use for this record, which is also the next record's
``tasPrev``. The MATLAB writes ``tasPrev = tas`` only inside the
``tasTemp ~= tasPrev`` branch; when the branch is not taken the two are
already equal, so the single return value here is faithful, not a
simplification.

## `arrayprobe_uiops.particle_perimeter`

Single-particle image perimeter (boundary pixel count).

### `SHADOWED`

```python
SHADOWED: int
```

### `BACKGROUND`

```python
BACKGROUND: int
```

### `particle_perimeter`

```python
def particle_perimeter(image_buffer)
```

Faithful port of ParticlePerimeter.m.

image_buffer: 2D sequence of ASCII codes (int), where SHADOWED (48)
marks a shadowed pixel and any other value is background.

Perimeter = count of shadowed pixels with at least one 4-connected
non-shadowed neighbor (the image is implicitly padded with
BACKGROUND on all sides, matching the original's `c1` padding).

"Any other value is background" is the original's behaviour, not an
interpretation of it: ParticlePerimeter.m tests `48==c1(i,j)` and
nothing else. Checked against MATLAB's own output for a code of 50 in
`tests/test_particle_perimeter_oracle.py`, along with the three
degenerate shapes (0x0, 3x0, 0x5) where a transcription of the
`2:m+1` loops can diverge silently.

### `particle_perimeter_setbased`

```python
def particle_perimeter_setbased(image_buffer)
```

Independent re-derivation of the same quantity, for cross-validation.

Treats shadowed pixels as a coordinate set and counts those with at
least one of their 4 neighbors missing from the set -- neighbors
that fall outside the image bounds count as "missing" too, which
reproduces the original's background-padding behavior without
building an explicit padded array. Written independently from
particle_perimeter() above so that the two implementations agree
only if the underlying logic (not just the code) is correct.

### `particle_perimeter_from_mask`

```python
def particle_perimeter_from_mask(mask)
```

Convenience wrapper: mask is a 2D sequence of bool, True = shadowed.

Source: wraps the port of ``ParticlePerimeter.m:9-22`` (UIOOPS v3.1.4).

## `arrayprobe_uiops.sample_area`

Optical Array Probe sample-area geometry.

### `calc_sa_randombins`

```python
def calc_sa_randombins(bins_mid, res, armdst, num_diodes, sa_method, probetype)
```

OAP sample area (mm^2) per bin, per Heymsfield & Parrish
(1978, 1979 -- see this module's docstring for which is which).

Direct port of calc_sa_randombins.m.

bins_mid  : sequence of bin midpoints, in MILLIMETRES.
res       : photodiode resolution / bin width, microns.
armdst    : probe arm separation, mm.
num_diodes: number of active photodiodes.
sa_method : 0 = center-in, 1 = entire-in, 2 = with correction.
probetype : 2 selects the alternate depth-of-field formula.

Returns a list of sample areas, one per entry in bins_mid.

THE UNITS OF ``bins_mid`` are millimetres, not "photodiode-number
units (not microns -- see original comment)", which is the opposite
of what the only call site passes. ``sizeDist.m:1562``
hands it ``cip2_binmid``, built at ``:1541-1543`` from ``kk``, and
every probe block defines ``kk`` in millimetres -- the 2D-S as
``diodesize/2 : diodesize : ...`` with ``diodesize = .010`` mm, the
HVPS as an explicit micron list divided by 1000. The source's comment
"you can use this one if you provide midpoint in doide number"
describes the *commented-out* ``radius = bins_mid .* res/2``, not the
live ``radius = bins_mid/2``.

Nothing computed changes either way -- the function does arithmetic on
whatever it is handed, which is why the wrong reading survived. What
it would have changed is a caller's. ``tests/test_sample_area_oracle.
SampleAreaUnitsTest`` pins the reading that is dimensionally coherent:
``bins_mid/res`` at ``:29`` is a diode count only if ``bins_mid`` is a
length in mm.

Note: the original MATLAB `switch` has no `otherwise` clause, so an
unsupported sa_method leaves EAWci/EAWri undefined and MATLAB dies at
`:49` with "'EAWri' undefined" (measured under Octave, and recorded in
the oracle bank as a status=ERROR case). This port raises ValueError
explicitly instead -- an intentional, documented deviation, not a
behavior change for any valid input.

## `arrayprobe_uiops.geometry_core`

Shared leaf: the minimum-enclosing-circle helpers both engines use.

*No public API declared (`__all__` empty or absent).*

## `arrayprobe_uiops.habit_core`

Shared leaf: the Holroyd shape statistics both engines use.

*No public API declared (`__all__` empty or absent).*
