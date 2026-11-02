# SPDX-License-Identifier: BSD-3-Clause
"""Tests for particle_clustering.py -- pure numpy, no real flight data needed.

Two things need checking: (1) the k-means/medoid machinery is numerically
correct on synthetic data with a known answer, and (2) extract_features reads
the right particles out of a proc-file-shaped netCDF fixture.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import netCDF4
import numpy as np

from arrayprobe_enhancements.particle_clustering import (
    _NC_FEATURE_NAMES,
    FEATURE_NAMES,
    MissingProcVariable,
    _feature_space,
    choose_k,
    cluster_flight,
    extract_features,
    feature_names_for,
    kmeans,
)


class TestKMeans(unittest.TestCase):
    def test_recovers_well_separated_blobs(self):
        rng = np.random.default_rng(1)
        centers_true = np.array([[0, 0], [20, 20], [0, 20]], dtype=float)
        X = np.concatenate([c + rng.normal(scale=0.5, size=(80, 2)) for c in centers_true])
        labels, centers, inertia = kmeans(X, k=3, seed=1)
        self.assertEqual(len(set(labels.tolist())), 3)
        # every true blob's 80 points must land in a single fitted cluster
        for i in range(3):
            block = labels[i * 80:(i + 1) * 80]
            self.assertEqual(len(set(block.tolist())), 1)
        self.assertGreater(inertia, 0)

    def test_k_equals_n_each_point_its_own_cluster(self):
        X = np.array([[0.0, 0.0], [5.0, 5.0], [10.0, 0.0]])
        labels, centers, inertia = kmeans(X, k=3, seed=0)
        self.assertEqual(len(set(labels.tolist())), 3)
        self.assertAlmostEqual(inertia, 0.0, places=8)

    def test_k_too_large_raises(self):
        X = np.zeros((3, 2))
        with self.assertRaises(ValueError):
            kmeans(X, k=5)

    def test_choose_k_prefers_true_cluster_count_on_obvious_data(self):
        rng = np.random.default_rng(2)
        centers_true = np.array([[0, 0], [30, 30], [0, 30], [30, 0]], dtype=float)
        X = np.concatenate([c + rng.normal(scale=0.3, size=(50, 2)) for c in centers_true])
        k = choose_k(X, k_range=range(2, 9), seed=2)
        self.assertIn(k, (3, 4, 5))  # elbow heuristic is approximate, not exact


def _write_proc_fixture(path: Path, n: int, group_split: int) -> None:
    """A minimal netCDF file carrying only what extract_features reads:
    image_auto_reject (first `group_split` particles rejected, i.e. != '0'),
    the real netCDF fields (_NC_FEATURE_NAMES; "compactness" is derived, not
    stored), and edge_at_max_hole (read alongside max_hole_diameter to undo
    the C5 swap -- not itself a clustering feature, but extract_features
    requires it to be present), in two well-separated blobs so clustering on
    the fixture is itself checkable."""
    with netCDF4.Dataset(path, "w", format="NETCDF3_CLASSIC") as ds:
        ds.createDimension("particle", n)
        rc = ds.createVariable("image_auto_reject", "f8", ("particle",))
        rc[:] = [ord("t") if i < group_split else ord("0") for i in range(n)]
        rng = np.random.default_rng(0)
        half = n // 2
        for name in (*_NC_FEATURE_NAMES, "edge_at_max_hole"):
            v = ds.createVariable(name, "f8", ("particle",))
            lo = rng.normal(loc=1.0, scale=0.05, size=half)
            hi = rng.normal(loc=50.0, scale=0.05, size=n - half)
            v[:] = np.concatenate([lo, hi])


class TestExtractFeatures(unittest.TestCase):
    def test_group_filtering_and_shape(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "proc.fixture.H.nc"
            _write_proc_fixture(p, n=20, group_split=5)
            idx_acc, X_acc = extract_features(p, "accepted")
            idx_rej, X_rej = extract_features(p, "rejected")
            idx_all, X_all = extract_features(p, "all")
            self.assertEqual(len(idx_acc), 15)
            self.assertEqual(len(idx_rej), 5)
            self.assertEqual(len(idx_all), 20)
            self.assertTrue(np.array_equal(idx_rej, np.arange(5)))
            self.assertEqual(X_acc.shape, (15, len(FEATURE_NAMES)))

    def test_max_hole_diameter_feature_is_c5_unswapped(self):
        """Regression test, 2026-08-27: extract_features used to read
        max_hole_diameter raw, but the upstream swapped hole variables established that
        column and edge_at_max_hole are swapped on disk in every proc file
        this port (or MATLAB itself) writes -- so the clustering feature
        must be the unswapped value, not the raw one."""
        with TemporaryDirectory() as d:
            p = Path(d) / "proc.fixture.H.nc"
            _write_proc_fixture(p, n=10, group_split=0)
            with netCDF4.Dataset(p) as ds:
                raw_max_hole = np.asarray(ds.variables["max_hole_diameter"][:])
                raw_edge = np.asarray(ds.variables["edge_at_max_hole"][:])
            idx, X = extract_features(p, "all")
            mh_col = X[:, _NC_FEATURE_NAMES.index("max_hole_diameter")]
            # the feature must be the SIBLING column (edge_at_max_hole),
            # not the raw max_hole_diameter column read straight off disk
            np.testing.assert_allclose(mh_col, raw_edge[idx])
            self.assertFalse(np.allclose(mh_col, raw_max_hole[idx]))

    def test_unknown_group_raises(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "proc.fixture.H.nc"
            _write_proc_fixture(p, n=10, group_split=2)
            with self.assertRaises(ValueError):
                extract_features(p, "bogus")


class TestFeatureSpace(unittest.TestCase):
    def test_size_columns_are_log1p_others_untouched(self):
        # one value per FEATURE_NAMES column, in order; percent_shadow_area
        # and area_hole_ratio are the only two left untouched by _feature_space
        values = {
            "image_length": 10.0, "image_width": 10.0, "image_diam_minR": 10.0,
            "image_diam_circle_fit": 10.0, "image_perimeter": 10.0, "image_area": 10.0,
            "percent_shadow_area": 50.0, "max_hole_diameter": 10.0,
            "area_hole_ratio": 0.5, "compactness": 3.0,
        }
        self.assertEqual(set(values), set(FEATURE_NAMES))
        X = np.array([[values[name] for name in FEATURE_NAMES]])
        Xt = _feature_space(X)
        for i, name in enumerate(FEATURE_NAMES):
            if name in ("percent_shadow_area", "area_hole_ratio"):
                self.assertAlmostEqual(Xt[0, i], X[0, i])
            else:
                self.assertAlmostEqual(Xt[0, i], np.log1p(X[0, i]))

    def test_raw_matrix_unmodified(self):
        X = np.array([[10.0] * len(FEATURE_NAMES)])
        X_before = X.copy()
        _feature_space(X)
        self.assertTrue(np.array_equal(X, X_before))


class TestClusterFlight(unittest.TestCase):
    def test_two_blobs_become_two_clusters_with_correct_medoids(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "proc.fixture.H.nc"
            _write_proc_fixture(p, n=200, group_split=0)  # all accepted
            result = cluster_flight(p, group="accepted", k=2, seed=0)
            self.assertEqual(result.k, 2)
            self.assertEqual(sum(result.cluster_size.values()), 200)
            self.assertEqual(len(result.medoid_particle_index), 2)
            # the two medoids must come from opposite halves (index < 100 vs >= 100)
            medoid_halves = sorted(idx < 100 for idx in result.medoid_particle_index.values())
            self.assertEqual(medoid_halves, [False, True])
            # members() must round-trip against labels/particle_indices
            for cid in result.clusters_by_size():
                members = result.members(cid)
                self.assertEqual(len(members), result.cluster_size[cid])

    def test_empty_group_raises(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "proc.fixture.H.nc"
            _write_proc_fixture(p, n=10, group_split=10)  # all rejected
            with self.assertRaises(ValueError):
                cluster_flight(p, group="accepted", k=2)

    def test_max_fit_n_still_assigns_full_population(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "proc.fixture.H.nc"
            _write_proc_fixture(p, n=300, group_split=0)
            result = cluster_flight(p, group="accepted", k=2, max_fit_n=50, seed=0)
            self.assertEqual(sum(result.cluster_size.values()), 300)


def _write_v35_proc_fixture(path: Path, n: int, group_split: int) -> None:
    """Same shape as :func:`_write_proc_fixture`, minus ``image_diam_circle_fit`` --
    the column v3.5's ``imgProc_sm.m`` never writes (``:455-458``, commented out;
    confirmed by opening the lines). Used to prove
    :func:`feature_names_for`/:func:`extract_features` handle a genuinely
    circle-fit-less proc file, not merely a fixture that happens to include it."""
    names = tuple(name for name in _NC_FEATURE_NAMES if name != "image_diam_circle_fit")
    with netCDF4.Dataset(path, "w", format="NETCDF3_CLASSIC") as ds:
        ds.createDimension("particle", n)
        rc = ds.createVariable("image_auto_reject", "f8", ("particle",))
        rc[:] = [ord("t") if i < group_split else ord("0") for i in range(n)]
        rng = np.random.default_rng(0)
        half = n // 2
        for name in (*names, "edge_at_max_hole"):
            v = ds.createVariable(name, "f8", ("particle",))
            lo = rng.normal(loc=1.0, scale=0.05, size=half)
            hi = rng.normal(loc=50.0, scale=0.05, size=n - half)
            v[:] = np.concatenate([lo, hi])


class TestFeatureNamesForEngine(unittest.TestCase):
    """the v3.5 adaptation of the feature-column list (plan section 2 step 3)."""

    def test_314_is_the_full_feature_names(self):
        self.assertEqual(feature_names_for("3.1.4"), FEATURE_NAMES)
        self.assertEqual(feature_names_for(), FEATURE_NAMES)  # default arg

    def test_35_drops_circle_fit_but_keeps_compactness(self):
        names = feature_names_for("3.5")
        self.assertNotIn("image_diam_circle_fit", names)
        self.assertEqual(names[-1], "compactness")
        self.assertEqual(len(names), len(FEATURE_NAMES) - 1)
        self.assertEqual(set(FEATURE_NAMES) - set(names), {"image_diam_circle_fit"})

    def test_unknown_engine_raises(self):
        with self.assertRaises(ValueError):
            feature_names_for("2.7")

    def test_extract_features_engine_314_is_byte_identical_to_the_default(self):
        """Equivalence side (a): passing engine="3.1.4" explicitly must change nothing --
        `pipeline.py`'s own module docstring standard applied to this module too."""
        with TemporaryDirectory() as d:
            p = Path(d) / "proc.fixture.H.nc"
            _write_proc_fixture(p, n=20, group_split=5)
            idx_default, X_default = extract_features(p, "accepted")
            idx_explicit, X_explicit = extract_features(p, "accepted", engine="3.1.4")
            self.assertTrue(np.array_equal(idx_default, idx_explicit))
            self.assertTrue(np.array_equal(X_default, X_explicit))

    def test_extract_features_engine_35_on_a_circle_fit_less_proc_returns_8_plus_1_columns(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "proc.fixture.H.nc"
            _write_v35_proc_fixture(p, n=20, group_split=5)
            idx, X = extract_features(p, "accepted", engine="3.5")
            self.assertEqual(X.shape, (15, 9))  # 8 nc columns (one dropped) + compactness

    def test_extract_features_default_engine_raises_named_refusal_on_a_v35_shaped_proc(self):
        """Discriminating test (plan section 2 step 3c): the default engine ("3.1.4")
        against a proc file that genuinely lacks image_diam_circle_fit must raise the
        named refusal, not a bare KeyError."""
        with TemporaryDirectory() as d:
            p = Path(d) / "proc.fixture.H.nc"
            _write_v35_proc_fixture(p, n=10, group_split=0)
            with self.assertRaises(MissingProcVariable) as ctx:
                extract_features(p, "all")
            self.assertEqual(ctx.exception.name, "image_diam_circle_fit")

    def test_cluster_flight_engine_35_runs_on_a_circle_fit_less_proc(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "proc.fixture.H.nc"
            _write_v35_proc_fixture(p, n=200, group_split=0)
            result = cluster_flight(p, group="accepted", k=2, seed=0, engine="3.5")
            self.assertEqual(result.k, 2)
            self.assertNotIn("image_diam_circle_fit", result.feature_names)
            self.assertEqual(sum(result.cluster_size.values()), 200)


if __name__ == "__main__":
    unittest.main()
