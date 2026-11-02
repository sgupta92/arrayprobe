# SPDX-License-Identifier: BSD-3-Clause
"""Tests for ml_accept_reject.py (task #27), Method B: pipeline, features, baseline model.

**Every test here runs on synthetic data and a temporary directory.** No decoded flight, no
proc file, no `_decoded/triage_verdicts/` -- deliberately, for two reasons. The obvious one is
that a fresh clone has none of that (the real-data evaluation lives in
`test_ml_accept_reject.py`, which skips when the files are absent). The load-bearing one is
that the verdict sidecars are **human labels that were already destroyed once**: an autonomous
bulk-labeling pass on 2026-08-27 overwrote ~2.69M particles' verdicts across three flights.
A test suite that writes into that directory to set up a fixture is one bad path away from
repeating it, so these tests build their own JSON in `tempfile.TemporaryDirectory()` and one of
them (`test_loading_never_modifies_the_verdict_file`) asserts the read path leaves a sidecar
byte-identical.

The numbers asserted below are measured from the code, not chosen to look good.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from arrayprobe_enhancements.ml_accept_reject import (
    BULK_LABEL_NOTE_PREFIX,
    DEFAULT_GRID,
    REVIEWED_LABELS,
    SCALAR_FEATURE_NAMES,
    TORCH_CNN_REQUIREMENTS,
    LabeledParticle,
    _overlap_matrix,
    build_dataset,
    evaluate_labeled_set,
    feature_names,
    fit_logistic,
    human_labeled_particles,
    leave_one_out,
    majority_class_accuracy,
    particle_features,
    pool_to_grid,
    read_verdict_sidecar,
)

# --------------------------------------------------------------------------- helpers

def _stuck_diode_shadow(n_slices=40, n_diodes=16, column=5, rng=None):
    """A synthetic stuck-diode artifact: one column dark for the whole span, plus noise."""
    rng = rng or np.random.default_rng(0)
    shadow = rng.random((n_slices, n_diodes)) < 0.05
    shadow[:, column] = True
    return shadow


def _real_particle_shadow(n_slices=40, n_diodes=16, rng=None):
    """A synthetic real drop: a compact blob that occupies no column for the whole span."""
    rng = rng or np.random.default_rng(1)
    shadow = np.zeros((n_slices, n_diodes), dtype=bool)
    r0 = n_slices // 3
    c0 = n_diodes // 3
    shadow[r0:r0 + 6, c0:c0 + 6] = True
    shadow |= rng.random((n_slices, n_diodes)) < 0.01
    return shadow


def _synthetic_pairs(n_artifact=12, n_real=9):
    """A balanced-ish synthetic labeled set, as (LabeledParticle, shadow) pairs."""
    pairs = []
    for i in range(n_artifact):
        rng = np.random.default_rng(100 + i)
        pairs.append((
            LabeledParticle("synthflight", i, "artifact"),
            _stuck_diode_shadow(column=i % 16, rng=rng),
        ))
    for i in range(n_real):
        rng = np.random.default_rng(200 + i)
        pairs.append((
            LabeledParticle("synthflight", 1000 + i, "real"),
            _real_particle_shadow(rng=rng),
        ))
    return pairs


# --------------------------------------------------------------------------- pooling

class OverlapMatrixTests(unittest.TestCase):
    def test_every_row_sums_to_one(self):
        for n_in, n_out in [(1, 4), (7, 4), (40, 4), (128, 8), (3, 3)]:
            w = _overlap_matrix(n_in, n_out)
            self.assertEqual(w.shape, (n_out, n_in))
            np.testing.assert_allclose(w.sum(axis=1), np.ones(n_out))

    def test_upsampling_a_single_input_row_does_not_divide_by_zero(self):
        """n_in < n_out is the case a floor-division index map gets wrong: it leaves
        output rows with no source and produces 0/0. Area resampling spreads the one
        input row across all output rows instead."""
        w = _overlap_matrix(1, 4)
        np.testing.assert_allclose(w, np.ones((4, 1)))
        self.assertTrue(np.isfinite(w).all())

    def test_exact_division_is_a_clean_block_average(self):
        w = _overlap_matrix(4, 2)
        np.testing.assert_allclose(w, np.array([[0.5, 0.5, 0, 0], [0, 0, 0.5, 0.5]]))


class PoolToGridTests(unittest.TestCase):
    def test_a_fully_shadowed_particle_pools_to_all_ones(self):
        pooled = pool_to_grid(np.ones((37, 23), dtype=bool), (4, 4))
        np.testing.assert_allclose(pooled, np.ones((4, 4)))

    def test_a_half_shadowed_particle_pools_to_the_right_halves(self):
        shadow = np.zeros((8, 8), dtype=bool)
        shadow[:, :4] = True
        pooled = pool_to_grid(shadow, (2, 2))
        np.testing.assert_allclose(pooled, np.array([[1.0, 0.0], [1.0, 0.0]]))

    def test_output_shape_is_fixed_whatever_the_input_size(self):
        """The whole point: a 3-slice particle and a 900-slice particle produce the
        same-length vector, which is what lets them share a model at all."""
        for shape in [(3, 5), (900, 128), (1, 1), (64, 64)]:
            self.assertEqual(pool_to_grid(np.ones(shape, dtype=bool), (4, 4)).shape, (4, 4))

    def test_empty_shadow_gives_a_zero_grid_rather_than_raising(self):
        np.testing.assert_allclose(pool_to_grid(np.zeros((0, 8), dtype=bool)), np.zeros((4, 4)))

    def test_occupancy_is_a_fraction_not_a_subsample(self):
        """One lit pixel in a 16x16 particle pooled to 4x4 lands as 1/16 in its cell,
        not as a 1 (nearest-neighbour) or a 0 (dropped)."""
        shadow = np.zeros((16, 16), dtype=bool)
        shadow[0, 0] = True
        pooled = pool_to_grid(shadow, (4, 4))
        self.assertAlmostEqual(pooled[0, 0], 1.0 / 16.0)
        self.assertAlmostEqual(pooled.sum(), 1.0 / 16.0)


# --------------------------------------------------------------------------- features

class FeatureTests(unittest.TestCase):
    def test_feature_vector_length_matches_the_names(self):
        shadow = _stuck_diode_shadow()
        vec = particle_features(shadow)
        self.assertEqual(len(vec), DEFAULT_GRID[0] * DEFAULT_GRID[1] + len(SCALAR_FEATURE_NAMES))
        self.assertEqual(len(vec), len(feature_names()))

    def test_max_col_occ_is_the_first_scalar_and_is_uncropped(self):
        """Method A's statistic is defined over the particle's whole detection window --
        a column dark for the ENTIRE span is the signature. Computing it after cropping
        would raise it artificially for every particle, so it is deliberately taken from
        the uncropped shadow while the pooled grid is taken from the cropped one."""
        shadow = np.zeros((40, 8), dtype=bool)
        shadow[10:20, 3] = True            # dark for 10 of 40 slices, not the whole span
        vec = particle_features(shadow)
        idx = DEFAULT_GRID[0] * DEFAULT_GRID[1] + SCALAR_FEATURE_NAMES.index("max_col_occ")
        self.assertAlmostEqual(vec[idx], 0.25)

    def test_features_are_deterministic(self):
        shadow = _stuck_diode_shadow()
        np.testing.assert_array_equal(particle_features(shadow), particle_features(shadow))

    def test_a_finer_grid_produces_a_longer_vector(self):
        shadow = _real_particle_shadow()
        self.assertEqual(len(particle_features(shadow, (8, 8))), 64 + len(SCALAR_FEATURE_NAMES))


# --------------------------------------------------------------------------- verdict I/O

class VerdictLoadingTests(unittest.TestCase):
    SIDECAR = {
        "1": {"note": "", "verdict": "real"},
        "2": {"note": "", "verdict": "artifact"},
        "3": {"note": "", "verdict": "unsure"},
        "4": {"note": f"{BULK_LABEL_NOTE_PREFIX} (k=8, cluster 1)", "verdict": "artifact"},
        "5": {"note": f"{BULK_LABEL_NOTE_PREFIX} (k=8, cluster 2)", "verdict": "artifact"},
    }

    def _write(self, root: Path, flight: str = "synthflight") -> Path:
        d = root / "triage_verdicts"
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{flight}.json"
        p.write_text(json.dumps(self.SIDECAR, indent=1), encoding="utf-8")
        return d

    def test_missing_file_reads_as_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(read_verdict_sidecar(Path(tmp) / "nope.json"), {})

    def test_missing_directory_yields_no_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(human_labeled_particles(Path(tmp) / "nope"), [])

    def test_bulk_labels_are_excluded_by_default(self):
        """The 2026-08-27 incident wrote ~2.69M of these. Training on them would teach a
        model to reproduce the mistake, so they are dropped unless explicitly asked for."""
        with tempfile.TemporaryDirectory() as tmp:
            d = self._write(Path(tmp))
            got = human_labeled_particles(d)
            self.assertEqual({item.particle_index for item in got}, {1, 2})

    def test_bulk_labels_can_be_requested_explicitly(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._write(Path(tmp))
            got = human_labeled_particles(d, exclude_bulk=False)
            self.assertEqual({item.particle_index for item in got}, {1, 2, 4, 5})

    def test_unsure_is_dropped_not_folded_into_a_class(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._write(Path(tmp))
            self.assertNotIn(3, {item.particle_index for item in human_labeled_particles(d)})

    def test_flights_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._write(Path(tmp), "flightA")
            self._write(Path(tmp), "flightB")
            got = human_labeled_particles(d, flights=["flightA"])
            self.assertEqual({item.flight for item in got}, {"flightA"})

    def test_loading_never_modifies_the_verdict_file(self):
        """Human labels are READ-ONLY input to this module. Asserted by hash, not by
        reading the source and trusting it."""
        with tempfile.TemporaryDirectory() as tmp:
            d = self._write(Path(tmp))
            path = d / "synthflight.json"
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            human_labeled_particles(d)
            human_labeled_particles(d, exclude_bulk=False)
            read_verdict_sidecar(path)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)


class ReviewedLabelRegistryTests(unittest.TestCase):
    """The committed 22-particle registry is the authoritative copy of the user's
    2026-08-27 review -- the sidecars hold only 14 of them, the rest having been
    overwritten by the bulk pass. Pinning its shape here is what stops a later edit
    from silently changing the set the published numbers were measured on."""

    def test_registry_has_the_twenty_two_reviewed_particles(self):
        self.assertEqual(len(REVIEWED_LABELS), 22)

    def test_class_counts(self):
        counts: dict[str, int] = {}
        for item in REVIEWED_LABELS:
            counts[item.label] = counts.get(item.label, 0) + 1
        self.assertEqual(counts, {"artifact": 16, "real": 5, "mixed": 1})

    def test_six_flights_are_represented(self):
        self.assertEqual(len({item.flight for item in REVIEWED_LABELS}), 6)

    def test_indices_are_unique_within_a_flight(self):
        keys = [(item.flight, item.particle_index) for item in REVIEWED_LABELS]
        self.assertEqual(len(keys), len(set(keys)))


# --------------------------------------------------------------------------- dataset

class BuildDatasetTests(unittest.TestCase):
    def test_mixed_is_excluded_rather_than_forced_into_a_class(self):
        pairs = _synthetic_pairs(2, 2)
        pairs.append((LabeledParticle("synthflight", 999, "mixed"), _real_particle_shadow()))
        x, y, kept = build_dataset(pairs)
        self.assertEqual(len(kept), 4)
        self.assertEqual(x.shape[0], 4)
        self.assertNotIn(999, [item.particle_index for item in kept])

    def test_artifact_is_the_positive_class(self):
        x, y, kept = build_dataset(_synthetic_pairs(3, 2))
        self.assertEqual(int(y.sum()), 3)
        self.assertEqual([item.label for item in kept][:3], ["artifact"] * 3)

    def test_empty_input_gives_correctly_shaped_empties(self):
        x, y, kept = build_dataset([])
        self.assertEqual(x.shape, (0, DEFAULT_GRID[0] * DEFAULT_GRID[1] + 6))
        self.assertEqual(len(y), 0)
        self.assertEqual(kept, [])


# --------------------------------------------------------------------------- model

class LogisticModelTests(unittest.TestCase):
    def test_fit_is_deterministic(self):
        x, y, _ = build_dataset(_synthetic_pairs())
        a = fit_logistic(x, y)
        b = fit_logistic(x, y)
        np.testing.assert_array_equal(a.weights, b.weights)
        self.assertEqual(a.bias, b.bias)

    def test_it_learns_a_separable_problem(self):
        x = np.array([[0.0], [0.1], [0.2], [5.0], [5.1], [5.2]])
        y = np.array([0, 0, 0, 1, 1, 1])
        model = fit_logistic(x, y, l2=0.01)
        np.testing.assert_array_equal(model.predict(x), y)

    def test_a_constant_column_does_not_divide_by_zero(self):
        x = np.array([[1.0, 0.0], [1.0, 1.0], [1.0, 5.0], [1.0, 6.0]])
        y = np.array([0, 0, 1, 1])
        model = fit_logistic(x, y)
        self.assertTrue(np.isfinite(model.weights).all())
        self.assertTrue(np.isfinite(model.predict_proba(x)).all())

    def test_predict_proba_is_stable_at_extreme_decision_values(self):
        """A naive 1/(1+exp(-z)) overflows for large negative z. Probabilities must stay
        finite and inside [0, 1] regardless."""
        x = np.array([[0.0], [1.0], [2.0], [3.0]])
        y = np.array([0, 0, 1, 1])
        model = fit_logistic(x, y, l2=1e-9, n_iter=4000, lr=2.0)
        p = model.predict_proba(np.array([[-1e6], [1e6]]))
        self.assertTrue(np.isfinite(p).all())
        self.assertTrue(((p >= 0.0) & (p <= 1.0)).all())

    def test_standardisation_travels_with_the_model(self):
        x, y, _ = build_dataset(_synthetic_pairs())
        model = fit_logistic(x, y)
        self.assertEqual(model.mean.shape, (x.shape[1],))
        self.assertTrue((model.std > 0).all())
        self.assertEqual(model.n_train, x.shape[0])


class LeaveOneOutTests(unittest.TestCase):
    def test_loo_on_a_synthetic_set_designed_to_be_easy(self):
        """20 of 21, not 21 of 21 -- and the number is asserted as measured rather than
        the fixture being tuned until it is perfect. Even a synthetic set built to be
        separable loses one point under an honest held-out protocol at n=21, which is
        the small-sample effect this whole module is careful about."""
        x, y, _ = build_dataset(_synthetic_pairs())
        result = leave_one_out(x, y)
        self.assertEqual(result.n, 21)
        self.assertAlmostEqual(result.accuracy, 20 / 21)
        self.assertEqual(sum(result.confusion.values()), 21)

    def test_loo_does_not_leak_the_held_out_point(self):
        """The leakage guard. On pure noise -- features independent of labels -- an
        honest leave-one-out lands near chance. A protocol that standardises over the
        full set, or that fits on all n and scores the same n, scores far above it.
        Seeded, so this is a fixed number, not a flaky threshold."""
        rng = np.random.default_rng(20260828)
        x = rng.normal(size=(20, 8))
        y = np.array([0, 1] * 10)
        self.assertLessEqual(leave_one_out(x, y).accuracy, 0.70)

    def test_confusion_counts_sum_to_n(self):
        x, y, _ = build_dataset(_synthetic_pairs(6, 5))
        c = leave_one_out(x, y).confusion
        self.assertEqual(sum(c.values()), 11)


class MajorityBaselineTests(unittest.TestCase):
    def test_majority_of_sixteen_artifacts_and_five_reals(self):
        y = np.array([1] * 16 + [0] * 5)
        self.assertAlmostEqual(majority_class_accuracy(y), 16 / 21)

    def test_balanced_set_is_a_half(self):
        self.assertAlmostEqual(majority_class_accuracy(np.array([0, 1, 0, 1])), 0.5)

    def test_empty_is_zero_rather_than_raising(self):
        self.assertEqual(majority_class_accuracy(np.array([], dtype=int)), 0.0)


# --------------------------------------------------------------------------- end to end

class SyntheticEndToEndTests(unittest.TestCase):
    """The whole Method B chain on synthetic images: features -> fit -> held-out score,
    reported against the majority floor and Method A on the identical particles."""

    def test_report_contains_every_number_needed_to_read_it_honestly(self):
        report = evaluate_labeled_set(_synthetic_pairs())
        for key in ("n", "n_positive", "majority_accuracy", "loo_accuracy",
                    "loo_confusion", "method_a_accuracy", "method_a_confusion"):
            self.assertIn(key, report)
        self.assertEqual(report["n"], 21)
        self.assertEqual(report["n_positive"], 12)

    def test_the_model_beats_the_majority_floor_on_separable_synthetic_data(self):
        """Synthetic stuck-diode vs. compact-blob is separable by construction, so this
        checks the machinery works -- it says NOTHING about real particles, where the
        classes genuinely overlap (see test_ml_accept_reject.py's real evaluation)."""
        report = evaluate_labeled_set(_synthetic_pairs())
        self.assertGreater(report["loo_accuracy"], report["majority_accuracy"])
        self.assertAlmostEqual(report["loo_accuracy"], 20 / 21)

    def test_a_mixed_particle_is_dropped_from_every_metric(self):
        pairs = _synthetic_pairs()
        pairs.append((LabeledParticle("synthflight", 5000, "mixed"), _real_particle_shadow()))
        self.assertEqual(evaluate_labeled_set(pairs)["n"], 21)


class DocumentedRequirementsTests(unittest.TestCase):
    def test_the_cnn_requirements_note_names_the_actual_blocker(self):
        """The framework is not the blocker and the note must not imply it is -- the
        labeled set is 21 particles. Pinned so a later edit cannot quietly soften it."""
        self.assertIn("LABELS", TORCH_CNN_REQUIREMENTS)
        self.assertIn("21", TORCH_CNN_REQUIREMENTS)
        self.assertIn("not the framework", TORCH_CNN_REQUIREMENTS)


if __name__ == "__main__":
    unittest.main()
