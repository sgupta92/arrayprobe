# ML-based per-particle accept/reject

**Status** (as stated in `enhancements_uiops/src/arrayprobe_enhancements/ml_accept_reject.py`'s
docstring): **Method A**, a diode-occupancy heuristic, is implemented and evaluated on real data.
**Method B**'s labeled-data pipeline and a numpy-only trained baseline are built and evaluated on
real data. **The CNN is not built**, for a measured reason given under "Method B".

**Summary of Method B.** The trained model scores **19 of 21 (0.905)** held out, against Method
A's **17 of 21 (0.810)** and a majority-class floor of **16 of 21 (0.762)**. A single re-tuned
threshold on Method A's one statistic also scores **exactly 19 of 21 with the identical confusion
matrix**, so the image features contribute nothing measurable. At n=21 the methods cannot be
distinguished. **The labeled set, not the model or the framework, is what blocks a CNN.**

## Scope

The module inspects every particle in a proc/image file pair and returns its own accept/reject
opinion. It is an opt-in enhancement: UIOPS's rule-based ladder (`holroyd.m`,
`calculate_reject_unified.m`, ported bit-exact in `reject.py`/`habit.py`) is untouched, and
`src/arrayprobe/` never imports this module. It never changes what the port computes or writes.

The intended job has two directions, which need separate labeled sets:

1. **False accepts**: accepted particles that are artifacts. Identifiable from the image alone.
2. **False rejects**: rejected particles that are real. Some real out-of-focus drops may be
   rejected outright by `calculate_reject_unified.m`'s hollow and aspect-ratio tests, which have
   no concept of focus depth. Recovering them is the first stage of a pipeline whose second stage
   is `outoffocus.py`'s size correction (the Korolev 2007 `part_z`/`size_factor` correction,
   computed by the MATLAB but never applied; `enhancements_uiops/docs/CORRECTIONS.md`, part
   `outoffocus.py`). The hand-off contract between the two modules is undecided and needs a joint
   design pass before either ships false-reject code.

**Why a classifier.** A stratified manual screen of 50 accepted and 50 rejected particles per
flight, over six 2016 field-campaign flights, covers a few hundred particles. Those flights hold
62,990 accepted and 5,636,077 rejected particles in the used size bins (bin 6 and up; per flight
3,382-23,332 accepted, 8,810-2,507,845 rejected). On the largest-rejected flight the sample is
effectively 0 % of the rejected population. The manual screen does find real false accepts —
particle `2598801` (0.678 mm, habit `'a'`) is a stuck-diode merge accepted into a used bin, with
three diode columns shadowed 94.5-100 % across its whole 65-slice span — but it cannot approach
exhaustive coverage.

## Prior work and licensing

CNN classification of OAP imagery is established, not a research gap.

- **Jaffeux, Coutris et al. (2022), AMT 15, 5141**
  (https://amt.copernicus.org/articles/15/5141/2022/): CNNs for **PIP and 2D-S**, with an
  explicit artifact class for the 2D-S model, trained on four campaigns (EXAEDRE, HAIC, AFLUX,
  EUREC4A). Code and models at https://github.com/Ljaffeux/AMT-2022-72, Zenodo
  10.5281/zenodo.6912294. **No usable licence**: the GitHub API reports `"license": null`, the
  repository holds no LICENSE file (`DS_model.h5py.zip`, `DS_training_data.zip`,
  `PIP_model.h5py.zip`, `PIP_training_data.zip`, `README.md`, `cnncode_2DS.py`,
  `cnncode_PIP.py`), the README carries no licence text, and Zenodo lists "Other (Open)" with no
  terms. **Their code and weights are not adapted or redistributed**; the published architecture
  is a legitimate reference, and Method B trains fresh on this project's own labels.
- **Jaffeux et al. (2025), AMT 18, 2311** (https://amt.copernicus.org/articles/18/2311/2025/):
  extends the 2022 models to a new dataset rather than superseding them. Data and models at
  `LJaffeux/JAFFEUX_et_al_AMT_2024` and Zenodo 10.5281/zenodo.15573218, but its scripts are
  provided only on request, so it is less open than the 2022 release.
- **Touloupas et al. (2020), JTECH**: CNN classifying holographic-imager (HOLIMO) particles as
  droplet / ice / artifact, 96.8 % median accuracy. The closest precedent for a CNN deciding
  accept versus artifact rather than habit.
- **Przybylo et al. (2022), JTECH**: CPI probe, 9 CNNs, >10M images, open code at
  https://github.com/vprzybylo/cocpit. An engineering reference for a production-scale labeling
  pipeline.

Cite SODA-2 as: Aaron Bansemer. (2026). abansemer/soda2: v2.26.0 (Version v2.26.0) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.18331418

**Aircraft state as a side-input.** None of these papers conditions on aircraft state.
Temperature, pressure and altitude as a tabular side-input (the standard image-plus-tabular
multi-input pattern) would be a genuine extension; temperature is a physical prior on which ice
habits are plausible. This is a hypothesis to check against the literature, not a result. For the
2016 field-campaign flights, the aircraft's 1 Hz state files (NASA-Ames 1001 format) carry
`Sys_TTemp` (total temperature, °C), `AIR_T_ROSE2` (Rosemount air temperature, °C), `Sys_SPress`
(static pressure, hPa) and `SysRadarAlt` (radar altitude, ft), keyed on UT seconds from midnight,
the same convention as the proc files, so the join is a direct key match. Confirmed present for
four flight days, two of them among the labeled set's four; check before relying on it for the
other two. Not wired into any code. The `Pres`/`Temp` arguments `sizeDist.m` and
`sizedist.py` take are flight-representative scalars for the sample area, not this time series.

## Labeled set

22 particles from six 2016 field-campaign flights, each reviewed individually through
`triage_server.py --queue-file` (`enhancements_uiops/docs/method_a_review_queue.json`), held in
the package as `REVIEWED_LABELS`. Real proc/image files, no synthetic data.

| Label | n | `max_col_occ` min | max |
|---|---|---|---|
| `artifact` (stuck-diode merge, or a merged close-particle frame) | 16 | 0.750 | 1.000 |
| `real` (correctly accepted) | 5 | 0.012 | 0.800 |
| `mixed` (real droplet + stuck diode + other artifacts in one detection) | 1 | 0.986 | 0.986 |

`mixed` has no correct binary answer and is excluded from every score, leaving 21.

**A first labeling pass was wrong in six of 22 labels.** The review changed:

| Particle | Old label | New label | `max_col_occ` |
|---|---|---|---|
| `292254` | real | artifact | 0.857 |
| `965074` | real | artifact | 0.950 |
| `5718294` | unsure | artifact | 0.800 |
| `5715466` | unsure | artifact | 0.773 |
| `2109304` | unsure | real | 0.800 |
| `40860` | real_reject | mixed (new category) | 0.986 |
| `5716830` | merge_A14 | real (merged close-particle frame) | 0.490 |

`965074` had been cited as Method A's false positive; it is an artifact, so Method A was right
and the label was wrong.

**Taxonomy gap.** `40860` and `5716830` did not fit the triage tool's three buttons (artifact /
real / unsure); two misfits in 22 suggest a fourth category is needed. Unresolved.

**Labels lost to bulk labeling.** Read from the verdict sidecars (`--from-sidecars`), only **14
of the 22** reviewed particles survive: the six flights' sidecars hold 4,827,974 verdicts, of
which 4,827,960 are bulk-labeled (k-means cluster bulk-apply). One flight that contributed four
reviewed particles retains none. Hence `REVIEWED_LABELS` is the authoritative copy, and
`human_labeled_particles` excludes bulk-labeled verdicts by default; otherwise bulk labels would
outnumber human ones by about 340,000 to 1.

**Nothing in this module writes to a verdict file.** `read_verdict_sidecar` opens in `"r"` and is
a deliberate 8-line duplicate rather than an import of `triage_server._load_verdicts`, which sits
in the same file as `_save_verdicts_bulk`. `test_ml_accept_reject_methodb.py`'s
`test_loading_never_modifies_the_verdict_file` asserts this by SHA-256 across a load.

## Method A: diode-occupancy heuristic

Not a trained model: one statistic, `max_col_occ(shadow)`, the maximum over diode columns of the
fraction of the particle's slices in which that column is shadowed. A stuck diode holds one column
dark for the particle's whole span; a real drop's shadow is transient and sparse.
`DEFAULT_THRESHOLD` is 0.90. `enhancements_uiops/src/arrayprobe_enhancements/ml_accept_reject.py`,
9 tests in `enhancements_uiops/tests/test_ml_accept_reject.py`.

### Method A: real evaluation

**Result on the 21 binary labels, threshold 0.90:** 12 of 16 artifacts caught (recall 75 %; the
four missed lie at 0.750-0.857), zero of five reals flagged. The classes overlap: highest real
`2109304` at 0.80, lowest artifact `737894` at 0.75.

**What it cannot catch, by construction.** A merged close-particle frame (`5716830`: two real
particles merged because `imgProc_sm`'s boundary scan found no fully blank slice between them)
has a shadow that moves between diode ranges rather than pinning one column. A single-column
statistic cannot see it; it needs a temporal-transition feature (diode-range change-point
detection) or the full image.

**The 0.90 default is on the wrong side of the overlap band.** In sample, a cut at 0.70-0.75
scores 20/21 (16 TP, 1 FP) against 0.90's 17/21. This is in-sample tuning on 21 points, not a
held-out claim, and the default is not changed, because re-tuning it on the evaluation set would
fit the default to that set. Open decision.

## Method B: data pipeline and trained baseline

All in `ml_accept_reject.py`, beside Method A:

| Piece | Function(s) | What it does |
|---|---|---|
| Verdict reader | `read_verdict_sidecar`, `human_labeled_particles` | Reads `triage_verdicts/<flight>.json` read-only; drops bulk-labeled entries by default |
| Label registry | `REVIEWED_LABELS` | The 22 reviewed particles |
| Image loader | `load_shadows` | Renders each particle through `arrayprobe.render.reconstruct_particle_image`, the port's own function |
| Fixed-size representation | `pool_to_grid`, `particle_features`, `feature_names` | Exact area-resampling of a variable-size shadow into a fixed occupancy grid, plus six shape scalars |
| Dataset assembly | `build_dataset` | `(X, y, kept)`; `mixed` and `unsure` are dropped, never folded into a class |
| Trained baseline | `fit_logistic`, `LogisticModel` | L2-regularised logistic regression, full-batch gradient descent, numpy only, deterministic |
| Evaluation | `leave_one_out`, `majority_class_accuracy`, `evaluate_labeled_set` | Leave-one-out CV with standardisation inside each fold, always reported against the majority floor and Method A on the same particles |
| CNN requirements | `TORCH_CNN_REQUIREMENTS` | What a CNN would need, recorded with the code |

CLI: `python -m arrayprobe_enhancements.ml_accept_reject --decoded-dir <dir>`.

**The CNN is not built.** No deep-learning framework (`torch`, `tensorflow`, `keras`) or
`scikit-learn` is installed in the project environment, and adding a ~2.5 GB dependency is a
decision the package has not made. The framework is not the real blocker; the numbers below are.

### Held-out evaluation

The 21 binary-labeled particles. Every number is reproducible with the CLI and pinned in
`enhancements_uiops/tests/test_ml_accept_reject.py`'s `MethodBRealEvaluationTests`.

| Approach | Held-out accuracy | TP | FP | TN | FN |
|---|---|---|---|---|---|
| Majority class ("always artifact") | **16/21 = 0.762** | 16 | 5 | 0 | 0 |
| Method A, threshold 0.90 as shipped | **17/21 = 0.810** | 12 | 0 | 5 | 4 |
| **Method B**, 22 features, LOO | **19/21 = 0.905** | 16 | 2 | 3 | 0 |
| `max_col_occ` alone, 1-feature logistic, LOO | **19/21 = 0.905** | 16 | 2 | 3 | 0 |
| Method A with its threshold re-tuned inside each LOO fold | **19/21 = 0.905** | 16 | 2 | 3 | 0 |

1. **The image features add nothing measurable.** The last three rows share one number and one
   confusion matrix, so Method B's +0.095 over Method A is threshold placement, not learned image
   structure. The pooled 4×4 occupancy grid, the part that would become convolutional filters, is
   dead weight on this data.
2. **The counts coincide; the particles do not.** The full model's false positives are `7319`
   (`max_col_occ` 0.155) and `2109304` (0.800); the one-feature model's are `5716830` (0.490) and
   `2109304`. Scoring identically while losing different reals means the two are
   indistinguishable at this n, not that one rescales the other. `7319`, a low-occupancy real
   pushed the wrong way by the extra features, is the overfitting signature of 22 features on 21
   points.
3. **The error bar swallows the difference.** 0.905 on 21 points has a binomial standard error of
   0.064; Methods A and B are 1.5 standard errors apart. Grids from 2×2 to 8×8 (10 to 70
   features) all score 19 or 20 of 21, a one-particle spread; L2 from 0.1 to 10 likewise.
4. **Class balance does most of the work.** 16 artifacts to 5 reals: the gap between the 0.762
   floor and 0.905 is three particles, all on the real side. One relabel on the minority class
   moves every number by ~0.05.

### What a CNN still needs

Recorded in the module as `TORCH_CNN_REQUIREMENTS`:

1. **Labels, the binding constraint.** ~10³ reviewed particles, far better balanced than 16:5.
   The comparables train on 10⁴-10⁶ (Jaffeux 2022: four campaigns; Przybylo 2022: >10M).
2. **A labeling path that scales and can be trusted.** k-means cluster bulk-apply mislabeled
   particles at scale, and the clustering is not tight enough for bulk-apply even from a correctly
   reviewed medoid. Open design problem; `--queue-file` review is trustworthy and slow.
3. **A framework decision**: ~2.5 GB, against a package whose declared dependencies are
   `arrayprobe`, `numpy`, `netCDF4`.
4. **The input representation**, already shipped: `load_shadows` + `pool_to_grid` turn any
   particle into a fixed tensor; a CNN swaps the 4×4 grid for the cropped shadow at, say, 64×64.

The aircraft-state side-input is second-order until item 1 is answered.

### Tests

- `enhancements_uiops/tests/test_ml_accept_reject_methodb.py`: 41 tests, entirely synthetic.
  Covers area resampling (including the `n_in < n_out` case where a floor-division index map
  divides by zero), pooling as a true occupancy fraction rather than a subsample, feature shape
  and determinism, verdict loading (bulk exclusion both ways, `unsure` dropped, the read-only hash
  assertion), the label registry, dataset assembly's exclusion of `mixed`, model determinism and
  numerical stability at extreme decision values, and **a leakage guard**: LOO on seeded pure
  noise must land at or below chance, which standardising over the full set would fail.
- `enhancements_uiops/tests/test_ml_accept_reject.py`: the real-data file, with 8 Method B tests
  pinning every number in the table, two of them negative results (the one-feature equivalence and
  the one-particle spread across grid sizes). Skips without the decoded flights;
  `ARRAYPROBE_DECODED_DIR` points it at a tree outside the working copy.

## Open items

1. **False-accept scope**: replace `calculate_reject_unified.m`'s ladder, run beside it as a
   second opinion, or flag disagreements for human QA. The port's own ladder output is unchanged
   whichever is chosen.
2. **Joint design with `outoffocus.py`** before any false-reject code (see Scope).
3. **False-reject labels.** None of the 22 targets "rejected but real". A candidate population
   exists: `particle_clustering.py` on the rejected side finds a donut/ring-shaped cluster matching
   reject code `'i'`'s single-direction-hollow finding, 72,394 particles across the six flights
   (1.04 % of 6,953,573 rejected; 0.02 %-2.76 % by flight), spot-checked visually (3 of 5 clean
   rings) but not individually adjudicated. Candidates, not labels.
4. **Fourth label category** (Labeled set) and **Method A's default threshold** (Method A).

## Non-goals

- No change outside `enhancements_uiops/`; the port's accept/reject output remains the bug-for-bug
  reproduction of the MATLAB ladder.
- No deep-learning dependency is added and no bulk labeling is performed.
