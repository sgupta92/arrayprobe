# SPDX-License-Identifier: BSD-3-Clause
"""Tests for ml_accept_reject.py (task #27), Method A.

Real-data evaluation against every particle this project has a confirmed human verdict for --
22 particles across 6 flights, not a synthetic sample. Skipped gracefully when the real decoded
flights are not present (a fresh clone, CI).

**Re-reviewed 2026-08-27** via `triage_server.py`'s new `--queue-file` review queue
(`enhancements_uiops/docs/method_a_review_queue.json`), user-directed ("your training and validation
data need to be reviewed by me because you still make errors"). The re-review changed six of
the original 22 labels -- see `enhancements_uiops/docs/ml_accept_reject_design.md`'s "Method A: real
evaluation" for the full before/after table. Labels below are pulled
from `_decoded/triage_verdicts/*.json` (the tool's own save format), not the older
`gallery_qa_verdicts.py` registry, which is now superseded for these 22 particles.

The numbers here are measured, not assumed.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

import netCDF4
import numpy as np
from arrayprobe.render import reconstruct_particle_image

from arrayprobe_enhancements.ml_accept_reject import (
    DEFAULT_GRID,
    DEFAULT_THRESHOLD,
    REVIEWED_LABELS,
    SCALAR_FEATURE_NAMES,
    build_dataset,
    classify_stuck_diode_artifact,
    evaluate_labeled_set,
    leave_one_out,
    load_shadows,
    max_col_occ,
)

# `ARRAYPROBE_DECODED_DIR` lets these run against a decoded tree that isn't the sibling
# `_decoded/` -- needed to evaluate from a git worktree, which has its own (empty) tree.
# Read-only in every case; nothing in this file opens a decoded or verdict file for writing.
_DECODED = Path(
    os.environ.get("ARRAYPROBE_DECODED_DIR")
    or Path(__file__).resolve().parent.parent.parent / "_decoded"
)

# The 22-particle labeled set now lives in the module itself
# (`ml_accept_reject.REVIEWED_LABELS`) rather than being a second copy here: Method B's
# pipeline needs it too, and two copies of a label registry is exactly how a re-review's
# corrections get applied to one of them and not the other. Re-reviewed 2026-08-27 -- see
# the module docstring and the design doc for the before/after table.
LABELS = [(item.flight, item.particle_index, item.label) for item in REVIEWED_LABELS]

_FLIGHTS = sorted({flight for flight, *_ in LABELS})
_MISSING = [
    f for f in _FLIGHTS
    if not (_DECODED / f"proc.{f}.H.nc").exists() or not (_DECODED / f"{f}.H.cdf").exists()
]


class MaxColOccUnitTests(unittest.TestCase):
    """Pure-array tests, no real data needed."""

    def test_a_column_shadowed_every_slice_gives_1(self):
        import numpy as np
        shadow = np.zeros((10, 5), dtype=bool)
        shadow[:, 2] = True   # column 2 shadowed in all 10 slices
        self.assertEqual(max_col_occ(shadow), 1.0)

    def test_a_column_shadowed_half_the_slices_gives_half(self):
        import numpy as np
        shadow = np.zeros((10, 5), dtype=bool)
        shadow[:5, 2] = True
        self.assertEqual(max_col_occ(shadow), 0.5)

    def test_empty_shadow_gives_zero_rather_than_raising(self):
        import numpy as np
        self.assertEqual(max_col_occ(np.zeros((0, 5), dtype=bool)), 0.0)

    def test_classify_uses_the_default_threshold(self):
        import numpy as np
        shadow = np.zeros((10, 5), dtype=bool)
        shadow[:, 0] = True
        call = classify_stuck_diode_artifact(shadow)
        self.assertTrue(call.is_artifact)
        self.assertEqual(call.threshold, DEFAULT_THRESHOLD)


@unittest.skipUnless(not _MISSING, f"real decoded flights not present: {_MISSING}")
class RealLabeledSetEvaluationTests(unittest.TestCase):
    """The actual evaluation: every particle this project has a confirmed human verdict for,
    as of the 2026-08-27 re-review."""

    @classmethod
    def setUpClass(cls):
        cls._open = {}
        for flight in _FLIGHTS:
            proc = netCDF4.Dataset(_DECODED / f"proc.{flight}.H.nc")
            image = netCDF4.Dataset(_DECODED / f"{flight}.H.cdf")
            cls._open[flight] = (image, proc)
        cls.results = []
        for flight, idx, label in LABELS:
            image_ds, proc_ds = cls._open[flight]
            shadow = reconstruct_particle_image(image_ds, proc_ds, idx)
            cls.results.append((flight, idx, label, max_col_occ(shadow)))

    @classmethod
    def tearDownClass(cls):
        for image_ds, proc_ds in cls._open.values():
            image_ds.close()
            proc_ds.close()

    def _occs(self, label):
        return [occ for _, _, lab, occ in self.results if lab == label]

    def test_twelve_of_sixteen_confirmed_artifacts_are_caught_at_the_default_threshold(self):
        artifacts = self._occs("artifact")
        self.assertEqual(len(artifacts), 16)
        caught = sum(1 for occ in artifacts if occ >= DEFAULT_THRESHOLD)
        self.assertEqual(caught, 12,
                         "if this changes, the threshold or the labeled set changed -- "
                         "update docs/ml_accept_reject_design.md's real-evaluation table too")

    def test_four_confirmed_artifacts_are_missed_at_the_default_threshold(self):
        """The re-review found MORE low-occupancy artifacts than the original labeled
        set had -- recall dropped (12/16 vs the old 11/12) even though precision
        improved (0 false positives now vs 1 before). Both directions reported, not
        just the flattering one."""
        artifacts = self._occs("artifact")
        missed = sorted(occ for occ in artifacts if occ < DEFAULT_THRESHOLD)
        self.assertEqual(len(missed), 4)
        self.assertAlmostEqual(missed[0], 0.75, places=2)   # idx 737894, the lowest

    def test_no_confirmed_real_particle_is_a_false_positive_after_the_re_review(self):
        """Before the re-review, idx 965074 (0.95) was Method A's headline "honest
        false positive." The re-review found it's actually a confirmed artifact --
        Method A was right, the OLD LABEL was wrong. Precision is clean now; this
        does not mean the overlap problem is solved (see the missed-artifacts test
        above), only that this particular case was a labeling error, not a model
        error."""
        reals = self._occs("real")
        self.assertEqual(len(reals), 5)
        false_positives = [occ for occ in reals if occ >= DEFAULT_THRESHOLD]
        self.assertEqual(false_positives, [])

    def test_the_overlap_band_is_narrower_but_still_real(self):
        """Highest confirmed-real (idx 2109304, 0.80) vs lowest confirmed-artifact
        (idx 737894, 0.75) -- closer together than before, not further apart. The
        re-review sharpened the picture; it didn't make max_col_occ a clean separator."""
        highest_real = max(self._occs("real"))
        lowest_artifact = min(self._occs("artifact"))
        self.assertAlmostEqual(highest_real, 0.80, places=2)
        self.assertAlmostEqual(lowest_artifact, 0.75, places=2)
        self.assertGreater(highest_real, lowest_artifact)   # genuine overlap, not just close

    def test_the_A14_merge_particle_is_not_expected_to_be_caught(self):
        """idx 5716830's shadow transitions between diode ranges over time, rather
        than one column staying dark for the whole span -- max_col_occ is low,
        correctly reflecting that this ISN'T a stuck-diode signature, even though
        it's confirmed real-but-merged (A14) by a different mechanism."""
        occ = next(occ for f, i, lab, occ in self.results if i == 5716830)
        self.assertLess(occ, DEFAULT_THRESHOLD)

    def test_the_mixed_particle_is_excluded_from_binary_metrics(self):
        """idx 40860 -- a real droplet plus a stuck diode plus other artifacts in one
        detection, per the user's own description. Not counted as a hit or a miss
        for either class; its score is still measured and reported, just not used
        to compute precision/recall."""
        mixed = self._occs("mixed")
        self.assertEqual(len(mixed), 1)
        self.assertAlmostEqual(mixed[0], 0.9856, places=3)
        # deliberately not asserting anything about is_artifact for this one --
        # there is no single correct answer for a mixed detection.


@unittest.skipUnless(not _MISSING, f"real decoded flights not present: {_MISSING}")
class MethodBRealEvaluationTests(unittest.TestCase):
    """Method B's real held-out numbers, 2026-08-28 -- pinned so the honest reading
    cannot drift.

    **The headline is not "0.905 beats 0.810."** It is that the trained 22-feature model
    and a *single re-tuned threshold on `max_col_occ` alone* score identically, which
    means the pooled image features contribute nothing measurable at n=21. Both facts are
    asserted below, because quoting the first without the second is the exact
    overclaim this project's own "measure, don't infer" rule exists to prevent.
    """

    @classmethod
    def setUpClass(cls):
        cls.pairs = load_shadows(list(REVIEWED_LABELS), _DECODED)
        cls.x, cls.y, cls.kept = build_dataset(cls.pairs)
        cls.report = evaluate_labeled_set(cls.pairs)

    def test_the_binary_labeled_set_is_twenty_one_particles_sixteen_positive(self):
        """22 reviewed, minus the one "mixed" detection that has no correct binary
        answer. This is the number every accuracy below has to be read against."""
        self.assertEqual(self.report["n"], 21)
        self.assertEqual(self.report["n_positive"], 16)
        self.assertEqual(self.report["n_features"], DEFAULT_GRID[0] * DEFAULT_GRID[1] + 6)
        self.assertEqual(len(self.report["flights"]), 6)

    def test_the_majority_class_floor_is_sixteen_of_twenty_one(self):
        """Predicting "artifact" unconditionally scores 0.762. Any number in the
        seventies has demonstrated nothing."""
        self.assertAlmostEqual(self.report["majority_accuracy"], 16 / 21)

    def test_method_b_leave_one_out_is_nineteen_of_twenty_one(self):
        self.assertAlmostEqual(self.report["loo_accuracy"], 19 / 21)
        self.assertEqual(self.report["loo_confusion"],
                         {"tp": 16, "fp": 2, "tn": 3, "fn": 0})

    def test_method_a_on_the_same_particles_is_seventeen_of_twenty_one(self):
        """Same 21 particles, so the two numbers are actually comparable. Method A
        trades the other way: no false positives, four missed artifacts."""
        self.assertAlmostEqual(self.report["method_a_accuracy"], 17 / 21)
        self.assertEqual(self.report["method_a_confusion"],
                         {"tp": 12, "fp": 0, "tn": 5, "fn": 4})

    def test_max_col_occ_alone_scores_exactly_what_the_full_model_does(self):
        """**The result that matters.** A one-feature logistic on Method A's own
        statistic reaches the same 19/21 with the same confusion matrix as the
        22-feature model. So Method B's gain over Method A is *threshold placement*,
        not the image: the pooled occupancy grid adds nothing detectable at this
        sample size. (The two false positives are not the same two particles --
        counts coincide, particles don't -- which is itself a sign these are
        indistinguishable at n=21, not that one model is a rescaling of the other.)"""
        col = DEFAULT_GRID[0] * DEFAULT_GRID[1] + SCALAR_FEATURE_NAMES.index("max_col_occ")
        one_feature = leave_one_out(self.x[:, [col]], self.y)
        self.assertAlmostEqual(one_feature.accuracy, self.report["loo_accuracy"])
        self.assertEqual(one_feature.confusion, self.report["loo_confusion"])

    def test_no_variant_separates_from_any_other_at_this_sample_size(self):
        """Grid 2x2 through 8x8 all land on 19 or 20 of 21 -- a one-particle spread,
        well inside the ~0.064 standard error of a 21-point accuracy. Pinned as a
        negative result: it is the evidence for "the labeled set is the blocker,"
        which is the whole basis for not adding a deep-learning dependency yet."""
        accs = []
        for grid in [(2, 2), (3, 3), (4, 4), (6, 6), (8, 8)]:
            x, y, _ = build_dataset(self.pairs, grid=grid)
            accs.append(leave_one_out(x, y).accuracy)
        self.assertTrue(all(19 / 21 <= a <= 20 / 21 for a in accs), accs)
        self.assertLessEqual(max(accs) - min(accs), 1 / 21 + 1e-9)

    def test_the_standard_error_of_the_headline_number_is_about_six_points(self):
        """Stated as an assertion rather than a caveat in prose, so it travels with
        the number: 0.905 on 21 points has a binomial standard error of ~0.064.
        Method B (0.905) and Method A (0.810) are 1.5 standard errors apart."""
        p = self.report["loo_accuracy"]
        se = float(np.sqrt(p * (1 - p) / self.report["n"]))
        self.assertAlmostEqual(se, 0.064, places=3)
        gap = self.report["loo_accuracy"] - self.report["method_a_accuracy"]
        self.assertLess(gap / se, 2.0)


if __name__ == "__main__":
    unittest.main()
