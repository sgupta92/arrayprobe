# SPDX-License-Identifier: BSD-3-Clause
"""R3: a demo flight dense enough to move a threshold.

**Why this exists** (plan Part B, S3.1). The plain synthetic demo flight
(``arrayprobe.tools.make_demo_flight.build_demo_flight``, tracked by
``tests/test_demo_reference.py``) cannot test anything: its five particles
are 4x4-diode blobs whose ``image_diam_minR`` (0.048 mm) sits below the first
used bin's lower edge (0.055 mm), and every ``inter_arrival`` is identically
zero because each is the only particle of its record -- measured, S3.1 of
the plan. No reject or shattering threshold can ever move a used-bin count
on that flight. ``build_dense_demo_flight`` fixes both: disks (to fill
used bins), rings (to move the ``area_ratio_z`` threshold) and bars (to move
the ``max_comp_img_ar`` aspect-ratio threshold), plus a designed
particle-clock gap pattern (to move the inter-arrival/shattering threshold).

**All three thresholds are measured, not assumed**, against
``tests/data/demo_flight_dense_digest.json`` (seed 20260913, 20 seconds x 12
particles/second = 240 particles, written 2026-09-13 by running exactly the
calls this module runs). Two deviations from the plan's own draft, found by
measurement and recorded here rather than silently absorbed:

* **A true one-diode-wide ring outline lands at area ratio ~0.15 for every
  diameter tried** -- below BOTH ``area_ratio_z`` thresholds (0.2, 0.5),
  because the outline's area falls linearly with diameter while the
  normalising circle grows quadratically. ``ring_runs`` is a genuine annulus
  (``RING_HOLE_FRACTION=0.8``) instead, landing at area ratio 0.312 --
  between the two thresholds, as measured.
* **Bars, at aspect ratio 4.5, have their OWN area ratio (~0.28, an
  elongated rectangle's minR-normalised ratio is inherently low) already
  below ``ORACLES_REJECT`` (0.5).** Calling ``sizedist.run`` with the
  production default (``tree="production"``, which defaults to
  ``ORACLES_REJECT``) rejects every bar via ``area_ratio_z`` regardless of
  ``max_comp_img_ar`` -- measured 2026-09-13: the first version of this test
  showed a used-bin difference of exactly 0 across ``max_comp_img_ar`` 4 vs
  5, even though the S3 accept/reject code demonstrably changed. Passing
  ``reject=sizedist.STOCK_REJECT`` (0.2, below the bars' own ratio) for BOTH
  sides of that one comparison neutralises ``area_ratio_z`` so only the
  aspect-ratio ceiling decides them.

**Bars are also pinned to gap-safe record positions**
(``make_demo_flight._gap_safe_indices``): the shattering ladder flags both a
particle and its immediate predecessor when a gap is short, so a bar drawn
at an unsafe position would be rejected by shattering regardless of
``max_comp_img_ar`` -- the same kind of confound as the area-ratio one
above, found the same way (a measured, non-invented, exactly-zero diff).

**Timing, measured 2026-09-13**: the dense flight (240 particles) through
S2+S3 in ``setUpClass`` takes ~1-3 s; each of the five ``sizedist.run`` calls
across the test methods a few tenths of a second; the mutation test's own
full rebuild (flight + S2 + S3 + two S4 calls) a few seconds more. The whole
module measured 6-10 s end to end on this machine, well under the 60 s
budget asserted by ``test_z_whole_module_runs_under_the_60s_budget`` (named
to sort last, so it reports the module's actual cumulative wall time).

**The plan's own "mutation for this guard"**
(``test_the_gap_mutation_makes_the_iat_guard_fire``): collapsing
``DENSE_GAP_SHORT`` onto ``DENSE_GAP_LONG`` removes every *designed*
sub-threshold gap (the record-boundary reset at index 0 of each record still
fires, since that is a preserved bug independent of this module's own gap
values), so the inter-arrival threshold's used-bin difference collapses from
92 to a small residual -- confirmed by running it, not asserted from theory.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import netCDF4
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "scripts"
DATA = ROOT / "tests" / "data"

DIGEST = json.loads((DATA / "demo_flight_dense_digest.json").read_text())
TRACKED_RAW = DATA / "demo_flight_dense_raw.2DS"

_DEMO_SPEC = importlib.util.spec_from_file_location(
    "make_demo_flight", TOOLS / "make_demo_flight.py")
_RF_SPEC = importlib.util.spec_from_file_location("run_flight", TOOLS / "run_flight.py")

make_demo_flight = None
run_flight = None


def setUpModule():
    """Bind ``make_demo_flight``/``run_flight`` at RUN time, to whichever
    module object is already REGISTERED -- never a private copy.

    Same reasoning as ``tests/test_run_from_config.py``: ``discover`` imports
    every test module before running any, and another module may register
    ``sys.modules["run_flight"]`` while it *runs*, after this module was
    merely imported. Binding at import time would then hold a module this
    file's own calls never reach. Registering fresh only when nothing exists
    yet also means this module never silently patches a shared object
    (e.g. silencing ``run_flight.log``) without every later test seeing the
    same object.
    """
    global make_demo_flight, run_flight
    if _DEMO_SPEC.name in sys.modules:
        make_demo_flight = sys.modules[_DEMO_SPEC.name]
    else:
        make_demo_flight = importlib.util.module_from_spec(_DEMO_SPEC)
        sys.modules[_DEMO_SPEC.name] = make_demo_flight
        _DEMO_SPEC.loader.exec_module(make_demo_flight)
    if _RF_SPEC.name in sys.modules:
        run_flight = sys.modules[_RF_SPEC.name]
    else:
        run_flight = importlib.util.module_from_spec(_RF_SPEC)
        sys.modules[_RF_SPEC.name] = run_flight
        _RF_SPEC.loader.exec_module(run_flight)


from tests._repo import needs_v314_engine  # noqa: E402

from arrayprobe._v314_lazy import lazy_module  # noqa: E402

sizedist = lazy_module("arrayprobe.sizedist")
from arrayprobe.profiles import ORACLES_PRODUCTION  # noqa: E402
from arrayprobe.tools import make_demo_flight as _packaged_make_demo_flight  # noqa: E402


def _used_bin_sum(sd_path) -> float:
    """Sum of the sd file's ``count`` over used bins 6..128 (0-based 5:),
    the same convention ``scripts/make_demo_reference.py``'s digest uses."""
    with netCDF4.Dataset(str(sd_path)) as ds:
        count = np.asarray(ds.variables["count"][:])
        return float(np.nansum(count[:, 5:]))


@needs_v314_engine
class DenseFlightThresholdTests(unittest.TestCase):
    """One dense flight, built and decoded once in ``setUpClass``; each test
    method calls ``arrayprobe.sizedist.run`` directly (bypassing
    ``run_flight.stage4``, which hard-codes ``tree="production"`` with no way
    to vary ``reject=``) so exactly one threshold moves per comparison."""

    @classmethod
    def setUpClass(cls):
        cls._t0 = time.perf_counter()
        # Registered before any work: unittest skips tearDownClass when
        # setUpClass raises, but always runs class cleanups, so a failing
        # build cannot leave the shared run_flight's logger silenced.
        cls.addClassCleanup(setattr, run_flight, "log", run_flight.log)
        run_flight.log = lambda *a, **kw: None
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls._tmp.name)
        cls.raw = cls.out / "base160101000000.2DS"
        make_demo_flight.build_dense_demo_flight(
            cls.raw, n_seconds=DIGEST["n_seconds"],
            particles_per_second=DIGEST["particles_per_second"],
            seed=DIGEST["seed"], tas_mps=DIGEST["tas_mps"])
        cls.image = run_flight.stage2(cls.raw, cls.out)
        cls.proc = run_flight.stage3(cls.image, cls.out)
        tas_csv = cls.out / f"{cls.raw.stem}.tas.csv"
        cls.timehhmmss, cls.tas = run_flight.load_tas_info(tas_csv)
        cls.ddate = f"20{cls.raw.stem[4:10]} {cls.raw.stem[10:16]}"

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _run_sizedist(self, proc, out_path, *, iat_file, reject=None):
        """``sizedist.run`` with this class's fixed flight metadata, varying
        only ``proc``, the twelfth-argument call and ``reject``."""
        varargin = (iat_file,) if iat_file else ()
        kwargs = {} if reject is None else {"reject": reject}
        sizedist.run(
            str(proc), str(out_path), self.tas, np.floor(self.timehhmmss),
            run_flight.PROBE, run_flight.D_CHOICE, run_flight.SA_METHOD,
            np.full_like(self.tas, run_flight.PRES_PA),
            np.full_like(self.tas, run_flight.TEMP_C),
            run_flight.PROJECT, self.ddate, *varargin, tree="production", **kwargs)

    def test_dense_flight_has_the_expected_particle_count_all_above_bin_6(self):
        """The discriminating measurement for the whole of Part B (plan
        S3.2): if the S2 reader did not parse several image packets per
        record, ``time`` would be far fewer than
        ``n_seconds * particles_per_second``."""
        with netCDF4.Dataset(str(self.proc)) as ds:
            n = len(ds.dimensions["time"])
            diam_minr = np.asarray(ds.variables["image_diam_minR"][:])
        expected = DIGEST["n_seconds"] * DIGEST["particles_per_second"]
        self.assertEqual(n, expected)
        self.assertGreater(
            diam_minr.min(), 0.055,
            "a particle below the first used bin's lower edge cannot move "
            "any used-bin count -- exactly what the plain demo flight measures")

    def test_inter_arrival_threshold_moves_the_used_bin_count(self):
        with_iat = self.out / "sd_with_iat.nc"
        without_iat = self.out / "sd_without_iat.nc"
        self._run_sizedist(self.proc, with_iat, iat_file=run_flight.IAT_FILE)
        self._run_sizedist(self.proc, without_iat, iat_file="")
        with_sum = _used_bin_sum(with_iat)
        without_sum = _used_bin_sum(without_iat)
        self.assertEqual(with_sum, DIGEST["used_bin_sum_with_iat"])
        self.assertEqual(without_sum, DIGEST["used_bin_sum_without_iat"])
        diff = without_sum - with_sum
        self.assertGreater(diff, 0)
        self.assertEqual(diff, DIGEST["iat_rejected"])

    def test_area_ratio_z_threshold_moves_the_used_bin_count(self):
        oracles = self.out / "sd_oracles_reject.nc"
        stock = self.out / "sd_stock_reject.nc"
        self._run_sizedist(self.proc, oracles, iat_file=run_flight.IAT_FILE,
                           reject=sizedist.ORACLES_REJECT)
        self._run_sizedist(self.proc, stock, iat_file=run_flight.IAT_FILE,
                           reject=sizedist.STOCK_REJECT)
        oracles_sum = _used_bin_sum(oracles)
        stock_sum = _used_bin_sum(stock)
        self.assertEqual(oracles_sum, DIGEST["used_bin_sum_oracles_reject"])
        self.assertEqual(stock_sum, DIGEST["used_bin_sum_stock_reject"])
        diff = stock_sum - oracles_sum
        self.assertGreater(diff, 0)
        self.assertEqual(diff, DIGEST["rings_rejected_at_0_5"])

    def test_max_comp_img_ar_threshold_moves_the_used_bin_count(self):
        # S3 reads the module GLOBAL run_flight.PROFILE, so this rebinds it
        # for one extra S3 call and restores it via addCleanup immediately --
        # never leaving the shared module patched for a later test (the
        # exact hazard this test module's setUpModule docstring names).
        orig_profile = run_flight.PROFILE
        self.addCleanup(setattr, run_flight, "PROFILE", orig_profile)
        run_flight.PROFILE = dataclasses.replace(
            ORACLES_PRODUCTION,
            reject_thresholds=dataclasses.replace(
                ORACLES_PRODUCTION.reject_thresholds, max_comp_img_ar=5),
        )
        alt_out = Path(tempfile.mkdtemp(dir=self.out))
        proc_alt = run_flight.stage3(self.image, alt_out)
        run_flight.PROFILE = orig_profile

        # reject=STOCK_REJECT on BOTH sides: see the module docstring's first
        # deviation -- the bars' own area ratio (~0.28) is below
        # ORACLES_REJECT's 0.5, so the production default would reject every
        # bar via area_ratio_z regardless of max_comp_img_ar and this
        # comparison would measure nothing (found exactly that way,
        # 2026-09-13: a diff of 0 despite the S3 codes visibly differing).
        default_sd = self.out / "sd_max_comp_img_ar_4.nc"
        alt_sd = alt_out / "sd_max_comp_img_ar_5.nc"
        self._run_sizedist(self.proc, default_sd, iat_file=run_flight.IAT_FILE,
                           reject=sizedist.STOCK_REJECT)
        self._run_sizedist(proc_alt, alt_sd, iat_file=run_flight.IAT_FILE,
                           reject=sizedist.STOCK_REJECT)
        sum4 = _used_bin_sum(default_sd)
        sum5 = _used_bin_sum(alt_sd)
        self.assertEqual(sum4, DIGEST["used_bin_sum_max_comp_img_ar_4"])
        self.assertEqual(sum5, DIGEST["used_bin_sum_max_comp_img_ar_5"])
        diff = sum5 - sum4
        self.assertGreater(diff, 0)
        self.assertEqual(diff, DIGEST["bars_rejected_at_4"])

    def test_determinism_against_the_tracked_raw_fixture(self):
        a = self.out / "det_a.2DS"
        b = self.out / "det_b.2DS"
        for path in (a, b):
            make_demo_flight.build_dense_demo_flight(
                path, n_seconds=DIGEST["n_seconds"],
                particles_per_second=DIGEST["particles_per_second"],
                seed=DIGEST["seed"], tas_mps=DIGEST["tas_mps"])
        a_bytes = a.read_bytes()
        self.assertEqual(len(a_bytes), DIGEST["raw_size_bytes"])
        self.assertEqual(a_bytes, b.read_bytes(),
                         "two builds under the same seed must be byte-identical")
        self.assertEqual(a_bytes, TRACKED_RAW.read_bytes(),
                         "a fresh build no longer matches the tracked reference raw file")

    def test_the_gap_mutation_makes_the_iat_guard_fire(self):
        """The plan's own "mutation for this guard": collapse the short gap
        onto the long one and show the inter-arrival test's own signal
        collapses too -- without this, a shattering comparison that silently
        measured nothing would pass forever, the same failure mode
        ``tests/test_demo_reference.py::TheComparisonIsNotVacuous`` guards on
        the reference side."""
        with mock.patch.object(_packaged_make_demo_flight, "DENSE_GAP_SHORT",
                              _packaged_make_demo_flight.DENSE_GAP_LONG):
            mutated = Path(tempfile.mkdtemp(dir=self.out))
            raw = mutated / "base160101000000.2DS"
            make_demo_flight.build_dense_demo_flight(
                raw, n_seconds=DIGEST["n_seconds"],
                particles_per_second=DIGEST["particles_per_second"],
                seed=DIGEST["seed"], tas_mps=DIGEST["tas_mps"])
            image = run_flight.stage2(raw, mutated)
            proc = run_flight.stage3(image, mutated)
            with_iat = mutated / "sd_with.nc"
            without_iat = mutated / "sd_without.nc"
            self._run_sizedist(proc, with_iat, iat_file=run_flight.IAT_FILE)
            self._run_sizedist(proc, without_iat, iat_file="")
            mutated_diff = _used_bin_sum(without_iat) - _used_bin_sum(with_iat)
        self.assertLess(
            mutated_diff, DIGEST["iat_rejected"],
            f"collapsing DENSE_GAP_SHORT onto DENSE_GAP_LONG should sharply reduce "
            f"the inter-arrival threshold's effect ({mutated_diff} vs the "
            f"unmutated {DIGEST['iat_rejected']}); an unchanged value would mean "
            "this test measures nothing")

    def test_z_whole_module_runs_under_the_60s_budget(self):
        """Named to sort last (unittest's default per-class ordering is
        alphabetical by method name), so ``self._t0`` -- stamped at the very
        start of ``setUpClass`` -- covers the flight build, S2, S3 and every
        other test method's ``sizedist.run`` calls that ran before this one,
        including the mutation test's own full rebuild."""
        elapsed = time.perf_counter() - self._t0
        self.assertLess(
            elapsed, 60.0,
            f"the whole module took {elapsed:.1f} s, over the 60 s budget "
            "plan Part B sets for a dense-flight threshold test")
