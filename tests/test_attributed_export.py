# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe.attributed_export`` -- the attributed second output.

**What these tests are defending.** The faithful combined writer carries zero attributes because
the MATLAB it reproduces carries zero attributes (``combine_sizedist.m:202-231``), and fifteen
validated flights rest on a byte comparison against files that have none. The attributed export
exists so a recipient can re-derive a number without the ``.call`` sidecar travelling alongside --
and it must buy that **without moving a single faithful byte**. So the first test hashes the source
either side of an export, and the second asserts every value survives exactly.

Two checks here deliberately draw their two sides from different places ("A check
must draw its two sides from different places, or it is testing nothing"):

* :class:`UnitsAgreeWithTheSdWriter` compares the units this module writes against
  ``arrayprobe.sizedist._VARS`` -- the port's transcription of ``sizeDist.m``'s own ``putAtt``
  lines -- rather than against a second copy of the same table.
* :class:`ARealStampRoundTrips` builds its stamp with ``scripts/run_flight.py``'s own
  ``sd_call_label``, so a change to the stamp's shape fails here instead of silently producing an
  attributed file that states the wrong thing.

The fixture is built by calling :func:`arrayprobe.combine._write` itself, not by hand-writing a
netCDF file with the same ten names. That is deliberate: it means the variable table in
:data:`~arrayprobe.attributed_export.COMBINED_SIZEDIST` is checked against the real writer, and a
rename in the writer fails these tests rather than producing an export that silently refuses every
real product.
"""

from __future__ import annotations

import importlib.util
import io
import math
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np
from netCDF4 import Dataset

from arrayprobe import attributed_export as ae
from arrayprobe import combine
from arrayprobe.matlab_compat import datenum
from arrayprobe_uiops.sizedist_core import _VARS, _VARS_ASPECT, _VARS_INTARR, _VARS_TAIL

#: Every variable the ``sd`` writer can define, across its four switched blocks
#: (``sizedist.py:1768-1840``) -- ``mean_area_ratio`` lives in ``_VARS_TAIL``, not ``_VARS``, so
#: reading only the first block would have made this cross-check silently incomplete.
SIZEDIST_VARS = _VARS + _VARS_ASPECT + _VARS_TAIL + _VARS_INTARR

_SPEC = importlib.util.spec_from_file_location(
    "run_flight", Path(__file__).resolve().parent.parent / "scripts" / "run_flight.py")
# Use whichever module object is REGISTERED -- same reason as
# test_run_flight_provenance.py's identical comment: an unconditional overwrite
# clobbers another test module's registration when both run in one process.
assert _SPEC is not None and _SPEC.loader is not None
if _SPEC.name in sys.modules:
    run_flight = sys.modules[_SPEC.name]
else:
    run_flight = importlib.util.module_from_spec(_SPEC)
    sys.modules[_SPEC.name] = run_flight
    _SPEC.loader.exec_module(run_flight)


#: A stamp of the shape ``run_flight.sd_call_label`` writes today -- an **sd** stamp. It is not a
#: stamp any exportable file carries: :func:`ae.identify_shape` supports exactly one shape,
#: ``combined_sizedist``, so the only file this module can export is the one carrying the S4c
#: combine stamp below. It is kept for two jobs: it is the fragment that combine stamp *nests*,
#: and it is the only shipped stamp shape whose ``reject`` and thresholds sit at the top level,
#: which is what the explosion tests need.
SD_STAMP = (
    "engine=3.1.4 iat_file=2DS_intArrThreshold_MISSING.cdf profile=ORACLES_PRODUCTION "
    "reject=(rej_hollow=0,max_edge_img_ar=4,max_comp_img_ar=4,area_ratio_z=0.5) "
    "shadow_diode=none tree=production area_ratio_z=0.5 (default) "
    "default_int_arr_thresh=6e-06 (default)"
)

#: A stamp of the shape ``run_flight._combine_stamp`` writes today -- the sd stamp above nested
#: whole inside ``inputs_built_with=(...)`` -- spelled out so these tests state what they mean
#: rather than inheriting whatever the driver's current defaults happen to be.
#: :class:`ARealStampRoundTrips` checks the real thing, built by the driver, separately.
#:
#: **This is the fixture defect of 2026-09-20.** Until then ``_faithful`` wrote :data:`SD_STAMP`
#: beside a combined-shaped product -- a pairing ``run_flight.py`` never writes, since the sd stamp
#: only ever sits beside an sd file and an sd file is not exportable. So every test here parsed a
#: flat stamp, the string ``inputs_built_with`` appeared in no test in the repository, and the
#: nested-stamp misparse that made ``--attributed`` a total outage on every real product passed a
#: green suite. Both sides of the check came from the same place: the flat stamp.
STAMP = (
    "engine=3.1.4 combine=oracles-fork:combine_sizedist.m "
    "inputs=sd.base160906064017.2DS.nc "
    f"inputs_built_with=({SD_STAMP})"
)

N_TIME, N_BIN, N_FILES = 4, 3, 5


def _faithful(dirpath: Path, *, stamp: str | None = STAMP) -> Path:
    """A small combined product written by the REAL writer, plus its ``.call`` sidecar.

    Row 2 is all-NaN, which is the faithful writer's own padding convention
    (``combine_sizedist.m:124-148``) and the case a value comparison most easily gets wrong.
    """
    out = dirpath / "base160906064017.combined.H.2DS_2.cdf"
    bin_min = np.array([0.05, 0.10, 0.15])
    bin_max = np.array([0.10, 0.15, 0.20])
    bin_mid = np.array([0.075, 0.125, 0.175])
    bin_dd = np.array([0.05, 0.05, 0.05])
    timevec = datenum(2016, 9, 6) + np.arange(N_TIME) / 86400.0
    mar = np.arange(N_TIME * N_BIN, dtype=float).reshape(N_TIME, N_BIN) / 10.0
    count = np.arange(N_TIME * N_BIN, dtype=float).reshape(N_TIME, N_BIN)
    nd = count / 1000.0
    nt = np.array([1.0, 2.0, np.nan, 4.0])
    rr = np.array([0.1, 0.2, np.nan, 0.4])
    mar[2, :] = np.nan
    count[2, :] = np.nan
    nd[2, :] = np.nan
    combine._write(out, N_FILES, bin_min, bin_max, bin_mid, bin_dd,
                   timevec, mar, count, nd, nt, rr)
    if stamp is not None:
        Path(str(out) + ae.CALL_SUFFIX).write_text(stamp)
    return out


class _Fixture(unittest.TestCase):
    """One faithful product and its export, in a temporary directory."""

    def setUp(self):
        # A Windows runner can still hold a written file when tearDown removes the folder
        # (WinError 32, CI run 41338745088); the files are scratch, so cleanup may leave one.
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.dir = Path(self._tmp.name)
        self.source = _faithful(self.dir)
        self.out = ae.export(self.source, export_time="2026-09-17T00:00:00+00:00")

    def tearDown(self):
        self._tmp.cleanup()

    def atts(self) -> dict:
        ds = Dataset(str(self.out), "r")
        try:
            return {k: ds.getncattr(k) for k in ds.ncattrs()}
        finally:
            ds.close()


class TheFaithfulFileDoesNotMove(_Fixture):
    """The one property that cannot be traded: the reproduction is unaffected."""

    def test_the_source_bytes_are_identical_after_an_export(self):
        before = ae.sha256_of(self.source)
        ae.export(self.source, self.dir / "second.nc", export_time="2026-09-17T00:00:00+00:00")
        self.assertEqual(before, ae.sha256_of(self.source))

    def test_the_source_is_still_netcdf3_classic(self):
        # The faithful file's format is part of the output contract (MATLAB's bare 'clobber');
        # the export being NETCDF4 must not have leaked back into it.
        ds = Dataset(str(self.source), "r")
        try:
            self.assertEqual(ds.data_model, "NETCDF3_CLASSIC")
        finally:
            ds.close()

    def test_the_export_refuses_to_write_over_the_faithful_file(self):
        with self.assertRaises(ae.AttributedExportError):
            ae.export(self.source, self.source)

    def test_the_export_is_netcdf4(self):
        ds = Dataset(str(self.out), "r")
        try:
            self.assertEqual(ds.data_model, "NETCDF4")
        finally:
            ds.close()


class ValuesSurviveExactly(_Fixture):
    """Not "close": equal, NaN included, dtype and on-disk dimension order included."""

    def test_every_value_dtype_and_dimension_list_is_identical(self):
        src = Dataset(str(self.source), "r")
        dst = Dataset(str(self.out), "r")
        try:
            src.set_auto_maskandscale(False)
            dst.set_auto_maskandscale(False)
            self.assertEqual(set(src.variables), set(dst.variables))
            for name, var in src.variables.items():
                got = dst.variables[name]
                with self.subTest(variable=name):
                    self.assertEqual(var.dtype, got.dtype)
                    # Verbatim, not re-ordered: the export hand-rolls no transpose, so the
                    # on-disk dimension list must come through unchanged.
                    self.assertEqual(var.dimensions, got.dimensions)
                    self.assertTrue(np.array_equal(np.asarray(var[...]), np.asarray(got[...]),
                                                   equal_nan=True))
        finally:
            src.close()
            dst.close()

    def test_a_nan_padded_row_is_still_nan_and_not_a_fill_value(self):
        dst = Dataset(str(self.out), "r")
        try:
            dst.set_auto_maskandscale(False)
            nt = np.asarray(dst.variables["Number Concentration cm-3"][...])
            self.assertTrue(math.isnan(float(nt[2])))
            self.assertNotIn("_FillValue", dst.variables["Number Concentration cm-3"].ncattrs())
        finally:
            dst.close()

    def test_the_files_stitched_dimension_is_carried_and_surfaced(self):
        dst = Dataset(str(self.out), "r")
        try:
            self.assertEqual(len(dst.dimensions["files_stitched"]), N_FILES)
        finally:
            dst.close()
        self.assertEqual(self.atts()["arrayprobe_files_stitched"], N_FILES)


class EveryVariableIsLabelled(_Fixture):
    """The gap this module exists to close: the faithful file states no unit for anything."""

    def test_the_faithful_file_really_does_carry_no_attributes(self):
        # Measured here rather than asserted from the docstring -- if the faithful writer ever
        # gains an attribute, the reproduction has changed and this module's premise with it.
        ds = Dataset(str(self.source), "r")
        try:
            self.assertEqual(ds.ncattrs(), [])
            for name, var in ds.variables.items():
                with self.subTest(variable=name):
                    self.assertEqual(var.ncattrs(), [])
        finally:
            ds.close()

    def test_every_variable_gains_units_long_name_and_a_stated_basis(self):
        ds = Dataset(str(self.out), "r")
        try:
            for name, var in ds.variables.items():
                with self.subTest(variable=name):
                    for att in ("units", "long_name", "arrayprobe_units_basis"):
                        self.assertIn(att, var.ncattrs())
                        self.assertTrue(str(var.getncattr(att)).strip())
                    basis = var.getncattr("arrayprobe_units_basis")
                    # How it was established is part of the claim, not decoration.
                    self.assertTrue(basis.startswith(("read", "derived")), basis)
        finally:
            ds.close()

    def test_bin_midpoints_now_states_the_unit_the_faithful_file_omits(self):
        ds = Dataset(str(self.out), "r")
        try:
            self.assertEqual(ds.variables["Bin Midpoints"].units, "mm")
        finally:
            ds.close()


#: combined-product variable -> the ``sd`` variable it is built from
#: (``arrayprobe.combine._READ_VARS`` / ``:162-180``), and whether this module's
#: ``source_units`` should equal the ``sd`` writer's string exactly. The two ``False`` rows are the
#: ones the combine step transforms: ``Time Vector`` (HHMMSS -> datenum) and
#: ``Size Distribution cm-3`` (cm-4 -> cm-3 by the bin-width multiplication).
_SD_ORIGIN = {
    "Bin Minimum": ("bin_min", True),
    "Bin Maximum": ("bin_max", True),
    "Bin Midpoints": ("bin_mid", True),
    "Bin Width": ("bin_dD", True),
    "Mean Area Ratio": ("mean_area_ratio", True),
    "Counts": ("count", True),
    "Number Concentration cm-3": ("n", True),
    "Reject Ratio": ("Reject_ratio", True),
    "Time Vector": ("time", False),
    "Size Distribution cm-3": ("conc_minR", False),
}


class UnitsAgreeWithTheSdWriter(unittest.TestCase):
    """The two sides come from different places: this module's table, and the port's own
    transcription of ``sizeDist.m``'s ``putAtt`` lines (``arrayprobe.sizedist._VARS``)."""

    def setUp(self):
        self.sd_units = {name: dict(atts).get("units") for name, _dims, atts in SIZEDIST_VARS}

    def test_every_combined_variable_is_mapped_to_an_sd_variable(self):
        self.assertEqual(set(_SD_ORIGIN), set(ae.COMBINED_SIZEDIST))

    def test_source_units_equal_the_sd_writers_own_string(self):
        for name, (sd_name, exact) in _SD_ORIGIN.items():
            with self.subTest(variable=name):
                sd_unit = self.sd_units[sd_name]
                self.assertIsNotNone(sd_unit, f"sizedist._VARS has no units for {sd_name}")
                source_units = ae.COMBINED_SIZEDIST[name].source_units
                self.assertIsNotNone(source_units)
                if exact:
                    self.assertEqual(source_units, sd_unit)
                else:
                    # Transformed by the combine step: the sd string must still be quoted, and the
                    # basis must say how the value stopped being in it.
                    self.assertIn(sd_unit, source_units)
                    self.assertTrue(
                        ae.COMBINED_SIZEDIST[name].basis.startswith("derived"),
                        ae.COMBINED_SIZEDIST[name].basis)

    def test_the_variable_table_matches_what_the_faithful_writer_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = _faithful(Path(tmp))
            ds = Dataset(str(source), "r")
            try:
                self.assertEqual(set(ds.variables), set(ae.COMBINED_SIZEDIST))
            finally:
                ds.close()


class TheDatenumEpochIsMeasuredNotAsserted(unittest.TestCase):
    """Two sides again: the constant written into every exported file, and
    :func:`arrayprobe.matlab_compat.datenum` itself."""

    def test_the_written_epoch_is_matlab_compats_own(self):
        self.assertEqual(ae.DATENUM_UNIX_EPOCH_DAYS, float(datenum(1970, 1, 1)))

    def test_the_conversion_recovers_the_flight_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = _faithful(Path(tmp))
            out = ae.export(source, export_time="2026-09-17T00:00:00+00:00")
            ds = Dataset(str(out), "r")
            try:
                ds.set_auto_maskandscale(False)
                t0 = float(np.asarray(ds.variables["Time Vector"][...])[0])
                epoch = ds.getncattr("arrayprobe_datenum_unix_epoch_days")
            finally:
                ds.close()
        import datetime as dt
        recovered = dt.datetime.fromtimestamp((t0 - epoch) * 86400.0, dt.UTC)
        self.assertEqual(recovered.date(), dt.date(2016, 9, 6))


class TheWholeStampSurvives(_Fixture):
    """The recipient must be able to re-derive the number from this file alone."""

    def test_the_raw_stamp_is_written_verbatim(self):
        self.assertEqual(self.atts()["arrayprobe_call_stamp"], STAMP)

    def test_every_key_in_the_stamp_becomes_an_attribute(self):
        atts = self.atts()
        for key in ae.parse_stamp(STAMP):
            with self.subTest(key=key):
                self.assertIn(f"arrayprobe_{key}", atts)

    def test_the_outer_keys_describe_the_product_in_hand(self):
        atts = self.atts()
        self.assertEqual(atts["arrayprobe_engine"], "3.1.4")
        self.assertEqual(atts["arrayprobe_combine"], "oracles-fork:combine_sizedist.m")
        self.assertEqual(atts["arrayprobe_inputs"], "sd.base160906064017.2DS.nc")

    def test_the_inputs_provenance_stays_nested_and_is_not_promoted(self):
        """The decision of 2026-09-20: the outer level wins, the nested fragment stays nested.

        ``engine`` and ``profile`` exist at both levels and mean different things -- the product's
        own configuration, and the configuration of the files it was stitched from -- so promoting
        the inner keys would either overwrite the outer ones or trip the duplicate guard. The
        fragment is written verbatim, under its own name, and :func:`ae.parse_nested` is how a
        reader gets at it deliberately.
        """
        atts = self.atts()
        self.assertEqual(atts["arrayprobe_inputs_built_with"], f"({SD_STAMP})",
                         "the whole nested stamp, parens included, verbatim")
        for inner in ("iat_file", "profile", "tree", "shadow_diode", "reject",
                      "area_ratio_z", "default_int_arr_thresh"):
            with self.subTest(key=inner):
                self.assertNotIn(f"arrayprobe_{inner}", atts,
                                 f"{inner!r} is the INPUTS' value, not this product's; promoting "
                                 f"it puts the wrong fact under the product's own name")
        inputs = ae.parse_nested(atts["arrayprobe_inputs_built_with"])
        self.assertEqual(inputs["iat_file"], "2DS_intArrThreshold_MISSING.cdf")
        self.assertEqual(inputs["profile"], "ORACLES_PRODUCTION")
        self.assertEqual(inputs["tree"], "production")
        self.assertEqual(ae.parse_reject(inputs["reject"])["rej_hollow"], "0")
        self.assertEqual(ae.parse_tagged_value(inputs["default_int_arr_thresh"]),
                         (6e-06, "default"))

    def test_every_reject_field_is_exploded_into_its_own_attribute(self):
        """The explosion, driven from a stamp that carries ``reject`` at the top level.

        No shipped stamp does today -- the sd stamp is not exportable and the combine stamp keeps
        its reject nested -- so this is a unit test of :func:`ae.global_attributes`' branch, said
        plainly rather than dressed up as a driver-written case. The driver-written case is
        :meth:`test_the_inputs_provenance_stays_nested_and_is_not_promoted` above, which reaches
        the same fields through ``inputs_built_with``.
        """
        flat = self.dir / "flat"
        flat.mkdir()
        source = _faithful(flat, stamp=SD_STAMP)
        out = ae.export(source, export_time="2026-09-17T00:00:00+00:00")
        ds = Dataset(str(out), "r")
        try:
            atts = {k: ds.getncattr(k) for k in ds.ncattrs()}
        finally:
            ds.close()
        self.assertEqual(atts["arrayprobe_reject_rej_hollow"], "0")
        self.assertEqual(atts["arrayprobe_reject_max_edge_img_ar"], "4")
        self.assertEqual(atts["arrayprobe_reject_max_comp_img_ar"], "4")
        # ...and the raw fragment is kept too, so nothing depends on the explosion being complete.
        self.assertIn("rej_hollow=0", atts["arrayprobe_reject"])

    def test_the_provenance_and_the_enhancement_policy_are_stated(self):
        atts = self.atts()
        self.assertEqual(atts["arrayprobe_source_file"], self.source.name)
        self.assertEqual(atts["arrayprobe_source_sha256"], ae.sha256_of(self.source))
        self.assertEqual(atts["arrayprobe_source_bytes"], self.source.stat().st_size)
        self.assertEqual(atts["arrayprobe_enhancements_applied"], "none")
        self.assertEqual(atts["arrayprobe_export_convention"], ae.EXPORT_CONVENTION)
        self.assertIn("combine_sizedist.m:202-231", atts["arrayprobe_source_writer"])
        # The file must not be mistaken for the byte-comparison artefact.
        self.assertIn("NOT the byte-comparison artefact", atts["arrayprobe_fidelity_note"])

    def test_a_named_enhancement_is_recorded_when_the_producer_names_one(self):
        out = ae.export(self.source, self.dir / "enh.nc", enhancements=("wide_hollow_fix",),
                        export_time="2026-09-17T00:00:00+00:00")
        ds = Dataset(str(out), "r")
        try:
            self.assertEqual(ds.getncattr("arrayprobe_enhancements_applied"), "wide_hollow_fix")
        finally:
            ds.close()


class ThresholdTagsSurvive(unittest.TestCase):
    """The three epistemic objects -- ``stock``, ``regime:<name>``, ``user:<path>`` -- must
    reach the exported file as the tag they are, never blurred into a bare number."""

    def _export_with(self, area_tag: str, iat_tag: str) -> dict:
        stamp = (f"engine=3.1.4 iat_file=<none> profile=STOCK_V314 "
                 f"reject=(rej_hollow=1,max_edge_img_ar=6) shadow_diode=none tree=production "
                 f"area_ratio_z=0.2 ({area_tag}) default_int_arr_thresh=4e-06 ({iat_tag})")
        with tempfile.TemporaryDirectory() as tmp:
            source = _faithful(Path(tmp), stamp=stamp)
            out = ae.export(source, export_time="2026-09-17T00:00:00+00:00")
            ds = Dataset(str(out), "r")
            try:
                return {k: ds.getncattr(k) for k in ds.ncattrs()}
            finally:
                ds.close()

    def test_an_old_stock_stamp_is_still_read_and_the_tag_survives_verbatim(self):
        """Must-fire: stamps written before 2026-10-16 spell the built-in fallback
        ``(stock)``; they must still parse, and the attribute copies the tag as written."""
        self.assertEqual(ae.parse_tagged_value("0.5 (stock)"), (0.5, "stock"))
        atts = self._export_with("stock", "stock")
        self.assertEqual(atts["arrayprobe_area_ratio_z"], 0.2)
        self.assertEqual(atts["arrayprobe_area_ratio_z_source"], "stock")
        self.assertEqual(atts["arrayprobe_default_int_arr_thresh"], 4e-06)
        self.assertEqual(atts["arrayprobe_default_int_arr_thresh_source"], "stock")

    def test_a_default_tag_survives_as_default(self):
        atts = self._export_with("default", "default")
        self.assertEqual(atts["arrayprobe_area_ratio_z_source"], "default")
        self.assertEqual(atts["arrayprobe_default_int_arr_thresh_source"], "default")

    def test_a_regime_tag_survives_with_its_regime_name(self):
        atts = self._export_with("regime:liquid-warm", "regime:ice")
        self.assertEqual(atts["arrayprobe_area_ratio_z_source"], "regime:liquid-warm")
        self.assertEqual(atts["arrayprobe_default_int_arr_thresh_source"], "regime:ice")

    def test_a_user_override_survives_with_the_path_it_came_from(self):
        atts = self._export_with("user:C:/runs/ena.toml", "user:cli")
        self.assertEqual(atts["arrayprobe_area_ratio_z_source"], "user:C:/runs/ena.toml")
        self.assertEqual(atts["arrayprobe_default_int_arr_thresh_source"], "user:cli")

    def test_the_two_fields_are_tagged_independently(self):
        # A run may mix origins; reporting both as whichever was set last is exactly the blurring
        # the regime machinery exists to prevent (regimes.ResolvedThresholds' own docstring).
        atts = self._export_with("regime:liquid-warm", "user:cli")
        self.assertNotEqual(atts["arrayprobe_area_ratio_z_source"],
                            atts["arrayprobe_default_int_arr_thresh_source"])

    def test_every_shipped_regime_name_round_trips(self):
        from arrayprobe.regimes import REGIMES, resolve_thresholds
        for name in REGIMES:
            with self.subTest(regime=name):
                resolved = resolve_thresholds(regime_name=name)
                rendered = resolved.area_ratio_z.render()
                value, source = ae.parse_tagged_value(rendered)
                self.assertEqual(source, f"regime:{name}")
                self.assertEqual(value, resolved.area_ratio_z.value)


def _driver_combine_stamp(dirpath: Path) -> str:
    """The S4c combine stamp, built by ``run_flight`` itself over an sd file it stamped itself.

    Both halves come from the driver (``sd_call_label`` and ``_combine_stamp``), so a change to
    either shape fails here rather than producing an attributed file that states the wrong thing.
    """
    sd = dirpath / "sd.base160906064017.2DS.nc"
    sd.write_bytes(b"")                     # only its .call sidecar is read by _combine_stamp
    run_flight.write_stamp(sd, run_flight.sd_call_label("2DS_intArrThreshold_MISSING.cdf"))
    return run_flight._combine_stamp([sd])


class ARealStampRoundTrips(unittest.TestCase):
    """The stamp is built by ``scripts/run_flight.py`` itself, for the shape this module exports.

    **The pairing matters, and getting it wrong is why the suite was green through a total
    outage.** ``identify_shape`` supports exactly one shape, ``combined_sizedist``, so the only
    file ``export`` can ever be given is one carrying the *combine* stamp. Until 2026-09-20 this
    class built its "real stamp" from ``sd_call_label`` -- the S4 stamp -- and attached it to a
    combined-shaped fixture, a pairing ``run_flight.py`` never writes.
    """

    def test_the_drivers_combine_stamp_parses_and_every_key_reaches_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            stamp = _driver_combine_stamp(Path(tmp))
            keys = ae.parse_stamp(stamp)
            # What the combine stamp says about the product in hand.
            for required in ("engine", "combine", "inputs", "inputs_built_with"):
                self.assertIn(required, keys, f"{required!r} missing from {stamp!r}")
            # ...and what it says about the files it was stitched from, one level down.
            inputs = ae.parse_nested(keys["inputs_built_with"])
            for required in ("engine", "profile", "reject", "iat_file",
                             "tree", "area_ratio_z", "default_int_arr_thresh"):
                self.assertIn(required, inputs, f"{required!r} missing from {keys!r}")
            self.assertEqual(ae.parse_tagged_value(inputs["default_int_arr_thresh"])[1], "default")
            source = _faithful(Path(tmp), stamp=stamp)
            out = ae.export(source, export_time="2026-09-17T00:00:00+00:00")
            ds = Dataset(str(out), "r")
            try:
                atts = {k: ds.getncattr(k) for k in ds.ncattrs()}
            finally:
                ds.close()
        self.assertEqual(atts["arrayprobe_call_stamp"], stamp)
        for key in keys:
            self.assertIn(f"arrayprobe_{key}", atts)

    def test_the_spelled_out_STAMP_is_the_shape_the_driver_writes(self):
        """The guard on the fixture itself, with its two sides from different places.

        Every fixture in this file carries :data:`STAMP`, spelled out so the tests say what they
        mean. That is only safe while it is the key set ``run_flight`` writes **for the shape this
        module exports**; when it was not, the suite went green through a total outage. The
        comparison is against the driver's own generator, never a second copy of the string.
        """
        with tempfile.TemporaryDirectory() as tmp:
            driver = ae.parse_stamp(_driver_combine_stamp(Path(tmp)))
        self.assertEqual(sorted(ae.parse_stamp(STAMP)), sorted(driver))
        self.assertEqual(sorted(ae.parse_nested(ae.parse_stamp(STAMP)["inputs_built_with"])),
                         sorted(ae.parse_nested(driver["inputs_built_with"])))

    def test_sd_call_label_parses_on_its_own(self):
        """The nested fragment's own shape, checked where it actually lives: beside an sd file."""
        keys = ae.parse_stamp(run_flight.sd_call_label("2DS_intArrThreshold_MISSING.cdf"))
        for required in ("engine", "profile", "reject", "iat_file",
                         "tree", "area_ratio_z", "default_int_arr_thresh"):
            self.assertIn(required, keys)

    def test_the_drivers_own_threshold_fragment_splits_into_value_and_tag(self):
        fragment = run_flight.thresholds_stamp()
        keys = ae.parse_stamp(fragment)
        for field in ae.TAGGED_KEYS:
            value, source = ae.parse_tagged_value(keys[field])
            self.assertIsInstance(value, float)
            self.assertTrue(source in ("default", "stock")
                            or source.startswith(("regime:", "user:")), source)


class TheParserHandlesTheShapesTheStampActuallyTakes(unittest.TestCase):

    def test_a_value_containing_spaces_is_one_value(self):
        keys = ae.parse_stamp("tree=production area_ratio_z=0.5 (default) shadow_diode=none")
        self.assertEqual(keys["area_ratio_z"], "0.5 (default)")
        self.assertEqual(keys["shadow_diode"], "none")

    def test_nested_equals_inside_the_reject_fragment_are_not_keys(self):
        keys = ae.parse_stamp("profile=X reject=(a=1,b=2) shadow_diode=none")
        self.assertEqual(sorted(keys), ["profile", "reject", "shadow_diode"])
        self.assertEqual(ae.parse_reject(keys["reject"]), {"a": "1", "b": "2"})

    def test_a_duplicated_key_is_refused_rather_than_resolved(self):
        with self.assertRaises(ae.StampParseError):
            ae.parse_stamp("engine=3.1.4 profile=X engine=3.5")


class TheNestedCombineStampIsOneValue(unittest.TestCase):
    """``inputs_built_with=(<a whole stamp>)`` -- the shape that made ``--attributed`` a total
    outage on every product the driver writes (2026-09-20).

    The inner keys are preceded by spaces, so the flat scanner promoted them to the top level,
    truncated ``inputs_built_with`` at the first one, and left the closing paren on the last value,
    where ``parse_tagged_value`` raised ``StampParseError`` and ``run_flight.write_attributed``
    swallowed it. Nothing in the repository tested the string ``inputs_built_with``.
    """

    NESTED = ("engine=3.1.4 combine=oracles-fork:combine_sizedist.m inputs=sd.a.nc "
              "inputs_built_with=(engine=3.1.4 profile=oracles-production "
              "reject=(rej_hollow=False,max_edge_img_ar=4) tree=production "
              "area_ratio_z=0.5 (default) default_int_arr_thresh=6e-06 (default))")

    def test_the_nested_stamp_is_one_value_and_keeps_both_parens(self):
        keys = ae.parse_stamp(self.NESTED)
        self.assertEqual(sorted(keys), ["combine", "engine", "inputs", "inputs_built_with"])
        self.assertTrue(keys["inputs_built_with"].startswith("(engine=3.1.4 "))
        self.assertTrue(keys["inputs_built_with"].endswith("(default))"))

    def test_the_outer_engine_wins_and_the_inner_one_is_not_a_top_level_key(self):
        keys = ae.parse_stamp(self.NESTED)
        self.assertEqual(keys["engine"], "3.1.4")
        self.assertNotIn("profile", keys, "the inner profile is the INPUTS' profile")
        self.assertEqual(ae.parse_nested(keys["inputs_built_with"])["profile"],
                         "oracles-production")

    def test_the_last_inner_threshold_no_longer_carries_the_closing_paren(self):
        """The exact exception the outage raised: ``'6e-06 (default))'``."""
        inner = ae.parse_nested(ae.parse_stamp(self.NESTED)["inputs_built_with"])
        self.assertEqual(inner["default_int_arr_thresh"], "6e-06 (default)")
        self.assertEqual(ae.parse_tagged_value(inner["default_int_arr_thresh"]), (6e-06, "default"))

    def test_a_genuinely_duplicated_TOP_LEVEL_key_is_still_refused(self):
        """The guard that must survive the fix: paren-awareness must not become last-wins."""
        with self.assertRaises(ae.StampParseError):
            ae.parse_stamp("engine=3.1.4 inputs_built_with=(engine=3.5) engine=3.5")

    def test_an_unbalanced_paren_is_refused_rather_than_guessed_at(self):
        for bad in ("engine=3.1.4 inputs_built_with=(profile=X",
                    "engine=3.1.4 profile=X) tree=production"):
            with self.subTest(stamp=bad), self.assertRaises(ae.StampParseError):
                ae.parse_stamp(bad)

    def test_an_unparenthesised_nested_fragment_is_refused(self):
        with self.assertRaises(ae.StampParseError):
            ae.parse_nested("engine=3.1.4 profile=X")

    def test_an_empty_or_shapeless_stamp_is_refused(self):
        for bad in ("", "   ", "no pairs here"):
            with self.subTest(stamp=bad), self.assertRaises(ae.StampParseError):
                ae.parse_stamp(bad)

    def test_a_threshold_without_its_tag_is_refused(self):
        with self.assertRaises(ae.StampParseError):
            ae.parse_tagged_value("0.5")

    def test_an_unparenthesised_reject_fragment_is_refused(self):
        with self.assertRaises(ae.StampParseError):
            ae.parse_reject("rej_hollow=0")


class Refusals(unittest.TestCase):
    """What the export declines to guess."""

    def test_a_product_with_no_sourced_unit_table_is_refused_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            other = Path(tmp) / "not_a_combined_product.nc"
            ds = Dataset(str(other), "w", format="NETCDF4")
            ds.createDimension("time", 2)
            ds.createVariable("something_else", "f8", ("time",))[:] = [1.0, 2.0]
            ds.close()
            Path(str(other) + ae.CALL_SUFFIX).write_text(STAMP)
            with self.assertRaises(ae.UnknownProductError) as caught:
                ae.export(other, Path(tmp) / "out.nc")
        self.assertIn("guessed units", str(caught.exception))

    def test_an_unstamped_product_is_refused_unless_explicitly_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = _faithful(Path(tmp), stamp=None)
            with self.assertRaises(ae.MissingStampError):
                ae.export(source)
            out = ae.export(source, accept_unstamped=True,
                            export_time="2026-09-17T00:00:00+00:00")
            ds = Dataset(str(out), "r")
            try:
                note = ds.getncattr("arrayprobe_call_stamp")
            finally:
                ds.close()
        # Silence about provenance is itself stated, never left blank.
        self.assertTrue(note.startswith("ABSENT"), note)


class AnOlderStampIsReadTheWayTheDriverReadsIt(unittest.TestCase):
    """``run_flight._stamps_equivalent`` reads a missing ``engine=`` as ``engine=3.1.4``
    (stamps written before 2026-09-15 have no such key). The export reads it the same way, and
    says that it inferred rather than read it."""

    def test_a_pre_2026_09_15_stamp_is_read_as_engine_3_1_4_and_says_so(self):
        stamp = ("iat_file=<none> profile=ORACLES_2016 reject=(rej_hollow=1) shadow_diode=none")
        with tempfile.TemporaryDirectory() as tmp:
            source = _faithful(Path(tmp), stamp=stamp)
            out = ae.export(source, export_time="2026-09-17T00:00:00+00:00")
            ds = Dataset(str(out), "r")
            try:
                atts = {k: ds.getncattr(k) for k in ds.ncattrs()}
            finally:
                ds.close()
        self.assertEqual(atts["arrayprobe_engine"], "3.1.4")
        self.assertIn("inferred", atts["arrayprobe_engine_basis"])
        self.assertEqual(atts["arrayprobe_call_stamp"], stamp)

    def test_a_stamp_written_with_the_old_stock_tag_is_current_not_stale(self):
        """Must-fire: the tag was renamed stock -> default; a run stamped under the old
        spelling is the same configuration, so the resume check must not call it stale."""
        from arrayprobe.driver import run_flight
        old = "tree=production area_ratio_z=0.5 (stock) default_int_arr_thresh=6e-06 (stock)"
        new = "tree=production area_ratio_z=0.5 (default) default_int_arr_thresh=6e-06 (default)"
        self.assertTrue(run_flight._stamps_equivalent(old, new))
        self.assertFalse(run_flight._stamps_equivalent(
            old, new.replace("area_ratio_z=0.5", "area_ratio_z=0.2")))


class TheCommandLineForm(unittest.TestCase):

    def test_main_writes_the_default_sibling_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = _faithful(Path(tmp))
            self.assertEqual(ae.main([str(source)]), 0)
            self.assertTrue(ae.default_output_path(source).exists())

    def test_the_default_output_sits_beside_the_source_with_the_same_stem(self):
        got = ae.default_output_path(Path("/d/base160906064017.combined.H.2DS_2.cdf"))
        self.assertEqual(got.parent, Path("/d"))
        self.assertTrue(got.name.startswith("base160906064017.combined.H.2DS_2.cdf"))
        self.assertTrue(got.name.endswith(".nc"))


class TheExportIsReproducible(unittest.TestCase):
    """A pinned ``export_time`` makes two exports of the same input state the same thing --
    the same reason ``creation_time=`` exists on the faithful writers."""

    def test_two_exports_with_a_pinned_time_carry_identical_global_attributes(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = _faithful(Path(tmp))
            pairs = []
            for name in ("a.nc", "b.nc"):
                out = ae.export(source, Path(tmp) / name,
                                export_time="2026-09-17T00:00:00+00:00")
                ds = Dataset(str(out), "r")
                try:
                    pairs.append({k: ds.getncattr(k) for k in ds.ncattrs()})
                finally:
                    ds.close()
        self.assertEqual(pairs[0], pairs[1])


if __name__ == "__main__":
    unittest.main()


class TheTasQcRecordIsCarried(unittest.TestCase):
    """Step 6: the source's ``.tasqc.json`` reaches the attributed file, or its absence is
    stated -- a reader can tell "no default-TAS seconds" from "not recorded"."""

    def setUp(self):
        # A Windows runner can still hold a written file when tearDown removes the folder
        # (WinError 32, CI run 41338745088); the files are scratch, so cleanup may leave one.
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.dir = Path(self._tmp.name)
        self.source = _faithful(self.dir)

    def tearDown(self):
        self._tmp.cleanup()

    def _atts(self, out):
        ds = Dataset(str(out), "r")
        try:
            return {k: ds.getncattr(k) for k in ds.ncattrs()}
        finally:
            ds.close()

    def test_the_record_is_folded_in_key_for_key(self):
        from arrayprobe.tools import tas_sources
        rec = tas_sources.qc_record(None, tas_sources.TasPolicy(), [120000.0, 120001.0],
                                    [120001], None)
        tas_sources.write_qc_sidecar(self.source, rec)
        atts = self._atts(ae.export(self.source, export_time="2026-09-23T00:00:00+00:00"))
        for key, value in rec.items():
            self.assertEqual(atts[ae.ATTR_PREFIX + key], value, key)
        self.assertNotIn(ae.ATTR_PREFIX + "tas_qc", atts)

    def test_no_record_says_absent(self):
        atts = self._atts(ae.export(self.source, export_time="2026-09-23T00:00:00+00:00"))
        self.assertTrue(atts[ae.ATTR_PREFIX + "tas_qc"].startswith("absent"))
        self.assertFalse(any(k.startswith(ae.ATTR_PREFIX + "tas_seconds") for k in atts))


class AV35AreaRatioStampExports(unittest.TestCase):
    """An engine 3.5 run with ``--area-ratio-z`` stamps the bare value (``sd_call_label``, v3.5
    ``sizeDist.m:1162``), not the tagged ``<value> (<source>)`` form. It sits inside the combine
    stamp's ``inputs_built_with``, which the export carries verbatim and never promotes, so the
    tagged parser never sees it and the export succeeds with the value stated."""

    def test_the_override_reaches_the_file_inside_the_inputs_provenance(self):
        saved = (run_flight.ENGINE, run_flight.AREA_RATIO_Z_OVERRIDE)
        run_flight.ENGINE, run_flight.AREA_RATIO_Z_OVERRIDE = "3.5", 0.5
        try:
            with tempfile.TemporaryDirectory() as tmp:
                sd = Path(tmp) / "sd.base180215125340.2DS.nc"
                sd.write_bytes(b"")
                run_flight.write_stamp(sd, run_flight.sd_call_label(None))
                stamp = run_flight._combine_stamp([sd])
                out = ae.export(_faithful(Path(tmp), stamp=stamp),
                                export_time="2026-09-30T00:00:00+00:00")
                ds = Dataset(str(out), "r")
                try:
                    atts = {k: ds.getncattr(k) for k in ds.ncattrs()}
                finally:
                    ds.close()
        finally:
            run_flight.ENGINE, run_flight.AREA_RATIO_Z_OVERRIDE = saved
        self.assertEqual(atts[ae.ATTR_PREFIX + "engine"], "3.5")
        self.assertIn(" area_ratio_z=0.5", atts[ae.ATTR_PREFIX + "inputs_built_with"])
        self.assertNotIn(ae.ATTR_PREFIX + "area_ratio_z", atts)


class TheRunRecordIsWrittenUnderAcddNames(_Fixture):
    """The ``.call`` content reaches the six ACDD discovery attributes; faithful file untouched."""

    def test_every_acdd_key_is_written_from_the_stamp(self):
        atts = self.atts()
        for key in ae.ACDD_KEYS:
            self.assertIn(key, atts, key)
        self.assertEqual(atts["Conventions"], ae.ACDD_CONVENTIONS)
        self.assertNotIn("CF-", atts["Conventions"])
        self.assertEqual(atts["date_created"], "2026-09-17T00:00:00+00:00")
        self.assertEqual(atts["product_version"], atts["arrayprobe_package_version"])
        self.assertIn("engine=3.1.4", atts["source"])
        self.assertIn(STAMP, atts["history"])
        self.assertIn(ae.sha256_of(self.source), atts["history"])
        self.assertIn("combined_sizedist", atts["processing_level"])

    def test_the_faithful_file_hash_is_unchanged_by_the_acdd_export(self):
        before = ae.sha256_of(self.source)
        out = ae.export(self.source, self.dir / "acdd.nc", export_time="2026-10-05T00:00:00+00:00")
        self.assertEqual(before, ae.sha256_of(self.source))
        ds = Dataset(str(out), "r")
        try:
            self.assertEqual(ds.getncattr("date_created"), "2026-10-05T00:00:00+00:00")
        finally:
            ds.close()

    def test_an_attribute_the_faithful_file_holds_is_never_overwritten(self):
        held = {"history": "written by the engine", "Conventions": "engine-own"}
        got = ae.acdd_attributes(
            {"arrayprobe_package_version": "0.0", "arrayprobe_engine": "3.5"}, stamp=STAMP,
            source_path=self.source, source_sha256="0" * 64,
            shape=ae.COMBINED_SHAPE,
            created="2026-10-05T00:00:00+00:00", existing=held)
        self.assertEqual(got["history"], "written by the engine")
        self.assertEqual(got["Conventions"], "engine-own")
        self.assertEqual(got["product_version"], "0.0")

    def test_no_sidecar_is_refused_or_marked_as_having_no_run_record(self):
        bare = self.dir / "bare"
        bare.mkdir()
        source = _faithful(bare, stamp=None)
        with self.assertRaises(ae.MissingStampError):
            ae.export(source)
        out = ae.export(source, accept_unstamped=True, export_time="2026-10-05T00:00:00+00:00")
        ds = Dataset(str(out), "r")
        try:
            self.assertIn("ABSENT", ds.getncattr("history"))
            self.assertIn("not established", ds.getncattr("source"))
        finally:
            ds.close()


class TheAttributedFileIsAnalysisReady(unittest.TestCase):
    """The attributed output is also the cloud-optimised one -- chunked and losslessly
    compressed by default, contiguous on request -- and the encoding never changes a value."""

    def setUp(self):
        # A Windows runner can still hold a written file when tearDown removes the folder
        # (WinError 32, CI run 41338745088); the files are scratch, so cleanup may leave one.
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _long_source(self, n_time=5000):
        """A combined product with more seconds than one chunk, so the chunk rule is exercised."""
        out = self.dir / "base160906064017.combined.H.2DS_2.cdf"
        edges = np.array([0.05, 0.10, 0.15, 0.20])
        timevec = datenum(2016, 9, 6) + np.arange(n_time) / 86400.0
        count = np.arange(n_time * 3, dtype=float).reshape(n_time, 3)
        count[7, :] = np.nan
        combine._write(out, 2, edges[:-1], edges[1:], (edges[:-1] + edges[1:]) / 2,
                       np.diff(edges), timevec, count / 10.0, count, count / 1000.0,
                       np.arange(n_time, dtype=float), np.full(n_time, 0.25))
        Path(str(out) + ae.CALL_SUFFIX).write_text(STAMP)
        return out

    @staticmethod
    def _values(path):
        ds = Dataset(str(path), "r")
        ds.set_auto_maskandscale(False)
        try:
            return {n: (v.dtype, v.dimensions, np.asarray(v[...])) for n, v in ds.variables.items()}
        finally:
            ds.close()

    def test_both_encodings_hold_the_faithful_values_exactly(self):
        source = self._long_source()
        before = ae.sha256_of(source)
        ready = ae.export(source, self.dir / "ready.nc", export_time="2026-10-08T00:00:00+00:00")
        plain = ae.export(source, self.dir / "plain.nc", export_time="2026-10-08T00:00:00+00:00",
                          analysis_ready=False)
        self.assertEqual(before, ae.sha256_of(source))
        want = self._values(source)
        for out in (ready, plain):
            got = self._values(out)
            self.assertEqual(set(got), set(want))
            for name, (dtype, dims, values) in want.items():
                self.assertEqual(got[name][0], dtype, name)
                self.assertEqual(got[name][1], dims, name)
                self.assertTrue(np.array_equal(got[name][2], values, equal_nan=True), name)

    def test_the_default_file_is_chunked_compressed_and_says_so(self):
        source = self._long_source()
        out = ae.export(source, export_time="2026-10-08T00:00:00+00:00")
        ds = Dataset(str(out), "r")
        try:
            self.assertEqual(ds.getncattr("arrayprobe_encoding"), ae.ENCODING_ANALYSIS_READY)
            for name, var in ds.variables.items():
                sizes = [len(ds.dimensions[d]) for d in var.dimensions]
                filt = var.filters()
                self.assertTrue(filt["zlib"], name)
                self.assertEqual(filt["complevel"], ae.ANALYSIS_READY_COMPLEVEL, name)
                self.assertEqual(filt["shuffle"], var.dtype.kind in "biu", name)
                want = [n if n <= ae.ANALYSIS_READY_WHOLE_DIM else min(n, ae.ANALYSIS_READY_CHUNK)
                        for n in sizes]
                self.assertEqual(list(var.chunking()), want, name)
            self.assertTrue(any(ae.ANALYSIS_READY_CHUNK in var.chunking()
                                for var in ds.variables.values()),
                            "no variable long enough to exercise the one-hour chunk")
        finally:
            ds.close()

    def test_plain_is_contiguous_and_uncompressed(self):
        out = ae.export(self._long_source(), export_time="2026-10-08T00:00:00+00:00",
                        analysis_ready=False)
        ds = Dataset(str(out), "r")
        try:
            self.assertEqual(ds.getncattr("arrayprobe_encoding"), ae.ENCODING_PLAIN)
            for name, var in ds.variables.items():
                self.assertFalse(var.filters()["zlib"], name)
                self.assertEqual(var.chunking(), "contiguous", name)
        finally:
            ds.close()

    def test_storage_options_leaves_what_it_cannot_compress_alone(self):
        self.assertEqual(ae.storage_options(np.float64, []), {})
        self.assertEqual(ae.storage_options(np.float64, [0, 3]), {})
        self.assertEqual(ae.storage_options(np.dtype("S4"), [10]), {})
        self.assertEqual(ae.storage_options(np.float64, [10], analysis_ready=False), {})
        self.assertEqual(ae.storage_options(np.int16, [70, 28797])["chunksizes"], [70, 3600])

    def test_the_command_line_opt_out(self):
        source = self._long_source()
        self.assertEqual(ae.main([str(source), str(self.dir / "p.nc"), "--plain"]), 0)
        ds = Dataset(str(self.dir / "p.nc"), "r")
        try:
            self.assertEqual(ds.getncattr("arrayprobe_encoding"), ae.ENCODING_PLAIN)
        finally:
            ds.close()


class TheOptInZarrStoreHoldsTheSameFile(unittest.TestCase):
    """NetCDF4 is the default output; :func:`ae.export_zarr` is the opt-in Zarr copy of the
    attributed file, with every value, dtype, dimension order and attribute unchanged except the
    encoding statement."""

    def setUp(self):
        try:
            import xarray  # noqa: F401
            import zarr  # noqa: F401
        except ImportError:
            self.skipTest("zarr/xarray not installed (the [zarr] extra)")
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _export(self):
        source = _faithful(self.dir)
        return ae.export(source, self.dir / "a.nc", export_time="2026-10-08T00:00:00+00:00")

    def test_round_trip_keeps_every_value_dtype_dimension_and_attribute(self):
        import xarray as xr
        nc = self._export()
        store = ae.export_zarr(nc)
        self.assertEqual(store, self.dir / "a.zarr")
        self.assertTrue(store.is_dir())
        ds = Dataset(str(nc), "r")
        ds.set_auto_maskandscale(False)
        try:
            want = {n: (v.dtype, v.dimensions, np.asarray(v[...]),
                        {k: v.getncattr(k) for k in v.ncattrs()})
                    for n, v in ds.variables.items()}
            want_globals = {k: ds.getncattr(k) for k in ds.ncattrs()}
        finally:
            ds.close()
        self.assertTrue(any(np.isnan(w[2]).any() for w in want.values()
                            if w[0].kind == "f"), "fixture carries no NaN to protect")
        with xr.open_zarr(store, decode_cf=False, mask_and_scale=False, decode_times=False,
                          consolidated=False) as got:
            self.assertEqual(set(got.variables), set(want))
            for name, (dtype, dims, values, attrs) in want.items():
                with self.subTest(variable=name):
                    var = got.variables[name]
                    self.assertEqual(var.dtype, dtype)
                    self.assertEqual(var.dims, dims)
                    self.assertTrue(np.array_equal(var.values, values, equal_nan=True))
                    self.assertNotIn("_FillValue", var.attrs)
                    self.assertEqual(set(var.attrs), set(attrs))
                    for key, value in attrs.items():
                        np.testing.assert_array_equal(var.attrs[key], value)
            key = f"{ae.ATTR_PREFIX}encoding"
            self.assertEqual(got.attrs[key], ae.ENCODING_ZARR)
            self.assertEqual(set(got.attrs), set(want_globals))
            for k, value in want_globals.items():
                if k != key:
                    with self.subTest(attribute=k):
                        np.testing.assert_array_equal(got.attrs[k], value)

    def test_refuses_to_write_over_an_existing_store(self):
        nc = self._export()
        store = self.dir / "taken.zarr"
        store.mkdir()
        with self.assertRaises(ae.AttributedExportError):
            ae.export_zarr(nc, store)
        self.assertEqual(list(store.iterdir()), [])

    def test_the_command_line_flag_writes_both(self):
        source = _faithful(self.dir)
        out = self.dir / "cli.nc"
        self.assertEqual(ae.main([str(source), str(out), "--zarr"]), 0)
        self.assertTrue(out.is_file())
        self.assertTrue((self.dir / "cli.zarr").is_dir())


class TestStampSharedAttributesCarriesEnhancements(unittest.TestCase):
    """``stamp_shared_attributes`` takes the run's enhancements, so the enhanced ARM copy's block
    is built whole (``run_flight.stamp_enhanced_arm``) instead of patched after the stamp."""

    def test_enhancement_keys_equal_shared_attributes(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "x.enh.arm.nc"
            with Dataset(str(target), "w", format="NETCDF3_CLASSIC"):
                pass
            names, record = ("diode_correction", "stray_pixels"), "chain record text"
            block = ae.stamp_shared_attributes(target, Path(tmp) / "x.enh.sd.nc",
                                               enhancements=names, enhancements_record=record)
            want = ae.shared_attributes(engine=None, enhancements=names,
                                        enhancements_record=record)
            enh_keys = [k for k in want if k.startswith(f"{ae.ATTR_PREFIX}enhancements")]
            self.assertTrue(enh_keys)
            with Dataset(str(target)) as ds:
                for key in enh_keys:
                    self.assertEqual(block[key], want[key])
                    self.assertEqual(str(ds.getncattr(key)), str(want[key]))
_HAVE_PYARROW = importlib.util.find_spec("pyarrow") is not None


class TheOptInParquetMirrorHoldsTheSameFile(unittest.TestCase):
    """:func:`ae.export_parquet` is the opt-in Parquet copy of an attributed file, behind the
    ``[parquet]`` extra; pyarrow is never a hard dependency."""

    def setUp(self):
        # A Windows runner can still hold a written file when tearDown removes the folder
        # (WinError 32, CI run 41338745088); the files are scratch, so cleanup may leave one.
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.dir = Path(self._tmp.name)
        self.nc = self.dir / "x.attributed.nc"
        with Dataset(str(self.nc), "w", format="NETCDF4") as ds:
            ds.setncattr("title", "fixture")
            ds.createDimension("time", 3)
            ds.createDimension("bin", 2)
            t = ds.createVariable("conc", "f8", ("time", "bin"))
            t[:] = np.array([[1.0, np.nan], [2.5, 3.0], [0.0, -1.0]])
            t.setncattr("units", "m-4")
            c = ds.createVariable("count", "i4", ("bin",))
            c[:] = np.array([7, 9], dtype=np.int32)
            s = ds.createVariable("flag", "i2")
            s.assignValue(4)

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_pyarrow_names_the_extra(self):
        import builtins
        from unittest import mock
        real = builtins.__import__

        def no_pyarrow(name, *args, **kwargs):
            if name == "pyarrow" or name.startswith("pyarrow."):
                raise ImportError("No module named 'pyarrow'")
            return real(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=no_pyarrow):
            with self.assertRaises(ae.AttributedExportError) as ctx:
                ae.export_parquet(self.nc)
        self.assertIn(f"arrayprobe[{ae.PARQUET_EXTRA}]", str(ctx.exception))
        self.assertIn("arrayprobe[parquet]", str(ctx.exception))
        self.assertFalse(ae.default_parquet_path(self.nc).exists())

    def test_default_path_replaces_the_nc_suffix(self):
        self.assertEqual(ae.default_parquet_path(self.dir / "a.nc"), self.dir / "a.parquet")
        self.assertEqual(ae.default_parquet_path(self.dir / "a.cdf"),
                         self.dir / "a.cdf.parquet")

    @unittest.skipUnless(_HAVE_PYARROW, "pyarrow not installed (the [parquet] extra)")
    def test_round_trip_keeps_every_value_dtype_and_attribute(self):
        import json

        import pyarrow.parquet as pq
        out = ae.export_parquet(self.nc)
        tbl = pq.read_table(out / "time__bin.parquet")
        meta = {k.decode(): v.decode() for k, v in tbl.schema.metadata.items()}
        self.assertEqual(meta["arrayprobe_encoding"], ae.ENCODING_PARQUET)
        self.assertEqual(json.loads(meta["arrayprobe_global_attrs"])["title"], "fixture")
        self.assertEqual(json.loads(meta["arrayprobe_var_attrs"])["conc"]["units"], "m-4")
        conc = np.full((3, 2), -999.0)
        conc[tbl["time"].to_numpy(), tbl["bin"].to_numpy()] = tbl["conc"].to_numpy()
        with Dataset(str(self.nc)) as ds:
            ds.set_auto_maskandscale(False)
            want = ds["conc"][...]
            self.assertTrue(np.array_equal(conc, want, equal_nan=True))
            self.assertEqual(tbl["conc"].to_numpy().dtype, want.dtype)
            cnt = pq.read_table(out / "bin.parquet")["count"].to_numpy()
            self.assertEqual(cnt.dtype, np.int32)
            self.assertTrue(np.array_equal(cnt, ds["count"][...]))
            flag = pq.read_table(out / "scalars.parquet")["flag"].to_numpy()
            self.assertEqual(flag.tolist(), [4])

    @unittest.skipUnless(_HAVE_PYARROW, "pyarrow not installed (the [parquet] extra)")
    def test_a_coordinate_variable_replaces_its_index_column(self):
        import pyarrow.parquet as pq
        with Dataset(str(self.nc), "a") as ds:
            tv = ds.createVariable("time", "f8", ("time",))
            tv[:] = np.array([10.0, 11.0, 12.0])
        out = ae.export_parquet(self.nc)
        tbl = pq.read_table(out / "time.parquet")
        self.assertEqual(tbl.column_names, ["time"])
        self.assertEqual(tbl["time"].to_numpy().tolist(), [10.0, 11.0, 12.0])

    def test_the_cli_offers_parquet(self):
        buf = io.StringIO()
        with redirect_stdout(buf), self.assertRaises(SystemExit):
            ae.main(["--help"])
        self.assertIn("--parquet", buf.getvalue())
        self.assertIn("[parquet]", buf.getvalue())

    @unittest.skipUnless(_HAVE_PYARROW, "pyarrow not installed (the [parquet] extra)")
    def test_refuses_to_write_over_an_existing_path(self):
        ae.default_parquet_path(self.nc).mkdir()
        with self.assertRaises(ae.AttributedExportError):
            ae.export_parquet(self.nc)
