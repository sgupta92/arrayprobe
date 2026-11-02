# SPDX-License-Identifier: BSD-3-Clause
"""The particle properties beside the image read as names and units, not variable names.

The rows printed ``particle_info``'s keys verbatim: ``diam_minR 0.08345188393134889`` (mm, 17
digits), ``image_width 11.0`` (diodes). Each row now shows a long name, the value in a readable
unit and the variable name in small type beside it. The conversions are for display only: the
stored number is unchanged and stays in the row's tooltip.
"""
from __future__ import annotations

import http.client
import re
import tempfile
import threading
import unittest
from pathlib import Path

from tests.test_triage_server import HAVE_MPL, _make_fixture, netCDF4

from arrayprobe.triage_server import TriageServer


def kv_html(info: dict) -> str:
    from arrayprobe.triage_server import _kv_html
    return _kv_html(info)


def row_for(page: str, var: str) -> str:
    """The one row of ``var`` in ``page``, tooltip included."""
    rows = [m.group(0) for m in re.finditer(r"<div(?: title='[^']*')?><b>.*?</div>", page)
            if f"<small class=var>{var}</small>" in m.group(0)]
    if len(rows) != 1:
        raise AssertionError(f"{len(rows)} rows for {var!r}")
    return rows[0]


class TheNamesTable(unittest.TestCase):
    def test_every_name_has_a_long_name_and_a_unit_slot(self):
        from arrayprobe.triage_server import PROPERTY_NAMES
        for var, entry in PROPERTY_NAMES.items():
            long_name, unit, fmt = entry
            self.assertTrue(long_name and long_name != var, var)
            self.assertIsInstance(unit, str)
            self.assertIsInstance(fmt, str)

    def test_the_rows_particle_info_writes_are_all_named(self):
        from arrayprobe.triage_server import PROPERTY_NAMES
        for var in ("particle_index", "parent_rec_num", "particle_num", "image_width",
                    "image_length", "reject_code", "habit_code", "diam_minR",
                    "image_area", "image_hollow", "area_hole_ratio", "image_axis_ratio",
                    "percent_shadow_area", "image_touching_edge"):
            self.assertIn(var, PROPERTY_NAMES)


class TheRows(unittest.TestCase):
    def test_minR_shows_its_long_name_and_variable_name(self):
        out = kv_html({"diam_minR": 0.08345188393134889})
        self.assertIn("Smallest enclosing circle", out)
        self.assertIn("<small class=var>diam_minR</small>", out)

    def test_minR_is_shown_in_um_as_1000_times_the_stored_mm(self):
        stored_mm = 0.08345188393134889
        row = row_for(kv_html({"diam_minR": stored_mm}), "diam_minR")
        m = re.search(r"([0-9.]+) µm", row)
        self.assertIsNotNone(m, row)
        self.assertEqual(float(m.group(1)), float(f"{1000 * stored_mm:.3g}"))
        self.assertIn("(0.0835 mm)", row)
        # The stored number itself is kept, unrounded, in the tooltip.
        self.assertIn(repr(stored_mm), row)
        self.assertNotIn(f">{stored_mm!r}", row)

    def test_large_minR_has_no_exponent(self):
        row = row_for(kv_html({"diam_minR": 1.23456}), "diam_minR")
        self.assertIn("1230 µm", row)
        self.assertNotIn("e+", row)

    def test_integers_print_without_point_zero(self):
        out = kv_html({"image_width": 11.0, "image_length": 3.0, "parent_rec_num": 7,
                       "image_hollow": 0.0})
        self.assertIn("11 diodes", row_for(out, "image_width"))
        self.assertIn("3 slices", row_for(out, "image_length"))
        self.assertNotIn("11.0", out)
        self.assertNotIn("3.0", out)

    def test_touching_edge_is_in_words(self):
        for stored, word in ((0.0, "no"), (68.0, "yes"), (-48.0, "no slices")):
            row = row_for(kv_html({"image_touching_edge": stored}), "image_touching_edge")
            self.assertIn(f"{word} <small", row)
            self.assertIn(str(int(stored)), row)

    def test_reject_and_habit_codes_are_words_with_the_letter(self):
        out = kv_html({"reject_code": "H", "habit_code": "s"})
        self.assertIn("Automatic reject code", out)
        self.assertIn("hollow", row_for(out, "reject_code"))
        self.assertIn("sphere", row_for(out, "habit_code"))
        self.assertIn("Holroyd habit", out)

    def test_an_unnamed_property_still_shows_under_its_variable_name(self):
        row = row_for(kv_html({"image_mystery": 2.5}), "image_mystery")
        self.assertIn("image_mystery", row)
        self.assertIn("2.5", row)

    def test_missing_and_nan_values_are_said_so(self):
        out = kv_html({"diam_minR": None, "image_axis_ratio": float("nan")})
        self.assertIn("—", row_for(out, "diam_minR"))
        self.assertIn("not a number", row_for(out, "image_axis_ratio"))

    def test_names_are_escaped(self):
        out = kv_html({"<x>": "<y>"})
        self.assertNotIn("<x>", out)
        self.assertNotIn("<y>", out)


@unittest.skipUnless(HAVE_MPL and netCDF4 is not None, "matplotlib/netCDF4 not installed")
class ThePages(unittest.TestCase):
    """The particle page and the queue page both carry the named rows."""

    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer

        cls._tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls._tmp.name)
        _make_fixture(cls.dir, "flightP")
        cls._saved = {k: TriageServer.__dict__[k] for k in ("decoded_dir", "queues")
                      if k in TriageServer.__dict__}
        TriageServer.decoded_dir = cls.dir
        TriageServer.queues = {"qp": [{"flight": "flightP", "particle_index": 0}]}
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), TriageServer)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        for k in ("decoded_dir", "queues"):
            if k in cls._saved:
                setattr(TriageServer, k, cls._saved[k])
            else:
                delattr(TriageServer, k)
        cls._tmp.cleanup()

    def _get(self, path: str) -> str:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        conn.close()
        self.assertEqual(resp.status, 200, body[:500])
        return body

    def test_particle_page(self):
        page = self._get("/particle/flightP/0")
        self.assertIn("Smallest enclosing circle", page)
        self.assertIn("<small class=var>diam_minR</small>", page)
        # The fixture stores 0.1 mm for particle 0.
        self.assertIn("100 µm", row_for(page, "diam_minR"))
        self.assertIn("8 diodes", row_for(page, "image_width"))

    def test_queue_page(self):
        page = self._get("/queue/qp/0")
        self.assertIn("Smallest enclosing circle", page)
        self.assertIn("<small class=var>diam_minR</small>", page)
        self.assertIn("100 µm", row_for(page, "diam_minR"))


if __name__ == "__main__":
    unittest.main()
