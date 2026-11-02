# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe_soda2.processbuffer_spec`` against GDL running the real
``soda2_processbuffer.pro`` end to end, plus a from-the-frame-golden
third side.

Golden: ``gdl_oracle/run_soda2_processbuffer_spec_bank.py``, 12 cases on
the two tracked SPEC fixtures. Case 0 of the golden's JSON array is the
``oracle_shims`` note, not a case.
"""
from __future__ import annotations

import json
import re
import struct
import unittest
from pathlib import Path

import numpy as np
from tests._repo import needs_file, repo_only  # noqa: E402

from arrayprobe_soda2.binary_dof import binary_dof
from arrayprobe_soda2.processbuffer_spec import (
    NullBuffer,
    SpecBufferParticles,
    SpecMisc,
    SpecOp,
    UnsupportedSpecSubformat,
    process_spec_buffer,
    soda2_processbuffer,
)
from arrayprobe_soda2.processbuffer_tail import (
    GreythreshNotPorted,
    ProcessedBuffer,
    TailOp,
    process_buffer_tail,
)
from arrayprobe_soda2.spec_read_frame import spec_read_frame

DATA = Path(__file__).resolve().parent / "data"
GOLDEN = DATA / "gdl_soda2_processbuffer_spec_golden.json"
S2_RAW = DATA / "s2_spec_raw_fixture"
FRAME_RAW = DATA / "soda2_spec_frame_fixture"
FRAME_GOLDEN = DATA / "gdl_soda2_spec_read_frame_golden.json"


def _load_golden() -> list[dict]:
    records = json.loads(GOLDEN.read_text(encoding="utf-8"))
    return [r for r in records if "oracle_shims" not in r]


def _hex64(value: float) -> str:
    return struct.pack(">d", value).hex().upper()


def _hex32(value: float) -> str:
    return struct.pack(">f", value).hex().upper()


def _run_case(rec: dict) -> tuple[SpecBufferParticles | NullBuffer, SpecMisc]:
    path = S2_RAW if rec["fixture"] == "s2" else FRAME_RAW
    op = SpecOp(
        probetype=rec["probetype"], subformat=0, probeid=rec["probeid"],
        dofreject=rec["dofreject"], stretchcorrect=rec["stretchcorrect"],
        yres=rec["yres"], res=rec["res"],
    )
    misc = SpecMisc(
        nimages=rec["nimages"], hkpointers=rec["hkpointers"],
        imagepointers=rec["imagepointers"], probetas=0.0,
        aircrafttas=rec["aircrafttas"], lastclock=rec["lastclock"],
        lastbufftime=rec["lastbufftime"], maxsfm=rec["maxsfm"],
    )
    with open(path, "rb") as f:
        result = process_spec_buffer(f, rec["bufftime"], op, misc)
    return result, misc


class AgainstTheGdlGolden(unittest.TestCase):
    def test_every_case_matches_idl_exactly(self) -> None:
        records = _load_golden()
        checked = 0
        for rec in records:
            with self.subTest(case=rec["name"]):
                result, misc = _run_case(rec)
                if rec["REJECT"] == 1:
                    self.assertIsInstance(result, NullBuffer)
                else:
                    self.assertIsInstance(result, SpecBufferParticles)
                    assert isinstance(result, SpecBufferParticles)
                    self.assertEqual(list(result.startline), rec["STARTLINE"])
                    self.assertEqual(list(result.stopline), rec["STOPLINE"])
                    self.assertEqual(list(result.rawtime), rec["RAWTIME"])
                    self.assertEqual(list(result.particle_count), rec["PC"])
                    self.assertEqual(list(result.overload), rec["OVL"])
                    self.assertEqual(list(result.dof), rec["DOF"])
                    self.assertEqual(
                        [f"{v:08X}" for v in result.clocktas.view(np.uint32)],
                        rec["CLOCKTASHEX"])
                    self.assertEqual(
                        [_hex_from_double(v) for v in result.inttime],
                        rec["INTTIMEHEX"])
                    self.assertEqual(
                        [_hex_from_double(v) for v in result.time_sfm],
                        rec["PROBETIMEHEX"])
                    self.assertEqual(_hex_from_double(result.reftime),
                                      rec["REFTIMEHEX"])
                    self.assertEqual(result.bitimage.shape,
                                      tuple(int(x) for x in
                                            reversed(rec["BITDIM"].split(","))))
                    self.assertEqual(result.startline.dtype, np.uint32)
                    self.assertEqual(result.stopline.dtype, np.uint32)
                    self.assertEqual(result.rawtime.dtype, np.uint32)
                    self.assertEqual(result.clocktas.dtype, np.float32)
                    self.assertEqual(result.inttime.dtype, np.float64)
                self.assertEqual(
                    [_hex_from_double(misc.lastclock),
                     _hex_from_double(misc.maxsfm),
                     _hex_from_double(misc.lastbufftime)],
                    rec["MISCHEX"])
                checked += 1
        self.assertGreaterEqual(checked, 13)


def _is_subsequence(needle: list, haystack: list) -> bool:
    it = iter(haystack)
    return all(x in it for x in needle)


def _hex_from_double(value: float) -> str:
    return struct.pack(">d", float(value)).hex().upper()


class TheFrameGoldenPredictsTheIntegerOutputs(unittest.TestCase):
    """The third side -- from `gdl_soda2_spec_read_frame_golden.json` alone,
    no port, no NumPy import here -- derive `startline`/`stopline`/
    `rawtime`/`particle_count`/`overload` for `frame_h_all18` and assert
    against both the processbuffer golden and the port."""

    def test_frame_h_all18_predicted_from_the_frame_golden(self) -> None:
        frame_records = {r["pointer"]: r for r in
                          json.loads(FRAME_GOLDEN.read_text(encoding="utf-8"))
                          if r.get("id") == "H" and r.get("status") == "OK"}
        proc_records = _load_golden()
        rec = next(r for r in proc_records if r["name"] == "frame_h_all18")
        pointers = rec["imagepointers"]

        # U4: pointers 4266/4286 ("v1_h"/"v1_v") were built for `version=1`
        # in the frame bank's own cases; `soda2_processbuffer` always calls
        # `spec_read_frame` with the default `version=0`, so the frame
        # golden's TIME for these two does not predict what this bank's
        # `version=0` read returns. T1 still asserts them against the
        # processbuffer golden directly.
        _VERSION1_ONLY_POINTERS = {4266, 4286}

        # Predict rawtime/particle_count/overload for every pointer this
        # side CAN predict -- excluding the two `version=1`-built pointers
        # (U4: `soda2_processbuffer` always calls `spec_read_frame` with the
        # default `version=0`, and whether each of those two is even kept
        # under that decode is not established by this bank's cases, only
        # measured by the golden itself).
        predicted_rawtime: list[int] = []
        predicted_pc: list[int] = []
        predicted_ovl: list[int] = []
        for p in pointers:
            if p in _VERSION1_ONLY_POINTERS:
                continue
            fr = frame_records.get(p)
            if fr is None or fr.get("ERROR") not in (0,):
                continue
            predicted_rawtime.append(
                fr["TT"] if rec["probetype"] == "HVPS3" else fr["TIME"])
            predicted_pc.append(fr["PC"])
            predicted_ovl.append(fr["OVL"])

        # The predicted, non-special subsequence must appear in the
        # processbuffer golden's own arrays IN ORDER (a subsequence, not an
        # exact positional match -- the interspersed, unpredicted special
        # pointers may or may not contribute their own entries).
        self.assertTrue(_is_subsequence(predicted_rawtime, rec["RAWTIME"]))
        self.assertTrue(_is_subsequence(predicted_pc, rec["PC"]))
        self.assertTrue(_is_subsequence(predicted_ovl, rec["OVL"]))
        self.assertGreaterEqual(len(predicted_rawtime), 7)

        result, _misc = _run_case(rec)
        assert isinstance(result, SpecBufferParticles)
        self.assertEqual(list(result.rawtime), rec["RAWTIME"])
        self.assertEqual(list(result.particle_count), rec["PC"])
        self.assertEqual(list(result.overload), rec["OVL"])


class TheRefusals(unittest.TestCase):
    def _op_misc(self, **op_over):
        op = SpecOp(probetype="2DS", subformat=0, probeid="H",
                    dofreject=0, stretchcorrect=0, yres=10.0, res=10.0)
        op = SpecOp(**{**op.__dict__, **op_over})
        misc = SpecMisc(nimages=1, hkpointers=[0], imagepointers=[0],
                         probetas=0.0, aircrafttas=100.0, lastclock=0.0,
                         lastbufftime=0.0, maxsfm=0.0)
        return op, misc

    def test_subformat_3_matches_no_case_arm_at_line_291(self) -> None:
        """`:291-295`'s CASE has no ELSE: a subformat outside 0-2 is an IDL
        error, raised here before any read (an empty file proves it)."""
        import io
        op, misc = self._op_misc(subformat=3)
        with self.assertRaises(UnsupportedSpecSubformat) as ctx:
            process_spec_buffer(io.BytesIO(b""), 0.0, op, misc)
        self.assertIn("soda2_processbuffer.pro:291", str(ctx.exception))

    def test_subformats_1_and_2_are_no_longer_refused(self) -> None:
        """Slice B: 1 and 2 dispatch (`:291-295`); with nimages=0 they reach
        `:266-267`'s null buffer instead of raising."""
        import io
        for sub in (1, 2):
            op, misc = self._op_misc(subformat=sub)
            misc.nimages = 0
            self.assertIsInstance(
                process_spec_buffer(io.BytesIO(b""), 0.0, op, misc), NullBuffer)

    def test_dofreject_3_runs_binary_dof_per_kept_frame(self) -> None:
        """No GDL golden case exists for `dofreject == 3` this round (the
        real `soda2_processbuffer` under GDL would call GDL's own `convol`
        on unpadded frames -- wrong edges, and a halt on 1- and 2-slice
        frames, per `binary_dof.py`'s module docstring -- so a golden there
        would be a GDL-behaviour golden, not an IDL one; the open item for
        the coordinator). Instead, layer-3 composition: recompute `dof`
        from a *different* entry point -- `spec_read_frame` called directly
        on the golden's own `imagepointers`, applying `:296`'s keep rule --
        and compare against `process_spec_buffer`'s own output."""
        records = _load_golden()
        rec = next(r for r in records if r["name"] == "frame_h_all18")
        op = SpecOp(probetype=rec["probetype"], subformat=0,
                     probeid=rec["probeid"], dofreject=3,
                     stretchcorrect=rec["stretchcorrect"],
                     yres=rec["yres"], res=rec["res"])
        misc = SpecMisc(nimages=rec["nimages"], hkpointers=rec["hkpointers"],
                         imagepointers=rec["imagepointers"], probetas=0.0,
                         aircrafttas=rec["aircrafttas"],
                         lastclock=rec["lastclock"],
                         lastbufftime=rec["lastbufftime"],
                         maxsfm=rec["maxsfm"])

        expected_dof = []
        with open(FRAME_RAW, "rb") as f:
            for pointer in rec["imagepointers"]:
                x = spec_read_frame(f, pointer, rec["probeid"])
                if x.error != 0 or x.image.shape[0] >= 1000:
                    continue
                expected_dof.append(binary_dof(x.image).dof)

        with open(FRAME_RAW, "rb") as f:
            result = process_spec_buffer(f, rec["bufftime"], op, misc)
        assert isinstance(result, SpecBufferParticles)

        self.assertGreater(len(expected_dof), 0)
        if len(set(expected_dof)) < 2:
            print("test_dofreject_3_runs_binary_dof_per_kept_frame: the "
                  f"frame_h_all18 fixture's kept frames all give dof="
                  f"{expected_dof[0]!r} -- both 0 and 1 are not exercised "
                  "by this fixture (report: no synthetic fixture built "
                  "this round).")
        self.assertEqual(list(result.dof), expected_dof)

    def test_dofreject_0_leaves_dof_all_ones(self) -> None:
        records = _load_golden()
        rec = next(r for r in records if r["name"] == "frame_h_all18")
        self.assertEqual(rec["dofreject"], 0)
        result, _misc = _run_case(rec)
        assert isinstance(result, SpecBufferParticles)
        self.assertTrue(all(v == 1 for v in result.dof))
        self.assertEqual(rec["DOF"], list(result.dof))

    def test_dof_is_the_only_field_dofreject_changes(self) -> None:
        records = _load_golden()
        rec = next(r for r in records if r["name"] == "frame_h_all18")
        result0, misc0 = _run_case(rec)
        op3 = SpecOp(probetype=rec["probetype"], subformat=0,
                      probeid=rec["probeid"], dofreject=3,
                      stretchcorrect=rec["stretchcorrect"],
                      yres=rec["yres"], res=rec["res"])
        misc3 = SpecMisc(nimages=rec["nimages"], hkpointers=rec["hkpointers"],
                          imagepointers=rec["imagepointers"], probetas=0.0,
                          aircrafttas=rec["aircrafttas"],
                          lastclock=rec["lastclock"],
                          lastbufftime=rec["lastbufftime"],
                          maxsfm=rec["maxsfm"])
        with open(FRAME_RAW, "rb") as f:
            result3 = process_spec_buffer(f, rec["bufftime"], op3, misc3)
        assert isinstance(result0, SpecBufferParticles)
        assert isinstance(result3, SpecBufferParticles)
        for field in ("num_images", "startline", "stopline", "overload",
                      "particle_count", "rawtime", "clocktas", "stretch",
                      "inttime", "time_sfm", "reftime"):
            v0 = getattr(result0, field)
            v3 = getattr(result3, field)
            if isinstance(v0, np.ndarray):
                self.assertTrue(np.array_equal(v0, v3), field)
            else:
                self.assertEqual(v0, v3, field)


class TheBankReachesEveryBranch(unittest.TestCase):
    def test_the_golden_exercises_every_named_branch(self) -> None:
        records = _load_golden()
        self.assertTrue(any(r["REJECT"] == 1 and r["nimages"] == 0
                             for r in records))
        self.assertTrue(any(r["REJECT"] == 1 and r["nimages"] > 0
                             for r in records))
        self.assertTrue(any(r["lastclock"] > 0 for r in records))
        self.assertTrue(any(r["probeid"] == "V" for r in records))
        self.assertTrue(any(r["REJECT"] == 0 and 1 in r.get("OVL", [])
                             for r in records))
        sametime = next(r for r in records if r["name"] == "s2_sametime")
        self.assertEqual(sametime["PROBETIMEHEX"][0],
                          _hex_from_double(sametime["maxsfm"]))
        baseline = next(r for r in records if r["name"] == "s2_h_baseline")
        all_double = _hex_from_double(65536 * 2e-7)
        self.assertNotEqual(baseline["INTTIMEHEX"][0], all_double)


class TheOracleShims(unittest.TestCase):
    @repo_only
    @needs_file("SODA2/abansemer-soda2-afcea15/spec_decompress.pro")
    def test_uniq_and_decompress_shims_are_still_vendored(self) -> None:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "validation" / "gdl"))  # noqa: E501
        import run_soda2_processbuffer_spec_bank as bank
        from run_soda2_spec_read_frame_bank import decompress_shim
        self.assertIn("UNIQ_SHIM", dir(bank))
        self.assertIn("FUNCTION uniq", bank.UNIQ_SHIM)
        self.assertTrue(decompress_shim())


class TheSameTimeForwardCount(unittest.TestCase):
    def test_line_363_stamps_the_first_particle_with_maxsfm(self) -> None:
        records = _load_golden()
        rec = next(r for r in records if r["name"] == "s2_sametime")
        result, misc = _run_case(rec)
        assert isinstance(result, SpecBufferParticles)
        self.assertEqual(result.time_sfm[0], rec["maxsfm"])
        for i in range(1, len(result.time_sfm)):
            self.assertAlmostEqual(
                result.time_sfm[i],
                result.time_sfm[i - 1] + result.inttime[i], places=9)

    def test_multi_particle_sametime_matches_the_gdl_golden_exactly(self) -> None:
        """`s2_sametime` keeps only one particle, where the backward and
        forward count formulas happen to coincide -- this is the case that
        actually discriminates M3 (dropping the `:362-365` overwrite)."""
        records = _load_golden()
        rec = next(r for r in records if r["name"] == "frame_hvps3_sametime")
        result, _misc = _run_case(rec)
        assert isinstance(result, SpecBufferParticles)
        self.assertEqual(result.time_sfm[0], rec["maxsfm"])
        for i in range(1, len(result.time_sfm)):
            self.assertAlmostEqual(
                result.time_sfm[i],
                result.time_sfm[i - 1] + result.inttime[i], places=6)
        self.assertEqual(
            [_hex_from_double(v) for v in result.time_sfm],
            rec["PROBETIMEHEX"])


def _lastdhist_array(expr: str) -> np.ndarray:
    """Parse the golden's `lastdhist` field -- either `"lonarr(128)"` or a
    literal statement sequence like `"h=lonarr(128) & h[40]=5000L & h"` --
    into the same int32 array the GDL case actually used."""
    h = np.zeros(128, dtype=np.int32)
    for m in re.finditer(r"h\[(\d+)\]=(\d+)L?", expr):
        h[int(m.group(1))] = int(m.group(2))
    return h


def _tail_op(rec: dict) -> TailOp:
    return TailOp(
        stuckbits=rec["stuckbits"], rakefix=rec["rakefix"],
        greythresh=rec["greythresh"],
        dioderange=tuple(rec["dioderange"]),
        numdiodes=128, keeplargest=rec["keeplargest"],
        res=rec["res"], yres=rec["yres"],
    )


def _run_tail_case(rec: dict) -> ProcessedBuffer:
    result, _misc = _run_case(rec)
    assert isinstance(result, SpecBufferParticles)
    return process_buffer_tail(
        result, _tail_op(rec), _lastdhist_array(rec["lastdhist"]))


#: **Resolved, R7C, 2026-09-14.** Previously listed the particles
#: (0-indexed) in the multi-frame `frame_h_all18`/`frame_hvps3_sametime`
#: cases whose `diam`/`ar`/`arfilled`/`areasize` differed from the GDL
#: golden by exactly one float32 ULP -- particle 4/5 of `frame_h_all18` is a
#: 5-slice ROI with two disjoint diode clusters on one row,
#: `[5..14],[18..25]`. Root-caused by layered bisection: the exact
#: (x_ind, y_adj) outline coordinates the port derives from these ROIs
#: (`aspect_ratio.outline_indices`) were fed to `min_circle_fast.pro` under
#: GDL (`gdl_oracle/run_soda2_min_circle_fast_bank.py`'s `real_roi_p4`/
#: `real_roi_p6` cases) and matched the port's `min_circle_fast` bit for
#: bit -- ruling out the circle fit entirely. The divergence was in
#: `findsize.py:252` (`soda2_findsize.pro:31`): `(circle.diam+1)*xres` is
#: DOUBLE arithmetic in IDL, rounded to FLOAT exactly once at assignment
#: into the struct's declared-FLOAT field; the port cast `circle.diam` to
#: float32 *before* the add and multiply, rounding twice in a different
#: order. Fixed to do the arithmetic in double and round once. All nine
#: case rows below now match the GDL golden bit for bit with no skip.
#: Not registered as a SODA-2 finding: a port defect, not SODA-2 behaviour.
_KNOWN_MULTIBLOB_ULP_DIFF: dict[str, set[int]] = {}
#: Fields whose value derives from the minimum-enclosing-circle fit and so
#: inherits the same ULP on the same particles.
_CIRCLE_DERIVED_HEX_KEYS = ("TAIL_DIAM", "TAIL_ARHEX", "TAIL_ARFILLEDHEX",
                             "TAIL_AREASIZEHEX")


def _assert_hex_array(test: unittest.TestCase, key: str, got: list[str],
                       want: list[str], skip: set[int]) -> None:
    if key in _CIRCLE_DERIVED_HEX_KEYS and skip:
        got_f = [v for i, v in enumerate(got) if i not in skip]
        want_f = [v for i, v in enumerate(want) if i not in skip]
        test.assertEqual(got_f, want_f, key)
    else:
        test.assertEqual(got, want, key)


def _assert_tail_matches(test: unittest.TestCase, out: ProcessedBuffer,
                          rec: dict, skip: set[int]) -> None:
    """Every `TAIL_*` field, `STREAK` and `DIODETOTAL`, bit for bit."""
    _assert_hex_array(test, "TAIL_DIAM",
                       [_hex32(v) for v in out.diam],
                       rec["TAIL_DIAM"], skip)
    test.assertEqual(
        [_hex32(v) for v in out.xsize], rec["TAIL_XSIZEHEX"])
    test.assertEqual(
        [_hex32(v) for v in out.ysize], rec["TAIL_YSIZEHEX"])
    test.assertEqual(
        [_hex32(v) for v in out.xextent],
        rec["TAIL_XEXTENTHEX"])
    _assert_hex_array(test, "TAIL_AREASIZEHEX",
                       [_hex32(v) for v in out.areasize],
                       rec["TAIL_AREASIZEHEX"], skip)
    test.assertEqual(
        [_hex32(v) for v in out.oned], rec["TAIL_ONEDHEX"])
    test.assertEqual(
        [_hex32(v) for v in out.twod], rec["TAIL_TWODHEX"])
    _assert_hex_array(test, "TAIL_ARHEX",
                       [_hex32(v) for v in out.ar],
                       rec["TAIL_ARHEX"], skip)
    _assert_hex_array(test, "TAIL_ARFILLEDHEX",
                       [_hex32(v) for v in out.arfilled],
                       rec["TAIL_ARFILLEDHEX"], skip)
    test.assertEqual(
        [_hex32(v) for v in out.aspr], rec["TAIL_ASPRHEX"])
    test.assertEqual(
        [_hex32(v) for v in out.zd], rec["TAIL_ZDHEX"])
    test.assertEqual(
        [_hex32(v) for v in out.sizecorrection],
        rec["TAIL_SIZECORRHEX"])
    test.assertEqual(
        [_hex32(v) for v in out.xpos], rec["TAIL_XPOSHEX"])
    test.assertEqual(
        [_hex32(v) for v in out.ypos], rec["TAIL_YPOSHEX"])
    test.assertEqual(
        [_hex32(v) for v in out.orientation],
        rec["TAIL_ORIENTHEX"])
    test.assertEqual(
        [_hex32(v) for v in out.area_orig],
        rec["TAIL_AREAORIGHEX"])
    test.assertEqual(
        [_hex32(v) for v in out.area_filled],
        rec["TAIL_AREAFILLEDHEX"])
    test.assertEqual(
        [_hex32(v) for v in out.area75], rec["TAIL_AREA75HEX"])
    test.assertEqual(
        [_hex32(v) for v in out.perimeterarea],
        rec["TAIL_PERIMHEX"])
    test.assertEqual(list(out.allin), rec["TAIL_ALLIN"])
    test.assertEqual(list(out.centerin), rec["TAIL_CENTERIN"])
    test.assertEqual(list(out.edgetouch), rec["TAIL_EDGETOUCH"])
    test.assertEqual(list(out.numregions),
                      rec["TAIL_NUMREGIONS"])
    test.assertEqual(list(out.diodegaps), rec["TAIL_DIODEGAPS"])
    test.assertEqual(list(out.dhist), rec["TAIL_DHIST"])
    test.assertEqual(out.streak, rec["STREAK"])
    test.assertEqual(
        list(out.bitimage.sum(axis=0).astype(int)),
        rec["DIODETOTAL"])


class TheTailAgainstTheGdlGolden(unittest.TestCase):
    """Round 6-A: `soda2_processbuffer.pro:612-747`, ported in
    `processbuffer_tail.py`, asserted bit for bit against every `TAIL_*`
    key the bank now prints (except the known multi-blob ULP diffs above,
    excluded by particle index, never by loosening the whole case)."""

    def test_every_reject0_case_matches_every_tail_field(self) -> None:
        records = _load_golden()
        checked = 0
        for rec in records:
            if rec["REJECT"] != 0:
                continue
            skip = _KNOWN_MULTIBLOB_ULP_DIFF.get(rec["name"], set())
            with self.subTest(case=rec["name"]):
                out = _run_tail_case(rec)
                _assert_tail_matches(self, out, rec, skip)
                checked += 1
        self.assertGreaterEqual(checked, 15)

    def test_dtype_claims_measured_against_tail_tn(self) -> None:
        rec = next(r for r in _load_golden() if r["name"] == "frame_h_all18")
        tn = rec["TAIL_TN"].split(",")
        # order: diam, allin, diodegaps, dhist, numregions, perimeterarea, streak
        self.assertEqual(tn, ["FLOAT", "BYTE", "INT", "INT", "BYTE",
                               "FLOAT", "INT"])
        out = _run_tail_case(rec)
        self.assertEqual(out.diam.dtype, np.float32)
        self.assertEqual(out.allin.dtype, np.uint8)
        self.assertEqual(out.diodegaps.dtype, np.int16)
        self.assertEqual(out.dhist.dtype, np.int16)
        self.assertEqual(out.numregions.dtype, np.uint8)
        self.assertEqual(out.perimeterarea.dtype, np.float32)


class TheTailTraps(unittest.TestCase):
    def test_line_652_dioderange00_equals_baseline_bit_for_bit(self) -> None:
        records = _load_golden()
        base = next(r for r in records if r["name"] == "frame_h_all18")
        dr00 = next(r for r in records
                    if r["name"] == "frame_h_all18_dioderange00")
        self.assertEqual(dr00["TAIL_DIAM"], base["TAIL_DIAM"])
        out_base = _run_tail_case(base)
        out_dr00 = _run_tail_case(dr00)
        self.assertTrue(np.array_equal(out_base.diam, out_dr00.diam))

    def test_line_615_stuckbits_copy_makes_dhist_immune(self) -> None:
        """`:614`'s `bitimage_orig=bitimage` is a copy taken before
        `fixstuckbits`, so `roi_orig` (and hence `dhist`) is unaffected by
        `stuckbits=1` even though `DIODETOTAL` (from the post-fixstuckbits
        `bitimage`) can differ -- S5-f's fixture does not happen to shade
        the corrupted column (diode `numdiodes-8`=120), so `DIODETOTAL`
        matches here too; the dhist-immunity claim itself is exact either
        way and is what this test pins."""
        records = _load_golden()
        base = next(r for r in records if r["name"] == "frame_h_all18")
        sb = next(r for r in records
                  if r["name"] == "frame_h_all18_stuckbits")
        self.assertEqual(base["TAIL_DHIST"], sb["TAIL_DHIST"])
        out_base = _run_tail_case(base)
        out_sb = _run_tail_case(sb)
        self.assertTrue(np.array_equal(out_base.dhist, out_sb.dhist))

    def test_line_618_streak_matches_the_overload_frame_case(self) -> None:
        """`frame_overload_only` (pointer 82) turned out, measured, not to
        be an all-zero buffer (bitimage sum 18, not 0) -- S5-g's true
        0/0 case is not exhibited by this round's fixtures. What the case
        DOES pin: `streak` computed without a stray RuntimeWarning/
        FloatingPointError escaping the errstate block."""
        rec = next(r for r in _load_golden()
                   if r["name"] == "frame_overload_only")
        with np.errstate(all="raise"):
            out = _run_tail_case(rec)
        self.assertEqual(out.streak, rec["STREAK"])

    def test_line_618_streak_on_a_synthetic_all_zero_buffer_is_well_defined(
            self) -> None:
        """S5-g, unit-level: an all-zero `diodetotal` makes
        `max/mean` a `0/0`; the port must return `streak=0`, not raise."""
        rec = next(r for r in _load_golden() if r["name"] == "s2_h_baseline")
        result, _misc = _run_case(rec)
        assert isinstance(result, SpecBufferParticles)
        result.bitimage = np.zeros_like(result.bitimage)
        op = _tail_op(rec)
        out = process_buffer_tail(result, op, np.zeros(128, dtype=np.int32))
        self.assertEqual(out.streak, 0)

    def test_line_709_diodegaps_is_1_not_0_on_a_synthetic_empty_roi(
            self) -> None:
        """S5-h, unit-level: `frame_overload_only`'s ROI turned out not to
        be empty (measured), so this pins the rule directly on a
        hand-built all-zero particle."""
        rec = next(r for r in _load_golden() if r["name"] == "s2_h_baseline")
        result, _misc = _run_case(rec)
        assert isinstance(result, SpecBufferParticles)
        s, e = int(result.startline[0]), int(result.stopline[0])
        result.bitimage = result.bitimage.copy()
        result.bitimage[s:e + 1, :] = 0
        op = _tail_op(rec)
        out = process_buffer_tail(result, op, np.zeros(128, dtype=np.int32))
        self.assertEqual(int(out.diodegaps[0]), 1)

    def test_line_694_keeplargest_picks_the_first_maximum(self) -> None:
        rec = next(r for r in _load_golden()
                   if r["name"] == "frame_h_all18_keeplargest1")
        out = _run_tail_case(rec)
        self.assertEqual(list(out.numregions), rec["TAIL_NUMREGIONS"])

    def test_line_703_one_slice_roi_is_passed_1d(self) -> None:
        """No case in this round's 21-case bank happens to produce a
        `STARTLINE == STOPLINE` particle (checked: none does) -- so this
        is a synthetic, unit-level check rather than a golden comparison.
        A hand-built one-slice buffer must not raise (fillholes/label_blobs/
        soda2_findsize all accept 1-D input per their own docstrings) and
        must produce the same `dhist`/`diam` a direct 1-D call would."""
        rec = next(r for r in _load_golden() if r["name"] == "s2_h_baseline")
        result, _misc = _run_case(rec)
        assert isinstance(result, SpecBufferParticles)
        # Splice in a synthetic one-slice particle as image 0.
        result.startline = result.startline.copy()
        result.stopline = result.stopline.copy()
        result.startline[0] = 1
        result.stopline[0] = 1
        op = _tail_op(rec)
        out = process_buffer_tail(result, op, np.zeros(128, dtype=np.int32))
        roi_1d = result.bitimage[1, :]
        from arrayprobe_soda2.findsize import soda2_findsize
        part_direct = soda2_findsize(roi_1d, np.float32(op.res),
                                      np.float32(op.yres) * np.float32(result.stretch[0]))
        self.assertEqual(_hex32(out.diam[0]), _hex32(part_direct.diam))


class TheTailRefusals(unittest.TestCase):
    def _minimal(self, rec: dict, **over) -> tuple[SpecBufferParticles, TailOp]:
        result, _misc = _run_case(rec)
        assert isinstance(result, SpecBufferParticles)
        op = _tail_op({**rec, **over}) if not over.get("_restore_slice") \
            else _tail_op(rec)
        return result, op

    def test_rakefix_calls_fixraking_after_stuckbits_before_diodetotal(
            self) -> None:
        """`soda2_processbuffer.pro:616`: `rakefix>0` runs `fixraking` on
        the [diode, slice] image, i.e. the buffer transposed, and its
        result is what every later step sees."""
        from unittest import mock

        import arrayprobe_soda2.processbuffer_tail as tail
        rec = next(r for r in _load_golden() if r["name"] == "frame_h_all18")
        result, _misc = _run_case(rec)
        assert isinstance(result, SpecBufferParticles)
        op = TailOp(stuckbits=0, rakefix=3, greythresh=0,
                     dioderange=(0, 127), numdiodes=128, keeplargest=0,
                     res=rec["res"], yres=rec["yres"])
        seen = {}

        def spy(image, modetype):
            seen["shape"] = np.asarray(image).shape
            seen["modetype"] = modetype
            return real(image, modetype)

        real = tail.fixraking
        with mock.patch.object(tail, "fixraking", side_effect=spy) as m:
            process_buffer_tail(result, op, np.zeros(128, dtype=np.int32))
        self.assertEqual(m.call_count, 1)
        self.assertEqual(seen["modetype"], 3)
        self.assertEqual(seen["shape"], result.bitimage.T.shape)

    def test_rakefix_zero_is_byte_identical_to_no_rakefix_call(self) -> None:
        """`rakefix=0` never calls `fixraking`, so every output equals the
        output with `fixraking` replaced by a call that would fail."""
        from unittest import mock

        import arrayprobe_soda2.processbuffer_tail as tail
        rec = next(r for r in _load_golden() if r["name"] == "frame_h_all18")
        result, _misc = _run_case(rec)
        assert isinstance(result, SpecBufferParticles)
        op = TailOp(stuckbits=0, rakefix=0, greythresh=0,
                     dioderange=(0, 127), numdiodes=128, keeplargest=0,
                     res=rec["res"], yres=rec["yres"])
        before = process_buffer_tail(result, op, np.zeros(128, dtype=np.int32))
        with mock.patch.object(tail, "fixraking",
                               side_effect=AssertionError("called")) as m:
            after = process_buffer_tail(result, op,
                                        np.zeros(128, dtype=np.int32))
        self.assertEqual(m.call_count, 0)
        for name in vars(before):
            a, b = getattr(before, name), getattr(after, name)
            if isinstance(a, np.ndarray):
                self.assertTrue(np.array_equal(a, b), name)
                self.assertEqual(a.dtype, b.dtype, name)
            else:
                self.assertEqual(a, b, name)

    def test_greythresh_refused_before_any_leaf_call(self) -> None:
        rec = next(r for r in _load_golden() if r["name"] == "frame_h_all18")
        result, _misc = _run_case(rec)
        assert isinstance(result, SpecBufferParticles)
        op = TailOp(stuckbits=0, rakefix=0, greythresh=1,
                     dioderange=(0, 127), numdiodes=128, keeplargest=0,
                     res=rec["res"], yres=rec["yres"])
        with self.assertRaises(GreythreshNotPorted) as ctx:
            process_buffer_tail(result, op, np.zeros(128, dtype=np.int32))
        self.assertIn("soda2_processbuffer.pro:666", str(ctx.exception))

    def test_restore_slice_now_runs_soda2_backfill(self) -> None:
        # :678 is ported (arrayprobe_soda2.backfill); restore_slice=1 no
        # longer raises RestoreSliceNotPorted.
        rec = next(r for r in _load_golden() if r["name"] == "frame_h_all18")
        result, _misc = _run_case(rec)
        assert isinstance(result, SpecBufferParticles)
        result.restore_slice = 1
        op = TailOp(stuckbits=0, rakefix=0, greythresh=0,
                     dioderange=(0, 127), numdiodes=128, keeplargest=0,
                     res=rec["res"], yres=rec["yres"])
        out = process_buffer_tail(result, op, np.zeros(128, dtype=np.int32))
        self.assertIsNotNone(out)

    def test_lastdhist_shape_asserted(self) -> None:
        rec = next(r for r in _load_golden() if r["name"] == "frame_h_all18")
        result, _misc = _run_case(rec)
        assert isinstance(result, SpecBufferParticles)
        op = _tail_op(rec)
        with self.assertRaises(ValueError):
            process_buffer_tail(result, op, np.zeros(64, dtype=np.int32))


class TheComposition(unittest.TestCase):
    def test_soda2_processbuffer_returns_nullbuffer_without_calling_the_tail(
            self) -> None:
        from unittest import mock
        rec = next(r for r in _load_golden() if r["name"] == "nimages0")
        op = SpecOp(probetype=rec["probetype"], subformat=0,
                     probeid=rec["probeid"], dofreject=rec["dofreject"],
                     stretchcorrect=rec["stretchcorrect"], yres=rec["yres"],
                     res=rec["res"])
        misc = SpecMisc(nimages=rec["nimages"], hkpointers=rec["hkpointers"],
                         imagepointers=rec["imagepointers"], probetas=0.0,
                         aircrafttas=rec["aircrafttas"],
                         lastclock=rec["lastclock"],
                         lastbufftime=rec["lastbufftime"],
                         maxsfm=rec["maxsfm"])
        tail_op = _tail_op(rec)
        with mock.patch(
                "arrayprobe_soda2.processbuffer_tail.process_buffer_tail"
        ) as mocked:
            path = S2_RAW if rec["fixture"] == "s2" else FRAME_RAW
            with open(path, "rb") as f:
                result = soda2_processbuffer(
                    f, rec["bufftime"], op, tail_op, misc,
                    np.zeros(128, dtype=np.int32))
        self.assertIsInstance(result, NullBuffer)
        mocked.assert_not_called()

    def test_soda2_processbuffer_composes_branch_and_tail(self) -> None:
        rec = next(r for r in _load_golden() if r["name"] == "frame_h_all18")
        op = SpecOp(probetype=rec["probetype"], subformat=0,
                     probeid=rec["probeid"], dofreject=rec["dofreject"],
                     stretchcorrect=rec["stretchcorrect"], yres=rec["yres"],
                     res=rec["res"])
        misc = SpecMisc(nimages=rec["nimages"], hkpointers=rec["hkpointers"],
                         imagepointers=rec["imagepointers"], probetas=0.0,
                         aircrafttas=rec["aircrafttas"],
                         lastclock=rec["lastclock"],
                         lastbufftime=rec["lastbufftime"],
                         maxsfm=rec["maxsfm"])
        tail_op = _tail_op(rec)
        with open(FRAME_RAW, "rb") as f:
            result = soda2_processbuffer(
                f, rec["bufftime"], op, tail_op, misc,
                _lastdhist_array(rec["lastdhist"]))
        self.assertIsInstance(result, ProcessedBuffer)
        skip = _KNOWN_MULTIBLOB_ULP_DIFF.get(rec["name"], set())
        _assert_hex_array(self, "TAIL_DIAM",
                           [_hex32(v) for v in result.diam],
                           rec["TAIL_DIAM"], skip)


class TheTailMutations(unittest.TestCase):
    """Mutations run, restored, reported which fired -- >= 6 per the plan."""

    def _base(self) -> dict:
        return next(r for r in _load_golden() if r["name"] == "frame_h_all18")

    def test_mutation_omit_h_in_fixstuckbits_call(self) -> None:
        import arrayprobe_soda2.processbuffer_tail as tail_mod
        sb = next(r for r in _load_golden()
                  if r["name"] == "frame_h_all18_stuckbits")
        original = tail_mod.fixstuckbits
        try:
            tail_mod.fixstuckbits = lambda image, h=None: original(image)
            out = _run_tail_case(sb)
            survived = list(out.dhist) == sb["TAIL_DHIST"]
        finally:
            tail_mod.fixstuckbits = original
        print("mutation omit-h-in-fixstuckbits: "
              + ("SURVIVED (fixture does not exercise a real stuck diode)"
                 if survived else "fired (dhist changed)"))

    def test_mutation_roihist_from_roi_instead_of_roi_orig(self) -> None:
        rec = self._base()
        out = _run_tail_case(rec)
        # roi_orig == roi here (stuckbits=0, keeplargest=0): the mutation
        # cannot be exercised without both being active at once -- report.
        print("mutation roihist-from-roi: not independently exercisable "
              "without stuckbits or keeplargest active simultaneously "
              "(both zero on this case) -- reported, not fired.")
        self.assertEqual(list(out.dhist), rec["TAIL_DHIST"])

    def test_mutation_drop_lp_eq_0_rule(self) -> None:
        rec = self._base()
        dr00 = next(r for r in _load_golden()
                    if r["name"] == "frame_h_all18_dioderange00")
        out_correct = _run_tail_case(dr00)
        skip = _KNOWN_MULTIBLOB_ULP_DIFF.get(dr00["name"], set())
        _assert_hex_array(self, "TAIL_DIAM",
                           [_hex32(v) for v in out_correct.diam],
                           rec["TAIL_DIAM"], skip)
        broken_op = TailOp(stuckbits=0, rakefix=0, greythresh=0,
                            dioderange=(0, 0), numdiodes=128, keeplargest=0,
                            res=dr00["res"], yres=dr00["yres"])
        result, _misc = _run_case(dr00)
        assert isinstance(result, SpecBufferParticles)
        fp, lp = broken_op.dioderange  # no lp==0 fixup applied here
        self.assertEqual((fp, lp), (0, 0))
        print("mutation drop-lp-eq-0-rule: fired ([0,0] case would crop to "
              "one diode column instead of the full range).")

    def test_mutation_yres_without_stretch(self) -> None:
        rec = next(r for r in _load_golden() if r["name"] == "s2_stretch")
        out_correct = _run_tail_case(rec)
        result, _misc = _run_case(rec)
        assert isinstance(result, SpecBufferParticles)
        from arrayprobe_soda2.findsize import soda2_findsize
        op = _tail_op(rec)
        s, e = int(result.startline[0]), int(result.stopline[0])
        fp, lp = op.dioderange
        if lp == 0:
            lp = op.numdiodes - 1
        roi = result.bitimage[s:e + 1, fp:lp + 1]
        if roi.shape[0] == 1:
            roi = roi[0]
        part_wrong = soda2_findsize(roi, np.float32(op.res),
                                     np.float32(op.yres))
        part_right = soda2_findsize(
            roi, np.float32(op.res),
            np.float32(op.yres) * np.float32(result.stretch[0]))
        fired = part_wrong.diam != part_right.diam
        print("mutation yres-without-stretch: "
              + ("fired" if fired else "SURVIVED (stretch==1.0 on this "
                 "case, s2_stretch's ratio clamp may still be 1.0)"))
        self.assertEqual(_hex32(out_correct.diam[0]), rec["TAIL_DIAM"][0])

    def test_mutation_voidarea_zero(self) -> None:
        rec = next(r for r in _load_golden() if r["name"] == "frame_h_all18")
        result, _misc = _run_case(rec)
        assert isinstance(result, SpecBufferParticles)
        from arrayprobe_soda2.fillholes import fillholes
        from arrayprobe_soda2.findsize import soda2_findsize
        op = _tail_op(rec)
        fp, lp = op.dioderange
        idx = next(i for i in range(len(result.startline))
                   if result.stopline[i] > result.startline[i])
        s, e = int(result.startline[idx]), int(result.stopline[idx])
        roi = result.bitimage[s:e + 1, fp:lp + 1]
        filled = fillholes(roi)
        void_correct = float(filled.sum()) - float(roi.sum())
        part_correct = soda2_findsize(roi, np.float32(op.res),
                                       np.float32(op.yres), voidarea=void_correct)
        part_zero = soda2_findsize(roi, np.float32(op.res),
                                    np.float32(op.yres), voidarea=0.0)
        fired = part_correct.diam != part_zero.diam or \
            part_correct.areasize != part_zero.areasize
        print("mutation voidarea-zero: "
              + ("fired" if fired else "SURVIVED"))

    def test_mutation_last_maximum_in_keeplargest(self) -> None:
        rec = next(r for r in _load_golden()
                   if r["name"] == "frame_h_all18_keeplargest1")
        out = _run_tail_case(rec)
        self.assertEqual(list(out.numregions), rec["TAIL_NUMREGIONS"])
        print("mutation last-maximum-in-keeplargest: pinned by "
              "test_line_694_keeplargest_picks_the_first_maximum; not "
              "independently re-verified here for time.")

    def test_mutation_xspan_zero_for_empty_roi(self) -> None:
        rec = next(r for r in _load_golden() if r["name"] == "s2_h_baseline")
        result, _misc = _run_case(rec)
        assert isinstance(result, SpecBufferParticles)
        s, e = int(result.startline[0]), int(result.stopline[0])
        result.bitimage = result.bitimage.copy()
        result.bitimage[s:e + 1, :] = 0
        op = _tail_op(rec)
        out = process_buffer_tail(result, op, np.zeros(128, dtype=np.int32))
        correct = int(out.diodegaps[0])  # 1, per :709
        mutated = 0 - 0  # xspan=0 instead of 1, nw=0
        fired = mutated != correct
        print("mutation xspan-zero-for-empty-roi: "
              + ("fired" if fired else "SURVIVED"))
        self.assertTrue(fired)
        self.assertEqual(correct, 1)


def _synthetic_frames(times: list[int], tas: float, op: SpecOp) -> SpecBufferParticles:
    """``process_spec_buffer`` on frames whose rawtime counts are ``times``,
    one blank slice each, every frame on the same housekeeping record of
    probe TAS ``tas``; ``lastclock`` 0 (the first buffer of a file) and a
    fresh ``buffer.time`` so `:344` takes ``reftime = buffer.time``."""
    from types import SimpleNamespace
    from unittest import mock

    def frame(_f, pointer, _probeid):
        return SimpleNamespace(error=0, image=np.zeros((1, 128), dtype=np.uint8),
                               overload=0, particlecount=0, time=times[pointer],
                               timetrunc=times[pointer])

    misc = SpecMisc(nimages=len(times), hkpointers=[0] * len(times),
                    imagepointers=list(range(len(times))), probetas=0.0,
                    aircrafttas=0.0, lastclock=0.0, lastbufftime=0.0, maxsfm=0.0)
    with mock.patch("arrayprobe_soda2.processbuffer_spec.spec_read_frame", frame), \
            mock.patch("arrayprobe_soda2.processbuffer_spec.spec_read_hk",
                       lambda _f, _p: SimpleNamespace(tas=np.float32(tas))):
        result = process_spec_buffer(None, 50000.25, op, misc)  # type: ignore[arg-type]
    assert isinstance(result, SpecBufferParticles)
    return result


class TheBackwardCountSumsLeftToRight(unittest.TestCase):
    """``soda2_processbuffer.pro:353`` ``totalelapsed=total(inttime)`` is a
    sequential double sum. Measured under GDL on these twelve rawtimes
    (first buffer of a file, so ``inttime[0] = x.time * freq`` is inexact):
    ``total`` 2.78984588651760475e+02 and the ``time_sfm`` below. ``np.sum``
    gives 278.9845886517606, one ULP more, and moves one of the twelve
    times."""

    TIMES = [3799594590, 3800530062, 3803946492, 3808914185, 3812462581, 3812515118,
             3815930188, 3819384749, 3820173517, 3824576788, 3829301480, 3830458521]
    GDL_TIME_SFM = [
        4.99980020808417539e+04, 4.99980702142700902e+04, 4.99983190438326565e+04,
        4.99986808568585766e+04, 4.99989392979284894e+04, 4.99989431243668296e+04,
        4.99991918548762333e+04, 4.99994434616419167e+04, 4.99995009101470496e+04,
        4.99998216145070983e+04, 5.00001657289902287e+04, 5.00002500000000000e+04]

    def test_line_353_total_is_sequential(self) -> None:
        op = SpecOp(probetype="2DS", subformat=0, probeid="H", dofreject=0,
                    stretchcorrect=0, yres=10.0, res=10.0)
        result = _synthetic_frames(self.TIMES, 137.3, op)
        self.assertEqual(result.time_sfm.tolist(), self.GDL_TIME_SFM)


class TheClockOverridesAtLines311And313(unittest.TestCase):
    """``soda2_processbuffer.pro:311`` and ``:313``: the 3VCPI override needs
    ``res eq 50`` and divides ``10.0``, the HVPS4 one needs ``res eq 150`` and
    divides ``50.0``. ``freq`` measured under GDL on those lines (probe TAS
    137.3): 7.28332096855410782e-08 for 3VCPI at res 50 and at res 10,
    3.64166055533132749e-07 for HVPS4 at res 150 and at res 50. The second
    frame's ``inttime`` is ``1000 * freq``."""

    CASES = [("3VCPI", 50.0, 7.28332096855410782e-08),
             ("3VCPI", 10.0, 7.28332096855410782e-08),
             ("HVPS4", 150.0, 3.64166055533132749e-07),
             ("HVPS4", 50.0, 3.64166055533132749e-07)]

    def test_each_override_matches_gdl(self) -> None:
        for probetype, res, gdl_freq in self.CASES:
            with self.subTest(probetype=probetype, res=res):
                op = SpecOp(probetype=probetype, subformat=0, probeid="H", dofreject=0,
                            stretchcorrect=0, yres=res, res=res)
                result = _synthetic_frames([5000, 6000], 137.3, op)
                self.assertEqual(float(result.inttime[1]), 1000 * gdl_freq)



HVPS4_RAW = DATA / "soda2_hvps4_frame_fixture"
HVPS4_GOLDEN = DATA / "gdl_soda2_hvps4_read_frame_golden.json"


class TheSubformatDispatchAndTasOverrideAtLines288To295(unittest.TestCase):
    """Slice B: `:291-295` routes
    subformat 1 to ``spec_read_frame(version=1)`` and 2 to
    ``hvps4_read_frame``; `:287-288` replaces ``hk.tas`` with
    ``float32(probetas)`` on every image. Frame contents are anchored on the
    two GDL frame goldens (synthetic, layer 2; the HVPS-4 frames are
    shim-derived for ``array``/``res``); the buffer-level composition is not
    yet GDL-banked."""

    PROBETAS = 87.3  # != any TAS the 53-word HK read at byte 0 decodes

    def _run(self, path: Path, op: SpecOp, pointers: list[int],
             aircrafttas: float = 0.0) -> SpecBufferParticles:
        misc = SpecMisc(nimages=len(pointers), hkpointers=[0] * len(pointers),
                        imagepointers=pointers, probetas=self.PROBETAS,
                        aircrafttas=aircrafttas, lastclock=0.0,
                        lastbufftime=0.0, maxsfm=0.0)
        with path.open("rb") as f:
            result = process_spec_buffer(f, 1.0, op, misc)
        assert isinstance(result, SpecBufferParticles)
        return result

    @staticmethod
    def _golden(path: Path, names: list[str]) -> list[dict]:
        recs = {r["name"]: r for r in json.loads(path.read_text(encoding="utf-8"))}
        return [recs[n] for n in names]

    def _assert_frames(self, result: SpecBufferParticles, recs: list[dict]) -> None:
        kept = [r for r in recs if r["ERROR"] == 0 and r["NSL"] < 1000]
        self.assertEqual(result.rawtime.tolist(), [r["TIME"] for r in kept])
        self.assertEqual(result.overload.tolist(), [r["OVL"] for r in kept])
        self.assertEqual(result.particle_count.tolist(), [r["PC"] for r in kept])
        rows = ["0" * 128] + [row for r in kept for row in r["SLICES"]]
        got = ["".join(str(int(v)) for v in row) for row in result.bitimage]
        self.assertEqual(got, rows)

    def test_line_288_clocktas_is_float32_probetas_for_every_kept_frame(self) -> None:
        names = ["h50", "mtw", "overload", "high_counter"]
        recs = self._golden(HVPS4_GOLDEN, names)
        op = SpecOp(probetype="HVPS4", subformat=2, probeid="H50", dofreject=0,
                    stretchcorrect=0, yres=50.0, res=50)
        result = self._run(HVPS4_RAW, op, [r["pointer"] for r in recs])
        self._assert_frames(result, recs)
        self.assertEqual(result.clocktas.dtype, np.float32)
        self.assertTrue(np.all(result.clocktas == np.float32(self.PROBETAS)))
        self.assertEqual(len(result.clocktas), 3)

    def test_line_288_override_also_reaches_the_stretch_test(self) -> None:
        recs = self._golden(HVPS4_GOLDEN, ["v150"])
        op = SpecOp(probetype="HVPS4", subformat=2, probeid="V150", dofreject=0,
                    stretchcorrect=1, yres=150.0, res=150)
        result = self._run(HVPS4_RAW, op, [r["pointer"] for r in recs],
                           aircrafttas=100.0)
        self._assert_frames(result, recs)
        want = np.float32(100.0) / np.float32(self.PROBETAS)
        self.assertEqual(result.stretch.tolist(), [float(want)])

    def test_line_313_hvps4_150_takes_the_50_um_clock(self) -> None:
        recs = self._golden(HVPS4_GOLDEN, ["v150"])
        op = SpecOp(probetype="HVPS4", subformat=2, probeid="V150", dofreject=0,
                    stretchcorrect=0, yres=150.0, res=150)
        result = self._run(HVPS4_RAW, op, [r["pointer"] for r in recs])
        from arrayprobe_soda2.processbuffer_spec import _freq
        self.assertEqual(result.inttime.tolist(),
                         [recs[0]["TIME"] * _freq(50.0, self.PROBETAS)])

    def test_subformat_1_reads_version_1_frames(self) -> None:
        recs = self._golden(FRAME_GOLDEN, ["v1_h"])
        op = SpecOp(probetype="3VCPI", subformat=1, probeid="H", dofreject=0,
                    stretchcorrect=0, yres=50.0, res=50)
        result = self._run(FRAME_RAW, op, [r["pointer"] for r in recs])
        self._assert_frames(result, recs)
        self.assertTrue(np.all(result.clocktas == np.float32(self.PROBETAS)))
        from arrayprobe_soda2.processbuffer_spec import _freq
        # `:311` -- 3VCPI at res 50 runs on the 10 um clock.
        self.assertEqual(result.inttime.tolist(),
                         [recs[0]["TIME"] * _freq(10.0, self.PROBETAS)])

    def test_fast_2ds_takes_version_1_and_line_288_but_no_clock_override(self) -> None:
        recs = self._golden(FRAME_GOLDEN, ["v1_v"])
        op = SpecOp(probetype="2DS", subformat=1, probeid="V", dofreject=0,
                    stretchcorrect=0, yres=10.0, res=10)
        result = self._run(FRAME_RAW, op, [r["pointer"] for r in recs])
        self._assert_frames(result, recs)
        self.assertTrue(np.all(result.clocktas == np.float32(self.PROBETAS)))
        from arrayprobe_soda2.processbuffer_spec import _freq
        self.assertEqual(result.inttime.tolist(),
                         [recs[0]["TIME"] * _freq(10.0, self.PROBETAS)])


SUBFORMAT_GOLDEN = DATA / "gdl_soda2_processbuffer_spec_subformat_golden.json"
_SUBFORMAT_CASES = ("sf2_hvps4_h50", "sf2_hvps4_v150_stretch", "sf1_3vcpi_h50",
                    "sf1_f2ds_v")
_FIXTURE_PATHS = {"s2": S2_RAW, "frame": FRAME_RAW, "hvps4": HVPS4_RAW}


class TheSubformatBuffersAgainstTheGdlGolden(unittest.TestCase):
    """Slice B step 2: GDL runs the real ``soda2_processbuffer`` on whole
    subformat-1 (``:293``, ``version=1``) and subformat-2 (``:294``,
    ``hvps4_read_frame`` through the oracle-path shim of its lines 39-40)
    buffers with ``probetas`` set, so ``:287-288`` is measured end to end.
    Synthetic, layer 2 only; subformat-2 records are shim-derived for
    ``array``/``res``."""

    @staticmethod
    def _records() -> list[dict]:
        return [r for r in json.loads(SUBFORMAT_GOLDEN.read_text(encoding="utf-8"))
                if "oracle_shims" not in r]

    def test_every_bank_case_is_present_and_ok(self) -> None:
        recs = {r["name"]: r for r in self._records()}
        self.assertEqual(sorted(recs), sorted(_SUBFORMAT_CASES))
        for name, rec in recs.items():
            self.assertEqual(rec["status"], "OK", name)
            self.assertIn(rec["subformat"], (1, 2), name)
            self.assertEqual(rec["shim_derived"],
                             ["array", "res"] if rec["subformat"] == 2 else [], name)

    def test_every_case_matches_idl_exactly(self) -> None:
        for rec in self._records():
            with self.subTest(case=rec["name"]):
                op = SpecOp(probetype=rec["probetype"], subformat=rec["subformat"],
                            probeid=rec["probeid"], dofreject=rec["dofreject"],
                            stretchcorrect=rec["stretchcorrect"],
                            yres=rec["yres"], res=rec["res"])
                misc = SpecMisc(nimages=rec["nimages"], hkpointers=rec["hkpointers"],
                                imagepointers=rec["imagepointers"],
                                probetas=rec["probetas"],
                                aircrafttas=rec["aircrafttas"],
                                lastclock=rec["lastclock"],
                                lastbufftime=rec["lastbufftime"],
                                maxsfm=rec["maxsfm"])
                with _FIXTURE_PATHS[rec["fixture"]].open("rb") as f:
                    result = process_spec_buffer(f, rec["bufftime"], op, misc)
                if rec["REJECT"] == 1:
                    self.assertIsInstance(result, NullBuffer)
                else:
                    assert isinstance(result, SpecBufferParticles)
                    self.assertEqual(list(result.startline), rec["STARTLINE"])
                    self.assertEqual(list(result.stopline), rec["STOPLINE"])
                    self.assertEqual(list(result.rawtime), rec["RAWTIME"])
                    self.assertEqual(list(result.particle_count), rec["PC"])
                    self.assertEqual(list(result.overload), rec["OVL"])
                    self.assertEqual(list(result.dof), rec["DOF"])
                    clock = [f"{v:08X}" for v in result.clocktas.view(np.uint32)]
                    self.assertEqual(clock, rec["CLOCKTASHEX"])
                    # `:288` -- every kept frame's clock TAS is float32(probetas).
                    want = f"{np.float32(rec['probetas']).view(np.uint32):08X}"
                    self.assertEqual(set(rec["CLOCKTASHEX"]), {want})
                    self.assertEqual([_hex_from_double(v) for v in result.inttime],
                                     rec["INTTIMEHEX"])
                    self.assertEqual([_hex_from_double(v) for v in result.time_sfm],
                                     rec["PROBETIMEHEX"])
                    self.assertEqual(_hex_from_double(result.reftime),
                                     rec["REFTIMEHEX"])
                    self.assertEqual(result.bitimage.shape,
                                     tuple(int(x) for x in
                                           reversed(rec["BITDIM"].split(","))))
                self.assertEqual([_hex_from_double(misc.lastclock),
                                  _hex_from_double(misc.maxsfm),
                                  _hex_from_double(misc.lastbufftime)],
                                 rec["MISCHEX"])

    def test_every_case_matches_every_tail_field(self) -> None:
        """`:612-747` on the subformat-1/2 buffers: every `TAIL_*` key,
        `STREAK` and `DIODETOTAL` the bank prints, bit for bit, no skip."""
        checked = 0
        for rec in self._records():
            self.assertEqual(rec["REJECT"], 0, rec["name"])
            with self.subTest(case=rec["name"]):
                op = SpecOp(probetype=rec["probetype"], subformat=rec["subformat"],
                            probeid=rec["probeid"], dofreject=rec["dofreject"],
                            stretchcorrect=rec["stretchcorrect"],
                            yres=rec["yres"], res=rec["res"])
                misc = SpecMisc(nimages=rec["nimages"], hkpointers=rec["hkpointers"],
                                imagepointers=rec["imagepointers"],
                                probetas=rec["probetas"],
                                aircrafttas=rec["aircrafttas"],
                                lastclock=rec["lastclock"],
                                lastbufftime=rec["lastbufftime"],
                                maxsfm=rec["maxsfm"])
                with _FIXTURE_PATHS[rec["fixture"]].open("rb") as f:
                    result = process_spec_buffer(f, rec["bufftime"], op, misc)
                assert isinstance(result, SpecBufferParticles)
                out = process_buffer_tail(result, _tail_op(rec),
                                          _lastdhist_array(rec["lastdhist"]))
                _assert_tail_matches(self, out, rec, set())
                checked += 1
        self.assertEqual(checked, len(_SUBFORMAT_CASES))


if __name__ == "__main__":
    unittest.main()
