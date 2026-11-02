# SPDX-License-Identifier: BSD-3-Clause
"""``load_config`` reports every problem in a file at once, and names the file.

Before 2026-10-01 a config with three mistakes took three runs to clear: the loader raised at
the first one. It now collects the independent problems into one :class:`ConfigError`, whose
first line is today's text for the first problem plus the file's path, with the rest numbered
below and the list on ``.problems``. A check whose input an earlier problem already broke is
skipped rather than reported, and an error raised before the file could be read (bad TOML,
wrong encoding, a directory) stays immediate (slice A).

"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arrayprobe.config import ConfigDecodeError, ConfigError, load_config

_GOOD_FIDELITY = '[fidelity]\nprofile = "STOCK_V314"\n'


class _Files(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def _refused(self, text: str) -> ConfigError:
        path = self.root / "run.toml"
        path.write_text(text, encoding="utf-8")
        self.path = path
        with self.assertRaises(ConfigError) as cm:
            load_config(path)
        return cm.exception


class TestEveryProblemIsReported(_Files):
    def test_three_independent_problems_are_all_reported(self):
        exc = self._refused(_GOOD_FIDELITY + '[export]\nformat = "HDF5"\n'
                            '[enhancements]\nx = 1\n[run]\nbogus = 1\n')
        msg = str(exc)
        self.assertIn("[export].format must be NETCDF3_CLASSIC or NETCDF4", msg)
        self.assertIn("[enhancements].x must be true/false (opt-in)", msg)
        self.assertIn("[run] has unknown key(s) ['bogus']", msg)
        self.assertEqual(len(exc.problems), 3)
        self.assertIn("3 problems", msg)

    def test_the_first_problem_leads_and_the_file_is_named(self):
        exc = self._refused(_GOOD_FIDELITY + '[export]\nformat = "HDF5"\n[run]\nbogus = 1\n')
        self.assertTrue(str(exc).startswith(
            "[export].format must be NETCDF3_CLASSIC or NETCDF4, got 'HDF5'"), str(exc))
        self.assertIn(str(self.path), str(exc).splitlines()[0])
        self.assertEqual(exc.problems[0],
                         "[export].format must be NETCDF3_CLASSIC or NETCDF4, got 'HDF5'")

    def test_one_problem_names_the_file(self):
        exc = self._refused(_GOOD_FIDELITY + "[run]\nbogus = 1\n")
        self.assertTrue(str(exc).endswith(f"(in {self.path})"), str(exc))
        self.assertEqual(len(exc.problems), 1)
        self.assertNotIn("\n", str(exc))


class TestDependentChecksAreSkipped(_Files):
    def test_a_consequence_is_not_reported(self):
        exc = self._refused(_GOOD_FIDELITY + '[export]\nformat = "HDF5"\n'
                            '[run]\nengine = "3.5"\nbogus = 1\n')
        self.assertEqual(len(exc.problems), 2, exc.problems)
        self.assertNotIn("cannot be honoured", str(exc))

    def test_a_forbidden_key_is_reported_once(self):
        exc = self._refused(_GOOD_FIDELITY + "[run]\nrej_hollow = 0\n")
        self.assertEqual(len(exc.problems), 1, exc.problems)
        self.assertIn("[run] sets ['rej_hollow']", str(exc))

    def test_missing_profile_skips_the_profile_chain(self):
        exc = self._refused('[fidelity]\nprofile_module = "zz_absent"\n[run]\nbogus = 1\n')
        self.assertEqual(len(exc.problems), 2, exc.problems)
        self.assertIn("[fidelity].profile or [fidelity].authordefaults is required", str(exc))
        self.assertNotIn("could not be imported", str(exc))

    def test_a_non_table_section_stops_after_phase_one(self):
        exc = self._refused('run = "x"\n[fidelty]\nprofile = "STOCK_V314"\n')
        self.assertEqual(len(exc.problems), 2, exc.problems)
        self.assertIn("unknown section(s) ['fidelty']", str(exc))
        self.assertIn("['run'] must be table(s)", str(exc))
        self.assertNotIn("[fidelity].profile or", str(exc))


class TestSectionHelpersCollectToo(_Files):
    """The per-section helpers (slice B): each reports all its own problems and skips the checks
    that read a value it already refused."""

    def test_thresholds_reports_both_bad_numbers_and_skips_the_resolver(self):
        exc = self._refused(_GOOD_FIDELITY + '[thresholds]\narea_ratio_z = "x"\n'
                            'default_int_arr_thresh = "y"\n')
        self.assertEqual(len(exc.problems), 2, exc.problems)
        self.assertIn("[thresholds].area_ratio_z must be a number, got 'x'", str(exc))
        self.assertIn("[thresholds].default_int_arr_thresh must be a number, got 'y'", str(exc))
        self.assertNotIn("[thresholds]: ", str(exc))
        self.assertNotIn("present but empty", str(exc))

    def test_an_empty_arm_identifier_is_reported_once_as_missing(self):
        exc = self._refused(_GOOD_FIDELITY + '[arm]\nsite_id = ""\n')
        self.assertEqual(len(exc.problems), 1, exc.problems)
        self.assertIn("[arm] is missing ['facility_id', 'platform_id', 'site_id']", str(exc))
        self.assertNotIn("[arm].site_id must be a non-empty string", str(exc))

    def test_soda2_reports_a_fidelity_section_and_a_bad_jit_together(self):
        exc = self._refused('[run]\nengine = "soda2"\njit = "yes"\n'
                            '[soda2]\nfn = "x.2DS"\n' + _GOOD_FIDELITY)
        self.assertEqual(len(exc.problems), 2, exc.problems)
        self.assertIn("reads no UIOPS fidelity profile", str(exc))
        self.assertIn("[run].jit is a switch and takes true or false", str(exc))

    def test_v35_reports_both_bad_switches_and_not_empty(self):
        exc = self._refused(_GOOD_FIDELITY + '[run]\nengine = "3.5"\n'
                            '[v35]\niQC = 2\niNewHabit = 3\n')
        self.assertEqual(len(exc.problems), 2, exc.problems)
        self.assertIn("[v35].iQC must be 0 or 1, got 2", str(exc))
        self.assertIn("[v35].iNewHabit must be 0 or 1, got 3", str(exc))
        self.assertNotIn("present but empty", str(exc))

    def test_tas_reports_a_bad_number_and_a_bad_source_and_skips_the_policy(self):
        exc = self._refused(_GOOD_FIDELITY + '[tas]\ncutoff_mps = "a"\nsource = "nope"\n')
        self.assertEqual(len(exc.problems), 2, exc.problems)
        self.assertIn("[tas].source must be one of", str(exc))
        self.assertIn("[tas].cutoff_mps must be a number, got 'a'", str(exc))
        self.assertNotIn("[tas]: ", str(exc))


class TestFileLevelErrorsStayImmediate(_Files):
    def test_file_level_errors_stay_immediate(self):
        path = self.root / "broken.toml"
        path.write_text("[fidelity\nprofile = 1\n", encoding="utf-8")
        with self.assertRaises(ConfigDecodeError) as cm:
            load_config(path)
        self.assertEqual(cm.exception.problems, ())


if __name__ == "__main__":
    unittest.main()
