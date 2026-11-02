# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe_soda2.aspect_ratio`` against GDL running SODA-2's own
``aspect_ratio.pro`` -- unmodified where GDL can run it (F1 images with at
most two slices, F2 coordinates), shimmed where it cannot (F3 images with
more than two slices, since GDL 1.1.2 has no ``ERODE``).

The golden's every OK record is a real, end-to-end run of the real
``aspect_ratio.pro``, including its calls to the real, vendored
``min_circle_fast.pro`` -- so ``TheFinishMatchesIdlGivenIdlsCircle`` (this
module's main differential test) needs no Python port of
``min_circle_fast`` at all: it builds a circle straight from what GDL
actually returned and checks :func:`axis_and_ratio` against IDL's own
finish. Only ``WholeRoutineMatchesIdl`` (the full composition, calling this
port's own eventual ``min_circle_fast``) needs that other port, and skips
method-level until it lands.
"""
from __future__ import annotations

import ast
import inspect
import json
import math
import unittest
import warnings
from pathlib import Path
from types import SimpleNamespace

import numpy as np

import arrayprobe_soda2.aspect_ratio as ar_mod
from arrayprobe_soda2.aspect_ratio import (
    ERODE_EDGE_RULE,
    MinCircleFastNotPorted,
    aspect_ratio,
    axis_and_ratio,
    orientation_deg,
    outline_indices,
)

GOLDEN = Path(__file__).resolve().parent / "data" / "gdl_soda2_aspect_ratio_golden.json"


def _load_golden() -> list[dict]:
    if not GOLDEN.is_file():
        raise AssertionError(
            f"{GOLDEN} is missing. It is a tracked fixture: without it this "
            "suite would silently stop checking the port against IDL.")
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _ok_cases(records: list[dict]) -> list[dict]:
    return [r for r in records if r.get("status") == "OK" and r.get("family") != "F4"]


def _y_adjusted(case: dict) -> np.ndarray:
    yi = np.asarray(case["YI"], dtype=np.int64)
    tas_kind = case["tas_kind"]
    if tas_kind == "none":
        return yi.astype(np.int32)
    if tas_kind == "float":
        return (yi.astype(np.float32) * np.float32(case["tas_value"])).astype(np.float32)
    if tas_kind == "double":
        return yi.astype(np.float64) * np.float64(case["tas_value"])
    raise ValueError(tas_kind)


def _circle_from_case(case: dict) -> SimpleNamespace:
    return SimpleNamespace(
        diam=float(case["DIAM"]),
        center=np.array([case["CX"], case["CY"]], dtype=np.float64),
        corners=list(case["CORNERS"]),
    )


def _image_array(case: dict) -> np.ndarray:
    return np.asarray(case["image"], dtype=np.uint8)


def _coords_array(case: dict) -> np.ndarray:
    return np.asarray(case["coords"], dtype=np.int64)


class TheBankReachesTheDegeneracies(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = _load_golden()
        cls.by_name = {r["name"]: r for r in cls.records}

    def test_every_named_anchor_case_is_present(self):
        needed = (
            "single_pixel", "empty_image", "hline_5", "vline_5",
            "square5_outline", "square5_full", "acute_tri", "right_tri",
            "den_clamp_bites_tas025_float", "duplicate_points",
            "two_slice_tas0p1_float", "two_slice_tas0p1_double",
            "column_1x7_image",
        )
        for name in needed:
            self.assertIn(name, self.by_name, f"missing case {name!r}")

    def test_at_least_six_coords_from_port_outline_cases(self):
        n = sum(1 for r in self.records if r.get("family") == "coords_from_port_outline")
        self.assertGreaterEqual(n, 6)

    def test_at_least_eight_f3_cases(self):
        n = sum(1 for r in self.records if r.get("family") == "F3")
        self.assertGreaterEqual(n, 8)

    def test_at_least_one_two_corner_and_one_three_corner_ok_case(self):
        ok = _ok_cases(self.records)
        n2 = sum(1 for r in ok if r["NCORNERS"] == 2)
        n3 = sum(1 for r in ok if r["NCORNERS"] == 3)
        self.assertGreaterEqual(n2, 1)
        self.assertGreaterEqual(n3, 1)

    def test_at_least_one_aspr_equal_one_and_one_below_0_3(self):
        ok = _ok_cases(self.records)
        self.assertTrue(any(r["ASPR"] == 1.0 for r in ok))
        self.assertTrue(any(r["ASPR"] < 0.3 for r in ok))

    def test_tas_dtype_actually_changes_the_gdl_answer(self):
        """If these two are equal, the bank fed GDL the same value twice
        (a known float-literal trap) and the whole
        `TypesFollowIdl` class would be proving nothing."""
        a = self.by_name["two_slice_tas0p1_float"]["ASPR"]
        b = self.by_name["two_slice_tas0p1_double"]["ASPR"]
        self.assertNotEqual(a, b)


class IdlSemanticsRecorded(unittest.TestCase):
    """(A) -- needs neither GDL nor min_circle_fast at test time."""

    @classmethod
    def setUpClass(cls):
        cls.records = _load_golden()
        cls.by_name = {r["name"]: r for r in cls.records}

    def test_nan_lt_one_is_exactly_one(self):
        """S2-d: IDL's `<` returns the OTHER operand for a NaN operand --
        `!values.d_nan < 1.0d` is measured `1.0`, not NaN."""
        self.assertEqual(self.by_name["nan_lt_one"]["value"], 1.0)

    def test_find_angle_vertex_matches_gdl_float_path(self):
        """find_angle.pro as aspect_ratio.pro:33-38 calls it (FLOAT) on a
        near-collinear triangle: the port's find_angle_f32 reproduces GDL's
        angle bits and argmin vertex."""
        from arrayprobe_soda2.angles import find_angle_f32
        g = self.by_name["find_angle_vertex_near_collinear"]
        self.assertEqual(g["status"], "OK")
        self.assertEqual(g["idl_type"], 4)
        x = g["x_ind"]
        y = [np.float32(v) * np.float32(g["tas_adjust"]) for v in g["y_ind"]]
        P, Q, R = 0, 1, 2
        angs = [find_angle_f32([x[P], y[P]], [x[R], y[R]], [x[Q], y[Q]]),
                find_angle_f32([x[Q], y[Q]], [x[R], y[R]], [x[P], y[P]]),
                find_angle_f32([x[R], y[R]], [x[Q], y[Q]], [x[P], y[P]])]
        bits = [int(np.asarray(a, dtype=np.float32).view(np.uint32)) for a in angs]
        self.assertEqual(bits, g["angle_bits_f32"])
        self.assertEqual(int(np.argmin(np.asarray(angs, dtype=np.float32))), g["vertex"])

    def test_orientation_deg_matches_the_mod_grid(self):
        """48 values (7x7 minus the origin) pinning the float32 atan2/mod
        chain independent of any circle. Tolerance is float32 ulp headroom
        for libm `atan2` differences between GDL and NumPy, stated rather
        than assumed."""
        checked = 0
        for name, rec in self.by_name.items():
            if not name.startswith("mod_grid_dx"):
                continue
            got = float(orientation_deg(0, 0, rec["dx"], rec["dy"]))
            self.assertAlmostEqual(got, rec["value"], delta=2e-6,
                                    msg=f"{name}: got {got!r} want {rec['value']!r}")
            checked += 1
        self.assertEqual(checked, 48)


class OutlineAndIndexOrderMatchIdl(unittest.TestCase):
    """(A, F1 only) -- erosion-free, so this is real layer-2 evidence for
    the where-order / column-major-to-C-order convention."""

    @classmethod
    def setUpClass(cls):
        cls.records = [r for r in _load_golden()
                        if r.get("status") == "OK" and r.get("family") == "F1"]

    def test_x_ind_and_y_ind_match_idl_exactly(self):
        checked = 0
        for case in self.records:
            with self.subTest(case=case["name"]):
                img = _image_array(case)
                x_ind, y_ind, _area = outline_indices(img)
                self.assertEqual(x_ind.tolist(), case["XI"])
                self.assertEqual(y_ind.tolist(), case["YI"])
            checked += 1
        self.assertGreaterEqual(checked, 8)

    def test_empty_image_gives_the_documented_sentinel(self):
        case = next(r for r in self.records if r["name"] == "empty_image")
        self.assertEqual(case["XI"], [-1])
        self.assertEqual(case["YI"], [0])
        x_ind, y_ind, area = outline_indices(_image_array(case))
        self.assertEqual(x_ind.tolist(), [-1])
        self.assertEqual(y_ind.tolist(), [0])
        self.assertEqual(area, 0)


class OutlineUnderTheShimRule(unittest.TestCase):
    """(F3) -- layer 3 until part F confirms the real IDL ERODE border
    behaviour: this only proves the port's own erosion/xor/where pipeline
    matches its own GDL shim, run under the identical edge_rule."""

    @classmethod
    def setUpClass(cls):
        cls.records = [r for r in _load_golden()
                        if r.get("status") == "OK" and r.get("family") == "F3"]

    def test_x_ind_and_y_ind_match_the_shim_under_the_same_rule(self):
        checked = 0
        for case in self.records:
            with self.subTest(case=case["name"]):
                img = _image_array(case)
                x_ind, y_ind, _area = outline_indices(img, edge_rule=ERODE_EDGE_RULE)
                self.assertEqual(x_ind.tolist(), case["XI"])
                self.assertEqual(y_ind.tolist(), case["YI"])
            checked += 1
        self.assertGreaterEqual(checked, 8)

    def test_padded_cases_agree_under_both_edge_rules(self):
        """A pixel more than one row from every border sees the same answer
        under 'zero_outside' and 'clip_element' -- rule-independent
        evidence, unlike the unpadded family above."""
        padded = [r for r in self.records if r["name"].endswith("_padded")]
        self.assertGreaterEqual(len(padded), 4)
        for case in padded:
            with self.subTest(case=case["name"]):
                img = _image_array(case)
                x0, y0, _ = outline_indices(img, edge_rule="zero_outside")
                x1, y1, _ = outline_indices(img, edge_rule="clip_element")
                self.assertEqual(x0.tolist(), x1.tolist())
                self.assertEqual(y0.tolist(), y1.tolist())


class TheFinishMatchesIdlGivenIdlsCircle(unittest.TestCase):
    """The port's main differential test. Needs neither the erode shim's
    confirmation status nor the other pair's `min_circle_fast` -- the circle
    comes straight from what GDL's real `aspect_ratio.pro` actually returned.

    Tolerance rationale: IDL and NumPy both use correctly-rounded `sqrt` and
    the four basic operations; with identical dtypes (enforced by
    :func:`arrayprobe_soda2.aspect_ratio._idl_promote`) the `aspr` chain is
    bit-reproducible end to end, hence 1e-12 relative. `atan2` may differ by
    a libm ulp between GDL and NumPy in single precision, hence 2e-6 on
    `orientation`, in degrees.
    """

    @classmethod
    def setUpClass(cls):
        cls.records = _ok_cases(_load_golden())

    def test_aspr_and_orientation_match_idl(self):
        checked = 0
        for case in self.records:
            with self.subTest(case=case["name"]):
                if case["mode"] == "image":
                    x_ind, _y_orig, _area = outline_indices(
                        _image_array(case), edge_rule=ERODE_EDGE_RULE)
                else:
                    coords = _coords_array(case)
                    x_ind = coords[:, 0].astype(np.int32)
                y_adj = _y_adjusted(case)
                circle = _circle_from_case(case)
                aspr, orientation = axis_and_ratio(x_ind, y_adj, circle)

                want_aspr = case["ASPR"]
                rel = abs(float(aspr) - want_aspr) / max(1.0, abs(want_aspr))
                self.assertLessEqual(
                    rel, 1e-9,
                    f"{case['name']}: aspr got {aspr!r} want {want_aspr!r}")
                self.assertAlmostEqual(
                    float(orientation), case["ORIENT"], delta=2e-6,
                    msg=f"{case['name']}: orientation got {orientation!r} "
                        f"want {case['ORIENT']!r}")
            checked += 1
        self.assertGreaterEqual(checked, 30)


class TheMinMaxOperatorsAreClamps(unittest.TestCase):
    """(A) -- line 66's MAX and line 105's MIN, driven past their boundary
    rather than only tested nominally (the failure mode a same-side reading
    can pass by accident, design record V1.3)."""

    @classmethod
    def setUpClass(cls):
        cls.by_name = {r["name"]: r for r in _load_golden()}

    def test_den_clamp_changes_the_answer_from_the_unclamped_one(self):
        """S2-f: the port's clamped result must equal IDL's clamped result
        AND differ from IDL's own *unclamped* recomputation of the same
        points -- proving the clamp is live and visible, not merely present
        in the source."""
        case = self.by_name["den_clamp_bites_tas025_float"]
        unclamped = self.by_name["den_unclamped_tas025_float"]
        coords = _coords_array(case)
        x_ind = coords[:, 0].astype(np.int32)
        y_adj = _y_adjusted(case)
        circle = _circle_from_case(case)
        aspr, _orientation = axis_and_ratio(x_ind, y_adj, circle)
        self.assertAlmostEqual(float(aspr), case["ASPR"], places=9)
        self.assertNotAlmostEqual(
            float(aspr), unclamped["ASPR_UNCLAMPED"], places=6,
            msg="the clamp did not change anything -- it is not being exercised")

    def test_a_zero_diameter_with_spread_points_clamps_to_one(self):
        x_ind = np.array([0, 6, 1], dtype=np.int32)
        y_ind = np.array([0, 0, 7], dtype=np.int32)
        circle = SimpleNamespace(diam=0.0, center=np.array([2.0, 2.0]),
                                  corners=[0, 1, 2])
        aspr, _orientation = axis_and_ratio(x_ind, y_ind, circle)
        self.assertEqual(float(aspr), 1.0)

    def test_a_nonfinite_diameter_clamps_to_one_with_no_warning(self):
        x_ind = np.array([0, 6, 1], dtype=np.int32)
        y_ind = np.array([0, 0, 7], dtype=np.int32)
        circle = SimpleNamespace(diam=float("nan"), center=np.array([2.0, 2.0]),
                                  corners=[0, 1, 2])
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            aspr, _orientation = axis_and_ratio(x_ind, y_ind, circle)
        self.assertEqual(float(aspr), 1.0)


class TypesFollowIdl(unittest.TestCase):
    """(A) -- the trap this whole file exists to catch: NumPy's own
    ``int32 * float32 -> float64`` is not IDL's ``LONG*FLOAT -> FLOAT``."""

    @classmethod
    def setUpClass(cls):
        cls.by_name = {r["name"]: r for r in _load_golden()}

    def test_float32_tas_matches_the_float_golden(self):
        case = self.by_name["two_slice_tas0p1_float"]
        x_ind, _y, _a = outline_indices(_image_array(case))
        y_adj = _y_adjusted(case)
        self.assertEqual(y_adj.dtype, np.float32)
        aspr, _o = axis_and_ratio(x_ind, y_adj, _circle_from_case(case))
        self.assertAlmostEqual(float(aspr), case["ASPR"], places=9)

    def test_float64_tas_matches_the_double_golden(self):
        case = self.by_name["two_slice_tas0p1_double"]
        x_ind, _y, _a = outline_indices(_image_array(case))
        y_adj = _y_adjusted(case)
        self.assertEqual(y_adj.dtype, np.float64)
        aspr, _o = axis_and_ratio(x_ind, y_adj, _circle_from_case(case))
        self.assertAlmostEqual(float(aspr), case["ASPR"], places=9)

    def test_letting_numpy_auto_promote_gives_a_different_wrong_answer(self):
        """Mutation #5's own bug, demonstrated directly: NumPy's own
        promotion of ``a (float32) * x_ind (int32)`` -- the multiplication at
        line 68, inside :func:`axis_and_ratio` -- is ``float64``, not IDL's
        ``FLOAT``. A trivial TAS value that only ever multiplies 0/1 (as
        ``two_slice_tas0p1_float`` does) hides this completely, because
        multiplying by 0 or 1 introduces no rounding either way -- so this
        uses a synthetic case with non-trivial diode/slice indices instead,
        where the two code paths are measured to give genuinely different
        floats (found by direct measurement, not assumed)."""
        x_ind = np.array([0, 127], dtype=np.int32)
        y_int = np.array([3, 58], dtype=np.int32)
        tas = np.float32(0.1)
        y_adj = (y_int.astype(np.float32) * tas).astype(np.float32)
        circle = SimpleNamespace(diam=100.0, center=np.array([0.0, 0.0]),
                                  corners=[0, 1])

        aspr_correct, _o = axis_and_ratio(x_ind, y_adj, circle)

        # The same lines 59-73, but with NumPy's OWN promotion in place of
        # `_op`/`_idl_promote` -- exactly mutation #5.
        cx1, cy1 = x_ind[0], y_adj[0]
        cx2, cy2 = x_ind[1], y_adj[1]
        a = cy1 - cy2
        b = cx2 - cx1
        c = cx1 * cy2 - cx2 * cy1
        self.assertEqual((a * x_ind).dtype, np.float64,
                          "the trap did not manifest under this NumPy -- "
                          "re-check the promotion table before trusting the rest")
        den = np.sqrt(a ** 2 + b ** 2)
        den = den if den > 1.0 else np.float64(1.0)
        distmajor = (a * x_ind + b * y_adj + c) / den
        width = np.max(distmajor) - np.min(distmajor) + 1
        aspr_naive = width / (circle.diam + 1)
        aspr_naive = aspr_naive if aspr_naive < 1.0 else 1.0

        self.assertNotEqual(float(aspr_naive), float(aspr_correct))


class PiIsSinglePrecision(unittest.TestCase):
    """Measured (the concurrent min_circle_fast pair's finding, folded in
    here because line 53 divides by it): IDL's ``!pi`` is FLOAT
    (3.1415927410125732), never ``!dpi`` (3.141592653589793) anywhere in the
    SODA-2 tree. Measured directly here rather than assumed covered by the
    ``mod_grid`` tolerance."""

    def test_orientation_deg_would_differ_measurably_under_double_pi(self):
        dy, dx = 1.0, 0.0001
        got = float(orientation_deg(0, 0, dx, dy))

        raw_deg = math.degrees(math.atan2(dy, dx))
        wrong_with_double_pi = math.fmod(raw_deg - 360 - 90, 180) + 90

        pi32 = np.float32(np.pi)
        raw32 = np.arctan2(np.float32(dy), np.float32(dx)) * np.float32(180) / pi32
        correct = float(np.fmod(raw32 - np.float32(360) - np.float32(90),
                                 np.float32(180)) + np.float32(90))

        self.assertAlmostEqual(got, correct, places=5)
        self.assertNotAlmostEqual(got, wrong_with_double_pi, places=5,
                                   msg="orientation_deg must not be using double pi")


class VertexSelectionIsPrecisionSensitive(unittest.TestCase):
    """Measured (search over integer triangles, not from GDL): computing
    `find_angle`'s own dot-product formula in float32 vs float64 can select
    a genuinely DIFFERENT vertex at line 38's `min(...)`, which then moves
    both the axis and the aspect ratio. This demonstrates the phenomenon
    directly with the formula itself; it is deliberately NOT routed through
    :func:`axis_and_ratio` / :func:`arrayprobe_soda2.angles.find_angle`,
    because that function currently always computes in float64 internally
    (owned by the concurrent min_circle_fast pair, not edited here) -- so
    this port's *own* vertex selection for this exact triangle is currently
    the float64 answer regardless of the dtype this call site now feeds it,
    and will only pick up the float32 answer once that centralised fix
    lands. Recorded here so the dependency is explicit rather than silently
    assumed fixed.
    """

    def test_a_constructed_triangle_flips_the_argmin(self):
        p_pt, q_pt, r_pt = (35, 5), (20, 21), (4, 38)

        def angle_at(dtype):
            def fa(a, b, c):
                av = np.asarray(a, dtype=dtype)
                bv = np.asarray(b, dtype=dtype) - av
                cv = np.asarray(c, dtype=dtype) - av
                with np.errstate(invalid="ignore", divide="ignore"):
                    arg = (bv * cv).sum(dtype=dtype) / np.sqrt(
                        (bv ** 2).sum(dtype=dtype) * (cv ** 2).sum(dtype=dtype))
                return float(np.arccos(dtype(arg)))
            return [fa(p_pt, r_pt, q_pt), fa(q_pt, r_pt, p_pt), fa(r_pt, q_pt, p_pt)]

        vertex32 = int(np.argmin(angle_at(np.float32)))
        vertex64 = int(np.argmin(angle_at(np.float64)))
        self.assertNotEqual(vertex32, vertex64,
                             "the whole point of this constructed case")
        self.assertEqual(vertex32, 0)
        self.assertEqual(vertex64, 2)


class WholeRoutineMatchesIdl(unittest.TestCase):
    """(G) -- the full composed routine, including this port's own eventual
    `min_circle_fast`. Skips method-level (never in setUpClass, so it is
    never invisible from the count -- commit 5cbe506) until that lands."""

    @classmethod
    def setUpClass(cls):
        cls.records = _ok_cases(_load_golden())
        cls.by_name = {r["name"]: r for r in _load_golden()}

    def _call(self, case):
        tas_kind = case["tas_kind"]
        tas_adjust = None
        if tas_kind == "float":
            tas_adjust = np.float32(case["tas_value"])
        elif tas_kind == "double":
            tas_adjust = float(case["tas_value"])
        if case["mode"] == "image":
            return aspect_ratio(_image_array(case), tas_adjust=tas_adjust,
                                 coordinates=False, edge_rule=ERODE_EDGE_RULE)
        return aspect_ratio(_coords_array(case), tas_adjust=tas_adjust,
                             coordinates=True)

    def test_whole_routine_matches_idl(self):
        try:
            result = self._call(self.records[0])
        except MinCircleFastNotPorted:
            self.skipTest("S2-c is not distributed with the package")
        checked = 0
        for case in self.records:
            with self.subTest(case=case["name"]):
                result = self._call(case)
                self.assertAlmostEqual(float(result.aspr), case["ASPR"], places=6)
                self.assertAlmostEqual(float(result.orientation), case["ORIENT"],
                                        delta=2e-6)
            checked += 1
        self.assertGreaterEqual(checked, 30)

    def test_empty_image_is_the_single_point_early_return(self):
        case = self.by_name["empty_image"]
        try:
            result = self._call(case)
        except MinCircleFastNotPorted:
            self.skipTest("S2-c is not distributed with the package")
        self.assertEqual(float(result.aspr), 1.0)

    def test_the_y_ind_keyword_is_unadjusted(self):
        case = self.by_name["hpair_tas05_float"]
        try:
            result = self._call(case)
        except MinCircleFastNotPorted:
            self.skipTest("S2-c is not distributed with the package")
        self.assertEqual(result.y_ind.tolist(), case["YI"])


class MinCircleFastIsComposedNotRederived(unittest.TestCase):
    """(A) -- a cheap guard against re-translating `find_angle`'s (or
    `min_circle_fast`'s) own angle math here instead of importing it.
    Checked over the AST rather than the raw source text, because this
    module's own docstrings quote the IDL source line verbatim
    (``atan(float(cy2-cy1), ...)``), which would trip a plain substring
    search on a false positive."""

    def test_no_bare_atan_call_and_find_angle_is_imported(self):
        source = inspect.getsource(ar_mod)
        self.assertIn(
            "from arrayprobe_soda2.angles import find_angle", source)
        tree = ast.parse(source)
        call_names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                if isinstance(f, ast.Attribute):
                    call_names.append(f.attr)
                elif isinstance(f, ast.Name):
                    call_names.append(f.id)
        self.assertNotIn("atan", call_names)


if __name__ == "__main__":
    unittest.main()
