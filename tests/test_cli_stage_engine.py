# SPDX-License-Identifier: BSD-3-Clause
"""``--engine`` on the per-stage commands ``read-binary``, ``sizedist`` and ``combine``.

Review item 2: these
three ran v3.1.4 through the top-level ``--uiops-version`` alone. Each now takes ``--engine``,
whose value is what lands in the ``.call`` stamp. It is required (2026-09-26), as
``scripts/run_flight.py``'s is: no default silently picks a side, and omitting it exits 2. A
disagreeing top-level ``--uiops-version`` is refused, never overridden.

The readers and combine are replaced by stubs that write an empty file: what is asserted is the
dispatch and the stamp, not the arithmetic, which the readers' and combine's own tests cover.
"""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._repo import needs_v314_engine  # noqa: E402

from arrayprobe import cli, provenance


def _touch(*args, **kwargs):
    Path(args[1]).write_bytes(b"")


class _Tmp(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def run_cli(self, argv):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(argv)
        return code, err.getvalue()


@needs_v314_engine
class ReadBinaryEngine(_Tmp):
    #: What each stubbed reader writes and returns, as the real readers do: DMT writes
    #: ``outfile`` and returns a record count; PMS and SEA write ``<outfile>.<probe>.cdf``
    #: files and return per-stream counts (``read-binary`` refuses an input that is not a
    #: file, and exits 1 when every count is zero, since 2026-09-26).
    STUBS = {"dmt": ("", 1), "pms": (".2dc.cdf", (1, 0, 0, 0)), "sea": (".CIP.cdf", (1, 0, 0))}

    def _run(self, *extra, fmt="dmt", top=()):
        out = self.d / "out.nc"
        raw = self.d / "raw"
        raw.write_bytes(b"")
        target = {"dmt": "read_binary_DMT", "pms": "read_binary_PMS", "sea": "read_binary_SEA"}
        module = {"dmt": cli.dmt, "pms": cli.pms, "sea": cli.sea}[fmt]
        suffix, counts = self.STUBS[fmt]

        def stub(*args, **kwargs):
            Path(f"{args[1]}{suffix}").write_bytes(b"")
            return counts

        with mock.patch.object(module, target[fmt], side_effect=stub) as reader:
            code, err = self.run_cli([*top, "read-binary", str(raw), str(out),
                                      "--format", fmt, *extra])
        return code, err, Path(f"{out}{suffix}"), reader

    def test_engine_3_5_runs_the_shared_reader_and_stamps_3_5(self):
        for fmt in ("dmt", "pms", "sea"):
            with self.subTest(fmt=fmt):
                code, _err, out, reader = self._run("--engine", "3.5", fmt=fmt)
                self.assertEqual(code, 0)
                reader.assert_called_once()
                self.assertEqual(provenance.read(out).engine, "3.5")

    @needs_v314_engine
    def test_engine_3_1_4_stamps_3_1_4(self):
        code, _err, out, _ = self._run("--engine", "3.1.4")
        self.assertEqual(code, 0)
        self.assertEqual(provenance.read(out).engine, "3.1.4")

    def test_omitted_exits_2_for_every_stage_command(self):
        argvs = {
            "read-binary": ["read-binary", "raw", "out.nc", "--format", "dmt"],
            "sizedist": SizedistEngine.ARGS,
            "combine": ["combine", "a.nc", "c.nc", "--flight-date", "20160906",
                        "--summary-time", "16_09_06_06_40_17"],
        }
        self.assertEqual(set(argvs), set(cli._STAGE_ENGINE_COMMANDS))
        for name, argv in argvs.items():
            with self.subTest(command=name):
                err = io.StringIO()
                with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
                    cli.build_parser().parse_args(argv)
                self.assertEqual(cm.exception.code, 2)
                self.assertIn("--engine", err.getvalue())

    @needs_v314_engine
    def test_disagreeing_top_level_version_is_refused(self):
        code, err, out, reader = self._run("--engine", "3.1.4", top=("--uiops-version", "3.5"))
        self.assertEqual(code, 2)
        self.assertIn("disagrees", err)
        reader.assert_not_called()
        self.assertFalse(out.exists())

    def test_agreeing_top_level_version_runs(self):
        code, _err, out, _ = self._run("--engine", "3.5", top=("--uiops-version", "3.5"))
        self.assertEqual(code, 0)
        self.assertEqual(provenance.read(out).engine, "3.5")

    @needs_v314_engine
    def test_spec_on_3_5_is_refused_with_the_reason(self):
        with mock.patch.object(cli.spec, "read_binary_SPEC") as reader:
            code, err = self.run_cli(["read-binary", "raw", str(self.d / "o"), "--format",
                                      "spec", "--profile", "oracles-production",
                                      "--engine", "3.5"])
        self.assertEqual(code, 2)
        self.assertIn("software", err)
        reader.assert_not_called()

    def test_the_flag_accepts_only_the_two_engines(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.build_parser().parse_args(["read-binary", "a", "b", "--format", "dmt",
                                           "--engine", "soda2"])


@needs_v314_engine
class SizedistEngine(_Tmp):
    ARGS = ["sizedist", "proc.nc", "sd.nc", "--tas-csv", "x.tas.csv", "2DS", "6", "1",
            "80000", "0", "ORACLES", "20160906 000000", "--tree", "production"]

    def test_engine_3_5_is_refused_before_anything_is_read(self):
        with mock.patch.object(cli, "load_tas_info") as load:
            code, err = self.run_cli([*self.ARGS, "--engine", "3.5"])
        self.assertEqual(code, 2)
        self.assertIn("arrayprobe run", err)
        load.assert_not_called()

    @needs_v314_engine
    def test_engine_3_1_4_reaches_the_v314_sizedist(self):
        import numpy as np

        with mock.patch.object(cli, "load_tas_info",
                               return_value=(np.zeros(2), np.ones(2))), \
             mock.patch.object(cli.sizedist_module, "run") as run:
            code, _ = self.run_cli([*self.ARGS, "--engine", "3.1.4"])
        self.assertEqual(code, 0)
        run.assert_called_once()


@needs_v314_engine
class CombineEngine(_Tmp):
    def _argv(self, *extra):
        return ["combine", "a.sd.nc", "b.sd.nc", str(self.d / "c.nc"), "--flight-date",
                "20160906", "--summary-time", "16_09_06_06_40_17", *extra]

    @needs_v314_engine
    def test_engine_3_1_4_runs_the_port_combine(self):
        with mock.patch.object(cli.combine_module, "combine_sizedist",
                               side_effect=lambda f, o, **k: Path(o).write_bytes(b"")) as c:
            code, _ = self.run_cli(self._argv("--engine", "3.1.4"))
        self.assertEqual(code, 0)
        c.assert_called_once()
        self.assertNotIn("borrowed_combine", c.call_args.kwargs)
        self.assertEqual(provenance.read(self.d / "c.nc").engine, "3.1.4")

    def test_engine_3_5_needs_the_opt_in(self):
        code, err = self.run_cli(self._argv("--engine", "3.5"))
        self.assertEqual(code, 2)
        self.assertIn("--borrowed-combine", err)
        self.assertFalse((self.d / "c.nc").exists())

    def test_engine_3_5_with_opt_in_runs_the_v35_combine(self):
        import arrayprobe_uiops.combine as v35c

        with mock.patch.object(v35c, "combine_sizedist",
                               side_effect=lambda f, o, **k: Path(o).write_bytes(b"")) as c:
            code, _ = self.run_cli(self._argv("--engine", "3.5", "--borrowed-combine"))
        self.assertEqual(code, 0)
        self.assertIs(c.call_args.kwargs["borrowed_combine"], True)
        stamp = provenance.read(self.d / "c.nc")
        self.assertEqual(stamp.engine, "3.5")

    @needs_v314_engine
    def test_opt_in_on_3_1_4_is_refused(self):
        code, err = self.run_cli(self._argv("--engine", "3.1.4", "--borrowed-combine"))
        self.assertEqual(code, 2)
        self.assertIn("3.5 only", err)


if __name__ == "__main__":
    unittest.main()
