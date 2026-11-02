# SPDX-License-Identifier: BSD-3-Clause
"""SODA-2 engine x {2DC, 2DP, Fast2DC} x {serial, --jobs, --chunks, --jit}, and SODA-2 x --s2-jobs.

``docs/developer/COVERAGE_MATRIX.md`` lists these arrayprobe_soda2 cells as ``untested``: "no test
exercises this combination, so nothing is claimed either way". This module is the test that
exercises them. What it establishes is a *refusal*, not a run: ``arrayprobe_soda2`` ports
only the SPEC branch and the SEA/CIP route of ``soda2_process_2d.pro``
(``process_2d.py``'s format/probetype gate), so every probe that ``soda2_probespecs`` files
under the 2DC, 2DP or Fast-2DC families is refused by name -- in every mode, and before any
raw file is opened.

Documented semantics asserted, not port output:

* ``soda2_probespecs.pro`` (ported table ``probespecs.py``) gives each named probe its
  ``format``/``probetype`` -- SEA ``2DC`` for the UND/NRC/MSC/SDSMT 2DC and 2DP entries,
  RAF for the NCAR/Wyoming Fast-2DC and 2DP entries.
* ``soda2_read2dbuffer.pro:77-82`` / ``soda2_processbuffer.pro:205-262`` dispatch those
  formats to read/process branches the port does not carry; ``process_2d.py`` says so in
  its ``NotImplementedError`` messages, which cite those lines.

Every raw path here is a file that does not exist, so an open before the gate would raise
``FileNotFoundError`` and fail ``assertRaises(NotImplementedError)``. No number is computed. The
cells covered read ``refused (not built)`` on this evidence: nothing known makes the
combination impossible, the branch is simply unported.
"""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import numpy as np

from arrayprobe import cli
from arrayprobe_soda2.probespecs import PROBE_NAMES, soda2_probespecs
from arrayprobe_soda2.process_2d import soda2_process_2d

#: Matrix probe -> soda2_probespecs names in that family (all present in the ported table).
FAMILIES: dict[str, tuple[str, ...]] = {
    "2DC": ("UND 2DC", "UND 2DC with Korolev Tips", "MSC 2DC", "NRC 2DC (SEA M300)",
            "SDSMT 2DC (SEA)"),
    "2DP": ("NRC 2DP (SEA M300)", "SDSMT 2DP (SEA)", "NCAR 2DP",
            "Wyoming 2DP (NCAR-RAF format)"),
    "Fast2DC": ("NCAR Fast-2DC [C4] (25um)", "NCAR Fast-2DC [C5] (25um)",
                "NCAR Fast-2DC [C6] (10um)", "Wyoming Fast-2DC (NCAR-RAF format)"),
}

#: Matrix mode -> soda2_process_2d keyword arguments the CLI would pass for it.
MODES: dict[str, dict] = {
    "serial": {},
    "jobs": {"jobs": 2},
    "chunks": {"jobs": 2, "chunks": 5},
    "jit": {"jit": True},
}

_SEA_MSG = "soda2_read2dbuffer.pro:77-82 / soda2_processbuffer.pro:205-262"
_FORMAT_MSG = "only op.format in ('SPEC', 'SEA', 'DMT', 'RAF') is ported"
# RAF boundary since soda2-raf-1006: process_2d.py ports the Fast-2DC arm
# (`soda2_processbuffer.pro:28-78`) for probetype F2DC/F2DC_v2 serially; RAF 2DC,
# HVPS1 and F2DC66 are still refused by name, and so is jobs > 1 (the
# `f2d_remainder` carry of `soda2_process_2d.pro:39` crosses chunk boundaries).
_RAF_PROBETYPE_MSG = "soda2_processbuffer.pro:22-127: RAF probetype"
_RAF_JOBS_MSG = "soda2_process_2d.pro:39: RAF "
_RAF_ACCEPTED = ("F2DC", "F2DC_v2", "2DC")  # RAF 2DC ported (2DC route, 2026-10-07)


def _expected_refusal(op: dict, mode: str) -> str | None:
    """The refusal message for this probe and mode, or None where the gate accepts it."""
    if op["format"] == "SEA":
        return _SEA_MSG
    if op["format"] == "RAF":
        if op["probetype"] not in _RAF_ACCEPTED:
            return _RAF_PROBETYPE_MSG
        if MODES[mode].get("jobs", 1) > 1:
            return _RAF_JOBS_MSG
        return None
    return _FORMAT_MSG


def _op(name: str, fn: str) -> dict:
    op = dict(soda2_probespecs(name=name))
    op["fn"] = fn
    # `soda2_update_op.pro` needs endbins (the IDL GUI always supplies it).
    op["endbins"] = np.array([25, 50, 100, 200, 400, 800], dtype=np.int16)
    op["outdir"] = str(Path(fn).parent) + "/"
    return op


class TheTableFilesTheseProbesWhereTheGateSaysItDoes(unittest.TestCase):
    """Precondition for every refusal below: soda2_probespecs.pro's own rows."""

    def test_every_family_member_is_in_the_ported_table(self):
        """Covers: the probe axis of arrayprobe_soda2 x {2DC, 2DP, Fast2DC}."""
        for fam, names in FAMILIES.items():
            for n in names:
                with self.subTest(family=fam, probe=n):
                    self.assertIn(n, PROBE_NAMES)

    def test_formats_are_sea_2dc_or_raf(self):
        """Covers: arrayprobe_soda2 x {2DC, 2DP, Fast2DC} -- the two unported routes."""
        for names in FAMILIES.values():
            for n in names:
                p = soda2_probespecs(name=n)
                with self.subTest(probe=n):
                    if p["format"] == "SEA":
                        self.assertEqual(p["probetype"], "2DC")
                    else:
                        self.assertEqual(p["format"], "RAF")


class EveryModeRefusesByNameBeforeOpeningAFile(unittest.TestCase):
    def _assert_refused(self, family: str, mode: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fn = str(Path(tmp) / "does_not_exist.2dc")
            for name in FAMILIES[family]:
                op = _op(name, fn)
                expect = _expected_refusal(op, mode)
                with self.subTest(probe=name, mode=mode):
                    if expect is None:
                        # Fast-2DC serial/jit is past the gate: the call
                        # fails later (no starttime / no file), never by refusal.
                        with self.assertRaises(Exception) as cm:
                            soda2_process_2d(op, **MODES[mode])
                        self.assertNotIsInstance(cm.exception, NotImplementedError)
                        continue
                    with self.assertRaises(NotImplementedError) as cm:
                        soda2_process_2d(op, **MODES[mode])
                    self.assertIn(expect, str(cm.exception))
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), [])

    def test_2dc_serial(self):
        """Covers cell: 2DC / arrayprobe_soda2 / serial -- refused (not built)."""
        self._assert_refused("2DC", "serial")

    def test_2dc_jobs(self):
        """Covers cell: 2DC / arrayprobe_soda2 / --jobs -- refused (not built)."""
        self._assert_refused("2DC", "jobs")

    def test_2dc_chunks(self):
        """Covers cell: 2DC / arrayprobe_soda2 / --chunks -- refused (not built)."""
        self._assert_refused("2DC", "chunks")

    def test_2dc_jit(self):
        """Covers cell: 2DC / arrayprobe_soda2 / --jit -- refused (not built)."""
        self._assert_refused("2DC", "jit")

    def test_2dp_serial(self):
        """Covers cell: 2DP / arrayprobe_soda2 / serial -- SEA 2DP refused (not built); the RAF
        2DP rows ('NCAR 2DP', 'Wyoming 2DP (NCAR-RAF format)', probetype '2DC') pass the gate.

        Their serial end-to-end runs on synthetic RAF files are ``test_soda2_raf_driver``'s
        ``RafTwoDpThroughThe2dcRoute``."""
        self._assert_refused("2DP", "serial")

    def test_2dp_jobs(self):
        """Covers cell: 2DP / arrayprobe_soda2 / --jobs -- refused (not built): SEA 2DP by the
        SEA route, the RAF 2DP rows by jobs > 1 (`soda2_process_2d.pro:39`)."""
        self._assert_refused("2DP", "jobs")

    def test_2dp_chunks(self):
        """Covers cell: 2DP / arrayprobe_soda2 / --chunks -- refused (not built): SEA 2DP by the
        SEA route, the RAF 2DP rows by jobs > 1 (`soda2_process_2d.pro:39`)."""
        self._assert_refused("2DP", "chunks")

    def test_2dp_jit(self):
        """Covers cell: 2DP / arrayprobe_soda2 / --jit -- SEA 2DP refused (not built); the RAF
        2DP rows are accepted by the gate only (no --jit on/off product comparison)."""
        self._assert_refused("2DP", "jit")

    def _assert_past_the_gate(self, family: str, mode: str) -> None:
        """Every probe in the family is accepted by the gate in this mode.

        Measured behaviour: with no ``starttime`` in ``op`` the accepted call stops in
        ``soda2_update_op`` with ``KeyError('starttime')`` -- after the format/probetype
        gate and before any file is opened, so nothing is written. A refusal would be a
        ``NotImplementedError``; a gate that opened the file first would be a
        ``FileNotFoundError``.
        """
        with tempfile.TemporaryDirectory() as tmp:
            fn = str(Path(tmp) / "does_not_exist.2dc")
            for name in FAMILIES[family]:
                op = _op(name, fn)
                with self.subTest(probe=name, mode=mode):
                    self.assertEqual(op["format"], "RAF")
                    self.assertIn(op["probetype"], _RAF_ACCEPTED)
                    self.assertIsNone(_expected_refusal(op, mode))
                    with self.assertRaises(KeyError) as cm:
                        soda2_process_2d(op, **MODES[mode])
                    self.assertEqual(cm.exception.args, ("starttime",))
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), [])

    def test_fast2dc_serial(self):
        """Covers cell: Fast2DC / arrayprobe_soda2 / serial -- runs past the gate.

        RAF F2DC/F2DC_v2 is ported; the serial end-to-end run on a synthetic RAF
        file is ``test_soda2_raf_driver``'s.
        """
        self._assert_past_the_gate("Fast2DC", "serial")

    def test_fast2dc_jobs(self):
        """Covers cell: Fast2DC / arrayprobe_soda2 / --jobs -- refused (not built)."""
        self._assert_refused("Fast2DC", "jobs")

    def test_fast2dc_chunks(self):
        """Covers cell: Fast2DC / arrayprobe_soda2 / --chunks -- refused (not built)."""
        self._assert_refused("Fast2DC", "chunks")

    def test_fast2dc_jit(self):
        """Covers cell: Fast2DC / arrayprobe_soda2 / --jit -- accepted by the gate only.

        The matrix reads this cell ``untested``: no test runs a RAF Fast-2DC file with
        --jit on and off and compares the products. What is asserted here is only what
        the code does -- ``jit=True`` is not refused for RAF F2DC/F2DC_v2.
        """
        self._assert_past_the_gate("Fast2DC", "jit")


class TheSoda2CliRefusesS2Jobs(unittest.TestCase):
    """``--s2-jobs`` is run_flight.py's SPEC stage-2 decode split; ``arrayprobe soda2 run``
    defines no such flag (cli.py ``_add_soda2``), so argparse rejects it with exit 2 before
    any config is read. That makes every SODA-2 ``--s2-jobs`` cell a deliberate refusal."""

    def test_s2_jobs_is_an_unrecognised_argument(self):
        """Covers cells: {2DC, 2DP, CIP, PIP, HVPS, 2DS, Fast2DC} / arrayprobe_soda2 /
        --s2-jobs -- refuses (by design); the flag is probe-independent, so one parse
        covers all seven."""
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                cli.main(["soda2", "run", "no_such_config.toml", "--s2-jobs", "2"])
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("--s2-jobs", err.getvalue())


if __name__ == "__main__":
    unittest.main()
