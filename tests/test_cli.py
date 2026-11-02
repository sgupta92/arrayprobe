# SPDX-License-Identifier: BSD-3-Clause
"""Tests for arrayprobe.cli -- the command-line front door.

Two kinds of test, deliberately: real end-to-end smoke tests for the
subcommands with a cheap enough fixture to run for real (read-binary,
imgproc), and dispatch-correctness tests for all four (does the CLI parse
arguments and call the underlying, already-fully-tested pipeline function
with exactly the right values) -- this module adds no new pipeline logic,
only argument parsing, so what needs testing here is the parsing and
dispatch, not the pipeline itself.
"""

from __future__ import annotations

import importlib.util
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import netCDF4
import numpy as np
from tests._repo import needs_v314_engine

from arrayprobe import cli
from arrayprobe.ncio import _quiet_netcdf4_setitem
from arrayprobe.profiles import ORACLES_2016
from arrayprobe.readers import dmt

#: The development netCDF comparison script is not an importable module, so it is loaded
#: by path -- the same pattern `test_timing_closure.py` uses for its own tool.
#: Loading it is the point: these tests assert the SHIM still behaves, and a
#: shim nobody executes is how the script would rot after the move.
_COMPARE_TOOL = (Path(__file__).resolve().parent.parent / "scripts" / "compare_nc.py")
_COMPARE_SPEC = importlib.util.spec_from_file_location(
    "compare_nc_tool", _COMPARE_TOOL)
compare_nc_tool = None
if _COMPARE_TOOL.is_file():  # a repository script; the public tree does not carry it
    assert _COMPARE_SPEC is not None and _COMPARE_SPEC.loader is not None
    compare_nc_tool = importlib.util.module_from_spec(_COMPARE_SPEC)
    sys.modules[_COMPARE_SPEC.name] = compare_nc_tool
    _COMPARE_SPEC.loader.exec_module(compare_nc_tool)

#: Same, for the gallery script -- loaded so its shim is executed rather
#: than assumed to still work.
_GALLERY_TOOL = (Path(__file__).resolve().parent.parent / "scripts"
                 / "render_flight_gallery.py")
_GALLERY_SPEC = importlib.util.spec_from_file_location(
    "render_flight_gallery_tool", _GALLERY_TOOL)
render_gallery_tool = None
if _GALLERY_TOOL.is_file():
    assert _GALLERY_SPEC is not None and _GALLERY_SPEC.loader is not None
    render_gallery_tool = importlib.util.module_from_spec(_GALLERY_SPEC)
    sys.modules[_GALLERY_SPEC.name] = render_gallery_tool
    _GALLERY_SPEC.loader.exec_module(render_gallery_tool)

DATA = Path(__file__).resolve().parent / "data"
DMT_RAW = DATA / "dmt_raw_synthetic.cip"
BOUNDARY = 43690


@needs_v314_engine
class TestReadBinaryEndToEnd(unittest.TestCase):
    @unittest.skipUnless(DMT_RAW.exists(), "DMT raw fixture is not distributed with the "
                                           "package; the test needs files that are not part of "
                                           "this release")
    @needs_v314_engine
    def test_dmt_matches_calling_the_reader_directly(self):
        with tempfile.TemporaryDirectory() as tmp:
            via_cli = Path(tmp) / "via_cli.nc"
            direct = Path(tmp) / "direct.nc"

            rc = cli.main(["read-binary", str(DMT_RAW), str(via_cli),
                           "--format", "dmt", "--engine", "3.1.4"])
            self.assertEqual(rc, 0)
            dmt.read_binary_DMT(str(DMT_RAW), str(direct))

            with netCDF4.Dataset(via_cli) as a, netCDF4.Dataset(direct) as b:
                self.assertEqual(set(a.variables), set(b.variables))
                for name in a.variables:
                    np.testing.assert_array_equal(
                        np.asarray(a.variables[name][:]),
                        np.asarray(b.variables[name][:]),
                        err_msg=f"variable {name!r} differs")

    def test_format_is_required(self):
        with self.assertRaises(SystemExit):
            cli.main(["read-binary", "in.raw", "out.nc"])

    def test_spec_without_profile_raises(self):
        with self.assertRaises(SystemExit):
            cli.main(["read-binary", "in.raw", "out", "--format", "spec"])


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
class TestImgprocEndToEnd(unittest.TestCase):
    def _write_input(self, path, image_word):
        with netCDF4.Dataset(path, "w", format="NETCDF3_CLASSIC") as ds:
            ds.createDimension("time", 1)
            ds.createDimension("ImgRowlen", 8)
            ds.createDimension("ImgBlocklen", 1700)
            for name, dtype in (("year", "i2"), ("month", "i1"), ("day", "i1"),
                                ("hour", "i1"), ("minute", "i1"),
                                ("second", "i1"), ("millisec", "i2"),
                                ("wkday", "i1")):
                ds.createVariable(name, dtype, ("time",))[:] = 1
            var = ds.createVariable("data", "i4",
                                    ("time", "ImgBlocklen", "ImgRowlen"))
            rec = np.zeros((1700, 8), dtype=np.int32)
            rec[0, 1] = image_word
            rec[1, 1] = image_word
            rec[2, :] = BOUNDARY
            rec[3, :] = [0, 0, 0, 0, 5, 2, 0, 100]
            with _quiet_netcdf4_setitem():
                var[0, :, :] = rec

    @needs_v314_engine
    def test_matches_calling_imgproc_sm_directly(self):
        from arrayprobe.imgproc import imgproc_sm

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.nc"
            self._write_input(src, 0x0FF0)
            via_cli = Path(tmp) / "via_cli.nc"
            direct = Path(tmp) / "direct.nc"

            rc = cli.main(["imgproc", str(src), str(via_cli), "2DS", "1", "1",
                           "T", "--profile", "oracles-2016",
                           "--engine", "3.1.4"])
            self.assertEqual(rc, 0)
            imgproc_sm(str(src), str(direct), "2DS", 1, 1, "T",
                      profile=ORACLES_2016)

            with netCDF4.Dataset(via_cli) as a, netCDF4.Dataset(direct) as b:
                for name in a.variables:
                    np.testing.assert_array_equal(
                        np.asarray(a.variables[name][:]),
                        np.asarray(b.variables[name][:]),
                        err_msg=f"variable {name!r} differs")

    @needs_v314_engine
    def test_profile_is_required(self):
        with self.assertRaises(SystemExit):
            cli.main(["imgproc", "in.nc", "out.nc", "2DS", "1", "1", "T"])


class TestDispatchCorrectness(unittest.TestCase):
    """Every fidelity-sensitive argument reaches the underlying function
    with exactly the value passed on the command line -- checked by mocking
    the wrapped function rather than re-running the (already tested)
    pipeline."""

    def setUp(self):
        """Run in a throwaway working directory.

        These tests pass RELATIVE output paths ("out.nc", "out") because the path is not what
        they are checking -- the mock intercepts the pipeline call. But ``cli.main`` still runs
        its own ``_stamp`` afterwards, and ``_stamp`` writes ``<output>.call`` beside a path that
        exists. With ``python_port/`` as the working directory and a stale ``out.nc`` sitting
        there, that wrote ``python_port/out.nc.call`` into the repository on every suite run.

        It went unnoticed for as long as it did because ``*.nc`` is gitignored, so the file these
        tests nominally target was invisible while its ``.call`` sidecar was not. Found 2026-09-19
        by the CI step that asserts the suite leaves ``git status --porcelain`` empty
        (``tests/test_tree_cleanliness_is_checked.py``) -- the first thing that step caught, on
        the run that introduced it.
        """
        self._cwd = Path.cwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmp.cleanup()

    @needs_v314_engine
    def test_read_binary_spec_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp, patch(
                "arrayprobe.readers.spec.read_binary_SPEC", return_value=(5, 7)) as mock_fn:
            raw = Path(tmp) / "in.raw"
            raw.write_bytes(b"")   # read-binary refuses an input that is not a file
            cli.main(["read-binary", str(raw), str(Path(tmp) / "out"), "--format", "spec",
                     "--profile", "oracles-2016", "--channels", "H", "--engine", "3.1.4"])
        mock_fn.assert_called_once()
        _args, kwargs = mock_fn.call_args
        self.assertEqual(kwargs["profile"].name, "oracles-2016")
        self.assertEqual(kwargs["channels"], "H")

    @needs_v314_engine
    def test_imgproc_dispatch(self):
        with patch("arrayprobe.imgproc.imgproc_sm", return_value=3) as mock_fn:
            cli.main(["imgproc", "in.nc", "out.nc", "2DS", "1", "2", "T",
                     "--profile", "stock-v3.1.4", "--i-rect-ellipse", "1",
                     "--engine", "3.1.4",
                     # stock-v3.1.4 reads the aircraft file (imgProc_sm.m:183-185); the verb
                     # refuses without it since 2026-09-26, as the unmocked library always did
                     "--tas-file", "air.cdf"])
        mock_fn.assert_called_once()
        posargs, kwargs = mock_fn.call_args
        self.assertEqual(posargs, ("in.nc", "out.nc", "2DS", 1, 2, "T"))
        self.assertEqual(kwargs["profile"].name, "stock-v3.1.4")
        self.assertEqual(kwargs["iRectEllipse"], 1)
        self.assertEqual(kwargs["iCalcAllDiodeStats"], 0)

    @needs_v314_engine
    def test_sizedist_dispatch_reads_tas_csv_and_requires_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            tas_csv = Path(tmp) / "flight.tas.csv"
            tas_csv.write_text("60000.0,120.5,,,,,,,\n60001.0,121.0,,,,,,,\n")
            with patch("arrayprobe.sizedist.run") as mock_fn:
                cli.main(["sizedist", "proc.nc", "sd.nc",
                         "--tas-csv", str(tas_csv),
                         "2DS", "6", "0", "900000", "15.0", "ORACLES",
                         "20160906 064403", "--tree", "production", "--engine", "3.1.4"])
            mock_fn.assert_called_once()
            posargs, kwargs = mock_fn.call_args
            self.assertEqual(posargs[0], "proc.nc")
            self.assertEqual(posargs[1], "sd.nc")
            np.testing.assert_allclose(posargs[2], [120.5, 121.0])  # tas
            np.testing.assert_allclose(posargs[3], [60000.0, 60001.0])  # timehhmmss
            self.assertEqual(posargs[4], "2DS")
            self.assertEqual(posargs[5], 6)
            self.assertEqual(kwargs["tree"], "production")

    @needs_v314_engine
    def test_sizedist_missing_tree_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            tas_csv = Path(tmp) / "flight.tas.csv"
            tas_csv.write_text("60000.0,120.5,,,,,,,\n")
            with self.assertRaises(SystemExit):
                cli.main(["sizedist", "proc.nc", "sd.nc",
                         "--tas-csv", str(tas_csv),
                         "2DS", "6", "0", "900000", "15.0", "ORACLES",
                         "20160906 064403"])

    @needs_v314_engine
    def test_combine_dispatch(self):
        with patch("arrayprobe.combine.combine_sizedist") as mock_fn:
            cli.main(["combine", "sd1.nc", "sd2.nc", "out.nc",
                     "--flight-date", "20160906",
                     "--summary-time", "16_09_06_06_40_17", "--engine", "3.1.4"])
        mock_fn.assert_called_once()
        posargs, kwargs = mock_fn.call_args
        self.assertEqual(posargs[0], ["sd1.nc", "sd2.nc"])
        self.assertEqual(posargs[1], "out.nc")
        self.assertEqual(kwargs["flight_date"], "20160906")
        self.assertEqual(kwargs["summary_time"], "16_09_06_06_40_17")

# _release_fixture_guard: real-data derived fixtures are excluded from the release
import pathlib as _rfg_pathlib  # noqa: E402
import unittest as _rfg_unittest  # noqa: E402

_RFG_EXCLUDED = ('dmt_raw_synthetic.cip',)
if not all((_rfg_pathlib.Path(__file__).resolve().parent / "data" / _n).exists()
           for _n in _RFG_EXCLUDED):
    raise _rfg_unittest.SkipTest(
        "needs the archived UIOPS v3.1.4 engine and sample files from real field-campaign "
        "data, which this release does not include")

if __name__ == "__main__":
    unittest.main()


class CompareReachesTheFrontDoor(unittest.TestCase):
    """``arrayprobe compare`` -- moved out of the netCDF comparison script 2026-09-10.

    The comparison engine was always in the package and always tested; what was
    missing is that nothing in ``arrayprobe --help`` mentioned it, so a reader
    with two files and the question "do these agree" had no way to find the
    package's own answer.

    The move is a MOVE, not a copy. The comparison script still exists,
    because it is named in the docs site and in two plans,
    and a reader following one
    of those should
    not meet a missing file -- but it now calls this, so the acceptance rule
    exists once. These tests hold that: the same arguments through either path
    must produce the same output and the same exit status, and the exit status
    must still distinguish accepted (0) from a usage error (2), because
    `compare_nc.py`'s documented contract is that a script can gate on it
    without reading the output.
    """

    # Borrowed rather than duplicated: TestImgprocEndToEnd already builds the
    # one-particle decoded file this needs, and a second copy of a netCDF
    # fixture is a second thing to keep in step with `read_slices`.
    _write_input = TestImgprocEndToEnd._write_input

    def _proc_file(self, tmp):
        src = Path(tmp) / "in.nc"
        proc = Path(tmp) / "proc.nc"
        self._write_input(src, 0x0FF0)
        rc = cli.main(["imgproc", str(src), str(proc), "2DS", "1", "1", "T",
                       "--profile", "oracles-2016", "--engine", "3.1.4"])
        self.assertEqual(rc, 0)
        return proc

    def _run(self, fn, argv):
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = fn(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_the_subcommand_is_registered(self):
        self.assertIn("compare", cli.build_parser().format_help())

    @unittest.skipIf(compare_nc_tool is None, "the netCDF comparison tool is not part of this "
                                              "release")
    def test_classes_listing_is_identical_through_both_paths(self):
        rc_cli, out_cli, _ = self._run(cli.main, ["compare", "--classes"])
        rc_tool, out_tool, _ = self._run(compare_nc_tool.main, ["--classes"])
        self.assertEqual(rc_cli, 0)
        self.assertEqual(rc_tool, 0)
        self.assertEqual(out_cli, out_tool)
        # Not merely equal -- non-empty and actually the classes, so the test
        # cannot pass on two identically broken paths printing nothing.
        self.assertIn("bit-exact", out_cli)

    @unittest.skipIf(compare_nc_tool is None, "the netCDF comparison tool is not part of this "
                                              "release")
    def test_a_missing_file_is_exit_2_through_both_paths(self):
        rc_cli, _, err_cli = self._run(cli.main, ["compare", "nope.nc", "x.nc"])
        rc_tool, _, err_tool = self._run(compare_nc_tool.main, ["nope.nc", "x.nc"])
        self.assertEqual(rc_cli, 2)
        self.assertEqual(rc_tool, 2)
        self.assertIn("not a file", err_cli)
        self.assertEqual(err_cli, err_tool)

    @needs_v314_engine
    def test_an_identical_pair_is_accepted_and_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = self._proc_file(tmp)
            rc, out, _ = self._run(cli.main, ["compare", str(proc), str(proc)])
            self.assertEqual(rc, 0)
            self.assertIn("ACCEPTED: True", out)

    @needs_v314_engine
    def test_the_filter_note_appears_only_when_filtering(self):
        """The `--var` note was one of two lines an escape bug had split.

        It is cheap to assert and it is the part of the handler that a
        transcription error would silently drop -- which is precisely what
        happened while this was being moved.
        """
        with tempfile.TemporaryDirectory() as tmp:
            proc = self._proc_file(tmp)
            _, plain, _ = self._run(cli.main, ["compare", str(proc), str(proc)])
            self.assertNotIn("the verdict above it is for the WHOLE file", plain)
            _, filtered, _ = self._run(
                cli.main, ["compare", str(proc), str(proc),
                           "--var", "image_length"])
            self.assertIn("the verdict above it is for the WHOLE file", filtered)
            self.assertIn("filtered to 1 variable(s)", filtered)


class GalleryAndTriageReachTheFrontDoor(unittest.TestCase):
    """``arrayprobe gallery`` and ``arrayprobe triage`` -- added 2026-09-10.

    Both capabilities were already core rather than enhancements, because
    visualisation and manual labelling change no computed number. Neither was
    mentioned by ``arrayprobe --help``: the gallery lived only in
    a script under ``scripts/`` and the server only as ``python -m
    arrayprobe.triage_server``.

    **The triage subcommand answers an objection rather than overruling it.**
    ``triage_server.main``'s own docstring says it is deliberately not a
    console script, because it needs a decoded directory and a bare command
    "makes it look like a command that works anywhere". So ``--decoded-dir``
    is *required* on the subcommand, with no default, which is the difference
    that objection was about. Since 2026-10-10 the module form requires it too
    (a deliberate choice): its old ``../_decoded`` default wrote above the repository.
    """

    def test_both_subcommands_are_registered(self):
        text = cli.build_parser().format_help()
        self.assertIn("gallery", text)
        self.assertIn("triage", text)

    def test_gallery_requires_its_three_paths(self):
        for argv in (["gallery"],
                     ["gallery", "--decoded-dir", "d"],
                     ["gallery", "--decoded-dir", "d", "--flight", "f"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                cli.build_parser().parse_args(argv)

    def test_gallery_reports_a_missing_input_as_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = cli.main(["gallery", "--decoded-dir", tmp,
                           "--flight", "nosuch.H", "--out", tmp])
        self.assertEqual(rc, 2)

    def test_gallery_defaults_match_the_script_they_came_from(self):
        """The defaults encode decisions -- accepted-only and cropped.

        Both were made once for real reasons (particle counts, and the diode
        search window vastly exceeding the shadow after a record reset). A
        move is exactly when a default gets silently re-made, so they are
        pinned here rather than left to the shim to preserve.
        """
        args = cli.build_parser().parse_args(
            ["gallery", "--decoded-dir", "d", "--flight", "f", "--out", "o"])
        self.assertEqual(args.classes, ["accepted"])
        self.assertEqual(args.scale, 3)
        self.assertFalse(args.no_crop)
        self.assertIsNone(args.limit)
        self.assertFalse(args.no_index)

    @unittest.skipIf(render_gallery_tool is None, "the gallery script is not part of this release")
    def test_the_gallery_script_is_a_shim_onto_the_same_handler(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc_tool = render_gallery_tool.main(
                ["--decoded-dir", tmp, "--flight", "nosuch.H", "--out", tmp])
            rc_cli = cli.main(["gallery", "--decoded-dir", tmp,
                               "--flight", "nosuch.H", "--out", tmp])
        self.assertEqual(rc_tool, rc_cli)
        self.assertEqual(rc_tool, 2)

    def test_triage_requires_decoded_dir(self):
        with self.assertRaises(SystemExit):
            cli.build_parser().parse_args(["triage"])
        args = cli.build_parser().parse_args(["triage", "--decoded-dir", "d"])
        self.assertEqual(args.port, 8765)
        self.assertIsNone(args.queue_file)

    def test_the_module_form_also_requires_decoded_dir(self):
        """Read from the module's own parser: no default directory, so no run."""
        from arrayprobe import triage_server
        with patch.object(triage_server, "run") as run, \
                redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            triage_server.main([])
        self.assertEqual(run.call_count, 0)

    def test_triage_passes_the_resolved_directory_through(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(cli.triage_module, "run") as run:
            rc = cli.main(["triage", "--decoded-dir", tmp, "--port", "9999"])
        self.assertEqual(rc, 0)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(Path(run.call_args[0][0]), Path(tmp).resolve())
        self.assertEqual(run.call_args[0][1], 9999)

    def test_triage_missing_decoded_dir_refuses_without_starting_the_server(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(cli.triage_module, "run") as run, \
                redirect_stderr(io.StringIO()) as err:
            rc = cli.main(["triage", "--decoded-dir", str(Path(tmp) / "nodir")])
        self.assertEqual(rc, 2)
        self.assertEqual(run.call_count, 0)
        self.assertIn("is not a directory", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())
