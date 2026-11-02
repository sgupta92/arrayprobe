# SPDX-License-Identifier: BSD-3-Clause
"""``scripts/export_human_verdicts.py``: only the author's labels leave the gitignored
store, each with the particle's raw identity, and a re-run writes identical bytes."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from tests._repo import repo_only

from arrayprobe import ncio, provenance

TOOL = Path(__file__).resolve().parents[1] / "scripts" / "export_human_verdicts.py"


def _load():
    spec = importlib.util.spec_from_file_location("export_human_verdicts", TOOL)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


def _proc(path, n=3):
    f = ncio.create(str(path), "clobber")
    t = f.def_dim("time", ncio.NC_UNLIMITED)
    ids = {name: f.def_var(name, "double", t) for name in
           ("Particle_number_all", "particle_microsec", "Time", "image_diam_minR")}
    f.end_def()
    f.put_var(ids["Particle_number_all"], np.array([100.0, 101.0, 102.0][:n]))
    f.put_var(ids["particle_microsec"], np.array([4e9, 4.1e9, 4.2e9][:n]))
    f.put_var(ids["Time"], np.array([65500.0] * n))
    f.put_var(ids["image_diam_minR"], np.array([0.2, 0.3, 0.4][:n]))
    f.close()
    # (2026-09-18): _discover_flights refuses an unstamped product rather than
    # indexing it, so this fixture needs a real stamp to be found at all.
    provenance.write(path, engine="3.1.4", profile="oracles-2016", stage="S3")


@repo_only
@unittest.skipUnless(TOOL.is_file(), f"{TOOL} is not distributed with the package")
class TheExport(unittest.TestCase):
    def setUp(self):
        self.mod = _load()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.dd = root / "dec"
        (self.dd / "triage_verdicts").mkdir(parents=True)
        _proc(self.dd / "proc.fl.H.nc")
        (self.dd / "fl.H.cdf").write_bytes(b"")
        (self.dd / "triage_verdicts" / "fl.json").write_text(json.dumps({
            "0": {"verdict": "real", "source": "model", "reviewer": "model-reviewer"},
            "2": {"verdict": "artifact", "source": "human", "note": "streak"},
        }))
        self.out = root / "labels"

    def test_only_human_records_leave_with_their_raw_identity(self):
        (p,) = self.mod.export_all([self.dd], self.out)
        doc = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(doc["n_labels"], 1)
        (row,) = doc["labels"]
        self.assertEqual((row["particle_index"], row["verdict"]), (2, "artifact"))
        self.assertEqual(row["Particle_number_all"], 102)
        self.assertEqual(row["particle_microsec"], 4200000000)
        self.assertIsNone(row["msec"])            # absent from this proc: None, not dropped
        self.assertEqual(len(doc["proc"]["sha256"]), 64)

    def test_a_rerun_writes_identical_bytes(self):
        (p,) = self.mod.export_all([self.dd], self.out)
        first = p.read_bytes()
        self.mod.export_all([self.dd], self.out)
        self.assertEqual(p.read_bytes(), first)

    def test_a_store_with_no_human_label_writes_nothing(self):
        (self.dd / "triage_verdicts" / "fl.json").write_text(json.dumps(
            {"0": {"verdict": "real", "source": "model"}}))
        self.assertEqual(self.mod.export_all([self.dd], self.out), [])

    def test_the_phase_leaves_with_its_verdict_and_is_absent_when_never_recorded(self):
        (self.dd / "triage_verdicts" / "fl.json").write_text(json.dumps({
            "1": {"verdict": "real", "source": "human", "phase": "ice"},
            "2": {"verdict": "artifact", "source": "human", "note": "streak"},
        }))
        (p,) = self.mod.export_all([self.dd], self.out)
        first, second = json.loads(p.read_text(encoding="utf-8"))["labels"]
        self.assertEqual((first["particle_index"], first["phase"]), (1, "ice"))
        self.assertNotIn("phase", second)


if __name__ == "__main__":
    unittest.main()
