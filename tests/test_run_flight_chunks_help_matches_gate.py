# SPDX-License-Identifier: BSD-3-Clause
"""``run_flight.py --chunks``'s help must not claim a refusal the engine-3.5 gate does not make.

The gate in ``scripts/run_flight.py``'s ``main()`` allows ``--chunks`` under ``--engine 3.5``
for every probe whose timing is in ``CHUNKABLE_TIMINGS_V35`` or ``PRIMABLE_TIMINGS_V35``
(``arrayprobe_uiops.imgproc``), and refuses only a primable timing run with ``iQC=1``. The help
text is a hand-written sentence beside it, so this test reads both sides: the timing sets and
probe table from the engine, the help from the script's own ``--help`` output, and the gate's
two conditions from the script's source (so a change to the gate fails here and forces the
help to be reread).
"""
from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

from tests._driver import driver_source

from arrayprobe_uiops import imgproc as v35_imgproc

PORT = Path(__file__).resolve().parent.parent
RUN_FLIGHT = PORT / "scripts" / "run_flight.py"

# The gate's two conditions, as written in main(). If either changes, the help sentence was
# written against a different gate and must be reread before this test is updated.
GATE_ALLOW = "if timing not in v35_imgproc.CHUNKABLE_TIMINGS_V35 and not primable:"
GATE_IQC = "if primable and V35_CALL.i_qc == 1:"


def _chunks_help() -> str:
    out = subprocess.run([sys.executable, str(RUN_FLIGHT), "--help"], cwd=PORT,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    lines = out.stdout.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.lstrip().startswith("--chunks "))
    block = [lines[start]]
    for ln in lines[start + 1:]:
        if re.match(r"^\s{2}-", ln):
            break
        block.append(ln)
    return " ".join(" ".join(block).split())


class ChunksHelpMatchesGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.help = _chunks_help()
        cls.source = driver_source("run_flight.py").read_text(encoding="utf-8")

    def test_gate_is_the_one_the_help_describes(self):
        self.assertIn(GATE_ALLOW, self.source)
        self.assertIn(GATE_IQC, self.source)

    def test_every_v35_probe_is_chunkable_by_the_gate(self):
        allowed = set(v35_imgproc.CHUNKABLE_TIMINGS_V35) | set(v35_imgproc.PRIMABLE_TIMINGS_V35)
        refused = sorted(p for p, spec in v35_imgproc.PROBES_V35.items()
                         if spec.timing not in allowed)
        # The help says "covers every probe"; that is only true while nothing is refused.
        if refused:
            self.assertNotIn("covers every probe", self.help)
        else:
            self.assertIn("covers every probe", self.help)

    def test_every_refusal_sentence_names_iqc_1(self):
        sentences = [s for s in re.split(r"(?<=[.;:])\s+", self.help) if "refus" in s.lower()]
        if v35_imgproc.PRIMABLE_TIMINGS_V35:
            self.assertTrue(sentences, "the iQC=1 refusal is not stated in --chunks help")
        for s in sentences:
            self.assertIn("iQC=1", s,
                          f"--chunks help states a refusal the gate does not make: {s!r}")

    def test_primed_probes_are_not_called_refused_outright(self):
        primed = [p for p, spec in v35_imgproc.PROBES_V35.items()
                  if spec.timing in v35_imgproc.PRIMABLE_TIMINGS_V35]
        self.assertTrue(primed)
        self.assertNotRegex(self.help, r"(2DS|HVPS|3VCPI)[^.]*\bare refused\b")


if __name__ == "__main__":
    unittest.main()
