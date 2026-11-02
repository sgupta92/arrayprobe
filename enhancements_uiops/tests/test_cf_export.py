# SPDX-License-Identifier: BSD-3-Clause
"""cf_export: a CF-1.10 sibling of a port sd file, and arm_export's delegation.

**Where each check draws its two sides.** The unit check parses the *written*
``units`` strings with this file's own udunits-subset parser (``cf_units`` and
``pint`` are not in the venv -- measured 2026-09-15 -- so a table-driven parser
is the stated fallback; ``cf_units`` is used too when importable). The
round trip reads the *source* file and the *exported* file and derives the
expected factor from the two unit strings through that parser, never from
``cf_export.VARIABLE_MAP``. The standard-name allowlist below is hand-checked
against the CF standard-name table and is not imported from the module.

Fixtures: the two tracked demo sd outputs (v3.1.4 NETCDF3_CLASSIC, v3.5
NETCDF4 -- both have empty size distributions) and two Octave-written sizeDist
goldens that hold real particles, so the rescale is exercised on non-zero values.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cftime
import netCDF4
import numpy as np

from arrayprobe_enhancements import arm_export, cf_export

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "tests" / "data"
FIXTURES = {
    "v314_demo": DATA / "demo_flight_v314_sd.nc",
    "v35_demo": DATA / "demo_flight_v35_sd.nc",
    "octave_s4": DATA / "s4_sizedist_octave_golden.nc",
    "octave_pip": DATA / "s7b_pip_sizedist_octave_golden.nc",
}


class _Present(dict):
    """The Octave goldens are real-data fixtures that are not distributed: absent
    ones are dropped, and a test that names one by key skips with that reason."""

    def __missing__(self, key):
        raise unittest.SkipTest(
            f"{key} is a real-data fixture that is not distributed")


FIXTURES = _Present({k: v for k, v in FIXTURES.items() if v.is_file()})
DATE = dt.date(2016, 9, 6)

#: Hand-checked against the CF standard-name table (cfconventions.org,
#: standard-name table): ``time`` is an entry. Nothing else may be emitted.
CF_STANDARD_NAMES_ALLOWED = {"time"}

# --- a udunits subset parser: symbol[exponent] tokens separated by spaces -----------------
_PREFIX = {"k": 1e3, "c": 1e-2, "m": 1e-3, "u": 1e-6, "": 1.0}
_BASE = {"m": ("m", 1.0), "g": ("kg", 1e-3), "s": ("s", 1.0), "h": ("s", 3600.0)}
_TOKEN = re.compile(r"^(k|c|m|u)?(m|g|s|h)(-?\d+)?$")


def parse_units(text: str) -> tuple[float, dict[str, int]]:
    """Return (factor to SI, {base: exponent}); raises ValueError if the string
    is outside the udunits subset this exporter is allowed to write."""
    if text == "1":
        return 1.0, {}
    dims: dict[str, int]
    factor, dims = 1.0, {}
    for tok in text.split(" "):
        mt = _TOKEN.match(tok)
        if not mt:
            raise ValueError(f"not a udunits token: {tok!r} in {text!r}")
        prefix, sym, exp = mt.group(1) or "", mt.group(2), int(mt.group(3) or 1)
        base, f = _BASE[sym]
        factor *= (_PREFIX[prefix] * f) ** exp
        dims[base] = dims.get(base, 0) + exp
    return factor, {k: v for k, v in dims.items() if v}


try:
    import cf_units  # type: ignore
except ImportError:  # pragma: no cover
    cf_units = None


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


class _ExportCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def export(self, key: str, **kw):
        out = self.dir / f"{key}.cf.nc"
        cf_export.export(FIXTURES[key], out, flight_date=DATE, **kw)
        return out


class TheParserItself(unittest.TestCase):
    def test_known_strings(self):
        self.assertEqual(parse_units("m-4")[1], {"m": -4})
        f, d = parse_units("g cm-4")
        self.assertAlmostEqual(f, 1e-3 * 1e8)
        self.assertEqual(d, {"kg": 1, "m": -4})

    def test_the_three_non_cf_source_strings_are_rejected(self):
        for bad in ("100/100", "HHMMSS", "g/cm-4", "mm/hr"):
            with self.assertRaises(ValueError, msg=bad):
                parse_units(bad)


class EveryFixture(_ExportCase):
    def test_units_are_udunits_legal_and_dimensionally_equal_to_the_true_unit(self):
        for key in FIXTURES:
            out = self.export(key)
            with self.subTest(fixture=key), netCDF4.Dataset(str(out)) as d:
                for name, var in d.variables.items():
                    if "units" not in var.ncattrs() or name == "time":
                        continue
                    factor, dims = parse_units(var.units)
                    if cf_units is not None:
                        cf_units.Unit(var.units)
                    if hasattr(var, "arrayprobe_cf_scale"):
                        true = cf_export.mapping_for(name).true_units
                        f_true, d_true = parse_units(true)
                        self.assertEqual(dims, d_true, name)
                        # The recorded scale equals what the two unit strings imply.
                        np.testing.assert_allclose(var.arrayprobe_cf_scale,
                                                   f_true / factor, rtol=1e-12,
                                                   err_msg=name)

    def test_round_trip_equals_source_times_recorded_scale(self):
        for key in FIXTURES:
            out = self.export(key)
            with self.subTest(fixture=key), netCDF4.Dataset(str(FIXTURES[key])) as s, \
                    netCDF4.Dataset(str(out)) as d:
                for name, svar in s.variables.items():
                    if name == "time":
                        np.testing.assert_array_equal(d.variables["time_hhmmss"][:], svar[:])
                        continue
                    dvar = d.variables[name]
                    scale = dvar.arrayprobe_cf_scale
                    self.assertEqual(dvar.arrayprobe_source_units, svar.units)
                    np.testing.assert_array_equal(np.asarray(dvar[:]),
                                                  np.asarray(svar[:], float) * scale,
                                                  err_msg=name)
                    back = np.asarray(dvar[:]) / scale
                    np.testing.assert_allclose(back, np.asarray(svar[:], float),
                                               rtol=4e-16, atol=0, err_msg=name)

    def test_the_demo_file_exercises_nonzero_rescaled_values(self):
        out = self.export("v35_demo")
        with netCDF4.Dataset(str(out)) as d:
            self.assertGreater(np.nanmax(d.variables["conc_minR"][:]), 0.0)

    def test_standard_names_are_only_from_the_cf_table(self):
        for key in FIXTURES:
            with self.subTest(fixture=key), netCDF4.Dataset(str(self.export(key))) as d:
                used = {v.standard_name for v in d.variables.values()
                        if "standard_name" in v.ncattrs()}
                self.assertLessEqual(used, CF_STANDARD_NAMES_ALLOWED)
                self.assertEqual(d.variables["time"].standard_name, "time")

    def test_every_dimension_has_a_coordinate_and_bins_carry_bounds(self):
        for key in FIXTURES:
            with self.subTest(fixture=key), netCDF4.Dataset(str(self.export(key))) as d, \
                    netCDF4.Dataset(str(FIXTURES[key])) as s:
                for dim in d.dimensions:
                    if dim == "nv":
                        continue
                    self.assertIn(dim, d.variables, f"dimension {dim} has no coordinate")
                self.assertEqual(d.variables["bin"].bounds, "bin_bounds")
                bb = np.asarray(d.variables["bin_bounds"][:])
                np.testing.assert_array_equal(bb[:, 0], np.asarray(s["bin_min"][:]) * 1e-3)
                np.testing.assert_array_equal(bb[:, 1], np.asarray(s["bin_max"][:]) * 1e-3)
                self.assertEqual(d.variables["area_ratio_bin"].bounds, "area_ratio_bin_bounds")
                self.assertEqual(d.Conventions, "CF-1.10")

    def test_time_decodes_to_the_right_wall_clock(self):
        for key in FIXTURES:
            with self.subTest(fixture=key), netCDF4.Dataset(str(self.export(key))) as d, \
                    netCDF4.Dataset(str(FIXTURES[key])) as s:
                t = d.variables["time"]
                when = cftime.num2date(np.asarray(t[:]), t.units, t.calendar,
                                       only_use_cftime_datetimes=False,
                                       only_use_python_datetimes=True)
                hhmmss = np.asarray(s["time"][:])
                for w, h in zip(when, hhmmss, strict=True):
                    h = int(h)
                    day = DATE + dt.timedelta(days=1 if h >= 240000 else 0)
                    h %= 240000
                    self.assertEqual((w.date(), w.hour, w.minute, w.second),
                                     (day, h // 10000, h // 100 % 100, h % 100))

    def test_the_port_file_is_byte_unchanged(self):
        for key in FIXTURES:
            before = _sha(FIXTURES[key])
            self.export(key)
            with self.subTest(fixture=key):
                self.assertEqual(_sha(FIXTURES[key]), before)

    def test_provenance_names_source_engine_and_versions(self):
        with netCDF4.Dataset(str(self.export("v35_demo"))) as d:
            self.assertEqual(d.arrayprobe_cf_export_source, "demo_flight_v35_sd.nc")
            self.assertEqual(d.enhancements_engine, "3.5")
            self.assertIn("UIOPS 3.5 engine", d.source)
            self.assertTrue(d.comment.startswith(".call stamp of the source: engine=3.5"))
            for a in ("arrayprobe_version", "arrayprobe_enhancements_version"):
                self.assertTrue(getattr(d, a))
        with netCDF4.Dataset(str(self.export("v314_demo"))) as d:
            # Since 2026-09-15 a v3.1.4 stamp names its engine too, and the
            # tracked v3.1.4 fixtures were regenerated with it.
            self.assertEqual(d.enhancements_engine, "3.1.4")
        # A stamp written before R4s carries no engine= key; that is never guessed.
        from arrayprobe_enhancements.cf_export import _stamp_engine
        self.assertIsNone(_stamp_engine("iat_file=<none> profile=stock-v3.1.4 reject=() "
                                        "shadow_diode=none"))


class Refusals(_ExportCase):
    def _copy(self, key: str) -> Path:
        p = self.dir / FIXTURES[key].name
        shutil.copy(FIXTURES[key], p)
        return p

    def test_a_non_monotonic_decoded_time_is_refused_not_sorted(self):
        """The preserved sizeDist.m:98-99 defect adds 240000 to the first
        post-midnight second only; the second one then decodes earlier."""
        p = self._copy("octave_s4")
        with netCDF4.Dataset(str(p), "a") as d:
            n = d.dimensions["Time"].size
            d.variables["time"][:] = [235958.0, 235959.0, 240000.0] + [1.0 + i for i in range(n - 3)]
        with self.assertRaisesRegex(cf_export.CfExportError, "not strictly increasing"):
            cf_export.export(p, self.dir / "o.nc", flight_date=DATE)
        self.assertFalse((self.dir / "o.nc").exists())

    def test_a_unit_string_sizedist_never_writes_is_refused(self):
        p = self._copy("octave_s4")
        with netCDF4.Dataset(str(p), "a") as d:
            d.variables["vt"].units = "m/s"
        with self.assertRaisesRegex(cf_export.CfExportError, "vt: units 'm/s'"):
            cf_export.export(p, self.dir / "o.nc", flight_date=DATE)

    def test_an_unmapped_variable_is_refused_by_name(self):
        p = self._copy("octave_s4")
        with netCDF4.Dataset(str(p), "a") as d:
            d.createVariable("mystery", "f8", ("Time",)).units = "1"
        with self.assertRaisesRegex(cf_export.CfExportError, "mystery"):
            cf_export.export(p, self.dir / "o.nc", flight_date=DATE)

    def test_writing_over_the_source_is_refused(self):
        p = self._copy("v314_demo")
        with self.assertRaises(cf_export.CfExportError):
            cf_export.export(p, p, flight_date=DATE)


class Mutation(_ExportCase):
    def test_a_wrong_scale_in_the_table_is_caught_by_the_unit_check(self):
        """Break one row's scale; the independent unit-string check must fail."""
        broken = dict(cf_export.VARIABLE_MAP)
        broken["n"] = cf_export.CfMapping(frozenset({"cm-3"}), "cm-3", "m-3", 1e5, "mutant")
        with mock.patch.object(cf_export, "VARIABLE_MAP", broken):
            out = self.export("octave_s4")
        with netCDF4.Dataset(str(out)) as d:
            v = d.variables["n"]
            f_cf, _ = parse_units(v.units)
            f_true, _ = parse_units("cm-3")
            self.assertNotAlmostEqual(v.arrayprobe_cf_scale, f_true / f_cf)

    def test_a_mislabelled_true_unit_is_caught_by_dimension(self):
        broken = dict(cf_export.VARIABLE_MAP)
        broken["vt"] = cf_export.CfMapping(frozenset({"g/cm4"}), "g cm-4", "m-3 s-1",
                                           1e8, "mutant: trusts the string")
        with mock.patch.object(cf_export, "VARIABLE_MAP", broken):
            self.assertNotEqual(parse_units(broken["vt"].true_units)[1],
                                parse_units(broken["vt"].cf_units)[1])


class ArmExportDelegates(_ExportCase):
    def test_arm_units_are_cf_exports_true_units_and_values_are_untouched(self):
        for key in FIXTURES:
            out = self.dir / f"{key}.arm.nc"
            arm_export.export(FIXTURES[key], out, flight_date=DATE, site_id="p3f",
                              platform_id="oap2ds", facility_id="F1")
            with self.subTest(fixture=key), netCDF4.Dataset(str(out)) as d, \
                    netCDF4.Dataset(str(FIXTURES[key])) as s:
                for name, svar in s.variables.items():
                    if name == "time":
                        continue
                    dvar = d.variables[name]
                    self.assertEqual(dvar.units, cf_export.mapping_for(name).true_units)
                    parse_units(dvar.units)
                    np.testing.assert_array_equal(np.asarray(dvar[:]), np.asarray(svar[:]))
                self.assertNotIn("units", d.variables["time_hhmmss"].ncattrs())
                self.assertEqual(d.variables["bin_mid"].bounds, "bin_bounds")
                self.assertIn("CF-1.9", d.Conventions)


class NotAppliedByDefault(unittest.TestCase):
    def test_the_driver_now_has_an_adapter_wired(self):
        """Registered (so ``[enhancements] cf_export`` is a known key), and now the
        driver has an adapter too (:func:`pipeline._apply_cf_export`) -- it no longer needs
        ``python -m arrayprobe_enhancements.cf_export`` run by hand. A run whose raw stem does
        not parse to a flight date still records a named skip (``DriverAdapter`` in this file),
        because the CF time axis is never guessed. This test used to pin
        the opposite (no adapter at all)."""
        from arrayprobe_enhancements import pipeline, registry
        self.assertIn("cf_export", registry.REGISTRY)
        self.assertIn("cf_export", pipeline._APPLIERS)
        self.assertNotIn("cf_export", pipeline._NO_ADAPTER_REASON_BY_NAME)

    def test_the_cli_requires_a_flight_date(self):
        with self.assertRaises(SystemExit):
            cf_export.main([str(FIXTURES["v314_demo"]), "x.nc"])


try:
    import xarray  # type: ignore
except ImportError:  # pragma: no cover
    xarray = None


@unittest.skipUnless(xarray is not None, "xarray is not installed in this venv "
                     "(measured 2026-09-15); the cftime decode above is the check it runs on")
class OpensWithXarray(_ExportCase):
    def test_xarray_decodes_time_and_indexes_bins(self):
        out = self.export("octave_s4")
        with xarray.open_dataset(out) as ds:
            self.assertEqual(ds["time"].dtype.kind, "M")
            self.assertIn("bin", ds.indexes)


class DriverAdapter(unittest.TestCase):
    """cf_export reachable through arrayprobe_enhancements.pipeline, the same way
    arm_export is wired -- exercises pipeline._apply_cf_export against a hand-built _RunOutputs,
    mirroring test_arm_export.py's DriverAdapter.

    THE RULE UNDER TEST: never invent a flight date. Missing outputs.flight_date -> a named
    ApplierSkip, never a guessed CF time axis.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out_dir = Path(self.tmp.name)
        self.src = self.out_dir / "sd.base170707102822.H.nc"
        shutil.copy(FIXTURES["v314_demo"], self.src)

    def _outputs(self, **overrides):
        from arrayprobe_enhancements.pipeline import _RunOutputs
        base = dict(out_dir=self.out_dir, raw_stem="base170707102822", engine="3.1.4",
                   image=None, proc=None, sd=self.src, combined=None)
        base.update(overrides)
        return _RunOutputs(**base)

    def test_it_is_registered_as_a_wired_adapter(self):
        from arrayprobe_enhancements.pipeline import _APPLIERS
        self.assertIn("cf_export", _APPLIERS)

    def test_no_longer_listed_as_having_no_adapter(self):
        """The whole point: this module must stop reporting itself unreachable."""
        from arrayprobe_enhancements.pipeline import _NO_ADAPTER_REASON_BY_NAME
        self.assertNotIn("cf_export", _NO_ADAPTER_REASON_BY_NAME)

    def test_refuses_without_a_flight_date(self):
        from arrayprobe_enhancements.pipeline import ApplierSkip, _apply_cf_export
        outputs = self._outputs(flight_date=None)
        with self.assertRaises(ApplierSkip) as cm:
            _apply_cf_export(outputs)
        self.assertIn("flight date", str(cm.exception))

    def test_a_config_supplied_flight_date_reaches_export(self):
        """The values the driver already has actually cross into the adapter call."""
        from arrayprobe_enhancements.pipeline import _apply_cf_export
        outputs = self._outputs(flight_date="20170707")
        with mock.patch("arrayprobe_enhancements.cf_export.export") as m:
            m.return_value = None
            # export() normally writes dst; the mock does not, so read the call args only.
            _apply_cf_export(outputs)
        self.assertEqual(m.call_count, 1)
        _args, kwargs = m.call_args
        self.assertEqual(kwargs["flight_date"], dt.date(2017, 7, 7))
        self.assertEqual(kwargs["engine"], "3.1.4")

    def test_a_content_refusal_is_a_recorded_skip_not_a_failed_pass(self):
        """ARM 2017-07-08 (2026-09-24): a repeated second made export() refuse, and the raw
        CfExportError aborted every correction after it. The adapter turns it into ApplierSkip,
        which apply_to_outputs records in `skipped`, and leaves no half-written file."""
        from arrayprobe_enhancements.cf_export import CfExportError
        from arrayprobe_enhancements.pipeline import ApplierSkip, _apply_cf_export
        outputs = self._outputs(flight_date="20170707")
        dst = self.out_dir / "base170707102822.enh.cf.nc"

        def refuse(_src, out, **_kw):
            Path(out).write_bytes(b"partial")
            raise CfExportError("decoded time is not strictly increasing at index 0")

        with mock.patch("arrayprobe_enhancements.cf_export.export", side_effect=refuse):
            with self.assertRaises(ApplierSkip) as cm:
                _apply_cf_export(outputs)
        self.assertIn("not strictly increasing", str(cm.exception))
        self.assertFalse(dst.exists())

    def test_without_a_preset_derived_date_nothing_changes(self):
        """No flight_date resolved (e.g. an unrecognised stem) -> export() is never called."""
        from arrayprobe_enhancements.pipeline import ApplierSkip, _apply_cf_export
        outputs = self._outputs(flight_date=None)
        with mock.patch("arrayprobe_enhancements.cf_export.export") as m:
            with self.assertRaises(ApplierSkip):
                _apply_cf_export(outputs)
        m.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class TasQualityFlag(_ExportCase):
    """Step 7 (TAS gap in file metadata): the source's ``.tasqc.json`` becomes a per-second flag the data variables
    point at; without one, the file says the record is absent."""

    def _copy_with_record(self, key):
        import shutil

        from arrayprobe.tools import tas_sources as ts
        src = self.dir / Path(FIXTURES[key]).name
        shutil.copyfile(FIXTURES[key], src)
        with netCDF4.Dataset(str(src)) as ds:
            t = np.asarray(ds.variables["time"][:], dtype=float).ravel()
        rec = ts.qc_record(None, ts.TasPolicy(), t, [int(t[1])], None)
        rec["tas_substituted_ranges"] = f"{int(t[0]):06d}"
        rec["tas_floor_round_residual_ranges"] = f"{int(t[-1]):06d}"
        ts.write_qc_sidecar(src, rec)
        return src, t

    def test_the_flag_marks_substituted_and_defaulted_seconds(self):
        key = next(iter(FIXTURES))
        src, t = self._copy_with_record(key)
        out = self.dir / "qc.cf.nc"
        cf_export.export(src, out, flight_date=DATE)
        with netCDF4.Dataset(str(out)) as ds:
            flag = np.asarray(ds.variables["tas_quality_flag"][:])
            expected = np.zeros(t.size, dtype=np.int8)
            expected[0], expected[1], expected[-1] = 1, 2, 2
            np.testing.assert_array_equal(flag, expected)
            data = [n for n, v in ds.variables.items() if "time" in v.dimensions
                    and n not in ("time", "time_hhmmss", "tas_quality_flag")]
            self.assertTrue(data)
            for n in data:
                self.assertEqual(ds.variables[n].ancillary_variables, "tas_quality_flag", n)
            self.assertEqual(ds.getncattr("arrayprobe_tas_missing_count"), 1)

    def test_no_record_says_absent_and_writes_no_flag(self):
        out = self.export(next(iter(FIXTURES)))
        with netCDF4.Dataset(str(out)) as ds:
            self.assertNotIn("tas_quality_flag", ds.variables)
            self.assertTrue(ds.getncattr("arrayprobe_tas_qc").startswith("absent"))
