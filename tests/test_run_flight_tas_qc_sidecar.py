# SPDX-License-Identifier: BSD-3-Clause
"""Step 2: S4 (faithful and enhanced) writes ``<sd>.tasqc.json`` when a run names a TAS
source, and changes neither the ``.call`` nor the sd file's own attributes.


Reuses :mod:`test_run_flight_tas_chain`'s demo-flight fixture.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

import netCDF4
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tests._repo import needs_v314_engine  # noqa: E402

import test_run_flight_tas_chain as _chain_tests  # noqa: E402
from test_run_flight_tas_chain import _WithProcAndCsv  # noqa: E402

setUpModule = _chain_tests.setUpModule


def _rf():
    return _chain_tests.run_flight


class SdSidecar(_WithProcAndCsv):

    def _chain(self, out, probe_t):
        rf = _rf()
        # The chain lacks the probe's first second, so that second is missing and absent.
        seconds = np.unique(np.floor(probe_t).astype(np.int64))[1:]
        return rf._tas_sources.ChainResult(
            mode="auto", tier="aircraft", source="oracles-p3-merge",
            path=str(out / "fake_merge.nc"), time=seconds.astype(np.float64),
            tas=np.full(seconds.shape, 61.5), policy=rf._mtf.TasPolicy(),
            steps=[], substituted=[], lines=[], provenance={})

    @needs_v314_engine
    def test_sd_gets_sidecar(self):
        rf = _rf()
        out, raw, proc, tas_csv = self._build_proc_and_csv()
        probe_t, _ = rf.load_tas_info(tas_csv)
        chain = self._chain(out, probe_t)
        self._run_stage4_mocked(out, raw, proc, chain)
        sd = out / f"sd.{raw.stem}.H.nc"
        rec = rf._tas_sources.read_qc_sidecar(sd)
        self.assertIsNotNone(rec, "a chain run wrote no .tasqc.json")
        self.assertEqual(rec["tas_missing_count"], 1)
        self.assertEqual(rec["tas_chain_used"], "aircraft:oracles-p3-merge")
        # The .call is exactly the stamp a chain run always wrote: no QC field reaches it.
        call = rf.read_stamp(sd)
        self.assertEqual(call, rf.sd_call_label(rf.IAT_FILE))
        for key in rec:
            self.assertNotIn(key, call)

    @needs_v314_engine
    def test_enhanced_sd_gets_sidecar(self):
        rf = _rf()
        out, raw, proc, tas_csv = self._build_proc_and_csv()
        probe_t, _ = rf.load_tas_info(tas_csv)
        rf.TAS_CHAIN = self._chain(out, probe_t)
        rf.TAS_POLICY = rf.TAS_CHAIN.policy
        dst = out / f"{raw.stem}.enh.sd.nc"
        with mock.patch.object(rf.sizedist, "run") as mocked:
            mocked.side_effect = lambda *a, **kw: Path(a[1]).write_bytes(b"")
            rf.EnhancedStages(out, rf.IAT_FILE).sizedist(proc, raw.stem, dst)
        rec = rf._tas_sources.read_qc_sidecar(dst)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["tas_missing_count"], 1)

    @needs_v314_engine
    def test_legacy_no_sidecar(self):
        rf = _rf()
        out, raw, proc, _tas_csv = self._build_proc_and_csv()
        self.assertIsNone(rf.TAS_CHAIN)
        rf.TAS_FILE = None
        sd = out / f"sd.{raw.stem}.H.nc"
        # A record left by an earlier source run must not survive to describe this product.
        rf._tas_sources.write_qc_sidecar(sd, {"tas_qc_convention": "arrayprobe-tasqc-1"})
        with mock.patch.object(rf.sizedist, "run") as mocked:
            mocked.side_effect = lambda *a, **kw: Path(a[1]).write_bytes(b"")
            rf.stage4(proc, raw.stem, out, rf.IAT_FILE)
        self.assertFalse(rf._tas_sources.qc_sidecar_path(sd).exists())

    @needs_v314_engine
    def test_faithful_bytes_unchanged(self):
        """A real sizeDist on the demo flight, chain run: the sd file carries no arrayprobe_tas*
        attribute -- the record lives only in the sidecar."""
        rf = _rf()
        out, raw, proc, tas_csv = self._build_proc_and_csv()
        probe_t, _ = rf.load_tas_info(tas_csv)
        rf.TAS_CHAIN = self._chain(out, probe_t)
        rf.TAS_POLICY = rf.TAS_CHAIN.policy
        sd = rf.stage4(proc, raw.stem, out, rf.IAT_FILE)
        self.assertIsNotNone(rf._tas_sources.read_qc_sidecar(sd))
        with netCDF4.Dataset(sd) as ds:
            names = list(ds.ncattrs())
            for v in ds.variables.values():
                names += list(v.ncattrs())
        self.assertEqual([n for n in names if n.startswith(("arrayprobe_tas", "tas_"))], [])


class CombinedSidecar(unittest.TestCase):
    """Step 5: S4c merges the constituent sd records into ``<combined>.tasqc.json``."""

    def _rec(self, probe_t, missing):
        ts = _rf()._tas_sources
        policy = _rf()._mtf.TasPolicy()
        return ts.qc_record(None, policy, probe_t, missing, legacy_subs=[])

    def test_merged_from_every_part(self):
        import tempfile
        rf = _rf()
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            sds = [d / "sd.a.H.nc", d / "sd.b.H.nc"]
            rf._tas_sources.write_qc_sidecar(sds[0], self._rec([120000.0, 120001.0], [120000]))
            rf._tas_sources.write_qc_sidecar(sds[1], self._rec([130000.0], [130000]))
            target = d / "combined.nc"
            rf._write_combined_tas_qc(target, sds)
            rec = rf._tas_sources.read_qc_sidecar(target)
            self.assertEqual(rec["tas_qc_parts"], "sd.a.H.nc,sd.b.H.nc")
            self.assertEqual(rec["tas_missing_count"], 2)
            self.assertEqual(rec["tas_missing_ranges"], "120000,130000")
            self.assertEqual(rec["tas_seconds_total"], 3)

    def test_none_written_without_part_records_and_stale_removed(self):
        import tempfile
        rf = _rf()
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            target = d / "combined.nc"
            rf._tas_sources.write_qc_sidecar(target, self._rec([1.0], []))
            rf._write_combined_tas_qc(target, [d / "sd.a.H.nc"])
            self.assertFalse(rf._tas_sources.qc_sidecar_path(target).exists())

    def test_part_without_record_refused(self):
        import tempfile
        rf = _rf()
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            sds = [d / "sd.a.H.nc", d / "sd.b.H.nc"]
            rf._tas_sources.write_qc_sidecar(sds[0], self._rec([120000.0], []))
            with self.assertRaises(SystemExit):
                rf._write_combined_tas_qc(d / "combined.nc", sds)


if __name__ == "__main__":
    unittest.main()
