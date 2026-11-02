# SPDX-License-Identifier: BSD-3-Clause
"""The known-truth synthetic flight generator (TT): ``arrayprobe.tools.synthetic_truth``.

Four kinds of check, each drawing its two sides from different places:

* the Korolev (2007) Appendix B table this module transcribed, against C4's independent
  transcription of the same page (the CIP pixelisation model's table), row by row where both
  have the row, and against the page's own structure (164 rows, 0 to 8.15 in 0.05 steps);
* the manifest round-trips, and the same spec writes the same bytes;
* the raw bytes, decoded by the port's own ``read_binary_SPEC`` and framed by ``imgProc_sm``,
  hold exactly the particles the manifest says were imaged, with the clock values it recorded;
* **the sanity anchor**: perfect in-focus disks centred on the array, through the v3.1.4 chain
  under stock settings, are all accepted and sized to their true diameter within the pixel
  quantisation -- and a mutation of the optical model (in-focus images rendered 30 % large)
  makes that anchor fail, so it is a check and not a restatement.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import netCDF4
import numpy as np
from tests._repo import needs_file, needs_v314_engine  # noqa: E402

from arrayprobe.tools import synthetic_truth as st

TOOLS = Path(__file__).resolve().parents[1] / "scripts"


def _load_tool(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, mod)
    spec.loader.exec_module(mod)
    return mod


class TheKorolevTableIsTranscribedWhole(unittest.TestCase):
    def test_the_table_has_the_pages_structure(self):
        zd = [r[0] for r in st.KOROLEV_2007_APPENDIX_B]
        self.assertEqual(len(zd), 164)
        np.testing.assert_allclose(zd, np.arange(164) * 0.05, atol=1e-9)
        self.assertEqual(st.KOROLEV_2007_APPENDIX_B[0], (0.0, 1.000, 0.003))
        self.assertEqual(st.KOROLEV_2007_APPENDIX_B[-1], (8.15, 1.845, 0.950))

    @needs_file("scripts/cip_pixelisation_model.py")
    def test_every_row_c4_transcribed_independently_agrees(self):
        c4 = _load_tool("cip_pixelisation_model").KOROLEV_2007_APPENDIX_B
        ours = {round(r[0], 2): (r[1], r[2]) for r in st.KOROLEV_2007_APPENDIX_B}
        self.assertGreaterEqual(len(c4), 10)
        for zd, dims in c4.items():
            with self.subTest(zd=zd):
                self.assertEqual(ours[round(zd, 2)], dims)

    def test_lookup_is_nearest_row_and_nothing_beyond_zdmax(self):
        self.assertEqual(st.korolev_dimensions(1.92), (1.407, 0.243))   # 1.90's row
        self.assertEqual(st.korolev_dimensions(1.93), (1.074, 0.327))   # 1.95's row
        self.assertIsNotNone(st.korolev_dimensions(8.18))
        self.assertIsNone(st.korolev_dimensions(8.19))


class Rendering(unittest.TestCase):
    model = st.OpticalModel()

    def test_an_in_focus_disk_has_the_disk_area(self):
        img, touches = st.render_droplet(200.0, 0.0, 640.0, 0.3, self.model)
        self.assertFalse(touches)
        area_px = img.sum()
        self.assertAlmostEqual(area_px / (np.pi / 4 * 20 ** 2), 1.0, delta=0.06)
        self.assertIn(img.shape[0], (20, 21))

    def test_far_from_focus_the_image_is_a_larger_ring(self):
        img, _ = st.render_droplet(200.0, 7.0, 640.0, 0.0, self.model)
        rows = img.shape[0]
        self.assertGreater(rows, 20 * 1.8)             # D_edge/D0 = 1.889 at Z_d = 7
        mid = img[rows // 2]
        cols = np.flatnonzero(mid)
        self.assertFalse(mid[(cols[0] + cols[-1]) // 2])   # the Poisson spot is clear

    def test_beyond_zdmax_there_is_no_image(self):
        self.assertIsNone(st.render_droplet(200.0, 8.3, 640.0, 0.0, self.model))

    def test_an_array_end_clips_the_image(self):
        img, touches = st.render_droplet(200.0, 0.0, 0.0, 0.0, self.model)
        self.assertTrue(touches)
        self.assertLessEqual(np.flatnonzero(img.any(axis=0)).max(), 11)

    @needs_v314_engine
    def test_run_words_decode_back_to_the_image(self):
        """The encoder against the port's own decoder, on a ring (two runs per slice)."""
        from arrayprobe.profiles import STOCK_V314
        from arrayprobe.readers import spec

        img, _ = st.render_droplet(300.0, 6.0, 500.0, 0.5, self.model)
        runs = st.image_runs(img)
        pkt = st.image_packet(runs, img.shape[0], channel="H", pc=1, t_particle=1234)
        buf = np.zeros(2 * spec.DATA_WORDS, dtype=np.int64)
        buf[: len(pkt)] = pkt
        img_h, _img_v, _ = spec.get_img(buf, 60640.0, profile=STOCK_V314)
        # The canvas is (diodes, slices), 1 = shadowed, slice 1 in column 0 (`set_run`).
        decoded = np.asarray(img_h)[:, : img.shape[0]].T.astype(bool)
        self.assertGreater(int(img.sum()), 100)
        np.testing.assert_array_equal(decoded, img)


def _small(**kw) -> st.FlightSpec:
    base = dict(n_seconds=3, rate_per_s=12.0, seed=7, depth="in_focus", across="mid",
                psd=st.PSD(kind="discrete", diameters_um=(50.0, 100.0, 150.0, 200.0)))
    base.update(kw)
    return st.FlightSpec(**base)


class TheManifest(unittest.TestCase):
    def test_it_round_trips(self):
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d) / "base160101060640.2DS"
            m = st.build_truth_flight(raw, _small(depth="uniform", across="margin",
                                                  burst_rate_per_s=1.0))
            back = st.TruthManifest.from_json(str(raw) + st.MANIFEST_SUFFIX)
            self.assertEqual(back.spec, m.spec)
            self.assertEqual(back.model, m.model)
            self.assertEqual(back.columns, m.columns)
            self.assertEqual(back.raw_name, raw.name)
            self.assertIn("fragment", back.columns["kind"])

    def test_the_same_spec_writes_the_same_bytes_and_another_seed_does_not(self):
        with tempfile.TemporaryDirectory() as d:
            a, b, c = (Path(d) / f"base16010106064{i}.2DS" for i in range(3))
            st.build_truth_flight(a, _small())
            st.build_truth_flight(b, _small())
            st.build_truth_flight(c, _small(seed=8))
            self.assertEqual(a.read_bytes(), b.read_bytes())
            self.assertNotEqual(a.read_bytes(), c.read_bytes())

    @needs_v314_engine
    def test_a_flight_stays_small(self):
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d) / "base160101060640.2DS"
            st.build_truth_flight(raw, _small(n_seconds=5, rate_per_s=100.0))
            self.assertLess(raw.stat().st_size, 5_000_000)
            self.assertEqual(raw.stat().st_size % (spec_record_bytes()), 0)


def spec_record_bytes() -> int:
    from arrayprobe.readers import spec
    return 2 * spec.RECORD_WORDS


def _run_v314_stock(raw: Path, flight: st.FlightSpec) -> tuple[Path, Path]:
    from arrayprobe import imgproc, sizedist
    from arrayprobe.profiles import STOCK_V314
    from arrayprobe.readers import spec
    from arrayprobe.readers.tasinfo import load_tas_info

    out = raw.parent
    spec.read_binary_SPEC(raw, out / raw.stem, profile=STOCK_V314, channels="H")
    img = out / f"{raw.stem}.H.cdf"
    with netCDF4.Dataset(str(img)) as d:
        n = len(d.dimensions["time"])
    ac = st.write_aircraft_tas(out / "aircraft.nc", flight)
    proc, sd = out / "proc.nc", out / "sd.nc"
    imgproc.imgproc_sm(str(img), str(proc), "2DS", 1, n, "DEMO", profile=STOCK_V314,
                       tas_file=str(ac))
    th, tas = load_tas_info(out / f"{raw.stem}.tas.csv")
    sizedist.run(str(proc), str(sd), tas, np.floor(th), "2DS", 6, 0, np.full_like(tas, 9e5),
                 np.full_like(tas, 15.0), "DEMO", "20160906 060640", tree="stock",
                 creation_time="test")
    return proc, sd


#: Anchor: in-focus disks at four diameters, centred two diodes clear of both array ends.
ANCHOR = _small(n_seconds=2, rate_per_s=10.0, seed=11)


def _anchor_verdict(raw: Path, flight: st.FlightSpec) -> tuple[bool, str]:
    """Run v3.1.4 stock on the flight at ``raw`` and judge it against its manifest: every imaged
    droplet framed, accepted and counted, and every one sized within 1.5 pixels of its true
    diameter. Returns ``(ok, why)``."""
    m = st.TruthManifest.from_json(str(raw) + st.MANIFEST_SUFFIX)
    proc, sd = _run_v314_stock(raw, flight)
    with netCDF4.Dataset(str(proc)) as d:
        d.set_auto_mask(False)
        diam_mm = np.asarray(d["image_diam_minR"][:], float).ravel()
        code = np.asarray(d["image_auto_reject"][:]).ravel().astype(int)
        clock = np.asarray(d["particle_microsec"][:], float).ravel()
    with netCDF4.Dataset(str(sd)) as d:
        d.set_auto_mask(False)
        t = np.asarray(d["time"][:], float)
        counts = np.nan_to_num(np.asarray(d["count"][:], float))
    imaged = np.asarray(m.columns["imaged"])
    true_d = np.asarray(m.columns["d0_um"])[imaged]
    if diam_mm.size != true_d.size:
        return False, f"{diam_mm.size} framed, {true_d.size} imaged"
    if not np.array_equal(clock, np.asarray(m.columns["clock"], float)[imaged]):
        return False, "clock values differ from the manifest"
    if not np.all(np.isin(code, [ord(c) for c in "0HhuR"])):
        return False, f"rejected codes {sorted(set(code.tolist()))}"
    err_px = np.abs(diam_mm * 1000.0 - true_d) / 10.0
    if err_px.max() > 1.5:
        return False, f"sizing error up to {err_px.max():.2f} px"
    in_flight = t < 240000
    if int(round(counts[in_flight].sum())) != true_d.size:
        return False, f"counted {counts[in_flight].sum()} of {true_d.size}"
    return True, "ok"


class TheSanityAnchor(unittest.TestCase):
    """Perfect in-focus mid-array disks, v3.1.4 under stock settings: the truth, exactly."""

    @needs_v314_engine
    def test_stock_v314_recovers_perfect_disks(self):
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d) / "base160101060640.2DS"
            st.build_truth_flight(raw, ANCHOR)
            ok, why = _anchor_verdict(raw, ANCHOR)
            self.assertTrue(ok, why)

    @needs_v314_engine
    def test_mutation_in_focus_images_rendered_large_fail_the_anchor(self):
        """The anchor is a check: render every in-focus image 30 % large (a wrong optical model,
        or equivalently a chain that oversizes) and it must fail."""
        real = st.korolev_dimensions

        def too_big(zd):
            edge, spot = real(zd)
            return edge * 1.3, spot

        with tempfile.TemporaryDirectory() as d, mock.patch.object(st, "korolev_dimensions",
                                                                  too_big):
            raw = Path(d) / "base160101060640.2DS"
            st.build_truth_flight(raw, ANCHOR)
            ok, why = _anchor_verdict(raw, ANCHOR)
        self.assertFalse(ok, "a 30 % oversizing passed the anchor")
        self.assertIn("sizing error", why)


class TheHarnessComparison(unittest.TestCase):
    def test_bands_are_unions_of_kk_bins(self):
        th = _load_tool("truth_harness")
        edges = th.band_edges_bins()
        self.assertEqual(len(edges), len(th.BANDS_UM) - 1)
        x = np.ones(th.NB)
        self.assertEqual(sum(th.bands(x)), (th.BANDS_UM[-1] - th.BANDS_UM[0]) / 10)

    def test_garwood_brackets_the_count(self):
        th = _load_tool("truth_harness")
        lo, hi = th.garwood(np.array([0, 1, 10, 100]))
        self.assertEqual(lo[0], 0.0)
        np.testing.assert_allclose(hi[0], 3.689, atol=0.01)
        np.testing.assert_allclose([lo[2], hi[2]], [4.795, 18.39], atol=0.01)

    def test_true_concentration_is_count_over_the_drawn_volume(self):
        th = _load_tool("truth_harness")
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d) / "base160101060640.2DS"
            m = st.build_truth_flight(raw, _small(depth="uniform", across="margin"))
            t = th.true_distribution(m)
            v = m.spec.tas_mps * m.spec.n_seconds * (1280 + 2 * m.spec.margin_um) * 1e-6 * 0.063
            self.assertAlmostEqual(t["volume_cm3"], v * 1e6, places=3)
            n = sum(k == "droplet" for k in m.columns["kind"])
            self.assertAlmostEqual(t["conc_cm3"].sum() * t["volume_cm3"], n, places=6)


if __name__ == "__main__":
    unittest.main()

