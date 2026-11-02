# SPDX-License-Identifier: BSD-3-Clause
"""Tests for :mod:`arrayprobe_enhancements.pipeline`.

Every test here
runs the real port through a subprocess (``pipeline.run_port``), on the tracked demo raw
``tests/data/demo_flight_v314_raw.2DS`` -- byte-identical to the v3.5 raw per
``scripts/make_demo_reference.py``'s own module docstring ("The v3.5 reference", measured
2026-09-13) -- so nothing here builds a fresh synthetic flight.

``test_sidecar_identical_for_chunks_1_and_2`` runs engine 3.5, which chunks probetype 2
by prefix-priming; its v3.1.4 twin runs only where that engine is installed.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import netCDF4
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
PY_PORT = REPO_ROOT  # the pre-move port directory is the repository root
RAW_FIXTURE = PY_PORT / "tests" / "data" / "demo_flight_v314_raw.2DS"
STEM = "base160101000000"

_MDR_SPEC = importlib.util.spec_from_file_location(
    "_test_pipeline_make_demo_reference", PY_PORT / "scripts" / "make_demo_reference.py")
assert _MDR_SPEC is not None and _MDR_SPEC.loader is not None  # the file path is fixed and exists
mdr = importlib.util.module_from_spec(_MDR_SPEC)
sys.modules[_MDR_SPEC.name] = mdr
_MDR_SPEC.loader.exec_module(mdr)

from arrayprobe_enhancements import applicability, pipeline, registry  # noqa: E402

#: The v3.1.4 engine stays in the development repository; a release tree omits it.
_V314 = importlib.util.find_spec("arrayprobe.sizedist") is not None
_NO_V314 = "the v3.1.4 engine is not in this release"
#: Engines this tree can run: both in development, v3.5 alone in a release.
ENGINES = ("3.5", "3.1.4") if _V314 else ("3.5",)
#: Present in the development repository, absent from a release tree (it does not ship).
ALLOWLIST = REPO_ROOT / "scripts" / "release_allowlist.txt"


@contextlib.contextmanager
def simulated_release_view():
    """The release view inside the development tree: every ``REQUIRES_V314`` module moved
    from ``REGISTRY``/``APPLICABILITY`` to ``OMITTED``/``OMITTED_APPLICABILITY``, as the
    import-time pass does when the module file is absent. All four tables are restored."""
    names = sorted(applicability.REQUIRES_V314 & set(registry.REGISTRY))
    with mock.patch.dict(registry.REGISTRY), mock.patch.dict(registry.OMITTED), \
            mock.patch.dict(applicability.APPLICABILITY), \
            mock.patch.dict(applicability.OMITTED_APPLICABILITY):
        for n in names:
            registry.OMITTED[n] = registry.REGISTRY.pop(n)
            applicability.OMITTED_APPLICABILITY[n] = applicability.APPLICABILITY.pop(n)
        yield names


def shipped_and_omitted(names) -> tuple[list[str], list[str]]:
    """Split ``names`` into those this distribution ships and those it omits. Reads
    ``registry.OMITTED`` at call time, so a simulated release view is seen."""
    omitted = set(registry.OMITTED)
    return [n for n in names if n not in omitted], [n for n in names if n in omitted]


def _toml(root: Path, *, engine: str, profile: str, enhancements: dict[str, bool] | None = None,
          stages: str = "234", tas_file: bool = True) -> Path:
    lines = [
        "[fidelity]",
        f'profile = "{profile}"',
        "[run]",
        f'engine = "{engine}"',
        'preset = "DEMO_2DS_H"',
        'out = "_decoded"',
        f'stages = "{stages}"',
    ]
    if tas_file:
        lines.append('tas_file = "aircraft.cdf"')
    # The confirmation gate: a v3.1.4 run that states no threshold policy refuses to
    # start when stdin is not a terminal, which a subprocess never has. That is the gate
    # working, so the config declares a policy the way any non-interactive caller must.
    # `liquid-warm` is the regime whose two values ARE the historical stock fallback
    # (regimes.py:82-91 -- area_ratio_z=0.5, default_int_arr_thresh=6e-6), so naming it
    # changes no computed number; it only says out loud which tuning this run uses.
    # Engine 3.5 is never gated (`needs_confirmation` returns False: it resolves no regime
    # and reads no tree) and REFUSES a [thresholds].regime outright, so it gets no section.
    if engine == "3.1.4":
        lines += ["[thresholds]", 'regime = "liquid-warm"']
    # the 2026-09-16 cold-start usability audit: opt-in, and the driver refuses a config with no [enhancements]
    # section at all. `enhancements=None` therefore means "ask for everything this engine
    # allows" -- the set these tests used to get for free from the old default-ON scheme --
    # computed from `applicability` rather than listed, so a superseded module is not
    # requested by name (which would raise NotApplicableToEngine instead of resolving off).
    lines.append("[enhancements]")
    if enhancements is None:
        lines += [f"{name} = true" for name in sorted(registry.REGISTRY)
                  if applicability.applicable(name, engine)]
    else:
        for key, val in enhancements.items():
            lines.append(f"{key} = {'true' if val else 'false'}")
    p = root / "run.toml"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _setup(profile: str, engine: str, *, enhancements=None, stages: str = "234",
           tas_file: bool = True) -> tuple[Path, Path, Path]:
    """A fresh tempdir with the tracked demo raw, a seeded aircraft file and a run.toml.
    Returns ``(root, raw, toml)``."""
    root = Path(tempfile.mkdtemp())
    raw = root / f"{STEM}.2DS"
    shutil.copyfile(RAW_FIXTURE, raw)
    mdr.write_aircraft_v35(root / "aircraft.cdf")
    toml = _toml(root, engine=engine, profile=profile, enhancements=enhancements, stages=stages,
                 tas_file=tas_file)
    return root, raw, toml


def _variables_equal(path_a, path_b) -> tuple[bool, str]:
    """Every variable's name, dtype and values equal (NaN-aware for floats); global attributes
    (``Creation Time`` and friends) are deliberately not compared: '`Creation
    Time` is non-deterministic; exclude it from byte comparisons'."""
    with netCDF4.Dataset(path_a) as a, netCDF4.Dataset(path_b) as b:
        names_a, names_b = set(a.variables), set(b.variables)
        if names_a != names_b:
            return False, f"variable sets differ: {names_a ^ names_b}"
        for name in sorted(names_a):
            va, vb = a.variables[name], b.variables[name]
            va.set_auto_mask(False)
            vb.set_auto_mask(False)
            arr_a, arr_b = np.asarray(va[:]), np.asarray(vb[:])
            if arr_a.dtype.kind == "f":
                equal = np.array_equal(arr_a, arr_b, equal_nan=True)
            else:
                equal = np.array_equal(arr_a, arr_b)
            if not equal:
                return False, f"variable {name!r} differs"
    return True, ""


class ResolutionRaisesBeforeAnyWrite(unittest.TestCase):
    """The double-correction guard: an explicitly-requested, inapplicable enhancement raises
    before ``run_port`` is called and before ``[run].out`` exists."""

    def test_int16_double_fix_on_under_v35_raises_before_any_write(self):
        root, raw, toml = _setup("stock-v3.5", "3.5",
                                 enhancements={"int16_double_fix": True})
        out_dir = root / "_decoded"

        called = []
        real_run_port = pipeline.run_port

        def _spy(*a, **kw):
            called.append((a, kw))
            self.fail("run_port must not be called once resolution has raised")

        pipeline.run_port = _spy
        try:
            with self.assertRaises(applicability.NotApplicableToEngine):
                pipeline.apply_enhancements(toml, [raw])
        finally:
            pipeline.run_port = real_run_port

        self.assertEqual(called, [])
        self.assertFalse(out_dir.exists(), "out dir must not be created before a write")
        shutil.rmtree(root, ignore_errors=True)


class SyntheticDemoFlightBothEngines(unittest.TestCase):
    """Builds and applies the driver once per engine, in ``setUpClass``, and shares the
    result across every assertion below -- each build is a real ~2 s subprocess."""

    @classmethod
    def setUpClass(cls):
        cls.roots: dict[str, Path] = {}
        cls.reports: dict[str, dict] = {}
        for engine, profile in (("3.5", "stock-v3.5"), ("3.1.4", "STOCK_V314")):
            if engine not in ENGINES:
                continue
            root, raw, toml = _setup(profile, engine)
            reports = pipeline.apply_enhancements(toml, [raw],
                                                   port_validation=engine == "3.1.4")
            cls.roots[engine] = root
            cls.reports[engine] = reports[0]

    @classmethod
    def tearDownClass(cls):
        for root in cls.roots.values():
            shutil.rmtree(root, ignore_errors=True)

    def test_sidecar_exists_and_engine_matches_the_call_stamp(self):
        for engine in ENGINES:
            with self.subTest(engine=engine):
                out_dir = self.roots[engine] / "_decoded"
                sd = out_dir / f"sd.{STEM}.H.nc"
                sidecar = out_dir / f"sd.{STEM}.H.nc.enhancements.json"
                self.assertTrue(sidecar.is_file(), sidecar)
                on_disk = json.loads(sidecar.read_text(encoding="utf-8"))
                self.assertEqual(on_disk, self.reports[engine])
                self.assertEqual(self.reports[engine]["engine"], engine)
                stamp = Path(f"{sd}.call").read_text(encoding="utf-8").strip()
                # Every stamp names its engine: v3.5 since 2026-09-13, v3.1.4 since
                # 2026-09-15 (run_flight._engine_prefix).
                self.assertTrue(stamp.startswith(f"engine={engine} "), stamp)

    def test_resolved_covers_every_registered_name(self):
        for engine in ENGINES:
            with self.subTest(engine=engine):
                self.assertEqual(set(self.reports[engine]["resolved"]), set(registry.REGISTRY))

    def test_v35_supersession_resolves_false(self):
        resolved = self.reports["3.5"]["resolved"]
        shipped, omitted = shipped_and_omitted(
            ("int16_double_fix", "conc_arear_fix", "reshape_fix", "wide_hollow_fix"))
        for name in shipped:
            with self.subTest(name=name):
                self.assertFalse(resolved[name])
        for name in omitted:  # release view only (TheDevelopmentViewOmitsNothing)
            with self.subTest(name=name, omitted=True):
                self.assertNotIn(name, resolved)

    def test_v35_variant_only_resolves_false(self):
        resolved = self.reports["3.5"]["resolved"]
        shipped, omitted = shipped_and_omitted(
            ("zero_image_recovery", "mask_presence_fix", "diode_range_fix",
             "intarr_threshold_fix"))
        for name in shipped:
            with self.subTest(name=name):
                self.assertFalse(resolved[name])
        for name in omitted:  # release view only (TheDevelopmentViewOmitsNothing)
            with self.subTest(name=name, omitted=True):
                self.assertNotIn(name, resolved)

    @unittest.skipUnless(_V314, _NO_V314)
    def test_v314_int16_double_fix_resolves_true_and_is_skipped_no_entry_point(self):
        report = self.reports["3.1.4"]
        self.assertTrue(report["resolved"]["int16_double_fix"])
        self.assertEqual(report["skipped"]["int16_double_fix"], "no entry_point")

    def test_hole_edge_swap_copy_matches_swapped_original_on_both_engines(self):
        for engine in ENGINES:
            with self.subTest(engine=engine):
                out_dir = self.roots[engine] / "_decoded"
                proc = out_dir / f"proc.{STEM}.H.nc"
                enh = out_dir / f"{STEM}.enh.proc.nc"
                self.assertTrue(enh.is_file(), enh)
                self.assertIn("hole_edge_swap", self.reports[engine]["applied"])
                with netCDF4.Dataset(proc) as ds_src, netCDF4.Dataset(enh) as ds_enh:
                    # Later work wired more proc-stage adapters that compose onto the same
                    # .enh.proc.nc (the chain rule) -- "hole_edge_swap" is one name among
                    # possibly several in enhancements_applied, not the whole string.
                    self.assertIn("hole_edge_swap", ds_enh.enhancements_applied.split(","))
                    src_edge = np.asarray(ds_src.variables["edge_at_max_hole"][:])
                    enh_max_hole = np.asarray(ds_enh.variables["max_hole_diameter"][:])
                    self.assertTrue(np.array_equal(src_edge, enh_max_hole, equal_nan=True))

    # --- every enhanced output names its enhancements -----------------------

    def test_every_enhanced_file_on_disk_is_named_in_the_record_and_vice_versa(self):
        """The record's ``outputs`` map and the ``*.enh.*.nc`` files in the directory are the
        same set, and ``outputs``' keys are exactly ``applied`` -- an enhanced file the record
        does not name, or a name with no file, both fail. The rebuild also writes
        ``enh.sd`` via ``rebuilt``, even when no sd-stage applier itself acts on it, so the
        on-disk set must be checked against ``outputs`` union ``rebuilt``, not ``outputs`` alone."""
        for engine in ENGINES:
            with self.subTest(engine=engine):
                out_dir = self.roots[engine] / "_decoded"
                report = self.reports[engine]
                on_disk = sorted(p.name for p in out_dir.glob(f"{STEM}.enh.*.nc"))
                # Several enhancements chain on one file (e.g. three on the .enh.proc.nc), so
                # the map's values repeat: compare the SET of files, not the list.
                self.assertEqual(
                    sorted(set(report["outputs"].values()) | set(report["rebuilt"].values())),
                    on_disk)
                self.assertEqual(sorted(report["outputs"]), report["applied"])
                self.assertTrue(on_disk, "the demo run must apply at least one enhancement")
                self.assertIn("hole_edge_swap", report["stages"]["proc"])
                self.assertEqual(report["rebuilt"]["S4"], f"{STEM}.enh.sd.nc")

    def test_each_enhanced_output_carries_its_own_sidecar_equal_to_the_record(self):
        """One ``<file>.enhancements.json`` beside each enhanced output, byte-equal to the
        per-stem record beside the port's sd file -- the ``.call`` convention, so the record
        travels with the file rather than with the directory."""
        for engine in ENGINES:
            with self.subTest(engine=engine):
                out_dir = self.roots[engine] / "_decoded"
                canonical = (out_dir / f"sd.{STEM}.H.nc.enhancements.json").read_bytes()
                for name, fname in self.reports[engine]["outputs"].items():
                    sidecar = out_dir / f"{fname}.enhancements.json"
                    self.assertTrue(sidecar.is_file(), sidecar)
                    self.assertEqual(sidecar.read_bytes(), canonical, name)

    def test_record_versions_are_the_installed_versions_not_unknown(self):
        """``_package_version`` falls back to ``"unknown"`` on any lookup failure; a record
        that says ``unknown`` would pass a shape check and still fail A9's own requirement."""
        from importlib.metadata import version
        for engine in ENGINES:
            with self.subTest(engine=engine):
                versions = self.reports[engine]["versions"]
                self.assertEqual(versions, {
                    "arrayprobe": version("arrayprobe"),
                    "arrayprobe_enhancements": version("arrayprobe-uiops-enhancements"),
                })
                self.assertNotIn("unknown", versions.values())

    def test_enhanced_files_are_stamped_with_engine_and_versions_in_the_file(self):
        """The file itself, not only its sidecar, says which engine and which package
        versions made it -- a ``.enh.*.nc`` copied out alone still names its provenance."""
        for engine in ENGINES:
            with self.subTest(engine=engine):
                out_dir = self.roots[engine] / "_decoded"
                report = self.reports[engine]
                for name, fname in report["outputs"].items():
                    with netCDF4.Dataset(out_dir / fname) as ds:
                        # A chained file names every enhancement applied to it, in order.
                        self.assertIn(name, ds.enhancements_applied.split(","))
                        self.assertEqual(ds.enhancements_engine, engine)
                        self.assertEqual(ds.arrayprobe_version,
                                         report["versions"]["arrayprobe"])
                        self.assertEqual(ds.arrayprobe_enhancements_version,
                                         report["versions"]["arrayprobe_enhancements"])

    def test_record_has_no_timestamp_and_every_resolved_name_is_applied_or_skipped(self):
        """Deterministic (no clock field anywhere in the record) and complete: every name
        resolved ON is either applied or skipped with a reason; none is both, none is lost."""
        for engine in ENGINES:
            with self.subTest(engine=engine):
                report = self.reports[engine]
                for key in report:
                    self.assertNotRegex(key.lower(), r"time|date|created")
                on = {n for n, v in report["resolved"].items() if v}
                applied, skipped = set(report["applied"]), set(report["skipped"])
                self.assertEqual(applied | skipped, on)
                self.assertEqual(applied & skipped, set())
                for reason in report["skipped"].values():
                    self.assertTrue(reason.strip(), "a skip must carry a reason")

    def test_reader_stage_is_recorded_not_applied(self):
        for engine in ENGINES:
            with self.subTest(engine=engine):
                report = self.reports[engine]
                skipped = report["skipped"]
                shipped, omitted = shipped_and_omitted(("last_record_fix",))
                for name in shipped:
                    self.assertIn(name, skipped)
                    self.assertIn("reader-stage", skipped[name])
                for name in omitted:  # release view only (TheDevelopmentViewOmitsNothing)
                    self.assertNotIn(name, skipped)
                    self.assertNotIn(name, report["resolved"])
                    self.assertNotIn(name, report["applied"])

    @unittest.skipUnless(_V314, _NO_V314)
    def test_overload_accounting_fix_is_conditional_on_v35(self):
        """Fact 0.1 (plan section 0): a default v3.5 ``sd`` has neither ``sum_IntArr`` nor
        ``sample_vol`` (``i_save_int_arr_sv=0``, ``run_flight.py`` ``V35_CALL``), so the applier
        must catch the resulting ``KeyError`` and record the reason string the engine's own refusal is
        expected to reuse. On v3.1.4 the same demo ``sd`` carries both variables
        unconditionally, so the correction actually runs."""
        v35 = self.reports["3.5"]
        self.assertNotIn("overload_accounting_fix", v35["applied"])
        self.assertEqual(v35["skipped"]["overload_accounting_fix"],
                         "sd lacks sum_IntArr/sample_vol (iSaveIntArrSV=0)")

        v314 = self.reports["3.1.4"]
        self.assertIn("overload_accounting_fix", v314["applied"])
        self.assertNotIn("overload_accounting_fix", v314["skipped"])


@unittest.skipUnless(_V314, _NO_V314)
class TheReleaseViewSplitIsExact(unittest.TestCase):
    """The shipped/omitted split the record tests above rely on, exercised in development
    under :func:`simulated_release_view` -- no flight is built."""

    NAMED = ("conc_arear_fix", "wide_hollow_fix", "zero_image_recovery", "last_record_fix",
             "int16_double_fix", "reshape_fix", "mask_presence_fix")

    def test_omitted_names_are_split_out_and_refused_by_name_simulated(self):
        before = (dict(registry.REGISTRY), dict(registry.OMITTED))
        with simulated_release_view():
            omitted_now = set(registry.OMITTED)
            shipped, omitted = shipped_and_omitted(self.NAMED)
            self.assertEqual(set(omitted), omitted_now & set(self.NAMED))
            self.assertLessEqual({"conc_arear_fix", "wide_hollow_fix", "zero_image_recovery",
                                  "last_record_fix"}, set(omitted))
            self.assertEqual(set(shipped) & omitted_now, set())
            got = registry.resolve({"all": True}, engine="3.5")
            for name in omitted:
                with self.subTest(name=name):
                    self.assertNotIn(name, got)
                    with self.assertRaisesRegex(registry.UnknownEnhancement, name):
                        registry.resolve({name: True}, engine="3.5")
            for name in shipped:
                with self.subTest(name=name):
                    self.assertIn(name, got)
        self.assertEqual((registry.REGISTRY, registry.OMITTED), before)  # restored

    def test_a_name_neither_registered_nor_omitted_still_fails(self):
        for view in (contextlib.nullcontext, simulated_release_view):
            with self.subTest(view=view.__name__), view():
                shipped, omitted = shipped_and_omitted(("conc_arear_fixx",))
                self.assertEqual((shipped, omitted), (["conc_arear_fixx"], []))
                with self.assertRaises(registry.UnknownEnhancement):
                    registry.resolve({"conc_arear_fixx": True}, engine="3.5")
                resolved = registry.resolve({"all": True}, engine="3.5")
                with self.assertRaises(KeyError):  # a record test would fail, not excuse it
                    resolved["conc_arear_fixx"]


@unittest.skipUnless(ALLOWLIST.is_file(), "release view: the allow-list does not ship")
class TheDevelopmentViewOmitsNothing(unittest.TestCase):
    """With the allow-list present (development), every v3.1.4-only module ships, so no
    release-view excusal above can fire here."""

    def test_nothing_is_omitted(self):
        self.assertEqual(registry.OMITTED, {})
        self.assertEqual(applicability.OMITTED_APPLICABILITY, {})
        self.assertLessEqual(set(applicability.REQUIRES_V314), set(registry.REGISTRY))


class SidecarIdenticalAcrossChunking(unittest.TestCase):
    """``--chunks`` is byte-identical by the port's own doctrine (the parallel decode/merge
    is asserted byte-identical to serial). The enhanced sidecar built on top of it must be
    too.

    Engine 3.5 chunks the demo 2DS by prefix-priming (probetype 2, ``PRIMABLE_TIMINGS_V35``,
    since 2026-09-18), so it carries this test in a release, where v3.1.4 does not ship.
    The v3.1.4 case runs where that engine is installed, on ``ORACLES_2016`` with no TAS
    file: its byte-identity holds only where ``Time_in_seconds`` carries no running sum
    across a seam. ``STOCK_V314`` builds it from a TAS file and differs after every seam
    (2026-09-23), so the driver refuses ``--chunks`` there and this test cannot use it."""

    def _assert_sidecar_identical(self, profile: str, engine: str, **setup_kw):
        root1, raw1, toml1 = _setup(profile, engine, **setup_kw)
        root2, raw2, toml2 = _setup(profile, engine, **setup_kw)
        pv = engine == "3.1.4"
        try:
            reports1 = pipeline.apply_enhancements(toml1, [raw1], chunks=1, port_validation=pv)
            reports2 = pipeline.apply_enhancements(toml2, [raw2], chunks=2, port_validation=pv)
            p1, p2 = dict(reports1[0]), dict(reports2[0])
            p1["config_path"] = p1["config_path"].replace(str(root1), "<root>")
            p2["config_path"] = p2["config_path"].replace(str(root2), "<root>")
            self.assertEqual(json.dumps(p1, sort_keys=True), json.dumps(p2, sort_keys=True))
        finally:
            shutil.rmtree(root1, ignore_errors=True)
            shutil.rmtree(root2, ignore_errors=True)

    def test_sidecar_identical_for_chunks_1_and_2(self):
        self._assert_sidecar_identical("stock-v3.5", "3.5")

    @unittest.skipUnless(_V314, _NO_V314)
    def test_sidecar_identical_for_chunks_1_and_2_v314(self):
        self._assert_sidecar_identical("ORACLES_2016", "3.1.4", tas_file=False)


class DisabledEnhancementsLeavePortOutputUnchanged(unittest.TestCase):
    """The driver must never change what the port writes when every enhancement is off --
    proved by a byte (variable) comparison against a bare ``arrayprobe run`` on the same input,
    excluding ``Creation Time``."""

    @unittest.skipUnless(_V314, _NO_V314)
    def test_disabled_enhancements_leave_port_output_byte_identical(self):
        # Side A: the plain port, called exactly as pipeline.run_port calls it.
        root_a, raw_a, toml_a = _setup("STOCK_V314", "3.1.4")
        pipeline.run_port(toml_a, [raw_a], port_validation=True)
        proc_a = root_a / "_decoded" / f"proc.{STEM}.H.nc"
        sd_a = root_a / "_decoded" / f"sd.{STEM}.H.nc"

        # Side B: the driver, with every registered enhancement explicitly turned off.
        root_b, raw_b, toml_b = _setup(
            "STOCK_V314", "3.1.4",
            enhancements={name: False for name in registry.REGISTRY})
        reports = pipeline.apply_enhancements(toml_b, [raw_b], port_validation=True)
        proc_b = root_b / "_decoded" / f"proc.{STEM}.H.nc"
        sd_b = root_b / "_decoded" / f"sd.{STEM}.H.nc"

        try:
            self.assertEqual(reports[0]["applied"], [])
            ok, detail = _variables_equal(proc_a, proc_b)
            self.assertTrue(ok, detail)
            ok, detail = _variables_equal(sd_a, sd_b)
            self.assertTrue(ok, detail)
            # And the driver's own extra artifacts never touched the port's own files in place --
            # only new, separately-named files exist beside them.
            self.assertFalse((root_b / "_decoded" / f"{STEM}.enh.proc.nc").exists())
            self.assertFalse((root_b / "_decoded" / f"{STEM}.enh.sd.nc").exists())
        finally:
            shutil.rmtree(root_a, ignore_errors=True)
            shutil.rmtree(root_b, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
