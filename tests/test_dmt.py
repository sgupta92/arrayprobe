# SPDX-License-Identifier: BSD-3-Clause
"""``read_binary_DMT.m``, the DMT probes' byte-level RLE raw decoder.

Covers the compression scheme (marker/literal/zero-run/fill-run/no-op),
the boundary search and its unbounded-MATLAB-loop replacement, the
byte-reversed reassembly, and the end-to-end reader against a small
tracked synthetic DMT raw file (``make_dmt_raw_synthetic.py``) compared to the
real ``read_binary_DMT.m`` running under Octave.

Record index 8 (0-based) of that slice is the case that caught a real bug:
an off-by-one at the literal-copy loop's end-of-payload guard made the port
decompress one byte more than MATLAB for any record whose last consumed
run reaches the payload's final byte. See ``dmt.py:_decompress_record``.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from arrayprobe import ncio
from arrayprobe.readers import dmt

DATA = Path(__file__).parent / "data"
RAW_FIXTURE = DATA / "dmt_raw_synthetic.cip"
GOLDEN = DATA / "s6_dmt_synthetic_octave_golden.nc"


def _control_byte(kind: str, count: int) -> int:
    """Build one control byte. ``kind`` in {"literal","zero","fill","noop","marker"}."""
    assert 1 <= count <= 32
    low5 = count - 1
    if kind == "marker":
        return 0x20 | low5
    top2 = {"literal": 0b00, "zero": 0b10, "fill": 0b01, "noop": 0b11}[kind]
    return (top2 << 6) | low5


class DecompressRecordTests(unittest.TestCase):
    """``:99-140`` -- the byte-level RLE scheme, one control kind at a time."""

    def test_literal_run_copies_the_following_bytes(self):
        payload = np.zeros(4096, dtype=np.uint8)
        payload[0] = _control_byte("literal", 3)
        payload[1:4] = [0x11, 0x22, 0x33]
        out = dmt._decompress_record(payload)
        np.testing.assert_array_equal(out[:3], [0x11, 0x22, 0x33])

    def test_zero_run_emits_count_zero_bytes_and_consumes_only_the_control_byte(self):
        payload = np.zeros(4096, dtype=np.uint8)
        payload[0] = _control_byte("zero", 5)
        payload[1] = _control_byte("literal", 1)
        payload[2] = 0xAB
        out = dmt._decompress_record(payload)
        np.testing.assert_array_equal(out[:5], [0] * 5)
        self.assertEqual(int(out[5]), 0xAB)

    def test_fill_run_emits_count_0xff_bytes(self):
        payload = np.zeros(4096, dtype=np.uint8)
        payload[0] = _control_byte("fill", 4)
        out = dmt._decompress_record(payload)
        np.testing.assert_array_equal(out[:4], [0xFF] * 4)

    def test_marker_byte_consumes_only_itself(self):
        # Trailing bytes are no-ops (top2==11, bit5 clear), not zeros -- a
        # zero byte is itself a literal-run control byte (count 1) and would
        # cascade into decoding the rest of the padding as more runs.
        payload = np.full(4096, _control_byte("noop", 1), dtype=np.uint8)
        payload[0] = _control_byte("marker", 7)
        payload[1] = _control_byte("literal", 1)
        payload[2] = 0x55
        out = dmt._decompress_record(payload)
        self.assertEqual(len(out), 1)
        self.assertEqual(int(out[0]), 0x55)

    def test_noop_byte_produces_nothing(self):
        payload = np.full(4096, _control_byte("noop", 1), dtype=np.uint8)
        payload[0] = _control_byte("noop", 1)
        payload[1] = _control_byte("literal", 1)
        payload[2] = 0x77
        out = dmt._decompress_record(payload)
        self.assertEqual(len(out), 1)
        self.assertEqual(int(out[0]), 0x77)

    def test_the_4096th_byte_is_never_read(self):
        """:117 -- MATLAB's ``i < length(bytes)`` guard, strict.

        A literal run whose count would reach the payload's last byte (0-based
        index 4095) must stop one short of it -- the off-by-one this test
        pins was the actual bug found against the Octave oracle.
        """
        payload = np.full(4096, _control_byte("noop", 1), dtype=np.uint8)
        payload[4093] = _control_byte("literal", 5)  # would read 4094..4098
        payload[4094:4096] = [0xAA, 0xBB]
        out = dmt._decompress_record(payload)
        # Only index 4094 is readable; 4095 (the last byte) must not be.
        self.assertEqual(len(out), 1)
        self.assertEqual(int(out[0]), 0xAA)

    def test_a_4095_byte_payload_decodes_with_the_guard_at_its_own_length(self):
        """:117's guard is ``i < length(bytes)``, the payload's own length, while
        :108's bound is the constant 4096 -- so a 4095-byte payload (a file's
        4111-byte tail) decodes, stopping its literal run one short of its end."""
        payload = np.full(4095, _control_byte("noop", 1), dtype=np.uint8)
        payload[4085] = _control_byte("literal", 20)
        out = dmt._decompress_record(payload)
        self.assertEqual(len(out), 8)  # 1-based 4087..4094; 4095 is length(bytes)

    def test_a_payload_shorter_than_4095_bytes_dies_at_109(self):
        """:108's ``while i<4096`` indexes ``b1full(i,:)`` past a short payload."""
        from arrayprobe.matlab_compat import MatlabIndexError
        payload = np.full(200, _control_byte("noop", 1), dtype=np.uint8)
        with self.assertRaisesRegex(MatlabIndexError, r"b1full\(201,:\)"):
            dmt._decompress_record(payload)


class FindBoundaryTests(unittest.TestCase):
    """``:144-160`` -- the first run of eight consecutive sync bytes."""

    def test_finds_the_run_and_returns_one_past_it(self):
        decomp = np.zeros(30, dtype=np.uint8)
        decomp[10:18] = 0xAA
        self.assertEqual(dmt._find_boundary(decomp), 18)

    def test_a_run_of_more_than_eight_still_returns_one_past_the_first_eight(self):
        decomp = np.zeros(30, dtype=np.uint8)
        decomp[5:15] = 0xAA  # ten consecutive
        self.assertEqual(dmt._find_boundary(decomp), 13)

    def test_a_run_shorter_than_eight_does_not_count(self):
        decomp = np.zeros(30, dtype=np.uint8)
        decomp[0:7] = 0xAA
        with self.assertRaises(dmt.DecompressionError):
            dmt._find_boundary(decomp)

    def test_no_run_raises(self):
        """MATLAB's search (:147-160) runs on into the low hex digits and dies."""
        decomp = np.zeros(10, dtype=np.uint8)
        with self.assertRaises(dmt.DecompressionError):
            dmt._find_boundary(decomp)

    def test_any_byte_with_high_digit_a_is_a_sync_byte(self):
        """``decomp(i)=='AA'`` compares one hex digit: 0xA0-0xAF all count."""
        decomp = np.zeros(30, dtype=np.uint8)
        decomp[10:18] = [0xA0, 0xA1, 0xA5, 0xAA, 0xAB, 0xAF, 0xA9, 0xA2]
        self.assertEqual(dmt._find_boundary(decomp), 18)
        with self.assertRaises(dmt.DecompressionError):
            dmt._find_boundary(decomp, exact_sync=True)

    def test_exact_sync_counts_only_0xaa(self):
        decomp = np.zeros(30, dtype=np.uint8)
        decomp[9] = 0xA3  # a sync byte to MATLAB, one before a real sentinel run
        decomp[10:18] = 0xAA
        self.assertEqual(dmt._find_boundary(decomp), 17)
        self.assertEqual(dmt._find_boundary(decomp, exact_sync=True), 18)


class ReassembleTests(unittest.TestCase):
    """``:162-180`` -- 8-byte groups, byte-reversed, padded onto the canvas."""

    def test_group_is_byte_reversed(self):
        decomp = np.tile(np.arange(1, 9, dtype=np.uint8), 8)  # eight groups of 1..8
        canvas = dmt._reassemble(decomp, 0)
        np.testing.assert_array_equal(canvas[0], [8, 7, 6, 5, 4, 3, 2, 1])

    def test_short_record_gets_a_sentinel_row_and_minus_one_padding(self):
        decomp = np.arange(0, 80, dtype=np.uint8)  # ten groups
        canvas = dmt._reassemble(decomp, 0)
        self.assertTrue((canvas[10] == dmt._SENTINEL).all())
        self.assertTrue((canvas[11:] == -1).all())

    def test_fewer_than_eight_groups_dies_at_177(self):
        """``length`` of an n-by-8 matrix is 8, so n < 8 rows go into eight."""
        for n in (0, 1, 7):
            with self.subTest(groups=n), self.assertRaises(dmt.NonconformantAssignmentError):
                dmt._reassemble(np.arange(8 * n, dtype=np.uint8), 0)

    def test_1700_groups_or_more_repeat_the_previous_image(self):
        """``:176`` rewrites the canvas only for a shorter record."""
        previous = np.full((dmt.IMG_BLOCKLEN, dmt.IMG_ROWLEN), 7, dtype=np.int64)
        for n in (dmt.IMG_BLOCKLEN, dmt.IMG_BLOCKLEN + 5):
            with self.subTest(groups=n):
                decomp = np.tile(np.arange(1, 9, dtype=np.uint8), n)
                self.assertIs(dmt._reassemble(decomp, 0, previous), previous)
                first = dmt._reassemble(decomp, 0)  # before any record: zeros(1700,8)
                self.assertTrue((first == 0).all())


class ReadBinaryDMTEndToEndTests(unittest.TestCase):
    """A synthetic raw file through the whole reader and back out of netCDF."""

    def _record(self, header):
        fields = (
            header["year"], header["month"], header["day"], header["hour"],
            header["minute"], header["second"], header["millisec"], header["wkday"],
        )
        head = np.asarray(fields, dtype="<u2").tobytes()
        # No-op filler everywhere except a literal run of eight 0xAA bytes: a
        # raw 0xAA byte in a control-byte position is itself a marker (bit 5
        # set), so the only way to get real 0xAA *data* into the decompressed
        # stream -- the boundary sentinel -- is a literal copy.
        # Then eight groups of data, so the record reassembles (fewer dies, :177).
        payload = np.full(dmt._PAYLOAD_BYTES, _control_byte("noop", 1), dtype=np.uint8)
        payload[0] = _control_byte("literal", 8)
        payload[1:9] = dmt._SENTINEL
        for k in range(2):
            payload[9 + 33 * k] = _control_byte("literal", 32)
            payload[10 + 33 * k : 42 + 33 * k] = np.arange(32) + 32 * k
        return head + payload.tobytes()

    def test_writes_one_record_per_input_record(self):
        import tempfile
        header = dict(year=2016, month=9, day=2, hour=6, minute=6, second=44,
                      millisec=250, wkday=5)
        with tempfile.TemporaryDirectory() as d:
            infile = Path(d) / "t.DMT"
            infile.write_bytes(self._record(header) * 3)
            outfile = Path(d) / "t.cdf"
            count = dmt.read_binary_DMT(str(infile), str(outfile))
            self.assertEqual(count, 3)
            with ncio.open(str(outfile)) as f:
                self.assertEqual(list(f.get_var(f.inq_var_id("second"))), [44, 44, 44])
                self.assertEqual(list(f.get_var(f.inq_var_id("wkday"))), [5, 5, 5])

    def test_a_short_trailing_chunk_is_not_decoded(self):
        import tempfile
        header = dict(year=2016, month=9, day=2, hour=6, minute=6, second=44,
                      millisec=250, wkday=5)
        with tempfile.TemporaryDirectory() as d:
            infile = Path(d) / "t.DMT"
            infile.write_bytes(self._record(header) + b"\x00" * 10)
            outfile = Path(d) / "t.cdf"
            count = dmt.read_binary_DMT(str(infile), str(outfile))
            self.assertEqual(count, 1)


@unittest.skipUnless(RAW_FIXTURE.is_file() and GOLDEN.is_file(),
                     "Tracked DMT oracle fixture is not distributed with the package")
class OctaveOracleEquivalenceTests(unittest.TestCase):
    """The acceptance check: bit-exact against the real MATLAB, run under Octave.

    The raw file is seeded synthetic data and the golden is the Octave decode
    of that same file, so no expected value comes from real data.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = None
        import tempfile
        cls._tmp = tempfile.TemporaryDirectory()
        cls.outfile = str(Path(cls._tmp.name) / "python_out.cdf")
        cls.count = dmt.read_binary_DMT(str(RAW_FIXTURE), cls.outfile)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_record_count_matches(self):
        with ncio.open(str(GOLDEN)) as f:
            n_oracle = f.inq_dim(0)[1]
        self.assertEqual(self.count, n_oracle)

    def test_every_variable_is_bit_exact(self):
        with ncio.open(self.outfile) as fa, ncio.open(str(GOLDEN)) as fb:
            for name, _ in dmt._TIME_VARS:
                a = fa.get_var(fa.inq_var_id(name))
                b = fb.get_var(fb.inq_var_id(name))
                np.testing.assert_array_equal(a, b, err_msg=name)
        import netCDF4
        with netCDF4.Dataset(self.outfile) as da, netCDF4.Dataset(str(GOLDEN)) as db:
            np.testing.assert_array_equal(da.variables["data"][:], db.variables["data"][:])

# _release_fixture_guard: real-data derived fixtures are excluded from the release
import pathlib as _rfg_pathlib  # noqa: E402
import unittest as _rfg_unittest  # noqa: E402

_RFG_EXCLUDED = ('s6_dmt_synthetic_octave_golden.nc', 'dmt_raw_synthetic.cip')
if not all((_rfg_pathlib.Path(__file__).resolve().parent / "data" / _n).exists()
           for _n in _RFG_EXCLUDED):
    raise _rfg_unittest.SkipTest(
        "real-data derived fixtures (UIOPS PECAN DMT / minimal-example 2D-S samples) "
        "are not shipped in the release")

if __name__ == "__main__":
    unittest.main()
