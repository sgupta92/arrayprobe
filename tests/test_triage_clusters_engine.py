# SPDX-License-Identifier: BSD-3-Clause
"""The triage Clusters page clusters a proc file with the engine that wrote it.

``particle_clustering.cluster_flight`` defaults to ``engine="3.1.4"``, whose feature list
needs v3.1.4-only proc variables (``image_diam_circle_fit``); on a v3.5 proc -- the default
engine's product -- that default raises ``MissingProcVariable``. The page must therefore pass
the engine read from the proc file's ``.call`` stamp, reading a stamp that names no engine as
v3.1.4 (the documented convention for pre-2026-09-15 stamps).
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arrayprobe import triage_server
from arrayprobe_uiops import provenance


class _FakeHandler:
    def __init__(self, decoded_dir: Path, flights: dict):
        self.decoded_dir = decoded_dir
        self._f = flights

    def _flights(self):
        return self._f


class ClustersPassTheProcEngine(unittest.TestCase):
    def _engine_passed(self, **stamp) -> str:
        seen = {}

        def fake_cluster_flight(proc_path, **kw):
            seen.update(kw)
            raise ValueError("stop after recording the call")

        with tempfile.TemporaryDirectory() as d:
            decoded = Path(d)
            proc = decoded / "proc.f1.H.nc"
            proc.write_bytes(b"")
            image = decoded / "f1.H.cdf"
            image.write_bytes(b"")
            if stamp:
                provenance.write(proc, **stamp)
            flights = {"f1": {"proc": proc, "image": image,
                              "stamp": provenance.read(proc)}}
            with mock.patch.object(triage_server, "_cluster_flight", fake_cluster_flight):
                triage_server.TriageServer._render_clusters(
                    _FakeHandler(decoded, flights), "f1", "accepted", None)
        self.assertIn("engine", seen, "cluster_flight was called without an engine")
        return seen["engine"]

    def test_a_v35_proc_is_clustered_as_v35(self):
        self.assertEqual(
            self._engine_passed(engine="3.5", profile="stock-v3.5", stage="S3"), "3.5")

    def test_a_v314_proc_is_clustered_as_v314(self):
        self.assertEqual(
            self._engine_passed(engine="3.1.4", profile="oracles-production", stage="S3"),
            "3.1.4")

    def test_a_proc_whose_stamp_names_no_engine_is_read_as_v314(self):
        self.assertEqual(self._engine_passed(), "3.1.4")


if __name__ == "__main__":
    unittest.main()
