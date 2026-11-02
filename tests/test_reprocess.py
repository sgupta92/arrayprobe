# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe reprocess`` (``scripts/reprocess.py``): re-running a product's stage from
its
own ``.call`` stamp reproduces a direct run exactly, on both engines, and refuses whatever it
cannot re-run as recorded.

The two sides come from different places: the product is written by a **direct run** of the
tracked demo flight (``tests/data/demo_flight_v314_raw.2DS``) -- for v3.1.4 through the driver's
stage functions at their module defaults, as ``scripts/make_demo_reference.py``'s ``build`` does;
for v3.5 through the user's own command line, ``python -m arrayprobe.cli run <toml> <raw>``, in a
subprocess -- and the fresh file by the reprocess, which loads its own private copy of the driver
and is told nothing but the product path and the preset.

The identity check is shown to be non-vacuous by mutating the product (one stored value, one global
attribute, the input basename) and watching it fire, and by mutating the *comparator* rule the
other way (``Creation Time``) and watching it stay silent -- the exclusion is exactly the declared
set, no wider.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent / "scripts"
SRC = HERE.parent / "src"
DATA = HERE / "data"
RAW = DATA / "demo_flight_v314_raw.2DS"
AIRCRAFT = DATA / "demo_flight_v35_aircraft.cdf"
STEM = "base160101000000"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


rp = _load(TOOLS / "reprocess.py", "_test_reprocess_tool")

from tests._repo import needs_v314_engine  # noqa: E402

from arrayprobe import cli  # noqa: E402

V35_TOML = """\
[fidelity]
profile = "stock-v3.5"

[run]
engine = "3.5"
preset = "DEMO_2DS_H"
out = "_decoded"
stages = "234"
tas_file = "demo_flight_v35_aircraft.cdf"
"""


def _direct_run_v314(out: Path) -> Path:
    """S2 -> S3 -> S4 of the tracked demo flight, through a private driver copy at its module
    defaults (preset ORACLES_2016_2DS_H, profile oracles-production, the production twelfth
    argument) -- ``make_demo_reference.build`` without the 68 MB combine."""
    drv = _load(TOOLS / "run_flight.py", "_test_reprocess_direct_run_flight")
    try:
        drv.log = lambda *a, **kw: None
        raw = out / f"{STEM}.2DS"
        shutil.copyfile(RAW, raw)
        image = drv.stage2(raw, out)
        proc = drv.stage3(image, out)
        drv.stage4(proc, raw.stem, out)
    finally:
        sys.modules.pop("_test_reprocess_direct_run_flight", None)
    return out


def _direct_run_v35(out: Path) -> Path:
    """The user's command line, in a subprocess, against this checkout's ``src``."""
    shutil.copyfile(RAW, out / f"{STEM}.2DS")
    shutil.copyfile(AIRCRAFT, out / AIRCRAFT.name)
    toml = out / "run.toml"
    toml.write_text(V35_TOML, encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(
        [str(SRC), *filter(None, [os.environ.get("PYTHONPATH")])]))
    done = subprocess.run([sys.executable, "-m", "arrayprobe.cli", "run", str(toml),
                           str(out / f"{STEM}.2DS")], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=600, env=env)
    if done.returncode != 0:
        raise RuntimeError(f"direct v3.5 run failed rc={done.returncode}\n{done.stdout}\n"
                           f"{done.stderr}")
    return out / "_decoded"


def _bump_first_element(path: Path, name: str) -> None:
    """Add one to the first stored element of ``name`` -- the smallest possible content change."""
    with netCDF4.Dataset(str(path), "a") as ds:
        var = ds.variables[name]
        var.set_auto_maskandscale(False)
        first = (slice(0, 1),) * var.ndim
        var[first] = np.asarray(var[first]) + 1


class _Flight(unittest.TestCase):
    """One direct run per class; each test reprocesses a private copy of its directory."""

    flight: Path
    preset: str
    _tmp: tempfile.TemporaryDirectory

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def copy(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        dest = Path(tmp.name) / "flight"
        shutil.copytree(self.flight, dest)
        return dest

    def sd(self, d: Path) -> Path:
        return d / f"sd.{STEM}.H.nc"

    def proc(self, d: Path) -> Path:
        return d / f"proc.{STEM}.H.nc"

    def cli(self, *argv) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(["reprocess", *map(str, argv)])
        return rc, out.getvalue(), err.getvalue()


@needs_v314_engine
class ReprocessV314(_Flight):
    preset = "ORACLES_2016_2DS_H"

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.flight = _direct_run_v314(Path(cls._tmp.name))

    # -- identity -------------------------------------------------------------------------------

    def test_sd_reprocesses_identical_to_the_direct_run(self):
        d = self.copy()
        result = rp.reprocess(self.sd(d), preset=self.preset)
        self.assertEqual((result.stage, result.engine), ("S4", "3.1.4"))
        self.assertEqual(result.differences, [])

    def test_proc_reprocesses_identical_to_the_direct_run(self):
        d = self.copy()
        result = rp.reprocess(self.proc(d), preset=self.preset)
        self.assertEqual((result.stage, result.engine), ("S3", "3.1.4"))
        self.assertEqual(result.differences, [])

    def test_the_command_line_exits_0_and_says_identical(self):
        rc, out, _ = self.cli(self.sd(self.copy()), "--preset", self.preset)
        self.assertEqual(rc, 0, out)
        self.assertIn("IDENTICAL", out)

    def test_the_product_is_never_modified(self):
        d = self.copy()
        before = self.sd(d).read_bytes(), Path(f"{self.sd(d)}.call").read_bytes()
        rp.reprocess(self.sd(d), preset=self.preset)
        self.assertEqual(before, (self.sd(d).read_bytes(), Path(f"{self.sd(d)}.call").read_bytes()))

    # -- the mutations that make the identity check fire ----------------------------------------

    def test_a_mutated_stored_value_is_reported_and_exits_1(self):
        d = self.copy()
        _bump_first_element(self.sd(d), "count")
        result = rp.reprocess(self.sd(d), preset=self.preset)
        self.assertEqual(len(result.differences), 1, result.differences)
        self.assertIn("/count: stored values differ (1 element(s))", result.differences[0])
        rc, out, _ = self.cli(self.sd(d), "--preset", self.preset)
        self.assertEqual(rc, 1)
        self.assertIn("DIFFERS", out)

    def test_a_mutated_global_attribute_is_reported(self):
        d = self.copy()
        with netCDF4.Dataset(str(self.sd(d)), "a") as ds:
            name = next(a for a in ds.ncattrs() if a not in rp.VOLATILE_ATTRS | rp.PATH_ATTRS)
            ds.setncattr(name, str(ds.getncattr(name)) + "x")
        result = rp.reprocess(self.sd(d), preset=self.preset)
        self.assertEqual([f"<global>@{name}" in x for x in result.differences], [True])

    def test_a_different_input_basename_is_reported_not_excluded(self):
        d = self.copy()
        with netCDF4.Dataset(str(self.sd(d)), "a") as ds:
            ds.setncattr("Data Source", "/elsewhere/proc.base999999999999.H.nc")
        result = rp.reprocess(self.sd(d), preset=self.preset)
        self.assertEqual(len(result.differences), 1)
        self.assertIn("Data Source: input basename differs", result.differences[0])

    def test_creation_time_alone_is_excluded(self):
        """The control: the exclusion is exactly the declared volatile set."""
        d = self.copy()
        with netCDF4.Dataset(str(self.sd(d)), "a") as ds:
            ds.setncattr("Creation Time", "01-Jan-1970 00:00:00")
        self.assertEqual(rp.reprocess(self.sd(d), preset=self.preset).differences, [])

    def test_a_wrong_preset_of_the_same_channel_shows_in_the_diff(self):
        """The preset is not stamped; naming the wrong one is caught by the diff, not trusted."""
        result = rp.reprocess(self.sd(self.copy()), preset="DEMO_2DS_H")
        self.assertIn("<global>@Project: 'DEMO' vs 'ORACLES'", result.differences)

    # -- refusals: nothing is run under a configuration the stamp does not record ---------------

    def assertRefused(self, fn, fragment):
        with self.assertRaises(rp.ReprocessRefused) as ctx:
            fn()
        self.assertIn(fragment, str(ctx.exception))

    def test_a_stamp_the_driver_would_not_write_is_refused_naming_both(self):
        d = self.copy()
        call = Path(f"{self.sd(d)}.call")
        call.write_text(call.read_text().replace("max_edge_img_ar=4", "max_edge_img_ar=5"))
        self.assertRefused(lambda: rp.reprocess(self.sd(d), preset=self.preset),
                           "cannot be re-run as recorded")
        rc, _, err = self.cli(self.sd(d), "--preset", self.preset)
        self.assertEqual(rc, 2)
        self.assertIn("REFUSED", err)

    def test_an_unstamped_product_is_refused(self):
        d = self.copy()
        Path(f"{self.sd(d)}.call").unlink()
        self.assertRefused(lambda: rp.reprocess(self.sd(d), preset=self.preset), "no .call")

    def test_an_unregistered_profile_is_refused(self):
        d = self.copy()
        call = Path(f"{self.proc(d)}.call")
        call.write_text(call.read_text().replace("profile=oracles-production",
                                                 "profile=no-such-profile"))
        self.assertRefused(lambda: rp.reprocess(self.proc(d), preset=self.preset),
                           "not registered")

    def test_an_s4_input_with_a_different_stamp_is_refused_by_stage4s_own_check(self):
        d = self.copy()
        Path(f"{self.proc(d)}.call").write_text(
            "profile=stock-v3.1.4 reject=() shadow_diode=none\n")
        self.assertRefused(lambda: rp.reprocess(self.sd(d), preset=self.preset),
                           "run S3 for it again")

    def test_an_s4_input_with_no_stamp_is_refused(self):
        d = self.copy()
        Path(f"{self.proc(d)}.call").unlink()
        self.assertRefused(lambda: rp.reprocess(self.sd(d), preset=self.preset),
                           "carries no .call sidecar")

    def test_an_s3_input_image_with_no_stamp_is_refused(self):
        d = self.copy()
        Path(f"{d / STEM}.H.cdf.call").unlink()
        self.assertRefused(lambda: rp.reprocess(self.proc(d), preset=self.preset), "unstamped")

    def test_a_missing_input_is_refused(self):
        d = self.copy()
        self.proc(d).unlink()
        self.assertRefused(lambda: rp.reprocess(self.sd(d), preset=self.preset),
                           "the proc file S4 reads")

    def test_a_preset_of_another_channel_is_refused_by_the_name(self):
        self.assertRefused(lambda: rp.reprocess(self.sd(self.copy()), preset="ORACLES_2017_2DS_V"),
                           "would be named")

    def test_a_tas_file_the_stamp_does_not_name_is_refused(self):
        self.assertRefused(lambda: rp.reprocess(self.proc(self.copy()), preset=self.preset,
                                                tas_file=AIRCRAFT), "no aircraft file")

    def test_s2_and_s4c_products_are_refused_by_name(self):
        d = self.copy()
        self.assertRefused(lambda: rp.reprocess(d / f"{STEM}.H.cdf", preset=self.preset),
                           "only a proc.* (S3) or sd.* (S4)")

    def test_a_disagreeing_uiops_version_is_refused(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(["--uiops-version", "3.5", "reprocess", str(self.sd(self.copy())),
                           "--preset", self.preset])
        self.assertEqual(rc, 2)
        self.assertIn("disagrees", err.getvalue())

    def test_preset_is_required_on_the_command_line(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.build_parser().parse_args(["reprocess", "sd.x.H.nc"])

    # -- isolation --------------------------------------------------------------------------------

    def test_the_shared_driver_module_is_never_touched(self):
        before = sys.modules.get("run_flight")
        rp.reprocess(self.sd(self.copy()), preset="DEMO_2DS_H")
        self.assertIs(sys.modules.get("run_flight"), before)
        self.assertEqual([m for m in sys.modules if m.startswith("_reprocess_run_flight_")], [])


class ReprocessV35(_Flight):
    preset = "DEMO_2DS_H"

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.flight = _direct_run_v35(Path(cls._tmp.name))

    def copy(self) -> Path:
        d = super().copy()
        # S3 reads the aircraft file; it lives beside the config, not in the output directory.
        shutil.copyfile(AIRCRAFT, d / AIRCRAFT.name)
        return d

    def test_sd_reprocesses_identical_to_the_users_own_run(self):
        result = rp.reprocess(self.sd(self.copy()), preset=self.preset)
        self.assertEqual((result.stage, result.engine), ("S4", "3.5"))
        self.assertEqual(result.differences, [])

    def test_an_sd_rerun_prints_no_warning_about_the_aircraft_file_it_never_needs(self):
        """S4 never reads the aircraft file, but its TAS QC sidecar did, by the stamp's bare
        basename, so every v3.5 sd re-run logged "S4 TAS QC record not written: cannot read
        demo_flight_v35_aircraft.cdf" from whatever directory it ran in (2026-09-26)."""
        lines: list[str] = []
        with tempfile.TemporaryDirectory() as elsewhere:
            cwd = os.getcwd()
            os.chdir(elsewhere)
            try:
                result = rp.reprocess(self.sd(self.copy()), preset=self.preset,
                                      log=lambda msg, *a, **k: lines.append(str(msg)))
            finally:
                os.chdir(cwd)
        self.assertEqual(result.differences, [])
        self.assertFalse([m for m in lines if "TAS QC record not written" in m], lines)

    def test_proc_reprocesses_identical_given_the_stamped_aircraft_file(self):
        d = self.copy()
        result = rp.reprocess(self.proc(d), preset=self.preset, tas_file=d / AIRCRAFT.name)
        self.assertEqual((result.stage, result.engine), ("S3", "3.5"))
        self.assertEqual(result.differences, [])

    def test_a_mutated_stored_value_is_reported(self):
        d = self.copy()
        _bump_first_element(self.proc(d), "image_area")
        result = rp.reprocess(self.proc(d), preset=self.preset, tas_file=d / AIRCRAFT.name)
        self.assertEqual(len(result.differences), 1, result.differences)
        self.assertIn("/image_area: stored values differ", result.differences[0])

    def test_s3_without_the_aircraft_file_is_refused(self):
        with self.assertRaises(rp.ReprocessRefused) as ctx:
            rp.reprocess(self.proc(self.copy()), preset=self.preset)
        self.assertIn("pass --tas-file", str(ctx.exception))

    def test_an_aircraft_file_of_another_name_is_refused(self):
        d = self.copy()
        other = d / "other_aircraft.cdf"
        shutil.copyfile(AIRCRAFT, other)
        with self.assertRaises(rp.ReprocessRefused) as ctx:
            rp.reprocess(self.proc(d), preset=self.preset, tas_file=other)
        self.assertIn("is not the stamped", str(ctx.exception))

    def test_a_changed_v35_call_switch_is_refused(self):
        d = self.copy()
        call = Path(f"{self.sd(d)}.call")
        call.write_text(call.read_text().replace("iSaveIntArrSV=0", "iSaveIntArrSV=1"))
        with self.assertRaises(rp.ReprocessRefused):
            rp.reprocess(self.sd(d), preset=self.preset)


def _direct_run_chain(out: Path, *argv: str) -> Path:
    """A TAS source-chain run of the demo flight through ``scripts/run_flight.py``'s own command
    line, in a subprocess: the chain resolves after S2 and writes ``<stem>.tas_<tier>.cdf`` beside
    the products, which S3 (when the profile reads an aircraft file) and S4 then consume."""
    shutil.copyfile(RAW, out / f"{STEM}.2DS")
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(
        [str(SRC), *filter(None, [os.environ.get("PYTHONPATH")])]))
    decoded = out / "_decoded"
    done = subprocess.run([sys.executable, str(TOOLS / "run_flight.py"), *argv,
                           "--tas-source", "probe", "--out", str(decoded), "--yes",
                           str(out / f"{STEM}.2DS")], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=600, env=env)
    if done.returncode != 0:
        raise RuntimeError(f"direct chain run failed rc={done.returncode}\n{done.stdout}\n"
                           f"{done.stderr}")
    return decoded


CHAIN_FILE = f"{STEM}.tas_probe.cdf"


class ReprocessChainV35(_Flight):
    """A v3.5 product sized on a probe-tier TAS chain, on the regular one-second grid: every
    chain key reaches both stamps (``tas_file=``, ``tas_chain=``, ``tas_policy=``, and in S4
    ``tas_series=`` and ``tas_grid=regular``)."""

    preset = "DEMO_2DS_H"

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.flight = _direct_run_chain(Path(cls._tmp.name), "--preset", "DEMO_2DS_H",
                                       "--engine", "3.5", "--profile", "stock-v3.5",
                                       "--tas-grid", "regular")

    def test_the_direct_run_stamped_the_chain(self):
        """The control: these products really carry the chain keys the parse must separate."""
        stamp = Path(f"{self.sd(self.flight)}.call").read_text()
        for key in (f"tas_file={CHAIN_FILE} ", "tas_chain=probe:", "tas_policy=(",
                    "tas_grid=regular"):
            self.assertIn(key, stamp)

    def test_sd_reprocesses_identical(self):
        result = rp.reprocess(self.sd(self.copy()), preset=self.preset)
        self.assertEqual((result.stage, result.engine), ("S4", "3.5"))
        self.assertEqual(result.differences, [])

    def test_proc_reprocesses_identical_from_the_chain_file_beside_it(self):
        result = rp.reprocess(self.proc(self.copy()), preset=self.preset)
        self.assertEqual((result.stage, result.engine), ("S3", "3.5"))
        self.assertEqual(result.differences, [])

    def test_the_command_line_exits_0_on_a_chain_product(self):
        rc, out, err = self.cli(self.sd(self.copy()), "--preset", self.preset)
        self.assertEqual(rc, 0, out + err)
        self.assertIn("IDENTICAL", out)

    def test_a_changed_chain_series_shows_in_the_proc_diff(self):
        """Non-vacuity: S3 really reads the chain file beside the product, so halving its
        airspeed changes the fresh proc file. (The demo flight's sd file sizes no particle into
        any bin, so its bytes cannot show a changed airspeed; the next test covers S4.)"""
        d = self.copy()
        with netCDF4.Dataset(str(d / CHAIN_FILE), "a") as ds:
            ds.variables["TAS"][:] = np.asarray(ds.variables["TAS"][:]) * 0.5
        result = rp.reprocess(self.proc(d), preset=self.preset)
        self.assertNotEqual(result.differences, [])

    def test_s4_is_handed_the_chain_files_series_and_the_stamped_policy_and_grid(self):
        d = self.copy()
        with netCDF4.Dataset(str(d / CHAIN_FILE), "a") as ds:
            ds.variables["TAS"][:] = np.asarray([101.0, 102.0, 103.0, 104.0])
        cfg = rp.parse_stamp(Path(f"{self.sd(d)}.call").read_text(), "S4")
        with rp._private_driver() as drv:
            rp._restore_chain(drv, self.sd(d), STEM, cfg)
            self.assertEqual(drv.TAS_CHAIN.tas.tolist(), [101.0, 102.0, 103.0, 104.0])
            self.assertEqual((drv.TAS_CHAIN.tier, drv.TAS_CHAIN.source),
                             ("probe", "probe-tas-csv"))
            self.assertEqual(drv.TAS_POLICY.token(), "cutoff=300.0,default=170.0")
            self.assertEqual(drv.TAS_GRID, "regular")
            _t, tas, _missing = drv._chain_series_for_sizedist(
                drv.load_tas_info(d / f"{STEM}.tas.csv")[0], "test")
            self.assertEqual(tas.tolist(), [101.0, 102.0, 103.0, 104.0])

    def test_a_missing_chain_file_is_refused_naming_it(self):
        d = self.copy()
        (d / CHAIN_FILE).unlink()
        with self.assertRaises(rp.ReprocessRefused) as ctx:
            rp.reprocess(self.sd(d), preset=self.preset)
        msg = str(ctx.exception)
        self.assertIn(CHAIN_FILE, msg)
        self.assertIn("by name only", msg)

    def test_a_chain_file_recording_another_chain_is_refused(self):
        d = self.copy()
        with netCDF4.Dataset(str(d / CHAIN_FILE), "a") as ds:
            ds.setncattr("tas_chain_used", "merge:oracles-merge")
        with self.assertRaises(rp.ReprocessRefused) as ctx:
            rp.reprocess(self.sd(d), preset=self.preset)
        self.assertIn("merge:oracles-merge", str(ctx.exception))


@needs_v314_engine
class ReprocessChainV314(_Flight):
    """A v3.1.4 product whose profile reads no aircraft file: the chain reaches only the sd stamp,
    as ``tas_series=`` and ``tas_series_policy=``."""

    preset = "ORACLES_2016_2DS_H"

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.flight = _direct_run_chain(Path(cls._tmp.name), "--preset", cls.preset,
                                       "--engine", "3.1.4", "--port-validation")

    def test_the_direct_run_stamped_the_chain(self):
        stamp = Path(f"{self.sd(self.flight)}.call").read_text()
        self.assertIn("tas_series=probe:", stamp)
        self.assertIn("tas_series_policy=(", stamp)

    def test_sd_reprocesses_identical(self):
        result = rp.reprocess(self.sd(self.copy()), preset=self.preset)
        self.assertEqual((result.stage, result.engine), ("S4", "3.1.4"))
        self.assertEqual(result.differences, [])


class ParseStamp(unittest.TestCase):
    """The parse only proposes; these pin that it proposes the right thing from real stamps."""

    NO_CHAIN = {"tas_chain": None, "tas_policy": None, "tas_grid": None}

    def test_the_tracked_v314_sd_stamp(self):
        got = rp.parse_stamp((DATA / "demo_flight_v314_sd.call").read_text(), "S4")
        self.assertEqual(got, {"engine": "3.1.4", "iat_file": "2DS_intArrThreshold_MISSING.cdf",
                               "port_validation": False, "profile_name": "oracles-production",
                               "shadow_diode": None,
                               "tas_file_name": None, "stray_pixel": None,
                               # A 2D-S stamp carries no ncar_2dc_timing= key (probetype 0 only).
                               "ncar_2dc_timing": None, **self.NO_CHAIN})

    def test_the_tracked_v35_sd_stamp(self):
        got = rp.parse_stamp((DATA / "demo_flight_v35_sd.call").read_text(), "S4")
        self.assertEqual(got, {"engine": "3.5", "iat_file": None, "port_validation": False,
                               "profile_name": "stock-v3.5",
                               "shadow_diode": None,
                               # Regenerated with the default-on stray-pixel correction.
                               "tas_file_name": "demo_flight_v35_aircraft.cdf",
                               "stray_pixel": "on:g8,n2,m9", "ncar_2dc_timing": None,
                               **self.NO_CHAIN})

    def test_the_stray_pixel_switch_is_read_from_the_stamp(self):
        """A default engine-3.5 stamp records the stray-pixel correction as on with its
        parameters; reprocess restores the switch from it, so the value must reach the config."""
        stamp = ("engine=3.5 iat_file=<none> profile=stock-v3.5 reject=(rej_zero_area=True) "
                 "shadow_diode=none tas_file=<none> software=UIOOPS_v3.5 "
                 "stray_pixel=on:g8,n2,m9 sizedist=(iaThreshType=0)")
        self.assertEqual(rp.parse_stamp(stamp, "S4")["stray_pixel"], "on:g8,n2,m9")
        self.assertEqual(rp.parse_stamp(stamp.replace("on:g8,n2,m9", "off"), "S4")["stray_pixel"],
                         "off")

    def test_a_chain_stamp_reads_each_key_on_its_own(self):
        """A chain run's stamp carries ``tas_chain=``/``tas_policy=`` after ``tas_file=``; the
        file name must stop at the next key rather than run on through them."""
        stamp = ("engine=3.5 iat_file=<none> profile=stock-v3.5 reject=(rej_zero_area=True) "
                 f"shadow_diode=none tas_file={CHAIN_FILE} tas_chain=probe:probe-tas-csv "
                 "tas_policy=(cutoff=300.0,default=170.0) call=(iQC=0,tas_ratio=off) "
                 "software=UIOOPS_v3.5 sizedist=(iSaveIntArrSV=0) tas_series=probe:probe-tas-csv "
                 "tas_grid=regular")
        got = rp.parse_stamp(stamp, "S4")
        self.assertEqual((got["tas_file_name"], got["tas_chain"], got["tas_policy"],
                          got["tas_grid"]),
                         (CHAIN_FILE, "probe:probe-tas-csv", "cutoff=300.0,default=170.0",
                          "regular"))

    def test_a_chain_stamp_without_an_aircraft_file_reads_the_series_keys(self):
        stamp = ("engine=3.1.4 iat_file=2DS_intArrThreshold_MISSING.cdf "
                 "profile=oracles-production reject=(rej_hollow=False) shadow_diode=none "
                 "tree=production area_ratio_z=0.5 (default) "
                 "default_int_arr_thresh=6e-06 (default) "
                 "tas_series=probe:probe-tas-csv tas_series_policy=(cutoff=300.0,default=170.0)")
        got = rp.parse_stamp(stamp, "S4")
        self.assertEqual((got["tas_file_name"], got["tas_chain"], got["tas_policy"]),
                         (None, "probe:probe-tas-csv", "cutoff=300.0,default=170.0"))

    def test_the_tracked_v35_proc_stamp(self):
        got = rp.parse_stamp((DATA / "demo_flight_v35_proc.call").read_text(), "S3")
        self.assertEqual((got["engine"], got["tas_file_name"]),
                         ("3.5", "demo_flight_v35_aircraft.cdf"))

    def test_a_diode_mask_and_a_trailing_tas_file(self):
        got = rp.parse_stamp("profile=stock-v3.1.4 reject=() shadow_diode=77,95 "
                             "tas_file=a b.cdf", "S3")
        self.assertEqual((got["shadow_diode"], got["tas_file_name"]), ([77, 95], "a b.cdf"))

    def test_an_sd_stamp_offered_as_a_proc_stamp_is_refused(self):
        with self.assertRaises(rp.ReprocessRefused):
            rp.parse_stamp((DATA / "demo_flight_v314_sd.call").read_text(), "S3")

    def test_an_unrecognised_stamp_is_refused(self):
        with self.assertRaises(rp.ReprocessRefused):
            rp.parse_stamp("not a stamp at all", "S4")

    def test_an_engine_prefixed_v314_stamp_parses(self):
        """Since 2026-09-15 (R4s) a freshly-written v3.1.4 stamp leads with
        ``engine=3.1.4 ``; the rest of it must still parse."""
        got = rp.parse_stamp("engine=3.1.4 iat_file=2DS_intArrThreshold_MISSING.cdf "
                             "profile=oracles-production reject=(rej_zero_area=True) "
                             "shadow_diode=none", "S4")
        self.assertEqual((got["engine"], got["iat_file"], got["profile_name"]),
                         ("3.1.4", "2DS_intArrThreshold_MISSING.cdf", "oracles-production"))

    def test_a_stamp_with_no_engine_key_reads_as_3_1_4(self):
        """An older stamp (before R4s) has no engine= key at all."""
        got = rp.parse_stamp("iat_file=<none> profile=stock-v3.1.4 reject=() "
                             "shadow_diode=none", "S4")
        self.assertEqual(got["engine"], "3.1.4")


if __name__ == "__main__":
    unittest.main()
