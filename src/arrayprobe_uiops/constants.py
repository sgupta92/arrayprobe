# SPDX-License-Identifier: BSD-3-Clause
"""Probe- and project-specific configuration tables, transcribed from UIOOPS.

Two independent switch statements in the MATLAB source decide everything about a
run.  This module transcribes both, verbatim, so that no later stage re-derives a
literal from memory:

* ``imgProc_sm.m:117-193`` -- keyed on **probe name alone**.  Supplies the image
  boundary word, the boundary-time marker, diode size and diode count.
* ``sizeDist.m:107-511`` -- keyed on **(project, probe)**.  Supplies diode size
  and count again (they do NOT always agree -- see :data:`DIODESIZE_DISAGREEMENTS`),
  plus arm distance, the size-bin edges, probe type, the airspeed ceiling, and the
  inter-arrival / shattering-reacceptance parameters.

Fidelity doctrine: preserve bugs, do not fix them.  Three upstream defects are
transcribed rather than repaired, each with a named test:

1. ``('otherwise', '2DP')`` never assigns ``tasMax``.  MATLAB therefore raises an
   undefined-variable error the first time ``sizeDist.m:968`` compares against it.
   Here :attr:`ProbeConfig.tas_max` is ``None`` and reading
   :attr:`ProbeConfig.tasMax` raises :class:`MatlabUndefinedVariable`.
2. ``('GPM', '2DS')``, ``('GPM', 'CIP')`` and ``('GPM', 'HVPS')`` never assign
   ``intar_threshold``, though the first two switch inter-arrival thresholding ON.
   :attr:`ProbeConfig.sets_intar_threshold` records this; ``sizeDist.m:1135`` would
   fail on the undefined variable.
3. The 2DC diode size is ``0.025`` mm in ``imgProc_sm.m:123`` but ``0.030`` mm in
   ``sizeDist.m:186``.  Both are kept, in their own tables.


MATLAB source of truth: ``UIOPS-v3.1.4/joefinlon-UIOPS-ba5e67c/``.

Vocabulary note: this module says "particle", never "drop".  The package must work
for ice as well as liquid; a liquid noun in a public name is a design commitment we
do not want to make.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TypedDict

import numpy as np

__all__ = [
    "MatlabUndefinedVariable",
    "ImgProcConfig",
    "ProbeConfig",
    "IMGPROC_CONFIG",
    "SIZEDIST_CONFIG",
    "PROBE_TYPES",
    "DIODESIZE_DISAGREEMENTS",
    "PROJECTS",
    "imgproc_config",
    "sizedist_config",
    "bin_edges",
    "bin_width",
    "resolution_um",
]


class MatlabUndefinedVariable(NameError):
    """Raised where MATLAB would raise ``Undefined function or variable``.

    Transcribing an upstream omission as a Python default (``0``, ``inf``,
    ``None`` used silently) would turn a MATLAB *crash* into a Python *number*,
    which is a behaviour change.  So the omission is preserved as an error at the
    moment of use.
    """


# --------------------------------------------------------------------------
# Probe type codes -- sizeDist.m:627,774,791,796,802,811,852,923,938,945
# --------------------------------------------------------------------------

PROBE_TYPES = MappingProxyType({
    0: "2DC/2DP (PMS, 32 diodes, 4-byte boundary)",
    1: "CIP/PIP (DMT, 64 diodes)",
    2: "2DS/HVPS (SPEC, 128 diodes)",
    3: "Fast2DC/F2DC (64 diodes, 12 MHz clock)",
})


# --------------------------------------------------------------------------
# imgProc_sm.m:117-193 -- keyed on probe name alone
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ImgProcConfig:
    """One case of the ``imgProc_sm.m`` probe switch.

    Attributes mirror the MATLAB variable names one-for-one so a transliterated
    call site reads the same as its source line.
    """

    probename: str
    boundary: tuple[int, ...]
    """The inter-particle marker word repeated across a full slice.

    ``imgProc_sm.m:119,129`` (2DC/2DP), ``:139,149`` (CIP/PIP), ``:159,174``
    (HVPS/2DS), ``:189`` (Fast2DC).  The 2DS/HVPS value 43690 is ``0xAAAA``; the
    CIP/PIP/Fast2DC value 170 is ``0xAA``; the 2DC/2DP value 255 is ``0xFF``.
    """

    boundarytime: float
    """Marker following the boundary word.  ``NaN`` for the DMT probes."""

    ds: float
    """Diode size in millimetres (``imgProc_sm.m:123`` etc.)."""

    diodenum: int
    """Diode count (``imgProc_sm.m:125`` etc.)."""

    probetype: int
    """See :data:`PROBE_TYPES`."""

    needs_tas_file: bool = False
    """2DS and HVPS read TAS from ``varargin{1}`` (``imgProc_sm.m:167-170,180-185``)."""

    read_width: int = 8
    """Column count of the raw ``data`` read (``imgProc_sm.m:488-494``).

    NOT always ``len(boundary)`` -- Fast2DC reads 8 columns wide but has a
    THREE-word boundary (``:189``), so the two must be kept apart.
    Conflating them (deriving the read width from ``len(boundary)``) was a
    real port bug found while triaging (``imgproc.py:640``): it happens
    to coincide for probetypes 0, 1 and 2, so S3's probetype-2 path never
    exposed it."""

    read_slices: int = 1700
    """Slice count of the raw ``data`` read (``imgProc_sm.m:488-494``): 1024 for
    probetype 0, 512 for Fast2DC, 1700 otherwise.

    A **literal per probetype in all three MATLAB trees**, and the port used
    the input file's dimension-2 length instead until 2026-09-10. MATLAB reads
    that dimension (``:205-207``) and assigns ``size_mat = dimlen`` -- and then
    never mentions ``size_mat`` again. It is a dead store, and the port had
    quietly promoted it to the read count. The two coincide on every file the
    port's own writer produces (``ImgBlocklen`` == 1700), which is why nothing
    caught it; on the OLYMPEX distribution's own stitched file, whose second
    dimension is not the block length, they do not. The `inq_dim` call itself
    is kept, because MATLAB makes it and a file with fewer than three
    dimensions must fail the same way."""

    start_first: int = 1
    """Initial ``start`` before any particle is found (``:524-529``).

    2 for probetypes 0, 1, 3; 1 for probetype 2."""

    boundary_needs_time: bool = True
    """Whether the boundary test's second clause (``:523``) checks
    ``data(j+1,1)==boundarytime``.

    False for probetypes 1 and 3: their ``boundarytime`` is NaN and
    ``isequal(NaN,NaN)`` is false in MATLAB, so ``:523``'s
    ``|| probetype==1 || probetype==3`` disjunct exists purely to bypass a
    check that would otherwise never pass. Do not "fix" this into a
    NaN-tolerant comparison."""

    image_slice_offset: int = 0
    """Extra offset on the image slice's start index (``:534,:541,:555,:558``).

    1 for probetype 0 (``data(start+1:j-1,:)``), 0 otherwise
    (``data(start:j-1,:)``). The SAME value also offsets the corrupt/zero-image
    guard test, which reads ``start+offset > (j-1)`` -- not a coincidence:
    probetype 0's guard is exactly the emptiness of that offset slice."""

    image_invert: bool = False
    """Whether the image is built as ``65535 - data`` (``:562``, probetype 2
    only) or used as-is (``:556,:559`` -- the PMS/DMT raw formats already
    store 1 = illuminated, so no inversion is needed or applied)."""

    image_word_bits: int = 16
    """Bits per ``dec2bin`` word in the image construction (``:556-564``).

    8 for probetypes 0, 1, 3; 16 for probetype 2."""

    timing: str = "spec"
    """Which particle-timing branch (``:580-778``) this probe takes:
    ``'pms'`` (0), ``'dmt'`` (1), ``'spec'`` (2, ported), ``'fast2dc'`` (3)."""

    @property
    def byteperslice(self) -> int:
        """``imgProc_sm.m:200`` -- ``byteperslice = diodenum/8``."""
        return self.diodenum // 8


IMGPROC_CONFIG: MappingProxyType[str, ImgProcConfig] = MappingProxyType({
    cfg.probename: cfg
    for cfg in (
        # imgProc_sm.m:118-126
        ImgProcConfig("2DC", (255, 255, 255, 255), 85.0, 0.025, 32, 0,
                      read_slices=1024, read_width=4, start_first=2, boundary_needs_time=True,
                      image_slice_offset=1, image_invert=False,
                      image_word_bits=8, timing="pms"),
        # imgProc_sm.m:128-136
        ImgProcConfig("2DP", (255, 255, 255, 255), 85.0, 0.200, 32, 0,
                      read_slices=1024, read_width=4, start_first=2, boundary_needs_time=True,
                      image_slice_offset=1, image_invert=False,
                      image_word_bits=8, timing="pms"),
        # imgProc_sm.m:138-146
        ImgProcConfig("CIP", (170,) * 8, float("nan"), 0.025, 64, 1,
                      read_width=8, start_first=2, boundary_needs_time=False,
                      image_slice_offset=0, image_invert=False,
                      image_word_bits=8, timing="dmt"),
        # imgProc_sm.m:148-156
        ImgProcConfig("PIP", (170,) * 8, float("nan"), 0.100, 64, 1,
                      read_width=8, start_first=2, boundary_needs_time=False,
                      image_slice_offset=0, image_invert=False,
                      image_word_bits=8, timing="dmt"),
        # imgProc_sm.m:158-172
        ImgProcConfig("HVPS", (43690,) * 8, 0.0, 0.150, 128, 2, needs_tas_file=True,
                      read_width=8, start_first=1, boundary_needs_time=True,
                      image_slice_offset=0, image_invert=True,
                      image_word_bits=16, timing="spec"),
        # imgProc_sm.m:173-187
        ImgProcConfig("2DS", (43690,) * 8, 0.0, 0.010, 128, 2, needs_tas_file=True,
                      read_width=8, start_first=1, boundary_needs_time=True,
                      image_slice_offset=0, image_invert=True,
                      image_word_bits=16, timing="spec"),
        # imgProc_sm.m:188-197 -- note the boundary is THREE words, not four or eight
        ImgProcConfig("Fast2DC", (170, 170, 170), float("nan"), 0.025, 64, 3,
                      read_slices=512, read_width=8, start_first=2, boundary_needs_time=False,
                      image_slice_offset=0, image_invert=False,
                      image_word_bits=8, timing="fast2dc"),
    )
})


# --------------------------------------------------------------------------
# sizeDist.m:107-511 -- keyed on (project, probe)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ProbeConfig:
    """One case of the ``sizeDist.m`` project/probe switch.

    ``kk`` is stored in millimetres, already divided (or multiplied) as the source
    line does, so the literal here equals the MATLAB value at the end of its own
    assignment.
    """

    project: str
    probename: str
    num_diodes: int
    diodesize: float
    """Millimetres.  Disagrees with :attr:`ImgProcConfig.ds` for the 2DC."""

    armdst: float
    """Arm separation in millimetres (sample-area geometry)."""

    num_bins: int
    kk: np.ndarray
    """Size-bin **edges** in millimetres.  ``len(kk) == num_bins + 1`` in every case."""

    probetype: int
    tas_max: float | None
    """``None`` where MATLAB leaves ``tasMax`` unassigned -- see :attr:`tasMax`."""

    apply_int_arr_thresh: bool
    default_int_arr_thresh: float
    reaccpt_shatrs: bool
    reaccpt_d: float
    """Minimum particle diameter (mm) eligible for shattering reacceptance."""

    reaccpt_max_ia: float
    """Maximum inter-arrival time (s) eligible for shattering reacceptance."""

    sets_intar_threshold: bool
    """False where the case never assigns ``intar_threshold`` (upstream omission)."""

    needs_pecan_params: bool = False
    """PECAN cases call ``getPECANparams``, which does not exist in the repo."""

    source_line: str = ""
    """``file:line`` of the case, so a reader can check the transcription."""

    kk_octave: np.ndarray | None = None
    """The ladder **Octave** would build, where that differs from MATLAB's.

    Only the three colon-built cases differ (see :func:`_colon`); every ladder
    written as an explicit literal is identical in both.  This exists solely so
    an Octave golden can be compared bit-for-bit -- it is never what the port
    computes by default.  ``None`` means "the same as :attr:`kk`", and
    :meth:`__post_init__` fills it in so callers need no special case.
    """

    def __post_init__(self) -> None:
        object.__setattr__(self, "kk", np.asarray(self.kk, dtype=np.float64))
        oct_kk = self.kk if self.kk_octave is None else np.asarray(
            self.kk_octave, dtype=np.float64)
        if oct_kk.shape != self.kk.shape:
            raise ValueError(
                f"kk_octave has {oct_kk.size} edges but kk has {self.kk.size}; "
                "the two ladders must differ only in rounding, never in length"
            )
        object.__setattr__(self, "kk_octave", oct_kk)

    @property
    def tasMax(self) -> float:  # noqa: N802 -- MATLAB name, deliberately
        """``tasMax``, raising where MATLAB would.

        ``('otherwise', '2DP')`` (``sizeDist.m:465-489``) never assigns it, so
        ``sizeDist.m:640`` and ``:968`` fail there.  Preserved, not defaulted.
        """
        if self.tas_max is None:
            raise MatlabUndefinedVariable(
                f"tasMax is not assigned for project={self.project!r} "
                f"probename={self.probename!r} (sizeDist.m:465-489 omits it); "
                "MATLAB raises 'Undefined function or variable' at sizeDist.m:968. No "
                "default exists: tasMax is the fastest airspeed the probe's clock samples "
                "without skewed images, a property of the instrument no release states for "
                "the 2DP. Pass tas_max=<m/s> with your probe's value."
            )
        return self.tas_max

    @property
    def res(self) -> float:
        """``sizeDist.m:522`` -- ``res = diodesize*1000``, i.e. microns."""
        return self.diodesize * 1000.0

    @property
    def binwidth(self) -> np.ndarray:
        """``sizeDist.m:523`` -- ``binwidth = diff(kk)``, length ``num_bins``."""
        return np.diff(self.kk)


def _colon(start: float, step: float, stop: float, *,
           matlab: bool = True) -> np.ndarray:
    """MATLAB ``start:step:stop``, for the eight cases that build ``kk`` this way.

    ``sizeDist.m:143`` (PECAN/PIP), ``:388`` (otherwise/2DS), ``:420``
    (otherwise/PIP) and their ORACLES-variant counterparts, plus the
    production tree's ``otherwise`` HVPS and CIP cases.  MATLAB's colon
    operator is inclusive of ``stop`` when it
    lands on a grid point and is computed to avoid accumulated rounding, which is
    what ``np.arange`` does not guarantee -- so the count is derived first.

    **MATLAB fills the result from both ends toward the middle**, and this is
    not a detail that can be skipped.  Elements in the lower half are computed
    as ``start + k*step``; those in the upper half as ``last - (m-k)*step``,
    where ``m`` is the number of steps and ``last = start + m*step``.  The two
    routes disagree in the last bit, so a naive ``start + k*step`` throughout
    gets the upper half wrong by one ULP.

    Measured 2026-09-03: for the ORACLES 2D-S ladder
    (``0.005:0.010:128.6*0.010``, 129 points) the naive form differs from the
    archived MATLAB product's own ``Bin Minimum``/``Bin Maximum`` bytes in
    **34 of 129 edges**, each by 2.2e-16 mm, all in the upper half; the
    two-sided form reproduces all 129 exactly.
    ``tests/test_bin_ladder.py`` pins that against the product.

    **Octave is not an oracle for this.** Octave's colon computes
    ``start + k*step`` throughout and agrees with the naive form, so the
    project's usual differential oracle would have confirmed the wrong answer
    here -- the archived product's bytes are what settled it.  Pass
    ``matlab=False`` to get Octave's construction, which exists **only** so an
    Octave golden can still be compared bit-for-bit; it is never the port's
    default, because the port targets MATLAB.
    """
    m = int(np.floor((stop - start) / step + 1e-10))
    k = np.arange(m + 1, dtype=np.float64)
    out = start + step * k
    if not matlab:
        return out
    last = start + step * m
    upper = k > m // 2
    out[upper] = last - step * (m - k[upper])
    return out


class _ColonPair(TypedDict):
    """The two ladders a colon-built case needs, named for keyword expansion."""

    kk: np.ndarray
    kk_octave: np.ndarray


def _colon_pair(start: float, step: float, stop: float) -> _ColonPair:
    """Both ladders for a colon-built case, from one set of parameters.

    Expanded into a :class:`ProbeConfig` as ``**_colon_pair(...)``, so ``kk``
    and ``kk_octave`` can never drift apart or be transcribed differently --
    the failure mode of writing the same three numbers twice.  The
    :class:`TypedDict` return is what lets the expansion keep its types.
    """
    return {
        "kk": _colon(start, step, stop),
        "kk_octave": _colon(start, step, stop, matlab=False),
    }


# The nineteen-bin ladder shared by CIP, 2DC, F2DC and 2DP (the last scaled by 8).
_KK19_UM = np.array([
    50.0, 100.0, 150.0, 200.0, 250.0, 300.0, 350.0, 400.0, 475.0, 550.0, 625.0,
    700.0, 800.0, 900.0, 1000.0, 1200.0, 1400.0, 1600.0, 1800.0, 2000.0,
])

_KK_HVPS_UM = np.array([
    200.0, 400.0, 600.0, 800.0, 1000.0, 1200.0, 1400.0, 1600.0, 1800.0, 2200.0,
    2600.0, 3000.0, 3400.0, 3800.0, 4200.0, 4600.0, 5000.0, 6000.0, 7000.0,
    8000.0, 9000.0, 10000.0, 12000.0, 14000.0, 16000.0, 18000.0, 20000.0,
    25000.0, 30000.0,
])

_KK_GPM_2DS_UM = np.array([
    40.0, 60.0, 80.0, 100.0, 125.0, 150.0, 200.0, 250.0, 300.0, 350.0, 400.0,
    475.0, 550.0, 625.0, 700.0, 800.0, 900.0, 1000.0, 1200.0, 1400.0, 1600.0,
    1800.0, 2000.0,
])

_KK_SOCRATES_2DS_UM = np.array([
    50.0, 75.0, 100.0, 125.0, 150.0, 200.0, 250.0, 300.0, 350.0, 400.0, 475.0,
    550.0, 625.0, 700.0, 800.0, 900.0, 1000.0, 1200.0, 1400.0, 1600.0, 1800.0,
    2000.0,
])

_KK_SOCRATES_FAST2DC_UM = np.array([
    150.0, 200.0, 250.0, 300.0, 350.0, 400.0, 475.0, 550.0, 625.0, 700.0, 800.0,
    900.0, 1000.0, 1200.0, 1400.0, 1600.0, 1800.0, 2000.0,
])

_KK_SOCRATES_PIP_UM = np.array([
    150.0, 200.0, 250.0, 300.0, 350.0, 400.0, 475.0, 550.0, 625.0, 700.0, 800.0,
    900.0, 1000.0, 1200.0, 1400.0, 1600.0, 1800.0, 2000.0, 2400.0, 2800.0,
    3200.0, 3600.0, 4000.0, 4800.0, 5600.0, 6400.0, 7200.0, 8000.0,
])


_CONFIGS: tuple[ProbeConfig, ...] = (
    # ---- PECAN (sizeDist.m:108-160) --------------------------------------
    ProbeConfig(
        project="PECAN", probename="CIP", num_diodes=64, diodesize=0.025,
        armdst=100.0, num_bins=19, kk=_KK19_UM / 1000.0, probetype=1,
        tas_max=200.0, apply_int_arr_thresh=True, default_int_arr_thresh=1e-5,
        reaccpt_shatrs=True, reaccpt_d=0.5, reaccpt_max_ia=2.5e-7,
        sets_intar_threshold=True, needs_pecan_params=True,
        source_line="sizeDist.m:110-146",
    ),
    ProbeConfig(
        project="PECAN", probename="PIP", num_diodes=64, diodesize=0.1,
        armdst=260.0, num_bins=64, **_colon_pair(0.05, 0.1, 64.6 * 0.1), probetype=1,
        tas_max=200.0, apply_int_arr_thresh=True, default_int_arr_thresh=1e-5,
        reaccpt_shatrs=True, reaccpt_d=0.5, reaccpt_max_ia=1e-6,
        sets_intar_threshold=True, needs_pecan_params=True,
        source_line="sizeDist.m:147-176",
    ),

    # ---- GPM (sizeDist.m:177-254) ----------------------------------------
    # NOTE: none of the GPM 2DS/CIP/HVPS cases assign intar_threshold.
    ProbeConfig(
        project="GPM", probename="2DS", num_diodes=128, diodesize=0.010,
        armdst=63.0, num_bins=22, kk=_KK_GPM_2DS_UM / 1000.0, probetype=2,
        tas_max=170.0, apply_int_arr_thresh=True, default_int_arr_thresh=1e-6,
        reaccpt_shatrs=True, reaccpt_d=0.5, reaccpt_max_ia=1e-6,
        sets_intar_threshold=False,
        source_line="sizeDist.m:179-196",
    ),
    ProbeConfig(
        project="GPM", probename="CIP", num_diodes=64, diodesize=0.025,
        armdst=100.0, num_bins=19, kk=_KK19_UM / 1000.0, probetype=1,
        tas_max=200.0, apply_int_arr_thresh=True, default_int_arr_thresh=1e-6,
        reaccpt_shatrs=True, reaccpt_d=0.5, reaccpt_max_ia=2.5e-7,
        sets_intar_threshold=False,
        source_line="sizeDist.m:197-214",
    ),
    ProbeConfig(
        project="GPM", probename="2DC", num_diodes=32, diodesize=0.03,
        armdst=61.0, num_bins=19, kk=_KK19_UM / 1000.0, probetype=0,
        tas_max=125.0, apply_int_arr_thresh=True, default_int_arr_thresh=1e-5,
        reaccpt_shatrs=False, reaccpt_d=0.5, reaccpt_max_ia=1e-6,
        sets_intar_threshold=True,
        source_line="sizeDist.m:215-236",
    ),
    ProbeConfig(
        project="GPM", probename="HVPS", num_diodes=128, diodesize=0.150,
        armdst=161.0, num_bins=28, kk=_KK_HVPS_UM / 1000.0, probetype=2,
        tas_max=170.0, apply_int_arr_thresh=False, default_int_arr_thresh=1e-6,
        reaccpt_shatrs=False, reaccpt_d=0.5, reaccpt_max_ia=1e-6,
        sets_intar_threshold=False,
        source_line="sizeDist.m:237-253",
    ),

    # ---- SOCRATES (sizeDist.m:255-338) -----------------------------------
    ProbeConfig(
        project="SOCRATES", probename="2DS", num_diodes=128, diodesize=0.010,
        armdst=63.0, num_bins=21, kk=_KK_SOCRATES_2DS_UM / 1000.0, probetype=2,
        tas_max=170.0, apply_int_arr_thresh=True, default_int_arr_thresh=1e-6,
        reaccpt_shatrs=True, reaccpt_d=0.05, reaccpt_max_ia=1e-6,
        sets_intar_threshold=True,
        source_line="sizeDist.m:262-284",
    ),
    ProbeConfig(
        project="SOCRATES", probename="Fast2DC", num_diodes=64, diodesize=0.025,
        armdst=61.0, num_bins=17, kk=_KK_SOCRATES_FAST2DC_UM / 1000.0,
        probetype=3, tas_max=300.0, apply_int_arr_thresh=True,
        default_int_arr_thresh=4e-6, reaccpt_shatrs=True, reaccpt_d=0.15,
        reaccpt_max_ia=2.5e-6, sets_intar_threshold=True,
        source_line="sizeDist.m:285-308",
    ),
    ProbeConfig(
        project="SOCRATES", probename="PIP", num_diodes=64, diodesize=0.1,
        armdst=260.0, num_bins=27, kk=_KK_SOCRATES_PIP_UM / 1000.0, probetype=1,
        tas_max=200.0, apply_int_arr_thresh=False, default_int_arr_thresh=1e-5,
        reaccpt_shatrs=False, reaccpt_d=0.5, reaccpt_max_ia=1e-6,
        sets_intar_threshold=True,
        source_line="sizeDist.m:309-337",
    ),

    # ---- otherwise: any project name not listed above (sizeDist.m:339-511)
    ProbeConfig(
        project="otherwise", probename="HVPS", num_diodes=128, diodesize=0.150,
        armdst=161.0, num_bins=28, kk=_KK_HVPS_UM / 1000.0, probetype=2,
        tas_max=170.0, apply_int_arr_thresh=False, default_int_arr_thresh=4e-6,
        reaccpt_shatrs=False, reaccpt_d=0.5, reaccpt_max_ia=1e-6,
        sets_intar_threshold=True,
        source_line="sizeDist.m:341-364",
    ),
    ProbeConfig(
        project="otherwise", probename="2DS", num_diodes=128, diodesize=0.010,
        armdst=63.0, num_bins=128, **_colon_pair(0.005, 0.010, 128.6 * 0.010),
        probetype=2, tas_max=170.0, apply_int_arr_thresh=False,
        default_int_arr_thresh=4e-6, reaccpt_shatrs=False, reaccpt_d=0.5,
        reaccpt_max_ia=1e-6, sets_intar_threshold=True,
        source_line="sizeDist.m:365-390",
    ),
    ProbeConfig(
        project="otherwise", probename="CIP", num_diodes=64, diodesize=0.025,
        armdst=100.0, num_bins=19, kk=_KK19_UM / 1000.0, probetype=1,
        tas_max=200.0, apply_int_arr_thresh=False, default_int_arr_thresh=1e-5,
        reaccpt_shatrs=False, reaccpt_d=0.5, reaccpt_max_ia=1e-6,
        sets_intar_threshold=True,
        source_line="sizeDist.m:391-414",
    ),
    ProbeConfig(
        project="otherwise", probename="PIP", num_diodes=64, diodesize=0.1,
        armdst=260.0, num_bins=64, **_colon_pair(0.05, 0.1, 64.6 * 0.1), probetype=1,
        tas_max=200.0, apply_int_arr_thresh=False, default_int_arr_thresh=1e-5,
        reaccpt_shatrs=False, reaccpt_d=0.5, reaccpt_max_ia=1e-6,
        sets_intar_threshold=True,
        source_line="sizeDist.m:415-440",
    ),
    ProbeConfig(
        project="otherwise", probename="2DC", num_diodes=32, diodesize=0.03,
        armdst=61.0, num_bins=19, kk=_KK19_UM / 1000.0, probetype=0,
        tas_max=125.0, apply_int_arr_thresh=False, default_int_arr_thresh=4e-6,
        reaccpt_shatrs=False, reaccpt_d=0.5, reaccpt_max_ia=1e-6,
        sets_intar_threshold=True,
        source_line="sizeDist.m:441-464",
    ),
    # tasMax is NEVER assigned in this case -- preserved as an error.
    ProbeConfig(
        project="otherwise", probename="2DP", num_diodes=32, diodesize=0.200,
        armdst=260.0, num_bins=19, kk=_KK19_UM * 8.0 / 1000.0, probetype=0,
        tas_max=None, apply_int_arr_thresh=False, default_int_arr_thresh=4e-6,
        reaccpt_shatrs=False, reaccpt_d=0.5, reaccpt_max_ia=1e-6,
        sets_intar_threshold=True,
        source_line="sizeDist.m:465-489",
    ),
    ProbeConfig(
        project="otherwise", probename="F2DC", num_diodes=64, diodesize=0.025,
        armdst=61.0, num_bins=19, kk=_KK19_UM / 1000.0, probetype=3,
        tas_max=300.0, apply_int_arr_thresh=False, default_int_arr_thresh=4e-6,
        reaccpt_shatrs=False, reaccpt_d=0.5, reaccpt_max_ia=1e-6,
        sets_intar_threshold=True,
        source_line="sizeDist.m:490-510",
    ),
)


SIZEDIST_CONFIG: MappingProxyType[tuple[str, str], ProbeConfig] = MappingProxyType({
    (cfg.project, cfg.probename): cfg for cfg in _CONFIGS
})
"""The **stock v3.1.4** table.  Not what ORACLES ran -- see
:data:`SIZEDIST_CONFIG_PRODUCTION`."""

PROJECTS: tuple[str, ...] = ("PECAN", "GPM", "SOCRATES")
"""Projects with their own switch case.  Anything else falls to ``otherwise``."""


# --------------------------------------------------------------------------
# the ORACLES-variant sizeDist.m:92-395 -- the ORACLES PRODUCTION table
# --------------------------------------------------------------------------
#
# WHY THERE ARE TWO TABLES.  The block above was transcribed at S0 from stock
# v3.1.4.  S4 established that the
# ORACLES products were made by the ORACLES-variant `sizeDist.m`, a different lineage
# whose project/probe switch is NOT the same file's -- 12 cases against stock's
# 16, and four of the shared cases carry different numbers.  Two of those
# differences decide output on the ORACLES 2D-S chain:
#
#   applyIntArrThresh  0 -> 1     (:268)   gates the WHOLE shattering block
#   defaultIntArrThresh 4e-6 -> 6e-6 (:269) "Changed from 1e-6 to 6e-6 for ORACLES"
#
# Running the port against the stock row would skip shatter identification
# entirely and silently produce a different size distribution.  This is the same
# shape of error four times over now -- S3 ported the wrong `imgProc_sm`, the reject port
# checked the reject constants in the wrong tree, S4's design found the `.5`
# area-ratio threshold -- so the answer is a SECOND TABLE, never a patch to the
# first.  `tests/test_reference_data.py` already said so in 2026-08-19:
# "the divergence is real, and it belongs in a FidelityProfile, not in a patched
# shared table."
#
# The full diff of the two switches, measured rather than argued:
#
#   GPM/2DC        present in stock, ABSENT in production
#   SOCRATES/*     three cases in stock, the whole branch ABSENT in production
#   otherwise/HVPS 28 hand-written bins -> 70 uniform 0.15 mm (reproduces the
#                  archived ORACLES HVPS ladder, which is how the file was
#                  identified in the first place); applyIntArrThresh 0 -> 1;
#                  defaultIntArrThresh 4e-6 -> 1e-6
#   otherwise/2DS  applyIntArrThresh 0 -> 1; defaultIntArrThresh 4e-6 -> 6e-6
#   otherwise/CIP  19 hand-written bins -> 64 uniform 0.025 mm;
#                  applyIntArrThresh 0 -> 1; defaultIntArrThresh 1e-5 -> 1e-6
#   otherwise/F2DC probetype 3 -> 0, and **tasMax is never assigned** -- so F2DC
#                  joins 2DP as a case that kills MATLAB at :968.  Stock had
#                  repaired it (Joe Finlon, 01/09/17); this lineage predates that.
#
# Everything else is whitespace.

_CONFIGS_PRODUCTION: tuple[ProbeConfig, ...] = (
    # ---- PECAN (ORACLES-variant sizeDist.m:93-159) -- identical to stock ----
    ProbeConfig(
        project="PECAN", probename="CIP", num_diodes=64, diodesize=0.025,
        armdst=100.0, num_bins=19, kk=_KK19_UM / 1000.0, probetype=1,
        tas_max=200.0, apply_int_arr_thresh=True, default_int_arr_thresh=1e-5,
        reaccpt_shatrs=True, reaccpt_d=0.5, reaccpt_max_ia=2.5e-7,
        sets_intar_threshold=True, needs_pecan_params=True,
        source_line="sizeDist.m (campaign-configured copy):95-127",
    ),
    ProbeConfig(
        project="PECAN", probename="PIP", num_diodes=64, diodesize=0.1,
        armdst=260.0, num_bins=64, **_colon_pair(0.05, 0.1, 64.6 * 0.1), probetype=1,
        tas_max=200.0, apply_int_arr_thresh=True, default_int_arr_thresh=1e-5,
        reaccpt_shatrs=True, reaccpt_d=0.5, reaccpt_max_ia=1e-6,
        sets_intar_threshold=True, needs_pecan_params=True,
        source_line="sizeDist.m (campaign-configured copy):128-159",
    ),

    # ---- GPM (ORACLES-variant sizeDist.m:160-222) -- NO 2DC case here
    ProbeConfig(
        project="GPM", probename="2DS", num_diodes=128, diodesize=0.010,
        armdst=63.0, num_bins=22, kk=_KK_GPM_2DS_UM / 1000.0, probetype=2,
        tas_max=170.0, apply_int_arr_thresh=True, default_int_arr_thresh=1e-6,
        reaccpt_shatrs=True, reaccpt_d=0.5, reaccpt_max_ia=1e-6,
        sets_intar_threshold=False,
        source_line="sizeDist.m (campaign-configured copy):162-181",
    ),
    ProbeConfig(
        project="GPM", probename="CIP", num_diodes=64, diodesize=0.025,
        armdst=100.0, num_bins=19, kk=_KK19_UM / 1000.0, probetype=1,
        tas_max=200.0, apply_int_arr_thresh=True, default_int_arr_thresh=1e-6,
        reaccpt_shatrs=True, reaccpt_d=0.5, reaccpt_max_ia=2.5e-7,
        sets_intar_threshold=False,
        source_line="sizeDist.m (campaign-configured copy):182-199",
    ),
    ProbeConfig(
        project="GPM", probename="HVPS", num_diodes=128, diodesize=0.150,
        armdst=161.0, num_bins=28, kk=_KK_HVPS_UM / 1000.0, probetype=2,
        tas_max=170.0, apply_int_arr_thresh=False, default_int_arr_thresh=1e-6,
        reaccpt_shatrs=False, reaccpt_d=0.5, reaccpt_max_ia=1e-6,
        sets_intar_threshold=False,
        source_line="sizeDist.m (campaign-configured copy):200-222",
    ),

    # ---- otherwise (ORACLES-variant sizeDist.m:223-394) -------------------
    # This is the branch ORACLES lands in: 'ORACLES' is not one of the named
    # projects, so `switch projectname` falls to `otherwise` at :223.
    ProbeConfig(
        project="otherwise", probename="HVPS", num_diodes=128, diodesize=0.150,
        armdst=161.0, num_bins=70, **_colon_pair(0.075, 0.15, 70.5 * 0.15),
        probetype=2, tas_max=170.0, apply_int_arr_thresh=True,
        default_int_arr_thresh=1e-6, reaccpt_shatrs=False, reaccpt_d=0.5,
        reaccpt_max_ia=1e-6, sets_intar_threshold=True,
        source_line="sizeDist.m (campaign-configured copy):225-249",
    ),
    ProbeConfig(
        project="otherwise", probename="2DS", num_diodes=128, diodesize=0.010,
        armdst=63.0, num_bins=128, **_colon_pair(0.005, 0.010, 128.6 * 0.010),
        probetype=2, tas_max=170.0, apply_int_arr_thresh=True,
        default_int_arr_thresh=6e-6, reaccpt_shatrs=False, reaccpt_d=0.5,
        reaccpt_max_ia=1e-6, sets_intar_threshold=True,
        source_line="sizeDist.m (campaign-configured copy):250-274",
    ),
    ProbeConfig(
        project="otherwise", probename="CIP", num_diodes=64, diodesize=0.025,
        armdst=100.0, num_bins=64, **_colon_pair(0.0125, 0.025, 64.5 * 0.025),
        probetype=1, tas_max=200.0, apply_int_arr_thresh=True,
        default_int_arr_thresh=1e-6, reaccpt_shatrs=False, reaccpt_d=0.5,
        reaccpt_max_ia=1e-6, sets_intar_threshold=True,
        source_line="sizeDist.m (campaign-configured copy):276-298",
    ),
    ProbeConfig(
        project="otherwise", probename="PIP", num_diodes=64, diodesize=0.1,
        armdst=260.0, num_bins=64, **_colon_pair(0.05, 0.1, 64.6 * 0.1), probetype=1,
        tas_max=200.0, apply_int_arr_thresh=False, default_int_arr_thresh=1e-5,
        reaccpt_shatrs=False, reaccpt_d=0.5, reaccpt_max_ia=1e-6,
        sets_intar_threshold=True,
        source_line="sizeDist.m (campaign-configured copy):300-322",
    ),
    ProbeConfig(
        project="otherwise", probename="2DC", num_diodes=32, diodesize=0.03,
        armdst=61.0, num_bins=19, kk=_KK19_UM / 1000.0, probetype=0,
        tas_max=125.0, apply_int_arr_thresh=False, default_int_arr_thresh=4e-6,
        reaccpt_shatrs=False, reaccpt_d=0.5, reaccpt_max_ia=1e-6,
        sets_intar_threshold=True,
        source_line="sizeDist.m (campaign-configured copy):325-347",
    ),
    # tasMax is NEVER assigned in this case -- preserved as an error.
    ProbeConfig(
        project="otherwise", probename="2DP", num_diodes=32, diodesize=0.200,
        armdst=260.0, num_bins=19, kk=_KK19_UM * 8.0 / 1000.0, probetype=0,
        tas_max=None, apply_int_arr_thresh=False, default_int_arr_thresh=4e-6,
        reaccpt_shatrs=False, reaccpt_d=0.5, reaccpt_max_ia=1e-6,
        sets_intar_threshold=True,
        source_line="sizeDist.m (campaign-configured copy):349-370",
    ),
    # ...and neither is it here, which stock had already fixed.
    ProbeConfig(
        project="otherwise", probename="F2DC", num_diodes=64, diodesize=0.025,
        armdst=61.0, num_bins=19, kk=_KK19_UM / 1000.0, probetype=0,
        tas_max=None, apply_int_arr_thresh=False, default_int_arr_thresh=4e-6,
        reaccpt_shatrs=False, reaccpt_d=0.5, reaccpt_max_ia=1e-6,
        sets_intar_threshold=True,
        source_line="sizeDist.m (campaign-configured copy):372-393",
    ),
)

SIZEDIST_CONFIG_PRODUCTION: MappingProxyType[tuple[str, str], ProbeConfig] = (
    MappingProxyType({
        (cfg.project, cfg.probename): cfg for cfg in _CONFIGS_PRODUCTION
    })
)
"""The **ORACLES production** table, from the ORACLES-variant ``sizeDist.m``."""

PROJECTS_PRODUCTION: tuple[str, ...] = ("PECAN", "GPM")
"""Production has no ``SOCRATES`` case, so SOCRATES falls to ``otherwise`` there."""

SIZEDIST_TREES: MappingProxyType[str, tuple[MappingProxyType, tuple[str, ...]]] = (
    MappingProxyType({
        "stock": (SIZEDIST_CONFIG, PROJECTS),
        "production": (SIZEDIST_CONFIG_PRODUCTION, PROJECTS_PRODUCTION),
    })
)
"""The two switch tables, by tree name.  ``sizedist_config`` selects between them."""


DIODESIZE_DISAGREEMENTS: MappingProxyType[str, tuple[float, float]] = MappingProxyType({
    # probe: (imgProc_sm.m ds, sizeDist.m diodesize)
    "2DC": (0.025, 0.03),
})
"""Probes whose two switches disagree on diode size.  Both values are preserved.

``imgProc_sm.m:123`` sizes 2DC images with 0.025 mm; ``sizeDist.m:186,344,443``
bins them with 0.030 mm.  Whichever is right, a faithful port reproduces both, so
the modules must each read their own table rather than a merged one.
"""


# --------------------------------------------------------------------------
# Lookup helpers
# --------------------------------------------------------------------------

def imgproc_config(probename: str) -> ImgProcConfig:
    """Look up the ``imgProc_sm.m`` probe case.

    Unlike ``sizeDist.m``, ``imgProc_sm.m:117`` has **no** ``otherwise`` branch:
    an unrecognized probe leaves every variable unassigned and MATLAB fails at
    ``imgProc_sm.m:195``.  Preserved as an error.
    """
    try:
        return IMGPROC_CONFIG[probename]
    except KeyError:
        raise MatlabUndefinedVariable(
            f"imgProc_sm.m:117 has no case for probename={probename!r} and no "
            "otherwise branch; MATLAB fails at imgProc_sm.m:195 (diodenum unset). "
            f"Known probes: {sorted(IMGPROC_CONFIG)}"
        ) from None


def sizedist_config(projectname: str, probename: str,
                    tree: str = "stock") -> ProbeConfig:
    """Look up the ``sizeDist.m`` (project, probe) case in one of the two trees.

    An unknown *project* falls through to the ``otherwise`` branch, exactly as
    ``sizeDist.m:339`` (stock) / ``:223`` (production) does.  An unknown *probe*
    within a branch matches no inner case, leaving everything unassigned --
    preserved as an error.

    ``tree`` selects the switch table: ``"stock"`` (v3.1.4) or ``"production"``
    (the campaign-configured ``sizeDist.m``, the file that made the archived products).
    The default is ``"stock"`` because every caller written before the size-distribution
    stage was ported meant
    stock and their tests assert stock numbers -- but a *pipeline* must name the
    tree, so the earlier translation's ``sizedist.run`` takes ``tree`` with no default at
    all.  Getting this wrong is not a rounding difference: production switches
    shattering identification **on** for the 2D-S and stock does not.
    """
    try:
        table, projects = SIZEDIST_TREES[tree]
    except KeyError:
        raise ValueError(
            f"unknown sizeDist tree {tree!r}; known: {sorted(SIZEDIST_TREES)}"
        ) from None
    key_project = projectname if projectname in projects else "otherwise"
    try:
        return table[(key_project, probename)]
    except KeyError:
        available = sorted(p for (proj, p) in table if proj == key_project)
        raise MatlabUndefinedVariable(
            f"sizeDist.m ({tree}) has no case for probename={probename!r} under "
            f"project branch {key_project!r} (from projectname={projectname!r}); "
            "MATLAB leaves num_diodes/diodesize/kk unassigned and fails at "
            f"sizeDist.m:522. Available probes in that branch: {available}"
        ) from None


def bin_edges(projectname: str, probename: str) -> np.ndarray:
    """``kk`` in millimetres for a run -- ``num_bins + 1`` edges."""
    return sizedist_config(projectname, probename).kk


def bin_width(projectname: str, probename: str) -> np.ndarray:
    """``binwidth = diff(kk)`` -- ``sizeDist.m:523``."""
    return sizedist_config(projectname, probename).binwidth


def resolution_um(projectname: str, probename: str) -> float:
    """``res = diodesize*1000`` -- ``sizeDist.m:522``."""
    return sizedist_config(projectname, probename).res
