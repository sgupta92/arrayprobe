# SPDX-License-Identifier: BSD-3-Clause
"""The v3.5 port against the A15 2DC Octave pair -- the first v3.5 golden on a probetype-0 file.

``enhancements_uiops/tools/a15_particle_time_bank.py --matlab-src UIOPS-v3.5/... --out-suffix _v35``
runs the unmodified v3.5 ``read_binary_PMS.m`` + ``imgProc_sm.m`` under Octave over a
hand-built 2DC record of two particles, with the **real** v3.5 ``CGAL_minR`` MEX
(``octave_oracle/mex_build/CGAL_minR_v35.mex``, compiled from the vendored ``.cpp``) forwarded
ahead of the v3.1.4 one-argument shim. So every column here, ``image_diam_minR`` included, is
oracle-derived; none is shim-derived.

**What the v3.5 port can be held to on this file.** Until V-PT (2026-09-16) the answer was "the
measurement block only": ``imgproc_sm_v35`` ported probetype 2 alone and refused a 2DC file by
name. Probetype 0 runs now, so the whole-file path is held to these goldens too --
:class:`TheWholeFilePathForProbetypeZero` below, which used to assert the refusal. What was
already ported and probe-independent is the per-particle measurement block, ``measure_record``
(``imgProc_sm.m:1204-1291``), validated so far on 2D-S geometry only (128 diodes, 0.010 mm).
Here it meets 2DC geometry (32 diodes, 0.03 mm) for the first time and must reproduce every
measurement column the file carries, bit for bit.

The two sides come from different places: the golden is Octave running the MATLAB; the images
fed to the port are rebuilt from the raw fixture's documented byte layout (``build_payload`` in
the bank tool), with ``imgProc_sm.m:786-787``'s 2DC slicing applied by hand, and cross-checked
against the golden's own pixel counts before anything else is compared.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

import arrayprobe_uiops  # noqa: F401 -- import order: the package breaks a profiles cycle
from arrayprobe_uiops.imgproc import PROBES_V35, UnportedProbeType, _percent_shadow, imgproc_sm_v35
from arrayprobe_uiops.measure import STOCK_V35_REJECT_CONFIG, RecordGeometry, measure_record

DATA = Path(__file__).resolve().parent / "data"
GOLDENS = (DATA / "a15_2dc_hour0_v35_octave_golden.nc",
           DATA / "a15_2dc_hour6_v35_octave_golden.nc")
RAW = DATA / "a15_2dc_hour6_v35_raw_fixture"

#: The raw record's image rows, from the bank tool's ``build_payload``: particle 1 is one
#: slice ``00 00 00 01``; particle 2 is two slices ``00 00 00 03``, ``00 00 00 07``. The
#: header row ahead of each (``rows[1]``/``rows[5]``) is the one ``:786``'s ``start+1``
#: skips -- "2DC has 3 slices between particles".
SLICES = ([(0, 0, 0, 1)], [(0, 0, 0, 3), (0, 0, 0, 7)])
RECORD_OFFSET = 4244 - 4096   # the XML header plus the 20-byte record tag and fields


def _c(rows) -> np.ndarray:
    """``:787`` -- ``[dec2bin(b1,8), ..., dec2bin(b4,8)]``; ``'0'`` is shadowed for 2DC."""
    return np.array([list("".join(format(b, "08b") for b in r)) for r in rows])


def _read(path: Path) -> dict[str, np.ndarray]:
    import netCDF4
    with netCDF4.Dataset(path) as ds:
        ds.set_auto_maskandscale(False)
        return {k: np.asarray(v[:]) for k, v in ds.variables.items()}


@unittest.skipUnless(all(p.is_file() for p in GOLDENS) and RAW.is_file(),
                     "v3.5 Octave reference golden is not distributed with the package; the test "
                     "needs files that are not part of this release")
class TheMeasurementBlockOn2DCGeometry(unittest.TestCase):
    """``measure_record`` against the columns the v3.5 MATLAB wrote."""

    @classmethod
    def setUpClass(cls):
        cls.golden = [_read(p) for p in GOLDENS]
        cls.probe = PROBES_V35["2DC"]
        geom = RecordGeometry(diodesize=cls.probe.ds, diodenum=cls.probe.diodenum,
                              tas_ratio=1.0,     # :711 -- no varargin{3}, iTAS == 0
                              i_new_habit=0, probename="2DC")
        cls.parts = measure_record([_c(s) for s in SLICES], geom,
                                   STOCK_V35_REJECT_CONFIG).particles

    def test_the_images_are_the_ones_in_the_raw_file(self):
        """The port's input is read back out of the tracked raw bytes, not only typed."""
        raw = RAW.read_bytes()
        rows = np.frombuffer(raw[RECORD_OFFSET:], dtype=np.uint8).reshape(1024, 4)
        self.assertEqual([tuple(rows[2])], SLICES[0])
        self.assertEqual([tuple(rows[6]), tuple(rows[7])], SLICES[1])
        self.assertEqual(tuple(rows[1]), (0, 0, 0, 0))    # the slice :786 skips
        self.assertEqual(tuple(rows[5]), (0, 0, 0, 0))

    def test_the_pixel_counts_agree_before_anything_else_is_compared(self):
        ds = self.probe.ds
        for g in self.golden:
            pixels = g["image_area"].ravel() / (ds * ds)
            np.testing.assert_allclose(pixels, [31, 59], rtol=0, atol=1e-9)

    def test_the_port_carries_v35s_2dc_diode_size(self):
        """E2: ``imgProc_sm.m:141`` is ``0.03`` in v3.5. Measured from the file: the
        perimeter of a one-slice, 31-diode particle is 31 diodes."""
        self.assertEqual(self.probe.ds, 0.03)
        self.assertEqual(self.probe.diodenum, 32)
        self.assertEqual(self.probe.probetype, 0)
        for g in self.golden:
            self.assertAlmostEqual(float(g["image_perimeter"].ravel()[0]) / 31, 0.03,
                                   places=15)

    def test_every_measurement_column_is_bit_identical(self):
        ds = self.probe.ds
        for g in self.golden:
            for i, p in enumerate(self.parts):
                te = p.image_touching_edge
                touching = (ord(te) if isinstance(te, str) else int(te)) - ord("0")
                pairs = {                           # the :1336-1400 putVar block, in order
                    "image_length": p.image_length,
                    "image_width": p.image_width,
                    "image_area": p.image_area * ds * ds / 1.0,
                    "image_longest_y": p.longest_y_within_a_slice,
                    "image_max_top_edge_touching": p.max_top_edge_touching,
                    "image_max_bottom_edge_touching": p.max_bottom_edge_touching,
                    "image_touching_edge": touching,
                    "image_auto_reject": ord(p.auto_reject),
                    "image_hollow": p.is_hollow,
                    "image_center_in": p.center_in,
                    "image_axis_ratio": p.axis_ratio,
                    "image_diam_minR": p.minR * ds,
                    "image_diam_AreaR": p.AreaR * ds,
                    "image_perimeter": p.Perimeter * ds,
                    "image_xpos": p.ctx,
                    "image_ypos": p.cty,
                    "percent_shadow_area": _percent_shadow(p),
                    "max_hole_diameter": p.max_hole_diameter,
                    "edge_at_max_hole": p.edge_at_max_hole,
                    "part_z": p.part_z,
                    "size_factor": p.sf,
                    "holroyd_habit": ord(p.holroyd_habit),
                    "fine_detail_ratio": p.FS,
                    "sphericity": p.sphericity,
                    "area_hole_ratio": p.area_hole_ratio,
                }
                for name, got in pairs.items():
                    with self.subTest(particle=i + 1, variable=name):
                        self.assertEqual(float(got), float(g[name].ravel()[i]))

    def test_the_centre_out_override_is_what_makes_both_habits_C(self):
        """``image_center_in`` is 0 for both particles (measured, in the file), so
        ``:1282-1285`` writes ``'C'`` over holroyd.m's answer -- where v3.1.4 wrote ``'l'``
        (108) for the same pixels (``a15_2dc_hour0_octave_golden.nc``). Recorded so that a
        later reading of "habit C in a v3.5 2DC file" is not mistaken for the dead v3.1.4
        ``parabola_fit_center_is_in`` stub: this is the v3.5 centre-out override."""
        for p in self.parts:
            self.assertEqual(p.center_in, 0)
            self.assertEqual(p.holroyd_habit, "C")


@unittest.skipUnless(all(p.is_file() for p in GOLDENS) and RAW.is_file(),
                     "v3.5 Octave reference golden is not distributed with the package; the test "
                     "needs files that are not part of this release")
class TheWholeFilePathForProbetypeZero(unittest.TestCase):
    """**V-PT, 2026-09-16 -- this class used to assert the opposite.**

    Until V-PT, ``imgproc_sm_v35`` refused a 2DC file by name and this test
    asserted that refusal, with the A15 v3.5 measurement resting on the Octave
    golden and the enhancement's replay alone.  Probetype 0 is ported now, so
    the whole-file path can be held to the same golden -- and this pair is a
    *different* fixture, built by a *different* tool
    (``enhancements_uiops/tools/a15_particle_time_bank.py``) from the one
    ``octave_oracle/run_v35_probetype013_bank.py`` built, so the two sides of
    this check come from different places.

    ``particle_time`` is the reason the pair exists: the hour-0 and hour-6
    files differ only in the record header's clock, and A15's int8 saturation
    collapses the hour-6 one to 127.  The port must reproduce both.
    """

    def _run(self, raw: Path, tmp: Path):
        from arrayprobe.readers.pms import read_binary_PMS
        stem = tmp / "dec"
        read_binary_PMS(str(raw), str(stem))
        out = tmp / "port.nc"
        written = imgproc_sm_v35(
            str(stem) + ".2dc.cdf", str(out), "2DC", 1, 1, "TEST",
            iRectEllipse=0, iCalcAllDiodeStats=0, iQC=0, iNewHabit=0,
            reject_config=STOCK_V35_REJECT_CONFIG, tas_time=None, tas=None,
            software="UIOOPS_v3.5", creation_time="2026/09/16 00:00:00")
        return written, _read(out)

    def test_the_port_reproduces_both_a15_goldens(self):
        import tempfile
        raws = (DATA / "a15_2dc_hour0_v35_raw_fixture", RAW)
        for raw, golden in zip(raws, self.__class__._goldens(), strict=True):
            with self.subTest(fixture=raw.name), tempfile.TemporaryDirectory() as tmp:
                written, got = self._run(raw, Path(tmp))
                self.assertEqual(written, 2)
                for name, want in golden.items():
                    if name == "Particle_number_all":
                        continue  # :1329's `&&` never writes it for probetype 0
                    with self.subTest(variable=name):
                        np.testing.assert_allclose(
                            np.asarray(got[name]).astype(float),
                            np.asarray(want).astype(float),
                            rtol=1e-9, equal_nan=True)

    def test_particle_time_saturates_at_hour_six_and_not_at_hour_zero(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            _, hour0 = self._run(DATA / "a15_2dc_hour0_v35_raw_fixture", Path(tmp))
        with tempfile.TemporaryDirectory() as tmp:
            _, hour6 = self._run(RAW, Path(tmp))
        np.testing.assert_array_equal(hour6["particle_time"], [127, 127])   # A15
        self.assertFalse(np.array_equal(hour0["particle_time"],
                                        hour6["particle_time"]))

    @classmethod
    def _goldens(cls):
        return [_read(p) for p in GOLDENS]


class TheRefusalIsNarrowedNotDeleted(unittest.TestCase):
    """Needs no data file, so it runs in the public package."""

    def test_the_refusal_is_narrowed_not_deleted(self):
        """``UnportedProbeType`` must still exist and still be reachable -- it
        is now keyed on the timing branch, not on probetype 2."""
        from arrayprobe_uiops.imgproc import PORTED_TIMINGS_V35
        self.assertTrue(issubclass(UnportedProbeType, Exception))
        self.assertEqual(sorted(PORTED_TIMINGS_V35),
                         ["dmt", "fast2dc", "pms", "spec"])
        self.assertNotIn("2DC", [p for p, v in PROBES_V35.items()
                                 if v.timing not in PORTED_TIMINGS_V35])


if __name__ == "__main__":
    unittest.main()
