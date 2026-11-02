# Using Octave to stand in for MATLAB — the objection, and the answer

*Written 2026-08-19. This is the first question any reviewer should ask about this
port's validation.*

## The objection, stated fairly

> You validated a Python port against **GNU Octave**, not against MATLAB. Octave
> is a separate implementation by different people. So "bit-exact" means
> bit-exact *against Octave* — which tells me nothing about whether the port
> reproduces the MATLAB that actually produced the published science.

That is a fair objection, and it is not fully answerable in the abstract. What
follows is what the risk reduces to, what was done about each part, and how a
sceptic can falsify any of it cheaply.

## 1. The claim is layered, and every result says which layer it rests on

Validation here is three layers, and they are **not** interchangeable:

| Layer | What it is | Strength |
|---|---|---|
| **1** | Agreement with **MATLAB-written output of record** — the ORACLES reference product, produced by real MATLAB before the licence lapsed | Decisive. MATLAB is in the loop. |
| **2** | Agreement with **Octave running the unmodified `.m`** | Strong evidence, not proof. This document is about layer 2. |
| **3** | Documented semantics plus pinned tests, where neither of the above reaches | Weakest; labelled as such. |

Octave is a **development** oracle. The MATLAB-written product is the
**acceptance** oracle. S4's gate is the reference product, not Octave — so the
final claim of this project does not rest on layer 2 at all.

Layer 1 has already fired twice, independently of Octave: `constants.py`'s 2D-S
bin ladder matches the archived product (128 bins, 0.005–1.285 mm), and
the SPEC header-slice layout checks out field by field against a MATLAB-written
image file.

**The claim is "to every printable digit", not "exactly", and the difference is measured** — see §2's
colon entry below. The ladder agreed to every printable digit and in every bin
count, and differed from the product in the last bit of 34 of its 129 edges. The
correction matters more than the defect: it is the clearest case in this project
of a layer-1 check that was *run* but not run at the precision it claimed.

## 2. Where Octave and MATLAB could actually differ — and what was done

The risk is not "different language". It is a short, enumerable list:

### Arithmetic on doubles — **no risk, by standard**

`+`, `-`, `*`, `/` and `sqrt` are required by IEEE-754 to be *correctly rounded*.
Any two conforming implementations produce bit-identical results; there is no
implementation freedom to differ. The overwhelming majority of this codebase is
double arithmetic, and that is why bit-exactness is the right bar rather than a
tolerance.

`exp`, `log` and the transcendentals are **not** required to be correctly
rounded, and both Octave and MATLAB defer to the platform `libm`. Where a ported
routine depends on one (`dropsize`'s lookup interpolation does not; `sizeDist`'s
mass–dimension relations do), that is stated at the site.

### Integer semantics — **the one real risk, and it was measured**

MATLAB's integer types saturate, round half away from zero, and dominate doubles
in mixed expressions. This is genuinely implementation-defined behaviour and it
matters enormously here (the MATLAB int16-times-double promotion rule — `int16 × double` collapses
`particle_diameter_minR` for four of the six size methods).

It was closed by **measurement, not assumption**:

```matlab
int16(37) * 0.010   % 0      -- not 0.37
int16(50) * 0.010   % 1      -- rounds half away from zero
int16(300)^2        % 32767  -- saturates
sqrt(int16(300)^2)  % 181    -- but sqrt PROMOTES to double
```

Octave documents MATLAB compatibility for integer arithmetic as an explicit
design goal, and these results match the documented MATLAB behaviour. **And the
port encodes them as tests** — so this is a specific, falsifiable claim, not a
hand-wave. Anyone with a licence can check the four lines above in under a
minute.

This is also the one place the upstream findings document explicitly asks the
original developers to double-check us: the `int16 × double` saturation that
collapses `particle_diameter_minR` for four of the six size methods.

### Summation order — **a real difference, found at S4, and it cuts both ways**

`sum` is not correctly rounded in the IEEE sense; the standard says nothing about
the *order* of a reduction, so two conforming implementations may legitimately
disagree in the last bits. Three things were measured at S4, and they are not the
same answer:

| Reduction | What it does | Port matches by |
|---|---|---|
| Octave `sum(x)` / `sum(x, dim)` | plain in-order accumulation | `matlab_compat.msum` — `np.cumsum(...)[-1]`, verified equal to a Python loop across sizes 3–5,000 and eight decades of magnitude |
| statistics-package `nansum`, `nanmean` | zero the NaNs, then plain `sum` | the same |
| **Octave core `mean`** | **compensated** | *deliberately not matched by default* |

NumPy sums **pairwise**, which is more accurate than either and matches neither.
Before this was noticed, 20 of 4,110 values of `n` and 23 of `re` missed the
oracle by 2–5 ULP; switching to in-order accumulation made them exact. So the
NumPy default was a fidelity defect that had not yet been asked a sharp enough
question.

**And `mean` is where Octave stops standing in for MATLAB.** Octave 11.3 rewrote
`mean.m` to route through `robust_mean_sum`, which calls `sum(x, dim, "extra")` —
a double-double accumulator. MATLAB's `sum` has no `"extra"` option and its
`mean` does not compensate. Read it yourself:

```
share/octave/11.3.0/m/statistics/mean.m   ->  robust_mean_sum()
    m = sum (x, dim, "extra") ./ n;
```

So for the one `sizeDist` output built with a plain `mean` — `ar`, from
`:1196` — **the oracle is more accurate than the thing it stands in for**, and
matching it bit-for-bit would mean *departing* from MATLAB. The port follows
MATLAB and pays 39 values of 4,110 differing by ≤ 2.1e-15; `run(octave_mean_extra=True)`
reproduces Octave exactly instead, and the test suite pins both states. The
comparison tool grew a tolerance class (**G**) for exactly this situation, which
its original six had no slot for.

This is the first case in the project where the two implementations genuinely
disagree and the *oracle* is the one in the wrong. Worth remembering as the
general shape: an oracle is evidence about the target, not the target itself.

### The colon operator — **Octave and MATLAB genuinely differ, measured 2026-09-03**

`a:d:b` is not the naive `a + k*d`. **MATLAB fills the vector from both ends
toward the middle**: the lower half as `a + k*d`, the upper half as
`last - (m-k)*d` with `last = a + m*d`. The two routes disagree in the last bit.
**Octave computes `a + k*d` throughout.**

This reached written output. `sizeDist.m:134` builds the 2D-S ladder as
`kk = diodesize/2 : diodesize : (num_bins+0.6)*diodesize`, and the port's
`_colon` used the naive form. Against the archived product's own bytes:

| | |
|---|---|
| Edges differing | **34 of 129**, every one in the upper half |
| Size of each difference | 2.2e-16 mm (one ULP) |
| Octave's `0.005:0.010:1.286` | identical to the naive form — **agrees with the defect** |
| Particles whose bin changed | **0**, measured over `proc.base160906064403.H.nc` |

So the consequence was confined to the four edge variables the port *writes*
(`Bin Minimum`, `Bin Maximum`, `Bin Midpoints`, `Bin Width`), which were not
byte-identical to MATLAB's. Fixed in `constants._colon`; pinned against a
fixture lifted from the product's bytes by `tests/test_bin_ladder.py`, which
also asserts the naive construction *would* fail — a test that passes against
both constructions protects nothing.

**This is the sharpest case of the pattern above: an oracle that agrees is not
proof.** Running the `.m` under Octave would have confirmed the wrong ladder
with complete confidence. Only layer 1 — MATLAB-written bytes — could catch it.
It is also why the layer-1 claim in §1 had to be corrected: the check had been
run, but at a precision that could not see the defect it was supposed to
exclude.

### Things Octave is *not* trusted for here

Stated so the boundary is visible:

- **`mean`** — see above. Compensated in Octave 11.3, not in MATLAB.
- **`textscan(..., Inf, ...)`** — MATLAB reads to end of file; Octave errors with
  `REPEAT = inf is too large`. Hit at S4 in `loadTASinfo_2DS.m`, which is
  ORACLES-local Import-Tool output, not part of distributed UIOOPS. Shimmed at
  the shim `loadTASinfo_2DS.m` (not included in this release). **This is an Octave limitation, not a
  MATLAB defect**. The shimmed
  function is a two-column CSV reader with no arithmetic, so nothing `sizeDist`
  *computes* is shim-derived — a weaker asterisk than `CGAL_minR`, and the
  distinction is worth keeping.
- **Robust `nlinfit`** (`IntArrAnalysis.m`) — no equivalent with matching
  semantics exists in Octave *or* SciPy. That module can never be bit-exact and
  needs a stated tolerance policy.
  Measured 2026-10-05: Octave's `statset` drops `'Robust','on'` with only an
  "unrecognized option" warning (`IntArrAnalysis_time.m:153`), so an Octave run
  is a *non-robust* fit; on HVPS 160906 block 1 that alone moves the threshold
  from the port's 4.12e-4 s to Octave's 2.57e-4 s.
- **The colon operator `a:d:b`** — see above. Octave fills naively, MATLAB fills
  from both ends. Any ladder or grid built with a colon must be pinned against
  MATLAB-written bytes, never against Octave.
- **Byte-level netCDF file format.** Octave's netCDF writer was checked for
  *values*, and it emits NETCDF3_CLASSIC with MATLAB's dimension structure — but
  for format questions the MATLAB-written reference product remains the
  authority.
- **Random number generation.** Nothing ported so far uses it; if something does,
  it cannot be cross-validated this way.

## 3. The empirical argument, which is stronger than the theoretical one

If Octave were meaningfully diverging from MATLAB on this code, the symptom would
be **noise** — scattered small mismatches across many outputs. That is not what
was observed:

| Stage | Comparison | Result |
|---|---|---|
| habit and reject | 105 particles × 16 outputs of `holroyd` + `calculate_reject_unified` | **zero mismatches, bit-exact** |
| `dropsize` | 127 `dropsize` argument tuples | **124 bit-exact first run**; the other 3 kill MATLAB and were recorded as errors |
| S3 | 41 written variables of `imgProc_sm`, both source trees | **40/41 bit-exact first run**; the 41st is shim-derived and agrees to 1 ULP |
| S3-OLYMPEX (**v3.1.4 engine**; the default is v3.5 and this has not yet been re-measured under it) | 41 written variables of `imgProc_sm` over **69,656 ice-phase particles** (HVPS 59,551 + 2D-S 10,105), against unmodified `imgProc_sm` under Octave with the **real** `CGAL_minR` MEX | **40/41 bit-exact.** The 41st is `image_diam_minR`: 1,519/59,551 (HVPS) and 95/10,105 (2D-S) differ, **all at 1-2 ULP**, max relative 4.01e-16 -- and here it is oracle-derived, not shim-derived, which is what makes this row stronger than the S3 row above rather than a repeat of it. |
| S4 | 25 written variables of `sizeDist` over 4,110 s × 128 bins of real flight data — 5.3 million values | **24/25 bit-exact, no shim on anything computed**; the 25th is the `mean` case above, and it is exact too when the port is asked for Octave's `mean` |

Hundreds of independent values agreeing to the last bit, on first run, is not
what a subtly-different arithmetic implementation produces. The null hypothesis
"Octave differs here" predicts scatter; exactness was observed instead.

## 3b. The oracle reaches further than this document said — two findings from the version work

Both come from the UIOOPS version comparison of 2026-09-03, which ran v3.1.4 and
v3.5 side by side under Octave. Neither is about Octave's *correctness*; both are
about its *reach*, and one of them removes an asterisk this document has carried
since S3.

**A real `CGAL_minR` MEX can be built per version, so `image_diam_minR` need not be
shim-derived.** The S3 row above — "the 41st is shim-derived and agrees to 1 ULP"
— reflected the belief that the `CGAL_*` routines were unreachable here. They are
not: `mkoctfile` compiles them from the shipped `.cpp` sources. **Build with
`-DNDEBUG`.** Without it, `Miniball.hpp:192`'s assertion aborts the interpreter on
an empty point set, where a MATLAB release build returns `NaN` — so the debug
build does not merely differ, it takes the session down. The header of
the shim `CGAL_minR.m` (not included in this release) had already reasoned this out correctly from the source; the
build confirms it.

**The versions are not drop-in comparable, and sharing one MEX between them would
silently corrupt the result.** v3.5's `CGAL_minR` takes a TAS-ratio input and
returns the circle *centre*, which its new hollow rule depends on; v3.1.4's does
neither. One MEX per version is a requirement, not a convenience. This is the same
class of error as the colon operator above — two things that look interchangeable,
where using one for the other produces plausible numbers rather than an error.

The general point for this document's argument: **"it calls MEX" was a weaker
blocker than it was written to be**, exactly as "it calls netCDF" turned out to be
in S2. Both were established by reading a call list rather than by measuring.

**And the exceptions behaved the way the argument predicts.** Two genuine
divergences have been found, at S4, and neither was noise: both were a single
named function with a single named cause, both were root-caused within an hour,
and one of them turned out to be Octave being *better* rather than different.
Scattered small mismatches would have been the worrying outcome; two crisp,
explicable ones are what a sound oracle looks like when you finally push it hard
enough to find its edges.

## 4. The oracle earns its place by what it *found*

A validation method that only confirms is hard to trust. This one produced
findings that careful source-reading had missed, and corrected several of our own
written notes:

- the hollow test packs diodes 1–32 whatever the probe, so particles beyond
  diode 32 are ruled hollow **on no evidence** (measured, not read);
- reject code `'t'` is unreachable, because the looser threshold is tested second;
- three `dropsize` inputs make MATLAB *die*, recorded as expected errors so
  crash-fidelity is measured rather than argued;
- and, at S3, that `mod(kk, 66536)` reaches no output at all — which an earlier published claim
  had wrong.

## 5. How to falsify any of this in five minutes

This is the part that matters, and it is why every fixture is **committed**
rather than gitignored.

Anyone with a MATLAB licence can:

1. take the input banks in `tests/data/` (`s1b_particles.txt`,
   `s1c_dropsize_cases.txt`, `2DS_s3_input_fixture.nc`);
2. run the *unmodified* UIOOPS `.m` files over them in MATLAB;
3. diff the result against the committed golden files
   (`s1b_octave_golden.csv`, `s1c_octave_golden.csv`,
   `s3_variant_octave_golden.nc`, `s3_stock_octave_golden.nc`).

Any disagreement is a real finding and we want to hear it. Nothing about this
setup requires trusting the port, whoever wrote it, or Octave — only
running one command and comparing two files.

**If a licence ever becomes available, this is the single highest-value hour that
could be spent on the project**, and it should be spent before any public
release.

## 6. What we would say to a reviewer, in one paragraph

> The port's acceptance criterion is agreement with MATLAB-written output of
> record, not with Octave. Octave is used as a *differential* oracle during
> development, on files that are pure base MATLAB, and the arithmetic involved is
> overwhelmingly IEEE-754 double precision where two conforming implementations
> are required to agree bit-for-bit. The one genuinely implementation-defined
> area — integer saturation and promotion — was measured explicitly, is encoded
> as tests, and is flagged to the original developers for confirmation. Every
> input bank and the goldens that carry no campaign data are committed, so any of it can be re-run
> against real MATLAB and diffed in minutes. Where Octave cannot substitute
> (robust `nlinfit`, byte-level file format), that is stated rather than papered
> over.
