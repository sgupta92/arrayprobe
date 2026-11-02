# SPDX-License-Identifier: BSD-3-Clause
"""Step 3 of the stray-pixel correction (both stray-pixel rules): the batch driver's default,
opt-out, port-validation refusal and ``.call`` stamp.
"""
import unittest
from unittest import mock

from arrayprobe.driver import run_flight as rf
from arrayprobe_uiops import stray_pixel as sp


class ResolveDefault(unittest.TestCase):
    def test_engine_35_defaults_on(self):
        self.assertTrue(rf.resolve_stray_pixel("3.5"))

    def test_cli_off_is_the_opt_out(self):
        self.assertFalse(rf.resolve_stray_pixel("3.5", "off"))

    def test_config_false_is_the_opt_out(self):
        self.assertFalse(rf.resolve_stray_pixel("3.5", None, False))

    def test_cli_wins_over_config(self):
        self.assertTrue(rf.resolve_stray_pixel("3.5", "on", False))
        self.assertFalse(rf.resolve_stray_pixel("3.5", "off", True))

    def test_port_validation_is_off(self):
        self.assertFalse(rf.resolve_stray_pixel("3.1.4"))
        self.assertFalse(rf.resolve_stray_pixel("3.1.4", "off"))

    def test_port_validation_refuses_on(self):
        with self.assertRaises(ValueError):
            rf.resolve_stray_pixel("3.1.4", "on")
        with self.assertRaises(ValueError):
            rf.resolve_stray_pixel("3.1.4", None, True)


class S3PassesTheResolvedValue(unittest.TestCase):
    def test_imgproc_call_site_forwards_stray_pixel(self):
        import inspect
        src = inspect.getsource(rf)
        self.assertIn("stray_pixel_fix=STRAY_PIXEL)", src)


class Stamp(unittest.TestCase):
    def test_v35_stamp_carries_on_token(self):
        with mock.patch.object(rf, "ENGINE", "3.5"), mock.patch.object(rf, "STRAY_PIXEL", True):
            self.assertEqual(rf.stray_pixel_fragment(), f" stray_pixel={sp.STAMP_ON}")
            self.assertIn(f" stray_pixel={sp.STAMP_ON}", rf.proc_call_label())

    def test_v35_stamp_carries_off_token(self):
        with mock.patch.object(rf, "ENGINE", "3.5"), mock.patch.object(rf, "STRAY_PIXEL", False):
            self.assertIn(" stray_pixel=off", rf.proc_call_label())

    def test_v314_stamp_has_no_key(self):
        with mock.patch.object(rf, "ENGINE", "3.1.4"):
            self.assertEqual(rf.stray_pixel_fragment(), "")

    def test_old_stamp_reads_as_off(self):
        want = "engine=3.5 profile=x call=(iQC=0) stray_pixel=off software=v"
        old = "engine=3.5 profile=x call=(iQC=0) software=v"
        self.assertTrue(rf._stamps_equivalent(old, want))

    def test_old_stamp_is_stale_against_on(self):
        want = f"engine=3.5 profile=x call=(iQC=0) stray_pixel={sp.STAMP_ON} software=v"
        old = "engine=3.5 profile=x call=(iQC=0) software=v"
        self.assertFalse(rf._stamps_equivalent(old, want))

    def test_other_setting_is_refused(self):
        on = f"engine=3.5 profile=x stray_pixel={sp.STAMP_ON}"
        off = "engine=3.5 profile=x stray_pixel=off"
        self.assertFalse(rf._stamps_equivalent(on, off))
        self.assertFalse(rf._stamps_equivalent(off, on))


class CommandLine(unittest.TestCase):
    def test_flag_is_parsed_and_documented(self):
        import inspect
        src = inspect.getsource(rf)
        self.assertIn('"--stray-pixel"', src)
        self.assertIn("resolve_stray_pixel(args.engine", src)

    def test_chunk_worker_receives_the_value(self):
        import inspect
        src = inspect.getsource(rf)
        self.assertIn('jit_tail.append(f"stray_pixel=', src)
        self.assertIn('token.startswith("stray_pixel=")', src)


if __name__ == "__main__":
    unittest.main()
