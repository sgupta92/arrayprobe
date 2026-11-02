# Validation
> What the port reproduces, measured against MATLAB-written output — and how each claim is established. The per-flight figures were measured with the v3.1.4 port, which reproduced the archived products and is not part of this package.

Cite SODA-2 as: Aaron Bansemer. (2026). abansemer/soda2: v2.26.0 (Version v2.26.0) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.18331418

| | |
|---|---|
| **Flights validated (v3.1.4 port)** | **15** — 6 of 6 held for 2016, and 9 of the 2017 flights with raw input |
| **Exact** | **10** — **2017-08-24 (43,416 / 43,416 cells)**, 2017-09-02 (37,541 / 37,541), 2017-08-13 (33,027 / 33,027), 2017-08-21 (15,953 / 15,953), 2017-08-28 (12,786 / 12,786), 09/10 (5,064 / 5,064), 2017-08-15 (4,810 / 4,810), 2017-08-18 (1,529 / 1,529), 2017-08-12 (1,416 / 1,416) and 09/25 (160 / 160) |
| **Worst** | 2017-08-17, 99.63 % (268 / 269 — one open cell, not yet root-caused) |
| **Differing cells, 2016** | 48 — and **none** has both products holding a disagreeing count |
| **Headline denominator** | non-zero cells in bins 6+ |
| **What "exactly" covers** | two variables of the combined 2D-S product, `Counts` and `Size Distribution cm-3`, in size bins 6 and above, over every second both products hold. A cell is counted when either product holds a non-zero value there, and *exactly* means every counted cell is equal, with no tolerance. Outside the claim: bins 1-5, seconds only one product holds (reported per flight as uncovered), and the product's other variables |

**See also** [Glossary](11-glossary.md) — what a cell, a bin and the four denominators are; the numbers above are meaningless without it.

## The evidence ladder

![The evidence ladder: layer 1 reproduces an archived product (an earlier v3.1.4 translation, not shipped, on ORACLES; 0 of the shipped engines' coverage-matrix cells); layer 2 matches the original source executing under Octave or GDL (the two shipped engines, 49 coverage-matrix cells); layer 3 is adjudicated by eye with n and the labeller stated.](figures/evidence_ladder.svg)

Every validation claim rests on one of three kinds of evidence, not three grades of the
same thing — the three questions above. Layer 1 was reached by an earlier v3.1.4 translation
(not shipped), on ORACLES; none of the shipped engines'
[70 coverage-matrix cells](https://github.com/sgupta92/arrayprobe/blob/main/docs/developer/COVERAGE_MATRIX.md)
reaches it, and every per-flight figure on this page belongs to that earlier translation.

Layer 2 is not a weaker layer 1: for both shipped engines it is the only question answerable,
because no archived product was ever written by v3.5 or by this SODA-2 revision. Layer 1 is the
per-flight tables below; layer 2 is ["The v3.5 port's own validation"](#the-v35-ports-own-validation)
and the SODA-2 GDL checks; layer 3 is
["Layer 3: adjudicated by eye"](#layer-3-adjudicated-by-eye) below.

## The reproduction holds outside 2016

The configuration was established on 2016, so a second year tests it rather than fits it.
**2017-08-13**, the first flight put to it, reproduces its archived product's `Counts` and `Size Distribution cm-3`
**exactly** in every non-zero cell of bins 6+ over the 33,187 seconds both hold:

| | |
|---|---|
| non-zero cells, bins 6+ | **33,027 / 33,027 = 100.0000 %** |
| non-zero cells, all 128 bins | **53,454 / 53,454 = 100.0000 %** |
| both-present cells, bins 6+ | 1,170,468 / 1,170,468 = 100.0000 % |
| **differing cells, every class** | **0** |
| `Counts` total, ours vs archive | **15,987,236 vs 15,987,236** |

2017-08-24 reproduces a larger denominator, **43,416 / 43,416**. Both raw files entered both combines (`files_stitched = 2` on each
side), and both `sd` inputs carry `.call` stamps recording the ORACLES production configuration.

7 seconds of the reproduction are absent from the product and **0 of the product's are absent from
the reproduction**: the archived axis starts at the flight's summary timestamp, a trim that
removes no shared second.

**The second 2017 flight, 2017-08-15, is exact too**, over 33,484 shared seconds:

| | |
|---|---|
| non-zero cells, bins 6+ | **4,810 / 4,810 = 100.0000 %** |
| non-zero cells, all 128 bins | **20,278 / 20,278 = 100.0000 %** |
| **differing cells, every class** | **0** |
| both-present `Counts`, ours vs archive | **3,808,439 vs 3,808,439** |

Two qualifiers, both measured. **1,384 product seconds are uncovered**, because the flight's first
raw file was never delivered — the product is named `…072145` and the earliest raw held is
`…074449`, and 07:44:49 − 07:21:45 is 1,384 s exactly. Those seconds hold **zero** archive
particles. And **40 particles of the reproduction sit in 640 cells the archive holds as fill**,
with 4 of the archive's where the reproduction is fill; the both-present rule excludes both
classes, so the raw totals differ by 36 while every comparable cell agrees.

**A third exact 2017 flight, 2017-08-12** (2 raw files stitched, 30,503 shared seconds): 1,416 /
1,416 non-zero used-bin cells, 11,027 / 11,027 over all 128 bins, zero differing cells.

**The fourth first-batch flight, 2017-08-17, is the one open result**: 268 / 269 non-zero
used-bin cells (99.63 %) — one product-only cell, bin 6, second 16:22:35, not yet root-caused.
Its raw and intermediates are kept until that cell is explained.

Nine 2017 flights hold both raw input and an archived product, and eight of them
reproduce theirs exactly on both compared variables — 2017-08-18 (1,529 / 1,529 non-zero cells
in bins 6+ over 21,351 shared seconds), 08-21, 08-24,
08-28 and 09-02 among them.

Two further 2017 flights cannot be adjudicated. **2017-08-19** has complete raw for both probes
but no archived product of any date. **2017-08-31** has both, but its archived product and the
reproduction each stitch a different raw file — the start times differ by exactly the coverage gap
the comparison reports, and no raw file matching the archive's start is held. Compared anyway it
agrees on under half its non-zero used-bin cells, a figure about two recordings rather than two
implementations. Every flight counted above first passed the opposite test: the archived product's
count of stitched files matches the reproduction's and the raw held.

Validation needs no MATLAB. It is three layers:

1. **Reference pair (authoritative).** Raw files together with the processed output a MATLAB run
   produced from them. The pairs held here are listed in
   [Conventions and terms](09-conventions.md#reference-campaigns); they are not redistributable,
   and adding a campaign or probe means adding a pair, not changing the pipeline.
2. **Differential oracle.** GNU Octave runs the original `.m` files *unmodified* and the port is
   asserted against their real output — including whole-file oracles for `imgProc_sm` and
   `sizeDist` (not distributed), and the three `CGAL_*` MEX routines compiled from source.
3. **Documented semantics with pinned tests** where neither reaches.

These describe the earlier v3.1.4 translation, which every per-flight figure on this page measures.
The two engines shipped here ([Index](00-index.md#the-two-engines)), one UIOOPS engine and one
SODA-2 engine, stand on fewer. **The v3.5 port has no layer 1 and never will**, because no archived campaign product
was produced by v3.5, so its results are asserted against Octave runs of v3.5's own sources —
deliberately **not** against the v3.1.4 port's output, which would be circular: both ports come
from the same reading and share many imports. A real axis defect in the v3.5 port passed its own
fixture test for a day, because the test helper and the port shared one misreading of the C++ and
every fixture record was square, so the axis convention — the whole subject of v3.5's change to
that file — was never exercised. A bank of 60 non-square records fed from the real compiled MEX
caught it: two sides from different places. See [The v3.5 port's own
validation](#the-v35-ports-own-validation) below. **The SODA-2 port's layer 2 is GDL** — GNU Data
Language runs SODA-2's unmodified `.pro` sources as Octave runs UIOOPS's `.m` files (the real-file GDL reference outputs are not distributed; those on synthetic inputs are), so no IDL
licence is needed. Neither port contributes a number to the reproduction claim above.

## Current result

The port's reject stage re-runs on the real image of every particle in a second, then
`sizeDist`'s area-ratio and inter-arrival rejections, binned and compared bin by bin against the
product's `Counts`, on seconds sampled from the product in each cloud regime.

| Flight | File | Seconds | Result |
|---|---|---|---|
| 09/06 | `064403` (whole file) | 3,854 | **493,312 / 493,312 cells** of `Size Distribution` and `Counts`, under the stock reject thresholds |
| 09/06 | `075333` (dense, whole file) | 7,534 | **100.0000 %** — every non-zero used-bin cell of both variables, every second, every cloud regime |
| 09/06 | `104932` (dense, whole file) | 7,475 | **100.0000 %** in the used bins; 99.98 % over all 128 bins (three single particles in bins 1–2, cause identified below) |
| 09/06 | `095907` (whole file) | 3,025 | exact except **two seconds** (one instance of the duplicate TAS-second particle loss), worth 6 used-bin particles of 18,077 |
| 09/10 | `071623`, `102201`, `124240`, `102921` | whole flight | the flight combine below is the result of record — all four files validated whole |

## Two complete flights, end to end

The per-file table is diagnostic; **the acceptance gate is the flight combine**, the only
comparison whose two sides are built from the same inputs.

### Flight 09/10 — exact in every used bin, with the stuck-diode correction on

Four raw files, 29,574 seconds. **This result requires `--diode-corrected`**: two files carry a
confirmed stuck diode (`base160910071623` diode 77, `base160910124240` diode 95), re-illuminated
only under that flag, and the product's `.call` sidecar records `shadow_diode` for those stems.
Without it the four files reproduce 5,057 / 5,069 used-bin cells (99.7633 %), all 12 differing
cells inside those two files.

| | ours / product | |
|---|---|---|
| non-zero used-bin cells | 5,064 / 5,064 | **100.0000 %** |
| both-present used-bin cells | 2,521,746 / 2,521,746 | **100.0000 %** |
| seconds exact | 29,476 / 29,574 | |
| sparse regime, used bins | 997 / 997 | 100.0 % |
| moderate regime, used bins | 6,654 / 6,654 | 100.0 % |
| dense regime, used bins | 10,000 / 10,000 | 100.0 % |

Identical on both `Size Distribution` and `Counts`, with no second present in one product and
absent from the other. **Every difference on the flight lies in bins 1–5**, which the size
distributions do not use — the same place the duplicate TAS-second particle loss, the dropped final raw record and the noisy-diode masks all land. The
whole-flight used-bin excess is 14 particles, all in seconds the product records as empty.

### Flight 09/06

Five raw files, 28,815 seconds:

| | ours / product | |
|---|---|---|
| non-zero used-bin cells | 31,303 / 31,314 | **99.9649 %** |
| seconds exact | 28,806 / 28,815 | |
| sparse regime | 44,172 / 44,175 | 100.0 % |
| moderate regime | 2,082,821 / 2,082,821 | 100.0 % |
| dense regime | 34,176,689 / 34,185,949 | 100.0 % |
| used-bin particles | 233,052 / 233,058 | 6 apart |

**The residual is six particles across a whole flight**, from the duplicate TAS-second particle loss described below.

The figures above use the stock reject profile for the flight's first file and the production
profile for the other four — what the archived product turns out to contain. All five under the
production profile gives 99.834 %; that difference *is* the two-configuration finding, measured
at flight scale.

A file's first second can belong to the *previous* raw file, so scoring one file alone against a
whole-flight product attributes those particles nowhere — hence the combine is the gate.

The one difference over all bins is a UIOOPS behaviour the port reproduces deliberately: when a
file's true-airspeed grid holds two entries for the same second, every particle in that second is
discarded, by the original as by the port, and the archived products show the same loss. See
[the findings](07-findings.md) (duplicated airspeed seconds).

Below the size-bin comparison, two independent checks: a 128-element diode-statistics array
MATLAB wrote in 2017 is reproduced **bit-identical on all 128** (raw decode, channel routing and
framing at once), and over 4,110 seconds of a real flight **24 of 25 `imgProc` variables are
bit-identical across 5.3 million values** — the 25th within 2.1e-15, because Octave's `mean` is
compensated and MATLAB's is not.

## How agreement is counted

A single percentage is meaningless without saying which cells it counts, so
`validate_combined_product.py` always prints **both denominators** — cells both files populate
(which includes agreement about emptiness) and cells where at least one side is non-zero — and
states how much of the looser one is `0 == 0`. The two definitions are in
[Conventions and terms](09-conventions.md#measurement-terms). It exits 1 when any non-zero cell in
the used bins disagrees and 0 only when all agree; `--report-only` prints the comparison and
exits 0.

On a file that agrees completely both figures are 100 %. Both are reported because a single
figure has misled here twice — once by counting `NaN == NaN` as agreement, once by mixing the two
conventions between documents.

**A cell-by-cell reproduction report.** `arrayprobe reproduce-report <product> <archived> [--out FILE] [--json FILE]` compares every variable two netCDF products share, cell by cell, and reports for each the cells compared, the exact matches, the largest absolute and relative residual and every differing cell, with the engine and `.call` stamp of each file. It reads both files and writes only `--out` and `--json` (the Markdown report goes to the terminal without `--out`). Exit 0 when every shared cell is exact, 1 otherwise.

**Count closure.** `arrayprobe check-counts SD PROC` reconciles the binned counts of a size-distribution file with the accepted particles of its particle file, second by second, and lists each excluded particle with its cause; the probe's own housekeeping total is reported as not available until a reader exposes it. Exit 0 when every second closes exactly, 1 otherwise.

## One finding about the reference itself

Stated as measurement: the same archived product file is reproduced by **two different reject
configurations in two time segments** — its `064403` segment only by `rej_hollow = 1`, every
other decoded file on both flights only by `rej_hollow = 0`. The port reproduces both; which one
a user wants is a profile choice. Whether the archive was assembled from passes on either side of
a 2017 edit is for its processing records to settle.

## Why two version numbers, and why that is not a contradiction

They answer different questions.

**The findings about UIOOPS are fixed in the v3.5 engine** (where the developers addressed them)
**and in the opt-in enhancements** (where they did not).

**Findings about UIOOPS are anchored on v3.5**, the current release, because a defect reported
against a version nobody runs helps nobody. Every finding therefore carries a version axis: fixed
in v3.5, still present, transfers verbatim (the file is byte-identical between the two), or
variant-only — describing a modified copy of the UIOOPS MATLAB code, with its own thresholds, that
one campaign's processing ran, rather than UIOOPS as released.

17 of 24 shared files (classified per module in `uiops.CATALOGUE`) are byte-identical between
the two releases, so findings in them transfer with their line numbers intact. One qualifier is
easy to lose and matters — `dropsize.m` is byte-identical across all 16 releases but is called by
no version from v3.3 onward. Identical is not the same as live.

Full treatment: [Conventions](09-conventions.md#version-anchors) and
[Findings](07-findings.md).

## The v3.5 port's own validation

**No figure in this section belongs to the reproduction claim**, and none is evidence about v3.1.4.

The v3.5 port (`arrayprobe_uiops`) is asserted at every stage against GNU Octave
running v3.5's *own* vendored sources, never against the v3.1.4 port. End to end,
the port is run for each of three whole-program Octave reference outputs and every variable and every
attribute is diffed. The `imgProc_sm` reference output is distributed; the `sizeDist` and combine reference outputs are
cut from campaign data and are not, so those tests skip. `STOCK_V35`, a fourth fidelity profile, cites every
field to v3.5's source, checked against an Octave parse (`[fidelity].profile = "stock-v3.5"`).

| Configuration | Result |
|---|---|
| Stock v3.5 reject thresholds | **0 disagreeing items** |
| ORACLES-production reject thresholds | **0 disagreeing items** |
| The new habit scheme ([Schima et al. 2024](https://doi.org/10.1029/2024JD040895)) | **0 disagreeing items** |

Each reference output is a run of the unmodified vendored `imgProc_sm.m` over **6,819 real ORACLES 2016
2D-S particles**, through the real `CGAL_minR` MEX compiled from source — not a shim — across 40
variables. The three reference outputs are tracked in the repository, so the comparison is reproducible from
a fresh clone.

**Why three configurations rather than one.** The stock and ORACLES-production runs disagree with
*each other* on `image_auto_reject` for **2,945 of the 6,819 particles**, so a port that
hard-coded one reject configuration would fail the other reference output by 43 % of its particles.

**What this does not establish.**

- **There is no layer 1 for v3.5 and there never will be.** No archived campaign product was
  produced by v3.5. A v3.5 number is layer-2
  evidence, permanently.
- **One routine agrees within a tolerance rather than exactly**: the ellipse fit
  (`CGAL_EllipseSize.cpp`, `iRectEllipse=1`), checked against the real binary compiled under
  Octave — axes and centre within 1e-2, angle within 1e-3. The bound and why it cannot be tighter
  are in [Known gaps](10-known-gaps.md) rather than folded into the table above.
- **The reference outputs' decoded input is campaign data and does not travel** (774 MB), so the whole-program reference output check is a tool,
  not a test that would skip everywhere but here. a test in the development suite asserts
  the three reference outputs are present, git-tracked and match their SHA-256 digests, with no
  `skipUnless`, so a fresh clone that cannot see them fails loudly.

## A self-check, independent of any reference product

`arrayprobe.timing_closure` checks whether **the probe's own two clocks agree with each other**,
on any file, with no reference product. McFarquhar et al. (2017, ch. 11, p. 11.20): *"checks
should ensure that the sum of particle interarrival times matches the record time."* For a
2D-S/HVPS file, the particle-frame clock's span (`Time_in_seconds[-1] - Time_in_seconds[0]`, in
the proc file) is compared against the independent housekeeping wall-clock span between the
decoded file's first and last record.

```bash
# Linux / macOS: .venv/bin/python
.venv/Scripts/python.exe -m arrayprobe validate timing-closure decoded.H.nc proc.nc
```

**This tool reports, it does not verdict** — no published tolerance exists for how close the two
clocks should agree, so it prints both spans, their difference and their ratio, as
[`compare_nc.py`](#how-agreement-is-counted) reports tolerance-classed differences without a
pass/fail line. Run once, while the tool was being built, on one ORACLES 2016-09-06 HVPS file (`base160906064343`,
decoded with the 2D-S reader; particle clock from a proc file written by the v3.1.4 port) that is
not public, the two clocks disagreed by roughly 8× (v3.1.4-port proc file against the decoded
file's housekeeping clock): a
~59-minute particle-clock span against a ~7.9-hour housekeeping span, the housekeeping one
matching the flight's length. The cause is **unexplained** and the run has not been repeated; it
is recorded as a measurement, not a defect claim, beside the HVPS count disagreement in
[Known gaps](10-known-gaps.md).

## Layer 3: adjudicated by eye

A person adjudicates particle images where no archived product (the file the campaign served) exists, using the triage labelling tool.

## Layer 3, continued: the hollow-rejection threshold pass

A second eye-adjudication pass settled two questions whose ground truth is only in the images.
**The package author labelled 480 particles across 16
cells in two rounds** on CIP particle images (a label is engine-independent; which engine's run offered the particles is not recorded here), through the triage labelling tool
(`arrayprobe.triage_server` and the gallery).

- **Where the hollow-rejection test flips from correct to harmful.** The estimate is **~155 µm**
  — a best estimate, not a boundary: the Wilson 95 % intervals overlap, **45 % [31, 60]** below
  the flip against **60 % [45, 74]** above it, so the sides are not yet distinguishable at this
  *n*; a sharper crossover needs more labels.
- **Whether the 55–105 µm bin holds real particles even among those both configurations accept.**
  It does, at **32 % real, Wilson 95 % [17, 52]** — agreement between configurations is not
  correctness.

**What this licenses.** Adjudication by eye settles what a particle *is*; it validates no
pipeline against an archived product, of which there is none here. It gives a best-estimate
crossover for the hollow-rejection threshold and a real-fraction for one bin, and licenses no
change to any gate, threshold or default on its own. **Labeller: the package author**, the only labeller
to date; no inter-labeller agreement number exists.

## "But Octave isn't MATLAB"

Correct: MATLAB-written output of record is the *acceptance* oracle, Octave only the
*development* one. The arithmetic is overwhelmingly IEEE-754 double, where conforming
implementations agree bit-for-bit; integer saturation and promotion, the one
implementation-defined area, was measured and is pinned by tests; and every input bank and reference output
is committed, so anyone with a licence can re-run the originals and diff. Full argument:
`docs/developer/OCTAVE_AS_ORACLE.md`.
