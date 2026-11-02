# SPDX-License-Identifier: BSD-3-Clause
"""``imgproc_sm_v35(ncar_2dc_timing_fix=...)``: the NCAR 2DC timing-word correction
(``arrayprobe_uiops.ncar_2dc_timing``, SODA-2's ``fix2dimage.pro`` under its
``soda2_processbuffer.pro:84-87`` gate). Not UIOOPS behaviour.

Synthetic records built here, no raw data: the tracked hand-built 2DC fixture
(``tests/data/s7c_2dc_octave_decoded.nc``) supplies the file layout, and its one record
is overwritten with

* an **NCAR-form** record -- per particle ``[FFFFFFFF][FF tttttt][FF000000]`` then image
  slices, the form the ACE-1 RAF 2DC records carry;
* a **0x55-form** record -- the same particles with the timing and sync words already
  ``[55 tttttt][55000000]``, i.e. at least three primary syncs, so the gate leaves it alone.

Off is checked against a run with the keyword omitted, byte for byte; that the omitted
call still equals upstream is ``test_v35_imgproc_probetypes``'s Octave golden.
"""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

try:
    import netCDF4
except ImportError:  # pragma: no cover
    netCDF4 = None

from arrayprobe_uiops import imgproc as _imgproc
from arrayprobe_uiops.imgproc import imgproc_sm_v35
from arrayprobe_uiops.measure import STOCK_V35_REJECT_CONFIG
from arrayprobe_uiops.ncar_2dc_timing import STAMP_ON, convert_record, ncar_word_slices

DATA = Path(__file__).resolve().parent / "data"
DEC_2DC = DATA / "s7c_2dc_octave_decoded.nc"
SOFTWARE = "UIOOPS_v3.5"
CREATION_TIME = "2026/10/07 00:00:00"
ATTR = "arrayprobe_ncar_2dc_timing"
N_PARTICLES = 8
#: Image slices taken from no fixture: no word is a fix2dimage.pro:9 candidate
#: (FF800000, 0, FF000000, 2A000000) and none starts with 0x55 or is all-blank.
_IMAGE = ((0, 0, 0, 3), (0, 0, 0, 7), (0, 0, 0, 15), (0, 0, 0, 7))


def _record(top: int) -> np.ndarray:
    """1024 x 4 record of ``N_PARTICLES`` frames ``[FFFFFFFF][top 12 34 p][top 00 00 00]``
    followed by ``_IMAGE``; ``top`` 0xFF is the NCAR form, 0x55 the converted one."""
    rows: list[tuple[int, int, int, int]] = []
    for p in range(N_PARTICLES):
        rows.append((255, 255, 255, 255))
        rows.append((top, 0x12, 0x34, p + 1))
        rows.append((top, 0, 0, 0))
        rows.extend(_IMAGE)
    rows.append((255, 255, 255, 255))
    rows.extend([(0, 0, 0, 1)] * (1024 - len(rows)))
    return np.asarray(rows, dtype=np.int32)


def _write_input(dest: Path, record: np.ndarray) -> Path:
    shutil.copyfile(DEC_2DC, dest)
    with netCDF4.Dataset(str(dest), "a") as ds:
        ds.set_auto_maskandscale(False)
        ds.variables["data"][0:1, :, :] = record[np.newaxis]
    return dest


def _run(infile: Path, outfile: Path, **kw) -> int:
    return imgproc_sm_v35(
        str(infile), str(outfile), "2DC", 1, 1, "TEST",
        iRectEllipse=0, iCalcAllDiodeStats=1, iQC=0, iNewHabit=0,
        reject_config=STOCK_V35_REJECT_CONFIG, tas_time=None, tas=None,
        software=SOFTWARE, creation_time=CREATION_TIME, **kw,
    )


def _variables(path: Path) -> dict[str, np.ndarray]:
    with netCDF4.Dataset(str(path)) as ds:
        ds.set_auto_maskandscale(False)
        return {k: np.asarray(v[:]) for k, v in ds.variables.items()}


def _globals(path: Path) -> dict[str, str]:
    with netCDF4.Dataset(str(path)) as ds:
        return {k: str(ds.getncattr(k)) for k in ds.ncattrs()}


@unittest.skipUnless(netCDF4 is not None and DEC_2DC.is_file(), "netCDF4 or 2DC fixture absent")
class TestNcar2dcTimingFix(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.ncar_in = _write_input(self.tmp / "ncar.nc", _record(0xFF))
        self.form55_in = _write_input(self.tmp / "form55.nc", _record(0x55))

    def tearDown(self):
        self._tmp.cleanup()

    # (a) off writes what the keyword-omitted call writes
    def test_off_is_byte_identical_to_the_keyword_omitted_call(self):
        for name, infile in (("ncar", self.ncar_in), ("form55", self.form55_in),
                             ("fixture", DEC_2DC)):
            with self.subTest(input=name):
                omitted, off = self.tmp / f"{name}_omit.nc", self.tmp / f"{name}_off.nc"
                n_omit = _run(infile, omitted)
                n_off = _run(infile, off, ncar_2dc_timing_fix=False)
                self.assertEqual(n_omit, n_off)
                self.assertEqual(_imgproc.NCAR_2DC_SYNCS_CONVERTED, {})
                a, b = _variables(omitted), _variables(off)
                self.assertEqual(list(a), list(b))
                for var in a:
                    self.assertTrue(np.array_equal(a[var], b[var], equal_nan=True), var)
                self.assertNotIn(ATTR, _globals(off))
                self.assertEqual(omitted.read_bytes(), off.read_bytes())

    def test_off_frames_nothing_on_an_ncar_record(self):
        # The defect itself: imgProc_sm.m:754 needs byte 0x55 after the boundary.
        self.assertEqual(_run(self.ncar_in, self.tmp / "off.nc"), 0)

    # (b) on frames particles on an NCAR record
    def test_on_frames_particles_on_an_ncar_record(self):
        n_on = _run(self.ncar_in, self.tmp / "on.nc", ncar_2dc_timing_fix=True)
        self.assertGreater(n_on, 0)
        self.assertEqual(sum(_imgproc.NCAR_2DC_SYNCS_CONVERTED.values()), N_PARTICLES - 1)

    def test_on_converts_the_ncar_record_to_the_55_form(self):
        # fix2dimage.pro:13-15 keeps a candidate only when a gap > 1 follows it, so the
        # record's last sync word is never converted -- SODA-2's behaviour, kept.
        converted, n = convert_record(_record(0xFF))
        self.assertEqual(n, N_PARTICLES - 1)
        want = _record(0x55)
        last = (N_PARTICLES - 1) * (3 + len(_IMAGE))
        want[last + 1, 0] = want[last + 2, 0] = 0xFF
        np.testing.assert_array_equal(converted, want)

    # (c) a record already carrying 0x55 syncs is left unchanged
    def test_a_record_with_55_syncs_is_left_unchanged(self):
        rec = _record(0x55)
        self.assertEqual(ncar_word_slices(rec).size, 0)
        out, n = convert_record(rec)
        self.assertIs(out, rec)
        self.assertEqual(n, 0)

    def test_on_and_off_agree_on_a_55_form_record_except_the_stamp(self):
        off, on = self.tmp / "off.nc", self.tmp / "on.nc"
        n_off = _run(self.form55_in, off)
        n_on = _run(self.form55_in, on, ncar_2dc_timing_fix=True)
        self.assertGreater(n_off, 0)
        self.assertEqual(n_on, n_off)
        self.assertEqual(_imgproc.NCAR_2DC_SYNCS_CONVERTED, {1: 0})
        a, b = _variables(off), _variables(on)
        self.assertEqual(list(a), list(b))
        for var in a:
            self.assertTrue(np.array_equal(a[var], b[var], equal_nan=True), var)

    # (d) the stamp
    def test_on_stamps_the_global_attribute(self):
        on = self.tmp / "on.nc"
        _run(self.ncar_in, on, ncar_2dc_timing_fix=True)
        self.assertEqual(_globals(on).get(ATTR), "on:fix2dimage")
        self.assertEqual(STAMP_ON, "on:fix2dimage")


if __name__ == "__main__":
    unittest.main()
