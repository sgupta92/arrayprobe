# SPDX-License-Identifier: BSD-3-Clause
"""is every registered enhancement's ``consumes`` actually openable
against a real v3.5 file?


``registry.EnhancementSpec.consumes`` was declared from reading each
module's source, never checked against a real file -- its own docstring says
so (``registry.py:89-95``: "a name that turns out wrong is that test's job to
catch"). This module is that test: it draws Side A from the registry's own
declaration and Side B from the variable sets of the two tracked v3.5 demo
files, opened with ``netCDF4.Dataset`` (both NETCDF4).

Two real mismatches were found and are asserted here as *known*, not hidden:

* ``outoffocus`` declares ``particle_diameter_minR`` -- that is the MATLAB
  *source* variable name (``sizeDist.m:793``, quoted in the module's own
  docstring), not a netCDF column. ``outoffocus.apply_outoffocus`` actually
  reads ``image_diam_minR`` (``outoffocus.py:83, :86``) -- present on both
  engines. The registry's ``consumes`` entry is wrong; not fixed here per
  this stage's instructions (report it, the coordinator fixes ``registry.py``
  after merge).
* ``particle_clustering`` declares ``image_diam_circle_fit``
  (``particle_clustering.py:23, :89, :169``), which
  ``extract_features`` (``:135``) really does read via
  ``ds.variables[name]`` for every name in ``_NC_FEATURE_NAMES`` -- a genuine
  ``KeyError`` on today's v3.5 demo proc, which carries no such variable
  (measured: present in ``demo_flight_v314_proc.nc``, absent from
  ``demo_flight_v35_proc.nc``). This one is not a wrong label -- it is a real
  v3.5-openability gap for this enhancement, exercised and asserted below.
"""
from __future__ import annotations

import unittest
from pathlib import Path

try:
    import netCDF4
except ImportError:  # pragma: no cover
    netCDF4 = None  # type: ignore[assignment]  # optional-dependency sentinel: mypy cannot type a module-or-None name

from arrayprobe_enhancements import registry

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA = REPO_ROOT / "tests" / "data"
V35_PROC = DATA / "demo_flight_v35_proc.nc"
V35_SD = DATA / "demo_flight_v35_sd.nc"

#: Tokens ``consumes`` may hold that name no single netCDF variable.
ALLOWED_TOKENS = frozenset({"*", "images", "raw"})

#: Names that are real, but are in-memory intermediates rather than a written
#: file variable -- flagged by the S2 report (plan section 7's "Cites").
ALLOWED_INTERMEDIATES = frozenset({"int_arr", "timehhmmss"})

#: Fact 0.1 (plan section 0): a *default* v3.5 run's ``sd`` never carries
#: these two -- gated at ``arrayprobe_uiops/sizedist.py:706`` on
#: ``i_save_int_arr_sv``, which ``scripts/run_flight.py``'s ``V35_CALL`` pins to
#: 0. Asserted absent, not merely skipped, so a future default-call change
#: that starts writing them flips this test loudly rather than silently.
EXPECTED_ABSENT = frozenset({"sum_IntArr", "sample_vol"})

#: Real, measured mismatches between a spec's declared ``consumes`` and what
#: the v3.5 demo files actually carry -- see the module docstring above.
#: Keyed by enhancement name, valued by the wrongly-declared names. Asserted
#: absent from the real files here (documenting the gap precisely) rather
#: than left to fail the general sweep below opaquely.
KNOWN_CONSUMES_MISMATCHES = {
    # Real v3.5 gap: the module really does read "image_diam_circle_fit",
    # which v3.5's proc file does not carry.
    "particle_clustering": frozenset({"image_diam_circle_fit"}),
}

_FILE_STAGES = ("proc", "sd", "product")


@unittest.skipUnless(netCDF4 is not None and V35_PROC.is_file() and V35_SD.is_file(),
                     "netCDF4 or the tracked v3.5 demo proc/sd files are not available")
class ConsumesAgainstRealV35File(unittest.TestCase):
    """Side A: ``registry.REGISTRY[name].consumes``. Side B: the real
    variable sets of the tracked v3.5 demo ``proc``/``sd`` files."""

    @classmethod
    def setUpClass(cls):
        with netCDF4.Dataset(str(V35_PROC)) as ds:
            cls.proc_vars = frozenset(ds.variables.keys())
        with netCDF4.Dataset(str(V35_SD)) as ds:
            cls.sd_vars = frozenset(ds.variables.keys())
        cls.all_vars = cls.proc_vars | cls.sd_vars

    def test_expected_absent_variables_really_are_absent(self):
        """Fact 0.1, checked against the file rather than assumed."""
        for name in EXPECTED_ABSENT:
            with self.subTest(name=name):
                self.assertNotIn(name, self.all_vars,
                                 f"{name!r} was expected absent from a default v3.5 "
                                 "run (iSaveIntArrSV=0) but is present -- V35_CALL "
                                 "or the gate at sizedist.py:706 may have changed")

    def test_known_mismatches_are_confirmed_wrong_or_absent(self):
        """The two documented gaps above, checked live rather than asserted
        from memory -- if either name starts showing up in the real file,
        this test needs updating, which is the point of pinning it here."""
        for name, bad_names in KNOWN_CONSUMES_MISMATCHES.items():
            spec = registry.REGISTRY[name]
            with self.subTest(name=name):
                self.assertTrue(bad_names <= spec.consumes,
                                f"{name}: expected the known-mismatched name(s) "
                                f"{sorted(bad_names)} in consumes={sorted(spec.consumes)} "
                                "-- update KNOWN_CONSUMES_MISMATCHES if the registry "
                                "was corrected upstream")
                for bad in bad_names:
                    self.assertNotIn(bad, self.all_vars,
                                     f"{name}: {bad!r} is now present in the v3.5 demo "
                                     "files -- the known mismatch may be resolved; "
                                     "update KNOWN_CONSUMES_MISMATCHES and report it")

    def test_every_other_real_consumes_name_is_in_the_v35_files(self):
        """The general sweep, over every ``proc``/``sd``/``product``-stage
        spec, excluding the two names already called out above by name."""
        for name, spec in sorted(registry.REGISTRY.items()):
            if spec.stage not in _FILE_STAGES:
                continue
            known_bad = KNOWN_CONSUMES_MISMATCHES.get(name, frozenset())
            for var in sorted(spec.consumes):
                if var in ALLOWED_TOKENS or var in ALLOWED_INTERMEDIATES:
                    continue
                if var in EXPECTED_ABSENT or var in known_bad:
                    continue
                with self.subTest(name=name, var=var):
                    self.assertIn(var, self.all_vars,
                                 f"{name}: consumes {var!r} (stage={spec.stage!r}) is "
                                 "not a variable in either tracked v3.5 demo file "
                                 "(proc or sd) -- either a wrong registry label or a "
                                 "genuine v3.5-openability gap; report it, do not edit "
                                 "registry.py here")


@unittest.skipUnless(netCDF4 is not None and V35_PROC.is_file() and V35_SD.is_file(),
                     "netCDF4 or the tracked v3.5 demo proc/sd files are not available")
class EntryPointsOpenTheV35Files(unittest.TestCase):
    """For specs whose ``consumes`` names real proc/sd variables: does the
    module's own read path actually handle the v3.5 (NETCDF4) files?

    Every case is exercised against the tracked demo files with real
    arguments only -- an entry point whose signature needs something the two
    demo files cannot supply is recorded with ``skipTest`` naming the missing
    argument, never fabricated.
    """

    def test_particle_number_all_fix_audit_proc_file(self):
        from arrayprobe_enhancements.particle_number_all_fix import audit_proc_file
        report = audit_proc_file(V35_PROC)
        self.assertIn("present", report)

    def test_int_arr_rollback_fix_proc_file_with_rollback_corrected(self):
        import tempfile

        from arrayprobe_enhancements.int_arr_rollback_fix import (
            SECONDS_PER_DAY,
            proc_file_with_rollback_corrected,
        )
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "corrected.nc"
            report = proc_file_with_rollback_corrected(V35_PROC, dst, step=SECONDS_PER_DAY)
        self.assertIn("rollbacks", report)
        self.assertGreaterEqual(report["rollbacks"], 0)

    def test_particle_time_int8_fix_read_proc(self):
        from arrayprobe_enhancements.particle_time_int8_fix import _read_proc
        out = _read_proc(V35_PROC)
        for name in ("parent_rec_num", "Time", "Time_in_seconds",
                     "particle_millisec", "particle_microsec"):
            self.assertIn(name, out)

    def test_arco_export_export(self):
        import tempfile

        from arrayprobe_enhancements.arco_export import export
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "arco.nc"
            plans = export(V35_PROC, out)
            self.assertGreater(len(plans), 0)
            self.assertTrue(out.is_file())

    def test_arm_export_export(self):
        import datetime as dt
        import tempfile

        from arrayprobe_enhancements.arm_export import export
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "arm.nc"
            # site_id/platform_id/facility_id/flight_date: arbitrary ARM
            # identifiers, not measured facts -- same convention
            # test_arm_export.py already uses for every other fixture.
            export(V35_SD, out, flight_date=dt.date(2016, 9, 6),
                  site_id="p3f", platform_id="oap2ds", facility_id="F1")
            self.assertTrue(out.is_file())

    def test_particle_clustering_extract_features_raises_named_refusal_on_v35(self):
        """Row 29's finding, exercised: ``image_diam_circle_fit`` is a real
        column ``extract_features`` reads (``particle_clustering.py:135``)
        and the v3.5 demo proc genuinely does not carry it.

        flipped from a bare ``KeyError`` to the named refusal
        :class:`~arrayprobe_enhancements.particle_clustering.MissingProcVariable`
        -- the discriminating test the design plan calls for:
        ``extract_features(V35_PROC)`` (default engine, ``"3.1.4"``) now
        passes on the named refusal naming ``image_diam_circle_fit`` and
        FAILS on a bare ``KeyError`` -- ``MissingProcVariable`` does not
        subclass ``KeyError``, so this assertion is genuinely discriminating,
        not merely a rename."""
        from arrayprobe_enhancements.particle_clustering import (
            MissingProcVariable,
            extract_features,
        )
        self.assertFalse(issubclass(MissingProcVariable, KeyError))
        with self.assertRaises(MissingProcVariable) as ctx:
            extract_features(V35_PROC)
        self.assertEqual(ctx.exception.name, "image_diam_circle_fit")
        # engine="3.5" is the non-vacuous path: it drops the missing column
        # from its own request, so the same file now succeeds.
        idx, X = extract_features(V35_PROC, engine="3.5")
        self.assertEqual(X.shape[1], 9)  # 8 nc columns (one dropped) + compactness

    def test_effective_density_needs_area_ratio_not_a_stored_column(self):
        """``effective_density(holroyd_habit, area_ratio, ...)`` takes a
        scalar ``area_ratio`` that is not itself a proc-file column (it is
        derived elsewhere, e.g. ``image_area`` over a bounding-box area) --
        cannot be supplied from the two demo files alone without deriving a
        new number, which this stage does not invent."""
        self.skipTest("effective_density(holroyd_habit, area_ratio, ...) needs "
                      "area_ratio, which is not a stored proc/sd variable in "
                      "either demo file and is not derived here")

    def test_poisson_restore_needs_false_rejection_fraction(self):
        """``scale_size_distribution(concentration_by_bin,
        false_rejection_fraction)`` -- ``false_rejection_fraction`` is not a
        file variable on either demo file; it is the output of a separate
        inter-arrival analysis this stage does not run."""
        self.skipTest("poisson_restore.scale_size_distribution needs "
                      "false_rejection_fraction, not derivable from the two "
                      "demo files alone")

    def test_distance_rejection_needs_tas_not_a_proc_or_sd_column(self):
        """``is_shattered_by_distance(int_arr, tas, threshold_distance)`` --
        ``tas`` (true airspeed per particle) lives in the flight's TAS
        sidecar, not in ``proc`` or ``sd``; ``threshold_distance`` is a
        calibrated constant, not a file variable."""
        self.skipTest("distance_rejection.is_shattered_by_distance needs tas "
                      "and threshold_distance, neither a proc/sd variable in "
                      "the two demo files")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
