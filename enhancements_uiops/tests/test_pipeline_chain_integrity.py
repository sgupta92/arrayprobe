# SPDX-License-Identifier: BSD-3-Clause
"""The enhancement chain in ``pipeline.apply_to_outputs``: order, records and sidecars.

Each class pins one property of the chain that a correctness review found broken:

* the proc-stage corrections run in the order ``pipeline._APPLIERS`` declares, so the
  glitch repair acts on a probetype-1 clock before the rollback correction reads it;
* the glitch repair's policy (repair or drop) and what it did travel in the provenance
  record, not only the classifier's verdict;
* an enhanced sd keeps the TAS quality record (``<sd>.tasqc.json``) of the sd it descends
  from, so the CF and ARM exports of the enhanced chain state which seconds used a default
  airspeed rather than reporting the record absent;
* the ``protective`` switch in ``[enhancements]`` is a driver setting, not a module name;
* an ARM export the source file cannot satisfy is a named skip of that export, as it is for
  the CF export, never a failure of every other correction in the pass.
"""

from __future__ import annotations

import contextlib
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import netCDF4
import numpy as np

from arrayprobe_enhancements import applicability, pipeline, registry

ROOT = Path(__file__).resolve().parents[2]
#: Present in the development repository, absent from a release tree (it does not ship).
ALLOWLIST = ROOT / "scripts" / "release_allowlist.txt"
PIP_PROC = ROOT / "tests" / "data" / "s7a_pip_octave_golden.nc"
STEM = "base160912120000"
ARM_IDS = {"site_id": "ena", "platform_id": "aaf2dsh", "facility_id": "F1"}


def unaccounted_appliers(order) -> list[str]:
    """``_APPLIERS`` keys that are neither registered nor omitted by this distribution."""
    return sorted(n for n in order if n not in registry.REGISTRY and n not in registry.OMITTED)


def excused_appliers(order) -> list[str]:
    """``_APPLIERS`` keys whose module this distribution omits (empty in development)."""
    return sorted(n for n in order if n in registry.OMITTED)


@contextlib.contextmanager
def simulated_release_view():
    """The release view inside the development tree: every ``REQUIRES_V314`` module moved
    from ``REGISTRY``/``APPLICABILITY`` to ``OMITTED``/``OMITTED_APPLICABILITY``, as the
    import-time pass does when the module file is absent. All four tables are restored."""
    names = sorted(applicability.REQUIRES_V314 & set(registry.REGISTRY))
    with mock.patch.dict(registry.REGISTRY), mock.patch.dict(registry.OMITTED),             mock.patch.dict(applicability.APPLICABILITY),             mock.patch.dict(applicability.OMITTED_APPLICABILITY):
        for n in names:
            registry.OMITTED[n] = registry.REGISTRY.pop(n)
            applicability.OMITTED_APPLICABILITY[n] = applicability.APPLICABILITY.pop(n)
        yield names


def _only(*names: str) -> dict[str, bool]:
    return {n: n in names for n in registry.REGISTRY}


def _stamp(path: Path, text: str = "engine=3.5 profile=stock-v3.5") -> None:
    path.with_name(path.name + ".call").write_text(text + "\n", encoding="utf-8")


def _write_sd(path: Path, extra_variable: bool = False) -> None:
    """A minimal sizeDist-shaped sd file (the shape ``test_arm_export`` uses)."""
    with netCDF4.Dataset(str(path), "w", format="NETCDF3_CLASSIC") as d:
        d.createDimension("Time", 4)
        d.createVariable("time", "f8", ("Time",))[:] = [120000.0, 120001.0, 120002.0, 120003.0]
        n = d.createVariable("n", "f8", ("Time",))
        n[:] = [1.0, 2.0, 3.0, 4.0]
        n.units = "cm-3"
        n.long_name = "number concentration"
        if extra_variable:
            # A variable no CF mapping covers: the ARM export's variable pass refuses it.
            v = d.createVariable("not_a_sizedist_variable", "f8", ("Time",))
            v[:] = 0.0
            v.units = "1"


def _qc_record():
    from arrayprobe.tools import tas_sources as ts
    rec = ts.qc_record(None, ts.TasPolicy(), [120000.0, 120001.0, 120002.0, 120003.0],
                       [120002], None)
    return ts, rec


class _TmpDir(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out = Path(self._tmp.name)


@unittest.skipUnless(PIP_PROC.is_file(), "Probetype-1 proc fixture is not distributed with the "
                                         "package; this test runs in the development repository")
class GlitchRepairRunsBeforeTheRollbackCorrection(_TmpDir):
    """Both probetype-1 clock corrections ON: a glitched header time is repaired first, so
    the rollback correction never reads it as a midnight crossing and adds a day to the
    rest of the flight."""

    def _glitched_proc(self) -> Path:
        proc = self.out / f"proc.{STEM}.H.nc"
        shutil.copyfile(PIP_PROC, proc)
        with netCDF4.Dataset(proc, "a") as ds:
            for name in ("particle_time", "Time_in_seconds"):
                var = ds.variables[name]
                var.set_auto_mask(False)
                v = np.asarray(var[:]).ravel().copy()
                v[400] = 0          # an all-zero header: inside the 61340 run, recoverable
                var[:] = v
        _stamp(proc)
        return proc

    def _run_both(self):
        self._glitched_proc()
        [report] = pipeline.apply_to_outputs(
            "unused.toml", "3.5", self.out, [STEM],
            _only("particle_time_glitch_fix", "int_arr_rollback_fix"), preset_probetype=1)
        with netCDF4.Dataset(self.out / f"{STEM}.enh.proc.nc") as ds:
            ds.set_auto_mask(False)
            tis = np.asarray(ds.variables["Time_in_seconds"][:]).ravel()
        return report, tis

    @staticmethod
    def _clean_max() -> float:
        with netCDF4.Dataset(PIP_PROC) as ds:
            ds.set_auto_mask(False)
            return float(np.max(ds.variables["Time_in_seconds"][:]))

    def test_the_enhanced_clock_gains_no_day(self):
        report, tis = self._run_both()
        self.assertEqual(report["stages"]["proc"],
                         ["particle_time_glitch_fix", "int_arr_rollback_fix"])
        self.assertTrue(np.all(np.diff(tis) >= 0))
        self.assertLessEqual(float(tis.max()), self._clean_max(),
                             "a day was added at the glitch: the rollback correction ran first")

    def test_mutation_in_registry_order_the_day_comes_back(self):
        """The assertion above has teeth: iterate in registry order and the day is added."""
        def registry_order(reg, stage):
            return [n for n, spec in reg.items() if spec.stage == stage]

        with mock.patch.object(pipeline, "_ordered_for_stage", registry_order):
            report, tis = self._run_both()
        self.assertEqual(report["stages"]["proc"],
                         ["int_arr_rollback_fix", "particle_time_glitch_fix"])
        self.assertGreater(float(tis.max()), self._clean_max() + 86000.0)

    def _assert_loop_follows_declared_order(self):
        order = list(pipeline._APPLIERS)
        self.assertLess(order.index("particle_time_glitch_fix"),
                        order.index("int_arr_rollback_fix"))
        self.assertEqual(unaccounted_appliers(order), [])
        # An applier whose module this distribution omits (release view only; empty in
        # development, see TheDevelopmentViewOmitsNothing) is refused by resolve(), so it
        # never reaches the loop.
        for name in excused_appliers(order):
            with self.assertRaisesRegex(registry.UnknownEnhancement, name):
                registry.resolve({name: True}, engine="3.5")
        wired = [n for n in pipeline._ordered_for_stage(registry.REGISTRY, "proc")
                 if n in pipeline._APPLIERS]
        self.assertEqual(wired, [n for n in order if n in registry.REGISTRY
                                 and registry.REGISTRY[n].stage == "proc"])

    def test_the_loop_follows_the_declared_applier_order(self):
        self._assert_loop_follows_declared_order()

    def test_the_loop_follows_the_declared_applier_order_release_view_simulated(self):
        with simulated_release_view():
            omitted = set(registry.OMITTED) & set(pipeline._APPLIERS)
            self.assertTrue(omitted)  # pressure_units_fix keeps its applier
            self.assertEqual(excused_appliers(pipeline._APPLIERS), sorted(omitted))
            self._assert_loop_follows_declared_order()

    def test_an_applier_neither_registered_nor_omitted_still_fails(self):
        order = [*pipeline._APPLIERS, "no_such_fix"]
        self.assertEqual(unaccounted_appliers(order), ["no_such_fix"])
        with simulated_release_view():
            self.assertEqual(unaccounted_appliers(order), ["no_such_fix"])


@unittest.skipUnless(ALLOWLIST.is_file(), "release view: the allow-list does not ship")
class TheDevelopmentViewOmitsNothing(unittest.TestCase):
    """With the allow-list present (development), every ``_APPLIERS`` key is registered:
    the release-view excusal above cannot fire here."""

    def test_every_applier_is_registered(self):
        self.assertEqual(registry.OMITTED, {})
        self.assertEqual(excused_appliers(pipeline._APPLIERS), [])
        self.assertLessEqual(set(pipeline._APPLIERS), set(registry.REGISTRY))


@unittest.skipUnless(PIP_PROC.is_file(), "Probetype-1 proc fixture is not distributed with the "
                                         "package; this test runs in the development repository")
class GlitchPolicyIsInTheRecord(_TmpDir):
    """Under ``policy="drop"`` nothing is recovered; a record carrying only the classifier's
    ``counts`` (which says one particle *could* be recovered) would read as a repair."""

    def test_drop_is_recorded_with_what_it_did(self):
        GlitchRepairRunsBeforeTheRollbackCorrection._glitched_proc(self)
        [report] = pipeline.apply_to_outputs(
            "unused.toml", "3.5", self.out, [STEM], _only("particle_time_glitch_fix"),
            preset_probetype=1, policies={"particle_time_glitch_fix": {"policy": "drop"}})
        details = report["details"]["particle_time_glitch_fix"]
        self.assertEqual(details["policy"], "drop")
        self.assertEqual(details["applied"]["policy"], "drop")
        self.assertEqual(details["applied"]["dropped"], 1)
        self.assertEqual(details["applied"]["repaired"], 0)


class _FakeRunner:
    """Stands in for ``scripts/run_flight.py``'s ``EnhancedStages``: S4 "rebuilds" the sd by
    writing a fresh sd and, as the real one does, its ``.tasqc.json`` beside the path it
    was handed."""

    def __init__(self):
        self.ts, self.rec = _qc_record()

    def sizedist(self, proc, raw_stem, dst):
        _write_sd(Path(dst))
        self.ts.write_qc_sidecar(Path(dst), self.rec)

    def stamp(self, target, source, names, rebuilt=()):
        _stamp(Path(target), f"engine=3.5 enhancements={','.join(names)}")


def _fake_proc_applier(outputs):
    src = pipeline._enhanced_or_original(outputs, "proc")
    dst = pipeline._enh_path(outputs, "proc")
    tmp = pipeline._tmp_for(dst)
    pipeline._copy_netcdf(src, tmp)
    return pipeline._finish_enh_copy(tmp, dst, ["hole_edge_swap"])


def _fake_sd_applier(outputs):
    src = pipeline._enhanced_or_original(outputs, "sd")
    dst = pipeline._enh_path(outputs, "sd")
    tmp = pipeline._tmp_for(dst)
    pipeline._copy_netcdf(src, tmp)
    return pipeline._finish_enh_copy(tmp, dst, ["published_dof"])


class TheEnhancedSdKeepsItsTasQcRecord(_TmpDir):
    def setUp(self):
        super().setUp()
        self.sd = self.out / f"sd.{STEM}.H.nc"
        _write_sd(self.sd)
        _stamp(self.sd)
        self.ts, rec = _qc_record()
        self.ts.write_qc_sidecar(self.sd, rec)
        self.enh_sd = self.out / f"{STEM}.enh.sd.nc"

    def _assert_carried(self):
        self.assertTrue(self.ts.qc_sidecar_path(self.enh_sd).is_file(),
                        "the enhanced sd has no .tasqc.json")
        self.assertEqual(sorted(p.name for p in self.out.glob("*.tmp*")), [])
        with netCDF4.Dataset(self.out / f"{STEM}.enh.arm.nc") as ds:
            self.assertIn("qc_tas", ds.variables)
            self.assertNotIn("arrayprobe_tas_qc", ds.ncattrs())

    def test_an_sd_rebuilt_from_the_enhanced_proc(self):
        proc = self.out / f"proc.{STEM}.H.nc"
        _write_sd(proc)          # any netCDF: the fake proc applier only copies it
        _stamp(proc)
        with mock.patch.dict(pipeline._APPLIERS, {"hole_edge_swap": _fake_proc_applier}):
            [report] = pipeline.apply_to_outputs(
                "unused.toml", "3.5", self.out, [STEM], _only("hole_edge_swap", "arm_export"),
                arm_config=ARM_IDS, runner=_FakeRunner())
        self.assertEqual(report["rebuilt"], {"S4": self.enh_sd.name})
        self.assertIn("arm_export", report["applied"])
        self._assert_carried()

    def test_an_sd_written_by_an_sd_stage_correction(self):
        with mock.patch.dict(pipeline._APPLIERS, {"published_dof": _fake_sd_applier}):
            [report] = pipeline.apply_to_outputs(
                "unused.toml", "3.5", self.out, [STEM], _only("published_dof", "arm_export"),
                arm_config=ARM_IDS)
        self.assertEqual(report["applied"], ["arm_export", "published_dof"])
        self._assert_carried()


class TheProtectiveSwitchIsNotAModuleName(unittest.TestCase):
    """``[enhancements] protective = false`` is documented (the CIP example's README) as the
    way to turn the protective corrections off; ``arrayprobe-enhanced run`` resolves the same
    table and must not refuse it as an unknown enhancement."""

    def test_resolve_accepts_it_and_returns_modules_only(self):
        for value in (True, False):
            got = registry.resolve({"protective": value, "hole_edge_swap": True}, "3.5")
            self.assertNotIn("protective", got)
            self.assertEqual(set(got), set(registry.REGISTRY))
            self.assertTrue(got["hole_edge_swap"])

    def test_it_switches_no_module_on(self):
        self.assertFalse(any(registry.resolve({"protective": True}, "3.5").values()))


class NothingToDropIsASkip(_TmpDir):
    """A proc without ``Particle_number_all`` gives the correction nothing to drop: it is a
    named skip, not an applied correction stamped on an unchanged copy."""

    def test_an_absent_column_is_not_applied(self):
        proc = self.out / f"proc.{STEM}.H.nc"
        _write_sd(proc)          # a netCDF file with no Particle_number_all
        _stamp(proc)
        [report] = pipeline.apply_to_outputs(
            "unused.toml", "3.5", self.out, [STEM], _only("particle_number_all_fix"))
        self.assertNotIn("particle_number_all_fix", report["applied"])
        self.assertIn("absent", report["skipped"]["particle_number_all_fix"])
        self.assertFalse((self.out / f"{STEM}.enh.proc.nc").exists())


class AnArmExportRefusalIsASkip(_TmpDir):
    def test_the_pass_completes_and_names_the_skip(self):
        sd = self.out / f"sd.{STEM}.H.nc"
        _write_sd(sd, extra_variable=True)
        _stamp(sd)
        [report] = pipeline.apply_to_outputs(
            "unused.toml", "3.5", self.out, [STEM], _only("arm_export", "arco_export"),
            arm_config=ARM_IDS)
        self.assertIn("arco_export", report["applied"])
        self.assertIn("arm_export", report["skipped"])
        self.assertIn("refused", report["skipped"]["arm_export"])
        self.assertFalse((self.out / f"{STEM}.enh.arm.nc").exists())
        self.assertTrue(Path(f"{sd}.enhancements.json").is_file())

# _release_fixture_guard: needs a real field-campaign file, not in the release
import unittest as _rfg_unittest  # noqa: E402
raise _rfg_unittest.SkipTest(
    "this test needs a real field-campaign PIP file (about 1,200 particles); the "
    "shipped fixture is a small synthetic stand-in, and this release does not include real data")

if __name__ == "__main__":
    unittest.main()
