# SPDX-License-Identifier: BSD-3-Clause
"""Diff-triage: align two UIOOPS output files, then compare them by tolerance class.

This is the comparison stage, and it is deliberately built *before* S4 rather than after it.
S4 is where mismatches against a reference product start arriving — for this project
that meant the ORACLES 2016 2D-S products, but the tool assumes nothing about which
campaign or probe produced either side — and the expensive part of a mismatch is
never noticing it — it is working out *which stage caused it*. A comparison tool
built during the panic is a tool built to confirm whatever the author already
suspects.

Two ideas carry the whole design.

**Align before comparing.** A naive element-wise diff of two per-particle files is
worthless the moment the particle *counts* differ: one extra particle at index 12
makes every subsequent row disagree, and a real one-particle framing difference
presents as "all 41 variables are wrong". So particles are joined on identity first
— ``(Date, Time, parent_rec_num, position_start, position_end)``, every component
framing-derived — and the join statistics are reported *before* any value is looked
at. Unmatched particles are summarised as **runs** rather than counts, because one
run of 300 is a different problem from 300 isolated singletons and the count alone
cannot tell them apart.

**Not every variable deserves the same verdict.** Asserting bit-equality on an
accumulated float is a test that fails for reasons no-one can act on; asserting
nothing on an integer count throws away the strongest evidence available. So each
variable is assigned a :class:`ToleranceClass`, and each class gets comparison
semantics *and a reporting style* that suits it — a confusion matrix for a
categorical code, drift-against-index for an accumulator, bit-equality for a count.

The classes are A–G, and the assignment is :data:`PROC_CLASSES` for the imgProc
per-particle file and :data:`SD_CLASSES` for the ``sizeDist`` size-distribution
file. Anything unassigned is reported as ``UNCLASSIFIED`` rather than silently
defaulted: a new variable appearing in a file is a fact about the file, and
picking a tolerance for it without deciding is how a comparison quietly stops
meaning anything.

**Both file kinds are handled, and the alignment differs between them.** A proc
file joins on particle identity. A sd file has no particles left in it, and its
one-second stamp turns out not to identify a row either — 256 of the ORACLES
09/06 TAS sidecar's 4,110 rows are exact duplicates of their predecessor — so it
joins positionally on the ``Time`` index and verifies ``time`` as an ordinary
class-A variable. :func:`file_kind` decides which from the file's *dimensions*,
never from its name; that is the S2 rule, learned the hard way.

Class **G** was added at S4 for a situation the original six had no slot for: a
value where the Octave oracle and MATLAB genuinely disagree and the port
deliberately follows MATLAB. Octave 11.3's ``mean`` routes through
``robust_mean_sum``, which uses a compensated accumulator MATLAB has no
equivalent of, so bit-equality with the oracle would be the *wrong* bar for the
one variable built with a plain ``mean``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

__all__ = [
    "ToleranceClass",
    "CLASSES",
    "PROC_CLASSES",
    "PROC_CLASSES_V35",
    "SD_CLASSES",
    "JOIN_KEY",
    "SD_JOIN_KEY",
    "JoinResult",
    "VariableVerdict",
    "ComparisonReport",
    "join_particles",
    "join_seconds",
    "compare_variables",
    "compare_proc_files",
    "compare_sd_files",
    "compare_files",
    "file_kind",
    "format_report",
]


# ---------------------------------------------------------------------------
# Tolerance classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ToleranceClass:
    """One of the A-G comparison regimes, and whether a difference in it fails.

    A class bundles two things that must travel together: *how* two values are
    judged equal, and *what a difference means*. Splitting them is how a
    comparison stops meaning anything -- a bit-equality assertion on an
    accumulated float fails for reasons nobody can act on, and a loose
    tolerance on an integer count throws away the strongest evidence in the
    file.

    ``rule`` is prose because it is written for the person reading a report,
    not consumed by code; the executable half lives in
    :func:`compare_variables`, which switches on ``key``. ``asserts`` is the
    part that decides a verdict: a class with ``asserts=False`` is reported and
    never blocks acceptance (see :meth:`ComparisonReport.accepted`).

    Instances are the values of :data:`CLASSES`; nothing else constructs one.
    """

    key: str
    name: str
    rule: str
    """How a difference is judged."""
    asserts: bool
    """Whether a difference in this class is a *failure*, or only information."""


CLASSES: dict[str, ToleranceClass] = {
    "A": ToleranceClass(
        "A", "bit-exact",
        "Integers, ASCII codes, counts and bin edges. Any difference at all is a "
        "failure — these carry no floating-point slack, so a mismatch is a real "
        "disagreement about what happened, never a rounding artefact.",
        asserts=True,
    ),
    "B": ToleranceClass(
        "B", "closed-form float",
        "Floats produced by a short arithmetic expression with no accumulation. "
        "Tolerance is a few ULP (rtol 1e-12, atol 0). A difference larger than "
        "that is a different formula, not a different rounding order.",
        asserts=True,
    ),
    "C": ToleranceClass(
        "C", "accumulated float",
        "Values built by summing along the record, so error grows with index. "
        "Reported as drift against index — first divergence, slope, endpoint — "
        "rather than as a single max, because the max alone cannot distinguish "
        "a steady accumulation from one bad element.",
        asserts=False,
    ),
    "D": ToleranceClass(
        "D", "algorithm substitution",
        "Computed by a different implementation of the same mathematical object "
        "(the smallest enclosing circle). Agreement is a theorem, not a "
        "coincidence, so the tolerance is real but loose: atol 1e-9.",
        asserts=True,
    ),
    "E": ToleranceClass(
        "E", "legitimately version-dependent",
        "Categorical outputs that two MATLAB versions may genuinely disagree on. "
        "**Never asserted.** Reported as a confusion matrix, because 'how many "
        "differ' is the wrong question and 'which code became which' is the right "
        "one — the shape of the matrix names the divergent branch.",
        asserts=False,
    ),
    "F": ToleranceClass(
        "F", "preserved defect",
        "A value whose agreement is asserted *because a preserved defect makes it "
        "so*. Held separately from A so that a fidelity decision is never confused "
        "with an ordinary equality.",
        asserts=True,
    ),
    "G": ToleranceClass(
        "G", "oracle more accurate than MATLAB",
        "A value where the Octave oracle and MATLAB genuinely differ and the port "
        "deliberately follows MATLAB, so bit-equality with the oracle is the WRONG "
        "bar. Asserted within a stated ULP budget (rtol 1e-14, atol 0), which is "
        "loose enough for the known cause and far too tight to hide a real "
        "disagreement. Added at S4, when Octave 11.3's `mean` turned out to use a "
        "compensated accumulator (`sum(...,\"extra\")` via `robust_mean_sum`) that "
        "MATLAB has no equivalent of.",
        asserts=True,
    ),
}


#: The join key. Every component is framing-derived — decided before any
#: measurement is taken from the particle image — so a difference in a *measured*
#: quantity can never move a particle from one side of the join to the other.
#: Neither ``position`` nor ``particle_num`` identifies a particle on its own, and
#: ``parent_rec_num`` restarts per input file, which is why ``Date`` and ``Time``
#: are in the key at all.
JOIN_KEY = ("Date", "Time", "parent_rec_num", "position")


PROC_CLASSES: dict[str, str] = {
    # -- A: integers, counts, flags, and floats that hold integer values --------
    "Date": "A",
    "Time": "A",
    "msec": "A",
    "SliceCount": "A",
    "DMT_DOF_SPEC_OVERLOAD": "A",
    "Particle_number_all": "A",
    "position": "A",
    "particle_time": "A",
    "particle_millisec": "A",
    # A raw clock count. Declared double, integer-valued, so bit-equality is the
    # right bar despite the type.
    "particle_microsec": "A",
    "parent_rec_num": "A",
    "particle_num": "A",
    "image_length": "A",
    "image_width": "A",
    # A count of shadowed pixels. Double in the file, integer in fact.
    "image_area": "A",
    "image_longest_y": "A",
    "image_max_top_edge_touching": "A",
    "image_max_bottom_edge_touching": "A",
    # Tri-valued {-48, 0, 68}, not boolean.
    "image_touching_edge": "A",
    "image_hollow": "A",
    "image_center_in": "A",
    "edge_at_max_hole": "A",
    "max_hole_diameter": "A",
    "bin_stats": "A",

    # -- B: short closed-form arithmetic ---------------------------------------
    "image_axis_ratio": "B",
    "image_diam_circle_fit": "B",
    "image_diam_horiz_chord": "B",
    "image_diam_horiz_chord_corr": "B",
    "image_diam_following_bamex_code": "B",
    "image_diam_vert_chord": "B",
    "image_diam_AreaR": "B",
    "image_perimeter": "B",
    "percent_shadow_area": "B",
    "part_z": "B",
    "size_factor": "B",
    "area_hole_ratio": "B",

    # -- C: accumulated along the record ---------------------------------------
    "Time_in_seconds": "C",
    "inter_arrival": "C",

    # -- D: our geometry against CGAL's ----------------------------------------
    "image_diam_minR": "D",

    # -- E: categorical, and genuinely version-dependent ------------------------
    "image_auto_reject": "E",
    "holroyd_habit": "E",
}

#: v3.5's ``imgProc_sm`` writes four per-particle variables v3.1.4 never did
#: (``arrayprobe_uiops/imgproc.py:715-716, 736-737``; v3.5 ``imgProc_sm.m:1359-1360, 1381-1382``).
#: ``PROC_CLASSES`` stays the v3.1.4 table (``tests/test_compare.py`` pins it to the v3.1.4
#: profiles' variable lists); a v3.5 proc file is compared with THIS table, or
#: ``compare_files`` reports the four as unclassified and ``accepted()`` is False (measured
#: 2026-09-13 on the demo flight -- exactly these four, nothing else).
PROC_CLASSES_V35: dict[str, str] = {
    **PROC_CLASSES,
    # Centre of the minimum enclosing circle, unscaled -- the same substituted algorithm
    # that produces image_diam_minR, so the same class.
    "image_xpos": "D",
    "image_ypos": "D",
    # Closed-form ratios of already-compared quantities: Perim*Diam/Area; sqrt(area)/perim.
    "fine_detail_ratio": "B",
    "sphericity": "B",
    # The default-on stray-pixel correction (engine 3.5 driver): a count of pixels removed,
    # integer in fact, and the minimum-enclosing-circle diameter before the correction --
    # the same substituted algorithm as image_diam_minR, so the same class.
    "image_stray_pixels_removed": "A",
    "image_diam_minR_uncorrected": "D",
}

#: The join key for a size-distribution file. There is no particle identity left
#: at this stage -- every variable is per second -- so the key is the one-second
#: timestamp the file carries in ``time``.
SD_JOIN_KEY = ("Time index",)


SD_CLASSES: dict[str, str] = {
    # -- A: bit-exact, and measured so against the S4 oracle on a real flight --
    # 24 of the 25 written variables reproduce the Octave run bit for bit, so
    # anything less than bit-equality here is a genuine disagreement. Nothing in
    # this file is an integer, which makes that a strong statement rather than a
    # cheap one: it says the whole 1 Hz loop, the sample volume and the
    # normalisation all reduce in MATLAB's order.
    "time": "A",
    "bin_min": "A",
    "bin_max": "A",
    "bin_mid": "A",
    "bin_dD": "A",
    "conc_minR": "A",
    "area": "A",
    "n": "A",
    "total_area": "A",
    "mass": "A",
    "habitsd": "A",
    "re": "A",
    "massBL": "B",
    "Reject_ratio": "A",
    "vt": "B",
    "Prec_rate": "B",
    "habitmsd": "A",
    "Calcd_area": "A",
    "count": "A",
    "mean_perimeter": "A",
    "sum_IntArr": "A",
    "sample_vol": "A",

    # -- Reclassified A -> B on 2026-09-08, by cross-platform measurement ------
    # `massBL` and `vt` sat in A, the class whose own rule reads "Integers, ASCII
    # codes, counts and bin edges ... these carry no floating-point slack". They
    # are neither. `massBL` is `0.115/1000 * area ** 1.218` (sizedist.py:1223,
    # sizeDist.m:844) and `vt` comes out of single_vt.m -- closed-form floats
    # through a fractional power and transcendental functions, which is the
    # written definition of B.
    #
    # They were in A for an honest but single-platform reason: measured equal,
    # bit for bit, against the Octave goldens. Every one of those measurements
    # was taken on the same Windows machine that built the goldens, so both
    # sides called the same libm and the same rounding came out twice. The first
    # cross-platform CI run took the measurement somewhere else and it did not
    # survive:
    #
    #   Linux-6.17.0 / glibc 2.39 / numpy 2.5.2
    #     massBL  n_diff=2/256  max_abs=1.59e-22  (values ~2.7e-08 to 3.3e-07)
    #     massBL  n_diff=2/384  max_abs=5.29e-23
    #   macOS     vt differs in the same shape
    #
    # That is a relative difference of order 1e-15 on two cells in 256 -- the
    # last bits of a double, which is what glibc's pow() and Microsoft's UCRT
    # pow() are permitted to disagree about. A different formula would move
    # every cell and move it far; this moves two, by 1e-22. B's tolerance is
    # rtol 1e-12, four orders of magnitude above what was measured, so the port
    # is still held to a bound that a real disagreement could not pass.
    #
    # NOTHING ELSE IS RECLASSIFIED. `mass`, `re`, `Prec_rate` and `Calcd_area`
    # are derived floats sitting in A on the same single-platform evidence and
    # are under exactly the same suspicion -- but no platform has yet produced a
    # difference in them, and this project does not move a classification on
    # analogy. They move if and when something measures them.
    #
    # -- Prec_rate (and REJ_Prec_rate) reclassified A -> B on 2026-10-02 ------
    # Measured: CI run 37074378298 (master c00fdf8), Linux-6.17.0 / glibc 2.39 /
    # numpy 2.5.3, stock-tree PIP cases of test_sizedist_stock_divergences:
    #     Prec_rate  n_diff=1/384  max_abs=3.31e-24  at 1.46971e-08  (clamp)
    #     Prec_rate  n_diff=1/320  max_abs=3.31e-24  at 1.46971e-08  (pt1abs)
    # i.e. rel 2.3e-16, two ULP (ulp of 1.47e-08 is 2^-79 = 1.65e-24), in one
    # cell. `Prec_rate` is sum(mass * vt) / binwidth * 10 / svol (sizedist.py
    # particle_pr = particle_mass * particle_vt), and vt comes out of single_vt
    # through exp/log/pow -- the variable `vt` already moved to B on macOS for
    # this reason. REJ_Prec_rate is the same expression on the rejected
    # population and moves with it, as REJ_massBL and REJ_vt did.

    # -- F: exact BECAUSE a preserved defect makes it so ------------------------
    # `conc_AreaR` is identically zero (the double-scaled area-ratio concentration:
    # sizeDist.m:669 scaling an already-scaled diameter), and `mean_area_ratio` is a
    # column-major reshape of the array MATLAB meant to transpose (:1981). Both agree exactly, and
    # both would agree exactly with a "fixed" port too if the fix were applied on
    # both sides -- which is why they are held apart from A.
    "conc_AreaR": "F",
    "mean_area_ratio": "F",

    # -- G: the oracle is more accurate than the MATLAB it stands in for --------
    "ar": "G",

    # -- The optional-branch variables, classified 2026-09-06 -------------------
    # `iCreateBad` and `iCreateAspectRatio` add 21 more variables, and until this
    # date NONE of them had a class -- because no test had ever run sizeDist with
    # either flag on, so nothing ever asked. A comparison that touched them
    # reported UNCLASSIFIED, which blocks acceptance: the comparator was right to
    # refuse, and the refusal was invisible for want of a caller.
    #
    # All 21 are A on measurement, not by analogy: stock v3.1.4 run under Octave
    # with iCreateAspectRatio=1 and iCreateBad=1 over the same proc file agrees
    # with the port in every cell of every one of them, NaN positions included
    # (octave_oracle/run_s4_aspectratio_bank.py, 46/46 variables, 2 seconds x 128
    # bins). The rejected-population block is the accepted one line for line, so
    # bit-equality there is what its shared transcription predicts.
    "REJ_conc_minR": "A",
    "REJ_conc_AreaR": "A",
    "REJ_area": "A",
    "REJ_n": "A",
    "REJ_total_area": "A",
    "REJ_mass": "A",
    "REJ_massBL": "B",
    "REJ_habitsd": "A",
    "REJ_habitmsd": "A",
    "REJ_re": "A",
    "REJ_vt": "B",
    "REJ_Prec_rate": "B",
    "REJ_Calcd_area": "A",
    "REJ_count": "A",
    "REJ_mean_perimeter": "A",
    "REJ_mean_area_ratio": "A",
    "REJ_ar": "A",
    # The two this bank was built for. They were written all-NaN by the port
    # until 2026-09-06 while MATLAB filled them (:1257-1263, :1978-1979); the
    # class records that they now agree, which is a different statement from
    # "both are NaN" -- 14 of the 256 accepted cells and 8 of the 256 rejected
    # ones carry real numbers in this fixture.
    "mean_aspect_ratio_rectangle": "A",
    "mean_aspect_ratio_ellipse": "A",
    "REJ_mean_aspect_ratio_rectangle": "A",
    "REJ_mean_aspect_ratio_ellipse": "A",
}

_CLASS_TOL = {"B": (1e-12, 0.0), "D": (0.0, 1e-9), "G": (1e-14, 0.0)}

#: Values that mean "this branch did not compute me" rather than a measurement.
#: A mismatch in one of these is a *branch* difference, and saying so is more
#: useful than reporting a numeric delta.
SENTINELS: dict[str, tuple[str, Any]] = {
    "image_axis_ratio": ("0.0 for every edge-touching particle", 0.0),
    "image_diam_minR": ("NaN for an all-lit image", np.nan),
    "particle_time": ("identically zero for probetype 2", 0),
    "particle_millisec": ("identically zero for probetype 2", 0),
}


# ---------------------------------------------------------------------------
# Join
# ---------------------------------------------------------------------------

def describe_differences(report) -> str:
    """One line per non-EXACT variable, carrying the MEASUREMENT.

    A bit-exactness assertion that fails with only a variable name cannot
    distinguish the two things it could possibly mean: one ulp of a platform's
    libm, or a real disagreement about the physics. The first cross-platform CI
    run (2026-09-08) failed on Linux with ``['massBL']`` and on macOS with
    ``['vt']`` and said nothing else -- both are derived quantities computed
    through fractional powers and transcendental functions, exactly where two
    libm implementations are allowed to differ in the last bit, but nothing in
    the message established that. Every bit-exactness test in this repository
    formats its failure through here so the log says which.
    """
    import platform
    bad = [v for v in report.variables if v.verdict != "EXACT"]
    if not bad:
        return "none"
    rows = "; ".join(
        f"{v.name} [{v.tclass}] {v.verdict} n_diff={v.n_diff}/{v.n_total} "
        f"max_abs={v.max_abs:.6g} {v.detail}" for v in bad)
    return f"on {platform.platform()} / numpy {np.__version__}: {rows}"


@dataclass
class JoinResult:
    """Which rows of two files are the same thing, decided before any value is read.

    Produced by :func:`join_particles` (proc files, joined on the identity
    tuple :data:`JOIN_KEY`) or :func:`join_seconds` (sd files, joined
    positionally on the ``Time`` index). Everything in
    :func:`compare_variables` is indexed through ``left_index``/``right_index``,
    so a bad join makes every subsequent verdict meaningless -- which is why
    the join statistics are reported above the value table rather than below
    it.

    The unmatched rows are kept as index arrays, not counts, so
    :meth:`unmatched_runs` can distinguish one abandoned record from a
    systematic framing difference.
    """

    left_index: np.ndarray
    """Indices into A of matched particles, in A's order."""
    right_index: np.ndarray
    """Indices into B of the same particles."""
    left_only: np.ndarray
    right_only: np.ndarray
    n_left: int
    n_right: int
    duplicate_keys: int = 0
    """Keys appearing more than once on either side.

    Not expected, and worth surfacing loudly if it happens: it would mean the
    join key does not identify a particle, which invalidates every value
    comparison built on top of it.
    """

    @property
    def n_matched(self) -> int:
        """Rows present on both sides. Equal to ``left_index.size`` by construction."""
        return int(self.left_index.size)

    @property
    def join_fraction(self) -> float:
        """Matched, as a fraction of the larger side. 1.0 iff both sides align."""
        denom = max(self.n_left, self.n_right)
        return float(self.n_matched / denom) if denom else 1.0

    def unmatched_runs(self, side: str = "left") -> list[tuple[int, int]]:
        """Consecutive unmatched indices, collapsed to ``(start, length)`` runs.

        The distinction this exists to preserve: 300 unmatched particles in one
        run is a single event -- most likely a record abandoned early -- while
        300 singletons scattered through the file is a systematic framing
        difference. The counts are identical and the diagnoses are not.
        """
        idx = np.sort(self.left_only if side == "left" else self.right_only)
        if idx.size == 0:
            return []
        breaks = np.flatnonzero(np.diff(idx) != 1)
        starts = np.concatenate(([0], breaks + 1))
        ends = np.concatenate((breaks, [idx.size - 1]))
        return [(int(idx[s]), int(idx[e] - idx[s] + 1)) for s, e in zip(starts, ends, strict=True)]


def _key_columns(ds, n):
    """Build the (n, k) integer key matrix from a netCDF dataset."""
    cols = []
    for name in JOIN_KEY:
        if name not in ds.variables:
            raise KeyError(
                f"join key component {name!r} is missing from the file; "
                f"available: {', '.join(sorted(ds.variables))}"
            )
        v = np.asarray(ds.variables[name][:])
        if v.ndim == 1:
            cols.append(v.reshape(n, 1))
        else:
            # `position` is (pos_count, time) in MATLAB and therefore (time,
            # pos_count) as stored. Take whichever axis is the particle axis
            # rather than assuming, since a transposed write is exactly the kind
            # of defect this tool exists to find.
            arr = v if v.shape[0] == n else v.T
            cols.append(arr.reshape(n, -1))
    return np.hstack([c.astype(np.int64) for c in cols])


def join_particles(ds_a, ds_b) -> JoinResult:
    """Align two per-particle files on particle identity.

    Returns index arrays into each side. Order is A's order, so a report can be
    read against the left-hand file.
    """
    n_a = len(ds_a.dimensions["time"])
    n_b = len(ds_b.dimensions["time"])
    ka = _key_columns(ds_a, n_a)
    kb = _key_columns(ds_b, n_b)

    # Structured void view gives exact tuple equality without hashing floats.
    va = np.ascontiguousarray(ka).view([("", ka.dtype)] * ka.shape[1]).ravel()
    vb = np.ascontiguousarray(kb).view([("", kb.dtype)] * kb.shape[1]).ravel()

    dup = int(n_a - np.unique(va).size) + int(n_b - np.unique(vb).size)

    common, ia, ib = np.intersect1d(va, vb, return_indices=True)
    order = np.argsort(ia)
    ia, ib = ia[order], ib[order]

    left_only = np.setdiff1d(np.arange(n_a), ia)
    right_only = np.setdiff1d(np.arange(n_b), ib)
    del common
    return JoinResult(ia, ib, left_only, right_only, n_a, n_b, duplicate_keys=dup)


# ---------------------------------------------------------------------------
# Value comparison
# ---------------------------------------------------------------------------

@dataclass
class VariableVerdict:
    """The comparison outcome for one netCDF variable, in its tolerance class.

    ``verdict`` is the coarse answer and ``detail`` the class-appropriate
    evidence behind it -- a drift slope for an accumulator, the worst absolute
    difference for a closed-form float, a per-value breakdown for a
    categorical. ``confusion`` is populated only for the categorical classes,
    mapping ``(left_value, right_value)`` to how often that substitution
    happened; for a reject-code or habit-code variable that table is the whole
    diagnosis, where ``n_diff`` alone would say only that something moved.

    Whether the verdict *counts against* the run is not stored here: it is
    :attr:`failed`, which asks the variable's :class:`ToleranceClass`.
    """

    name: str
    tclass: str
    verdict: str
    """``EXACT`` · ``WITHIN`` · ``DIFF`` · ``SHAPE`` · ``MISSING`` · ``INFO``."""
    n_diff: int = 0
    n_total: int = 0
    max_abs: float = 0.0
    detail: str = ""
    confusion: dict[tuple[float, float], int] = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        """A bad verdict *in a class that asserts* -- the two halves are separate.

        ``DIFF`` on a class-C accumulator is information and not a failure;
        the same verdict on a class-A count is a real disagreement about what
        happened. An unknown class falls back to A, the strictest, so a
        variable nobody has classified cannot be quietly excused.
        """
        return self.verdict in ("DIFF", "SHAPE", "MISSING") and CLASSES.get(
            self.tclass, CLASSES["A"]
        ).asserts


def _values(ds, name, index):
    v = np.asarray(ds.variables[name][:])
    if v.ndim == 1 and v.shape[0] == index.size + (v.shape[0] - index.size):
        pass
    return v


def _aligned(ds, name, index, n_particles):
    """Pull `name` and select the joined particles, whatever the axis order."""
    v = np.asarray(ds.variables[name][:])
    if v.ndim == 1:
        if v.shape[0] != n_particles:
            return v            # a per-bin variable such as bin_stats
        return v[index]
    axis = 0 if v.shape[0] == n_particles else 1
    return np.take(v, index, axis=axis)


def compare_variables(ds_a, ds_b, join: JoinResult,
                      classes: dict[str, str] | None = None) -> list[VariableVerdict]:
    """Compare every variable of A against B over the joined particles."""
    classes = PROC_CLASSES if classes is None else classes
    out: list[VariableVerdict] = []

    for name in ds_a.variables:
        tclass = classes.get(name, "?")
        if name not in ds_b.variables:
            out.append(VariableVerdict(name, tclass, "MISSING",
                                       detail="absent from the right-hand file"))
            continue

        a = _aligned(ds_a, name, join.left_index, join.n_left).astype(np.float64)
        b = _aligned(ds_b, name, join.right_index, join.n_right).astype(np.float64)
        if a.shape != b.shape:
            out.append(VariableVerdict(name, tclass, "SHAPE",
                                       detail=f"{a.shape} vs {b.shape}"))
            continue

        both_nan = np.isnan(a) & np.isnan(b)
        equal = both_nan | (a == b)
        n_diff = int(np.count_nonzero(~equal))
        diff = np.where(both_nan, 0.0, np.abs(a - b))
        max_abs = float(np.nanmax(diff)) if diff.size else 0.0

        if tclass == "?":
            out.append(VariableVerdict(
                name, "?", "INFO", n_diff, a.size, max_abs,
                detail="UNCLASSIFIED — assign a tolerance class before trusting "
                       "this row either way",
            ))
            continue

        if n_diff == 0:
            out.append(VariableVerdict(name, tclass, "EXACT", 0, a.size, 0.0,
                                       detail=_sentinel_note(name)))
            continue

        if tclass == "E":
            out.append(VariableVerdict(
                name, tclass, "INFO", n_diff, a.size, max_abs,
                detail=_confusion_detail(a, b, equal),
                confusion=_confusion(a, b, equal),
            ))
        elif tclass == "C":
            out.append(VariableVerdict(name, tclass, "INFO", n_diff, a.size,
                                       max_abs, detail=_drift_detail(a, b, equal)))
        elif tclass in _CLASS_TOL:
            rtol, atol = _CLASS_TOL[tclass]
            close = both_nan | np.isclose(a, b, rtol=rtol, atol=atol, equal_nan=True)
            n_out = int(np.count_nonzero(~close))
            out.append(VariableVerdict(
                name, tclass, "WITHIN" if n_out == 0 else "DIFF",
                n_out if n_out else n_diff, a.size, max_abs,
                detail=(f"{n_diff} not bit-equal, all within tolerance"
                        if n_out == 0
                        else f"{n_out} outside rtol={rtol:g} atol={atol:g}")
                       + _sentinel_note(name, prefix="; "),
            ))
        else:   # A and F both demand bit-equality
            out.append(VariableVerdict(
                name, tclass, "DIFF", n_diff, a.size, max_abs,
                detail=_first_offenders(a, b, equal) + _sentinel_note(name, prefix="; "),
            ))
    # A variable only the right-hand file carries is as much a disagreement as one only the
    # left carries; iterating the left file alone never saw it, and the gate passed.
    for name in ds_b.variables:
        if name not in ds_a.variables:
            out.append(VariableVerdict(name, classes.get(name, "?"), "MISSING",
                                       detail="absent from the left-hand file"))
    return out


def _sentinel_note(name, prefix=""):
    if name not in SENTINELS:
        return ""
    return f"{prefix}sentinel: {SENTINELS[name][0]}"


def _first_offenders(a, b, equal, k=3):
    idx = np.flatnonzero(~equal.ravel())[:k]
    if idx.size == 0:
        return ""
    af, bf = a.ravel(), b.ravel()
    parts = [f"[{int(i)}] {af[i]:g} vs {bf[i]:g}" for i in idx]
    return "first: " + ", ".join(parts)


def _confusion(a, b, equal):
    out: dict[tuple[float, float], int] = {}
    for left, right in zip(a.ravel()[~equal.ravel()], b.ravel()[~equal.ravel()], strict=True):
        out[(float(left), float(right))] = out.get((float(left), float(right)), 0) + 1
    return out


def _confusion_detail(a, b, equal, k=4):
    pairs = sorted(_confusion(a, b, equal).items(), key=lambda kv: -kv[1])[:k]
    if not pairs:
        return ""
    shown = ", ".join(f"{_code(x)}->{_code(y)} x{n}" for (x, y), n in pairs)
    return "top transitions: " + shown


def _code(v):
    """Render a categorical value as its ASCII character where that is what it is."""
    iv = int(v)
    if 32 <= iv < 127:
        return f"{iv}({chr(iv)!r})"
    return str(iv)


def _drift_detail(a, b, equal):
    bad = np.flatnonzero(~equal.ravel())
    if bad.size == 0:
        return ""
    d = (a.ravel() - b.ravel())
    first = int(bad[0])
    # Slope of the difference against index: a steady accumulation has one, a
    # single bad element does not.
    if bad.size >= 2:
        slope = float(np.polyfit(bad.astype(float), d[bad], 1)[0])
    else:
        slope = 0.0
    return (f"first divergence at particle {first}; "
            f"drift slope {slope:.3g} per particle; "
            f"endpoint delta {d[-1]:.6g}")


# ---------------------------------------------------------------------------
# Top level
# ---------------------------------------------------------------------------

@dataclass
class ComparisonReport:
    """One whole file-against-file comparison: the alignment, then every variable.

    Returned by :func:`compare_proc_files`, :func:`compare_sd_files` and
    :func:`compare_files`, and rendered for a human by :func:`format_report`.
    The ordering of the fields is the ordering of the report on purpose: a
    reader must see how well the two files aligned, and any ``notes`` about
    that alignment, before a single value verdict -- a 98 % join makes the
    value table describe a different population on each side.

    :meth:`accepted` is the gate; :attr:`failures` and :attr:`unclassified` are
    the two ways it can be closed.
    """

    join: JoinResult
    variables: list[VariableVerdict]
    left: str = ""
    right: str = ""
    join_key: tuple[str, ...] = JOIN_KEY
    """What the join was on -- particle identity, or the one-second row index."""
    notes: list[str] = field(default_factory=list)
    """Things about the alignment a reader must see before the value table."""

    @property
    def failures(self) -> list[VariableVerdict]:
        """Variables that disagreed *in a class that asserts* (see
        :attr:`VariableVerdict.failed`). Empty is one of the two conditions
        :meth:`accepted` requires."""
        return [v for v in self.variables if v.failed]

    @property
    def unclassified(self) -> list[VariableVerdict]:
        """Variables present in the files but absent from the class table.

        Reported separately rather than folded into :attr:`failures` because
        the two need different actions: a failure is a disagreement to explain,
        an unclassified variable is a decision nobody has made yet. Both block
        acceptance -- a variable nobody has judged is not evidence of agreement.
        """
        return [v for v in self.variables if v.tclass == "?"]

    def accepted(self, min_join=0.999) -> bool:
        """The comparison stage's acceptance gate: >=99.9% join and no asserting class in failure.

        Unclassified variables block acceptance too. A variable nobody has
        decided about is not evidence of agreement, and letting it pass silently
        is how the gate stops meaning anything.
        """
        return (self.join.join_fraction >= min_join
                and not self.failures
                and not self.unclassified
                and self.join.duplicate_keys == 0)


def compare_proc_files(path_a, path_b, classes=None) -> ComparisonReport:
    """Join and compare two imgProc per-particle files. Requires ``netCDF4``."""
    import netCDF4

    with netCDF4.Dataset(str(path_a)) as a, netCDF4.Dataset(str(path_b)) as b:
        join = join_particles(a, b)
        variables = compare_variables(a, b, join, classes)
    return ComparisonReport(join, variables, str(path_a), str(path_b))


def join_seconds(ds_a, ds_b) -> tuple[JoinResult, list[str]]:
    """Align two size-distribution files on their ``Time`` index.

    A sd file has no particle identity left in it -- ``sizeDist`` reduces every
    particle to a per-second row -- and, crucially, **the HHMMSS stamp in
    ``time`` does not identify a row.**  Measured on an archived 2D-S flight's TAS
    sidecar: 4,110 rows carry 3,854 distinct stamps, because 256 rows are exact
    duplicates of their predecessor down to the millisecond (``64923.4`` twice,
    and so on).  ``sizeDist`` processes such a second twice and advances to the
    *next* particle block on the repeat, so the duplication is real in the
    output too.

    So the join is **positional**: row *i* of one file is row *i* of the other,
    because both were produced from the same TAS vector and ``Time`` is that
    vector's index.  That is not a weaker join than a keyed one here -- it is the
    only correct one -- and it is checked rather than assumed: ``time`` is itself
    a compared variable in class A, so a positional misalignment shows up as a
    ``time`` mismatch before anything else is believed.

    Returns the join and any notes worth printing above the table.
    """
    n_a = len(ds_a.dimensions["Time"])
    n_b = len(ds_b.dimensions["Time"])
    n = min(n_a, n_b)
    idx = np.arange(n)

    notes = []
    stamps = np.asarray(ds_a.variables["time"][:]).astype(np.int64).ravel()
    repeats = int(stamps.size - np.unique(stamps).size)
    if repeats:
        notes.append(
            f"{repeats} of {stamps.size} one-second stamps are repeats, so `time` "
            "does not identify a row; the join is positional on the Time index "
            "and `time` is verified as an ordinary class-A variable"
        )
    if n_a != n_b:
        notes.append(
            f"Time axes differ in length ({n_a} vs {n_b}); compared over the "
            f"first {n} rows only"
        )

    return JoinResult(idx, idx,
                      np.arange(n, n_a), np.arange(n, n_b),
                      n_a, n_b, duplicate_keys=0), notes


def compare_sd_files(path_a, path_b, classes=None) -> ComparisonReport:
    """Join and compare two ``sizeDist`` size-distribution files."""
    import netCDF4

    classes = SD_CLASSES if classes is None else classes
    with netCDF4.Dataset(str(path_a)) as a, netCDF4.Dataset(str(path_b)) as b:
        join, notes = join_seconds(a, b)
        variables = compare_variables(a, b, join, classes)
    return ComparisonReport(join, variables, str(path_a), str(path_b),
                            join_key=SD_JOIN_KEY, notes=notes)


def file_kind(path) -> str:
    """``"proc"`` or ``"sd"``, from the dimensions rather than the filename.

    A filename is not evidence -- the standing rule from the decode stage, and the reason this
    reads the structure instead.  A proc file dimensions its particle axis
    ``time`` (lower case, one row per particle); a sd file dimensions its
    one-second axis ``Time`` alongside ``CIPcorrlen``.
    """
    import netCDF4

    with netCDF4.Dataset(str(path)) as ds:
        if "CIPcorrlen" in ds.dimensions and "Time" in ds.dimensions:
            return "sd"
        if "time" in ds.dimensions:
            return "proc"
        raise ValueError(
            f"{path}: neither a proc file (dimension 'time') nor a sizeDist file "
            f"(dimensions 'Time' and 'CIPcorrlen'); has {sorted(ds.dimensions)}"
        )


def compare_files(path_a, path_b, classes=None) -> ComparisonReport:
    """Compare two UIOOPS files, choosing the join from what they are."""
    kind_a, kind_b = file_kind(path_a), file_kind(path_b)
    if kind_a != kind_b:
        raise ValueError(
            f"cannot compare a {kind_a} file against a {kind_b} file: "
            f"{path_a} vs {path_b}"
        )
    if kind_a == "sd":
        return compare_sd_files(path_a, path_b, classes)
    return compare_proc_files(path_a, path_b, classes)


def format_report(report: ComparisonReport, verbose: bool = False,
                  accepted: bool | None = None) -> str:
    """Render a report.

    ``accepted`` overrides the verdict line. The CLI passes the decision it
    computed over the WHOLE file, so that filtering the table with ``--var``
    cannot turn a failing comparison into a green one.
    """
    j = report.join
    lines = [
        f"left : {report.left}",
        f"right: {report.right}",
        "",
        "JOIN  " + " | ".join(report.join_key),
        f"  matched {j.n_matched} of {j.n_left} left / {j.n_right} right "
        f"({j.join_fraction * 100:.4f}%)",
    ]
    lines += [f"  note: {n}" for n in report.notes]
    if j.duplicate_keys:
        lines.append(
            f"  !! {j.duplicate_keys} duplicate keys — the join key does not "
            "identify a particle here, so every value comparison below is suspect"
        )
    noun = "seconds" if report.join_key == SD_JOIN_KEY else "particles"
    for side, only in (("left", j.left_only), ("right", j.right_only)):
        if only.size:
            runs = j.unmatched_runs(side)
            biggest = max(runs, key=lambda r: r[1])
            lines.append(
                f"  {side}-only: {only.size} {noun} in {len(runs)} run(s); "
                f"largest run {biggest[1]} from index {biggest[0]}"
            )

    lines += ["", f"{'VARIABLE':34s} {'CLS':4s} {'VERDICT':8s} {'N DIFF':>9s}  DETAIL"]
    for v in sorted(report.variables, key=lambda x: (x.verdict == "EXACT", x.name)):
        if v.verdict == "EXACT" and not verbose:
            continue
        n = f"{v.n_diff}/{v.n_total}" if v.n_total else "-"
        lines.append(f"{v.name:34s} {v.tclass:4s} {v.verdict:8s} {n:>9s}  {v.detail}")

    exact = sum(1 for v in report.variables if v.verdict == "EXACT")
    lines += [
        "",
        f"{exact}/{len(report.variables)} variables bit-exact over the joined "
        f"{'seconds' if report.join_key == SD_JOIN_KEY else 'particles'}.",
        f"ACCEPTED: {report.accepted() if accepted is None else accepted}",
    ]
    if report.unclassified:
        lines.append(
            "  blocked by unclassified variables: "
            + ", ".join(v.name for v in report.unclassified)
        )
    return "\n".join(lines)
