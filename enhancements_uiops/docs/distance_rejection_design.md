# Inter-particle distance rejection — design record

Written 2026-09-10.

## Citation, read directly from the primary source

Korolev & Field 2015, *AMT* **8**, 761–777, doi:10.5194/amt-8-761-2015 — Sect. 4, pp. 765–766:
reject on inter-particle **distance** Δx rather than time, removing the TAS drift of a fixed Δt.

**Status upgraded from `derived` to `measured`, 2026-09-10.** The paper is open access
(Copernicus, CC-BY 3.0) and was fetched and read directly from
`https://amt.copernicus.org/articles/8/761/2015/amt-8-761-2015.pdf` — pp. 764, 765, 766 and 768
read as page images. Everything below is checked against the source text itself, not against
the plan's quoted description. Doing so resolved the open dimensional question an earlier revision of this
document carried; see the finding section below.

## What the module implements

`enhancements_uiops/src/arrayprobe_enhancements/distance_rejection.py`:

- `distance_from_time(int_arr, tas) = int_arr * tas` — Δx = Δt·u, elementwise, using each
  particle's own LOCAL true airspeed.
- `threshold_to_distance(ia_thresh, reference_tas) = ia_thresh * reference_tas` — converts the
  port's fitted time threshold to a distance ONCE, at a single reference airspeed (the mean TAS
  of the block the threshold was fitted over, in the intended use — the caller supplies it; this
  module does not compute a mean itself).
- `is_shattered_by_distance(int_arr, tas, threshold_distance) = distance_from_time(int_arr, tas) < threshold_distance`.

The threshold is calibrated once, as a fixed distance, and then compared against each particle's
own actual local-TAS-derived distance. This is what makes it differ from the time-only test at
all: if the calibration TAS and the local TAS were the same value substituted on both sides, the
TAS cancels algebraically and the test degenerates to the original time comparison. Tests
(`test_distance_rejection.py`) pin both properties directly: **agreement** with the time-only
test at the reference TAS, and **divergence** away from it (a pair the time test would flag
becomes un-flagged at high TAS; a pair the time test would not flag becomes flagged at low TAS).

## RESOLVED — a finding about the published paper, not about this project

**This section is a finding about Korolev & Field (2015) itself**, in the spirit of
a bug report but addressed to the literature rather than to UIOOPS: objective,
checkable by anyone holding the paper, and stated without inferring intent. Raised and closed
2026-09-10 by reading the source.

### The finding

**Korolev & Field (2015) prints its time-to-distance conversion as a division by airspeed, in
two places, and the printed form is dimensionally impossible.**

| Where | Printed exactly as | Problem |
|---|---|---|
| p. 765, Sect. 4, final paragraph | "the inter-particle distance Δx = Δt/u will be used instead of Δt" | Δt/u has units s/(m s⁻¹) = s² m⁻¹, not a length |
| p. 766, Sect. 4, first line | "χ* = τ*/u will be used instead of φ(Δt) and τ*, respectively" | same, for the cut-off |

The intended operation is plainly **multiplication** — Δx = Δt·u, χ* = τ*·u. Three confirmations,
each from the paper's own content, so no external assumption is needed:

1. **Units.** p. 764 defines `u` unambiguously: "τ = 1/nSu is the average inter-arrival time…
   *u* is the sampling speed". That expression only yields seconds with `u` a speed, so `u` is a
   speed wherever it appears, and dividing a time by it cannot give a length.
2. **The paper writes the identical relation correctly in the inverse direction**, p. 764:
   "Δt_sh = L_sh/u is the duration of the shattering event", where `L_sh` is defined in the same
   sentence as "the spatial length of the shattering event along the flight direction (i.e.,
   distance between the first and last fragments)". Division by `u` is therefore the
   distance → time conversion; time → distance must multiply. **This is the strongest evidence:
   the paper is internally inconsistent with itself two pages earlier, which is the signature of
   a typesetting slip rather than a different convention.**
3. **The paper's own figure axes.** Fig. 5 (p. 766) plots "Inter-particle distance (m)" over
   ~10⁻³–10² m, with the red cut-off lines labelled χ*. OAP inter-arrival times of ~10⁻⁶–10⁻² s
   at ~100 m s⁻¹ give Δt·u ≈ 10⁻⁴–10⁰ m, which falls on that scale; Δt/u ≈ 10⁻⁸–10⁻⁴ m, which
   does not. The figure could not have been produced by the printed equation.

### Consequences for this project

- **This project's transcription was faithful, not mistaken.** The plan row's `χ* = τ*/u`
  correctly quotes what the paper prints. There was nothing to fix in the citation — the error
  is upstream, in the published text.
- **`χ*` is the cut-off distance**, the distance analogue of the cut-off time `τ*` — explanation
  (a) of the two an earlier revision of this document listed. It is exactly the quantity
  `threshold_to_distance` already returns. No second function is needed, and explanation (b) (a
  dimensionless ratio) is ruled out by Fig. 5 plotting χ* directly on a metre axis.
- **No computed number changes.** `distance_rejection.py` implemented `Δx = Δt·u` from the start,
  having declined to copy the dimensionally-inconsistent form. The code was already right; only
  its own statement of uncertainty was out of date.

### The check, because a note is not a control

The live risk this creates is the *opposite* of the usual one: a future reader who obtains the
PDF, sees `χ* = τ*/u` printed in black and white, and "fixes" the code to match it — silently
changing every distance by eight orders of magnitude with the paper apparently on their side.
`tests/test_distance_rejection.py::ThePaperPrintsThisEquationWrong` exists for exactly that
reader. It pins the conversion against the magnitudes of the paper's own Fig. 5 and fails with a
message pointing here, so the mistake cannot be made quietly.

## What this does not change

Additive only. `arrayprobe.sizedist` and its own time-based `_reaccept_shattered` /
inter-arrival test are untouched — this enhancement is applied by a caller, after the fact, to
data the port already computed (inter-arrival times, TAS), the same shape `outoffocus.py`
already established for a Korolev-family correction with no MATLAB oracle to check against.

## Validation status

Unit-tested against the algebra directly (no oracle exists or could exist for this — SODA-2's
own port, once it exists, uses a comparable idea per its documented "custom DoF curve"-style
feature list, but that is a different mechanism, not a source of ground truth for this one).
**Not yet checked against a real flight.** A real-data A/B (the same shape the enhancement rows for the diode-32 hollow test, the abandoned zero-image record and the duplicate TAS-second particle loss use) would need: a TAS-sidecar's own drift within one flight leg (measured, not
assumed — check whether any held flight's `.tas.csv` shows meaningful TAS variance within a
single shattering-fit block before claiming this enhancement changes anything on real data), and
a chosen `reference_tas` convention (this design leaves that choice to the caller). Both are
open items for whoever picks this up next.
