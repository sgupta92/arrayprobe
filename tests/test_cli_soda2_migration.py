# SPDX-License-Identifier: BSD-3-Clause
"""Every example on ``docs/30-from-a-soda2-batch-script.md`` is executed.

The page translates SODA-2's ``example_script.pro`` / ``example_batch.pro`` into a
configuration file and ``arrayprobe soda2 run``. The risk it carries is claiming a capability
the port refuses, so nothing on it is only parsed: the printed TOML is run through the real CLI
on the tracked 2D-S frame fixture (only ``fn``, ``outdir``, ``starttime``, ``stoptime``
repointed), the Python block is executed, and each ``arrayprobe`` command line parses. The
TOML's field set is checked against the ``op={...}`` literal of the vendored script itself --
a second, independent source -- so the page cannot drop or invent a field.

The FLOAT/DOUBLE claim on the page is checked both ways: the TOML route gives a DOUBLE
``activetime`` and the page's Python route a FLOAT one (the IDL side, ``fltarr(3)+{rate:1}.rate``
is FLOAT, was measured under GDL and is recorded in the migration measurement report).
"""
from __future__ import annotations

import contextlib
import io
import os
import re
import shlex
import tempfile
import tomllib
import unittest
from pathlib import Path

import numpy as np
from tests import _upstream  # noqa: E402
from tests._repo import repo_only

from arrayprobe import cli

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "30-from-a-soda2-batch-script.md"
SCRIPT = _upstream.source("soda2") / "example_script.pro"
FRAME_FIXTURE = Path(__file__).resolve().parent / "data" / "soda2_spec_frame_fixture"

#: The fixture's window, as `test_cli_soda2._write_config` uses it.
_WINDOW = {"starttime": 24240, "stoptime": 24250}


def setUpModule():
    # Raised here rather than at import: an import-time SkipTest crashes
    # ``python -m unittest tests.<module>``, where ``discover`` reports it as a skip.
    _upstream.require("soda2")


def _fences(lang: str) -> list[str]:
    if not PAGE.is_file():  # an sdist carries no docs/_build/
        raise unittest.SkipTest(f"{PAGE} absent (sdist)")
    text = PAGE.read_text(encoding="utf-8")
    return re.findall(rf"^```{lang}\n(.*?)^```", text, flags=re.M | re.S)


def _repoint(toml_text: str, outdir: str) -> str:
    """Only these four lines change; the assertion fails if one is missing from the page."""
    subs = {"fn": f'fn = "{FRAME_FIXTURE.as_posix()}"',
            "outdir": f'outdir = "{Path(outdir).as_posix()}/"',
            "starttime": f"starttime = {_WINDOW['starttime']}",
            "stoptime": f"stoptime = {_WINDOW['stoptime']}"}
    for key, line in subs.items():
        toml_text, n = re.subn(rf"^{key} = .*$", line, toml_text, count=1, flags=re.M)
        assert n == 1, f"the page's TOML has no `{key} =` line to repoint"
    return toml_text


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


@repo_only
class TheExampleScriptTranslationRuns(unittest.TestCase):
    def test_the_page_prints_exactly_one_toml_block(self):
        self.assertEqual(len(_fences("toml")), 1)

    def test_the_toml_carries_exactly_the_scripts_op_fields(self):
        """Independent side: the ``op={...}`` literal in the vendored ``example_script.pro``."""
        src = SCRIPT.read_text(encoding="latin-1")
        literal = re.search(r"op=\{(.*?)\}", src, flags=re.S)
        assert literal is not None, "example_script.pro has no op={...} literal"
        body = re.sub(r"\$\s*\n", " ", literal.group(1))
        script_fields = {part.split(":")[0].strip().lower() for part in body.split(",")
                         if ":" in part}
        page_fields = set(tomllib.loads(_fences("toml")[0])["soda2"])
        self.assertEqual(page_fields, script_fields)

    def test_the_toml_runs_through_arrayprobe_soda2_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "example_script.toml"
            cfg.write_text(_repoint(_fences("toml")[0], tmp), encoding="utf-8")
            rc, out, err = _run_cli(["soda2", "run", str(cfg), "--out", tmp])
            self.assertEqual(rc, 0, err)
            sidecars = list(Path(tmp).glob("*.pbp.call"))
            self.assertEqual(len(sidecars), 1, out + err)
            self.assertTrue(list(Path(tmp).glob("*.pbp.csv")), "particlefile = 1 wrote no CSV")
            # `savfile = 1` writes the IDL SAVE file (`:729-731`).
            self.assertEqual(len(list(Path(tmp).glob("*.dat"))), 1,
                             "the page says savfile = 1 writes one IDL SAVE .dat")

    def test_the_toml_route_gives_a_float_activetime(self):
        """A Python integer `rate` is IDL's INT, so `rate = 1`
        gives FLOAT `activetime` (`:644`, measured under GDL by
        `run_soda2_save_writer_bank.py`'s `rate_types`)."""
        from arrayprobe_soda2.process_2d import soda2_process_2d
        with tempfile.TemporaryDirectory() as tmp:
            op = tomllib.loads(_repoint(_fences("toml")[0], tmp))["soda2"]
            self.assertIsInstance(op["rate"], int)
            d = soda2_process_2d(op)
        assert d is not None
        self.assertEqual(d.activetime.dtype, np.float32)

    def test_the_python_route_runs_and_gives_a_float_activetime(self):
        (block,) = _fences("python")
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "example_script.toml").write_text(
                _repoint(_fences("toml")[0], tmp), encoding="utf-8")
            here = os.getcwd()
            out = io.StringIO()
            try:
                os.chdir(tmp)
                with contextlib.redirect_stdout(out):
                    exec(compile(block, str(PAGE), "exec"), {"__name__": "__page__"})
            finally:
                os.chdir(here)
        self.assertEqual(out.getvalue().strip(), "float32")

    def test_every_arrayprobe_command_on_the_page_parses(self):
        parser = cli.build_parser()
        lines = [ln for block in _fences("bash") for ln in block.splitlines()
                 if ln.startswith("arrayprobe ")]
        self.assertEqual(len(lines), 3)
        for line in lines:
            with self.subTest(line=line):
                ns = parser.parse_args(shlex.split(line)[1:])
                self.assertEqual(ns.func.__name__, "_soda2_run")


if __name__ == "__main__":
    unittest.main()
