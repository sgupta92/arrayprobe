# SPDX-License-Identifier: BSD-3-Clause
"""``[thresholds].tas_max`` / ``[thresholds].pecan_params``: the two sizeDist inputs a UIOOPS case
can lack, loaded and validated by :mod:`arrayprobe.config`; absent, nothing is set."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arrayprobe.config import ConfigError, load_config

_BASE = ('[fidelity]\nprofile = "stock-v3.5"\n\n[run]\nengine = "3.5"\n'
         'preset = "DEMO_2DS_H"\n')


class S4CaseInputsInConfig(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def _cfg(self, extra: str):
        p = self.dir / "run.toml"
        p.write_text(_BASE + extra, encoding="utf-8")
        return load_config(p)

    def test_absent_leaves_both_none(self):
        cfg = self._cfg("")
        self.assertIsNone(cfg.thresholds_tas_max)
        self.assertIsNone(cfg.thresholds_pecan_params)

    def test_tas_max_alone_is_a_declared_section(self):
        cfg = self._cfg("\n[thresholds]\ntas_max = 140\n")
        self.assertEqual(cfg.thresholds_tas_max, 140.0)
        self.assertTrue(cfg.thresholds_declared)
        self.assertIsNone(cfg.thresholds_area_ratio_z)

    def test_bad_tas_max_is_refused(self):
        for bad in ("0", "-5", "nan", "true", '"fast"'):
            with self.subTest(value=bad), self.assertRaises(ConfigError):
                self._cfg(f"\n[thresholds]\ntas_max = {bad}\n")

    def test_pecan_params_resolves_relative_to_the_file_and_is_parsed(self):
        (self.dir / "spirals.csv").write_text(
            "start_s,end_s,intar_threshold_s\n100,200,2.5e-6\n", encoding="utf-8")
        cfg = self._cfg('\n[thresholds]\npecan_params = "spirals.csv"\n')
        self.assertEqual(Path(cfg.thresholds_pecan_params), (self.dir / "spirals.csv").resolve())

    def test_a_missing_or_malformed_pecan_file_is_refused_at_load(self):
        (self.dir / "bad.csv").write_text("start_s,end_s\n1,2\n", encoding="utf-8")
        for name in ("missing.csv", "bad.csv"):
            with self.subTest(file=name), self.assertRaises(ConfigError):
                self._cfg(f'\n[thresholds]\npecan_params = "{name}"\n')


if __name__ == "__main__":
    unittest.main()
