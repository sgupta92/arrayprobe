# SPDX-License-Identifier: BSD-3-Clause
"""R4 (2026-09-29): every ``--engine 3.1.4`` run of
``scripts/run_flight.py`` needs ``--port-validation``.

Without the flag the run is refused with exit 2 and a one-line reason; with it, every ``.call``
stamp the run writes begins ``engine=3.1.4 port_validation=on `` (the output is port validation,
not for quoting). The token changes no computed byte, so a stamp written before the gate existed,
or one written without the token by ``scripts/reprocess.py``'s main-less label functions, must stay
current: ``_stamps_equivalent`` strips the token from both sides.

What this module pins, and why each line is here:

* the refusal is the first one a v3.1.4 run meets (it names the root cause), is one log line, and
  decodes nothing;
* the converse: ``--port-validation`` is refused under any other engine;
* a gated run stamps the token exactly once at the front of the image, proc and sd stamps;
* archived stamps (the real 2026-09-10 goldens, with and without ``engine=``) stay equivalent to
  the new labels in both directions, and the strip removes only its own token;
* a flight whose sd files straddle the gate does not read as MIXED at the combine.
"""
from __future__ import annotations

import importlib.util
import io
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "scripts"
sys.path.insert(0, str(ROOT / "tests"))
import _run_flight_state  # noqa: E402

_SPEC = importlib.util.spec_from_file_location("run_flight", TOOLS / "run_flight.py")
sys.modules.setdefault(_SPEC.name, importlib.util.module_from_spec(_SPEC))
run_flight = sys.modules[_SPEC.name]
if not hasattr(run_flight, "main"):
    _SPEC.loader.exec_module(run_flight)

from tests._repo import needs_file, needs_v314_engine  # noqa: E402

from arrayprobe import cli  # noqa: E402 (after run_flight is registered in sys.modules)
from arrayprobe.tools.make_demo_flight import build_demo_flight  # noqa: E402

SHIPPED_TOML = TOOLS / "oracles_2016_2ds.toml"

_REFUSAL = "--engine 3.1.4 needs --port-validation"
_CONVERSE = "--port-validation is engine 3.1.4 only"

# The real on-disk sidecars of base160912071923 (read 2026-09-13, mtime 2026-09-10), the same
# goldens tests/test_run_from_config.py::ValidatedCallStampsAreByteIdentical holds: no ``engine=``
# key at all, the form every v3.1.4 stamp had before 2026-09-15.
_DECODE_STAMP = "profile=oracles-production spec_buffer_guard=False hvps_reader=hvps channels=H"
_PROC_STAMP = ("profile=oracles-production reject=(rej_zero_area=True,rej_split=True,"
               "rej_hollow=False,shadowed_area=25,max_edge_img_ar=4,max_comp_img_ar=4) "
               "shadow_diode=none")
_SD_STAMP = ("iat_file=2DS_intArrThreshold_MISSING.cdf " + _PROC_STAMP
             + " tree=production area_ratio_z=0.5 (default) default_int_arr_thresh=6e-06 (default)")


class _Base(unittest.TestCase):
    def setUp(self):
        _run_flight_state.preserve(self, run_flight)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.raw = build_demo_flight(self.root / "base160101000000.2DS", n_seconds=3)
        self.out = self.root / "_decoded"

    def run_main(self, *argv: str) -> tuple[int, str]:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = run_flight.main([str(self.raw), "--preset", "DEMO_2DS_H", "--out", str(self.out),
                                  "--yes", *argv])
        return rc, buf.getvalue()


class TheGateRefusesAndAccepts(_Base):

    @needs_v314_engine
    def test_engine_314_without_the_flag_is_refused(self):
        rc, out = self.run_main("--engine", "3.1.4")
        self.assertEqual(rc, 2, out)
        self.assertIn(_REFUSAL, out)
        self.assertFalse(self.out.exists() and any(self.out.iterdir()),
                         "a refused run decoded something")

    @needs_v314_engine
    def test_the_refusal_is_one_line_and_names_the_alternative(self):
        rc, out = self.run_main("--engine", "3.1.4")
        self.assertEqual(rc, 2, out)
        lines = [ln for ln in out.splitlines() if "needs --port-validation" in ln]
        self.assertEqual(len(lines), 1, out)
        self.assertIn("--engine 3.5", lines[0])

    @needs_v314_engine
    def test_the_refusal_comes_before_every_other_one(self):
        """``--libm-pow`` is itself refused off engine 3.1.4 -- but here the engine IS 3.1.4, and
        the run must be told the missing flag first, not proceed to a later gate."""
        rc, out = self.run_main("--engine", "3.1.4", "--libm-pow")
        self.assertEqual(rc, 2, out)
        self.assertIn(_REFUSAL, out)

    def test_the_flag_is_refused_under_engine_35(self):
        rc, out = self.run_main("--engine", "3.5", "--port-validation")
        self.assertEqual(rc, 2, out)
        self.assertIn(_CONVERSE, out)
        self.assertNotIn(_REFUSAL, out)

    @needs_v314_engine
    def test_engine_314_with_the_flag_is_accepted(self):
        rc, out = self.run_main("--engine", "3.1.4", "--port-validation", "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertNotIn(_REFUSAL, out)
        self.assertNotIn(_CONVERSE, out)

    def test_the_engine_advice_names_the_flag(self):
        """The missing-``--engine`` refusal lists the two engines; the 3.1.4 line must now say what
        it needs."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = run_flight.main([str(self.raw), "--preset", "DEMO_2DS_H", "--out", str(self.out),
                                  "--yes"])
        self.assertEqual(rc, 2, buf.getvalue())
        self.assertIn("--engine 3.5", buf.getvalue())
        from arrayprobe._v314_lazy import engine_present
        if engine_present():
            self.assertIn("--engine 3.1.4 --port-validation", buf.getvalue())
        else:
            # The public distribution omits v3.1.4, so its refusal must not offer it.
            self.assertNotIn("--engine 3.1.4", buf.getvalue())


class AGatedRunIsStamped(_Base):

    @needs_v314_engine
    def test_with_the_flag_the_run_is_stamped_port_validation(self):
        rc, out = self.run_main("--engine", "3.1.4", "--port-validation", "--stages", "234")
        stem = "base160101000000"
        files = {
            "decode": self.out / f"{stem}.H.cdf",
            "proc": self.out / f"proc.{stem}.H.nc",
            "sd": self.out / f"sd.{stem}.H.nc",
        }
        stamps = {}
        for what, path in files.items():
            if path.exists():
                stamps[what] = run_flight.read_stamp(path)
        # Stage 4 on the demo flight skips for want of an airspeed record and exits 1 (see
        # test_run_flight_s4_skip_names_the_cause.py), so no sd file is written here; the sd label
        # is held to the same form by test_the_labels_carry_the_token_once_only_under_314, and the
        # decode and proc stamps, written by the real run, must exist and carry the token.
        self.assertIn("decode", stamps, out)
        self.assertIn("proc", stamps, out)
        for what, stamp in stamps.items():
            with self.subTest(file=what):
                self.assertIsNotNone(stamp, f"{what} has no .call stamp:\n{out}")
                self.assertTrue(stamp.startswith("engine=3.1.4 port_validation=on "), stamp)
                self.assertEqual(stamp.count("port_validation="), 1, stamp)
        self.assertIn(rc, (0, 1), out)  # never 2: the gate accepted the run

    def test_the_labels_carry_the_token_once_only_under_314(self):
        """The one writer, ``_engine_prefix``: the token rides the prefix under v3.1.4 with the
        flag, and nowhere else (engine 3.5, or v3.1.4 at its default global)."""
        run_flight.ENGINE, run_flight.PORT_VALIDATION = "3.1.4", True
        self.assertEqual(run_flight._engine_prefix(), "engine=3.1.4 port_validation=on ")
        label = run_flight.sd_call_label(run_flight.IAT_FILE)
        self.assertEqual(label.count("port_validation="), 1, label)
        self.assertTrue(label.startswith("engine=3.1.4 port_validation=on "), label)
        run_flight.PORT_VALIDATION = False
        self.assertEqual(run_flight._engine_prefix(), "engine=3.1.4 ")
        run_flight.ENGINE, run_flight.PORT_VALIDATION = "3.5", True
        self.assertEqual(run_flight._engine_prefix(), "engine=3.5 ")


@needs_file("scripts/oracles_2016_2ds.toml")
class ArchivedStampsStayCurrent(_Base):

    def _new_labels(self) -> tuple[str, str, str]:
        """The three labels the shipped ORACLES 2016 configuration resolves to today, from a real
        ``main()`` dry run with the flag (the same route tests/test_run_from_config.py takes)."""
        toml_dir = self.root / "scripts"
        toml_dir.mkdir()
        toml = toml_dir / SHIPPED_TOML.name
        toml.write_bytes(SHIPPED_TOML.read_bytes())
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = run_flight.main([str(self.raw), "--config", str(toml), "--preset",
                                  "ORACLES_2016_2DS_H", "--out", str(self.out), "--stages", "234",
                                  "--engine", "3.1.4", "--port-validation", "--dry-run", "--yes"])
        self.assertEqual(rc, 0, buf.getvalue())
        return (run_flight.image_call_label(channels="H"), run_flight.proc_call_label(),
                run_flight.sd_call_label(run_flight.IAT_FILE))

    def test_an_archived_stamp_stays_current(self):
        image, proc, sd = self._new_labels()
        for golden, new in ((_DECODE_STAMP, image), (_PROC_STAMP, proc), (_SD_STAMP, sd)):
            self.assertTrue(new.startswith("engine=3.1.4 port_validation=on "), new)
            for old in (golden, "engine=3.1.4 " + golden):
                with self.subTest(old=old[:40]):
                    # An archived got against the new want: the case the gate must keep current.
                    self.assertTrue(run_flight._stamps_equivalent(old, new))
            # New got against an old want. A want with no ``engine=`` key at all is not expanded
            # on the got side (pre-existing, unrelated to the token), so the reverse is held only
            # for the stamp that already named its engine: the two differ by the token alone.
            self.assertTrue(run_flight._stamps_equivalent(new, "engine=3.1.4 " + golden))

    def test_the_strip_does_not_hide_a_real_difference(self):
        _, proc, _ = self._new_labels()
        self.assertIn("max_edge_img_ar=4", proc)
        changed = proc.replace("max_edge_img_ar=4", "max_edge_img_ar=6")
        self.assertFalse(run_flight._stamps_equivalent(_PROC_STAMP, changed))
        self.assertFalse(run_flight._stamps_equivalent(changed, _PROC_STAMP))

    def test_the_strip_reaches_the_token_inside_a_combine_stamp(self):
        inner_old = f"inputs_built_with=(engine=3.1.4 {_SD_STAMP})"
        inner_new = f"inputs_built_with=(engine=3.1.4 port_validation=on {_SD_STAMP})"
        old = f"engine=3.1.4 combine=oracles-fork:combine_sizedist.m inputs=a.nc {inner_old}"
        new = ("engine=3.1.4 port_validation=on combine=oracles-fork:combine_sizedist.m "
               f"inputs=a.nc {inner_new}")
        self.assertTrue(run_flight._stamps_equivalent(old, new))
        self.assertTrue(run_flight._stamps_equivalent(new, old))


class AFlightAcrossTheGateCombines(_Base):

    def _sd_files(self, old_stamp: str = "engine=3.1.4 " + _SD_STAMP) -> list[Path]:
        """Two sd files, one stamped as the pre-gate engine=3.1.4 form, one with the token."""
        old = self.root / "sd.base160101000000.H.nc"
        new = self.root / "sd.base160101000100.H.nc"
        old.write_bytes(b"")
        new.write_bytes(b"")
        run_flight.call_path(old).write_text(old_stamp + "\n")
        run_flight.call_path(new).write_text("engine=3.1.4 port_validation=on " + _SD_STAMP + "\n")
        return [old, new]

    def test_a_flight_before_engine_keys_also_passes_the_provenance_check(self):
        """The oldest form (no ``engine=``) against a gated one: ``check_combine_provenance``
        canonicalises the missing key, and now the token, so it does not read as MIXED."""
        old, new = self._sd_files(old_stamp=_SD_STAMP)
        with redirect_stdout(io.StringIO()):
            # None when the pair is one configuration; UnverifiableProvenance if it reads MIXED.
            self.assertIsNone(
                run_flight.check_combine_provenance([(old.name, old), (new.name, new)]))

    def test_a_flight_of_old_and_new_sd_stamps_combines(self):
        old, new = self._sd_files()
        present = [(old.name, old), (new.name, new)]
        with redirect_stdout(io.StringIO()):
            run_flight.check_combine_provenance(present)  # raises UnverifiableProvenance if MIXED
        run_flight.ENGINE, run_flight.PORT_VALIDATION = "3.1.4", True
        stamp = run_flight._combine_stamp([old, new])
        self.assertNotIn("MIXED(", stamp)
        self.assertTrue(stamp.startswith("engine=3.1.4 port_validation=on combine="), stamp)

    def test_a_real_mixture_is_still_refused(self):
        """The dedup strips only the token: sd files that differ in a threshold still read MIXED."""
        old, new = self._sd_files()
        run_flight.call_path(new).write_text(
            "engine=3.1.4 port_validation=on "
            + _SD_STAMP.replace("max_edge_img_ar=4", "max_edge_img_ar=6") + "\n")
        present = [(old.name, old), (new.name, new)]
        with redirect_stdout(io.StringIO()), self.assertRaises(run_flight.UnverifiableProvenance):
            run_flight.check_combine_provenance(present)


@needs_file("scripts/oracles_2016_2ds.toml")
class ArrayprobeRunForwardsTheFlag(_Base):
    """``arrayprobe run <v3.1.4 toml>`` (cli._run) forwards ``--port-validation`` and never adds it
    from the engine: the refusal is ``run_flight.main``'s, so both entry points agree."""

    def setUp(self):
        super().setUp()
        tools_dir = self.root / "scripts"
        tools_dir.mkdir()
        self.toml = tools_dir / SHIPPED_TOML.name
        shutil.copy(SHIPPED_TOML, self.toml)

    def _run(self, *extra: str) -> tuple[int, str]:
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(buf):
            rc = cli.main(["run", str(self.toml), str(self.raw), "--dry-run", *extra])
        return rc, buf.getvalue()

    def test_the_shipped_314_config_is_refused_without_the_flag(self):
        rc, out = self._run()
        self.assertEqual(rc, 2, out)
        self.assertIn(_REFUSAL, out)

    def test_arrayprobe_run_forwards_the_flag(self):
        rc, out = self._run("--port-validation")
        self.assertEqual(rc, 0, out)
        self.assertNotIn(_REFUSAL, out)

    def test_the_flag_is_in_the_run_help(self):
        help_text = cli.build_parser()._subparsers._group_actions[0].choices["run"].format_help()
        self.assertIn("--port-validation", help_text)


if __name__ == "__main__":
    unittest.main()
