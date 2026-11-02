# SPDX-License-Identifier: BSD-3-Clause
"""The run-level outputs manifest lists only the files the run itself wrote, and a sidecar it
cannot decode never drops the manifest (driver ``write_outputs_manifest``)."""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from tests._run_flight_state import preserve

from arrayprobe.driver import run_flight


class TestManifestScope(unittest.TestCase):
    def setUp(self):
        preserve(self, run_flight)
        self.out = Path(tempfile.mkdtemp())

    def _touch(self, name: str, when: float | None = None) -> Path:
        p = self.out / name
        p.write_bytes(b"x")
        if when is not None:
            os.utime(p, (when, when))
        return p

    def _listed(self, manifest: Path) -> set[str]:
        return {e["path"] for e in json.loads(manifest.read_text(encoding="utf-8"))["outputs"]}

    def test_a_second_run_into_the_same_out_does_not_list_the_first_runs_files(self):
        past = time.time() - 3600
        # Run 1 (an hour ago): flight A.
        self._touch("A.combined.H.2DS_2.cdf", past)
        self._touch("A.combined.H.2DS_2.attributed.nc", past)
        self._touch("rawA.arm.nc", past)
        # Run 2 (now): flight B into the same folder.
        started = time.time()
        self._touch("B.combined.H.2DS_2.cdf")
        self._touch("B.combined.H.2DS_2.attributed.nc")
        self._touch("rawB.arm.nc")
        target = run_flight.write_outputs_manifest(self.out, ["rawB"], since=started)
        self.assertIsNotNone(target)
        self.assertEqual(target.name, "B.outputs.json")
        self.assertEqual(self._listed(target), {"B.combined.H.2DS_2.cdf",
                                                "B.combined.H.2DS_2.attributed.nc",
                                                "rawB.arm.nc"})

    def test_a_stale_zarr_store_is_not_listed(self):
        past = time.time() - 3600
        store = self.out / "A.combined.H.2DS_2.attributed.zarr"
        store.mkdir()
        (store / "zarr.json").write_bytes(b"{}")
        os.utime(store / "zarr.json", (past, past))
        os.utime(store, (past, past))
        started = time.time()
        self._touch("rawB.arm.nc")
        target = run_flight.write_outputs_manifest(self.out, ["rawB"], since=started)
        self.assertEqual(self._listed(target), {"rawB.arm.nc"})

    def test_a_fresh_parquet_directory_is_listed_with_its_encoding(self):
        started = time.time()
        out = self.out / "B.combined.H.2DS_2.attributed.parquet"
        out.mkdir()
        (out / "time.parquet").write_bytes(b"PAR1")
        self._touch("rawB.arm.nc")
        target = run_flight.write_outputs_manifest(self.out, ["rawB"], since=started)
        entries = {e["path"]: e for e in
                   json.loads(target.read_text(encoding="utf-8"))["outputs"]}
        self.assertEqual(set(entries), {"rawB.arm.nc", out.name})
        self.assertEqual((entries[out.name]["role"], entries[out.name]["encoding"]),
                         ("attributed", "parquet"))
        self.assertEqual(entries[out.name]["size"], 4)

    def test_a_stale_parquet_directory_is_not_listed(self):
        past = time.time() - 3600
        out = self.out / "A.combined.H.2DS_2.attributed.parquet"
        out.mkdir()
        (out / "time.parquet").write_bytes(b"PAR1")
        os.utime(out / "time.parquet", (past, past))
        os.utime(out, (past, past))
        started = time.time()
        self._touch("rawB.arm.nc")
        target = run_flight.write_outputs_manifest(self.out, ["rawB"], since=started)
        self.assertEqual(self._listed(target), {"rawB.arm.nc"})

    def test_write_attributed_parquet_without_pyarrow_is_a_named_skip(self):
        import importlib.util
        if importlib.util.find_spec("pyarrow") is not None:
            self.skipTest("pyarrow installed; the skip path is not reachable")
        self._touch("B.combined.H.2DS_2.attributed.nc")
        self.assertEqual(run_flight.write_attributed_parquet(self.out), [])
        self.assertFalse((self.out / "B.combined.H.2DS_2.attributed.parquet").exists())

    def test_a_call_sidecar_that_is_not_utf8_does_not_drop_the_manifest(self):
        self._touch("rawB.arm.nc")
        (self.out / "rawB.arm.nc.call").write_bytes(b"engine=3.5 \xff\xfe bad\n")
        target = run_flight.write_outputs_manifest(self.out, ["rawB"])
        self.assertIsNotNone(target)
        self.assertEqual(self._listed(target), {"rawB.arm.nc"})


if __name__ == "__main__":
    unittest.main()
