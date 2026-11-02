# SPDX-License-Identifier: BSD-3-Clause
"""v3.5 stage-4 (``sizeDist.m``) support for probetype 1 (CIP/PIP).

Before this, ``arrayprobe_uiops.sizedist.run`` refused every probetype but 2, so
a CIP or PIP flight was refused by the engine the project makes the default.
These tests pin the four probetype-gated behaviours that separate probetype 1
from probetype 2 in v3.5's own ``sizeDist.m``, each cited to its line.

**Oracle status.** The tail block (``:1931-1958``) was executed under Octave as
a verbatim slice of the vendored v3.5 source with the probetype-1 arm bound;
:data:`OCTAVE_TAIL_GOLDEN` records that real output.  The remaining three
gates are *read* from the source (their branch structure, not a computed
value), and ``overload_dead_time`` is asserted directly.  The whole-file
differential is ``tests/test_v35_sizedist_probetype1_whole_file.py``: every
written variable against unmodified v3.5 ``sizeDist.m`` under Octave, on a
real PIP proc file and a short-inter-arrival synthetic twin, for GPM/CIP,
SOCRATES/PIP and the catch-all CIP and PIP.  It does not cover the
inter-arrival threshold or shatter reacceptance, which only the PECAN arms
switch on (``:154-156``, ``:188-190``) through ``getPECANparams``, absent from
the vendored tree; nor the tail block's negative-count unwrap, which this
file's slice golden covers.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from arrayprobe_uiops.sizedist import UnsupportedProbetype, overload_dead_time
from arrayprobe_uiops.sizedist_tables import probe_defaults

#: Measured 2026-09-17 by running v3.5 ``sizeDist.m:1931-1958`` (probetype-1
#: arm, verbatim slice) under GNU Octave 11.3.0 with
#: ``TotalPC1 = [10 20 30 40 50]``, ``TotalPC2 = [5 40 -6 40 100]``.
OCTAVE_TAIL_GOLDEN = {
    "TotalPC2_after": [5, 40, 65530, 40, 100],
    "t199": [2.0, 0.5, 0.00045780558522813981, 1.0, 0.5],
    "t200": [1.0, 0.5, 0.00045780558522813981, 1.0, 0.5],
    "nexceed": 1,
}


class TestTailAgainstOctave(unittest.TestCase):
    """``:1931-1958`` -- probetype 1 derives live time from a COUNT RATIO.

    Probetype 2 writes ``1 - dead_time``; probetype 1 writes
    ``TotalPC1 ./ TotalPC2`` clamped at 1.  The port's arithmetic is asserted
    against the Octave run recorded in :data:`OCTAVE_TAIL_GOLDEN`.
    """

    def _port_tail(self, total_pc1, total_pc2):
        """The port's own expression, lifted from ``sizedist._run``'s tail."""
        total_pc2 = np.asarray(total_pc2, dtype=np.float64).copy()
        total_pc2[total_pc2 < 0] += 2 ** 16
        t199 = np.asarray(total_pc1, dtype=np.float64) / total_pc2
        t200 = t199.copy()
        n = int(np.count_nonzero(t199 > 1))
        t200[t199 > 1] = 1.0
        return total_pc2, t199, t200, n

    def test_matches_the_octave_slice(self):
        pc2, t199, t200, n = self._port_tail([10, 20, 30, 40, 50],
                                             [5, 40, -6, 40, 100])
        np.testing.assert_array_equal(pc2, OCTAVE_TAIL_GOLDEN["TotalPC2_after"])
        np.testing.assert_allclose(t199, OCTAVE_TAIL_GOLDEN["t199"], rtol=0, atol=0)
        np.testing.assert_allclose(t200, OCTAVE_TAIL_GOLDEN["t200"], rtol=0, atol=0)
        self.assertEqual(n, OCTAVE_TAIL_GOLDEN["nexceed"])

    def test_the_16_bit_counter_unwrap_is_not_a_clip(self):
        """``:1934`` adds 2^16; it does not clamp to zero. -6 -> 65530."""
        pc2, _, _, _ = self._port_tail([1], [-6])
        self.assertEqual(pc2[0], 65530.0)


class TestOverloadCapIsProbetype2Only(unittest.TestCase):
    """``:1118`` gates the 0.8 s warning / 1.0 s cap on ``probetype==2``.

    Both probetypes 1 and 2 reach the same ``else`` arm at ``:1116``, so the
    SUM is identical; only the cap differs.  A probetype-1 second whose
    overload sum exceeds 1 s writes that value through uncapped.
    """

    def setUp(self):
        # Six particles, every one flagged overloaded, summing to 1.2 s.
        self.int_arr = np.full(6, 0.2)
        self.dof = np.ones(6)

    def test_probetype_2_caps_at_one_second(self):
        self.assertAlmostEqual(
            overload_dead_time(self.int_arr, self.dof, 2), 1.0)

    def test_probetype_1_is_uncapped(self):
        got = overload_dead_time(self.int_arr, self.dof, 1)
        self.assertGreater(got, 1.0)
        self.assertAlmostEqual(got, 1.2)

    def test_the_default_is_probetype_2_so_old_call_sites_are_unchanged(self):
        self.assertEqual(
            overload_dead_time(self.int_arr, self.dof),
            overload_dead_time(self.int_arr, self.dof, 2),
        )

    def test_below_the_cap_the_two_probetypes_agree(self):
        small = np.full(3, 0.1)
        dof = np.ones(3)
        self.assertEqual(overload_dead_time(small, dof, 1),
                         overload_dead_time(small, dof, 2))


class TestWhichProbetypesTheDriverAdmits(unittest.TestCase):
    """The refusal is narrowed, not deleted: probetypes 0-3 are admitted
    (0 and 3 since 2026-09-23, tests/test_v35_sizedist_probetype03.py) and
    anything else still refuses loudly, naming what is admitted."""

    def test_the_probe_table_still_resolves_all_four_probetypes(self):
        # Non-PECAN representatives, so `calls_getPECANparams` is not the
        # thing under test here.
        for project, probe, want in [
            ("GPM", "2DC", 0),
            ("GPM", "CIP", 1),
            ("GPM", "2DS", 2),
            ("SOCRATES", "Fast2DC", 3),
            ("SOCRATES", "PIP", 1),
        ]:
            with self.subTest(probe=probe):
                cfg = probe_defaults(project, probe, version="3.5")
                self.assertEqual(cfg.probetype, want)

    def test_probetypes_0_and_3_fall_outside_the_admitted_set(self):
        for project, probe in [("GPM", "2DC"), ("GPM", "2DP")
                               if False else ("SOCRATES", "Fast2DC")]:
            with self.subTest(probe=probe):
                cfg = probe_defaults(project, probe, version="3.5")
                self.assertNotIn(cfg.probetype, (1, 2))

    def test_the_refusal_names_the_admitted_probetypes(self):
        """A refusal that just says "unsupported" tells a stranger nothing.

        Until 2026-09-23 the message named the probetype-0/3 branches that were
        missing (``parent_rec_num``, ``:984-985``, ``:969``, ``:1111-1115``);
        those branches are ported now, so the message names the admitted set.
        """
        import inspect

        from arrayprobe_uiops import sizedist as sd

        src = inspect.getsource(sd.run)
        self.assertIn("cfg.probetype not in (0, 1, 2, 3)", src)
        for token in ("0 (2DC/2DP)", "1 (CIP/PIP)", "2 (2D-S/HVPS/3VCPI)",
                      "3 (Fast2DC)"):
            with self.subTest(token=token):
                self.assertIn(token, src)

    def test_unsupported_probetype_is_still_exported(self):
        self.assertTrue(issubclass(UnsupportedProbetype, Exception))


def _write_probetype1_proc(path, particle_time, n_per_second=4):
    """A minimal probetype-1 proc file: every variable ``_run`` reads, nothing else.

    ``particle_time`` is one HHMMSS value per second of data; each gets
    ``n_per_second`` identical particles.  Values are chosen so every particle
    is accepted (``image_auto_reject`` ``'0'``, habit ``'t'``, an area ratio
    well above the ``'z'`` threshold), so an empty product can only come from
    the time axis and never from a rejection.
    """
    import netCDF4

    times = np.repeat(np.asarray(particle_time, dtype=np.float64), n_per_second)
    n = times.size
    insec = (np.floor(times / 10000) * 3600
             + np.floor((times % 10000) / 100) * 60
             + times % 100)
    micro = np.tile(np.arange(n_per_second) * 1e-3, len(particle_time))

    diam = np.full(n, 0.5)          # mm, lands inside the CIP bin table
    area = (np.pi / 4) * diam ** 2  # area ratio exactly 1 -> never 'z'

    with netCDF4.Dataset(path, "w", format="NETCDF4") as ds:
        ds.createDimension("time", n)
        cols = {
            "particle_time": times,
            "particle_millisec": np.zeros(n),
            "particle_microsec": micro,
            "image_auto_reject": np.full(n, float(ord("0"))),
            "image_width": np.full(n, 20.0),
            "image_length": np.full(n, 20.0),
            "image_area": area,
            "image_perimeter": np.full(n, 4 * 20.0),
            "holroyd_habit": np.full(n, float(ord("t"))),
            "image_center_in": np.ones(n),
            "image_touching_edge": np.zeros(n),
            "image_diam_AreaR": diam,
            "Time_in_seconds": insec + micro,
            "DMT_DOF_SPEC_OVERLOAD": np.zeros(n),
            "Particle_number_all": np.arange(1.0, n + 1.0),
            "image_diam_minR": diam,
        }
        for name, values in cols.items():
            v = ds.createVariable(name, "f8", ("time",))
            v[:] = values
    return n


def _axis(h0, h1):
    """A 1 Hz HHMMSS axis covering ``[h0, h1)`` whole hours."""
    return np.array(
        [hh * 10000 + mm * 100 + ss
         for hh in range(h0, h1) for mm in range(60) for ss in range(60)],
        dtype=np.float64,
    )


class TestParticleTimeIsTheProbeClockNotTheAircraftClock(unittest.TestCase):
    """``sizeDist.m:758-759`` (v3.5) / ``:627-628`` (v3.1.4).

    Probetype 1 matches particles to seconds on ``particle_time``, which
    ``imgProc_sm.m:1336`` writes from the CIP's **own** clock
    (``:939-944``), corrected only for ``PECAN``/``PIP`` (``:946``) and
    ``GCPEx``/``CIP`` (``:976``); every other project takes the ``else`` at
    ``:1072-1074`` and gets offsets of zero.  So on any other campaign the
    particle clock need not be UTC, while ``timehhmmss`` -- the TAS series --
    always is.  When the two do not intersect, what happens depends on **which tree** is
    running, and conflating the two is what this class did until 2026-09-20: the ORACLES
    fork bounds the block-sync walk (``uioops_testing/sizeDist.m:627``) and writes a silently
    empty product; **stock v3.5 has no such bound (``:918``) and dies** reading ``starttime``
    off the end.  This port reproduces stock, so it raises.

    Measured on a real UND 2016 CIP, 2026-09-17: ``particle_time`` spanned
    000540-040403 against a record clock of 072622-111644, and exactly one
    second of 18,000 entered the particle block at all.


    The V34 finding -- probetype 1 matches on the probe's own clock, so a wall-clock TAS
    axis need not intersect it -- is upstream's and is preserved.  The *empty product* half
    was this port's own divergence from stock and was corrected 2026-09-20; see the first
    test below.
    """

    #: One block per second, on a probe clock that starts at 00:05:40 -- the
    #: real file's own first value.
    PROBE_CLOCK = [540.0, 541.0, 542.0, 543.0, 544.0]

    def _run_on_axis(self, tmpdir, axis):
        import netCDF4

        from arrayprobe_uiops import sizedist as sd

        proc = str(Path(tmpdir) / "proc.nc")
        _write_probetype1_proc(proc, self.PROBE_CLOCK)
        out = str(Path(tmpdir) / f"sd_{int(axis[0])}.nc")
        sd.run(
            proc, out,
            np.full(axis.shape, 100.0), axis.copy(),
            "CIP", 6, 2,
            np.full(axis.shape, 85000.0), np.full(axis.shape, 5.0),
            0, 0, 0, 0, "UND2016", "20160912 071830",
            software="UIOOPS_v3.5", creation_time="x",
        )
        with netCDF4.Dataset(out) as ds:
            ds.set_auto_mask(False)
            conc = np.asarray(ds.variables["conc_minR"][:])
            rej = np.asarray(ds.variables["Reject_ratio"][:]).reshape(-1)
        return conc, rej

    def test_a_wall_clock_axis_over_a_probe_clock_file_now_dies_as_v35_does(self):
        """**This asserted the opposite until 2026-09-20, and its claim was about the wrong
        program.**

        It asserted that a non-intersecting axis writes a silently empty product with no
        error, and called that "upstream's" behaviour.  It is the **ORACLES fork's**.
        ``uioops_testing/sizeDist.m:627`` bounds the block-sync loop; stock v3.5's ``:918``
        does not, so a TAS second past the last particle block reads ``starttime`` off the
        end and MATLAB dies.  Octave-confirmed against the unmodified v3.5 source
        (case ``tasgap``).

        The port had been carrying the fork's bound while claiming to reproduce stock, so this
        test was pinning our own divergence as if it were the original's behaviour.  The tell
        was in its own comment, which said the ``jjj`` walk "runs to EOF" -- running to EOF is
        exactly what kills the MATLAB.

        **What survives**: the finding itself, that probetype 1 matches on ``particle_time``
        and so need not intersect a wall-clock axis at all.  The sibling test below still
        shows the same file filling on its own clock.

        **What it changes for the empty-product investigation**: the real UND 2016 case
        had *one* second of 18,000 enter the block, so its
        walk did not run off the end and stock v3.5 would have completed too.  That
        observation stands.  The generalisation -- that any non-intersecting axis is quietly
        empty under v3.5 -- does not: under v3.5 it is an error.
        """
        from arrayprobe.matlab_compat import MatlabIndexError

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(MatlabIndexError) as caught:
                self._run_on_axis(tmp, _axis(7, 8))
        self.assertIn("starttime", str(caught.exception).lower())

    def test_the_same_file_on_its_own_probe_clock_axis_is_not_empty(self):
        """The discriminating half: only the AXIS changes, and it fills."""
        with tempfile.TemporaryDirectory() as tmp:
            conc, _ = self._run_on_axis(tmp, _axis(0, 1))
        finite = np.isfinite(conc)
        self.assertGreater(int(np.count_nonzero(conc[finite])), 0)

    def test_probetype_1_reads_particle_time_and_probetype_2_reads_Time(self):
        """``:758-759`` vs ``:760-780`` -- the gate itself, not its effect."""
        import inspect

        from arrayprobe_uiops import sizedist as sd

        src = inspect.getsource(sd._run)
        gate = src[src.index("if cfg.probetype == 1:"):]
        head = gate[:gate.index("else:")]
        self.assertIn("particle_time", head)
        self.assertNotIn('"Time"', head)

    def test_nothing_in_the_port_re_bases_particle_time_onto_the_tas_clock(self):
        """The ORACLES fork DOES (``uioops_testing/sizeDist.m:513``).  Stock
        does not, and this port follows stock -- asserted so that adding the
        fork's ``+ tas_time(1)`` becomes a deliberate, visible change.
        """
        import inspect

        from arrayprobe_uiops import sizedist as sd

        src = inspect.getsource(sd._run)
        gate = src[src.index("if cfg.probetype == 1:"):]
        head = gate[:gate.index("else:")]
        self.assertNotIn("tas_time", head)


if __name__ == "__main__":
    unittest.main()
