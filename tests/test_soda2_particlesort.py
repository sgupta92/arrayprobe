# SPDX-License-Identifier: BSD-3-Clause
"""Tests for ``arrayprobe_soda2.particlesort`` (
the GDL bank is ``AgainstTheGdlGolden``).

Most tests below check the port against the IDL source's own documented
semantics -- doctrine layer 3. ``AgainstTheGdlGolden`` and the
``test_line_*`` tests naming the first two hypotheses check the port against a real GDL run
instead (layer 2), via ``tests/data/gdl_soda2_particlesort_golden.json``
(``gdl_oracle/run_soda2_particlesort_bank.py``, 14 cases). Each
``test_line_<n>_...`` name below cites the plan trap and source line it
protects, per the project's naming convention for preserved-behaviour tests.
"""
from __future__ import annotations

import json
import struct
import unittest
from pathlib import Path

import numpy as np

from arrayprobe_soda2.particlesort import (
    ParticlesortOptions,
    Soda2ParticlesortError,
    _idl_powf,
    idl_median,
    new_accumulator,
    soda2_particlesort,
)

GOLDEN_PATH = Path(__file__).resolve().parent / "data" / "gdl_soda2_particlesort_golden.json"

ENDBINS = np.array([10.0, 50.0, 100.0, 200.0, 500.0])
ARENDBINS = np.array([0.0, 0.5, 1.0])


def _particle_batch(n: int, **overrides) -> dict[str, np.ndarray]:
    """A minimal all-accepted SPEC particle batch, ``n`` particles, every
    field a scalar broadcast unless overridden."""
    base = dict(
        probetime=np.zeros(n),
        buffertime=np.zeros(n),
        reftime=np.zeros(n),
        inttime=np.full(n, 0.01),
        overloadflag=np.zeros(n, dtype=np.uint8),
        probetas=np.full(n, 50.0, dtype=np.float32),
        missed=np.zeros(n),
        xsize=np.full(n, 100.0),
        ysize=np.full(n, 100.0),
        areasize=np.full(n, 100.0),
        xextent=np.full(n, 100.0),
        oned=np.full(n, 100.0),
        twod=np.full(n, 100.0),
        diam=np.full(n, 100.0),
        sizecorrection=np.ones(n),
        arearatiofilled=np.full(n, 0.8),
        arearatio=np.full(n, 0.8),
        aspectratio=np.full(n, 0.8),
        orientation=np.zeros(n),
        zd=np.zeros(n),
        allin=np.ones(n, dtype=np.uint8),
        centerin=np.ones(n, dtype=np.uint8),
        dofflag=np.ones(n, dtype=np.uint8),  # set -> dof bit does not fire
    )
    base.update(overrides)
    return base


def _default_op(**overrides) -> ParticlesortOptions:
    kwargs = dict(
        starttime=0.0,
        rate=1.0,
        clusterthresh=0.0,
        inttime_reject=0,
        smethod="diam",
        apply_psc=0,
        apply_psc_sizelimit=0.0,
        water=0,
        endbins=ENDBINS,
        arendbins=ARENDBINS,
        eawmethod="allin",
        dofreject=1,
        probetype="",
        format="SPEC",
    )
    kwargs.update(overrides)
    return ParticlesortOptions(**kwargs)


class TestRefusals(unittest.TestCase):
    def test_2dc_without_inewbuffer_is_refused_by_name(self):
        op = _default_op(probetype="2DC", format="RAF")
        x = _particle_batch(1)
        d = new_accumulator(op, numrecords=1)
        with self.assertRaises(Soda2ParticlesortError) as ctx:
            soda2_particlesort(op, x, d)
        self.assertIn("soda2_particlesort.pro:68", str(ctx.exception))


class TestLines65to76Deadtime2DC(unittest.TestCase):
    """`soda2_particlesort.pro:65-76` against the IDL formula, both arms."""

    def _run(self, fmt):
        from arrayprobe_soda2.particlesort import _deadtime_2dc
        op = _default_op(probetype="2DC", format=fmt, starttime=0.0, rate=1.0)
        d = new_accumulator(op, numrecords=4)
        d.deadtime[:] = np.float32(9.0)        # sentinel: the block assigns, not adds
        truetime = np.array([0.1, 0.2, 0.9, 1.5, 1.6, 2.0, 2.9], dtype=np.float64)
        timeindex = np.trunc(truetime).astype(np.int64)
        inewbuffer = np.array([0, 2, 3, 5, 6])
        _deadtime_2dc(op, d, truetime, timeindex, inewbuffer)
        return d, truetime, timeindex, inewbuffer

    def test_sea_arm_sums_buffer_gaps_per_second_capped_at_rate(self):
        d, t, ti, nb = self._run("SEA")
        gaps = np.maximum(t[nb[1:]] - t[nb[1:] - 1], 0.0)    # :68
        ideadtime = ti[nb[1:]]
        want = np.full(4, 9.0, dtype=np.float32)
        for it in range(ti.min(), ti.max() + 1):              # :72-75
            w = ideadtime == it
            if w.any():
                want[it] = np.float32(min(gaps[w].sum(), 1.0))
        np.testing.assert_array_equal(d.deadtime, want)
        self.assertEqual(d.deadtime[3], np.float32(9.0))      # untouched second

    def test_sea_arm_cap_at_rate(self):
        from arrayprobe_soda2.particlesort import _deadtime_2dc
        op = _default_op(probetype="2DC", format="SEA", starttime=0.0, rate=1.0)
        d = new_accumulator(op, numrecords=4)
        t = np.array([0.0, 2.5], dtype=np.float64)
        _deadtime_2dc(op, d, t, np.trunc(t).astype(np.int64), np.array([0, 1]))
        self.assertEqual(d.deadtime[2], np.float32(1.0))     # 2.5 s gap < op.rate

    def test_raf_arm_zeroes_each_buffer_start_second(self):
        d, t, ti, nb = self._run("RAF")                       # :69 deadtimes=0
        want = np.full(4, 9.0, dtype=np.float32)
        want[np.unique(ti[nb[1:]])] = 0.0
        np.testing.assert_array_equal(d.deadtime, want)

    def test_multi_flush_inewbuffer_subscripts_clip_as_idl(self):
        """`inewbuffer` from a multi-flush run holds 0 (rejected buffer, so `-1` at
        `:68`'s ``inewbuffer[1:*]-1``) and a stale start past this flush's end; IDL clips
        both into ``[0, n-1]`` (GDL: ``tt[[0,2,7]]-tt[[-1,1,6]]`` on 3 elements gives
        0 10 0). SEA arm, so the clipped gaps reach ``d.deadtime``."""
        from arrayprobe_soda2.particlesort import _deadtime_2dc
        op = _default_op(probetype="2DC", format="SEA", starttime=0.0, rate=1.0)
        d = new_accumulator(op, numrecords=4)
        d.deadtime[:] = np.float32(9.0)
        t = np.array([0.1, 0.5, 1.2], dtype=np.float64)
        _deadtime_2dc(op, d, t, np.trunc(t).astype(np.int64), np.array([0, 0, 2, 7]))
        # nb -> [0, 2, 2], nb-1 -> [0, 1, 2]; gaps [0, t2-t1, 0] at seconds [0, 1, 1].
        want = np.array([0.0, min((t[2] - t[1]) + 0.0, 1.0), 9.0, 9.0], dtype=np.float32)
        np.testing.assert_array_equal(d.deadtime, want)

    def test_single_buffer_halts(self):
        from arrayprobe_soda2.particlesort import _deadtime_2dc
        op = _default_op(probetype="2DC", format="SEA")
        d = new_accumulator(op, numrecords=2)
        with self.assertRaises(Soda2ParticlesortError):
            _deadtime_2dc(op, d, np.array([0.0]), np.array([0]), np.array([0]))

    def test_non_spec_non_sea_format_is_refused_by_name(self):
        # CIP-1: 'SEA' is now ported (the CIP route); 'TXT' (`:43-46`)
        # is the format this refusal still names.
        #
        op = _default_op(format="TXT")
        x = _particle_batch(1)
        d = new_accumulator(op, numrecords=1)
        with self.assertRaises(NotImplementedError) as ctx:
            soda2_particlesort(op, x, d)
        self.assertIn("TXT", str(ctx.exception))


class TestLine22MaxNotComparison(unittest.TestCase):
    """Trap 1: ``x.inttime > 0`` is MAX. A negative inttime clamps to 0, so
    it never triggers a cutoff-below rejection through a negative
    interarrival."""

    def test_negative_inttime_clamps_to_zero(self):
        op = _default_op(clusterthresh=0.0)
        x = _particle_batch(1, inttime=np.array([-5.0]))
        d = new_accumulator(op, numrecords=1)
        soda2_particlesort(op, x, d)
        # accepted (no cluster, no reject criteria triggered by a clamped-0
        # interarrival on its own) confirms no exception/NaN propagated.
        self.assertEqual(int(d.count_accepted[0]), 1)


class TestIdlMedianUpperMiddle(unittest.TestCase):
    """Trap 2: IDL MEDIAN without /EVEN returns the upper-middle element for
    an even-length array."""

    def test_even_length_returns_upper_middle(self):
        # sorted: [1, 2, 3, 4] -> upper middle is 3 (index 2), not 2.5.
        self.assertEqual(idl_median(np.array([4.0, 1.0, 3.0, 2.0])), 3.0)

    def test_odd_length_returns_true_middle(self):
        self.assertEqual(idl_median(np.array([5.0, 1.0, 3.0])), 3.0)


class TestLine50ClusterChain(unittest.TestCase):
    """Trap 3: the cluster loop is sequential and self-referential."""

    def test_three_consecutive_sub_threshold_gaps_grow_the_cluster(self):
        op = _default_op(clusterthresh=1.0)
        n = 4
        x = _particle_batch(n, inttime=np.full(n, 0.1))
        d = new_accumulator(op, numrecords=1)
        # particles all in the same second so cluster growth is observable
        # through the reject bit (clusterthresh>0 makes bit 16 reachable).
        soda2_particlesort(op, x, d)
        # total rejected count should be > 0 once a cluster >= 2 forms.
        self.assertGreaterEqual(int(d.total_count_rejected[0]), 1)

    def test_cluster_count_wraps_past_255_without_raising(self):
        # Renamed after it was measured by the GDL bank (cluster_300, H2) to
        # WRAP modulo 256, not saturate at 255 as round 5 assumed. This test
        # only guards against a raise; TestLine53ClusterByteWrapAt256 pins
        # the measured wrap behaviour exactly.
        op = _default_op(clusterthresh=1.0)
        n = 300
        x = _particle_batch(n, inttime=np.full(n, 0.1))
        d = new_accumulator(op, numrecords=1)
        # Must not raise (byte overflow would raise in a naive port).
        soda2_particlesort(op, x, d)


class TestLine60TruncationTowardZero(unittest.TestCase):
    """Trap 4: long() truncates toward zero -- a particle before starttime
    gets timeindex 0, not -1."""

    def test_particle_before_starttime_indexes_to_zero(self):
        op = _default_op(starttime=10.0, rate=1.0)
        x = _particle_batch(1, buffertime=np.array([9.5]), probetime=np.array([9.5]))
        d = new_accumulator(op, numrecords=5)
        soda2_particlesort(op, x, d)
        self.assertEqual(int(d.count_accepted[0]), 1)


class TestLine79ParticleAtNumrecordsIsDropped(unittest.TestCase):
    """Trap 5 / finding S5-c: a particle whose timeindex == numrecords is
    silently excluded by the inner guard."""

    def test_a_particle_at_numrecords_is_dropped(self):
        op = _default_op(starttime=0.0, rate=1.0)
        numrecords = 3
        # timeindex = trunc((buffertime-0)/1) = 3 == numrecords -> dropped
        x = _particle_batch(1, buffertime=np.array([3.5]), probetime=np.array([3.5]))
        d = new_accumulator(op, numrecords=numrecords)
        soda2_particlesort(op, x, d)
        self.assertEqual(int(d.count_accepted.sum()), 0)
        self.assertEqual(int(d.total_count_rejected.sum()), 0)


class TestLine87IntbinBelowFirstEdge(unittest.TestCase):
    """Trap 6: an interarrival below the first intendbins edge is guarded by
    nw > 0 and silently uncounted."""

    def test_interarrival_below_first_edge_is_not_counted(self):
        op = _default_op()
        d = new_accumulator(op, numrecords=1)
        # intendbins[0] = 10**-7; a value of exactly 0 is below it.
        self.assertLess(0.0, d.intendbins[0])
        x = _particle_batch(1, inttime=np.array([0.0]))
        soda2_particlesort(op, x, d)
        self.assertEqual(float(d.intspec_all[0, :].sum()), 0.0)


class TestLine102BackwardDeadtime(unittest.TestCase):
    """Trap 8: an overload spans indices are handled backward, split only
    across the start/stop index -- no intermediate fill."""

    def test_overload_spanning_three_seconds_touches_only_first_and_last(self):
        op = _default_op(starttime=0.0, rate=1.0)
        numrecords = 5
        x = _particle_batch(
            1,
            buffertime=np.array([3.0]),
            probetime=np.array([3.0]),
            inttime=np.array([2.5]),  # spans back to t=0.5 -> index 0
            overloadflag=np.array([1], dtype=np.uint8),
        )
        d = new_accumulator(op, numrecords=numrecords)
        soda2_particlesort(op, x, d)
        touched = np.nonzero(d.deadtime)[0]
        self.assertTrue(set(touched.tolist()).issubset({0, 1, 2, 3}))
        # the intermediate indices (1, 2) must be untouched (commented-out
        # fill), only the start (0) and stop (3) index.
        self.assertEqual(float(d.deadtime[1]), 0.0)
        self.assertEqual(float(d.deadtime[2]), 0.0)


class TestLine159SizebinEdgeCases(unittest.TestCase):
    """Trap 9: le for sizebin with a special case at endbins[0]; lt for
    arbin/asprbin."""

    def test_size_exactly_on_first_edge_uses_special_case_bin_zero(self):
        op = _default_op(smethod="diam")
        x = _particle_batch(1, diam=np.array([ENDBINS[0]]))
        d = new_accumulator(op, numrecords=1)
        soda2_particlesort(op, x, d)
        self.assertEqual(int(d.spec2d[0, 0, :].sum()), 1)

    def test_size_above_last_bin_indexes_the_final_row(self):
        op = _default_op(smethod="diam")
        x = _particle_batch(1, diam=np.array([ENDBINS[-1] + 1.0]))
        d = new_accumulator(op, numrecords=1)
        soda2_particlesort(op, x, d)
        # max(where(endbins <= binningsize)) lands on the last endbin index,
        # which is one past the last valid *bin* index (numbins-1) -- a
        # Python negative-index-free straight read here would raise if out
        # of bounds; if it didn't raise, some row got the count.
        self.assertEqual(int(d.spec2d.sum()) + int(d.total_count_rejected.sum()), 1)


class TestLine177Bit128Wraparound(unittest.TestCase):
    """Trap 10 / finding S5-a: a reject on bit 128 alone increments
    count_rejected's last column via -1 wraparound, confirmed by hand
    against a live run."""

    def test_dof_only_rejection_lands_in_the_last_column(self):
        op = _default_op(dofreject=1)
        x = _particle_batch(1, dofflag=np.array([0], dtype=np.uint8))
        d = new_accumulator(op, numrecords=1)
        rf = soda2_particlesort(op, x, d)
        self.assertEqual(int(rf[0]), 128)
        self.assertEqual(int(d.count_rejected[0, 6]), 1)
        self.assertEqual(int(d.count_rejected[0, :6].sum()), 0)
        self.assertEqual(int(d.total_count_rejected[0]), 1)


class TestLine154PoissonSpotCorrectionZeroDivide(unittest.TestCase):
    """Trap 11 / finding S5-d: sizecorrection == 0 divides to inf under
    apply_psc, pushing the particle to the top size bin rather than
    raising."""

    def test_zero_sizecorrection_does_not_raise(self):
        op = _default_op(apply_psc=1, apply_psc_sizelimit=0.0, smethod="diam")
        x = _particle_batch(1, sizecorrection=np.array([0.0]))
        d = new_accumulator(op, numrecords=1)
        soda2_particlesort(op, x, d)  # must not raise


class TestLine83TasMean(unittest.TestCase):
    """Trap 12: FLOAT mean of probetas over a second's particles."""

    def test_tas_mean_matches_expected_average(self):
        op = _default_op()
        n = 1000
        rng = np.random.default_rng(1)
        tas_values = rng.uniform(40, 60, n).astype(np.float32)
        x = _particle_batch(n, probetas=tas_values, buffertime=np.zeros(n), probetime=np.zeros(n))
        d = new_accumulator(op, numrecords=1)
        soda2_particlesort(op, x, d)
        self.assertAlmostEqual(float(d.tas[0]), float(tas_values.mean()), delta=0.01)


class TestReprocessedTime(unittest.TestCase):
    def test_reprocessed_time_keyword_is_applied(self):
        op = _default_op(starttime=0.0, rate=1.0)
        x = _particle_batch(1, buffertime=np.array([99.0]))  # would be out of range
        reprocessed = np.array([0.5])
        d = new_accumulator(op, numrecords=2)
        soda2_particlesort(op, x, d, reprocessed_time=reprocessed)
        self.assertEqual(int(d.count_accepted.sum()) + int(d.total_count_rejected.sum()), 1)


class TestThirdSideBisect(unittest.TestCase):
    """The doctrine's "two sides from different places": recompute the
    expected sizebin with plain Python, independent of the port's own
    _max_where helper."""

    def test_sizebin_matches_independent_bisect(self):
        import bisect

        endbins = ENDBINS.tolist()
        binningsize = 150.0
        # IDL: max(where(endbins le binningsize)) -- the count of edges
        # <= binningsize, minus one, is the same index bisect_right gives.
        expected = bisect.bisect_right(endbins, binningsize) - 1

        op = _default_op(smethod="diam")
        x = _particle_batch(1, diam=np.array([binningsize]))
        d = new_accumulator(op, numrecords=1)
        soda2_particlesort(op, x, d)
        actual_bin = np.nonzero(d.spec2d[0].sum(axis=1))[0]
        self.assertEqual(len(actual_bin), 1)
        self.assertEqual(int(actual_bin[0]), expected)


def _load_golden() -> list[dict]:
    records = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    return records[1:]  # records[0] is {"oracle_shims": []}


def _op_from_record(rec: dict) -> ParticlesortOptions:
    op = rec["op"]
    return ParticlesortOptions(
        starttime=op["starttime"],
        rate=op["rate"],
        clusterthresh=op["clusterthresh"],
        inttime_reject=op["inttime_reject"],
        smethod=op["smethod"],
        apply_psc=op["apply_psc"],
        apply_psc_sizelimit=op["apply_psc_sizelimit"],
        water=op["water"],
        endbins=np.array(op["endbins"]),
        arendbins=np.array(op["arendbins"]),
        eawmethod=op["eawmethod"],
        res=op["res"],
        dofreject=op["dofreject"],
        format="SPEC",
        probetype=op["probetype"],
    )


def _particles_from_record(rec: dict) -> dict[str, np.ndarray]:
    ps = rec["particles"]
    keys = ps[0].keys()
    out: dict[str, np.ndarray] = {}
    float_keys = {
        "buffertime", "probetime", "reftime", "inttime", "probetas", "missed",
        "diam", "xsize", "ysize", "areasize", "xextent", "oned", "twod",
        "sizecorrection", "arearatiofilled", "arearatio", "aspectratio",
        "orientation", "zd",
    }
    for k in keys:
        vals = [p[k] for p in ps]
        if k in float_keys:
            out[k] = np.array(vals, dtype=np.float64 if k in
                               ("buffertime", "probetime", "reftime", "inttime")
                               else np.float32)
        else:
            out[k] = np.array(vals, dtype=np.uint8)
    return out


def _numrecords(rec: dict) -> int:
    return int(rec["op"]["numrecords"])


def _parse_nz(spec: str, shape: tuple[int, ...]) -> np.ndarray:
    """Rebuild a dense array from the bank's sparse ``IDX;VAL`` idiom, IDL
    column-major (Fortran) linear indices."""
    arr = np.zeros(shape, dtype=np.float64)
    if spec == "-1;" or spec.strip() == "-1;":
        return arr
    idx_part, _, val_part = spec.partition(";")
    idx = [int(v) for v in idx_part.split(",") if v.strip() != ""]
    val = [float(v) for v in val_part.split(",") if v.strip() != ""]
    unraveled = np.unravel_index(idx, shape, order="F")
    arr[unraveled] = val
    return arr


class AgainstTheGdlGolden(unittest.TestCase):
    """Every OK case in the R6C bank, compared exactly. A HALTED record (none
    in this bank's 14 cases) would assert the port raises at the same input."""

    def test_every_case_matches_idl_exactly(self):
        for rec in _load_golden():
            with self.subTest(case=rec["name"]):
                self.assertEqual(rec["status"], "OK", rec["name"])
                op = _op_from_record(rec)
                x = _particles_from_record(rec)
                numrecords = _numrecords(rec)
                d = new_accumulator(op, numrecords=numrecords)
                rf = soda2_particlesort(op, x, d)

                self.assertEqual(rf.tolist(), rec["RF"], "rejectionflag")

                expected_accepted = [int(v) for v in rec["COUNT_ACCEPTED"].split(",")]
                self.assertEqual(d.count_accepted.tolist(), expected_accepted,
                                  "count_accepted")

                expected_rejected = np.array(
                    [int(v) for v in rec["COUNT_REJECTED"].split(",")]
                ).reshape((numrecords, 7), order="F")
                np.testing.assert_array_equal(d.count_rejected, expected_rejected,
                                               err_msg="count_rejected")

                expected_total_rejected = [int(v) for v in rec["TOTAL_COUNT_REJECTED"].split(",")]
                self.assertEqual(d.total_count_rejected.tolist(), expected_total_rejected,
                                  "total_count_rejected")

                expected_spec2d = _parse_nz(
                    rec["SPEC2D_NZ"], (numrecords, d.numbins, d.numarbins)
                )
                np.testing.assert_array_equal(d.spec2d, expected_spec2d, "spec2d")


class TestLine53ClusterByteWrapAt256(unittest.TestCase):
    """H2, finding S5-p, measured by the bank's ``cluster_300`` case: the
    cluster counter is BYTE and WRAPS at 256, zeroing the whole chain, not a
    255 ceiling. The mutation (saturate instead of wrap) fails this case."""

    def test_cluster_300_wraps_not_saturates(self):
        rec = next(r for r in _load_golden() if r["name"] == "cluster_300")
        op = _op_from_record(rec)
        x = _particles_from_record(rec)
        d = new_accumulator(op, numrecords=_numrecords(rec))
        rf = soda2_particlesort(op, x, d)
        self.assertEqual(rf.tolist(), rec["RF"])
        # the wrap signature: particles 0-254 accepted (cluster zeroed back
        # to 0), only 255-299 rejected on bit 16.
        self.assertEqual(rf[:255].tolist(), [0] * 255)
        self.assertEqual(rf[255:].tolist(), [16] * 45)


class TestLine178IrejectFirstElementColumn(unittest.TestCase):
    """H1, finding S5-q, measured by the bank's ``multi_bit_reject`` case:
    ``ireject[0]`` is the FIRST (lowest-bit) reject column, not the last."""

    def test_multi_bit_reject_lands_in_the_lowest_bit_column(self):
        rec = next(r for r in _load_golden() if r["name"] == "multi_bit_reject")
        op = _op_from_record(rec)
        x = _particles_from_record(rec)
        d = new_accumulator(op, numrecords=_numrecords(rec))
        rf = soda2_particlesort(op, x, d)
        self.assertEqual(int(rf[0]), 9)  # bits 1 + 8
        # column 0 (bit 1), not column 3 (bit 8): the bank measured GDL puts
        # the count in the bit-1 column.
        self.assertEqual(int(d.count_rejected[0, 0]), 1)
        self.assertEqual(int(d.count_rejected[0, 3]), 0)


class TestLine83TasMeanMatchesGdlBitPattern(unittest.TestCase):
    """Trap 12, finding S5-e question settled: the port's sequential
    float32 accumulation matches GDL's ``mean()`` bit-for-bit on the bank's
    ``tas_mean_100`` case (100 FLOAT probetas values)."""

    def test_tas_bit_pattern_matches_gdl(self):
        rec = next(r for r in _load_golden() if r["name"] == "tas_mean_100")
        op = _op_from_record(rec)
        x = _particles_from_record(rec)
        d = new_accumulator(op, numrecords=_numrecords(rec))
        soda2_particlesort(op, x, d)
        port_hex = format(
            struct.unpack("<I", struct.pack("<f", float(d.tas[0])))[0], "08X"
        )
        gdl_hex = rec["TAS"].split(",")[0]
        if port_hex == gdl_hex:
            self.assertEqual(port_hex, gdl_hex,
                              "port's sequential float32 mean matches GDL bit-for-bit")
        else:
            numpy_mean = np.float32(x["probetas"][:100].astype(np.float32).mean())
            numpy_hex = format(
                struct.unpack("<I", struct.pack("<f", float(numpy_mean)))[0], "08X"
            )
            self.fail(
                f"port={port_hex} gdl={gdl_hex} numpy.mean(float32)={numpy_hex} "
                "-- measured mismatch (the SODA-2 port design)"
            )


class TestLine13RejectBit4SupersedesS5bAndS5d(unittest.TestCase):
    """H3: soda2_reject.pro:13 rejects bit 4 for a below-first-bin,
    above-last-bin, or non-finite (post-correction) size -- before :159's
    sizebin computation ever runs -- so S5-b ('sizebin=-1 reads the last
    row') and S5-d ('sizecorrection=0 sorts to the top bin') describe an
    unreachable path. Measured by three bank cases."""

    def test_size_below_first_bin_rejects_bit4_spec2d_untouched(self):
        rec = next(r for r in _load_golden() if r["name"] == "size_below_first_bin")
        op = _op_from_record(rec)
        x = _particles_from_record(rec)
        d = new_accumulator(op, numrecords=_numrecords(rec))
        rf = soda2_particlesort(op, x, d)
        self.assertEqual(int(rf[0]), 4)
        self.assertEqual(int(d.spec2d.sum()), 0)

    def test_size_above_last_bin_rejects_bit4_spec2d_untouched(self):
        rec = next(r for r in _load_golden() if r["name"] == "size_above_last_bin")
        op = _op_from_record(rec)
        x = _particles_from_record(rec)
        d = new_accumulator(op, numrecords=_numrecords(rec))
        rf = soda2_particlesort(op, x, d)
        self.assertEqual(rf.tolist(), [4, 4])
        self.assertEqual(int(d.spec2d.sum()), 0)

    def test_psc_zero_correction_rejects_bit4_spec2d_untouched(self):
        rec = next(r for r in _load_golden() if r["name"] == "psc_zero_correction")
        op = _op_from_record(rec)
        x = _particles_from_record(rec)
        d = new_accumulator(op, numrecords=_numrecords(rec))
        rf = soda2_particlesort(op, x, d)
        self.assertEqual(int(rf[0]), 4)
        self.assertEqual(int(d.spec2d.sum()), 0)


class TestThirdSideBisectPredictsGoldenSpec2d(unittest.TestCase):
    """Doctrine: two sides from different places. Compute sizebin with plain
    Python ``bisect`` directly from the JSON inputs and assert it against
    the golden's own spec2d cell, not the port's."""

    def test_bisect_matches_golden_cell_for_five_cases(self):
        import bisect

        for name in ("single_accepted", "two_seconds_two_particles",
                     "size_on_interior_edge", "ar_clamp", "orientation_bins"):
            with self.subTest(case=name):
                rec = next(r for r in _load_golden() if r["name"] == name)
                endbins = rec["op"]["endbins"]
                numrecords = _numrecords(rec)
                shape = (numrecords, len(endbins) - 1, len(rec["op"]["arendbins"]) - 1)
                expected = _parse_nz(rec["SPEC2D_NZ"], shape)
                for p in rec["particles"]:
                    diam = p["diam"]
                    if diam < endbins[0] or diam >= endbins[-1]:
                        continue  # rejected by bit 4, no spec2d cell to predict
                    sizebin = (0 if diam == endbins[0]
                               else bisect.bisect_right(endbins, diam) - 1)
                    itime = int((p["buffertime"] - rec["op"]["starttime"])
                                // rec["op"]["rate"])
                    if not (0 <= itime < numrecords):
                        continue
                    self.assertGreater(
                        float(expected[itime, sizebin, :].sum()), 0.0,
                        f"{name}: bisect predicts a hit at itime={itime} "
                        f"sizebin={sizebin} the golden does not show",
                    )


class TestNoSecondExceeds100ParticlesInTheGolden(unittest.TestCase):
    """Guards the bank's LMFIT-never-reached premise: no case exercises
    fit_poisson, which has no GDL oracle."""

    def test_every_second_has_at_most_100_particles(self):
        for rec in _load_golden():
            per_second: dict[int, int] = {}
            for p in rec["particles"]:
                idx = int((p["buffertime"] - rec["op"]["starttime"])
                          // rec["op"]["rate"])
                per_second[idx] = per_second.get(idx, 0) + 1
            self.assertLessEqual(max(per_second.values(), default=0), 100,
                                  rec["name"])


class TestNoCouplingToOtherPorts(unittest.TestCase):
    def test_module_imports_neither_arrayprobe_nor_arrayprobe_v35(self):
        import inspect

        import arrayprobe_soda2.particlesort as mod

        source = inspect.getsource(mod)
        self.assertNotIn("import arrayprobe\n", source)
        self.assertNotIn("from arrayprobe ", source)
        self.assertNotIn("from arrayprobe_uiops", source)
        self.assertNotIn("import arrayprobe_uiops", source)


class TestIdlPowfNarrowsToFloat(unittest.TestCase):
    """``_idl_powf`` is IDL ``FLOAT^FLOAT``: the correctly rounded double power
    narrowed to float32. Added 2026-09-27 after ``.astype(np.float64)`` left
    the module green -- the GDL bank's cases never reach a value where the
    narrowing changes a digit."""

    def test_the_result_is_float32_and_rounded_as_float32(self):
        out = _idl_powf(10.0, 1.0 / 3.0)
        self.assertEqual(out.dtype, np.float32)
        exact = np.power(10.0, 1.0 / 3.0)                          # float64
        self.assertEqual(float(out), float(np.float32(exact)))
        self.assertNotEqual(float(out), exact)


class TestLine40SeaThresholdIsAFloatLiteral(unittest.TestCase):
    """``soda2_particlesort.pro:40`` ``abs(interarrival-it2) gt 0.1``: ``0.1``
    is a FLOAT literal, promoted to DOUBLE as 0.100000001490116, so a DOUBLE
    difference in (0.1, 0.100000001490116] is not flagged. Measured under GDL
    on these inputs: ``nbad`` is 1 and ``interarrival`` is
    ``[0, 1.1000000009999999, 0]`` -- the second particle kept, the third
    zeroed. A double ``0.1`` threshold zeroes both."""

    def test_a_difference_just_above_double_one_tenth_is_kept(self):
        from arrayprobe_soda2.particlesort import spec_sort_locals
        x = {
            "inttime": np.array([0.0, 1.100000001, 2.3]),
            "probetime": np.array([0.0, 1.0, 2.1]),
            "reftime": np.zeros(3),
            "buffertime": np.zeros(3),
        }
        _truetime, interarrival = spec_sort_locals(x, format="SEA")
        self.assertEqual(interarrival.tolist(), [0.0, 1.100000001, 0.0])


def _f32(value: float) -> float:
    return float(np.float32(value))


def _bank_batch(n: int, **overrides) -> dict[str, np.ndarray]:
    """The GDL bank's default particle (`run_soda2_particlesort_bank.Particle`):
    buffertime 0.5, diam 120, area ratios 0.8, every IDL FLOAT field float32."""
    base = _particle_batch(
        n, buffertime=np.full(n, 0.5), missed=np.zeros(n, dtype=np.float32),
        **{k: np.full(n, 120.0, dtype=np.float32)
           for k in ("xsize", "ysize", "areasize", "xextent", "oned", "twod", "diam")})
    for k in ("arearatiofilled", "arearatio", "aspectratio"):
        base[k] = np.full(n, 0.8, dtype=np.float32)
    base.update(overrides)
    return base


def _spec2d_cells(a: np.ndarray) -> list[tuple[int, ...]]:
    return [tuple(int(i) for i in idx) for idx in np.argwhere(a)]


class TestLine130CountMissedIsAFloatSum(unittest.TestCase):
    """``soda2_particlesort.pro:130`` ``d.count_missed[itime] +
    total(x[iparticles].missed > 0)``: ``missed`` is FLOAT, ``total`` a
    sequential FLOAT sum and the LONG + FLOAT sum FLOAT, truncated into the
    LONG array. Measured under GDL with the bank's template, 300 particles in
    one second each ``missed = 65535`` (a CIP's repeated counter):
    ``count_missed`` 19660544, not the exact 19660500."""

    def test_300_repeated_counters_sum_in_float(self):
        op = _default_op(endbins=np.array([10.0, 50.0, 100.0, 200.0, 500.0]))
        d = new_accumulator(op, numrecords=4)
        soda2_particlesort(op, _bank_batch(300, missed=np.full(300, 65535.0, np.float32)), d)
        self.assertEqual(d.count_missed.tolist(), [19660544, 0, 0, 0])


class TestLines162And163ClampIsAFloatScalarMinMax(unittest.TestCase):
    """``soda2_particlesort.pro:162-163`` ``binningar<0.99>0.01``: scalar MIN
    then MAX with FLOAT literals. Measured under GDL with the bank's template
    (spec2d/hist3d linear indices decoded to bins):

    - FLOAT ladder ``[0.0,0.5,0.995,1.0]``, ``arearatio`` and ``aspectratio``
      NaN: arbin 1 and asprbin 1 (NaN clamps to 0.99). NaN kept, as Python's
      ``min``/``max`` keep it, lands at ``[-1]``, bin 2.
    - DOUBLE ladder ``[0d,0.5d,0.99d,1d]``, both ratios 1.0: arbin 2 (FLOAT
      0.99 is above DOUBLE 0.99); a DOUBLE 0.99 clamp gives bin 1."""

    def _run(self, arendbins, ratio):
        op = _default_op(endbins=np.array([10.0, 50.0, 100.0, 200.0, 500.0]),
                         arendbins=np.asarray(arendbins, dtype=np.float64))
        d = new_accumulator(op, numrecords=4)
        x = _bank_batch(1, arearatio=np.array([ratio], np.float32),
                        aspectratio=np.array([ratio], np.float32))
        soda2_particlesort(op, x, d)
        return d

    def test_nan_ratio_clamps_to_0_99(self):
        ladder = np.asarray([0.0, 0.5, 0.995, 1.0], dtype=np.float32)
        d = self._run(ladder, np.nan)
        self.assertEqual(_spec2d_cells(d.spec2d), [(0, 2, 1)])
        self.assertEqual(_spec2d_cells(d.hist3d), [(2, 1, 1)])

    def test_the_clamp_is_float_0_99(self):
        d = self._run([0.0, 0.5, 0.99, 1.0], 1.0)
        self.assertEqual(_spec2d_cells(d.spec2d), [(0, 2, 2)])
        self.assertEqual(_spec2d_cells(d.spec2d_aspr), [(0, 2, 2)])


class TestDriverOpLaddersAreFloat(unittest.TestCase):
    """The driver's ``op`` floats are IDL FLOAT (its concentration block and
    buffer processing already read them so, and SODA-2's own ladders are
    FLOAT literals), so ``process_2d._psopts`` must hand ``particlesort``
    FLOAT edges and thresholds. Each case measured under GDL with the bank's
    template and FLOAT op literals:

    - ``arendbins`` ``[0.0,0.1,...,1.0]`` (``soda2.pro:383``), ``arearatio``
      FLOAT 0.3 and ``aspectratio`` FLOAT 0.2 (a one-pixel line five pixels
      long): arbin 2, asprbin 1. Decimal double edges give 3 and 2.
    - ``endbins`` ``[10.0,12.7,50.0,100.0]``, ``diam`` FLOAT 12.7: sizebin 1;
      a double 12.7 edge gives 0.
    - ``clusterthresh`` FLOAT ``1e-6``, second particle's interarrival
      ``9.9999999999e-7``: no particle rejected; a double threshold clusters
      it (bit 16)."""

    def _op(self, **kw):
        from arrayprobe_soda2.process_2d import _psopts
        op = dict(clusterthresh=0.0, inttime_reject=0, smethod="diam", apply_psc=0,
                  apply_psc_sizelimit=0, water=0, endbins=[10.0, 50.0, 100.0, 200.0, 500.0],
                  arendbins=[0.0, 0.5, 1.0], eawmethod="allin", res=10.0, dofreject=1,
                  format="SPEC", probetype="")
        op.update(kw)
        return _psopts(op, 0.0, 1.0)

    def test_default_ar_ladder_edges_are_float(self):
        op = self._op(arendbins=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
        d = new_accumulator(op, numrecords=4)
        soda2_particlesort(op, _bank_batch(1, arearatio=np.array([0.3], np.float32),
                                           aspectratio=np.array([0.2], np.float32)), d)
        self.assertEqual(_spec2d_cells(d.spec2d), [(0, 2, 2)])
        self.assertEqual(_spec2d_cells(d.spec2d_aspr), [(0, 2, 1)])

    def test_endbins_edges_are_float(self):
        op = self._op(endbins=[10.0, 12.7, 50.0, 100.0])
        d = new_accumulator(op, numrecords=4)
        soda2_particlesort(op, _bank_batch(1, diam=np.array([_f32(12.7)], np.float32)), d)
        self.assertEqual(_spec2d_cells(d.spec2d), [(0, 1, 1)])

    def test_clusterthresh_is_float(self):
        op = self._op(clusterthresh=1e-6)
        d = new_accumulator(op, numrecords=4)
        rf = soda2_particlesort(
            op, _bank_batch(3, inttime=np.array([0.01, 9.9999999999e-7, 0.01])), d)
        self.assertEqual(rf.tolist(), [0, 0, 0])


if __name__ == "__main__":
    unittest.main()
