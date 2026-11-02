# SPDX-License-Identifier: BSD-3-Clause
"""The ARM/CF export must be readable by generic tools and lose no values.

**Why these are the assertions.** The whole point (plan S3C, item 22) is that
a generic reader -- ``xarray``, ACT's ``act.io.read_arm_netcdf`` (the module's
own docstring named ``act.io.read_netcdf`` until 2026-09-10; the real ACT
package renamed that function before this project ever tested against it, so
the citation was wrong from the day it was written, not from later drift) --
opens the file and gets a real, decodable time axis, not that the file merely
parses. So this decodes ``time`` the way ``xarray``/CF tooling would (an
offset plus a ``"seconds since <date>"`` units string) and checks the
wall-clock result, rather than only checking that the attribute exists.
``ReadableByRealArmTools`` below closes the ACT half of that claim for real,
which had never actually been run against the real package before.

Exercised against **the real tracked S4 fixture**
(``tests/data/s4_sizedist_octave_golden.nc``), not only a
synthetic file shaped like one -- this is a structural transform of an actual
port-shaped output, and a synthetic stand-in could hide a dimension-name or
dtype assumption the real file breaks.
"""

from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np

from arrayprobe_enhancements.arm_export import (
    ArmExportReport,
    _hhmmss_to_offset_seconds,
    build_datastream_id,
    export,
)

ROOT = Path(__file__).resolve().parents[2]
REAL_FIXTURE = ROOT / "tests" / "data" / "demo_flight_v35_sd.nc"


def _write_source(path: Path) -> None:
    """A minimal file shaped like sizeDist's output: a 'Time' dimension, an
    HHMMSS 'time' variable, and one physical variable with the port's usual
    long_name/units attributes and no standard_name."""
    with netCDF4.Dataset(str(path), "w", format="NETCDF3_CLASSIC") as d:
        d.createDimension("Time", 4)
        d.createVariable("time", "f8", ("Time",))[:] = [235959.0, 240000.0, 240001.0, 240002.0]
        n = d.createVariable("n", "f8", ("Time",))
        n[:] = [1.0, 2.0, 3.0, 4.0]
        n.units = "cm-3"
        n.long_name = "number concentration"


class HhmmssDecoding(unittest.TestCase):
    def test_ordinary_values_convert_within_the_day(self):
        secs = _hhmmss_to_offset_seconds(np.array([0.0, 10000.0, 235959.0]))
        np.testing.assert_allclose(secs, [0.0, 3600.0, 86399.0])

    def test_the_preserved_rollover_bug_is_decoded_not_repaired(self):
        """sizeDist.m adds 240000 to the FIRST post-midnight second only
        (a preserved upstream bug, sizeDist.m:98-99). This function must
        decode that value into the next day, not reject it or normalise it
        away."""
        secs = _hhmmss_to_offset_seconds(np.array([235959.0, 240000.0, 240001.0]))
        np.testing.assert_allclose(secs, [86399.0, 86400.0, 86401.0])


class DatastreamId(unittest.TestCase):
    def test_matches_the_standards_document_formula(self):
        # S6.7.1 worked example: site_id + platform_id + facility_id + "." + data_level
        self.assertEqual(build_datastream_id("sgp", "mfrsr", "E32", "b1"), "sgpmfrsrE32.b1")


class ExportingASyntheticFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = Path(self.tmp.name) / "sd.synthetic.H.nc"
        _write_source(self.src)
        self.out = Path(self.tmp.name) / "sd.synthetic.H.arm.nc"

    def test_returns_a_report_naming_the_datastream(self):
        report = export(self.src, self.out, flight_date=dt.date(2016, 9, 6),
                         site_id="p3f", platform_id="oap2ds", facility_id="F1")
        self.assertIsInstance(report, ArmExportReport)
        self.assertEqual(report.datastream, "p3foap2dsF1.c1")
        self.assertEqual(report.n_times, 4)

    def test_the_time_axis_decodes_to_the_right_wall_clock_time(self):
        export(self.src, self.out, flight_date=dt.date(2016, 9, 6),
               site_id="p3f", platform_id="oap2ds", facility_id="F1")
        with netCDF4.Dataset(str(self.out)) as d:
            offsets = np.asarray(d.variables["time_offset"][:])
            units = d.variables["time"].units
            self.assertEqual(units, "seconds since 2016-09-06 00:00:00 0:00")
            # 23:59:59, then the rollover-decoded 00:00:00/01/02 of the NEXT day.
            np.testing.assert_allclose(offsets, [86399.0, 86400.0, 86401.0, 86402.0])
            base_time = int(np.asarray(d.variables["base_time"][:]))
            wallclock = dt.datetime.fromtimestamp(base_time, tz=dt.timezone.utc) \
                + dt.timedelta(seconds=float(offsets[1]))
            self.assertEqual(wallclock, dt.datetime(2016, 9, 7, 0, 0, 0, tzinfo=dt.timezone.utc))

    def test_the_original_hhmmss_encoding_is_preserved_not_discarded(self):
        export(self.src, self.out, flight_date=dt.date(2016, 9, 6),
               site_id="p3f", platform_id="oap2ds", facility_id="F1")
        with netCDF4.Dataset(str(self.out)) as d, netCDF4.Dataset(str(self.src)) as s:
            np.testing.assert_array_equal(d.variables["time_hhmmss"][:], s.variables["time"][:])

    def test_a_physical_variable_is_copied_verbatim_with_no_invented_standard_name(self):
        export(self.src, self.out, flight_date=dt.date(2016, 9, 6),
               site_id="p3f", platform_id="oap2ds", facility_id="F1")
        with netCDF4.Dataset(str(self.out)) as d:
            np.testing.assert_array_equal(d.variables["n"][:], [1.0, 2.0, 3.0, 4.0])
            self.assertEqual(d.variables["n"].units, "cm-3")
            self.assertEqual(d.variables["n"].long_name, "number concentration")
            self.assertNotIn("standard_name", d.variables["n"].ncattrs(),
                              "CF forbids inventing a standard_name that is not "
                              "in its own table; this variable has none there")

    def test_required_global_attributes_are_present(self):
        export(self.src, self.out, flight_date=dt.date(2016, 9, 6),
               site_id="p3f", platform_id="oap2ds", facility_id="F1",
               command_line="arrayprobe run-flight --preset DEMO")
        with netCDF4.Dataset(str(self.out)) as d:
            for attr in ("command_line", "Conventions", "process_version", "site_id",
                         "platform_id", "facility_id", "data_level", "datastream",
                         "title", "institution", "description", "history"):
                self.assertTrue(hasattr(d, attr), f"missing required attribute {attr!r}")
            self.assertIn("ARM-1.3", d.Conventions)
            self.assertIn("CF-1.9", d.Conventions)
            self.assertEqual(d.command_line, "arrayprobe run-flight --preset DEMO")

    def test_no_doi_and_no_qc_variables_are_invented(self):
        """These require an ARM Data Center registration or a QC framework
        this project does not have; claiming either would be dishonest."""
        export(self.src, self.out, flight_date=dt.date(2016, 9, 6),
               site_id="p3f", platform_id="oap2ds", facility_id="F1")
        with netCDF4.Dataset(str(self.out)) as d:
            self.assertFalse(hasattr(d, "doi"))
            self.assertEqual([v for v in d.variables if v.startswith("qc_")], [])


class SourceGlobalsAndRunProvenance(unittest.TestCase):
    """The gap ARM_OUTPUT_FORMAT.md and the 2026-09-21 ARM-output task named:
    export() dropped every incoming global attribute and had no way to carry
    the engine, the run's .call stamp, or the enhancements applicability
    report. These assert the fix, not just that export() still runs."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = Path(self.tmp.name) / "sd.synthetic.H.nc"
        _write_source(self.src)
        with netCDF4.Dataset(str(self.src), "a") as d:
            d.setncattr("Software", "UIOOPS_v3.5")
            d.setncattr("Project", "ARM_ENA")
        self.out = Path(self.tmp.name) / "sd.synthetic.H.arm.nc"

    def test_source_globals_are_preserved_under_a_prefix_by_default(self):
        export(self.src, self.out, flight_date=dt.date(2017, 7, 7),
               site_id="ena", platform_id="aaf2dsh", facility_id="F1")
        with netCDF4.Dataset(str(self.out)) as d:
            self.assertEqual(d.getncattr("arrayprobe_source_Software"), "UIOOPS_v3.5")
            self.assertEqual(d.getncattr("arrayprobe_source_Project"), "ARM_ENA")

    def test_source_globals_can_be_switched_off(self):
        export(self.src, self.out, flight_date=dt.date(2017, 7, 7),
               site_id="ena", platform_id="aaf2dsh", facility_id="F1",
               preserve_source_globals=False)
        with netCDF4.Dataset(str(self.out)) as d:
            self.assertFalse(any(a.startswith("arrayprobe_source_") for a in d.ncattrs()))

    def test_run_provenance_is_written_when_supplied(self):
        export(self.src, self.out, flight_date=dt.date(2017, 7, 7),
               site_id="ena", platform_id="aaf2dsh", facility_id="F1",
               engine="3.5",
               engine_validation="layer 2 only: Octave goldens on v3.5's own sources",
               stage="sd",
               call_stamp="engine=3.5 profile=stock-v3.5",
               enhancements_report='{"applied": ["arco_export"]}')
        with netCDF4.Dataset(str(self.out)) as d:
            self.assertEqual(d.getncattr("arrayprobe_engine"), "3.5")
            self.assertIn("layer 2", d.getncattr("arrayprobe_engine_validation"))
            self.assertEqual(d.getncattr("arrayprobe_stage"), "sd")
            self.assertEqual(d.getncattr("arrayprobe_call_stamp"), "engine=3.5 profile=stock-v3.5")
            self.assertIn("arco_export", d.getncattr("arrayprobe_enhancements_report"))

    def test_run_provenance_attributes_are_absent_not_guessed_when_not_supplied(self):
        """No engine, call stamp, etc. supplied -> none of these five
        attributes appear at all. A missing fact is never filled in."""
        export(self.src, self.out, flight_date=dt.date(2017, 7, 7),
               site_id="ena", platform_id="aaf2dsh", facility_id="F1")
        with netCDF4.Dataset(str(self.out)) as d:
            for attr in ("arrayprobe_engine", "arrayprobe_engine_validation",
                         "arrayprobe_stage", "arrayprobe_call_stamp",
                         "arrayprobe_enhancements_report"):
                self.assertFalse(hasattr(d, attr), f"{attr!r} should be absent, not guessed")


@unittest.skipUnless(REAL_FIXTURE.is_file(), "tracked S4 golden fixture is missing")
class ExportingTheRealS4Fixture(unittest.TestCase):
    """The real port-shaped file, not a synthetic stand-in -- its 'Time'
    dimension, real variable set (conc_minR, habitsd, ...) and real HHMMSS
    values are exactly what a caller will actually hand this function."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "s4.arm.nc"

    def test_every_source_value_survives_untouched(self):
        export(REAL_FIXTURE, self.out, flight_date=dt.date(2016, 9, 6),
               site_id="p3f", platform_id="oap2ds", facility_id="F1")
        with netCDF4.Dataset(str(REAL_FIXTURE)) as s, netCDF4.Dataset(str(self.out)) as d:
            for name, var in s.variables.items():
                if name == "time":
                    continue
                with self.subTest(variable=name):
                    np.testing.assert_array_equal(np.asarray(var[:]), np.asarray(d.variables[name][:]))

    def test_the_time_dimension_length_matches(self):
        with netCDF4.Dataset(str(REAL_FIXTURE)) as s:
            n_time = s.dimensions["Time"].size
        report = export(REAL_FIXTURE, self.out, flight_date=dt.date(2016, 9, 6),
                         site_id="p3f", platform_id="oap2ds", facility_id="F1")
        self.assertEqual(report.n_times, n_time)


try:
    from act.io import read_arm_netcdf as _act_read_arm_netcdf
except ImportError:  # pragma: no cover -- act-atmos is a heavy, optional dependency
    _act_read_arm_netcdf = None


@unittest.skipUnless(_act_read_arm_netcdf is not None,
                     "act-atmos not installed -- a heavy optional dependency "
                     "(dask, pandas, xarray, pint, metpy, ...) this project "
                     "does not declare as a dependency or extra; install `act-atmos` "
                     "yourself to run this check")
class ReadableByRealArmTools(unittest.TestCase):
    """Plan row 14's actual exit criterion: ``ACT's read_netcdf opens the
    copy``, run against the real package rather than assumed from its name.

    Never wired into CI or any declared extra -- act-atmos pulls in dask,
    pandas, xarray, pint, metpy and a dozen more packages, which this
    project's own dependency discipline (no new dependency
    without a real need) does not justify for a single interop check. This
    test exists so the claim is checkable by anyone who installs the real
    package, not asserted from its docstring.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "s4.arm.nc"
        export(REAL_FIXTURE, self.out, flight_date=dt.date(2016, 9, 6),
               site_id="ena", platform_id="aaf2ds", facility_id="F1",
               institution="ANL")

    def test_act_opens_it_and_flags_it_arm_standard(self):
        ds = _act_read_arm_netcdf(str(self.out))
        try:
            # ACT's own reader sets this iff the file passed its ARM-standard
            # structural checks -- the strongest available signal that a
            # generic ARM tool, not just this project's own parser, accepts
            # the file's shape.
            self.assertEqual(ds.attrs.get("_arm_standards_flag"), 1)
            self.assertEqual(ds.attrs.get("_datastream"), "enaaaf2dsF1.c1")
            self.assertIn("time", ds.variables)
            self.assertIn("base_time", ds.variables)
        finally:
            ds.close()


class DriverAdapter(unittest.TestCase):
    """arm_export reachable through arrayprobe_enhancements.pipeline, not only by
    calling export() from Python. Exercises pipeline._apply_arm_export directly against a
    hand-built _RunOutputs, the same shape test_pipeline_adapters.py uses for the other
    product-stage adapter (arco_export) -- kept in this file per the task's own instruction
    that arm_export's tests, including its driver wiring, live here.

    THE RULE UNDER TEST: never invent or default an ARM identifier. Absent or incomplete
    [arm] -> a named ApplierSkip, never a placeholder datastream.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out_dir = Path(self.tmp.name)
        self.src = self.out_dir / "sd.base170707102822.H.nc"
        _write_source(self.src)

    def _outputs(self, **overrides):
        from arrayprobe_enhancements.pipeline import _RunOutputs
        base = dict(out_dir=self.out_dir, raw_stem="base170707102822", engine="3.5",
                   image=None, proc=None, sd=self.src, combined=None)
        base.update(overrides)
        return _RunOutputs(**base)

    def test_it_is_registered_as_a_wired_adapter(self):
        from arrayprobe_enhancements.pipeline import _APPLIERS
        self.assertIn("arm_export", _APPLIERS)

    def test_no_longer_listed_as_having_no_adapter(self):
        """The whole point: this module must stop reporting itself unreachable."""
        from arrayprobe_enhancements.pipeline import _NO_ADAPTER_REASON_BY_NAME
        self.assertNotIn("arm_export", _NO_ADAPTER_REASON_BY_NAME)

    def test_refuses_without_an_arm_section(self):
        from arrayprobe_enhancements.pipeline import ApplierSkip, _apply_arm_export
        outputs = self._outputs(arm={}, flight_date="20170707")
        with self.assertRaises(ApplierSkip) as cm:
            _apply_arm_export(outputs)
        self.assertIn("[arm]", str(cm.exception))
        self.assertIn("never invented", str(cm.exception))

    def test_refuses_on_a_partial_arm_section(self):
        """Belt and suspenders: arrayprobe.config._load_arm already refuses a partial [arm]
        table at load time, but the adapter must not silently proceed with two of three
        either, in case something ever hands it a hand-built dict that skipped that check."""
        from arrayprobe_enhancements.pipeline import ApplierSkip, _apply_arm_export
        outputs = self._outputs(arm={"site_id": "ena", "platform_id": "aaf2dsh"},
                                flight_date="20170707")
        with self.assertRaises(ApplierSkip) as cm:
            _apply_arm_export(outputs)
        self.assertIn("facility_id", str(cm.exception))

    def test_refuses_without_a_flight_date(self):
        from arrayprobe_enhancements.pipeline import ApplierSkip, _apply_arm_export
        outputs = self._outputs(
            arm={"site_id": "ena", "platform_id": "aaf2dsharrayprobev35", "facility_id": "F1"},
            flight_date=None)
        with self.assertRaises(ApplierSkip) as cm:
            _apply_arm_export(outputs)
        self.assertIn("flight date", str(cm.exception))

    def test_refuses_with_no_sd_output(self):
        from arrayprobe_enhancements.pipeline import ApplierSkip, _apply_arm_export
        outputs = self._outputs(
            sd=None,
            arm={"site_id": "ena", "platform_id": "aaf2dsharrayprobev35", "facility_id": "F1"},
            flight_date="20170707")
        with self.assertRaises(ApplierSkip):
            _apply_arm_export(outputs)

    def test_a_config_supplying_ids_reaches_the_real_export(self):
        """The success path: real ids in outputs.arm and a real flight_date produce a real
        ARM-convention file through the driver adapter."""
        from arrayprobe_enhancements.pipeline import _apply_arm_export
        outputs = self._outputs(
            arm={"site_id": "ena", "platform_id": "aaf2dsharrayprobev35", "facility_id": "F1"},
            flight_date="20170707")
        dst = _apply_arm_export(outputs)
        self.assertTrue(dst.is_file())
        with netCDF4.Dataset(str(dst)) as d:
            self.assertEqual(d.datastream, "enaaaf2dsharrayprobev35F1.c1")
            self.assertEqual(d.site_id, "ena")
            self.assertEqual(d.data_level, "c1")  # export()'s own default, not named in [arm]
            self.assertEqual(d.arrayprobe_engine, "3.5")
            self.assertEqual(d.arrayprobe_stage, "sd")
            self.assertIn("arm_export", d.enhancements_applied)

    def test_a_named_data_level_overrides_the_default(self):
        from arrayprobe_enhancements.pipeline import _apply_arm_export
        outputs = self._outputs(
            arm={"site_id": "ena", "platform_id": "aaf2dsharrayprobev35", "facility_id": "F1",
                "data_level": "b1"},
            flight_date="20170707")
        dst = _apply_arm_export(outputs)
        with netCDF4.Dataset(str(dst)) as d:
            self.assertEqual(d.data_level, "b1")


class ThreadedThroughApplyToOutputs(unittest.TestCase):
    """The wiring one level up: RunConfig.arm -> apply_to_outputs's arm_config parameter ->
    _RunOutputs.arm -> the driver adapter -- without running the port, since locate_outputs
    only needs an already-stamped sd file on disk."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out_dir = Path(self.tmp.name)
        self.stem = "base170707102822"
        self.sd = self.out_dir / f"sd.{self.stem}.H.nc"
        _write_source(self.sd)
        (self.out_dir / f"sd.{self.stem}.H.nc.call").write_text(
            "engine=3.5 profile=stock-v3.5", encoding="utf-8")

    def _resolved_only_arm_export(self):
        from arrayprobe_enhancements import registry
        return {n: (n == "arm_export") for n in registry.REGISTRY}

    def test_arm_config_reaches_the_written_file(self):
        from arrayprobe_enhancements.pipeline import apply_to_outputs
        reports = apply_to_outputs(
            "unused.toml", "3.5", self.out_dir, [self.stem], self._resolved_only_arm_export(),
            arm_config={"site_id": "ena", "platform_id": "aaf2dsharrayprobev35",
                       "facility_id": "F1"})
        self.assertEqual(len(reports), 1)
        self.assertIn("arm_export", reports[0]["applied"])
        dst = self.out_dir / f"{self.stem}.enh.arm.nc"
        self.assertTrue(dst.is_file())
        with netCDF4.Dataset(str(dst)) as d:
            self.assertEqual(d.datastream, "enaaaf2dsharrayprobev35F1.c1")

    def test_without_arm_config_the_driver_names_the_skip_not_a_placeholder(self):
        from arrayprobe_enhancements.pipeline import apply_to_outputs
        reports = apply_to_outputs("unused.toml", "3.5", self.out_dir, [self.stem],
                                   self._resolved_only_arm_export())
        self.assertNotIn("arm_export", reports[0]["applied"])
        self.assertIn("arm_export", reports[0]["skipped"])
        self.assertIn("[arm]", reports[0]["skipped"]["arm_export"])
        self.assertFalse((self.out_dir / f"{self.stem}.enh.arm.nc").exists())


if __name__ == "__main__":
    unittest.main()


class QcTas(unittest.TestCase):
    """Step 8 (TAS gap in file metadata): ``qc_tas`` bits follow the source's ``.tasqc.json``; no record, no QC
    variable, and a global that says the record is absent."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = Path(self.tmp.name) / "sd.synthetic.H.nc"
        _write_source(self.src)
        self.out = Path(self.tmp.name) / "out.nc"

    def _export(self):
        export(self.src, self.out, flight_date=dt.date(2016, 9, 6),
               site_id="p3f", platform_id="oap2ds", facility_id="F1")
        return netCDF4.Dataset(str(self.out))

    def test_bits_match_the_record(self):
        from arrayprobe.tools import tas_sources as ts
        rec = ts.qc_record(None, ts.TasPolicy(), [235959.0, 240000.0, 240001.0, 240002.0],
                           [240001], None)
        rec["tas_substituted_ranges"] = "235959"
        ts.write_qc_sidecar(self.src, rec)
        with self._export() as ds:
            self.assertEqual(list(ds.variables["qc_tas"][:]), [1, 0, 2, 0])
            self.assertEqual(ds.variables["qc_tas"].flag_method, "bit")
            self.assertEqual(ds.getncattr("arrayprobe_tas_missing_count"), 1)

    def test_no_record_no_qc_variable(self):
        with self._export() as ds:
            self.assertNotIn("qc_tas", ds.variables)
            self.assertTrue(ds.getncattr("arrayprobe_tas_qc").startswith("absent"))
