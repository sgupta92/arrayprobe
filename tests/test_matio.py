# SPDX-License-Identifier: BSD-3-Clause
"""The Level 5 MAT-file reader, against Octave and against known contents.

``arrayprobe.matio`` exists so the port can read the ``diode.*.mat`` stuck-diode
masks without making SciPy a runtime dependency (see the module docstring for
that trade).  It is a hand-rolled binary parser, which is exactly the kind of
code that passes its own tests and is still wrong, so it is checked three ways:

1. **Against fixtures whose contents are stated here as literals**, not derived
   from the reader.
2. **Against real MATLAB-written files** -- the 2017 GLNXA64 ORACLES masks --
   whenever ``old-stuff-data/`` is present.  Those exercise the container
   MATLAB actually emits: one ``miCOMPRESSED`` element per variable, unpadded,
   with char data in ``miUINT16``.  Their expected values are literals here too,
   taken from Octave's own ``load``.
3. **Against Octave**, indirectly but bindingly: the fixtures below are written
   by ``octave_oracle/run_s3o_bank.py``'s writer, and the S3o oracle bank only
   produces its goldens because Octave's ``load`` accepted those same files and
   re-illuminated the diodes they name.  A writer bug would have shown up as a
   changed golden, not as a green test here.

The two layout rules that were established by *failing* rather than by reading
the specification are pinned in :class:`MatFileLayoutTest`, because both are
easy to reintroduce and neither produces an obvious symptom.
"""

from __future__ import annotations

import struct
import unittest
import zlib
from pathlib import Path

import numpy as np

from arrayprobe.matio import MatFileError, UnsupportedMatFeature, loadmat

DATA = Path(__file__).parent / "data"
FIXTURE = DATA / "shadow_diode_fixture.mat"
EMPTY_FIXTURE = DATA / "shadow_diode_empty_fixture.mat"

#: The tracked fixture's nine diodes: seeded synthetic, written by
#: ``scripts/validation/octave/run_s3o_bank.write_mask_mat`` from
#: ``numpy.random.default_rng(20260915).choice(np.arange(1, 129), 9, replace=False)``
#: sorted.  Not taken from any campaign mask.
SYNTHETIC_DIODES = [24, 66, 67, 73, 83, 90, 112, 119, 125]

#: Real MATLAB output, gitignored.  Values below are Octave's reading of them.
REFERENCE = Path(__file__).parents[1] / "arrayprobe-local-data" / "old-stuff-data" / "diode_masks"
REAL_MASKS = {
    "diode.160906064403.combined.mat": (
        [8, 24, 28, 36, 67, 69, 73, 94, 96],
        "Tue Oct 31 21:09:47 2017",
    ),
    "diode.160906064403.corrected.mat": (
        [60, 66, 98],
        "Wed Nov  1 08:58:34 2017",
    ),
}


class MatFileReadTest(unittest.TestCase):
    def test_reads_the_tracked_fixture(self):
        m = loadmat(FIXTURE)
        self.assertEqual(m["date"], "151205")
        self.assertEqual(m["time"], "000000")
        np.testing.assert_array_equal(
            m["shadow_diode"].ravel(),
            np.array(SYNTHETIC_DIODES, dtype=np.float64),
        )

    def test_shape_is_matlab_s(self):
        # find_shadow_diodes.m:95 does `shadow_diode = sort(diode)` on a column
        # from find(), so the variable is Nx1, not 1xN.  Keeping the shape means
        # a caller that reshapes is doing so deliberately.
        self.assertEqual(loadmat(FIXTURE)["shadow_diode"].shape, (9, 1))

    def test_double_class_survives_int_storage(self):
        # MATLAB stores a double array in the narrowest integer type that fits,
        # so these nine synthetic diode numbers go out as miINT8/miUINT8. They must
        # still come back float64: an int8 mask would wrap silently at 127, and
        # a 128-diode probe reaches 128.
        self.assertEqual(loadmat(FIXTURE)["shadow_diode"].dtype, np.float64)

    def test_empty_mask_reads_as_empty(self):
        # The case that actually occurred for every 09/06/2016 2D-S file.
        m = loadmat(EMPTY_FIXTURE)
        self.assertEqual(m["shadow_diode"].size, 0)

    def test_header_is_preserved(self):
        self.assertIn("MATLAB 5.0 MAT-file", loadmat(FIXTURE).header)

    def test_membership_and_keys(self):
        m = loadmat(FIXTURE)
        self.assertIn("shadow_diode", m)
        self.assertNotIn("nope", m)
        self.assertEqual(set(m.keys()), {"date", "time", "shadow_diode"})


class MatFileLayoutTest(unittest.TestCase):
    """The two container rules that bite, pinned so they cannot be un-learned."""

    def test_compressed_elements_are_not_padded(self):
        # Every Level 5 element is padded to an eight-byte boundary EXCEPT
        # miCOMPRESSED.  Pad it and the next tag is read two bytes out of
        # alignment; the reader then sees a type of 0 and either stops early or
        # invents a variable.  Build a file with the wrong padding and require
        # that it does not silently yield the right answer.
        good = FIXTURE.read_bytes()
        head, rest = good[:128], good[128:]
        mi_type, nbytes = struct.unpack("<II", rest[:8])
        self.assertEqual(mi_type, 15, "fixture should use the compressed container")
        padded = head + rest[:8 + nbytes] + b"\x00" * 4 + rest[8 + nbytes:]
        broken = DATA / "_tmp_padded.mat"
        broken.write_bytes(padded)
        try:
            got = loadmat(broken)
            self.assertNotEqual(
                set(got.keys()), {"date", "time", "shadow_diode"},
                "a mis-padded compressed element parsed as if it were correct, "
                "so the padding rule is not actually being enforced",
            )
        except MatFileError:
            pass
        finally:
            broken.unlink()

    def test_one_compressed_element_per_variable(self):
        # This is how MATLAB -v7 lays a `save` out, and it is what Octave's
        # `load` will accept: three variables means three back-to-back
        # miCOMPRESSED elements, not one wrapping the lot.
        raw = FIXTURE.read_bytes()[128:]
        pos = 0
        seen = 0
        while pos + 8 <= len(raw):
            mi_type, nbytes = struct.unpack("<II", raw[pos:pos + 8])
            if mi_type == 0:
                break
            self.assertEqual(mi_type, 15)
            seen += 1
            pos += 8 + nbytes
        self.assertEqual(seen, 3, "expected one compressed element per variable")


class MatFileRejectionTest(unittest.TestCase):
    """What the reader refuses, and why refusing beats guessing."""

    def test_v73_is_named_rather_than_mangled(self):
        p = DATA / "_tmp_v73.mat"
        p.write_bytes(b"\x89HDF\r\n\x1a\n" + b"\x00" * 200)
        try:
            with self.assertRaises(UnsupportedMatFeature) as cm:
                loadmat(p)
            self.assertIn("v7.3", str(cm.exception))
        finally:
            p.unlink()

    def test_short_file_is_rejected(self):
        p = DATA / "_tmp_short.mat"
        p.write_bytes(b"too short")
        try:
            with self.assertRaises(MatFileError):
                loadmat(p)
        finally:
            p.unlink()

    def test_bad_endian_tag_is_rejected(self):
        p = DATA / "_tmp_bad.mat"
        p.write_bytes(b"x" * 126 + b"ZZ")
        try:
            with self.assertRaises(MatFileError):
                loadmat(p)
        finally:
            p.unlink()

    def test_struct_is_refused_not_guessed(self):
        # A struct would be the natural thing for someone to hand this reader
        # next.  Refusing by name beats returning a plausible-looking array.
        flags = struct.pack("<II", 2, 0)          # mxSTRUCT_CLASS

        def element(t, payload):
            pad = (-len(payload)) % 8
            return struct.pack("<II", t, len(payload)) + payload + b"\x00" * pad

        body = (element(6, flags) + element(5, struct.pack("<2i", 1, 1))
                + element(1, b"s"))
        matrix = element(14, body)
        head = (b"MATLAB 5.0 MAT-file".ljust(116, b" ") + b"\x00" * 8
                + struct.pack("<H", 0x0100) + b"IM")
        comp = zlib.compress(matrix)
        p = DATA / "_tmp_struct.mat"
        p.write_bytes(head + struct.pack("<II", 15, len(comp)) + comp)
        try:
            with self.assertRaises(UnsupportedMatFeature) as cm:
                loadmat(p)
            self.assertIn("struct", str(cm.exception))
        finally:
            p.unlink()


@unittest.skipUnless(
    REFERENCE.is_dir(), "needs reference data not distributed with the package"
)
class RealMatlabFileTest(unittest.TestCase):
    """Against files MATLAB itself wrote, on Linux, in 2017.

    The fixtures above are written by this repo's own writer, so on their own
    they could only prove the writer and reader agree.  These are the files of
    record, and their expected contents are Octave's reading of them.
    """

    def test_reads_the_real_oracles_masks(self):
        for name, (diodes, created) in REAL_MASKS.items():
            path = REFERENCE / name
            if not path.is_file():
                self.skipTest(f"{name} is not distributed with the package")
            with self.subTest(mask=name):
                m = loadmat(path)
                np.testing.assert_array_equal(
                    m["shadow_diode"].ravel(),
                    np.array(diodes, dtype=np.float64),
                )
                self.assertEqual(m["date"], "160906")
                self.assertEqual(m["time"], "064403")
                self.assertIn("GLNXA64", m.header)
                self.assertIn(created, m.header)


if __name__ == "__main__":
    unittest.main()
