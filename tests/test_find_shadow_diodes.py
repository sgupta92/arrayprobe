# SPDX-License-Identifier: BSD-3-Clause
"""``masks.find_shadow_diodes`` against the real ``find_shadow_diodes.m`` run in Octave.

The golden (``tests/data/find_shadow_diodes_octave_golden.json``) is written by
``octave_oracle/run_find_shadow_diodes_bank.py``: the dissertation-recovered
source, unedited, with its hard-coded ``/condo/...`` path resolved through a
``subst`` drive.  Three shims (``octave_oracle/shims/find_shadow_diodes/``) --
``nanmean`` (absent from Octave core), ``ncread`` (a drive prefix) and
``saveas`` (no rendering) -- none of which computes a value the bank pins.

Each case builds the same proc file here, runs the port, and compares what
MATLAB-under-Octave computed and saved: the returned diodes, the ``.mat``
filename (F2's ``...Hempty.mat`` included), the saved workspace's variable
names in order, ``a`` after the high-count replacement and its class, and the
error when the source dies before saving.  Two mutations show the comparison
is not vacuous.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import netCDF4
import numpy as np

from arrayprobe import masks
from arrayprobe.matio import loadmat
from arrayprobe_uiops import diode_mask

DATA = Path(__file__).resolve().parent / "data"
GOLDEN = json.loads((DATA / "find_shadow_diodes_octave_golden.json").read_text(encoding="utf-8"))
CASES = {c["name"]: c for c in GOLDEN["cases"]}


def _proc(directory: Path, case: dict) -> Path:
    path = directory / f"base{case['date']}{case['time']}.{case['orientation']}_1.cdf"
    with netCDF4.Dataset(str(path), "w", format="NETCDF3_CLASSIC") as ds:
        ds.createDimension("bin_count", len(case["bin_stats"]))
        ds.createVariable("bin_stats", "i4", ("bin_count",))[:] = np.asarray(
            case["bin_stats"], dtype=np.int32)
    return path


def _run(case: dict, directory: Path):
    _proc(directory, case)
    return masks.find_shadow_diodes(case["date"], case["time"], case["orientation"],
                                    path=str(directory) + "/")


def _mismatches(case: dict, directory: Path) -> list[str]:
    """Every way the port's run of ``case`` differs from Octave's."""
    wrong = []
    try:
        result = _run(case, directory)
    except masks.ShadowDiodeSearchError as exc:
        if case["status"] != "ERROR":
            wrong.append(f"port raised, Octave did not: {exc}")
        return wrong
    if case["status"] == "ERROR":
        return [f"Octave died ({case['error']}), the port returned"]
    written = sorted(p.name for p in directory.glob("diode.*.mat"))
    if written != case["mat_files"]:
        wrong.append(f"mat files {written} != {case['mat_files']}")
    if result.shadow_diode.tolist() != case["shadow_diode"]:
        wrong.append(f"shadow_diode {result.shadow_diode.tolist()} != {case['shadow_diode']}")
    if written:
        mat = loadmat(directory / written[0])
        if list(mat.keys()) != case["saved_variables"]:
            wrong.append(f"saved variables {list(mat.keys())} != {case['saved_variables']}")
        saved = np.asarray(mat["shadow_diode"])
        if list(saved.shape) != case["shadow_diode_shape"]:
            wrong.append(f"shadow_diode shape {saved.shape} != {case['shadow_diode_shape']}")
        a = np.asarray(mat["a"])
        if str(a.dtype) != case["a_class"] or a.ravel().tolist() != case["a"]:
            wrong.append("saved a differs from Octave's")
    return wrong


class TheOctaveBank(unittest.TestCase):
    def test_the_bank_covers_both_branches_f2_and_the_error(self):
        statuses = {c["status"] for c in GOLDEN["cases"]}
        self.assertEqual({"OK", "ERROR"}, statuses)
        self.assertTrue(any(f.endswith("empty.mat") for c in GOLDEN["cases"]
                            for f in c["mat_files"]), "no F2 case in the bank")
        self.assertGreaterEqual(len(GOLDEN["cases"]), 8)

    def test_every_case_matches_octave(self):
        for name, case in CASES.items():
            with self.subTest(case=name), tempfile.TemporaryDirectory() as tmp:
                self.assertEqual([], _mismatches(case, Path(tmp)))

    def test_the_tracked_demo_proc_read_in_place(self):
        case = CASES["demo_v314_proc"]
        with tempfile.TemporaryDirectory() as tmp:
            result = masks.find_shadow_diodes(
                case["date"], case["time"], case["orientation"], path=tmp + "/",
                infile=DATA / "demo_flight_v314_proc.nc")
            self.assertEqual(case["shadow_diode"], result.shadow_diode.tolist())
            self.assertEqual(case["mat_files"], [result.written.name])

    def test_the_saved_mask_loads_through_the_second_pass_loader(self):
        case = CASES["max_branch_two_stuck"]
        with tempfile.TemporaryDirectory() as tmp:
            _run(case, Path(tmp))
            infile = f"base{case['date']}{case['time']}.{case['orientation']}.cdf"
            mask = masks.find_shadow_diode_mask(tmp, case["date"], case["time"], infile)
            self.assertIsNotNone(mask)
            self.assertEqual([3.0, 77.0], mask.diodes.tolist())

    def test_f2_the_empty_mask_is_invisible_to_the_second_pass(self):
        case = CASES["flat_empty"]
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(case, Path(tmp))
            self.assertEqual("diode.160906000002.Hempty.mat", result.written.name)
            infile = f"base{case['date']}{case['time']}.H.cdf"
            self.assertIsNone(masks.find_shadow_diode_mask(
                tmp, case["date"], case["time"], infile))


class TheQuirksAreThere(unittest.TestCase):
    def test_nan_in_int32_is_zero_so_the_replacement_is_diluted(self):
        case = CASES["mean_branch_nan_dilution"]
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(case, Path(tmp))
        self.assertEqual("mean", result.branch)
        self.assertEqual(20, result.ill_diode.size)
        self.assertEqual(842, int(result.a[-1]))      # (107000+790)/128, not 998
        self.assertEqual([], result.shadow_diode.tolist())

    def test_the_diodes_masked_in_flight_can_come_back_as_shadow_diodes(self):
        case = CASES["mean_branch_flags_the_high_diodes"]
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(case, Path(tmp))
        self.assertEqual(list(range(69, 129)), result.shadow_diode.astype(int).tolist())

    def test_the_max_branch_is_strict_and_int32(self):
        case = CASES["max_branch_strict_boundary"]
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(case, Path(tmp))
        self.assertEqual(("max", 800.0), (result.branch, result.threshold))
        self.assertEqual([101.0], result.shadow_diode.tolist())

    def test_write_false_writes_nothing(self):
        case = CASES["max_branch_two_stuck"]
        with tempfile.TemporaryDirectory() as tmp:
            _proc(Path(tmp), case)
            result = masks.find_shadow_diodes(case["date"], case["time"], "H",
                                              path=tmp + "/", write=False)
            self.assertIsNone(result.written)
            self.assertEqual([], list(Path(tmp).glob("*.mat")))

    def test_shadowed_counts_are_converted_before_the_rule(self):
        # Stock UIOOPS counts shadowed slices; the rule wants lit ones.
        case = dict(CASES["max_branch_two_stuck"])
        lit = np.asarray(case["bin_stats"], dtype=np.int64)
        total = int(lit.max()) + 5
        shadow = dict(case, bin_stats=(total - lit).tolist())
        with tempfile.TemporaryDirectory() as tmp:
            _proc(Path(tmp), shadow)
            kw = dict(path=tmp + "/", write=False)
            converted = masks.find_shadow_diodes(
                case["date"], case["time"], "H", counts="shadowed", slice_total=total, **kw)
            self.assertEqual([3.0, 77.0], converted.shadow_diode.tolist())
            raw = masks.find_shadow_diodes(case["date"], case["time"], "H", **kw)
            self.assertNotEqual([3.0, 77.0], raw.shadow_diode.tolist())
            with self.assertRaises(ValueError):
                masks.find_shadow_diodes(case["date"], case["time"], "H",
                                         counts="shadowed", **kw)
            with self.assertRaises(ValueError):
                masks.find_shadow_diodes(case["date"], case["time"], "H",
                                         counts="dark", **kw)


class TheCommandLine(unittest.TestCase):
    """``arrayprobe diode-masks``: both views, and only MATLAB's file written."""

    def test_it_writes_only_the_mask_and_prints_both_views(self):
        import contextlib
        import io
        import shutil

        from arrayprobe import cli
        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp) / "proc.base160906000001.H.nc"
            shutil.copy(DATA / "demo_flight_v314_proc.nc", proc)
            before = set(Path(tmp).iterdir())
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                status = cli.main(["diode-masks", "--proc", str(proc),
                                   "--profile", "oracles-production",
                                   "--image", str(DATA / "demo_flight_v314_image.cdf")])
            self.assertEqual(0, status)
            new = {p.name for p in set(Path(tmp).iterdir()) - before}
            self.assertEqual({"diode.160906000001.H.mat"}, new)
        text = buf.getvalue()
        self.assertIn("shadow_diode (1-based): [61, 62, 63, 64]", text)
        self.assertIn("SPEC noisy-diode test", text)
        self.assertIn("diode_report:", text)
        self.assertIn("(lit-slice count per diode)", text)

    def _write_proc(self, tmp, bin_stats, stamp, position=((1, 100),) * 10):
        from netCDF4 import Dataset
        path = Path(tmp) / "proc.base160906000001.H.nc"
        with Dataset(path, "w", format="NETCDF4") as ds:
            ds.createDimension("time", None)
            ds.createDimension("pos_count", 2)
            ds.createDimension("bin_count", len(bin_stats))
            ds.createVariable("bin_stats", "i4", ("bin_count",))[:] = np.asarray(bin_stats)
            if position is not None:
                pos = np.asarray(position, dtype=np.int16)
                ds.createVariable("position", "i2", ("time", "pos_count"))[:pos.shape[0], :] = pos
        if stamp:
            path.with_name(path.name + ".call").write_text(stamp + "\n", encoding="utf-8")
        return path

    def _run(self, proc, *extra):
        import contextlib
        import io

        from arrayprobe import cli
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = cli.main(["diode-masks", "--proc", str(proc), "--no-write", *extra])
        return status, out.getvalue(), err.getvalue()

    def test_a_v35_shadow_count_finds_the_stuck_diode(self):
        # Ten particles of 100 slices: S = 1000.  Diode 60 is stuck dark (950 shadowed, 50 lit).
        shadow = np.full(128, 200)
        shadow[[0, 127]] = 100
        shadow[59] = 950
        with tempfile.TemporaryDirectory() as tmp:
            proc = self._write_proc(tmp, shadow, "engine=3.5 profile=stock-v3.5")
            status, text, _ = self._run(proc)
        self.assertEqual(0, status)
        self.assertIn("shadowed-slice count per diode, converted to lit", text)
        self.assertIn("shadow_diode (1-based): [60]", text)

    def test_the_same_counts_read_as_lit_flag_the_wrong_diodes(self):
        shadow = np.full(128, 200)
        shadow[[0, 127]] = 100
        shadow[59] = 950
        with tempfile.TemporaryDirectory() as tmp:
            proc = self._write_proc(
                tmp, shadow, "engine=3.1.4 profile=oracles-production channels=H")
            status, text, _ = self._run(proc)
        self.assertEqual(0, status)
        self.assertIn("(lit-slice count per diode)", text)
        self.assertNotIn("shadow_diode (1-based): [60]", text)

    def test_an_unstamped_file_without_a_profile_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = self._write_proc(tmp, np.full(128, 200), None)
            status, text, err = self._run(proc)
        self.assertEqual(2, status)
        self.assertIn("name the profile", err)
        self.assertNotIn("shadow_diode", text)

    def test_an_unparseable_name_needs_the_stamp_given(self):
        import contextlib
        import io

        from arrayprobe import cli
        with contextlib.redirect_stderr(io.StringIO()):
            status = cli.main(["diode-masks", "--proc",
                               str(DATA / "demo_flight_v314_proc.nc"), "--no-write"])
        self.assertEqual(2, status)


class Mutations(unittest.TestCase):
    """The comparison fails when the port is changed in a plausible way."""

    def _failing_cases(self) -> set[str]:
        failing = set()
        for name, case in CASES.items():
            with tempfile.TemporaryDirectory() as tmp:
                if _mismatches(case, Path(tmp)):
                    failing.add(name)
        return failing

    def test_a_true_nanmean_is_caught(self):
        def intended(a, idx, mean):
            a = a.copy()
            keep = np.ones(a.size, dtype=bool)
            keep[idx] = False
            a[idx] = np.int32(round(a[keep].mean()))
            return a
        with mock.patch.object(diode_mask, "_replace_high_counts", intended):
            failing = self._failing_cases()
        self.assertIn("mean_branch_nan_dilution", failing)
        self.assertIn("mean_branch_flags_the_high_diodes", failing)

    def test_the_75_percent_vintage_is_caught(self):
        with mock.patch.object(diode_mask, "STUCK_FRACTION", 0.75):
            failing = self._failing_cases()
        self.assertIn("max_branch_two_stuck", failing)

    def test_saving_the_empty_mask_under_the_loadable_name_is_caught(self):
        def upstream_suggestion(date, time, orientation, empty):   # F2's suggested edit
            return f"diode.{date}{time}.{orientation}.mat"
        with mock.patch.object(masks, "_saved_mask_filename", upstream_suggestion):
            failing = self._failing_cases()
        self.assertIn("flat_empty", failing)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
