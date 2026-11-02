# SPDX-License-Identifier: BSD-3-Clause
"""A SODA-2 config accepts ``[outputs]`` and ``[arm]`` (slice S7a).


Every selection the SODA-2 engine has not built yet is refused by name at exit 2, never silently
ignored, and an all-false ``[outputs]`` runs exactly as a file without the section. Built on the
frame fixture of ``tests/test_cli_soda2.py`` (10 s, ``ncdfparticlefile = 1``).
"""
from __future__ import annotations

import importlib.util
import os
import re
import tempfile
import unittest
from pathlib import Path

import numpy as np
from tests.test_cli_soda2 import _STEM, _run_cli, _write_config

from arrayprobe.config import ConfigError, load_config

_ARM = '\n[arm]\nsite_id = "ena"\nplatform_id = "aaf2ds"\nfacility_id = "F1"\n'


def _with(p: Path, text: str) -> Path:
    p.write_text(p.read_text(encoding="utf-8") + text, encoding="utf-8")
    return p


class SODA2OutputsSection(unittest.TestCase):

    def test_outputs_and_arm_load_under_soda2(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(_with(_write_config(tmp),
                                    "\n[outputs]\nfaithful_attributed = false\n" + _ARM))
        self.assertEqual(cfg.outputs, {"faithful_attributed": False})
        self.assertEqual(cfg.arm["site_id"], "ena")

    def test_an_unknown_outputs_key_is_refused_at_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _with(_write_config(tmp), "\n[outputs]\nbogus = true\n")
            with self.assertRaises(ConfigError) as cm:
                load_config(p)
            self.assertIn("unknown key(s) ['bogus']", str(cm.exception))
            rc, _, err = _run_cli(["soda2", "run", str(p)])
        self.assertEqual(rc, 2)
        self.assertIn("bogus", err)

    def test_each_unbuilt_selection_is_refused_by_name(self):
        # `faithful_attributed`, `analysis_ready` and `enhanced_attributed` are built
        # (TheAttributedPsdOfARun and TheCorrectedPassOfARun below).
        for key, value in (("arm", '"faithful"'), ("zarr", "true")):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as tmp:
                p = _with(_write_config(tmp), f"\n[outputs]\n{key} = {value}\n")
                rc, _, err = _run_cli(["soda2", "run", str(p)])
                self.assertEqual(sorted(os.listdir(tmp)), ["soda2.toml"])
            self.assertEqual(rc, 2)
            self.assertIn(f"['{key}'] not yet implemented for engine soda2", err)

    def test_arm_is_refused_while_the_arm_output_is_unbuilt(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _with(_write_config(tmp), _ARM)
            rc, _, err = _run_cli(["soda2", "run", str(p)])
            self.assertEqual(sorted(os.listdir(tmp)), ["soda2.toml"])
        self.assertEqual(rc, 2)
        self.assertIn("[arm] is read only by the ARM output", err)

    def test_all_false_outputs_runs_as_a_file_without_the_section(self):
        import netCDF4
        runs = {}
        for label, extra in (("plain", ""), ("outputs", "\n[outputs]\nfaithful_attributed = "
                                                       "false\nzarr = false\n")):
            tmp = tempfile.mkdtemp()
            self.addCleanup(__import__("shutil").rmtree, tmp, True)
            p = _with(_write_config(tmp, ncdf=1), extra)
            rc, _, err = _run_cli(["soda2", "run", str(p)])
            self.assertEqual(rc, 0, err)
            runs[label] = Path(tmp)
        a, b = runs["plain"], runs["outputs"]
        self.assertEqual(sorted(os.listdir(a)), sorted(os.listdir(b)))
        # The header carries the processing time (``Thu Oct  8 10:44:47 2026``), which differs
        # between two runs a second apart; everything else must be byte-identical.
        stamp = re.compile(rb"[A-Z][a-z]{2} [A-Z][a-z]{2} [ \d]\d \d\d:\d\d:\d\d \d{4}")
        csv_a = (a / f"{_STEM}.pbp.csv").read_bytes()
        csv_b = (b / f"{_STEM}.pbp.csv").read_bytes()
        self.assertEqual(len(stamp.findall(csv_a)), 1)
        self.assertEqual(stamp.sub(b"<time>", csv_a), stamp.sub(b"<time>", csv_b))
        with netCDF4.Dataset(a / f"{_STEM}.pbp.nc") as da, \
                netCDF4.Dataset(b / f"{_STEM}.pbp.nc") as db:
            self.assertEqual(sorted(da.variables), sorted(db.variables))
            for name in da.variables:
                self.assertTrue(np.array_equal(da[name][:], db[name][:]), name)
            # The output directory (a different temporary directory per run) is the one
            # attribute value allowed to differ besides the processing date.
            ga = {k: repr(da.getncattr(k)).replace(a.name, "OUT")
                  for k in da.ncattrs() if k != "DateProcessed"}
            gb = {k: repr(db.getncattr(k)).replace(b.name, "OUT")
                  for k in db.ncattrs() if k != "DateProcessed"}
            self.assertEqual(ga, gb)


class TheFaithfulPsdFileOfARun(unittest.TestCase):
    """Slice S7b: ``write_run_psd`` writes ``<stem>.nc`` from a finished run's ``ProcessData``,
    byte-identical to ``soda2_export_ncdf`` called directly on the same struct (both with the
    same fixed ``date_created``, the one non-deterministic attribute). No CLI path calls it yet."""

    def test_stem_nc_is_byte_identical_to_a_direct_export(self):
        from arrayprobe_soda2.export_ncdf import soda2_export_ncdf, write_run_psd
        from arrayprobe_soda2.process_2d import soda2_process_2d
        with tempfile.TemporaryDirectory() as tmp:
            op = dict(load_config(_write_config(tmp, ncdf=1)).soda2)
            d = soda2_process_2d(op)
            fixed = "Thu Oct 08 00:00:00 2026"
            a = Path(tmp) / "a"
            b = Path(tmp) / "b"
            a.mkdir()
            b.mkdir()
            got = write_run_psd(d, outdir=str(a) + os.sep, date_created=fixed)
            self.assertEqual(Path(got), a / f"{_STEM}.nc")
            ref = soda2_export_ncdf(d, str(b / f"{_STEM}.nc"), date_created=fixed)
            self.assertEqual(Path(got).read_bytes(), Path(ref).read_bytes())

    def test_outdir_defaults_to_the_runs_own(self):
        from arrayprobe_soda2.export_ncdf import write_run_psd
        from arrayprobe_soda2.process_2d import soda2_process_2d
        with tempfile.TemporaryDirectory() as tmp:
            d = soda2_process_2d(dict(load_config(_write_config(tmp)).soda2))
            got = write_run_psd(d, date_created="x")
            self.assertEqual(Path(got).resolve(), (Path(tmp) / f"{_STEM}.nc").resolve())


class TheAttributedPsdOfARun(unittest.TestCase):
    """Slice S7c in the CLI: ``[outputs] faithful_attributed = true`` writes the run's
    ``<stem>.nc`` and its attributed sibling (named by ``default_output_path``, as the UIOOPS
    driver names its own), with the ``.pbp.call`` as the run record."""

    def _run(self, extra: str) -> Path:
        tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        p = _with(_write_config(tmp, ncdf=1), "\n[outputs]\n" + extra)
        rc, _, err = _run_cli(["soda2", "run", str(p)])
        self.assertEqual(rc, 0, err)
        return Path(tmp)

    def test_writes_the_psd_and_its_attributed_sibling(self):
        from arrayprobe.attributed_export import default_output_path
        out = self._run("faithful_attributed = true\n")
        psd = out / f"{_STEM}.nc"
        self.assertTrue(psd.is_file())
        self.assertTrue(default_output_path(psd).is_file())
        self.assertTrue((out / f"{_STEM}.pbp.call").is_file())

    def test_attributed_file_carries_the_soda2_citation_and_passes_ai_ready(self):
        import netCDF4

        from arrayprobe import ai_ready
        from arrayprobe.attributed_export import SODA2_CITATION, default_output_path
        attributed = default_output_path(self._run("faithful_attributed = true\n")
                                         / f"{_STEM}.nc")
        self.assertEqual(ai_ready.check(attributed), [])
        with netCDF4.Dataset(attributed) as ds:
            self.assertEqual(ds.getncattr("arrayprobe_engine_citation"), SODA2_CITATION)
            self.assertEqual(ds.getncattr("arrayprobe_engine"), "soda2")

    def test_analysis_ready_false_writes_the_plain_encoding(self):
        import netCDF4

        from arrayprobe.attributed_export import ENCODING_PLAIN, default_output_path
        out = self._run("faithful_attributed = true\nanalysis_ready = false\n")
        with netCDF4.Dataset(default_output_path(out / f"{_STEM}.nc")) as ds:
            self.assertEqual(ds.getncattr("arrayprobe_encoding"), ENCODING_PLAIN)

    def test_without_the_selection_no_psd_is_written(self):
        out = self._run("faithful_attributed = false\n")
        self.assertFalse((out / f"{_STEM}.nc").exists())


_STAMP = re.compile(rb"[A-Z][a-z]{2} [A-Z][a-z]{2} [ \d]\d \d\d:\d\d:\d\d \d{4}")


class TheCorrectedPassOfARun(unittest.TestCase):
    """Slice S7d: ``[outputs] enhanced_attributed = true`` runs the faithful pass (protective
    corrections off, no ``[enhancements]``, today's file names) and then a corrected pass
    written as ``<stem>.enh.*``; when no correction applies, a named skip and no copy."""

    def _run(self, extra: str) -> tuple[Path, str]:
        tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        p = _with(_write_config(tmp, ncdf=1), extra)
        rc, out, err = _run_cli(["soda2", "run", str(p)])
        self.assertEqual(rc, 0, err)
        return Path(tmp), out + err

    def test_faithful_files_match_a_faithful_only_run_and_the_corrected_pass_is_enh(self):
        import json

        import netCDF4
        both, log = self._run("\n[outputs]\nfaithful_attributed = true\n"
                              "enhanced_attributed = true\n\n[enhancements]\nprotective = true\n")
        only, _ = self._run("\n[outputs]\nfaithful_attributed = true\n\n[enhancements]\n"
                            "protective = false\n")
        csv_a = (both / f"{_STEM}.pbp.csv").read_bytes()
        csv_b = (only / f"{_STEM}.pbp.csv").read_bytes()
        self.assertEqual(_STAMP.sub(b"<time>", csv_a), _STAMP.sub(b"<time>", csv_b))
        with netCDF4.Dataset(both / f"{_STEM}.nc") as da, \
                netCDF4.Dataset(only / f"{_STEM}.nc") as db:
            for name in db.variables:
                self.assertTrue(np.array_equal(da[name][:], db[name][:]), name)
        faithful = json.loads((both / f"{_STEM}.pbp.call").read_text(encoding="utf-8"))
        self.assertEqual(faithful["enhancements"]["protective_mode"], "off")
        self.assertEqual(faithful["enhancements"]["applied"], [])
        enh_call = both / f"{_STEM}.enh.pbp.call"
        if not enh_call.is_file():
            # The frame fixture's probe may have no correction that applies; then the named
            # skip is the whole contract, and no `.enh.` file exists.
            self.assertIn("ENHANCED skipped", log)
            self.assertEqual([n for n in os.listdir(both) if ".enh." in n], [])
            return
        from arrayprobe.attributed_export import default_output_path
        record = json.loads(enh_call.read_text(encoding="utf-8"))
        applied = record["enhancements"]["applied"]
        self.assertTrue(applied)
        for name in (f"{_STEM}.enh.pbp.csv", f"{_STEM}.enh.pbp.nc", f"{_STEM}.enh.nc"):
            self.assertTrue((both / name).is_file(), name)
        attributed = default_output_path(both / f"{_STEM}.enh.nc")
        self.assertTrue(attributed.is_file())
        with netCDF4.Dataset(attributed) as ds:
            text = " ".join(str(ds.getncattr(k)) for k in ds.ncattrs())
        for name in applied:
            self.assertIn(name, text)
        self.assertFalse((both / ".enh_pass").exists())

    def test_no_applicable_correction_logs_the_named_skip_and_writes_no_copy(self):
        out, log = self._run("\n[outputs]\nenhanced_attributed = true\n\n[enhancements]\n"
                             "protective = false\n")
        self.assertIn("ENHANCED skipped", log)
        self.assertTrue((out / f"{_STEM}.pbp.call").is_file())
        self.assertEqual([n for n in os.listdir(out) if ".enh" in n], [])


@unittest.skipUnless(importlib.util.find_spec("arrayprobe_soda2_enhancements"),
                     "patches arrayprobe_soda2_enhancements, which this install lacks")
class TheCorrectedPassIsForced(unittest.TestCase):
    """Review 1, findings 2 and 4: the frame fixture has no applicable correction, so
    ``TheCorrectedPassOfARun`` leaves through its skip branch and ``_soda2_corrected_pass``'s
    body (the ``.enh_pass`` work dir, ``_move``, ``<stem>.enh.nc`` and its attributed sibling,
    the cleanup loop and ``rmdir``) would run under no test. Here the enhancement table and the
    registry's ``apply`` are replaced by fakes, so a non-empty resolved set reaches that body."""

    _FAKE = {"applied": ["fake_correction"], "skipped": [], "hook_points": []}

    def _forced_run(self) -> tuple[Path, str, list]:
        import contextlib
        from unittest import mock

        from arrayprobe import cli
        calls: list = []

        @contextlib.contextmanager
        def fake_apply(resolved):
            calls.append(dict(resolved))
            yield dict(self._FAKE)

        table = {"package": "installed", "requested": {}, "resolved": {"fake_correction": True},
                 "applied": [], "skipped": {}, "protective_mode": "on",
                 "protective_set": ["fake_correction"]}
        tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        p = _with(_write_config(tmp, ncdf=1), "\n[outputs]\nfaithful_attributed = true\n"
                                               "enhanced_attributed = true\n")
        with mock.patch.object(cli, "_soda2_enhancement_table", return_value=table), \
                mock.patch("arrayprobe_soda2_enhancements.registry.apply", fake_apply):
            rc, out, err = _run_cli(["soda2", "run", str(p)])
        self.assertEqual(rc, 0, err)
        return Path(tmp), out + err, calls

    def test_the_corrected_branch_runs_and_writes_every_enh_file(self):
        import json

        import netCDF4

        from arrayprobe.attributed_export import default_output_path
        out, log, calls = self._forced_run()
        # Reached, not skipped: the fake ran once, for the corrected pass only.
        self.assertNotIn("ENHANCED skipped", log)
        self.assertEqual(calls, [{"fake_correction": True}])
        enh_call = out / f"{_STEM}.enh.pbp.call"
        self.assertTrue(enh_call.is_file(), sorted(os.listdir(out)))
        record = json.loads(enh_call.read_text(encoding="utf-8"))
        self.assertEqual(record["enhancements"]["pass"], "corrected")
        self.assertEqual(record["enhancements"]["applied"], ["fake_correction"])
        for name in (f"{_STEM}.enh.pbp.csv", f"{_STEM}.enh.pbp.nc", f"{_STEM}.enh.nc"):
            self.assertTrue((out / name).is_file(), name)
        self.assertEqual(Path(record["outputs"]["pbp_csv"]), out / f"{_STEM}.enh.pbp.csv")
        self.assertEqual(Path(record["outputs"]["pbp_ncdf"]), out / f"{_STEM}.enh.pbp.nc")
        attributed = default_output_path(out / f"{_STEM}.enh.nc")
        self.assertTrue(attributed.is_file())
        # The attributed file's run record is the corrected pass's own `.enh.pbp.call`
        # (attributed_export finds it as `<stem>.enh.nc`.with_suffix(".pbp.call")).
        with netCDF4.Dataset(attributed) as ds:
            self.assertEqual(ds.getncattr("arrayprobe_run_record"),
                             enh_call.read_text(encoding="utf-8"))
        self.assertFalse((out / ".enh_pass").exists())

    def test_the_faithful_pass_is_untouched(self):
        import json
        out, _, _ = self._forced_run()
        faithful = json.loads((out / f"{_STEM}.pbp.call").read_text(encoding="utf-8"))
        self.assertEqual(faithful["enhancements"]["pass"], "faithful")
        self.assertEqual(faithful["enhancements"]["applied"], [])
        for name in (f"{_STEM}.pbp.csv", f"{_STEM}.pbp.nc", f"{_STEM}.nc"):
            self.assertTrue((out / name).is_file(), name)

    def test_every_enh_file_has_a_faithful_counterpart(self):
        out, _, _ = self._forced_run()
        names = set(os.listdir(out))
        enh = sorted(n for n in names if ".enh." in n)
        self.assertTrue(enh)
        missing = [n for n in enh if n.replace(".enh.", ".", 1) not in names]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
