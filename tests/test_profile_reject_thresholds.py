# SPDX-License-Identifier: BSD-3-Clause
"""The reject thresholds are a profile axis, and the production profile carries
the ``uioops_testing`` values that made the archived ORACLES products.

**The bug these pin.** Until 2026-08-28 ``imgproc.py`` called
``calculate_reject_unified(c, habit)`` with the module default -- the stock
thresholds -- for every profile.  On a dense ORACLES file that silently
rejected ~40% of the large particles the archived product keeps (``'i'`` from
the hollow block, which ``rej_hollow=0`` skips entirely), while the sparse
``base160906064403`` still validated exactly because it barely exercises that
block.  The fix is two-sided: the thresholds live on the profile, and the call
site is asserted to use them.
"""

from __future__ import annotations

import unittest
from unittest import mock

import numpy as np
from tests._repo import needs_v314_engine

from arrayprobe._v314_lazy import lazy_module
from arrayprobe.profiles import ORACLES_2016, ORACLES_PRODUCTION, STOCK_V314
from arrayprobe_uiops.reject_core import (
    DEFAULT_REJECT_CONFIG,
    ORACLES_PRODUCTION_REJECT_CONFIG,
)

imgproc = lazy_module("arrayprobe.imgproc")
_reject = lazy_module("arrayprobe.reject")


class ProfileCarriesRejectThresholds(unittest.TestCase):

    def test_production_profile_carries_the_uioops_testing_edits(self):
        cfg = ORACLES_PRODUCTION.reject_thresholds
        self.assertIs(cfg, ORACLES_PRODUCTION_REJECT_CONFIG)
        # uioops_testing/calculate_reject_unified.m:73, :76, :77 -- verbatim
        self.assertFalse(cfg.rej_hollow)
        self.assertEqual(cfg.max_edge_img_ar, 4)
        self.assertEqual(cfg.max_comp_img_ar, 4)

    def test_stock_and_variant_profiles_carry_the_stock_thresholds(self):
        # calculate_reject_unified.m is byte-identical between those two trees
        for prof in (STOCK_V314, ORACLES_2016):
            with self.subTest(prof.name):
                self.assertIs(prof.reject_thresholds, DEFAULT_REJECT_CONFIG)
                self.assertTrue(prof.reject_thresholds.rej_hollow)
                self.assertEqual(prof.reject_thresholds.max_edge_img_ar, 6)
                self.assertEqual(prof.reject_thresholds.max_comp_img_ar, 5)

    def test_the_two_configs_are_different_objects_with_different_values(self):
        """Guards against a refactor that makes them alias each other."""
        self.assertIsNot(DEFAULT_REJECT_CONFIG, ORACLES_PRODUCTION_REJECT_CONFIG)
        self.assertNotEqual(DEFAULT_REJECT_CONFIG, ORACLES_PRODUCTION_REJECT_CONFIG)


def _hollow_particle() -> np.ndarray:
    """A shadowed ring on a full 128-diode-wide 2D-S image (MATLAB convention:
    '0' = shadowed, '1' = lit), 14 slices long, 14 diodes wide, 3 pixels thick,
    placed within the first 32 diodes so the side-scan (which packs diodes
    1-32 only -- the upstream diode-32 hollow test) can actually see it.  Hollow by construction, so
    the hollow block has something to fire on."""
    c = np.full((14, 128), ord("1"), dtype=np.uint8)
    c[1:13, 5:19] = ord("0")
    c[4:10, 8:16] = ord("1")
    return c


@needs_v314_engine
class RejHollowGatesTheWholeHollowBlock(unittest.TestCase):
    """``calculate_reject_unified.m:278`` -- ``elseif handles.rej_hollow == 1``
    wraps everything from ``is_it_hollow`` to the ``'i'``/``'u'`` assignments;
    with it off, execution falls through to ``reject_status = '0'`` (``:369``)."""

    def test_hollow_particle_is_accepted_plain_under_production_config(self):
        r = _reject.calculate_reject_unified(_hollow_particle(), "h",
                                     ORACLES_PRODUCTION_REJECT_CONFIG)
        self.assertEqual(r.reject_status, "0")

    def test_same_particle_enters_the_hollow_block_under_stock_config(self):
        r = _reject.calculate_reject_unified(_hollow_particle(), "h", DEFAULT_REJECT_CONFIG)
        # Any hollow-block outcome; the point is that the block RAN.
        self.assertIn(r.reject_status, set("HhiuR"))


@needs_v314_engine
class ImgprocPassesTheProfileConfig(unittest.TestCase):
    """The call site must forward the profile's thresholds -- the exact thing
    that was missing.  Spied rather than inferred from output, so a future
    regression to the module default fails by name."""

    def _describe_with(self, profile):
        seen = {}
        real = imgproc.calculate_reject_unified

        def spy(c, habit, config=None):
            seen["config"] = config
            return real(c, habit, config)

        acc = mock.MagicMock()
        diode_stats = np.zeros(128)
        with mock.patch.object(imgproc, "calculate_reject_unified", spy):
            try:
                imgproc._describe_particle(acc, 0, _hollow_particle(), 128, 0.010,
                                           diode_stats, profile, 0)
            except Exception:
                # Downstream sizing on a MagicMock accumulator may raise;
                # the reject call has already happened by then.
                pass
        return seen.get("config")

    def test_production_profile_reaches_the_reject_call(self):
        self.assertIs(self._describe_with(ORACLES_PRODUCTION),
                      ORACLES_PRODUCTION_REJECT_CONFIG)

    def test_stock_profile_reaches_the_reject_call(self):
        self.assertIs(self._describe_with(STOCK_V314), DEFAULT_REJECT_CONFIG)


if __name__ == "__main__":
    unittest.main()
