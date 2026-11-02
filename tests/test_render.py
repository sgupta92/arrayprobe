# SPDX-License-Identifier: BSD-3-Clause
"""Track V -- particle visualisation. Covers the one piece that must be
exactly right (the reconstruction, ``imgProc_sm.m:266-268`` transcribed) on a
small hand-built image+proc pair, plus smoke tests for the three rendering
avenues (single particle, contact sheet, HTML gallery) confirming they run
and produce the expected artifact, not that a rendered PNG looks a
particular way -- that check is visual, by design (see the plan's
"Enhancement track V": a validation lane a human can *look at*).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

try:
    import matplotlib
    matplotlib.use("Agg")  # headless, no display needed for tests
    HAVE_MPL = True
except ImportError:  # pragma: no cover
    HAVE_MPL = False

try:
    import netCDF4
except ImportError:  # pragma: no cover
    netCDF4 = None

from arrayprobe import ncio

if HAVE_MPL:
    from arrayprobe import render


def _make_image_file(path, blocks):
    """A minimal ``.H.cdf``-shaped file: ``blocks`` is a list of (1700, 8)
    uint16 arrays, one per record.
    """
    f = ncio.create(str(path), "clobber")
    dim_time = f.def_dim("time", ncio.NC_UNLIMITED)
    dim_row = f.def_dim("ImgRowlen", 8)
    dim_block = f.def_dim("ImgBlocklen", 1700)
    varid = f.def_var("data", "int", [dim_row, dim_block, dim_time])
    f.end_def()
    stacked = np.stack(blocks).astype(np.int64)  # (n, 1700, 8), on-disk order
    ncio.write_record_block(f, varid, 0, stacked)
    f.close()


def _make_proc_file(path, particles):
    """A minimal ``proc.*.nc``-shaped file with just the variables
    ``render.py`` reads. ``particles`` is a list of dicts with keys
    parent_rec_num, start, end, width, length, reject, habit, diam.
    """
    f = ncio.create(str(path), "clobber")
    dim_time = f.def_dim("time", ncio.NC_UNLIMITED)
    dim_pos = f.def_dim("pos_count", 2)
    v_pos = f.def_var("position", "double", [dim_pos, dim_time])
    v_prn = f.def_var("parent_rec_num", "double", dim_time)
    v_pnum = f.def_var("particle_num", "double", dim_time)
    v_width = f.def_var("image_width", "double", dim_time)
    v_length = f.def_var("image_length", "double", dim_time)
    v_reject = f.def_var("image_auto_reject", "double", dim_time)
    v_habit = f.def_var("holroyd_habit", "double", dim_time)
    v_diam = f.def_var("image_diam_minR", "double", dim_time)
    f.end_def()
    pos = np.array([[p["start"] for p in particles], [p["end"] for p in particles]],
                   dtype=np.float64)
    f.put_var(v_pos, pos)
    f.put_var(v_prn, np.array([p["parent_rec_num"] for p in particles], dtype=np.float64))
    f.put_var(v_pnum, np.array([p.get("particle_num", i + 1) for i, p in enumerate(particles)],
                               dtype=np.float64))
    f.put_var(v_width, np.array([p["width"] for p in particles], dtype=np.float64))
    f.put_var(v_length, np.array([p["length"] for p in particles], dtype=np.float64))
    f.put_var(v_reject, np.array([ord(p.get("reject", "0")) for p in particles], dtype=np.float64))
    f.put_var(v_habit, np.array([ord(p.get("habit", "a")) for p in particles], dtype=np.float64))
    f.put_var(v_diam, np.array([p.get("diam", 1.0) for p in particles], dtype=np.float64))
    f.close()


@unittest.skipUnless(HAVE_MPL and netCDF4 is not None, "matplotlib/netCDF4 not installed")
class ReconstructParticleImageTests(unittest.TestCase):
    """The one part that has to be exactly right: ``ind_matrix = 65535 -
    data(start:j-1,:)`` then ``dec2bin_concat``, transcribed from
    ``imgProc_sm.m:266-268``.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    # Raw diode-word convention, confirmed against real flight data before
    # writing these: 65535 - data == 0 decodes to all '0' chars, and '0' is
    # SHADOWED (per the module docstring) -- so a raw word of 65535 is a
    # fully SHADOWED slice, and 0 is fully LIT. Backwards from the naive
    # "65535 = all bits set = all lit" reading; caught these tests failing
    # against a hand-built fixture, not against the real data (which already
    # rendered correctly), so this was a fixture bug, not a render.py one.

    def test_all_lit_word_reconstructs_to_all_unshadowed(self):
        block = np.zeros((1700, 8), dtype=np.uint16)  # every diode lit
        img = self.dir / "img.cdf"
        proc = self.dir / "proc.nc"
        _make_image_file(img, [block])
        _make_proc_file(proc, [{"parent_rec_num": 1, "start": 1, "end": 5,
                                "width": 1, "length": 5}])
        with netCDF4.Dataset(str(img)) as ids, netCDF4.Dataset(str(proc)) as pds:
            c = render.reconstruct_particle_image(ids, pds, 0)
        self.assertEqual(c.shape, (5, 128))  # 8 words * 16 bits
        self.assertFalse(c.any(), "an all-lit record must decode to zero shadowed pixels")

    def test_a_saturated_word_reconstructs_to_all_shadowed(self):
        block = np.zeros((1700, 8), dtype=np.uint16)
        block[2, :] = 65535  # one fully-shadowed slice inside the selected range
        img = self.dir / "img.cdf"
        proc = self.dir / "proc.nc"
        _make_image_file(img, [block])
        _make_proc_file(proc, [{"parent_rec_num": 1, "start": 1, "end": 5,
                                "width": 1, "length": 5}])
        with netCDF4.Dataset(str(img)) as ids, netCDF4.Dataset(str(proc)) as pds:
            c = render.reconstruct_particle_image(ids, pds, 0)
        # start=1,end=5 (1-based) -> Python rows 0..4 of the block; block row 2
        # (0-based) lands at c[2].
        self.assertTrue(c[2, :].all())
        self.assertFalse(c[0, :].any())

    def test_position_selects_the_right_1based_inclusive_range(self):
        block = np.zeros((1700, 8), dtype=np.uint16)
        block[9, :] = 65535  # 0-based row 9 == MATLAB 1-based slice 10
        img = self.dir / "img.cdf"
        proc = self.dir / "proc.nc"
        _make_image_file(img, [block])
        # start=8, end=12 (1-based inclusive) must include slice 10
        _make_proc_file(proc, [{"parent_rec_num": 1, "start": 8, "end": 12,
                                "width": 1, "length": 5}])
        with netCDF4.Dataset(str(img)) as ids, netCDF4.Dataset(str(proc)) as pds:
            c = render.reconstruct_particle_image(ids, pds, 0)
        self.assertEqual(c.shape, (5, 128))
        # 1-based slice 10 is the 3rd row (index 2) of the 8:12 selection
        self.assertTrue(c[2, :].all())

    def test_second_record_is_selected_by_parent_rec_num(self):
        block0 = np.zeros((1700, 8), dtype=np.uint16)
        block1 = np.zeros((1700, 8), dtype=np.uint16)
        block1[0, :] = 65535
        img = self.dir / "img.cdf"
        proc = self.dir / "proc.nc"
        _make_image_file(img, [block0, block1])
        _make_proc_file(proc, [{"parent_rec_num": 2, "start": 1, "end": 3,
                                "width": 1, "length": 3}])
        with netCDF4.Dataset(str(img)) as ids, netCDF4.Dataset(str(proc)) as pds:
            c = render.reconstruct_particle_image(ids, pds, 0)
        self.assertTrue(c[0, :].all(), "must read record index 1 (parent_rec_num=2), not 0")


@unittest.skipUnless(HAVE_MPL and netCDF4 is not None, "matplotlib/netCDF4 not installed")
class TestReconstructOffset(unittest.TestCase):
    """``reconstruct_particle_image`` never applied ``cfg.image_slice_offset``
    on the read side, though ``imgproc.py:893`` applies it on the write side
    (``slice_start = start - 1 + cfg.image_slice_offset``). For 2D-S/HVPS the
    offset is 0 and the bug was invisible; for 2DC/2DP it is 1
    (``imgProc_sm.m:555``), so the old formula prepended one extra row -- a
    header/timing slice ``imgProc_sm.m`` never put in the particle.

    Oracle: ``tests/data/s7c_2dc_octave_{decoded,golden}.nc``, the real
    Octave run of unmodified ``imgProc_sm.m`` on a hand-built synthetic 2DC
    file (``test_imgproc_s7c_2dc_oracle.py``). Known ``position`` there is
    ``[[2, 3], [6, 8]]`` and ``SliceCount`` is ``[1, 2]`` -- both read
    straight from the golden, not asserted from memory.

    2DC/2DP stay outside :data:`render.DRAWABLE_PROBES` (only two synthetic
    particles are checked here, not a real campaign file), so this test
    reaches the real, unmodified :func:`render.reconstruct_particle_image` --
    same code path a drawable probe uses -- by patching ``DRAWABLE_PROBES``
    just long enough to get past its gate. ``cfg`` inside the function still
    comes from :data:`arrayprobe.constants.IMGPROC_CONFIG` for probe
    ``"2DC"`` -- no second table, no literal ``1``.
    """

    DATA = Path(__file__).parent / "data"
    INPUT = DATA / "s7c_2dc_octave_decoded.nc"
    GOLDEN = DATA / "s7c_2dc_octave_golden.nc"

    @unittest.skipUnless(INPUT.is_file() and GOLDEN.is_file(),
                         "2DC Octave reference fixtures are not distributed with the package")
    def test_2dc_particle_rows_match_the_octave_oracle(self):
        import unittest.mock as mock

        from arrayprobe.constants import IMGPROC_CONFIG

        cfg = IMGPROC_CONFIG["2DC"]
        self.assertEqual(cfg.image_slice_offset, 1)  # the defect this guards

        with netCDF4.Dataset(str(self.INPUT)) as ids, netCDF4.Dataset(str(self.GOLDEN)) as pds:
            position = np.asarray(pds.variables["position"][:]).astype(int)
            slicecount = np.asarray(pds.variables["SliceCount"][:]).astype(int)
            self.assertEqual(position.tolist(), [[2, 3], [6, 8]])  # read, not assumed
            self.assertEqual(slicecount.tolist(), [1, 2])

            for i in range(2):
                # Only the DRAWABLE_PROBES gate is bypassed here; the
                # reconstruction itself is whatever reconstruct_particle_image
                # actually does -- so this fails pre-fix, on the real bug,
                # not on a test-only stand-in.
                with mock.patch.object(render, "DRAWABLE_PROBES",
                                       render.DRAWABLE_PROBES + ("2DC",)):
                    c = render.reconstruct_particle_image(ids, pds, i, probe="2DC")
                # imgProc_sm.m:575 stores position=[start, j-1] BEFORE the
                # offset; imgProc_sm.m:555 builds the particle from
                # data(start+1:j-1,:). Oracle-confirmed 0-based row indices
                # (independent of render.py, straight from the MATLAB
                # source and the raw decoded file):
                oracle_rows = {0: [2], 1: [6, 7]}[i]
                block = ids.variables["data"][0, :, :]
                expected_raw = block[oracle_rows, :]
                expected_c = render.dec2bin_concat(expected_raw, cfg.image_word_bits) == ord("0")
                self.assertEqual(c.shape[0], slicecount[i],
                                  f"particle {i}: row count must match the real "
                                  f"Octave-produced SliceCount, not a guess")
                np.testing.assert_array_equal(
                    c, expected_c,
                    f"particle {i}: reconstructed rows do not match the rows "
                    f"imgProc_sm.m:555 actually built the particle from")


@unittest.skipUnless(HAVE_MPL and netCDF4 is not None, "matplotlib/netCDF4 not installed")
class TestOffsetIsNoopFor2DS(unittest.TestCase):
    """``image_slice_offset`` is 0 for 2D-S/HVPS, so the fix must not move a
    single pixel of an existing rendered image. Direct comparison against the
    pre-fix formula (``start - 1`` alone), not an assumption.
    """

    def test_2ds_reconstruction_is_byte_identical_to_the_pre_fix_formula(self):
        rng = np.random.default_rng(0)
        block = rng.integers(0, 65536, size=(1700, 8), dtype=np.uint64).astype(np.uint16)
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            img_path, proc_path = d / "img.cdf", d / "proc.nc"
            _make_image_file(img_path, [block])
            _make_proc_file(proc_path, [{"parent_rec_num": 1, "start": 8, "end": 40,
                                         "width": 1, "length": 33}])
            with netCDF4.Dataset(str(img_path)) as ids, netCDF4.Dataset(str(proc_path)) as pds:
                from arrayprobe.constants import IMGPROC_CONFIG
                cfg = IMGPROC_CONFIG["2DS"]
                self.assertEqual(cfg.image_slice_offset, 0)
                c_new = render.reconstruct_particle_image(ids, pds, 0, probe="2DS")
                # The pre-fix formula, inlined here rather than reintroduced
                # into render.py: block[start-1:end,:], offset never added.
                start, end = 8, 40
                pre_fix_raw = np.asarray(ids.variables["data"][0, :, :])[start - 1:end, :]
                pre_fix_ind = 65535 - pre_fix_raw if cfg.image_invert else pre_fix_raw
                c_pre_fix = render.dec2bin_concat(pre_fix_ind, cfg.image_word_bits) == ord("0")
                np.testing.assert_array_equal(c_new, c_pre_fix)


@unittest.skipUnless(HAVE_MPL and netCDF4 is not None, "matplotlib/netCDF4 not installed")
class ProbeFramingTests(unittest.TestCase):
    """``probe=`` takes the framing ``imgproc`` uses (``constants.IMGPROC_CONFIG``).
    Until 2026-09-15 every image was drawn as a 2D-S, and a CIP came back an
    inverted 128-column picture (VA1); the CIP triage queues could not open."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        d = Path(self._tmp.name)
        block = np.full((1700, 8), 255, dtype=np.uint16)   # CIP: 8-bit words, 1 = lit
        block[0, 0] = 0b01111111                           # slice 1: diode 1 shadowed
        block[1, 7] = 0b11111110                           # slice 2: diode 64 shadowed
        self.img, self.proc = d / "c.CIP.cdf", d / "proc.c.CIP.nc"
        _make_image_file(self.img, [block])
        _make_proc_file(self.proc, [{"parent_rec_num": 1, "start": 1, "end": 2,
                                     "width": 64, "length": 2}])

    def test_a_cip_image_is_64_diodes_as_stored(self):
        with netCDF4.Dataset(self.img) as i, netCDF4.Dataset(self.proc) as p:
            c = render.reconstruct_particle_image(i, p, 0, probe="CIP")
        self.assertEqual(c.shape, (2, 64))
        self.assertEqual(np.argwhere(c).tolist(), [[0, 0], [1, 63]])

    def test_the_default_is_the_2ds_framing(self):
        with netCDF4.Dataset(self.img) as i, netCDF4.Dataset(self.proc) as p:
            c = render.reconstruct_particle_image(i, p, 0)
            self.assertTrue(np.array_equal(
                c, render.reconstruct_particle_image(i, p, 0, probe="2DS")))
        self.assertEqual(c.shape, (2, 128))   # the wrong picture a CIP used to get

    def test_a_probe_whose_framing_is_unchecked_is_refused(self):
        with netCDF4.Dataset(self.img) as i, netCDF4.Dataset(self.proc) as p:
            with self.assertRaises(ValueError):
                render.reconstruct_particle_image(i, p, 0, probe="2DC")


@unittest.skipUnless(HAVE_MPL and netCDF4 is not None, "matplotlib/netCDF4 not installed")
class CropToContentTests(unittest.TestCase):
    """Found during the gallery's own visual QA (2026-08-22): a particle
    immediately after a fresh record, or after an unusually large boundary
    gap, can have a ``position`` span hundreds of slices wider than its own
    ``image_length`` -- faithful to imgProc_sm.m, but the shadow vanishes at
    thumbnail scale. Display-only fix; the underlying array is never altered
    for anything but what gets shown.
    """

    def test_crops_to_the_shadowed_bounding_box_plus_padding(self):
        c = np.zeros((500, 128), dtype=bool)
        c[490:495, 60:65] = True  # a small shadow near the far end
        cropped = render.crop_to_content(c, pad=3)
        self.assertEqual(cropped.shape, (5 + 2 * 3, 5 + 2 * 3))
        self.assertTrue(cropped.any())

    def test_padding_clamps_to_array_bounds_at_an_edge(self):
        c = np.zeros((10, 10), dtype=bool)
        c[0:2, 0:2] = True  # touches the top-left corner
        cropped = render.crop_to_content(c, pad=3)
        # No negative-index wraparound: the crop starts at 0, not -3.
        self.assertEqual(cropped.shape, (2 + 3, 2 + 3))

    def test_an_all_lit_array_with_nothing_to_crop_to_is_returned_unchanged(self):
        c = np.zeros((50, 128), dtype=bool)
        cropped = render.crop_to_content(c)
        self.assertEqual(cropped.shape, c.shape)
        np.testing.assert_array_equal(cropped, c)

    def test_render_particle_crop_true_shrinks_the_figure_relative_to_false(self):
        img_dir = tempfile.TemporaryDirectory()
        self.addCleanup(img_dir.cleanup)
        img_path = Path(img_dir.name) / "img.cdf"
        proc_path = Path(img_dir.name) / "proc.nc"
        block = np.zeros((1700, 8), dtype=np.uint16)
        block[300, :] = 65535  # one shadowed slice, far from the window's start
        _make_image_file(img_path, [block])
        _make_proc_file(proc_path, [{"parent_rec_num": 1, "start": 1, "end": 400,
                                     "width": 1, "length": 1}])
        with netCDF4.Dataset(str(img_path)) as ids, netCDF4.Dataset(str(proc_path)) as pds:
            fig_full = render.render_particle(ids, pds, 0, crop=False)
            fig_crop = render.render_particle(ids, pds, 0, crop=True)
        self.assertLess(fig_crop.get_size_inches()[1], fig_full.get_size_inches()[1])


@unittest.skipUnless(HAVE_MPL and netCDF4 is not None, "matplotlib/netCDF4 not installed")
class ParticleInfoTests(unittest.TestCase):
    def test_decodes_reject_and_habit_codes(self):
        img_dir = tempfile.TemporaryDirectory()
        self.addCleanup(img_dir.cleanup)
        proc = Path(img_dir.name) / "proc.nc"
        _make_proc_file(proc, [{"parent_rec_num": 1, "start": 1, "end": 3,
                                "width": 2, "length": 3, "reject": "h", "habit": "d",
                                "diam": 0.5}])
        with netCDF4.Dataset(str(proc)) as pds:
            info = render.particle_info(pds, 0)
        self.assertEqual(info["reject_code"], "h")
        self.assertEqual(info["habit_code"], "d")
        self.assertAlmostEqual(info["diam_minR"], 0.5)


@unittest.skipUnless(HAVE_MPL and netCDF4 is not None, "matplotlib/netCDF4 not installed")
class RenderingAvenueTests(unittest.TestCase):
    """Smoke tests: each avenue runs and produces the expected artifact."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        blocks = []
        particles = []
        for k in range(3):
            block = np.full((1700, 8), 65535, dtype=np.uint16)
            block[k, :] = 0
            blocks.append(block)
            particles.append({"parent_rec_num": k + 1, "start": 1, "end": 5,
                              "width": 1, "length": 5})
        self.img_path = self.dir / "img.cdf"
        self.proc_path = self.dir / "proc.nc"
        _make_image_file(self.img_path, blocks)
        _make_proc_file(self.proc_path, particles)

    def test_render_particle_returns_a_figure(self):
        import matplotlib.figure
        with (netCDF4.Dataset(str(self.img_path)) as ids,
              netCDF4.Dataset(str(self.proc_path)) as pds):
            fig = render.render_particle(ids, pds, 0)
        self.assertIsInstance(fig, matplotlib.figure.Figure)

    def test_contact_sheet_covers_every_requested_particle(self):
        with (netCDF4.Dataset(str(self.img_path)) as ids,
              netCDF4.Dataset(str(self.proc_path)) as pds):
            fig = render.render_contact_sheet(ids, pds, [0, 1, 2], ncols=2)
        self.assertEqual(len(fig.axes), 4)  # 2x2 grid for 3 particles, 1 blanked

    def test_gallery_html_writes_a_self_contained_page(self):
        out = self.dir / "gallery.html"
        with (netCDF4.Dataset(str(self.img_path)) as ids,
              netCDF4.Dataset(str(self.proc_path)) as pds):
            render.render_gallery_html(ids, pds, [0, 1, 2], out, title="Test gallery")
        text = out.read_text(encoding="utf-8")
        self.assertIn("Test gallery", text)
        self.assertEqual(text.count("data:image/png;base64,"), 3)
        self.assertNotIn("<html", text.lower())  # a fragment, per the Artifact convention


if __name__ == "__main__":
    unittest.main()
