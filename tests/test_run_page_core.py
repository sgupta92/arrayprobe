# SPDX-License-Identifier: BSD-3-Clause
"""Run page slice 1: the pure form -> TOML -> argv core (``arrayprobe.run_page``).

Design: ``RUN_PAGE_PLAN.md`` section 3, slice 1. Every decision the core makes is pinned here.
"""

import ast
import sys
import tempfile
import unittest
from pathlib import Path

from arrayprobe import run_page
from arrayprobe.config import load_config


def _uiops_form(tmp: Path, **over):
    raw = tmp / "base160906064017.2DS"
    raw.write_bytes(b"")
    form = {"engine": "3.5", "profile": "stock-v3.5", "preset": "DEMO_2DS_H",
            "raw": str(raw), "out": str(tmp / "out"), "stages": "234", "name": "demo",
            "jobs": 1, "s2_jobs": 1, "chunks": 1}
    form.update(over)
    return form


class _Tmp(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()


class TestBuildToml(_Tmp):
    def test_uiops_form_round_trips_through_load_config(self):
        form = _uiops_form(self.tmp, probe="2DS")
        path = self.tmp / "run.toml"
        path.write_text(run_page.build_toml(form), encoding="utf-8")
        cfg = load_config(path)
        self.assertEqual(cfg.run["engine"], "3.5")
        self.assertEqual(cfg.run["preset"], "DEMO_2DS_H")
        self.assertEqual(cfg.run["raw"], [str(Path(form["raw"]).resolve())])
        self.assertEqual(cfg.run["out"], str(Path(form["out"]).resolve()))
        self.assertEqual(cfg.run["stages"], "234")
        self.assertEqual(cfg.run["probe"], "2DS")

    def test_soda2_form_has_only_run_and_soda2_sections(self):
        raw = self.tmp / "base.2DS"
        raw.write_bytes(b"")
        probe = run_page.probe_choices_soda2()[0]
        form = {"engine": "soda2", "probe": probe, "raw": str(raw), "out": str(self.tmp / "o"),
                "name": "s", "jit": True, "date": "20160906"}
        path = self.tmp / "run.toml"
        text = run_page.build_toml(form)
        path.write_text(text, encoding="utf-8")
        import tomllib
        doc = tomllib.loads(text)
        self.assertEqual(set(doc), {"run", "soda2"})
        self.assertEqual(doc["run"], {"engine": "soda2", "jit": True})
        cfg = load_config(path)
        self.assertEqual(cfg.soda2["probename"], probe)
        self.assertEqual(cfg.soda2["fn"], str(raw.resolve()))
        self.assertEqual(cfg.soda2["date"], "20160906")

    def test_soda2_float32_fields_are_written_as_typed_in_the_table(self):
        # 'NASA Langley CAPS' tau is 5.1e-08 in soda2_probespecs.pro; a widened float32 would
        # write 5.099999918495389e-08.
        raw = self.tmp / "x.2DS"
        raw.write_bytes(b"")
        text = run_page.build_toml({"engine": "soda2", "probe": "NASA Langley CAPS",
                                    "raw": str(raw), "out": str(self.tmp)})
        self.assertIn("tau = 5.1e-08", text)

    def test_windows_paths_survive_toml_quoting(self):
        import tomllib
        doc = tomllib.loads(run_page.build_toml(_uiops_form(self.tmp)))
        self.assertTrue(Path(doc["run"]["out"]).is_absolute())

    def test_uiops_file_names_the_profile_because_load_config_assumes_none(self):
        text = run_page.build_toml(_uiops_form(self.tmp))
        self.assertIn('[fidelity]\nprofile = "stock-v3.5"', text)


class TestBuildArgv(_Tmp):
    def test_argv_is_a_list_with_no_shell_tokens(self):
        argv = run_page.build_argv(_uiops_form(self.tmp, jit=True), self.tmp / "r.toml",
                                   dry_run=False)
        self.assertIsInstance(argv, list)
        self.assertEqual(argv[:4], [sys.executable, "-m", "arrayprobe", "run"])
        for tok in argv:
            self.assertIsInstance(tok, str)
            for bad in ("|", "&&", ";", ">"):
                self.assertNotEqual(tok, bad)
        self.assertIn("--yes", argv)   # detached run has no terminal for the gate
        self.assertIn("--jit", argv)

    def test_engine_314_appends_port_validation(self):
        argv = run_page.build_argv(_uiops_form(self.tmp, engine="3.1.4", port_validation=True),
                                   "r.toml", dry_run=False)
        self.assertIn("--port-validation", argv)
        argv = run_page.build_argv(_uiops_form(self.tmp), "r.toml", dry_run=False)
        self.assertNotIn("--port-validation", argv)

    def test_dry_run_flag_forwarded(self):
        self.assertEqual(run_page.build_argv(_uiops_form(self.tmp), "r.toml",
                                             dry_run=True)[-1], "--dry-run")
        self.assertNotIn("--dry-run", run_page.build_argv(_uiops_form(self.tmp), "r.toml",
                                                          dry_run=False))

    def test_soda2_dry_run_is_the_enhancements_preflight(self):
        form = {"engine": "soda2", "probe": "x", "out": str(self.tmp), "protective": "on"}
        self.assertEqual(run_page.build_argv(form, "r.toml", dry_run=True)[3:],
                         ["soda2", "enhancements", "r.toml", "--protective", "on"])
        argv = run_page.build_argv({**form, "jobs": 4, "chunks": 3, "jit": True}, "r.toml",
                                   dry_run=False)
        self.assertEqual(argv[3:5], ["soda2", "run"])
        for tok in ("--out", "--jit", "--protective"):
            self.assertIn(tok, argv)
        self.assertEqual(argv[argv.index("--chunks") + 1], "3")


class TestValidateForm(_Tmp):
    TABLES = {"presets": ("DEMO_2DS_H",), "profiles": ("stock-v3.5", "stock-v3.1.4"),
              "probes_v35": ("2DS", "CIP"), "soda2_probes": ("2D-S Horizontal Array",)}

    def check(self, form):
        return run_page.validate_form(form, **self.TABLES)

    def test_good_form_has_no_errors(self):
        self.assertEqual(self.check(_uiops_form(self.tmp)), [])

    def test_discovered_tables_accept_the_demo_form(self):
        self.assertEqual(run_page.validate_form(_uiops_form(self.tmp)), [])

    def test_unknown_preset_refused(self):
        self.assertTrue(any("preset" in e for e in self.check(_uiops_form(self.tmp,
                                                                          preset="NOPE"))))

    def test_unknown_engine_profile_probe_refused(self):
        self.assertTrue(self.check(_uiops_form(self.tmp, engine="4.0")))
        self.assertTrue(any("profile" in e for e in self.check(_uiops_form(self.tmp,
                                                                           profile="x"))))
        self.assertTrue(any("probe" in e for e in self.check(_uiops_form(self.tmp,
                                                                         probe="../2DS"))))

    def test_missing_raw_file_refused(self):
        errs = self.check(_uiops_form(self.tmp, raw=str(self.tmp / "absent.2DS")))
        self.assertTrue(any("not found" in e for e in errs))
        self.assertTrue(any("raw" in e for e in self.check(_uiops_form(self.tmp, raw=""))))

    def test_stages_outside_234_refused(self):
        self.assertTrue(any("stages" in e for e in self.check(_uiops_form(self.tmp,
                                                                          stages="235x"))))

    def test_engine_314_without_port_validation_refused(self):
        errs = self.check(_uiops_form(self.tmp, engine="3.1.4", profile="stock-v3.1.4"))
        self.assertIn(run_page.REFUSAL_314, errs)
        self.assertEqual(self.check(_uiops_form(self.tmp, engine="3.1.4", profile="stock-v3.1.4",
                                                port_validation=True)), [])

    def test_port_validation_under_another_engine_refused(self):
        self.assertTrue(self.check(_uiops_form(self.tmp, port_validation=True)))

    def test_run_name_charset(self):
        for bad in ("", "a/b", "..\\x", "a b", "x" * 65):
            self.assertTrue(any("run name" in e for e in self.check(_uiops_form(self.tmp,
                                                                                name=bad))), bad)

    def test_jobs_must_be_positive_integers(self):
        for bad in (0, -1, "two", True, 1.5):
            self.assertTrue(self.check(_uiops_form(self.tmp, jobs=bad)), bad)

    def test_out_whose_parent_is_missing_refused(self):
        errs = self.check(_uiops_form(self.tmp, out=str(self.tmp / "a" / "b")))
        self.assertTrue(any("parent" in e for e in errs))

    def test_protective_other_than_auto_refused_for_uiops(self):
        # `arrayprobe run` has no --protective, so the page cannot honour one.
        self.assertTrue(self.check(_uiops_form(self.tmp, protective="on")))

    def test_soda2_probe_whitelisted(self):
        raw = self.tmp / "r.2DS"
        raw.write_bytes(b"")
        form = {"engine": "soda2", "probe": "2D-S Horizontal Array", "raw": str(raw),
                "out": str(self.tmp), "name": "s"}
        self.assertEqual(self.check(form), [])
        self.assertTrue(self.check({**form, "probe": "Made Up"}))


class TestNoProcessingLogic(unittest.TestCase):
    """Risk 3: the page validates shape only; no threshold or profile field is read here."""

    def test_module_names_no_threshold_or_profile_field(self):
        src = Path(run_page.__file__).read_text(encoding="utf-8")
        names = {n.attr for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Attribute)}
        for forbidden in ("rej_hollow", "max_edge_img_ar", "max_comp_img_ar", "d_choice",
                          "sa_method", "area_ratio"):
            self.assertNotIn(forbidden, names)
        self.assertNotIn("shell=True", src)

    def test_only_the_launch_functions_import_subprocess(self):
        # Slice 1 kept the core free of processes; slice 2 confines them to three functions.
        tree = ast.parse(Path(run_page.__file__).read_text(encoding="utf-8"))
        owners = set()
        for fn in ast.walk(tree):
            if isinstance(fn, ast.FunctionDef):
                for node in ast.walk(fn):
                    if isinstance(node, ast.Import) and any(
                            a.name == "subprocess" for a in node.names):
                        owners.add(fn.name)
        top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))
               and "subprocess" in ast.dump(n)]
        self.assertEqual(top, [])
        self.assertEqual(owners, {"dry_run", "launch_detached", "_wrap"})


if __name__ == "__main__":
    unittest.main()
