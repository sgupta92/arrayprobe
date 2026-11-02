# SPDX-License-Identifier: BSD-3-Clause
"""v3.5's ``sizeDist.m`` DRIVER: the record/second loop, the
netCDF writer, and the ``iat_threshold`` output variable.

``sizedist_tables.py`` ports the pure, case-griddable pieces: the
per-campaign/per-probe bin tables, ``iaThreshType == 3``'s pure per-second
functions, and ``iNewHabit`` detection. This module is the rest: every
*discrete* new-or-changed driver behaviour the v3.1.4->v3.5 diff contains --
the shattering dispatch across all three ``iaThreshType`` conventions, the
multi-day/corrupt particle-time fix, one-second block resolution, the
overload dead-time cap, the ``d_choice`` diameter definitions and
``particle_diameter_AreaR``, the ``area_ratio`` clip, and the writer's
variable-definition/attribute/transpose deltas -- each independently
oracle-validated on its own -- assembled into :func:`run`, a real
record-by-record netCDF-in/netCDF-out driver for **all four probetypes** --
probetype 2 as first written, probetype 1 (CIP/PIP) added 2026-09-17, probetypes 0
(2DC/2DP) and 3 (Fast2DC) added 2026-09-23 with the CIP pipeline, each against an Octave run of
the unmodified v3.5 ``sizeDist.m`` (``octave_oracle/run_v35_probetype03_sizedist_bank.py``,
``tests/test_v35_sizedist_probetype03.py``); see "Scope" below.
*(This line said "probetype 2 only" until 2026-09-18, twenty-four hours after
the extension forty lines below it landed.  The same drift -- a docstring
contradicting its own module -- put a false capability claim on two shared
artifact pages the same week, so it is corrected here rather than noted.)*

**What is, and is not, validated end to end.** Every discrete piece above
carries its own Octave-oracle or documented-semantics validation, the
same
"validate the signal you claim" standard every other stage in this port
holds itself to. The *assembly* in :func:`run`/:func:`_run` reuses
the v3.1.4 validation engine's ``sizedist``'s own unchanged numeric core directly --
:func:`arrayprobe_uiops.sizedist_core._process_population` for the per-second binning
(confirmed unchanged: the v3.5 diff across that whole region is pure
reindentation, no logic change) and :func:`arrayprobe_uiops.sizedist_core._reaccept_shattered`
for the two D3-preserving loops -- rather than re-deriving it, but the
*assembly itself* has not been run end-to-end against a real MATLAB v3.5
execution on a full synthetic per-particle netCDF fixture (no archived
product exists to validate against either, since v3.5 postdates every
campaign this project holds -- oracle layer 1 does not apply to any v3.5
stage). That full differential is V9's job, once V8's own imgProc output
exists to feed it. :class:`TestRunOnASyntheticFile` exercises :func:`run`
top-to-bottom on a small netCDF fixture built directly with
:mod:`arrayprobe_uiops.ncio` (not MATLAB/Octave) to prove the assembly does not
crash and produces the expected shape and gross values -- a real but weaker
claim than the piece-level Octave validation, and stated as such rather than
conflated with it.

**Scope, decided up front rather than discovered by a half-finished
transcription.**  v3.5's driver changes touch every probetype's shared
scaffolding (the particle-time rollover, the block-resolution logic feeding
the main loop) but only ONE probetype-specific line (the 0.8/1.0 s
overload-dead-time cap, explicitly gated ``probetype==2``).  This driver ports
**probetype 2 only** (2D-S / HVPS / the IMPACTS 3VCPI probes) -- the probe
family the measurement-block and driver stages already scoped to, so
an end-to-end differential has a complete probetype-2 chain to run.

**Extended to probetype 1 (CIP/PIP) on 2026-09-17.**  v3.5 is the default
engine, so refusing probetype 1 here refused a CIP or PIP flight by way of the
engine this project tells a stranger to use, while stage 3 (V-PT) already
covered all four probetypes.  Five sites separate probetype 1 from probetype 2
and each is now ported and cited in place: the ``particle_time`` source for
``image_time_hhmmssall`` (``:758-759``), the ``'D'`` DOF-overload mark
(``:975-977``), the ABSENCE of any counter-rollover correction (``:1025-1029``
has arms for probetypes 2 and 0 only), the ABSENCE of the 0.8/1.0 s dead-time
cap (``:1118`` gates it ``probetype==2``), and the count-ratio live-time
fraction ``TotalPC1./TotalPC2`` clamped at 1 (``:1931-1958``) in place of
``1 - dead_time``.  The tail block is Octave-goldened; the other four are
branch structure read from the source.  A whole-file probetype-1 differential
has not been run.

**Extended to probetypes 0 (2DC/2DP) and 3 (Fast2DC) on 2026-09-23** (with the CIP pipeline).
Their record-loop branches, each cited in place: ``parent_rec_num`` and the
record-start dead time (``:945-947``, ``:1111-1113``), the SEA-convention overload
zeroing (``:964-966``), the skipped ``Particle_number_all`` read (``:969-973``), and
probetype 0's absolute-time ``int_arr`` with its ``2^24`` rollback (``:984-985``,
``:1027-1028``; Fast2DC takes the differenced arm and no rollback). The two latent
undefined-variable defects come across preserved: a probetype-0 run dies on
``int_arr2`` at ``:1311`` under ``iaThreshType == 2`` (measured under Octave) and on
``int_arr3`` with reacceptance on, and the port raises at both. Validated against the
unmodified v3.5 ``sizeDist.m`` under Octave on synthetic 2DC and Fast2DC inputs built so
each branch changes a written number (``run_v35_probetype03_sizedist_bank.py``; each
branch's mutation fails ``tests/test_v35_sizedist_probetype03.py``) -- layer 2, and
synthetic: the held real files (a 1995 ACE-1 2DC/2DP RAF file, reader checked only; a
CAESAR 2024 Fast-2DC file) have not been run through this stage in a validated way.

PECAN (``getPECANparams`` missing from both vendored trees) and
``save_workspace_mat`` (a ~380 MB whole-workspace ``.mat`` dump) are refused
for the same reason the v3.1.4 port refuses them -- see
the module docstring of the v3.1.4 validation engine's ``sizedist`` (not included in this package).

**No FidelityProfile / no "tree" parameter, deliberately.**  v3.5 has exactly
one source tree -- there is no v3.5 analogue of the ORACLES-variant tree's
ORACLES-only fork (established when the SPEC reader was ported, restated here
because it decides this module's whole signature).  So this driver's positional signature matches
v3.5's ``sizeDist.m`` *exactly*, including ``iaThreshType``,
``iCreateAspectRatio``, ``iCreateBad`` and ``iSaveIntArrSV`` as required
positional arguments (stock's own shape, unchanged by the v3.5 diff) rather
than the keyword-defaulted style ``sizedist.run`` in the v3.1.4 validation engine (not included in
this package) uses to
paper over the "stock vs. production" ambiguity that v3.5 does not have.

**Reuse, not re-transcription, wherever the diff proves nothing changed.**
Everything below cites the exact v3.1.4/v3.5 line(s) that license it.  Three
findings are
upstream *fixes*,
not defects:
v3.5 no longer loses the int16xdouble saturation on d_choice sizing
(im_width/im_length are cast to double before use), no longer scales an
already-scaled ``particle_diameter_AreaR``, and writes
``mean_area_ratio``/the two aspect-ratio means/their three ``REJ_`` twins
**with** the transpose the v3.1.4 port's own docstring names as a defect.
A port that "preserved" any of the three here would be preserving a bug the
source no longer has, which is the wrong direction of infidelity.  Two further
findings -- the ``re``/``REJ_re`` units label, ``'um'`` -> ``'mm'``, on an
unchanged microns-valued formula (preserved AS v3.5 has it, not corrected),
and :func:`fix_multiday_particle_times`'s "no crossover detected" path, which
leaves corrupt-looking particle times uncorrected with only a printed
diagnostic -- are read/measured gaps, not fixes.  A third, the past-end-of-data
branch (``:1848-1875``), touches only good-side variables, so
``bad_one_sec_ar`` keeps its own zero pre-allocation there rather than the NaN
a naive good/bad-symmetric loop would write -- caught only by the end-to-end
Octave comparison (``REJ_ar`` was the one variable that disagreed); the same
line is in v3.1.4, so the register records it as a both-releases finding.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, replace
from typing import cast

import numpy as np

from arrayprobe_uiops.matlab_compat import MatlabIndexError, datestr, mfind, mint32, msum, nansum
from arrayprobe_uiops.sample_area import calc_sa_randombins
from arrayprobe_uiops.sizedist_core import (
    _REJ_ATTS,
    _REJ_ORDER,
    _VARS,
    _VARS_ASPECT,
    _VARS_INTARR,
    _VARS_TAIL,
    D_CHOICE,
    GOOD_REJECT_CODES,
    REJECT_CRITERION_CODES,
    STOCK_REJECT,
    _d_hypot,
    _d_length,
    _d_max,
    _d_mean,
    _d_minr,
    _d_width,
    _hhmmss_to_insec,
    _insec_to_hhmmss,
    _num2str,
    _optional_parameters,
    _process_population,
    _reaccept_shattered,
    _rollover_240000,
    warn_suspect_rollover,
)

from . import lwc as _lwc
from . import ncio, provenance
from .particle_physics import single_area, single_mass, single_vt
from .pecan_params import pecan_intar_threshold, resolve_pecan_params

# Re-exported deliberately (the retracted 2D-S bin table): `scripts/run_flight.py` reaches
# `arrayprobe_uiops` only through the `uiops` selector, and the selector is keyed
# by the v3.1.4 port's own module names -- `probe_cases` has no v3.1.4
# counterpart, so it is not in `uiops.CATALOGUE` and cannot be. Naming both
# symbols here makes the registry reachable as
# `_v35().module("sizedist").resolve_probe_case`, through a catalogued module,
# rather than by a direct `import arrayprobe_uiops.probe_cases` that would bypass
# the selector.
from .probe_cases import (
    ACCEPTED_IA_THRESH_TYPES,
    REQUIRED_IA_THRESH_TYPE,
    UnknownProbeCase,
    register_v35_2ds_ladder_fix,
    resolve_probe_case,
    resolve_shipped_probe_case,
)
from .sizedist_tables import (
    InterarrivalThresholdSpec,
    ProbeDefaults,
    detect_habit_scheme,
    flag_shattered_1hz,
    probe_defaults,
    reaccept_shattered_1hz,
    select_interarrival_threshold,
)

__all__ = [
    "TasMaxUndefined",
    "run",
    "UnsupportedProbetype",
    "resolve_probe_case",
    "resolve_shipped_probe_case",
    "register_v35_2ds_ladder_fix",
    "UnknownProbeCase",
    "REQUIRED_IA_THRESH_TYPE",
    "ACCEPTED_IA_THRESH_TYPES",
    "AREA_RATIO_Z",
    "AREA_RATIO_UPPER_CLIP",
    "OVERLOAD_WARN_SEC",
    "OVERLOAD_CAP_SEC",
    "fix_multiday_particle_times",
    "apply_flight_day_carryover",
    "resolve_particle_blocks",
    "overload_dead_time",
    "d_choice_diameter",
    "area_r_diameter",
    "clip_area_ratio",
    "apply_shattering",
    "WRITER_GAPS",
]

# Since 2026-09-15 the three ``fprintf``/``display`` reproductions
# below (``fix_multiday_particle_times``, ``overload_dead_time``,
# :func:`run`) now go through this module logger instead of a bare
# ``print``, so a library caller can capture or redirect them; the package
# ``__init__`` installs only a ``NullHandler``, so importing this module
# alone stays silent, same as before. ``arrayprobe.cli`` attaches a real
# handler for the console script, at the same default (INFO/WARNING)
# visibility a bare ``print`` always had.
_logger = logging.getLogger(__name__)


class TasMaxUndefined(NameError):
    """``tasMax`` read where the case never assigns it (2DP), as MATLAB dies there."""


_TASMAX_UNDEFINED = (
    "tasMax is not assigned for this project/probe case (2DP: v3.5 sizeDist.m:595-617 omits "
    "it), and :771, :1026-1088 (the 2^32 x res/1e6/tasMax clock rollover), :1144 (area "
    "reconstruction above tasMax) and :1926 read it, so MATLAB dies with \"'tasMax' "
    "undefined\". No default exists: tasMax is the fastest airspeed the probe's clock samples "
    "without skewed images, a property of the individual instrument's electronics that no "
    "UIOPS release states for the 2DP. Pass tas_max=<m/s> "
    "with the value for your probe."
)

_PECAN_UNDEFINED = (
    "{case} calls getPECANparams(ddate, probename) (v3.5 sizeDist.m:164/:195), which ships in "
    "no UIOPS release, so MATLAB dies there. Pass pecan_params=<file>: a CSV of spiral start_s, "
    "end_s and intar_threshold_s (arrayprobe_uiops.pecan_params)."
)


class UnsupportedProbetype(NotImplementedError):
    """Raised for a (campaign, probe) resolving to a probetype outside 0-3.

    No v3.5 probetype is refused here: probetypes 0-3 are all ported (probetype 1
    is CIP/PIP). The class remains for a
    table row that names a probetype no stock release defines.

    This docstring must track the module docstring's "Scope" section: it is the
    half a reader meets first -- it is what an exception class is *for*. A version
    that lagged the probetype-1 port by a day was copied onto two shared artifact
    pages, which told readers that v3.5 stage 4 refuses probetypes
    0, 1 and 3 -- denying the engine capability the entire CIP result rests on.
    It was caught by the artifact refresh, not by any test: no check compares a
    docstring against the code it describes.
    """


#: ``sizeDist.m:1162`` (v3.5) and ``:985`` (v3.1.4 stock) -- both stock trees
#: use ``.2``; the ORACLES-only ``.5`` override lives solely in
#: the ORACLES-variant tree, a v3.1.4-era fork with no v3.5 sibling (the SPEC
#: reader's "No FidelityProfile, deliberately" finding). Reused directly rather than
#: re-declared.
AREA_RATIO_Z = STOCK_REJECT.area_ratio_z


# ---------------------------------------------------------------------------
# Opt-in probe-clock offset (not MATLAB): particle times moved onto aircraft time
# ---------------------------------------------------------------------------

#: Where the per-second ``timehhmmss``/``tas`` rows came from, which decides whether a time
#: offset moves them too: ``"probe"`` (the probe's own record, stamped by the same off clock as
#: the particles: shifted) or ``"aircraft"`` (an aircraft file, already on aircraft time: not).
TAS_CLOCKS = ("probe", "aircraft")


@dataclass(frozen=True)
class TimeOffset:
    """A whole-second correction ADDED to the probe clock's particle times, with its evidence.

    Not part of v3.5's ``sizeDist``: an opt-in for a probe whose own clock is measured off
    aircraft time (raw SPEC clock ~100-115 s and ~78 s off on two ARM ACE-ENA flights), so the
    product inherits the error. ``seconds`` is whole: ``sizeDist`` files a particle by the whole
    HHMMSS second of its ``Time`` (``hhmmss2insec`` of it, :func:`_diameters_and_mass`) and never
    by ``particle_millisec``, so a fractional shift would have to re-split seconds the file does
    not resolve -- refused rather than rounded. ``tas_clock`` is one of :data:`TAS_CLOCKS`.
    """

    seconds: int
    evidence: str
    tas_clock: str

    @classmethod
    def build(cls, seconds, evidence, tas_clock) -> TimeOffset:
        if isinstance(seconds, bool) or not isinstance(
                seconds, (int, float, np.integer, np.floating)) or not math.isfinite(
                float(seconds)) or float(seconds) != int(float(seconds)):
            raise ValueError("time_offset_s is a whole number of seconds (sizeDist files particles "
                             f"by whole HHMMSS seconds); got {seconds!r}")
        if int(float(seconds)) == 0:
            raise ValueError("time_offset_s = 0 changes nothing; leave it unset")
        if abs(int(float(seconds))) >= 86400:
            raise ValueError(f"time_offset_s is under one day in magnitude; got {seconds!r}")
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError("time_offset_s needs time_offset_evidence: a non-empty statement of "
                             "how the offset was measured")
        if tas_clock not in TAS_CLOCKS:
            raise ValueError(f"time_offset_tas_clock is one of {TAS_CLOCKS} (whether the "
                             f"timehhmmss/tas rows share the particles' clock); got {tas_clock!r}")
        return cls(int(float(seconds)), evidence.strip(), tas_clock)


def shift_hhmmss(hhmmss, seconds: int) -> np.ndarray:
    """``hhmmss`` (HHMMSS, whole seconds of the day) moved by ``seconds``, wrapped onto one day.

    The result reads as the clock would have read had it been right: a value moved past midnight
    wraps to ``000000`` onward and one moved before it to ``2359xx``, so the midnight logic
    downstream (:func:`fix_multiday_particle_times`, :func:`apply_flight_day_carryover`,
    ``_rollover_240000``) sees the same form of data it sees from a real clock. Any fraction of a
    second in the input is dropped, as ``hhmmss2insec`` drops it.
    """
    insec = _hhmmss_to_insec(hhmmss) + int(seconds)
    return _insec_to_hhmmss(np.mod(insec, 86400.0))

#: ``sizeDist.m:1161`` (v3.5 only) -- ``area_ratio(area_ratio > 1.) = 1.;``,
#: added 2023-03-19 with no v3.1.4 analogue. Applied BEFORE the ``.2``
#: rejection test, so it can only ever raise a value into acceptance range,
#: never push one out of it.
AREA_RATIO_UPPER_CLIP = 1.0

#: ``sizeDist.m:1123-1128`` (v3.5), replacing v3.1.4's silent reset-to-zero
#: at the same site. Gated ``probetype == 2`` in the source; this module
#: enforces probetype 2 everywhere, so the gate is unconditional here.
OVERLOAD_WARN_SEC = 0.8
OVERLOAD_CAP_SEC = 1.0


# ---------------------------------------------------------------------------
# 1. The new multi-day particle-time fix (sizeDist.m ~:127-149, v3.5)
# ---------------------------------------------------------------------------



def _libm_pow(base: np.ndarray, exponent: float) -> np.ndarray:
    """``base .^ exponent`` element by element through ``math.pow`` (the platform libm), so the
    result does not depend on numpy's SIMD dispatch; NaN and inf propagate as in libm."""
    def one(v: float) -> float:
        try:
            return math.pow(v, exponent)
        except ValueError:  # negative base, fractional exponent: numpy's nan
            return math.nan
        except OverflowError:  # numpy, libm and MATLAB give inf (review F4)
            return math.inf

    flat = np.asarray(base, dtype=np.float64).ravel()
    out = np.fromiter((one(float(v)) for v in flat), dtype=np.float64, count=flat.size)
    return out.reshape(np.shape(base))

def fix_multiday_particle_times(image_time_hhmmssall: np.ndarray) -> tuple[np.ndarray, bool]:
    """v3.5's replacement for the ``image_time_hhmmssall`` midnight rollover.

    v3.1.4 (``:652-654``, reused here for ``timehhmmss`` itself via
    :func:`arrayprobe_uiops.sizedist_core._rollover_240000` -- **unchanged in v3.5**, see
    the module docstring) corrects a midnight crossing with
    ``x(find(diff(x)<0)+1:end) += 240000``, which MATLAB's first-element colon
    rule collapses to only the FIRST decrease.  v3.5's own authors worked
    around exactly that trap for the *particle*-time array by branching on
    ``numel(find(...))`` explicitly, rather than by fixing the colon idiom:

    * **Zero decreases**: no-op, unchanged.
    * **Exactly one decrease**: apply the same ``+240000`` shift v3.1.4 always
      applied -- identical result to the old code for this case.
    * **More than one decrease**: scan the decreases in order for a genuine
      day crossover -- ``x[d] > 230000 and x[d] - x[d+1] > 230000`` -- and
      shift everything after the FIRST one found, then stop.  If none of the
      decreases looks like a real crossover (all of them look like corrupt,
      briefly-reversed particle times instead), the array is returned
      **unmodified** and a message is printed; see the v3.5 ``sizeDist`` driver design
      record for why this is a real, if narrow, gap.

    Returns ``(fixed_array, crossover_applied)``.  Mutates a **copy**, unlike
    :func:`arrayprobe_uiops.sizedist_core._rollover_240000`, which mutates in place --
    the v3.5 source assigns back to the same name either way, so an in-place
    mutation would be equally faithful; a copy is used here so a caller
    cannot be surprised by an aliased array from an earlier stage.
    """
    x = np.array(image_time_hhmmssall, dtype=np.float64, copy=True)
    decreases = np.flatnonzero(np.diff(x) < 0)  # 0-based, matches MATLAB's find()-1
    if decreases.size == 0:
        return x, False
    if decreases.size == 1:
        warn_suspect_rollover(x, "3.5")  # user caution, diagnostic only
        x[decreases[0] + 1 :] += 240000.0
        return x, True
    for d in decreases:
        if x[d] > 230000 and x[d] - x[d + 1] > 230000:
            # User caution, diagnostic only: the test is applied to single values, so an all-ones
            # header (316363 = 31:63:63, not a valid HHMMSS) passes it and moves every later
            # particle; say so rather than let it pass silently.
            if (x[d] // 100) % 100 >= 60 or x[d] % 100 >= 60:
                _logger.warning(
                    "sizeDist crossover (engine 3.5): particle %d reads %06d, not a valid "
                    "HHMMSS, yet passes sizeDist.m:796-797's crossover test, so all %d later "
                    "particles are shifted +240000 and filed a day late -- reproduced "
                    "faithfully. To keep them, run the enhancement particle_time_glitch_fix "
                    "([enhancements] particle_time_glitch_fix = true) or a SODA-2 run.",
                    int(d) + 1, int(x[d]), int(x.size - d - 1))
            x[d + 1 :] += 240000.0
            return x, True
    _logger.warning(
        "Multiple instances of decreasing particle time were found,\n"
        "  but a crossover between dates was not detected."
    )
    return x, False


def apply_flight_day_carryover(
    image_time_hhmmssall: np.ndarray, timehhmmss: np.ndarray
) -> np.ndarray:
    """v3.5 ``sizeDist.m:806-810``: *"Fix particle times if they do not span
    multiple days but the flight file does - Added by Joe Finlon - 02/09/18"*.

    When any flight time exceeds 240000 but no particle time does, every
    particle time is shifted by +240000 (v3.1.4 ``sizeDist.m:662-663``).

    A THIRD, independent particle-time correction, not caught when this
    module's :func:`fix_multiday_particle_times` was first written from this
    file's own diff/read summary -- found only by reading the source lines
    immediately after it (``:786-805``) through to ``:829`` (the block-start
    predicate) and noticing the ``if`` at ``:807`` does not belong to either
    branch above it. It runs unconditionally after
    :func:`fix_multiday_particle_times`, regardless of what that function did:
    if the per-second ``timehhmmss`` (already midnight-corrected by
    :func:`arrayprobe_uiops.sizedist_core._rollover_240000`, called before this) crossed
    into the next day but the particle-time array's own ``diff`` never showed
    a decrease at all -- possible when the particle stream itself starts
    exactly at, or resumes after, the crossing with no reversal to detect --
    then every particle time is shifted by ``+240000`` unconditionally, with
    no idiom bug of its own (``numel(find(...))`` counts are scalars here,
    not vectors sliced with the first-element colon rule the other two
    corrections in this module inherit or avoid).

    **Correction, made while writing this module's tests**: this block is
    **byte-identical in v3.1.4** (``UIOPS-v3.1.4/.../sizeDist.m:661-664``,
    same three lines, same comment) -- it is not new to v3.5 at all, unlike
    :func:`fix_multiday_particle_times`'s own genuine v3.5 improvement (the
    ``numel(find(...))`` branching). What IS new here is narrower than first
    written: **the earlier translation never implemented it** -- it
    reused ``_rollover_240000`` for ``image_time_hhmmssall`` (its own
    ``:927``) but had no code for this second, independent ``if``. That is
    a gap in the earlier translation, not a v3.5 finding, and this function
    is kept as v3.5's own copy of the same three lines rather than left
    unported a second time.
    """
    x = np.asarray(image_time_hhmmssall, dtype=np.float64)
    tt = np.asarray(timehhmmss, dtype=np.float64)
    if np.any(tt > 240000) and not np.any(x > 240000):
        return x + 240000.0
    return x.copy()


# ---------------------------------------------------------------------------
# 2. The new block-resolution logic (sizeDist.m ~:160-208, v3.5)
# ---------------------------------------------------------------------------


def resolve_particle_blocks(
    image_time_hhmmssall: np.ndarray, num_of_part: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """v3.5's replacement for the ``start_all``/``count_all`` resolution.

    v3.1.4 finds one-second block starts in file order, sorts them by time,
    de-duplicates by first-occurrence, and only THEN computes ``count_all``
    as ``diff(start_all)`` on the final, sorted array -- valid only if the
    sort left ``start_all`` monotonic, which a corrupted/out-of-order
    particle-time series need not.  A negative count from a non-monotonic
    ``diff`` is clamped to 1, silently under-counting the block.

    v3.5 (02/13/19) computes ``count_all`` ONCE, in original file order
    (where ``start_all`` is inherently increasing, since it comes from
    ``find`` on a monotonically-scanned buffer), and carries that same
    ``count_all`` through every later sort/filter/dedupe step by index --
    never recomputing it from a ``diff`` that could go negative.  It also:

    * widens the block-start predicate from ``diff(...)>0`` to
      ``diff(...)~=0``, so a DECREASE (as well as an increase) in particle
      time starts a new block -- corrupt/out-of-order particle times are,
      unlike v3.1.4, not silently absorbed into the previous block;
    * inserts a corrupt-time-removal pass, active only when the
      chronologically-first block is not also the file-order-first block
      (``newindexofsort(1) ~= 1``): it keeps a sorted-order position only
      when the NEXT position in sorted order is exactly one more in file
      order (``newindexofsort(k+1) - newindexofsort(k) == 1``), i.e. only
      where sorting by time reproduces a genuinely contiguous run of file
      order -- dropping isolated, out-of-place blocks a real day crossing or
      clock glitch can produce.

    Returns ``(starttime, start_all, count_all)`` -- ``start_all`` 0-based,
    ready to index the proc file exactly as :func:`resolve_particle_blocks`'s
    caller does.
    """
    insec = _hhmmss_to_insec(image_time_hhmmssall)
    startindex = np.concatenate([[True], np.diff(insec) != 0])  # v3.5: != 0, not > 0
    starttime = image_time_hhmmssall[startindex]
    start_all = mfind(startindex) - 1  # 0-based, file order (inherently increasing)
    count_all = np.concatenate([np.diff(start_all), [num_of_part - start_all[-1]]])

    order = np.argsort(starttime, kind="stable")
    starttime = starttime[order]
    start_all = start_all[order]
    count_all = count_all[order]

    if order[0] != 0:
        keep = []
        k = 0
        n = len(order)
        while k < n - 1:
            if k == 0 and order[k] == 0:
                keep.append(k)
            elif k > 0 and order[k + 1] - order[k] == 1:
                keep.append(k)
            k += 1
        keep_idx = np.asarray(keep, dtype=np.int64)
        starttime = starttime[keep_idx]
        start_all = start_all[keep_idx]
        count_all = count_all[keep_idx]

    if starttime.size:
        keep_first = np.concatenate([[True], np.diff(starttime) != 0])
        starttime = starttime[keep_first]
        start_all = start_all[keep_first]
        count_all = count_all[keep_first]
    count_all = count_all.copy()
    count_all[count_all < 0] = 1
    return starttime, start_all, count_all


# ---------------------------------------------------------------------------
# 3. The overload dead-time cap (sizeDist.m ~:1120-1128, v3.5; probetype==2)
# ---------------------------------------------------------------------------


def overload_dead_time(
    int_arr: np.ndarray, dof_overload: np.ndarray, probetype: int = 2
) -> float:
    """v3.1.4 ``:813`` / v3.5 ``:1116-1126``, the ``else`` arm's ``time_interval72``.

    v3.1.4 computed the same sum and silently reset it to 0 whenever it
    exceeded 1 second ("EXPERIMENTAL correction... Joe Finlon 02/09/18").
    v3.5 instead warns above 0.8 s and only caps (to 1.0, not 0.0) above
    1.0 s -- real overload time under 1 s reaches the file where v3.1.4
    discarded it whenever the sum passed 1 s at all.

    **The warn-and-cap is gated ``probetype==2`` at v3.5 ``:1118``**, inside an
    ``else`` arm that probetypes 1 AND 2 both reach (``:1111``'s ``if`` takes
    probetypes 0 and 3 down the ``rec_start`` path instead).  So a probetype-1
    (CIP/PIP) run takes the bare ``sum(int_arr(DMT_DOF_SPEC_OVERLOAD~=0))`` of
    ``:1116`` with **no warning and no cap** -- a probetype-1 second whose
    overload sum exceeds 1 s writes that value through, where the same sum on a
    2D-S is clamped to 1.  Ported as a gate, not "fixed" to apply everywhere.
    ``probetype`` defaults to 2 so existing probetype-2 call sites are
    unchanged.
    """
    total = float(msum(int_arr[dof_overload != 0]))
    if probetype == 2 and total > OVERLOAD_WARN_SEC:
        _logger.warning(
            "Sum of overloaded particles (%.2f sec) exceeds "
            "%s sec. Use caution when interpreting results.",
            total, OVERLOAD_WARN_SEC,
        )
        if total > OVERLOAD_CAP_SEC:
            total = OVERLOAD_CAP_SEC
    return total


# ---------------------------------------------------------------------------
# 3b. d_choice diameters (the int16 diameter saturation no longer reproduces), and
#     particle_diameter_AreaR (the double-scaled area-ratio concentration no longer reproduces)
# ---------------------------------------------------------------------------


def d_choice_diameter(d_choice, im_length, im_width, diodesize, minr):
    """v3.5 ``sizeDist.m:1054-1066`` (stock v3.1.4 ``:876-890``).

    **What v3.5 changed.** v3.5 adds ``im_width = double(netcdf.getVar(...))`` /
    ``im_length = double(...)`` (``:941-942``) immediately before this
    computation; stock keeps them the file's native ``int16`` and multiplies
    in place -- a bug the earlier translation preserves (upstream finding: the int16 diameter
    saturation): ``int16 x double``
    saturation collapses ``particle_diameter_minR`` toward zero for
    ``d_choice`` 1, 2, 3 and 5). Casting to double first removes the integer
    dominance that causes it, so **the saturation does not reproduce under v3.5**.

    Implemented as exactly that precondition and nothing else:
    :func:`arrayprobe.matlab_compat.mmul`/``mpow``/``mmax`` already dispatch
    on the *actual* dtype of their arguments -- integer-dominant only when an
    operand really is an integer array -- so calling
    the earlier translation's own ``_d_length`` &c. on ``float64`` inputs
    reuses that arithmetic correctly with no new saturating-arithmetic code
    of its own. ``d_choice == 6`` (the default) is unaffected either way: it
    reads ``image_diam_minR`` straight from the file, untouched by the cast.
    """
    length64 = np.asarray(im_length, dtype=np.float64)
    width64 = np.asarray(im_width, dtype=np.float64)
    fn = {
        1: _d_length, 2: _d_width, 3: _d_mean,
        4: _d_hypot, 5: _d_max, 6: _d_minr,
    }.get(d_choice)
    if fn is None:
        raise ValueError(f"sizeDist v3.5: d_choice must be 1-6, got {d_choice!r}")
    return fn(length64, width64, diodesize, np.asarray(minr, dtype=np.float64))


def area_r_diameter(image_diam_areaR: np.ndarray) -> np.ndarray:
    """v3.5 ``sizeDist.m:954-956`` vs. stock v3.1.4 ``:783``.

    **What v3.5 changed.** Stock v3.1.4 reads ``particle_diameter_AreaR`` from the
    file and multiplies it by ``diodesize`` a SECOND time -- a bug the earlier
    translation preserves (upstream finding: the double-scaled area-ratio
    concentration; ``:669`` in the line numbering of the production-configuration variant of
    ``sizeDist.m``, not shipped): ``imgProc_sm.m`` already writes it scaled, so the second
    scaling is a 100x-too-small double-scale for a 2D-S, and the consequence
    is total (``conc_AreaR`` identically zero wherever finite).
    v3.5 comments the multiply out (``%particle_diameter_AreaR
    = particle_diameter_AreaR * diodesize; % Removed/ not needed (see
    imgProc_sm variable reference) ~ Joe Finlon 3/4/19``) -- an independent
    upstream fix of the exact defect this project documents, the same shape
    as the habit-'C' case. **The double scaling does
    not reproduce under v3.5.** This function is the identity: there is no
    MATLAB operation left here to transcribe.
    """
    return np.asarray(image_diam_areaR, dtype=np.float64)


def clip_area_ratio(area_ratio: np.ndarray) -> np.ndarray:
    """v3.5 ``sizeDist.m:1161`` -- ``area_ratio(area_ratio > 1.) = 1.;``,
    "Added by Joe Finlon 03/19/23". Absent from stock v3.1.4, which lets
    ``area_ratio`` exceed 1 (a geometrically impossible value the ``.2``
    reject test never filters, since it only rejects *small* ratios). Runs
    immediately before that reject test; this function is only the clip,
    using :data:`AREA_RATIO_UPPER_CLIP`.
    """
    out = np.asarray(area_ratio, dtype=np.float64).copy()
    out[out > AREA_RATIO_UPPER_CLIP] = AREA_RATIO_UPPER_CLIP
    return out


# ---------------------------------------------------------------------------
# 4. Reacceptance dispatch -- the three loops, two behaviours
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ReaccptCfg:
    """Adapts :class:`~.sizedist_tables.ProbeDefaults`' field names to what
    :func:`arrayprobe_uiops.sizedist_core._reaccept_shattered` reads off its ``cfg``."""

    reaccpt_d: float
    reaccpt_max_ia: float


def _reaccpt_cfg(cfg: ProbeDefaults) -> _ReaccptCfg:
    return _ReaccptCfg(reaccpt_d=cfg.reaccptD, reaccpt_max_ia=cfg.reaccptMaxIA)


def _auto_reject_to_chars(auto_reject: np.ndarray) -> np.ndarray:
    return np.array([chr(int(c)) for c in auto_reject], dtype="<U1")


def _auto_reject_from_chars(chars: np.ndarray, dtype) -> np.ndarray:
    return np.array([ord(c) for c in chars], dtype=dtype)


def apply_shattering(
    *,
    ia_thresh_type: int,
    cfg: ProbeDefaults,
    spec: InterarrivalThresholdSpec,
    i: int,
    auto_reject: np.ndarray,
    int_arr: np.ndarray,
    int_arr2: np.ndarray | None,
    int_arr3: np.ndarray | None,
    particle_diameter_minR: np.ndarray,
    start: int,
    count: int,
    intar_threshold: np.ndarray | None = None,
) -> np.ndarray:
    """Dispatch to whichever of the THREE reacceptance loops this second's
    ``ia_thresh_type`` selects, mutating and returning ``auto_reject``.

    **This function IS the trap the brief calls "the most important thing in
    this brief," made explicit as code.**  v3.5's ``sizeDist.m`` carries three
    structurally similar shattering blocks that do NOT all behave the same:

    * ``ia_thresh_type == 1`` (``:1213``) and ``== 2`` (``:1346``) both scan
      a colon range from ``find(rBegin)`` to ``find(rEnd)`` -- MATLAB's first-element colon
      rule collapses this to the FIRST shattering event only, the same
      preserved defect documented at v3.1.4 ``sizeDist.m:1036``,
      ``:1169``.  **Reused verbatim** via
      :func:`arrayprobe_uiops.sizedist_core._reaccept_shattered` -- not re-transcribed,
      since the block is byte-for-byte the same idiom v3.1.4 already has and
      already tests.  Regression tests:
      ``TestThreeLoopsTwoBehaviours::test_type1_and_type2_use_the_v314_preserved_bug_reaccept_shattered``.
    * ``ia_thresh_type == 3`` (``:1416-1419``, "JF 11/5/25") is NEW in v3.5
      and was deliberately rewritten to scan
      from the first ``rBegin`` index to the last ``rEnd`` index
      (v3.5 ``sizeDist.m:1419``) -- one continuous bracket spanning
      EVERY shattering event in the second, not just the first.  Uses
      :func:`~.sizedist_tables.reaccept_shattered_1hz`, which
      implements exactly this bracketed scan.  Regression test:
      ``TestThreeLoopsTwoBehaviours::test_type3_uses_the_fixed_bracketed_reaccept``.
    * ``TestThreeLoopsTwoBehaviours::test_the_two_conventions_differ_on_the_same_second``
      asserts, on one synthetic second carrying two separate shattering
      events, that dispatching it through type 1/2 reaccepts nothing from the
      second event while dispatching the SAME data through type 3 does --
      the two conventions provably differing within the same file, as the
      brief requires.
    """
    def _refuse_missing_int_arr3(line: int) -> None:
        # int_arr3 is None only on probetype 0 (see _interarrival), where MATLAB never
        # assigns it, so the block about to read it dies there. Refused, never invented.
        if int_arr3 is None:
            raise NotImplementedError(
                f"v3.5 sizeDist.m:{line} reads int_arr3, which :1004-1018 builds only for "
                "probetype != 0: this probetype-0 run with reaccptShatrs=1 dies in MATLAB "
                "with \"'int_arr3' undefined\".")

    if ia_thresh_type == 0:
        return auto_reject  # :1179's `if iaThreshType==1...`/`==2`/`==3` all
        # false; neither of the three blocks runs (measured for v3.1.4 on a
        # 2DC fixture, restated here for v3.5's identical gating -- see
        # arrayprobe.sizedist.run's own docstring for that measurement).

    if ia_thresh_type == 1:
        if not (cfg.applyIntArrThresh and spec.ia_thresh_file not in (None, "NONE")):
            return auto_reject
        # Invariant: with iaThreshType == 1 and one argument, select_interarrival_threshold
        # hands back varargin{1} itself, the threshold file's name (sizeDist.m:1179 opens it).
        ia_thresh_path = cast(str, spec.ia_thresh_file)
        with ncio.open(ia_thresh_path, "nowrite") as ia_nc:
            ia_thresh = ia_nc.get_var(
                ia_nc.inq_var_id("threshold"), start, count
            ).reshape(-1)
        if len(int_arr) == 1 and int_arr[0] <= ia_thresh[0]:
            auto_reject[0] = ord("S")
        else:
            if int_arr[0] <= ia_thresh[0]:
                auto_reject[0] = ord("S")
            hits = np.flatnonzero(int_arr[1:] <= ia_thresh[1:]) + 1
            for ix in hits:
                auto_reject[ix - 1 : ix + 1] = ord("S")
        if cfg.reaccptShatrs:
            _refuse_missing_int_arr3(1204)
            _reaccept_shattered(
                auto_reject, int_arr, int_arr3, ia_thresh,
                particle_diameter_minR, _reaccpt_cfg(cfg),
            )
        return auto_reject

    if ia_thresh_type == 2:
        if not cfg.applyIntArrThresh:
            return auto_reject
        if not cfg.intar_threshold_defaulted and intar_threshold is None:
            # (PECAN assigns it through its spiral loop, supplied as `intar_threshold`.)
            # The case sets applyIntArrThresh = 1 but never assigns intar_threshold, so the
            # block's first read of intar_threshold(i) is where MATLAB dies: :1312 when int_arr2
            # is non-empty, else :1317 for a one-particle second, else :1320 (Octave 11.3 on
            # GPM/2DS and IMPACTS/2DS: "'intar_threshold' undefined near line 1320").
            has_int_arr2 = int_arr2 is not None and int_arr2.size > 0
            line = 1312 if has_int_arr2 else 1317 if len(int_arr) == 1 else 1320
            raise NotImplementedError(
                f"v3.5 sizeDist.m:{line} reads intar_threshold(i), which this project/probe "
                "case never assigns although it sets applyIntArrThresh = 1: with "
                "iaThreshType = 2 MATLAB dies with \"'intar_threshold' undefined\". "
                "Refused, never invented.")
        # `intar_threshold(i)`: the case's constant every second, except under PECAN, where a
        # supplied parameter file's spirals set it per second (pecan_params.py, :160-172).
        thresh_i = (cfg.defaultIntArrThresh if intar_threshold is None
                    else float(intar_threshold[i]))
        ia_thresh = np.full(count, thresh_i)
        if int_arr2 is not None and int_arr2.size and int_arr2[0] <= thresh_i:
            auto_reject[-1] = ord("S")
        if len(int_arr) == 1 and int_arr[0] <= thresh_i:
            auto_reject[0] = ord("S")
        else:
            if int_arr[0] <= thresh_i:
                auto_reject[0] = ord("S")
            hits = np.flatnonzero(int_arr[1:] <= thresh_i) + 1
            for ix in hits:
                auto_reject[ix - 1 : ix + 1] = ord("S")
        if cfg.reaccptShatrs:
            _refuse_missing_int_arr3(1337)
            _reaccept_shattered(
                auto_reject, int_arr, int_arr3, ia_thresh,
                particle_diameter_minR, _reaccpt_cfg(cfg),
            )
        return auto_reject

    if ia_thresh_type == 3:
        if not (cfg.applyIntArrThresh and spec.iat_thresh is not None):
            return auto_reject
        thresh_i = float(spec.iat_thresh[i])
        int_arr_list = np.asarray(int_arr, dtype=np.float64).tolist()
        chars = _auto_reject_to_chars(auto_reject)
        chars = flag_shattered_1hz(int_arr_list, thresh_i, auto_reject=chars.tolist())
        if cfg.reaccptShatrs:
            _refuse_missing_int_arr3(1403)
            assert int_arr3 is not None  # the line above raises otherwise
            chars, _e_index = reaccept_shattered_1hz(
                chars.tolist(), int_arr_list,
                np.asarray(int_arr3, dtype=np.float64).tolist(),
                np.asarray(particle_diameter_minR, dtype=np.float64).tolist(), thresh_i,
                reaccptD=cfg.reaccptD, reaccptMaxIA=cfg.reaccptMaxIA,
            )
        return _auto_reject_from_chars(chars, auto_reject.dtype)

    raise ValueError(f"iaThreshType is 0, 1, 2 or 3 in v3.5's sizeDist.m; got {ia_thresh_type!r}")


# ---------------------------------------------------------------------------
# 5. The writer -- NETCDF4, renamed/added attributes, iat_threshold, and the
#    three fixed transposes
# ---------------------------------------------------------------------------

#: Declared gaps, same convention as ``arrayprobe_uiops.spec.WRITER_GAPS``:
#: ``arrayprobe_uiops.ncio.def_var`` (the project's single netCDF encoder) exposes
#: no ``deflate`` parameter, and extending it is a change to
#: ``src/arrayprobe/``, out of scope while a regression run is live in that
#: tree at the time. Deflate is lossless -- ``TestWriterGaps`` proves that
#: rather than asserting it -- so the port's v3.5 files are NETCDF4 but
#: uncompressed.
WRITER_GAPS = {
    "deflate": (
        "sizeDist.m gains `netcdf.defVarDeflate(..., true, true, 9)` on every "
        "variable (v3.5 diff). `ncio.def_var` has no deflate parameter; "
        "closes with one keyword there. Lossless -- values are unaffected."
    ),
}

_NOT_TRANSPOSED_V314 = frozenset(
    {"mean_area_ratio", "mean_aspect_ratio_rectangle", "mean_aspect_ratio_ellipse"}
)


def _vars_v35():
    """v3.1.4's ``_VARS``/``_VARS_ASPECT``/``_REJ_ATTS`` with the one
    attribute-text change v3.5 makes (``re``'s ``units`` -- ``:12`` below):
    ``'um'`` -> ``'mm'`` (``sizeDist.m`` diff, ``varid12``/``varid32``).  The
    schema (names, dims, which vars exist under which flag) is otherwise
    unchanged; only the ``re``/``REJ_re`` unit LABEL and the six transposes
    (handled at the value-assembly step, not here) differ.

    That diff is against the stock v3.1.4 MATLAB.  The v3.1.4 *port's* own
    tables already carry ``'mm'`` -- the ORACLES fork's label -- and
    the v3.1.4 validation engine's ``sizedist.run(attribute_text=...)`` (not included in this
    package) swaps in stock's ``'um'``
    at write time (2026-09-13), so this patch is a no-op on today's tables.
    It stays so v3.5's label never depends on that table's literal.
    """
    def _patch_units(defs):
        out = []
        for name, dims, atts in defs:
            if name in ("re",):
                atts = tuple(
                    ("units", "mm") if a == "units" else (a, v) for a, v in atts
                )
            out.append((name, dims, atts))
        return tuple(out)

    return _patch_units(_VARS), _VARS_ASPECT, _VARS_TAIL, _VARS_INTARR


def _rej_atts_v35():
    atts = dict(_REJ_ATTS)
    re_atts = atts["re"]
    atts["re"] = tuple(("units", "mm") if a == "units" else (a, v) for a, v in re_atts)
    return atts


def _write_v35(
    mainf, out, num_bins, n_sec, infile, projectname, probename, sa_method,
    d_choice, apply_int_arr_thresh, reaccpt_shatrs, cfg, i_create_bad,
    i_create_aspect_ratio, i_save_int_arr_sv, attr_habit, iat_threshold,
    software, creation_time, stamp_profile=None, tas_qc=None, area_ratio_z=None,
    default_int_arr_thresh=None, time_offset=None,
):
    """v3.5 ``sizeDist.m:~2026-2450``.  Structurally ``sizedist._write`` in the v3.1.4
    validation engine (not included in this package),
    with: ``netcdf.create(...,'NETCDF4')`` (done by the caller, at ``ncio.create``
    time -- nothing to redo here), the renamed/added/dropped global attributes,
    the new ``iat_threshold`` variable when ``iat_threshold is not None``, and
    deflate declared as a gap (:data:`WRITER_GAPS`) rather than silently
    dropped.
    """
    dim = {
        "CIPcorrlen": mainf.def_dim("CIPcorrlen", num_bins),
        "CIParealen": mainf.def_dim("CIParealen", 10),
        "Time": mainf.def_dim("Time", n_sec),
        "Habit": mainf.def_dim("Habit", 10),
    }

    g = ncio.get_constant("NC_GLOBAL")
    mainf.put_att(g, "Software", software)
    # 'Institution' is commented out in v3.5's own source (same hunk as the
    # Software rewrite) -- dropped, not renamed.
    mainf.put_att(
        g, "Creation_Time",
        creation_time if creation_time is not None else datestr(None, "yyyy/mm/dd HH:MM:SS"),
    )
    mainf.put_att(g, "Description", "Contains size distributions of particle "
                  "count, mass, etc. & various bulk properties.")
    mainf.put_att(g, "Project", projectname)
    mainf.put_att(g, "Data_Source", str(infile))
    mainf.put_att(g, "Probe_Type", probename)
    mainf.put_att(g, "Habit_Scheme", attr_habit)
    sa_label = {0: "Center-in", 1: "Entire-in",
                2: "Using Heymsfield & Parrish (1978) correction"}
    if sa_method in sa_label:
        mainf.put_att(g, "SA Method", sa_label[sa_method])
    if d_choice in D_CHOICE:
        mainf.put_att(g, "Dmax Definition", D_CHOICE[d_choice][1])
    if apply_int_arr_thresh and reaccpt_shatrs:
        mainf.put_att(g, "Shattering Algorithm", "Applied w/ reacceptance of particles")
        mainf.put_att(
            g, "Reacceptance Criteria",
            f"D > {_num2str(cfg.reaccptD * 1000)} um; inter-arrival "
            f"< {_num2str(cfg.reaccptMaxIA)} sec",
        )
    elif apply_int_arr_thresh:
        mainf.put_att(g, "Shattering Algorithm", "Applied without reacceptance of particles")
    else:
        mainf.put_att(g, "Shattering Algorithm", "Not applied")
    mainf.put_att(
        g, "Optional Parameters Saved",
        _optional_parameters(i_create_bad, i_create_aspect_ratio, i_save_int_arr_sv),
    )
    # In-file provenance: arrayprobe_engine / arrayprobe_profile, not MATLAB output.
    for name, value in provenance.engine_attrs(engine="3.5", profile=stamp_profile).items():
        mainf.put_att(g, name, value)
    # The airspeed data-quality record, written by default on this engine: which seconds
    # were sized with a substituted or default TAS, and why. ``None`` (the run named no TAS
    # source, so there is no record to state) writes nothing.
    # Sorted, as the .tasqc.json sidecar is, so a re-run from the sidecar writes the same order.
    for key, value in sorted((tas_qc or {}).items()):
        mainf.put_att(g, f"{provenance.ATTR_PREFIX}{key}", value)
    # The opt-in 'z' threshold (run()'s docstring), written only when set so the default
    # file is byte-for-byte the one that was always written.
    if area_ratio_z is not None:
        mainf.put_att(g, f"{provenance.ATTR_PREFIX}area_ratio_z", float(area_ratio_z))
    # The opt-in default inter-arrival threshold (run()'s docstring), likewise written only
    # when set.
    if default_int_arr_thresh is not None:
        mainf.put_att(g, f"{provenance.ATTR_PREFIX}default_int_arr_thresh",
                      float(default_int_arr_thresh))
    # The opt-in probe-clock offset (TimeOffset), likewise written only when set.
    if time_offset is not None:
        mainf.put_att(g, f"{provenance.ATTR_PREFIX}time_offset_s", float(time_offset.seconds))
        mainf.put_att(g, f"{provenance.ATTR_PREFIX}time_offset_evidence", time_offset.evidence)
        mainf.put_att(g, f"{provenance.ATTR_PREFIX}time_offset_tas_clock", time_offset.tas_clock)

    vars_, vars_aspect, vars_tail, vars_intarr = _vars_v35()
    defs = list(vars_)
    if i_create_aspect_ratio:
        defs += list(vars_aspect)
    defs += list(vars_tail)
    if i_create_bad:
        by_name = {name: (dims, atts) for name, dims, atts in vars_ + vars_aspect + vars_tail}
        rej_atts = _rej_atts_v35()
        defs += [("REJ_" + name, by_name[name][0], rej_atts[name]) for name in _REJ_ORDER]
    if i_save_int_arr_sv:
        defs += list(vars_intarr)
    if iat_threshold is not None:
        defs.append((
            "iat_threshold", ("Time",),
            (("units", "s"), ("long_name",
             "inter-arrival time threshold used to determine which particles "
             "are likely shattered artifacts")),
        ))

    varid = {}
    for name, dims, atts in defs:
        varid[name] = mainf.def_var(name, "double", [dim[d] for d in dims])
        for att, value in atts:
            mainf.put_att(varid[name], att, value)

    mainf.end_def()

    for name in varid:
        mainf.put_var(varid[name], np.asarray(out[name]))


# ---------------------------------------------------------------------------
# 6. The driver
# ---------------------------------------------------------------------------


def run(
    infile, outfile, tas, timehhmmss, probename, d_choice, sa_method, pres, temp,
    ia_thresh_type, i_create_aspect_ratio, i_create_bad, i_save_int_arr_sv,
    projectname, ddate, *varargin,
    software,
    probe_case=None,
    mmethod=0,
    mmethod_pow=0.0,
    area_ratio_z=None,
    default_int_arr_thresh=None,
    pecan_params=None,
    tas_max=None,
    octave_mean_extra=False,
    octave_colon=False,
    creation_time=None,
    progress=None,
    stamp_profile=None,
    tas_qc=None,
    time_offset_s=None,
    time_offset_evidence=None,
    time_offset_tas_clock=None,
    zero_sv_nan=False,
):
    """``sizeDist(infile, outfile, tas, timehhmmss, probename, d_choice,
    SAmethod, Pres, Temp, iaThreshType, iCreateAspectRatio, iCreateBad,
    iSaveIntArrSV, projectname, ddate, varargin)`` -- v3.5's own positional
    signature (unchanged from v3.1.4 stock; see the module docstring).

    ``mmethod``/``mmethod_pow`` are NOT part of stock v3.5's signature -- they
    port Peter Brechner's ``Mmethod`` argument to his forked
    ``sizeDist_decibel3.m`` (``:1186-1211``), an opt-in flag defaulting to 0,
    stock v3.5's own habit M-D and textually the same code path this function
    always ran before ``mmethod`` existed --
    ``tests/test_held_back_modules_refuse_cleanly.py`` asserts the default never
    reaches ``mass_b26``.
    ``mmethod`` 1, 2 or 3 reaches ``arrayprobe_uiops.mass_b26``, which this
    release does not include because the method is not yet published. The
    import is lazy and guarded: with the module absent, ``mmethod`` 1-3
    refuses by name, so only ``mmethod=0`` runs.

    ``software`` is required, no default -- v3.5 reads it from a
    ``version.txt`` beside the MATLAB source at runtime (``:2033-2035``,
    "Added dynamic software version to netCDF metadata"), the same cwd-relative,
    unchecked-``fopen`` pattern already found and named an upstream finding for
    ``read_binary_SPEC.m`` and ``imgProc_sm.m``.  Reproducing the
    cwd-dependence itself would make this port's OUTPUT depend on where Python
    was started; naming the string explicitly instead makes the same fact
    recordable rather than accidental, the same choice ``arrayprobe_uiops.spec``
    already made for its own ``software``/``creation_time`` arguments.

    ``tas_qc`` is the airspeed data-quality record
    (:func:`arrayprobe.tools.tas_sources.qc_record`), not a MATLAB argument: each key is
    written as an ``arrayprobe_<key>`` global attribute beside the engine attributes, so the
    file itself says which seconds were sized with a substituted or default TAS.
    ``None`` writes nothing; no variable changes either way.

    ``area_ratio_z`` is NOT part of stock v3.5's signature either. ``None`` (default)
    keeps ``sizeDist.m:1162``'s literal ``.2`` through :data:`AREA_RATIO_Z`, so the path is
    textually the one that always ran (``tests/test_v35_area_ratio_z.py::
    TestDefaultIsBitIdentical``). A value in ``[0, 1]`` replaces only that literal: a particle
    whose clipped area ratio is below it is rejected as ``'z'``. ``0.0`` is the gate off (an
    area ratio is ``area / (pi/4 d^2)`` with ``area >= 0``, so never below 0, and NaN compares
    false; asserted against the Octave oracle, not assumed). Anything else raises. The
    oracle is named: the vendored ``sizeDist.m`` with that one literal changed in a
    shadowing copy (the Octave bank ``run_v35_area_ratio_z_bank.py``, dev repository only,
    ``tests/test_v35_area_ratio_z_oracle.py``). A run that sets it writes one global
    attribute, ``arrayprobe_area_ratio_z``; a run that does not writes nothing new.

    ``default_int_arr_thresh`` is NOT part of stock v3.5's signature either. ``None``
    (default) keeps the case's own ``defaultIntArrThresh = <literal>`` assignment
    (``sizeDist.m:139-642``, e.g. ``:313`` for SOCRATES/2DS), so the path is textually the
    one that always ran. A finite value ``>= 0`` (seconds) replaces only that constant in
    the resolved ``ProbeDefaults``, after the switch or probe-case lookup. v3.5 reads
    ``defaultIntArrThresh`` in exactly one place: ``intar_threshold =
    ones(size(tas_time))*defaultIntArrThresh`` (e.g. ``:318``), which is read only by the
    ``iaThreshType == 2 && applyIntArrThresh`` block (``:1308-1338``). So the value is
    unused when ``iaThreshType`` is not 2, when the case sets ``applyIntArrThresh = 0``,
    and it does not rescue a case that never assigns ``intar_threshold`` (GPM/2DS,
    IMPACTS/2DS: still refused at the read site, as MATLAB dies there). A run that sets it
    writes the attribute ``arrayprobe_default_int_arr_thresh`` whether or not the gate used it;
    one that does not writes nothing new. Octave oracle: ``run_v35_default_int_arr_thresh_bank.py``.

    ``pecan_params`` is NOT part of stock v3.5's signature either. The PECAN CIP and PIP
    cases call ``getPECANparams`` (``:164``, ``:195``), which ships in no release, so without
    it the run is refused as MATLAB dies there. A path to a parameter file (or a
    :class:`~arrayprobe_uiops.pecan_params.PecanParams`) supplies the call's three used outputs,
    and the case then runs exactly as MATLAB would with them: ``intar_threshold`` is the
    case's ``defaultIntArrThresh`` every second except inside a spiral, read only under
    ``iaThreshType == 2``. Refused on any other case. Format: ``pecan_params.py``.

    ``tas_max`` is NOT part of stock v3.5's signature either. The 2DP case (``:595-617``)
    assigns no ``tasMax``, which ``:771``, ``:1026-1088``, ``:1144`` and ``:1926`` read, so
    without it the run is refused as MATLAB dies there (:class:`TasMaxUndefined`). A finite
    value ``> 0`` (m/s) is used as that case's ``tasMax``; there is no default. Refused on a
    case that assigns its own ``tasMax``. Neither keyword writes anything when unset.

    ``time_offset_s`` is NOT part of stock v3.5's signature either: a whole number of seconds
    ADDED to every particle's ``Time``/``particle_time`` where it is read, for a probe whose own
    clock is measured off aircraft time (:class:`TimeOffset`). It needs
    ``time_offset_evidence`` (how it was measured) and ``time_offset_tas_clock``: ``"probe"``
    when ``timehhmmss``/``tas`` came from the probe's own record (same off clock: shifted too),
    ``"aircraft"`` when they came from an aircraft file (already aircraft time: left alone).
    Inter-arrival times are differences of ``Time_in_seconds`` and do not move. ``None``
    (default) leaves the path textually the one that always ran; a run that sets it writes
    ``arrayprobe_time_offset_s``, ``arrayprobe_time_offset_evidence`` and
    ``arrayprobe_time_offset_tas_clock``.

    Probetypes 0-3 are supported -- see the module docstring's "Scope".
    Everything else this function refuses is refused explicitly, as an error
    naming the source line, never a silent fallback.
    """
    if ia_thresh_type not in (0, 1, 2, 3):
        raise ValueError(
            f"iaThreshType is 0, 1, 2 or 3 in v3.5's sizeDist.m; got {ia_thresh_type!r}"
        )

    if area_ratio_z is not None:
        if isinstance(area_ratio_z, bool) or not (
                isinstance(area_ratio_z, (int, float, np.integer, np.floating))
                and math.isfinite(float(area_ratio_z)) and 0.0 <= float(area_ratio_z) <= 1.0):
            raise ValueError(
                "area_ratio_z replaces the literal .2 at v3.5 sizeDist.m:1162 and is a finite "
                f"number in [0, 1] (0 is the gate off); got {area_ratio_z!r}"
            )
        area_ratio_z = float(area_ratio_z)

    if default_int_arr_thresh is not None:
        if isinstance(default_int_arr_thresh, bool) or not (
                isinstance(default_int_arr_thresh, (int, float, np.integer, np.floating))
                and math.isfinite(float(default_int_arr_thresh))
                and float(default_int_arr_thresh) >= 0.0):
            raise ValueError(
                "default_int_arr_thresh replaces the case's defaultIntArrThresh constant "
                "(v3.5 sizeDist.m:139-642, read through intar_threshold at :1308-1338) and "
                f"is a finite number of seconds >= 0; got {default_int_arr_thresh!r}"
            )
        default_int_arr_thresh = float(default_int_arr_thresh)

    if tas_max is not None:
        if isinstance(tas_max, bool) or not (
                isinstance(tas_max, (int, float, np.integer, np.floating))
                and math.isfinite(float(tas_max)) and float(tas_max) > 0.0):
            raise ValueError(f"tas_max is an airspeed in m/s, finite and > 0; got {tas_max!r}")
        tas_max = float(tas_max)
    time_offset = None
    if time_offset_s is not None:
        time_offset = TimeOffset.build(time_offset_s, time_offset_evidence, time_offset_tas_clock)
    elif time_offset_evidence is not None or time_offset_tas_clock is not None:
        raise ValueError("time_offset_evidence/time_offset_tas_clock given without time_offset_s")

    spec = select_interarrival_threshold(ia_thresh_type, varargin)
    if spec.too_many_inputs:
        _logger.warning("You have added too many inputs!")

    tas = np.asarray(tas, dtype=np.float64).reshape(-1)
    timehhmmss = np.array(timehhmmss, dtype=np.float64).reshape(-1)
    pres = np.asarray(pres, dtype=np.float64).reshape(-1)
    temp = np.asarray(temp, dtype=np.float64).reshape(-1)

    f = ncio.open(infile, "nowrite")
    try:
        # v3.5 sizeDist.m:100-108 -- `ncinfo(infile)` / `{pbpinfo.Variables.Name}`,
        # read here through `.dataset` deliberately: this is metadata
        # enumeration (variable NAMES), never data, so none of the
        # shape/orientation contract `.dataset`'s own docstring warns ported
        # call sites off of applies.
        var_names = list(f.dataset.variables.keys())
        i_new_habit, attr_habit = detect_habit_scheme(var_names)

        if probe_case is None:
            cfg = probe_defaults(projectname, probename, version="3.5")
        else:
            # Opt-in, default-off (the retracted 2D-S bin table): a NAMED case replaces the switch's
            # lookup for this run, and nothing else about the driver changes --
            # `cfg` is the same ProbeDefaults record either way. `probe_case`
            # is None on every run that does not name one, so the stock path
            # above is bit-identical to what it always was
            # (tests/test_v35_probe_cases.py::TestDefaultIsBitIdentical).
            # Why a registry rather than a table entry, and why the ladder is
            # not "fixed" in V35_TABLES: arrayprobe_uiops/probe_cases.py.
            cfg = resolve_probe_case(probe_case).defaults
        pecan = None
        if cfg.calls_getPECANparams:
            if pecan_params is None:
                raise NotImplementedError(
                    _PECAN_UNDEFINED.format(case=f"{projectname!r}/{probename!r}"))
            pecan = resolve_pecan_params(pecan_params, ddate=ddate, probename=probename)
        elif pecan_params is not None:
            raise ValueError(
                f"pecan_params replaces getPECANparams, which only the PECAN CIP/PIP cases "
                f"call; {projectname!r}/{probename!r} does not")
        if tas_max is not None:
            if cfg.tasMax is not None:
                raise ValueError(
                    f"tas_max supplies a tasMax the case leaves unassigned (2DP); "
                    f"{projectname!r}/{probename!r} assigns tasMax = {cfg.tasMax:g}")
            cfg = replace(cfg, tasMax=tas_max)
        if cfg.probetype not in (0, 1, 2, 3):
            raise UnsupportedProbetype(
                f"{projectname!r}/{probename!r} (v3.5) is probetype {cfg.probetype}. "
                "This driver ports probetypes 0 (2DC/2DP), 1 (CIP/PIP), "
                "2 (2D-S/HVPS/3VCPI) and 3 (Fast2DC) and no other; see the "
                "module docstring's Scope section."
            )
        if default_int_arr_thresh is not None:
            # Opt-in, default-off: only the constant changes. `intar_threshold_defaulted`
            # is the case's own (whether it assigns intar_threshold at all), so a case
            # MATLAB dies on stays refused rather than invented.
            cfg = replace(cfg, defaultIntArrThresh=default_int_arr_thresh)

        mainf = ncio.create(outfile, "clobber", format="NETCDF4")
        try:
            out = _run(
                f, mainf, infile, tas, timehhmmss, probename, d_choice, sa_method,
                pres, temp, projectname, ddate, ia_thresh_type, spec, cfg,
                i_new_habit, attr_habit, bool(i_create_bad),
                bool(i_create_aspect_ratio), bool(i_save_int_arr_sv),
                octave_mean_extra, octave_colon, software, creation_time, progress,
                mmethod, mmethod_pow, stamp_profile=stamp_profile, tas_qc=tas_qc,
                area_ratio_z=area_ratio_z, default_int_arr_thresh=default_int_arr_thresh,
                pecan=pecan,
                time_offset=time_offset,
                zero_sv_nan=zero_sv_nan,
            )
        finally:
            mainf.close()
    finally:
        f.close()
    return out


def _read_block(gv, i, old_style, i_create_aspect_ratio, probetype, total_pc1, total_pc2):
    """Phase 1 of `_run`'s per-second body: the particle-block reads (v3.5 `:925-977`).

    Extracted verbatim from `_run` (V35_CODE_REVIEW item 1): the same `gv` reads in the
    same order, the same casts, the same in-place writes to `total_pc1[i]`/`total_pc2[i]`
    (the caller's arrays), and every array returned is the object `_run` bound before.
    """
    auto_reject = gv("image_auto_reject").copy()
    # -- v3.5 fix for the int16 diameter saturation: cast to double BEFORE the d_choice arithmetic,
    # so `mmul`/`mdiv`/`mpow`/`mmax` (matlab_compat's saturating ops)
    # never see an int16 operand and never saturate.
    im_width = gv("image_width").astype(np.float64)
    im_length = gv("image_length").astype(np.float64)
    area = gv("image_area").astype(np.float64).copy()
    perimeter = gv("image_perimeter")
    habit1 = gv("holroyd_habit")
    centerin = gv("image_center_in")
    entirein = gv("image_touching_edge")

    if i_create_aspect_ratio:
        with np.errstate(divide="ignore", invalid="ignore"):
            aspect_ratio = gv("image_RectangleW") / gv("image_RectangleL")
            aspect_ratio1 = gv("image_EllipseW") / gv("image_EllipseL")
    else:
        aspect_ratio = aspect_ratio1 = None

    # -- v3.5 fix: NO second scaling by diodesize. `image_diam_AreaR` is read and
    # used exactly as `imgProc_sm.m` wrote it, unlike v3.1.4's `:669`, which the
    # v3.1.4 port's own docstring names as the double-scaled area-ratio
    # concentration (conc_AreaR effectively always zero on a 2D-S).
    particle_diameter_AreaR = gv("image_diam_AreaR")

    time_in_seconds = gv("Time_in_seconds")

    rec_nums = gv("parent_rec_num") if old_style else None   # `:945-947`
    dof_overload = gv("DMT_DOF_SPEC_OVERLOAD")
    # `:964-966` -- a 2DC/2DP/Fast2DC file written in the SEA convention flags
    # EVERY particle overloaded; the source zeroes the whole array, "since
    # overload can't be treated using SEA convention".
    if old_style and np.sum(dof_overload) == len(dof_overload):
        dof_overload = 0 * dof_overload
    # `:969-973` -- gated `(probetype~=0) && (probetype~=3)`: probetypes 0/3 never
    # read the probe's own count, so TotalPC1/TotalPC2 keep their zeros.
    if not old_style:
        particle_count = gv("Particle_number_all")
        total_pc1[i] = len(particle_count)
        total_pc2[i] = particle_count[-1] - particle_count[0]

    # `:975-977` -- probetype 1 ONLY: every particle in an overloaded
    # DOF sample is marked rejected with 'D'. No such mark exists for
    # probetype 2, which is why the same second on a 2D-S keeps its
    # particles and only loses the dead TIME (`:1116`) instead.
    if probetype == 1:
        auto_reject[dof_overload != 0] = ord("D")
    return (auto_reject, im_width, im_length, area, perimeter, habit1, centerin,
            entirein, aspect_ratio, aspect_ratio1, particle_diameter_AreaR,
            time_in_seconds, rec_nums, dof_overload)


def _interarrival(f, vid, start, count, start_all_max, time_in_seconds, probetype,
                  res, tas_max, reaccpt_shatrs):
    """Per-block interarrival times ``int_arr``/``int_arr2``/``int_arr3``
    (``sizeDist.m:984-1046``), moved verbatim out of ``_run`` (2026-09-25 code review, item 1,
    phase 2). Returns the three arrays ``_run`` reads afterwards; ``int_arr2``
    and ``int_arr3`` stay ``None`` on the arms that do not build them."""
    if probetype == 0:
        # `:984-985` -- not a difference: probetype 0's `int_arr` IS the
        # absolute `Time_in_seconds`. Fast2DC (3) takes the `else` arm below.
        int_arr = time_in_seconds.astype(np.float64).copy()
    elif start - 1 <= 0:
        int_arr = np.concatenate([[0.0], np.diff(time_in_seconds)])
    else:
        t2 = f.get_var(vid["Time_in_seconds"], start - 1, count + 1).reshape(-1)
        int_arr = np.diff(t2)
    int_arr = int_arr.copy()
    # `:1025-1029` -- the counter-rollover correction exists for
    # probetype 2 (`<-10`, 2^32-1) and probetype 0 (`<0`, 2^24-1) ONLY.
    # There is no `elseif 1==probetype` arm, so a CIP/PIP run gets no
    # rollover correction of any kind and its negative interarrival
    # times fall straight through to `:1046`'s `int_arr(int_arr<0)=0`.
    # Preserved as written.
    if probetype == 2:
        roll = int_arr < -10
        int_arr[roll] += (2 ** 32 - 1) * (res / 1e6 / tas_max)
    elif probetype == 0:
        # `:1027-1028` -- the 24-bit clock's rollback, threshold 0 (not -10).
        roll = int_arr < 0
        int_arr[roll] += (2 ** 24 - 1) * (res / 1e6 / tas_max)

    # -- int_arr2: NEW in v3.5, `max(start_all)` not `start_all(end)` --
    int_arr2 = None
    if probetype != 0 and start - 1 > 0 and start != start_all_max:
        t3 = f.get_var(vid["Time_in_seconds"], (start + count) - 1, 2).reshape(-1)
        int_arr2 = np.diff(t3)
        int_arr2 = int_arr2.copy()
        int_arr2[int_arr2 < 0] = 0

    # -- int_arr3: same `max(start_all)` change; stock's own
    # single-particle-at-last-block guard, unconditional here since
    # v3.5 IS the (only) stock lineage continued (no FidelityProfile).
    int_arr3 = None
    # `:1004-1018` builds int_arr3 only in the `else` of `:984`, so a probetype-0 run leaves
    # it unassigned (None here). Whether MATLAB then dies depends on whether one of the
    # shattering blocks that read it (`:1204`, `:1337`, `:1403`) runs, each gated on
    # iaThreshType and applyIntArrThresh; apply_shattering raises exactly there
    # (_refuse_missing_int_arr3), so a run in which no block runs completes, as MATLAB's does.
    if reaccpt_shatrs and probetype != 0:
        if start != start_all_max:
            t4 = f.get_var(vid["Time_in_seconds"], start, count + 1).reshape(-1)
            int_arr3 = np.diff(t4)
        elif len(time_in_seconds) > 1:
            d3 = np.diff(time_in_seconds)
            int_arr3 = np.concatenate([d3, [d3[-1]]])
        else:
            int_arr3 = np.zeros(1)
        int_arr3 = int_arr3.copy()
        int_arr3[int_arr3 < 0] = 0
    return int_arr, int_arr2, int_arr3


def _diameters_and_mass(gv, i, start, count, cfg, d_choice, diodesize, old_style, im_length,
    im_width, area, perimeter, habit1, centerin, entirein, rec_nums, dof_overload,
    auto_reject, int_arr, int_arr2, int_arr3, image_time_hhmmssall, tas, tas_max, pres,
    temp, mmethod, mmethod_pow, i_new_habit, ia_thresh_type, apply_int_arr_thresh, spec,
    sa_method, one_sec_times, time_interval72, time_interval2, good_partpercent,
    reject_by_criterion, total_one_sec_locs, area_ratio_z=None, intar_threshold=None):
    """Per-block diameters, mass, area ratio, fall speed, shattering and the
    good/bad masks (``sizeDist.m:1050-1211``), moved verbatim out of ``_run``
    (2026-09-25 code review, item 1, phase 3). Writes ``time_interval72``, ``time_interval2``,
    ``good_partpercent``, ``reject_by_criterion``, ``total_one_sec_locs`` and
    ``auto_reject`` in place, as the inline block did, and returns what the
    ``_process_population`` loop reads."""
    minr = gv("image_diam_minR") if d_choice == 6 else None
    particle_diameter_minR = d_choice_diameter(
        d_choice, im_length, im_width, diodesize, minr)

    if old_style:
        # `:1111-1113` -- 2DC/2DP/Fast2DC overload: the first particle of each
        # record carries the record's overload time in ms. MATLAB indexes the
        # length-n array with the length-(n-1) mask `diff(rec_nums)>0`, which
        # reads the first n-1 elements.
        rec_start = np.diff(rec_nums) > 0
        time_interval72[i] = float(np.sum(dof_overload[:-1][rec_start])) / 1000.0
    else:
        time_interval72[i] = overload_dead_time(
            int_arr, dof_overload, cfg.probetype)

    image_time_hhmmss = image_time_hhmmssall[start:start + count]

    if tas[i] > tas_max:
        area = area * tas[i] / tas_max
    if mmethod == 0:
        # Unchanged: literally the same computation this function
        # always ran before `mmethod` existed --
        # tests/test_mmethod_default_is_bit_identical.py.
        particle_mass = np.array([
            single_mass(d / 10, chr(int(h)), i_new_habit)
            for d, h in zip(particle_diameter_minR, habit1, strict=True)
        ])
    else:
        # Peter Brechner's `sizeDist_decibel3.m:1186-1211` `Mmethod`
        # ladder -- opt-in, folded into this engine from the
        # sibling package `arrayprobe_v35_brechner` on 2026-09-17
        # (the no-new-packages rule). Only `mmethod` in (1, 2, 3)
        # reaches it, and `mass_b26` is not part of every
        # distribution, so its absence is a named refusal rather
        # than a bare ImportError.
        try:
            from arrayprobe_uiops.mass_b26 import particle_mass_dispatch
        except ImportError as exc:
            raise ImportError(
                f"Mmethod={mmethod} is not available in this release: it needs "
                "arrayprobe_uiops.mass_b26, which this distribution does not ship. "
                "Use Mmethod=0 (the default)."
            ) from exc
        mass_diameter_minR = (
            particle_diameter_minR if d_choice == 6 else gv("image_diam_minR")
        )
        holroyd_perimeter = gv("Holroyd_perimeter") if mmethod == 3 else None
        hollow_mask = (auto_reject == ord("h")) if mmethod == 3 else None
        particle_mass = particle_mass_dispatch(
            mmethod,
            area=area,
            particle_diameter_minR=particle_diameter_minR,
            mass_diameter_minR=mass_diameter_minR,
            holroyd_perimeter=holroyd_perimeter,
            outer_perimeter=perimeter,
            hollow_mask=hollow_mask,
            diodesize=diodesize,
            pow=mmethod_pow,
        )
    calcd_area = np.array([
        single_area(d / 10, chr(int(h)), i_new_habit)
        for d, h in zip(particle_diameter_minR, habit1, strict=True)
    ])
    # Elementwise through the platform libm, as Octave's `.^` does: numpy's array `**` takes a
    # SIMD pow whose last bit depends on the CPU's dispatch (AVX-512 differed from the Octave
    # golden in 1-2 ULP where the libm pow did not; cloud pass 7 item 4).
    particle_massbl = 0.115 / 1000 * _libm_pow(area, 1.218)

    with np.errstate(divide="ignore", invalid="ignore"):
        area_ratio = area / (np.pi / 4 * particle_diameter_minR ** 2)
    # v3.5-only: clip (:1161) before the 'z' rejection test (:1162).
    area_ratio = np.minimum(area_ratio, AREA_RATIO_UPPER_CLIP)
    # `area_ratio_z` None is the literal `.2` of :1162 through AREA_RATIO_Z, the path that
    # always ran; a value replaces only that literal (run()'s docstring).
    z = AREA_RATIO_Z if area_ratio_z is None else area_ratio_z
    auto_reject[area_ratio < z] = ord("z")

    with np.errstate(divide="ignore", invalid="ignore"):
        particle_vt = np.array([
            single_vt(d / 1000, ar, m / 1000, pres[i], temp[i])
            for d, ar, m in zip(particle_diameter_minR, area_ratio,
                                particle_mass, strict=True)
        ])
    particle_pr = particle_mass * particle_vt

    if cfg.probetype == 0 and ia_thresh_type == 2 and apply_int_arr_thresh:
        # `:1310-1311` reads `~isempty(int_arr2)`, and `:984`'s probetype-0 arm
        # never assigns int_arr2 in any second, so v3.5 MATLAB dies with
        # "'int_arr2' undefined" -- the GPM 2DC int_arr2 crash, unchanged by the diff
        # and demonstrated under Octave for v3.1.4 on ('GPM','2DC').
        raise NotImplementedError(
            "v3.5 sizeDist.m:1311 reads int_arr2, which :984-985 never assigns "
            "for probetype 0: MATLAB dies with \"'int_arr2' undefined\" "
            "(an upstream finding). Reached via iaThreshType == 2.")
    auto_reject = apply_shattering(
        ia_thresh_type=ia_thresh_type, cfg=cfg, spec=spec, i=i,
        auto_reject=auto_reject, int_arr=int_arr, int_arr2=int_arr2,
        int_arr3=int_arr3, particle_diameter_minR=particle_diameter_minR,
        start=start, count=count, intar_threshold=intar_threshold,
    )

    good_particles = np.isin(auto_reject, [ord(c) for c in GOOD_REJECT_CODES])
    bad_particles = ~good_particles
    if sa_method == 0:
        good_particles = good_particles & (centerin == 1)
        bad_particles = bad_particles & (centerin == 1)
    elif sa_method == 1:
        good_particles = good_particles & (entirein == 0)
        bad_particles = bad_particles & (centerin == 0)

    good_partpercent[i] = np.count_nonzero(good_particles) / len(good_particles)
    reject_by_criterion[i, 0] = np.count_nonzero(centerin == 1) / len(good_particles)
    for c, code in enumerate(REJECT_CRITERION_CODES[1:], start=1):
        reject_by_criterion[i, c] = (
            np.count_nonzero(auto_reject == ord(code)) / len(good_particles))

    image_time = _hhmmss_to_insec(image_time_hhmmss)

    in_sec = (image_time >= one_sec_times[i]) & (image_time < one_sec_times[i + 1])
    total_one_sec_locs[i] = np.count_nonzero(in_sec)
    time_interval2[i] = float(msum(int_arr[in_sec]))
    if total_one_sec_locs[i] == 0:
        time_interval2[i] = 1
    return (particle_diameter_minR, area, particle_mass, calcd_area, particle_massbl,
            area_ratio, particle_vt, particle_pr, good_particles, bad_particles, image_time)


def _run(
    f, mainf, infile, tas, timehhmmss, probename, d_choice, sa_method, pres, temp,
    projectname, ddate, ia_thresh_type, spec, cfg, i_new_habit, attr_habit,
    i_create_bad, i_create_aspect_ratio, i_save_int_arr_sv, octave_mean_extra,
    octave_colon, software, creation_time, progress,
    mmethod=0, mmethod_pow=0.0, stamp_profile=None, tas_qc=None, area_ratio_z=None,
    default_int_arr_thresh=None, pecan=None, time_offset=None, zero_sv_nan=False,
):
    if time_offset is not None and time_offset.tas_clock == "probe":
        # Opt-in (TimeOffset): the per-second rows share the particles' off clock, so they move
        # with them, before the rollover below sees them as it would a real clock's.
        timehhmmss = shift_hhmmss(timehhmmss, time_offset.seconds)
    # -- flight-time rollover: UNCHANGED in v3.5, reused verbatim ----------
    _rollover_240000(timehhmmss)

    tas_time = (np.floor(timehhmmss / 10000) * 3600
                + np.floor((timehhmmss % 10000) / 100) * 60
                + np.floor(timehhmmss % 100))
    # :164-172 / :195-203 -- PECAN's per-second threshold from the supplied parameters;
    # None on every other case, which reads the constant (apply_shattering).
    intar_threshold = (None if pecan is None else
                       pecan_intar_threshold(tas_time, pecan, cfg.defaultIntArrThresh))

    num_bins = cfg.num_bins
    kk = cfg.kk(octave_colon=octave_colon)
    diodesize = cfg.diodesize
    res = diodesize * 1000
    binwidth = np.diff(kk)
    tas_max = cfg.tasMax
    if tas_max is None:
        raise TasMaxUndefined(_TASMAX_UNDEFINED)
    apply_int_arr_thresh = cfg.applyIntArrThresh
    reaccpt_shatrs = cfg.reaccptShatrs

    n_sec = len(tas)

    def nanmat():
        return np.full((n_sec, num_bins), np.nan)

    def nancube():
        return np.full((n_sec, num_bins, 10), np.nan)

    good = dict(
        dist_minR=nanmat(), dist_AreaR=nanmat(), areaRatio1=nanmat(),
        area=nanmat(), meanp=nanmat(), iwc=nanmat(), iwcbl=nanmat(),
        vt=nanmat(), pr=nanmat(), partarea=nanmat(),
        habitsd=nancube(), habitmsd=nancube(), area_dist2=nancube(),
        re=np.full(n_sec, np.nan), one_sec_ar=np.full(n_sec, np.nan),
        aspectRatio=nanmat() if i_create_aspect_ratio else None,
        aspectRatio1=nanmat() if i_create_aspect_ratio else None,
    )
    bad = dict(
        dist_minR=nanmat(), dist_AreaR=nanmat(), areaRatio1=nanmat(),
        area=nanmat(), meanp=nanmat(), iwc=nanmat(), iwcbl=nanmat(),
        vt=nanmat(), pr=nanmat(), partarea=nanmat(),
        habitsd=nancube(), habitmsd=nancube(), area_dist2=nancube(),
        re=np.full(n_sec, np.nan),
        # `bad_one_sec_ar = zeros(length(tas),1)` (v3.5 :708) -- ZERO, not NaN,
        # unlike every sibling `bad_*` accumulator (all `zeros(...)*NaN`). The
        # past-end-of-data branch below never touches ANY `bad_*` variable
        # (measured: :1848-1875 names only good-side variables), so a second
        # that never gets a real particle block leaves this at its own
        # allocation -- 0, not NaN (the uncorrected no-crossover particle time).
        one_sec_ar=np.zeros(n_sec),
        aspectRatio=nanmat() if i_create_aspect_ratio else None,
        aspectRatio1=nanmat() if i_create_aspect_ratio else None,
    )
    good_partpercent = np.zeros(n_sec)
    reject_by_criterion = np.zeros((n_sec, 14))
    time_interval2 = np.zeros(n_sec)
    time_interval72 = np.zeros(n_sec)
    total_one_sec_locs = np.zeros(n_sec)
    total_pc1 = np.zeros(n_sec)
    total_pc2 = np.zeros(n_sec)

    one_sec_times = np.concatenate([tas_time, [tas_time[-1] + 1]])

    _, num_of_part = f.inq_dim(0)

    # -- particle time: v3.5 `:758-781`, the three-arm probetype switch -----
    # `:758-759`  probetype 1 -> `particle_time`
    # `:760-778`  probetype 2 -> `Time`, via `image_time_hhmmssallbuffer`
    # `:779-780`  else (probetypes 0 and 3) -> `Time`, directly
    # so 0, 2 and 3 all end up with `Time` and only probetype 1 differs --
    # measured by reading the three arms, not inferred from probetype 2's.
    if cfg.probetype == 1:
        image_time_hhmmssall = f.get_var(f.inq_var_id("particle_time")).reshape(-1)
    else:
        image_time_hhmmssall = f.get_var(f.inq_var_id("Time")).reshape(-1)
    if time_offset is not None:
        # Opt-in (TimeOffset): onto aircraft time where the particle times are read, before
        # every midnight correction below, so those see a corrected clock's data.
        image_time_hhmmssall = shift_hhmmss(image_time_hhmmssall, time_offset.seconds)
    # `Time_in_seconds`/`msec` are also read here in the source but feed only
    # the dead-store `alltimeinseconds` computation (v3.1.4 port's own
    # docstring, ":522-528... DEAD STORE... discarded at :534"); v3.5's diff
    # does not touch that block. Not transcribed -- see the design record.

    # -- NEW in v3.5: the multi-day fix and the block-resolution logic -----
    image_time_hhmmssall, _ = fix_multiday_particle_times(image_time_hhmmssall)
    image_time_hhmmssall = apply_flight_day_carryover(image_time_hhmmssall, timehhmmss)
    starttime, start_all, count_all = resolve_particle_blocks(
        image_time_hhmmssall, int(num_of_part)
    )
    start_all_max = int(start_all.max())

    jjj = 1
    eof_flag = False
    n_blocks = len(start_all)

    vid_names = [
        "particle_millisec", "particle_microsec", "image_auto_reject",
        "image_width", "image_length", "image_area", "image_perimeter",
        "holroyd_habit", "image_center_in", "image_touching_edge",
        "image_diam_AreaR", "Time_in_seconds", "DMT_DOF_SPEC_OVERLOAD",
        "image_diam_minR",
    ]
    # `:945-947` reads `parent_rec_num` for probetypes 0 and 3 only; `:969-973` reads
    # `Particle_number_all` for every OTHER probetype (added with the CIP pipeline, 2026-09-23).
    old_style = cfg.probetype in (0, 3)
    vid_names += ["parent_rec_num"] if old_style else ["Particle_number_all"]
    if i_create_aspect_ratio:
        vid_names += ["image_RectangleW", "image_RectangleL",
                      "image_EllipseW", "image_EllipseL"]
    if mmethod == 3:
        # `sizeDist_decibel3.m:1206` -- only Mmethod 3 reads this variable;
        # a stock v3.5 fixture with no `Holroyd_perimeter` variable is
        # untouched at mmethod=0, the only value any existing caller passes.
        vid_names += ["Holroyd_perimeter"]
    vid = {name: f.inq_var_id(name) for name in vid_names}

    for i in range(n_sec):
        if progress is not None and (i + 1) % 1000 == 0:
            progress(i + 1, n_sec)

        # v3.5 :913/:918 compare `int32(timehhmmss(i))` with `int32(starttime(jjj))`:
        # int32 ROUNDS (half away from zero), where Python's `int` truncates, so a
        # fractional TAS time such as 164128.6 is second 164129 to MATLAB. `int()`
        # here before V35; measured under Octave, case `fractime`.
        t_int32 = int(mint32(timehhmmss[i]))
        if not eof_flag and t_int32 >= int(mint32(starttime[jjj - 1])):
            # v3.5 :918 -- `while (int32(timehhmmss(i))>int32(starttime(jjj)))`,
            # with NO `jjj < length(start_all)` bound (the ORACLES fork's
            # ORACLES-variant sizeDist.m:627 has one; no stock release does).
            while t_int32 > int(mint32(starttime[jjj - 1])):
                jjj += 1
                if jjj == n_blocks:
                    eof_flag = True
                if jjj > n_blocks:
                    # The loop's next test reads `starttime(jjj)` one past the
                    # end, so v3.5 MATLAB dies whenever a TAS second lands
                    # beyond the last particle block before `jjj` has reached
                    # it (a TAS gap over the final block). Measured under
                    # Octave on the unmodified v3.5 source, V35, case
                    # `tasgap`: "starttime(3): out of bound 2". Before V35
                    # this loop carried the fork's bound and completed.
                    raise MatlabIndexError(
                        f"v3.5 sizeDist.m:918 reads starttime({jjj}) past the "
                        f"last of {n_blocks} particle blocks at TAS second "
                        f"{t_int32}: the while loop has no "
                        "`jjj <= length(start_all)` bound, so MATLAB dies with "
                        "an out-of-bound index here.")
            if jjj == n_blocks:
                eof_flag = True

            start = int(start_all[jjj - 1])
            count = int(count_all[jjj - 1])
            jjj = min(jjj + 1, n_blocks)

            def gv(name, s=start, c=count):
                return f.get_var(vid[name], s, c).reshape(-1)

            (auto_reject, im_width, im_length, area, perimeter, habit1, centerin,
             entirein, aspect_ratio, aspect_ratio1, particle_diameter_AreaR,
             time_in_seconds, rec_nums, dof_overload) = _read_block(
                gv, i, old_style, i_create_aspect_ratio, cfg.probetype,
                total_pc1, total_pc2)

            int_arr, int_arr2, int_arr3 = _interarrival(
                f, vid, start, count, start_all_max, time_in_seconds, cfg.probetype,
                res, tas_max, reaccpt_shatrs)

            auto_reject[int_arr < 0] = ord("I")
            int_arr[int_arr < 0] = 0

            (particle_diameter_minR, area, particle_mass, calcd_area, particle_massbl,
             area_ratio, particle_vt, particle_pr, good_particles, bad_particles,
             image_time) = _diameters_and_mass(
                gv=gv, i=i, start=start, count=count, cfg=cfg, d_choice=d_choice,
                diodesize=diodesize, old_style=old_style, im_length=im_length,
                im_width=im_width, area=area, perimeter=perimeter, habit1=habit1,
                centerin=centerin, entirein=entirein, rec_nums=rec_nums,
                dof_overload=dof_overload, auto_reject=auto_reject, int_arr=int_arr,
                int_arr2=int_arr2, int_arr3=int_arr3,
                image_time_hhmmssall=image_time_hhmmssall, tas=tas, tas_max=tas_max,
                pres=pres, temp=temp, mmethod=mmethod, mmethod_pow=mmethod_pow,
                i_new_habit=i_new_habit, ia_thresh_type=ia_thresh_type,
                apply_int_arr_thresh=apply_int_arr_thresh, spec=spec, sa_method=sa_method,
                one_sec_times=one_sec_times, time_interval72=time_interval72,
                time_interval2=time_interval2, good_partpercent=good_partpercent,
                reject_by_criterion=reject_by_criterion,
                total_one_sec_locs=total_one_sec_locs, area_ratio_z=area_ratio_z,
                intar_threshold=intar_threshold)

            for which, mask, store in (("good", good_particles, good),
                                       ("bad", bad_particles, bad)):
                if which == "bad" and not i_create_bad:
                    continue
                empty = _process_population(
                    i, mask, entirein, image_time, one_sec_times, kk, num_bins,
                    binwidth, particle_diameter_minR, particle_diameter_AreaR,
                    habit1, area, perimeter, area_ratio, particle_mass,
                    calcd_area, particle_massbl, particle_vt, particle_pr,
                    store, octave_mean_extra, aspect_ratio, aspect_ratio1,
                )
                if empty and which == "good":
                    time_interval2[i] = 1
                    time_interval72[i] = 0
                    total_pc1[i] = 1
                    total_pc2[i] = 1
        else:
            # v3.5 :1848-1875 (unchanged from v3.1.4) names ONLY good-side
            # variables in this branch -- no `bad_*` array is touched at all.
            # A second that never gets a real particle block therefore leaves
            # every `bad_*` accumulator at its own pre-allocation (NaN, except
            # `bad_one_sec_ar`'s own zero -- see the `bad` dict above,
            # the uncorrected no-crossover particle time). Looping over `(good, bad)`
            # symmetrically here, as a naive port would, measurably disagrees with
            # real Octave on `REJ_ar` alone.
            for store in (good,):
                store["dist_minR"][i, :] = np.nan
                store["dist_AreaR"][i, :] = np.nan
                store["area_dist2"][i, :, :] = np.nan
                store["partarea"][i, :] = np.nan
                store["iwc"][i, :] = np.nan
                store["iwcbl"][i, :] = np.nan
                store["vt"][i, :] = np.nan
                store["pr"][i, :] = np.nan
                store["re"][i] = np.nan
                store["habitsd"][i, :, :] = np.nan
                store["habitmsd"][i, :, :] = np.nan
                store["one_sec_ar"][i] = np.nan
            good_partpercent[i] = 1
            reject_by_criterion[i, :] = np.nan
            time_interval2[i] = 1
            time_interval72[i] = 0
            total_pc1[i] = 1
            total_pc2[i] = 1

    # -- sample volume and normalisation (unchanged by the diff) -----------
    cip2_binmin = kk[:-1]
    cip2_binmax = kk[1:]
    cip2_binmid = (cip2_binmin + cip2_binmax) / 2
    cip2_bindD = np.diff(kk)

    sa2 = np.asarray(calc_sa_randombins(cip2_binmid, res, cfg.armdst,
                                        cfg.num_diodes, sa_method,
                                        cfg.probetype)).reshape(-1)

    # `:1931-1948` -- how the per-second live-time fraction is derived differs
    # by probetype. Probetype 2 (and 0/3) use 1 - dead time; probetype 1 uses
    # the RATIO of images kept to particles the probe itself counted, which is
    # a different quantity entirely.
    if cfg.probetype == 1:
        # `:1934` -- TotalPC2 is a 16-bit probe counter read as signed, so a
        # wrapped count comes back negative; += 2^16 unwraps it.
        total_pc2 = total_pc2.copy()
        total_pc2[total_pc2 < 0] += 2 ** 16
        # `:1938` -- images we have / particles the probe counted.
        time_interval199 = total_pc1 / total_pc2
        # `:1950-1958` -- "Experimental - Use with care!". During PECAN the
        # image count ran up to TWICE the probe's own particle count, which
        # would inflate concentration; every ratio above 1 is pinned to 1.
        # The clamp is applied for EVERY campaign, not just PECAN, because
        # `:1950`'s gate is `probetype==1` alone. Preserved.
        time_interval200 = time_interval199.copy()
        n_exceeded = int(np.count_nonzero(time_interval199 > 1))
        time_interval200[time_interval199 > 1] = 1.0
        _logger.warning(
            "Total image count exceeded probe particle count %d times; "
            "time_interval200 was set to 1 in these cases.", n_exceeded,
        )
    else:
        time_interval200 = 1 - time_interval72   # `:1932` probetype 2 (and 0/3)

    # v3.5 :1959-1971 (Finlon 02/26/18): a NaN TAS takes the last valid TAS
    # before it, or 100 m/s when there is none. Placed where v3.5 places it --
    # after the per-second loop, so it reaches only the sample volume below;
    # the loop's `tas(i) > tasMax` (:1144) saw the NaN. A copy, because the
    # caller's array is not MATLAB's pass-by-value `tas`. Absent from this port
    # before V35, which wrote a NaN sample volume there; measured under
    # Octave on the unmodified v3.5 source, case `nantas`. Applies to every
    # probetype: :1959 is outside the :1931-1958 probetype split.
    tas = tas.copy()
    for k in np.flatnonzero(np.isnan(tas)):
        prev = tas[:k]
        prev = prev[~np.isnan(prev)]
        tas[k] = prev[-1] if prev.size else 100.0
    # (:1972-1973's "Found %d instances..." fprintf is stdout only; not reproduced.)

    svol2 =(sa2[:, None] * (1e-3) ** 2) * time_interval200[None, :]
    svol2 = svol2 * tas[None, :]
    svol2 = svol2 * 100 ** 3
    # Default-on correction: a 1 s overload gives time_interval200 = 0 (:1121-1123, :1932),
    # so every concentration below is count/0 = Inf. Opt-in here (the Octave goldens run stock);
    # the driver passes zero_sv_nan=True by default on this engine. NaN divisor -> NaN conc;
    # sample_vol itself is written unchanged.
    svol_div = svol2
    zero_sv_seconds = 0
    if zero_sv_nan:
        bad = ~(svol2 > 0)
        zero_sv_seconds = int(bad.any(axis=0).sum())
        svol_div = np.where(bad, np.nan, svol2)
    svol2_t = svol_div.T
    svol2a = np.repeat(svol2_t[:, :, None], 10, axis=2)

    out = {}
    unwritten = {}
    for which, store in (("", good), ("REJ_", bad)):
        if which == "REJ_" and not i_create_bad:
            continue
        with np.errstate(divide="ignore", invalid="ignore"):
            conc_minR = store["dist_minR"] / svol2_t
            out[which + "conc_minR"] = conc_minR.T
            out[which + "conc_AreaR"] = (store["dist_AreaR"] / svol2_t).T
            out[which + "total_area"] = (store["area"] / svol2_t).T
            out[which + "Calcd_area"] = (store["partarea"] / svol2_t).T
            out[which + "mass"] = (store["iwc"] / svol2_t).T
            out[which + "massBL"] = (store["iwcbl"] / svol2_t).T
            out[which + "vt"] = (store["vt"] / svol2_t).T
            out[which + "Prec_rate"] = (store["pr"] / svol2_t).T
            out[which + "count"] = (store["dist_minR"] * binwidth[None, :] / 10).T
            out[which + "area"] = np.transpose(store["area_dist2"] / svol2a, (2, 1, 0))
            out[which + "habitsd"] = np.transpose(store["habitsd"] / svol2a, (2, 1, 0))
            out[which + "habitmsd"] = np.transpose(store["habitmsd"] / svol2a, (2, 1, 0))
            out[which + "n"] = nansum(conc_minR * binwidth[None, :], 2) / 10
        out[which + "re"] = store["re"]
        out[which + "ar"] = store["one_sec_ar"]
        out[which + "mean_perimeter"] = store["meanp"].T
        # v3.5 fix (the fixed area-ratio double scaling): these three (and their REJ_ twins) are now
        # written WITH the transpose every sibling variable already carries.
        # v3.1.4's own port names their absence a defect (its `NOT_TRANSPOSED`
        # set); v3.5 no longer has it, so this port must not "preserve" it.
        out[which + "mean_area_ratio"] = store["areaRatio1"].T
        if i_create_aspect_ratio:
            out[which + "mean_aspect_ratio_rectangle"] = store["aspectRatio"].T
            out[which + "mean_aspect_ratio_ellipse"] = store["aspectRatio1"].T
        unwritten[which + "lwc"] = _lwc.lwc_calc(conc_minR, cip2_binmid)

    if i_create_bad:
        for name in ("mean_aspect_ratio_rectangle", "mean_aspect_ratio_ellipse"):
            out.setdefault("REJ_" + name, np.full((n_sec, num_bins), np.nan).T)

    out["time"] = timehhmmss
    out["bin_min"] = cip2_binmin
    out["bin_max"] = cip2_binmax
    out["bin_mid"] = cip2_binmid
    out["bin_dD"] = cip2_bindD
    out["Reject_ratio"] = 1 - good_partpercent
    out["sum_IntArr"] = time_interval200
    out["sample_vol"] = svol2

    iat_threshold = None
    if spec.iat_thresh is not None:
        iat_threshold = np.asarray(spec.iat_thresh, dtype=np.float64)
        out["iat_threshold"] = iat_threshold

    _write_v35(
        mainf, out, num_bins, n_sec, infile, projectname, probename, sa_method,
        d_choice, apply_int_arr_thresh, reaccpt_shatrs, cfg, i_create_bad,
        i_create_aspect_ratio, i_save_int_arr_sv, attr_habit, iat_threshold,
        software, creation_time, stamp_profile, tas_qc, area_ratio_z=area_ratio_z,
        default_int_arr_thresh=default_int_arr_thresh, time_offset=time_offset,
    )
    out["_unwritten"] = unwritten
    out["_zero_sv_seconds"] = zero_sv_seconds
    out["_reject_by_criterion"] = reject_by_criterion
    out["_total_one_sec_locs"] = total_one_sec_locs
    out["_time_interval2"] = time_interval2
    out["_TotalPC1"] = total_pc1
    out["_TotalPC2"] = total_pc2
    return out


def fix_time_grid(timehhmmss):
    """Default-on v3.5 correction for the duplicated-and-skipped seconds of the S4 time vector.

    ``read_binary_SPEC.m:301-302`` writes each primary record's header time, and S4 floors it
    (``run_flight``'s ``np.floor(timehhmmss)``); clock jitter floors two records to the same
    second and skips the next, so second *t* appears twice and *t + 1* never.
    Minimal correction: a duplicate whose immediate successor gap is exactly two seconds moves
    up into the skipped second; failing that, its partner moves down when the gap before it is
    exactly two seconds. A duplicate with no single-second hole beside it is left as it is, so
    no row is invented and no particle is reassigned by more than one second. Midnight is
    unwrapped before the pass and rewrapped after. Returns ``(fixed HHMMSS float array,
    n_moved)``; the input is not modified.
    """
    t = np.asarray(timehhmmss, dtype=float)
    hh, rem = np.divmod(t, 10000)
    mm, ss = np.divmod(rem, 100)
    sec = hh * 3600 + mm * 60 + ss
    if sec.size > 1:
        sec = sec + 86400 * np.concatenate(([0], np.cumsum(np.diff(sec) < -43200)))
    sec = sec.copy()
    n = sec.size
    moved = 0
    for i in range(1, n):
        if sec[i] != sec[i - 1]:
            continue
        if (i + 1 >= n or sec[i + 1] - sec[i] == 2) and i + 1 < n:
            sec[i] += 1
            moved += 1
        elif i - 2 >= 0 and sec[i - 1] - sec[i - 2] == 2:
            sec[i - 1] -= 1
            moved += 1
    sec = np.mod(sec, 86400)
    h, r = np.divmod(sec, 3600)
    m, s_ = np.divmod(r, 60)
    return h * 10000 + m * 100 + s_, moved


def count_duplicate_seconds(timehhmmss):
    """Rows of ``timehhmmss`` (floored to whole seconds) equal to their predecessor: the
    duplicates :func:`fix_time_grid` left unresolved because no single-second hole sat beside
    them (back-to-back repeats). Counted and stamped, never moved."""
    t = np.floor(np.asarray(timehhmmss, dtype=float).reshape(-1))
    return int(np.count_nonzero(t[1:] == t[:-1])) if t.size > 1 else 0
