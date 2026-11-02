# SPDX-License-Identifier: BSD-3-Clause
"""The FEATURE demo flight carries every fault it claims to.

``arrayprobe.tools.make_demo_flight.build_feature_demo_flight`` exists because
enhancement A/Bs on the plain and dense demo flights came out vacuous -- those
flights have no clipped particle, no duplicated TAS second, no clock glitch.
This module pins (1) the tracked raw bytes (a fresh build must reproduce them)
and (2) that each feature in ``FEATURES`` is present in the *decoded* output,
read from the port's own S2 sidecar and S3 proc file rather than from the
builder's description of itself.

The plain and dense flights are untouched by this builder; their own digests
stay pinned by ``test_demo_reference.py`` and ``test_demo_flight_thresholds.py``.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data"
DIGEST = json.loads((DATA / "demo_flight_feature_digest.json").read_text())
TRACKED_RAW = DATA / "demo_flight_feature_raw.2DS"

from tests._repo import needs_v314_engine  # noqa: E402

from arrayprobe.tools import make_demo_flight as mdf  # noqa: E402

_RF_SPEC = importlib.util.spec_from_file_location(
    "_test_demo_flight_features_run_flight", ROOT / "scripts" / "run_flight.py")


class TheTrackedRawIsWhatTheBuilderWrites(unittest.TestCase):
    def test_fresh_build_matches_the_tracked_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            raw = mdf.build_feature_demo_flight(Path(td) / "base160101000000.2DS",
                                                seed=DIGEST["seed"])
            data = raw.read_bytes()
        self.assertEqual(len(data), DIGEST["raw_size_bytes"])
        self.assertEqual(hashlib.sha256(data).hexdigest(), DIGEST["raw_sha256"])
        self.assertEqual(data, TRACKED_RAW.read_bytes())

    def test_stays_small_enough_to_track(self):
        self.assertLess(TRACKED_RAW.stat().st_size, 300_000)

    def test_every_feature_names_its_matlab_line(self):
        for name, feat in mdf.FEATURES.items():
            self.assertRegex(feat["matlab"], r"\.m[: ]", name)


@needs_v314_engine
class EachFeatureIsInTheDecodedOutput(unittest.TestCase):
    """S2 + S3 once, under the port's default (ORACLES production) profile."""

    @classmethod
    def setUpClass(cls):
        rf = importlib.util.module_from_spec(_RF_SPEC)
        sys.modules[_RF_SPEC.name] = rf
        _RF_SPEC.loader.exec_module(rf)
        rf.log = lambda *a, **kw: None
        cls._tmp = tempfile.TemporaryDirectory()
        out = Path(cls._tmp.name)
        cls.raw = out / "base160101000000.2DS"
        cls.raw.write_bytes(TRACKED_RAW.read_bytes())
        image = rf.stage2(cls.raw, out)
        proc = rf.stage3(image, out)
        with netCDF4.Dataset(str(proc)) as ds:
            cls.v = {k: np.asarray(ds.variables[k][:]).ravel() for k in (
                "image_auto_reject", "image_touching_edge", "image_center_in", "Time",
                "image_width", "image_length")}
        cls.tas_rows = [ln.split(",") for ln in
                        (out / "base160101000000.tas.csv").read_text().splitlines() if ln]
        # The port decodes every particle but the final record's (read_binary_SPEC.m).
        cls.man = [p for p in mdf.feature_particle_manifest(DIGEST["seed"])
                   if p["feature"] != "last_record_particles"]

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop(_RF_SPEC.name, None)
        cls._tmp.cleanup()

    def _idx(self, feature):
        return [i for i, p in enumerate(self.man) if p["feature"] == feature]

    def test_particle_count_is_the_manifest_less_the_final_record(self):
        self.assertEqual(len(self.v["Time"]), len(self.man))
        self.assertEqual(len(self.man), DIGEST["n_particles_decoded_by_the_port"])

    def test_edge_clipped_particles_touch_the_edge(self):
        # calculate_reject_unified.m:213-216 't', written as 't' - '0' = 68 (imgProc_sm.m:897)
        idx = self._idx("edge_clipped")
        self.assertEqual(len(idx), 6)
        self.assertTrue(np.all(self.v["image_touching_edge"][idx] == 68))
        others = [i for i in range(len(self.man)) if i not in idx]
        self.assertFalse(np.any(self.v["image_touching_edge"][others] == 68))
        mins = {self.man[i]["min_diode"] for i in idx}
        maxs = {self.man[i]["max_diode"] for i in idx}
        self.assertIn(1, mins)
        self.assertIn(128, maxs)

    def test_hollow_rings_are_decoded_with_their_hole(self):
        idx = self._idx("hollow_ring")
        self.assertEqual(len(idx), 6)
        for i in idx:
            p = self.man[i]
            self.assertLess(p["area"], 0.8 * p["n_slices"] * p["width"])
        self.assertTrue(any(self.man[i]["max_diode"] <= 32 for i in idx))
        self.assertTrue(any(self.man[i]["min_diode"] > 32 for i in idx))

    def test_one_diode_streaks_are_one_diode_wide_and_rejected(self):
        idx = self._idx("one_diode_streak")
        self.assertTrue(np.all(self.v["image_width"][idx] == 1))
        self.assertTrue(np.all(self.v["image_auto_reject"][idx] == ord("a")))

    def test_stuck_diode_widens_every_particle_to_it(self):
        idx = self._idx("stuck_diode")
        self.assertEqual(len(idx), 12)
        for i in idx:
            self.assertEqual(self.man[i]["max_diode"], mdf.FEATURE_STUCK_DIODE)
        self.assertTrue(np.all(self.v["image_width"][idx] > 20))

    def test_noisy_diode_fires_one_pixel_particles(self):
        idx = self._idx("noisy_diode")
        self.assertEqual(len(idx), 10)
        self.assertTrue(np.all(self.v["image_width"][idx] == 1))
        self.assertTrue(np.all(self.v["image_length"][idx] == 1))
        self.assertEqual({self.man[i]["min_diode"] for i in idx}, {mdf.FEATURE_NOISY_DIODE})

    def test_shattering_burst_carries_sub_threshold_gaps(self):
        idx = self._idx("shattering_burst")
        self.assertEqual(len(idx), 14)
        # 10 burst particles sit FEATURE_GAP_BURST counts behind their predecessor
        self.assertEqual(sum(1 for i in range(len(self.man)) if i in idx), 14)

    def test_the_tas_grid_has_one_duplicated_and_one_missing_second(self):
        secs = [int(float(r[0])) for r in self.tas_rows]
        values, counts = np.unique(secs, return_counts=True)
        self.assertEqual(values[counts > 1].tolist(), [60651])
        self.assertEqual(sorted(set(range(secs[0], secs[-1] + 1)) - set(secs)), [60652])
        dup = [float(r[1]) for r in self.tas_rows if int(float(r[0])) == 60651]
        self.assertEqual(dup, [130.0, mdf.FEATURE_DUPLICATE_TAS_MPS])

    def test_exactly_one_particle_time_decrease_at_the_glitch(self):
        t = self.v["Time"].astype(float)
        dec = np.flatnonzero(np.diff(t) < 0) + 1
        glitch = self._idx("bad_particle_timestamp")
        self.assertEqual(len(glitch), 1)
        self.assertEqual(dec.tolist(), glitch)
        self.assertLess(t[glitch[0]], 10000)   # hour field 0: 00:MM:SS
        # sizeDist.m:544-545 would shift the glitch and every later particle by 240000
        victims = self._idx("cascade_victims")
        self.assertTrue(all(v > glitch[0] for v in victims))


def _final_record_image_packets(path: Path) -> int:
    """Count '2S' markers in the file's final record, read straight from the bytes."""
    from arrayprobe.readers import spec
    words = np.fromfile(path, dtype="<u2").reshape(-1, spec.RECORD_WORDS)
    last = words[-1, spec.HEADER_WORDS:]
    n, i = 0, 0
    while i < last.size:
        if last[i] == spec.MARKER_2S:
            n += 1
            i += 5 + int(last[i + 1] & 0x0FFF)
        else:
            i += 1
    return n


class TheFinalRecordHoldsParticles(unittest.TestCase):
    @needs_v314_engine
    def test_final_record_has_the_last_record_particles(self):
        want = sum(p["feature"] == "last_record_particles"
                   for p in mdf.feature_particle_manifest(DIGEST["seed"]))
        self.assertEqual(want, 4)
        self.assertEqual(_final_record_image_packets(TRACKED_RAW), want)


if __name__ == "__main__":
    unittest.main()
