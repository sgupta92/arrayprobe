# SPDX-License-Identifier: BSD-3-Clause
"""``[outputs]`` -- the config file selects which of a run's three artefacts it owes.

Slice S1. Two sides:
the loader (``arrayprobe.config``) accepts only the keys whose effect is built and refuses
anything else by name; the driver (``run_flight._apply_config``) turns
``faithful_attributed = true`` into ``--attributed``, lets the command line win over ``false``,
and leaves ``args`` exactly as given when the section is absent -- the default path's
byte-identity rests on that last case, since ``--attributed`` off writes no sibling at all.
"""

from __future__ import annotations

import datetime as _dt
import importlib.util
import io
import sys
import tempfile
import unittest
from collections.abc import Sequence
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from arrayprobe import attributed_export as ae
from arrayprobe import config

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("run_flight", ROOT / "scripts" / "run_flight.py")
run_flight = importlib.util.module_from_spec(spec)
sys.modules.setdefault(spec.name, run_flight)
spec.loader.exec_module(run_flight)

from tests._profile_registry_guard import module_hooks  # noqa: E402
from tests._repo import repo_only  # noqa: E402

setUpModule, tearDownModule = module_hooks()

BASE_V35 = '[fidelity]\nprofile = "stock-v3.5"\n[run]\nengine = "3.5"\n'


def _toml(text: str) -> Path:
    path = Path(tempfile.mkdtemp()) / "run.toml"
    path.write_text(text, encoding="utf-8")
    return path


def _load(text: str) -> config.RunConfig:
    return config.load_config(_toml(text))


class TheLoaderSelectsOnlyWhatIsBuilt(unittest.TestCase):
    def test_absent_section_is_empty(self):
        self.assertEqual(_load(BASE_V35).outputs, {})

    def test_the_built_key_loads_both_ways(self):
        self.assertEqual(_load(BASE_V35 + "[outputs]\nfaithful_attributed = true\n").outputs,
                         {"faithful_attributed": True})
        self.assertEqual(_load(BASE_V35 + "[outputs]\nfaithful_attributed = false\n").outputs,
                         {"faithful_attributed": False})

    def test_a_non_boolean_is_refused_not_coerced(self):
        with self.assertRaises(config.ConfigError) as caught:
            _load(BASE_V35 + '[outputs]\nfaithful_attributed = "yes"\n')
        self.assertIn("[outputs].faithful_attributed must be true/false", str(caught.exception))

    def test_enhanced_attributed_loads_both_ways(self):
        for val in (True, False):
            with self.subTest(val=val):
                text = BASE_V35 + f"[outputs]\nenhanced_attributed = {str(val).lower()}\n"
                self.assertEqual(_load(text).outputs, {"enhanced_attributed": val})

    def test_an_unknown_output_is_refused_by_name(self):
        with self.assertRaises(config.ConfigError) as caught:
            _load(BASE_V35 + "[outputs]\nfaithfull_attributed = true\n")
        self.assertIn("[outputs] has unknown key(s) ['faithfull_attributed']",
                      str(caught.exception))

    def test_arm_loads_faithful_or_false(self):
        self.assertEqual(_load(BASE_V35 + '[outputs]\narm = "faithful"\n').outputs,
                         {"arm": "faithful"})
        self.assertEqual(_load(BASE_V35 + "[outputs]\narm = false\n").outputs, {"arm": False})

    def test_arm_refuses_anything_else(self):
        for val in ('"enhanced"', "true", '"yes"'):
            with self.subTest(val=val):
                with self.assertRaises(config.ConfigError) as caught:
                    _load(BASE_V35 + f"[outputs]\narm = {val}\n")
                self.assertIn('[outputs].arm must be "faithful" or false', str(caught.exception))


class _Args:
    def __init__(self, **kw):
        self.iat_file = run_flight.IAT_FILE
        self.diode_corrected = False
        self.accept_unstamped = False
        self.engine = "3.5"
        self.attributed = False
        self.enhancements = False
        self.stages = "234c"
        self.__dict__.update(kw)


class TheDriverHonoursTheSelection(unittest.TestCase):
    def setUp(self):
        from tests import _run_flight_state
        self._masks = dict(run_flight.SHADOW_DIODE_OVERRIDES)
        # _apply_config rebinds the driver's module globals (the profile among them); restore
        # them, so a later module sharing the driver does not inherit this file's profile.
        _run_flight_state.preserve(self, run_flight)

    def tearDown(self):
        run_flight.SHADOW_DIODE_OVERRIDES.clear()
        run_flight.SHADOW_DIODE_OVERRIDES.update(self._masks)

    def _apply(self, toml_text, **kw):
        args = _Args(**kw)
        args.config = _toml(toml_text)
        buf = io.StringIO()
        with redirect_stdout(buf):
            out = run_flight._apply_config(args, None, [])
        self.assertIsNotNone(out)
        return out, buf.getvalue()

    def test_absent_section_leaves_the_flag_as_given(self):
        for given in (False, True):
            with self.subTest(given=given):
                out, log = self._apply(BASE_V35, attributed=given)
                self.assertIs(out.attributed, given)
                self.assertNotIn("[outputs]", log)

    def test_true_turns_attributed_on(self):
        out, log = self._apply(BASE_V35 + "[outputs]\nfaithful_attributed = true\n")
        self.assertTrue(out.attributed)
        self.assertIn("[outputs].faithful_attributed = true -> --attributed", log)

    def test_false_is_an_opt_out_and_the_command_line_wins(self):
        out, _ = self._apply(BASE_V35 + "[outputs]\nfaithful_attributed = false\n")
        self.assertFalse(out.attributed)
        out, log = self._apply(BASE_V35 + "[outputs]\nfaithful_attributed = false\n",
                               attributed=True)
        self.assertTrue(out.attributed)
        self.assertIn("the command line wins", log)


ENH_ON = "[enhancements]\nhole_edge_swap = true\n"


class TheDriverHonoursEnhancedAttributed(TheDriverHonoursTheSelection):
    """``enhanced_attributed``: ``true`` is ``--enhancements`` with stage ``c``, and a
    selection the run could not honour is refused before any stage runs."""

    def _refused(self, toml_text, **kw):
        args = _Args(**kw)
        args.config = _toml(toml_text)
        buf = io.StringIO()
        with redirect_stdout(buf):
            out = run_flight._apply_config(args, None, [])
        self.assertIsNone(out)
        self.assertIn("refused before any stage ran", buf.getvalue())
        return buf.getvalue()

    def test_absent_key_leaves_the_flag_as_given(self):
        for given in (False, True):
            with self.subTest(given=given):
                out, log = self._apply(BASE_V35 + ENH_ON, enhancements=given)
                self.assertIs(out.enhancements, given)
                self.assertNotIn("enhanced_attributed", log)

    @unittest.skipUnless(importlib.util.find_spec("arrayprobe_enhancements"),
                         "arrayprobe_enhancements is not installed")
    def test_true_turns_enhancements_on(self):
        out, log = self._apply(BASE_V35 + ENH_ON + "[outputs]\nenhanced_attributed = true\n")
        self.assertTrue(out.enhancements)
        self.assertIn("[outputs].enhanced_attributed = true -> --enhancements", log)

    def test_false_is_an_opt_out_and_the_command_line_wins(self):
        out, _ = self._apply(BASE_V35 + ENH_ON + "[outputs]\nenhanced_attributed = false\n")
        self.assertFalse(out.enhancements)
        out, log = self._apply(BASE_V35 + ENH_ON + "[outputs]\nenhanced_attributed = false\n",
                               enhancements=True)
        self.assertTrue(out.enhancements)
        self.assertIn("enhanced_attributed = false, but --enhancements was given", log)

    def test_refused_when_no_enhancement_is_switched_on(self):
        for table in ("", "[enhancements]\nhole_edge_swap = false\n"):
            with self.subTest(table=table):
                log = self._refused(BASE_V35 + table + "[outputs]\nenhanced_attributed = true\n")
                self.assertIn("switches no enhancement on", log)

    def test_refused_when_the_stages_leave_out_the_combine(self):
        log = self._refused(BASE_V35 + ENH_ON + "[outputs]\nenhanced_attributed = true\n",
                            stages="234")
        self.assertIn("leave out 'c'", log)

    def test_refused_when_the_enhancements_package_is_missing(self):
        real = importlib.util.find_spec

        def fake(name, *a, **kw):
            return None if name == "arrayprobe_enhancements" else real(name, *a, **kw)

        with mock.patch("importlib.util.find_spec", fake):
            log = self._refused(BASE_V35 + ENH_ON + "[outputs]\nenhanced_attributed = true\n")
        self.assertIn("arrayprobe-enhancements is not installed", log)


ARM_IDS = '[arm]\nsite_id = "tst"\nplatform_id = "demo2ds"\nfacility_id = "X1"\n'


class OnlyTheParentHonoursTheOutputs(TheDriverHonoursTheSelection):
    """A ``--jobs`` worker loads the same ``--config`` as its parent, with ``c`` taken out of its
    stages and ``protective_worker`` set. The enhanced selection and the faithful ARM export are
    the parent's: a worker neither refuses the run nor switches either on."""

    def test_a_worker_with_enhanced_attributed_is_neither_refused_nor_enhanced(self):
        out, log = self._apply(BASE_V35 + ENH_ON + "[outputs]\nenhanced_attributed = true\n",
                               stages="234", protective_worker=True)
        self.assertFalse(out.enhancements)
        self.assertNotIn("enhanced_attributed", log)

    def test_the_parent_still_refuses_stages_without_the_combine(self):
        args = _Args(stages="234", protective_worker=False)
        args.config = _toml(BASE_V35 + ENH_ON + "[outputs]\nenhanced_attributed = true\n")
        with redirect_stdout(io.StringIO()):
            self.assertIsNone(run_flight._apply_config(args, None, []))

    def test_a_worker_does_not_take_the_faithful_arm_export(self):
        out, log = self._apply(BASE_V35 + ARM_IDS + '[outputs]\narm = "faithful"\n',
                               stages="234", protective_worker=True)
        self.assertIsNone(getattr(out, "faithful_arm", None))
        self.assertNotIn("[outputs].arm", log)

    def test_the_parent_takes_the_faithful_arm_export(self):
        out, log = self._apply(BASE_V35 + ARM_IDS + '[outputs]\narm = "faithful"\n')
        self.assertEqual(out.faithful_arm,
                         {"site_id": "tst", "platform_id": "demo2ds", "facility_id": "X1"})
        self.assertIn('[outputs].arm = "faithful" -> <stem>.arm.nc', log)

    def test_without_arm_the_skip_is_logged_and_no_export_is_selected(self):
        out, log = self._apply(BASE_V35 + '[outputs]\narm = "faithful"\n')
        self.assertIsNone(getattr(out, "faithful_arm", None))
        self.assertIn('[outputs].arm = "faithful" SKIPPED: no [arm] section', log)


class MainResetsTheShatteringType(unittest.TestCase):
    """``IA_THRESH_TYPE`` comes from this run's ``[shattering]`` alone: an in-process caller
    running ``main()`` twice does not inherit the previous config's value."""

    def test_main_clears_a_leaked_value(self):
        from tests import _run_flight_state
        _run_flight_state.preserve(self, run_flight)
        run_flight.IA_THRESH_TYPE = 2
        with redirect_stdout(io.StringIO()):
            rc = run_flight.main(["--engine", "3.5", "--profile", "stock-v3.5",
                                  "--preset", "ORACLES_2016_2DS_H",
                                  "--probe-case", "no-such-case-9f3a", "nosuch-raw.2DS"])
        self.assertEqual(rc, 2)
        self.assertIsNone(run_flight.IA_THRESH_TYPE)


def _load_demo_reference():
    spec_ = importlib.util.spec_from_file_location(
        "make_demo_reference_s2", ROOT / "scripts" / "make_demo_reference.py")
    mdr = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(mdr)
    return mdr


def _build_demo(mdr, out_dir: Path) -> Path:
    """The synthetic v3.5 demo flight and its seeded aircraft file, written into ``out_dir``."""
    raw = out_dir / f"{mdr.STEM}.2DS"
    mdr._load_tool_module("make_demo_flight").build_demo_flight(raw, n_seconds=mdr.N_SECONDS)
    mdr.write_aircraft_v35(out_dir / f"{mdr.PREFIX_V35}aircraft.cdf")
    return raw


def _demo_env(mdr) -> dict:
    """The demo build's environment with this checkout's ``enhancements_uiops/src`` first on
    the path."""
    import os

    env = mdr.demo_build_env()
    enh_src = ROOT / "enhancements_uiops" / "src"
    if enh_src.is_dir():
        env["PYTHONPATH"] = os.pathsep.join(
            [str(enh_src)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    return env


def _run_demo(case: unittest.TestCase, mdr, out_dir: Path, raw: Path, extra: str, label: str):
    """``arrayprobe run <toml> <raw>`` as a subprocess, from a clean ``_decoded``.

    The subprocess sees this checkout's own ``enhancements_uiops/src`` first on its path, so the
    enhancements half of an ``[outputs]`` selection is the one beside the port under test, not
    whichever copy happens to be installed.
    """
    import shutil
    import subprocess

    toml = out_dir / f"{mdr.PREFIX_V35}run.toml"
    toml.write_text(mdr.RUN_TOML_V35 + extra, encoding="utf-8")
    decoded = out_dir / "_decoded"
    shutil.rmtree(decoded, ignore_errors=True)
    env = _demo_env(mdr)
    run = subprocess.run(
        [sys.executable, "-m", "arrayprobe.cli", "run", str(toml), str(raw)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=600, env=env)
    case.assertEqual(run.returncode, 0, f"{label}: {run.stdout}\n{run.stderr}")
    return decoded, run.stdout + run.stderr


_WALL_CLOCK = {"Creation Time", "Creation_Time"}


def _netcdf_contents(path: Path):
    """Every dimension, every variable's raw values and every attribute, global and
    per-variable, except the global creation stamp (``'Creation Time'`` on v3.1.4,
    ``'Creation_Time'`` on v3.5's sd), which records the wall clock."""
    import netCDF4
    import numpy as np

    with netCDF4.Dataset(path, "r") as ds:
        ds.set_auto_maskandscale(False)
        glob = {k: str(ds.getncattr(k)) for k in ds.ncattrs() if k not in _WALL_CLOCK}
        dims = {k: len(v) for k, v in ds.dimensions.items()}
        var = {}
        for name, v in ds.variables.items():
            var[name] = (v.dtype.str, v.dimensions, np.asarray(v[...]).tobytes(),
                         {k: str(v.getncattr(k)) for k in v.ncattrs()})
    return glob, dims, var


@repo_only
class AFileWithEveryOutputOffRunsExactlyAsBefore(unittest.TestCase):
    """Byte-identity on the tracked synthetic v3.5 demo flight: the faithful ``combined`` and its
    ``.call`` are identical with ``[outputs]`` absent and with every ``[outputs]`` key false,
    ``arm = false`` included.

    One directory, two runs of the user's command line (``arrayprobe run <toml> <raw>``, as a
    subprocess so the shared driver module is never touched), so no path differs between them.
    The combined is compared as netCDF contents with the global ``'Creation Time'`` left out, so
    a wall-clock stamp landing in a different second cannot fail the test while any other
    difference still does.
    """

    def test_combined_and_call_are_identical(self):
        mdr = _load_demo_reference()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            out_dir = Path(tmp)
            raw = _build_demo(mdr, out_dir)
            combined_name = f"{mdr.STEM}.combined.H.2DS.cdf"
            got = {}
            for label, extra in (("absent", ""),
                                 ("all false", "\n[outputs]\nfaithful_attributed = false\n"
                                               "enhanced_attributed = false\narm = false\n"
                                               "analysis_ready = false\nzarr = false\n")):
                decoded, log = _run_demo(self, mdr, out_dir, raw, extra, label)
                combined = decoded / combined_name
                got[label] = (_netcdf_contents(combined),
                              Path(f"{combined}.call").read_bytes(),
                              sorted(p.name for p in decoded.iterdir()), log)
            a, b = got["absent"], got["all false"]
            self.assertEqual(a[2], b[2], "the two runs wrote different sets of files")
            self.assertFalse(any(n.endswith(".arm.nc") for n in b[2]),
                             "arm = false wrote an ARM file")
            self.assertNotIn("ARM faithful", b[3])
            self.assertEqual(a[1], b[1], "the combined's .call differs")
            self.assertEqual(a[0], b[0], "the faithful combined differs (Creation Time aside)")


@unittest.skipUnless(importlib.util.find_spec("arrayprobe_enhancements"),
                     "arrayprobe_enhancements is not installed")
@repo_only
class TheFaithfulArmFileIsACopyOfThePortsSd(unittest.TestCase):
    """``arm = "faithful"`` end to end on the synthetic v3.5 demo flight: with ``[arm]`` the ARM
    file is written and says it is of the faithful lineage, and the port's ``sd`` is unchanged by
    the export; without ``[arm]`` the log names the skip and no ARM file is written."""

    ARM = '\n[arm]\nsite_id = "tst"\nplatform_id = "demo2ds"\nfacility_id = "X1"\n'
    SELECT = '\n[outputs]\narm = "faithful"\n'

    def _sd(self, decoded: Path, stem: str) -> Path:
        sds = sorted(p for p in decoded.glob(f"sd.*{stem}*")
                     if p.suffix not in (".call", ".json"))
        self.assertEqual(len(sds), 1, f"expected one sd, found {[p.name for p in sds]}")
        return sds[0]

    def test_with_arm_the_file_is_written_and_the_sd_is_untouched(self):
        import hashlib

        import netCDF4

        mdr = _load_demo_reference()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            out_dir = Path(tmp)
            raw = _build_demo(mdr, out_dir)
            # The sd the plain run writes, then the same run with the ARM copy selected.
            decoded, _ = _run_demo(self, mdr, out_dir, raw, "", "plain")
            sd_plain = self._sd(decoded, mdr.STEM)
            plain = (_netcdf_contents(sd_plain), Path(f"{sd_plain}.call").read_bytes())
            decoded, log = _run_demo(self, mdr, out_dir, raw, self.SELECT + self.ARM,
                                     "faithful")
            arm_file = decoded / f"{mdr.STEM}.arm.nc"
            self.assertTrue(arm_file.is_file(), f"no ARM file written; log:\n{log}")
            self.assertIn(f"ARM faithful {arm_file.name}", log)
            sd = self._sd(decoded, mdr.STEM)
            self.assertEqual((_netcdf_contents(sd), Path(f"{sd}.call").read_bytes()), plain,
                             "selecting the ARM copy changed the port's sd")
            with netCDF4.Dataset(arm_file, "r") as ds:
                self.assertEqual(ds.getncattr("arrayprobe_lineage"), "faithful")
                self.assertEqual(ds.getncattr("arrayprobe_sd_lineage"), "port")
                self.assertEqual(ds.getncattr("arrayprobe_sd_source"), sd.name)
            self.assertEqual(Path(f"{arm_file}.call").read_text().strip(),
                             Path(f"{sd}.call").read_text().strip())

            # The export only reads the sd: run it again on the same sd (in a subprocess with
            # the run's own path, so it is this checkout's enhancements), hashing either side.
            import subprocess

            before = hashlib.sha256(sd.read_bytes()).hexdigest()
            code = ("import sys; from arrayprobe_enhancements import pipeline; "
                    "pipeline.export_faithful_arm(sys.argv[1], sys.argv[2], '3.5', "
                    "{'site_id': 'tst', 'platform_id': 'demo2ds', 'facility_id': 'X1'})")
            again = subprocess.run([sys.executable, "-c", code, str(decoded), mdr.STEM],
                                   capture_output=True, text=True, timeout=300,
                                   env=_demo_env(mdr))
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertEqual(hashlib.sha256(sd.read_bytes()).hexdigest(), before)

    def test_without_arm_the_skip_is_logged_and_no_file_is_written(self):
        mdr = _load_demo_reference()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            out_dir = Path(tmp)
            raw = _build_demo(mdr, out_dir)
            decoded, log = _run_demo(self, mdr, out_dir, raw, self.SELECT, "no [arm]")
            self.assertIn('[outputs].arm = "faithful" SKIPPED: no [arm] section', log)
            # The skip is the config's: the export is never attempted, so a port-only install
            # cannot fail the run over an output the log already declared skipped.
            self.assertNotIn("ARM faithful", log)
            self.assertEqual([p.name for p in decoded.glob("*.arm.nc*")], [])


# ---------------------------------------------------------------------------
# The run-level block shared by the attributed combined and the faithful ARM copy
# ---------------------------------------------------------------------------

def _attributes_before_split(
    stamp: str | None,
    *,
    source_path: Path | str,
    source_sha256: str,
    source_bytes: int,
    shape: ae.ProductShape,
    files_stitched: int | None = None,
    enhancements: Sequence[str] = (),
    export_time: str | None = None,
    enhancements_record: str | None = None,
    tas_qc: dict | None = None,
) -> dict[str, object]:
    """The attributed export's global attributes as written before the run-level block was split
    out, frozen here so the split can be shown to change nothing."""
    now = export_time or _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")
    atts: dict[str, object] = {
        f"{ae.ATTR_PREFIX}export_convention": ae.EXPORT_CONVENTION,
        f"{ae.ATTR_PREFIX}export_module": "arrayprobe.attributed_export",
        f"{ae.ATTR_PREFIX}package_version": ae._package_version(),
        f"{ae.ATTR_PREFIX}export_time": now,
        f"{ae.ATTR_PREFIX}source_file": Path(source_path).name,
        f"{ae.ATTR_PREFIX}source_sha256": source_sha256,
        f"{ae.ATTR_PREFIX}source_bytes": int(source_bytes),
        f"{ae.ATTR_PREFIX}source_writer": shape.writer,
        f"{ae.ATTR_PREFIX}product_shape": shape.name,
        f"{ae.ATTR_PREFIX}fidelity_note": (
            "This file is NOT the byte-comparison artefact. The faithful file named in "
            "arrayprobe_source_file is: it carries zero attributes because the MATLAB that defines "
            "its format writes zero attributes (combine_sizedist.m:202-231, measured), and every "
            "validated-flight comparison is made against it. This file holds the same values and "
            "adds metadata; use it to read the data, use the faithful file to compare bytes."),
        f"{ae.ATTR_PREFIX}time_convention": (
            "Time Vector is a MATLAB datenum in days (combine_sizedist.m:95-120), not the HHMMSS "
            "the sd files carry. Seconds since 1970-01-01T00:00:00Z = "
            "(Time Vector - arrayprobe_datenum_unix_epoch_days) * 86400."),
        f"{ae.ATTR_PREFIX}datenum_unix_epoch_days": ae.DATENUM_UNIX_EPOCH_DAYS,
        f"{ae.ATTR_PREFIX}missing_value_convention": (
            "Missing seconds are IEEE-754 NaN in the float64 payload, with no _FillValue attribute "
            "-- the faithful writer's own convention (combine_sizedist.m:124-148 pads the 1 Hz "
            "grid with NaN; arrayprobe.combine:245-250). No _FillValue is added here, because "
            "adding one would change what a masking reader returns."),
        f"{ae.ATTR_PREFIX}enhancements_applied": ",".join(enhancements) if enhancements else "none",
        f"{ae.ATTR_PREFIX}enhancements_basis": (
            "none by construction when the producer is the port: 'the port is the faithful "
            "reproduction and nothing else' (the package's rule that enhancements live outside "
            "the port), "
            "enforced by tests/test_no_enhancement_coupling.py. scripts/run_flight.py applies "
            "corrections only to SEPARATE <stem>.enh.* products (named in their own .call), "
            "never to the faithful file this export reads. A non-port chain must name what it "
            "applied through this exporter's `enhancements` argument."),
    }
    if files_stitched is not None:
        atts[f"{ae.ATTR_PREFIX}files_stitched"] = int(files_stitched)
    if enhancements_record is not None:
        # The producing chain's own record, verbatim text read from
        # its sidecar by the caller -- nothing here imports the enhancements package.
        atts[f"{ae.ATTR_PREFIX}enhancements_record"] = enhancements_record
    if tas_qc is not None:
        # Which seconds were sized with a substituted or default TAS, read from the
        # source's <product>.tasqc.json -- the run log is not the only record of it.
        for key, value in tas_qc.items():
            atts[f"{ae.ATTR_PREFIX}{key}"] = value
    else:
        # Moved verbatim into the shared block; read from there rather than retyped.
        atts[f"{ae.ATTR_PREFIX}tas_qc"] = ae.shared_attributes(engine=None)[
            f"{ae.ATTR_PREFIX}tas_qc"]

    if stamp is None:
        atts[f"{ae.ATTR_PREFIX}call_stamp"] = (
            "ABSENT -- the faithful file carried no .call sidecar and the export was run with "
            "accept_unstamped=True. The engine, profile, thresholds and reject configuration that "
            "produced it are NOT established. Stated rather than left blank.")
        return atts

    atts[f"{ae.ATTR_PREFIX}call_stamp"] = stamp
    keys = ae.parse_stamp(stamp)
    for key, value in keys.items():
        if key == "reject":
            atts[f"{ae.ATTR_PREFIX}reject"] = value
            for field, field_value in ae.parse_reject(value).items():
                atts[f"{ae.ATTR_PREFIX}reject_{field}"] = field_value
        elif key in ae.TAGGED_KEYS:
            number, tag = ae.parse_tagged_value(value)
            atts[f"{ae.ATTR_PREFIX}{key}"] = number
            atts[f"{ae.ATTR_PREFIX}{key}_source"] = tag
        else:
            atts[f"{ae.ATTR_PREFIX}{key}"] = value

    if "engine" not in keys:
        # src/arrayprobe/driver/run_flight.py:1925-1928: a v3.1.4 stamp written before
        # 2026-09-15 has no `engine=` key at all, and `_stamps_equivalent` reads that absence as
        # engine=3.1.4. Read the same way here rather than leaving the field blank, and say that
        # it was inferred.
        atts[f"{ae.ATTR_PREFIX}engine"] = "3.1.4"
        atts[f"{ae.ATTR_PREFIX}engine_basis"] = (
            "inferred, not stamped: this .call predates 2026-09-15, when every v3.1.4 stamp began "
            "naming its own engine (run_flight._engine_prefix). run_flight._stamps_equivalent "
            "reads the absence of engine= as engine=3.1.4; this export reads it the same way.")
    return atts


def _globals(path: Path) -> dict:
    import netCDF4

    with netCDF4.Dataset(path, "r") as ds:
        return {k: ds.getncattr(k) for k in ds.ncattrs()}


def _same(a, b) -> bool:
    import numpy as np

    return bool(np.array_equal(np.asarray(a), np.asarray(b)))


@unittest.skipUnless(importlib.util.find_spec("arrayprobe_enhancements"),
                     "arrayprobe_enhancements is not installed")
@repo_only
class TheAttributedCombinedAndTheArmCopyShareOneRunLevelBlock(unittest.TestCase):
    """``faithful_attributed = true`` and ``arm = "faithful"`` in one run of the demo flight: the
    shared keys (engine, the sd configuration, enhancements, airspeed QC, package version) are
    equal in both files, each file's own ``arrayprobe_call_stamp`` is its own ``.call``, and the
    attributed combined's attributes are exactly what they were before the block was split out.
    Under the author's option (a) (2026-10-01) the ARM file's block is the COMBINED product's, read
    here from the combined's own ``.call`` and ``.tasqc.json`` (the merged-parts key included),
    so each side comes from a different file than the one it is checked in.
    """

    SELECT = ('\n[outputs]\nfaithful_attributed = true\narm = "faithful"\n'
              '\n[arm]\nsite_id = "tst"\nplatform_id = "demo2ds"\nfacility_id = "X1"\n')

    def test_shared_keys_agree_and_each_stamp_is_its_own(self):
        mdr = _load_demo_reference()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            out_dir = Path(tmp)
            raw = _build_demo(mdr, out_dir)
            decoded, log = _run_demo(self, mdr, out_dir, raw, self.SELECT, "both outputs")
            combined = decoded / f"{mdr.STEM}.combined.H.2DS.cdf"
            attributed = ae.default_output_path(combined)
            arm_file = decoded / f"{mdr.STEM}.arm.nc"
            self.assertTrue(attributed.is_file(), f"no attributed combined; log:\n{log}")
            self.assertTrue(arm_file.is_file(), f"no ARM file; log:\n{log}")
            two, three = _globals(attributed), _globals(arm_file)

            p = ae.ATTR_PREFIX
            shared = ae._shared_from_stamp(ae.read_stamp(combined), nested=True,
                                           tas_qc=ae.read_qc_sidecar(combined))
            for key in (f"{p}package_version", f"{p}engine", f"{p}inputs_built_with",
                        f"{p}enhancements_applied", f"{p}enhancements_basis"):
                self.assertIn(key, shared)
            for key, value in shared.items():
                self.assertIn(key, two, f"{key} missing from the attributed combined")
                self.assertIn(key, three, f"{key} missing from the ARM copy")
                self.assertTrue(_same(two[key], value), f"{key} differs in output 2")
                self.assertTrue(_same(three[key], two[key]), f"{key} differs between outputs")

            # Each file keeps its own stamp, and it is its own .call.
            self.assertEqual(str(two[f"{p}call_stamp"]),
                             Path(f"{combined}.call").read_text().strip())
            self.assertEqual(str(three[f"{p}call_stamp"]),
                             Path(f"{arm_file}.call").read_text().strip())
            self.assertNotEqual(two[f"{p}call_stamp"], three[f"{p}call_stamp"])

            # Output 2 is unchanged by the split: same keys, same order, same values.
            before = _attributes_before_split(
                ae.read_stamp(combined), source_path=combined,
                source_sha256=ae.sha256_of(combined), source_bytes=combined.stat().st_size,
                shape=next(s for s in ae.SHAPES if s.name == str(two[f"{p}product_shape"])),
                files_stitched=int(two[f"{p}files_stitched"]),
                export_time=str(two[f"{p}export_time"]),
                tas_qc=ae.read_qc_sidecar(combined))
            # The ACDD discovery attributes (2026-10-05) are a later, additive change with
            # their own tests in test_attributed_export: they are written after every key the
            # split produced, so the split's own claim is checked on the rest.
            acdd = [k for k in two if k in ae.ACDD_KEYS]
            self.assertEqual(list(two)[len(two) - len(acdd):], acdd,
                             "the ACDD attributes must follow every pre-existing key")
            # Likewise arrayprobe_encoding (2026-10-08: the attributed file is also the
            # analysis-ready one), additive, tested in test_attributed_export.
            later = set(ae.ACDD_KEYS) | {f"{p}encoding"}
            got = {k: v for k, v in two.items() if k not in _WALL_CLOCK and k not in later}
            self.assertEqual(list(got), list(before), "the attribute set or order changed")
            for key, value in before.items():
                self.assertTrue(_same(got[key], value), f"{key} changed")



@unittest.skipUnless(importlib.util.find_spec("arrayprobe_enhancements"),
                     "arrayprobe_enhancements is not installed")
@repo_only
class TheRunWritesOneOutputsManifest(unittest.TestCase):
    """A run that writes an OUTPUT 2 or 3 file writes ``<base>.outputs.json`` listing every
    output it produced; checked against the files on disk, read independently. A run with no
    ``[outputs]`` writes no manifest."""

    SELECT = '\n[outputs]\nfaithful_attributed = true\narm = "faithful"\n'

    def test_the_manifest_lists_every_output_with_its_hash_and_size(self):
        import hashlib
        import json

        mdr = _load_demo_reference()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            out_dir = Path(tmp)
            raw = _build_demo(mdr, out_dir)
            decoded, log = _run_demo(self, mdr, out_dir, raw,
                                     self.SELECT + "\n" + ARM_IDS, "manifest")
            manifest = decoded / f"{mdr.STEM}.outputs.json"
            self.assertTrue(manifest.is_file(), f"no manifest; log:\n{log}")
            text = manifest.read_text(encoding="utf-8")
            self.assertTrue(text.endswith("\n"))
            entries = json.loads(text)["outputs"]
            listed = {e["path"]: e for e in entries}
            for rel, e in listed.items():
                path = decoded / rel
                self.assertTrue(path.is_file(), rel)
                data = path.read_bytes()
                self.assertEqual(e["sha256"], hashlib.sha256(data).hexdigest(), rel)
                self.assertEqual(e["size"], len(data), rel)
                call = Path(f"{path}.call")
                self.assertEqual(e["call"], call.read_text(encoding="utf-8")
                                 if call.is_file() else None, rel)
                self.assertIn(e["lineage"], ("faithful", "enhanced"))
            on_disk = sorted(p.name for p in decoded.iterdir()
                             if p.name.endswith((".attributed.nc", ".arm.nc")))
            self.assertTrue(on_disk, "the run wrote no OUTPUT 2/3 file")
            for name in on_disk:
                self.assertIn(name, listed, f"{name} is on disk but not in the manifest")
            original = f"{mdr.STEM}.combined.H.2DS.cdf"
            self.assertEqual(listed[original]["role"], "original")
            self.assertEqual({e["role"] for e in entries}, {"original", "attributed", "arm"})

    def test_a_run_without_outputs_writes_no_manifest(self):
        mdr = _load_demo_reference()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            out_dir = Path(tmp)
            raw = _build_demo(mdr, out_dir)
            decoded, _ = _run_demo(self, mdr, out_dir, raw, "", "plain")
            self.assertEqual([p.name for p in decoded.glob("*.outputs.json")], [])


class TheEncodingKeys(TheDriverHonoursTheSelection):
    """``[outputs] analysis_ready`` (absent = true) and ``zarr`` (absent = false),
    each with an explicit opt-out; the driver globals they set are restored after each test."""

    def setUp(self):
        super().setUp()
        self._enc = (run_flight.ATTRIBUTED_ANALYSIS_READY, run_flight.ATTRIBUTED_ZARR,
                     run_flight.ATTRIBUTED_PARQUET)

    def tearDown(self):
        (run_flight.ATTRIBUTED_ANALYSIS_READY, run_flight.ATTRIBUTED_ZARR,
         run_flight.ATTRIBUTED_PARQUET) = self._enc
        super().tearDown()

    def test_both_keys_load_both_ways(self):
        for key in ("analysis_ready", "zarr", "parquet"):
            for val in (True, False):
                with self.subTest(key=key, val=val):
                    cfg = _load(BASE_V35 + f"[outputs]\n{key} = {str(val).lower()}\n")
                    self.assertIs(cfg.outputs[key], val)
        self.assertEqual(_load(BASE_V35).outputs, {})

    def test_a_non_boolean_is_refused_by_name(self):
        for key in ("analysis_ready", "zarr", "parquet"):
            with self.subTest(key=key):
                with self.assertRaisesRegex(config.ConfigError, rf"\[outputs\]\.{key}"):
                    _load(BASE_V35 + f'[outputs]\n{key} = "yes"\n')

    def test_analysis_ready_false_sets_plain(self):
        run_flight.ATTRIBUTED_ANALYSIS_READY = True
        _, log = self._apply(BASE_V35 + "[outputs]\nanalysis_ready = false\n")
        self.assertFalse(run_flight.ATTRIBUTED_ANALYSIS_READY)
        self.assertIn("analysis_ready = false", log)

    def test_zarr_without_an_attributed_output_is_refused(self):
        args = _Args()
        args.config = _toml(BASE_V35 + "[outputs]\nzarr = true\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            out = run_flight._apply_config(args, None, [])
        self.assertIsNone(out)
        self.assertIn("[outputs].zarr = true cannot be honoured", buf.getvalue())

    def test_zarr_with_faithful_attributed_is_taken(self):
        run_flight.ATTRIBUTED_ZARR = False
        self._apply(BASE_V35 + "[outputs]\nfaithful_attributed = true\nzarr = true\n")
        self.assertTrue(run_flight.ATTRIBUTED_ZARR)

    def test_parquet_without_an_attributed_output_is_refused(self):
        args = _Args()
        args.config = _toml(BASE_V35 + "[outputs]\nparquet = true\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            out = run_flight._apply_config(args, None, [])
        self.assertIsNone(out)
        self.assertIn("[outputs].parquet = true cannot be honoured", buf.getvalue())

    def test_parquet_with_faithful_attributed_is_taken(self):
        run_flight.ATTRIBUTED_PARQUET = False
        self._apply(BASE_V35 + "[outputs]\nfaithful_attributed = true\nparquet = true\n")
        self.assertTrue(run_flight.ATTRIBUTED_PARQUET)

    def test_parquet_absent_stays_off(self):
        run_flight.ATTRIBUTED_PARQUET = False
        self._apply(BASE_V35 + "[outputs]\nfaithful_attributed = true\n")
        self.assertFalse(run_flight.ATTRIBUTED_PARQUET)


@repo_only
class TheEncodingKeysEndToEnd(unittest.TestCase):
    """The demo flight: ``analysis_ready = false`` writes a plain OUTPUT 2; ``zarr = true`` writes
    the store, lists it in the manifest with its encoding, and xarray opens it."""

    def test_analysis_ready_false_writes_a_plain_attributed_file(self):
        import netCDF4

        from arrayprobe import attributed_export
        mdr = _load_demo_reference()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            out_dir = Path(tmp)
            raw = _build_demo(mdr, out_dir)
            decoded, log = _run_demo(
                self, mdr, out_dir, raw,
                "\n[outputs]\nfaithful_attributed = true\nanalysis_ready = false\n", "plain")
            files = sorted(decoded.glob("*.attributed.nc"))
            self.assertTrue(files, f"no attributed file; log:\n{log}")
            with netCDF4.Dataset(files[0]) as ds:
                self.assertEqual(ds.arrayprobe_encoding, attributed_export.ENCODING_PLAIN)

    @unittest.skipUnless(importlib.util.find_spec("zarr") and importlib.util.find_spec("xarray"),
                         "zarr/xarray not installed")
    def test_zarr_true_writes_a_listed_store_xarray_opens(self):
        import json

        import xarray as xr
        mdr = _load_demo_reference()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            out_dir = Path(tmp)
            raw = _build_demo(mdr, out_dir)
            decoded, log = _run_demo(
                self, mdr, out_dir, raw,
                "\n[outputs]\nfaithful_attributed = true\nzarr = true\n", "zarr")
            stores = sorted(decoded.glob("*.attributed.zarr"))
            self.assertTrue(stores, f"no Zarr store; log:\n{log}")
            listed = {e["path"]: e for e in json.loads(
                (decoded / f"{mdr.STEM}.outputs.json").read_text(encoding="utf-8"))["outputs"]}
            entry = listed[stores[0].name]
            self.assertEqual((entry["role"], entry["encoding"]), ("attributed", "zarr"))
            self.assertEqual(entry["size"], sum(p.stat().st_size for p in stores[0].rglob("*")
                                                if p.is_file()))
            nc = [e for e in listed.values() if e["path"].endswith(".attributed.nc")]
            self.assertEqual(nc[0]["encoding"], "netcdf4-analysis-ready")
            with xr.open_zarr(stores[0], consolidated=False) as ds:
                self.assertTrue(len(ds.variables) > 0)

if __name__ == "__main__":
    unittest.main()

PRESUITE_GUARD = True
