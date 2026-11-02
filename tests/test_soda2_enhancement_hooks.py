# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe_soda2.enhancement_hooks`` -- the port-side adapter surface.

A hook table that names bindings nobody calls would read fine and match nothing (the fourth
such guard on this machine would be one too many), so the central test here runs the real
driver with every point replaced by a counting pass-through and asserts each point was called,
and that routing every call through a hook moves no written value. The pristine-identity test
compares against the port's own functions by identity, captured from the *provider* module, so
its two sides come from different places even where consumer and provider coincide.
"""

from __future__ import annotations

import collections
import os
import tempfile
import unittest
from dataclasses import fields
from pathlib import Path

import numpy as np
from tests.test_soda2_process_2d import FRAME_FIXTURE, _base_op

from arrayprobe_soda2 import enhancement_hooks as hooks
from arrayprobe_soda2.process_2d import ProcessData, soda2_process_2d

_HOOKS_SRC = Path(hooks.__file__)

#: Frame fixture with the three op switches that gate the conditional points: `stuckbits`
#: (fixstuckbits), `dofreject = 3` (binary_dof), `keeplargest = 1` (label_blobs). Measured
#: 2026-09-15: with these every point in HOOK_POINTS is called at least once.
_EVERY_POINT_OP = dict(fn=str(FRAME_FIXTURE), particlefile=1, ncdfparticlefile=1,
                       stuckbits=1, dofreject=3, keeplargest=1)


def _run(op_overrides: dict, replacements: dict | None = None):
    """Run the driver into a temp dir; return (ProcessData, csv bytes, nc variables)."""
    netCDF4 = __import__("netCDF4")
    with tempfile.TemporaryDirectory() as tmp:
        op = _base_op(outdir=tmp + os.sep, **op_overrides)
        with hooks.overridden(replacements or {}):
            d = soda2_process_2d(op)
        # `pbp_writer.py:207` stamps the wall clock ("Date Processed:"); every other byte kept.
        csv = b"".join(line for p in sorted(Path(tmp).glob("*.pbp.csv"))
                       for line in p.read_bytes().splitlines(keepends=True)
                       if not line.startswith(b"Date Processed:"))
        nc: dict[str, tuple[str, np.ndarray]] = {}
        for p in sorted(Path(tmp).glob("*.pbp.nc")):
            ds = netCDF4.Dataset(str(p))
            try:
                ds.set_auto_maskandscale(False)
                for name, var in ds.variables.items():
                    nc[name] = (var.dtype.str, np.array(var[:]))
            finally:
                ds.close()
    return d, csv, nc


def _assert_processdata_equal(tc: unittest.TestCase, a, b, where: str = "data") -> None:
    """Field by field, recursing into nested dataclasses (``house``). ``op`` is compared by
    key only (it carries the temp ``outdir``); wall-clock and temp-path fields are skipped."""
    for f in fields(a):
        if f.name in ("date_processed", "pbp_csv_path", "pbp_ncdf_path"):
            continue
        va, vb = getattr(a, f.name), getattr(b, f.name)
        name = f"{where}.{f.name}"
        if isinstance(va, np.ndarray):
            tc.assertEqual(va.dtype, vb.dtype, name)
            np.testing.assert_array_equal(va, vb, err_msg=name)
        elif f.name == "op":
            tc.assertEqual(sorted(va), sorted(vb), name)
        elif hasattr(va, "__dataclass_fields__"):
            _assert_processdata_equal(tc, va, vb, name)
        else:
            tc.assertEqual(va, vb, name)


class TheTableNamesRealBindings(unittest.TestCase):
    def test_every_point_is_pristine_at_rest(self):
        self.assertTrue(all(hooks.pristine().values()), hooks.pristine())

    def test_every_consumer_binding_is_the_providers_function(self):
        import importlib
        for name, p in hooks.HOOK_POINTS.items():
            consumer = getattr(importlib.import_module(p.consumer), p.attribute)
            provider = getattr(importlib.import_module(p.provider), p.attribute)
            self.assertIs(consumer, provider, name)
            self.assertIs(hooks.original(name), provider, name)

    def test_nothing_is_active_at_rest(self):
        self.assertEqual(hooks.active(), {})


class EveryPointIsCalledByTheDriver(unittest.TestCase):
    """The discriminating test: a pass-through on every point, the real driver, counts > 0."""

    def test_every_point_is_reached_and_routing_changes_no_output(self):
        counts: collections.Counter[str] = collections.Counter()

        def passthrough(name):
            orig = hooks.original(name)

            def call(*a, **k):
                counts[name] += 1
                return orig(*a, **k)
            return call

        plain = _run(_EVERY_POINT_OP)
        routed = _run(_EVERY_POINT_OP, {n: passthrough(n) for n in hooks.HOOK_POINTS})
        self.assertEqual(sorted(n for n in hooks.HOOK_POINTS if counts[n] == 0), [],
                         f"points the driver never called: {dict(counts)}")
        self.assertIsInstance(plain[0], ProcessData)
        _assert_processdata_equal(self, plain[0], routed[0])
        self.assertGreater(len(plain[1]), 0)
        self.assertEqual(plain[1], routed[1])
        self.assertEqual(sorted(plain[2]), sorted(routed[2]))
        for name, (dtype, arr) in plain[2].items():
            self.assertEqual(dtype, routed[2][name][0], name)
            np.testing.assert_array_equal(arr, routed[2][name][1], err_msg=name)
        self.assertTrue(all(hooks.pristine().values()))

    def test_a_substitution_reaches_the_output(self):
        """The other direction: a replacement that changes its return value changes the run.
        ``soda2_findsize`` returning twice the diameter moves the ``.pbp.csv`` (every particle,
        accepted or not, is written there, so the check does not depend on acceptance)."""
        def doubled(*a, **k):
            res = hooks.original("soda2_findsize")(*a, **k)
            res.diam = res.diam * 2
            return res

        op = dict(fn=str(FRAME_FIXTURE), particlefile=1)
        plain = _run(op)[1]
        moved = _run(op, {"soda2_findsize": doubled})[1]
        self.assertGreater(len(plain), 0)
        self.assertNotEqual(plain, moved)


class RefusalsAndRestoration(unittest.TestCase):
    def test_unknown_point_is_refused(self):
        with self.assertRaises(hooks.HookError), hooks.overridden({"no_such_point": print}):
            pass

    def test_stacking_on_one_point_is_refused(self):
        with hooks.overridden({"fillholes": lambda img: img}):
            with self.assertRaises(hooks.HookError), hooks.overridden({"fillholes": print}):
                pass
            self.assertEqual(list(hooks.active()), ["fillholes"])
        self.assertTrue(all(hooks.pristine().values()))

    def test_a_binding_rebound_elsewhere_is_refused(self):
        from arrayprobe_soda2 import processbuffer_tail
        saved = processbuffer_tail.fillholes
        try:
            processbuffer_tail.fillholes = lambda img: img
            self.assertFalse(hooks.pristine()["fillholes"])
            with self.assertRaises(hooks.HookError), hooks.overridden({"fillholes": print}):
                pass
        finally:
            processbuffer_tail.fillholes = saved
        self.assertTrue(all(hooks.pristine().values()))

    def test_non_callable_is_refused(self):
        with self.assertRaises(hooks.HookError), hooks.overridden({"fillholes": 3}):
            pass

    def test_an_exception_inside_the_block_restores_every_binding(self):
        with self.assertRaises(ZeroDivisionError), hooks.overridden(
                {"fillholes": lambda img: img, "label_blobs": print}):
            _ = 1 / 0
        self.assertTrue(all(hooks.pristine().values()))
        self.assertEqual(hooks.active(), {})

    def test_empty_mapping_is_allowed(self):
        with hooks.overridden({}) as act:
            self.assertEqual(act, {})


class TheHooksModuleNamesNoEnhancementPackage(unittest.TestCase):
    """Stricter than the package-wide AST sweep (which allows a guarded import): the adapter
    surface must not mention the correction package at all, guarded or not."""

    def test_no_reference_even_guarded(self):
        text = _HOOKS_SRC.read_text(encoding="utf-8")
        code = "\n".join(line for line in text.splitlines()
                         if line.strip().startswith(("import ", "from ")))
        self.assertNotIn("enhancements", code)


if __name__ == "__main__":
    unittest.main()
