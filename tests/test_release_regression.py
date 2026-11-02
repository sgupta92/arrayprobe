# SPDX-License-Identifier: BSD-3-Clause
"""Release-regression diff: identical trees pass, an unnamed change fails, a named one passes."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

try:
    import tomllib
except ImportError:  # pragma: no cover -- Python < 3.11, not this project's floor
    import tomli as tomllib  # type: ignore[no-redef]

try:
    import netCDF4
except ImportError:  # pragma: no cover
    netCDF4 = None

_TOOL = Path(__file__).resolve().parents[1] / "scripts" / "release_regression.py"
_spec = importlib.util.spec_from_file_location("release_regression", _TOOL)
rr = importlib.util.module_from_spec(_spec)
sys.modules["release_regression"] = rr
_spec.loader.exec_module(rr)


def _write(path: Path, counts, creation="2026-10-27 10:00", extra=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with netCDF4.Dataset(str(path), "w", format="NETCDF3_CLASSIC") as ds:
        ds.createDimension("Time", 3)
        ds.createDimension("bin", 4)
        ds.setncattr("Creation Time", creation)
        ds.setncattr("Title", "tiny")
        c = ds.createVariable("Counts", "f8", ("Time", "bin"))
        c[:] = np.asarray(counts, dtype="f8")
        t = ds.createVariable("Seconds", "i4", ("Time",))
        t[:] = [1, 2, 3]
        if extra:
            e = ds.createVariable(extra, "f8", ("Time",))
            e[:] = [0.0, 0.0, 0.0]


BASE = np.arange(12, dtype="f8").reshape(3, 4)


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
class ReleaseRegressionTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.old, self.new = root / "old", root / "new"
        self.changes, self.out = root / "CHANGES.md", root / "CHANGED_CELLS.md"
        self.changes.write_text("# Changes\n\n## 0.1.1\n\n- Nothing user-visible.\n\n"
                                "## 0.1.0\n\n- Counts first release.\n", encoding="utf-8")

    def _run(self):
        return rr.main(["--old-dir", str(self.old), "--new-dir", str(self.new),
                        "--changes", str(self.changes), "--out", str(self.out)])

    def test_identical_dirs_pass_with_empty_change_list(self):
        _write(self.old / "sub" / "a.nc", BASE)
        # Creation Time differs on purpose: it is excluded
        _write(self.new / "sub" / "a.nc", BASE, creation="2026-10-28 09:00")
        self.assertEqual(self._run(), 0)
        text = self.out.read_text(encoding="utf-8")
        self.assertIn("changes: 0 (0 not named", text)
        self.assertIn("No changes.", text)

    def test_unnamed_cell_change_fails_and_is_listed(self):
        changed = BASE.copy()
        changed[1, 2] = 99.0
        _write(self.old / "a.nc", BASE)
        _write(self.new / "a.nc", changed)
        self.assertEqual(self._run(), 1)
        text = self.out.read_text(encoding="utf-8")
        self.assertIn("| cell | a.nc | Counts | (1, 2) | 6 | 99 | UNNAMED |", text)
        self.assertEqual(text.count("| cell |"), 1)

    def test_named_change_passes_but_is_still_logged(self):
        changed = BASE.copy()
        changed[1, 2] = 99.0
        _write(self.old / "a.nc", BASE)
        _write(self.new / "a.nc", changed)
        self.changes.write_text("## 0.1.1\n\n- `Counts` in a corrected bin.\n\n"
                                "## 0.1.0\n\n- first\n", encoding="utf-8")
        self.assertEqual(self._run(), 0)
        text = self.out.read_text(encoding="utf-8")
        self.assertIn("| cell | a.nc | Counts | (1, 2) | 6 | 99 | named |", text)

    def test_name_in_an_older_section_does_not_count(self):
        changed = BASE.copy()
        changed[0, 0] = -1.0
        _write(self.old / "a.nc", BASE)
        _write(self.new / "a.nc", changed)
        self.changes.write_text("## 0.1.1\n\n- other\n\n## 0.1.0\n\n- `Counts` here only\n",
                                encoding="utf-8")
        self.assertEqual(self._run(), 1)

    def test_files_on_one_side_only_are_listed(self):
        _write(self.old / "gone.nc", BASE)
        _write(self.new / "added.nc", BASE)
        self.assertEqual(self._run(), 1)
        text = self.out.read_text(encoding="utf-8")
        self.assertIn("| gone.nc | present | <absent> | UNNAMED |", text)
        self.assertIn("| added.nc | <absent> | present | UNNAMED |", text)

    def test_added_variable_named_by_path_passes(self):
        _write(self.old / "a.nc", BASE)
        _write(self.new / "a.nc", BASE, extra="Extra")
        self.assertEqual(self._run(), 1)
        self.changes.write_text("## 0.1.1\n\n- a.nc gains a variable.\n", encoding="utf-8")
        self.assertEqual(self._run(), 0)

    def test_bare_word_in_prose_does_not_name_a_change(self):
        _write(self.old / "a.nc", BASE)
        _write(self.new / "a.nc", BASE, extra="time")
        self.changes.write_text("## 0.1.1\n\n- Processing time is shorter; Counts unchanged.\n",
                                encoding="utf-8")
        self.assertEqual(self._run(), 1)
        self.changes.write_text("## 0.1.1\n\n- New variable `time`.\n", encoding="utf-8")
        self.assertEqual(self._run(), 0)

    def test_nan_in_both_is_not_a_change(self):
        a = BASE.copy()
        a[0, 0] = np.nan
        _write(self.old / "a.nc", a)
        _write(self.new / "a.nc", a)
        self.assertEqual(self._run(), 0)

    def test_missing_input_is_usage_error(self):
        self.assertEqual(self._run(), 2)



class DefaultChangesFileTest(unittest.TestCase):
    """With no ``--changes``, the script reads the package's own release history."""

    def test_default_is_the_release_history(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(rr.DEFAULT_CHANGES, root / "docs" / "developer" / "HISTORY.md")
        self.assertTrue(rr.DEFAULT_CHANGES.is_file(), rr.DEFAULT_CHANGES)

    def test_the_history_file_has_a_section_the_rule_selects(self):
        text = rr.DEFAULT_CHANGES.read_text(encoding="utf-8")
        # Once release.py has stamped the package's version, its changes sit under that
        # heading and [Unreleased] is empty until the next change lands; the release run
        # passes --version to select it.
        pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
        version = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
        stamped = any(line.startswith("## ") and f"[{version}]" in line
                      for line in text.splitlines())
        section = rr.new_version_section(text, version if stamped else None)
        self.assertTrue(section.splitlines()[0].startswith("## "))
        # A "### " subsection belongs to its "## " release, not a release of its own.
        self.assertIn("### ", section)
        self.assertNotIn("\n## ", section.rstrip())

    def test_keep_a_changelog_headings_select_by_version(self):
        text = ("# Release notes\n\n## [Unreleased]\n\n### Fixed\n\n- `Counts` in a bin.\n\n"
                "## [0.1.0] - 2026-10-28\n\n### Added\n\n- first\n")
        self.assertIn("`Counts`", rr.new_version_section(text))
        self.assertIn("- first", rr.new_version_section(text, "0.1.0"))
        self.assertNotIn("`Counts`", rr.new_version_section(text, "0.1.0"))


if __name__ == "__main__":
    unittest.main()
