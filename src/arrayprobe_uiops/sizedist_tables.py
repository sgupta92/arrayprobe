# SPDX-License-Identifier: BSD-3-Clause
"""The self-contained pieces of v3.5's ``sizeDist.m``.

Three things, none of which needs the netCDF input the whole driver needs:

1. **The per-campaign / per-probe defaults** set by the ``switch projectname``
   block (v3.5 ``sizeDist.m:139-642``; v3.1.4 ``:107-511``): ``num_bins``, the
   bin-edge vector ``kk``, and the ten other per-probe constants assigned
   alongside them.  Both releases' tables are held here so the diff between
   them is a computed fact (:func:`diff_tables`), not a sentence.
2. **The ``varargin`` block** (``:98-110``), which is where the new
   ``iaThreshType == 3`` (1-Hz threshold) mode enters, and the per-second
   shatter-flagging / reacceptance block it drives (``:1383-1428``).
3. **``iNewHabit`` detection** (``:117-123``): the switch that the V1
   ``single_area`` / ``single_mass`` port consumes.

Every table and every branch below is asserted against a real Octave run of the
vendored source's own lines (``octave_oracle/run_v35_sizedist_tables_bank.py``,
fixture ``tests/data/v35_sizedist_tables_oracle.json``) in
``tests/test_v35_sizedist_tables.py``.  **Oracle layer 2 only** -- no archived
product was ever produced by v3.5, so nothing here has layer-1 validation.

Where the two releases differ, the difference is a **science change** made by
the upstream authors, not a defect; neither side is "fixed" here.  The largest:
the ``otherwise/2DS`` case -- the one an ORACLES run resolves to -- carries the
128-bin 10 um ladder in v3.1.4 and the **HVPS 28-bin 0.2-30 mm table** in v3.5.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from arrayprobe_uiops.constants import _colon

__all__ = [
    "BinLadder",
    "BinLiteral",
    "ProbeDefaults",
    "UndefinedProbeCase",
    "V314_TABLES",
    "V35_TABLES",
    "V35_CAMPAIGNS",
    "V314_CAMPAIGNS",
    "probe_defaults",
    "diff_tables",
    "InterarrivalThresholdSpec",
    "select_interarrival_threshold",
    "flag_shattered_1hz",
    "reaccept_shattered_1hz",
    "HABIT_ATTR_OLD",
    "HABIT_ATTR_NEW",
    "HABIT_SCHEME_SENTINEL_VARIABLE",
    "detect_habit_scheme",
]


# ---------------------------------------------------------------------------
# 1. The per-campaign / per-probe defaults
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BinLadder:
    """``kk = diodesize/2:diodesize:(num_bins+0.6)*diodesize`` -- a colon-built ladder.

    Source: the ``switch projectname`` block of ``sizeDist.m:139-642`` (UIOOPS v3.5; v3.1.4
    ``:107-511``).

    Built with :func:`arrayprobe.constants._colon`, which knows that MATLAB
    fills a colon range from both ends and Octave does not (they differ by one
    ULP in the upper half).  ``octave_colon=True`` exists only so the Octave
    fixture can be compared bit-for-bit; the port targets MATLAB.
    """

    def edges(self, diodesize: float, num_bins: int, *, octave_colon: bool = False) -> np.ndarray:
        return _colon(
            diodesize / 2, diodesize, (num_bins + 0.6) * diodesize, matlab=not octave_colon
        )


@dataclass(frozen=True)
class BinLiteral:
    """``kk = [microns ...] * times / 1000`` -- a literal table, in the source's
    own operation order (``*8`` then ``/1000`` for 2DP; ``/1000`` alone otherwise).

    Source: the ``switch projectname`` block of ``sizeDist.m:139-642`` (UIOOPS v3.5; v3.1.4
    ``:107-511``)."""

    microns: tuple[float, ...]
    times: float = 1.0

    def edges(self, diodesize: float, num_bins: int, *, octave_colon: bool = False) -> np.ndarray:
        arr = np.asarray(self.microns, dtype=np.float64)
        if self.times != 1.0:
            arr = arr * self.times
        return arr / 1000


@dataclass(frozen=True)
class ProbeDefaults:
    """Everything one ``case`` of the inner ``switch probename`` assigns.

    Source: the ``switch projectname`` block of ``sizeDist.m:139-642`` (UIOOPS v3.5; v3.1.4
    ``:107-511``).

    ``tasMax`` is ``None`` for 2DP, which assigns none in either release (the
    earlier translation already ships that crash).  ``intar_threshold_defaulted`` records
    whether the case runs ``intar_threshold = ones(size(tas_time))*defaultIntArrThresh``;
    ``calls_getPECANparams`` records the PECAN cases' call to a function that
    exists in **neither** vendored tree (measured: both releases error there).
    """

    num_diodes: int
    diodesize: float
    armdst: float
    num_bins: int
    bins: BinLadder | BinLiteral
    probetype: int
    tasMax: float | None
    applyIntArrThresh: int
    defaultIntArrThresh: float
    reaccptShatrs: int
    reaccptD: float
    reaccptMaxIA: float
    intar_threshold_defaulted: bool
    calls_getPECANparams: bool = False

    def kk(self, *, octave_colon: bool = False) -> np.ndarray:
        return self.bins.edges(self.diodesize, self.num_bins, octave_colon=octave_colon)


class UndefinedProbeCase(LookupError):
    """The inner ``switch probename`` has no ``otherwise``: an unlisted probe
    leaves ``num_bins``/``kk`` (and everything else) unassigned, and the driver
    fails later on the first use.  The port refuses up front rather than invent
    a table.

    Source: the ``switch projectname`` block of ``sizeDist.m:139-642`` (UIOOPS v3.5; v3.1.4
    ``:107-511``)."""


_LADDER = BinLadder()

# Shared literal tables (microns), named for where they first appear.
_CIP19 = BinLiteral(
    (
        50.0,
        100.0,
        150.0,
        200.0,
        250.0,
        300.0,
        350.0,
        400.0,
        475.0,
        550.0,
        625.0,
        700.0,
        800.0,
        900.0,
        1000.0,
        1200.0,
        1400.0,
        1600.0,
        1800.0,
        2000.0,
    )
)
_2DP19 = BinLiteral(_CIP19.microns, times=8.0)
_HVPS28 = BinLiteral(
    (
        200.0,
        400.0,
        600.0,
        800.0,
        1000.0,
        1200.0,
        1400.0,
        1600.0,
        1800.0,
        2200.0,
        2600.0,
        3000.0,
        3400.0,
        3800.0,
        4200.0,
        4600.0,
        5000.0,
        6000.0,
        7000.0,
        8000.0,
        9000.0,
        10000.0,
        12000.0,
        14000.0,
        16000.0,
        18000.0,
        20000.0,
        25000.0,
        30000.0,
    )
)
_GPM_2DS22 = BinLiteral(
    (
        40.0,
        60.0,
        80.0,
        100.0,
        125.0,
        150.0,
        200.0,
        250.0,
        300.0,
        350.0,
        400.0,
        475.0,
        550.0,
        625.0,
        700.0,
        800.0,
        900.0,
        1000.0,
        1200.0,
        1400.0,
        1600.0,
        1800.0,
        2000.0,
    )
)
_SOC_2DS21 = BinLiteral(
    (
        50.0,
        75.0,
        100.0,
        125.0,
        150.0,
        200.0,
        250.0,
        300.0,
        350.0,
        400.0,
        475.0,
        550.0,
        625.0,
        700.0,
        800.0,
        900.0,
        1000.0,
        1200.0,
        1400.0,
        1600.0,
        1800.0,
        2000.0,
    )
)
_SOC_F2DC17 = BinLiteral(
    (
        150.0,
        200.0,
        250.0,
        300.0,
        350.0,
        400.0,
        475.0,
        550.0,
        625.0,
        700.0,
        800.0,
        900.0,
        1000.0,
        1200.0,
        1400.0,
        1600.0,
        1800.0,
        2000.0,
    )
)
_SOC_PIP27 = BinLiteral(
    (
        150.0,
        200.0,
        250.0,
        300.0,
        350.0,
        400.0,
        475.0,
        550.0,
        625.0,
        700.0,
        800.0,
        900.0,
        1000.0,
        1200.0,
        1400.0,
        1600.0,
        1800.0,
        2000.0,
        2400.0,
        2800.0,
        3200.0,
        3600.0,
        4000.0,
        4800.0,
        5600.0,
        6400.0,
        7200.0,
        8000.0,
    )
)
_IMP_2DS29 = BinLiteral(
    (
        20.0,
        40.0,
        60.0,
        80.0,
        100.0,
        125.0,
        150.0,
        200.0,
        250.0,
        300.0,
        350.0,
        400.0,
        475.0,
        550.0,
        625.0,
        700.0,
        800.0,
        900.0,
        1000.0,
        1200.0,
        1400.0,
        1600.0,
        1800.0,
        2000.0,
        2200.0,
        2400.0,
        2600.0,
        2800.0,
        3000.0,
        3200.0,
    )
)
_IMP_3VH25 = BinLiteral(
    (
        100.0,
        125.0,
        150.0,
        200.0,
        250.0,
        300.0,
        350.0,
        400.0,
        475.0,
        550.0,
        625.0,
        700.0,
        800.0,
        900.0,
        1000.0,
        1200.0,
        1400.0,
        1600.0,
        1800.0,
        2000.0,
        2200.0,
        2400.0,
        2600.0,
        2800.0,
        3000.0,
        3200.0,
    )
)


def _pd(nd: Any, ds: Any, arm: Any, nb: Any, bins: Any, pt: Any, tasmax: Any, a: Any, d: Any,
        rs: Any, rd: Any, rmia: Any, itdef: Any, pecan: Any = False) -> ProbeDefaults:
    return ProbeDefaults(nd, ds, arm, nb, bins, pt, tasmax, a, d, rs, rd, rmia, itdef, pecan)


# The ``otherwise`` branch, keyed by the sentinel campaign name ``None``.
OTHERWISE = None

#: v3.1.4 ``sizeDist.m:107-511`` (measured under Octave, see module docstring).
V314_TABLES: dict[str | None, dict[str, ProbeDefaults]] = {
    "PECAN": {
        "CIP": _pd(
            64, 0.025, 100.0, 19, _CIP19, 1, 200.0, 1, 1e-5, 1, 0.5, 2.5e-7, False, pecan=True
        ),
        "PIP": _pd(64, 0.1, 260.0, 64, _LADDER, 1, 200.0, 1, 1e-5, 1, 0.5, 1e-6, False, pecan=True),
    },
    "GPM": {
        "2DS": _pd(128, 0.010, 63.0, 22, _GPM_2DS22, 2, 170.0, 1, 1e-6, 1, 0.5, 1e-6, False),
        "CIP": _pd(64, 0.025, 100.0, 19, _CIP19, 1, 200.0, 1, 1e-6, 1, 0.5, 2.5e-7, False),
        "2DC": _pd(32, 0.03, 61.0, 19, _CIP19, 0, 125.0, 1, 1e-5, 0, 0.5, 1e-6, True),
        "HVPS": _pd(128, 0.150, 161.0, 28, _HVPS28, 2, 170.0, 0, 1e-6, 0, 0.5, 1e-6, False),
    },
    "SOCRATES": {
        "2DS": _pd(128, 0.010, 63.0, 21, _SOC_2DS21, 2, 170.0, 1, 1e-6, 1, 0.05, 1e-6, True),
        "Fast2DC": _pd(64, 0.025, 61.0, 17, _SOC_F2DC17, 3, 300.0, 1, 4e-6, 1, 0.15, 2.5e-6, True),
        "PIP": _pd(64, 0.1, 260.0, 27, _SOC_PIP27, 1, 200.0, 0, 1e-5, 0, 0.5, 1e-6, True),
    },
    OTHERWISE: {
        "HVPS": _pd(128, 0.150, 161.0, 28, _HVPS28, 2, 170.0, 0, 4e-6, 0, 0.5, 1e-6, True),
        "2DS": _pd(128, 0.010, 63.0, 128, _LADDER, 2, 170.0, 0, 4e-6, 0, 0.5, 1e-6, True),
        "CIP": _pd(64, 0.025, 100.0, 19, _CIP19, 1, 200.0, 0, 1e-5, 0, 0.5, 1e-6, True),
        "PIP": _pd(64, 0.1, 260.0, 64, _LADDER, 1, 200.0, 0, 1e-5, 0, 0.5, 1e-6, True),
        "2DC": _pd(32, 0.03, 61.0, 19, _CIP19, 0, 125.0, 0, 4e-6, 0, 0.5, 1e-6, True),
        "2DP": _pd(32, 0.200, 260.0, 19, _2DP19, 0, None, 0, 4e-6, 0, 0.5, 1e-6, True),
        "F2DC": _pd(64, 0.025, 61.0, 19, _CIP19, 3, 300.0, 0, 4e-6, 0, 0.5, 1e-6, True),
    },
}

#: v3.5 ``sizeDist.m:139-642``.
V35_TABLES: dict[str | None, dict[str, ProbeDefaults]] = {
    "PECAN": V314_TABLES["PECAN"],
    "GPM": {
        "2DS": V314_TABLES["GPM"]["2DS"],
        # applyIntArrThresh 1 -> 0 and reaccptShatrs 1 -> 0; bins unchanged.
        "CIP": _pd(64, 0.025, 100.0, 19, _CIP19, 1, 200.0, 0, 1e-6, 0, 0.5, 2.5e-7, False),
        "2DC": V314_TABLES["GPM"]["2DC"],
        "HVPS": V314_TABLES["GPM"]["HVPS"],
    },
    "SOCRATES": {
        # 21 literal bins (50 um - 2 mm) -> 256-bin 10 um ladder (5 um - 2.565 mm).
        "2DS": _pd(128, 0.010, 63.0, 256, _LADDER, 2, 170.0, 1, 1e-6, 1, 0.05, 1e-6, True),
        # 17 literal bins (150 um - 2 mm) -> 128-bin 25 um ladder (12.5 um - 3.2125 mm).
        "Fast2DC": _pd(64, 0.025, 61.0, 128, _LADDER, 3, 300.0, 1, 4e-6, 1, 0.15, 2.5e-6, True),
        "PIP": V314_TABLES["SOCRATES"]["PIP"],
    },
    "IMPACTS": {
        "2DS": _pd(128, 0.010, 63.0, 29, _IMP_2DS29, 2, 170.0, 1, 1e-6, 1, 0.5, 1e-6, False),
        "3VCPI_V": _pd(128, 0.010, 50.8, 29, _IMP_2DS29, 2, 170.0, 1, 1e-6, 1, 0.5, 1e-6, False),
        "3VCPI_H": _pd(128, 0.050, 50.8, 25, _IMP_3VH25, 2, 170.0, 1, 1e-6, 1, 0.5, 2.5e-6, False),
        "HVPS": _pd(128, 0.150, 161.0, 28, _HVPS28, 2, 170.0, 0, 1e-6, 0, 0.5, 1e-6, False),
    },
    OTHERWISE: {
        "HVPS": V314_TABLES[OTHERWISE]["HVPS"],
        # 128-bin 10 um ladder -> the HVPS 28-bin table (0.2 - 30 mm), verbatim.
        "2DS": _pd(128, 0.010, 63.0, 28, _HVPS28, 2, 170.0, 0, 4e-6, 0, 0.5, 1e-6, True),
        "CIP": V314_TABLES[OTHERWISE]["CIP"],
        "PIP": V314_TABLES[OTHERWISE]["PIP"],
        "2DC": V314_TABLES[OTHERWISE]["2DC"],
        "2DP": V314_TABLES[OTHERWISE]["2DP"],
        "F2DC": V314_TABLES[OTHERWISE]["F2DC"],
    },
}

V314_CAMPAIGNS = tuple(k for k in V314_TABLES if k is not None)
V35_CAMPAIGNS = tuple(k for k in V35_TABLES if k is not None)


def probe_defaults(projectname: str, probename: str, *, version: str = "3.5") -> ProbeDefaults:
    """Resolve ``(projectname, probename)`` exactly as the ``switch`` does.

    Source: the ``switch projectname`` block of ``sizeDist.m:139-642`` (UIOOPS v3.5; v3.1.4
    ``:107-511``).

    An unlisted campaign takes the ``otherwise`` branch; an unlisted probe
    *within* a branch raises :class:`UndefinedProbeCase` (the inner switch has
    no ``otherwise``).  Case-sensitive, as MATLAB's ``switch`` on strings is.
    """
    tables = {"3.5": V35_TABLES, "3.1.4": V314_TABLES}[version]
    branch = tables.get(projectname, tables[OTHERWISE])
    try:
        return branch[probename]
    except KeyError:
        raise UndefinedProbeCase(
            f"sizeDist v{version}: no case for probe {probename!r} under "
            + ("campaign " + repr(projectname) if projectname in tables else "the otherwise branch")
        ) from None


@dataclass(frozen=True)
class TableDiff:
    campaign: str
    probe: str
    status: str  # "unchanged" | "changed" | "new" | "removed"
    changed_fields: tuple[str, ...]
    v314: ProbeDefaults | None
    v35: ProbeDefaults | None


def diff_tables(
    campaigns: Sequence[str] = ("PECAN", "GPM", "SOCRATES", "IMPACTS", "ORACLES"),
) -> list[TableDiff]:
    """The complete v3.1.4 -> v3.5 diff over ``campaigns`` x every probe either
    release names.  ``ORACLES`` (or any unlisted name) exercises ``otherwise``."""
    probes = sorted({p for t in (V314_TABLES, V35_TABLES) for b in t.values() for p in b})
    fields = [f for f in ProbeDefaults.__dataclass_fields__ if f != "bins"]
    out = []
    for c in campaigns:
        for p in probes:
            old = new = None
            try:
                old = probe_defaults(c, p, version="3.1.4")
            except UndefinedProbeCase:
                pass
            try:
                new = probe_defaults(c, p, version="3.5")
            except UndefinedProbeCase:
                pass
            if old is None and new is None:
                continue
            if old is None:
                out.append(TableDiff(c, p, "new", (), None, new))
            elif new is None:
                out.append(TableDiff(c, p, "removed", (), old, None))
            else:
                changed = [f for f in fields if getattr(old, f) != getattr(new, f)]
                if not np.array_equal(old.kk(), new.kk()):
                    changed.append("kk")
                out.append(
                    TableDiff(c, p, "changed" if changed else "unchanged", tuple(changed), old, new)
                )
    return out


# ---------------------------------------------------------------------------
# 2. iaThreshType: the varargin block and the 1-Hz (type 3) shatter block
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InterarrivalThresholdSpec:
    """What v3.5 ``sizeDist.m:98-110`` leaves behind.

    ``ia_thresh_file`` is ``None`` where MATLAB leaves ``iaThreshFile``
    **unassigned** -- one argument with ``iaThreshType`` 0 or 2 (v3.1.4 assigned
    ``varargin{1}`` unconditionally; v3.5's inner ``if/elseif`` has no ``else``).
    Latent in v3.5 because the only later read, ``:1179``, is short-circuited
    behind ``iaThreshType == 1``.  ``iat_thresh`` is the per-second array, set
    only for type 3 with exactly one argument.
    """

    ia_thresh_file: str | object | None
    iat_thresh: np.ndarray | None
    too_many_inputs: bool


def select_interarrival_threshold(
    ia_thresh_type: int, varargin: Sequence[object]
) -> InterarrivalThresholdSpec:
    """v3.5 ``sizeDist.m:98-110``, as a pure function of the call's inputs."""
    n = len(varargin)
    if n == 1:
        if ia_thresh_type == 1:
            return InterarrivalThresholdSpec(varargin[0], None, False)
        if ia_thresh_type == 3:
            return InterarrivalThresholdSpec(
                "NONE", np.asarray(varargin[0], dtype=np.float64), False
            )
        return InterarrivalThresholdSpec(None, None, False)
    if n > 1:
        return InterarrivalThresholdSpec("NONE", None, True)
    return InterarrivalThresholdSpec("NONE", None, False)


def flag_shattered_1hz(
    int_arr: Sequence[float], thresh: float, auto_reject: Sequence[str] | None = None
) -> np.ndarray:
    """v3.5 ``sizeDist.m:1384-1396``: the type-3 shatter flagging for one second.

    ``thresh`` is ``iatThresh(i)`` for that second.  A particle at or below the
    threshold is ``'S'``, and so is the one immediately before it (``(ix-1):ix``).
    Returns the per-particle reject codes (1-D ``<U1`` array).
    """
    ia = np.asarray(int_arr, dtype=np.float64).ravel()
    rej = np.array(["A"] * ia.size if auto_reject is None else list(auto_reject), dtype="<U1")
    if ia.size == 0:
        return rej
    if ia.size == 1 and ia[0] <= thresh:
        rej[0] = "S"
    else:
        if ia[0] <= thresh:
            rej[0] = "S"
        for ix in range(1, ia.size):  # MATLAB ix = 2:length(int_arr)
            if ia[ix] <= thresh:
                rej[ix - 1 : ix + 1] = "S"
    return rej


def reaccept_shattered_1hz(
    auto_reject: Sequence[str],
    int_arr: Sequence[float],
    int_arr3: Sequence[float],
    particle_diameter_minR: Sequence[float],
    thresh: float,
    *,
    reaccptD: float,
    reaccptMaxIA: float,
) -> tuple[np.ndarray, int | None]:
    """v3.5 ``sizeDist.m:1398-1428``: the type-3 block's reacceptance.

    **This is not the v3.1.4 reacceptance**, nor v3.5's own type-1/type-2 one.
    Those iterate ``find(rBegin):find(rEnd)`` -- which, through MATLAB's
    first-element colon rule, scans only the first shattering event (a preserved
    v3.1.4 bug).  v3.5 rewrites the type-3 block ("JF 11/5/25")
    to scan ``find(rBegin,1,'first'):find(rEnd,1,'last')``, one continuous range
    spanning every event.  Returns ``(auto_reject, eIndex)`` with ``eIndex`` the
    1-based index reaccepted, or ``None`` (MATLAB's ``[]``).
    """
    rej = np.array(list(auto_reject), dtype="<U1")
    ia = np.asarray(int_arr, dtype=np.float64).ravel()
    ia3 = np.asarray(int_arr3, dtype=np.float64).ravel()
    diam = np.asarray(particle_diameter_minR, dtype=np.float64).ravel()
    r_begin = (ia > thresh) & (ia3 < thresh)
    r_end = (ia < thresh) & (ia3 > thresh)
    max_particle = reaccptD
    e_index: int | None = None
    b = np.flatnonzero(r_begin)
    e = np.flatnonzero(r_end)
    if b.size and e.size and e[-1] >= b[0]:
        for i_event in range(b[0], e[-1] + 1):
            if diam[i_event] > max_particle and ia[i_event] < reaccptMaxIA:
                max_particle = diam[i_event]
                e_index = i_event + 1
    if e_index is not None:
        rej[e_index - 1] = "R"
    return rej, e_index


# ---------------------------------------------------------------------------
# 3. iNewHabit detection
# ---------------------------------------------------------------------------

HABIT_SCHEME_SENTINEL_VARIABLE = "width_length_percentile"
HABIT_ATTR_NEW = "Schima et al. (2024)"
HABIT_ATTR_OLD = "Holroyd (1987; doi:10.1175/1520-0426(1987)004<0498:STAUOC>2.0.CO;2)"


def detect_habit_scheme(variable_names: Sequence[str]) -> tuple[int, str]:
    """v3.5 ``sizeDist.m:117-123``: ``(iNewHabit, attr_habit)`` from the input
    file's variable list.  Exact, case-sensitive membership, as ``ismember`` on
    a cellstr is."""
    if HABIT_SCHEME_SENTINEL_VARIABLE in list(variable_names):
        return 1, HABIT_ATTR_NEW
    return 0, HABIT_ATTR_OLD
