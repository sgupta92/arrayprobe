# SPDX-License-Identifier: BSD-3-Clause
"""Every copyable ``run_flight.py`` command in the documentation names its engine.

``--engine`` became required for every preset on 2026-09-23: a documented command
without it exits 2 for a reader who copies it. A second failure has the same shape: under
``--engine 3.5`` a probe whose imgProc path builds ``Time_in_seconds`` from an aircraft TAS file
refuses to run without ``--tas-file`` or ``--tas-source``. A cold-user sweep fixed both
by hand; this guard refuses the next one.

Which probes need a TAS file is read from the code -- ``run_flight.PRESETS`` maps the preset to
its probe and ``constants.imgproc_config(probe).needs_tas_file`` answers, the same call
``run_flight.main`` makes -- never from a list typed here. A placeholder preset (``NAME``,
``<preset>``) is checked for ``--engine`` only.
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import json
import re
import shlex
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from tests._hygiene import hygiene
from tests._repo import repo_only

from arrayprobe import constants

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT
TOOLS = ROOT / "scripts"

_RF_SPEC = importlib.util.spec_from_file_location("run_flight", TOOLS / "run_flight.py")
assert _RF_SPEC is not None and _RF_SPEC.loader is not None
run_flight = importlib.util.module_from_spec(_RF_SPEC)
sys.modules.setdefault(_RF_SPEC.name, run_flight)
_RF_SPEC.loader.exec_module(run_flight)

#: The documents a reader copies commands from.
SOURCES = (
    "README.md", "docs/developer/PACKAGE_README.md", "docs/*.md",
    "docs/developer/*.md", "examples/*.ipynb", "enhancements_uiops/README.md",
    "enhancements_uiops/docs/*.md",
)
#: Development-only documents a reader also copies commands from, one pattern per line. The
#: file does not ship, so the public distribution sweeps only the documents it carries.
_DEV_SOURCES = ROOT / "tests" / "dev_command_sources.txt"
if _DEV_SOURCES.is_file():
    SOURCES += tuple(ln.strip() for ln in _DEV_SOURCES.read_text(encoding="utf-8").splitlines()
                     if ln.strip() and not ln.startswith("#"))

#: Bare commands shown on purpose, matched by (file, content) rather than line number.
#: Each shows what a bare call does -- the exit-2 refusal -- so naming an engine would
#: defeat the example. Rows are ``file<TAB>content`` in a development-only file, because
#: the documents they name do not ship and the public distribution must not name them.
_DEV_ALLOWED = ROOT / "tests" / "dev_allowed_bare.txt"
ALLOWED_BARE = set()
if _DEV_ALLOWED.is_file():
    ALLOWED_BARE = {tuple(ln.split("	", 1)) for ln in
                    _DEV_ALLOWED.read_text(encoding="utf-8").splitlines()
                    if ln.strip() and not ln.startswith("#")}

_FENCE = re.compile(r"^\s*(```|~~~)")
_INLINE = re.compile(r"`([^`\n]+)`")


def _logical_lines(text: str):
    """Yield (first_line_no, logical_line), joining backslash continuations."""
    buf, start = [], None
    for no, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if start is None:
            start = no
        if line.endswith("\\"):
            buf.append(line[:-1])
            continue
        buf.append(line)
        yield start, " ".join(s.strip() for s in buf)
        buf, start = [], None
    if buf:
        yield start, " ".join(s.strip() for s in buf)


_CALL = re.compile(r"(?:^|\s)\S*run_flight\.py\s+\S")
_INTERPRETER = re.compile(r"(?:^|[\s/\\])python[\d.]*(?:\.exe)?\s", re.IGNORECASE)


def _is_command(s: str) -> bool:
    """A shell invocation of run_flight.py with arguments, not prose or a ``file:line`` cite.

    The script is either the first word or run by a Python interpreter; ``python_port/`` in a
    path is not an interpreter.
    """
    m = _CALL.search(s)
    if not m:
        return False
    head = s[:m.start()].strip()
    if head:
        return bool(_INTERPRETER.search(head + " "))
    # No interpreter: a command only when it names a positional input (`run_flight.py raw.2DS`);
    # `run_flight.py --chunks` in prose names a flag, not a call.
    words = s.split()
    return (len(words) >= 2 and re.fullmatch(r"[\w./~-]*run_flight\.py", words[0]) is not None
            and re.match(r"[\w.<$~/]", words[1]) is not None and words[1] != "...")


def extract_commands(text: str):
    """Every run_flight.py command in a markdown (or cell source) text, as (line, command)."""
    found = []
    in_fence = False
    for no, line in _logical_lines(text):
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            cmd = line.strip().lstrip("!$> ").strip()
            if _is_command(cmd):
                found.append((no, cmd))
            continue
        for span in _INLINE.findall(line):
            if _is_command(span):
                found.append((no, span.strip()))
    return found


def _texts(path: Path):
    """(label, text) pairs: the file itself, or each notebook cell's source."""
    if path.suffix == ".ipynb":
        nb = json.loads(path.read_text(encoding="utf-8"))
        for i, cell in enumerate(nb.get("cells", [])):
            src = cell.get("source", "")
            src = "".join(src) if isinstance(src, list) else src
            if cell.get("cell_type") == "code":
                src = "```\n" + src + "\n```"
            yield f"cell {i}", src
    else:
        yield "", path.read_text(encoding="utf-8")


def all_commands():
    out = []
    for pattern in SOURCES:
        for path in sorted(REPO.glob(pattern)):
            rel = path.relative_to(REPO).as_posix()
            for label, text in _texts(path):
                for no, cmd in extract_commands(text):
                    where = f"{rel}:{label or no}"
                    out.append((rel, where, cmd))
    return out


def _tokens(cmd: str):
    try:
        return shlex.split(cmd, posix=True)
    except ValueError:
        return cmd.split()


def _value(tokens, flag):
    for i, t in enumerate(tokens):
        if t == flag and i + 1 < len(tokens):
            return tokens[i + 1]
        if t.startswith(flag + "="):
            return t.split("=", 1)[1]
    return None


_KNOWN: set[str] = set()


def known_flags() -> set[str]:
    """Every option string ``run_flight.main`` accepts, read off the parser it really builds (its
    one ``parse_args`` call intercepted on ``--help``, as ``test_engine_flag_parity`` does), plus
    the ``--presets`` pre-parser's own flag. Found 2026-09-29: a documented
    command quoting a flag the driver does not have fails here rather than in a reader's shell."""
    if not _KNOWN:
        captured = {}
        original = argparse.ArgumentParser.parse_args

        def _capture(self, *a, **kw):
            captured["ap"] = self
            return original(self, *a, **kw)

        with mock.patch.object(argparse.ArgumentParser, "parse_args", _capture), \
                redirect_stdout(io.StringIO()):
            try:
                run_flight.main(["--help"])
            except SystemExit:
                pass
        _KNOWN.update(s for a in captured["ap"]._actions for s in a.option_strings)  # noqa: SLF001
        _KNOWN.add("--presets")
    return _KNOWN


def problems(rel: str, cmd: str):
    """What is wrong with one command: an empty list when it is copyable."""
    if any(rel == f and content in cmd and "--engine" not in cmd
           for f, content in ALLOWED_BARE):
        return []
    toks = _tokens(cmd)
    unknown = [t.split("=", 1)[0] for t in toks
               if t.startswith("--") and t.split("=", 1)[0] not in known_flags()]
    if unknown:
        return [f"flag(s) run_flight.py does not have: {', '.join(unknown)}"]
    engine = _value(toks, "--engine")
    if engine is None:
        return ["no --engine"]
    if engine == "3.1.4" and "--port-validation" not in toks:
        return ["--engine 3.1.4 without --port-validation"]
    preset = _value(toks, "--preset")
    if engine != "3.5" or preset not in run_flight.PRESETS:
        return []  # placeholder presets are checked for --engine only
    probe = run_flight.PRESETS[preset].probe
    if constants.imgproc_config(probe).needs_tas_file and not (
            _value(toks, "--tas-file") or _value(toks, "--tas-source")):
        return [f"--engine 3.5 on {probe} ({preset}) needs --tas-file or --tas-source"]
    return []


@repo_only
@hygiene
class DocumentedCommandsNameTheirEngine(unittest.TestCase):
    def test_the_extractor_finds_commands(self):
        # A guard that extracts nothing passes vacuously. The development tree's extra sources
        # carry many commands; the public distribution's documents carry four (CI run
        # 41338745088), so there the bar is only that the sweep reads something.
        self.assertGreaterEqual(len(all_commands()), 5 if _DEV_SOURCES.is_file() else 1)

    def test_every_documented_command_is_copyable(self):
        bad = [f"{where}: {why}: {cmd}"
               for rel, where, cmd in all_commands() for why in problems(rel, cmd)]
        self.assertEqual(bad, [], "\n".join(bad))

    def test_the_allowlist_still_matches_something(self):
        # A stale allowlist entry would silently exempt a future command instead.
        cmds = all_commands()
        for f, content in ALLOWED_BARE:
            self.assertTrue(any(rel == f and content in cmd for rel, _w, cmd in cmds),
                            f"allowlist entry {f!r} / {content!r} matches no command")


@hygiene
class TheCheckFires(unittest.TestCase):
    def _bad(self, text):
        return [p for _no, c in extract_commands(text) for p in problems("synthetic.md", c)]

    def test_a_bare_fenced_command_is_caught(self):
        md = ("```bash\n.venv/Scripts/python.exe scripts/run_flight.py raw.2DS \\\n"
              "    --preset ORACLES_2016_2DS_H\n```\n")
        self.assertEqual(self._bad(md), ["no --engine"])

    def test_a_bare_inline_command_is_caught(self):
        self.assertEqual(self._bad("Run `python scripts/run_flight.py raw --preset NAME`."),
                         ["no --engine"])

    def test_engine_equals_form_is_accepted(self):
        self.assertEqual(self._bad("`python run_flight.py x --preset NAME --engine=3.5`"), [])

    def test_a_tas_probe_on_35_without_a_tas_source_is_caught(self):
        tas = [n for n, p in run_flight.PRESETS.items()
               if constants.imgproc_config(p.probe).needs_tas_file]
        self.assertTrue(tas, "no preset needs a TAS file: the second check is untested")
        md = f"```\npython scripts/run_flight.py raw --preset {tas[0]} --engine 3.5\n```\n"
        self.assertEqual(len(self._bad(md)), 1)
        fixed = md.replace("--engine 3.5", "--engine 3.5 --tas-source aircraft")
        self.assertEqual(self._bad(fixed), [])

    def test_a_v314_command_without_the_port_validation_flag_is_caught(self):
        md = "```\npython scripts/run_flight.py raw --preset NAME --engine 3.1.4\n```\n"
        self.assertEqual(self._bad(md), ["--engine 3.1.4 without --port-validation"])
        self.assertEqual(self._bad(md.replace("3.1.4", "3.1.4 --port-validation")), [])

    def test_a_flag_the_driver_does_not_have_is_caught(self):
        md = "```\npython scripts/run_flight.py raw --preset NAME --engine 3.5 --jobz 4\n```\n"
        self.assertEqual(self._bad(md), ["flag(s) run_flight.py does not have: --jobz"])
        self.assertIn("--jobs", known_flags())

    def test_prose_naming_the_file_is_not_a_command(self):
        self.assertEqual(extract_commands("`run_flight.py`'s `--s2-jobs` flag"), [])


def setUpModule():
    # Restore the driver's UPPER_CASE globals when this module finishes.
    from tests import _run_flight_state
    _run_flight_state.preserve_module(run_flight)


if __name__ == "__main__":
    unittest.main()
