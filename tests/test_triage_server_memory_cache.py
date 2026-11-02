# SPDX-License-Identifier: BSD-3-Clause
"""The triage server holds each flight's index and the diode page's whole-file results once.

Triage-server memory incident, 2026-10-01 (44 GB on a 17.8M-particle flight). Remaining
per-request costs after the record-strip fix: the index sidecar was ``np.load``-ed on every
``/flight`` and ``/sheet`` request, concurrent first requests each built their own index, and the
diode page's inter-arrival and rate panels read the particle clock whole on every request.

Two sides, from different places: what is read or built is counted by patching the loader, the
builder and ``netCDF4.Dataset``; what is shown is compared with a verbatim copy of the old
panel code (``_old_*`` below) and with an uncached selection computed here.
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import netCDF4
import numpy as np

from arrayprobe import triage_server as ts


def _write_proc(path: Path, n: int, seed: int) -> None:
    rng = np.random.default_rng(seed)
    with netCDF4.Dataset(path, "w", format="NETCDF3_CLASSIC") as ds:
        ds.createDimension("pos_count", n)
        rc = ds.createVariable("image_auto_reject", "i2", ("pos_count",))
        rc[:] = rng.choice([48, 72, 97, 104], size=n)
        d = ds.createVariable("image_diam_minR", "f4", ("pos_count",))
        d[:] = rng.integers(1, 40, size=n).astype(np.float32) * np.float32(0.01)  # many ties
        sod = 43200 + np.sort(rng.uniform(0, 300, size=n))
        t = ds.createVariable("Time_in_seconds", "f8", ("pos_count",))
        t[:] = sod
        whole = np.floor(sod).astype(int)
        hh = ds.createVariable("Time", "f8", ("pos_count",))
        hh[:] = (whole // 3600) * 10000 + (whole % 3600 // 60) * 100 + whole % 60


def _old_selected(proc_path: Path, group: str) -> np.ndarray:
    """``_selected_particles`` as it computed before 2026-10-01, from a fresh read."""
    idx = ts._build_flight_index(proc_path)
    rc, diam = idx["reject_code"], idx["diam_minR"]
    if group == "accepted":
        idx_all = np.where(np.isin(rc, [ord(c) for c in "0HhuR"]))[0]
    elif group == "rejected":
        idx_all = np.where(~np.isin(rc, [ord(c) for c in "0HhuR"]))[0]
    else:
        idx_all = np.arange(len(rc))
    return idx_all[np.argsort(diam[idx_all])[::-1]]


def _old_intarr_panel(proc_path) -> list[str]:
    """``_intarr_panel`` as it was before 2026-10-01, kept verbatim as the reference."""
    from arrayprobe.intarr import bimodal_model
    from arrayprobe.intarr_analysis import HIST_BINS, block_thresholds, inter_arrival

    with netCDF4.Dataset(str(proc_path)) as ds:
        ds.set_auto_maskandscale(False)
        seconds = np.asarray(ds.variables["Time_in_seconds"][:]).reshape(-1)
    int_arr = inter_arrival(seconds)
    finite = int_arr[np.isfinite(int_arr)]
    counts, _ = np.histogram(finite, bins=HIST_BINS)
    centres = HIST_BINS[:-1] + np.diff(HIST_BINS) / 2
    threshold, ww, ak, tau = block_thresholds(counts)
    fitted = (None if tau is None or np.isnan(np.asarray(tau)).any()
              else bimodal_model(tau, centres))
    marks = [("2 x min(tau)", threshold), ("fit minimum", ww), ("observed minimum", ak)]
    body = [
        "<h2>Inter-arrival</h2>",
        f"<p class='muted'>{finite.size:,} finite gap(s) over the whole "
        f"file, as one population -- not the five blocks `sizeDist` uses, "
        f"so these thresholds describe the flight rather than reproducing "
        f"any run's own</p>",
        ts.render_intarr_svg(counts, centres, fitted, marks),
        "<p>" + "; ".join(f"{label} {value:.3g} s" for label, value in marks) + "</p>",
    ]
    if tau is not None and not np.isnan(np.asarray(tau)).any():
        body.append(f"<p class='muted'>tau = "
                    f"{', '.join(f'{t:.4g}' for t in np.asarray(tau))}</p>")
    return body


def _old_rate_panel(proc_path) -> list[str]:
    """``_rate_panel`` as it was before 2026-10-01 (no TAS sidecar in these fixtures)."""
    from arrayprobe.diagnostic_views import per_second_counts

    with netCDF4.Dataset(str(proc_path)) as ds:
        ds.set_auto_maskandscale(False)
        hhmmss = np.asarray(ds.variables["Time"][:]).reshape(-1).astype(float)
    seconds, counts = per_second_counts(hhmmss)
    return ["<h2>Particles per second</h2>",
            ts.render_rate_svg(seconds, counts, None, None)]


class _Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="triage_mem_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        for cache in ("_INDEX_CACHE", "_SELECTION_CACHE", "_PANEL_CACHE"):
            c = getattr(ts, cache, None)
            if c is not None:
                c.clear()
        self.procs = {}
        for k, name in enumerate(("fA", "fB", "fC")):
            p = self.tmp / f"proc.{name}.H.nc"
            _write_proc(p, 3000, seed=k)
            self.procs[name] = p


class TestFlightIndexHeldOnce(_Fixture):
    def test_concurrent_first_requests_build_the_index_once(self):
        real = ts._build_flight_index
        builds = []

        def slow_build(proc_path):
            builds.append(proc_path)
            time.sleep(0.3)  # widen the window in which the other threads arrive
            return real(proc_path)

        results, errors = [], []

        def worker():
            try:
                results.append(ts._flight_index(self.tmp, "fA", self.procs["fA"]))
            except Exception as exc:  # noqa: BLE001 -- reported below
                errors.append(exc)

        with mock.patch.object(ts, "_build_flight_index", slow_build):
            threads = [threading.Thread(target=worker) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(30)
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 4)
        self.assertEqual(len(builds), 1, f"{len(builds)} builds for 4 concurrent first requests")

    def test_second_request_does_not_load_the_sidecar_again(self):
        ts._selected_particles(self.tmp, "fA", self.procs["fA"], "accepted")
        real_load = np.load
        loads = []

        def counting_load(*a, **k):
            loads.append(a)
            return real_load(*a, **k)

        with mock.patch("numpy.load", counting_load):
            for group in ("accepted", "rejected", "all", "accepted"):
                ts._selected_particles(self.tmp, "fA", self.procs["fA"], group)
                ts._flight_index(self.tmp, "fA", self.procs["fA"])
        self.assertEqual(loads, [], "a /flight or /sheet request re-read the index sidecar")

    def test_selection_is_identical_to_the_uncached_computation(self):
        for group in ("accepted", "rejected", "all"):
            for _ in range(2):  # the cold call and the held one
                got = ts._selected_particles(self.tmp, "fA", self.procs["fA"], group)
                np.testing.assert_array_equal(got, _old_selected(self.procs["fA"], group))
        idx = ts._flight_index(self.tmp, "fA", self.procs["fA"])
        built = ts._build_flight_index(self.procs["fA"])
        np.testing.assert_array_equal(idx["reject_code"], built["reject_code"])
        np.testing.assert_array_equal(np.asarray(idx["diam_minR"], dtype=np.float64),
                                      built["diam_minR"])

    def test_the_cache_holds_at_most_two_flights(self):
        for name in ("fA", "fB", "fC"):
            ts._flight_index(self.tmp, name, self.procs[name])
        self.assertLessEqual(len(ts._INDEX_CACHE), 2)
        held = {k[0] for k in ts._INDEX_CACHE.keys()}
        self.assertNotIn(str(self.procs["fA"]), held, "the least recently used flight was kept")

    def test_a_deleted_sidecar_still_forces_a_rebuild(self):
        ts._flight_index(self.tmp, "fA", self.procs["fA"])
        ts._index_path(self.tmp, "fA").unlink()
        builds = []
        real = ts._build_flight_index
        with mock.patch.object(ts, "_build_flight_index",
                               lambda p: builds.append(p) or real(p)):
            ts._flight_index(self.tmp, "fA", self.procs["fA"])
        self.assertEqual(len(builds), 1)


class TestDiodePanelsReadOncePerFile(_Fixture):
    def _count_opens(self):
        real = netCDF4.Dataset
        opens = []

        def counting(*a, **k):
            opens.append(a)
            return real(*a, **k)

        return opens, mock.patch.object(netCDF4, "Dataset", counting)

    def test_intarr_panel_second_request_reads_nothing_and_matches_old(self):
        proc = self.procs["fB"]
        first = ts.TriageServer._intarr_panel(None, proc)
        opens, patch = self._count_opens()
        with patch:
            second = ts.TriageServer._intarr_panel(None, proc)
        self.assertEqual(opens, [], "the inter-arrival panel re-read the particle clock")
        self.assertEqual(first, _old_intarr_panel(proc))
        self.assertEqual(second, first)

    def test_rate_panel_second_request_reads_nothing_and_matches_old(self):
        proc = self.procs["fB"]
        first = ts.TriageServer._rate_panel(None, "fB", proc)
        opens, patch = self._count_opens()
        with patch:
            second = ts.TriageServer._rate_panel(None, "fB", proc)
        self.assertEqual(opens, [], "the rate panel re-read the particle clock")
        self.assertEqual(first, _old_rate_panel(proc))
        self.assertEqual(second, first)


if __name__ == "__main__":
    unittest.main()
