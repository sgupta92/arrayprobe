# SPDX-License-Identifier: BSD-3-Clause
"""``imgproc_sm_v35(shadow_diode=...)``: stuck-diode re-illumination on the v3.5 engine.

Stock v3.5 has no masking. The ORACLES fork's nine-argument ``imgProc_sm``
re-illuminates stuck diodes with ``c(:,shadow_diode)='1'`` (extraction
``:286-292``) right after decoding the image into characters; the v3.5 engine
takes the same step through :func:`arrayprobe_uiops.diode_mask.reilluminate`,
opt-in, before the ``iQC`` clean-up (``:801-846``), as the author decided.


What is asserted:

* **Off is bit-identical.** The keyword omitted, ``None``, an empty list, an
  empty array and an empty :class:`ShadowDiodeMask` write the same file, byte
  for byte with ``creation_time`` pinned, and the same arrays
  (``np.array_equal``) variable by variable. The omitted-keyword path is the
  one ``tests/test_v35_imgproc.py::TestAgainstTheOctaveGolden`` holds to
  v3.5's own Octave output, so "unchanged" is anchored there.
* **On changes exactly the masked columns**, as ``reilluminate`` defines: the
  image after the step equals the decoded image except that each masked
  column is ``'1'`` (lit) in every slice; and it reaches the written
  measurements.
* **Before ``iQC``**: with ``iQC=1``, the image ``qc_image`` receives already
  has the masked column lit. This is measured by spying on ``qc_image``'s
  input, not by reading the function's source.
* **A diode past the probe's width** widens the image (MATLAB's assignment
  growth) and the ``:850-853`` width check ends the run.
"""

from __future__ import annotations

import filecmp
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from tests.test_v35_imgproc import (
    TAS,
    TAS_TIME,
    _header,
    _read,
    _record,
    _ring,
    _square,
    _write_input,
)

from arrayprobe_uiops import diode_mask
from arrayprobe_uiops import imgproc as v35_imgproc
from arrayprobe_uiops.diode_mask import ShadowDiodeMask
from arrayprobe_uiops.measure import STOCK_V35_REJECT_CONFIG

LIT = ord("1")

#: Three records, five particles: a square crossing diode 46, a ring, and a
#: square well clear of it, so a mask on 46 alters some particles and not others.
def _records():
    recs = [
        _record([_square(0, 40, 10), _ring(0, 70, 12, 4)], [1000, 2000]),
        _record([_square(0, 90, 6)], [3000]),
        _record([_square(0, 42, 8), _square(0, 10, 5)], [4000, 5000]),
    ]
    headers = [_header(second=0), _header(second=1), _header(second=2)]
    return recs, headers


def _run_to(tmp: str, name: str, **kw):
    """Run on one shared input (its path is written into ``Image Source``) to
    ``<name>.proc.nc``; return (n, variables, proc path)."""
    infile = Path(tmp) / "in.H.nc"
    if not infile.exists():
        recs, headers = _records()
        _write_input(infile, recs, headers)
    outfile = Path(tmp) / f"{name}.proc.nc"
    kw.setdefault("iNewHabit", 0)
    kw.setdefault("reject_config", STOCK_V35_REJECT_CONFIG)
    kw.setdefault("tas_time", TAS_TIME)
    kw.setdefault("tas", TAS)
    kw.setdefault("software", "UIOOPS_v3.5")
    kw.setdefault("creation_time", "2026/09/11 00:00:00")
    n = v35_imgproc.imgproc_sm_v35(infile, outfile, "2DS", 1, 1000, "ORACLES", **kw)
    return n, _read(outfile), outfile


class OffIsBitIdentical(unittest.TestCase):
    """Every "no mask" spelling writes what the unchanged engine writes."""

    def test_none_and_every_empty_mask_equal_the_omitted_keyword(self):
        empty_mask = ShadowDiodeMask(diodes=np.array([], dtype=np.float64),
                                     date=None, time=None, source=None)
        variants = {
            "none": dict(shadow_diode=None),
            "empty_list": dict(shadow_diode=[]),
            "empty_array": dict(shadow_diode=np.array([], dtype=np.float64)),
            "empty_mask": dict(shadow_diode=empty_mask),
        }
        with tempfile.TemporaryDirectory() as tmp:
            n0, ref, ref_path = _run_to(tmp, "omitted")
            self.assertGreater(n0, 0)
            for name, kw in variants.items():
                with self.subTest(variant=name):
                    n, got, path = _run_to(tmp, name, **kw)
                    self.assertEqual(n, n0)
                    self.assertEqual(got["order"], ref["order"])
                    self.assertEqual(got["attrs"], ref["attrs"])
                    for var in ref["order"]:
                        self.assertTrue(np.array_equal(got["vars"][var], ref["vars"][var]),
                                        var)
                    self.assertTrue(filecmp.cmp(path, ref_path, shallow=False),
                                    "proc files differ byte for byte")

    def test_none_never_calls_reilluminate(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(diode_mask, "reilluminate",
                                  wraps=diode_mask.reilluminate) as spy:
            _run_to(tmp, "none", shadow_diode=None)
        spy.assert_not_called()


class OnChangesExactlyTheMaskedColumns(unittest.TestCase):

    def _spy_run(self, tmp, mask, **kw):
        seen: list[tuple[np.ndarray, np.ndarray]] = []
        real = diode_mask.reilluminate

        def spy(c, diodes, **k):
            before = c.copy()
            after = real(c, diodes, **k)
            seen.append((before, after.copy()))
            return after

        with mock.patch.object(diode_mask, "reilluminate", side_effect=spy):
            n, got, _ = _run_to(tmp, "masked", shadow_diode=mask, **kw)
        return n, got, seen

    def test_masked_columns_lit_and_nothing_else_moves(self):
        mask = [46, 100]
        cols = [d - 1 for d in mask]
        with tempfile.TemporaryDirectory() as tmp:
            _, _, seen = self._spy_run(tmp, mask)
        self.assertEqual(len(seen), 5, "one call per decoded particle image")
        crossed = 0
        for before, after in seen:
            self.assertEqual(after.shape, before.shape)
            self.assertTrue(np.all(after[:, cols] == LIT))
            others = np.setdiff1d(np.arange(before.shape[1]), cols)
            self.assertTrue(np.array_equal(after[:, others], before[:, others]))
            crossed += int(np.any(before[:, cols] != LIT))
        self.assertGreater(crossed, 0, "the fixture must shadow a masked diode somewhere")

    def test_the_mask_reaches_the_written_measurements(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, off, _ = _run_to(tmp, "off")
            _, on, _ = _run_to(tmp, "on", shadow_diode=[46])
        self.assertFalse(np.array_equal(on["vars"]["image_area"], off["vars"]["image_area"]))


class AppliedBeforeIQC(unittest.TestCase):
    """Author decision 2: qc_image sees the re-illuminated image."""

    def _qc_inputs(self, tmp, name, **kw):
        seen: list[np.ndarray] = []
        real = v35_imgproc.qc_image

        def spy(c, *a, **k):
            seen.append(np.array(c, copy=True))
            return real(c, *a, **k)

        with mock.patch.object(v35_imgproc, "qc_image", side_effect=spy):
            _run_to(tmp, name, iQC=1, **kw)
        return seen

    def test_qc_image_receives_the_masked_column_lit(self):
        col = 46 - 1
        with tempfile.TemporaryDirectory() as tmp:
            off = self._qc_inputs(tmp, "off")
            on = self._qc_inputs(tmp, "on", shadow_diode=[46])
        self.assertEqual(len(on), len(off))
        self.assertTrue(any(np.any(c[:, col] != LIT) for c in off),
                        "unmasked, some image shadows diode 46 when qc_image sees it")
        for c in on:
            self.assertTrue(np.all(c[:, col] == LIT))


class DiodePastTheWidth(unittest.TestCase):

    def test_widened_image_takes_the_850_853_return(self):
        with tempfile.TemporaryDirectory() as tmp:
            n, _, _ = _run_to(tmp, "wide", shadow_diode=[129])
        self.assertEqual(n, 0)
        self.assertTrue(v35_imgproc.WIDTH_MISMATCH_RETURNS)

    def test_zero_is_refused_as_matlab_refuses_it(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(IndexError):
            _run_to(tmp, "zero", shadow_diode=[0])


if __name__ == "__main__":
    unittest.main()


class DriverForwardsTheMask(unittest.TestCase):
    """The batch driver's engine-3.5 S3 call passes the mask to ``imgproc_sm_v35``, names the
    corrected output apart from the default proc, and leaves the unmasked stamp unchanged."""

    def setUp(self):
        from arrayprobe.driver import run_flight as rf
        self.rf = rf
        for name in ("ENGINE", "PROFILE", "TAS_FILE", "TAS_CHAIN", "AUTHORDEFAULTS_STAMP",
                     "STRAY_PIXEL"):
            self.addCleanup(setattr, rf, name, getattr(rf, name))

    def _chunk_call(self, shadow_diode):
        rf = self.rf
        fake = mock.MagicMock()
        fake.PROBES_V35.__getitem__.return_value.probetype = 2
        selector = mock.MagicMock()
        selector.module.return_value = fake
        with mock.patch.object(rf, "ENGINE", "3.5"), \
                mock.patch.object(rf, "_v35", return_value=selector), \
                mock.patch.object(rf, "_aircraft_series", return_value=(None, None)), \
                mock.patch.object(rf, "_s3_tas_qc_v35", return_value=None):
            rf._imgproc_sm_chunk(Path("base160101000000.H.nc"), Path("out.nc"), 1, 10,
                                 shadow_diode=shadow_diode)
        return fake.imgproc_sm_v35.call_args.kwargs

    def test_the_mask_reaches_imgproc_sm_v35(self):
        self.assertEqual(self._chunk_call([46])["shadow_diode"], [46])

    def test_no_mask_forwards_none(self):
        self.assertIsNone(self._chunk_call(None)["shadow_diode"])

    def test_a_v35_decode_does_not_name_the_default_proc(self):
        rf = self.rf
        default = rf.proc_path_for_decode(Path("base160101000000.H.nc"), Path("o"))
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.dict(rf.SHADOW_DIODE_OVERRIDES, {"base160101000000": [46]}), \
                mock.patch.object(rf, "_check_proc_state", return_value=True):
            target = rf.stage3_corrected(Path(d) / "base160101000000.H.nc", Path(d))
        self.assertEqual(target.name, "proc.base160101000000.H.diodecorrected.nc")
        self.assertNotEqual(target.name, default.name)

    def test_the_unmasked_v35_stamp_equals_the_tracked_fixture(self):
        """``tests/data/demo_flight_v35_proc.call`` was written by an engine-3.5 S3 run with
        no mask before ``--diode-corrected`` reached this engine; the stamp is rebuilt here
        from the same configuration and must match it byte for byte. That run was made with the
        default-on stray-pixel correction, so the switch is pinned on to match its stamp."""
        from arrayprobe.profiles import STOCK_V35
        rf = self.rf
        fixture = (Path(__file__).resolve().parent / "data"
                   / "demo_flight_v35_proc.call").read_text(encoding="utf-8").strip()
        self.assertIn("stray_pixel=on:g8,n2,m9", fixture)
        rf.ENGINE, rf.PROFILE = "3.5", STOCK_V35
        rf.TAS_FILE = "somewhere/demo_flight_v35_aircraft.cdf"
        rf.TAS_CHAIN, rf.AUTHORDEFAULTS_STAMP = None, None
        rf.STRAY_PIXEL = True
        self.assertEqual(rf.proc_call_label(shadow_diode=None), fixture)
        self.assertEqual(rf.proc_call_label(shadow_diode=[]), fixture)
        self.assertEqual(rf.proc_call_label(shadow_diode=[46]),
                         fixture.replace("shadow_diode=none", "shadow_diode=46"))
