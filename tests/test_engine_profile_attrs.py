# SPDX-License-Identifier: BSD-3-Clause
"""In-file provenance: every v3.5 and SODA-2 netCDF product carries ``arrayprobe_engine`` and
``arrayprobe_profile``; no v3.1.4 product does.

Author, 2026-09-24: *"the difference from matlab will only be for oracles files or files being
re-processed. completely new processing would not have this issue"* -- so the two attributes are
written unconditionally by the v3.5 and SODA-2 writers and never by the v3.1.4 lineage, whose
products must stay byte-faithful to MATLAB. Each writer is executed here, not read.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import netCDF4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tests._repo import needs_v314_engine  # noqa: E402

from arrayprobe import provenance  # noqa: E402

ENGINE, PROFILE = "arrayprobe_engine", "arrayprobe_profile"


def _globals(path) -> dict:
    with netCDF4.Dataset(path, "r") as ds:
        return {a: ds.getncattr(a) for a in ds.ncattrs()}


class TestHelper(unittest.TestCase):
    def test_names_match_the_provenance_constants(self):
        self.assertEqual((provenance.ATTR_ENGINE, provenance.ATTR_PROFILE), (ENGINE, PROFILE))

    def test_unstated_profile_is_written_and_read_back_as_silence(self):
        attrs = provenance.engine_attrs(engine="3.5", profile=None)
        self.assertEqual(attrs, {ENGINE: "3.5", PROFILE: "unstated"})
        stamp = provenance.stamp_from_attrs(attrs)
        self.assertEqual(stamp.engine, "3.5")
        self.assertIsNone(stamp.profile)

    def test_v314_is_refused(self):
        with self.assertRaises(ValueError):
            provenance.engine_attrs(engine="3.1.4", profile="oracles-production")

    def test_soda2_helper_agrees_with_the_port_helper(self):
        from arrayprobe_soda2.pbp_writer import engine_attrs
        self.assertEqual(engine_attrs(None), {ENGINE: "soda2", PROFILE: "unstated"})
        self.assertEqual(engine_attrs("x"), {ENGINE: "soda2", PROFILE: "x"})

    def test_soda2_config_stamp_is_the_file_name_without_whitespace(self):
        from arrayprobe_soda2.pbp_writer import engine_attrs, soda2_stamp_profile
        self.assertEqual(soda2_stamp_profile(Path("a") / "b" / "ena.toml"), "config:ena.toml")
        spaced = soda2_stamp_profile("C:/x y/my run.toml")
        self.assertEqual(spaced, "config:my_run.toml")
        self.assertEqual(engine_attrs(spaced)[PROFILE], spaced)  # a legal stamp value


class TestWriters(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_v35_decode_writer_carries_both(self):
        from arrayprobe_uiops.spec import _ImageFileV35
        for profile, expected in ((None, "unstated"), ("stock-v3.5", "stock-v3.5")):
            path = self.dir / f"x_{expected}.H.nc"
            f = _ImageFileV35(str(path), "Horizontal", "UIOOPS_v3.5", write_tas_ratio=False,
                              creation_time="2026/01/01 00:00:00", stamp_profile=profile)
            f.close()
            got = _globals(path)
            self.assertEqual((got[ENGINE], got[PROFILE]), ("3.5", expected))

    def test_v35_imgproc_writer_carries_both(self):
        from arrayprobe_uiops.imgproc import _create_output
        path = self.dir / "proc.nc"
        f = _create_output(str(path), 128, "ORACLES", "in.H.nc", "2DS", 0, 0, 0, 1, None,
                           "UIOOPS_v3.5", "2026/01/01 00:00:00", "oracles-production-v3.5")
        f.close()
        got = _globals(path)
        self.assertEqual((got[ENGINE], got[PROFILE]), ("3.5", "oracles-production-v3.5"))

    def test_soda2_pbp_writer_carries_both(self):
        from arrayprobe_soda2.pbp_writer import open_pbp_ncdf
        path = self.dir / "x.pbp.nc"
        op = {"starttime": 0.0, "stoptime": 10.0, "ncdfparticlefile": 1}
        ds = open_pbp_ncdf(str(path), op, {"month": "09", "day": "06", "year": "2016"})
        ds.close()
        got = _globals(path)
        self.assertEqual((got[ENGINE], got[PROFILE]), ("soda2", "unstated"))

    def test_soda2_driver_forwards_stamp_profile_to_the_pbp_nc(self):
        """``soda2_process_2d(stamp_profile=...)`` reaches ``open_pbp_ncdf``
        (it used to write "unstated" whatever the caller knew), and moves no
        computed number: every variable equals the unstamped run's."""
        import numpy as np
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from arrayprobe_soda2.process_2d import soda2_process_2d
        from test_soda2_process_2d_pbp import _frame_full_op
        runs = {}
        for profile in (None, "config:ena.toml"):
            out = self.dir / str(profile).replace(":", "_")
            out.mkdir()
            soda2_process_2d(_frame_full_op(str(out) + "/", particlefile=0, ncdfparticlefile=1),
                             stamp_profile=profile)
            (nc,) = out.glob("*.pbp.nc")
            with netCDF4.Dataset(nc, "r") as ds:
                runs[profile] = (ds.getncattr(ENGINE), ds.getncattr(PROFILE),
                                 {v: np.asarray(ds.variables[v][:]) for v in ds.variables})
        self.assertEqual(runs[None][:2], ("soda2", "unstated"))
        self.assertEqual(runs["config:ena.toml"][:2], ("soda2", "config:ena.toml"))
        self.assertEqual(runs[None][2].keys(), runs["config:ena.toml"][2].keys())
        for v, a in runs[None][2].items():
            np.testing.assert_array_equal(a, runs["config:ena.toml"][2][v], err_msg=v)

    @needs_v314_engine
    def test_v314_decode_writer_carries_neither(self):
        from arrayprobe.readers.spec import _ImageFile
        path = self.dir / "x.H.cdf"
        f = _ImageFile(str(path))
        f.close()
        got = _globals(path)
        self.assertNotIn(ENGINE, got)
        self.assertNotIn(PROFILE, got)
        self.assertFalse([a for a in got if provenance.is_provenance_attr(a)])

    @needs_v314_engine
    def test_v314_imgproc_writer_carries_neither_by_default(self):
        # noqa below: arrayprobe.imgproc is v3.1.4-only and absent from the release tree, where
        # ruff's import sorter files it apart from arrayprobe.profiles.
        from arrayprobe.imgproc import _create_output  # noqa: I001
        from arrayprobe.profiles import ORACLES_PRODUCTION
        path = self.dir / "proc314.nc"
        f = _create_output(str(path), ORACLES_PRODUCTION, 128, "ORACLES", "in.H.nc", "2DS",
                           0, 0, "2026/01/01 00:00:00")
        f.close()
        got = _globals(path)
        self.assertFalse([a for a in got if provenance.is_provenance_attr(a)], got)


if __name__ == "__main__":
    unittest.main()
