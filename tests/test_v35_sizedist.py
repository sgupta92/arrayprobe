# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe_uiops.sizedist``: the record/second loop, the
netCDF writer, and the ``iat_threshold`` output variable.

Two Octave-generated fixtures back this suite:

* ``tests/data/v35_sizedist_driver_oracle.json`` -- pure blocks sliced out of
  the vendored v3.5 source and ``eval``-ed under Octave with free variables
  bound per case (``run_v35_sizedist_driver_bank.py``): the multi-day
  particle-time fix, the flight-day carryover, one-second block resolution,
  the overload dead-time cap, the ``area_ratio`` clip, and a
  file-I/O-excluded slice of the type-1/type-2 shattering ladders.
* ``tests/data/v35_sizedist_shatter_oracle.json`` -- the type-1 (real
  threshold **file**) and type-2 (per-second scalar) shattering gates in
  full, including the file read, plus the ``area_ratio`` clamp again from a
  different case grid (``run_v35_sizedist_shatter_bank.py``).
* ``tests/data/v35_sizedist/*.nc`` -- four END-TO-END runs of the real,
  unmodified v3.5 ``sizeDist.m`` over the same small real 2D-S proc fixture
  S4's own v3.1.4 oracle uses (``run_v35_sizedist_bank.py``), against which
  :func:`arrayprobe_uiops.sizedist.run` is compared variable-for-variable.

Oracle layer 2 only throughout: no archived product was ever written by
v3.5, so nothing here has layer-1 validation.


"""

from __future__ import annotations

import json
import math
import shutil
import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np
from tests import _upstream  # noqa: E402
from tests._repo import needs_v314_engine, repo_only

from arrayprobe import ncio
from arrayprobe_uiops import sizedist as v35s
from arrayprobe_uiops.sizedist_tables import (
    InterarrivalThresholdSpec,
    ProbeDefaults,
    reaccept_shattered_1hz,
)

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
ROOT = HERE.parent
V35_SIZEDIST = _upstream.source("uiops35") / "sizeDist.m"

if not (DATA / "v35_sizedist_driver_oracle.json").is_file():
    raise unittest.SkipTest(
        "The sizeDist oracle files is not distributed with the package")

with (DATA / "v35_sizedist_driver_oracle.json").open(encoding="utf-8") as fh:
    DFX = json.load(fh)
with (DATA / "v35_sizedist_shatter_oracle.json").open(encoding="utf-8") as fh:
    SFX = json.load(fh)

PROC_FIXTURE = DATA / "v35_sizedist_synthetic.proc.nc"
SIZEDIST_DIR = DATA / "v35_sizedist"

#: The same TAS/time series ``run_v35_sizedist_bank.py`` used to build the
#: four end-to-end goldens -- one second (164130) above the 2D-S ``tasMax``
#: of 170 to reach the area-reconstruction branch.
TAS = np.array([170.0, 170.0, 180.0, 170.0, 170.0, 170.0])
TIMES = np.array([120001.0, 120002.0, 120003.0, 120004.0, 120005.0, 120006.0])
PRES = np.full(6, 9e5)
TEMP = np.full(6, 15.0)
DDATE = "20151205 120002"
SOFTWARE = "UIOOPS_v3.5"
CREATION_TIME = "2026/09/12 01:19:41"

#: A minimal :class:`ProbeDefaults` for :func:`apply_shattering`'s own tests
#: -- only the fields that function reads matter; the rest describe a
#: plausible 2D-S-shaped probe so a stray read elsewhere does not explode.
def setUpModule():
    # Raised here rather than at import: an import-time SkipTest crashes
    # ``python -m unittest tests.<module>``, where ``discover`` reports it as a skip.
    _upstream.require("uiops35")


def _cfg(*, apply_int_arr_thresh, default_int_arr_thresh=1e-6, reaccpt_shatrs,
         reaccpt_d=0.5, reaccpt_max_ia=1e-6):
    return ProbeDefaults(
        num_diodes=128, diodesize=0.010, armdst=63.0, num_bins=22,
        bins=_dummy_bins(),
        probetype=2, tasMax=170.0,
        applyIntArrThresh=int(apply_int_arr_thresh),
        defaultIntArrThresh=default_int_arr_thresh,
        reaccptShatrs=int(reaccpt_shatrs),
        reaccptD=reaccpt_d, reaccptMaxIA=reaccpt_max_ia,
        intar_threshold_defaulted=True,
    )


def _dummy_bins():
    from arrayprobe_uiops.sizedist_tables import BinLadder
    return BinLadder()


def _build_threshold_nc(path: Path, values: list[float]) -> None:
    """A minimal ``threshold(Time)`` netCDF file, matching what
    ``run_v35_sizedist_shatter_bank.py``'s Octave harness writes for the
    type-1 gate's own file read."""
    f = ncio.create(str(path), "clobber")
    dim = f.def_dim("Time", len(values))
    vid = f.def_var("threshold", "double", [dim])
    f.end_def()
    f.put_var(vid, np.asarray(values, dtype=np.float64))
    f.close()


@repo_only
class TestTheOracleRanTheVendoredSource(unittest.TestCase):
    """Both fixtures re-slice the vendored file and must still match --
    guards against a future re-vendor silently invalidating either golden."""

    def test_driver_oracle_blocks_still_match(self):
        import sys
        sys.path.insert(0, str(HERE.parent / "scripts" / "validation" / "octave"))
        import run_v35_sizedist_driver_bank as bank
        for name, extractor in (
            ("type1", bank.extract_type1_block),
            ("type2", bank.extract_type2_block),
            ("multiday", bank.extract_multiday_block),
            ("carryover", bank.extract_carryover_block),
            ("blockres", bank.extract_blockres_block),
            ("deadtime", bank.extract_deadtime_block),
            ("arearatio", bank.extract_arearatio_block),
        ):
            with self.subTest(block=name):
                self.assertEqual(extractor(V35_SIZEDIST)["text"], DFX["blocks"][name]["text"])

    def test_shatter_oracle_blocks_still_match(self):
        import sys
        sys.path.insert(0, str(HERE.parent / "scripts" / "validation" / "octave"))
        import run_v35_sizedist_shatter_bank as bank
        for name, extractor in (
            ("type1_v35", bank.extract_type1_block),
            ("type2_v35", bank.extract_type2_block),
            ("area_ratio_v35", bank.extract_area_ratio_block),
        ):
            with self.subTest(block=name):
                self.assertEqual(extractor(V35_SIZEDIST)["text"], SFX["blocks"][name]["text"])


class TestFixMultidayParticleTimes(unittest.TestCase):
    def test_against_octave(self):
        for name, times in DFX["multiday_cases"].items():
            with self.subTest(case=name):
                got, _ = v35s.fix_multiday_particle_times(np.asarray(times, dtype=np.float64))
                np.testing.assert_allclose(got, DFX["multiday"][name]["image_time_hhmmssall"])

    def test_crossover_applied_flag(self):
        # v3.5's own comment names this "modified 02/13/19 to ignore corrupt
        # particle boundary times" -- the flag distinguishes a real shift
        # from the "printed a diagnostic, changed nothing" path.
        x, applied = v35s.fix_multiday_particle_times(
            np.array(DFX["multiday_cases"]["two_decreases_no_crossover"], dtype=np.float64)
        )
        self.assertFalse(applied)
        x2, applied2 = v35s.fix_multiday_particle_times(
            np.array(DFX["multiday_cases"]["one_decrease_midnight"], dtype=np.float64)
        )
        self.assertTrue(applied2)


class TestApplyFlightDayCarryover(unittest.TestCase):
    """A particle-time correction found only by reading past
    :func:`fix_multiday_particle_times`'s own block rather than trusting the
    2026-09-10 diff-read summary that first named this stage. **Not a v3.5
    finding**: this exact block is byte-identical in v3.1.4
    (``sizeDist.m:661-664``, same three lines, same comment) -- what is
    actually missing is the v3.1.4 PYTHON PORT's own implementation of it
    (``arrayprobe.sizedist`` has no code for this second, independent ``if``
    at all). See ``test_present_in_v314_source_but_missing_from_the_v314_port``."""

    def test_against_octave(self):
        for name, case in DFX["carryover_cases"].items():
            with self.subTest(case=name):
                got = v35s.apply_flight_day_carryover(
                    np.asarray(case["image_time_hhmmssall"], dtype=np.float64),
                    np.asarray(case["timehhmmss"], dtype=np.float64),
                )
                np.testing.assert_allclose(got, DFX["carryover"][name]["image_time_hhmmssall"])

    @repo_only
    @needs_v314_engine
    def test_present_in_v314_source_but_missing_from_the_v314_port(self):
        from arrayprobe import sizedist as v314

        _upstream.require("uiops314")
        v314_lines = (
            _upstream.source("uiops314") / "sizeDist.m"
        ).read_text(encoding="utf-8", errors="replace").splitlines()
        anchor = (
            "if (numel(find(timehhmmss>240000))>0) && "
            "(numel(find(image_time_hhmmssall>240000))==0)"
        )
        self.assertTrue(
            any(ln.strip() == anchor for ln in v314_lines),
            "v3.1.4 no longer carries this block -- the docstring's correction is stale",
        )
        import inspect
        self.assertNotIn("apply_flight_day_carryover", inspect.getsource(v314))

    def test_runs_unconditionally_after_the_multiday_fix_in_run(self):
        # Regression for the exact gap this stage found and closed:
        # apply_flight_day_carryover was written and tested in isolation
        # before it was ever wired into _run's own particle-time pipeline.
        import inspect
        src = inspect.getsource(v35s._run)
        multiday_pos = src.index("fix_multiday_particle_times(")
        carryover_pos = src.index("apply_flight_day_carryover(")
        self.assertLess(multiday_pos, carryover_pos)


class TestResolveParticleBlocks(unittest.TestCase):
    def test_against_octave(self):
        for name, case in DFX["blockres_cases"].items():
            with self.subTest(case=name):
                starttime, start_all, count_all = v35s.resolve_particle_blocks(
                    np.asarray(case["image_time_hhmmssall"], dtype=np.float64),
                    int(case["num_of_part"]),
                )
                oracle = DFX["blockres"][name]
                np.testing.assert_allclose(starttime, oracle["starttime"])
                np.testing.assert_array_equal(start_all, oracle["start_all"])
                np.testing.assert_array_equal(count_all, oracle["count_all"])

    def test_corrupt_removal_can_drop_every_block(self):
        # out_of_order_leading_block_dropped: the filter finds no genuinely
        # contiguous run at all, so every block is dropped -- MEASURED, not
        # a hypothetical. A caller reaching `_run`'s main loop on this input
        # would index an empty `starttime`, exactly as real MATLAB would
        # index an empty array the same way -- not guarded, by design --
        # the crash is reproduced.
        oracle = DFX["blockres"]["out_of_order_leading_block_dropped"]
        self.assertEqual(oracle["start_all"], [])

    def test_sizeDist_845_859_last_time_sorted_block_is_never_examined(self):
        # Preserved bug, UIOOPS v3.5 sizeDist.m:845-859. The corrupt-time
        # filter runs `while k < n-1`, so the LAST block in time order is
        # never tested and always dropped, however clean; and a block is kept
        # only when the NEXT one in file order follows it, so a clean block
        # sitting just before a corrupt one is dropped too. Expected values
        # are the Octave run of the unmodified v3.5 lines.
        #
        #
        seconds = ([100000] * 2 + [100001] * 3 + [100002] + [95000]
                   + [100003] * 2 + [100004] * 4)
        starttime, start_all, count_all = v35s.resolve_particle_blocks(
            np.asarray(seconds, dtype=np.float64), len(seconds))
        np.testing.assert_array_equal(starttime, [100000, 100001, 100003])
        np.testing.assert_array_equal(start_all, [0, 2, 7])
        np.testing.assert_array_equal(count_all, [2, 3, 2])
        self.assertEqual(int(np.sum(count_all)), 7)  # 7 of 13 kept
        # Loss 1: the last second in time order (100004, 4 clean particles).
        self.assertNotIn(100004, starttime)
        # Loss 2: 100002 (1 clean particle) precedes the corrupt 095000
        # block in file order, so its file-order successor test fails.
        self.assertNotIn(100002, starttime)
        # The corrupt second itself is gone.
        self.assertNotIn(95000, starttime)


class TestOverloadDeadTime(unittest.TestCase):
    def test_against_octave(self):
        for name, case in DFX["deadtime_cases"].items():
            if name == "not_probetype_2":
                continue  # overload_dead_time IS the probetype==2 formula; see its own test below
            with self.subTest(case=name):
                got = v35s.overload_dead_time(
                    np.asarray(case["int_arr"], dtype=np.float64),
                    np.asarray(case["overload"], dtype=np.float64),
                )
                self.assertAlmostEqual(got, DFX["deadtime"][name]["time_interval72"])

    @needs_v314_engine
    def test_probetype_gate_lives_in_run_not_in_this_function(self):
        from arrayprobe import sizedist as v314

        # "not_probetype_2" in the oracle shows the RAW sum (1.8) reaching
        # the file uncapped for any other probetype -- this module supports
        # probetype 2 only (see the module docstring's Scope), so
        # overload_dead_time IS that formula unconditionally, and the branch
        # that would skip it for another probetype does not exist here.
        raw_sum = float(
            v314.msum(
                np.array(DFX["deadtime_cases"]["not_probetype_2"]["int_arr"])[
                    np.array(DFX["deadtime_cases"]["not_probetype_2"]["overload"]) != 0
                ]
            )
        )
        self.assertEqual(DFX["deadtime"]["not_probetype_2"]["time_interval72"], raw_sum)


class TestClipAreaRatio(unittest.TestCase):
    def test_against_driver_oracle(self):
        for name, case in DFX["arearatio_cases"].items():
            with self.subTest(case=name):
                area = np.asarray(case["area"], dtype=np.float64)
                diam = np.asarray(case["diam"], dtype=np.float64)
                with np.errstate(divide="ignore", invalid="ignore"):
                    raw = area / (np.pi / 4 * diam ** 2)
                got = v35s.clip_area_ratio(raw)
                np.testing.assert_allclose(got, [DFX["arearatio"][name]["area_ratio"]])

    def test_against_shatter_oracle(self):
        for name, case in SFX["area_ratio_cases"].items():
            with self.subTest(case=name):
                diam = case["diam"]
                area = (np.pi / 4) * diam ** 2 if case["area"] is None else case["area"]
                with np.errstate(divide="ignore", invalid="ignore"):
                    raw = np.array([area / (np.pi / 4 * diam ** 2)])
                got = v35s.clip_area_ratio(raw)
                oracle = SFX["area_ratio"][name]["area_ratio"]
                if oracle is None:  # Octave's jsonencode writes NaN as JSON null
                    self.assertTrue(np.isnan(got[0]))
                else:
                    np.testing.assert_allclose(got, [oracle])

    def test_only_clips_downward_never_up(self):
        out = v35s.clip_area_ratio(np.array([0.3, 1.5, np.nan]))
        np.testing.assert_allclose(out[:2], [0.3, 1.0])
        self.assertTrue(np.isnan(out[2]))


class TestDChoiceDiameterFindingV23(unittest.TestCase):
    """v3.5's own ``double(netcdf.getVar(...))`` cast (:938-939) removes the
    preserved int16xdouble saturation the v3.1.4 port documents as "A2" --
    measured here by ARITHMETIC (the effect is dtype promotion, which needs
    no MATLAB/Octave run to demonstrate) rather than by a fresh Octave case,
    since the claim is about which dtype reaches a shared, already-tested
    formula."""

    @needs_v314_engine
    def test_int16_input_saturates_via_v314s_own_function(self):
        from arrayprobe import sizedist as v314
        im_length = np.array([20000], dtype=np.int16)
        diodesize = 2.0  # forces int16*double MATLAB-compat saturation at 32767
        saturated = v314._d_length(im_length, im_length, diodesize, None)
        self.assertLess(saturated[0], 20000 * diodesize)  # collapsed toward int16 max

    def test_v35_double_cast_removes_the_saturation(self):
        im_length = np.array([20000], dtype=np.int16)
        diodesize = 2.0
        got = v35s.d_choice_diameter(1, im_length, im_length, diodesize, None)
        self.assertAlmostEqual(got[0], 20000 * diodesize)

    def test_d_choice_6_unaffected_either_way(self):
        minr = np.array([1.23])
        got = v35s.d_choice_diameter(6, np.array([1], dtype=np.int16),
                                      np.array([1], dtype=np.int16), 0.01, minr)
        np.testing.assert_allclose(got, minr)

    def test_rejects_unknown_d_choice(self):
        with self.assertRaises(ValueError):
            v35s.d_choice_diameter(7, np.array([1.0]), np.array([1.0]), 0.01, None)


class TestAreaRDiameterFindingV24(unittest.TestCase):
    """v3.5 comments out the second ``* diodesize`` scale entirely --
    the v3.1.4 port's own double-scaling defect, which the module docstring
    there measures as making ``conc_AreaR`` identically zero wherever
    finite. Identity function; the assertion is that it stays one."""

    def test_is_the_identity(self):
        raw = np.array([0.1, 0.25, np.nan])
        np.testing.assert_array_equal(v35s.area_r_diameter(raw), raw)

    def test_v314_would_have_rescaled_this(self):
        # Demonstrates what the removed line WOULD have done, so the "no
        # longer reproduces" claim is a comparison, not an assertion.
        raw = np.array([0.1])
        diodesize = 0.010
        v314_rescaled = raw * diodesize
        self.assertFalse(np.allclose(v35s.area_r_diameter(raw), v314_rescaled))


class TestApplyShatteringType1(unittest.TestCase):
    """v3.5 ``:1213`` -- reuses :func:`arrayprobe.sizedist._reaccept_shattered`
    (the v3.1.4-preserved-bug reacceptance), validated here against a REAL
    threshold netCDF file, matching what the type-1 gate actually reads."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_against_octave(self):
        for name, case in SFX["type1_cases"].items():
            oracle = SFX["type1"][name]
            with self.subTest(case=name):
                thresh_path = Path(self._tmp.name) / f"{name}.nc"
                n = len(case["int_arr"])
                _build_threshold_nc(thresh_path, [case["thresh"]] * n)
                cfg = _cfg(apply_int_arr_thresh=True, reaccpt_shatrs=case["reaccpt"],
                           reaccpt_d=case["reaccptD"], reaccpt_max_ia=case["reaccptMaxIA"])
                spec = InterarrivalThresholdSpec(
                    ia_thresh_file=str(thresh_path), iat_thresh=None, too_many_inputs=False
                )
                auto_reject = np.array([ord("A")] * n, dtype=np.uint8)
                got = v35s.apply_shattering(
                    ia_thresh_type=1, cfg=cfg, spec=spec, i=0, auto_reject=auto_reject,
                    int_arr=np.asarray(case["int_arr"]), int_arr2=None,
                    int_arr3=np.asarray(case["int_arr3"]),
                    particle_diameter_minR=np.asarray(case["diam"]),
                    start=0, count=n,
                )
                got_str = "".join(chr(c) for c in got)
                self.assertEqual(got_str, oracle["auto_reject"])

    def test_gate_closed_without_apply_int_arr_thresh(self):
        cfg = _cfg(apply_int_arr_thresh=False, reaccpt_shatrs=False)
        spec = InterarrivalThresholdSpec(
            ia_thresh_file="NONE", iat_thresh=None, too_many_inputs=False
        )
        auto_reject = np.array([ord("A")], dtype=np.uint8)
        got = v35s.apply_shattering(
            ia_thresh_type=1, cfg=cfg, spec=spec, i=0, auto_reject=auto_reject,
            int_arr=np.array([1e-9]), int_arr2=None, int_arr3=np.array([1e-9]),
            particle_diameter_minR=np.array([0.5]), start=0, count=1,
        )
        self.assertEqual(chr(got[0]), "A")  # untouched -- gate never opened


class TestApplyShatteringType2(unittest.TestCase):
    """v3.5 ``:1346`` -- the other D3-preserving loop; a per-second scalar
    threshold, not a file, and the ONLY gate with the ``int_arr2``
    next-second-burst check."""

    def test_against_octave(self):
        for name, case in SFX["type2_cases"].items():
            oracle = SFX["type2"][name]
            with self.subTest(case=name):
                n = len(case["int_arr"])
                cfg = _cfg(apply_int_arr_thresh=True, default_int_arr_thresh=case["thresh"],
                           reaccpt_shatrs=case["reaccpt"], reaccpt_d=case["reaccptD"],
                           reaccpt_max_ia=case["reaccptMaxIA"])
                spec = InterarrivalThresholdSpec(ia_thresh_file=None, iat_thresh=None,
                                                  too_many_inputs=False)
                int_arr2 = (
                    np.asarray(case["int_arr2"], dtype=np.float64)
                    if case.get("int_arr2") else np.array([])
                )
                auto_reject = np.array([ord("A")] * n, dtype=np.uint8)
                got = v35s.apply_shattering(
                    ia_thresh_type=2, cfg=cfg, spec=spec, i=1, auto_reject=auto_reject,
                    int_arr=np.asarray(case["int_arr"]), int_arr2=int_arr2,
                    int_arr3=np.asarray(case["int_arr3"]),
                    particle_diameter_minR=np.asarray(case["diam"]),
                    start=0, count=n,
                )
                got_str = "".join(chr(c) for c in got)
                self.assertEqual(got_str, oracle["auto_reject"])


class TestThreeLoopsTwoBehaviours(unittest.TestCase):
    """**The trap this stage exists to avoid, made explicit as a test.**

    v3.5's ``sizeDist.m`` carries three structurally similar shattering
    loops. Type 1 (``:1213``) and type 2 (``:1346``) both scan
    ``find(rBegin):find(rEnd)`` -- collapsed by MATLAB's first-element colon
    rule to the FIRST shattering event, the v3.1.4-preserved bug this
    project already names at ``sizeDist.m:1036``/``:1169``. Type 3
    (``:1416-1419``, "JF 11/5/25") was deliberately rewritten to scan
    ``rBeginIdx:rEndIdx`` -- one bracket spanning EVERY event. On the SAME
    two-event second, the three must not agree.
    """

    TWO_EVENT = SFX["type1_cases"]["reaccept_two_events_spanned"]

    def test_type1_and_type2_use_the_v314_preserved_bug_reaccept_shattered(self):
        oracle1 = SFX["type1"]["reaccept_two_events_spanned"]
        oracle2 = SFX["type2"]["reaccept_two_events_spanned"]
        # Both real-MATLAB runs reaccept index 3 (1-based) -- the FIRST
        # event only, exactly as the preserved-bug idiom predicts.
        self.assertEqual(oracle1["eIndex"], [3])
        self.assertEqual(oracle2["eIndex"], [3])

    def test_type3_uses_the_fixed_bracketed_reaccept(self):
        # The ``sizedist_tables`` oracle bank ran this exact case (same int_arr/int_arr3/
        # diam/thresh) through the type-3 block and measured index 6
        # (1-based) reaccepted -- the SECOND event, unreachable by type 1/2's
        # own `find(rBegin):find(rEnd)` collapse.
        with (DATA / "v35_sizedist_tables_oracle.json").open(encoding="utf-8") as fh:
            v7a_fx = json.load(fh)
        t3 = v7a_fx["type3"]["reaccept_two_events_spanned"]
        self.assertEqual(t3["eIndex"], [6])

    def test_the_two_conventions_differ_on_the_same_second(self):
        c = self.TWO_EVENT
        chars_start = np.array(["A"] * len(c["int_arr"]))
        # type-1/2 convention, via ``sizedist_tables``' own reaccept function called with the
        # OLD collapsed range (what _reaccept_shattered implements) --
        # cross-checked directly against the real Octave result already
        # asserted above (index 3, 1-based -> 0-based 2).
        old_e_index = SFX["type1"]["reaccept_two_events_spanned"]["eIndex"][0] - 1
        # type-3 convention:
        _chars3, e_index3 = reaccept_shattered_1hz(
            chars_start.tolist(), c["int_arr"], c["int_arr3"], c["diam"], c["thresh"],
            reaccptD=0.5, reaccptMaxIA=1e-6,
        )
        self.assertNotEqual(old_e_index, e_index3 - 1)
        self.assertEqual(old_e_index, 2)
        self.assertEqual(e_index3, 6)


class TestWriterGaps(unittest.TestCase):
    def test_deflate_is_declared(self):
        self.assertIn("deflate", v35s.WRITER_GAPS)

    def test_deflate_changes_no_value_that_is_read_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            plain = Path(tmp) / "plain.nc"
            deflated = Path(tmp) / "deflated.nc"
            data = np.linspace(0, 1, 50)
            for path, use_zlib in ((plain, False), (deflated, True)):
                ds = netCDF4.Dataset(path, "w")
                ds.createDimension("x", len(data))
                v = ds.createVariable(
                    "v", "f8", ("x",), zlib=use_zlib, complevel=9 if use_zlib else 0
                )
                v[:] = data
                ds.close()
            with netCDF4.Dataset(plain) as a, netCDF4.Dataset(deflated) as b:
                np.testing.assert_array_equal(a.variables["v"][:], b.variables["v"][:])


class TestScopeRefusals(unittest.TestCase):
    def test_probetypes_0_and_3_are_admitted(self):
        """Probetypes 0 (2DC/2DP) and 3 (F2DC) pass the gate since 2026-09-23.

        This test pinned their refusal until they were ported; their numbers are asserted
        against Octave in ``test_v35_sizedist_probetype03.py``. Here only the gate is pinned:
        whatever else this 2D-S fixture makes them do, it is not ``UnsupportedProbetype``.
        """
        for probename in ("2DC", "F2DC"):
            with self.subTest(probename=probename), tempfile.TemporaryDirectory() as tmp:
                try:
                    v35s.run(
                        str(PROC_FIXTURE), str(Path(tmp) / "out.nc"), TAS, TIMES,
                        probename, 6, 0, PRES, TEMP, 0, 0, 1, 1, "otherwise",
                        DDATE, software=SOFTWARE,
                    )
                except v35s.UnsupportedProbetype as exc:  # pragma: no cover
                    self.fail(f"{probename} refused at the probetype gate: {exc}")
                except Exception:  # noqa: BLE001, S110 -- fixture mismatch past the gate
                    pass

    def test_pecan_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(NotImplementedError):
                v35s.run(
                    str(PROC_FIXTURE), str(Path(tmp) / "out.nc"), TAS, TIMES,
                    "CIP", 6, 0, PRES, TEMP, 0, 0, 1, 1, "PECAN", DDATE,
                    software=SOFTWARE,
                )

    def test_bad_ia_thresh_type_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                v35s.run(
                    str(PROC_FIXTURE), str(Path(tmp) / "out.nc"), TAS, TIMES,
                    "2DS", 6, 0, PRES, TEMP, 4, 0, 1, 1, "ORACLES", DDATE,
                    software=SOFTWARE,
                )

    def test_save_workspace_mat_not_a_parameter(self):
        # Unlike arrayprobe.sizedist.run, this module never offers
        # save_workspace_mat at all -- v3.5's own :826/:2450 whole-workspace
        # dumps are simply not reachable through this driver's signature.
        import inspect
        self.assertNotIn("save_workspace_mat", inspect.signature(v35s.run).parameters)


class TestReuseIsNotAccidental(unittest.TestCase):
    """Everything the v3.1.4->v3.5 diff proves unchanged is imported, not
    re-transcribed -- the same pattern the ``spec`` port's own test class uses."""

    @needs_v314_engine
    def test_reused_functions_are_the_v314_objects(self):
        from arrayprobe import sizedist as v314

        self.assertIs(v35s._process_population, v314._process_population)
        self.assertIs(v35s._reaccept_shattered, v314._reaccept_shattered)
        self.assertIs(v35s._hhmmss_to_insec, v314._hhmmss_to_insec)
        self.assertIs(v35s._rollover_240000, v314._rollover_240000)
        self.assertIs(v35s.D_CHOICE, v314.D_CHOICE)
        self.assertIs(v35s.GOOD_REJECT_CODES, v314.GOOD_REJECT_CODES)
        self.assertIs(v35s.AREA_RATIO_Z, v314.STOCK_REJECT.area_ratio_z)

    @needs_v314_engine
    def test_borrowed_private_helpers_still_exist(self):
        from arrayprobe import sizedist as v314

        for name in ("_d_length", "_d_width", "_d_mean", "_d_hypot", "_d_max",
                     "_d_minr", "_D_CHOICE_SPECS", "_write", "_VARS",
                     "_VARS_ASPECT", "_VARS_TAIL", "_VARS_INTARR", "_REJ_ORDER",
                     "_REJ_ATTS", "_num2str", "_optional_parameters"):
            self.assertTrue(hasattr(v314, name), f"arrayprobe.sizedist.{name} no longer exists")


def _add_dummy_new_habit_variable(src: Path, dst: Path) -> None:
    shutil.copy(src, dst)
    with netCDF4.Dataset(dst, "a") as ds:
        n = ds.dimensions["time"].size
        v = ds.createVariable("width_length_percentile", "f8", ("time",))
        v[:] = np.zeros(n)


class TestEndToEndAgainstOctave(unittest.TestCase):
    """The whole driver, run on the SAME small real 2D-S proc fixture as the
    real, unmodified v3.5 ``sizeDist.m`` (``run_v35_sizedist_bank.py``),
    compared variable-for-variable against that Octave run.

    Layer 2 only (no v3.5-written archived product exists anywhere). Four
    cases reach every :func:`apply_shattering` branch and the writer's
    NETCDF4/attribute/transpose/``iat_threshold`` surface at once:
    ``main`` (type 0, ``iNewHabit=0``), ``main_new_habit`` (type 0,
    ``iNewHabit=1``), ``shatter_type2`` (the reused D3-preserving loop),
    ``shatter_type3`` (the new bracketed loop, ``iat_threshold`` written).
    """

    def setUp(self):
        if not PROC_FIXTURE.is_file():
            self.skipTest(f"proc fixture missing: {PROC_FIXTURE}")
        for name in ("main.nc", "main_new_habit.nc", "shatter_type2.nc", "shatter_type3.nc"):
            if not (SIZEDIST_DIR / name).is_file():
                self.skipTest(f"Octave golden missing: {name} -- run run_v35_sizedist_bank.py")
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _compare(self, golden_name: str, python_path: Path):
        golden_path = SIZEDIST_DIR / golden_name
        with netCDF4.Dataset(golden_path) as a, netCDF4.Dataset(python_path) as b:
            self.assertEqual(a.data_model, "NETCDF4")
            self.assertEqual(b.data_model, "NETCDF4")
            names_a = set(a.variables.keys())
            names_b = set(b.variables.keys())
            self.assertEqual(names_a, names_b, f"{golden_name}: variable set differs")
            for name in sorted(names_a):
                va = np.asarray(a.variables[name][:])
                vb = np.asarray(b.variables[name][:])
                self.assertEqual(va.shape, vb.shape, f"{golden_name}:{name} shape differs")
                with np.errstate(invalid="ignore"):
                    close = np.allclose(va, vb, rtol=1e-9, atol=1e-9, equal_nan=True)
                self.assertTrue(close, f"{golden_name}:{name} values differ")
            # Institution dropped, not renamed (:2039's own commented-out line).
            self.assertNotIn("Institution", a.ncattrs())
            for attr in ("Creation_Time", "Data_Source", "Probe_Type", "Habit_Scheme"):
                self.assertIn(attr, a.ncattrs())

    def test_main_no_habit_no_shatter(self):
        out_path = Path(self._tmp.name) / "main.nc"
        v35s.run(
            str(PROC_FIXTURE), str(out_path), TAS, TIMES, "2DS", 6, 0, PRES, TEMP,
            0, 0, 1, 1, "ORACLES", DDATE,
            software=SOFTWARE, creation_time=CREATION_TIME,
        )
        self._compare("main.nc", out_path)

    def test_main_new_habit(self):
        habit_fixture = Path(self._tmp.name) / "habit_fixture.nc"
        _add_dummy_new_habit_variable(PROC_FIXTURE, habit_fixture)
        out_path = Path(self._tmp.name) / "out.nc"
        v35s.run(
            str(habit_fixture), str(out_path), TAS, TIMES, "2DS", 6, 0, PRES, TEMP,
            0, 0, 1, 1, "ORACLES", DDATE,
            software=SOFTWARE, creation_time=CREATION_TIME,
        )
        self._compare("main_new_habit.nc", out_path)
        with netCDF4.Dataset(out_path) as ds:
            self.assertEqual(ds.getncattr("Habit_Scheme"), "Schima et al. (2024)")

    def test_shatter_type2(self):
        out_path = Path(self._tmp.name) / "out.nc"
        v35s.run(
            str(PROC_FIXTURE), str(out_path), TAS, TIMES, "2DS", 6, 0, PRES, TEMP,
            2, 0, 1, 1, "SOCRATES", DDATE,
            software=SOFTWARE, creation_time=CREATION_TIME,
        )
        self._compare("shatter_type2.nc", out_path)
        with netCDF4.Dataset(out_path) as ds:
            self.assertNotIn("iat_threshold", ds.variables)

    def test_shatter_type3_writes_iat_threshold(self):
        out_path = Path(self._tmp.name) / "out.nc"
        iat_thresh = np.full(6, 1e-3)
        v35s.run(
            str(PROC_FIXTURE), str(out_path), TAS, TIMES, "2DS", 6, 0, PRES, TEMP,
            3, 0, 1, 1, "GPM", DDATE, iat_thresh,
            software=SOFTWARE, creation_time=CREATION_TIME,
        )
        self._compare("shatter_type3.nc", out_path)
        with netCDF4.Dataset(out_path) as ds:
            np.testing.assert_allclose(ds.variables["iat_threshold"][:], iat_thresh)

    def test_conc_AreaR_is_not_identically_zero_finding_V24(self):
        # The A4 defect the v3.1.4 port documents makes conc_AreaR
        # identically zero wherever finite. v3.5 fixes it; the port must
        # reproduce that, not "preserve" a bug the source no longer has.
        with netCDF4.Dataset(SIZEDIST_DIR / "main.nc") as ds:
            v = np.asarray(ds.variables["conc_AreaR"][:])
        finite_nonzero = np.count_nonzero(np.isfinite(v) & (v != 0))
        self.assertGreater(finite_nonzero, 0)

    def test_six_transposed_variables_have_time_as_first_axis(self):
        # v3.5 fixes all six of the v3.1.4 port's own
        # NOT_TRANSPOSED variables. Their shape's first axis is Time (6
        # seconds); a variable still carrying v3.1.4's missing transpose
        # would instead show the bin axis first for these two-dimensional
        # variables, or crash the reshape entirely for a different-sized one.
        with netCDF4.Dataset(SIZEDIST_DIR / "main.nc") as ds:
            for name in ("mean_area_ratio", "REJ_mean_area_ratio"):
                self.assertEqual(ds.variables[name].shape[0], 6, name)

    def test_good_bad_asymmetry_in_past_end_of_data_branch_finding_V28(self):
        # REJ_ar (bad_one_sec_ar) at a second before any real particle data
        # is 0.0 in real MATLAB (its own zero-initialisation, never reset by
        # the past-end-of-data branch, which names only good-side variables)
        # -- not NaN, which a naive good/bad-symmetric port produces and
        # which this exact assertion caught during development.
        with netCDF4.Dataset(SIZEDIST_DIR / "main.nc") as ds:
            rej_ar = np.asarray(ds.variables["REJ_ar"][:])
        self.assertEqual(rej_ar[0], 0.0)
        self.assertFalse(np.isnan(rej_ar[0]))


class MassBlPowIsLibm(unittest.TestCase):
    """``area .^ 1.218`` goes through the platform libm element by element, as Octave's ``.^``
    does; numpy's array ``**`` takes a SIMD pow that differed from the Octave golden by 1-2 ULP on
    an AVX-512 CPU (cloud pass 7, item 4)."""

    def test_equals_math_pow_element_by_element(self) -> None:
        from arrayprobe_uiops.sizedist import _libm_pow
        x = np.random.default_rng(7).uniform(0.0, 5.0e4, 5000)
        want = np.array([math.pow(float(v), 1.218) for v in x])
        self.assertTrue(np.array_equal(_libm_pow(x, 1.218), want))

    def test_nan_and_shape_follow_numpy(self) -> None:
        from arrayprobe_uiops.sizedist import _libm_pow
        got = _libm_pow(np.array([[4.0, np.nan], [-1.0, 0.0]]), 1.218)
        self.assertEqual(got.shape, (2, 2))
        self.assertTrue(np.isnan(got[0, 1]) and np.isnan(got[1, 0]))
        self.assertEqual(got[1, 1], 0.0)

    def test_overflow_gives_inf_as_numpy_and_matlab_do(self) -> None:
        from arrayprobe_uiops.sizedist import _libm_pow
        self.assertEqual(_libm_pow(np.array([1e308]), 1.218)[0], np.inf)

# _release_fixture_guard: real-data derived fixtures are excluded from the release
import pathlib as _rfg_pathlib  # noqa: E402
import unittest as _rfg_unittest  # noqa: E402

_RFG_EXCLUDED = ('v35_sizedist_synthetic.proc.nc', 'v35_sizedist/main.nc')
if not all((_rfg_pathlib.Path(__file__).resolve().parent / "data" / _n).exists()
           for _n in _RFG_EXCLUDED):
    raise _rfg_unittest.SkipTest(
        "real-data derived fixtures (UIOPS PECAN DMT / minimal-example 2D-S samples) "
        "are not shipped in the release")

if __name__ == "__main__":
    unittest.main()
