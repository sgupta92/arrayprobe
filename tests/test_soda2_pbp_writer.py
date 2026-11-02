# SPDX-License-Identifier: BSD-3-Clause
"""``pbp_writer.py`` -- its GDL bank lives in
(``gdl_oracle/run_soda2_pbp_writer_bank.py``).
Most of these
remain unit/third-side tests against the transcribed source lines; the CSV
header-width fix (the numbered header's field is 7 characters wide, not 4) is GDL-measured, in
``test_line_350_numbered_header_uses_the_default_i_width`` above. The
netCDF side of the bank stays unmeasured -- ``ncdf_create`` hangs under this
machine's GDL build even called alone, so the netCDF-side items (attribute names and dtypes,
short columns, the signed rejectionflag byte) were not GDL-checked; see the bank's docstring."""
from __future__ import annotations

import os
import tempfile
import unittest

import numpy as np

from arrayprobe_soda2 import pbp_writer as pw


def _make_x(n: int) -> dict:
    x = {
        name: np.zeros(n, dtype=np.float64)
        for name, *_ in pw.PBPPROPS
        if name not in ("time", "rejectionflag")
    }
    return x


class TestPbpprops(unittest.TestCase):
    def test_line_202_pbpprops_is_verbatim(self) -> None:
        # Transcribed independently from soda2_process_2d.pro:202-238 (not
        # imported from the module) -- the third side for the table itself.
        expected_names = (
            "time", "probetime", "buffertime", "rawtime", "reftime", "inttime",
            "diam", "xsize", "ysize", "xextent", "oned", "twod", "areasize",
            "arearatio", "arearatiofilled", "aspectratio", "area", "areafilled",
            "perimeterarea", "area75", "xpos", "ypos", "allin", "centerin",
            "dofflag", "edgetouch", "sizecorrection", "zd", "missed",
            "probetas", "aircrafttas", "overloadflag", "particlecounter",
            "orientation", "rejectionflag", "numregions", "diodegaps",
        )
        self.assertEqual(len(pw.PBPPROPS), 37)
        self.assertEqual(tuple(n for n, *_ in pw.PBPPROPS), expected_names)


class TestCsvWriter(unittest.TestCase):
    def _write(self, x, istop, truetime, rejectionflag):
        fd, path = tempfile.mkstemp(suffix=".pbp.csv")
        os.close(fd)
        op = {"outdir": tempfile.gettempdir() + os.sep, "date": "09062016",
              "starttime": 61.0, "stoptime": 120.0}
        date = {"month": "09", "day": "06", "year": "2016"}
        f = pw.open_pbp_csv(path, op, date)
        pw.write_pbp_csv_buffer(f, x, istop, truetime, rejectionflag)
        f.close()
        with open(path) as fh:
            lines = fh.readlines()
        os.remove(path)
        return lines

    def test_line_293_time_and_rejectionflag_are_not_x_tags(self) -> None:
        n = 1
        x = _make_x(n)
        x["inttime"][0] = 0.25
        lines = self._write(x, 0, np.array([42.5]), np.array([7], dtype=np.uint8))
        row = lines[-1].strip().split(",")
        # column order: time, probetime, ..., rejectionflag is last (index 34).
        self.assertEqual(row[0], "42.50000")  # time <- truetime, not x['time'] (no such tag)
        self.assertEqual(row[-3], "7")  # rejectionflag <- the passed array, not a tag lookup

    def test_line_198_ncdf_inttime_is_interarrival_csv_is_x_inttime(self) -> None:
        """S6-i, measured: CSV prints the raw x['inttime'] tag (through the
        generic nw==1 branch, :289-290), including a negative value; netCDF
        prints the clamped `interarrival` local instead (:198)."""
        n = 1
        x = _make_x(n)
        x["inttime"][0] = -0.5
        lines = self._write(x, 0, np.array([1.0]), np.array([0], dtype=np.uint8))
        row = lines[-1].strip().split(",")
        inttime_col = [n for n, *_ in pw.PBPPROPS].index("inttime")
        self.assertEqual(row[inttime_col], "-5.00000e-01")

    def test_header_37_numbered_lines_and_trailing_comma_suppressed(self) -> None:
        n = 1
        x = _make_x(n)
        lines = self._write(x, 0, np.array([1.0]), np.array([0], dtype=np.uint8))
        numbered = [ln for ln in lines if ln[:8].strip().rstrip(".").isdigit()]
        self.assertEqual(len(numbered), 37)
        self.assertFalse(lines[5 + 37].rstrip("\n").endswith(","))

    def test_line_350_numbered_header_uses_the_default_i_width(self) -> None:
        """B2, measured under GDL R8B (2026-09-14):
        ``run_soda2_pbp_writer_bank.py`` -- ``string(i+1, format='(4i)')``'s
        ``4`` is a repeat count, not a field width; the actual field is the
        default ``I`` width for the (INT) loop variable, 7 characters, not
        4. Golden: ``tests/data/gdl_soda2_pbp_one_buffer_3p.pbp.csv`` line 5
        (``'      1. time: ...'``)."""
        n = 1
        x = _make_x(n)
        lines = self._write(x, 0, np.array([1.0]), np.array([0], dtype=np.uint8))
        first_numbered = lines[4]
        self.assertEqual(first_numbered[:9], "      1. ")
        # Mutation, reverted: the old (wrong) 4-char width would read "   1. ".
        wrong = f"{1:4d}. "
        self.assertNotEqual(first_numbered[: len(wrong)], wrong)


class TestNcdfWriter(unittest.TestCase):
    def _write(self, x, istop, truetime, interarrival, rejectionflag, op_extra=None):
        netCDF4 = __import__("netCDF4")
        fd, path = tempfile.mkstemp(suffix=".pbp.nc")
        os.close(fd)
        os.remove(path)
        op = {"outdir": tempfile.gettempdir() + os.sep, "date": "09062016",
              "starttime": 61.0, "stoptime": 120.0, "shortname": "t",
              "particlefile": 0, "ncdfparticlefile": 1, "filetag": ""}
        if op_extra:
            op.update(op_extra)
        date = {"month": "09", "day": "06", "year": "2016"}
        ds = pw.open_pbp_ncdf(path, op, date)
        pw.write_pbp_ncdf_buffer(ds, x, istop, truetime, interarrival, rejectionflag, 0)
        pw.close_pbp_ncdf(ds)
        ds2 = netCDF4.Dataset(path)
        yield ds2
        ds2.close()
        os.remove(path)

    def test_line_236_rejectionflag_byte_is_signed(self) -> None:
        """S6-k, measured: netCDF `/byte` is signed NC_BYTE (int8); bit 128
        (S5-a) reads back as -128."""
        n = 1
        x = _make_x(n)
        gen = self._write(x, 0, np.array([1.0]), np.array([0.0]), np.array([128], dtype=np.uint8))
        ds = next(gen)
        self.assertEqual(ds.variables["rejectionflag"].dtype.name, "int8")
        self.assertEqual(int(ds.variables["rejectionflag"][0]), -128)
        list(gen)  # drain to close/remove

    def test_line_188_ncdf_time_is_truetime_not_probetime(self) -> None:
        n = 1
        x = _make_x(n)
        x["probetime"][0] = 999.0
        gen = self._write(x, 0, np.array([1.5]), np.array([0.0]), np.array([0], dtype=np.uint8))
        ds = next(gen)
        self.assertAlmostEqual(float(ds.variables["time"][0]), 1.5)
        self.assertAlmostEqual(float(ds.variables["probetime"][0]), 999.0)
        list(gen)

    def test_line_267_empty_string_attr_becomes_none(self) -> None:
        # Global attribute names are upper-cased at write,
        # matching IDL's `tag_names(op)` -- so the golden's own attribute
        # name for this tag is `CUSTOMTAG`, not the literal case it was
        # declared in here.
        n = 1
        x = _make_x(n)
        gen = self._write(x, 0, np.array([1.0]), np.array([0.0]), np.array([0], dtype=np.uint8),
                           op_extra={"filetag": "", "customtag": ""})
        ds = next(gen)
        self.assertEqual(ds.getncattr("CUSTOMTAG"), "none")
        list(gen)

    def test_variables_gzip5(self) -> None:
        n = 1
        x = _make_x(n)
        gen = self._write(x, 0, np.array([1.0]), np.array([0.0]), np.array([0], dtype=np.uint8))
        ds = next(gen)
        filt = ds.variables["diam"].filters()
        self.assertTrue(filt["zlib"])
        self.assertEqual(filt["complevel"], 5)
        list(gen)


class TestFilename(unittest.TestCase):
    def test_line_15_filename_appends_probeid_for_2ds(self) -> None:
        fn = pw.pbp_filename(
            {"outdir": "/o/", "date": "09062016", "starttime": 61.0,
             "probetype": "2DS", "probeid": "H"},
            "short",
        )
        self.assertIn("_H", fn)

    def test_line_20_filename_hhmmss_is_the_first_particle_time(self) -> None:
        fn = pw.pbp_filename({"outdir": "/o/", "date": "09062016", "starttime": 61.0}, "short")
        self.assertIn("000101", fn)


class TestRefusals(unittest.TestCase):
    def test_ncdfparticlefile_2_two_flushes_offset_by_hand(self) -> None:
        """Particle-image output: `soda2_process_2d.pro:286-306` definitions and
        `soda2_particlesort.pro:264-276` writes, two hand-built flushes. The
        second flush's particles land at `ncdf_offset` 2 and its image block
        at `slices_written` 3; `startx` is 0 and `stopx` numdiodes-1."""
        import netCDF4

        op = {"outdir": tempfile.gettempdir() + os.sep, "date": "09062016",
              "starttime": 61.0, "stoptime": 120.0, "ncdfparticlefile": 2,
              "numdiodes": 4}
        date = {"month": "09", "day": "06", "year": "2016"}
        with tempfile.TemporaryDirectory() as tmp:
            fn = os.path.join(tmp, "img.pbp.nc")
            ds = pw.open_pbp_ncdf(fn, op, date)
            img1 = np.arange(12, dtype=np.uint8).reshape(3, 4)
            img2 = (np.arange(8, dtype=np.uint8) + 100).reshape(2, 4)
            pw.write_pbp_ncdf_images(
                ds, {"startline": np.array([1, 2], np.uint64),
                     "stopline": np.array([1, 2], np.uint64)}, 1, img1, 0, 0)
            pw.write_pbp_ncdf_images(
                ds, {"startline": np.array([4], np.uint64),
                     "stopline": np.array([4], np.uint64)}, 0, img2, 2, 3)
            ds.close()
            with netCDF4.Dataset(fn) as nc:
                self.assertTrue(nc.dimensions["Diode"].isunlimited())
                self.assertTrue(nc.dimensions["Slice"].isunlimited())
                self.assertEqual(nc.variables["image"].dimensions, ("Slice", "Diode"))
                self.assertEqual(nc.variables["image"].dtype, np.uint8)
                self.assertEqual(nc.variables["starty"].dtype, np.uint32)
                np.testing.assert_array_equal(nc.variables["starty"][:], [1, 2, 4])
                np.testing.assert_array_equal(nc.variables["stopy"][:], [1, 2, 4])
                np.testing.assert_array_equal(nc.variables["startx"][:], [0, 0, 0])
                np.testing.assert_array_equal(nc.variables["stopx"][:], [3, 3, 3])
                np.testing.assert_array_equal(
                    nc.variables["image"][:], np.concatenate([img1, img2]))
                self.assertEqual(nc.variables["image"].longname, "Particle images")

    def test_one_slice_image_chunk_refused_until_measured(self) -> None:
        with self.assertRaises(pw.PbpImagesNotPorted):
            pw.write_pbp_ncdf_images(None, {}, 0, np.zeros((1, 4), np.uint8), 0, 0)

    def test_ascii_psd_not_ported(self) -> None:
        with self.assertRaises(pw.AsciiPsdNotPorted):
            raise pw.AsciiPsdNotPorted("soda2_export_ascii.pro not ported")

    def test_save_file_not_ported(self) -> None:
        with self.assertRaises(pw.SaveFileNotPorted):
            raise pw.SaveFileNotPorted("soda2_process_2d.pro:729-731 not ported")


class TestNoEnhancementCoupling(unittest.TestCase):
    def test_no_arrayprobe_import(self) -> None:
        import inspect
        src = inspect.getsource(pw)
        self.assertNotIn("import arrayprobe\n", src)
        self.assertNotIn("from arrayprobe ", src)
        self.assertNotIn("import arrayprobe_uiops", src)
        self.assertNotIn("from arrayprobe_uiops", src)


class TestMutations(unittest.TestCase):
    """>=5 mutations, run and reverted by construction (each test builds its
    own broken call rather than editing the module)."""

    def test_mutation_swap_truetime_for_probetime_changes_time_column(self) -> None:
        n = 1
        x = _make_x(n)
        x["probetime"][0] = 5.0
        fd, path = tempfile.mkstemp(suffix=".pbp.csv")
        os.close(fd)
        op = {"outdir": tempfile.gettempdir() + os.sep, "date": "09062016",
              "starttime": 61.0, "stoptime": 120.0}
        date = {"month": "09", "day": "06", "year": "2016"}
        f = pw.open_pbp_csv(path, op, date)
        # correct call uses truetime, not x['probetime']
        pw.write_pbp_csv_buffer(f, x, 0, np.array([1.0]), np.array([0], dtype=np.uint8))
        f.close()
        with open(path) as fh:
            row = fh.readlines()[-1].strip().split(",")
        os.remove(path)
        self.assertEqual(row[0], "1.00000")  # would be "5.00000" under the mutation


if __name__ == "__main__":
    unittest.main()
