# SPDX-License-Identifier: BSD-3-Clause
"""IDL FLOAT transcendentals are correctly rounded; numpy's float32 kernels are not.

``arrayprobe_soda2.process_hk.f32_via_f64`` computes in float64 and rounds once.

"""
from __future__ import annotations

import ast
import inspect
import math
import pathlib
import unittest

import numpy as np
from tests._repo import needs_source

from arrayprobe_soda2 import process_hk
from arrayprobe_soda2.process_hk import f32_via_f64


def _correct(fn, x: np.float32) -> np.float32:
    return np.float32(fn(float(x)))


class TestHelper(unittest.TestCase):
    def test_equals_float32_of_float64_on_edge_values(self) -> None:
        xs = np.array([1e-38, 1e-3, 0.5, 1.0, 2.0, np.e, 10.0, 99.999, 3.4e38], np.float32)
        got = f32_via_f64(np.log, xs)
        self.assertEqual(got.dtype, np.float32)
        want = np.array([_correct(math.log, x) for x in xs], np.float32)
        np.testing.assert_array_equal(got, want)
        np.testing.assert_array_equal(
            f32_via_f64(np.exp, np.array([-50.0, 0.0, 1.0, 50.0], np.float32)),
            np.array([_correct(math.exp, np.float32(v)) for v in (-50.0, 0.0, 1.0, 50.0)],
                     np.float32))

    def test_zero_negative_and_inf_follow_numpy_float64(self) -> None:
        got = f32_via_f64(np.log, np.array([0.0, -1.0, np.inf], np.float32))
        self.assertEqual(got[0], -np.inf)
        self.assertTrue(np.isnan(got[1]))
        self.assertEqual(got[2], np.inf)

    def test_two_argument_power(self) -> None:
        got = f32_via_f64(np.power, np.float32(2.5), np.float32(1.5))
        self.assertEqual(got, np.float32(2.5 ** 1.5))


class TestProcessHkLogSite(unittest.TestCase):
    """process_hk.py's ``alog(Rt)`` (FLOAT in IDL) goes through the helper,
    and on inputs where numpy's float32 log is off, the helper is correct."""

    def test_site_routes_through_helper(self) -> None:
        src = inspect.getsource(process_hk)
        self.assertIn("lr = f32_via_f64(np.log, Rt)", src)

    def test_helper_is_correct_where_numpy_float32_log_is_not(self) -> None:
        rng = np.random.default_rng(0)
        xs = rng.uniform(1e-3, 100, 20000).astype(np.float32)
        want = np.log(xs.astype(np.float64)).astype(np.float32)
        bad = xs[np.log(xs) != want]
        if bad.size == 0:
            self.skipTest("numpy's float32 log is correctly rounded on this platform")
        np.testing.assert_array_equal(
            f32_via_f64(np.log, bad), np.array([_correct(math.log, x) for x in bad], np.float32))


_SWEPT = {"exp", "log", "log10", "sin", "cos", "tan", "arccos", "arcsin", "arctan", "power"}
_SODA2_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "arrayprobe_soda2"

# (module, enclosing function, numpy function) -> reason. Line-insensitive, so
# moving code does not fire; a new call site (or a new function holding one) does.
_ALLOWED: dict[tuple[str, str, str], str] = {
    ("angles", "find_angle", "arccos"):
        "aspect_ratio path FLOAT, ported as find_angle_f32 (commit 45964b2), measured "
        "under GDL; min_circle_fast path DOUBLE. "
        "measured under GDL 2026-10-04: find_angle.pro:7 returns DOUBLE (type 5) from "
        "min_circle_fast.pro:33 (x=double(xin) at :11) and FLOAT (type 4) from "
        "aspect_ratio.pro:33-35 (LONG x_ind, FLOAT y_ind*tas_adjust; tas_adjust=yres/xres "
        "is FLOAT at soda2_findsize.pro:30, soda2_probespecs.pro:9 res:0.0 yres:0.0, "
        "soda2.pro:572-573 cw_field /float, stretch fltarr); the angle only feeds the "
        "argmin at aspect_ratio.pro:38, so float64 differs only on a near-tie. Measured "
        "2026-10-04 (random integer triangles, 19.7M with tas_adjust in ten FLOATs): the "
        "float32 argmin differs from float64 in 7,199 (all near-collinear, e.g. x=[109,101,105] "
        "y=[10,99,54] tas 1.0: two angles tie at 0.0009765625 in float32), and 11,855 more "
        "take NaN in float32 only; GDL vertex pick on such a case not yet banked; open",
    ("angles", "find_angle_array", "arccos"):
        "double in IDL: find_angle_array.pro:4 stops unless DOUBLE; acos at :22",
    ("export_ascii", "_idl_powf", "power"): "double operand: both arguments cast to float64",
    ("export_ascii", "_idl_alog10", "log10"):
        "FLOAT input routed through float64 then rounded; the other branch is non-FLOAT input "
        "kept in its own dtype (DOUBLE alog10 in IDL)",
    ("findsize", "soda2_findsize", "arccos"):
        "double in IDL: soda2_findsize.pro:79-80, x=circle.center[0] (:73) is DOUBLE "
        "per the port (findsize.py:320-330), so x/r and s[1]-1-x promote",
    ("findsize", "soda2_findsize", "sin"):
        "double in IDL: soda2_findsize.pro:82 sin of theta/phi, DOUBLE from acos at :79-80",
    ("fit_poisson", "<module>", "log10"): "double constant log10(e)",
    ("fit_poisson", "fn_poisson", "exp"): "double operand per IDL fit_poisson.pro:31 (/double)",
    ("min_circle_fast", "min_circle_fast_traced", "arctan"):
        "double in IDL: min_circle_fast.pro:19 atan(float(b)/a); a is DOUBLE, "
        "so the quotient is DOUBLE",
    ("particlesort", "_idl_powf", "power"): "double operand: both arguments cast to float64",
    ("particlesort", "soda2_particlesort", "exp"):
        "double in IDL: soda2_particlesort.pro:98 multiplies FLOAT intcutoff by pf.a[1], "
        "a DOUBLE from lmfit(/double) at fit_poisson.pro:31, so the product is DOUBLE",
    ("spec_read_hk", "_spec_read_hk_v2", "log"): (
        "double in IDL: spec_read_hk.pro:49 rt uses 65536d, so alog(rt) at :50 is DOUBLE"),
}


def _np_transcendental_sites(source: str, module: str) -> set[tuple[str, str, str]]:
    sites: set[tuple[str, str, str]] = set()

    def walk(node: ast.AST, fn: str) -> None:
        for child in ast.iter_child_nodes(node):
            inner = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else fn
            if (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                    and isinstance(child.func.value, ast.Name)
                    and child.func.value.id in ("np", "numpy") and child.func.attr in _SWEPT):
                sites.add((module, inner, child.func.attr))
            walk(child, inner)

    walk(ast.parse(source), "<module>")
    return sites


@needs_source
class TestEveryNumpyTranscendentalIsClassified(unittest.TestCase):
    """A numpy transcendental in the SODA-2 port is either on a DOUBLE operand in
    IDL or routed through ``f32_via_f64``; a new call site fails until classified."""

    def test_sweep_equals_allow_list(self) -> None:
        found: set[tuple[str, str, str]] = set()
        for path in sorted(_SODA2_SRC.glob("*.py")):
            found |= _np_transcendental_sites(path.read_text(encoding="utf-8"), path.stem)
        self.assertGreater(len(found), 0)
        self.assertEqual(sorted(found - set(_ALLOWED)), [], "unclassified new call sites")
        self.assertEqual(sorted(set(_ALLOWED) - found), [], "stale allow-list entries")

    def test_every_entry_carries_a_reason(self) -> None:
        for key, reason in _ALLOWED.items():
            self.assertTrue(reason.strip(), key)

    def test_sweep_fires_on_a_synthetic_module(self) -> None:
        src = ("import numpy as np\n"
               "def g(x):\n    return np.sin(x) + np.exp(x)\n"
               "def h(x):\n    return f32_via_f64(np.log, x)\n")
        self.assertEqual(_np_transcendental_sites(src, "fake"),
                         {("fake", "g", "sin"), ("fake", "g", "exp")})
        self.assertFalse(_np_transcendental_sites(src, "fake") <= set(_ALLOWED))


if __name__ == "__main__":
    unittest.main()
