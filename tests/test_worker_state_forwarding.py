# SPDX-License-Identifier: BSD-3-Clause
"""The gap: state that reaches a --_run-chunk worker some way OTHER than a
named ``ap.add_argument`` flag -- positional argv fields, and trailing keyed
tokens -- which ``test_worker_argument_forwarding.py`` does not cover (that
file's own regex is anchored on ``ap.add_argument("--...")`` and has nothing
to say about ``argv[1:11]`` or ``jit_tail``). Do not duplicate that file.

WHY THIS IS REAL, tonight's instance: ``prime=`` was added as a third
trailing token alongside ``jit`` and ``engine=``. Nothing mechanically
requires a new trailing token to be both built by stage3 and parsed by the
``--_run-chunk`` branch -- a token parsed but never emitted is dead; a token
emitted but never parsed is silently dropped, and a chunked run with a
dropped ``prime=`` produces a file that looks like a serial run and is not
("any and all such enhancements_uiops/functions/capabilities now and
forever").

Both sides are derived from source, never hardcoded, per the same rot this
is guarding against: a hardcoded list of tokens would itself need updating
every time a token is added, which is exactly the step this test exists to
stop being optional.
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

# Loaded the same way test_worker_argument_forwarding.py and test_run_flight.py
# do: this is a scripts/ script, not an installed package module, so it has no
# import path of its own.
_SPEC = importlib.util.spec_from_file_location("run_flight", TOOLS / "run_flight.py")
assert _SPEC is not None and _SPEC.loader is not None
run_flight = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault("run_flight", run_flight)
_SPEC.loader.exec_module(run_flight)


def _branch_source() -> str:
    """The ``--_run-chunk`` branch's own text: from ``main()``'s first ``if``
    through its ``return 0``. Bounded on CODE (the return), not on comment
    prose, so a reworded comment cannot silently shrink what this reads."""
    start = SOURCE.index('if argv and argv[0] == "--_run-chunk":')
    end_marker = "\n        return 0\n"
    end = SOURCE.index(end_marker, start) + len(end_marker)
    return SOURCE[start:end]


def _stage3_source() -> str:
    return inspect.getsource(run_flight.stage3)


def _strip_comments(src: str) -> str:
    """Drop whole-line ``#`` comments. Safe over the cmd_base/tail-building
    region of stage3: every comment there is its own line, with no trailing
    inline comment on a code line that builds cmd_base, cmd or jit_tail
    (verified by reading src/arrayprobe/driver/run_flight.py:3082-3144,
    2026-10-01) -- so this cannot eat a code token."""
    return "\n".join(line for line in src.splitlines() if not line.strip().startswith("#"))


def _positional_names() -> list[str]:
    """The worker's own unpack of its positional argv, e.g.
    ``(image_file, probe, ..., n_every) = argv[1:11]``."""
    m = re.search(r"\(([^)]+)\)\s*=\s*argv\[1:(\d+)\]", _branch_source())
    assert m, "positional unpack `(...) = argv[1:N]` not found in the --_run-chunk branch"
    names = [n.strip() for n in m.group(1).split(",")]
    upper = int(m.group(2))
    assert upper - 1 == len(names), (
        f"argv[1:{upper}] implies {upper - 1} names but the tuple has {len(names)}: {names}")
    return names


def _tail_start_index() -> int:
    m = re.search(r"tail\s*=\s*argv\[(\d+):\]", _branch_source())
    assert m, "`tail = argv[N:]` not found in the --_run-chunk branch"
    return int(m.group(1))


def _parsed_trailing_tokens(src: str | None = None) -> set[str]:
    """Trailing-token kinds the WORKER branch parses: a bare membership test
    (``"jit" in tail`` -> ``"jit"``) or a keyed prefix check
    (``token.startswith("engine=")`` -> ``"engine="``). The trailing ``=`` is
    kept on keyed kinds so a keyed and a bare token can never collide."""
    src = _branch_source() if src is None else src
    bare = set(re.findall(r'"([a-z_]+)"\s+in\s+tail', src))
    keyed = set(re.findall(r'token\.startswith\("([a-z_]+=)"\)', src))
    return bare | keyed


def _emitted_trailing_tokens(src: str | None = None) -> set[str]:
    """Trailing-token kinds stage3 EMITS: a bare conditional single-element
    list (``["jit"] if JIT else []`` -> ``"jit"``) or a keyed f-string
    ``.append`` (``.append(f"engine={ENGINE}")`` -> ``"engine="``)."""
    src = _stage3_source() if src is None else src
    bare = set(re.findall(r'\[\s*"([a-z_]+)"\s*\]\s*if\b', src))
    keyed = set(re.findall(r'\.append\(f"([a-z_]+=)', src))
    return bare | keyed


def _missing_forwarding(parsed: set, emitted: set) -> tuple[set, set]:
    """(parsed-but-never-emitted -- dead code the worker can never trigger,
    emitted-but-never-parsed -- silently dropped, the actual bug class)."""
    return parsed - emitted, emitted - parsed


def _globals_the_worker_sets() -> list[str]:
    """The ``global ...`` declaration at the top of the branch. ``[ \\t]``
    only (not ``\\s``), so the class cannot cross the newline into the
    positional-unpack line that follows it."""
    m = re.search(r"global[ \t]+([A-Z_][A-Z_, \t]*)", _branch_source())
    assert m, "`global ...` declaration not found in the --_run-chunk branch"
    return [g.strip() for g in m.group(1).split(",")]


class PositionalArgvContract(unittest.TestCase):
    def test_worker_unpack_count_matches_what_stage3_actually_builds(self):
        """Two sides from two places: the worker's tuple-unpack length vs.
        the element count of stage3's own cmd_base/cmd list literals."""
        names = _positional_names()
        self.assertEqual(len(names), 10, names)  # documents today's contract; free to grow
        self.assertEqual(_tail_start_index(), len(names) + 1,
                          "tail = argv[N:] must start immediately after the positional unpack")

        s3 = _strip_comments(_stage3_source())
        m_base = re.search(r"cmd_base\s*=\s*\[(.*?)\]", s3, re.DOTALL)
        assert m_base, "cmd_base = [...] not found in stage3"
        base_fields = [f.strip() for f in m_base.group(1).split(",") if f.strip()]
        # The first three build the subprocess invocation itself (interpreter,
        # this script's own path, the --_run-chunk mode flag) -- not positional
        # DATA that argv[1:] carries.
        self.assertEqual(base_fields[:3],
                          ["sys.executable", "str(Path(__file__).resolve())", '"--_run-chunk"'],
                          base_fields[:3])
        data_from_base = base_fields[3:]

        m_cmd = re.search(r"cmd\s*=\s*\[\*cmd_base,(.*?)\*tail\]", s3, re.DOTALL)
        assert m_cmd, "cmd = [*cmd_base, ..., *tail] not found in stage3"
        data_from_cmd = [f.strip() for f in m_cmd.group(1).split(",") if f.strip()]

        total = len(data_from_base) + len(data_from_cmd)
        self.assertEqual(
            total, len(names),
            f"stage3 emits {total} positional fields ({data_from_base + data_from_cmd}) but "
            f"the --_run-chunk branch unpacks {len(names)} names ({names})")


class TrailingTokensAgree(unittest.TestCase):
    def test_worker_and_parent_agree_on_the_trailing_token_set_today(self):
        parsed = _parsed_trailing_tokens()
        emitted = _emitted_trailing_tokens()
        self.assertTrue(parsed, "no trailing tokens found being parsed -- regex or branch moved")
        self.assertTrue(emitted, "no trailing tokens found being emitted -- regex or stage3 moved")
        dead, dropped = _missing_forwarding(parsed, emitted)
        self.assertEqual(
            dead, set(),
            f"the --_run-chunk branch parses {dead} but stage3 never builds it -- dead code, "
            "or a token the parent forgot to emit")
        self.assertEqual(
            dropped, set(),
            f"stage3 builds {dropped} but the --_run-chunk branch never parses it -- the same "
            "exact bug class: a silently dropped token producing a wrong-but-plausible file")

    def test_checker_is_not_vacuous_a_dropped_token_is_caught(self):
        """Ship it with proof it can fail (a memory note here: 'four guards in
        this repository matched nothing while reading fine'). Remove one member
        from each side in turn and confirm the comparison notices -- the exact
        shape of a future ``prime=``-style token that fails to travel."""
        parsed = _parsed_trailing_tokens()
        emitted = _emitted_trailing_tokens()
        self.assertIn("prime=", emitted)  # precondition: the mutation below removes a real member
        self.assertIn("engine=", parsed)  # precondition: ditto for the mirror mutation

        mutated_emitted = emitted - {"prime="}
        dead, _dropped = _missing_forwarding(parsed, mutated_emitted)
        self.assertIn("prime=", dead,
                       "removing prime= from the emitted set must surface it as "
                       "parsed-but-never-emitted; the checker did not notice")

        mutated_parsed = parsed - {"engine="}
        _dead2, dropped2 = _missing_forwarding(mutated_parsed, emitted)
        self.assertIn("engine=", dropped2,
                       "removing engine= from the parsed set must surface it as "
                       "emitted-but-never-parsed; the checker did not notice")


class ModuleGlobalsReachTheWorker(unittest.TestCase):
    def test_every_global_the_worker_sets_is_threaded_through_stage3(self):
        globals_set = _globals_the_worker_sets()
        self.assertGreaterEqual(len(globals_set), 4, globals_set)
        s3 = _strip_comments(_stage3_source())
        missing = [g for g in globals_set if not re.search(rf"\b{re.escape(g)}\b", s3)]
        self.assertEqual(
            missing, [],
            f"the --_run-chunk branch declares {missing} global and sets it from argv, but "
            "stage3's own source never references it while building cmd_base/cmd/jit_tail -- "
            "it cannot be threading a value the fresh subprocess needs")

    def test_checker_is_not_vacuous_an_unthreaded_global_is_caught(self):
        """Mutation proof for the globals check: a global stage3 never
        mentions must be flagged, not silently pass."""
        s3 = _strip_comments(_stage3_source())
        missing = [g for g in ["PROBE", "NOT_A_REAL_GLOBAL_XYZZY"]
                   if not re.search(rf"\b{re.escape(g)}\b", s3)]
        self.assertEqual(missing, ["NOT_A_REAL_GLOBAL_XYZZY"], missing)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
