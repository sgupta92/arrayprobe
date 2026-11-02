# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe_uiops.spec`` against a real Octave run of v3.5.

The golden, ``tests/data/v35_spec_oracle.json``, is what the **vendored v3.5
``read_binary_SPEC.m`` itself wrote** when Octave 11.3.0 ran it unmodified on
the two tracked synthetic fixtures (``octave_oracle/run_v35_spec_bank.py``).
Both sides of every comparison below therefore come from different places: one
from the MATLAB program, one from the Python port.

**Oracle layer 2 only.** No archived product was ever produced by v3.5, so
nothing here is validated against a real campaign file the way the v3.1.4
port's own readers are. Stated so it is never mistaken for that.

Two cases carry the load:

``main_no_tas`` / ``main_with_tas``
    the same ten-record fixture with and without the aircraft TAS series --
    the only difference between the two runs -- so the ``tasRatio`` path is
    isolated from everything else.
``bound_v35`` / ``bound_v314``
    the same two-record fixture under **both** vendored releases, which is how
    the ``while iii+4<=2048`` change is measured rather than read off a diff.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np
from tests import _upstream  # noqa: E402
from tests._repo import needs_v314_engine, repo_only

from arrayprobe_uiops import spec as v35_spec
from arrayprobe_uiops.spec import (
    DIODE_VOLTAGE_SCALE,
    INITIAL_TAS,
    LATE_MARKER_FIRST_SKIPPED,
    SCAN_LIMIT,
    SHARED_WITH_V314,
    WRITER_GAPS,
    SidecarWriterV35,
    apply_time_offset,
    get_img_v35,
    read_binary_spec_v35,
)

DATA = Path(__file__).resolve().parent / "data"
GOLDEN_PATH = DATA / "v35_spec_oracle.json"
MAIN_FIXTURE = DATA / "v35_spec_raw_fixture"
BOUND_FIXTURE = DATA / "v35_spec_bound_raw_fixture"

ROOT = Path(__file__).resolve().parents[1]
V35_SPEC_M = _upstream.source("uiops35") / "read_binary_SPEC.m"

#: ``version.txt`` in the vendored v3.5 tree, which is what upstream's
#: cwd-relative ``fopen`` would have found had the process been started there.
SOFTWARE = "UIOOPS_v3.5"
#: ``datestr(now, ...)`` is excluded from every byte comparison in this project;
#: the port takes it as an argument so a run is reproducible.
CREATION_TIME = "2026/09/11 00:00:00"


def setUpModule():
    # Raised here rather than at import: an import-time SkipTest crashes
    # ``python -m unittest tests.<module>``, where ``discover`` reports it as a skip.
    _upstream.require("uiops35")


def _golden() -> dict:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def _run_port(tmp: Path, fixture: Path, name: str, *, with_tas: bool):
    """Run the port over one fixture and read back what it wrote.

    Returns ``(counts, netcdf-by-suffix, sidecars-by-suffix)`` in the same shape
    the golden stores, so the comparisons below are value-to-value.
    """
    from netCDF4 import Dataset

    golden = _golden()
    stem = tmp / name
    kwargs = {}
    if with_tas:
        va = golden["cases"]["main_with_tas"]["varargin"]
        kwargs = {"flt_time": va["fltTime"], "flt_tas": va["fltTAS"]}
    counts = read_binary_spec_v35(
        fixture, stem, software=SOFTWARE, creation_time=CREATION_TIME, **kwargs
    )
    nc: dict[str, dict] = {}
    for suffix in (".H.nc", ".V.nc"):
        path = Path(str(stem) + suffix)
        with Dataset(path, "r") as ds:
            ds.set_auto_maskandscale(False)
            entry = {
                "data_model": ds.data_model,
                "global_attributes": {n: str(ds.getncattr(n)) for n in ds.ncattrs()},
                "variables": {},
            }
            for vname, var in ds.variables.items():
                values = np.asarray(var[:])
                if vname == "data":
                    nz = np.argwhere(values != 0)
                    entry["variables"][vname] = {
                        "shape": list(values.shape),
                        "nonzero": [[int(i) for i in idx] + [int(values[tuple(idx)])]
                                    for idx in nz],
                    }
                else:
                    entry["variables"][vname] = {
                        "dtype": str(values.dtype),
                        "values": [float(v) for v in np.atleast_1d(values).ravel()],
                    }
            nc[suffix] = entry
    sidecars = {}
    for suffix in (".tas.csv", ".MK.csv", ".NV.csv"):
        path = Path(str(stem) + suffix)
        if path.exists():
            sidecars[suffix] = path.read_bytes().decode("ascii")
    return counts, nc, sidecars


class TestTheGoldenIsWhatItClaims(unittest.TestCase):
    """A fixture nobody checks is a fixture that can rot silently."""

    def test_the_tracked_fixtures_hash_to_what_the_bank_recorded(self):
        import hashlib

        golden = _golden()
        for name, path in ((MAIN_FIXTURE.name, MAIN_FIXTURE),
                           (BOUND_FIXTURE.name, BOUND_FIXTURE)):
            with self.subTest(fixture=name):
                self.assertEqual(
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                    golden["fixtures"][name],
                    "the raw fixture changed under the golden; re-run "
                    "scripts/validation/octave/run_v35_spec_bank.py",
                )

    def test_all_four_cases_are_present_and_none_is_empty(self):
        cases = _golden()["cases"]
        self.assertEqual(
            sorted(cases), ["bound_v314", "bound_v35", "main_no_tas", "main_with_tas"]
        )
        for name, case in cases.items():
            with self.subTest(case=name):
                nc = case["netcdf"]
                self.assertTrue(nc, f"{name} wrote no netCDF file at all")

    @repo_only
    def test_the_source_lines_this_stage_ports_are_still_in_the_vendored_file(self):
        """Anchors, not line numbers -- a re-vendor must fail here, not silently."""
        text = V35_SPEC_M.read_text(encoding="utf-8", errors="replace")
        for anchor in (
            "while iii+4<=2048",
            "if (tasTemp==170) || (nHOL+nVOL>0)",
            "'%f, %f, %f, %d, %d, %d, %d, %d, %d, %f, %f, %f, %f, %f, %f\\n'",
            "netcdf.create(outfilename1, 'NETCDF4')",
            "'Probe Channel_Orientation', 'Horizontal'",
            "if hour>=24",
            "daystart = 99999999;",
        ):
            with self.subTest(anchor=anchor):
                self.assertIn(anchor, text)

    @repo_only
    def test_the_v314_source_really_does_use_the_looser_bound(self):
        """The bound case is only a case if the two releases disagree."""
        _upstream.require("uiops314")
        V314_SPEC_M = _upstream.source("uiops314") / "read_binary_SPEC.m"
        self.assertIn("while iii<=2048", V314_SPEC_M.read_text(encoding="utf-8"))
        self.assertNotIn("while iii+4<=2048", V314_SPEC_M.read_text(encoding="utf-8"))


class TestReuseIsNotAccidental(unittest.TestCase):
    """Every borrowed helper is the v3.1.4 port's own object, not a copy."""

    @needs_v314_engine
    def test_the_shared_names_are_the_same_objects(self):
        from arrayprobe.readers import spec as v314_spec

        for name in SHARED_WITH_V314:
            with self.subTest(name=name):
                self.assertIs(getattr(v35_spec, name), getattr(v314_spec, name))

    @needs_v314_engine
    def test_the_private_helpers_this_module_leans_on_still_exist(self):
        """A rename in the v3.1.4 port must fail here, not at import time only."""
        from arrayprobe.readers import spec as v314_spec

        for name in ("_at", "_decode_runs_auto", "_decode_runs_scalar", "_ImageCanvas",
                     "_marker_positions", "_next_marker", "_pack_image",
                     "_write_header_slice", "SidecarWriter"):
            with self.subTest(name=name):
                self.assertTrue(hasattr(v314_spec, name))

    @needs_v314_engine
    def test_the_v35_sidecar_writer_extends_the_v314_one(self):
        from arrayprobe.readers import spec as v314_spec

        self.assertTrue(issubclass(SidecarWriterV35, v314_spec.SidecarWriter))


class TestAgainstTheOctaveGolden(unittest.TestCase):
    """The port's output against what v3.5's own program wrote."""

    def _compare(self, name: str, *, with_tas: bool):
        import tempfile

        golden = _golden()["cases"][name]
        with tempfile.TemporaryDirectory() as tmp:
            _, nc, sidecars = _run_port(
                Path(tmp), MAIN_FIXTURE, name, with_tas=with_tas
            )
        for suffix, want in golden["netcdf"].items():
            got = nc[suffix]
            with self.subTest(file=suffix):
                self.assertEqual(got["data_model"], want["data_model"])
                for vname, wvar in want["variables"].items():
                    with self.subTest(variable=vname):
                        if vname == "data":
                            self.assertEqual(got["variables"][vname]["shape"],
                                             wvar["shape"])
                            self.assertEqual(got["variables"][vname]["nonzero"],
                                             wvar["nonzero"])
                        else:
                            self.assertEqual(got["variables"][vname]["values"],
                                             wvar["values"])
        for suffix, want in golden["sidecars"].items():
            with self.subTest(sidecar=suffix):
                self.assertEqual(sidecars.get(suffix), want)
        return golden, nc, sidecars

    def test_main_no_tas_matches_octave_exactly(self):
        self._compare("main_no_tas", with_tas=False)

    def test_main_with_tas_matches_octave_exactly(self):
        self._compare("main_with_tas", with_tas=True)

    def test_the_two_main_runs_differ_only_in_tasRatio(self):
        """Otherwise "matches the golden" could be true of the wrong golden."""
        cases = _golden()["cases"]
        a, b = cases["main_no_tas"]["netcdf"], cases["main_with_tas"]["netcdf"]
        for suffix in a:
            for vname in a[suffix]["variables"]:
                with self.subTest(file=suffix, variable=vname):
                    same = a[suffix]["variables"][vname] == b[suffix]["variables"][vname]
                    self.assertEqual(same, vname != "tasRatio")

    def test_global_attributes_carry_the_two_that_are_deterministic(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            _, nc, _ = _run_port(Path(tmp), MAIN_FIXTURE, "attrs", with_tas=False)
        want = _golden()["cases"]["main_no_tas"]["netcdf"]
        for suffix, orientation in ((".H.nc", "Horizontal"), (".V.nc", "Vertical")):
            with self.subTest(file=suffix):
                got = nc[suffix]["global_attributes"]
                self.assertEqual(got["Software"],
                                 want[suffix]["global_attributes"]["Software"])
                self.assertEqual(got["Probe Channel_Orientation"], orientation)
                # 'Creation Time' is non-deterministic upstream; the port takes
                # it as an argument precisely so it is never compared by accident.
                self.assertEqual(got["Creation Time"], CREATION_TIME)


class TestTheBoundChange(unittest.TestCase):
    """``while iii<=2048`` -> ``while iii+4<=2048``: a fix AND a behaviour change."""

    def test_the_two_releases_decoded_the_same_bytes_differently(self):
        cases = _golden()["cases"]
        nz35 = cases["bound_v35"]["netcdf"][".H.nc"]["variables"]["data"]["nonzero"]
        nz314 = cases["bound_v314"]["netcdf"][".H.cdf"]["variables"]["data"]["nonzero"]
        self.assertTrue(nz35, "v3.5 decoded nothing; the case proves nothing")
        self.assertNotEqual(nz35, nz314)
        # v3.1.4 sees the late packet as well as the lead one, so its image is a
        # strict superset -- not merely different.
        self.assertLess(len(nz35), len(nz314))
        self.assertTrue({tuple(e) for e in nz35} < {tuple(e) for e in nz314})

    def test_the_port_reproduces_v35_on_the_bound_fixture(self):
        import tempfile

        want = _golden()["cases"]["bound_v35"]
        with tempfile.TemporaryDirectory() as tmp:
            _, nc, sidecars = _run_port(
                Path(tmp), BOUND_FIXTURE, "bound", with_tas=False
            )
        self.assertEqual(nc[".H.nc"]["variables"]["data"]["nonzero"],
                         want["netcdf"][".H.nc"]["variables"]["data"]["nonzero"])
        # One NV line, not two: the late packet is never reached, so its
        # `.NV.csv` row is never written either.
        self.assertEqual(sidecars.get(".NV.csv"), want["sidecars"][".NV.csv"])
        self.assertEqual(sidecars[".NV.csv"].count("\n"), 1)

    def test_the_scan_limit_is_four_short_and_named(self):
        self.assertEqual(SCAN_LIMIT, 2044)
        self.assertEqual(LATE_MARKER_FIRST_SKIPPED, 2045)

    def test_a_marker_at_2045_is_walked_past_by_the_port(self):
        """Directly, without the fixture: the loop must not examine word 2045."""
        buf = np.zeros(4096, dtype=np.int64)
        buf[LATE_MARKER_FIRST_SKIPPED - 1] = v35_spec.MARKER_HK
        img_h, img_v, n_next, tas, tas_prev = get_img_v35(buf, 0.0, None, 42.0)
        self.assertEqual(tas, 42.0, "a housekeeping packet at 2045 was decoded")
        self.assertEqual(tas_prev, 42.0)
        self.assertFalse(img_h.any())
        self.assertFalse(img_v.any())
        # :441 measures nNext from 2048 regardless of where the scan stopped.
        self.assertEqual(n_next, SCAN_LIMIT + 1 - 2048)


class TestTheTasGateAndItsSidecar(unittest.TestCase):
    """The gate is ``arrayprobe_uiops.tas``'s; what the driver adds is where its output goes."""

    def test_the_tas_series_is_the_gated_one_record_by_record(self):
        """Three records in a row keep 50 after the gate rejects 170 and nHOL."""
        tas = _golden()["cases"]["main_no_tas"]["netcdf"][".H.nc"]["variables"]["tas"]
        self.assertEqual(tas["values"], [-999.0, 50.0, 50.0, 50.0, 90.0, 90.0, 90.0])

    def test_the_first_records_carry_the_minus_999_initialiser(self):
        for suffix in (".H.nc", ".V.nc"):
            with self.subTest(file=suffix):
                values = (_golden()["cases"]["main_no_tas"]["netcdf"][suffix]
                          ["variables"]["tas"]["values"])
                self.assertEqual(values[0], INITIAL_TAS)

    def test_the_sidecar_logs_the_gated_value_not_the_probes_reading(self):
        """THE FINDING. The rejected reading is recorded nowhere at all.

        Row 2's packet carried ``tasTemp = 170`` and row 3's carried 75 with
        ``nHOL = 1``; both rows log 50, the last accepted value. v3.1.4's
        ``.tas.csv`` logged the probe's own reading in that column.
        """
        rows = [r for r in
                _golden()["cases"]["main_no_tas"]["sidecars"][".tas.csv"].splitlines() if r]
        self.assertEqual(len(rows), 4)
        logged = [float(r.split(",")[1]) for r in rows]
        self.assertEqual(logged, [50.0, 50.0, 50.0, 90.0])
        self.assertNotIn(170.0, logged)
        self.assertNotIn(75.0, logged)
        # The nHOL column still shows why one of them was rejected; the
        # tasTemp == 170 rejection leaves no trace in the file at all.
        self.assertEqual([int(r.split(",")[5]) for r in rows], [0, 0, 1, 0])

    def test_the_sidecar_has_fifteen_columns_and_six_voltages(self):
        rows = [r for r in
                _golden()["cases"]["main_no_tas"]["sidecars"][".tas.csv"].splitlines() if r]
        for row in rows:
            with self.subTest(row=row[:20]):
                fields = row.split(", ")
                self.assertEqual(len(fields), 15)
                self.assertEqual([float(f) for f in fields[9:]],
                                 [512 * k * DIODE_VOLTAGE_SCALE for k in range(1, 7)])

    def test_the_voltage_scale_is_exactly_ten_over_4096(self):
        """A 12-bit converter over a 10 V full scale. Upstream writes the
        decimal with no comment; this checks the two really are one number,
        because a decimal that is only *close* would drift the sixth figure of
        every voltage column."""
        self.assertEqual(DIODE_VOLTAGE_SCALE, 10.0 / 4096.0)
        self.assertNotEqual(DIODE_VOLTAGE_SCALE, 2.0 ** -9)

    def test_the_writer_emits_the_same_row_the_octave_run_did(self):
        """The Python format string against MATLAB's, one row, byte for byte."""
        want = (_golden()["cases"]["main_no_tas"]["sidecars"][".tas.csv"]
                .splitlines()[0] + "\n")
        writer = SidecarWriterV35("unused")
        writer.tas(64405.5, 50.0, 100000.0, 22, 33, 0, 0, 66, 77,
                   *(512 * k * DIODE_VOLTAGE_SCALE for k in range(1, 7)))
        self.assertEqual(writer._tas, [want])


class TestPreservedDefects(unittest.TestCase):
    """Each measured on the v3.5 source, not inherited from the v3.1.4 write-up."""

    def test_the_mask_sidecar_still_has_no_line_terminator(self):
        """The preserved bug, re-measured against v3.5 rather than
        inferred from the diff not mentioning ``.MK.csv``."""
        text = _golden()["cases"]["main_no_tas"]["sidecars"][".MK.csv"]
        self.assertNotIn("\n", text)
        self.assertTrue(text.endswith(", "))
        self.assertEqual(len([f for f in text.split(",") if f.strip()]), 19)

    def test_the_last_record_is_never_a_primary(self):
        """Ten records in, nine decode windows -- unchanged in v3.5."""
        windows = list(v35_spec.iter_record_windows(MAIN_FIXTURE))
        n_records = MAIN_FIXTURE.stat().st_size // v35_spec.RECORD_BYTES
        self.assertEqual(n_records, 10)
        self.assertEqual(len(windows), n_records - 1)

    def test_the_day_rollover_clamp_is_applied_to_V_only(self):
        """THE FINDING. One physical record, two different hours on disk.

        Raw record 7 has ``hour = 25``. ``:224-226`` clamps it inside the V
        write block, which runs after the H one, so ``.H.nc`` keeps 25 and
        ``.V.nc`` gets 1 -- a one-day disagreement between the two channels of
        the same file, with nothing recording that it happened.
        """
        nc = _golden()["cases"]["main_no_tas"]["netcdf"]
        h_hours = nc[".H.nc"]["variables"]["hour"]["values"]
        v_hours = nc[".V.nc"]["variables"]["hour"]["values"]
        self.assertIn(25.0, h_hours)
        self.assertNotIn(25.0, v_hours)
        self.assertEqual(v_hours[-1], 1.0)
        # Same record: same second, same millisecond, different hour.
        self.assertEqual(nc[".H.nc"]["variables"]["second"]["values"][-2], 10.0)
        self.assertEqual(nc[".V.nc"]["variables"]["second"]["values"][-1], 10.0)

    def test_the_clamp_does_not_persist_into_the_next_record(self):
        """MATLAB mutates ``hour`` in place; the next iteration re-reads it."""
        h_hours = _golden()["cases"]["main_no_tas"]["netcdf"][".H.nc"]["variables"]["hour"]
        self.assertEqual(h_hours["values"][-1], 6.0)

    @repo_only
    def test_daystart_is_dead_in_the_vendored_source(self):
        """Assigned once, read nowhere, and never passed or requested."""
        text = V35_SPEC_M.read_text(encoding="utf-8", errors="replace")
        hits = [ln for ln in text.splitlines() if "daystart" in ln]
        self.assertEqual(len(hits), 2, hits)
        self.assertIn("daystart = 99999999;", hits[0])
        self.assertIn("function [year,month, wkday,day, hour, minute, second, "
                      "millisec, data, discard, daystart]=readRecord(fid, daystart)",
                      hits[1])
        # Both call sites take ten outputs and one argument.
        self.assertEqual(text.count("]=readRecord(fid);"), 2)
        self.assertEqual(text.count("]=readRecord(fid, daystart);"), 0)

    @repo_only
    def test_nStereo_is_read_and_never_used(self):
        text = V35_SPEC_M.read_text(encoding="utf-8", errors="replace")
        self.assertEqual(len([ln for ln in text.splitlines() if "nStereo" in ln]), 1)


class TestTasRatio(unittest.TestCase):
    """The driver half of the ``tas`` module's ``tas_ratio``: precision, and when it is written."""

    def test_without_an_aircraft_series_tasRatio_is_pure_fill(self):
        """THE FINDING. The variable is DEFINED unconditionally and WRITTEN
        conditionally, so a run with no TAS input leaves a fill-valued column
        and nothing in the file says it was never populated."""
        for suffix in (".H.nc", ".V.nc"):
            with self.subTest(file=suffix):
                values = (_golden()["cases"]["main_no_tas"]["netcdf"][suffix]
                          ["variables"]["tasRatio"]["values"])
                self.assertTrue(values)
                self.assertEqual(set(values), {9.969209968386869e36})

    def test_the_ratio_is_single_precision_because_the_probe_tas_is(self):
        """50/120 comes back as float32, not float64 -- measured, then ported."""
        values = (_golden()["cases"]["main_with_tas"]["netcdf"][".H.nc"]
                  ["variables"]["tasRatio"]["values"])
        self.assertEqual(values[1], float(np.float32(50.0 / 120.0)))
        self.assertNotEqual(values[1], 50.0 / 120.0)

    def test_the_fallbacks_are_exactly_one(self):
        """-999 probe TAS (record 0) and a record time absent from the series."""
        values = (_golden()["cases"]["main_with_tas"]["netcdf"][".H.nc"]
                  ["variables"]["tasRatio"]["values"])
        self.assertEqual(values[0], 1.0)
        self.assertEqual(values[5], 1.0)

    def test_one_of_flt_time_and_flt_tas_alone_is_refused(self):
        with self.assertRaises(ValueError):
            read_binary_spec_v35(MAIN_FIXTURE, "unused", software=SOFTWARE,
                                 creation_time=CREATION_TIME, flt_time=[1, 2])

    def test_a_dead_tas_feed_aborts_before_a_record_is_read(self):
        """``arrayprobe_uiops.tas``'s measured ``interp1`` raise, reached through the driver."""
        from arrayprobe_uiops.tas import InterpTasError

        with self.assertRaises(InterpTasError):
            read_binary_spec_v35(MAIN_FIXTURE, "unused", software=SOFTWARE,
                                 creation_time=CREATION_TIME,
                                 flt_time=[1, 2, 3], flt_tas=[0.0, 0.0, 0.0])


class TestTimeOffset(unittest.TestCase):
    """Doctrine layer 3: Octave 11.3.0 has ``datetime`` but no ``plus`` for it."""

    def test_the_gap_is_declared(self):
        self.assertIn("time_offset", WRITER_GAPS)

    def test_a_positive_offset_rolls_the_clock_forward(self):
        header = v35_spec.RecordHeader(2016, 9, 2, 6, 23, 59, 50, 250)
        moved = apply_time_offset(header, 20)
        self.assertEqual((moved.year, moved.month, moved.day), (2016, 9, 7))
        self.assertEqual((moved.hour, moved.minute, moved.second), (0, 0, 10))

    def test_millisec_and_wkday_are_not_touched(self):
        """Because the MATLAB does not touch them -- ``ymd``/``hms`` rebuild six
        fields out of eight, and the ``datetime`` is built without the
        milliseconds. A fractional offset is therefore silently lost."""
        header = v35_spec.RecordHeader(2016, 9, 2, 6, 23, 59, 50, 250)
        moved = apply_time_offset(header, 20.5)
        self.assertEqual(moved.millisec, 250)
        self.assertEqual(moved.wkday, 2)
        self.assertEqual(moved.second, 10)

    def test_a_negative_offset_works_the_same_way(self):
        header = v35_spec.RecordHeader(2016, 9, 2, 6, 0, 0, 5, 0)
        moved = apply_time_offset(header, -10)
        self.assertEqual((moved.day, moved.hour, moved.minute, moved.second),
                         (5, 23, 59, 55))

    def test_an_hour_of_25_is_carried_into_the_date_not_rejected(self):
        """The clamp at ``:224-226`` is the only thing upstream does about
        ``hour >= 24``; a ``datetime`` cannot hold one, so the offset path
        normalises it into the day. Stated because it is a divergence the
        MATLAB would hit as an error rather than a value."""
        header = v35_spec.RecordHeader(2016, 9, 2, 6, 25, 0, 0, 0)
        moved = apply_time_offset(header, 0)
        self.assertEqual((moved.day, moved.hour), (7, 1))


class TestWriterGaps(unittest.TestCase):
    """The two encoding details this port does not reproduce, measured not argued."""

    def test_both_gaps_are_named(self):
        self.assertEqual(WRITER_GAPS, ("deflate", "tas_fill_value", "time_offset"))

    def test_the_octave_run_really_did_deflate_every_variable(self):
        """Otherwise "we do not reproduce the deflate" would be about nothing."""
        for suffix in (".H.nc", ".V.nc"):
            variables = (_golden()["cases"]["main_no_tas"]["netcdf"][suffix]
                         ["variables"])
            for name, entry in variables.items():
                with self.subTest(file=suffix, variable=name):
                    self.assertTrue(entry["filters"]["zlib"])
                    self.assertEqual(entry["filters"]["complevel"], 9)
                    self.assertTrue(entry["filters"]["shuffle"])

    def test_deflate_changes_no_value_that_is_read_back(self):
        """The gap is a storage one. Measured here rather than asserted: write
        the same array twice, deflated and not, and read both back."""
        import tempfile

        from netCDF4 import Dataset

        values = np.arange(-5, 5, dtype=np.float64) / 7.0
        out = []
        with tempfile.TemporaryDirectory() as tmp:
            for label, kw in (("plain", {}),
                              ("deflated", {"zlib": True, "complevel": 9,
                                            "shuffle": True})):
                path = Path(tmp) / f"{label}.nc"
                with Dataset(path, "w", format="NETCDF4") as ds:
                    ds.createDimension("time", None)
                    var = ds.createVariable("tas", "f8", ("time",), **kw)
                    var[:] = values
                with Dataset(path, "r") as ds:
                    ds.set_auto_maskandscale(False)
                    out.append(np.asarray(ds.variables["tas"][:]))
        np.testing.assert_array_equal(out[0], out[1])

    def test_the_tas_fill_value_is_never_exercised_by_this_program(self):
        """``tas`` is written for every record on both channels, so the missing
        ``_FillValue`` attribute changes no value anyone can read."""
        for case in ("main_no_tas", "main_with_tas"):
            nc = _golden()["cases"][case]["netcdf"]
            for suffix, entry in nc.items():
                with self.subTest(case=case, file=suffix):
                    n = entry["dimensions"]["time"][0]
                    self.assertEqual(len(entry["variables"]["tas"]["values"]), n)
                    self.assertNotIn(9.969209968386869e36,
                                     entry["variables"]["tas"]["values"])

    def test_the_port_writes_netcdf4_like_the_source_does(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            _, nc, _ = _run_port(Path(tmp), MAIN_FIXTURE, "fmt", with_tas=False)
        for suffix in (".H.nc", ".V.nc"):
            with self.subTest(file=suffix):
                self.assertEqual(nc[suffix]["data_model"], "NETCDF4")


class TestChannelSelection(unittest.TestCase):
    """Skipping a channel is a storage decision, never a behavioural one."""

    def test_counts_and_sidecars_are_unchanged_when_V_is_skipped(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            both = read_binary_spec_v35(
                MAIN_FIXTURE, Path(tmp) / "both", software=SOFTWARE,
                creation_time=CREATION_TIME)
            h_only = read_binary_spec_v35(
                MAIN_FIXTURE, Path(tmp) / "h", software=SOFTWARE,
                creation_time=CREATION_TIME, channels="H")
            self.assertEqual(both, h_only)
            self.assertFalse((Path(tmp) / "h.V.nc").exists())
            self.assertTrue((Path(tmp) / "h.H.nc").exists())
            for suffix in (".tas.csv", ".MK.csv", ".NV.csv"):
                with self.subTest(sidecar=suffix):
                    self.assertEqual(
                        (Path(tmp) / f"both{suffix}").read_bytes(),
                        (Path(tmp) / f"h{suffix}").read_bytes(),
                    )

    def test_an_unknown_channel_selection_is_refused(self):
        with self.assertRaises(ValueError):
            read_binary_spec_v35(MAIN_FIXTURE, "unused", software=SOFTWARE,
                                 creation_time=CREATION_TIME, channels="X")


class TestSoftwareAttributeIsAnArgument(unittest.TestCase):
    """``:79-81`` reads ``version.txt`` from the *cwd*; this port refuses to."""

    def test_software_has_no_default(self):
        import inspect

        sig = inspect.signature(read_binary_spec_v35)
        for name in ("software", "creation_time"):
            with self.subTest(parameter=name):
                self.assertIs(sig.parameters[name].default, inspect.Parameter.empty)

    @repo_only
    def test_the_vendored_version_file_says_what_the_golden_recorded(self):
        version = (_upstream.source("uiops35") / "version.txt")
        self.assertEqual(version.read_text(encoding="ascii").strip(), SOFTWARE)
        self.assertEqual(
            _golden()["cases"]["main_no_tas"]["netcdf"][".H.nc"]
            ["global_attributes"]["Software"],
            SOFTWARE,
        )


if __name__ == "__main__":
    unittest.main()
