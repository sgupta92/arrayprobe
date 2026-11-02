# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe reprocess`` takes its engine from the product's stamp, and refuses when there
is none.

WHY THIS EXISTS (2026-09-18). ``cli._reprocess`` used to read the sidecar itself::

    stamped = "3.5" if stamp.startswith("engine=3.5 ") else "3.1.4"

Four different facts -- no sidecar (``OSError -> ""``), a lane script's JSON sidecar, a
truncated sidecar, and a genuine v3.1.4 sidecar -- all produced the single definite answer
``"3.1.4"``. Worse, the whole block sat behind ``if args.uiops_version != "3.1.4"``, and
``"3.1.4"`` is that option's default, so on the ordinary command line the check did not run at
all. A 1.25 GB CIP product carrying a JSON stamp with no engine key was described as v3.5 for
a day; this is the reader that would have said so, and did not.

**These are firing tests.** Each case builds a real product on disk whose provenance is
genuinely absent or genuinely engine-less, and asserts the command exits 2 **and runs
nothing** -- the second half matters, because a refusal that arrives after the stage has
started is not a refusal. ``scripts/reprocess.py`` is replaced by a recording stub so "ran
nothing" is an assertion about a call that did not happen, not an inference from an exit code.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from arrayprobe import cli

_DRIVER_V314 = ("engine=3.1.4 profile=oracles-production "
                "reject=(rej_zero_area=True,rej_split=True,rej_hollow=False,shadowed_area=25,"
                "max_edge_img_ar=4,max_comp_img_ar=4) shadow_diode=none")
_DRIVER_V35 = "engine=3.5 profile=stock-v3.5 shadow_diode=none software=UIOOPS_v3.5"

#: A lane script's stamp, verbatim in shape: stage and profile, and no engine key anywhere.
#: This is what ``_decoded/cip160906/proc.cip_s2.nc.call`` carries.
_LEGACY_JSON = '{"stage": "S3", "profile": "oracles-production", "reject": "production"}'

#: A driver stamp from before 2026-09-15, when ``engine=`` was added. ``run_flight`` reads one
#: of these as v3.1.4 *for resume equality*, which is a different question with a different
#: safe answer; asked "what wrote this", the file does not say, and this command must not
#: pretend otherwise.
_DRIVER_NO_ENGINE = "profile=oracles-production shadow_diode=none"


class _Recorder:
    """Stands in for ``scripts/reprocess.py``. ``ran`` is the assertion."""

    def __init__(self):
        self.ran = False

    def run(self, args):
        self.ran = True
        return 0


class _Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.product = self.d / "proc.160906064017.H.nc"
        self.product.write_bytes(b"")
        self.recorder = _Recorder()
        real = cli._load_reprocess
        cli._load_reprocess = lambda: self.recorder
        self.addCleanup(lambda: setattr(cli, "_load_reprocess", real))

    def _stamp(self, text: str) -> None:
        self.product.with_name(self.product.name + ".call").write_text(
            text + "\n", encoding="utf-8")

    def _main(self, *top_level: str) -> int:
        """``--uiops-version`` is a TOP-LEVEL option, so it precedes the subcommand."""
        return cli.main([*top_level, "reprocess", str(self.product),
                         "--preset", "ORACLES_2016_2DS_H"])


class RefusesWhenProvenanceIsAbsent(_Case):
    """Exit 2, nothing run. The firing half of this module."""

    def test_an_unstamped_product_exits_2_and_runs_nothing(self):
        code = self._main()
        self.assertEqual(code, 2)
        self.assertFalse(self.recorder.ran, "the stage ran despite the refusal")

    def test_a_legacy_json_product_exits_2_and_runs_nothing(self):
        """A sidecar that exists and records no engine. Under the old prefix test this read as
        v3.1.4 and the stage ran under an engine nobody had established."""
        self._stamp(_LEGACY_JSON)
        code = self._main()
        self.assertEqual(code, 2)
        self.assertFalse(self.recorder.ran)

    def test_a_driver_stamp_with_no_engine_key_exits_2_and_runs_nothing(self):
        self._stamp(_DRIVER_NO_ENGINE)
        self.assertEqual(self._main(), 2)
        self.assertFalse(self.recorder.ran)

    def test_a_truncated_stamp_exits_2_rather_than_reading_as_3_1_4(self):
        """The prefix test's worst case: a stamp cut mid-write still ``startswith``-failed the
        3.5 prefix and was therefore reported as v3.1.4."""
        self._stamp("engi")
        self.assertEqual(self._main(), 2)
        self.assertFalse(self.recorder.ran)

    def test_the_refusal_names_the_file_and_the_way_forward(self):
        import contextlib
        import io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self._main()
        message = err.getvalue()
        self.assertIn(self.product.name, message)
        self.assertIn("arrayprobe provenance", message)


class ProceedsOnARealStamp(_Case):
    """The not-vacuous half: with provenance recorded, the command still works exactly as it
    did. A guard that refused everything would pass every test above."""

    def test_a_v314_stamp_runs_the_stage(self):
        self._stamp(_DRIVER_V314)
        self.assertEqual(self._main(), 0)
        self.assertTrue(self.recorder.ran)

    def test_a_v35_stamp_runs_the_stage(self):
        self._stamp(_DRIVER_V35)
        self.assertEqual(self._main(), 0)
        self.assertTrue(self.recorder.ran)

    def test_uiops_version_3_5_still_routes_on_a_v35_stamp(self):
        self._stamp(_DRIVER_V35)
        self.assertEqual(self._main("--uiops-version", "3.5"), 0)
        self.assertTrue(self.recorder.ran)

    def test_a_named_version_that_disagrees_with_the_stamp_is_still_refused(self):
        """The one check that did exist, preserved: asking for 3.5 on a 3.1.4 product."""
        self._stamp(_DRIVER_V314)
        self.assertEqual(self._main("--uiops-version", "3.5"), 2)
        self.assertFalse(self.recorder.ran)


class TheOldDefaultIsGone(unittest.TestCase):
    """The string-prefix reader must not survive anywhere in this module: a second copy would
    be a second place for absence to acquire a default."""

    def test_cli_no_longer_maps_a_missing_stamp_onto_a_version(self):
        """Asserted against the compiled code's constants, not the file's text: the docstring
        above quotes the old expression on purpose, and a grep over the source would be
        satisfied by deleting that explanation instead of by keeping the defect out."""
        code = cli._reprocess.__code__
        self.assertNotIn("engine=3.5 ", code.co_consts)
        self.assertIn("engine_of", code.co_names,
                      "the engine must come from provenance.engine_of, which raises on absence")

    def test_the_guard_is_reached_on_the_default_command_line(self):
        """The old block sat behind ``if args.uiops_version != "3.1.4"`` -- its own default --
        so the ordinary invocation skipped it entirely. This asserts the default parse reaches
        the check, which is the property that was actually missing."""
        parser = cli.build_parser()
        args = parser.parse_args(["reprocess", "x.nc", "--preset", "P"])
        self.assertEqual(args.uiops_version, "3.1.4")


if __name__ == "__main__":
    sys.exit(unittest.main())
