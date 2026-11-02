# SPDX-License-Identifier: BSD-3-Clause
"""The attributed export is REACHABLE -- from the installed command and from the driver.

``tests/test_attributed_export.py`` proves the export is correct. This file proves a user can
get at it, which is the half that is the deliverable: *"this is an important user-facing
deliverable for the package"*. Before this, the only way in was
``python -m arrayprobe.attributed_export``, which someone who installed the package and read
``arrayprobe --help`` would never find, and a finished flight never produced one.

**Both states are asserted, because the addition is opt-in and default-off** (
"Any behaviour-changing deviation is an opt-in flag, defaulting OFF, with a test for both
states"): the driver's ``--attributed`` defaults to ``False``, both of ``stage_combine``'s
calls to :func:`run_flight.write_attributed` are gated on it, and with the flag on the sibling
appears while **the faithful product's SHA-256 does not move** -- the invariant the whole
module exists to protect.

The two sides of the CLI check come from different places ("A check must draw
its two sides from different places"): the subcommand's behaviour is compared against
``attributed_export``'s own defaults (:data:`ae.DEFAULT_SUFFIX`), not against a string repeated
here.
"""

from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path

from netCDF4 import Dataset
from tests._driver import driver_source

from arrayprobe import attributed_export as ae
from arrayprobe import cli

# The fixture writer is reused from the correctness suite rather than copied, so a change to
# what a faithful product looks like reaches both files at once.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from test_attributed_export import STAMP, _faithful  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "run_flight", Path(__file__).resolve().parent.parent / "scripts" / "run_flight.py")
# Use whichever module object is REGISTERED -- an unconditional overwrite clobbers another
# test module's registration when both run in one process (the same comment, and the same
# reason, as test_attributed_export.py and test_run_flight_provenance.py).
assert _SPEC is not None and _SPEC.loader is not None
if _SPEC.name in sys.modules:
    run_flight = sys.modules[_SPEC.name]
else:
    run_flight = importlib.util.module_from_spec(_SPEC)
    sys.modules[_SPEC.name] = run_flight
    _SPEC.loader.exec_module(run_flight)


class _Tmp(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


class TheInstalledCommandReachesIt(_Tmp):
    """``arrayprobe attributed`` exists, and does what the module form does."""

    def test_the_subcommand_is_registered(self):
        parser = cli.build_parser()
        actions = [a for a in parser._actions if hasattr(a, "choices") and a.choices]
        names = set()
        for action in actions:
            with contextlib.suppress(TypeError):
                names |= set(action.choices)
        self.assertIn("attributed", names,
                      "`arrayprobe attributed` must be a subcommand: the module form is not "
                      "discoverable from `arrayprobe --help`, and the author calls this the "
                      "user-facing deliverable")

    def test_it_writes_the_module_forms_default_path(self):
        source = _faithful(self.dir)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            status = cli.main(["attributed", str(source)])
        self.assertEqual(status, 0)
        # The expected path is asked of the module, never spelled out here.
        self.assertTrue(ae.default_output_path(source).exists())

    def test_an_explicit_output_path_is_honoured(self):
        source = _faithful(self.dir)
        out = self.dir / "elsewhere.nc"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["attributed", str(source), str(out)]), 0)
        self.assertTrue(out.exists())
        self.assertFalse(ae.default_output_path(source).exists())

    def test_an_unstamped_product_is_refused_and_the_flag_overrides(self):
        source = _faithful(self.dir, stamp=None)
        # Since 2026-09-26 the command line reports the refusal in one line, exit 2, naming
        # the flag, rather than a MissingStampError traceback (the library still raises it).
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            self.assertEqual(cli.main(["attributed", str(source)]), 2)
        self.assertIn("--accept-unstamped", err.getvalue())
        self.assertFalse(ae.default_output_path(source).exists())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(
                cli.main(["attributed", str(source), "--accept-unstamped"]), 0)
        ds = Dataset(str(ae.default_output_path(source)), "r")
        try:
            self.assertIn("ABSENT", ds.getncattr("arrayprobe_call_stamp"))
        finally:
            ds.close()

    def test_enhancements_reach_the_exporter(self):
        source = _faithful(self.dir)
        with contextlib.redirect_stdout(io.StringIO()):
            cli.main(["attributed", str(source), "--enhancements", "alpha,beta"])
        ds = Dataset(str(ae.default_output_path(source)), "r")
        try:
            self.assertEqual(ds.getncattr("arrayprobe_enhancements_applied"), "alpha,beta")
        finally:
            ds.close()


class TheDriverFlagIsOffByDefault(unittest.TestCase):
    """OFF is the default, and it is the parser that says so -- not this file."""

    def test_the_flag_exists_and_is_a_store_true(self):
        """The driver builds its parser inside ``main``, so the declaration is read instead.

        ``action="store_true"`` is what makes the default ``False``; asserting the action is
        asserting the default, and it fails if someone gives the flag an explicit truthy
        default later.
        """
        tree = ast.parse(driver_source("run_flight.py").read_text(encoding="utf-8"))
        decls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and getattr(node.func, "attr", None) == "add_argument"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "--attributed"
        ]
        self.assertEqual(len(decls), 1, "--attributed must be declared exactly once")
        kw = {k.arg: k.value for k in decls[0].keywords}
        self.assertIn("action", kw)
        self.assertEqual(kw["action"].value, "store_true",
                         "--attributed must default to OFF: a run writes what it says it "
                         "writes, and an extra product nobody asked for is a surprise")
        self.assertNotIn("default", kw, "a store_true flag's default is False; do not override")

    def test_stage_combine_defaults_the_parameter_off(self):
        import inspect

        sig = inspect.signature(run_flight.stage_combine)
        self.assertIn("attributed", sig.parameters)
        self.assertIs(sig.parameters["attributed"].default, False)


class EveryCallSiteIsGated(unittest.TestCase):
    """No path through ``stage_combine`` writes the sibling unless the flag asked for it.

    Read off the source tree rather than asserted in prose: a future edit that calls
    :func:`run_flight.write_attributed` unconditionally -- turning an opt-in addition into a
    file every run writes -- fails here, which a signature default cannot catch.
    """

    def test_both_calls_inside_stage_combine_are_under_if_attributed(self):
        source = driver_source("run_flight.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        func = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "stage_combine")
        calls = [n for n in ast.walk(func)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "write_attributed"]
        self.assertEqual(len(calls), 2,
                         "expected the finished-combine path and the already-current skip path")
        guarded = []
        for node in ast.walk(func):
            if isinstance(node, ast.If) and isinstance(node.test, ast.Name) \
                    and node.test.id == "attributed":
                guarded += [n for n in ast.walk(node)
                            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                            and n.func.id == "write_attributed"]
        self.assertEqual(len(guarded), len(calls),
                         "every write_attributed call in stage_combine must sit under "
                         "`if attributed:` -- the addition is opt-in, default-off")


class WithTheFlagOnTheFaithfulFileStillDoesNotMove(_Tmp):
    """ON writes the sibling; the faithful bytes are identical either side. The invariant."""

    def test_the_sibling_appears_and_the_source_hash_is_unchanged(self):
        source = _faithful(self.dir)
        before = ae.sha256_of(source)
        written = run_flight.write_attributed(source)
        self.assertIsNotNone(written)
        self.assertTrue(written.exists())
        self.assertEqual(ae.sha256_of(source), before,
                         "the faithful product is the byte-comparison artefact; a metadata "
                         "step that moved one of its bytes would break every validated flight")
        ds = Dataset(str(written), "r")
        try:
            self.assertEqual(ds.getncattr("arrayprobe_call_stamp"), STAMP)
            self.assertEqual(ds.variables["Bin Midpoints"].units, "mm")
        finally:
            ds.close()

    def test_a_failure_is_logged_and_the_flight_is_not_lost(self):
        """An unexportable product must not fail a finished flight -- it is already written."""
        source = _faithful(self.dir, stamp=None)
        self.assertIsNone(run_flight.write_attributed(source, accept_unstamped=False))
        self.assertFalse(ae.default_output_path(source).exists())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
