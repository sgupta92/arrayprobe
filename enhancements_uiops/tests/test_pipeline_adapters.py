# SPDX-License-Identifier: BSD-3-Clause
"""Tests for the six driver adapters added to
:mod:`arrayprobe_enhancements.pipeline` -- ``particle_number_all_fix``,
``int_arr_rollback_fix``, ``particle_time_int8_fix``, ``outoffocus``,
``pressure_units_fix`` and ``arco_export``.

Every test
here runs the real port through a subprocess (``pipeline.run_port``), on the tracked demo
raw ``tests/data/demo_flight_v314_raw.2DS`` -- the same fixture
``tests/test_pipeline_provenance.py`` (S3) uses, byte-identical to the v3.5 raw.
"""
from __future__ import annotations

import contextlib
import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import netCDF4

REPO_ROOT = Path(__file__).resolve().parents[2]
PY_PORT = REPO_ROOT  # the pre-move port directory is the repository root
RAW_FIXTURE = PY_PORT / "tests" / "data" / "demo_flight_v314_raw.2DS"
STEM = "base160101000000"

_MDR_SPEC = importlib.util.spec_from_file_location(
    "_test_pipeline_adapters_make_demo_reference", PY_PORT / "scripts" / "make_demo_reference.py")
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


def _toml(root: Path, *, engine: str, profile: str) -> Path:
    lines = [
        "[fidelity]",
        f'profile = "{profile}"',
        "[run]",
        f'engine = "{engine}"',
        'preset = "DEMO_2DS_H"',
        'out = "_decoded"',
        'stages = "234"',
        'tas_file = "aircraft.cdf"',
        # The confirmation gate: a v3.1.4 run that states no threshold policy refuses to
        # start when stdin is not a terminal, which a subprocess never has. That is the gate
        # working, so the config declares a policy the way any non-interactive caller must.
        # `liquid-warm` is the regime whose two values ARE the historical stock fallback
        # (regimes.py:82-91 -- area_ratio_z=0.5, default_int_arr_thresh=6e-6), so naming it
        # changes no computed number. Engine 3.5 is never gated and REFUSES the section
        # outright (it resolves no regime and reads no tree), so it is added conditionally.
        *(["[thresholds]", 'regime = "liquid-warm"'] if engine == "3.1.4" else []),
        # the 2026-09-16 cold-start usability audit: every enhancement is OFF unless the file names it true, and
        # the driver refuses a config with no [enhancements] section at all. This class
        # exercises every adapter, so it asks for every module the engine allows --
        # computed from `applicability`, never listed by hand, so a new module joins the
        # exercise automatically and a superseded one is not requested (which would raise
        # NotApplicableToEngine rather than resolving off).
        "[enhancements]",
        *(f"{name} = true" for name in sorted(registry.REGISTRY)
          if applicability.applicable(name, engine)),
    ]
    p = root / "run.toml"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _setup(profile: str, engine: str) -> tuple[Path, Path, Path]:
    root = Path(tempfile.mkdtemp())
    raw = root / f"{STEM}.2DS"
    shutil.copyfile(RAW_FIXTURE, raw)
    mdr.write_aircraft_v35(root / "aircraft.cdf")
    toml = _toml(root, engine=engine, profile=profile)
    return root, raw, toml


class AdaptersRunOnBothEngines(unittest.TestCase):
    """One ``apply_enhancements`` call per engine, on the demo raw with every
    engine-applicable enhancement named ``true`` in ``[enhancements]``."""

    roots: dict[str, Path]  # set in setUpClass
    reports: dict  # set in setUpClass

    @classmethod
    def setUpClass(cls):
        cls.roots, cls.reports = {}, {}
        for profile, engine in (("stock-v3.5", "3.5"), ("STOCK_V314", "3.1.4")):
            if engine not in ENGINES:
                continue
            root, raw, toml = _setup(profile, engine)
            cls.roots[engine] = root
            cls.reports[engine] = pipeline.apply_enhancements(
                toml, [raw], port_validation=engine == "3.1.4")[0]

    @classmethod
    def tearDownClass(cls):
        for root in cls.roots.values():
            shutil.rmtree(root, ignore_errors=True)

    def _enh_proc(self, engine: str) -> Path:
        return self.roots[engine] / "_decoded" / f"{STEM}.enh.proc.nc"

    def _out_dir(self, engine: str) -> Path:
        return self.roots[engine] / "_decoded"

    # --- particle_number_all_fix ---------------------------------------------------------

    def test_particle_number_all_fix_is_a_named_noop_on_the_2ds_demo(self):
        """C5b is a no-op by construction on probetype 2 (2D-S): the proc-file audit shows
        Particle_number_all is written with real values, so the applier must record a named
        skip -- never silently drop real data, never raise an uncaught ValueError."""
        from arrayprobe_enhancements.particle_number_all_fix import audit_proc_file
        for engine in ENGINES:
            with self.subTest(engine=engine):
                proc = self._out_dir(engine) / f"proc.{STEM}.H.nc"
                report = audit_proc_file(proc)
                self.assertFalse(report["all_fill"])  # the audit, asserted, not assumed
                skipped = self.reports[engine]["skipped"]
                self.assertIn("particle_number_all_fix", skipped)
                self.assertIn("no-op", skipped["particle_number_all_fix"])
                self.assertNotIn("particle_number_all_fix", self.reports[engine]["applied"])

    # --- int_arr_rollback_fix -------------------------------------------------------------

    def test_int_arr_rollback_fix_is_a_named_skip_on_probetype_2(self):
        """int_arr_rollback_fix is now probetype 1 only (measured unneeded on the
        2D-S -- its ~250 s clock period is the wrong magnitude for a one-day correction by a
        factor of ~350). The demo raw is a 2D-S (probetype 2), so this must be a named skip,
        not an apply, the same shape as particle_time_int8_fix's skip above."""
        for engine in ENGINES:
            with self.subTest(engine=engine):
                skipped = self.reports[engine]["skipped"]
                self.assertIn("int_arr_rollback_fix", skipped)
                self.assertIn("probetype 2 not affected", skipped["int_arr_rollback_fix"])
                self.assertNotIn("int_arr_rollback_fix", self.reports[engine]["applied"])

    # --- particle_time_int8_fix ------------------------------------------------------------

    def test_particle_time_int8_fix_is_a_named_skip_on_probetype_2(self):
        """The 2D-S demo's preset (DEMO_2DS_H, probe="2DS") resolves to probetype 2, which
        AFFECTED_PROBETYPES = (0, 3) does not cover -- a named skip, not the module's raw
        ValueError."""
        for engine in ENGINES:
            with self.subTest(engine=engine):
                skipped = self.reports[engine]["skipped"]
                self.assertIn("particle_time_int8_fix", skipped)
                self.assertIn("probetype 2 not affected", skipped["particle_time_int8_fix"])

    @unittest.skipUnless(_V314, _NO_V314)
    def test_preset_probetype_is_resolved_from_the_run_toml(self):
        from arrayprobe.constants import imgproc_config
        expected = imgproc_config("2DS").probetype
        root, raw, toml = _setup("STOCK_V314", "3.1.4")
        try:
            pipeline.run_port(toml, [raw], port_validation=True)
            outputs = pipeline.locate_outputs(root / "_decoded", STEM, "3.1.4")
            resolved = pipeline._preset_probetype(pipeline.load_config(toml))
            self.assertEqual(resolved, expected)
            self.assertIsNone(outputs.preset_probetype)  # locate_outputs alone never sets it
        finally:
            shutil.rmtree(root, ignore_errors=True)

    # --- outoffocus --------------------------------------------------------------------

    def test_outoffocus_applies_and_composes_onto_the_chain(self):
        for engine in ENGINES:
            with self.subTest(engine=engine):
                self.assertIn("outoffocus", self.reports[engine]["applied"])
                with netCDF4.Dataset(self._enh_proc(engine)) as ds:
                    names = ds.enhancements_applied.split(",")
                self.assertIn("outoffocus", names)
                self.assertIn("hole_edge_swap", names)  # the chain composes, not overwrites

    # --- pressure_units_fix -------------------------------------------------------------

    @unittest.skipIf("pressure_units_fix" in registry.OMITTED,
                     "release view: pressure_units_fix needs the v3.1.4 engine and does not "
                     "ship; test_pressure_units_fix_is_refused_by_name_in_the_release_view "
                     "covers it there")
    def test_pressure_units_fix_is_a_named_skip_pressure_not_in_the_call_stamp(self):
        for engine in ENGINES:
            with self.subTest(engine=engine):
                skipped = self.reports[engine]["skipped"]
                self.assertIn("pressure_units_fix", skipped)
                self.assertIn("not recoverable", skipped["pressure_units_fix"])
                self.assertNotIn("pressure_units_fix", self.reports[engine]["applied"])

    @unittest.skipUnless("pressure_units_fix" in registry.OMITTED,
                         "development view: pressure_units_fix ships")
    def test_pressure_units_fix_is_refused_by_name_in_the_release_view(self):
        for engine in ENGINES:
            with self.subTest(engine=engine):
                report = self.reports[engine]
                for key in ("resolved", "applied", "skipped"):
                    self.assertNotIn("pressure_units_fix", report[key])
                with self.assertRaisesRegex(registry.UnknownEnhancement, "pressure_units_fix"):
                    registry.resolve({"pressure_units_fix": True}, engine=engine)

    # --- arco_export ---------------------------------------------------------------------

    def test_arco_export_writes_a_product_file_and_is_applied(self):
        for engine in ENGINES:
            with self.subTest(engine=engine):
                self.assertIn("arco_export", self.reports[engine]["applied"])
                out = self._out_dir(engine) / f"{STEM}.enh.arco.nc"
                self.assertTrue(out.is_file())
                with netCDF4.Dataset(out) as ds:
                    self.assertEqual(ds.enhancements_applied, "arco_export")


class PressureUnitsFixReleaseView(unittest.TestCase):
    """The release-view refusal above, exercised in development under
    :func:`simulated_release_view` -- no flight is built."""

    def test_resolve_refuses_pressure_units_fix_by_name_simulated(self):
        before = (dict(registry.REGISTRY), dict(registry.OMITTED))
        with simulated_release_view():
            self.assertIn("pressure_units_fix", set(registry.OMITTED))
            self.assertNotIn("pressure_units_fix", registry.resolve({"all": True}, engine="3.5"))
            with self.assertRaisesRegex(registry.UnknownEnhancement, "pressure_units_fix"):
                registry.resolve({"pressure_units_fix": True}, engine="3.5")
            # the run TOML this module writes no longer requests it
            toml = _toml(Path(tempfile.mkdtemp()), engine="3.5", profile="stock-v3.5")
            try:
                self.assertNotIn("pressure_units_fix", toml.read_text(encoding="utf-8"))
            finally:
                shutil.rmtree(toml.parent, ignore_errors=True)
        self.assertEqual((registry.REGISTRY, registry.OMITTED), before)  # restored

    def test_a_name_neither_registered_nor_omitted_still_fails(self):
        for view in (contextlib.nullcontext, simulated_release_view):
            with self.subTest(view=view.__name__), view():
                self.assertNotIn("pressure_units_fixx", registry.OMITTED)
                with self.assertRaises(registry.UnknownEnhancement):
                    registry.resolve({"pressure_units_fixx": True}, engine="3.5")


@unittest.skipUnless(ALLOWLIST.is_file(), "release view: the allow-list does not ship")
class TheDevelopmentViewOmitsNothing(unittest.TestCase):
    """With the allow-list present (development), pressure_units_fix and the other
    v3.1.4-only modules ship, so no release-view excusal above can fire here."""

    def test_nothing_is_omitted(self):
        self.assertEqual(registry.OMITTED, {})
        self.assertEqual(applicability.OMITTED_APPLICABILITY, {})
        self.assertIn("pressure_units_fix", registry.REGISTRY)


class ChainComposition(unittest.TestCase):
    """Ranked uncertainty 4 (plan section 5): a second proc-stage applier must compose onto
    the file the first one wrote, in the chain's declared order, never re-derive from the
    port's output."""

    @unittest.skipUnless(_V314, _NO_V314)
    def test_two_proc_appliers_both_leave_their_names_comma_joined_in_chain_order(self):
        root, raw, toml = _setup("STOCK_V314", "3.1.4")
        try:
            enhancements = {name: False for name in registry.REGISTRY}
            enhancements["hole_edge_swap"] = True
            enhancements["outoffocus"] = True
            lines = [
                "[fidelity]", 'profile = "STOCK_V314"',
                "[run]", 'engine = "3.1.4"', 'preset = "DEMO_2DS_H"',
                'out = "_decoded"', 'stages = "234"', 'tas_file = "aircraft.cdf"',
                # see `_toml` above: the confirmation gate needs a declared policy, and
                # `liquid-warm` restates the stock values rather than changing them.
                "[thresholds]", 'regime = "liquid-warm"',
                "[enhancements]",
                *(f"{k} = {'true' if v else 'false'}" for k, v in enhancements.items()),
            ]
            toml.write_text("\n".join(lines) + "\n", encoding="utf-8")
            report = pipeline.apply_enhancements(toml, [raw], port_validation=True)[0]
            self.assertEqual(sorted(report["applied"]),
                             ["hole_edge_swap", "outoffocus"])
            enh = root / "_decoded" / f"{STEM}.enh.proc.nc"
            with netCDF4.Dataset(enh) as ds:
                names = ds.enhancements_applied.split(",")
            # the chain's declared order (pipeline._APPLIERS, which the driver follows within a
            # stage), not the registry's and not call order
            applier_order = [n for n in pipeline._APPLIERS if n in names]
            self.assertEqual(names, applier_order)
            self.assertIn("hole_edge_swap", names)
            self.assertIn("outoffocus", names)
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
