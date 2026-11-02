# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe tune sample``: review queues drawn from a small synthetic proc file.

Pins the two queues (accepted codes only, every code), the per-bin cap and under-fill, that the
seed reproduces the draw, that only particles inside the given windows are drawn, the window
parsing (inline and from a file), and that the file written is one the triage server reads.
No test here reads a real flight file.
"""
from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import numpy as np

from arrayprobe import cli
from arrayprobe.triage_server import _load_queue_file, _review_queues
from arrayprobe.tune import sample

#: Windows used throughout: 10:00:00-10:00:59 and 11:00:00-11:00:09 (seconds of day).
WINDOWS = "36000-36059, 39600-39609"
IN_A, IN_B, OUT = 100030, 110009, 110010  # HHMMSS: in the first, last second of the second, out


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    code = None
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(argv)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def _write_proc(path: Path, t, d, code) -> Path:
    import netCDF4

    with netCDF4.Dataset(path, "w", format="NETCDF3_CLASSIC") as nc:
        nc.createDimension("Particle", len(t))
        nc.createVariable("Time", "i4", ("Particle",))[:] = np.asarray(t)
        nc.createVariable("image_diam_minR", "f4", ("Particle",))[:] = np.asarray(d)
        nc.createVariable("image_auto_reject", "i2", ("Particle",))[:] = np.asarray(code)
    return path


def _many(n_per_bin_in: int, n_out: int, seed: int = 0):
    """Particles in bin 0 (55-100 um) inside the windows, a few in bin 1, and some outside."""
    rng = np.random.default_rng(seed)
    t = np.r_[np.where(rng.random(n_per_bin_in) < 0.5, IN_A, IN_B), np.full(5, IN_A),
              np.full(n_out, OUT)]
    d = np.r_[rng.uniform(0.056, 0.099, n_per_bin_in), np.full(5, 0.15),
              rng.uniform(0.056, 0.099, n_out)]
    codes = np.full(t.size, ord("0"), np.int16)
    codes[1::7] = ord("a")  # a reject code every seventh particle
    return t, d, codes


class Windows(unittest.TestCase):

    def test_inline_pairs_parse_in_order(self):
        self.assertEqual(sample.read_windows(WINDOWS), ((36000, 36059), (39600, 39609)))

    def test_a_file_of_pairs_with_comments_parses(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "w.txt"
            f.write_text("# cold windows\n36000-36059\n39600-39609  # second\n",
                         encoding="utf-8")
            self.assertEqual(sample.read_windows(f), ((36000, 36059), (39600, 39609)))

    def test_bad_windows_are_refused(self):
        for text in ("36059-36000", "86000-86400", "no windows here"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                sample.parse_windows(text)

    def test_window_ends_are_included(self):
        sod = sample.hhmmss_to_sod([95959, 100000, 100059, 100100])
        self.assertEqual(sample.in_windows(sod, ((36000, 36059),)).tolist(),
                         [False, True, True, False])


class TheDraw(unittest.TestCase):

    def test_only_particles_inside_the_windows_are_drawn(self):
        t, d, code = _many(30, 50)
        windows = sample.parse_windows(WINDOWS)
        for codes in (sample.ACCEPTED_CODES, None):
            strata = sample.draw(t, d, code, windows=windows, per_bin=1000, accepted_codes=codes)
            picked = [i for s in strata for i in s["indices"]]
            self.assertTrue(picked)
            self.assertTrue(np.all(t[picked] != OUT))

    def test_per_bin_caps_each_bin_and_flags_under_fill(self):
        t, d, code = _many(200, 10)
        strata = sample.draw(t, d, code, windows=sample.parse_windows(WINDOWS), per_bin=12,
                             accepted_codes=None)
        self.assertEqual([s["taken"] for s in strata], [12, 5, 0, 0, 0])
        self.assertEqual([s["under_filled"] for s in strata], [False, True, True, True, True])
        self.assertEqual(strata[0]["available"], 200)

    def test_the_seed_reproduces_the_draw_and_another_seed_does_not(self):
        t, d, code = _many(200, 10)
        w = sample.parse_windows(WINDOWS)
        a = sample.draw(t, d, code, windows=w, per_bin=12, seed=7)
        b = sample.draw(t, d, code, windows=w, per_bin=12, seed=7)
        c = sample.draw(t, d, code, windows=w, per_bin=12, seed=8)
        self.assertEqual(a, b)
        self.assertNotEqual(a[0]["indices"], c[0]["indices"])

    def test_custom_edges_set_the_floor_and_the_bins(self):
        self.assertEqual(sample.bin_labels((0.1, 0.5, float("inf"))), ["100-500um", "500-infum"])
        with self.assertRaises(ValueError):
            sample.check_edges((0.1, 0.1, 0.5))

    def test_the_flight_comes_from_the_proc_name(self):
        self.assertEqual(sample.flight_from_proc_name("proc.base180215125340.H.nc"),
                         "base180215125340.H")


class TheCommand(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        t, d, code = _many(200, 10)
        self.cols = (t, d, code)
        self.proc = _write_proc(self.dir / "proc.base000000000000.H.nc", t, d, code)

    def _sample(self, *extra):
        out = self.dir / "queues" / "q.json"
        argv = ["tune", "sample", "--proc", str(self.proc), "--windows", WINDOWS,
                "--queue-out", str(out), "--route", "A (whole file)", *extra]
        return _run(argv), out

    def test_two_queues_load_in_the_triage_server(self):
        (code, stdout, err), out = self._sample("--per-bin", "12", "--seed", "7")
        self.assertEqual(code, 0, err)
        data = _load_queue_file(out)
        self.assertEqual(sorted(_review_queues(data)),
                         ["sample-accepted-n12-s7", "sample-all-n12-s7"])
        acc = data["sample-accepted-n12-s7"]
        self.assertTrue(all(i["flight"] == "base000000000000.H" for i in acc))
        t, d, codes = self.cols
        idx = [i["particle_index"] for i in acc]
        self.assertTrue(np.all(codes[idx] == ord("0")))
        cov = data["_coverage"]["sample-accepted-n12-s7"]
        self.assertEqual((cov["seed"], cov["per_bin"], cov["route"], cov["tool"]),
                         (7, 12, "A (whole file)", "arrayprobe tune sample"))
        self.assertEqual(cov["windows_s_of_day_inclusive"], [[36000, 36059], [39600, 39609]])
        self.assertEqual([s["taken"] for s in cov["strata"]], [12, 4, 0, 0, 0])  # 204 is 'a'
        all_cov = data["_coverage"]["sample-all-n12-s7"]
        self.assertEqual([s["taken"] for s in all_cov["strata"]], [12, 5, 0, 0, 0])
        self.assertEqual(cov["n_particles_in_windows"], 205)
        self.assertIn("sample-all-n12-s7", stdout)

    def test_the_command_matches_the_module_and_the_seed_reproduces(self):
        (code, _o, err), out = self._sample("--per-bin", "12", "--seed", "7")
        self.assertEqual(code, 0, err)
        first = out.read_text(encoding="utf-8")
        out.unlink()
        (code, _o, err), out = self._sample("--per-bin", "12", "--seed", "7")
        self.assertEqual(code, 0, err)
        self.assertEqual(out.read_text(encoding="utf-8"), first)
        queues, _cov = sample.build(self.proc.name, *self.cols, route="A (whole file)",
                                    flight="base000000000000.H",
                                    windows=sample.parse_windows(WINDOWS),
                                    queue_stem="sample", per_bin=12, seed=7)
        data = _load_queue_file(out)
        self.assertEqual(data["sample-all-n12-s7"], queues["sample-all-n12-s7"])

    def test_the_defaults_are_the_module_constants(self):
        (code, _o, err), out = self._sample()
        self.assertEqual(code, 0, err)
        cov = _load_queue_file(out)["_coverage"][f"sample-accepted-n{sample.PER_BIN}"
                                                 f"-s{sample.SEED}"]
        self.assertEqual(cov["size_edges_mm"][:-1], list(sample.SIZE_EDGES_MM[:-1]))
        self.assertEqual(cov["size_edges_mm"][-1], "inf")
        self.assertEqual(cov["accepted_codes"], sample.ACCEPTED_CODES)

    def test_size_edges_option_sets_the_bins(self):
        (code, _o, err), out = self._sample("--size-edges", "0.1", "0.2", "inf")
        self.assertEqual(code, 0, err)
        cov = _load_queue_file(out)["_coverage"]["sample-all-n40-s20260930"]
        self.assertEqual([s["bin"] for s in cov["strata"]], ["100-200um", "200-infum"])
        self.assertEqual(cov["strata"][0]["taken"], 5)

    def test_bad_windows_and_a_missing_proc_exit_2(self):
        (code, _o, err), _out = self._sample("--windows", "5-1")
        self.assertEqual(code, 2)
        self.assertIn("ends before it starts", err)
        code, _o, err = _run(["tune", "sample", "--proc", str(self.dir / "none.nc"),
                              "--windows", WINDOWS, "--queue-out", str(self.dir / "q.json")])
        self.assertEqual(code, 2)
        self.assertIn("no proc file", err)


if __name__ == "__main__":
    unittest.main()
