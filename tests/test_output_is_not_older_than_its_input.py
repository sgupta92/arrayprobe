# SPDX-License-Identifier: BSD-3-Clause
"""A stage output older than its input is not a product of it, whatever its stamp says.

**The incident, 2026-09-19.** The documented ten-minute quickstart --
``docs/02-user-guide.md``'s own two commands, run verbatim on a clean checkout --
wrote a fresh raw file and then produced a well-formed 68 MB combined product with **zero
particles counted into any bin**. It printed ``ALL DONE`` and exited 0. The driver's own log said
why::

    S3 skip   proc.base160101000000.H.nc exists
    S4 skip   sd.base160101000000.H.nc exists

Those two files were dated **2026-09-10, nine days earlier**, from a different (plain, not
``--dense``) demo flight. They were stitched into the product instead of anything the user had
just built.

**Why every existing control missed it, which is the part worth keeping.** The ``.call`` stamp
records the *configuration* a file was built with and deliberately **not** its inputs --
``scripts/reprocess.py``'s own docstring says so in as many words. Here the two runs' configurations
were byte-for-byte identical (same preset, same profile, same thresholds); only the raw file
differed. So every stamp comparison correctly answered "current", and the stage was correctly
skipped according to the only question anything was asking.

That is the same shape as the HVPS-bin fallback: the user does not get an obviously broken file,
they get a plausible one that is empty. Here it reaches a **new user on the first thing the
documentation asks them to run**, which is why it is worth a guard rather than a note.

**The fix** is one new state in :func:`run_flight.output_state`: given a ``source``, an output
older than that input is ``outdated`` -- redone, with the reason logged -- however well its stamp
matches. ``source`` is optional so a caller with no single input (S4c stitches many) keeps its
old behaviour rather than being silently given a wrong answer.

**What makes this file a control and not a restatement**: the first test below builds exactly the
incident -- a matching stamp, an input newer than the output -- and asserts the state is
``outdated``. Reverting the fix makes it fail. The remaining tests pin the three states it must
*not* disturb, because a staleness check that fires too eagerly would destroy the resume story the
runner is built on (a long flight that crashes at hour six must not restart at hour zero).
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "scripts"
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


def _load_run_flight():
    if "run_flight" in sys.modules:
        return sys.modules["run_flight"]
    spec = importlib.util.spec_from_file_location("run_flight", TOOLS / "run_flight.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_flight"] = mod
    spec.loader.exec_module(mod)
    return mod


run_flight = _load_run_flight()

STAMP = "engine=3.1.4 profile=oracles-production reject=(rej_hollow=False) shadow_diode=none"


class _Fixture(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.d = Path(self._td.name)
        self.addCleanup(self._td.cleanup)

    def _write(self, name: str, stamp: str | None = STAMP) -> Path:
        p = self.d / name
        p.write_bytes(b"x")
        if stamp is not None:
            # `<output>.call` is the sidecar convention `read_stamp` reads; written
            # directly rather than through a helper so this fixture states the shape
            # the driver depends on instead of inheriting it.
            p.with_name(p.name + ".call").write_text(stamp, encoding="utf-8")
        return p

    @staticmethod
    def _make_older(path: Path, seconds: float = 120.0) -> None:
        """Move a file's mtime back. Done explicitly rather than by sleeping: the
        filesystem's timestamp granularity is coarse enough that two files written in
        the same test can share an mtime, which would make the check look like it
        passed when it had nothing to compare."""
        st = path.stat()
        os.utime(path, (st.st_atime - seconds, st.st_mtime - seconds))


class TheIncidentItself(_Fixture):
    def test_a_matching_stamp_does_not_rescue_an_output_older_than_its_input(self):
        """Revert the ``source`` branch in ``output_state`` and this fails."""
        output = self._write("proc.flight.H.nc")
        source = self._write("flight.H.cdf")
        self._make_older(output)          # the 2026-09-10 proc file
        # the stamp matches perfectly -- that is the whole point
        self.assertEqual("current", run_flight.output_state(output, STAMP))
        self.assertEqual(
            "outdated", run_flight.output_state(output, STAMP, source),
            "an output older than the input it claims to be built from was reported "
            "current, which is exactly the state that emptied the documented quickstart")


class TheStatesItMustNotDisturb(_Fixture):
    """A staleness check that fires too eagerly destroys the resume story: a flight
    that crashes at hour six must not restart at hour zero."""

    def test_an_output_newer_than_its_input_is_still_current(self):
        source = self._write("flight.H.cdf")
        self._make_older(source)
        output = self._write("proc.flight.H.nc")
        self.assertEqual("current", run_flight.output_state(output, STAMP, source))

    def test_a_differing_stamp_is_still_stale_not_outdated(self):
        """Configuration drift keeps its own name and its own message, because the
        two call for different explanations to the operator."""
        output = self._write("proc.flight.H.nc")
        source = self._write("flight.H.cdf")
        self._make_older(output)
        self.assertEqual(
            "stale", run_flight.output_state(output, "engine=3.5 profile=stock-v3.5", source))

    def test_an_unstamped_output_is_still_unstamped(self):
        """Unstamped outranks outdated: the driver refuses rather than quietly
        rebuilding what may be evidence."""
        output = self._write("proc.flight.H.nc", stamp=None)
        source = self._write("flight.H.cdf")
        self._make_older(output)
        self.assertEqual("unstamped", run_flight.output_state(output, STAMP, source))

    def test_a_missing_output_is_still_absent(self):
        source = self._write("flight.H.cdf")
        self.assertEqual(
            "absent", run_flight.output_state(self.d / "nope.nc", STAMP, source))

    def test_a_missing_source_changes_nothing(self):
        """A caller that names an input which is not there gets the stamp's answer,
        not an invented one -- absence of the input is not evidence about the output."""
        output = self._write("proc.flight.H.nc")
        self._make_older(output)
        self.assertEqual(
            "current", run_flight.output_state(output, STAMP, self.d / "gone.cdf"))

    def test_omitting_source_is_the_old_behaviour_exactly(self):
        """Every caller that cannot name a single input (S4c stitches many) must be
        unaffected, so the default stays the pre-2026-09-19 answer."""
        output = self._write("proc.flight.H.nc")
        self._make_older(output)
        self.assertEqual("current", run_flight.output_state(output, STAMP))


class TheEqualTimestampCase(_Fixture):
    def test_an_output_written_in_the_same_instant_is_current(self):
        """Strictly older, not 'not newer'. Coarse filesystem granularity makes
        equal mtimes common for fast stages, and treating equality as outdated would
        rebuild a correct product on every run."""
        source = self._write("flight.H.cdf")
        output = self._write("proc.flight.H.nc")
        st = source.stat()
        os.utime(output, (st.st_atime, st.st_mtime))
        self.assertEqual(source.stat().st_mtime, output.stat().st_mtime)
        self.assertEqual("current", run_flight.output_state(output, STAMP, source))


if __name__ == "__main__":
    unittest.main()
