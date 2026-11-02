# SPDX-License-Identifier: BSD-3-Clause
"""v3.5 particle stage: port defects found by the 2026-09-28 whole-module review.

Every expected value here was produced by the unmodified vendored v3.5 source
running under Octave 11.3 (``octave_oracle/run_v35_r10_particle_bank.py`` ->
``tests/data/v35_r10_particle_golden.json``).

"""

from __future__ import annotations

import hashlib
import json
import math
import unittest
from pathlib import Path

import numpy as np
from tests import _upstream  # noqa: E402
from tests._repo import repo_only

from arrayprobe_uiops import habit as v35_habit
from arrayprobe_uiops import imgproc as v35_imgproc

GOLDEN = json.loads((Path(__file__).resolve().parent / "data"
                     / "v35_r10_particle_golden.json").read_text(encoding="utf-8"))
V35_TREE = _upstream.source("uiops35")
_FIELDS = ("F", "w_l_p", "c_r", "e_d_r", "m_g", "O", "a_r", "p")


def setUpModule():
    # Raised here rather than at import: an import-time SkipTest crashes
    # ``python -m unittest tests.<module>``, where ``discover`` reports it as a skip.
    _upstream.require("uiops35")


def _same(a: float, b: float) -> bool:
    return (math.isnan(a) and math.isnan(b)) or a == b


@repo_only
class TestGoldenProvenance(unittest.TestCase):
    def test_the_golden_ran_the_vendored_habit_files(self):
        for name, digest in GOLDEN["sources_sha256"].items():
            self.assertEqual(hashlib.sha256((V35_TREE / name).read_bytes()).hexdigest(), digest,
                             f"{name} changed; re-run octave_oracle/run_v35_r10_particle_bank.py")


class TestHolroydNew421ImaginarySqrt(unittest.TestCase):
    """``holroyd_new.m:421`` / ``holroyd_new_HVPS.m:382``: ``sqrt`` of a negative
    ``cross_x2 * cross_y2`` is imaginary in MATLAB, its real part 0 passes the
    ``r2_correlation < 0.3`` reset, and the particle is measured unrotated. The
    port took a float ``sqrt`` (NaN), skipped the reset and rotated the particle,
    so ``a_r``, ``F``, ``c_r`` and ``e_d_r`` all moved (a 26-diode line read as
    aspect ratio 3.1 where MATLAB writes 26)."""

    def test_the_bank_reaches_the_imaginary_branch(self):
        neg = [r for r in GOLDEN["complex_r2"] if r["r2_prod"] < 0]
        self.assertGreaterEqual(len(neg), 18)
        self.assertTrue(any(r["r2_prod"] >= 0 for r in GOLDEN["complex_r2"]),
                        "the controls (product >= 0) are gone")

    def test_holroyd_new_421_single_slice_particles_match_octave(self):  # noqa: N802
        cases = {c["name"]: c for c in GOLDEN["cases"]}
        for want in GOLDEN["complex_r2"]:
            case = cases[want["name"]]
            with self.subTest(case=want["name"]):
                img = np.array(list(case["flat"]), dtype="U1").reshape(case["rows"], case["cols"])
                fn = (v35_habit.holroyd_new_hvps if case["fn"] == "holroyd_new_HVPS"
                      else v35_habit.holroyd_new)
                got = fn(img, probe_resolution=case["diodesize"], tas_ratio=case["tasRatio"],
                         bits_per_slice=case["cols"])
                self.assertEqual(got.holroyd_habit, want["habit"])
                for f in _FIELDS:
                    self.assertTrue(_same(float(getattr(got, f)), float(want[f])),
                                    f"{f}: port {getattr(got, f)!r}, Octave {want[f]!r}")


class TestMatlabRoundHalfAwayFromZero(unittest.TestCase):
    """``floor(x + 0.5)`` is not MATLAB ``round``: ``0.49999999999999994 + 0.5``
    rounds to 1.0, and so does every odd integer above 2^52 plus 0.5."""

    def test_holroyd_new_454_round_matches_octave(self):
        for row in GOLDEN["round"]:
            with self.subTest(x=row["x"]):
                self.assertEqual(v35_habit._matlab_round(row["x"]), row["round"])

    def test_imgProc_980_int16_matches_octave(self):  # noqa: N802
        for row in GOLDEN["round"]:
            with self.subTest(x=row["x"]):
                self.assertEqual(v35_imgproc._matlab_int16(row["x"]), row["int16"])

    def test_nan_still_round_trips(self):
        self.assertTrue(math.isnan(v35_habit._matlab_round(math.nan)))


def _decode(values: list) -> np.ndarray:
    return np.array([math.nan if v is None else math.inf if v == "Inf"
                     else -math.inf if v == "-Inf" else v for v in values], dtype=np.float64)


def _write_pms_input(case: dict, dest: Path) -> None:
    """The same bytes ``run_v35_r10_particle_bank.write_pms_input`` gave Octave."""
    from netCDF4 import Dataset

    template = Path(__file__).resolve().parent / "data" / {
        "2dc": "s7c_2dc_octave_decoded.nc", "f2dc": "s7e_f2dc_octave_decoded.nc"}[case["template"]]
    with Dataset(str(template)) as src, Dataset(str(dest), "w", format=src.file_format) as dst:
        for name, d in src.dimensions.items():
            dst.createDimension(name, None if name == "time" else len(d))
        for name, v in src.variables.items():
            nv = dst.createVariable(name, v.dtype, v.dimensions)
            for a in v.ncattrs():
                if a != "_FillValue":
                    nv.setncattr(a, v.getncattr(a))
        dst.set_auto_maskandscale(False)
        for i, rec in enumerate(case["records"]):
            rows = list(rec["rows"])
            rows += [[case["filler"]] * len(rows[0])] * (case["rows_per_record"] - len(rows))
            dst["data"][i, :, :] = np.asarray(rows, dtype=np.int32)
            for k, val in rec["clock"].items():
                dst[k][i] = val


class TestProbetype03ParticleTimeClasses(unittest.TestCase):
    """``imgProc_sm.m:861-934`` on probetypes 0 and 3, whole program.

    ``:866`` divides by the record's ``tas``; at 0 MATLAB gets Inf (or NaN for a
    zero clock) where the port raised ``ZeroDivisionError`` and wrote nothing.
    ``part_hour``/``part_min``/``part_sec`` are ``int8`` and ``part_mil`` is
    ``int16`` (``:901-904`` copy the header variables' classes), so ``:915-917``
    round and saturate, and ``:922-933`` re-apply the carry to the whole vector
    at every particle, which revisits an earlier particle left at 60 or more
    by saturation. The port summed in double and carried the current particle
    only."""

    #: Values the port reaches by a different floating-point route (the exact
    #: minimum circle, the QR least-squares slope), compared to 1e-9.
    _FLOAT_ROUTE = {"sphericity", "image_xpos", "image_ypos", "image_diam_minR"}

    def _run(self, case: dict, tmp: Path) -> dict:
        from netCDF4 import Dataset

        from arrayprobe_uiops.imgproc import imgproc_sm_v35
        from arrayprobe_uiops.measure import STOCK_V35_REJECT_CONFIG

        infile = tmp / f"{case['name']}.in.nc"
        _write_pms_input(case, infile)
        out = tmp / f"{case['name']}.port.nc"
        imgproc_sm_v35(str(infile), out, case["probe"], 1, 1000, "TEST",
                       iCalcAllDiodeStats=1, iQC=0, iNewHabit=0,
                       reject_config=STOCK_V35_REJECT_CONFIG, tas_time=None, tas=None,
                       software="UIOOPS_v3.5", creation_time="x")
        with Dataset(str(out)) as ds:
            ds.set_auto_maskandscale(False)
            return {n: np.asarray(v[:], dtype=np.float64) for n, v in ds.variables.items()}

    def test_imgProc_866_to_933_every_variable_matches_octave(self):  # noqa: N802
        import tempfile

        cases = {c["name"]: c for c in GOLDEN["pms_cases"]}
        with tempfile.TemporaryDirectory() as tmp:
            for want in GOLDEN["pms"]:
                with self.subTest(case=want["name"]):
                    got = self._run(cases[want["name"]], Path(tmp))
                    self.assertEqual(sorted(got), sorted(want["variables"]))
                    for name, spec in want["variables"].items():
                        w = _decode(spec["values"])
                        h = got[name].ravel()
                        self.assertEqual(h.size, w.size, name)
                        if name in self._FLOAT_ROUTE:
                            np.testing.assert_allclose(h, w, rtol=1e-9, equal_nan=True,
                                                       err_msg=name)
                        else:
                            np.testing.assert_array_equal(h, w, err_msg=name)

    def test_the_cases_reach_the_paths_they_were_built_for(self):
        by_name = {r["name"]: r["variables"] for r in GOLDEN["pms"]}
        t = _decode(by_name["2dc_tas0"]["Time_in_seconds"]["values"])
        self.assertTrue(np.isinf(t).any() and np.isnan(t).any(), "tas=0 gives Inf and NaN")
        pt = _decode(by_name["f2dc_midnight"]["particle_time"]["values"])
        self.assertTrue(((pt > 0) & (pt < 127)).any(),
                        "an unsaturated particle_time after midnight")


if __name__ == "__main__":
    unittest.main()
