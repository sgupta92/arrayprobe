# SPDX-License-Identifier: BSD-3-Clause
"""Time navigation on the record strip (viewer-survey item 2, after xpms2d's time widget): a
go-to-UTC box, step by one record and by seconds, carrying ``n`` and ``by`` along. A record is
found by the proc file's ``Time`` and ``parent_rec_num`` as stored; bad input is refused with
the reason."""
from __future__ import annotations

import http.client
import tempfile
import threading
import unittest
import urllib.parse
from pathlib import Path

import numpy as np
from tests.test_triage_server import (
    HAVE_MPL,
    _make_image_file,
    _make_proc_file,
    netCDF4,
)

if HAVE_MPL and netCDF4 is not None:
    from http.server import ThreadingHTTPServer

    from arrayprobe import triage_server as ts

NEEDS = unittest.skipUnless(HAVE_MPL and netCDF4 is not None, "matplotlib/netCDF4 not installed")

#: One particle per record, records 1-5, at these stored HHMMSS times.
RECORDS = [1, 2, 3, 4, 5]
TIMES = [64015, 64016, 64016, 64020, 64030]


def _make_flight(decoded_dir: Path, flight: str) -> None:
    block = np.zeros((1700, 8), dtype=np.uint16)
    block[0:3, :] = 65535
    _make_image_file(decoded_dir / f"{flight}.H.cdf", [block] * len(RECORDS))
    proc = decoded_dir / f"proc.{flight}.H.nc"
    _make_proc_file(proc, [{"parent_rec_num": r, "start": 0, "end": 2, "width": 8,
                            "length": 3, "particle_num": 1} for r in RECORDS])
    with netCDF4.Dataset(proc, "a") as ds:
        v = ds.createVariable("Time", "f8", ("time",))
        v[:] = np.asarray(TIMES, dtype=float)


class LocatingARecordByTime(unittest.TestCase):
    @NEEDS
    def test_utc_text_is_parsed_in_three_spellings(self):
        self.assertEqual(ts.parse_utc("06:40:17"), 6 * 3600 + 40 * 60 + 17)
        self.assertEqual(ts.parse_utc("064017"), 6 * 3600 + 40 * 60 + 17)
        self.assertEqual(ts.parse_utc("06:40"), 6 * 3600 + 40 * 60)

    @NEEDS
    def test_bad_utc_text_is_refused_with_the_reason(self):
        for bad in ("abc", "", "6:4:1", "06:40:17.5"):
            with self.assertRaisesRegex(ValueError, "is not a UTC time: give hh:mm:ss"):
                ts.parse_utc(bad)
        with self.assertRaisesRegex(ValueError, "hours run 0-23"):
            ts.parse_utc("25:00:00")

    @NEEDS
    def test_the_first_record_at_or_after_the_time_is_found(self):
        at = ts.parse_utc
        self.assertEqual(ts.record_at_time(RECORDS, TIMES, at("06:40:15")), 1)
        self.assertEqual(ts.record_at_time(RECORDS, TIMES, at("06:40:16")), 2)
        self.assertEqual(ts.record_at_time(RECORDS, TIMES, at("06:40:17")), 4)
        self.assertEqual(ts.record_at_time(RECORDS, TIMES, at("00:00:00")), 1)
        self.assertEqual(ts.record_seconds(RECORDS, TIMES, 3), at("06:40:16"))

    @NEEDS
    def test_a_time_past_the_file_names_the_span(self):
        with self.assertRaisesRegex(ValueError, r"no particle at or after 07:00:00 UTC: "
                                                r"this file's particle times run "
                                                r"06:40:15-06:40:30 UTC"):
            ts.record_at_time(RECORDS, TIMES, ts.parse_utc("07:00:00"))

    @NEEDS
    def test_non_finite_times_are_skipped(self):
        times = [np.nan, 64016, 64020]
        self.assertEqual(ts.record_at_time([1, 2, 3], times, ts.parse_utc("06:40:00")), 2)


@NEEDS
class TheStripRoute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        d = Path(cls._tmp.name)
        _make_flight(d, "fT")
        cls._saved = ts.TriageServer.__dict__.get("decoded_dir")
        ts.TriageServer.decoded_dir = d
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), ts.TriageServer)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        if cls._saved is None:
            del ts.TriageServer.decoded_dir
        else:
            ts.TriageServer.decoded_dir = cls._saved
        cls._tmp.cleanup()

    def _get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1],
                                          timeout=120)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8", "replace")
        conn.close()
        return resp.status, body

    def test_go_to_time_lands_on_the_right_record(self):
        status, body = self._get("/strip/fT?t=" + urllib.parse.quote("06:40:17") + "&n=1")
        self.assertEqual(status, 200, body)
        self.assertIn("Records 4-4 of 5", body)

    def test_a_step_in_seconds_starts_from_the_records_time(self):
        status, body = self._get("/strip/fT?rec=1&dt=10&n=1")   # 06:40:15 + 10 s
        self.assertEqual(status, 200, body)
        self.assertIn("Records 5-5 of 5", body)

    def test_the_time_bar_carries_n_and_colour_along(self):
        status, body = self._get("/strip/fT?rec=2&n=2&by=habit")
        self.assertEqual(status, 200, body)
        self.assertIn("id='strip-time'", body)
        self.assertIn("name='n' value='2'", body)
        self.assertIn("name='by' value='habit'", body)
        self.assertIn("/strip/fT?rec=1&amp;n=2&amp;by=habit'>&minus;1 record", body)
        self.assertIn("/strip/fT?rec=3&amp;n=2&amp;by=habit'>+1 record", body)
        self.assertIn("/strip/fT?rec=2&amp;dt=-10&amp;n=2&amp;by=habit", body)

    def test_malformed_input_is_refused_with_a_message(self):
        for query, reason in (("t=abc", "is not a UTC time"),
                              ("t=25:00:00", "hours run 0-23"),
                              ("dt=ten", "is not a step in whole seconds")):
            status, body = self._get(f"/strip/fT?rec=2&{query}")
            self.assertEqual(status, 400, query)
            self.assertIn("id='strip-time-msg'", body)
            self.assertIn(reason, body)

    def test_a_time_the_file_does_not_reach_keeps_the_record_and_says_why(self):
        status, body = self._get("/strip/fT?rec=2&n=1&t=07:00:00")
        self.assertEqual(status, 200, body)
        self.assertIn("Records 2-2 of 5", body)
        self.assertIn("no particle at or after 07:00:00 UTC", body)


if __name__ == "__main__":
    unittest.main()
