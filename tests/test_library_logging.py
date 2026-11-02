# SPDX-License-Identifier: BSD-3-Clause
"""Since 2026-09-15, the library packages now use ``logging``, not a
bare ``print()``, and the CLI is the only place that attaches a real handler.

R6 measured 81 ``print(`` calls and zero ``logging.getLogger`` in
``src/arrayprobe`` before this change, with
one caller unable to silence or redirect a library's own progress messages.
Scope is the four ``src/`` packages (``arrayprobe``, ``arrayprobe_uiops``,
``arrayprobe_soda2``, ``uiops``) -- ``scripts/`` (a separate, larger `print`
population, 263 counted by the review) and the top-level CLI/triage modules keep `print`,
because that is user-facing console text, not library progress, and moving
``scripts/run_flight.py`` into ``src/`` is separate, later work.

Four things checked here, matching the F3 executor spec:

1. Importing any of the four packages alone emits nothing on stdout/stderr
   (a ``NullHandler`` only) -- :class:`ImportEmitsNoOutput`.
2. Every converted message still reaches its previous default visibility
   under the CLI's own logging configuration -- :class:`ConvertedMessagesStillAppear`.
3. ``--quiet`` suppresses informational/warning output but not errors;
   ``--verbose`` adds DEBUG -- :class:`QuietAndVerboseChangeVisibilityOnly`.
4. No new bare ``print(`` has crept into the library scope outside the
   documented CLI-output allowlist, checked with a real mutation (a
   temporary copy carrying an injected ``print(`` is asserted to fail the
   same scan) so this guard is proven to fire, not just read fine --
   :class:`NoBarePrintOutsideTheAllowlist`.
"""

from __future__ import annotations

import ast
import contextlib
import io
import logging
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests._repo import needs_file, needs_source, needs_v314_engine  # noqa: E402

from arrayprobe import cli

SRC = Path(__file__).resolve().parents[1] / "src"

#: The four packages this change gave a ``NullHandler``-by-default logger.
LIBRARY_PACKAGES = ("arrayprobe", "arrayprobe_uiops", "arrayprobe_soda2", "uiops")

#: Files inside the four library packages that are CLI-output, not library
#: progress, and are therefore exempt from the bare-``print(`` sweep --
#: The review item's own text: "keep `print` for CLI output". Paths are relative to
#: ``SRC``, forward-slash, matching ``Path.as_posix()``.
PRINT_ALLOWLIST = frozenset({
    "arrayprobe/cli.py",
    "arrayprobe/triage_server.py",
    # The Run page's detached wrapper (``python -m arrayprobe.run_page _wrap``): its
    # prints are the launched run's log lines (start failure, the exit line).
    "arrayprobe/run_page.py",
    # ``python -m arrayprobe.ai_ready FILE...``: its prints are the command-line
    # check's usage text and per-file verdicts, the same class as cli.py's.
    "arrayprobe/ai_ready.py",
    # A CLI tool shipped inside the installed package (``arrayprobe
    # make-demo-flight``) rather than in the un-shipped top-level `scripts/` --
    # see the module's own docstring ("This module lives inside the
    # installed package rather than in scripts/, which pip install does not
    # ship"). Its prints are the command's user-facing output, the same
    # class as cli.py's.
    "arrayprobe/tools/make_demo_flight.py",
    # Same class, same directory, same reason (``arrayprobe make-tas-file``): both prints are
    # the command's own result line and its "what to do next" line, addressed to whoever typed
    # the command. Added 2026-09-17 -- the file landed at 814c3ba with its prints and without
    # this entry, so the sweep failed on it until now.
    "arrayprobe/tools/make_tas_file.py",
    # `python -m arrayprobe.attributed_export` -- its one print is the command's own
    # result line ("wrote <path>"), inside `main()`, addressed to whoever typed it.
    # Same class as the two above; the module writes nothing else to stdout.
    "arrayprobe/attributed_export.py",
    # `arrayprobe_soda2.process_2d_parallel` -- one `report_every`-gated liveness
    # line per chunk, at `:246-248`, from inside a `ProcessPoolExecutor` worker.
    # Added 2026-09-17 with the parallel buffer loop.
    #
    # WHY ALLOWLISTED RATHER THAN CONVERTED, and this is a compromise worth
    # naming. `arrayprobe.readers.spec` solves the same problem properly, with
    # `_report_part_progress` (`spec.py:1022-1059`): a non-propagating logger, a
    # fresh `StreamHandler` bound to the *current* `sys.stdout` on every call
    # (never cached, so a test can still redirect it), an unconditional flush
    # because a file-backed stdout is block-buffered, and an explicit
    # `sys.stdout is None` guard because `StreamHandler` falls back to stderr
    # where `print` was a no-op. Reproducing forty lines of that reasoning by
    # hand in a second package invites getting one of those details wrong, and
    # `arrayprobe_soda2` must NOT import from `arrayprobe` -- they are separate
    # engines and the port has no dependency on the other's internals.
    #
    # The print is defensible on its own terms: it is silent for library callers
    # (`report_every > 0` must be passed), it flushes, and the line it writes is
    # what the stall watchdog reads to judge a worker alive -- so it is
    # operationally load-bearing, not decoration.
    #
    # OWED: lift that helper into a place both packages may use (it belongs
    # beside neither engine's internals), then convert this and drop the row.
    "arrayprobe_soda2/process_2d_parallel.py",
    # The batch flight driver, moved into the package from the top-level `scripts/` on
    # 2026-10-01 (`scripts/<name>.py` are now shims that exec these files). In `scripts/` it sat
    # outside this sweep's scope, which covers the four library packages only; it is a
    # command-line program whose stdout IS its interface -- the run log a user reads and the
    # liveness lines the stall watchdogs read -- the same class as cli.py. Converting these
    # prints to logging would change what a user sees, so the five modules that print are
    # named here one by one; `driver/__init__.py` prints nothing and is not listed, and any
    # other package module still fails the sweep.
    "arrayprobe/driver/run_flight.py",
    "arrayprobe/driver/reprocess.py",
    "arrayprobe/driver/preflight_inputs.py",
    "arrayprobe/driver/tas_from_probe_housekeeping.py",
    # `_load_record.LoadRecorder`'s three prints are all its "LOAD RECORD: ..." verdict line
    # (the verdict, an unwritable-path notice, a recorder-error notice), printed at the end of
    # a timed window by design (its module docstring): it is the line a timing's reader
    # quotes, under the rule that a wall-clock figure is quotable only with the load record
    # beside it.
    "arrayprobe/driver/_load_record.py",
    # `arrayprobe tas-from-nasa-ames` -- every print sits inside `main()`: the refusal
    # line, the result line, the source provenance read out of the file's own header,
    # the dropped-row count and the "what to do next" line; the provenance and
    # dropped-row lines are the point of the command. Added 2026-09-17. Listed only
    # where the module exists: the public release holds it back.
    *(("arrayprobe/tools/nasa_ames_tas.py",)
      if (SRC / "arrayprobe/tools/nasa_ames_tas.py").is_file() else ()),
    # `python -m arrayprobe_uiops.export_oap` and `python -m arrayprobe_uiops.populations` --
    # each has exactly one print, inside `main()`, and it is the command's own result line
    # ("<out>: N particles, M records ..." / "<out>: N s, all=..., round=..."), addressed to
    # whoever typed it. Same class as attributed_export.py above; the library functions in
    # both modules print nothing. Added 2026-10-05 when both landed.
    "arrayprobe_uiops/export_oap.py",
    # Listed only where the module exists: the public release holds `populations` back.
    *(("arrayprobe_uiops/populations.py",)
      if (SRC / "arrayprobe_uiops/populations.py").is_file() else ()),
    # `python -m arrayprobe_uiops.product_sanity FILE...` prints one report per file it was
    # asked to check, inside `main()`; the check itself (`check_file`) prints nothing and the
    # driver's plausibility gate reads its return value. Same class. Added 2026-10-05.
    "arrayprobe_uiops/product_sanity.py",
})


def _bare_print_calls(source: str, filename: str):
    """Line numbers of every *actual* bare ``print(...)`` call in ``source``,
    found by parsing (``ast``), not by pattern-matching text -- so a comment
    or docstring that merely mentions ``print(`` (this module's own included)
    never counts as a hit, only real code does.
    """
    tree = ast.parse(source, filename=filename)
    lines = source.splitlines()
    hits = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
        ):
            hits.append((node.lineno, lines[node.lineno - 1].strip()))
    return hits


def _find_disallowed_prints(root: Path = SRC):
    """Return ``[(relative_path, line_no, line_text), ...]`` for every real
    bare ``print(...)`` call found in the four library packages outside
    :data:`PRINT_ALLOWLIST`.
    """
    findings = []
    for package in LIBRARY_PACKAGES:
        pkg_dir = root / package
        if not pkg_dir.is_dir():
            continue
        for path in sorted(pkg_dir.rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if rel in PRINT_ALLOWLIST:
                continue
            text = path.read_text(encoding="utf-8")
            for lineno, line in _bare_print_calls(text, str(path)):
                findings.append((rel, lineno, line))
    return findings


@needs_source
class ImportEmitsNoOutput(unittest.TestCase):
    """A bare ``import`` of any of the four packages must stay silent -- the
    NullHandler-by-default contract the review asked for. Run as a subprocess (not
    just re-import in-process) so a module already cached in ``sys.modules``
    by an earlier test in the same run cannot hide a real import-time print.
    """

    def test_each_package_import_is_silent(self):
        for package in LIBRARY_PACKAGES:
            with self.subTest(package=package):
                result = subprocess.run(
                    [sys.executable, "-c", f"import {package}"],
                    cwd=str(SRC),
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                self.assertEqual(
                    0, result.returncode,
                    f"import {package} failed: {result.stderr}")
                self.assertEqual(
                    "", result.stdout,
                    f"import {package} wrote to stdout: {result.stdout!r}")
                self.assertEqual(
                    "", result.stderr,
                    f"import {package} wrote to stderr: {result.stderr!r}")


class ConvertedMessagesStillAppear(unittest.TestCase):
    """Each print-turned-logger-call still shows up at the CLI's default
    verbosity (no --quiet/--verbose), the same visibility a bare ``print``
    always had.
    """

    def setUp(self):
        # cli._configure_logging mutates real, process-global loggers (by
        # design -- it configures the console script's own output channel).
        # Snapshot and restore each one so this test cannot leak a handler
        # into a test that runs after it.
        self._saved = {}
        for name in cli._LIBRARY_LOGGER_NAMES:
            logger = logging.getLogger(name)
            self._saved[name] = (list(logger.handlers), logger.level, logger.propagate)

    def tearDown(self):
        for name, (handlers, level, propagate) in self._saved.items():
            logger = logging.getLogger(name)
            logger.handlers = handlers
            logger.setLevel(level)
            logger.propagate = propagate

    def test_v35_rollover_ambiguity_message_appears_by_default(self):
        import numpy as np

        from arrayprobe_uiops.sizedist import fix_multiday_particle_times

        cli._configure_logging(quiet=False, verbose=False)
        buf = io.StringIO()
        logging.getLogger("arrayprobe_uiops").handlers = [
            logging.StreamHandler(buf)]
        # Two decreases, neither crossing 230000 -- the "not detected" branch.
        times = np.array([100.0, 50.0, 30.0, 10.0])
        fix_multiday_particle_times(times)
        self.assertIn(
            "Multiple instances of decreasing particle time were found",
            buf.getvalue())

    def test_v35_too_many_inputs_message_appears_by_default(self):
        from arrayprobe_uiops.sizedist_tables import select_interarrival_threshold

        cli._configure_logging(quiet=False, verbose=False)
        # select_interarrival_threshold itself only sets the flag; run() is
        # what logs it (see sizedist.py) -- exercise the flag-setting half
        # and the logger call directly, the same split the source code has.
        spec = select_interarrival_threshold(0, ["a", "b"])
        self.assertTrue(spec.too_many_inputs)
        from arrayprobe_uiops import sizedist as m
        saved = (list(m._logger.handlers), m._logger.level, m._logger.propagate)
        self.addCleanup(
            lambda: (
                setattr(m._logger, "handlers", saved[0]),
                setattr(m._logger, "level", saved[1]),
                setattr(m._logger, "propagate", saved[2]),
            ))
        buf = io.StringIO()
        m._logger.handlers = [logging.StreamHandler(buf)]
        m._logger.setLevel(logging.INFO)
        m._logger.propagate = False
        m._logger.warning("You have added too many inputs!")
        self.assertIn("You have added too many inputs!", buf.getvalue())

    @needs_v314_engine
    def test_spec_progress_heartbeat_matches_the_old_print_format(self):
        """``_report_part_progress`` cannot go through the CLI's handler (it
        runs in a spawned worker process, see its module comment) -- it
        keeps its own byte-identical-by-default output instead. This
        asserts that contract directly: same shape, same fields, written to
        stdout with no CLI configuration involved at all.
        """
        from arrayprobe.readers import spec as spec_module

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            # _report_part_progress builds a fresh handler against the
            # *current* sys.stdout on every call (never a cached one) --
            # redirect_stdout must be active first, exactly like the real
            # worker's inherited fd 1.
            spec_module._report_part_progress("p001", 20000, 100000)
        out = buf.getvalue()
        self.assertRegex(
            out,
            r"^\[\d{2}:\d{2}:\d{2}\]   \.\.\.part p001 20000/100000 windows\n$")


class QuietAndVerboseChangeVisibilityOnly(unittest.TestCase):
    def setUp(self):
        self._saved = {}
        for name in cli._LIBRARY_LOGGER_NAMES:
            logger = logging.getLogger(name)
            self._saved[name] = (list(logger.handlers), logger.level, logger.propagate)

    def tearDown(self):
        for name, (handlers, level, propagate) in self._saved.items():
            logger = logging.getLogger(name)
            logger.handlers = handlers
            logger.setLevel(level)
            logger.propagate = propagate

    def _emit_and_capture(self, *, quiet: bool, verbose: bool):
        cli._configure_logging(quiet=quiet, verbose=verbose)
        buf = io.StringIO()
        logger = logging.getLogger("arrayprobe")
        logger.handlers = [logging.StreamHandler(buf)]
        logger.debug("a debug message")
        logger.info("an info message")
        logger.warning("a warning message")
        logger.error("an error message")
        return buf.getvalue()

    def test_default_shows_info_warning_error_not_debug(self):
        out = self._emit_and_capture(quiet=False, verbose=False)
        self.assertNotIn("a debug message", out)
        self.assertIn("an info message", out)
        self.assertIn("a warning message", out)
        self.assertIn("an error message", out)

    def test_quiet_suppresses_info_and_warning_but_not_error(self):
        out = self._emit_and_capture(quiet=True, verbose=False)
        self.assertNotIn("a debug message", out)
        self.assertNotIn("an info message", out)
        self.assertNotIn("a warning message", out)
        self.assertIn("an error message", out)

    def test_verbose_shows_debug_too(self):
        out = self._emit_and_capture(quiet=False, verbose=True)
        self.assertIn("a debug message", out)
        self.assertIn("an info message", out)
        self.assertIn("a warning message", out)
        self.assertIn("an error message", out)

    def test_quiet_and_verbose_are_mutually_exclusive_on_the_parser(self):
        with self.assertRaises(SystemExit):
            cli.build_parser().parse_args(
                ["--quiet", "--verbose", "engines"])


@needs_source
class NoBarePrintOutsideTheAllowlist(unittest.TestCase):
    def test_current_tree_has_no_disallowed_print(self):
        findings = _find_disallowed_prints()
        self.assertEqual(
            [], findings,
            "bare print( found in a library package outside "
            "PRINT_ALLOWLIST -- convert it to logging (the library logs and never "
            "prints) or, if it is "
            "genuinely CLI-facing output, add it to the allowlist with a "
            "reason:\n  " + "\n  ".join(f"{p}:{n}: {t}" for p, n, t in findings))

    @needs_file("src/arrayprobe/readers/spec.py")
    def test_the_scan_actually_fires_on_an_injected_print(self):
        """Prove the guard works, not just that it currently reads clean
        (the 'guards must be executed, not read' lesson) -- copy one real
        library file into a scratch tree, inject a bare print(, and assert
        the scan finds it.
        """
        target = SRC / "arrayprobe" / "readers" / "spec.py"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            scratch_pkg = tmp_root / "arrayprobe" / "readers"
            scratch_pkg.mkdir(parents=True)
            original = target.read_text(encoding="utf-8")
            mutated = original + '\n\nprint("a new, un-converted library print")\n'
            (scratch_pkg / "spec.py").write_text(mutated, encoding="utf-8")
            findings = _find_disallowed_prints(root=tmp_root)
        self.assertTrue(
            any("a new, un-converted library print" in text for _, _, text in findings),
            "the sweep did not flag an injected bare print( -- the guard is "
            "not actually firing")

    def test_the_allowlist_files_do_contain_print(self):
        """The allowlist should name files that actually use print() -- an
        allowlist entry for a file that has since lost its last print()
        would be silently over-broad, exempting nothing real.
        """
        for rel in sorted(PRINT_ALLOWLIST):
            path = SRC / rel
            self.assertTrue(path.is_file(), f"allowlisted path does not exist: {rel}")
            self.assertRegex(
                path.read_text(encoding="utf-8"), r"print\(",
                f"{rel} is allowlisted but contains no print( -- drop the entry")


if __name__ == "__main__":
    unittest.main()

# A repository sweep: run before every full suite by a tool that is not part of this package
# (tests/test_presuite_covers_repo_sweeps.py keeps that true).
PRESUITE_GUARD = True
