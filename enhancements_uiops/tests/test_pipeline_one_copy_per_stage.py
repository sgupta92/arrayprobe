# SPDX-License-Identifier: BSD-3-Clause
"""The proc stage copies the proc file once, however many in-place corrections it runs.

Two proc-stage corrections (``hole_edge_swap`` then ``outoffocus``, the two that edit a copy in
place) run on the tracked v3.1.4 demo proc and image, once on the copy-per-applier path
(``pipeline._ONE_COPY_PER_STAGE = False``) and once on the one-copy path. Every file each run
leaves in its output directory -- the ``.enh.proc.nc`` and any sidecar -- must be identical byte
for byte, and every variable and attribute equal; the copies made are counted (2, then 1).
"""
from __future__ import annotations

import dataclasses
import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import netCDF4
import numpy as np

from arrayprobe_enhancements import pipeline

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA = REPO_ROOT / "tests" / "data"
STEM = "base160101000000"
CORRECTIONS = [n for n in pipeline._APPLIERS if n in ("hole_edge_swap", "outoffocus")]
#: The fixture is a v3.1.4 proc and ``outoffocus`` runs it on that engine, which a release
#: tree omits (the development repository keeps it).
_V314 = importlib.util.find_spec("arrayprobe.sizedist") is not None


def _run_proc_stage(root: Path, one_copy: bool) -> tuple[Path, int, list[str]]:
    out = root / ("one" if one_copy else "per")
    out.mkdir()
    proc = out / f"proc.{STEM}.nc"
    image = out / f"{STEM}.H.cdf"
    shutil.copyfile(DATA / "demo_flight_v314_proc.nc", proc)
    shutil.copyfile(DATA / "demo_flight_v314_image.cdf", image)
    outputs = pipeline._RunOutputs(out_dir=out, raw_stem=STEM, engine="3.1.4",
                                   image=image, proc=proc, sd=None, combined=None)
    outputs = dataclasses.replace(outputs, preset_probetype=2)
    real_copy = pipeline._copy_netcdf
    with mock.patch.object(pipeline, "_ONE_COPY_PER_STAGE", one_copy), \
            mock.patch.object(pipeline, "_copy_netcdf", side_effect=real_copy) as copy:
        applied = []
        for name in CORRECTIONS:
            result = pipeline._APPLIERS[name](outputs)
            written = result[0] if isinstance(result, tuple) else result
            assert written == pipeline._enh_path(outputs, "proc")
            outputs.fresh.add("proc")
            applied.append(name)
    return out, copy.call_count, applied


def _attrs(obj) -> dict:
    return {k: obj.getncattr(k) for k in obj.ncattrs()}


@unittest.skipUnless(_V314, "The v3.1.4 engine is not in this release is not distributed with "
                            "the package; this test runs in the development repository")
class OneCopyPerProcStage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="one_copy_"))
        cls.per, cls.per_copies, cls.per_applied = _run_proc_stage(cls.root, one_copy=False)
        cls.one, cls.one_copies, cls.one_applied = _run_proc_stage(cls.root, one_copy=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def test_both_corrections_ran_in_the_same_order(self):
        self.assertEqual(CORRECTIONS, ["hole_edge_swap", "outoffocus"])
        self.assertEqual(self.per_applied, CORRECTIONS)
        self.assertEqual(self.one_applied, CORRECTIONS)

    def test_copies_made_drop_from_two_to_one(self):
        self.assertEqual(self.per_copies, 2)
        self.assertEqual(self.one_copies, 1)

    def test_every_written_file_is_byte_identical(self):
        per = sorted(p.name for p in self.per.iterdir())
        one = sorted(p.name for p in self.one.iterdir())
        self.assertEqual(per, one)
        self.assertIn(f"{STEM}.enh.proc.nc", per)
        self.assertFalse([n for n in per if n.endswith(".tmp")])
        for name in per:
            with self.subTest(file=name):
                self.assertEqual((self.per / name).read_bytes(), (self.one / name).read_bytes())

    def test_every_variable_and_attribute_is_equal(self):
        name = f"{STEM}.enh.proc.nc"
        with netCDF4.Dataset(self.per / name) as a, netCDF4.Dataset(self.one / name) as b:
            self.assertEqual(_attrs(a), _attrs(b))
            self.assertEqual(a.enhancements_applied, ",".join(CORRECTIONS))
            self.assertEqual(list(a.variables), list(b.variables))
            for var in a.variables:
                with self.subTest(variable=var):
                    va, vb = a.variables[var], b.variables[var]
                    self.assertEqual(_attrs(va), _attrs(vb))
                    self.assertEqual(va.dtype, vb.dtype)
                    np.testing.assert_array_equal(np.ma.getdata(va[:]), np.ma.getdata(vb[:]))
                    np.testing.assert_array_equal(np.ma.getmaskarray(va[:]),
                                                  np.ma.getmaskarray(vb[:]))


class ASkipLeavesTheEarlierWorkInPlace(unittest.TestCase):
    def test_skip_on_the_in_place_path_keeps_the_enh_proc(self):
        root = Path(tempfile.mkdtemp(prefix="one_copy_skip_"))
        try:
            dst = root / f"{STEM}.enh.proc.nc"
            shutil.copyfile(DATA / "demo_flight_v314_proc.nc", dst)
            before = dst.read_bytes()
            pipeline._discard_edit_target(dst, dst)
            self.assertEqual(dst.read_bytes(), before)
            tmp = pipeline._tmp_for(dst)
            shutil.copyfile(dst, tmp)
            pipeline._discard_edit_target(tmp, dst)
            self.assertFalse(tmp.exists())
            self.assertTrue(dst.exists())
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
