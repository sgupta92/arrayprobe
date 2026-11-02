# SPDX-License-Identifier: BSD-3-Clause
"""The triage server pairs a proc file with the decode its own engine wrote.

v3.1.4's stage 2 writes ``<flight>.H.cdf``; v3.5's writes ``<flight>.H.nc``. The server
used to look only for ``.cdf``, so a v3.5 flight was listed with no particle images. The
decode is chosen by the proc file's ``.call`` stamp, never by which file exists: a stale
v3.1.4 decode left beside a v3.5 proc must not be paired with it.

Built from the synthetic demo flight the way
``examples/1_getting_started/03_choosing_an_engine.ipynb``
runs both engines (stage 2 and stage 3 only, six seconds of particles), so it runs in seconds.
Visualisation only: nothing here changes a computed number.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import netCDF4
except ImportError:  # pragma: no cover
    netCDF4 = None

from tests._repo import needs_v314_engine  # noqa: E402

from arrayprobe import provenance

TOOLS = Path(__file__).resolve().parents[1] / "scripts"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
ACCEPTED = [ord(c) for c in "0HhuR"]


def _run_engine(run_flight, st, flight_spec, source_raw: Path, out: Path, engine: str):
    """Stages 2 and 3 of one engine on a copy of ``source_raw`` into ``out``."""
    from arrayprobe.profiles import STOCK_V35

    out.mkdir()
    raw = out / source_raw.name
    shutil.copyfile(source_raw, raw)
    if engine == "3.5":  # the module globals are what `--engine` / `[run] engine` set
        run_flight.ENGINE, run_flight.PROFILE = "3.5", STOCK_V35
        run_flight.TAS_FILE = str(st.write_aircraft_tas(out / "aircraft.cdf", flight_spec))
    image = run_flight.stage2(raw, out)
    proc = run_flight.stage3(image, out)
    return image, proc


@needs_v314_engine
@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
class TestTriagePairsTheEnginesOwnDecode(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from arrayprobe.tools import synthetic_truth as st

        sys.path.insert(0, str(TOOLS))
        from tests import _run_flight_state

        import run_flight

        # Every UPPER_CASE global the stages or the preset set is restored when the class
        # ends; ``log`` is lowercase, outside the helper, so its silencing is undone beside it.
        _run_flight_state.preserve(cls, run_flight)
        cls.addClassCleanup(setattr, run_flight, "log", run_flight.log)
        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name)
        try:
            run_flight.log = lambda *a, **kw: None
            run_flight.use_preset("DEMO_2DS_H")
            spec = st.FlightSpec(n_seconds=6, rate_per_s=12.0, seed=7, depth="in_focus",
                                 across="mid",
                                 psd=st.PSD(kind="discrete",
                                            diameters_um=(50.0, 100.0, 150.0, 200.0)))
            source = root / "base160101060640.2DS"
            st.build_truth_flight(source, spec)
            cls.v314_image, cls.v314_proc = _run_engine(run_flight, st, spec, source,
                                                        root / "engine_3.1.4", "3.1.4")
            cls.v35_image, cls.v35_proc = _run_engine(run_flight, st, spec, source,
                                                      root / "engine_3.5", "3.5")
        finally:
            if str(TOOLS) in sys.path:
                sys.path.remove(str(TOOLS))
        cls.flight = "base160101060640"

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_the_fixture_is_what_the_test_needs(self):
        self.assertEqual(self.v35_image.name, f"{self.flight}.H.nc")
        self.assertEqual(self.v314_image.name, f"{self.flight}.H.cdf")
        self.assertEqual(provenance.read(self.v35_proc).engine, "3.5")

    def test_a_v35_proc_is_paired_with_its_nc_decode(self):
        from arrayprobe.triage_server import _discover_flights

        flights = _discover_flights(self.v35_proc.parent)
        self.assertEqual(flights[self.flight]["image"], self.v35_image)

    def test_the_first_accepted_v35_particle_renders_as_png(self):
        import numpy as np

        from arrayprobe.render import particle_thumbnail_png
        from arrayprobe.triage_server import _discover_flights

        paths = _discover_flights(self.v35_proc.parent)[self.flight]
        self.assertIsNotNone(paths["image"], "the v3.5 decode was not paired")
        with netCDF4.Dataset(str(paths["image"])) as im, \
                netCDF4.Dataset(str(paths["proc"])) as pr:
            code = np.asarray(pr["image_auto_reject"][:]).ravel().astype(int)
            accepted = np.flatnonzero(np.isin(code, ACCEPTED))
            self.assertGreater(accepted.size, 0)
            png = particle_thumbnail_png(im, pr, int(accepted[0]))
        self.assertTrue(png.startswith(PNG_MAGIC))

    def test_a_stale_v314_decode_beside_a_v35_proc_is_not_paired(self):
        from arrayprobe.triage_server import _discover_flights

        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            for src in (self.v35_proc, provenance.call_path(self.v35_proc), self.v314_image):
                shutil.copyfile(src, d / src.name)
            flights = _discover_flights(d)
            self.assertIsNone(flights[self.flight]["image"])

    def test_a_v35_cip_proc_is_paired_with_its_cdf_decode(self):
        """v3.5 runs CIP through the SEA reader both engines share, which writes ``.cdf``.

        The proc and its v3.5 stamp are the demo flight's, renamed to the CIP channel; the
        decode beside it is ``<flight>.CIP.cdf``, and a ``.CIP.nc`` (which no reader writes)
        must not be looked for.
        """
        from arrayprobe.triage_server import _discover_flights

        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            proc = d / f"proc.{self.flight}.CIP.nc"
            shutil.copyfile(self.v35_proc, proc)
            shutil.copyfile(provenance.call_path(self.v35_proc), provenance.call_path(proc))
            decode = d / f"{self.flight}.CIP.cdf"
            shutil.copyfile(self.v314_image, decode)
            self.assertEqual(provenance.read(proc).engine, "3.5")
            flights = _discover_flights(d)
            self.assertEqual(flights[self.flight]["image"], decode)

    def test_the_gallery_renders_a_v35_flight_from_its_nc_decode(self):
        """``arrayprobe gallery`` names the decode from the proc file's stamp, as triage does.

        It used to open ``<flight>.cdf`` only, so a v3.5 flight was refused as missing input.
        """
        import contextlib
        import io

        from arrayprobe import cli

        with tempfile.TemporaryDirectory() as out, \
                contextlib.redirect_stdout(io.StringIO()):
            rc = cli.main(["gallery", "--decoded-dir", str(self.v35_proc.parent),
                           "--flight", f"{self.flight}.H", "--out", out,
                           "--limit", "2", "--no-index"])
            pngs = list(Path(out).rglob("*.png"))
        self.assertEqual(rc, 0)
        self.assertGreater(len(pngs), 0)

    def test_a_v314_proc_is_still_paired_with_its_cdf_decode(self):
        from arrayprobe.triage_server import _discover_flights

        flights = _discover_flights(self.v314_proc.parent)
        self.assertEqual(flights[self.flight]["image"], self.v314_image)

    def test_an_unstamped_proc_keeps_the_cdf_decode(self):
        from arrayprobe.triage_server import _discover_flights

        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            for src in (self.v314_proc, self.v314_image, self.v35_image):
                shutil.copyfile(src, d / src.name)
            flights = _discover_flights(d, accept_unstamped=True)
            self.assertEqual(flights[self.flight]["image"], d / self.v314_image.name)


if __name__ == "__main__":
    unittest.main()
