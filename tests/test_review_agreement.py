# SPDX-License-Identifier: BSD-3-Clause
"""Track V phase 2, item 3: re-check queues and Cohen's kappa (``arrayprobe.review_agreement``)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arrayprobe import triage_server  # noqa: E402
from arrayprobe.review_agreement import agreement, cohen_kappa, recheck_queue  # noqa: E402


class CohenKappa(unittest.TestCase):
    def test_a_hand_computed_case(self):
        """20 a/a, 5 a/b, 10 b/a, 15 b/b: p_o = 0.7, p_e = 0.5*0.6 + 0.5*0.4 = 0.5, kappa = 0.4."""
        first = ["a"] * 25 + ["b"] * 25
        second = ["a"] * 20 + ["b"] * 5 + ["a"] * 10 + ["b"] * 15
        r = cohen_kappa(first, second)
        self.assertEqual(r.n, 50)
        self.assertAlmostEqual(r.observed, 0.7)
        self.assertAlmostEqual(r.expected, 0.5)
        self.assertAlmostEqual(r.kappa, 0.4)
        self.assertEqual(r.confusion["a"]["b"], 5)
        self.assertEqual(r.confusion["b"]["a"], 10)

    def test_perfect_agreement_is_one(self):
        self.assertAlmostEqual(cohen_kappa(["a", "b", "c"], ["a", "b", "c"]).kappa, 1.0)

    def test_one_label_throughout_is_undefined_not_a_number(self):
        self.assertIsNone(cohen_kappa(["real"] * 4, ["real"] * 4).kappa)

    def test_unequal_lengths_are_refused(self):
        with self.assertRaises(ValueError):
            cohen_kappa(["a"], ["a", "b"])


class RecheckStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        for i in range(10):
            triage_server._save_verdict(self.dir, "f1", i, "real" if i % 2 else "artifact",
                                        source="human", reviewer="r1", queue="q")
        triage_server._save_verdict(self.dir, "f1", 99, "real", source="bulk-cluster",
                                    reviewer="test")

    def test_the_queue_draws_only_human_labels_reproducibly(self):
        out = self.dir / "q.json"
        a = recheck_queue(self.dir, "f1", out, fraction=0.5, seed=7)
        b = recheck_queue(self.dir, "f1", out, fraction=0.5, seed=7)
        name = next(k for k in a if not k.startswith("_"))
        self.assertTrue(name.startswith(triage_server.RECHECK_PREFIX))
        drawn = [it["particle_index"] for it in a[name]]
        self.assertEqual(len(drawn), 5)
        self.assertNotIn(99, drawn)
        self.assertEqual(a, b)
        self.assertEqual(a["_about"]["of_human_labelled"], 10)
        self.assertEqual(triage_server._review_queues(json.loads(out.read_text())), {name: a[name]})

    def test_a_recheck_verdict_never_overwrites_the_first(self):
        before = (self.dir / "triage_verdicts" / "f1.json").read_bytes()
        triage_server._save_verdict(self.dir, "f1", 3, "artifact", source="human",
                                    reviewer="r1", queue="recheck-f1-seed7")
        self.assertEqual((self.dir / "triage_verdicts" / "f1.json").read_bytes(), before)
        rc = triage_server._load_verdicts(self.dir, "f1", recheck=True)
        self.assertEqual(rc["3"]["verdict"], "artifact")

    def test_agreement_pairs_first_and_recheck_labels(self):
        for i, v in [(1, "real"), (2, "artifact"), (3, "artifact"), (4, "real")]:
            triage_server._save_verdict(self.dir, "f1", i, v, source="human", reviewer="r2",
                                        queue="recheck-f1-seed7")
        r = agreement(self.dir, "f1")
        self.assertEqual(r.n, 4)
        self.assertAlmostEqual(r.observed, 0.5)  # 1 and 2 agree; 3 and 4 flip


class TheCommandLine(RecheckStore):
    def test_recheck_then_agreement_from_the_cli(self):
        import contextlib
        import io

        from arrayprobe import cli
        out = self.dir / "rq.json"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.main(["triage-recheck", "--decoded-dir", str(self.dir), "--flight", "f1",
                           "--out", str(out), "--fraction", "0.3", "--seed", "3"])
        self.assertEqual(rc, 0)
        self.assertIn("3 of 10 human-labelled", buf.getvalue())
        data = json.loads(out.read_text())
        name = next(k for k in data if not k.startswith("_"))
        for it in data[name]:
            triage_server._save_verdict(self.dir, "f1", it["particle_index"], "real",
                                        source="human", reviewer="r2", queue=name)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.main(["triage-agreement", "--decoded-dir", str(self.dir), "--flight", "f1"])
        self.assertEqual(rc, 0)
        self.assertIn("3 re-checked particles", buf.getvalue())
        self.assertIn("Cohen's kappa", buf.getvalue())

if __name__ == "__main__":
    unittest.main()
