# SPDX-License-Identifier: BSD-3-Clause
"""``read_binary_PMS.m``, the NCAR-OAP raw reader for 2DC/F2DC/2DP.

Covers the XML-header skip, the plain (non-reversed) column-major image
reshape, and -- the reason this module has the most upstream-facing value
of the raw readers -- the `'C6'` file-handle bug: a tag meant for the F2DC
output writes its scalar fields into the 2DC file instead, at the F2DC
write-counter's index, which can silently collide with an unrelated 2DC
record's own data. See ``arrayprobe_uiops/readers/pms.py``'s module docstring for
the full mechanism, traced by following every ``netcdf.putVar`` call's file
handle against its variable id rather than by reading the branch's own
(misleading) comment.

The Octave-oracle test runs the real, unmodified MATLAB over a small
synthetic file built by ``octave_oracle/run_s6_pms_bank.py`` -- no real PMS
campaign file exists on this machine, but the doctrine only requires the
MATLAB itself to be runnable, which it is (no MEX, no toolbox).
"""

from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np

from arrayprobe import ncio
from arrayprobe.readers import pms

DATA = Path(__file__).parent / "data"
RAW_FIXTURE = DATA / "s6_pms_raw_fixture"
GOLDEN_2DC = DATA / "s6_pms_octave_golden.2dc.nc"
GOLDEN_F2DC = DATA / "s6_pms_octave_golden.f2dc.nc"
GOLDEN_2DP = DATA / "s6_pms_octave_golden.2dp.nc"


def _record(tag, hour, minute, second, year, month, day, tas, millisec, wkday, fill_start=1):
    out = bytes(tag) + struct.pack(">9H", hour, minute, second, year, month, day,
                                    tas, millisec, wkday)
    data = np.zeros(4096, dtype=np.uint8)
    pattern = np.arange(fill_start, fill_start + 16, dtype=np.uint8)
    data[: len(pattern)] = pattern
    out += data.tobytes()
    return out


def _raw_file(path, records, header=b'<?xml version="1.0"?>\n<OAP>\n</OAP>\n'):
    with open(path, "wb") as fh:
        fh.write(header)
        for r in records:
            fh.write(r)


class ReshapeTests(unittest.TestCase):
    """The plain column-major reshape -- no byte reversal, unlike DMT."""

    def test_matches_matlab_column_major_by_hand(self):
        data = np.arange(6, dtype=np.uint8)  # a,b,c,d,e,f
        got = pms._reshape_matlab(data, 2)
        # MATLAB reshape([a b c d e f], 2, 3) = [[a c e],[b d f]] (2x3)
        np.testing.assert_array_equal(got, [[0, 2, 4], [1, 3, 5]])

    def test_shape_is_n_by_4096_over_n(self):
        data = np.zeros(4096, dtype=np.uint8)
        self.assertEqual(pms._reshape_matlab(data, 4).shape, (4, 1024))
        self.assertEqual(pms._reshape_matlab(data, 8).shape, (8, 512))


class SkipXmlHeaderTests(unittest.TestCase):
    def test_stops_exactly_after_the_closing_tag(self):
        import io
        body = b'<?xml version="1.0"?>\n<OAP>\n<probe>x</probe>\n</OAP>\nREST'
        fh = io.BytesIO(body)
        pms._skip_xml_header(fh)
        self.assertEqual(fh.read(), b"REST")

    def test_whitespace_around_the_closing_tag_still_matches(self):
        import io
        fh = io.BytesIO(b"<OAP>\n  </OAP>  \nDATA")
        pms._skip_xml_header(fh)
        self.assertEqual(fh.read(), b"DATA")

    def test_missing_terminator_raises(self):
        import io
        fh = io.BytesIO(b"<OAP>\nno closing tag here\n")
        with self.assertRaises(ValueError):
            pms._skip_xml_header(fh)


class ReadBinaryPMSEndToEndTests(unittest.TestCase):
    """Synthetic files through the whole reader, checking routing and counts."""

    def test_each_tag_routes_to_its_own_file_and_counter(self):
        records = [
            _record((67, 49), 6, 6, 1, 2016, 9, 2, 100, 0, 5),  # 2DC
            _record((80, 1), 6, 6, 2, 2016, 9, 2, 100, 0, 5),   # 2DP
            _record((67, 52), 6, 6, 3, 2016, 9, 2, 100, 0, 5),  # F2DC 'C4'
        ]
        with tempfile.TemporaryDirectory() as d:
            infile = Path(d) / "t.PMS"
            _raw_file(infile, records)
            out = str(Path(d) / "out")
            counts = pms.read_binary_PMS(infile, out)
        self.assertEqual(counts, (1, 0, 1, 1))  # (2dc, f2dc_c6, f2dc_c4, 2dp)

    def test_c6_scalars_land_in_the_2dc_file_not_f2dc(self):
        """The bug this module exists to document, on a minimal fixture."""
        records = [_record((67, 54), 6, 6, 45, 2016, 9, 2, 171, 260, 5)]
        with tempfile.TemporaryDirectory() as d:
            infile = Path(d) / "t.PMS"
            _raw_file(infile, records)
            out = str(Path(d) / "out")
            counts = pms.read_binary_PMS(infile, out)
            self.assertEqual(counts, (0, 1, 0, 0))
            with ncio.open(out + ".2dc.cdf") as f:
                second = np.asarray(f.get_var(f.inq_var_id("second"))).reshape(-1)
                tas = np.asarray(f.get_var(f.inq_var_id("tas"))).reshape(-1)
                self.assertEqual(int(second[0]), 45)
                self.assertEqual(float(tas[0]), 171.0)
            with ncio.open(out + ".f2dc.cdf") as f:
                # The scalar variable exists but was never written for this
                # index -- it reads back as the netCDF fill value, not 45.
                second = np.asarray(f.get_var(f.inq_var_id("second"))).reshape(-1)
                self.assertNotEqual(int(second[0]), 45)

    def test_a_short_trailing_record_is_not_decoded(self):
        records = [_record((67, 49), 6, 6, 1, 2016, 9, 2, 100, 0, 5)]
        with tempfile.TemporaryDirectory() as d:
            infile = Path(d) / "t.PMS"
            _raw_file(infile, records)
            with open(infile, "ab") as fh:
                fh.write(b"\x00" * 10)  # a short, undecodable trailing chunk
            out = str(Path(d) / "out")
            counts = pms.read_binary_PMS(infile, out)
        self.assertEqual(counts, (1, 0, 0, 0))


@unittest.skipUnless(
    RAW_FIXTURE.is_file() and GOLDEN_2DC.is_file() and GOLDEN_F2DC.is_file()
    and GOLDEN_2DP.is_file(),
    "Tracked PMS oracle fixture is not distributed with the package",
)
class OctaveOracleEquivalenceTests(unittest.TestCase):
    """Bit-exact against the real MATLAB, run under Octave over a synthetic file.

    Built by ``octave_oracle/run_s6_pms_bank.py``: five records chosen to
    exercise both write-counter collisions the source contains (see that
    script's and ``pms.py``'s docstrings for the exact mechanism each one
    exercises).
    """

    @classmethod
    def setUpClass(cls):
        import tempfile
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out_base = str(Path(cls._tmp.name) / "python_out")
        cls.counts = pms.read_binary_PMS(str(RAW_FIXTURE), cls.out_base)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_counts_match_the_fixtures_design(self):
        # 2 real 2DC records, one 'C6', one 'C4', one 2DP -- see the bank
        # script's docstring for why these five records were chosen.
        self.assertEqual(self.counts, (2, 1, 1, 1))

    def _assert_file_bit_exact(self, suffix, golden):
        with ncio.open(self.out_base + suffix) as fa, ncio.open(str(golden)) as fb:
            for name in ("year", "month", "day", "hour", "minute", "second",
                         "millisec", "wkday", "tas"):
                a = fa.get_var(fa.inq_var_id(name))
                b = fb.get_var(fb.inq_var_id(name))
                np.testing.assert_array_equal(a, b, err_msg=f"{suffix}:{name}")
        import netCDF4
        with netCDF4.Dataset(self.out_base + suffix) as da, netCDF4.Dataset(str(golden)) as db:
            np.testing.assert_array_equal(
                da.variables["data"][:], db.variables["data"][:], err_msg=f"{suffix}:data"
            )

    def test_2dc_file_is_bit_exact(self):
        self._assert_file_bit_exact(".2dc.cdf", GOLDEN_2DC)

    def test_f2dc_file_is_bit_exact(self):
        self._assert_file_bit_exact(".f2dc.cdf", GOLDEN_F2DC)

    def test_2dp_file_is_bit_exact(self):
        self._assert_file_bit_exact(".2dp.cdf", GOLDEN_2DP)


class SkipsTwoDsRecordsTests(unittest.TestCase):
    """``read_binary_PMS`` knows the tags 'C1', 'C6', 'C4' and 'P*' only: a 2D-S record
    (tag ``SH``) is dropped without a message, so it cannot decode an OAP export
    of 2D-S images (``arrayprobe_uiops.oap_read`` exists for that). Pins the gap;
    not a fix."""

    def test_sh_file_yields_no_records_in_any_output(self):
        sync = (5).to_bytes(8, "little") + (0xAAAAAA0000000000).to_bytes(8, "little")
        image = bytes([0xFF] * 15 + [0xDF])  # one shaded diode, 1 = clear
        stream = (image + sync).ljust(4096, bytes(1))
        record = struct.pack(">2s9H", b"SH", 12, 34, 56, 2016, 9, 6, 150, 250, 0) + stream
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "s.2d"
            src.write_bytes(b'<OAP version="1">' + b"\n</OAP>\n" + record * 3)
            counts = pms.read_binary_PMS(str(src), str(Path(tmp) / "out"))
        self.assertEqual(counts, (0, 0, 0, 0))


if __name__ == "__main__":
    unittest.main()
