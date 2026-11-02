# SPDX-License-Identifier: BSD-3-Clause
"""``partial_image_habit`` -- Korolev & Sussman (2000) RABIT.

Each test draws its two sides from different places: the paper's printed numbers against
the paper's own normalisation statement, Eq. 2 against an independently derived arc length,
and the perimeter reading against the paper's own measured basis distributions.
"""

from __future__ import annotations

import hashlib
import inspect
import math
import unittest
from pathlib import Path

import numpy as np

from arrayprobe_enhancements import applicability, registry
from arrayprobe_enhancements import partial_image_habit as pih

DATA = Path(__file__).resolve().parents[2] / "tests" / "data"
IMAGE = DATA / "demo_flight_v314_image.cdf"
PROC = DATA / "demo_flight_v314_proc.nc"


def disc(radius, n_diodes, centre_diode, n_slices=None):
    """A digitised filled circle: a pixel is shadowed when its centre is inside."""
    n_slices = n_slices or int(2 * radius + 6)
    y, x = np.meshgrid(np.arange(n_diodes) + 0.5, np.arange(n_slices) + 0.5)
    return (x - n_slices / 2) ** 2 + (y - centre_diode) ** 2 <= radius ** 2


def literal_direction_perimeter(image):
    """Eq. 4 with step 2 read literally (A shifted *left*, opposite to step 4's *right*).

    Kept here, not in the module, only to pin the measurement that rules this reading
    out (module docstring, reading 4)."""
    a = np.pad(np.asarray(image, dtype=np.int8), ((1, 1), (0, 0)))
    a = np.pad(a, ((0, 0), (1, 1)), mode="edge")
    up = np.zeros_like(a)
    up[:, :-1] = a[:, 1:]
    b = (a + up) % 2
    left = np.zeros_like(a)
    left[:-1, :] = a[1:, :]
    c = (a + left) % 2
    b_right = np.zeros_like(b)
    b_right[1:, :] = b[:-1, :]
    f = b_right + c + b + c
    f[f == 1] = 0
    inside = f[:, 1:image.shape[1] + 1]
    return int((inside == 2).sum()) + math.sqrt(2) * int((inside == 3).sum())


class TheAppendixIsTranscribed(unittest.TestCase):
    """p. 1057 against Sect. 4d's own statement that each B_i is normalised to unity."""

    def test_every_basis_row_sums_to_one_at_the_printed_precision(self):
        for matrix in (pih.KS2000_OAP2DC_COMPLETE, pih.KS2000_OAP2DC_PARTIAL):
            for habit, row in zip(matrix.habits, matrix.rows, strict=True):
                with self.subTest(ratio=matrix.ratio, habit=habit):
                    self.assertAlmostEqual(sum(row), 1.0, delta=2e-4)

    def test_the_matrices_are_square_and_invertible(self):
        for matrix in (pih.KS2000_OAP2DC_COMPLETE, pih.KS2000_OAP2DC_PARTIAL):
            b = matrix.as_array()
            self.assertEqual(b.shape, (len(matrix.habits), len(matrix.edges) - 1))
            self.assertEqual(b.shape[0], b.shape[1])
            self.assertLess(np.linalg.cond(b), 20.0)

    def test_the_intervals_are_the_printed_ones(self):
        self.assertEqual(pih.KS2000_OAP2DC_COMPLETE.edges, (0.0, 1.07, 1.94, math.inf))
        self.assertEqual(pih.KS2000_OAP2DC_PARTIAL.edges, (0.0, 0.94, 1.16, 2.06, math.inf))

    def test_both_matrices_name_the_probe_they_came_from(self):
        for matrix in (pih.KS2000_OAP2DC_COMPLETE, pih.KS2000_OAP2DC_PARTIAL):
            self.assertEqual((matrix.n_diodes, matrix.pixel_um), (32, 25.0))


class Eq2PartialCirclePerimeter(unittest.TestCase):
    """Eq. 2 against the arc length of a circle cut by two parallel lines, derived here."""

    @staticmethod
    def independent_arc(radius, h, y):
        """In-frame arc of a circle whose centre is ``h`` from edge 1, frame ``y`` wide."""
        lost = 0.0
        for d in (h, y - h):
            if d < radius:
                lost += 2 * radius * math.acos(d / radius)
        return 2 * math.pi * radius - lost

    def test_a_complete_circle_is_pi_times_its_diameter(self):
        for y in (3, 10, 32, 57):
            self.assertAlmostEqual(pih.p_circ(0, 0, y), math.pi * y, places=12)

    def test_cut_on_both_edges(self):
        for radius, h, y in ((20.0, 12.0, 32.0), (40.0, 16.0, 32.0), (18.0, 17.5, 32.0)):
            x1 = 2 * math.sqrt(radius ** 2 - h ** 2)
            x2 = 2 * math.sqrt(radius ** 2 - (y - h) ** 2)
            with self.subTest(radius=radius, h=h):
                self.assertAlmostEqual(pih.p_circ(x1, x2, y),
                                       self.independent_arc(radius, h, y), places=9)

    def test_cut_on_one_edge_only(self):
        for radius, h in ((20.0, 8.0), (12.0, 2.0)):
            y = h + radius                               # tangent to the far side
            x1 = 2 * math.sqrt(radius ** 2 - h ** 2)
            with self.subTest(radius=radius, h=h):
                self.assertAlmostEqual(pih.p_circ(x1, 0, y),
                                       self.independent_arc(radius, h, y), places=9)
                self.assertAlmostEqual(pih.p_circ(0, x1, y),
                                       self.independent_arc(radius, h, y), places=9)


class Eq4Perimeter(unittest.TestCase):

    def test_a_straight_run_pinned_as_measured(self):
        """A 7-slice, one-diode run: its two long sides read as legs (2 x 6) and two of its
        four corner types read as a diagonal step -- an approximation of the algorithm
        under reading 4, pinned so a change to it is seen, not claimed exact."""
        line = np.zeros((12, 20), bool)
        line[2:9, 10] = True
        self.assertAlmostEqual(pih.ks_perimeter(line), 12.0 + 2 * math.sqrt(2))

    def test_digitised_discs_read_as_an_eight_connected_chain_code_does(self):
        for radius in (5, 10, 20, 30):
            ratio = pih.ks_perimeter(disc(radius, 128, 64)) / (2 * math.pi * radius)
            with self.subTest(radius=radius):
                self.assertTrue(1.03 < ratio < 1.10, ratio)

    def test_the_literal_direction_reading_undercounts_by_two_quadrants(self):
        """Reading 4's discriminator: literal 'left' then 'right' counts two diagonal
        quadrants as legs. Measured 0.79-0.85 on the same discs."""
        for radius in (5, 10, 20, 30):
            ratio = literal_direction_perimeter(disc(radius, 128, 64)) / (2 * math.pi * radius)
            with self.subTest(radius=radius):
                self.assertTrue(0.75 < ratio < 0.90, ratio)

    def test_the_cut_edge_is_not_perimeter(self):
        """A partial disc's N_P must not include its chord along the array edge."""
        whole = disc(20, 32, 16 + 30)                    # centre beyond the far edge
        cut = pih.ks_perimeter(whole)
        m = pih.measure(whole)
        self.assertGreater(m.n_edge2, 20)
        self.assertLess(cut, pih.p_circ(m.n_edge1, m.n_edge2, m.ny) * 1.2)


class TheRatiosLandWhereThePaperSaysSpheresDo(unittest.TestCase):
    """Geometry against the paper's measured basis: 98 % of complete spheres have R1 in
    [0, 1.07); 94.7 % of partial spheres have R2 in [0.94, 1.16) (appendix)."""

    def test_complete_discs_have_r1_in_the_sphere_interval(self):
        for radius in (3, 6, 10, 20):
            m = pih.measure(disc(radius, 128, 64))
            with self.subTest(radius=radius):
                self.assertLess(pih.r1(m), 1.07)

    def test_partial_discs_have_r2_in_the_sphere_interval(self):
        for radius, centre in ((20, 10), (30, 5), (40, -10), (20, 20), (12, 3)):
            img = disc(radius, 32, centre)
            with self.subTest(radius=radius, centre=centre):
                self.assertEqual(pih.image_groups(pih.measure(img), 32),
                                 frozenset({"accepted_partial"}))
                self.assertTrue(0.94 <= pih.r2(img) < 1.16, pih.r2(img))

    def test_a_long_needle_has_r1_in_the_needle_interval(self):
        needle = np.zeros((40, 128), bool)
        needle[4:36, 60:63] = True                       # c/a = 32/3
        self.assertGreaterEqual(pih.r1(pih.measure(needle)), 1.94)


class ImageGroups(unittest.TestCase):
    """Sect. 4b, p. 1050-1051, rule by rule."""

    @staticmethod
    def groups(img, n_diodes=32):
        return pih.image_groups(pih.measure(img), n_diodes)

    def test_tiny(self):
        img = np.zeros((10, 32), bool)
        img[3:6, 10:13] = True                           # 9 pixels
        self.assertEqual(self.groups(img), frozenset({"tiny"}))

    def test_complete(self):
        self.assertEqual(self.groups(disc(5, 32, 16)), frozenset({"complete"}))

    def test_accepted_partial(self):
        self.assertEqual(self.groups(disc(20, 32, 10)), frozenset({"accepted_partial"}))

    def test_rejected_partial(self):
        img = disc(8, 32, 3)                              # small, cut by edge 1
        m = pih.measure(img)
        self.assertLessEqual(m.n_total, 180)
        self.assertGreaterEqual(m.n_edge, 4)
        self.assertEqual(self.groups(img), frozenset({"rejected_partial"}))

    def test_an_interior_empty_slice_is_rejected(self):
        img = disc(5, 32, 16)
        img[img.any(axis=1).nonzero()[0][4]] = False
        self.assertIn("rejected_partial", self.groups(img))
        self.assertIsNone(pih.retrieval_group(self.groups(img)))

    def test_the_rules_overlap_and_the_overlap_is_not_retrieved(self):
        """> 180 pixels spanning the array with N_edge < 4 is both complete and accepted
        partial; the paper states no precedence, so neither is retrieved."""
        img = np.zeros((20, 32), bool)
        img[2:18, 1:31] = True
        img[10, 0] = img[10, 31] = True                  # spans all 32, N_edge = 2
        g = self.groups(img)
        self.assertEqual(g, frozenset({"complete", "accepted_partial"}))
        self.assertIsNone(pih.retrieval_group(g))

    def test_exactly_twenty_pixels_is_in_no_group(self):
        img = np.zeros((10, 32), bool)
        img[2:6, 10:15] = True                           # 20 pixels
        self.assertEqual(self.groups(img), frozenset())

    def test_full_span_means_the_probe_width_not_32(self):
        """Reading 2: 32 diodes across, clear of both edges, on a 128-diode array is a
        complete image -- read literally as ``N_y == 32`` it would also be a partial."""
        img = np.zeros((30, 128), bool)
        img[2:25, 10:42] = True
        self.assertEqual(pih.measure(img).ny, 32)
        self.assertEqual(self.groups(img, n_diodes=128), frozenset({"complete"}))


class Retrieval(unittest.TestCase):

    def test_a_mixture_of_the_basis_rows_is_recovered(self):
        """Eq. 5 forward, Eq. 8 back, with the paper's own example f (p. 1054)."""
        matrix = pih.KS2000_OAP2DC_PARTIAL
        f = np.array([0.5, 0.2, 0.05, 0.25])
        m = matrix.as_array().T @ f
        counts = np.rint(m * 1_000_000).astype(int)
        mids = (0.5, 1.0, 1.5, 3.0)
        ratios = np.repeat(mids, counts)
        # Two printed rows sum to 1.0001 (four-decimal rounding), so exact recovery is
        # to the printed precision, not to machine precision.
        np.testing.assert_allclose(pih.retrieve_fractions(ratios, matrix), f, atol=1e-4)

    def test_eq9_weights_by_image_count(self):
        f = pih.combine([1.0, 0.0, 0.0], 3, [0.0, 0.0, 0.0, 1.0], 1)
        np.testing.assert_allclose(f, [0.75, 0.0, 0.0, 0.25])

    def test_a_training_set_rebuilds_its_own_basis(self):
        edges = (0.0, 1.0, 2.0)
        m = pih.build_retrieval_matrix({"a": [0.5, 0.5, 1.5], "b": [1.5, 1.5, 1.5, 0.5]},
                                       edges, ratio="R", n_diodes=128, pixel_um=10.0,
                                       probe="test", source="test")
        np.testing.assert_allclose(m.as_array(), [[2 / 3, 1 / 3], [0.25, 0.75]])

    def test_a_non_square_training_set_is_refused(self):
        with self.assertRaises(ValueError):
            pih.build_retrieval_matrix({"a": [0.5], "b": [1.5]}, (0.0, 1.0, 2.0, 3.0),
                                       ratio="R", n_diodes=128, pixel_um=10.0,
                                       probe="t", source="t")


class TheOAP2DCMatricesAreRefusedElsewhere(unittest.TestCase):
    """p. 1057: the matrices do not transfer to other probe configurations."""

    def test_a_2ds_population_is_refused_before_any_image_is_read(self):
        with self.assertRaises(pih.NoRetrievalMatrixForProbe) as ctx:
            pih.classify_population(iter(()), n_diodes=128, pixel_um=10.0)
        self.assertIn("p. 1057", str(ctx.exception))

    def test_the_same_pixel_count_at_another_resolution_is_refused(self):
        with self.assertRaises(pih.NoRetrievalMatrixForProbe):
            pih.classify_population([disc(5, 32, 16)], n_diodes=32, pixel_um=10.0)

    def test_an_oap2dc_shaped_population_is_classified(self):
        images = [disc(5, 32, 16)] * 5 + [disc(20, 32, 10)] * 3
        result = pih.classify_population(images, n_diodes=32, pixel_um=25.0)
        self.assertEqual((result.n_complete, result.n_partial), (5, 3))
        self.assertAlmostEqual(sum(result.fractions), 1.0, delta=1e-4)
        self.assertGreater(result.fractions[0], 0.9)      # discs retrieve as spheres

    def test_census_needs_no_matrix(self):
        result = pih.census([disc(5, 128, 64), disc(20, 128, 10)], 128)
        self.assertEqual((result.n_complete, result.n_partial), (1, 1))
        self.assertIsNone(result.fractions)


class RegisteredAndDeclared(unittest.TestCase):

    def test_registered_opt_in_with_its_entry_point(self):
        spec = registry.REGISTRY["partial_image_habit"]
        self.assertFalse(spec.default_on)  # 2026-09-16: opt-in, like every other module
        self.assertIs(registry.entry_point("partial_image_habit"), pih.classify_population)
        self.assertEqual(spec.consumes, frozenset({"images"}))

    def test_applies_on_both_engines_and_is_individually_selectable(self):
        for engine in applicability.ENGINES:
            self.assertTrue(applicability.applicable("partial_image_habit", engine))
            self.assertTrue(registry.resolve({"partial_image_habit": True},
                                             engine=engine)["partial_image_habit"])
            self.assertFalse(registry.resolve(None, engine=engine)["partial_image_habit"])

    def test_the_driver_records_why_it_has_no_adapter(self):
        from arrayprobe_enhancements import pipeline
        self.assertNotIn("partial_image_habit", pipeline._APPLIERS)
        reason = pipeline._NO_ADAPTER_REASON_BY_NAME["partial_image_habit"]
        self.assertIn("retrieval matrix", reason)


class OffIsByteIdentical(unittest.TestCase):
    """The module writes nothing: on or off, every port output is the bytes the port wrote."""

    def test_the_module_has_no_write_path(self):
        source = inspect.getsource(pih)
        for token in ('"w"', "'w'", '"r+"', "'r+'", "Dataset(", ".write", "to_netcdf"):
            with self.subTest(token=token):
                self.assertNotIn(token, source)

    def test_the_input_silhouettes_are_not_modified(self):
        images = [disc(5, 32, 16), disc(20, 32, 10)]
        before = [img.copy() for img in images]
        pih.classify_population(images, n_diodes=32, pixel_um=25.0)
        for a, b in zip(images, before, strict=True):
            np.testing.assert_array_equal(a, b)

    @unittest.skipUnless(IMAGE.is_file() and PROC.is_file(), "tracked demo files missing")
    def test_reading_a_flight_through_it_leaves_both_files_byte_identical(self):
        import netCDF4
        from arrayprobe.render import reconstruct_particle_image
        digest = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (IMAGE, PROC)}
        with netCDF4.Dataset(IMAGE) as image_ds, netCDF4.Dataset(PROC) as proc_ds:
            n = len(proc_ds.dimensions["time"])
            images = [reconstruct_particle_image(image_ds, proc_ds, i) for i in range(n)]
        result = pih.census(images, images[0].shape[1])
        self.assertEqual(sum(result.groups.values()), n)
        for p, h in digest.items():
            self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), h)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
