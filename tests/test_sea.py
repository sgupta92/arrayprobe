# SPDX-License-Identifier: BSD-3-Clause
"""``read_binary_SEA.m``, the SEA (CIP/2DC) tagged-container raw reader.

Covers the 16-byte directory-record navigation (including the doubled
peek-and-rewind reads that make a naive byte-count transliteration desync
after the first real CIP record -- the actual bug this test suite exists to
pin), the shared DMT-style RLE decompression, SEA's own graceful
no-boundary-found handling (unlike DMT's crash), the off-by-one padding
quirk that overwrites the last real row, and the genuine MATLAB crash on
any 5000/4096-tagged record (``varid91`` is never assigned).

The Octave-oracle test runs the real, unmodified MATLAB (via a documented
Octave-only shim for one unrelated package strictness issue -- see
``octave_oracle/shims/+netcdf/endDef.m``) over the tracked synthetic
``tests/data/sea_raw_synthetic.sea`` (``make_sea_raw_synthetic.py``), built by
``scripts/validation/octave/run_s6_sea_bank.py --synthetic``.
"""

from __future__ import annotations

import struct
import unittest
from pathlib import Path

import numpy as np

from arrayprobe import ncio
from arrayprobe.readers import sea

DATA = Path(__file__).parent / "data"
RAW_FIXTURE = DATA / "sea_raw_synthetic.sea"
GOLDEN_CIP = DATA / "s6_sea_synthetic_octave_golden.cip.nc"
GOLDEN_2DC = DATA / "s6_sea_synthetic_octave_golden.2dc.nc"


def _dir_record(tag, offset=0, nbytes=0, samples=0, bps=0, typ=0, p1=0, p2=0, p3=0, addr=0):
    return struct.pack("<5H4BH", tag, offset, nbytes, samples, bps, typ, p1, p2, p3, addr)


class ReadDirTests(unittest.TestCase):
    def test_reads_all_ten_fields_little_endian(self):
        raw = _dir_record(33000, 84, 4098, 1, 4098, 78, 1, 2, 3, 29442)
        with_extra = raw + b"\x00" * 8
        import io
        got = sea._read_dir(io.BytesIO(with_extra))
        self.assertEqual(got, (33000, 84, 4098, 1, 4098, 78, 1, 2, 3, 29442))

    def test_short_read_returns_none(self):
        import io
        self.assertIsNone(sea._read_dir(io.BytesIO(b"\x00" * 10)))


class ReadTimeTests(unittest.TestCase):
    def test_keeps_only_the_second_group(self):
        import io
        group1 = struct.pack("<9H", 1, 1, 1, 1, 1, 1, 1, 1, 1)
        group2 = struct.pack("<9H", 2016, 9, 6, 6, 40, 17, 500, 3, 7)
        got = sea._read_time(io.BytesIO(group1 + group2))
        self.assertEqual(got, (2016, 9, 6, 6, 40, 17, 500, 3, 7))


class DecompressionReuseTests(unittest.TestCase):
    """SEA's image payload uses DMT's exact algorithm -- reused, not copied."""

    def test_sea_module_imports_dmts_decompressor(self):
        from arrayprobe.readers.dmt import _decompress_record
        self.assertIs(sea._decompress_record, _decompress_record)


class BoundarySearchTests(unittest.TestCase):
    """``:157-180`` -- graceful fallback, unlike DMT's crash on no boundary."""

    def test_finds_the_run_and_returns_one_past_it(self):
        decomp = np.zeros(30, dtype=np.uint8)
        decomp[10:18] = 0xAA
        self.assertEqual(sea._find_boundary_or_none(decomp), 18)

    def test_no_run_returns_none_not_an_exception(self):
        decomp = np.zeros(10, dtype=np.uint8)
        self.assertIsNone(sea._find_boundary_or_none(decomp))


def _matlab_sync_byte_predicate(decomp: np.ndarray) -> np.ndarray:
    """A byte-for-byte mirror of ``read_binary_SEA.m:161``'s ACTUAL predicate, kept independent
    of ``arrayprobe.readers.sea`` so the tests below compare the port against it rather than
    against itself. The port adopted it as its default on 2026-09-28, with the exact-``0xAA``
    rule as the opt-in ``exact_sync``.

    ``:161`` reads ``if decomp(i)=='AA'``, where MATLAB's ``decomp`` is an N-by-2 **char** array of
    hex-digit pairs (one row per byte, built at ``:134``/``:143``/``:149``). For a linear index
    ``i <= N``, ``decomp(i)`` is a single character -- the byte's HIGH hex digit -- and MATLAB
    scalar-expands ``'A' == 'AA'`` to ``[1 1]``, which ``if`` takes as true. So the predicate fires
    for every byte whose high nibble is ``0xA``: sixteen values, ``0xA0``..``0xAF``, not the single
    byte ``0xAA`` the port's opt-in ``exact_sync`` tests.

    Measured under Octave 11.3.0 against ``read_binary_SEA.m`` directly, not inferred from reading
    it: an Octave script (September 2026) enumerates all 256 byte
    values and reports exactly this set (``test_the_accepted_byte_set_matches_the_octave_
    measurement`` below pins the two against each other, so this mirror cannot quietly drift from
    what was actually measured).
    """
    return (decomp.astype(np.uint8) & 0xF0) == 0xA0


def _find_boundary_or_none_matlab_rule(decomp: np.ndarray) -> int | None:
    """The same eight-in-a-row search ``sea._find_boundary_or_none`` runs (``:157-180``), over
    :func:`_matlab_sync_byte_predicate` instead of the port's exact-``0xAA`` test -- independent of
    ``arrayprobe.readers.sea`` by construction, so it cannot accidentally exercise the port's own
    code under a different name."""
    accepted = _matlab_sync_byte_predicate(decomp)
    if len(accepted) >= 8:
        window = np.convolve(accepted.astype(np.int64), np.ones(8, dtype=np.int64), mode="valid")
        hit = np.flatnonzero(window == 8)
        if hit.size:
            return int(hit[0]) + 8
    return None


class DiscriminatingSyncByteFixtureTests(unittest.TestCase):
    """Closes the coverage hole the September 2026 SEA sync-rule review (its item 4)
    names: neither ``OctaveOracleEquivalenceTests`` below (an eleven-record, early-flight prefix --
    every record in sync, so no record where the two rules pick a different grid origin is in it)
    nor ``BoundarySearchTests.test_finds_the_run_and_returns_one_past_it`` (built from ``0xAA``
    bytes only, so it passes under either rule) can see the sync-byte divergence: the
    port was *stricter* than the MATLAB it ports (``decomp == 0xAA`` exactly, against MATLAB's
    real 16-of-256-value test above) until 2026-09-28, when MATLAB's rule became the default.
    Measured on the real 2016-09-06 CIP flight
    (``sea_syncrule.py`` / ``sea_syncrule.json``): 78 of 23,939 records (0.33%) take a different
    grid origin under the two rules. This fixture is a constructed minimal case of that same
    disagreement -- not one of those 78 records, which would need the held-out raw ``.sea`` file
    and Octave to extract (out of scope here; see the report handed back with this change)."""

    def test_a_run_of_0xAF_bytes_disagrees_between_the_two_rules(self):
        """0xAF: high nibble 0xA (MATLAB's real test fires), but not the literal byte 0xAA --
        the exact shape of sea_aa_semantics.m's own probe. The port follows MATLAB by default
        (2026-09-28); the exact-byte rule is the opt-in ``exact_sync``."""
        decomp = np.zeros(30, dtype=np.uint8)
        decomp[10:18] = 0xAF
        self.assertIsNone(
            sea._find_boundary_or_none(decomp, exact_sync=True),
            "the opt-in exact rule must not lock onto a run of 0xAF")
        self.assertEqual(
            _find_boundary_or_none_matlab_rule(decomp), 18,
            "MATLAB's actual rule locks at the same offset a genuine 0xAA run would (compare "
            "BoundarySearchTests.test_finds_the_run_and_returns_one_past_it) -- the two "
            "predicates disagree on this record, the sync-byte divergence neither test sees")
        self.assertEqual(sea._find_boundary_or_none(decomp), 18,
                         "the default rule is MATLAB's, measured under Octave")

    def test_a_pure_0xAA_run_is_the_non_discriminating_control(self):
        """Why BoundarySearchTests's own fixture could not have caught this: both rules agree on
        a genuine 0xAA run, so it discriminates nothing between them."""
        decomp = np.zeros(30, dtype=np.uint8)
        decomp[10:18] = 0xAA
        self.assertEqual(sea._find_boundary_or_none(decomp), 18)
        self.assertEqual(sea._find_boundary_or_none(decomp, exact_sync=True), 18)
        self.assertEqual(_find_boundary_or_none_matlab_rule(decomp), 18)

    def test_the_accepted_byte_set_matches_the_octave_measurement(self):
        """Pinned against the measurement itself (sea_aa_semantics.m: 'Bytes accepted as a sync
        byte by decomp(i)==''AA'': 16 of 256 -- A0 A1 A2 ... AE AF'), not re-derived from reading
        read_binary_SEA.m a second time -- if this mirror and the measured set ever disagreed, the
        two tests above would be exercising the wrong rule without anything failing to say so."""
        accepted = {v for v in range(256)
                   if _matlab_sync_byte_predicate(np.array([v], dtype=np.uint8))[0]}
        self.assertEqual(accepted, set(range(0xA0, 0xB0)))


class ReassembleSeaTests(unittest.TestCase):
    """``:183-200`` -- byte-reversed groups, and the last-real-row-overwritten pad."""

    def test_group_is_byte_reversed(self):
        # Two groups: with only one, the last-real-row-overwrite quirk below
        # would immediately erase the very row this test checks.
        decomp = np.arange(1, 17, dtype=np.uint8)
        canvas = sea._reassemble_sea(decomp, 0)
        np.testing.assert_array_equal(canvas[0], [8, 7, 6, 5, 4, 3, 2, 1])

    def test_short_record_overwrites_the_last_real_row_too(self):
        """Unlike DMT: MATLAB's ``L:1700`` (inclusive) pad starts one row early."""
        decomp = np.arange(1, 81, dtype=np.uint8)  # ten groups
        canvas = sea._reassemble_sea(decomp, 0)
        self.assertTrue((canvas[:9] != -1).all())  # the first nine real rows survive
        self.assertTrue((canvas[9:] == -1).all())  # the tenth is overwritten, and on

    def test_below_eight_groups_every_row_survives_and_zeros_fill_to_seven(self):
        """``length`` of an n-by-8 matrix is 8, so the pad starts at row 8 whatever n < 8 is;
        MATLAB grows the matrix to reach it with zeros (Octave-measured,
        tests/test_reader_edge_octave.py::SeaAgainstOctave)."""
        decomp = np.arange(1, 25, dtype=np.uint8)  # three groups
        canvas = sea._reassemble_sea(decomp, 0)
        self.assertTrue((canvas[:3] > 0).all())
        self.assertTrue((canvas[3:7] == 0).all())
        self.assertTrue((canvas[7:] == -1).all())

    def test_exactly_1700_groups_leaves_every_row_real(self):
        decomp = np.tile(np.arange(1, 9, dtype=np.uint8), sea._IMG_BLOCKLEN)
        canvas = sea._reassemble_sea(decomp, 0)
        self.assertFalse((canvas == -1).any())


class ReadBinarySeaEndToEndTests(unittest.TestCase):
    """Synthetic files, checking the crash-fidelity and weird-record paths."""

    def _dir(self, **kw):
        return _dir_record(**kw)

    def test_a_5000_4096_tagged_record_raises(self):
        import tempfile
        # The outer loop's own first read must not be tag 999, or nTagNext
        # starts true and the inner loop -- which is what actually checks
        # for 5000/4096 -- never runs at all.
        body = self._dir(tag=0, offset=0) + self._dir(tag=5000, nbytes=4096)
        with tempfile.TemporaryDirectory() as d:
            infile = Path(d) / "t.sea"
            infile.write_bytes(body)
            with self.assertRaises(sea.SeaUndefinedVariableError):
                sea.read_binary_SEA(str(infile), str(Path(d) / "out"))

    def test_an_unrecognized_tag_is_walked_past_without_error(self):
        import tempfile
        body = (
            self._dir(tag=0, offset=0)       # outer's own read: not 999
            + self._dir(tag=12345, nbytes=77)  # inner's first read: unrecognized
            + self._dir(tag=999, offset=0)     # inner's second read: terminates it
        )
        with tempfile.TemporaryDirectory() as d:
            infile = Path(d) / "t.sea"
            infile.write_bytes(body)
            counts = sea.read_binary_SEA(str(infile), str(Path(d) / "out"))
        self.assertEqual(counts, (0, 0, 0))

    def test_an_all_no_op_record_raises_where_matlab_dies_at_161(self):
        import tempfile
        # A CIP-tagged record whose payload decompresses to nothing at all: `decomp` is
        # never assigned, :280 cleared the last one, and MATLAB dies at :161 (measured under
        # Octave 11.3, 2026-09-27). Until then this test asserted a quiet "weird" count.
        noop = 0xC0  # top2==11, bit5 clear: a no-op control byte
        payload = bytes([noop]) * 4098
        # The rewind after the CIP branch's peek leaves the file positioned
        # to re-read starting at the "time" block's own first 16 bytes (see
        # the module docstring) -- so those 16 bytes are crafted here to
        # double as a tag-999 directory record, cleanly terminating the
        # inner loop on the very next read instead of drifting into garbage.
        time_block = self._dir(tag=999, offset=0) + b"\x00" * 20
        body = (
            self._dir(tag=0, offset=0)          # outer's own read: not 999
            + self._dir(tag=33000, nbytes=4098)   # inner's first read: CIP
            + self._dir(tag=0, offset=0)            # the peeked-then-rewound record
            + time_block                             # readTime's 36 bytes (peeked)
            + payload                                # the 4098-byte payload (peeked)
            # After :286 the outer loop resumes at the 20 zero bytes and walks
            # the payload as directory records; 4118 bytes leave a 6-byte
            # tail. Pad it to a whole record and end on a tag-999, or the
            # inner loop hits EOF mid-record, where MATLAB dies at :90.
            + b"\xc0" * 10 + self._dir(tag=999, offset=0)
        )
        with tempfile.TemporaryDirectory() as d:
            infile = Path(d) / "t.sea"
            infile.write_bytes(body)
            with self.assertRaises(sea.SeaUndefinedVariableError) as cm:
                sea.read_binary_SEA(str(infile), str(Path(d) / "out"))
        self.assertIn(":161", str(cm.exception))

    def test_a_record_with_no_boundary_counts_as_weird_as_octave_does(self):
        """The tracked CIP fixture with its second record replaced by a stream that decodes to
        four bytes and no 0xAA run: Octave 11.3 writes 8 CIP records and prints
        nWierdTotal = 1, and the port's CIP data matched Octave's bit for bit (2026-09-27)."""
        import tempfile
        seed = bytearray((DATA / "soda2_sea_cip_fixture.sea").read_bytes())
        # Offset 4462 is the second CIP record's payload, located by the reader itself.
        seed[4462:4462 + 4096] = bytes([0x03]) + bytes([0x11] * 4) + bytes([0x20]) * 4091
        with tempfile.TemporaryDirectory() as d:
            infile = Path(d) / "nb.sea"
            infile.write_bytes(bytes(seed))
            counts = sea.read_binary_SEA(str(infile), str(Path(d) / "out"))
        self.assertEqual(counts, (8, 1, 0))


class OctaveOracleEquivalenceTests(unittest.TestCase):
    """Bit-exact against the real MATLAB, run under Octave over a synthetic SEA file.

    Built by ``scripts/validation/octave/run_s6_sea_bank.py --synthetic`` from
    ``tests/data/sea_raw_synthetic.sea``: clean CIP image records only, no 2DC and
    no 5000/4096-tagged record, so the crash path is not exercised here -- see
    ``ReadBinarySeaEndToEndTests`` for that.

    **Does not cover the ``0xAA`` vs. ``0xA0``-``0xAF`` sync-byte divergence** (upstream
    defect): every record in the synthetic file is in sync, so no record where the
    port's rule and MATLAB's own rule pick a different grid origin is here -- that gap is real
    (measured 0.33% of a real flight's records) and is guarded instead by the constructed fixture
    in ``DiscriminatingSyncByteFixtureTests`` below, which needs no raw data or Octave to run.
    """

    @classmethod
    def setUpClass(cls):
        import tempfile
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out_base = str(Path(cls._tmp.name) / "python_out")
        cls.counts = sea.read_binary_SEA(str(RAW_FIXTURE), cls.out_base)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_counts_match_the_octave_golden(self):
        """CIP and 2DC counts are the record dimensions of the files Octave wrote.

        The weird-record count is not stored in either file; the generator writes
        clean records only and the Octave run printed ``nWierdTotal = 0``.
        """
        import netCDF4
        with netCDF4.Dataset(str(GOLDEN_CIP)) as dc, netCDF4.Dataset(str(GOLDEN_2DC)) as dd:
            expected = (dc.variables["data"].shape[0], 0, dd.variables["data"].shape[0])
        self.assertGreater(expected[0], 0)
        self.assertEqual(self.counts, expected)

    def _assert_file_bit_exact(self, suffix, golden):
        with ncio.open(self.out_base + suffix) as fa, ncio.open(str(golden)) as fb:
            for name in ("year", "month", "day", "hour", "minute", "second",
                         "millisec", "wkday"):
                a = fa.get_var(fa.inq_var_id(name))
                b = fb.get_var(fb.inq_var_id(name))
                np.testing.assert_array_equal(a, b, err_msg=f"{suffix}:{name}")
        import netCDF4
        with netCDF4.Dataset(self.out_base + suffix) as da, netCDF4.Dataset(str(golden)) as db:
            np.testing.assert_array_equal(
                da.variables["data"][:], db.variables["data"][:], err_msg=f"{suffix}:data"
            )

    def test_cip_file_is_bit_exact(self):
        self._assert_file_bit_exact(".CIP.cdf", GOLDEN_CIP)

    def test_2dc_file_is_bit_exact(self):
        self._assert_file_bit_exact(".2DC.cdf", GOLDEN_2DC)


EDGE_GOLDEN = DATA / "s6_sea_edge_octave_golden.npz"
EDGE_SEED = DATA / "soda2_sea_cip_fixture.sea"


def _edge_bank():
    import importlib.util
    path = Path(__file__).resolve().parents[1] / "scripts" / "validation" / "octave" / "run_s6_sea_bank.py"  # noqa: E501
    spec = importlib.util.spec_from_file_location("run_s6_sea_bank", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@unittest.skipUnless(EDGE_GOLDEN.is_file() and EDGE_SEED.is_file(),
                     "Tracked SEA edge-case Octave reference golden is not distributed with the "
                     "package")
class OctaveEdgeCaseTests(unittest.TestCase):
    """Malformed-input behaviour against the unmodified ``read_binary_SEA.m``
    under Octave 8.4 (``octave_oracle/run_s6_sea_bank.py --edge-cases``).

    F1: where MATLAB dies at ``:110`` on a short payload, the port raises.
    F2: where ``:285``'s ``fseek`` targets a byte outside the file, MATLAB's
    ``fseek`` returns -1 and stays put, and so does the port. Before this,
    the port raised ``OSError`` (before BOF) or seeked past EOF and returned
    zero records (past EOF); both F2 inputs are built so that staying put is
    what reaches the fixture's nine CIP records.
    """

    @classmethod
    def setUpClass(cls):
        cls.golden = np.load(EDGE_GOLDEN)
        cls.bank = _edge_bank()
        cls.seed = cls.bank.edge_seed()

    def _write(self, d, case):
        import hashlib
        body = self.bank.edge_case_bytes(case, self.seed)
        self.assertEqual(hashlib.sha256(body).hexdigest(),
                         str(self.golden[f"{case}__sha256"]),
                         f"{case}: rebuilt input differs from the one Octave ran")
        infile = Path(d) / f"{case}.sea"
        infile.write_bytes(body)
        return infile

    def test_f1_short_payload_raises_where_matlab_dies_at_110(self):
        import tempfile

        from arrayprobe.matlab_compat import MatlabIndexError
        case = "f1_short_payload"
        self.assertEqual(int(self.golden[f"{case}__exit"]), 1)
        self.assertIn("read_binary_SEA at line 110", str(self.golden[f"{case}__error"]))
        with tempfile.TemporaryDirectory() as d:
            infile = self._write(d, case)
            with self.assertRaisesRegex(MatlabIndexError, r"read_binary_SEA\.m:110"):
                sea.read_binary_SEA(str(infile), str(Path(d) / "out"))

    def _assert_matches_octave(self, case):
        import tempfile

        import netCDF4
        self.assertEqual(int(self.golden[f"{case}__exit"]), 0)
        with tempfile.TemporaryDirectory() as d:
            infile = self._write(d, case)
            out = str(Path(d) / "out")
            counts = sea.read_binary_SEA(str(infile), out)
            with netCDF4.Dataset(out + ".CIP.cdf") as ds:
                for v in self.bank._CIP_VARS:
                    np.testing.assert_array_equal(
                        np.asarray(ds.variables[v][:]), self.golden[f"{case}__{v}"],
                        err_msg=f"{case}:{v}")
        self.assertEqual(counts, (9, 0, 0))

    def test_f2_seek_before_bof_stays_put_like_matlab_fseek(self):
        self._assert_matches_octave("f2_seek_before_bof")

    def test_f2_seek_past_eof_stays_put_like_matlab_fseek(self):
        self._assert_matches_octave("f2_seek_past_eof")

    def _assert_dies_like_octave(self, case, line):
        import tempfile

        from arrayprobe.matlab_compat import MatlabIndexError
        self.assertEqual(int(self.golden[f"{case}__exit"]), 1)
        self.assertIn(f"read_binary_SEA at line {line} ", str(self.golden[f"{case}__error"]))
        with tempfile.TemporaryDirectory() as d:
            infile = self._write(d, case)
            with self.assertRaisesRegex(MatlabIndexError, rf"read_binary_SEA\.m:{line}:"):
                sea.read_binary_SEA(str(infile), str(Path(d) / "out"))

    # An end of file inside the inner directory loop. The port used to
    # set endfile and return quietly; MATLAB has no guard and dies.
    def test_f5_eof_at_a_record_boundary_raises_where_matlab_dies_at_90(self):
        self._assert_dies_like_octave("f5_eof_at_dir_boundary", 90)

    def test_f5_eof_mid_record_raises_where_matlab_dies_at_90(self):
        self._assert_dies_like_octave("f5_eof_mid_dir", 90)

    def test_f5_eof_after_a_cip_record_raises_where_matlab_dies_at_97(self):
        self._assert_dies_like_octave("f5_eof_after_cip_dir", 97)

    def test_f5_eof_before_a_999_offset_raises_where_matlab_dies_at_283(self):
        self._assert_dies_like_octave("f5_eof_mid_999_offset_read", 283)

    def test_f5_eof_after_a_999_offset_finishes_like_matlab(self):
        import tempfile

        import netCDF4
        case = "f5_eof_mid_999_after_offset"
        self.assertEqual(int(self.golden[f"{case}__exit"]), 0)
        with tempfile.TemporaryDirectory() as d:
            infile = self._write(d, case)
            out = str(Path(d) / "out")
            counts = sea.read_binary_SEA(str(infile), out)
            with netCDF4.Dataset(out + ".CIP.cdf") as ds:
                for v in self.bank._CIP_VARS:
                    np.testing.assert_array_equal(
                        np.asarray(ds.variables[v][:]), self.golden[f"{case}__{v}"],
                        err_msg=f"{case}:{v}")
        self.assertEqual(counts, (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
