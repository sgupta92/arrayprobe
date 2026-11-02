# SPDX-License-Identifier: BSD-3-Clause
"""``run_flight.stage2 --s2-jobs N`` for a DMT ``.cip`` file.

``--s2-jobs > 1`` is allowed for ``.cip`` (``readers.dmt.read_binary_DMT_parallel``)
and still refused for ``.sea`` and PMS, which have no parallel form. The pool
is replaced by an in-process stand-in so these tests spawn nothing; the real
pool's byte-identity is ``tests/test_dmt_parallel.py``.

"""
from __future__ import annotations

import concurrent.futures
import concurrent.futures.process
import dataclasses
import filecmp
import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1] / "scripts"
FIXTURE = Path(__file__).resolve().parent / "data" / "dmt_raw_synthetic.cip"


def _load():
    spec = importlib.util.spec_from_file_location("run_flight", TOOLS / "run_flight.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("run_flight", module)
    spec.loader.exec_module(module)
    return module


class _InProcessPool:
    def __init__(self, max_workers=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def map(self, fn, tasks):
        return [fn(t) for t in tasks]


class _DeadPool(_InProcessPool):
    def map(self, fn, tasks):
        raise concurrent.futures.process.BrokenProcessPool("dead")


class DmtParallelThroughTheDriver(unittest.TestCase):
    def setUp(self):
        self.mod = _load()
        self._saved = self.mod.ACTIVE
        self.mod.use_preset("UND_2016_CIP")
        self.tmp = Path(tempfile.mkdtemp(prefix="rf_dmtpar_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def tearDown(self):
        self.mod.use_preset(self._saved.name)

    def _run(self, name, jobs, pool=_InProcessPool):
        out = self.tmp / name
        out.mkdir()
        raw = out / "flight.cip"
        shutil.copyfile(FIXTURE, raw)
        with (mock.patch.object(concurrent.futures, "ProcessPoolExecutor", pool),
              mock.patch("time.sleep")):
            target = self.mod.stage2(raw, out, s2_jobs=jobs)
        record = (out / f"{target.name}.decode").read_text(encoding="utf-8").strip()
        return target, record

    def test_cip_parallel_equals_serial_and_says_so(self):
        serial, rec_s = self._run("serial", 1)
        par, rec_p = self._run("par", 3)
        self.assertTrue(rec_s.startswith("mode=serial jobs=1 reader="), rec_s)
        self.assertEqual(
            rec_p, "mode=parallel jobs=3 retries=0 "
                   "reader=arrayprobe.readers.dmt.read_binary_DMT")
        self.assertEqual(serial.name, par.name)
        self.assertTrue(filecmp.cmp(serial, par, shallow=False))

    def test_a_dead_pool_falls_back_to_serial(self):
        serial, _ = self._run("serial", 1)
        par, rec = self._run("dead", 2, pool=_DeadPool)
        self.assertTrue(rec.startswith("mode=serial_fallback(from_parallel) jobs=2 "), rec)
        self.assertTrue(filecmp.cmp(serial, par, shallow=False))

    def test_sea_is_still_refused(self):
        raw = self.tmp / "flight.sea"
        raw.write_bytes(b"")
        with self.assertRaises(self.mod.UnsupportedProbe) as caught:
            self.mod.stage2(raw, self.tmp, s2_jobs=4)
        self.assertIn("--s2-jobs", str(caught.exception))

    def test_pms_is_still_refused(self):
        twodc = dataclasses.replace(self._saved, name="TEST_ONLY_2DC_DMTPAR", probe="2DC",
                                    orientation="none")
        self.mod.PRESETS[twodc.name] = twodc
        self.addCleanup(self.mod.PRESETS.pop, twodc.name, None)
        self.mod.use_preset(twodc.name)
        raw = self.tmp / "flight.PMS"
        raw.write_bytes(b"")
        with self.assertRaises(self.mod.UnsupportedProbe) as caught:
            self.mod.stage2(raw, self.tmp, s2_jobs=4)
        self.assertIn("--s2-jobs", str(caught.exception))

# _release_fixture_guard: skip unless the synthetic DMT fixture is present
import pathlib as _rfg_pathlib  # noqa: E402
import unittest as _rfg_unittest  # noqa: E402

_RFG_EXCLUDED = ('dmt_raw_synthetic.cip',)
if not all((_rfg_pathlib.Path(__file__).resolve().parent / "data" / _n).exists()
           for _n in _RFG_EXCLUDED):
    raise _rfg_unittest.SkipTest(
        "the synthetic DMT raw fixture (tests/data/dmt_raw_synthetic.cip) "
        "is not present in this tree")

if __name__ == "__main__":
    unittest.main()
