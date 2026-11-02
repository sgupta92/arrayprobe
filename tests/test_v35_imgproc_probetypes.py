# SPDX-License-Identifier: BSD-3-Clause
"""V-PT acceptance: ``arrayprobe_uiops``'s probetype 0/1/3 paths against the real,
unmodified v3.5 ``imgProc_sm.m`` running under Octave.

The golden is ``tests/data/v35_probetype013_oracle.json``, built by
``octave_oracle/run_v35_probetype013_bank.py``.  Thirteen cases: 2DC
(probetype 0) and Fast2DC (probetype 3) on the hand-built synthetic PMS
fixtures, CIP/PIP (probetype 1) on a three-record slice of the real
``ImagefileExamplePECAN`` decode, and the four GCPEx-dated CIP runs that are
the only way to reach v3.5's own new clock-offset table
(``imgProc_sm.m:976-1093``) -- a branch v3.1.4 does not have at all.

Two things are asserted besides value equality:

* the GCPEx inputs the port is fed are **byte-identical** to the ones the bank
  fed Octave (sha256, recorded in the golden), so a case cannot silently drift
  into comparing two different files;
* ``Particle_number_all`` must be *defined but never written* for probetypes 0
  and 3 (``:356``'s ``||`` against ``:1329``'s ``&&``), which is a different
  file from one where the variable is absent.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

import numpy as np

try:
    import netCDF4
except ImportError:  # pragma: no cover
    netCDF4 = None

from arrayprobe.constants import IMGPROC_CONFIG
from arrayprobe_uiops.imgproc import (
    PROBES_V35,
    gcpex_cip_offsets,
    imgproc_sm_v35,
    imgproc_variables_v35,
)
from arrayprobe_uiops.measure import STOCK_V35_REJECT_CONFIG

DATA = Path(__file__).resolve().parent / "data"
ORACLE_PATH = DATA / "v35_probetype013_oracle.json"

DEC_2DC = DATA / "s7c_2dc_octave_decoded.nc"
DEC_F2DC = DATA / "s7e_f2dc_octave_decoded.nc"
DMT_DECODED = DATA / "s6_dmt_synthetic_octave_golden.nc"

SOFTWARE = "UIOOPS_v3.5"
CREATION_TIME = "2026/09/16 00:00:00"

#: Same two ``test_v35_imgproc.py`` excludes, for the same reasons:
#: ``'Creation Time'`` (``:297``) is a wall clock, and ``'Image Source'``
#: (``:302``) is the input path as the caller spelled it -- an absolute path
#: under a scratch directory for the GCPEx cases, and ``as_posix()`` in the
#: Octave driver against a native Windows path here.  The bank already drops
#: both from the golden (they would put a home directory into a tracked file),
#: so this list is belt and braces; every other global attribute, and every
#: value and per-variable attribute, IS compared.
_NON_COMPARABLE_ATTRS = ("Creation Time", "Image Source", "arrayprobe_engine", "arrayprobe_profile")

_INPUTS = {"2DC": DEC_2DC, "Fast2DC": DEC_F2DC, "CIP": DMT_DECODED, "PIP": DMT_DECODED}


def _write_gcpex_dated(source: Path, dest: Path, date) -> None:
    """The bank's own :func:`run_v35_probetype013_bank._write_gcpex_dated`,
    repeated here so the test has no import from ``octave_oracle/``.  The
    sha256 assertion below is what keeps the two in step: if this drifts, the
    hash stops matching and the case fails rather than quietly comparing the
    port on one input against Octave on another."""
    month, day, hour, minute, second = date
    shutil.copy2(source, dest)
    with netCDF4.Dataset(str(dest), "a") as ds:
        ds.set_auto_maskandscale(False)
        n = len(ds.dimensions["time"])
        for name, value in (("month", month), ("day", day), ("hour", hour),
                            ("minute", minute), ("second", second)):
            ds.variables[name][:] = np.full(n, value, dtype=ds.variables[name].dtype)


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
@unittest.skipUnless(ORACLE_PATH.is_file(), "V-PT Octave golden not present")
class TestFramingConstantsMatchTheV314Table(unittest.TestCase):
    """``PROBES_V35``'s framing fields are the same literals the v3.1.4 port
    reads out of the same (byte-identical) region of ``imgProc_sm.m``.

    Asserted rather than asserted-in-a-comment: this is the check behind the
    claim in :class:`arrayprobe_uiops.imgproc.ProbeV35`'s docstring.  ``ds`` is
    deliberately NOT compared -- 2DC's diode size really did change from 0.025
    to 0.03 at ``imgProc_sm.m:141``, and a test that demanded equality there
    would be demanding the port miss v3.5's one probe-table change."""

    FIELDS = ("probetype", "read_width", "read_slices", "start_first",
              "boundary_needs_time", "image_slice_offset", "image_invert",
              "image_word_bits", "timing", "diodenum")

    def test_every_shared_probe_agrees(self):
        for name, probe in PROBES_V35.items():
            if name not in IMGPROC_CONFIG:
                continue  # 3VCPI_H/_V are v3.4+ only; no v3.1.4 counterpart
            cfg = IMGPROC_CONFIG[name]
            for field in self.FIELDS:
                with self.subTest(probe=name, field=field):
                    self.assertEqual(getattr(probe, field), getattr(cfg, field))
            with self.subTest(probe=name, field="boundary"):
                self.assertEqual(probe.boundary, cfg.boundary)

    def test_2dc_diode_size_is_the_one_field_that_changed(self):
        self.assertEqual(PROBES_V35["2DC"].ds, 0.03)      # imgProc_sm.m:141 (v3.5)
        self.assertEqual(IMGPROC_CONFIG["2DC"].ds, 0.025)  # imgProc_sm.m:123 (v3.1.4)
        for name in ("2DP", "CIP", "PIP", "HVPS", "2DS", "Fast2DC"):
            with self.subTest(probe=name):
                self.assertEqual(PROBES_V35[name].ds, IMGPROC_CONFIG[name].ds)


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
@unittest.skipUnless(ORACLE_PATH.is_file(), "V-PT Octave golden not present")
class TestGcpexTable(unittest.TestCase):
    """``:976-1074``, read directly rather than through a whole-file run."""

    @staticmethod
    def _rec(month, day, hour, minute=0, second=0, millisec=0):
        return {"month": float(month), "day": float(day), "hour": float(hour),
                "minute": float(minute), "second": float(second),
                "millisec": float(millisec)}

    def test_a_date_outside_the_table_is_a_no_op(self):
        self.assertEqual(gcpex_cip_offsets(self._rec(6, 17, 12)), (0, 0, 0))  # :1072

    def test_the_flat_date(self):
        # :996-997 -- 01/30 has no time chain at all.
        for hour in (0, 6, 23):
            self.assertEqual(gcpex_cip_offsets(self._rec(1, 30, hour)), (22, 36, 48))

    def test_the_only_date_that_uses_millisec(self):
        """``:980`` tests ``recTime + handles.millisec/1000`` on 01/19 and on no
        other date.  ``handles.millisec`` is int16 (``netcdf.getVar`` on
        ``read_binary_DMT.m:41``'s ``'short'``), so the sum is int16 and
        saturates at 32767: at 55660 s with 90 ms it is 32767, still
        ``< 55660.09``, and the first branch wins. ``:982-986`` are dead
        (Octave golden ``v35_gcpex_time_octave_golden.json``, ``nc`` rows;
        this test asserted the double reading until pass 6)."""
        self.assertEqual(gcpex_cip_offsets(self._rec(1, 19, 15, 27, 40, 0)),
                         (14, 40, 53))                                  # :980-981
        self.assertEqual(gcpex_cip_offsets(self._rec(1, 19, 15, 27, 40, 90)),
                         (14, 40, 53))                                  # :980-981
        self.assertEqual(gcpex_cip_offsets(self._rec(1, 19, 23, 59, 59, 999)),
                         (14, 40, 53))                                  # :980-981
        # 01/28's chain has the same shape WITHOUT the millisec term (:991),
        # and **derived**: it could not have mattered there anyway. Every
        # threshold on every other date is an integer and
        # ``recTime_secFromMidnight`` is a sum of integer clock fields, so
        # adding at most 0.999 s can never cross one. 01/19 is the only date
        # with fractional thresholds (55660.09, 62372.095) and the only one
        # that adds the term -- the two facts go together.
        self.assertEqual(gcpex_cip_offsets(self._rec(1, 28, 16, 3, 49, 999)),
                         (15, 46, 36))                                  # :991-992
        self.assertEqual(gcpex_cip_offsets(self._rec(1, 28, 16, 3, 50, 0)),
                         (16, 3, 50))                                   # :993-994

    def test_the_negative_offsets(self):
        # :1001-1002 -- the one row whose offsets are all negative.
        self.assertEqual(gcpex_cip_offsets(self._rec(1, 31, 1, 0, 0)), (-1, -23, -11))

    def test_every_chain_is_total(self):
        """No ``(month, day)`` in the table can fall through its own if/elseif
        chain without an assignment -- if one could, MATLAB would die on an
        undefined ``part_hour_offset`` rather than return zeros."""
        for (month, day) in (
            (1, 19), (1, 28), (1, 30), (1, 31), (2, 12), (2, 18), (2, 24),
        ):
            for t in range(0, 86400, 97):
                rec = self._rec(month, day, t // 3600, (t % 3600) // 60, t % 60)
                with self.subTest(month=month, day=day, t=t):
                    self.assertEqual(len(gcpex_cip_offsets(rec)), 3)


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
@unittest.skipUnless(ORACLE_PATH.is_file(), "V-PT Octave golden not present")
class TestAgainstTheOctaveGolden(unittest.TestCase):
    """Every case of the bank, variable by variable, attribute by attribute."""
    oracle: Any  # assigned in setUpClass/setUp; see there for the value

    @classmethod
    def setUpClass(cls):
        cls.oracle = json.loads(ORACLE_PATH.read_text(encoding="utf-8"))

    def _run_port(self, tmp: Path, case: dict):
        probe = case["probe"]
        if case["gcpex_date"] is None:
            infile = _INPUTS[probe]
        else:
            infile = tmp / "dmt_dated.nc"
            _write_gcpex_dated(DMT_DECODED, infile, tuple(case["gcpex_date"]))
            self.assertEqual(
                hashlib.sha256(infile.read_bytes()).hexdigest(),
                self.oracle["gcpex_inputs_sha256"][case["_name"]],
                "the date-rewritten input this test built is not the one the bank "
                "fed Octave; the comparison below would be between two files.",
            )
        out = tmp / "port.nc"
        written = imgproc_sm_v35(
            str(infile), str(out), probe, 1, case["nEvery"], case["project"],
            iRectEllipse=0, iCalcAllDiodeStats=1, iQC=case["iQC"],
            iNewHabit=case["iNewHabit"], reject_config=STOCK_V35_REJECT_CONFIG,
            tas_time=None, tas=None, software=SOFTWARE, creation_time=CREATION_TIME,
        )
        return written, out

    def _check(self, name: str):
        case = dict(self.oracle["cases"][name], _name=name)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            written, out = self._run_port(tmp, case)
            self.assertEqual(written, case["n_particles"])

            spec_table = {s.name: s.xtype for s in imgproc_variables_v35(
                iRectEllipse=0, iCalcAllDiodeStats=1, iQC=case["iQC"],
                iNewHabit=case["iNewHabit"], extended_ellipse_outputs=None,
                probetype=PROBES_V35[case["probe"]].probetype)}

            with netCDF4.Dataset(str(out)) as ds:
                ds.set_auto_maskandscale(False)
                self.assertEqual(list(ds.variables), case["order"],
                                 "variable set or definition order differs")
                for var_name, want_spec in case["variables"].items():
                    want = np.asarray(want_spec["values"])
                    have = np.asarray(ds.variables[var_name][:])
                    with self.subTest(case=name, variable=var_name):
                        self.assertEqual(list(have.shape), want_spec["shape"])
                        if spec_table[var_name] == "double":
                            np.testing.assert_allclose(
                                have.astype(float), want.astype(float),
                                rtol=1e-9, equal_nan=True)
                        else:
                            np.testing.assert_array_equal(have, want)
                        self.assertEqual(
                            {k: str(ds.variables[var_name].getncattr(k))
                             for k in ds.variables[var_name].ncattrs()},
                            want_spec["attrs"])
                for key, value in case["global_attributes"].items():
                    if key in _NON_COMPARABLE_ATTRS:
                        continue
                    with self.subTest(case=name, attribute=key):
                        self.assertEqual(str(ds.getncattr(key)), value)

    def test_2dc(self):
        self._check("2dc")

    def test_2dc_newhabit1(self):
        self._check("2dc_newhabit1")

    def test_2dc_qc1(self):
        self._check("2dc_qc1")

    def test_f2dc(self):
        self._check("f2dc")

    def test_f2dc_newhabit1(self):
        self._check("f2dc_newhabit1")

    def test_pip(self):
        self._check("pip")

    def test_pip_newhabit1(self):
        self._check("pip_newhabit1")

    def test_cip(self):
        self._check("cip")

    def test_pip_pecan(self):
        self._check("pip_pecan")

    def test_cip_gcpex_0130(self):
        self._check("cip_gcpex_0130")

    def test_cip_gcpex_0119a(self):
        self._check("cip_gcpex_0119a")

    def test_cip_gcpex_0212(self):
        self._check("cip_gcpex_0212")

    def test_cip_gcpex_0131(self):
        self._check("cip_gcpex_0131")


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
@unittest.skipUnless(ORACLE_PATH.is_file(), "V-PT Octave golden not present")
class TestThePremisesTheGoldenRecorded(unittest.TestCase):
    """The bank refuses to write a golden whose premises fail; these re-check
    the ones that are claims about the PORT rather than about Octave."""

    @classmethod
    def setUpClass(cls):
        cls.oracle = json.loads(ORACLE_PATH.read_text(encoding="utf-8"))

    def test_the_inputs_are_still_the_files_the_bank_measured(self):
        for path in (DEC_2DC, DEC_F2DC, DMT_DECODED):
            with self.subTest(fixture=path.name):
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                                 self.oracle["fixtures_sha256"][path.name])

    def test_particle_number_all_is_defined_but_never_written_for_pt0_and_pt3(self):
        for name in ("2dc", "f2dc"):
            case = self.oracle["cases"][name]
            with self.subTest(case=name):
                self.assertIn("Particle_number_all", case["variables"])  # :356's ||
                fill = netCDF4.default_fillvals[
                    np.dtype(case["variables"]["Particle_number_all"]["dtype"]).str[1:]]
                self.assertTrue(
                    all(v == fill
                        for v in case["variables"]["Particle_number_all"]["values"]),
                    "imgProc_sm.m:1329's `&&` gate should have skipped the write")

    def test_the_gcpex_table_moves_the_written_time(self):
        base = self.oracle["cases"]["cip"]["variables"]["particle_time"]["values"]
        for name in ("cip_gcpex_0130", "cip_gcpex_0119a",
                     "cip_gcpex_0212", "cip_gcpex_0131"):
            with self.subTest(case=name):
                self.assertNotEqual(
                    self.oracle["cases"][name]["variables"]["particle_time"]["values"],
                    base,
                    "this dated case did not move particle_time, so the golden "
                    "proves nothing about imgProc_sm.m:976-1093")

# _release_fixture_guard: real-data derived fixtures are excluded from the release
import pathlib as _rfg_pathlib  # noqa: E402
import unittest as _rfg_unittest  # noqa: E402

_RFG_EXCLUDED = ('s6_dmt_synthetic_octave_golden.nc',)
if not all((_rfg_pathlib.Path(__file__).resolve().parent / "data" / _n).exists()
           for _n in _RFG_EXCLUDED):
    raise _rfg_unittest.SkipTest(
        "real-data derived fixtures (UIOPS PECAN DMT / minimal-example 2D-S samples) "
        "are not shipped in the release")

if __name__ == "__main__":
    unittest.main()
