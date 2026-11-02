# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe tune score``: triage labels crossed with reject code and size bin, synthetic data.

Verdicts are written through the triage server's own store (``_save_verdict``), and the queue
items through ``tune.sample.queue_items``, so the join is tested against the formats the
reviewer's labels and the queue writer actually produce. Known counts in, known counts out.
"""
from __future__ import annotations

import io
import json
import math
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import numpy as np

from arrayprobe import cli
from arrayprobe.triage_server import _save_verdict
from arrayprobe.tune import sample, score

_TOOLS = Path(__file__).resolve().parents[1] / "scripts"
tool_wilson = None
if (_TOOLS / "score_ena_reject_fields.py").is_file():  # a repository tool, not in the public tree
    sys.path.insert(0, str(_TOOLS))
    from score_ena_reject_fields import wilson as tool_wilson  # noqa: E402

needs_score_tool = unittest.skipIf(tool_wilson is None,
                                   "The reject-field scoring tool is not distributed with the "
                                   "package")

FLIGHT = "base180215125340.H"
QNAME = "spot-all-n4-s1"
RECHECK = "recheck-spot"


def _items():
    """Particles 0-3 in 55-100um, 4-5 in 100-200um; codes 0, a, a, z, 0, h."""
    t = np.full(6, 120000)
    diam = np.array([0.06, 0.07, 0.08, 0.09, 0.15, 0.16])
    rej = np.array([ord(c) for c in "0aaz0h"])
    strata = [{"bin": "55-100um", "indices": [0, 1, 2, 3]},
              {"bin": "100-200um", "indices": [4, 5]}]
    return sample.queue_items(strata, t, diam, rej, FLIGHT)


def _label(d: Path):
    """0 real ice, 1 real drizzle (an 'a' reject labelled real), 2 artifact, 3 real ice,
    4 artifact (accepted, labelled artifact), 5 unlabelled. Re-check store: 1 artifact."""
    _save_verdict(d, FLIGHT, 0, "real", source="human", phase="ice", reviewer="test")
    _save_verdict(d, FLIGHT, 1, "real", source="human", phase="drizzle", reviewer="test")
    _save_verdict(d, FLIGHT, 2, "artifact", source="human", reviewer="test")
    _save_verdict(d, FLIGHT, 3, "real", source="human", phase="ice", reviewer="test")
    _save_verdict(d, FLIGHT, 4, "artifact", source="human", reviewer="test")
    _save_verdict(d, FLIGHT, 1, "artifact", source="human", queue=RECHECK, reviewer="test")


class TestRejectCodeOfQueueItems(unittest.TestCase):
    def test_the_code_round_trips_through_the_queue_writer(self):
        self.assertEqual([score.reject_code_of(it) for it in _items()], list("0aaz0h"))

    def test_an_explicit_field_wins_and_a_missing_code_is_unknown(self):
        self.assertEqual(score.reject_code_of({"reject_code": "p", "note": "code a"}), "p")
        self.assertEqual(score.reject_code_of({"note": "window, no code here"}),
                         score.UNKNOWN_CODE)

    @needs_score_tool
    def test_wilson_is_the_score_tools_interval(self):
        for k, n in ((0, 1), (3, 4), (7, 20), (20, 20)):
            self.assertEqual(score.wilson(k, n), tool_wilson(k, n))
        self.assertTrue(all(math.isnan(x) for x in score.wilson(0, 0)))


class TestScoreFile(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        _label(self.dir)
        items = _items()
        self.data = {QNAME: items, RECHECK: items[:2], "_coverage": {}}
        self.rep = score.score_file(self.data, self.dir)

    def _codes(self, name):
        return {c["code"]: c for c in self.rep["queues"][name]["by_code"]}

    def test_rejected_labelled_real_and_accepted_labelled_artifact(self):
        c = self._codes(QNAME)
        self.assertEqual((c["a"]["queued"], c["a"]["v_real"], c["a"]["v_artifact"]), (2, 1, 1))
        self.assertEqual(c["a"]["rejected_labelled_real"], 1)
        self.assertIsNone(c["a"]["accepted_labelled_artifact"])
        self.assertEqual(c["z"]["rejected_labelled_real"], 1)
        self.assertEqual(c["0"]["accepted_labelled_artifact"], 1)
        self.assertIsNone(c["0"]["rejected_labelled_real"])
        self.assertEqual((c["h"]["queued"], c["h"]["labelled"]), (1, 0))
        self.assertEqual(c["h"]["accepted_labelled_artifact"], 0)

    def test_code_counts_split_by_size_bin(self):
        c = self._codes(QNAME)["0"]
        self.assertEqual(c["bins"]["55-100um"]["v_real"], 1)
        self.assertEqual(c["bins"]["100-200um"]["v_artifact"], 1)

    @needs_score_tool
    def test_by_bin_phase_and_wilson(self):
        small, big = self.rep["queues"][QNAME]["by_bin"]["rows"]
        self.assertEqual((small["p_ice"], small["p_drizzle"]), (2, 1))
        self.assertAlmostEqual(small["ice_fraction"], 2 / 3)
        self.assertEqual(small["wilson95"], list(tool_wilson(2, 3)))
        self.assertIsNone(small["available"])
        self.assertIsNone(big["ice_fraction"])

    def test_a_recheck_queue_reads_only_its_own_store(self):
        q = self.rep["queues"][RECHECK]
        self.assertEqual(q["store"], "recheck")
        c = {x["code"]: x for x in q["by_code"]}
        self.assertEqual((c["0"]["labelled"], c["a"]["labelled"]), (0, 1))
        self.assertEqual(c["a"]["v_artifact"], 1)
        self.assertEqual(c["a"]["rejected_labelled_real"], 0)

    def test_coverage_supplies_the_accepted_codes_and_available(self):
        cov = {QNAME: {"accepted_codes": "0Hh", "strata": [
            {"bin": "55-100um", "available": 30}, {"bin": "100-200um", "available": 10}]}}
        rep = score.score_file({QNAME: _items(), "_coverage": cov}, self.dir)
        q = rep["queues"][QNAME]
        self.assertEqual(q["accepted_codes"], "0Hh")
        self.assertEqual([r["available"] for r in q["by_bin"]["rows"]], [30, 10])
        self.assertAlmostEqual(q["by_bin"]["weighted_ice_fraction"], 2 / 3)

    def test_unknown_phase_verdict_is_refused(self):
        with self.assertRaises(ValueError):
            score.score_file(self.data, self.dir, ("real", "liquid"))


class TestCli(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        _label(self.dir)
        self.queue = self.dir / "q.json"
        self.queue.write_text(json.dumps({QNAME: _items()}), encoding="utf-8")

    def _run(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.main(["tune", "score", *argv])
        return rc, out.getvalue(), err.getvalue()

    def test_writes_the_report(self):
        rep = self.dir / "out" / "score.json"
        rc, out, _ = self._run("--queue-file", str(self.queue), "--decoded-dir", str(self.dir),
                               "--out", str(rep))
        self.assertEqual(rc, 0)
        self.assertIn("rejected, 1 labelled real", out)
        got = json.loads(rep.read_text(encoding="utf-8"))
        self.assertEqual(got["queues"][QNAME]["store"], "first")

    def test_missing_inputs_exit_2(self):
        rc, _, err = self._run("--queue-file", str(self.dir / "none.json"),
                               "--decoded-dir", str(self.dir))
        self.assertEqual(rc, 2)
        self.assertIn("no queue file", err)
        rc, _, err = self._run("--queue-file", str(self.queue),
                               "--decoded-dir", str(self.dir / "missing"))
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
