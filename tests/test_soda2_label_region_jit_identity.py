# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe_soda2.label_blobs.label_blobs(..., jit=True)`` vs the default
(``jit=False``) path -- byte identity, never a tolerance comparison
(``np.array_equal`` / ``tobytes()``), plus mutation tests proving that
comparison actually discriminates a broken kernel rather than passing
vacuously.

Space: the port (``src/arrayprobe_soda2/jit_kernels.py``,
``label_blobs.py``'s new ``jit=`` parameter).
The one kernel ported is
``label_blobs._label_region``, and
``jit_kernels.py``'s own module docstring for why an array-backed
flood-fill stack cannot change the result versus the reference's
list-of-tuples stack.

Run standalone: ``PYTHONPATH=tests .venv/Scripts/python.exe -m unittest
tests.test_soda2_label_region_jit_identity -v`` from the repository root.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np

from arrayprobe_soda2 import jit_kernels
from arrayprobe_soda2.label_blobs import _label_region, label_blobs

GOLDEN = Path(__file__).resolve().parent / "data" / "gdl_soda2_label_blobs_golden.json"


def _require_numba() -> None:
    try:
        import numba  # noqa: F401
    except ImportError as exc:
        raise unittest.SkipTest(
            "numba not installed; label_blobs(jit=True) is untestable "
            "without it (the default jit=False path is unaffected)."
        ) from exc


class ByteIdenticalToTheDefaultPath(unittest.TestCase):
    """label_blobs(img, jit=True, ...) must return the exact same array,
    element for element and byte for byte, as label_blobs(img, jit=False,
    ...) on the same arguments -- never ``np.allclose``, this is an integer
    kernel with no floating point in it at all."""

    @classmethod
    def setUpClass(cls):
        _require_numba()

    def _assert_identical(self, img, **kwargs):
        ref = label_blobs(img, jit=False, **kwargs)
        got = label_blobs(img, jit=True, **kwargs)
        self.assertEqual(ref.shape, got.shape)
        self.assertEqual(ref.dtype, got.dtype)
        self.assertTrue(
            np.array_equal(ref, got),
            f"jit=True disagreed with jit=False for kwargs={kwargs}\n"
            f"ref=\n{ref}\ngot=\n{got}")
        self.assertEqual(ref.tobytes(), got.tobytes())

    def test_random_images_4_and_8_connected_both_integer_modes(self):
        rng = np.random.default_rng(20260918)
        for trial in range(60):
            shape = tuple(int(v) for v in rng.integers(1, 60, size=2))
            density = rng.uniform(0.05, 0.6)
            img = (rng.random(shape) < density).astype(np.uint8)
            for all_n in (False, True):
                for integer in (False, True):
                    with self.subTest(trial=trial, shape=shape,
                                       all_n=all_n, integer=integer):
                        self._assert_identical(
                            img, all_neighbors=all_n, integer=integer)

    def test_dilation_path_dilatelength_1_2_3(self):
        rng = np.random.default_rng(7)
        for trial in range(20):
            shape = tuple(int(v) for v in rng.integers(2, 30, size=2))
            img = (rng.random(shape) < 0.3).astype(np.uint8)
            for dl in (1, 2, 3):
                for all_n in (False, True):
                    with self.subTest(trial=trial, dl=dl, all_n=all_n):
                        self._assert_identical(
                            img, dilatelength=dl, all_neighbors=all_n)

    def test_real_call_shapes_from_processbuffer_tail(self):
        """processbuffer_tail.py:253-257's three actual call patterns:
        keeplargest 1 (dilatelength=2), 2 (dilatelength=1), 3 (dilatelength=0,
        all_neighbors=True), on a multi-slice ROI-shaped image."""
        rng = np.random.default_rng(42)
        img = (rng.random((80, 24)) < 0.25).astype(np.uint8)  # (roilen, ndiodes)-ish
        self._assert_identical(img, dilatelength=2)
        self._assert_identical(img, dilatelength=1)
        self._assert_identical(img, dilatelength=0, all_neighbors=True)

    def test_one_d_input(self):
        img = np.array([0, 1, 1, 0, 1, 1, 1, 0, 0, 1], dtype=np.uint8)
        self._assert_identical(img)
        self._assert_identical(img, integer=True)

    def test_all_zero_and_all_one(self):
        self._assert_identical(np.zeros((10, 10), dtype=np.uint8))
        self._assert_identical(np.ones((10, 10), dtype=np.uint8))

    def test_single_pixel(self):
        img = np.zeros((5, 5), dtype=np.uint8)
        img[2, 3] = 1
        self._assert_identical(img)

    def test_border_pixels_all_four_corners(self):
        img = np.zeros((6, 6), dtype=np.uint8)
        img[0, 0] = 1
        img[-1, -1] = 1
        img[0, -1] = 1
        img[-1, 0] = 1
        self._assert_identical(img)
        self._assert_identical(img, all_neighbors=True)

    def test_diagonal_only_connectivity_4_vs_8(self):
        img = np.zeros((4, 4), dtype=np.uint8)
        img[1, 1] = 1
        img[2, 2] = 1  # touches (1,1) only diagonally
        self._assert_identical(img, all_neighbors=False)
        self._assert_identical(img, all_neighbors=True)

    def test_byte_wrap_at_256_blobs(self):
        # Same construction as test_soda2_label_blobs.py's ByteWrapAt256,
        # run through the jit path: 300 isolated single-pixel blobs, so the
        # uint8 (integer=False) return wraps modulo 256 (S4-y) -- a large
        # enough label count that a kernel bug in next_label bookkeeping
        # would very likely show up here.
        n = 300
        img = np.zeros((2 * n, 1), dtype=np.uint8)
        for i in range(n):
            img[2 * i, 0] = 1
        self._assert_identical(img)
        self._assert_identical(img, integer=True)

    def test_gdl_golden_cases(self):
        """Every OK case in the GDL golden bank
        (test_soda2_label_blobs.py's own fixture), run through both paths."""
        if not GOLDEN.is_file():
            self.skipTest(f"{GOLDEN} is not distributed with the package")
        records = json.loads(GOLDEN.read_text(encoding="utf-8"))
        checked = 0
        for case in records:
            if case["status"] != "OK":
                continue
            img = np.asarray(case["img"], dtype=np.int32)
            with self.subTest(case=case["name"]):
                self._assert_identical(
                    img,
                    dilatelength=case["dilatelength"],
                    all_neighbors=case["all_neighbors"],
                    integer=case["integer"],
                )
            checked += 1
        self.assertGreaterEqual(checked, 10)


class CompiledKernelAgainstThePurePythonReference(unittest.TestCase):
    """arrayprobe_soda2.jit_kernels.JitKernels.label_region called directly
    (bypassing label_blobs' padding wrapper) against label_blobs._label_region
    directly, on padded arrays shaped exactly the way label_blobs itself
    builds them ([y, x] convention, per _label_region's own docstring)."""

    @classmethod
    def setUpClass(cls):
        _require_numba()
        cls.kernels = jit_kernels.load()

    def test_direct_call_matches_on_padded_arrays(self):
        rng = np.random.default_rng(99)
        for trial in range(30):
            shape = tuple(int(v) for v in rng.integers(3, 25, size=2))
            temp = (rng.random(shape) < 0.35).astype(np.uint8)
            for all_n in (False, True):
                ref = _label_region(temp, all_n)
                got = self.kernels.label_region(temp, all_n)
                self.assertEqual(ref.dtype, got.dtype)
                self.assertTrue(np.array_equal(ref, got), (trial, shape, all_n))
                self.assertEqual(ref.tobytes(), got.tobytes())

    def test_non_integer_dtype_falls_back_and_still_matches(self):
        """A 2-D ``bool`` array exercises the ``dtype.kind not in "iu"``
        guard (the same guard shape ``particle_perimeter`` uses in
        ``arrayprobe/jit_kernels.py``): ``label_region`` routes it to the
        pure Python reference instead of the compiled kernel. Confirmed by
        hand first (bool is not in "iu", and ``_label_region`` itself
        handles a bool array fine -- ``temp[y, x] == 0`` and indexing both
        work on it), rather than assumed: a genuinely 1-D input was tried
        here first and found to raise inside the reference itself
        (``ny, nx = temp.shape`` on a 1-tuple shape) -- expected, since
        ``_label_region`` documents a 2-D contract and label_blobs() never
        calls it otherwise (:123-125 reshapes first), so that is not a
        meaningful case to assert byte identity over."""
        rng = np.random.default_rng(123)
        temp = rng.random((10, 8)) < 0.4  # dtype bool, kind 'b'
        self.assertEqual(temp.dtype.kind, "b")
        ref = _label_region(temp, False)
        got = self.kernels.label_region(temp, False)
        self.assertEqual(ref.dtype, got.dtype)
        self.assertTrue(np.array_equal(ref, got))
        self.assertEqual(ref.tobytes(), got.tobytes())


class MutationsProveTheComparisonIsNotVacuous(unittest.TestCase):
    """Two one-unit breaks of the kernel body, each written locally here
    (jit_kernels.py itself is never edited), each disagreeing with the
    trusted reference on a case built to require exactly the broken piece.
    If either assertion below ever passed by accident, the byte-identity
    tests above would not be trustworthy."""

    def test_raster_order_swap_breaks_identity(self):
        """label_blobs.py's own docstring: labels are assigned in "raster
        order (x fastest, then y)". Swapping the loop nesting so y is
        fastest instead is a one-line mutation that silently reassigns
        which blob gets which label id -- caught only by a real
        element-wise/byte comparison, not by a partition-only check."""

        def _y_fastest_kernel(temp: np.ndarray, all_neighbors: bool) -> np.ndarray:
            ny, nx = temp.shape
            labels = np.zeros((ny, nx), dtype=np.uint32)
            next_label = 1
            neighbours = (
                [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
                if all_neighbors else [(-1, 0), (1, 0), (0, -1), (0, 1)]
            )
            for x in range(nx):           # mutated: x slowest, y fastest
                for y in range(ny):        # (reference has y outer, x inner)
                    if temp[y, x] == 0 or labels[y, x] != 0:
                        continue
                    stack = [(y, x)]
                    labels[y, x] = next_label
                    while stack:
                        cy, cx = stack.pop()
                        for dy, dx in neighbours:
                            ny_, nx_ = cy + dy, cx + dx
                            if (0 <= ny_ < ny and 0 <= nx_ < nx
                                    and temp[ny_, nx_] != 0
                                    and labels[ny_, nx_] == 0):
                                labels[ny_, nx_] = next_label
                                stack.append((ny_, nx_))
                    next_label += 1
            return labels

        # Two isolated single pixels, positioned so x-fastest and y-fastest
        # scans reach them in opposite order: temp is [y, x] = (2, 6).
        temp = np.zeros((2, 6), dtype=np.uint8)
        temp[0, 5] = 1
        temp[1, 0] = 1

        correct = _label_region(temp, False)
        broken = _y_fastest_kernel(temp, False)

        self.assertEqual(int(correct[0, 5]), 1)
        self.assertEqual(int(correct[1, 0]), 2)
        self.assertEqual(int(broken[1, 0]), 1)
        self.assertEqual(int(broken[0, 5]), 2)
        self.assertFalse(
            np.array_equal(correct, broken),
            "the y-fastest mutant must disagree with the reference -- if it "
            "did not, the byte-identity assertions above would be testing "
            "nothing.")
        self.assertNotEqual(correct.tobytes(), broken.tobytes())

    def test_dropped_neighbour_offset_breaks_identity(self):
        """Dropping the east offset from the 4-connected neighbour set is a
        one-entry change that silently splits a connected horizontal run
        into several separate blobs."""

        def _label_region_missing_east(temp, all_neighbors):
            ny, nx = temp.shape
            labels = np.zeros((ny, nx), dtype=np.uint32)
            next_label = 1
            neighbours = [(-1, 0), (1, 0), (0, -1)]  # (0, 1) east dropped
            for y in range(ny):
                for x in range(nx):
                    if temp[y, x] == 0 or labels[y, x] != 0:
                        continue
                    stack = [(y, x)]
                    labels[y, x] = next_label
                    while stack:
                        cy, cx = stack.pop()
                        for dy, dx in neighbours:
                            ny_, nx_ = cy + dy, cx + dx
                            if (0 <= ny_ < ny and 0 <= nx_ < nx
                                    and temp[ny_, nx_] != 0
                                    and labels[ny_, nx_] == 0):
                                labels[ny_, nx_] = next_label
                                stack.append((ny_, nx_))
                    next_label += 1
            return labels

        # A single horizontal run of 4 pixels: 4-connected, this is one
        # blob; scanned left to right with "east" missing, each pixel to
        # the right of the first is only ever discoverable through its own
        # west neighbour once *it* becomes the seed of a fresh blob, so the
        # run fragments into four separate labels.
        temp = np.zeros((3, 6), dtype=np.uint8)
        temp[1, 1:5] = 1

        correct = _label_region(temp, False)
        broken = _label_region_missing_east(temp, False)

        self.assertEqual(len(set(correct[correct != 0].tolist())), 1)
        self.assertEqual(
            len(set(broken[broken != 0].tolist())), 4,
            "the dropped-east mutant should fragment the run into four "
            "singleton blobs; if it did not, this case does not exercise "
            "the missing offset.")
        self.assertFalse(np.array_equal(correct, broken))
        self.assertNotEqual(correct.tobytes(), broken.tobytes())


if __name__ == "__main__":
    unittest.main()
