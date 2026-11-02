# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe.tune.settings``: every row is cited, and the effect column is right.

Two sides from two places: the citations are read out of the files they name, and the coverage
check reads the field lists from ``RejectConfig`` and ``Regime`` themselves.
"""

from __future__ import annotations

import ast
import dataclasses
import unittest
from pathlib import Path

from tests import _upstream
from tests._repo import PKG_ROOT, needs_source, repo_only

from arrayprobe.regimes import Regime
from arrayprobe.tune import settings as S
from arrayprobe_uiops.reject_core import RejectConfig

REPO = Path(__file__).resolve().parents[1]
SHATTERING = ("shattering threshold file", "defaultIntArrThresh", "reaccptShatrs", "reaccptD",
              "reaccptMaxIA")


def _line(path: str, n: int) -> str:
    lines = _upstream.cited_path(path).read_text(encoding="utf-8", errors="replace").split("\n")
    return lines[n - 1] if 0 < n <= len(lines) else ""


def _nearest(path: str, n: int, text: str, k: int = 3) -> list[int]:
    """The ``k`` line numbers nearest ``n`` that hold ``text``, for the failure message only."""
    lines = _upstream.cited_path(path).read_text(encoding="utf-8", errors="replace").split("\n")
    hits = [i for i, s in enumerate(lines, 1) if text in s]
    return sorted(sorted(hits, key=lambda i: abs(i - n))[:k])


@repo_only
class TestCitations(unittest.TestCase):
    def test_every_cited_line_holds_its_named_text(self):
        bad = []
        for row in S.SETTINGS:
            self.assertTrue(row.cites, row.name)
            for c in row.cites:
                if c.contains not in _line(c.path, c.line):
                    near = _nearest(c.path, c.line, c.contains)
                    bad.append(f"{row.name}: {c} lacks {c.contains!r}; nearest lines holding "
                               f"it: {near or 'none'}")
        self.assertEqual(bad, [], "\n" + "\n".join(bad))

    def test_a_wrong_line_is_caught(self):
        c = S.Cite("UIOPS-v3.5/joefinlon-UIOPS-039be82/sizeDist.m", 1161, "area_ratio < .2")
        self.assertNotIn(c.contains, _line(c.path, c.line))

    def test_names_are_unique(self):
        names = [s.name for s in S.SETTINGS]
        self.assertEqual(len(names), len(set(names)))


class TestCoverage(unittest.TestCase):
    def test_every_reject_threshold_has_a_row(self):
        have = S.settings_by_name()
        for f in dataclasses.fields(RejectConfig):
            self.assertIn(f.name, have)

    def test_every_regime_number_has_a_row(self):
        names = " ".join(S.settings_by_name())
        for f in dataclasses.fields(Regime):
            if f.type in ("float", float):
                self.assertIn(f.name, names)


def _gate_off_case():
    """The shipped generic ``v35-2ds-ladder-fix`` case, registered; its shattering gate is off."""
    from arrayprobe_uiops.probe_cases import register_v35_2ds_ladder_fix

    return register_v35_2ds_ladder_fix()


class TestEngine35Refusals(unittest.TestCase):
    def test_the_regime_rows_are_accepted(self):
        # Regime slice 4 lifted the engine-3.5 refusal.
        case = _gate_off_case()
        self.assertFalse(case.defaults.applyIntArrThresh)
        rows = S.settings_by_name()
        for name in ("regime", "default_int_arr_thresh (driver override)"):
            self.assertEqual(rows[name].engine_35, S.ACCEPTED)
        # The regime carries area_ratio_z, which is ungated, so it always acts.
        self.assertTrue(rows["regime"].effect(case.name).effective)
        # The raw override is the shattering constant: the gate-off case ignores it.
        eff = rows["default_int_arr_thresh (driver override)"].effect(case.name, 2)
        self.assertFalse(eff.effective)
        self.assertIn("the gate is off", eff.reason)

    def test_area_ratio_z_is_accepted_and_ungated(self):
        row = S.settings_by_name()["area_ratio_z"]
        self.assertEqual(row.engine_35, S.ACCEPTED)
        self.assertTrue(row.effect("arm-ena-2ds").effective)


class TestShatteringGate(unittest.TestCase):
    def test_no_effect_on_a_gate_off_case(self):
        case = _gate_off_case()
        self.assertFalse(case.defaults.applyIntArrThresh)
        rows = S.settings_by_name()
        for name in SHATTERING:
            eff = rows[name].effect(case.name)
            self.assertFalse(eff.effective, name)
            self.assertIn("no effect: the gate is off on this probe case", eff.reason)
            # The gate is checked first: no iaThreshType makes a gate-off case act.
            self.assertFalse(rows[name].effect(case.name, 2).effective, name)

    def test_gate_on_but_iaThreshType_0_has_no_effect(self):
        # Engine 3.5 without a threshold file runs iaThreshType 0, and apply_shattering returns
        # before any test; only choosing the file (which selects type 1) acts.
        from arrayprobe_uiops.sizedist_tables import probe_defaults

        on = probe_defaults("IMPACTS", "2DS")
        self.assertEqual(on.applyIntArrThresh, 1)
        rows = S.settings_by_name()
        for name in SHATTERING:
            eff = rows[name].effect(on)
            if name == "shattering threshold file":
                self.assertTrue(eff.effective, name)
                self.assertIn("iaThreshType is 1", eff.reason)
            else:
                self.assertFalse(eff.effective, name)
                self.assertIn("no effect: iaThreshType 0, the default for engine 3.5", eff.reason)

    def test_gate_on_and_iaThreshType_2_acts(self):
        from arrayprobe_uiops.sizedist_tables import probe_defaults

        on = probe_defaults("IMPACTS", "2DS")
        rows = S.settings_by_name()
        for name in SHATTERING:
            eff = rows[name].effect(on, 2)
            self.assertTrue(eff.effective, name)
            self.assertIn("acts: the gate is on", eff.reason)

    def test_defaultIntArrThresh_is_read_only_by_type_2(self):
        # A synthetic gate-on case: the generic case with its gate turned on.
        on = dataclasses.replace(_gate_off_case().defaults, applyIntArrThresh=1)
        row = S.settings_by_name()["defaultIntArrThresh"]
        self.assertTrue(row.effect(on, 2).effective)
        for t in (1, 3):
            eff = row.effect(on, t)
            self.assertFalse(eff.effective, t)
            self.assertIn(f"iaThreshType {t} does not read it", eff.reason)

    def test_an_iaThreshType_outside_0_to_3_is_refused(self):
        with self.assertRaises(ValueError):
            S.settings_by_name()["defaultIntArrThresh"].effect("arm-ena-2ds-cold", 4)

    def test_a_named_case_gate_is_read_from_the_case(self):
        case = _gate_off_case()
        self.assertIs(S.resolve_probe_defaults(case.name), case.defaults)
        self.assertEqual(S.resolve_probe_defaults(case.name).applyIntArrThresh,
                         case.defaults.applyIntArrThresh)


@needs_source
class TestImportIsLight(unittest.TestCase):
    def test_settings_py_names_no_top_level_v35_import(self):
        tree = ast.parse((PKG_ROOT / "src/arrayprobe/tune/settings.py").read_text("utf-8"))
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [
                    node.module or ""]
                self.assertFalse(any(m.startswith("arrayprobe_uiops") for m in mods), mods)


if __name__ == "__main__":
    unittest.main()
