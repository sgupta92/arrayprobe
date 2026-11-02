# `dmax_sensitivity.py` — the six `d_choice` diameters, compared

**What "six-D_max switch" turned out to mean, measured rather than assumed.** The six
diameter definitions `sizeDist.m:755-767` selects between (`sizeDist.d_choice`, 1-6)
already exist and are already faithfully ported — `arrayprobe.sizedist._D_CHOICE_SPECS`.
There was no missing sixth definition and no new "switch" to build; the real gap was that
nothing showed how far the six answers actually diverge *for the same particle*. That is
what this module does, calling the port's own diameter functions directly rather than
re-deriving them, so a change to the port's own math is reflected automatically.

## The measurement, real particles, not synthetic

99 particles from the S4 aspect-ratio processed file, a real-data fixture that is not distributed
(`enhancements_uiops/tests/test_dmax_sensitivity.py::RealParticles`, printed verbatim):

| Statistic | Value |
|---|---|
| Particles | 99 |
| Excluded (non-finite spread — zero-image artifacts) | 2 |
| Mean relative spread across the six choices | **227.95 %** of the six-way mean |
| Max relative spread (one particle) | 351.47 % |
| Mean absolute spread | 0.388 mm |

**The spread is large and real, not a rounding artifact.** The two int16-saturation
findings this module surfaced along the way (both already documented as the int16 diameter saturation,
confirmed again here on real data rather than re-asserted):
`d_length`/`d_width`/`d_mean`/`d_max` all saturate through `int16`, so they agree with
each other exactly whenever length equals width; `d_hypot` alone escapes, because `sqrt`
promotes to `double` before the final multiply. A square particle therefore disagrees with
itself by definition — the hypotenuse of a square is never equal to its side — which is
why even a "square" case in the unit tests shows non-zero spread.

## What this module is, and is not

- **Not a fidelity change.** It calls `_D_CHOICE_SPECS`'s six functions unmodified; nothing
  about the port's own computed numbers changes by this existing.
- **A capability**, the same shape as `arco_export.py`/`particle_clustering.py`: it answers
  "how much does this choice matter" for a reader deciding which `d_choice` to trust for
  their own analysis, which the port's own six-way registry cannot answer by itself.
- **`DChoiceSensitivity.summary()`** is the reusable entry point; a notebook or report can
  call `compute_sensitivity(image_length, image_width, diodesize, image_diam_minR)` on any
  proc file's arrays and get the same table.

## Not done in the 30-minute window this was built under

- No CLI/notebook wiring yet — `compute_sensitivity` is library-only.
- Not measured on more than one flight/fixture; whether 227.95 % mean spread is typical or
  this fixture's own particle-size mix is unknown.
- Not added to `enhancements_uiops/BACKLOG_STATUS.md`,
  `enhancements_uiops/README.md`, or `applicability_matrix.md` by the build itself — shared bookkeeping is
  reconciled centrally rather than module by module, to avoid concurrent edits when
  several modules land the same day. All four now carry it.
