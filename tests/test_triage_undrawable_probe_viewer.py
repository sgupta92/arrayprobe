# SPDX-License-Identifier: BSD-3-Clause
"""A 2DC/2DP/Fast2DC flight became discoverable by ``arrayprobe.triage_server`` on
2026-09-20 (commit 034da39), but ``render.py``'s ``DRAWABLE_PROBES`` still refuses to
draw 2DC and 2DP: their ``image_slice_offset`` is 1 and whether that offset must be
applied when *reading the proc file's stored `position` back* (as opposed to only when
``imgProc_sm`` originally wrote it) had not been checked against real output.

Before this test's fix, the viewer would LIST such a flight and then raise
``ValueError`` from ``render.reconstruct_particle_image`` the moment anyone opened a
particle -- listing something you cannot open is worse than not listing it. This
module asserts the fix: the flight still lists, and every route that would otherwise
call into ``render.py``'s refusal returns a clear, specific, non-raising explanation
instead (naming the probe and the exact unchecked assumption), rather than a 500 or a
broken image icon.

Fixture pattern (image + proc + ``.call`` stamp, real HTTP server on an ephemeral
port) copied from ``test_triage_server.py``'s own ``_make_image_file`` /
``_make_proc_file`` / ``_stamp_proc`` -- duplicated rather than imported, so this
module stands alone and does not depend on that file's fixtures not drifting.
"""

from __future__ import annotations

import http.client
import tempfile
import threading
import unittest
from pathlib import Path

import numpy as np

from arrayprobe import ncio

try:
    import matplotlib
    matplotlib.use("Agg")
    HAVE_MPL = True
except ImportError:  # pragma: no cover
    HAVE_MPL = False

try:
    import netCDF4
except ImportError:  # pragma: no cover
    netCDF4 = None

if HAVE_MPL and netCDF4 is not None:
    from http.server import ThreadingHTTPServer

    from arrayprobe import provenance
    from arrayprobe.constants import IMGPROC_CONFIG
    from arrayprobe.render import DRAWABLE_PROBES
    from arrayprobe.triage_server import TriageServer, _discover_flights, _not_drawable_message

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _make_image_file(path):
    """A minimal PMS-shaped image file. Content is irrelevant here: the fix
    under test means a 2DC/2DP particle image is never actually reconstructed
    from this file, only the fact that it exists (so discovery does not treat
    the flight as image-less) matters.
    """
    f = ncio.create(str(path), "clobber")
    dim_time = f.def_dim("time", ncio.NC_UNLIMITED)
    dim_row = f.def_dim("ImgRowlen", 4)
    dim_block = f.def_dim("ImgBlocklen", 1024)
    varid = f.def_var("data", "int", [dim_row, dim_block, dim_time])
    f.end_def()
    block = np.zeros((1024, 4), dtype=np.int64)
    ncio.write_record_block(f, varid, 0, block[np.newaxis, ...])
    f.close()


def _make_proc_file(path, particles):
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
    pos = np.array(
        [[p["start"] for p in particles], [p["end"] for p in particles]], dtype=np.float64,
    )
    f.put_var(v_pos, pos)
    f.put_var(v_prn, np.array([p["parent_rec_num"] for p in particles], dtype=np.float64))
    pnum = [p.get("particle_num", i + 1) for i, p in enumerate(particles)]
    f.put_var(v_pnum, np.array(pnum, dtype=np.float64))
    f.put_var(v_width, np.array([p["width"] for p in particles], dtype=np.float64))
    f.put_var(v_length, np.array([p["length"] for p in particles], dtype=np.float64))
    f.put_var(v_reject, np.array([ord(p.get("reject", "0")) for p in particles], dtype=np.float64))
    f.put_var(v_habit, np.array([ord(p.get("habit", "a")) for p in particles], dtype=np.float64))
    f.put_var(v_diam, np.array([p.get("diam", 1.0) for p in particles], dtype=np.float64))
    f.close()
    provenance.write(Path(path), engine="3.1.4", profile="oracles-production", stage="S3")


def _make_2dc_fixture(decoded_dir: Path, flight: str = "dcflight"):
    _make_image_file(decoded_dir / f"{flight}.2DC.cdf")
    _make_proc_file(
        decoded_dir / f"proc.{flight}.2DC.nc",
        [
            {"parent_rec_num": 1, "start": 2, "end": 3, "width": 8, "length": 1,
             "reject": "0", "diam": 0.1},
            {"parent_rec_num": 1, "start": 6, "end": 8, "width": 8, "length": 2,
             "reject": "a", "diam": 0.2, "particle_num": 2},
        ],
    )
    return flight


@unittest.skipUnless(HAVE_MPL and netCDF4 is not None, "matplotlib/netCDF4 not installed")
class NotDrawableMessageTests(unittest.TestCase):
    """Unit-level: the explanatory text itself names the probe and the reason."""

    def test_2dc_is_not_in_drawable_probes(self):
        # The premise this whole module tests against: if 2DC ever becomes
        # drawable, this test (and the ones below) should fail loudly rather
        # than silently keep asserting a refusal that no longer happens.
        self.assertNotIn("2DC", DRAWABLE_PROBES)
        self.assertNotIn("2DP", DRAWABLE_PROBES)

    def test_message_names_the_probe_and_the_offset(self):
        msg = _not_drawable_message("2DC")
        self.assertIn("2DC", msg)
        self.assertIn("image_slice_offset", msg)
        self.assertIn(str(IMGPROC_CONFIG["2DC"].image_slice_offset), msg)
        self.assertIn("unverified", msg)

    def test_message_is_specific_per_probe(self):
        self.assertNotEqual(_not_drawable_message("2DC"), _not_drawable_message("2DP"))


@unittest.skipUnless(HAVE_MPL and netCDF4 is not None, "matplotlib/netCDF4 not installed")
class UndrawableProbeHttpTests(unittest.TestCase):
    """Real HTTP requests against a real server, over a 2DC flight fixture."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls._tmp.name)
        cls.flight = _make_2dc_fixture(cls.dir)
        TriageServer.decoded_dir = cls.dir
        TriageServer.queues = {}
        TriageServer.reviewer = None
        TriageServer.accept_unstamped = False
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), TriageServer)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls._tmp.cleanup()

    def _get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
        try:
            conn.request("GET", path)
            resp = conn.getresponse()
            body = resp.read()
            return resp.status, resp.getheader("Content-Type"), body
        finally:
            conn.close()

    def test_the_flight_is_discovered_as_2dc(self):
        flights = _discover_flights(self.dir)
        self.assertIn(self.flight, flights)
        self.assertEqual(flights[self.flight]["probe"], "2DC")

    def test_the_flight_lists_on_the_index_page(self):
        status, _ct, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn(self.flight.encode(), body)

    def test_opening_the_flight_grid_does_not_500(self):
        """The grid embeds ``<img src='/image/...'>`` for every particle --
        the first place a 2DC flight's images would have been requested,
        before anyone opens a specific particle."""
        status, _ct, body = self._get(f"/flight/{self.flight}?group=all")
        self.assertEqual(status, 200)
        self.assertNotIn(b"ValueError", body)
        self.assertNotIn(b"Traceback", body)

    def test_requesting_the_particle_image_returns_a_png_not_a_raise(self):
        """The exact scenario from the bug report: someone opens a particle.
        Before the fix this 500'd with ``ValueError: probe '2DC' is not
        drawable here`` instead of an image."""
        status, content_type, body = self._get(f"/image/{self.flight}/0.png?crop=0")
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "image/png")
        self.assertTrue(body.startswith(_PNG_MAGIC))

    def test_requesting_the_particle_thumb_returns_a_png_not_a_raise(self):
        status, content_type, body = self._get(f"/thumb/{self.flight}/0.png")
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "image/png")
        self.assertTrue(body.startswith(_PNG_MAGIC))

    def test_opening_the_particle_detail_page_does_not_500(self):
        status, _ct, body = self._get(f"/particle/{self.flight}/0")
        self.assertEqual(status, 200)
        self.assertNotIn(b"ValueError", body)
        self.assertNotIn(b"Traceback", body)
        # Metadata still shows: particle_info's own fields are drawn from the
        # proc file directly and never touch render.py's refusal.
        self.assertIn(b"reject_code", body)

    def test_opening_the_sheet_view_does_not_500(self):
        status, _ct, body = self._get(f"/sheet/{self.flight}?group=all")
        self.assertEqual(status, 200)
        self.assertNotIn(b"ValueError", body)
        self.assertNotIn(b"Traceback", body)


if __name__ == "__main__":
    unittest.main()
