# SPDX-License-Identifier: BSD-3-Clause
"""The registry guard restores the shipped profile set after every registering import.

Importing ``arrayprobe_uiops.register_image_assisted`` (as ``test_paper_numbers``'s
stamp-example class does, through ``register_stock_v35_image_assisted()``) used to add
``stock-v3.5-image-assisted`` to the live ``PROFILES`` for the rest of the process.
These tests run the registrations in-process and assert the helper removes them, and
that a later import registers again rather than being a cached no-op.
"""

from __future__ import annotations

import importlib
import importlib.util
import io
import unittest

from tests._profile_registry_guard import (  # noqa: E402
    REGISTERING_MODULES,
    preserved,
)
from tests._repo import needs_file  # noqa: E402

from arrayprobe import profiles  # noqa: E402


def _present_registering_modules() -> list[str]:
    """The registering modules this distribution ships; the ARM ENA one is development-only."""
    out = []
    for m in REGISTERING_MODULES:
        try:
            if importlib.util.find_spec(m) is not None:
                out.append(m)
        except (ImportError, ValueError):
            pass
    return out


def _names() -> list[str]:
    return sorted(profiles.PROFILES)


class RegisteringImportsDoNotLeak(unittest.TestCase):
    def test_every_registering_module_is_undone(self):
        before = _names()
        before_v35 = set(profiles._V35_TREE_PROFILES)
        with preserved():
            present = _present_registering_modules()
            # Absent modules are left out of the sweep rather than the test skipped, so the
            # guard still runs on every module the distribution does ship.
            self.assertIn("arrayprobe_uiops.register_image_assisted", present)
            for m in present:
                importlib.import_module(m)
            self.assertIn("stock-v3.5-image-assisted", profiles.PROFILES)
            if "arrayprobe_uiops.register_arm_stock" in present:
                self.assertIn("arm-ena-stock-v3.5", profiles.PROFILES)
        self.assertEqual(_names(), before)
        self.assertEqual(set(profiles._V35_TREE_PROFILES), before_v35)

    def test_a_later_import_registers_again(self):
        with preserved():
            importlib.import_module("arrayprobe_uiops.register_image_assisted")
        with preserved():
            importlib.import_module("arrayprobe_uiops.register_image_assisted")
            self.assertIn("stock-v3.5-image-assisted", profiles.PROFILES)

    @needs_file("tests/test_paper_numbers.py")
    def test_paper_numbers_stamp_class_leaves_the_shipped_set(self):
        """Run test_paper_numbers' registering class in this process, then check."""
        from tests import test_paper_numbers as tpn

        before = _names()
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(
            tpn.TheStampInThePaperIsOneTheDriverWrites)
        unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
        self.assertEqual(_names(), before)
        self.assertNotIn("stock-v3.5-image-assisted", profiles.PROFILES)

    def test_registry_now_equals_the_shipped_set(self):
        """Whatever ran before this module in the process, nothing is left registered."""
        self.assertEqual(_names(), sorted(profiles.SHIPPED))


if __name__ == "__main__":
    unittest.main()
