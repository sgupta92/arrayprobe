# SPDX-License-Identifier: BSD-3-Clause
"""The SODA-2 CLI: ``arrayprobe soda2 run|enhancements``, the
``.pbp.call`` sidecar, and ``"soda2"`` as a third ``[run].engine``.

The SODA-2 engine is its own engine, not a UIOOPS version: ``arrayprobe run`` refuses it
with a pointer, ``--uiops-version`` does not gate it, and a config naming it must carry a
``[soda2]`` table (the driver's ``op`` fields). The sidecar records the enhancement table
-- with which corrections the driver adapter applied and which it skipped --
and is deterministic, so two runs of one config write identical bytes. Every flag the
subcommand takes is passed by a test here.

The optional package ``arrayprobe_soda2_enhancements`` **may or may not be installed** in the
shared venv, and nothing here may depend on which. It was absent when this module was written
and was installed on 2026-09-17, which is what ``.gitignore``'s documented
rebuild says to do -- and that change broke a test whose mock simulated absence
by blocking only the import, leaving ``importlib.metadata`` to answer truthfully underneath it.
``_without_the_package`` now blocks both doors, so the absent-package path is tested the same
way on either machine. Its *installed* path is exercised in a subprocess whose ``PYTHONPATH``
adds ``enhancements_soda2/src``, so importing it can never leak into another test module of the
same run. Skipped, by name, when that directory is absent (the port must pass without it).
"""
from __future__ import annotations

import ast
import builtins
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from importlib import metadata
from pathlib import Path
from unittest import mock

from arrayprobe import cli
from arrayprobe.config import ConfigError, load_config

DATA = Path(__file__).resolve().parent / "data"
FRAME_FIXTURE = DATA / "soda2_spec_frame_fixture"
_PORT_SRC = Path(cli.__file__).resolve().parents[1]
_ENH_SRC = _PORT_SRC.parents[1] / "enhancements_soda2" / "src"

_FID = '[fidelity]\nprofile = "STOCK_V314"\n'

# No `[fidelity]` table: the SODA-2 engine reads no FidelityProfile, and
# a soda2 config may not name one. The op values are
# `test_soda2_process_2d._base_op`'s, on the frame fixture the plan names.
_OP_TOML = """
[run]
engine = "soda2"

[soda2]
fn = {fn!r}
date = "20160906"
starttime = {starttime}
stoptime = {stoptime}
format = "SPEC"
subformat = 0
probetype = "2DS"
res = 10.0
endbins = [0.0, 50.0, 100.0, 200.0, 500.0]
arendbins = [0.0, 0.5, 1.0]
rate = 1.0
smethod = "xy"
pth = ""
particlefile = 1
inttime_reject = 0
stuckbits = 0
water = 0
fixedtas = 0.0
timeoffset = 0.0
armwidth = 6.3
numdiodes = 128
greythresh = 0
probeid = "H"
eawmethod = "centerin"
wavelength = 0.785e-6
dofconst = 8.12
ncdfparticlefile = {ncdf}
asciipsdfile = 0
shortname = "x1frame"
outdir = {outdir!r}
"""

#: `soda2_filename.pro`: `<date>_<hhmmss>_<shortname>_<probeid>` for a 2DS; 24240 s = 06:44:00.
_STEM = "20160906_064400_x1frame_H"


def _write_config(tmp: str, *, starttime: float = 24240.0, stoptime: float = 24250.0,
                  ncdf: int = 0, enhancements: str = "", outdir: str | None = None) -> Path:
    outdir = (tmp + os.sep) if outdir is None else outdir
    text = _OP_TOML.format(fn=str(FRAME_FIXTURE).replace("\\", "/"),
                           outdir=outdir.replace("\\", "/"), starttime=starttime,
                           stoptime=stoptime, ncdf=ncdf)
    if enhancements:
        text += "\n[enhancements]\n" + enhancements + "\n"
    p = Path(tmp) / "soda2.toml"
    p.write_text(text, encoding="utf-8")
    return p


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


@contextlib.contextmanager
def _without_the_package():
    """The package is absent: neither importable **nor** present in metadata.

    It used to block only ``import arrayprobe_soda2_enhancements``. That was an
    incomplete simulation, and it looked correct for as long as the package
    genuinely was not installed on the author's machine. When it was installed
    on 2026-09-17 -- which ``.gitignore``'s documented rebuild says to do
    -- the gap showed: the CLI's sidecar recorded ``package: "not
    installed"`` from the blocked import while ``versions`` reported
    ``0.0.0.dev0`` from ``importlib.metadata``, which the mock never touched. A
    sidecar cannot truthfully say both.

    A package that is not there has no distribution metadata either, so this
    blocks both doors. The guard now tests the same thing on a machine with the
    package and on one without -- which is the point of a mock.
    """
    real_import = builtins.__import__
    real_version = metadata.version

    def fake_import(name, *a, **k):
        if name.startswith("arrayprobe_soda2_enhancements"):
            raise ImportError(name)
        return real_import(name, *a, **k)

    def fake_version(dist, *a, **k):
        if dist == "arrayprobe-soda2-enhancements":
            raise metadata.PackageNotFoundError(dist)
        return real_version(dist, *a, **k)

    with mock.patch.object(builtins, "__import__", side_effect=fake_import), \
            mock.patch.object(metadata, "version", side_effect=fake_version):
        yield


def _run_with_the_package(argv: list[str]) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(_PORT_SRC), str(_ENH_SRC)])
    code = "import sys; from arrayprobe import cli; sys.exit(cli.main(sys.argv[1:]))"
    return subprocess.run([sys.executable, "-c", code, *argv], env=env, capture_output=True,
                          text=True, timeout=300)


def _registry_names_on_disk() -> set[str]:
    """What the package ships, read from its files -- the other side of the comparison."""
    return {p.stem for p in (_ENH_SRC / "arrayprobe_soda2_enhancements").glob("*.py")
            if p.stem != "registry" and not p.stem.startswith("_")}


class TheSoda2SubcommandExists(unittest.TestCase):
    def test_soda2_is_a_subcommand_with_run_and_enhancements(self):
        p = cli.build_parser()
        ns = p.parse_args(["soda2", "run", "x.toml", "--out", "o"])
        self.assertEqual((ns.command, ns.verb), ("soda2", "run"))
        self.assertEqual(ns.out, Path("o"))
        ns = p.parse_args(["soda2", "enhancements"])
        self.assertEqual((ns.command, ns.verb), ("soda2", "enhancements"))
        self.assertIsNone(ns.config)
        ns = p.parse_args(["soda2", "enhancements", "c.toml"])
        self.assertEqual(ns.config, Path("c.toml"))

    def test_a_verb_is_required(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.build_parser().parse_args(["soda2"])


class TheSplitLoopIsReachableAndOptIn(unittest.TestCase):
    """``soda2 run --jobs N`` splits ``soda2_process_2d``'s buffer loop.

    A resource knob, so it is a flag and not a ``[soda2]`` key -- a config file
    selects a run's science and never describes it, and
    ``op`` is the IDL struct, which has no such tag. Byte-identity is
    ``tests/test_soda2_parallel.py``'s subject; this only pins the surface."""

    def test_jobs_and_chunks_parse_and_default_to_serial(self):
        p = cli.build_parser()
        ns = p.parse_args(["soda2", "run", "x.toml"])
        self.assertEqual((ns.jobs, ns.chunks), (1, 0),
                         "the CLI default must be serial: the IDL has no parallelism")
        ns = p.parse_args(["soda2", "run", "x.toml", "--jobs", "6", "--chunks", "24"])
        self.assertEqual((ns.jobs, ns.chunks), (6, 24))

    def test_jobs_is_not_a_config_key(self):
        """Were it one, it would land in ``op`` and then in the ``.pbp.call``
        sidecar, making two runs of one configuration produce different
        records for the same numbers."""
        from arrayprobe_soda2.update_op import update_op
        tags = {str(k).lower() for k in update_op({
            "fn": "x", "date": "20160906", "starttime": 0.0, "stoptime": 1.0,
            "format": "SPEC", "probetype": "2DS", "res": 10.0, "yres": 10.0,
            "armwidth": 6.0, "numdiodes": 128, "shortname": "2DS", "probeid": "",
            "greythresh": 0, "wavelength": 0.658e-6, "dofconst": 3.0,
            "endbins": [10.0, 20.0, 30.0], "arendbins": [0.0, 0.5, 1.0],
        })}
        self.assertNotIn("jobs", tags)
        self.assertNotIn("chunks", tags)


class UiopsVersionDoesNotGateSoda2(unittest.TestCase):
    def test_soda2_is_exempt_from_the_unwired_engine_refusal(self):
        ns = cli.build_parser().parse_args(["--uiops-version", "3.5", "soda2", "enhancements"])
        self.assertIsNone(cli._refuse_unwired_engine(ns))

    def test_the_refusal_is_live_for_a_per_stage_command(self):
        """Control: without this, the exemption test above would pass on a refusal that
        refuses nothing."""
        import argparse
        ns = argparse.Namespace(command="imgproc", uiops_version="3.5")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli._refuse_unwired_engine(ns), 2)

    def test_soda2_enhancements_runs_end_to_end_under_uiops_version_3_5(self):
        with _without_the_package():
            rc, out, err = _run_cli(["--uiops-version", "3.5", "soda2", "enhancements"])
        self.assertEqual(rc, 0, err)
        self.assertIn("not installed", out)


class ConfigAcceptsSoda2Engine(unittest.TestCase):
    def test_engine_soda2_with_a_soda2_table_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(_write_config(tmp))
            self.assertEqual(cfg.run["engine"], "soda2")
            self.assertEqual(cfg.soda2["shortname"], "x1frame")
            self.assertEqual(cfg.soda2["endbins"], [0.0, 50.0, 100.0, 200.0, 500.0])
            self.assertEqual(cfg.soda2["starttime"], 24240.0)

    def test_engine_soda2_without_a_soda2_table_is_a_config_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "bare.toml"
            p.write_text('[run]\nengine = "soda2"\n', encoding="utf-8")
            with self.assertRaises(ConfigError) as cm:
                load_config(p)
            self.assertIn("[soda2]", str(cm.exception))

    def test_a_soda2_table_under_a_uiops_engine_is_a_config_error(self):
        """A UIOOPS run would ignore ``[soda2]``, so the file would say more than the run did
        -- the reason ``load_config`` refuses an unknown section."""
        for engine in ("3.1.4", "3.5"):
            with self.subTest(engine=engine), tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp) / "mixed.toml"
                p.write_text(_FID + f'[run]\nengine = "{engine}"\n[soda2]\nres = 10.0\n',
                             encoding="utf-8")
                with self.assertRaises(ConfigError) as cm:
                    load_config(p)
                self.assertIn("SODA-2 engine", str(cm.exception))

    def test_an_unknown_engine_is_still_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.toml"
            p.write_text(_FID + '[run]\nengine = "soda3"\n', encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(p)

    def test_a_uiops_config_has_an_empty_soda2_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "u.toml"
            p.write_text(_FID + '[run]\nengine = "3.5"\n', encoding="utf-8")
            self.assertEqual(load_config(p).soda2, {})


class ASoda2ConfigNamesNoProfile(unittest.TestCase):
    """Implemented as recommended; its adoption is **not yet confirmed**.
    The SODA-2 engine has one source tree and reads no FidelityProfile, so a
    soda2 config needs no ``[fidelity]`` and may not carry one (nor any other section the
    engine would ignore). Both states are pinned: required for a UIOOPS engine, refused here."""

    def test_a_soda2_config_loads_with_no_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(_write_config(tmp))
        self.assertIsNone(cfg.profile)
        self.assertEqual(cfg.run, {"engine": "soda2"})

    def test_a_uiops_config_still_requires_the_profile(self):
        for engine in ("3.1.4", "3.5"):
            with self.subTest(engine=engine), tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp) / "u.toml"
                p.write_text(f'[run]\nengine = "{engine}"\n', encoding="utf-8")
                with self.assertRaises(ConfigError) as cm:
                    load_config(p)
                self.assertIn("[fidelity].profile or [fidelity].authordefaults is required",
                              str(cm.exception))

    def test_a_fidelity_table_under_soda2_is_refused_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write_config(tmp)
            p.write_text(_FID + p.read_text(encoding="utf-8"), encoding="utf-8")
            with self.assertRaises(ConfigError) as cm:
                load_config(p)
            self.assertIn("'fidelity'", str(cm.exception))
            self.assertIn("one source tree", str(cm.exception))
            rc, _, err = _run_cli(["soda2", "run", str(p)])
            self.assertEqual(sorted(os.listdir(tmp)), ["soda2.toml"])
        self.assertEqual(rc, 2)
        self.assertIn("fidelity", err)

    def test_every_uiops_only_section_under_soda2_is_refused(self):
        """The class, not the instance: each would be silently ignored by ``soda2 run``."""
        extras = {"shattering": '[shattering]\nthreshold_file = "x.cdf"\n',
                  "masking": "[masking]\ndiodes = { base1 = [5] }\n",
                  "export": '[export]\nformat = "NETCDF4"\n',
                  "combine": "[combine]\nborrowed = true\n"}
        for name, text in extras.items():
            with self.subTest(section=name), tempfile.TemporaryDirectory() as tmp:
                p = _write_config(tmp)
                p.write_text(p.read_text(encoding="utf-8") + "\n" + text, encoding="utf-8")
                with self.assertRaises(ConfigError) as cm:
                    load_config(p)
                self.assertIn(f"'{name}'", str(cm.exception))

    def test_run_keys_other_than_engine_are_refused(self):
        for key, value in (("raw", '["a.2DS"]'), ("out", '"o"'), ("preset", '"P"'),
                           ("stages", '"234"'), ("tas_file", '"t.cdf"')):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as tmp:
                p = _write_config(tmp)
                text = p.read_text(encoding="utf-8").replace(
                    'engine = "soda2"\n', f'engine = "soda2"\n{key} = {value}\n', 1)
                p.write_text(text, encoding="utf-8")
                with self.assertRaises(ConfigError) as cm:
                    load_config(p)
                self.assertIn(key, str(cm.exception))
                self.assertIn("[soda2].fn", str(cm.exception))

    def test_a_soda2_table_with_no_engine_follows_the_soda2_rules(self):
        """``soda2 run`` defaults a missing engine to ``"soda2"``, so such a file is a SODA-2
        file: it loads without a profile, and a profile in it is refused."""
        with tempfile.TemporaryDirectory() as tmp:
            p = _write_config(tmp)
            text = p.read_text(encoding="utf-8").replace('[run]\nengine = "soda2"\n', "", 1)
            self.assertNotIn("[run]", text)
            p.write_text(text, encoding="utf-8")
            self.assertIsNone(load_config(p).profile)
            p.write_text(_FID + text, encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(p)

    def test_enhancement_switches_are_still_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write_config(tmp, enhancements="some_fix = 1")
            with self.assertRaises(ConfigError) as cm:
                load_config(p)
            self.assertIn("true/false", str(cm.exception))

    def test_run_flight_refuses_a_soda2_config_instead_of_crashing(self):
        """``RunConfig.profile`` is ``None`` for a soda2 file; ``scripts/run_flight.py``'s
        ``_apply_config`` reads ``cfg.profile.name``, so it must refuse first."""
        import argparse
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "run_flight", _PORT_SRC.parent / "scripts" / "run_flight.py")
        assert spec is not None and spec.loader is not None
        if "run_flight" in sys.modules:  # loaded by another module of the same run
            run_flight = sys.modules["run_flight"]
        else:
            # Registered before exec, as test_run_flight_config.py does: its dataclass needs it.
            run_flight = sys.modules.setdefault("run_flight", importlib.util.module_from_spec(spec))
            spec.loader.exec_module(run_flight)
        from tests import _run_flight_state
        _run_flight_state.preserve(self, run_flight)
        with tempfile.TemporaryDirectory() as tmp:
            args = argparse.Namespace(config=str(_write_config(tmp)))
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertIsNone(run_flight._apply_config(args, None, []))


class RunRefusesEngineSoda2UnderArrayprobeRun(unittest.TestCase):
    def test_arrayprobe_run_points_at_soda2_run_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfgp = _write_config(tmp)
            rc, _, err = _run_cli(["run", str(cfgp)])
            self.assertEqual(sorted(os.listdir(tmp)), ["soda2.toml"])
        self.assertEqual(rc, 2)
        self.assertIn(f"arrayprobe soda2 run {cfgp}", err)


class RunWritesTheCallSidecar(unittest.TestCase):
    def _run_once(self, tmp: str, **cfg_kw) -> tuple[Path, dict]:
        cfgp = _write_config(tmp, **cfg_kw)
        with _without_the_package():
            rc, out, err = _run_cli(["soda2", "run", str(cfgp), "--out", tmp])
        self.assertEqual(rc, 0, err)
        sidecar = Path(tmp) / f"{_STEM}.pbp.call"
        self.assertTrue(sidecar.exists(), (out, os.listdir(tmp)))
        # The name, not the full path: --out is resolved, so an 8.3 temp path comes back long.
        self.assertIn(sidecar.name, out)
        return sidecar, json.loads(sidecar.read_text(encoding="utf-8"))

    def test_pbp_nc_names_the_config_it_was_run_under(self):
        """In-file provenance: ``soda2 run`` passes the config's
        name as ``stamp_profile``, so ``.pbp.nc`` carries ``arrayprobe_profile =
        "config:soda2.toml"`` rather than ``"unstated"``; ``op`` does not gain it."""
        import netCDF4
        with tempfile.TemporaryDirectory() as tmp:
            _, rec = self._run_once(tmp, ncdf=1)
            self.assertNotIn("stamp_profile", rec["op"])
            with netCDF4.Dataset(rec["outputs"]["pbp_ncdf"], "r") as ds:
                got = (ds.getncattr("arrayprobe_engine"), ds.getncattr("arrayprobe_profile"))
        self.assertEqual(got, ("soda2", "config:soda2.toml"))

    def test_sidecar_has_the_stage_10_keys_and_records_not_applies(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, rec = self._run_once(tmp)
            self.assertEqual(set(rec), {"engine", "probe", "config_path", "op", "op_dtypes",
                                        "enhancements", "versions", "outputs"})
            self.assertEqual(rec["engine"], "soda2")
            self.assertEqual(rec["probe"], {"format": "SPEC", "probetype": "2DS",
                                            "subformat": 0})
            self.assertEqual(rec["config_path"], str((Path(tmp) / "soda2.toml").resolve()))
            self.assertEqual(rec["op"]["shortname"], "x1frame")
            # The sidecar records WHAT WAS ASKED FOR and what that resolved to.
            # With no [enhancements] table, nothing is requested, resolved or
            # applied -- and that is true whether or not the package is present.
            self.assertEqual(rec["enhancements"]["requested"], {})
            self.assertEqual(rec["enhancements"]["resolved"], {})
            self.assertEqual(rec["enhancements"]["applied"], [])
            self.assertEqual(rec["enhancements"]["skipped"], {})
            # The package line and its version are an ENVIRONMENT fact, not a
            # result. These two assertions pinned "not installed" and began
            # failing on 2026-09-17 when the package was installed into this
            # venv -- which `.gitignore`'s documented rebuild says to do.
            # The test was encoding an incidental state of one machine as
            # if it were the contract. What the contract actually requires is
            # that the two agree with each other, so that a sidecar can never
            # claim a package is absent while reporting its version.
            pkg = rec["enhancements"]["package"]
            version = rec["versions"]["arrayprobe-soda2-enhancements"]
            if pkg == "not installed":
                self.assertEqual("not installed", version)
            else:
                self.assertNotEqual("not installed", version)
                self.assertRegex(version, r"^\d")
            self.assertIn("arrayprobe", rec["versions"])
            self.assertNotIn("date_processed", json.dumps(rec))

    def test_outputs_name_the_files_on_disk_beside_the_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            sidecar, rec = self._run_once(tmp, ncdf=1)
            csv, nc = Path(rec["outputs"]["pbp_csv"]), Path(rec["outputs"]["pbp_ncdf"])
            self.assertEqual((csv.name, nc.name), (f"{_STEM}.pbp.csv", f"{_STEM}.pbp.nc"))
            for f in (csv, nc):
                self.assertTrue(f.is_file(), f)
                self.assertEqual(f.parent.resolve(), sidecar.parent.resolve())

    def test_a_writer_not_opened_is_recorded_as_null(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, rec = self._run_once(tmp)
            self.assertIsNone(rec["outputs"]["pbp_ncdf"])
            self.assertTrue(Path(rec["outputs"]["pbp_csv"]).is_file())

    def test_op_is_the_update_op_resolution_with_its_dtypes(self):
        """``op`` carries the fields ``soda2_update_op.pro`` defaulted (not only the file's),
        as JSON values, and ``op_dtypes`` keeps the NumPy type ``str()`` would have lost."""
        from arrayprobe_soda2.update_op import update_op
        with tempfile.TemporaryDirectory() as tmp:
            _, rec = self._run_once(tmp)
            cfg = load_config(Path(tmp) / "soda2.toml")
        resolved = update_op(dict(cfg.soda2, outdir=str(Path(tmp).resolve()) + os.sep))
        self.assertEqual(set(rec["op"]), set(resolved))
        self.assertGreater(len(rec["op"]), len(cfg.soda2))
        self.assertEqual(rec["op"]["seatag"], [33000, 0, 0])
        self.assertEqual(rec["op_dtypes"]["seatag"], "int32")
        for k, v in resolved.items():
            if hasattr(v, "dtype"):
                self.assertEqual(rec["op_dtypes"][k], str(v.dtype), k)
                self.assertNotIsInstance(rec["op"][k], str, k)

    def test_out_overrides_the_files_outdir(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as elsewhere:
            cfgp = _write_config(tmp, outdir=elsewhere + os.sep)
            with _without_the_package():
                rc, _, err = _run_cli(["soda2", "run", str(cfgp), "--out", tmp])
            self.assertEqual(rc, 0, err)
            self.assertTrue((Path(tmp) / f"{_STEM}.pbp.call").is_file())
            self.assertEqual(os.listdir(elsewhere), [])

    def test_without_out_the_files_outdir_is_used(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as there:
            cfgp = _write_config(tmp, outdir=there + os.sep)
            with _without_the_package():
                rc, _, err = _run_cli(["soda2", "run", str(cfgp)])
            self.assertEqual(rc, 0, err)
            # `.dat`: the IDL SAVE file (`savfile` defaults to 1), written
            # since the SAVE writer was ported -- before it the driver silently skipped it.
            self.assertEqual(sorted(os.listdir(there)),
                             [f"{_STEM}.dat", f"{_STEM}.pbp.call", f"{_STEM}.pbp.csv"])

    def test_an_out_directory_that_does_not_exist_yet_is_created_first(self):
        """The "--out trap" (examples/*_soda2/README.md): with particlefile = 1 the driver
        opens the per-particle CSV partway through, and a directory the CLI created only after
        the driver returned was not there yet -- FileNotFoundError, no products (2026-09-26)."""
        for via_flag in (True, False):
            with self.subTest(via_flag=via_flag), tempfile.TemporaryDirectory() as tmp:
                new = Path(tmp) / "not" / "yet"
                cfgp = _write_config(tmp, outdir=str(new) + os.sep)
                argv = ["soda2", "run", str(cfgp)] + (["--out", str(new)] if via_flag else [])
                with _without_the_package():
                    rc, _, err = _run_cli(argv)
                self.assertEqual(rc, 0, err)
                self.assertTrue((new / f"{_STEM}.pbp.csv").is_file())

    def test_two_runs_of_one_config_write_identical_sidecars(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, _ = self._run_once(tmp)
            b1 = first.read_bytes()
            second, _ = self._run_once(tmp)
            self.assertEqual(b1, second.read_bytes())

    def test_a_different_window_gets_its_own_sidecar(self):
        """The sidecar takes the PBP files' stem, so two windows into one directory do not
        overwrite each other's record (a bare ``<shortname>.pbp.call`` would)."""
        with tempfile.TemporaryDirectory() as tmp:
            self._run_once(tmp)
            cfgp = _write_config(tmp, starttime=24241.0)
            with _without_the_package():
                rc, _, err = _run_cli(["soda2", "run", str(cfgp), "--out", tmp])
            self.assertEqual(rc, 0, err)
            self.assertEqual(sorted(p.name for p in Path(tmp).glob("*.pbp.call")),
                             [f"{_STEM}.pbp.call", "20160906_064401_x1frame_H.pbp.call"])

    def test_an_empty_window_exits_1_and_writes_no_sidecar(self):
        """``soda2_process_2d.pro:430-433``: no buffers in the window, the driver returns
        nothing. The CLI says so and records nothing; the PBP header the driver opened first
        is S6-f's (preserved) business, not the CLI's."""
        with tempfile.TemporaryDirectory() as tmp:
            cfgp = _write_config(tmp, starttime=24300.0, stoptime=24310.0)
            with _without_the_package():
                rc, _, err = _run_cli(["soda2", "run", str(cfgp), "--out", tmp])
            self.assertEqual(list(Path(tmp).glob("*.pbp.call")), [])
        self.assertEqual(rc, 1)
        self.assertIn("returned no data", err)


class RunRefusesWhatItCannotRun(unittest.TestCase):
    def test_a_uiops_config_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "u.toml"
            p.write_text(_FID + '[run]\nengine = "3.5"\n', encoding="utf-8")
            rc, _, err = _run_cli(["soda2", "run", str(p)])
        self.assertEqual(rc, 2)
        self.assertIn("SODA-2 engine only", err)

    def test_a_config_with_no_engine_and_no_soda2_table_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "none.toml"
            p.write_text(_FID, encoding="utf-8")
            rc, _, err = _run_cli(["soda2", "run", str(p)])
        self.assertEqual(rc, 2)
        self.assertIn("no [soda2] table", err)

    def test_a_config_error_is_exit_2_not_a_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "bare.toml"
            p.write_text('[run]\nengine = "soda2"\n', encoding="utf-8")
            rc, _, err = _run_cli(["soda2", "run", str(p)])
        self.assertEqual(rc, 2)
        self.assertIn("[soda2]", err)

    def test_a_missing_config_file_is_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, _, err = _run_cli(["soda2", "run", str(Path(tmp) / "absent.toml")])
        self.assertEqual(rc, 2)
        self.assertIn("absent.toml", err)


class EnhancementsListsWithoutThePackage(unittest.TestCase):
    def test_lists_not_installed_when_the_import_fails(self):
        with _without_the_package():
            rc, out, _ = _run_cli(["soda2", "enhancements"])
        self.assertEqual(rc, 0)
        self.assertIn("package not installed", out)

    def test_a_config_is_accepted_and_still_reports_not_installed(self):
        with tempfile.TemporaryDirectory() as tmp, _without_the_package():
            rc, out, _ = _run_cli(["soda2", "enhancements", str(_write_config(tmp))])
        self.assertEqual(rc, 0)
        self.assertIn("package not installed", out)

    def test_the_files_opt_outs_are_recorded_even_without_the_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfgp = _write_config(tmp, enhancements="double_pi_fix = false")
            with _without_the_package():
                rc, _, err = _run_cli(["soda2", "run", str(cfgp), "--out", tmp])
            self.assertEqual(rc, 0, err)
            rec = json.loads((Path(tmp) / f"{_STEM}.pbp.call").read_text(encoding="utf-8"))
        self.assertEqual(rec["enhancements"]["requested"], {"double_pi_fix": False})
        self.assertEqual(rec["enhancements"]["resolved"], {})


@unittest.skipUnless(_ENH_SRC.is_dir(), "enhancements_soda2/src is not distributed with the "
                                        "package")
class EnhancementsWithThePackage(unittest.TestCase):
    """Subprocess, so the import never reaches this process's ``sys.modules``."""

    def test_lists_every_shipped_correction_with_its_reachability(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = _run_with_the_package(["soda2", "enhancements", str(_write_config(tmp))])
        self.assertEqual(r.returncode, 0, r.stderr)
        names = _registry_names_on_disk()
        self.assertGreater(len(names), 0)
        # Line 1 records the protective mode and set, line 2 is the table header.
        self.assertTrue(r.stdout.splitlines()[0].startswith("protective: mode=auto set="),
                        r.stdout)
        listed = {line.split()[0] for line in r.stdout.splitlines()[2:] if line.strip()}
        self.assertEqual(listed, names)
        for line in r.stdout.splitlines()[2:]:
            self.assertIn(line.split()[1], ("live", "latent", "flagged"), line)

    def test_run_applies_the_routable_corrections_and_records_the_rest(self):
        """Every resolved-ON correction is either applied (a
        driver-adapter route exists) or skipped with its reason; an OFF one is neither."""
        with tempfile.TemporaryDirectory() as tmp:
            cfgp = _write_config(tmp, enhancements="double_pi_fix = false")
            r = _run_with_the_package(["soda2", "run", str(cfgp), "--out", tmp])
            self.assertEqual(r.returncode, 0, r.stderr)
            rec = json.loads((Path(tmp) / f"{_STEM}.pbp.call").read_text(encoding="utf-8"))
        enh = rec["enhancements"]
        names = _registry_names_on_disk()
        self.assertEqual(enh["package"], "installed")
        self.assertEqual(set(enh["resolved"]), names)
        self.assertEqual(set(enh["reachability"]), names)
        self.assertIs(enh["resolved"]["double_pi_fix"], False)
        on = {n for n, v in enh["resolved"].items() if v}
        self.assertTrue(enh["applied"], "no correction was applied")
        self.assertEqual(set(enh["applied"]) | set(enh["skipped"]), on)
        self.assertFalse(set(enh["applied"]) & set(enh["skipped"]))
        for name, reason in enh["skipped"].items():
            self.assertTrue(reason and reason != "no driver adapter", name)
        self.assertIn("hook_points", enh)
        self.assertNotIn("double_pi_fix", enh["skipped"])
        self.assertNotIn("double_pi_fix", enh["applied"])

    def test_an_unknown_correction_name_is_exit_2_before_any_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfgp = _write_config(tmp, enhancements="no_such_fix = false")
            r = _run_with_the_package(["soda2", "run", str(cfgp), "--out", tmp])
            self.assertEqual(sorted(os.listdir(tmp)), ["soda2.toml"])
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("no_such_fix", r.stderr)


class TheCliNeverImportsTheSoda2PackageUnguarded(unittest.TestCase):
    """``test_no_enhancement_coupling``'s SODA-2 half sweeps ``src/arrayprobe_soda2`` only, and
    ``test_no_enhancement_coupling`` looks for ``arrayprobe_enhancements`` only -- neither
    sees ``cli.py``'s new reference. Same visitor, ``src/arrayprobe`` as the root."""

    def _offenders_and_hits(self):
        from tests.test_no_enhancement_coupling import (
            _SODA2_ENHANCEMENTS_ROOT,
            _EnhancementReferenceVisitor,
        )

        offenders: list[str] = []
        guarded_hits = 0
        for path in (_PORT_SRC / "arrayprobe").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            v = _EnhancementReferenceVisitor(_SODA2_ENHANCEMENTS_ROOT)
            v.visit(ast.parse(text))
            offenders += [f"{path.name}:{n}" for n in v.unguarded_linenos]
            guarded_hits += text.count("import arrayprobe_soda2_enhancements")
        return offenders, guarded_hits

    def test_every_reference_in_the_port_package_is_import_error_guarded(self):
        offenders, hits = self._offenders_and_hits()
        self.assertEqual(offenders, [])
        self.assertGreater(hits, 0, "the sweep found no reference at all: it tests nothing")


class ProcessDataNamesItsOutputs(unittest.TestCase):
    def test_pbp_paths_default_to_none(self):
        import dataclasses

        from arrayprobe_soda2.process_2d import ProcessData
        fields = {f.name: f for f in dataclasses.fields(ProcessData)}
        self.assertIsNone(fields["pbp_csv_path"].default)
        self.assertIsNone(fields["pbp_ncdf_path"].default)


if __name__ == "__main__":
    unittest.main()
