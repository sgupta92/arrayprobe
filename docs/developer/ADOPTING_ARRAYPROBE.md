# Adopting this package: what changed, and what it does to your data

**Who this is for.** Someone deciding whether to run this package on their own OAP data — not a
reviewer of the port's fidelity and not an
audit of what this project has built. This page answers two questions a new user
actually has: *will it run on my probe/engine combination*, and *what will it do to my numbers if
I turn a correction on*. **It is not a changelog** — commit history answers "what changed"; this
answers "why a specific change matters to your data".

**The aim, as first stated:** *"then we need to document all
updates, fixes, and present them to a potential user. have appropriate notebooks, etc."* This page
is the first piece of that. What remains is listed at the bottom.

---

## 1. The clearest answer yet to "what will a correction do to my numbers"

The image-assisted CIP hollow-particle correction answers both halves of what a potential user
needs: it is a real before/after on real data (a corrections A/B), and it is the first correction
carried end to end through triage, reprocessing and comparison — the workflow a user would
themselves run.

**What was run**: a CIP file from one flight (3,797,537 particles),
reprocessed with exactly one reject threshold changed (`rej_hollow`: 1 → 0, everything else held at
`STOCK_V35`), then compared against the 2D-S product of record on the same flight.

**The result — copied verbatim from that file, not retyped from memory:**

| bin (µm) | stock (`rej_hollow=1`) | image-assisted (`rej_hollow=0`) | comparable |
|---|---|---|---|
| 55–105 | 6.213 | 5.977 | **False** (probe at its resolution limit — see below) |
| 105–155 | 5.104 | 5.638 | True |
| **155–205** | **1.414** | **3.108** | True |
| **205–255** | **0.428** | **1.826** | True |
| **255–305** | **0.329** | **1.672** | True |
| 305–355 | 1.205 | 1.205 | True |
| 355–405 | 2.146 | 2.146 | True |
| 405–455 | 1.020 | 1.020 | True |
| 455–505 | 2.095 | 2.095 | True |
| 505–555 | 1.142 | 1.142 | True |

R = CIP ÷ 2D-S concentration, 50 µm bins, full flight.

**What this means for your data, in one sentence each:**

- **Above ~305 µm, this setting cannot matter to you** — the two arms are identical to every
  printed digit, bin after bin. If your science lives above 305 µm, `rej_hollow` is not a decision
  you need to make.
- **Between 155 and 305 µm, it can matter by a factor of 4–5** — 0.329 → 1.672 at 255–305 µm is
  a 5.1× move in a single threshold flip, and the direction reverses which side of the 2D-S the
  CIP lands on. If your science lives in this range, which setting you choose is not a formality.
- **Below ~155 µm, do not trust the CIP at all on this probe**: 32 % of particles in the 55–105 µm
  bin disagree between the two arms even among particles *both* configurations accept — that bin
  is marked not-comparable and stays excluded in the source result. No threshold rescues it; it is
  the probe at its 25 µm pixel resolution.

**What it does not establish**: *which* arm is right. R = 1 is not a target — the CIP and the 2D-S
are different instruments with different sample volumes, and this project's standing rule is that
the CIP is a cross-check, never a validation (no archived UIOOPS CIP product exists anywhere to
validate against). What the result does establish is *where the decision lives* and *how large it
is* — exactly what a user needs to decide whether their own science falls inside the sensitive band.

---

## 1b. The same correction on a 2D-S, where the answer comes out cleaner

The CIP result above crosses a chain boundary — it compares a CIP against an
archived 2D-S product — so count effects and sizing effects are entangled in it. The same
correction was then run **within one instrument**, on one ORACLES 2016-09-06 2D-S file, changing
`rej_hollow` and nothing else. That removes the entanglement, and the answer is sharper than the
ladder:

**Turning the hollow correction on or off does not accept or reject a single particle.** The
acceptance mask is byte-identical between the two arms across all 50,838 particles. The reason is
structural, not a property of this flight: `GOOD_REJECT_CODES` is `"0HhuR"`, so the two hollow
codes `H` and `h` are *accepted* codes. **Being ruled hollow never removes a particle from a size
distribution.** It routes the particle through the Korolev correction, which rewrites its
**diameter**.

| What changes | |
|---|---|
| particles accepted | **no change at all** — 37,688 either way |
| particles whose recorded diameter changes | 4,821 (9.48 %) — exactly the `H`-coded set |
| direction | larger in all 4,821, smaller in none |
| size of the change | median 48.35 µm → 77.08 µm; median per-particle ratio **1.694** |
| `h`-coded particles affected | **none** of 26,747 |

So the per-bin ratios below are **migration up the ladder**, not acceptance — which is why the
slices move while the flight total is exactly 1.0000:

| Bin (µm) | ratio (correction on ÷ off) | |
|---|---|---|
| 55–105 | **1.3360** | |
| 105–155 | **2.2054** | |
| 155–205 | **4.4706** | |
| 205–255 and above | — | every slice below n = 30; not quotable |
| whole flight, all sizes | **1.0000** | exact, by construction |

**Why this matters for your data specifically.** If you were expecting this correction to change
how many particles survive, it will not. What it changes is where they land on the size ladder,
and the effect is concentrated: a factor of ~4.5 at 155–205 µm against 1.34 at 55–105 µm. If your
science sits below ~150 µm the correction moves your numbers by a third; between 150 and 205 µm it
can multiply them by four; above that this flight cannot tell you, because it ran out of particles.

**And what this does not establish**: nothing here says the 1.694× enlargement is *right*. This is
a within-instrument A/B with no external reference — it measures what the two configurations do
differently, and nothing adjudicates which is closer to the truth. The only admissible evidence
for that is layer 3, a person judging the particle images directly, not yet run on this set.

---

## 2. Is this — or any correction — applied when you run the package?

**No, and this is the warning worth acting on.** Two independent mechanisms, both off unless you
ask:

- **The hollow-test setting above is a `FidelityProfile` choice, not a silent default.** It is a
  named profile (`stock-v3.5-image-assisted`), selected the same way any profile is — explicitly,
  by name — and it is one field away from `STOCK_V35`, deliberately: `max_edge_img_ar` and
  `max_comp_img_ar` are untouched, so the effect measured above is the hollow test alone, not a
  bundle of threshold changes. No reader path defaults a profile
  (`tests/test_profile_is_never_defaulted.py`); the driver's own `--preset` is a
  required argument, not a default.
- **Separately, the `arrayprobe-uiops-enhancements` package's 36 modules are OFF by default, every one,
  with no exemption.** Checked directly against the code for this page, not assumed:
  `enhancements_uiops/src/arrayprobe_enhancements/registry.py:109-119` —
  `` `default_on` is **False for every module and must stay that way** `` — and
  `enhancements_uiops/tests/test_enhancement_opt_in.py::test_no_registered_module_claims_a_default_on_exemption`
  asserts `sorted(n for n, s in REGISTRY.items() if s.default_on) == []`. The batch driver,
  not the library, makes the default depend on whether an archived product exists:
  `resolve_protective` (`src/arrayprobe/driver/run_flight.py:2380`) applies the
  corrections for data-destroying upstream defects by default on probes with no archived product
  (and the bin-table fix on engine 3.5), as separate `enh` products recorded in the `.call` stamp;
  `--protective off` skips them. Importing either engine as a library applies no correction
  unless you name one.

**The practical rule for a new user:** the package applies the UIOOPS developers' own upstream
fixes (v3.5) and nothing more unless you explicitly select a profile or enhancement. Nothing is fixed for you silently, in either direction.

---

## 3. Which probe / engine / mode combinations actually run

Generated, not hand-maintained — `docs/developer/COVERAGE_MATRIX.md`, checked
against the code by a test in the development suite. Its own
headline, copied from that file's "Status counts" table (70 cells = 7 probes × 2 engines × 5
modes):

| Status | Cells |
|---|---|
| runs and validated against an archived product | 0 |
| runs and cross-checked | 49 |
| runs, unvalidated | 0 |
| refuses, deliberately | 0 |
| refuses, not built | 5 |
| refuses, defect | 0 |
| untested | 16 |

Read that as it is written there: **archived-product validation was done with an earlier v3.1.4
translation (not shipped), on 2D-S serial; no cell of the shipped engines is validated against an archived product.** Everything else is either cross-checked
against the original MATLAB/IDL source (a weaker but real claim: the routine matches its own
reference implementation), unvalidated, or refuses. A refusal is not always a limitation you
should route around — none of the 70 cells refuses on a defect (PIP on `arrayprobe_soda2`, the
last one, runs through SODA-2's DMT path, checked bit for bit against SODA-2's IDL under GDL);
5 refuse because the code is **not built** (`--s2-jobs` for the 2DC, 2DP and Fast2DC on the v3.5
engine, whose raw readers have no parallel form yet, and `--jobs`/`--chunks` for the Fast2DC on
the SODA-2 engine, refused because the RAF buffer remainder carries across chunk boundaries); the
other 0 refuse **by design** (the earlier v3.1.4 translation, not shipped and not in these
cells, refused every probe but 2D-S and HVPS by design: it was scoped to ORACLES 2D-S/HVPS and
port validation only).

**Before you run your probe on your engine, look up your exact cell in `COVERAGE_MATRIX.md` —
this page's summary tells you the shape of the coverage, not your specific answer.**

---

## 4. The speed story, each figure labelled with what it was measured on

`docs/developer/SPEED.md` is this project's single source of truth for every speed claim — every
outward surface quotes from it so a number cannot drift between them. Copied here with the same
labels that file uses:

| Figure | What it measured | Scope |
|---|---|---|
| **1.79×** | `arrayprobe_uiops.jit_kernels` on S3 of a real CIP production pass (150 records / 9,245 particles, one CIP file) | one machine, serial, not chunked, not another probe |
| **6.33×** | `calculate_reject_unified` under the modified reject thresholds (3.686 s → 0.582 s), same 9,245 particles | serial; **4.77×** with `rej_hollow=True` instead |
| **1.60×** | `--jit` on S3 of a **real full flight** (one CIP flight file, 3,797,537 particles): 1412.5 s → 880.9 s, on a machine *verified* quiet (not assumed), all 40 variables byte-identical | corroborated at **1.56×** on a smaller file from the same flight, serial |
| **1.43×** | **derived**, not measured — S2/S4 carry no JIT kernel; S3 is 79.8 % of the pipeline, so the whole-pipeline bound is computed from that share | labelled derived in `SPEED.md` itself; do not read it as a wall-clock run |

**There is no measured whole-pipeline figure for the v3.5 engine**; the only measured whole-flight figures were taken on the earlier v3.1.4 translation (not shipped), on 2D-S with its flags combined (`SPEED.md`, the v3.1.4 section). `SPEED.md` withdrew an earlier 1.22× headline
after finding it was measured on a machine contended by a concurrent test suite (a 5.4× spread on
an unchanged configuration exposed it); the honest current answer is a band, not a figure, and
`SPEED.md` says explicitly what a real one would still take. **All four figures above are CIP,
one stage, one file** — none is a 2D-S or HVPS number, and none should be quoted as a
package-wide multiplier. `SPEED.md` names this trap directly: *"arrayprobe is N× faster" is not a
claim this project can make.*

---

## What this page is not

Not a fidelity audit, not a project-status ledger, not a
notebook. Every figure above is either copied verbatim from a generated or measured source
document (`COVERAGE_MATRIX.md`, `SPEED.md`, the CIP image-assisted result report) or checked directly
against the source code at the time this page was written (`registry.py`, its test) — none
invented or estimated for this page. If any of the three source documents regenerates with
different numbers, this page is what has gone stale, not them — cross-check against the source
before quoting this page in turn.

**Which of the above is enforced:**

- **Swept, every run** (by the publish-readiness test): this page is in that
  test's `PUBLIC` sweep, so its bare "N modules" claim is checked against
  `count_enhancement_modules()` like every other public surface's module count.
- **Cross-checked against their generated source, every run** (`_adoption_page_figure_problems`,
  called from `test_module_count` in the same file — a plain function rather than its own
  `def test_` method, so adding it does not shift `count_tests()` against the exact count every
  public surface pins): the coverage table's six counts and 70-cell total against
  `COVERAGE_MATRIX.md`'s own generated table; the R-value table's ten rows against
  that result report, verbatim; each speed multiplier quoted here against the set of
  figures `SPEED.md` actually states (existence, not the imgproc/reject/full-flight *label*
  pairing — `SPEED.md` carries no stable anchor for that yet).
- **Hand-copied, cite-checked only, not swept**: the finding-register totals (UIOPS/SODA-2) if
  this page ever grows to quote them; the particle counts and flight identifiers in prose (e.g.
  "3,797,537 particles", a CIP file from one flight) beyond the R-value table rows themselves; anything in
  section 1's prose interpretation of the numbers (the "×4–5", "32 %" figures are restatements, not
  re-extractions).

Run `.venv/Scripts/python.exe -m unittest tests.test_publish_ready` from the repository root before
trusting a hand-edit to this page — that is the whole mechanism, and it fails closed (an anchor or
table shape it cannot find is a reported problem, never a silent pass).

## What is left of this page's brief

1. **Done — `examples/5_data_quality/11_image_assisted_threshold.ipynb`.** It demonstrates the decision the
   triage → threshold → reprocess chain exists to make: the hollow test is *right* at 55–105 µm
   (0 of 25 labelled rejections were real particles) and *wrong* at 255–305 µm (87 %), so neither
   `stock-v3.5` nor `stock-v3.5-image-assisted` is the answer and `hollow_size_rule`'s threshold
   is. Its synthetic population's truth is interpolated from the hand-labelled
   hollow-particle fractions; it runs the real `hollow_size_rule.resolve_ihollow_array` and checks
   that `rule=None` is bit-identical to stock and that the rule only narrows what stock rejects.
   Turning the hollow test off keeps hundreds more particles *below* the threshold, where the
   labels say none were real — where a size distribution is most densely populated. Executed by
   `tests/test_examples_execute.py`, stored output written by
   `scripts/execute_example_notebooks.py`, listed in `examples/README.md`.
2. **Done — the corrections A/B notebook**, `examples/2_processing/09_enhancement_ab.ipynb`: the `outoffocus`
   enhancement A/B on the tracked synthetic `demo_flight_dense_raw.2DS`, both engines, ending in
   §6 with a config-file run through `arrayprobe-enhanced run` (`pipeline.apply_enhancements`).
3. **Done — this page's numbers are wired to a build-time check**:
   the publish-readiness test's `_adoption_page_figure_problems()`, called from
   `test_module_count` (see "Which of the above is enforced"). The repository's count-sync check is
   a different mechanism and propagates only this page's module count.
4. **Open — promotion to the public docs site** (`docs/`), timing not yet set:
   the page is kept out of the `docs/_build/build.py` build, and no page under `docs/`
   mirrors it.
