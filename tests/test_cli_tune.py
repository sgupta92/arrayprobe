# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe tune settings``: the settings table, as a cold user reads it from the CLI.

The table itself (every default and location cited to a source line) is pinned by
``tests/test_tune_settings.py``; this module pins that the command shows all of it, as text and as
JSON, and that ``--probe-case arm-ena-2ds`` marks the shattering rows as having no effect there
(that case's ``applyIntArrThresh`` is 0).
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import unittest

from arrayprobe import cli
from arrayprobe.tune.settings import SETTINGS


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    code = None
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(argv)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def _subparsers(parser: argparse.ArgumentParser) -> argparse._SubParsersAction:
    return next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))


class TheHelpListsTheVerb(unittest.TestCase):

    def test_top_level_help_lists_tune(self):
        self.assertIn("tune", _subparsers(cli.build_parser()).choices)

    def test_tune_help_lists_settings(self):
        code, out, _err = _run(["tune", "--help"])
        self.assertEqual(code, 0)
        self.assertIn("settings", out)

    def test_tune_without_a_verb_is_refused(self):
        code, _out, _err = _run(["tune"])
        self.assertEqual(code, 2)


class TheTablePrints(unittest.TestCase):

    def test_every_row_prints_with_its_default_and_where(self):
        code, out, err = _run(["tune", "settings"])
        self.assertEqual(code, 0, err)
        for s in SETTINGS:
            with self.subTest(setting=s.name):
                self.assertIn(s.name, out)
                self.assertIn(s.default, out)
                self.assertIn("; ".join(s.where), out)
        self.assertIn(f"{len(SETTINGS)} settings.", out)

    def test_no_effect_column_without_a_probe_case(self):
        _code, out, _err = _run(["tune", "settings"])
        self.assertNotIn("no effect", out)

    def test_a_top_level_uiops_version_does_not_refuse_it(self):
        # `tune` describes the default engine; it runs nothing, like `engines`.
        code, _out, err = _run(["--uiops-version", "3.5", "tune", "settings"])
        self.assertEqual(code, 0, err)


class TheJsonParses(unittest.TestCase):

    def test_json_has_every_settings_row(self):
        code, out, err = _run(["tune", "settings", "--json"])
        self.assertEqual(code, 0, err)
        doc = json.loads(out)
        self.assertEqual(doc["engine"], "3.5")
        self.assertIsNone(doc["probe_case"])
        self.assertEqual([r["name"] for r in doc["settings"]], [s.name for s in SETTINGS])
        for row, s in zip(doc["settings"], SETTINGS, strict=True):
            with self.subTest(setting=s.name):
                self.assertEqual(row["default"], s.default)
                self.assertEqual(row["where"], list(s.where))
                self.assertEqual(row["engine_3_5"], s.engine_35)
                self.assertEqual(row["sources"], [str(c) for c in s.cites])
                self.assertNotIn("effect", row)


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


#: The ARM ENA case is development-only: the release does not ship its registration
#: modules, so the tests about that case skip there instead of failing on a missing case.
_needs_arm_ena = unittest.skipUnless(
    _has_module("arrayprobe_uiops.register_arm_ena_2ds")
    and _has_module("arrayprobe_uiops.register_arm_ena_2ds_cold"),
    "arrayprobe_uiops.register_arm_ena_2ds and register_arm_ena_2ds_cold: the ARM ENA "
    "probe-case registration modules are not in this distribution",
)


@_needs_arm_ena
class TheArmEnaCaseMarksShatteringAsNoEffect(unittest.TestCase):

    def test_json_marks_every_gated_row_as_no_effect(self):
        code, out, err = _run(["tune", "settings", "--json", "--probe-case", "arm-ena-2ds"])
        self.assertEqual(code, 0, err)
        rows = {r["name"]: r for r in json.loads(out)["settings"]}
        gated = [s.name for s in SETTINGS if s.shattering_gated]
        self.assertIn("defaultIntArrThresh", gated)
        self.assertIn("shattering threshold file", gated)
        for name in gated:
            with self.subTest(setting=name):
                self.assertFalse(rows[name]["effect"]["effective"])
                self.assertIn("applyIntArrThresh = 0", rows[name]["effect"]["reason"])
        self.assertTrue(rows["area_ratio_z"]["effect"]["effective"])

    def test_text_marks_the_gated_rows(self):
        code, out, err = _run(["tune", "settings", "--probe-case", "arm-ena-2ds"])
        self.assertEqual(code, 0, err)
        gated = sum(s.shattering_gated for s in SETTINGS)
        self.assertEqual(
            out.count("on arm-ena-2ds:  no effect: the gate is off on this probe case"), gated)

    def test_an_unknown_probe_case_is_refused_with_the_registered_names(self):
        code, out, err = _run(["tune", "settings", "--probe-case", "no-such-case"])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("no-such-case", err)


@_needs_arm_ena
class TheArmEnaColdCaseActsOnlyOnceIaThreshTypeIsChosen(unittest.TestCase):
    """The cold case's gate is on, but engine 3.5's default run is iaThreshType 0."""

    def test_default_run_marks_the_threshold_rows_as_no_effect(self):
        code, out, err = _run(["tune", "settings", "--json", "--probe-case", "arm-ena-2ds-cold"])
        self.assertEqual(code, 0, err)
        doc = json.loads(out)
        self.assertEqual(doc["ia_thresh_type"], 0)
        rows = {r["name"]: r for r in doc["settings"]}
        gated = [s.name for s in SETTINGS if s.shattering_gated]
        self.assertIn("defaultIntArrThresh", gated)
        for name in gated:
            with self.subTest(setting=name):
                eff = rows[name]["effect"]
                if name == "shattering threshold file":
                    # choosing a file is itself what selects iaThreshType 1
                    self.assertTrue(eff["effective"])
                else:
                    self.assertFalse(eff["effective"])
                    self.assertIn("iaThreshType 0, the default for engine 3.5", eff["reason"])

    def test_iaThreshType_2_marks_every_gated_row_as_acting(self):
        code, out, err = _run(["tune", "settings", "--json", "--probe-case", "arm-ena-2ds-cold",
                               "--ia-thresh-type", "2"])
        self.assertEqual(code, 0, err)
        rows = {r["name"]: r for r in json.loads(out)["settings"]}
        for name in (s.name for s in SETTINGS if s.shattering_gated):
            with self.subTest(setting=name):
                self.assertTrue(rows[name]["effect"]["effective"])
                self.assertIn("applyIntArrThresh = 1", rows[name]["effect"]["reason"])

    def test_text_marks_the_gated_rows(self):
        code, out, err = _run(["tune", "settings", "--probe-case", "arm-ena-2ds-cold"])
        self.assertEqual(code, 0, err)
        gated = sum(s.shattering_gated for s in SETTINGS)
        self.assertEqual(
            out.count("on arm-ena-2ds-cold:  no effect: iaThreshType 0, the default"), gated - 1)
        self.assertEqual(out.count("on arm-ena-2ds-cold:  acts: the gate is on"), 1)


class TuneDiodesPrintsTheMaskLine(unittest.TestCase):
    """``arrayprobe tune diodes`` on a synthetic v3.5 proc file (counts as in test_tune_diodes)."""

    def setUp(self):
        import tempfile
        from pathlib import Path

        import numpy as np
        from netCDF4 import Dataset

        self.proc = Path(tempfile.mkdtemp()) / "proc.base160910124240.H.cdf"
        shadow = np.full(128, 200)
        shadow[[0, 127]] = 100
        shadow[59] = 950
        with Dataset(self.proc, "w") as ds:
            ds.createDimension("time", 10)
            ds.createDimension("pos_count", 2)
            ds.createDimension("bin_count", 128)
            ds.createVariable("bin_stats", "i4", ("bin_count",))[:] = shadow
            ds.createVariable("position", "i2", ("time", "pos_count"))[:] = [[1, 100]] * 10
        self.proc.with_name(self.proc.name + ".call").write_text(
            "engine=3.5 profile=stock-v3.5\n", encoding="utf-8")

    def test_summary_and_run_file_lines(self):
        code, out, err = _run(["tune", "diodes", "--proc", str(self.proc)])
        self.assertEqual(code, 0, err)
        self.assertIn("flagged: [60]", out)
        self.assertIn("[masking.diodes]", out)
        self.assertIn('"base160910124240" = [60]', out)

    def test_json(self):
        code, out, err = _run(["tune", "diodes", "--proc", str(self.proc), "--json"])
        self.assertEqual(code, 0, err)
        doc = json.loads(out)
        self.assertEqual((doc["flagged"], doc["S"], doc["branch"]), ([60], 1000, "max"))
        self.assertEqual(doc["stem"], "base160910124240")

    def test_jobs_reaches_the_slice_total_and_1_forces_a_serial_read(self):
        from unittest import mock

        from arrayprobe.tune import diodes

        seen = []
        real = diodes.position_slice_total

        def spy(path, offset, **kw):
            seen.append(kw.get("jobs"))
            return real(path, offset, **kw)

        with (mock.patch.object(diodes, "position_slice_total", spy),
              mock.patch("concurrent.futures.ProcessPoolExecutor") as pool):
            code, out, err = _run(["tune", "diodes", "--proc", str(self.proc), "--json",
                                   "--jobs", "1"])
            code_default, _o, _e = _run(["tune", "diodes", "--proc", str(self.proc), "--json"])
        self.assertEqual((code, code_default), (0, 0), err)
        self.assertEqual(seen, [1, None])
        self.assertEqual(json.loads(out)["S"], 1000)
        pool.assert_not_called()

    def test_a_missing_file_exits_2(self):
        code, _out, err = _run(["tune", "diodes", "--proc", str(self.proc) + ".nope"])
        self.assertEqual(code, 2)
        self.assertIn("no proc file", err)


if __name__ == "__main__":
    unittest.main()
