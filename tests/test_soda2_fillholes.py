# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe_soda2.fillholes`` against GDL running SODA-2's own
`fillholes.pro` + `label_blobs.pro` end to end, plus an independent
flood-fill cross-check.

**Stub for ``label_blobs``.** This file and ``label_blobs.py``'s port
were written at the same time; ``label_blobs`` may
not exist in this worktree yet. If it is absent, a minimal 4-connected
two-pass labeller matching the geometry port's coordinator-relayed signature
(``label_blobs(img, dilatelength=0, all_neighbors=False, integer=False)``)
is installed into ``sys.modules`` before ``fillholes`` is imported, so this
suite is always collectible. **When the real module is present, the stub
is never installed** -- the GDL golden (produced by the real
``fillholes.pro`` calling the real ``label_blobs.pro``) then adjudicates
the geometry port *through these tests*, and the coordinator reruns this file
after the merge to confirm.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

import numpy as np

GOLDEN = Path(__file__).resolve().parent / "data" / "gdl_soda2_fillholes_golden.json"

_STUB_IN_USE = importlib.util.find_spec("arrayprobe_soda2.label_blobs") is None

if _STUB_IN_USE:
    import types

    print("test_soda2_fillholes: arrayprobe_soda2.label_blobs not found -- "
          "installing a test stub (4-connected two-pass labeller). The GDL "
          "golden then adjudicates only through this stub, not S2's port.")

    def _stub_label_blobs(img, dilatelength=0, all_neighbors=False, integer=False):
        if dilatelength != 0 or all_neighbors:
            raise NotImplementedError(
                "test stub: only the keyword-less call used by fillholes.pro:9 "
                "is implemented")
        arr = np.asarray(img, dtype=np.uint8)
        labels = np.zeros(arr.shape, dtype=np.int32)
        next_label = 1
        # first-encounter numbering in C-order = IDL memory order on the
        # (roilen, ndiodes) array (this package's transpose of [ndiodes,
        # roilen]).
        parent: dict[int, int] = {}

        def find(x: int) -> int:
            while parent.get(x, x) != x:
                x = parent[x]
            return x

        def union(a: int, b: int) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)

        for r in range(arr.shape[0]):
            for c in range(arr.shape[1]):
                if arr[r, c] == 0:
                    continue
                neighbors = []
                if r > 0 and arr[r - 1, c] and labels[r - 1, c] > 0:
                    neighbors.append(int(labels[r - 1, c]))
                if c > 0 and arr[r, c - 1] and labels[r, c - 1] > 0:
                    neighbors.append(int(labels[r, c - 1]))
                if neighbors:
                    lbl = min(neighbors)
                    labels[r, c] = lbl
                    for n in neighbors:
                        union(lbl, n)
                else:
                    labels[r, c] = next_label
                    parent[next_label] = next_label
                    next_label += 1

        # resolve unions, then renumber compactly by first-encounter order.
        resolved = np.zeros(arr.shape, dtype=np.int32)
        remap: dict[int, int] = {}
        counter = 1
        for r in range(arr.shape[0]):
            for c in range(arr.shape[1]):
                if labels[r, c] == 0:
                    continue
                root = find(int(labels[r, c]))
                if root not in remap:
                    remap[root] = counter
                    counter += 1
                resolved[r, c] = remap[root]

        if integer:
            return resolved
        return (resolved % 256).astype(np.uint8)  # label_blobs.pro:28's wrap

    _stub_module = types.ModuleType("arrayprobe_soda2.label_blobs")
    _stub_module.label_blobs = _stub_label_blobs
    sys.modules["arrayprobe_soda2.label_blobs"] = _stub_module

from arrayprobe_soda2.fillholes import _labelled_negative, fillholes  # noqa: E402


def _image_from_dims_and_string(dims: str, out: str, ndiodes: int, nslices: int) -> np.ndarray:
    """GDL prints `OUT` as `strjoin(string(reform(out, n_elements(out))))`,
    IDL column-major flattening of the `[ndiodes, roilen]` array -- i.e.
    diode fastest, slice slowest. Rebuild the `(nslices, ndiodes)` (this
    package's `(roilen, ndiodes)`) array from that flat string."""
    flat = np.array([int(ch) for ch in out], dtype=np.uint8)
    # IDL column-major over [ndiodes, nslices]: element (d, s) at index
    # d + s*ndiodes -- exactly a reshape with diode fastest.
    return flat.reshape(nslices, ndiodes)


def _flood_fill_holes(arr: np.ndarray) -> np.ndarray:
    """Independent third side: BFS from every border zero pixel,
    4-connected, over the background; whatever zero pixel is neither
    particle nor border-reachable is a hole, filled."""
    from collections import deque

    nrows, ncols = arr.shape
    reachable = np.zeros(arr.shape, dtype=bool)
    q: deque[tuple[int, int]] = deque()
    for r in range(nrows):
        for c in (0, ncols - 1):
            if arr[r, c] == 0 and not reachable[r, c]:
                reachable[r, c] = True
                q.append((r, c))
    for c in range(ncols):
        for r in (0, nrows - 1):
            if arr[r, c] == 0 and not reachable[r, c]:
                reachable[r, c] = True
                q.append((r, c))
    while q:
        r, c = q.popleft()
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nr, nc = r + dr, c + dc
            if 0 <= nr < nrows and 0 <= nc < ncols:
                if arr[nr, nc] == 0 and not reachable[nr, nc]:
                    reachable[nr, nc] = True
                    q.append((nr, nc))
    filled = arr.copy()
    filled[(arr == 0) & (~reachable)] = 1
    return filled


class AgainstTheGdlGolden(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not GOLDEN.is_file():
            raise AssertionError(
                f"{GOLDEN} is missing. It is a tracked fixture: without it "
                "this suite would silently stop checking the port against GDL.")
        cls.cases = json.loads(GOLDEN.read_text(encoding="utf-8"))

    def test_the_bank_has_enough_cases(self):
        self.assertGreaterEqual(len(self.cases), 10)

    def test_the_bank_reaches_the_named_regimes(self):
        names = {c["name"] for c in self.cases}
        for needed in ("many_holes", "diagonal_gap", "single_slice"):
            self.assertIn(needed, names)

    def test_column_major_flattening_convention(self):
        # 2x3 (ndiodes=2, nslices=3) sanity check of the IDL flattening
        # mapping used by `_image_from_dims_and_string`.
        img = np.zeros((3, 2), dtype=np.uint8)
        img[0, 0] = 1  # slice 0, diode 0
        img[1, 1] = 1  # slice 1, diode 1
        # IDL column-major flat: d0s0, d1s0, d0s1, d1s1, d0s2, d1s2
        expected = "100100"
        flat = img.reshape(6)  # (nslices, ndiodes) reshape == same order
        self.assertEqual("".join(str(int(v)) for v in flat), expected)

    def test_every_ok_case_reports_byte_output(self):
        # `fillholes.pro` returns BYTE unconditionally (`:5`, `:21`); the
        # golden-vs-port array equality itself is asserted in
        # `AgainstTheBankCasesDirectly` below, which rebuilds the exact
        # pixel sets the bank used (never duplicating that geometry here).
        checked = 0
        for case in self.cases:
            if case["status"] != "OK":
                continue
            with self.subTest(case=case["name"]):
                self.assertEqual(case["TNAME"], "BYTE")
            checked += 1
        self.assertGreaterEqual(checked, 10)


def _pixels_for_case(name: str):
    """Re-derive the exact pixel set the bank used for `name`, by importing
    the bank's own case builders (never duplicating the geometry here)."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "validation" / "gdl"))
    import run_soda2_fillholes_bank as bank
    return bank.CASES[name]


class AgainstTheBankCasesDirectly(unittest.TestCase):
    """Rebuilds each bank case's exact pixel set (via the bank module
    itself) and compares the port's flattened output against `OUT`."""

    @classmethod
    def setUpClass(cls):
        cls.cases = {c["name"]: c for c in json.loads(GOLDEN.read_text(encoding="utf-8"))}

    def test_matches_every_ok_case(self):
        checked = 0
        for name, rec in self.cases.items():
            if rec["status"] != "OK":
                continue
            ndiodes, nslices, pixels = _pixels_for_case(name)
            with self.subTest(case=name):
                img = np.zeros((nslices, ndiodes), dtype=np.uint8)
                for d, s in pixels:
                    img[s, d] = 1
                out = fillholes(img)
                self.assertEqual(out.dtype, np.uint8)
                self.assertEqual(out.shape, (nslices, ndiodes))
                # IDL column-major flatten of [ndiodes, nslices] == this
                # array's own row-major flatten (diode fastest already).
                flat = "".join(str(int(v)) for v in out.reshape(-1))
                self.assertEqual(flat, rec["OUT"], name)
                self.assertEqual(float(out.sum()), float(rec["AREA_FILLED"]), name)
            checked += 1
        self.assertGreaterEqual(checked, 10)


class TheThirdSideFloodFill(unittest.TestCase):
    """For every OK case with <=255 labels, an independent flood-fill from
    the border must equal the port's output. For `many_holes` (>255
    labels) it must **differ**, exactly where the wrapped labels sit --
    S4-u demonstrated two ways."""

    def test_flood_fill_agrees_below_256_labels_and_differs_above(self):
        cases = {c["name"]: c for c in json.loads(GOLDEN.read_text(encoding="utf-8"))}
        for name in ("ring", "ring_open", "diagonal_gap", "two_holes",
                      "particle_on_all_edges", "no_particle", "many_holes_255"):
            rec = cases[name]
            if rec["status"] != "OK":
                continue
            ndiodes, nslices, pixels = _pixels_for_case(name)
            img = np.zeros((nslices, ndiodes), dtype=np.uint8)
            for d, s in pixels:
                img[s, d] = 1
            port_out = fillholes(img)
            flood_out = _flood_fill_holes(img)
            with self.subTest(case=name):
                self.assertTrue(np.array_equal(port_out, flood_out), name)

        rec = cases["many_holes"]
        ndiodes, nslices, pixels = _pixels_for_case("many_holes")
        img = np.zeros((nslices, ndiodes), dtype=np.uint8)
        for d, s in pixels:
            img[s, d] = 1
        port_out = fillholes(img)
        flood_out = _flood_fill_holes(img)
        diff = port_out != flood_out
        self.assertTrue(diff.any(),
                         "many_holes: expected the port to disagree with an "
                         "unbounded (no label cap) flood-fill oracle at the "
                         "wrapped label(s)")
        # And the golden (real GDL fillholes+label_blobs) agrees with the
        # port, not with the flood-fill, at those pixels.
        flat_port = "".join(str(int(v)) for v in port_out.reshape(-1))
        self.assertEqual(flat_port, rec["OUT"])


class PinnedSemantics(unittest.TestCase):
    def test_small_images_are_returned_unchanged_as_uint8(self):
        for shape in ((3, 8), (8, 3), (1, 8)):
            img = np.zeros(shape, dtype=np.uint8)
            img[0, 0] = 1
            out = fillholes(img)
            self.assertEqual(out.dtype, np.uint8)
            self.assertTrue(np.array_equal(out, img.astype(np.uint8)))

    def test_labels_wrap_at_256(self):
        ndiodes, nslices, pixels = _pixels_for_case("many_holes")
        img = np.zeros((nslices, ndiodes), dtype=np.uint8)
        for d, s in pixels:
            img[s, d] = 1
        labelled = _labelled_negative(img)
        self.assertEqual(labelled.dtype, np.uint8)
        self.assertLessEqual(int(labelled.max()), 255)
        if _STUB_IN_USE:
            import arrayprobe_soda2.label_blobs as lb
            neg = img ^ np.uint8(1)
            n_labels = int(lb.label_blobs(neg, integer=True).max())
            self.assertGreater(n_labels, 255)

    def test_removal_is_by_label_identity_so_order_is_irrelevant(self):
        ndiodes, nslices, pixels = _pixels_for_case("ring")
        img = np.zeros((nslices, ndiodes), dtype=np.uint8)
        for d, s in pixels:
            img[s, d] = 1
        reverse = _labelled_negative(img)
        edges = np.concatenate([reverse[:, 0], reverse[0, :],
                                 reverse[:, -1], reverse[-1, :]])
        self.assertEqual(set(np.unique(edges).tolist()),
                          set(sorted(set(edges.tolist()))))


if __name__ == "__main__":
    unittest.main()
