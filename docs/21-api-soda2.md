# API reference: the SODA-2 port
> Generated from `src/arrayprobe_soda2`'s own AST; never hand-typed. Regenerate with `docs/_build/apidoc.py`.

The **SODA-2 port** -- NCAR's IDL chain, a third and independent processing lineage rather than a UIOOPS variant, and an engine on equal footing with UIOOPS v3.5. Its differential oracle is GDL. The SPEC path is ported from raw bytes to written output: the buffer decode (`spec_decompress`, `spec_readint`, `spec_read_frame`, `spec_read_hk`, `spec_index`, `spec_absolutepointers`); the driver's pre-loop (`hms2sfm`, `soda2_parsedate`, `soda2_update_op`, `soda2_buildindex`, `soda2_read2dbuffer`, `spec_process_hk` versions 1 and 2, `spec_index_hk`); `soda2_processbuffer.pro` end to end (`processbuffer_spec` and the shared per-particle tail, `processbuffer_tail`); the particle path (sample area, the geometry core, sizing and rejection); the per-second accumulation (`particlesort`, `fit_poisson`); the driver itself (`process_2d`); the `.pbp.csv` and `.pbp.nc` per-particle writers (`pbp_writer`); the ASCII size-distribution export (`export_ascii`, turned on by `asciipsdfile`); the IDL SAVE file (`save_writer`, `savfile`); and the ASCII/CSV/netCDF PTH (true-airspeed) readers (`pth_readers`), wired into `process_2d`; and reprocessing from an existing `.pbp.nc` (`fn_pbp`, `reprocess_pbp`), library-only. `arrayprobe soda2 run <config>` drives it from a `[soda2]` run configuration and writes a `.pbp.call` sidecar. The driver takes three `op.format` families: SPEC; DMT CIP (PIP included) in SEA or DMT framing (`processbuffer_cip`, `decompress_dmt`, `sea`, GDL-validated), with the CIP 1-D housekeeping route (`process_cip1d_sea`) when `seatag` has two or more elements; and RAF Fast-2DC, probetypes `F2DC` and `F2DC_v2` (`processbuffer_f2dc`), serial only, because the `f2d_remainder` carry crosses buffers; on a real CAESAR 2024 file its output is identical to `soda2_process_2d.pro` under GDL in all eight fields compared (`tests/test_soda2_raf_realfile_gdl.py`). Any other `op.format` raises, as does any other probetype within a family: SEA CIPG, 2DC, 1D2D, HVPS and HAIL; DMT CIPG; RAF 2DC, HVPS1 and F2DC66. The HVPS-4 and 3VCPI/Hawkeye SPEC subformats (1 and 2) decode through `hvps4_read_frame` and `spec_read_frame`'s version-1 path, checked against GDL on synthetic buffers only. Particle-image output (`ncdfparticlefile` 2) runs on the serial driver and is refused with `jobs > 1`; several raw files per run are indexed and concatenated for the SEA, DMT and RAF formats on the serial driver, while SPEC stops on the second file as `soda2_process_2d.pro:376` does. `soda2_export_ncdf.pro` is ported and GDL-banked (`export_ncdf`), as is its NCAR-RAF sibling `soda2_export_ncdf_raf.pro` (`export_ncdf_raf`); neither has a driver call site to wire -- the original `soda2_process_2d.pro` never calls either. Cite SODA-2 as: Aaron Bansemer. (2026). abansemer/soda2: v2.26.0 (Version v2.26.0) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.18331418

**See also** [CLI reference](13-cli-reference.md) · [Reference](08-reference.md).

## `arrayprobe_soda2.__init__`

arrayprobe_soda2 -- a from-source Python port of SODA-2's OAP processing.

### `angles`

*Submodule -- `arrayprobe_soda2.angles`, documented below.*

### `aspect_ratio`

*Submodule -- `arrayprobe_soda2.aspect_ratio`, documented below.*

### `binary_dof`

*Submodule -- `arrayprobe_soda2.binary_dof`, documented below.*

### `buildindex`

*Submodule -- `arrayprobe_soda2.buildindex`, documented below.*

### `find_radius`

*Submodule -- `arrayprobe_soda2.find_radius`, documented below.*

### `findsize`

*Submodule -- `arrayprobe_soda2.findsize`, documented below.*

### `fillholes`

*Submodule -- `arrayprobe_soda2.fillholes`, documented below.*

### `fixraking`

*Submodule -- `arrayprobe_soda2.fixraking`, documented below.*

### `fixstuckbits`

*Submodule -- `arrayprobe_soda2.fixstuckbits`, documented below.*

### `label_blobs`

*Submodule -- `arrayprobe_soda2.label_blobs`, documented below.*

### `min_circle_fast`

*Submodule -- `arrayprobe_soda2.min_circle_fast`, documented below.*

### `poisson_spot_correct`

*Submodule -- `arrayprobe_soda2.poisson_spot_correct`, documented below.*

### `fit_poisson`

*Submodule -- `arrayprobe_soda2.fit_poisson`, documented below.*

### `particlesort`

*Submodule -- `arrayprobe_soda2.particlesort`, documented below.*

### `princomp`

*Submodule -- `arrayprobe_soda2.princomp`, documented below.*

### `process_2d`

*Submodule -- `arrayprobe_soda2.process_2d`, documented below.*

### `process_hk`

*Submodule -- `arrayprobe_soda2.process_hk`, documented below.*

### `processbuffer_spec`

*Submodule -- `arrayprobe_soda2.processbuffer_spec`, documented below.*

### `read2dbuffer`

*Submodule -- `arrayprobe_soda2.read2dbuffer`, documented below.*

### `processbuffer_tail`

*Submodule -- `arrayprobe_soda2.processbuffer_tail`, documented below.*

### `reject`

*Submodule -- `arrayprobe_soda2.reject`, documented below.*

### `sample_area`

*Submodule -- `arrayprobe_soda2.sample_area`, documented below.*

### `spec_absolutepointers`

*Submodule -- `arrayprobe_soda2.spec_absolutepointers`, documented below.*

### `spec_decompress`

*Submodule -- `arrayprobe_soda2.spec_decompress`, documented below.*

### `spec_index`

*Submodule -- `arrayprobe_soda2.spec_index`, documented below.*

### `spec_read_frame`

*Submodule -- `arrayprobe_soda2.spec_read_frame`, documented below.*

### `spec_read_hk`

*Submodule -- `arrayprobe_soda2.spec_read_hk`, documented below.*

### `spec_readint`

*Submodule -- `arrayprobe_soda2.spec_readint`, documented below.*

### `timeconv`

*Submodule -- `arrayprobe_soda2.timeconv`, documented below.*

### `update_op`

*Submodule -- `arrayprobe_soda2.update_op`, documented below.*

## `arrayprobe_soda2.sample_area`

SODA-2 sample area — a port of ``soda2_samplearea.pro``.

### `EAW_METHODS`

```python
EAW_METHODS: tuple
```

### `UnsupportedSampleVolumeMethod`

```python
class UnsupportedSampleVolumeMethod(ValueError)
```

Raised where ``soda2_samplearea.pro`` reaches its ``stop`` statement.

See this module's docstring: IDL's ``stop`` is an interactive debugger
halt, so this exception is a deliberate divergence, not a reproduction.

### `sample_area`

```python
def sample_area(diam: ArrayLike, res: Any, armwidth: Any, numdiodes: Any, eawmethod: str, wavelength: Any, dofconst: Any=0.0, dof: ArrayLike | None=None) -> tuple[NDArray[Any], NDArray[Any], NDArray[Any]]
```

Sample area in m^2, per ``soda2_samplearea.pro``.

Returns ``(sa, dof, eff_wid)``. The IDL returns ``sa`` and passes ``dof``
and ``eff_wid`` back through keyword outputs; a tuple is the Python
equivalent, and callers that want only the area take ``[0]``.

Units, as the IDL's own header states them: ``diam`` in micrometres,
``res`` in micrometres, ``armwidth`` in centimetres, ``wavelength`` in
metres. The returned ``dof`` is in micrometres and ``sa`` in m^2.

``dofconst=0.0`` means "not specified in the original op structure" and
selects the literature default, exactly as the IDL's ``IF dofconst eq 0``
does -- zero is a sentinel here, not a value.

``dof=None`` (or an all-zero array) means "compute it", mirroring the
source's ``IF total(dof) eq 0`` test. Note that test is on the *total*:
a caller supplying a mixed array of zeros and non-zeros gets the whole
array kept, not the zeros filled in. Preserved as written.

## `arrayprobe_soda2.min_circle_fast`

``min_circle_fast.pro`` -- SODA-2's minimum-enclosing-circle routine.

### `PI_SINGLE`

```python
PI_SINGLE: float
```

### `HALF_PI_SINGLE`

```python
HALF_PI_SINGLE: float
```

### `ITERATION_CAP`

```python
ITERATION_CAP: int
```

### `MinCircle`

```python
class MinCircle
```

The IDL anonymous structure ``{diam, center, corners, area}``.

``diam`` is a **diameter** (the source's own comment: ``;RETURNS
*DIAMETER*``). ``corners`` is 0-based indices into ``xin``/``yin`` in the
order the IDL builds them -- ``[P, Q]``, ``[P, Q, R]``, or the fallback's
``[i_max, i_min]`` -- consumed by ``aspect_ratio.pro:27-49`` for both its
branch and its orientation sign. ``area`` is ``len(xin)``, not a
geometric area; kept under this name because ``soda2_findsize.pro:34``
reads it as ``circle.area``.

### `Trace`

```python
class Trace
```

What the IDL computes but never returns -- exposed additively.

``niter`` is the number of times the ``REPEAT...UNTIL`` body ran (so
``ITERATION_CAP + 1`` marks a capped run); ``hit_cap`` and ``fell_back``
name the two mechanisms SODA-2 register entry S2-h found to be one (the fallback's
``finite()`` test at ``:64`` is, for finite duplicate-free input, only
ever reached after the cap); ``q0`` is the initial ``Q`` chosen at
``:21``, before any swap.

### `MinCircleCapWarning`

```python
class MinCircleCapWarning(UserWarning)
```

Opt-in only (see ``warn_on_cap``): the 10001-iteration cap was hit.

The IDL emits nothing here -- no flag, no message -- so a warning is
itself a behaviour change relative to the source, and this project's own
tests run degenerate inputs under ``warnings.simplefilter("error")``,
where a warning becomes an exception the IDL never raises. Silent by
default; see `min_circle_fast_traced` for the always-on channel.

### `EmptyInput`

```python
class EmptyInput(ValueError)
```

``xin``/``yin`` had zero elements.

The IDL has no explicit guard for this: ``min(y, P)`` on an empty array is
itself an IDL error, so there is no return value from the original to
reproduce here -- raising is the port's own choice, not a translated one.

### `min_circle_fast`

```python
def min_circle_fast(xin: ArrayLike, yin: ArrayLike, *, warn_on_cap: bool=False) -> MinCircle
```

``min_circle_fast(xin, yin)`` -- SODA-2's minimum bounding circle.

Source: ``min_circle_fast.pro`` (SODA-2).

``warn_on_cap`` is an opt-in flag, **defaulting OFF** per this project's
fidelity doctrine: the IDL returns whatever it holds at the 10001st
iteration with no signal at all, so silence is the faithful default. When
``True`` and the cap was hit, emits `MinCircleCapWarning`; it
changes no returned field (pinned by a silent-by-default test).

### `min_circle_fast_traced`

```python
def min_circle_fast_traced(xin: ArrayLike, yin: ArrayLike, *, _angle_at_q: Callable[..., float] | None=None) -> tuple[MinCircle, Trace]
```

``min_circle_fast(xin, yin)`` plus everything the IDL computes but
discards on return -- see `Trace`. `min_circle_fast` is a
thin wrapper that keeps only the first element.

Source: ``min_circle_fast.pro`` (SODA-2).

Degenerate arithmetic (``0.0/0.0``, ``x/0.0``) is kept in numpy scalars
throughout, never a bare Python ``float`` division -- ``x / 0.0`` on a
Python ``float`` raises ``ZeroDivisionError`` where IDL, and numpy, yield
``inf``/``nan``. Those values are the behaviour being ported: the fallback
at ``:64`` branches on exactly this.

``_angle_at_q`` is a **private, test-only** hook (default
`~arrayprobe_soda2.angles.find_angle`, matching ``:33`` exactly).
It exists only so a formula-pairing
search can pass `~arrayprobe_soda2.angles.find_angle_array` instead,
wrapped to the same ``(p1, p2, p3)`` calling convention, to look for a
case where the formula pairing of SODA-2 register entry S2-a changes
which ``corners`` come back.
`min_circle_fast` never sets it.

## `arrayprobe_soda2.angles`

``find_angle.pro`` and ``find_angle_array.pro`` -- SODA-2's two angle routines.

### `NotDoublePrecision`

```python
class NotDoublePrecision(RuntimeError)
```

``find_angle_array.pro``'s own type guard reached. It ``stop``s rather
than returning, so there is no value for the port to produce.

### `find_angle`

```python
def find_angle(p1: ArrayLike, p2: ArrayLike, p3: ArrayLike) -> float
```

``find_angle(p1, p2, p3)`` -- the angle at ``p1``, by the dot product.

Source: ``find_angle.pro`` (SODA-2).

``p1``/``p2``/``p3`` are 2-element ``[x, y]``. NaN for coincident points;
exactly 0 for an angle too thin for ``acos`` to resolve. See the module
docstring — do not substitute `find_angle_array` here.

### `find_angle_array`

```python
def find_angle_array(x1: ArrayLike, y1: ArrayLike, x2: ArrayLike, y2: ArrayLike, x3: ArrayLike, y3: ArrayLike) -> float | np.ndarray
```

``find_angle_array(x1, y1, x2, y2, x3, y3)`` -- the angle at
``(x1, y1)``, by the law of cosines. ``x1``/``y1`` may be arrays.

Source: ``find_angle_array.pro`` (SODA-2).

Raises `NotDoublePrecision` for a non-floating input, reproducing the
source's own ``typename(x1) ne 'DOUBLE'`` guard. Integer input is refused
rather than silently promoted: IDL would have halted, and promoting it here
would answer a question the original refuses to answer.

## `arrayprobe_soda2.find_radius`

``find_radius.pro`` -- Goldman's circumradius, and the degenerate value

### `Circle`

```python
class Circle
```

``{r: ..., center: ...}`` -- the IDL anonymous structure this returns.

Source: the return structure of ``find_radius.pro`` (SODA-2).

``r`` is a **radius**; note that ``min_circle_fast`` doubles it on the way
out and its own return field is named ``diam``.

### `find_radius`

```python
def find_radius(p1: ArrayLike, p2: ArrayLike, p3: ArrayLike) -> Circle
```

``find_radius(p1, p2, p3)`` -- circumradius and centre of three points.

Source: ``find_radius.pro`` (SODA-2).

Each point is 2-element ``[x, y]``. Degenerate inputs return ``inf`` or
``nan`` rather than raising, exactly as the IDL does — see the module
docstring for the four measured regimes, and note that the caller's own
comment about which one occurs is wrong.

## `arrayprobe_soda2.princomp`

``princomp.pro`` -- SODA-2's orthogonal ("principal components") line fit.

### `PrincompLengthMismatch`

```python
class PrincompLengthMismatch(RuntimeError)
```

``princomp.pro``'s own length check reached: it prints
``** Error: x and y arrays not the same length`` and then ``stop``, which
halts IDL rather than returning. Raised here for the same reason the v3.5
port raises on ``CGAL_minR``'s abort: the original does not produce a value
on this path, so neither may the port.

### `princomp`

```python
def princomp(x: ArrayLike, y: ArrayLike) -> tuple[np.ndarray, float]
```

``c = princomp(x, y, corr)`` -- returns ``(c, corr)``.

Source: ``princomp.pro`` (SODA-2).

IDL's third argument is a pass-by-reference **output**; Python has no such
thing, so it is returned alongside ``c`` rather than mutated into a caller's
variable.

Arithmetic is float64 throughout, matching ``dblarr(2)`` and the
``total()`` calls on doubled inputs. Division by zero is left to IEEE --
see the module docstring for the four measured outcomes.

## `arrayprobe_soda2.aspect_ratio`

``aspect_ratio.pro`` -- SODA-2's rotation-invariant aspect ratio, the last

### `ERODE_EDGE_RULE`

```python
ERODE_EDGE_RULE: str
```

### `AspectRatioResult`

```python
class AspectRatioResult
```

Everything ``aspect_ratio.pro`` returns, keyword outputs included.

``circle`` is whatever `arrayprobe_soda2.min_circle_fast.min_circle_fast`
returns -- an object or mapping with ``diam``, ``center`` (2-element) and
``corners`` (2 or 3 zero-based indices into ``x_ind``/``y_ind``).
``y_ind`` is the **unadjusted** indices, exactly as IDL's ``y_ind_orig``
keyword output is (:74 in the source): the TAS correction is applied to a
local copy only, and the keyword hands back the copy made before that.

### `MinCircleFastNotPorted`

```python
class MinCircleFastNotPorted(ImportError)
```

``arrayprobe_soda2.min_circle_fast`` has not landed yet (a concurrent
pair owns that port). Raised lazily, at call time, so importing this
module never requires it -- only calling `aspect_ratio` does.

### `aspect_ratio`

```python
def aspect_ratio(img_or_coords: np.ndarray, *, tas_adjust: Any=None, coordinates: bool=False, edge_rule: str | None=None) -> AspectRatioResult
```

``aspect_ratio.pro``, whole routine (minus the ``makeplot`` block).

``coordinates=True``: ``img_or_coords`` is an ``(n, 2)`` array of
``[x, y]`` integer coordinates (lines 19-21) rather than an image.

``tas_adjust`` selects IDL's own type behaviour by the *type of the
Python value passed*, mirroring what a caller in IDL would have to do
with a literal: ``None`` means the keyword was never supplied (line 24's
``n_elements(tas_adjust) gt 0`` is false), so ``y_ind`` stays whatever
integer/float type it already was; ``np.float32`` gives FLOAT, which is
what the real production caller passes
(``soda2_findsize.pro:30``, ``tas_adjust=yres/xres`` where both are FLOAT
fields); any other floating value -- a bare Python ``float`` or
``np.float64`` -- is treated as DOUBLE, exactly as IDL would treat a
``0.5d`` literal. **A bare Python float is therefore not "whatever is
convenient" here: it silently selects DOUBLE**, so a caller wanting to
reproduce the production path must pass ``np.float32(yres / xres)``
explicitly, not a plain float that happens to equal it.

The enclosing circle comes from ``arrayprobe_soda2.min_circle_fast``
(ported; checked against GDL by a test that is not part of this package), imported lazily. The
``except ImportError`` branch that raises `MinCircleFastNotPorted`
is unreachable in a complete install and is kept so an old import of the
exception does not break.

### `axis_and_ratio`

```python
def axis_and_ratio(x_ind: np.ndarray, y_ind_adjusted: np.ndarray, circle: Any) -> tuple[np.float64, np.float32]
```

``aspect_ratio.pro`` lines 27-73 and 105, given an already-computed
``circle``. Returns ``(aspr, orientation)``.

``circle`` needs ``corners`` (2 or 3 zero-based indices into ``x_ind`` /
``y_ind_adjusted``), ``center`` (2-element, DOUBLE in the source) and
``diam`` (DOUBLE); see `_field` for the attribute-or-mapping
accessor that lets this take either a real ``min_circle_fast`` result or
a ``SimpleNamespace``/``dict`` built straight from the GDL golden.

**Dtype.** ``y_ind_adjusted``'s own dtype is IDL's "Ty": ``int32`` if no
TAS correction was applied, ``float32`` in production
(``tas_adjust`` is a FLOAT keyword), ``float64`` only if a caller passes a
genuine DOUBLE. In the 2-point branch, ``a`` (``cy1-cy2``) and the running
sums stay in Ty; ``b`` (``cx2-cx1``) is always ``int32`` (``x_ind`` is
always LONG) but gets promoted to Ty the moment it multiplies against a
Ty operand, via `_op`/`_idl_promote` rather than NumPy's own
(wider) promotion. In the 3-point branch ``cx2``/``cy2`` come from
``circle.center``, which is DOUBLE, so **everything** downstream --
``a``, ``b``, ``c``, ``den``, ``distmajor`` -- ends up ``float64``
regardless of Ty; this falls out of `_idl_promote` automatically
once ``cx2``/``cy2`` are cast to ``float64`` up front, with no separate
branch needed. ``aspr`` is always returned as ``float64`` (``circle.diam``
is DOUBLE, so ``width / (diam + 1)`` is DOUBLE regardless of ``width``'s
own dtype).

**The two clamps.** ``den = sqrt(a^2+b^2) > 1`` (MAX) and the final
``return, aspr < 1.0`` (MIN) are both written as a Python ternary
(``x if x > floor else floor`` / ``x if x < ceiling else ceiling``) rather
than ``max``/``min``, because Python's comparison operators already give
``False`` for a NaN operand, which is exactly IDL's own measured
behaviour for ``<`` (SODA-2 register entry S2-d: ``!values.d_nan < 1.0d`` is ``1.0`` under
GDL) -- so the *ternary form* reproduces the NaN case for free, where
calling ``min()``/``max()`` would not reliably. The ``>`` side is written
the same way for consistency; only the ``<`` case has actually been
measured against real IDL/GDL.

### `orientation_deg`

```python
def orientation_deg(cx1: Any, cy1: Any, cx2: Any, cy2: Any) -> np.float32
```

``aspect_ratio.pro`` lines 53 and 57: orientation in degrees.

``atan(float(cy2-cy1), float(cx2-cx1)) * 180/!pi``, then folded to
``(-90, 90]`` by ``((orientation - 360 - 90) mod 180) + 90``.

Each difference is computed at its *native* precision first (whatever
dtype the caller's ``cx1``/``cy1``/``cx2``/``cy2`` actually carry -- the
only mixing that ever occurs here is with ``float64``
(`axis_and_ratio`'s 3-point branch, via ``circle.center``), which
NumPy promotes to unambiguously, exactly as IDL would) and *then*
narrowed to ``float32`` with an explicit cast -- mirroring IDL's
``float(cy2-cy1)``, which narrows after subtracting, not before. ``!pi``
is IDL's **single-precision** pi (measured under GDL:
``3.1415927410125732``, not ``3.141592653589793``); ``!dpi`` is never used
in this tree. ``np.fmod``, not Python's ``%``, for the ``mod`` at line 57
-- IDL's ``mod`` takes the dividend's sign, and ``np.fmod`` does too.

### `outline_indices`

```python
def outline_indices(img: np.ndarray, *, edge_rule: str | None=None) -> tuple[np.ndarray, np.ndarray, int]
```

``aspect_ratio.pro`` lines 11-17: outline pixel indices of an image.

``img`` is ``(n_slices, n_diodes)`` -- y (along airflow) first, x (across
the array) second, matching how this port holds every other SODA-2/UIOOPS
image. IDL's array is column-major with x as dimension 1, so its flat
``where`` index order (x fastest) is exactly this array's C-order
``ravel()`` -- **this equivalence is load-bearing** for
``min_circle_fast``'s tie-breaking on the returned index order, so it is
asserted directly by ``OutlineAndIndexOrderMatchIdl`` rather than only
implied by matching final answers.

A 1-D ``img`` is treated as a single slice (no erosion), which is also
what IDL does here, but not for the reason it looks like: after
``img = byte(img_in)``, IDL's ``size(img)`` for a 1-D array is
``[1, n, type, n_elements]``, so ``s[2]`` is the **type code** (1, for
BYTE), never the y-dimension, and 1 is never greater than 2. The outline
step is skipped by coincidence, not by an explicit 1-D branch -- SODA-2
register entry S2-g. It is harmless in production because ``soda2_findsize.pro`` reforms
1-D images before calling this routine.

Returns ``(x_ind, y_ind, area)``, both ``int32``. An image with nothing
shadowed returns exactly ``([-1], [0], 0)`` -- IDL's ``where`` returns the
scalar ``-1`` with count 0 on no match, and ``-1 mod nx`` keeps the
dividend's sign (stays ``-1``) while IDL's ``/`` truncates toward zero
(``-1/nx`` is 0 for any ``nx > 1``), not the floor NumPy's ``//`` would
give.

## `arrayprobe_soda2.findsize`

``soda2_findsize.pro`` -- every size SODA-2 reports, from one silhouette.

### `RESHAPES_CALLER_INPUT`

```python
RESHAPES_CALLER_INPUT: bool
```

### `FindSizeResult`

```python
class FindSizeResult
```

``soda2_findsize.pro``'s predefined output structure (``:9-10``), field
for field and in declaration order.

The declared types are part of the contract and are reproduced: the seven
sizes and ``ar``/``arfilled``/``aspr``/``orientation`` are declared
``0.0`` (FLOAT); ``perimeterarea`` is ``0L`` (LONG); ``allin``,
``centerin`` and ``edgetouch`` are BYTE; ``c`` is ``fltarr(2)``.

### `soda2_findsize`

```python
def soda2_findsize(img: Any, xres: Any, yres: Any, voidarea: Any=0) -> FindSizeResult
```

``out = soda2_findsize(img, xres, yres, voidarea=voidarea)``.

Source: ``soda2_findsize.pro`` (SODA-2).

``img`` is a binary silhouette indexed ``[diode, slice]``, matching IDL's
``img[x, y]``. ``xres`` and ``yres`` are micrometres per pixel along the
diode and slice axes.

**Pass FLOAT resolutions.** An integer ``xres``/``yres`` reproduces IDL's
integer division at ``:11`` and can zero every returned size without
error (SODA-2 register entry S3-d), and the reason the type of these two arguments is
respected rather than coerced.

## `arrayprobe_soda2.fixraking`

SODA-2 ``fixraking.pro:1-67`` -- reconstruct raked images (every other

### `FixrakingIncompatibleDimensions`

```python
class FixrakingIncompatibleDimensions(ValueError)
```

``fixraking.pro:57``: ``convol`` of a 1-D image with the 3x3 kernel;
GDL halts with ``CONVOL: Incompatible dimensions for Array and Kernel``.

### `FixrakingUndefinedKernel`

```python
class FixrakingUndefinedKernel(RuntimeError)
```

``fixraking.pro:43-57``: ``type >= 4`` (``modetype >= 7``) enters the
convolution block with ``kernel`` never assigned; IDL halts at ``:57``.

### `fixraking`

```python
def fixraking(image: np.ndarray, modetype: int) -> np.ndarray
```

``fixraking.pro:1-67``. ``image`` is ``[diode, slice]``.

## `arrayprobe_soda2.fixstuckbits`

``fixstuckbits.pro`` -- work around bits stuck 'on' in an OAP image

### `NoStuckBitsHalt`

```python
class NoStuckBitsHalt(RuntimeError)
```

``fixstuckbits.pro:17-20`` -- when no diode crosses the threshold
and the image has **fewer than 8 diodes**, IDL's scalar index ``-8``
(the where() sentinel ``-1`` minus ``pad=7``) falls outside the array
and GDL halts: ``% FIXSTUCKBITS: Subscript out of range [-i]``
(measured on a 5-diode image). This is the genuine-halt half of SODA-2 register entry S4-x;
for 8 or more diodes, ``-8`` is a valid negative index and the
routine silently corrupts diode column ``n - 8`` instead -- see the
module docstring and the non-halting half of that entry.

### `fixstuckbits`

```python
def fixstuckbits(image: np.ndarray, h: np.ndarray | None=None) -> np.ndarray
```

``fixstuckbits(image, h=h)`` (``fixstuckbits.pro:8-29``).

``image`` is a 2-D array, diode axis first (axis 0), matching
``findsize.py`` / ``processbuffer_spec.py``'s ``[x, y]`` convention.
``h`` is an ``intarr`` (``(*pmisc).lastdhist``) at the one call site
that supplies it; when omitted, ``h = total(image, 2)`` (a per-column
sum over slices).

Raises `NoStuckBitsHalt` where IDL itself would halt (SODA-2 register entry S4-x),
rather than silently returning ``image`` unchanged.

The input is never mutated; the return is always a fresh array.

## `arrayprobe_soda2.label_blobs`

``label_blobs.pro`` -- label connected blobs in a binary image, working

### `label_blobs`

```python
def label_blobs(img: np.ndarray, dilatelength: int=0, all_neighbors: bool=False, integer: bool=False, jit: bool=False) -> np.ndarray
```

``label_blobs(img, dilatelength=dilatelength,
all_neighbors=all_neighbors, integer=integer)``
(``label_blobs.pro:9-29``).

``all_neighbors`` is this port's name for IDL's ``/all`` keyword
(passed through ``_EXTRA`` to ``label_region``'s ``ALL_NEIGHBORS``).
Accepts and returns 1-D input for a 1-D ``img`` (``:13``). Returns
``uint32`` labels when ``integer=True``, else ``uint8`` (**wraps at
256 blobs, modulo; SODA-2 register entry S4-y**, ``:29``).

``jit``
    Speed only, **default off** (space: the port --
    a profile found
    `_label_region` the single hottest leaf in a real SODA-2 run,
    ~24-28 %). ``True`` routes `_label_region` through
    `arrayprobe_soda2.jit_kernels`'s numba flood fill, exact by
    construction, so the array returned is the same bytes
    (``tests/test_soda2_label_region_jit_identity.py``). Needs numba,
    imported only here, never by ``import arrayprobe_soda2``. Not IDL's.

## `arrayprobe_soda2.jit_kernels`

SODA-2's opt-in accelerated kernel -- ``label_blobs(..., jit=True)``.

### `JitKernels`

```python
class JitKernels
```

The compiled kernel, and the drop-in function ``label_blobs`` calls
through.

### `load`

```python
def load() -> JitKernels
```

Import numba and compile (or load from cache) the kernel, once per
process.

## `arrayprobe_soda2.reject`

``soda2_reject.pro`` -- SODA-2's per-particle accept/reject decision.

### `EAW_METHODS`

```python
EAW_METHODS: tuple
```

### `Particle`

```python
class Particle
```

The tags of ``soda2_readpbp``'s per-particle structure that this
routine reads. Deliberately only those six: a fuller record would invite
the port to consult a field the original does not.

### `RejectOptions`

```python
class RejectOptions
```

The tags of ``op`` that this routine reads, through ``(*pop)``.

``clusterthresh`` has a default here for the same reason
``soda2_update_op.pro:22`` gives it one: it is absent from ``op`` as built
by ``soda2.pro:455`` and is added later, so a caller that skipped that
step would hit a missing-tag error rather than a disabled feature.

### `RejectResult`

```python
class RejectResult(NamedTuple)
```

``reject`` plus the IDL type the original would have returned.

``idl_type`` is not decoration: it is the one thing about this routine's
output that a Python ``int`` cannot carry, and it is measurably
value-dependent (SODA-2 register entry S3-a). Callers comparing against an IDL run need
it; callers doing arithmetic can ignore it.

### `REJECT_BITS`

*(re-exported from elsewhere; not defined in this module)*

### `soda2_reject`

```python
def soda2_reject(a: Particle, inttime: float, nextinttime: float, cutoff: float, clustercount: int, binningsize: float, pop: RejectOptions) -> RejectResult
```

``r = soda2_reject(a, inttime, nextinttime, cutoff, clustercount,
binningsize, pop)``.

Source: ``soda2_reject.pro`` (SODA-2).

Argument order and names follow the IDL exactly. ``pop`` is a pointer
there and a plain object here; nothing in this routine mutates it.

Every comparison below is written as the source writes it, including the
strictness of each boundary -- measured at the boundary in the bank rather
than inferred, because ``lt``/``le`` is the kind of detail a reader
reconstructs wrongly and a test at the midpoint never catches:

- ``arearatio`` exactly 0.10 or exactly 1.0 is **accepted**.
- ``binningsize`` exactly ``min(endbins)`` is **accepted**; exactly
  ``max(endbins)`` is **rejected**. The ladder is half-open at the top and
  closed at the bottom, which is the opposite of what most bin conventions
  do and is preserved.

## `arrayprobe_soda2.spec_decompress`

``spec_decompress.pro`` -- one buffer's compressed words to a bit image.

### `spec_decompress`

```python
def spec_decompress(cimage: ArrayLike, overload: int, version: int=0) -> np.ndarray
```

``bi = spec_decompress(cimage, overload, version=version)``.

Source: ``spec_decompress.pro`` (SODA-2).

``cimage`` is a sequence of 16-bit unsigned compressed words (as produced
by `spec_readint`). ``overload`` is truthy/1 when the frame's overload
flag is set, which drops the last two words from the decode (`:23`).
``version`` selects the HVPS4/3VCPI 8-word-uncompressed-block convention
(1) versus the original 2D-S/HVPS3 convention (0).

Returns a ``(numslices, 128)`` ``uint8`` array, row-major over slices --
the transpose of IDL's ``bitarr(128, numslices)``. Row 0 is always blank
(SODA-2 register entry S4-a); no clamping, no bounds "fix" beyond what `:46` itself
already does (SODA-2 register entry S4-c is preserved, not corrected).

## `arrayprobe_soda2.spec_readint`

``spec_readint.pro`` -- read ``length`` SPEC integers, skipping buffer

### `spec_readint`

```python
def spec_readint(f: BinaryIO, length: int, buffsize: int=4114, signed: bool=False) -> np.ndarray
```

``x = spec_readint(lun, length, buffsize=buffsize, signed=signed)``.

Source: ``spec_readint.pro`` (SODA-2).

``f`` is an open binary file positioned at the read start (IDL's ``lun``
plus ``point_lun,-lun,pointer``, here ``f.tell()``/``f.seek()``).
``buffsize=0`` bypasses the boundary logic entirely (`:11-16`, the
2DSCPIHK-file case, which has no buffer structure to skip).

Returns a 1-D array, dtype ``int16`` if ``signed`` else ``uint16``. On a
2+-crossing span the array is ``length + crossings*9`` **zeros** --
longer than ``length`` -- reproducing SODA-2 register entry S4-b rather than raising.

## `arrayprobe_soda2.spec_read_frame`

``spec_read_frame.pro`` -- read and assemble one HVPS3/2DS frame, composing

### `SpecFrame`

```python
class SpecFrame
```

``q = spec_read_frame(...)``'s return struct (`:96-97`).

Source: ``spec_read_frame.pro:96-97`` (SODA-2).

### `spec_read_frame`

```python
def spec_read_frame(f: BinaryIO, fpoint: int, id: str, version: int=0, recursioncount: int=0) -> SpecFrame
```

``q = spec_read_frame(lun, fpoint, id, version=version,
recursioncount=recursioncount)``.

Source: ``spec_read_frame.pro`` (SODA-2).

``f`` is an open binary SPEC raw file; ``fpoint`` the byte offset of the
frame's start (IDL's ``point_lun, lun, fpoint``, `:11`). ``id`` is
``'H'`` or ``'V'`` and is matched **case-sensitively** (IDL's ``eq`` on
strings), exactly like the source -- ``'h'`` matches neither block and
comes back as a no-frame result even over a perfectly good H frame
(bank case ``h_plain_lowercase_id``).

No EOF guard: a recursion chain that runs off the end of the file
raises, exactly as the IDL would (an unhandled read failure), rather
than silently returning a short frame.

## `arrayprobe_soda2.spec_read_hk`

``spec_read_hk.pro`` -- read one HVPS3/2DS housekeeping record: 48 diode

### `SpecHK`

```python
class SpecHK
```

``hk = spec_read_hk(...)``'s return struct (`:67`).

Source: ``spec_read_hk.pro:67`` (SODA-2).

### `spec_read_hk`

```python
def spec_read_hk(f: BinaryIO, bpoint: int, buffsize: int=4114, version: int=1) -> SpecHK
```

``hk = spec_read_hk(lun, bpoint, buffsize=buffsize, version=version)``.

``f`` is an open binary SPEC raw file; ``bpoint`` the byte offset of the
housekeeping record's `'HK'` marker word (IDL's ``point_lun,lun,bpoint``,
`:13`). ``buffsize=4114`` reproduces the IDL's *effective* default: the
source declares ``buffsize`` as an optional positional with no explicit
default, and an omitted argument reaches ``spec_readint.pro:9``, which
defaults it to 4114 -- both vendored callers omit it.

``version=1`` (2DS/HVPS3, 53 words) and ``version=2`` (3VCPI/Hawkeye,
83 words, `:43-65`, ``_spec_read_hk_v2``) are both ported; any other
value raises ``ValueError``, matching the IDL's own fate at `:14`
(``hklength`` undefined). The refusal does not advance the file
position -- exactly as the IDL would not have read anything either.

## `arrayprobe_soda2.spec_index`

``spec_index.pro`` -- walk a SPEC raw file two buffers at a time and

### `SpecIndex`

```python
class SpecIndex
```

`spec_index`'s return struct (`:157-159`), one field per IDL tag.
Dtypes are the measured `size(/tname)` values, not assumed.

Source: ``spec_index.pro:157-159`` (SODA-2).

### `SpecIndexLite`

```python
class SpecIndexLite
```

`lite=1`'s return (`:148`) -- built only after the full walk has
already run; no caller in the vendored tree uses it.

### `SpecIndexError`

```python
class SpecIndexError(ValueError)
```

`:30` -- the buffer-size autodetection found fewer than two matches
for the file's own first three words, so IDL's `w[1]` is a scalar
subscript out of range.

Source: ``spec_index.pro:30`` (SODA-2).

### `SpecFileMisaligned`

```python
class SpecFileMisaligned(RuntimeError)
```

`:72` -- IDL's `stop, 'File misaligned'`. Measured under GDL
(two separate runs): `stop` here printed the message and
returned control within seconds rather than blocking, unlike the
`soda2_samplearea` bank -- see `run_soda2_spec_index_bank`'s module
docstring.

Source: ``spec_index.pro:72`` (SODA-2).

Carries the ``buffsize`` the `:26-30` autodetection computed before the
walk that raised this -- `:72` fires only after `buffsize` is already
known, and `triple_full`'s own halt is evidence about *that* value
(216, not 4114; SODA-2 register entry S4-k) as much as about the halt itself.

### `julday`

```python
def julday(month: int, day: int, year: int) -> int
```

The Julian Day Number IDL's `julday(month, day, year)` returns for a
date at 00:00 (no fractional-day argument is ever passed here) --
Fliegel-Van Flandern, ported rather than transcribed from `julday.pro`
(not in the vendored tree; IDL's own library routine). Bank-measured:
``julday(9,6,2016) == 2457638``, ``julday(9,7,1999) == 2451429``,
``julday(1,1,2000) == 2451545``, ``julday(9,2,2016) == 2457634``; the
day-0 arithmetic case ``julday(9,0,2016) == 2457632`` is GDL-measured
only, not IDL-confirmed (nothing in the fixtures reaches it).

### `spec_index`

```python
def spec_index(f: BinaryIO, *, lite: bool=False, minimagesize: int=2, pointerstart: int=0, pointerstop: int | None=None, absolutepointer: bool=False, version: int=1) -> SpecIndex | SpecIndexLite
```

``idx = spec_index(lun, lite=lite, minimagesize=minimagesize,
pointerstart=pointerstart, pointerstop=pointerstop,
absolutepointer=absolutepointer, version=version)``.

Source: ``spec_index.pro`` (SODA-2); bare line references here are into that file.

``f`` is an open binary SPEC raw file. Every vendored caller passes no
keyword at all; `minimagesize=2`, `pointerstart=0`,
`absolutepointer=False` and `version=1` are IDL's own effective
defaults (`:12-19`). `pointerstop=None` reproduces "defaults to the
file size" (`:22`).

Raises `SpecIndexError` where IDL's own buffer-size
autodetection would die (`:30`, a one-buffer file or fewer than three
words to scan), `SpecFileMisaligned` where IDL's `stop, 'File
misaligned'` would halt (`:72`, a header year outside 2005..2050 in any
buffer but the last -- the last is never checked, SODA-2 register entry S4-i), and
`ValueError` for any `version` other than 1 or 2 (`:18-19`
leaves `hklength` undefined and the IDL's own next use of it dies).
None of the three refusals advances the file position past what the
autodetection scan itself required.

## `arrayprobe_soda2.spec_absolutepointers`

``spec_absolutepointers.pro`` -- turn a `spec_index` result and a list of

### `AbsolutePointers`

```python
class AbsolutePointers
```

`spec_absolutepointers`'s return struct (`:21`). Empty (`nt==0`,
`:10`) is IDL's own `{ap:0, n:0}`: both fields collapse to a scalar INT
zero (`n_elements=1`), not a length-0 array -- reproduced here as
``np.int16(0)`` rather than ``np.ndarray([])``.

Source: ``spec_absolutepointers.pro:21`` (SODA-2).

### `spec_absolutepointers`

```python
def spec_absolutepointers(buffnum: int | Sequence[int], index: SpecIndex) -> AbsolutePointers
```

``a = spec_absolutepointers(buffnum, p)`` -- `p` is `index` itself
here, not a pointer to it (see the module docstring). `buffnum` may be
a single buffer number or a sequence of them; results are written in
that exact order, never sorted.

Source: ``spec_absolutepointers.pro`` (SODA-2).

## `arrayprobe_soda2.hvps4_read_frame`

``hvps4_read_frame.pro`` -- read one HVPS-4 frame (SPEC subformat 2).

### `Hvps4Frame`

```python
class Hvps4Frame
```

``hvps4_read_frame``'s return struct (`:66`), IDL types carried as
NumPy scalar dtypes as GDL reports them (bank ``TN`` field).

### `hvps4_read_frame`

```python
def hvps4_read_frame(f: BinaryIO, bpoint: int, id: str) -> Hvps4Frame
```

``q = hvps4_read_frame(lun, bpoint, id)``; ``id`` is e.g. ``'H50'``.

Source: ``hvps4_read_frame.pro`` (SODA-2).

## `arrayprobe_soda2.processbuffer_spec`

``soda2_processbuffer.pro``, the SPEC branch (`:264-376`) -- P-c+P-d.

### `SpecOp`

```python
class SpecOp
```

The `(*pop)` fields the branch reads, `:264-318`. IDL types in
comments; `yres`/`res` are FLOAT (`soda2_probespecs.pro:9`) -- kept as
Python floats but the `:309` division reproduces float32 semantics
explicitly (SODA-2 register entry S4-p) regardless of this field's own storage.

### `SpecMisc`

```python
class SpecMisc
```

The `(*pmisc)` fields the branch reads and mutates in place, exactly
where the IDL writes them (`:326`, `:374`, `:375`).

Source: ``soda2_processbuffer.pro`` (SODA-2); bare line references here are into that file.

### `SpecBufferParticles`

```python
class SpecBufferParticles
```

The branch's locals at `:376`, what the shared tail consumes.
`rejectbuffer` is always 0 here -- a rejected buffer is a
`NullBuffer` instead.

Source: ``soda2_processbuffer.pro`` (SODA-2); bare line references here are into that file.

### `NullBuffer`

```python
class NullBuffer
```

`:18-20`'s `nullbuffer` -- the branch's `rejectbuffer=1` return, at
`:267` (no images) or `:339` (kept slices exceed 10 000).

Source: ``soda2_processbuffer.pro`` (SODA-2); bare line references here are into that file.

### `UnsupportedSpecSubformat`

```python
class UnsupportedSpecSubformat(NotImplementedError)
```

`:291-295` -- a `subformat` outside 0-2. The IDL `CASE` has no
`ELSE`, so such a value is an IDL error; raised before any read
(`soda2_processbuffer.pro:291`).

### `process_spec_buffer`

```python
def process_spec_buffer(f: BinaryIO, buffer_time: float, op: SpecOp, misc: SpecMisc) -> SpecBufferParticles | NullBuffer
```

``p = soda2_processbuffer(buffer, pop, pmisc)``, the SPEC branch
only (`:264-376`). ``f`` is the open raw file IDL has as LUN 1;
``buffer_time`` is `buffer.time`. ``misc`` is mutated in place, exactly
where the IDL writes `(*pmisc)`.

Source: ``soda2_processbuffer.pro:264-376`` (SODA-2); bare line references here are into that
file.

### `soda2_processbuffer`

```python
def soda2_processbuffer(f: BinaryIO, buffer_time: float, op: SpecOp, tail_op: Any, misc: SpecMisc, lastdhist: Any) -> NullBuffer | ProcessedBuffer
```

``p = soda2_processbuffer(buffer, pop, pmisc)``, SPEC path, whole
function (`:264-747`) -- composes `process_spec_buffer` with
`processbuffer_tail.process_buffer_tail`. A `NullBuffer` from the
branch is returned immediately, without calling the tail, matching
IDL's early `nullbuffer` returns at `:267`/`:339`.

Source: ``soda2_processbuffer.pro:264-747`` (SODA-2); bare line references here are into that
file.

## `arrayprobe_soda2.processbuffer_tail`

``soda2_processbuffer.pro:612-747`` -- the shared per-particle tail, SPEC path.

### `TailOp`

```python
class TailOp
```

The `(*pop)` fields the tail (`:612-747`) reads, beyond `SpecOp`.
No defaults -- every field is a fidelity-relevant threshold and must
be given explicitly (the same discipline `profiles.py` applies to
`FidelityProfile`). IDL types in comments; `res`/`yres` are FLOAT.

Source: ``soda2_processbuffer.pro:612-747`` (SODA-2).

### `ProcessedBuffer`

```python
class ProcessedBuffer
```

`soda2_processbuffer.pro:740-747`'s 40-field return structure, in
declaration order.

### `process_buffer_tail`

```python
def process_buffer_tail(p: SpecBufferParticles, op: TailOp, lastdhist: np.ndarray) -> ProcessedBuffer
```

``soda2_processbuffer.pro:612-747``, SPEC path only. ``lastdhist``
is ``(*pmisc).lastdhist`` -- unused directly (``fixstuckbits`` already
consumed it at ``:615`` when ``op.stuckbits`` is set, via the caller),
kept as a parameter only to assert its shape against ``op.numdiodes``.

## `arrayprobe_soda2.poisson_spot_correct`

``poisson_spot_correct.pro`` -- Korolev (2007) hole-filling size correction.

### `DSPOT_DEDGE`

```python
DSPOT_DEDGE: array
```

### `DEDGE_D0`

```python
DEDGE_D0: array
```

### `ZEED`

```python
ZEED: array
```

### `PoissonCorrection`

```python
class PoissonCorrection
```

``{correction, zd}`` -- ``poisson_spot_correct``'s return value plus
its ``zd=`` keyword output, and ``ip``, the clamped table index (not part
of the IDL return, exposed here because the tests and the GDL bank need
to inspect it). ``ip == -1`` means the branch at ``:26`` was not taken.

### `poisson_spot_correct`

```python
def poisson_spot_correct(img_orig: float | np.floating, img_fill: float | np.floating) -> PoissonCorrection
```

``poisson_spot_correct(img_orig, img_fill, zd=zd)`` -- Korolev (2007)
hole-filling size correction, ported line for line.

Source: ``poisson_spot_correct.pro`` (SODA-2).

Both arguments are cast to ``np.float32`` at entry (the call site's
``total()`` already returns FLOAT, so this is a type assertion, not a
conversion decision). Runs under ``np.errstate(all="ignore")`` because a
zero or shrinking fill area drives ``:27`` to ``0/0`` or the square root
of a negative -- IDL/GDL report this as a floating-point arithmetic error
(SODA-2 register entry S4-t) but the *value* that reaches the caller is well defined: the same
``(1.0, 0.0)`` the untaken branch returns, arrived at through the
``where`` result of ``-1`` being clamped to ``0`` at ``:28``.

## `arrayprobe_soda2.binary_dof`

``binary_dof.pro`` -- depth-of-field rejection by neighbour compactness.

### `KERNEL`

```python
KERNEL: array
```

### `THRESHOLDS`

*(re-exported from elsewhere; not defined in this module)*

### `BinaryDof`

```python
class BinaryDof
```

``binary_dof.pro``'s return value plus its ``neighbor_count=``
output keyword and the ``area`` it computed along the way.

### `binary_dof`

```python
def binary_dof(bitimage: np.ndarray) -> BinaryDof
```

``d = binary_dof(bitimage, neighbor_count=nc)``.

Source: ``binary_dof.pro`` (SODA-2).

``bitimage`` is a 2-D binary (0/1) array, this package's
``(nslices, 128)`` convention. A 1-D 128-vector (the one-slice IDL
frame ``[128, 1]``, itself 2-D) is reshaped to ``(1, 128)``.

## `arrayprobe_soda2.fillholes`

``fillholes.pro`` -- fill interior holes in a binary particle image.

### `fillholes`

```python
def fillholes(img: np.ndarray, *, jit: bool=False) -> np.ndarray
```

``newimg = fillholes(img)``.

Source: ``fillholes.pro`` (SODA-2).

``img`` is a 2-D binary (0/1) array on this package's ``(roilen,
ndiodes)`` convention (IDL: ``[ndiodes, roilen]``). Returns a uint8
array of the same shape.

## `arrayprobe_soda2.particlesort`

``soda2_particlesort.pro:1-171`` -- SODA-2's per-buffer accumulation step.

### `Accumulator`

```python
class Accumulator
```

``d``, transcribed from ``soda2_process_2d.pro:49-104``. Every field's
dtype mirrors the IDL literal it was built from (``fltarr`` -> float32,
``lonarr`` -> int32, ``dblarr``/``dindgen`` -> float64).

### `ParticlesortOptions`

```python
class ParticlesortOptions
```

The ``op`` (``*pop``) tags this module reads. ``format`` must be
``"SPEC"``, ``"SEA"``, ``"DMT"`` or ``"RAF"`` and ``probetype`` must not be
``"2DC"``; anything else raises ``NotImplementedError`` naming the source
line the unported branch lives at.

### `Soda2ParticlesortError`

```python
class Soda2ParticlesortError(RuntimeError)
```

An IDL subscript-range halt this module reproduces as a raise, naming
the line. CIP-1: ``soda2_particlesort.pro:39``'s ``truetime[1:*]`` halts in IDL
for a 1-particle ``x`` (the finding derived for the SPEC branch's own
``:13``, same construct, `run_soda2_process_2d_bank.py` module docstring).

### `idl_median`

```python
def idl_median(values: np.ndarray) -> float
```

IDL ``MEDIAN(values)`` without ``/EVEN``: for an even-length array
this is the upper-middle sorted element, not an average. Python 0-based
``sorted[n // 2]`` lands on exactly that element for both parities.

### `new_accumulator`

```python
def new_accumulator(op: ParticlesortOptions, numrecords: int) -> Accumulator
```

``d={...}`` from ``soda2_process_2d.pro:49-104``. ``numbins``/
``numarbins`` come from ``op.endbins``/``op.arendbins`` the way the
source derives them (``n_elements(endbins)-1``).

### `soda2_particlesort`

```python
def soda2_particlesort(op: ParticlesortOptions, x: dict[str, np.ndarray], d: Accumulator, reprocessed_time: np.ndarray | None=None, inewbuffer: np.ndarray | None=None) -> np.ndarray
```

Port of ``soda2_particlesort.pro:1-171``. Mutates ``d`` in place and
returns ``rejectionflag`` (the IDL keeps it local); the PBP writers in
`arrayprobe_soda2.pbp_writer` consume it directly. ``inewbuffer``
(the IDL positional argument) is read only by the 2DC block
(``:65-76``) and is required there.

## `arrayprobe_soda2.fit_poisson`

``fit_poisson.pro`` + ``fn_poisson.pro`` -- the double-Poisson interarrival

### `fn_poisson`

```python
def fn_poisson(dt: np.ndarray | float, ans: Sequence[float] | np.ndarray) -> np.ndarray
```

Port of ``fn_poisson.pro``.

``ans = [a, sigma, rho]``. Returns a length-4 array (for scalar ``dt``)
or an ``(4, len(dt))`` array (for array ``dt``): index 0 is the model
value, indices 1-3 are ``d(value)/d(ans[0..2])`` -- what IDL's ``LMFIT``
user function contract requires when it computes its own Jacobian
analytically rather than by finite differences.

Ported line-for-line from the IDL; the four output slots are exactly the
source's ``out[0..3]``.

### `fit_poisson`

```python
def fit_poisson(h: np.ndarray, dt: np.ndarray, minidt: float, plot: bool=False) -> PoissonFit
```

Port of ``fit_poisson.pro``.

``h`` -- histogram counts at the ``dt`` midbins (``d.intspec_all[itime,
*]`` in the caller). ``minidt`` -- first-guess separator for the two
Poisson components.

``plot`` is accepted for signature parity with the IDL keyword but does
nothing: the source's plotting branch (``:34-46``) is interactive
visualisation, out of scope for this accumulation port and never called
with a true value from ``soda2_particlesort.pro:95`` (``plot=0``).

### `PoissonFit`

```python
class PoissonFit
```

``fit_poisson``'s return. IDL returns ``{a:[0.0,0.0,0.0]}`` on the
empty-``iy`` early exit (``:26``) and ``{a:a}`` (the fitted coefficients)
otherwise -- both cases are one field, ``a``, reproduced here.

Source: the return of ``fit_poisson.pro`` (SODA-2); bare line references here are into that
file.

## `arrayprobe_soda2.timeconv`

The driver's two small time-conversion

*No public API declared (`__all__` empty or absent).*

## `arrayprobe_soda2.read2dbuffer`

`soda2_read2dbuffer.pro`, SPEC branch

*No public API declared (`__all__` empty or absent).*

## `arrayprobe_soda2.buildindex`

`soda2_buildindex.pro:8-17` (SPEC branch);

*No public API declared (`__all__` empty or absent).*

## `arrayprobe_soda2.update_op`

`soda2_update_op.pro:1-53` (`:55-84`, the `.txt` model-header

*No public API declared (`__all__` empty or absent).*

## `arrayprobe_soda2.probespecs`

`soda2_probespecs.pro` -- the SODA-2 probe table, 72 probes.

### `IDL_TYPES`

*(re-exported from elsewhere; not defined in this module)*

### `PROBE_NAMES`

*(re-exported from elsewhere; not defined in this module)*

### `SOURCE_LINES`

*(re-exported from elsewhere; not defined in this module)*

### `TAGS`

*(re-exported from elsewhere; not defined in this module)*

### `soda2_probespecs`

```python
def soda2_probespecs(name: str | list[str] | tuple[str, ...] | None=None, id: int | list[int] | tuple[int, ...] | None=None, fn: str | None=None) -> dict[str, Any] | list[dict[str, Any]]
```

`soda2_probespecs(name=, id=, fn=)`, `:1463-1478`.

Source: ``soda2_probespecs.pro`` (SODA-2); bare line references here are into that file.

Returns one probe as a ``dict`` (the table row, or `base` on a miss), or a
``list[dict]`` when IDL would return several. See the module docstring for
every edge; each is a bank case.

## `arrayprobe_soda2.process_hk`

`spec_process_hk.pro`, versions 1 and 2, and `spec_index_hk.pro`.

*No public API declared (`__all__` empty or absent).*

## `arrayprobe_soda2.pth_readers`

``soda2_process_2d.pro:147-172`` -- the ASCII/CSV and netCDF PTH (true

### `PthReaderHalt`

```python
class PthReaderHalt(RuntimeError)
```

An IDL halt inside ``:147-172``, raised naming the line.

### `pth_suffix`

```python
def pth_suffix(pth: str) -> str
```

``:129`` takes the suffix as the last dot-separated piece of ``op.pth``: the last
non-empty ``.``-separated token (``strsplit`` drops empty tokens), the
whole name when it has no ``.``, and ``''`` when every token is empty.
Case-sensitive, as ``:131-164``'s ``eq`` tests are.

Source: ``soda2_process_2d.pro:129`` (SODA-2).

### `read_pth_ascii`

```python
def read_pth_ascii(path: str | Path, starttime: float, rate: float, numrecords: int) -> np.ndarray
```

``:147-162`` -- returns ``pth_tas`` (float32[numrecords]); the caller
sets ``got_pth = 1`` whatever this returns (``:161``).

Source: ``soda2_process_2d.pro:147-162`` (SODA-2).

### `read_pth_ncdf`

```python
def read_pth_ncdf(path: str | Path, starttime: float, stoptime: float, rate: float, numrecords: int) -> np.ndarray
```

``:164-172`` -- returns ``pth_tas`` (float32[numrecords]).

Source: ``soda2_process_2d.pro:164-172`` (SODA-2).

### `read_pth`

```python
def read_pth(pth: str | Path, suffix: str, starttime: float, stoptime: float, rate: float, numrecords: int) -> tuple[np.ndarray, int]
```

``:147-172`` dispatch on ``suffix`` (``:129``, case-sensitive):
returns ``(pth_tas, got_pth)``. ``dat``/``sav`` is not this module's
(``process_2d._pth_from_sav``); any other suffix raises ``ValueError``.

Source: ``soda2_process_2d.pro:147-172`` (SODA-2).

## `arrayprobe_soda2.pbp_writer`

``soda2_process_2d.pro`` PBP writers.

### `PBPPROPS`

*(re-exported from elsewhere; not defined in this module)*

### `AsciiPsdNotPorted`

```python
class AsciiPsdNotPorted(NotImplementedError)
```

``op.asciipsdfile == 1`` (``soda2_export_ascii.pro``) lies outside this module; its
port is `arrayprobe_soda2.export_ascii`.

### `PbpImagesNotPorted`

```python
class PbpImagesNotPorted(NotImplementedError)
```

A particle-image case (``op.ncdfparticlefile == 2``) still refused: the
parallel driver and unmeasured chunk shapes. The serial path is ported
(``soda2_process_2d.pro:286-306``, ``:546-553``,
``soda2_particlesort.pro:264-276``; the particle-image output).

### `SaveFileNotPorted`

```python
class SaveFileNotPorted(NotImplementedError)
```

Retired: the IDL SAVE file (``soda2_process_2d.pro:729-731``) is written by
``save_writer.save_process_data``. Kept for import compatibility only;
nothing raises it.

### `sfm2hms`

```python
def sfm2hms(sfm: float) -> int
```

``sfm2hms.pro``: seconds-from-midnight to an ``HHMMSS`` integer (IDL
LONG). ``soda2_filename.pro:20``, ``soda2_process_2d.pro:253-254`` and
``soda2_export_ncdf.pro:56-57`` all call this; ``timeconv.py`` does not
carry it, so it is defined here and is the canonical port; moving it
into ``timeconv.py`` would be a rename, not a re-derivation.

**No wrap at midnight**: ``sfm=long(sfm_in)``,
``hour=sfm/3600l``, ``minute=(sfm mod 3600)/60``, ``sec=(sfm mod 3600) mod
60`` -- nothing reduces modulo 86400, so 86401 s is ``240001`` and 90061 s
``250101``. Applying ``% 86400`` (``000001``) would disagree with the source,
visibly in ``soda2_export_ncdf``'s ``TimeInterval``. IDL's ``long()`` and integer
``/`` truncate toward zero and ``mod`` takes the dividend's sign, so a
negative ``sfm`` gives a negative result (-5 s is ``-5``), unlike
Python's floor ``divmod``. Every case pinned by
the GDL bank ``run_soda2_sfm2hms_bank.py`` (not included in this package).

### `pbp_filename`

```python
def pbp_filename(op: Mapping[str, Any], suffix: str, *, extension: str='.dat', outdir: str | None=None) -> str
```

``soda2_filename.pro``. ``op`` is a plain mapping of IDL tag name
(upper- or lower-case, looked up case-insensitively as ``tag_names``
would present them) to value.

### `open_pbp_csv`

```python
def open_pbp_csv(fn_pbp: str, op: Mapping[str, Any], date: Mapping[str, str]) -> IO[str]
```

``soda2_process_2d.pro:336-354``. Text mode, ``\n`` line endings
(IDL's ``printf`` writes ``\n``, not the platform default).

### `write_pbp_csv_buffer`

```python
def write_pbp_csv_buffer(f: IO[str], x: Mapping[str, np.ndarray], istop: int, truetime: np.ndarray, rejectionflag: np.ndarray) -> None
```

``soda2_particlesort.pro:279-298``. ``time`` and ``rejectionflag``
are not tags of ``x`` (SODA-2 register entry S6-i notes ``inttime`` IS a tag, so it takes the
generic branch and prints the raw value, not the clamped ``interarrival``
netCDF writes).

### `open_pbp_ncdf`

```python
def open_pbp_ncdf(fn_ncdf: str, op: Mapping[str, Any], date: Mapping[str, str], pthdat: Mapping[str, Any] | None=None, *, stamp_profile: str | None=None) -> Any
```

``soda2_process_2d.pro:240-333``, with the ``ncdfparticlefile == 2``
image variables (`:286-306`). Returns an open
``netCDF4.Dataset`` in data mode (IDL's ``ncdf_control,/endef``).

### `write_pbp_ncdf_buffer`

```python
def write_pbp_ncdf_buffer(ds: Any, x: Mapping[str, np.ndarray], istop: int, truetime: np.ndarray, interarrival: np.ndarray, rejectionflag: np.ndarray, ncdf_offset: int) -> None
```

``soda2_particlesort.pro:186-261``. ``time`` <- ``truetime``,
``inttime`` <- ``interarrival`` (the clamped local, SODA-2 register entry S6-i -- NOT
``x['inttime']``, which is what the CSV writer uses); every other
variable is ``x[name][0:istop]``.

### `write_pbp_ncdf_images`

```python
def write_pbp_ncdf_images(ds: Any, x: Mapping[str, np.ndarray], istop: int, image: np.ndarray, ncdf_offset: int, image_offset: int) -> None
```

``soda2_particlesort.pro:264-276`` (``ncdfparticlefile eq 2``).
``image`` is this flush's chunk, slice-first ``(nslices, numdiodes)``;
``image_offset`` is the driver's ``slices_written``. ``startx`` is zeros
and ``stopx`` the chunk's diode width less one (`:269-272`).

### `PBP_IMAGE_INDEX_VARS`

*(re-exported from elsewhere; not defined in this module)*

### `close_pbp_ncdf`

```python
def close_pbp_ncdf(ds: Any, pthdat: Mapping[str, Any] | None=None) -> None
```

``soda2_process_2d.pro:696-721`` tail: interpolate PTH variables onto
the written ``time`` axis, then close, via ``_idl_interpol`` -- IDL's
``INTERPOL`` linearly extrapolates outside ``pthdat.time``'s range;
``np.interp`` would clamp there instead. Measured under GDL
(``pthdat_extrap`` golden case).

## `arrayprobe_soda2.process_2d`

``soda2_process_2d.pro`` -- the SODA-2 driver, SPEC path and (CIP-1) the

### `ProcessData`

```python
class ProcessData
```

``data`` (`:678-687``), declaration order. ``date_processed`` is
non-deterministic (like UIOOPS's ``'Creation Time'``) -- exclude it from
every comparison.

Source: ``soda2_process_2d.pro:678-687`` (SODA-2).

### `SeaHouse`

```python
class SeaHouse
```

``house={op:op}`` (``soda2_process_2d.pro:394``) -- the SEA/CIP
branch's housekeeping placeholder when ``n_elements(op.seatag) lt 2``
(`:397-398` then skips ``process_cip1d_sea``). CIP-1: a
``seatag`` of two or more elements fires ``process_cip1d_sea`` instead,
which gives ``data.house`` a different struct entirely (its own tag set, no
``time``/``tas``/``nb``): `soda2_process_2d` then stores
`process_hk.process_cip1d_sea`'s result, not this placeholder.

### `NUM2PROCESS`

```python
NUM2PROCESS: int
```

### `soda2_process_2d`

```python
def soda2_process_2d(op: dict, *, fn_pbp: str | None=None, num2process: int=NUM2PROCESS, report_every: int=0, jobs: int=1, chunks: int=0, jit: bool=False, stamp_profile: str | None=None) -> ProcessData | None
```

``soda2_process_2d, op`` -- SPEC path, and the SEA/CIP route (a
1-element ``op.seatag``, or two or more, which adds the CIP-1D
housekeeping of ``process_cip1d_sea``), raw bytes to the in-memory ``data``.
Returns ``None`` exactly where the IDL ``return``s with no output
(`:430-433`, `:576`).

Source: ``soda2_process_2d.pro`` (SODA-2); bare line references here are into that file.

``jobs`` (default 1, serial -- the IDL has no parallelism and this changes
no computed number) splits the buffer loop (`:449-573`) across that many
processes; ``chunks`` (default 0 = ``4 * jobs``) is how many contiguous
buffer ranges it is split into, more than ``jobs`` for balance because a
buffer's cost is its particle count. Every number the run produces comes
from the same per-buffer calls in the same buffer order and from this
function's own bookkeeping and ``_flush``; byte-identity is asserted on a
real fixture by ``tests/test_soda2_parallel.py``, not claimed here.
``jobs > 1`` is refused, by name, where the split would not be exact --
see `process_2d_parallel.run_parallel_loop`.

``jit`` (default False) routes ``label_blobs``'s ``_label_region`` -- and
``fillholes``' own call to it -- through `arrayprobe_soda2.jit_kernels`'
numba flood fill. Speed only: the kernel is exact by construction and
``tests/test_soda2_label_region_jit_identity.py`` asserts it with
``np.array_equal``, so it is not recorded in the ``op`` struct, exactly as
``jobs``/``chunks`` are not. It reaches the per-buffer work as
`processbuffer_tail.TailOp.jit`, which rides in ``_LoopContext`` and so
reaches a ``jobs > 1`` worker as well as the serial loop
(``tests/test_soda2_jit_flag.py``).

``stamp_profile`` (default None) is the configuration name a driver ran this under; it is
written into ``.pbp.nc`` as the ``arrayprobe_profile`` global attribute
(`pbp_writer.engine_attrs`), ``"unstated"`` when None. Metadata only: it is not
recorded in ``op`` and moves no computed number.

## `arrayprobe_soda2.process_2d_parallel`

``soda2_process_2d.pro:449-573``'s buffer loop, split across processes.

### `Soda2ParallelRefused`

```python
class Soda2ParallelRefused(NotImplementedError)
```

``jobs > 1`` asked for on a run whose loop this module cannot split
exactly. Never downgraded to a warning: the alternative to refusing is a
number that is wrong in a way nothing would catch.

### `chunk_bounds`

```python
def chunk_bounds(firstbuff: int, lastbuff: int, nchunks: int) -> list[tuple[int, int]]
```

Split ``[firstbuff, lastbuff]`` (inclusive, the driver's own range) into
at most ``nchunks`` contiguous half-open ranges, none empty.

Contiguous and in order, so an ordered concatenation of the chunks is the
serial sequence -- the same partition property
a range-iteration test pins for the UIOOPS decode.

### `refuse_unsplittable`

```python
def refuse_unsplittable(op: Mapping[str, Any], fn_list: Sequence[Any], jobs: int) -> None
```

Every configuration whose loop this module cannot split exactly, refused
by name and by the line that makes it so.

Called from ``soda2_process_2d`` **before anything is opened or read** --
beside the driver's other configuration refusals (`:478-520`) rather than
at the point of the split -- because a refusal raised later would leave the
PBP writers open behind it (the shape of SODA-2 register entry S6-f), and a configuration error
should cost no file.

### `run_parallel_loop`

```python
def run_parallel_loop(ctx: _LoopContext, firstbuff: int, lastbuff: int, misc: SpecMisc | CipMisc, *, jobs: int, chunks: int=0, report_every: int=0, d: Accumulator, dhist: np.ndarray, numbuffsaccepted: np.ndarray, numbuffsrejected: np.ndarray, pbpstartindex: np.ndarray, num2process: int, psopts: ParticlesortOptions, flush: Callable[..., int], csv_f: Any, ncdf_ds: Any) -> tuple[int, int, dict[str, np.ndarray]]
```

Run `:449-573` across ``jobs`` processes and replay the driver's
bookkeeping over the result.

Mutates ``dhist``, ``numbuffsaccepted``, ``numbuffsrejected``,
``pbpstartindex`` and (through ``flush``) ``d`` and the PBP writers exactly
as the serial loop does, and returns the ``(istop, ncdf_offset, x)`` the
serial loop would be holding when it fell out -- so everything after the
loop in ``soda2_process_2d`` is reached in the same state.

## `arrayprobe_soda2.reprocess_pbp`

Reprocess-from-PBP: ``soda2_restore_pbp.pro`` and ``spec_newtime.pro``,

### `PbpRestoreError`

```python
class PbpRestoreError(RuntimeError)
```

An ``ncdf_varget`` read the IDL could not perform (offset past the end).

### `SpecNewtimeStop`

```python
class SpecNewtimeStop(RuntimeError)
```

``spec_newtime.pro:7`` -- ``stop, 'File does not contain full rawtime,
just truncated.'``

### `pbp_particle_count`

```python
def pbp_particle_count(fn: str) -> int
```

`:587` -- ``restorenc, fn_pbp, 'pbp', var='time'``; only the length
is used (`:599`, `:611`).

### `restore_pbp`

```python
def restore_pbp(fn: str, offset: int=0, count: int | None=None) -> RestoredPbp
```

``soda2_restore_pbp.pro:1-30`` over ``restorenc``/``ncdf2sav``.

``ncdf_varget`` with ``offset`` past the last record cannot read; IDL
halts there (read from the IDL documentation, not measured under GDL),
raised here as `PbpRestoreError`. ``offset + count`` past the end
reads to the end, IDL's documented ``COUNT`` reduction.

### `spec_newtime`

```python
def spec_newtime(rawtime: np.ndarray, buffertime: np.ndarray, probetas: np.ndarray, yres: Any) -> np.ndarray
```

``spec_newtime.pro:1-39`` on the columns ``restorenc`` reads (`:5`).

Kept as the IDL has it:

- `:7` stops unless ``max(rawtime) >= 2^31``.
- `:15-16` ``where(..., nrollover)`` with no match returns ``-1``, and a
  scalar ``-1`` subscript is the last element, so with no rollover the
  **last** particle's counter delta gains ``2^32``.
- `:19` ``yres/(1.0e6*probetas)`` is FLOAT arithmetic (``probetas`` is
  FLOAT in the file) widened to DOUBLE after the division.
- `:23`, `:33` ``where(...)`` with no match is likewise ``-1``.
- `:34` ``median`` without ``/EVEN`` (upper-middle element).
- `:10` ``rawtime[1:*]`` on one particle is out of range and halts the IDL.
- `:34` subscripts ``buffertime`` with ``itimematch[matches]`` but ``elaptime``
  with ``[itimematch[matches]]``. When ``matches`` is ``-1`` (no buffer end in
  the period) the inner value is a SCALAR, so ``buffertime``'s subscript wraps
  a negative index (``-2`` -> ``n-2``) while ``elaptime``'s, an array, is
  clipped to 0; when ``matches`` is an array both are clipped. Measured under
  GDL 8.4 (``tests/data/gdl_soda2_spec_newtime_single_buffer_golden.json``).

## `arrayprobe_soda2.export_ascii`

``soda2_export_ascii.pro`` -- the ASCII particle-size-

### `MinsizeOutOfRange`

```python
class MinsizeOutOfRange(IndexError)
```

``soda2_export_ascii.pro:14-15`` -- no bin edge is ``>= minsize``, so
``iminsize = min(where(...))`` is ``-1``. Measured under GDL (case
``minsize_above_bins``): this does NOT itself raise (IDL's negative
index -1 is the last element, a valid access) -- the real halt is one
level down, in ``mmdiam.pro:12``'s ``z=fltarr(n)`` with ``n=0``, because
``binstart=-1`` collapses the ``endbins``/spec slices passed into
``mmdiam`` to length 1. This port raises here, before calling
``compute_bulk_simple`` at all, rather than reproducing the deeper
GDL stack -- the *user-visible* outcome (a halt for this input) is the
same either way, and this port has no ``fltarr(0)``-shaped failure mode
to reproduce faithfully.

### `OneD2DHousekeepingNotPorted`

```python
class OneD2DHousekeepingNotPorted(NotImplementedError)
```

``soda2_export_ascii.pro:37`` -- ``byte(leftreject+rightreject)`` on
non-integer housekeeping fields: no GDL bank case pins IDL's float-to-byte
conversion, so this port refuses it rather than guess. Integer fields
are ported (`:19-43`).

### `interpol`

```python
def interpol(v: np.ndarray, x: np.ndarray, xout: float | np.floating | np.ndarray) -> float | np.ndarray
```

IDL's 3-argument ``INTERPOL(V, X, XOUT)``: linear interpolation that
**extrapolates** past both ends of ``x`` using the nearest segment's
slope, rather than clamping (``numpy.interp`` clamps -- do not use it
here). ``x`` is located by the equivalent of IDL's ``VALUE_LOCATE``,
clamped to ``[0, n-2]`` so the two endpoint segments serve every
out-of-range query. Only the *left* extrapolation from a cumulative
sum's leading ``0`` pad is reachable from `mmdiam`/`mvdiam`
in this codebase; a run of empty bins makes ``x`` non-strictly-increasing
(repeated values), where the tie-breaking is implementation-defined and
pinned by the ``gappy_spectrum`` bank case, not assumed here.

### `unnormalize`

```python
def unnormalize(spectra: np.ndarray, endbins: np.ndarray) -> np.ndarray
```

``unnormalize.pro`` (whole file, 16 lines). ``spectra`` in m^-4,
``endbins`` in um; returns m^-3. 1-D or 2-D (``[ntimes, nbins]``) input,
same shape out.

In IDL's types, not float64: ``spec_un = spectra*0.0`` (`:7`) fixes
the 2-D result's type to the spectra's own, each row is
``(spectra[i,*]*binwidth)/1.0e6`` with ``1.0e6`` a FLOAT literal, and a
wider row (DOUBLE ``endbins``) is rounded back on assignment. The 1-D
branch (`:12`) keeps the promoted type.

### `mmdiam`

```python
def mmdiam(iwc_spec: np.ndarray, endbins: np.ndarray, nan: bool=False) -> np.ndarray
```

``mmdiam.pro`` (36 lines). ``iwc_spec`` un-normalized mass (g/m3),
1-D or ``[ntimes, nbins]``; returns one value per time record. Pads the
cumulative-mass array with a leading 0 so the first bin is interpolable
(`:31`).

``tmass`` (`:22`) is a sequential ``total`` in the spectrum's own type;
``z`` (`:12`, ``fltarr``) is FLOAT whatever the spectrum's type, each
``z[j] = total(iwc_spec[i,0:j])`` (`:23`) -- a sequential prefix sum,
which is ``cumsum``; ``[0,z]`` is FLOAT; GDL's ``INTERPOL`` computes in
double and returns FLOAT (measured).

### `mvdiam`

```python
def mvdiam(conc_raw: np.ndarray, endbins: np.ndarray, nan: bool=False) -> np.ndarray
```

``mvdiam.pro`` (32 lines). ``conc_raw`` un-normalized concentration
(m^-3), ``[ntimes, nbins]``. ``midbins`` here is
``(endbins[1:]+endbins[:-1])/2`` -- read directly off ``mvdiam.pro:13``,
which writes it as ``(endbins[1:*] + endbins)/2.0``, two arrays of
*different* length (n-1 and n): IDL arithmetic between differently-sized
arrays silently truncates both operands to the smaller size, using each
operand's own *first* N elements -- so ``endbins[1:*][i] + endbins[i]``
for ``i in 0..n-2`` is exactly ``endbins[i+1] + endbins[i]``, the
ordinary midpoint formula. No IDL bug; just an unusual way to write it.

In IDL's types: ``volume=(!pi/6)*midbins^3*conc_raw[i,*]`` (`:19`)
is ``((!pi/6)*((m*m)*m))*conc`` in FLOAT (``!pi`` is FLOAT, ``^3`` an INT
exponent), ``tvolume`` a sequential ``total``, ``z`` a FLOAT ``fltarr``
of sequential prefix sums.

### `meandiam`

```python
def meandiam(conc_raw: np.ndarray, midbins: np.ndarray, nan: bool=False, minimum: float=0.0) -> np.ndarray
```

``meandiam.pro`` (29 lines). ``midbins`` (not ``endbins`` -- the
source's own ``:16`` guard checks this by comparing lengths and
``stop``s otherwise; reproduced as `ValueError`).

`:19` in IDL's types: ``total(conc*midbins)/(total(conc) > 0.0001)``,
both totals sequential in the operands' type, ``0.0001`` a FLOAT literal
and ``>`` IDL's maximum operator.

### `compute_bulk_simple`

```python
def compute_bulk_simple(conc1d: np.ndarray, endbins: np.ndarray, *, binstart: int | None=None, binstop: int | None=None, acoeff: float | None=None, bcoeff: float | None=None) -> dict[str, np.ndarray]
```

``compute_bulk_simple.pro`` (73 lines). ``conc1d`` in m^-4
``[ntimes, nbins]`` FLOAT, ``endbins`` in um. Returns a dict of one
FLOAT32 value (or ``[ntimes, nbins]`` array for ``msd``/``msdnorm``) per
key, matching the IDL structure's tag names.

NaN in ``conc1d`` is zeroed on this function's own working copy
(`:16-17`). Measured under GDL (bank case ``nan_and_inf``): the
write reaches the caller through a *bare variable* argument (by
reference) but not through a structure field (by value), and every
vendored caller passes a field (``data.conc1d``, ``(*p1).conc1d``), so
the private copy is the faithful reading.

**Arithmetic in IDL's types, bit for bit** (bank
the GDL bank ``run_soda2_compute_bulk_simple_bank.py`` (dev repository only),
all fifteen tags of
twelve cases bit-exact): every ``total`` is a sequential FLOAT sum
(`_idl_total`), ``^3`` is ``(x*x)*x`` (`_idl_cube`),
``alog10`` is double-rounded-to-FLOAT (`_idl_alog10`), and
``unnormalize``/``mmdiam``/``mvdiam``/``meandiam`` stay FLOAT. A pairwise float64 sum
differs from these by 1-2 float32 ULPs. ``acoeff``/``bcoeff`` are held
FLOAT, as the two export callers' are (``soda2_export_ascii.pro:16``
passes undefined ``a``/``b``, so the FLOAT defaults at `:7-8` apply;
``soda2_export_ncdf.pro:194-202`` passes none). The GUI callers
(``soda2_browse``/``soda2_compare``) pass widget values of unmeasured
type; a DOUBLE coefficient would promote the IDL computation to DOUBLE,
which this port does not model.

### `soda2_export_ascii`

```python
def soda2_export_ascii(data: Any, outfile: str | None=None, *, a: float | None=None, b: float | None=None, minsize: float | None=None, counts: int=0) -> str
```

``soda2_export_ascii.pro`` (158 lines), byte-for-byte. ``data`` is the
``ProcessData`` `arrayprobe_soda2.process_2d.soda2_process_2d`
returns: ``.op`` (a dict, lower-case keys, as elsewhere in this
package), ``.conc1d``, ``.spec1d``, ``.midbins``, ``.sa``, ``.time``,
``.date_processed``.

Returns the path written (``outfile`` if given, else the internal
default naming, `:63` -- not exercised by the driver, which always
passes ``outfile`` itself, `soda2_process_2d.pro:723-724`).

## `arrayprobe_soda2.enhancement_hooks`

Named hook points through which an optional correction package can substitute one port call.

### `HOOK_POINTS`

*(re-exported from elsewhere; not defined in this module)*

### `HookError`

```python
class HookError(RuntimeError)
```

A substitution was refused: unknown point, already overridden, or not pristine.

### `HookPoint`

```python
class HookPoint
```

One call the driver chain makes through a module-global binding.

``consumer`` is the module whose global the call site reads; ``provider`` the module that
defines the port's own function; ``attribute`` the name in both. ``call_site`` cites the
port line (and the IDL line it ports) where the binding is read.

### `Reconstruction`

```python
class Reconstruction
```

How a *fresh interpreter* rebuilds one `overridden` substitution from plain data.

A substitution is a mapping of point name -> **function object**, and a function
object neither pickles in general nor survives a ``spawn``-started worker's re-import of
the package -- which is why ``process_2d_parallel.refuse_unsplittable`` refused ``jobs >
1`` outright whenever anything was substituted. This dataclass is the narrow escape: the
installer states *how to build the same mapping again from data*, and both halves of it
are data.

``factory`` is ``"module.path:callable"``, importable by name in a fresh interpreter;
``payload`` is the one picklable argument it takes. `build` imports and calls it and
returns the mapping. The installer is responsible for the factory being a pure function of
its payload -- ``overridden`` checks that it rebuilds *the same point names*, which catches
a stale or mismatched plan, and the parallel path's byte-identity test is what proves the
rebuilt callables are the same corrections.

A caller that passes an ad-hoc lambda through `overridden` supplies no
reconstruction, and stays refused. That is the honest residual: the refusal narrows from
*"any live substitution"* to *"a substitution this process cannot rebuild by name"*.

### `active`

```python
def active() -> dict[str, str]
```

Points currently overridden -> the replacement's qualified name.

### `current`

```python
def current(name: str) -> Callable[..., Any]
```

What the call site behind point ``name`` would call right now.

### `original`

```python
def original(name: str) -> Callable[..., Any]
```

The port's own function behind point ``name``.

### `overridden`

```python
def overridden(replacements: Mapping[str, Callable[..., Any]], *, reconstruction: Reconstruction | None=None) -> Iterator[dict[str, str]]
```

Substitute the named bindings for the duration of the ``with`` block.

Yields `active`'s view of what was substituted. An empty mapping substitutes nothing
and is allowed, so a caller need not special-case "every correction off".

``reconstruction`` states how a fresh interpreter rebuilds ``replacements`` from
plain data; it is **checked here, not trusted** -- the factory is imported and called and
must produce the same point names, so a plan that has drifted from what is being installed
fails at install time rather than in a worker. Omitted, the substitution is process-local
and ``jobs > 1`` stays refused.

### `pristine`

```python
def pristine() -> dict[str, bool]
```

Per point: is the consumer's binding the port's own function (identity)?

### `reconstruction_plan`

```python
def reconstruction_plan() -> Reconstruction | None
```

The live substitution's `Reconstruction`, or ``None``.

``None`` means one of two different things and the caller must treat them the same way:
nothing is substituted, or something is and its installer gave no way to rebuild it in a
fresh interpreter. Only a non-``None`` plan licenses carrying the substitution into a
``spawn``-started worker (``process_2d_parallel``).

## `arrayprobe_soda2.save_writer`

The IDL SAVE file ``soda2_process_2d.pro:729-731`` writes --

### `IdlSaveUnsupported`

```python
class IdlSaveUnsupported(ValueError)
```

A value this writer cannot represent in an IDL SAVE file.

### `PROCESS_DATA_TAGS`

*(re-exported from elsewhere; not defined in this module)*

### `write_idl_save`

```python
def write_idl_save(path: str | Path, variables: Mapping[str, Any], *, compress: bool=False, timestamp: tuple[str, str, str] | None=None) -> Path
```

``save, file=path, <variables>[, /compress]``.

``variables`` maps each IDL variable name to its value (module docstring
for the type rules), written in mapping order. ``timestamp`` overrides
the ``(date, user, host)`` the ``TIMESTAMP`` record carries (default:
now in IDL's ``systime()`` form, this user, this host) -- tests pin it so
two writes of the same data are byte-identical.

### `save_process_data`

```python
def save_process_data(path: str | Path, data: Any, *, compress: bool=True, timestamp: tuple[str, str, str] | None=None) -> Path
```

``soda2_process_2d.pro:731``: ``save, file=fn_out, data, /compress``.

### `struct_layout`

```python
def struct_layout(value: Any) -> tuple[int, list[tuple[str, int]]]
```

``(size, [(TAG, offset), ...])`` of ``value`` as a 64-bit IDL
structure -- the offsets this writer puts in the descriptor.

## `arrayprobe_soda2.export_ncdf`

``soda2_export_ncdf.pro`` (462 lines) -- SODA-2's own netCDF

### `DimensionNameInUse`

```python
class DimensionNameInUse(RuntimeError)
```

``soda2_export_ncdf.pro:30-42`` names every bin dimension
``'Vector'+n_elements(...)``, so two different axes of the same length
get the same name. The driver's interarrival axis has 40 midbins and 41
endbins (``soda2_process_2d.pro:53-57``), so a size axis of 39, 40 or 41
bins collides: measured under GDL (case ``vector_collision``),
``NCDF_DIMDEF: (NC_ERROR=-42)`` halts at `:38` with the file open.

### `MinsizeBinstartOutOfRange`

```python
class MinsizeBinstartOutOfRange(IndexError)
```

``soda2_export_ncdf.pro:195-202`` -- ``i100``/``i200``/``i1000`` is
``min(where(data.op.endbins ge N))``: ``-1`` when no edge reaches ``N``,
and equal to ``numbins`` when only the *last* edge does. Either way
``compute_bulk_simple`` cannot run: the ``-1`` case halts three frames
down in ``mmdiam.pro:12`` (``fltarr(0)``, the same halt measured for
``soda2_export_ascii``'s ``minsize_above_bins``; SODA-2 register entry S7-b), the
``numbins`` case on a ``[binstart:binstop]`` subscript with
``low > high``. The port raises here, before calling it; the bank pins
that GDL halts too.

### `NoskipNonNumericNotPorted`

```python
class NoskipNonNumericNotPorted(NotImplementedError)
```

``soda2_export_ncdf.pro:167-170`` with ``noskip=1`` on a tag that is a
string or structure but has ``n_elements(data.time)`` elements: IDL would
multiply it by ``1.0`` and ``ncdf_varput`` it. Not ported.

### `PthfileNotPorted`

```python
class PthfileNotPorted(NotImplementedError)
```

``soda2_export_ncdf.pro:392-457`` -- ``pthfile`` makes the routine
``restore`` an IDL SAVE file into its own local ``data`` (and so, by
reference, into the caller's). No caller in the vendored tree passes it
(``soda2_export.pro:43`` does not).

### `compute_area`

```python
def compute_area(data: Mapping[str, Any], binstart: int=0) -> dict[str, np.ndarray]
```

``compute_area.pro`` (40 lines). ``data`` is the upper-cased tag
mapping `soda2_export_ncdf` builds. Returns ``area`` (FLOAT
``[ntimes]``, 1/m) and ``asd`` (FLOAT ``[ntimes, nbins]``).

### `compute_meanar`

```python
def compute_meanar(spec2d: np.ndarray, armidbins: np.ndarray) -> np.ndarray
```

``compute_meanar.pro`` (22 lines). ``spec2d`` ``[ntimes, nbins,
narbins]``; returns FLOAT ``[ntimes, nbins]``, 0 where a size bin holds
nothing.

### `idl_sfm2hms`

```python
def idl_sfm2hms(sfm: float) -> int
```

``sfm2hms.pro`` exactly: ``long(sfm)``, then ``10000*hour +
100*minute + sec`` with **no** wrap at 86400 s -- 86401 s is
``240001``. This name delegates to `arrayprobe_soda2.pbp_writer.sfm2hms`, so the two
cannot drift apart. `:56-57` feed it
``min``/``max(data.time)``, which do cross midnight (bank case
``past_midnight``; ``run_soda2_sfm2hms_bank.py``).

### `soda2_export_ncdf`

```python
def soda2_export_ncdf(data: Any, outfile: str, *, pthfile: str | None=None, lite: int=0, noskip: int=0, date_created: str | None=None, stamp_profile: str | None=None) -> str
```

``soda2_export_ncdf.pro`` (462 lines). ``data`` is a
`~arrayprobe_soda2.process_2d.ProcessData` or a mapping of IDL
tag name to value in IDL declaration order; ``data['op']``/``data.op``
is a mapping of ``op`` field to value, types as `_idl_value`
reads them. ``[ntimes, nbins]`` arrays are row-per-time, as
``ProcessData`` holds them. ``date_created`` overrides ``systime()``
(`:64`, non-deterministic) for tests. Returns ``outfile``.

### `write_run_psd`

```python
def write_run_psd(data: Any, *, outdir: str | None=None, date_created: str | None=None) -> str
```

Write the size-distribution netCDF ``<stem>.nc`` of a finished run.

``data`` is the `~arrayprobe_soda2.process_2d.ProcessData` that
``soda2_process_2d`` returns, the struct the IDL driver saves at
``soda2_process_2d.pro:729-731``. The file is `soda2_export_ncdf`
on that struct, unchanged, named as ``soda2_filename.pro`` names the
SAVE file with ``.nc`` for ``.dat`` -- the PSD file NCAR's pipeline makes
by restoring the SAVE file and calling ``soda2_export_ncdf, data``.
``outdir`` defaults to ``op.outdir``. Returns the path written.

## `arrayprobe_soda2.export_ncdf_raf`

``soda2_export_ncdf_raf.pro`` (312 lines): SODA-2's NCAR-RAF/nimbus netCDF export.

### `BulkAttnameCarryOver`

```python
class BulkAttnameCarryOver(IndexError)
```

`:296-301`: the bulk loop never resets ``attname``, so it inherits the
main loop's last value (reset each pass at `:84`). When the last tag of
``data`` is CONC1D (nine names, `:165`) or SPEC1D (four, `:190`), the
loop walks past the two-field bulk ``attvalue``: ``attvalue.(2)`` at
`:297` is out of range, and ``attname[0] = '_FillValue'`` already pairs
with the long-name string at `:300` (derived, not GDL-measured). IDL
halts with the file open; the port raises before writing a bulk tag.

### `FillValueOnExistingVariable`

```python
class FillValueOnExistingVariable(NotImplementedError)
```

`:223-229`: a CONC1D/SPEC1D output name that repeats an existing
variable re-puts ``_FillValue`` on it. netCDF4-python refuses a
``_FillValue`` after creation, so this path is refused by name.

### `MinsizeBinstartOutOfRange`

*(re-exported from elsewhere; not defined in this module)*

### `soda2_export_ncdf_raf`

```python
def soda2_export_ncdf_raf(data: Any, outfile: str, *, normalize: int=1, suffix: str='', legacybinning: int=0, date_created: str | None=None, stamp_profile: str | None=None) -> str
```

``soda2_export_ncdf_raf.pro``. Keywords as IDL's (`:7-9` defaults).
``date_created`` overrides ``systime()`` (`:47`, non-deterministic).

### `sps1_size`

```python
def sps1_size(rate: Any) -> int
```

`:19` ``(1.0/data.op.rate)>1``: FLOAT (DOUBLE for a DOUBLE rate),
truncated to a long dimension size.

## `arrayprobe_soda2.sea`

SODA-2's SEA M300 buffer walk for the CIP : ``readdatadir.pro``,

### `DataDir`

```python
class DataDir
```

``readdatadir.pro:4-5``'s ``datadir`` structure.

### `SeaPointers`

```python
class SeaPointers
```

``seaimagepointers.pro:81-82``'s return.

### `SeaBuffer`

```python
class SeaBuffer
```

``readseabuffer_caps.pro:45-47``'s return (``eof == 0``).

### `SeaEOF`

```python
class SeaEOF
```

``{starttime:999999, image:0, eof:1}`` -- the end-of-file return of
``seaimagepointers.pro:8,62,64`` and ``readseabuffer_caps.pro:9``.

### `readdatadir`

```python
def readdatadir(f: BinaryIO) -> DataDir
```

``readdatadir.pro`` -- one 16-byte directory at the current position.
A short read is IDL's ``readu`` "End of file encountered" halt.

### `seaimagepointers`

```python
def seaimagepointers(f: BinaryIO, tag: int | np.ndarray | list[int]) -> SeaPointers | SeaEOF
```

``seaimagepointers.pro:1-83``. ``tag`` is a scalar (``readseabuffer_caps``
always passes one) or up to three tags ``[image, tas, elapsed]``.

### `readseabuffer_caps`

```python
def readseabuffer_caps(f: BinaryIO, tag: int | np.ndarray, probetype: str) -> SeaBuffer | SeaEOF
```

``readseabuffer_caps.pro:1-48``, ``probetype`` ``'CIP'``/``'CIPG'`` (a
``numberbytes``-long BYTE image) or ``'CIP1D'`` (a `CIP1D_DTYPE`
record). ``'CAS'`` is refused by name (no CAS route in this port).

### `idl_sfm`

```python
def idl_sfm(hms: float) -> float
```

``sfm.pro`` / ``hms2sfm.pro`` (identical bodies) for a DOUBLE ``hms``,
including a non-finite or out-of-LONG-range one: every step is the IDL
LONG arithmetic, then ``fraction = double(hms) - long(hms)`` is added, so
a NaN or infinite ``hms`` gives back the same non-finite value whatever
``long()`` returned (derived; the GDL value of ``long()`` is used).

### `CIP1D_DTYPE`

```python
CIP1D_DTYPE: dtype
```

## `arrayprobe_soda2.decompress_dmt`

SODA-2's DMT CIP image decoder : ``decompress_dmt3.pro`` (133

### `HeaderSlice`

```python
class HeaderSlice
```

``decode_header_slice.pro:37``'s return. ``particle_count``,
``slice_count``, ``time`` and ``time_sfm`` are 1-element arrays in IDL
(``bin2dec`` returns ``ulonarr(n)``); scalars here, the values are the
same.

### `Dmt3Result`

```python
class Dmt3Result
```

``decompress_dmt3.pro:129-131`` (``null=False``) or the ``nullbuffer``
of ``:18-19`` (``null=True``: ``slice_count`` 0, ``header_slice_count``
999, everything else 0 -- so the caller's ``good1`` test at
``soda2_processbuffer.pro:134`` finds nothing).

### `decode_header_slice`

```python
def decode_header_slice(header: np.ndarray) -> HeaderSlice
```

``decode_header_slice.pro``. ``header`` is 8 values 0..255 (the INT
slice of the decompressed image); only each value's low 8 bits are read
(``dec2bin8.pro:9``).

### `decompress_dmt3`

```python
def decompress_dmt3(cimage: np.ndarray) -> Dmt3Result
```

``decompress_dmt3.pro``: ``cimage`` is the BYTE buffer as read
(``readseabuffer_caps.pro:34``, 4098 bytes for the UND CIP).

## `arrayprobe_soda2.processbuffer_cip`

``soda2_processbuffer.pro``, the CIP branch (`:129-203`).

### `CipOp`

```python
class CipOp
```

The ``(*pop)`` fields the CIP branch reads.

### `CipMisc`

```python
class CipMisc
```

The ``(*pmisc)`` fields the CIP branch reads and writes
(``soda2_process_2d.pro:39-41``: ``lastclock:0d``, ``lastparticlecount:0L``).

### `CipBufferParticles`

```python
class CipBufferParticles
```

The branch's locals at `:203`, what the shared tail consumes (the
attribute names `processbuffer_tail.process_buffer_tail` reads).
``bitimage`` is ``(slices, 64)``, slice first (the package convention).

Source: ``soda2_processbuffer.pro`` (SODA-2); bare line references here are into that file.

### `process_cip_buffer`

```python
def process_cip_buffer(image: np.ndarray, buffer_time: float, buffer_stoptime: float, buffer_tas: float, op: CipOp, misc: CipMisc) -> CipBufferParticles | NullBuffer
```

``soda2_processbuffer.pro:129-203``. ``misc`` is mutated in place where
the IDL writes ``(*pmisc)``; the returned ``stoptime`` is the value the
IDL leaves in the caller's ``buffer.stoptime``.

### `soda2_processbuffer_cip`

```python
def soda2_processbuffer_cip(image: np.ndarray, buffer_time: float, buffer_stoptime: float, buffer_tas: float, op: CipOp, tail_op: Any, misc: CipMisc, lastdhist: Any) -> tuple[Any, float]
```

``p = soda2_processbuffer(b, pop, pmisc)`` for ``probetype 'CIP'``, the
whole function (`:129-203` then `:612-747`). Returns ``(p, stoptime)``:
``p`` a `NullBuffer` or `processbuffer_tail.ProcessedBuffer`,
``stoptime`` the caller's ``buffer.stoptime`` afterwards (unchanged on a
null return).

Source: ``soda2_processbuffer.pro`` (SODA-2); bare line references here are into that file.

## `arrayprobe_soda2.processbuffer_f2dc`

SODA-2 ``soda2_processbuffer.pro:28-78``, the Fast-2DC branch

### `F2dcOp`

```python
class F2dcOp
```

The ``(*pop)`` field the branch reads.

### `F2dcMisc`

```python
class F2dcMisc
```

``(*pmisc)`` fields the branch reads and writes (``soda2_process_2d.pro:39``).

### `process_f2dc_buffer`

```python
def process_f2dc_buffer(image: np.ndarray, buffer_time: float, buffer_tas: float, op: F2dcOp, misc: F2dcMisc) -> NullBuffer | CipBufferParticles
```

`:28-78`. Mutates ``misc`` as the IDL writes ``(*pmisc)``.

### `soda2_processbuffer_f2dc`

```python
def soda2_processbuffer_f2dc(image: np.ndarray, buffer_time: float, buffer_tas: float, op: F2dcOp, tail_op: Any, misc: F2dcMisc, lastdhist: Any) -> Any
```

``p = soda2_processbuffer(b, pop, pmisc)`` for Fast-2DC: `:28-78` then
the shared tail `:612-747`. Returns a `NullBuffer` or
`processbuffer_tail.ProcessedBuffer`.

### `F2DC_REMAINDER_CAPACITY`

```python
F2DC_REMAINDER_CAPACITY: int
```

## `arrayprobe_soda2.processbuffer_2dc`

SODA-2 ``soda2_processbuffer.pro:80-127``, the 2DC branch (probetype ``'2DC'``,

### `TwoDcOp`

```python
class TwoDcOp
```

The ``(*pop)`` fields the branch reads.

### `TwoDcMisc`

```python
class TwoDcMisc
```

``(*pmisc).lastclock`` (``soda2_process_2d.pro:39``), read and written at `:118-120`.

### `process_2dc_buffer`

```python
def process_2dc_buffer(image: np.ndarray, buffer_time: float, buffer_tas: float, op: TwoDcOp, misc: TwoDcMisc) -> NullBuffer | CipBufferParticles
```

`:80-127`. Mutates ``misc`` as the IDL writes ``(*pmisc)``. The returned
``stoptime`` is ``buffer.stoptime`` after the branch (`:82`, `:124`).

## `arrayprobe_soda2.fix2dimage`

SODA-2 ``fix2dimage.pro`` (28 lines): rewrites NCAR-format sync/timing slices of

### `fix2dimage`

```python
def fix2dimage(image: np.ndarray) -> np.ndarray
```

Port of ``fix2dimage.pro:1-28``. Returns a new ULONG array (or the input,
unchanged, on the two early returns, as IDL returns ``image`` itself).

## `arrayprobe_soda2.backfill`

Bug-for-bug port of ``SODA2/abansemer-soda2-afcea15/soda2_backfill.pro``.

*No public API declared (`__all__` empty or absent).*
