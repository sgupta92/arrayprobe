# SPDX-License-Identifier: BSD-3-Clause
"""Proves the "usable" half of the enhancements_uiops/port boundary: this package can see
and call arrayprobe's public API. The "removable" half -- that arrayprobe never
imports this package back -- is proven from the other side, in
tests/test_no_enhancement_coupling.py, because that check has to survive
even if this whole package is deleted.
"""

import unittest


class BoundaryTests(unittest.TestCase):
    def test_can_import_the_port_as_an_ordinary_dependency(self):
        import arrayprobe  # noqa: F401

    def test_enhancements_can_call_the_ports_public_api(self):
        # outoffocus was a raising stub until 2026-08-28; it now calls
        # arrayprobe's own reject/render functions, which is the boundary this asserts.
        import numpy as np

        from arrayprobe_enhancements import outoffocus

        np.testing.assert_array_equal(outoffocus.correct_diameter([0.2], [1.0]), [0.2])


if __name__ == "__main__":
    unittest.main()
