# SPDX-License-Identifier: BSD-3-Clause
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lwc import lwc_calc


class TestLwcCalc(unittest.TestCase):
    def test_single_bin_single_timestep_hand_computed(self):
        # 1 particle/cm^3 at 100 micron diameter.
        conc = [[1.0]]
        bins = [100]

        diam_cm = 100 * 1e-4  # -> 0.01 cm
        expected_lwc = 1.0 * (math.pi / 6) * diam_cm ** 3 * 1e6

        result = lwc_calc(conc, bins)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0], expected_lwc)

    def test_zero_concentration_gives_zero_lwc(self):
        conc = [[0.0, 0.0, 0.0]]
        bins = [50, 100, 200]
        result = lwc_calc(conc, bins)
        self.assertAlmostEqual(result[0], 0.0)

    def test_multi_bin_multi_timestep(self):
        conc = [
            [1.0, 2.0],
            [0.5, 0.5],
        ]
        bins = [100, 200]

        vol0 = (math.pi / 6) * (100 * 1e-4) ** 3
        vol1 = (math.pi / 6) * (200 * 1e-4) ** 3
        expected_row0 = (1.0 * vol0 + 2.0 * vol1) * 1e6
        expected_row1 = (0.5 * vol0 + 0.5 * vol1) * 1e6

        result = lwc_calc(conc, bins)
        self.assertAlmostEqual(result[0], expected_row0)
        self.assertAlmostEqual(result[1], expected_row1)

    def test_uses_full_precision_pi_not_truncated_literal(self):
        # lwc_calc.m does NOT override MATLAB's built-in pi (unlike
        # single_vt.m), so this port must use math.pi, not 3.1415926.
        # A large-diameter case makes the difference detectable.
        conc = [[1.0]]
        bins = [10000]  # large diameter to amplify the pi-precision delta
        diam_cm = 10000 * 1e-4
        truncated_pi = 3.1415926
        expected_with_truncated_pi = 1.0 * (truncated_pi / 6) * diam_cm ** 3 * 1e6
        result = lwc_calc(conc, bins)[0]
        self.assertNotEqual(result, expected_with_truncated_pi)
        expected_with_full_pi = 1.0 * (math.pi / 6) * diam_cm ** 3 * 1e6
        self.assertAlmostEqual(result, expected_with_full_pi)



class TestOneHome(unittest.TestCase):
    """``lwc_calc`` has one translation, in the v3.5 engine; ``arrayprobe.lwc`` re-exports it
    lazily, so importing the v3.1.4 module loads no v3.5 module until the name is used."""

    def test_both_engines_hold_the_same_function_object(self):
        import arrayprobe.lwc
        import arrayprobe_uiops.lwc

        self.assertIs(arrayprobe.lwc.lwc_calc, arrayprobe_uiops.lwc.lwc_calc)
        self.assertIs(lwc_calc, arrayprobe_uiops.lwc.lwc_calc)

    def test_importing_the_v314_module_defers_the_v35_import(self):
        import subprocess

        script = "\n".join([
            "import sys",
            "import arrayprobe.lwc as m",
            "assert 'arrayprobe_uiops.lwc' not in sys.modules, 'eager import'",
            "m.lwc_calc",
            "assert 'arrayprobe_uiops.lwc' in sys.modules, 'first use did not resolve'",
        ])
        done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                              timeout=120, cwd=os.path.join(os.path.dirname(__file__), ".."))
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_a_length_mismatch_still_truncates(self):
        # lwc_calc.m:6 raises on a mismatch; the port keeps zip(strict=False), unchanged.
        self.assertEqual(lwc_calc([[1.0, 2.0, 3.0]], [100.0]), lwc_calc([[1.0]], [100.0]))

if __name__ == "__main__":
    unittest.main()
