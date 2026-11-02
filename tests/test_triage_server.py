# SPDX-License-Identifier: BSD-3-Clause
"""Tests for arrayprobe.triage_server -- the local mass particle triage GUI.

Two layers: pure-function tests for the verdict-storage helpers (no HTTP),
and HTTP integration tests against a real ThreadingHTTPServer bound to an
ephemeral localhost port, using a small hand-built proc/image fixture (same
pattern as test_render.py's, since triage_server reuses render.py's
reconstruction directly).

The path-traversal regression test (test_post_rejects_unknown_flight_and_
writes_nothing_outside_triage_verdicts) exists because a real bug was found
and fixed 2026-08-27: do_POST took `flight` straight from the JSON body with
no check against the server's own discovered-flights whitelist, so
`_verdicts_path` (decoded_dir / "triage_verdicts" / f"{flight}.json") could
be pointed anywhere pathlib's `/` operator would resolve to -- including
outside decoded_dir entirely for an absolute right-hand side, or a parent
directory via `..` segments. Fixed with a single `_valid_flight` gate
checked at the top of both do_GET and do_POST before any path is built.
"""

from __future__ import annotations

import http.client
import json
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

    from arrayprobe.triage_server import (
        TriageServer,
        VerdictStoreError,
        _discover_flights,
        _load_verdicts,
        _save_verdict,
        _save_verdicts_bulk,
        _verdicts_path,
    )


def _make_image_file(path, blocks):
    f = ncio.create(str(path), "clobber")
    dim_time = f.def_dim("time", ncio.NC_UNLIMITED)
    dim_row = f.def_dim("ImgRowlen", 8)
    dim_block = f.def_dim("ImgBlocklen", 1700)
    varid = f.def_var("data", "int", [dim_row, dim_block, dim_time])
    f.end_def()
    stacked = np.stack(blocks).astype(np.int64)
    ncio.write_record_block(f, varid, 0, stacked)
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
    _stamp_proc(path)


def _stamp_proc(path) -> None:
    """Give a fixture proc file the ``.call`` sidecar a real one has.

    Added 2026-09-18 when ``_discover_flights`` began refusing products whose
    provenance is unrecorded. Every fixture here stands for a product some stage wrote, and a
    real one carries a stamp -- so stamping them keeps these tests testing what they were
    written to test (discovery, rendering, verdict storage) rather than accidentally testing
    the new refusal. The refusal has its own module,
    ``tests/test_triage_refuses_unstamped.py``, where an unstamped file is the point.
    """
    from arrayprobe import provenance
    provenance.write(Path(path), engine="3.1.4", profile="oracles-production", stage="S3")


def _make_fixture(decoded_dir: Path, flight: str):
    # test_render.py's convention: raw word 65535 -> '0' chars -> SHADOWED.
    # Rows 0-2 shadowed (a tiny particle), the rest of the 1700-row block
    # lit -- same shape every ncio-backed image variable requires.
    block = np.zeros((1700, 8), dtype=np.uint16)
    block[0:3, :] = 65535
    _make_image_file(decoded_dir / f"{flight}.H.cdf", [block])
    _make_proc_file(
        decoded_dir / f"proc.{flight}.H.nc",
        [
            {"parent_rec_num": 0, "start": 0, "end": 2, "width": 8, "length": 3,
             "reject": "0", "diam": 0.1},
            {"parent_rec_num": 0, "start": 0, "end": 2, "width": 8, "length": 3,
             "reject": "a", "diam": 0.2, "particle_num": 2},
        ],
    )


@unittest.skipUnless(HAVE_MPL and netCDF4 is not None, "matplotlib/netCDF4 not installed")
class VerdictStorageTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_save_then_load_roundtrip(self):
        _save_verdict(self.dir, "flightA", 5, "artifact", "note here",
                      source="human", reviewer="test")
        data = _load_verdicts(self.dir, "flightA")
        self.assertEqual(set(data), {"5"})
        record = data["5"]
        self.assertEqual(record["verdict"], "artifact")
        self.assertEqual(record["note"], "note here")
        # Provenance is checked for presence here and for its own behaviour in
        # test_verdict_provenance.py; asserting the whole dict would pin the
        # clock into this test.
        self.assertEqual(record["source"], "human")

    def test_bulk_save_is_one_file_write_for_many_indices(self):
        data = _save_verdicts_bulk(self.dir, "flightA", [1, 2, 3], "real", "cluster 0",
                                   reviewer="test")
        self.assertEqual(set(data), {"1", "2", "3"})
        self.assertTrue(all(v["verdict"] == "real" for v in data.values()))

    def test_load_missing_flight_returns_empty(self):
        self.assertEqual(_load_verdicts(self.dir, "nope"), {})

    def test_load_corrupt_json_raises_rather_than_reading_as_empty(self):
        """The defect this replaces: ``_load_verdicts`` swallowed
        ``JSONDecodeError`` and returned ``{}``.

        A test named ``..._returns_empty_not_raise`` used to pin exactly that,
        so the suite was defending the data-loss path.  ``{}`` is not a safe
        answer here, because both save paths read-modify-write: the next click
        would have written a one-entry file over a whole flight's labels.  This
        is the failure the artifact-based predecessor had and this tool exists
        to avoid.
        """
        p = _verdicts_path(self.dir, "flightA")
        p.write_text("{not json", encoding="utf-8")
        with self.assertRaises(VerdictStoreError):
            _load_verdicts(self.dir, "flightA")

    def test_load_json_that_is_not_an_object_raises(self):
        _verdicts_path(self.dir, "flightA").write_text("[1, 2, 3]", encoding="utf-8")
        with self.assertRaises(VerdictStoreError):
            _load_verdicts(self.dir, "flightA")

    def test_save_refuses_to_overwrite_an_unreadable_sidecar(self):
        """The consequence, stated as a test: a corrupt file survives a save.

        Without it the file on disk would afterwards hold one verdict and
        nothing else -- silently, with the UI reporting success.
        """
        p = _verdicts_path(self.dir, "flightA")
        p.write_text("{not json", encoding="utf-8")
        with self.assertRaises(VerdictStoreError):
            _save_verdict(self.dir, "flightA", 5, "artifact", source="human", reviewer="test")
        with self.assertRaises(VerdictStoreError):
            _save_verdicts_bulk(self.dir, "flightA", [1, 2], "real", reviewer="test")
        self.assertEqual(p.read_text(encoding="utf-8"), "{not json")

    def test_bulk_save_refuses_before_writing_anything(self):
        """A bulk pass can cover thousands of particles; it must abort at the
        read, not part-way through the write."""
        good = _save_verdicts_bulk(self.dir, "flightA", [1, 2], "real", reviewer="test")
        self.assertEqual(set(good), {"1", "2"})
        p = _verdicts_path(self.dir, "flightA")
        original = p.read_text(encoding="utf-8")
        p.write_text(original + "trailing garbage", encoding="utf-8")
        with self.assertRaises(VerdictStoreError):
            _save_verdicts_bulk(self.dir, "flightA", range(1000), "artifact", reviewer="test")
        self.assertEqual(p.read_text(encoding="utf-8"), original + "trailing garbage")

    def test_verdicts_confined_to_triage_verdicts_subdir(self):
        _save_verdict(self.dir, "flightA", 1, "artifact", source="human", reviewer="test")
        written = list((self.dir / "triage_verdicts").glob("*.json"))
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0].name, "flightA.json")


@unittest.skipUnless(HAVE_MPL and netCDF4 is not None, "matplotlib/netCDF4 not installed")
class DiscoverFlightsTests(unittest.TestCase):
    def test_finds_matching_pairs_only(self):
        with tempfile.TemporaryDirectory() as d:
            decoded = Path(d)
            _make_fixture(decoded, "goodflight")
            (decoded / "proc.orphan.H.nc").write_bytes(b"")  # no matching .H.cdf
            _stamp_proc(decoded / "proc.orphan.H.nc")
            flights = _discover_flights(decoded)
            self.assertIn("goodflight", flights)
            self.assertIsNotNone(flights["goodflight"]["image"])
            self.assertIn("orphan", flights)
            self.assertIsNone(flights["orphan"]["image"])

    def test_a_cip_flight_is_found_by_its_probe_named_files(self):
        """``proc.<flight>.CIP.nc`` beside ``<flight>.CIP.cdf``, drawn as a CIP;
        a ``.H`` flight stays a 2D-S, and a stem holding both keeps ``.H`` bare."""
        with tempfile.TemporaryDirectory() as d:
            decoded = Path(d)
            _make_fixture(decoded, "twods")
            (decoded / "proc.cipflight.CIP.nc").write_bytes(b"")
            _stamp_proc(decoded / "proc.cipflight.CIP.nc")
            (decoded / "cipflight.CIP.cdf").write_bytes(b"")
            (decoded / "proc.twods.CIP.nc").write_bytes(b"")
            _stamp_proc(decoded / "proc.twods.CIP.nc")
            flights = _discover_flights(decoded)
            self.assertEqual(flights["cipflight"]["probe"], "CIP")
            self.assertIsNotNone(flights["cipflight"]["image"])
            self.assertEqual(flights["twods"]["probe"], "2DS")
            self.assertEqual(flights["twods.CIP"]["probe"], "CIP")

    def test_2dc_and_fast2dc_flights_are_found_and_unrelated_files_are_not(self):
        """2DC, 2DP and Fast2DC became drivable 2026-09-20 (commit 034da39) --
        their ``proc.<flight>.2DC.nc`` / ``.Fast2DC.nc`` products must be
        discoverable the same way CIP/PIP already are (regression for the
        defect: :func:`_discover_flights`'s channel regex named only
        ``H|CIP|PIP`` and silently skipped the three newly-drivable probes).
        An unrelated file sitting in the same directory must not be swept in
        by whatever widens the token set."""
        with tempfile.TemporaryDirectory() as d:
            decoded = Path(d)
            (decoded / "proc.dcflight.2DC.nc").write_bytes(b"")
            _stamp_proc(decoded / "proc.dcflight.2DC.nc")
            (decoded / "dcflight.2DC.cdf").write_bytes(b"")
            (decoded / "proc.fastflight.Fast2DC.nc").write_bytes(b"")
            _stamp_proc(decoded / "proc.fastflight.Fast2DC.nc")
            (decoded / "fastflight.Fast2DC.cdf").write_bytes(b"")
            (decoded / "notes.txt").write_bytes(b"not a decoded product")
            flights = _discover_flights(decoded)
            self.assertEqual(flights["dcflight"]["probe"], "2DC")
            self.assertIsNotNone(flights["dcflight"]["image"])
            self.assertEqual(flights["fastflight"]["probe"], "Fast2DC")
            self.assertIsNotNone(flights["fastflight"]["image"])
            self.assertNotIn("notes", flights)
            self.assertEqual(len(flights), 2)


@unittest.skipUnless(HAVE_MPL and netCDF4 is not None, "matplotlib/netCDF4 not installed")
class HttpIntegrationTests(unittest.TestCase):
    """Real requests against a real server on an ephemeral localhost port."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls._tmp.name)
        _make_fixture(cls.dir, "flightA")
        TriageServer.decoded_dir = cls.dir
        TriageServer.reviewer = "test"  # every save names a reviewer
        cls.addClassCleanup(setattr, TriageServer, "reviewer", None)
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
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, body

    def _post(self, path, payload):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
        body = json.dumps(payload).encode()
        conn.request("POST", path, body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        out = resp.read()
        conn.close()
        return resp.status, out

    def test_index(self):
        status, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"flightA", body)

    def test_flight_page(self):
        # Fixture has 2 particles: index 0 (reject='0', accepted) and index 1
        # (reject='a', rejected) -- the default accepted view shows only 0.
        status, body = self._get("/flight/flightA?group=accepted&page=1")
        self.assertEqual(status, 200)
        self.assertIn(b"particle/flightA/0", body)

        status, body = self._get("/flight/flightA?group=rejected&page=1")
        self.assertEqual(status, 200)
        self.assertIn(b"particle/flightA/1", body)

    def test_unknown_flight_page_404(self):
        status, _ = self._get("/flight/doesnotexist?group=accepted&page=1")
        self.assertEqual(status, 404)

    def test_particle_page(self):
        status, body = self._get("/particle/flightA/1")
        self.assertEqual(status, 200)
        self.assertIn(b"image/flightA/1.png", body)

    def test_flight_page_carries_the_one_line_overview(self):
        """Track V phase 3: counts, commonest reject codes and size before any image."""
        status, body = self._get("/flight/flightA?group=accepted&page=1")
        self.assertEqual(status, 200)
        self.assertIn(b" accepted, ", body)
        self.assertIn(b"commonest codes:", body)
        self.assertIn(b"labelled by a person", body)

    def test_particle_page_names_the_engine_and_profile_that_wrote_it(self):
        """Track V phase 3: the verdict is about a product, and the page says which one."""
        status, body = self._get("/particle/flightA/1")
        self.assertEqual(status, 200)
        self.assertIn(b"written by engine <b>", body)
        self.assertNotIn(b"written by engine <b>unrecorded", body,
                         "the fixture's proc file is stamped, so its engine must show")

    def test_image_route(self):
        status, body = self._get("/image/flightA/1.png")
        self.assertEqual(status, 200)
        self.assertTrue(body.startswith(b"\x89PNG"))

    def test_unknown_flight_image_404(self):
        status, _ = self._get("/image/doesnotexist/1.png")
        self.assertEqual(status, 404)

    def test_thumb_route_is_a_valid_matplotlib_free_png(self):
        """Unlike /image, this never imports matplotlib --
        checked by the fact that it works at all in this test process without
        matplotlib.use('Agg') mattering to it, and that the bytes are a real
        PNG regardless."""
        status, body = self._get("/thumb/flightA/1.png")
        self.assertEqual(status, 200)
        self.assertTrue(body.startswith(b"\x89PNG"))

    def test_unknown_flight_thumb_404(self):
        status, _ = self._get("/thumb/doesnotexist/1.png")
        self.assertEqual(status, 404)

    def test_sheet_route_lists_thumbnails_for_the_group(self):
        status, body = self._get("/sheet/flightA?group=accepted&page=1")
        self.assertEqual(status, 200)
        self.assertIn(b"thumb/flightA/0.png", body)
        self.assertNotIn(b"thumb/flightA/1.png", body)  # index 1 is rejected

        status, body = self._get("/sheet/flightA?group=rejected&page=1")
        self.assertEqual(status, 200)
        self.assertIn(b"thumb/flightA/1.png", body)

    def test_unknown_flight_sheet_404(self):
        status, _ = self._get("/sheet/doesnotexist")
        self.assertEqual(status, 404)

    def test_flight_index_cache_is_built_on_first_use_and_reused(self):
        """The index sidecar this phase adds: built once under
        triage_index/<flight>.json, and a second flight-page request must
        not rebuild it (same mtime/size stamp survives)."""
        from arrayprobe.triage_server import _index_path

        index_path = _index_path(self.dir, "flightA")
        if index_path.exists():
            index_path.unlink()  # other tests in this class may have built it already
        status, _ = self._get("/flight/flightA?group=accepted&page=1")
        self.assertEqual(status, 200)
        self.assertTrue(index_path.is_file())
        first_bytes = index_path.read_bytes()

        status, _ = self._get("/flight/flightA?group=rejected&page=1")
        self.assertEqual(status, 200)
        self.assertEqual(index_path.read_bytes(), first_bytes,
                         "the cache was rewritten on a request that changed nothing on disk")

    def test_concurrent_requests_do_not_crash_the_server(self):
        """Regression for a real crash, root-caused TWICE, 2026-08-27.

        First pass: _render_image built figures via matplotlib.pyplot's
        global, NOT-thread-safe figure-manager registry -- concurrent renders
        (routine browser behavior on any page with more than one <img>)
        corrupted that shared state and killed the process with a native
        "Windows fatal exception: access violation." Fixed by switching to
        the private per-call Figure/FigureCanvasAgg object-oriented API
        (commit 789c104) -- necessary, but NOT sufficient: the server crashed
        again with the identical symptom shortly after, both faulted threads'
        last Python frame at a `netCDF4.Dataset(...)` open, not in matplotlib
        at all. netCDF4's underlying HDF5 C library is not guaranteed
        thread-safe for concurrent opens/reads across threads (the common
        conda build isn't compiled --enable-threadsafe) -- the real, complete
        fix is `_NC_LOCK`, a module-level `threading.Lock` every netCDF4call
        in this module (and the one call into particle_clustering, which
        opens its own) now holds for its entire duration.

        This test mixes /image, /flight, and /particle concurrently (not just
        repeated identical image requests) because the real second crash
        involved concurrent netCDF4 access from different routes, not just
        repeated renders. It only proves the server survives concurrent load
        with every response well-formed; it cannot reproduce either native
        crash on demand (both depended on real thread-timing), so it does
        not fail before either fix -- it exists to catch a regression.
        """
        import concurrent.futures

        def fetch_image(_):
            return self._get("/image/flightA/1.png")

        def fetch_flight(_):
            return self._get("/flight/flightA?group=accepted&page=1")

        def fetch_particle(_):
            return self._get("/particle/flightA/1")

        def fetch_thumb(_):
            return self._get("/thumb/flightA/1.png")

        def fetch_sheet(_):
            return self._get("/sheet/flightA?group=accepted&page=1")

        fetchers = [fetch_image, fetch_flight, fetch_particle, fetch_thumb, fetch_sheet] * 8
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(lambda f: f(None), fetchers))

        for status, body in results:
            self.assertEqual(status, 200)
            self.assertTrue(len(body) > 0)

    def test_verdict_post_roundtrip(self):
        status, body = self._post(
            "/verdict", {"flight": "flightA", "particle_index": 1, "verdict": "real"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["ok"], True)
        self.assertEqual(_load_verdicts(self.dir, "flightA")["1"]["verdict"], "real")

    def test_verdict_bulk_post_roundtrip(self):
        status, body = self._post(
            "/verdict_bulk",
            {"flight": "flightA", "particle_indices": [1, 2], "verdict": "artifact"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["n_labeled"], 2)

    def test_post_rejects_unknown_flight_and_writes_nothing_outside_triage_verdicts(self):
        """Regression test for the 2026-08-27 path-traversal fix."""
        before = set((self.dir / "triage_verdicts").glob("*"))
        malicious_names = ["../../evil", "..\\..\\evil", str(self.dir.parent / "pwned")]
        for name in malicious_names:
            status, _ = self._post(
                "/verdict", {"flight": name, "particle_index": 1, "verdict": "artifact"}
            )
            self.assertEqual(status, 404, f"flight={name!r} should be rejected")
        after = set((self.dir / "triage_verdicts").glob("*"))
        self.assertEqual(before, after, "a rejected flight must not write any file")
        self.assertFalse((self.dir.parent / "pwned.json").exists())

    def test_bulk_post_rejects_unknown_flight(self):
        status, _ = self._post(
            "/verdict_bulk", {"flight": "../evil", "particle_indices": [1], "verdict": "artifact"}
        )
        self.assertEqual(status, 404)

    def test_unknown_route_404(self):
        status, _ = self._get("/nonsense")
        self.assertEqual(status, 404)

    def test_post_rejects_a_verdict_outside_the_three_legitimate_values(self):
        """Real finding, 2026-08-27: `verdict` was accepted from the POST body
        with no validation at all, written to the sidecar JSON, and later
        interpolated into an HTML class attribute unescaped -- a stored-XSS
        path a same-origin script (or any local process) could reach directly,
        without going through the rendered verdict buttons at all. Particle
        index 97 is used by no other test in this file, to avoid polluting
        the shared class-level fixture directory other tests read."""
        status, _ = self._post(
            "/verdict",
            {"flight": "flightA", "particle_index": 97,
             "verdict": "x' onmouseover='alert(1)"},
        )
        self.assertEqual(status, 400)
        self.assertNotIn("97", _load_verdicts(self.dir, "flightA"))

    def test_a_malicious_verdict_written_before_validation_existed_is_escaped_on_render(self):
        """Defense in depth: even a sidecar file written before verdict
        validation existed (or hand-edited) must not inject HTML when the
        flight page renders it back. Particle index 98, same isolation
        reasoning as above."""
        # The *verdict* below is deliberately not one of VALID_VERDICTS: this
        # test is about a sidecar that was hand-edited or predates verdict
        # validation. The store now refuses such a verdict, so the sidecar is
        # edited directly, as a hand edit would be.
        sidecar = _verdicts_path(self.dir, "flightA")

        def _edit_sidecar(update):
            data = (json.loads(sidecar.read_text(encoding="utf-8"))
                    if sidecar.is_file() else {})
            update(data)
            sidecar.write_text(json.dumps(data, indent=1, sort_keys=True),
                               encoding="utf-8")

        self.addCleanup(_edit_sidecar, lambda d: d.pop("98", None))
        _edit_sidecar(lambda d: d.update({"98": {
            "verdict": "<script>alert(1)</script>", "note": "", "source": "human"}}))
        status, body = self._get("/flight/flightA?group=rejected&page=1")
        self.assertEqual(status, 200)
        self.assertNotIn(b"<script>alert(1)</script>", body)
        # Not treated as a real verdict class (it isn't one of the three
        # legitimate values) -- the escaped text still shouldn't leak
        # unescaped anywhere, including truncated into the badge.
        self.assertNotIn(b"class='pcard v-<script>", body)

    def test_malformed_post_body_returns_500_not_a_dropped_connection(self):
        """do_POST previously had no exception handling, unlike do_GET's
        documented "surface the error, don't crash" philosophy -- a
        malformed body used to raise inside the request thread with no
        response sent at all."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
        conn.request("POST", "/verdict", body=b"not json",
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        self.assertEqual(resp.status, 500)
        self.assertIn(b"JSONDecodeError", body)

    def test_post_missing_required_field_returns_500_not_a_dropped_connection(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
        body = json.dumps({"flight": "flightA", "verdict": "real"}).encode()  # no particle_index
        conn.request("POST", "/verdict", body=body,
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        out = resp.read()
        conn.close()
        self.assertEqual(resp.status, 500)
        self.assertIn(b"KeyError", out)


@unittest.skipUnless(HAVE_MPL and netCDF4 is not None, "matplotlib/netCDF4 not installed")
class QueueTests(unittest.TestCase):
    """A curated review list for a specific pass -- built 2026-08-27, the direct
    answer to a real "I don't know where to provide labels" moment reviewing
    task #27's Method A labeled set."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls._tmp.name)
        _make_fixture(cls.dir, "flightA")
        TriageServer.decoded_dir = cls.dir
        TriageServer.reviewer = "test"  # every save names a reviewer
        cls.addClassCleanup(setattr, TriageServer, "reviewer", None)
        TriageServer.queues = {
            "test_queue": [
                {"flight": "flightA", "particle_index": 0, "note": "the accepted one"},
                {"flight": "flightA", "particle_index": 1, "note": "the rejected one"},
            ],
        }
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
        TriageServer.queues = {}   # don't leak into other test classes sharing the class attr

    def _get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, body

    def _post(self, path, payload):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
        body = json.dumps(payload).encode()
        conn.request("POST", path, body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        out = resp.read()
        conn.close()
        return resp.status, out

    def test_queue_list_shows_the_configured_queue(self):
        status, body = self._get("/queue")
        self.assertEqual(status, 200)
        self.assertIn(b"test_queue", body)

    def test_unknown_queue_is_404(self):
        status, _ = self._get("/queue/does_not_exist")
        self.assertEqual(status, 404)

    def test_queue_index_lists_both_items(self):
        status, body = self._get("/queue/test_queue")
        self.assertEqual(status, 200)
        self.assertIn(b"flightA #0", body)
        self.assertIn(b"flightA #1", body)
        self.assertIn(b"the accepted one", body)

    def test_queue_particle_position_out_of_range_is_404(self):
        status, _ = self._get("/queue/test_queue/2")
        self.assertEqual(status, 404)
        status, _ = self._get("/queue/test_queue/-1")
        self.assertEqual(status, 404)

    def test_queue_particle_page_renders_and_has_nav(self):
        status, body = self._get("/queue/test_queue/0")
        self.assertEqual(status, 200)
        # These assert the nav ANCHOR, not the word. They were written against
        # the words "next"/"previous" and broke on 2026-09-16 when the page
        # gained a keyboard-shortcut hint and a key handler that both mention
        # those words -- the page was correct and the proxy was not. Keying on
        # `data-nav`, which is also what the keyboard handler resolves, tests the
        # thing the test is named for: whether the link is there.
        self.assertIn(b"Item 1 of 2", body)   # heading now leads with the spelled-out queue title
        self.assertIn(b"data-nav='next'", body)
        self.assertNotIn(b"data-nav='prev'", body)   # first item, no prev link

        status, body = self._get("/queue/test_queue/1")
        self.assertEqual(status, 200)
        self.assertIn(b"Item 2 of 2", body)
        self.assertIn(b"data-nav='prev'", body)
        self.assertNotIn(b"data-nav='next'", body)   # last item, no next link

    def test_saving_a_verdict_via_the_normal_route_shows_up_in_the_queue_index(self):
        status, _ = self._post(
            "/verdict", {"flight": "flightA", "particle_index": 0, "verdict": "real"}
        )
        self.assertEqual(status, 200)
        status, body = self._get("/queue/test_queue")
        self.assertEqual(status, 200)
        self.assertIn(b"real", body)

    def test_queue_particle_references_unknown_flight_does_not_crash(self):
        TriageServer.queues["broken"] = [{"flight": "no_such_flight", "particle_index": 0}]
        try:
            status, body = self._get("/queue/broken/0")
            self.assertEqual(status, 200)   # renders a "not found" message, not a 500
            self.assertIn(b"unknown flight", body)
        finally:
            del TriageServer.queues["broken"]


class LoadQueueFileTests(unittest.TestCase):
    def test_round_trips_a_real_file(self):
        from arrayprobe.triage_server import _load_queue_file
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "q.json"
            p.write_text(json.dumps({
                "my_queue": [{"flight": "f1", "particle_index": 5, "note": "x"}],
            }))
            queues = _load_queue_file(p)
            self.assertEqual(queues["my_queue"][0]["particle_index"], 5)

    def test_metadata_keys_are_not_installed_as_queues(self):
        """An `_about`/`_coverage` block rode through as a queue and crashed /queue
        with `string indices must be integers` (VA1's spotcheck.json, 2026-09-15).
        The loader keeps it (test_review_sampling); the install drops it."""
        from arrayprobe.triage_server import _load_queue_file, _review_queues
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "q.json"
            p.write_text(json.dumps({
                "_about": {"seed": 1, "note": "metadata"},
                "_coverage": {"q": "all of it"},
                "q": [{"flight": "f1", "particle_index": 0}],
            }))
            loaded = _load_queue_file(p)
            self.assertIn("_about", loaded)
            self.assertEqual(list(_review_queues(loaded)), ["q"])

    def test_missing_required_field_raises(self):
        from arrayprobe.triage_server import _load_queue_file
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "q.json"
            p.write_text(json.dumps({"q": [{"flight": "f1"}]}))   # no particle_index
            with self.assertRaises(ValueError):
                _load_queue_file(p)


def _make_large_fixture(decoded_dir: Path, flight: str, n_particles: int = 20000):
    """A synthetic proc file with many particles, for the Phase 1 speed exit
    criteria ("flight page < 200 ms ... on the tracked
    fixture"). Generated at test time rather than committed as a large
    binary, matching this project's convention for reproducible large-scale
    tests without a checked-in multi-particle netCDF (`make_demo_flight.py`
    does the same for the raw-decode chain). Every particle points at the
    same single image record -- the reject/diameter arrays are what
    `_render_flight`'s `np.where`/`np.argsort` actually costs time on, and
    the image file only needs to exist, not be large, since no image route
    is exercised by the timing test below.
    """
    block = np.zeros((1700, 8), dtype=np.uint16)
    block[0:3, :] = 65535
    _make_image_file(decoded_dir / f"{flight}.H.cdf", [block])
    rng = np.random.default_rng(0)
    particles = [
        {
            "parent_rec_num": 0, "start": 0, "end": 2, "width": 8, "length": 3,
            "reject": "0" if rng.random() < 0.7 else "a",
            "diam": float(rng.uniform(0.05, 2.0)),
        }
        for _ in range(n_particles)
    ]
    _make_proc_file(decoded_dir / f"proc.{flight}.H.nc", particles)


@unittest.skipUnless(HAVE_MPL and netCDF4 is not None, "matplotlib/netCDF4 not installed")
class FlightPageSpeedTests(unittest.TestCase):
    """Exit criteria: flight page < 200 ms, thumbnail
    < 5 ms, on a tracked (here: generated) fixture, with a generous ceiling
    per the plan's own wording rather than a flaky tight one.

    Both ceilings are measured against the SECOND request onward -- the
    first request against a flight with no cached index pays the one-time
    index-build cost the whole point of this phase is to move out of the
    per-request path, and timing that cost would be timing the wrong thing.
    """

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls._tmp.name)
        _make_large_fixture(cls.dir, "bigflight", n_particles=20000)
        TriageServer.decoded_dir = cls.dir
        TriageServer.reviewer = "test"  # every save names a reviewer
        cls.addClassCleanup(setattr, TriageServer, "reviewer", None)
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
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, body

    def _timed_get(self, path):
        import time
        t0 = time.perf_counter()
        status, body = self._get(path)
        return status, body, time.perf_counter() - t0

    def test_flight_page_is_fast_once_the_index_is_cached(self):
        """Fixed 2026-09-15 (T1) alongside ``test_thumbnail_is_fast``
        below: the same flaw, found failing on this machine in the same
        session (316.9 ms median over three requests, over the plan's flat
        200 ms ceiling, with no code change under it) -- a flat wall-clock
        ceiling on a machine whose load varies run to run.

        Same fix, adapted for a real HTTP round trip rather than an
        in-process call: normalise against ``/`` (the index page), a real
        request over the same connection-per-request machinery -- OS
        connect/dispatch, ``ThreadingHTTPServer`` accept/dispatch, Python's
        own ``http.client`` -- but doing none of the 20,000-particle
        `_render_flight` work, so it isolates that fixed per-request
        overhead the same way the calibration workload isolates CPU
        contention in ``test_thumbnail_is_fast``. min per batch of 6
        requests (10 for the index, which is much cheaper and needs more
        samples to pin its own min down); median of four batches' ratios
        (one unlucky batch cannot flip the result).

        T1's 7.0 ratio ceiling (now 7.5, below) was measured:
        the unmutated route's median-of-batches ratio was 4.15-5.14
        across 3 runs on this loaded machine (worst single batch 7.73).
        A mutation that runs the whole ``_render_flight`` call **twice**
        per request (the shape of a real regression -- an accidental
        double-render in the route dispatch, not synthetic sleep) pushed
        the same statistic to 8.65-11.69 across 3 runs on the same loaded
        machine -- a smaller relative jump than the CPU-only thumbnail
        test (real per-request cost here is a smaller fraction of the
        total than in-process thumbnail generation is, since a fresh TCP
        connection's own OS-level jitter contributes to both numerator and
        denominator), but never once below 7.0. A first attempt at this
        mutation (doubling only the internal ``_selected_particles`` cache
        read, not the whole route) did *not* separate cleanly from
        baseline (6.43-12.47 vs. baseline's 3.35-7.66) -- evidence that
        ``_selected_particles``'s disk-cache read is not what dominates
        this route's cost, so the mutation was moved to wrap the whole
        route instead of guessing further.

        **Made load-robust 2026-09-15 (I3-T).**
        T1's single round still failed under other
        agents' load (median batch ratio 8.20; batches 11.55, 9.70, 6.70,
        4.89). Three changes, none a looser criterion: index and flight
        requests are now *interleaved* (index, index, flight) so both sides
        see the same load; the whole round is *retried* up to
        :attr:`_TIMING_ROUNDS` times and the test fails only if every round
        is over the ceiling (a real regression is slow in all of them, load
        noise is not); and one uncounted warm-up round runs first, because a
        fresh process's first doubled-render round came out low (5.35-7.73)
        often enough that a retry loop would have accepted it. Ceiling
        re-derived at **7.5** from single-round distributions on this machine
        (i7-1365U, 2 P + 8 E cores, 20-37 other agents' processes, with and
        without 8 CPU burners): unmutated rounds 3.2-7.9 (the upper end only
        in the heaviest ambient stretch, where every *test* still found a
        round at 6.4-6.9); doubled-render rounds after warm-up 7.75-14.8 and
        whole-test minima 8.15-12.0. Measured with the fix: 20/20 passes under
        burners, 15/15 without; the doubled render failed 5/5 under burners,
        5/5 without, and 2/2 as a source edit.
        """
        # Prime the cache -- this first request's own time is not asserted.
        status, _ = self._get(self._FLIGHT_URL)
        self.assertEqual(status, 200)
        self._get("/")  # prime the index route too

        rounds = self._rounds_until_under(self._flight_round, self._FLIGHT_CEILING)

        # Absolute backstop: generous, because the ratio below is the
        # binding criterion. Every measured baseline min here, loaded or
        # not, stayed under 100 ms.
        flight_min_ms = min(m for _s, _r, mins in rounds for m in mins)
        self.assertLess(
            flight_min_ms, 1000.0,
            f"flight page min {flight_min_ms:.1f} ms over {len(rounds)} "
            f"round(s) is implausibly slow regardless of machine load")

        best = min(stat for stat, _r, _m in rounds)
        self.assertLess(
            best, self._FLIGHT_CEILING,
            f"flight-page/index ratio exceeded {self._FLIGHT_CEILING} in every "
            f"one of {len(rounds)} rounds (round statistics: "
            f"{[f'{s:.2f}' for s, _r, _m in rounds]}; batch ratios per round: "
            f"{[[f'{x:.2f}' for x in r] for _s, r, _m in rounds]}); load noise "
            f"clears in some round, a real regression is slow in all of them. "
            f"The plan's 200 ms exit criterion tracks this "
            f"ratio, not the raw wall-clock time")

    _FLIGHT_URL = "/flight/bigflight?group=accepted&page=1"

    #: Rounds a ratio test may take before it fails. A round is the whole
    #: calibration+measurement statistic; the test passes on the first round
    #: under its ceiling and fails only if all of them are over it.
    _TIMING_ROUNDS = 5
    _FLIGHT_CEILING = 7.5
    _THUMB_CEILING = 1.8

    def _rounds_until_under(self, round_fn, ceiling):
        """Run ``round_fn`` up to :attr:`_TIMING_ROUNDS` times, stopping at the
        first round whose statistic is under ``ceiling``; return every round
        taken as ``(statistic, batch_ratios, batch_mins_ms)``.

        One uncounted warm-up round runs first. Measured:
        the first round in a fresh process is unrepresentative -- the flight
        ratio's first round came out *low* in 3 of 4 doubled-render runs
        (5.35, 6.79, 7.45 against a post-warm-up floor of 7.99), which a
        retry-until-under loop would otherwise accept as a pass."""
        round_fn()
        rounds = []
        for _ in range(self._TIMING_ROUNDS):
            rounds.append(round_fn())
            if rounds[-1][0] < ceiling:
                break
        return rounds

    def _flight_round(self):
        """One round of the flight-page ratio: four batches, each interleaving
        12 index GETs with 6 flight-page GETs (index, index, flight, ...), so
        both sides are sampled across the same stretch of machine load; min
        per side per batch; the statistic is the median of the four batch
        ratios."""
        import statistics

        ratios, flight_mins_ms = [], []
        for _batch in range(4):
            index_t, flight_t = [], []
            for _ in range(6):
                index_t.append(self._timed_get("/")[2])
                index_t.append(self._timed_get("/")[2])
                flight_t.append(self._timed_get(self._FLIGHT_URL)[2])
            flight_mins_ms.append(min(flight_t) * 1000)
            ratios.append(min(flight_t) / min(index_t))
        return statistics.median(ratios), ratios, flight_mins_ms

    def test_thumbnail_is_fast(self):
        """The plan's "< 5 ms" is the generation cost :func:`particle_thumbnail_png`
        actually adds -- not a fresh-TCP-connection HTTP round trip, which on
        this machine carries several ms of OS-level connect/dispatch jitter of
        its own regardless of how fast the PNG encoder is (measured: a plain
        HTTP GET of a trivial route here already varies 4-27 ms run to run).
        Timed in-process, the same way the module itself would be profiled.

        Fixed 2026-09-15 (T1): the previous form asserted a wall-clock
        *median* of 20 calls against a flat 5 ms ceiling. Under a quiet
        machine that tracks the plan's exit criterion fine, but this machine
        can carry ~20 concurrent agents, and under that load the median rose
        to 8.9-16.6 ms with zero code changes underneath it (`git log
        --since=2026-09-12 -- src/arrayprobe/render.py` is empty) -- a test
        of the machine, not of the code.

        Two changes, deliberately not a looser ceiling (that would weaken the
        criterion, not fix it):

        1. **min, not median, per batch.** System noise (scheduler
           preemption, a sibling process's CPU burst) can only make a call
           slower than its true cost, never faster, so the minimum over
           repeated calls is the standard estimator for "cost of the
           operation" (the same reasoning the stdlib ``timeit`` module's own
           docs give for why it reports the best of several repetitions
           rather than an average).
        2. **Normalised against an in-process calibration workload**, timed
           immediately alongside each batch. A single global slowdown (CPU
           contention, thermal throttling) inflates the calibration cost by
           roughly the same factor it inflates the real one, so the *ratio*
           stays put even when the absolute numbers do not -- exactly the
           "scale both sides" idea the CPU-contention problem calls for.
           T1's calibration was pure-Python integer arithmetic; I3-T replaced
           it (below) because it did not scale with the thumbnail.

        Three batches of (calibration min, thumbnail min); the asserted
        statistic is the **median of the three ratios**, so one unlucky batch
        (a single burst landing entirely inside one batch) cannot flip the
        result on its own -- the same "best of several tries, not any one
        try" idea as the retried rounds of the flight-page test above.

        (T1's statistic, superseded below.) The 0.10 ratio ceiling is
        measured, not guessed:
        the unmutated function's median-of-batches ratio was 0.032-0.093
        across 8 independent runs on this loaded machine (worst single batch
        0.093, worst run-level median 0.066) -- comfortable headroom under
        0.10. A mutation that does the whole
        reconstruct+crop+encode pipeline **twice** per call (the shape of a
        real regression: an accidental double-render, not synthetic sleep)
        pushed the same statistic to 0.152-0.304 across 8 runs on the same
        loaded machine -- never once below 0.10. A generous absolute
        backstop stays in place underneath the ratio, in case a future
        regression somehow inflates calibration and the real cost in lockstep
        (unlikely for a pure-arithmetic calibration workload, but a wall-clock
        assertion with no absolute ceiling at all is its own kind of trap).

        **Reworked 2026-09-15 (I3-T).**
        T1's statistic still failed under other
        agents' load (0.138-0.156), and the cause was measured, not guessed:
        on this hybrid CPU (i7-1365U, 2 P + 8 E cores) the pure-Python
        calibration's min moved 4.7-14.4 ms between consecutive rounds while
        the thumbnail's stayed at 0.41-0.50 ms, so the ratio tracked where the
        scheduler put the process (T1's rounds: 0.025-0.20 across conditions,
        median 0.13 in one ambient stretch -- the old test failing most of the
        time). The thumbnail is ~90 % a netCDF4 C-library read, which core
        placement barely moves; bytecode it moves a lot. Now:

        - **Calibration = the raw netCDF4 reads the reconstruction rests on**
          (:meth:`_thumbnail_calibration`, netCDF4/numpy only, no arrayprobe
          code), so it shares the thumbnail's resource mix; doubled arrayprobe
          work still doubles only the numerator.
        - **Interleaved** (one calibration, three thumbnails, repeated), and
          the round is **retried** up to :attr:`_TIMING_ROUNDS` times after
          one uncounted warm-up round; the test fails only if every round is
          over the ceiling.
        - **Ceiling re-derived at 1.8** from the new statistic's single-round
          distributions, with and without 8 CPU burners: unmutated 0.98-1.60
          (median 1.22, one 0.42 outlier), doubled pipeline 1.95-5.22
          (median 2.6). Measured with the fix: 20/20 passes (10 under burners,
          10 without; counted rounds 0.94-1.31); the doubled pipeline failed
          5/5 under burners, 5/5 without (every round 2.08-3.17), and 2/2 as
          a source edit to ``render.py``.
        """
        import netCDF4

        from arrayprobe.render import particle_thumbnail_png

        flights_dir = self.dir
        img_path = flights_dir / "bigflight.H.cdf"
        proc_path = flights_dir / "proc.bigflight.H.nc"
        with netCDF4.Dataset(img_path) as img_ds, netCDF4.Dataset(proc_path) as proc_ds:
            png = particle_thumbnail_png(img_ds, proc_ds, 0)  # warm any import-time cost
            rounds = self._rounds_until_under(
                lambda: self._thumbnail_round(
                    lambda: particle_thumbnail_png(img_ds, proc_ds, 0),
                    lambda: self._thumbnail_calibration(img_ds, proc_ds)),
                self._THUMB_CEILING)
        self.assertTrue(png.startswith(b"\x89PNG"))

        # Absolute backstop: generous, because it exists only to catch a
        # slowdown that inflates the netCDF4-read calibration in lockstep
        # (e.g. in the netCDF4 library itself) -- the ratio below is the
        # binding criterion. Every measured baseline min here, loaded or not,
        # stayed under 3 ms; 50 ms is a wide margin, not a tight one.
        thumb_min_ms = min(m for _s, _r, mins in rounds for m in mins)
        self.assertLess(
            thumb_min_ms, 50.0,
            f"thumbnail generation min {thumb_min_ms:.3f} ms over "
            f"{len(rounds)} round(s) is implausibly slow regardless of "
            f"machine load")

        best = min(stat for stat, _r, _m in rounds)
        self.assertLess(
            best, self._THUMB_CEILING,
            f"thumbnail/calibration ratio exceeded {self._THUMB_CEILING} in "
            f"every one of {len(rounds)} rounds (round statistics: "
            f"{[f'{s:.4f}' for s, _r, _m in rounds]}; batch ratios per round: "
            f"{[[f'{x:.4f}' for x in r] for _s, r, _m in rounds]}); load noise "
            f"clears in some round, a real regression is slow in all of them. "
            f"The plan's 5 ms exit criterion tracks this ratio, "
            f"not the raw wall-clock time")

    @staticmethod
    def _thumbnail_calibration(img_ds, proc_ds):
        """The raw netCDF4 reads a thumbnail's reconstruction rests on, done
        directly with netCDF4/numpy and no arrayprobe code: the same resource
        mix as the thumbnail (a C-library read, then numpy), so it slows down
        and speeds up with the thumbnail rather than independently of it."""
        int(proc_ds.variables["parent_rec_num"][0])
        np.asarray(proc_ds.variables["position"][0])
        return np.asarray(img_ds.variables["data"][0, :, :])

    def _thumbnail_round(self, thumb_fn, cal_fn):
        """One round of the thumbnail ratio: three batches, each interleaving
        8 calibration calls with 24 thumbnail calls (one calibration, then
        three thumbnails, repeated), so both sides are sampled across the same
        stretch of machine load; min per side per batch; the statistic is the
        median of the three batch ratios."""
        import statistics
        import time

        ratios, thumb_mins_ms = [], []
        for _batch in range(3):
            cal_t, thumb_t = [], []
            for _ in range(8):
                t0 = time.perf_counter()
                cal_fn()
                cal_t.append(time.perf_counter() - t0)
                for _ in range(3):
                    t0 = time.perf_counter()
                    thumb_fn()
                    thumb_t.append(time.perf_counter() - t0)
            thumb_mins_ms.append(min(thumb_t) * 1000)
            ratios.append(min(thumb_t) / min(cal_t))
        return statistics.median(ratios), ratios, thumb_mins_ms

    def test_thumb_route_never_renders_through_matplotlib_and_the_image_route_does(self):
        """The thumbnail route's speed comes from one structural fact: it
        never builds a matplotlib figure, while ``/image`` builds one per
        request. That is counted here, over real HTTP, by wrapping
        ``matplotlib.figure.Figure.savefig`` (the wrapper delegates, so both
        routes' output is unchanged). Both routes must still return a PNG.

        This test used to compare best-of-8 wall-clock times of the two routes;
        a comparison of two wall-clock minima under concurrent load measures
        the scheduler as much as the code, so it now asserts the cause of the
        speed-up rather than its size. The size is the subject of
        ``test_thumbnail_is_fast`` above.
        """
        from unittest import mock

        from matplotlib.figure import Figure

        real_savefig = Figure.savefig
        saves = []

        def counting_savefig(fig, *args, **kwargs):
            saves.append(1)
            return real_savefig(fig, *args, **kwargs)

        n = 4
        with mock.patch.object(Figure, "savefig", counting_savefig):
            for _ in range(n):
                status, body = self._get("/thumb/bigflight/0.png")
                self.assertEqual(status, 200)
                self.assertTrue(body.startswith(b"\x89PNG"))
            thumb_saves = len(saves)
            saves.clear()
            for _ in range(n):
                status, body = self._get("/image/bigflight/0.png")
                self.assertEqual(status, 200)
                self.assertTrue(body.startswith(b"\x89PNG"))
            image_saves = len(saves)

        self.assertEqual(
            thumb_saves, 0,
            f"{n} /thumb requests rendered {thumb_saves} matplotlib figure(s); "
            f"the thumbnail route must stay matplotlib-free")
        self.assertEqual(
            image_saves, n,
            f"{n} /image requests rendered {image_saves} matplotlib figure(s); "
            f"expected one each, or this test is not watching the right call")

    #: Flight-page requests per side. Enough that "once" and "every time"
    #: cannot be confused (1 against 5), cheap enough to stay a few seconds.
    _CACHE_REQUESTS = 5

    def test_the_index_cache_is_what_makes_the_flight_page_fast(self):
        """The cache's guarantee is structural: with the index sidecar in
        place, a flight-page request does not rebuild the index (the full
        netCDF read of ``image_auto_reject``/``image_diam_minR`` over 20,000
        particles, :func:`_build_flight_index`); without it, every request
        does. That is counted here, not timed, so machine load cannot move it.

        The build function is wrapped with a counter through
        ``mock.patch.object`` on the module global that :func:`_flight_index`
        calls, so the server's behaviour and output are unchanged (the wrapper
        delegates). The server thread runs in this process, so the counter
        sees every request's call.

        - Cache kept: sidecar deleted once, then N requests. Exactly one build
          (the first request), and the sidecar exists afterwards.
        - Cache removed before each request: N requests, N builds.
        - Every page body is identical across both regimes, so the cached path
          serves the same page the build path does.

        History: this test used to compare wall-clock medians (cached under
        0.75 x uncached over five interleaved pairs), with a skip when the
        samples spread more than five-fold. It failed in the full suite of
        2026-09-25 (cached 53.1 ms against uncached 68.6 ms, limit 51.5 ms)
        while twelve SODA-2 workers loaded the machine, and passed alone. A
        ratio of two wall-clock medians measures the scheduler as much as the
        code. Process CPU time was considered and rejected: on Windows
        ``time.process_time`` advances in ~15.6 ms ticks, the same order as
        the quantity being measured, and under load it still carries cache and
        clock-frequency effects. The count is exact.
        """
        from unittest import mock

        from arrayprobe import triage_server
        from arrayprobe.triage_server import _index_path

        url = self._FLIGHT_URL
        index_path = _index_path(self.dir, "bigflight")
        # Do not depend on another test method's execution order to have
        # built this: prime it here explicitly, and restore it at the end.
        status, reference_body = self._get(url)
        self.assertEqual(status, 200)
        self.assertTrue(index_path.is_file())
        cached_bytes = index_path.read_bytes()

        real_build = triage_server._build_flight_index
        builds = []

        def counting_build(proc_path):
            builds.append(proc_path)
            return real_build(proc_path)

        n = self._CACHE_REQUESTS
        try:
            with mock.patch.object(triage_server, "_build_flight_index",
                                   counting_build):
                # Cache kept: one cold request builds, the rest reuse.
                index_path.unlink()
                for _ in range(n):
                    status, body = self._get(url)
                    self.assertEqual(status, 200)
                    self.assertEqual(body, reference_body)
                builds_with_cache = len(builds)
                self.assertTrue(index_path.is_file(),
                                "the first request must write the index sidecar")

                # Cache removed before every request: every request builds.
                builds.clear()
                for _ in range(n):
                    index_path.unlink()
                    status, body = self._get(url)
                    self.assertEqual(status, 200)
                    self.assertEqual(body, reference_body)
                builds_without_cache = len(builds)
        finally:
            # Leave the cache as it was for any other test in this class.
            index_path.write_bytes(cached_bytes)

        self.assertEqual(
            builds_with_cache, 1,
            f"with the sidecar in place, {n} flight-page requests rebuilt the "
            f"index {builds_with_cache} times; the cache must make it once")
        self.assertEqual(
            builds_without_cache, n,
            f"with the sidecar removed before each of {n} requests, the index "
            f"was built {builds_without_cache} times; an uncached request must "
            f"pay the build, or this test is not measuring the cache")



class QueuePartnerTests(unittest.TestCase):
    """Track V phase 3's side-by-side view: a queue item names
    the same particle in another product, and the queue page shows it below the one labelled."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls._tmp.name)
        _make_fixture(cls.dir, "flightA")
        _make_fixture(cls.dir, "flightB")
        TriageServer.decoded_dir = cls.dir
        TriageServer.reviewer = "test"  # every save names a reviewer
        cls.addClassCleanup(setattr, TriageServer, "reviewer", None)
        TriageServer.queues = {"pair-v3.1.4-0-v3.5-t": [
            {"flight": "flightA", "particle_index": 1, "note": "v3.1.4 0 / v3.5 t",
             "compare": {"flight": "flightB", "particle_index": 1, "label": "v3.5"}},
            {"flight": "flightA", "particle_index": 0, "note": "no partner"}]}
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
        TriageServer.queues = {}

    def _get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, body

    def test_the_partner_is_shown_beside_the_labelled_particle(self):
        status, body = self._get("/queue/pair-v3.1.4-0-v3.5-t/0")
        self.assertEqual(status, 200)
        self.assertIn(b"The same particle in v3.5: flightB #1", body)
        self.assertIn(b"/image/flightB/1.png", body)
        self.assertIn(b"/image/flightA/1.png", body)

    def test_an_item_without_a_partner_renders_as_before(self):
        status, body = self._get("/queue/pair-v3.1.4-0-v3.5-t/1")
        self.assertEqual(status, 200)
        self.assertNotIn(b"The same particle in", body)

if __name__ == "__main__":
    unittest.main()


class QueueProgressCountsChannelSuffixedFlights(unittest.TestCase):
    """Progress must count labels that were actually saved.

    THE BUG, 2026-09-16, hit by the author mid-labelling-pass. The ACE-ENA queue
    names every item ``base170707102822.H``; ``_discover_flights`` gives the bare
    stem to whichever channel wins, so verdicts are stored under
    ``base170707102822``. The progress counters looked up the RAW queue name,
    opened a verdict file that does not exist, counted nothing, and reported
    ``0 / 20`` to someone who had just labelled twenty particles. The labels were
    safe throughout -- only the count lied, which is worse than it sounds: it is
    the kind of thing that makes a reviewer redo work or stop trusting the tool.
    """

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls._tmp.name)
        _make_fixture(cls.dir, "flightA")
        TriageServer.decoded_dir = cls.dir
        TriageServer.reviewer = "test"  # every save names a reviewer
        cls.addClassCleanup(setattr, TriageServer, "reviewer", None)
        # The queue names the channel explicitly -- as the real ENA queue does.
        TriageServer.queues = {
            "chan_queue": [
                {"flight": "flightA.H", "particle_index": 0},
                {"flight": "flightA.H", "particle_index": 1},
            ],
        }
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
        TriageServer.queues = {}

    def _get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, body

    def _post(self, path, payload):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
        conn.request("POST", path, body=json.dumps(payload).encode(),
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        resp.read()
        conn.close()
        return resp.status

    def test_a_saved_label_is_counted_on_both_pages(self):
        status, body = self._get("/")
        self.assertEqual(200, status)
        self.assertIn(b"0 / 2", body)          # nothing labelled yet

        # Label one, through the route the button uses.
        self.assertEqual(200, self._post("/verdict", {
            "flight": "flightA", "particle_index": 0,
            "verdict": "real", "queue": "chan_queue"}))

        status, body = self._get("/")
        self.assertEqual(200, status)
        self.assertIn(b"1 / 2", body,
                      "the front page must count a label that was actually saved; "
                      "0 / 2 here is the channel-suffix lookup bug returning")

        status, body = self._get("/queue")
        self.assertEqual(200, status)
        self.assertIn(b"1 / 2 labeled", body)

    def test_the_front_page_shows_queue_progress_at_all(self):
        """It used to show only a bare link, which is where the confusion began."""
        _, body = self._get("/")
        self.assertIn(b"Review queues", body)
        self.assertIn(b"chan_queue", body)
