# SPDX-License-Identifier: BSD-3-Clause
"""Every fidelity-sensitive CLI argument survives both subprocess re-execs.

WHY THIS EXISTS. ``run_flight.py`` re-execs itself as a fresh subprocess twice
-- ``_spawn_worker`` for ``--jobs``, and ``stage3``'s ``cmd_base`` for
``--chunks`` -- and each fresh process starts at this module's *import-time*
defaults, not the parent's resolved settings. Three flags have already gone
missing from ``_spawn_worker``'s explicit list and been found one at a time,
each the same shape (a silent, wrong-output bug, not a crash): ``--diode-
corrected`` (2026-08-27), ``--accept-unstamped``, ``--s2-jobs`` (2026-09-06).
A fourth, ``--preset``/``--presets``/``--config``/``--allow-mixed-config``, was
found 2026-09-10 -- missing from ``_spawn_worker`` entirely, which meant any
``--jobs > 1`` run under a non-default campaign or config silently processed
every worker under the argparse default instead.

Four instances of one bug is a pattern, not four bugs, per the author's own
standing instruction that this must hold for "any and all such
enhancements_uiops/functions/capabilities now and forever added to the package".
This is the mechanical version: it reads the CLI's own flag list from
the parser-building source and asserts each fidelity-sensitive one is
forwarded by BOTH re-exec sites, so the next flag added to ``main()`` fails
this test rather than waiting to be found the same way the first four were.

It is a RATCHET, the same shape ``test_flag_coverage.py`` already uses:
``_EXEMPT`` may shrink freely; growing it means writing down why a flag is
allowed to NOT survive a re-exec (only true for flags that name something
specific to the parent's own invocation, like ``--out`` or ``--dry-run``, or
that are deliberately transformed rather than forwarded verbatim, like
``--stages``).
"""
from __future__ import annotations

import importlib.util
import inspect
import re
import sys
import unittest
from pathlib import Path

from tests._driver import driver_source

TOOLS = Path(__file__).resolve().parent.parent / "scripts"
SOURCE = driver_source("run_flight.py").read_text(encoding="utf-8")

# Loaded the same way test_run_flight.py does: this is a scripts/ script, not
# an installed package module, so it has no import path of its own.
_SPEC = importlib.util.spec_from_file_location("run_flight", TOOLS / "run_flight.py")
assert _SPEC is not None and _SPEC.loader is not None
run_flight = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault("run_flight", run_flight)
_SPEC.loader.exec_module(run_flight)

_FLAG = re.compile(r'ap\.add_argument\("(--[a-z0-9-]+)"')

#: Flags that name something specific to the PARENT's own invocation (an
#: output directory, a dry-run switch) or that a re-exec deliberately
#: transforms rather than passes through verbatim -- each with why.
_EXEMPT = {
    "--out": "the worker writes into the same directory the parent already "
             "resolved; passed through, but as a derived value, not itself",
    "--dry-run": "a dry run never reaches the point of spawning a worker at all",
    "--jobs": "the worker IS one of --jobs's own workers; forwarding it back "
              "would recursively fan out rather than run one job",
    "--borrowed-combine": "combine ('c') never runs in a --jobs worker -- _spawn_worker strips "
              "'c' from the worker's stages (run_flight.py:1510) -- and the driver refuses the "
              "flag under the v3.1.4 engine, so forwarding it would make every 3.5 worker refuse "
              "a run its parent accepted",
    "--attributed": "the same class as --borrowed-combine, and exempt for the same reason: the "
              "attributed sibling is written beside the COMBINED product at S4c, which no --jobs "
              "or --chunks worker ever reaches (_spawn_worker strips 'c'). Added 2026-09-18 with "
              "the flag itself; this entry is the second half of that change, which the flag's "
              "own commit omitted -- the sweep caught it the same day. Forwarding it would make "
              "each worker try to write an attributed export for a product it does not produce",
    "--enhancements": "the same class as --attributed, added 2026-09-21 with the same omission "
              "and caught the same way. The corrections are applied AFTER every stage finishes, "
              "to the products the parent run wrote (run_flight.main's post-stage block); a "
              "--jobs worker has produced no combined product and a --chunks worker has produced "
              "no sd at all. Forwarding it would have each worker try to enhance files it did "
              "not write",
    "--enh-jobs": "read only by the parent's post-stage enhancement pass, as --enhancements is "
              "(above): no worker applies a correction, so no worker has a reject loop to "
              "spread, and the parent reaches the pass only after every worker has exited",
    "--write-provenance": "exempt for a STRONGER reason than the others here: the driver REFUSES "
              "--write-provenance together with --chunks or --jobs outright (and together with "
              "--engine 3.5), before any worker is spawned. So a worker can never legitimately "
              "receive it -- forwarding it would build a command line the driver itself rejects",
}


def _all_flags() -> list[str]:
    flags = _FLAG.findall(SOURCE)
    assert flags, "no ap.add_argument(\"--...\") calls found -- the regex or the file moved"
    return flags


def _hidden_without_v314() -> set[str]:
    """Flags whose ``help=`` is a conditional with an ``argparse.SUPPRESS`` branch, read from
    the parser-building source's AST."""
    import ast
    hidden = set()
    for node in ast.walk(ast.parse(SOURCE)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument" and node.args
                and isinstance(node.args[0], ast.Constant)):
            continue
        help_kw = next((k.value for k in node.keywords if k.arg == "help"), None)
        if isinstance(help_kw, ast.IfExp) and any(
                isinstance(b, ast.Attribute) and b.attr == "SUPPRESS"
                for b in (help_kw.body, help_kw.orelse)):
            hidden.add(node.args[0].value)
    return hidden


def _function_source(name: str) -> str:
    return inspect.getsource(getattr(run_flight, name))


def _forwarded(flag: str, src: str) -> bool:
    """Whether ``flag`` is actually built into a subprocess command line in
    ``src``, not merely mentioned in a comment or docstring.

    Requires the QUOTED form (``"--preset"``, with the literal quote
    characters) -- forwarding a flag always means putting that exact string
    into a list passed to ``subprocess.Popen``, which needs the quotes; a
    comment referencing the flag by name does not. Mutation-tested 2026-09-10:
    a version of this check that matched the bare flag name passed with
    ``--preset``'s forwarding code deleted outright, because a neighbouring
    comment about a DIFFERENT flag ("must travel with --preset") still
    mentioned it in prose.
    """
    return f'"{flag}"' in src


class EveryFidelitySensitiveFlagSurvivesBothReExecs(unittest.TestCase):
    def test_every_non_exempt_flag_is_forwarded_by_spawn_worker(self):
        src = _function_source("_spawn_worker")
        # --chunks, --s2-jobs, --iat-file, --stages, --preset, --presets,
        # --config, --accept-unstamped, --diode-corrected and
        # --allow-mixed-config are all named literally in the function body
        # (unconditionally, or behind an `if args.<flag>: cmd.append("--flag")`
        # guard) -- a flag forwarded neither way is missing, by construction:
        # the subprocess command line must contain the literal string somewhere.
        missing = [f for f in _all_flags() if f not in _EXEMPT and not _forwarded(f, src)]
        self.assertEqual(
            missing, [],
            f"these flags are not forwarded to --jobs workers: {missing}. "
            "Either forward them in _spawn_worker, or add them to _EXEMPT "
            "here with the reason they may legitimately not survive.")

    def test_every_non_exempt_flag_is_forwarded_by_the_chunk_worker(self):
        src = _function_source("stage3")
        missing = [f for f in _all_flags() if f not in _EXEMPT and not _forwarded(f, src)]
        # stage3's chunk worker (--_run-chunk) is a narrower re-exec than
        # --jobs's: it runs one chunk of one already-selected file, so it
        # only needs the settings that affect HOW that one chunk is framed
        # (PROBE/PROJECT/PROFILE, threaded via cmd_base) -- not --stages,
        # --iat-file (an S4-only setting), --accept-unstamped/--diode-
        # corrected (S2/whole-flight concerns), or the preset/config
        # machinery that already resolved PROFILE before stage3 was called.
        stage3_exempt = {
            "--stages", "--iat-file", "--accept-unstamped", "--diode-corrected",
            # --iat-source resolves S4's twelfth argument; a --_run-chunk re-exec runs one S3 chunk.
            "--iat-source",
            "--preset", "--presets", "--config", "--allow-mixed-config",
            "--s2-jobs", "--jobs",
            # S4-only, as --iat-file: a --_run-chunk re-exec computes one S3 chunk.
            "--tas-max", "--pecan-params",
            # Protective set: a --_run-chunk re-exec computes one S3 chunk and writes no stamp; the
            # parent that merges the chunks stamps the proc file with the protective fragment.
            "--protective",
            # --libm-pow (B9) changes only S4's massBL; a --_run-chunk re-exec runs one S3 chunk.
            "--libm-pow",
            # The probe-clock offset is an S4 (sizeDist) keyword; a --_run-chunk re-exec runs
            # one S3 chunk.
            "--time-offset-s", "--time-offset-evidence", "--time-offset-tas-clock",
            # --port-validation (R4, the removable-leaf rule): a --_run-chunk re-exec returns before
            # main()'s parser and gate, and writes no .call; the parent that merges the chunks
            # stamps the proc file.
            "--port-validation",
            # --accept-implausible overrides the post-S4 plausibility gate; a
            # --_run-chunk re-exec runs one S3 chunk and returns before S4, so it never writes
            # an sd or its stamp. The --jobs worker, which does run S4, forwards it.
            # Preflight-only (raw extension vs preset probe, C11): a --_run-chunk re-exec runs no
            # preflight; the parent checks the file and stamps the proc file.
            "--accept-preset-mismatch",
            "--accept-implausible",
            # --chunks itself is what triggers this whole cmd_base -- a
            # --_run-chunk re-exec processes exactly one already-divided
            # chunk, so passing --chunks again would mean "chunk this chunk",
            # not describe how many pieces THIS invocation is.
            "--chunks",
            # --resume-chunks decides, in the parent, which chunks are spawned at all; a
            # worker builds its one chunk the same way either way. What it does carry is the
            # intent hash, as an `intent=` token (tests/test_run_flight_chunk_resume.py).
            "--resume-chunks",
            # --tas-from-probe (CIP) builds <stem>.tas.csv in the parent before S3; a chunk
            # worker computes S3 only and never reads the 2D-S housekeeping it names.
            "--tas-from-probe",
            # --tas-file is threaded into cmd_base as a POSITIONAL (TAS_FILE or ""),
            # exactly like PROFILE.name/PROFILE_MODULE, so the literal flag never
            # appears in stage3; test_run_from_config_tas.py's
            # ChunkWorkerCarriesTheTasFile proves the positional is built and consumed.
            "--tas-file",
            # --tas-source/--tas-search/--tas-cutoff-mps/--tas-default-mps
            # (merged into this branch 2026-09-23) resolve to values already threaded another
            # way, the same shape as --preset/--config resolving to PROFILE below. The PARENT's
            # serial per-file loop calls _tas_sources.resolve_chain(TAS_SOURCE, ...) and, when
            # PROFILE.time_in_seconds_from_tas, reassigns the module-level TAS_FILE to the
            # resolved chain file BEFORE stage3 runs (run_flight.py:4556-4570) -- so TAS_FILE,
            # already threaded as a positional just above, carries --tas-source's effect too.
            # Cutoff and default are captured the same way through TAS_POLICY, built from
            # args.tas_cutoff_mps/args.tas_default_mps unconditionally (:4311-4320) and
            # threaded via the trailing tas_policy= token (:2390), read back at :3764. Traced
            # by reading the data flow, not run as a --chunks + --tas-source subprocess: that
            # combination has no dedicated integration test yet (test_run_flight_tas_chain.py
            # has none), so this exemption is the discriminating claim a future test should
            # confirm, not one this pass measured directly.
            "--tas-source", "--tas-search", "--tas-cutoff-mps", "--tas-default-mps",
            # --worker-stall-min travels the same positional way (str(worker_stall_min),
            # cmd[9]); test_run_flight_chunk_watchdog.py's
            # test_worker_stall_min_reaches_the_chunk_workers_positional_argv proves it
            # arrives. _spawn_worker forwards it literally since pair G (2026-09-13).
            "--worker-stall-min",
            # --profile travels the SAME positional way PROFILE.name/PROFILE_MODULE already do
            # in cmd_base (measured 2026-09-21: seven PROFILE.name and five PROFILE_MODULE
            # references inside stage3, none of them the literal flag), so this regex cannot see
            # it. The flag was added 2026-09-21; the positional route predates it.
            "--profile",
            # --probe-case / --probe-case-module select a bin ladder for sizeDist, and a
            # --_run-chunk re-exec runs STAGE 3 ONLY -- measured 2026-09-21: `sizeDist` appears
            # zero times in stage3. A chunk worker never reaches the code these flags configure,
            # so forwarding them would describe a stage the worker does not run. (_spawn_worker,
            # which DOES reach S4, forwards both, with its own test.)
            "--probe-case", "--probe-case-module",
            # --tas-grid (2026-09-25) chooses the time vector S4 hands sizeDist; TAS_GRID is read
            # only by sd_call_label, stage4 and the sizedist runner, never by stage3 (measured
            # 2026-09-25 by grep), so an S3-only chunk worker never reaches it. _spawn_worker,
            # which does reach S4, forwards it literally.
            "--tas-grid",
            # --stray-pixel (the stray-pixel rule, 2026-10-03) travels as a trailing keyed token
            # `stray_pixel=on|off` in stage3's jit_tail, and the --_run-chunk tail parser reads it
            # back (raising on any other value), so this literal-flag regex cannot see it.
            "--stray-pixel",
            # --ncar-2dc-timing (2026-10-07): main() refuses --chunks while the NCAR 2DC timing
            # conversion is on (test_run_flight_ncar_2dc_timing's
            # test_chunks_with_it_on_is_refused), so a chunk worker only ever runs with it off,
            # which is NCAR_2DC_TIMING's import-time value. If that refusal is ever lifted, the
            # value must travel in stage3's jit_tail like stray_pixel= does.
            "--ncar-2dc-timing",
            # --tas-ratio on travels as a trailing `tas_ratio=on` token in stage3's jit_tail
            # (absent means off), read back by the --_run-chunk tail parser into TAS_RATIO,
            # which _imgproc_sm_chunk's _s3_tas_ratio consults; this regex cannot see it.
            "--tas-ratio",
            # --engine travels as a trailing `engine=<v>` token, not as the literal flag
            # (run_flight.py's jit_tail), so this regex cannot see it. It became load-bearing
            # on 2026-09-17, when --chunks stopped being refused under engine 3.5 for
            # the record-local probetypes: before that a chunk worker only ever ran v3.1.4 and
            # the omission was unreachable. test_v35_imgproc_merge_chunks.py's
            # TestTheChunkWorkerCarriesTheEngine proves the token is built and consumed.
            "--engine",
            # S4c-only ("c" never reaches a chunk worker either -- stage3 only ever runs S3).
            "--borrowed-combine",
            # --jit travels positionally too: an optional trailing "jit" token
            # (run_flight.py's jit_tail, argv[11]), read back as JIT = argv[11:12] == ["jit"]
            # in the --_run-chunk branch. Exempted at integration (I2), when R4s's widened
            # flag regex first saw the flag.
            "--jit",
            # The confirmation gate is a main() gate, and the --_run-chunk branch returns
            # before main()'s parser ever runs (run_flight.main's first statement dispatches on
            # argv[0] == "--_run-chunk"). A chunk worker therefore cannot reach the gate, and
            # forwarding assent to it would be forwarding an answer to a question never asked.
            # The --jobs re-exec is the opposite case and DOES carry --yes literally
            # (_spawn_worker), because that one does re-enter main().
            "--yes",
            # The three threshold flags are S4 (sizeDist) inputs. A --_run-chunk worker runs
            # S3 (imgProc_sm) only -- "c" and "4" never reach it -- and the S4 threshold fragment
            # is appended by sd_call_label alone, never by proc_call_label, so neither the
            # computation nor the stamp a chunk worker writes can depend on them. Measured by
            # thresholds_stamp()'s own call sites.
            "--regime",
            "--area-ratio-z",
            "--default-int-arr-thresh",
            # --accept-flagged gates main()'s raw-input preflight (run_flight's
            # ACCEPT_FLAGGED, set in main from args). The --_run-chunk branch returns before
            # main() runs, so a chunk worker never reaches the preflight; the --jobs re-exec
            # does re-enter main() and carries it literally (_spawn_worker).
            "--accept-flagged",
        }
        missing = [f for f in missing if f not in stage3_exempt]
        self.assertEqual(
            missing, [],
            f"these flags are not threaded into the --_run-chunk re-exec: "
            f"{missing}. Either thread them through cmd_base, or add them to "
            "stage3_exempt above with the reason.")

    def test_exemptions_name_real_flags(self):
        """A stale exemption would hide a flag that no longer exists."""
        all_flags = set(_all_flags())
        stale = sorted(f for f in _EXEMPT if f not in all_flags)
        self.assertEqual(stale, [], f"_EXEMPT names flags that no longer exist: {stale}")

    def test_the_flag_list_itself_is_not_empty_or_trivially_short(self):
        """A check whose scope silently emptied (a moved file, a renamed
        function) would pass every assertion above vacuously."""
        self.assertGreaterEqual(len(_all_flags()), 10, _all_flags())

    def test_the_regex_flag_list_equals_what_argparse_itself_reports(self):
        """Two sides from two places (2026-09-14). ``_FLAG`` reads the
        parser-BUILDING source; a flag added in a form the regex does not match
        (single quotes, a helper, ``dest=``) would silently fall out of every
        sweep above and pass vacuously. The parser OBJECT is not callable in
        isolation -- ``main()`` builds it inline (``run_flight.py:2130``) -- but
        its own ``--help`` usage line is, so that is the second side.

        Not just the BRACKETED ``[--flag ...]`` tokens: since 2026-09-15
        ``--preset`` is ``required=True``, so argparse's usage line prints it un-bracketed
        (``... --preset {choices} ...``) -- a bracket-only regex would silently stop seeing any
        required flag, which is exactly the kind of blind spot this test exists to catch.
        """
        import contextlib
        import io
        buf = io.StringIO()
        with self.assertRaises(SystemExit) as cm, contextlib.redirect_stdout(buf), \
                contextlib.redirect_stderr(io.StringIO()):
            run_flight.main(["--help"])
        self.assertEqual(cm.exception.code, 0)
        usage = buf.getvalue().split("\n\n")[0]
        self.assertTrue(usage.startswith("usage:"), usage[:80])
        from_parser = set(re.findall(r"(--[a-z0-9-]+)", usage))
        if not run_flight._v314_engine_present():
            # Without the v3.1.4 engine the parser still accepts its flags but hides them from
            # --help (help=... if present else argparse.SUPPRESS), so usage cannot list them.
            from_parser |= _hidden_without_v314()
        self.assertEqual(from_parser, set(_all_flags()))


def setUpModule():
    # Restore the driver's UPPER_CASE globals when this module finishes.
    from tests import _run_flight_state
    _run_flight_state.preserve_module(run_flight)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
