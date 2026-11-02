# SPDX-License-Identifier: BSD-3-Clause
"""Every setting a user can change for the v3.5 engine, and whether it reaches the output.

One row per setting in :data:`SETTINGS`.  Each row says what the setting does, its default, where
it is set, whether ``--engine 3.5`` accepts it, and -- through :meth:`Setting.effect` -- whether it
has any effect on a given probe case.  Every default and location is cited to a ``file:line`` and
the substring that line holds (:class:`Cite`); ``tests/test_tune_settings.py`` reads each one.

**Why the probe case and the run's iaThreshType matter.**  The shattering (inter-arrival)
settings act only when the probe case's ``applyIntArrThresh`` is 1 *and* the run's
``iaThreshType`` is not 0.  ``arrayprobe_uiops.sizedist.apply_shattering`` returns before any test
when ``iaThreshType`` is 0 (``sizedist.py:625``, mirroring ``sizeDist.m``'s
``if iaThreshType==1``/``==2``/``==3`` branches), and inside each branch when the gate is 0
(``:634``, ``:657``, ``:692``).  Engine 3.5 runs with ``iaThreshType`` 0 unless a threshold file
(type 1) or ``[shattering].ia_thresh_type = 2`` is given, so on a gate-on case the default run
still changes no particle.  ``defaultIntArrThresh`` is read only by type 2 (``sizeDist.m:520``);
type 1 reads the file's thresholds instead.  The shipped 2D-S case ``v35-2ds-ladder-fix`` (the
case the batch driver applies by default to a 2D-S on engine 3.5) takes v3.5's
``otherwise``/``'2DS'`` record, whose gate is 0 (``sizeDist.m:514``), so a threshold file is
accepted and stamped there and changes no particle.

**Where values come from.**  ``TOML`` is a run-file key (``arrayprobe run run.toml``), ``CLI`` a
``scripts/run_flight.py`` flag (source ``arrayprobe.driver.run_flight``), ``authordefaults`` the
``[fidelity].authordefaults`` cited-overrides file, ``profile`` a registered ``FidelityProfile``,
``probe case`` a registered ``arrayprobe_uiops.probe_cases.ProbeCase`` (Python only), ``preset`` the
required ``--preset``.

Importing this module loads nothing from the v3.5 engine; :func:`resolve_probe_defaults` imports it
only when called.
"""

from __future__ import annotations

import dataclasses
import importlib
from typing import Any

__all__ = [
    "Cite",
    "Effect",
    "Setting",
    "SETTINGS",
    "settings_by_name",
    "resolve_probe_defaults",
]

#: Vendored v3.5 sources and the port's files, relative to the repository root.
_V35 = "UIOPS-v3.5/joefinlon-UIOPS-039be82"
_SIZEDIST_M = f"{_V35}/sizeDist.m"
_REJECT_M = f"{_V35}/calculate_reject_unified.m"
_RUN_FLIGHT = "src/arrayprobe/driver/run_flight.py"
_CONFIG = "src/arrayprobe/config.py"
_REGIMES = "src/arrayprobe/regimes.py"
#: RejectConfig's defaults live in the v3.5 engine and v3.1.4 imports them (one copy).
_REJECT_PY = "src/arrayprobe_uiops/reject_core.py"
_AUTHORDEFAULTS = "src/arrayprobe/authordefaults.py"
_V35_SIZEDIST = "src/arrayprobe_uiops/sizedist.py"
_V35_PROFILE = "src/arrayprobe_uiops/profile.py"
_PROBE_CASES = "src/arrayprobe_uiops/probe_cases.py"
_PARITY_TEST = "tests/test_engine_flag_parity.py"

ACCEPTED = "accepted"
REFUSED = "refused (exit 2)"


@dataclasses.dataclass(frozen=True)
class Cite:
    """``path:line`` (repository-relative, 1-based) and a substring that line contains."""

    path: str
    line: int
    contains: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}"


@dataclasses.dataclass(frozen=True)
class Effect:
    """Whether a setting changes the output on one probe case, and why."""

    effective: bool
    reason: str


_GATE_OFF = "no effect: the gate is off on this probe case (applyIntArrThresh = 0)"
_TYPE_0 = "no effect: iaThreshType 0, the default for engine 3.5 without a threshold file"
_TYPE_UNREAD = "no effect: iaThreshType {t} does not read it"
_ACTS = "acts: the gate is on (applyIntArrThresh = 1) and iaThreshType is {t}"
_REFUSED_35 = "no effect: engine 3.5 refuses it (exit 2)"
_UNGATED = "effect: not gated by the probe case"


@dataclasses.dataclass(frozen=True)
class Setting:
    """One row of :data:`SETTINGS`."""

    name: str
    does: str
    default: str
    where: tuple[str, ...]
    engine_35: str
    cites: tuple[Cite, ...]
    shattering_gated: bool = False
    #: The iaThreshType values whose branch reads this setting (shattering rows only).
    read_by_ia_thresh_types: tuple[int, ...] = (1, 2, 3)
    #: The iaThreshType that setting this row selects (the threshold file selects 1).
    selects_ia_thresh_type: int | None = None

    def effect(self, probe_case: Any, ia_thresh_type: int = 0) -> Effect:
        """Whether this setting changes the v3.5 output on ``probe_case``.

        ``probe_case`` is a registered case name (``"v35-2ds-ladder-fix"``), an
        ``arrayprobe_uiops.probe_cases.ProbeCase`` or an
        ``arrayprobe_uiops.sizedist_tables.ProbeDefaults``
        (what ``probe_defaults(project, probe)`` returns for a campaign's own case).
        ``ia_thresh_type`` is the run's ``iaThreshType``; 0, the default, is what engine 3.5
        runs without a threshold file or ``[shattering].ia_thresh_type``.
        """
        if self.engine_35 != ACCEPTED:
            return Effect(False, _REFUSED_35)
        if not self.shattering_gated:
            return Effect(True, _UNGATED)
        if ia_thresh_type not in (0, 1, 2, 3):
            raise ValueError(f"iaThreshType is 0, 1, 2 or 3; got {ia_thresh_type!r}")
        if not resolve_probe_defaults(probe_case).applyIntArrThresh:
            return Effect(False, _GATE_OFF)
        t = self.selects_ia_thresh_type
        if t is None:
            t = ia_thresh_type
        if t == 0:
            return Effect(False, _TYPE_0)
        if t not in self.read_by_ia_thresh_types:
            return Effect(False, _TYPE_UNREAD.format(t=t))
        return Effect(True, _ACTS.format(t=t))


def resolve_probe_defaults(probe_case: Any) -> Any:
    """The ``ProbeDefaults`` record behind ``probe_case`` (see :meth:`Setting.effect`)."""
    from arrayprobe_uiops import probe_cases
    from arrayprobe_uiops.sizedist_tables import ProbeDefaults

    if isinstance(probe_case, ProbeDefaults):
        return probe_case
    if isinstance(probe_case, probe_cases.ProbeCase):
        return probe_case.defaults
    if isinstance(probe_case, str):
        # Development-tree cases registered by modules a distribution may not carry.
        dev_cases = {"arm-ena-2ds": "arrayprobe_uiops.register_arm_ena_2ds",
                     "arm-ena-2ds-cold": "arrayprobe_uiops.register_arm_ena_2ds_cold"}
        if probe_case in dev_cases and probe_case not in probe_cases.PROBE_CASES:
            try:
                importlib.import_module(dev_cases[probe_case])
            except ModuleNotFoundError:
                # A distribution without the ARM ENA registration modules: fall through,
                # so the name is refused as any unregistered case is.
                pass
        # The shipped case registers on first use, as in the batch driver's preflight.
        return probe_cases.resolve_shipped_probe_case(probe_case).defaults
    raise TypeError(
        f"probe_case must be a registered name, a ProbeCase or a ProbeDefaults; got {probe_case!r}"
    )


_PRESET_WHERE = ("preset (CLI --preset, required)",)
_PROBE_WHERE = ("probe case (register_probe_case, Python only; selected by CLI --probe-case)",)
_REJECT_WHERE = ("profile reject_thresholds (register_profile, Python only)",
                 "authordefaults ([fidelity].authordefaults file)")
_PROFILE_KEYS = Cite(_CONFIG, 223, '"fidelity": {"profile", "profile_module", "authordefaults"}')
_AD_KEYS = Cite(_AUTHORDEFAULTS, 70, "THRESHOLD_KEYS")


def _reject(name: str, does: str, default: str, m_line: int, m_text: str, py_line: int,
            py_text: str, prof_line: int) -> Setting:
    return Setting(
        name=name, does=does, default=default, where=_REJECT_WHERE, engine_35=ACCEPTED,
        cites=(Cite(_REJECT_M, m_line, m_text), Cite(_REJECT_PY, py_line, py_text),
               Cite(_V35_PROFILE, prof_line, f"reject_thresholds.{name}"), _PROFILE_KEYS,
               _AD_KEYS),
    )


SETTINGS: tuple[Setting, ...] = (
    # --- the size-distribution stage's own thresholds -------------------------------------
    Setting(
        name="area_ratio_z",
        does="Rejects a particle (reject code 'z') whose area ratio is below this value.",
        default="0.2",
        where=("TOML [thresholds].area_ratio_z", "CLI --area-ratio-z"),
        engine_35=ACCEPTED,
        cites=(Cite(_SIZEDIST_M, 1162, "area_ratio < .2"),
               Cite(_RUN_FLIGHT, 7156, '"--area-ratio-z"'),
               Cite(_CONFIG, 85, "area_ratio_z"),
               Cite(_V35_SIZEDIST, 1015, "area_ratio_z=None")),
    ),
    Setting(
        name="regime",
        does="Names a bundle of the area-ratio gate and the shattering threshold.",
        default="none",
        where=("TOML [thresholds].regime", "CLI --regime"),
        engine_35=ACCEPTED,
        cites=(Cite(_RUN_FLIGHT, 7143, '"--regime"'),
               Cite(_CONFIG, 84, 'regime = "ice"'),
               Cite(_REGIMES, 123, "area_ratio_z: float"),
               Cite(_REGIMES, 125, "default_int_arr_thresh: float"),
               Cite(_RUN_FLIGHT, 1421, "def _v35_s4_thresholds"),
               Cite(_PARITY_TEST, 280, "test_regime_is_accepted_under_engine_35")),
    ),
    Setting(
        name="default_int_arr_thresh (driver override)",
        does="Replaces the probe case's shattering threshold with a raw value.",
        default="none (the probe case's defaultIntArrThresh)",
        where=("TOML [thresholds].default_int_arr_thresh", "CLI --default-int-arr-thresh"),
        engine_35=ACCEPTED,
        cites=(Cite(_RUN_FLIGHT, 7168, '"--default-int-arr-thresh"'),
               Cite(_CONFIG, 86, "default_int_arr_thresh"),
               Cite(_V35_SIZEDIST, 1016, "default_int_arr_thresh=None"),
               Cite(_RUN_FLIGHT, 1421, "def _v35_s4_thresholds"),
               Cite(_PARITY_TEST, 330, "test_default_int_arr_thresh_is_accepted_under_engine_35")),
        # sizedist.run's docstring: read only by the iaThreshType == 2 && applyIntArrThresh block.
        shattering_gated=True,
        read_by_ia_thresh_types=(2,),
    ),
    # --- shattering: the threshold file and the probe case's constants ---------------------
    Setting(
        name="shattering threshold file",
        does=("Names a per-time inter-arrival threshold file (sizeDist's iaThreshFile); with one, "
              "the run uses iaThreshType 1, without one iaThreshType 0 (or 2, when "
              "[shattering].ia_thresh_type = 2)."),
        default="none under engine 3.5 (iaThreshType 0)",
        where=("TOML [shattering].threshold_file", "CLI --iat-file"),
        engine_35=ACCEPTED,
        cites=(Cite(_RUN_FLIGHT, 6926, '"--iat-file"'),
               Cite(_CONFIG, 58, "threshold_file"),
               Cite(_RUN_FLIGHT, 5686,
                    'engine == "3.5" and cfg.shattering_threshold_file is None'),
               Cite(_RUN_FLIGHT, 1801, "derived per run from ``--iat-file``"),
               Cite(_SIZEDIST_M, 99, "if iaThreshType==1"),
               Cite(_V35_SIZEDIST, 745, "cfg.applyIntArrThresh")),
        shattering_gated=True,
        read_by_ia_thresh_types=(1,),
        selects_ia_thresh_type=1,
    ),
    Setting(
        name="applyIntArrThresh",
        does="Turns the shattering (inter-arrival) rejection on or off for the probe case.",
        default="per probe case; v35-2ds-ladder-fix: 0 (off)",
        where=_PROBE_WHERE,
        engine_35=ACCEPTED,
        cites=(Cite(_SIZEDIST_M, 514, "applyIntArrThresh = 0"),
               Cite(_V35_SIZEDIST, 1528, "apply_int_arr_thresh = cfg.applyIntArrThresh"),
               Cite(_PROBE_CASES, 139, "def register_probe_case"),
               Cite(_RUN_FLIGHT, 7101, '"--probe-case"')),
    ),
    Setting(
        name="defaultIntArrThresh",
        does="Inter-arrival time (s) below which a particle is rejected as a shattering fragment.",
        default="per probe case; v35-2ds-ladder-fix: 4e-6 s",
        where=_PROBE_WHERE,
        engine_35=ACCEPTED,
        cites=(Cite(_SIZEDIST_M, 515, "defaultIntArrThresh = 4e-6"),
               Cite(_SIZEDIST_M, 520, "intar_threshold = ones(size(tas_time))*defaultIntArrThresh"),
               Cite(_V35_SIZEDIST, 771, "if not cfg.applyIntArrThresh")),
        shattering_gated=True,
        read_by_ia_thresh_types=(2,),
    ),
    Setting(
        name="reaccptShatrs",
        does="Re-accepts particles the shattering test rejected, by the two limits below.",
        default="per probe case; v35-2ds-ladder-fix: 0 (off)",
        where=_PROBE_WHERE,
        engine_35=ACCEPTED,
        cites=(Cite(_SIZEDIST_M, 516, "reaccptShatrs = 0"),
               Cite(_V35_SIZEDIST, 932, "if apply_int_arr_thresh and reaccpt_shatrs")),
        shattering_gated=True,
    ),
    Setting(
        name="reaccptD",
        does="Minimum size (mm) of a shattering-rejected particle that may be re-accepted.",
        default="per probe case; v35-2ds-ladder-fix: 0.5",
        where=_PROBE_WHERE,
        engine_35=ACCEPTED,
        cites=(Cite(_SIZEDIST_M, 517, "reaccptD = 0.5"),
               Cite(_V35_SIZEDIST, 932, "if apply_int_arr_thresh and reaccpt_shatrs")),
        shattering_gated=True,
    ),
    Setting(
        name="reaccptMaxIA",
        does="Maximum inter-arrival time (s) for a shattering-rejected particle to be re-accepted.",
        default="per probe case; v35-2ds-ladder-fix: 1e-6 s",
        where=_PROBE_WHERE,
        engine_35=ACCEPTED,
        cites=(Cite(_SIZEDIST_M, 518, "reaccptMaxIA = 1e-6"),
               Cite(_V35_SIZEDIST, 932, "if apply_int_arr_thresh and reaccpt_shatrs")),
        shattering_gated=True,
    ),
    # --- the six image-stage reject thresholds ---------------------------------------------
    _reject("rej_zero_area", "Rejects a particle with zero area.", "1 (on)",
            60, "handles.rej_zero_area = 1", 47, "rej_zero_area: bool = True", 59),
    _reject("rej_split", "Rejects a particle split into separate pieces.", "1 (on)",
            61, "handles.rej_split = 1", 53, "rej_split: bool = True", 61),
    _reject("rej_hollow", "Rejects a hollow (out-of-focus drop) image.", "1 (on)",
            62, "handles.rej_hollow = 1", 56, "rej_hollow: bool = True", 63),
    _reject("shadowed_area",
            "Rejects a particle (code 'p') shadowing less than this percentage of its bounding "
            "rectangle.", "25",
            64, "handles.shadowed_area = 25", 60, "shadowed_area: float = 25", 65),
    _reject("max_edge_img_ar",
            "Aspect-ratio ceiling for a particle touching the array edge.", "6",
            65, "handles.max_edge_img_ar = 6", 65, "max_edge_img_ar: float = 6", 67),
    _reject("max_comp_img_ar",
            "Aspect-ratio ceiling (code 'a') for a particle wholly inside the array.", "5",
            66, "handles.max_comp_img_ar = 5", 71, "max_comp_img_ar: float = 5", 69),
    # --- the preset: sizeDist's call arguments ---------------------------------------------
    Setting(
        name="d_choice",
        does="Chooses which particle dimension is used as its size.",
        default="set by the preset (ORACLES_2016_2DS_H: 6, the minimum enclosing circle)",
        where=_PRESET_WHERE,
        engine_35=ACCEPTED,
        cites=(Cite(_SIZEDIST_M, 90, "d_choice"), Cite(_RUN_FLIGHT, 191, "d_choice: int"),
               Cite(_RUN_FLIGHT, 203, "d_choice=6")),
    ),
    Setting(
        name="SAmethod",
        does="Chooses the sample-area method.",
        default="set by the preset (ORACLES_2016_2DS_H: 0, centre-in)",
        where=_PRESET_WHERE,
        engine_35=ACCEPTED,
        cites=(Cite(_SIZEDIST_M, 90, "SAmethod"), Cite(_RUN_FLIGHT, 192, "sa_method: int"),
               Cite(_RUN_FLIGHT, 204, "sa_method=0")),
    ),
    Setting(
        name="Pres",
        does="Static pressure (Pa) passed to sizeDist.",
        default="set by the preset",
        where=_PRESET_WHERE,
        engine_35=ACCEPTED,
        cites=(Cite(_SIZEDIST_M, 90, "Pres"), Cite(_RUN_FLIGHT, 193, "pres_pa: float")),
    ),
    Setting(
        name="Temp",
        does="Temperature (C) passed to sizeDist.",
        default="set by the preset",
        where=_PRESET_WHERE,
        engine_35=ACCEPTED,
        cites=(Cite(_SIZEDIST_M, 90, "Temp"), Cite(_RUN_FLIGHT, 194, "temp_c: float")),
    ),
)


def settings_by_name() -> dict[str, Setting]:
    """:data:`SETTINGS` keyed by row name."""
    return {s.name: s for s in SETTINGS}
