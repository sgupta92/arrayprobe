# SPDX-License-Identifier: BSD-3-Clause
"""A run configuration file (TOML) -- selection only, never a silent default.

Decision #10 (2026-08-28): the loader lives in the core, but it can only *select* -- a named
``FidelityProfile``, per-file diode masks, the explicit shattering-threshold argument, export
options, and opt-in enhancement switches that the core does not interpret.  It cannot set a
threshold on the port; a fidelity-changing key outside ``[fidelity]`` is rejected at load time.
Design: ``enhancements_uiops/docs/config_file_design.md``.

**The no-raw-thresholds rule is lifted for exactly two fields (configurable thresholds):**
``[thresholds].area_ratio_z`` and ``[thresholds].default_int_arr_thresh`` -- the S4 (``sizeDist``)
threshold pair that was found arriving unnamed for any project ``constants.sizedist_config``
does not recognise (measured: an unrecognised project under ``tree="production"`` gets ORACLES's
own tuned values with no record of why). Everywhere else the rule stands: a raw
``rej_hollow``, ``max_edge_img_ar``, ``max_comp_img_ar``, ``spec_buffer_guard``, ``hvps_reader`` or
``zero_image_particle_recovery`` anywhere in the file is still refused (:data:`_FORBIDDEN`), because
those remain scientific claims that belong in code with provenance
(:class:`~arrayprobe.profiles.FidelityProfile`).

``[thresholds]`` may name a :data:`~arrayprobe.regimes.REGIMES` entry (``regime = "liquid-warm"``),
or give a raw value for either field, or both at once -- a regime for one field and a raw override
for the other is normal and expected.  A raw value here is validated (``arrayprobe.regimes``) and
recorded in ``RunConfig`` tagged ``"user:<config path>"``, distinct from a regime's
``"regime:<name>"`` tag and the historical hard-coded ``"stock"`` fallback -- three different
epistemic objects, and the ``.call`` sidecar and the startup print both keep them apart (see
``scripts/run_flight.py``). **A value here is a property of one run, never of the package**: the
package's own registered regimes (:data:`arrayprobe.regimes.REGIMES`) are the only names a fork may
add to permanently, through :func:`arrayprobe.regimes.register_regime` -- the same shape as a
:class:`~arrayprobe.profiles.FidelityProfile`.

Every fidelity-sensitive key is **required** when its section is present, and the file's absence
changes nothing: callers that do not use a config keep passing the profile explicitly.

A fork's own registered profile (``register_profile()``) is selected the same way once its
registration is *reachable*: ``[fidelity].profile_module`` names a Python module to import before
the profile is resolved, so a fresh process -- including every ``--jobs``/``--chunks`` worker
``run_flight.py`` re-execs, each a brand-new interpreter that has never run the fork's own
registration code -- can still find it by name. The module still only *selects*: importing it must
call ``register_profile()``, itself constrained to a fully-specified :class:`FidelityProfile`
exactly as if called directly, never described as data in this file.

``[fidelity].authordefaults`` (minimal form) is the third way to reach a profile,
mutually exclusive with ``profile``: it names a separate, content-hashed TOML file
(:mod:`arrayprobe.authordefaults`) that states a base profile plus cited overrides for the six
:class:`~arrayprobe_uiops.reject_core.RejectConfig` thresholds only. The loader here still only
*selects* --
the generated profile is built and registered the same way a fork's own variant would be, this
file just supplies six of its field values instead of them being typed by hand. Absent, nothing
about this loader's behaviour changes.

Example::

    [fidelity]
    profile = "ORACLES_PRODUCTION"
    # profile_module = "my_lab.profiles"   # only if profile names something it registers

    [shattering]
    threshold_file = "2DS_intArrThreshold_MISSING.cdf"   # explicit: the twelfth argument

    [masking]
    diodes = { base160910124240 = [95], base160910071623 = [77] }

    [export]
    format = "NETCDF3_CLASSIC"

    [enhancements]
    last_record_fix = true

    [run]
    engine = "3.1.4"                   # "3.5" for new data, "3.1.4" to reproduce an archived
                                       # product (as this ORACLES example does), or "soda2"
    preset = "ORACLES_2016_2DS_H"      # a campaign chosen whole, by name (CampaignPreset)
    raw = ["../raw/base1609*.2DS"]     # relative to this file; command-line raw files win
    out = "../_decoded"
    stages = "234"
    tas_file = "../aircraft/flightData_160906.cdf"   # only if profile.time_in_seconds_from_tas
    # probe = "CIP"                    # optional: must be the preset's probe, or the run is refused
    # tas_from_probe = ["../2ds/base160906*.tas.csv"]   # CIP/PIP only: another probe's airspeed

    [combine]
    borrowed = true    # engine 3.5 only: stitch with the ORACLES fork's combine, labelled borrowed

    [thresholds]
    regime = "ice"              # optional: one of arrayprobe.regimes.REGIMES
    area_ratio_z = 0.35         # optional: raw override, allowed for this field only
    default_int_arr_thresh = 5e-6   # optional: raw override, same lift
    # tas_max = 140.0           # 2DP only (it assigns no tasMax): the probe's own value, m/s
    # pecan_params = "pecan_spirals.csv"   # PECAN CIP/PIP only: stands in for getPECANparams

    [arm]
    site_id = "ena"              # required together: real, already-assigned ARM codes,
    platform_id = "aaf2dsh"      # never invented -- see _load_arm's own docstring
    facility_id = "F1"
    # data_level = "c1"          # optional: defaults to arm_export.export()'s own "c1"

    [tas]
    source = "auto"                              # or "merge" / "aircraft" / "probe" (pinned)
    search = ["../merge", "~/data/merge"]   # relative to this file; ~ expanded
    # cutoff_mps = 300.0         # optional: TasPolicy's cutoff (documented default 300 m/s)
    # default_mps = 170.0        # optional: TasPolicy's fallback (documented default 170 m/s)

    [time_offset]                # engine 3.5 only; all three together, or the section omitted
    seconds = -100               # whole seconds added to every particle time in sizeDist
    evidence = "SPEC clock vs aircraft TAS cross-correlation"   # how it was measured
    tas_clock = "probe"          # "probe" or "aircraft": which clock the time/TAS rows carry
"""

from __future__ import annotations

import importlib
import math
import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import profiles
from .authordefaults import AuthorDefaultsError, load_authordefaults, resolve_profile
from .profiles import FidelityProfile
from .regimes import ThresholdValidationError, resolve_thresholds
from .tools import tas_sources
from .tools.make_tas_file import TasPolicy

__all__ = ["RunConfig", "ConfigError", "PROFILES", "load_config"]

def _constant_spelling(name: str) -> str:
    """``"stock-v3.5"`` -> ``"STOCK_V35"``: a profile's own module-level constant name.

    One transform, not a table: ``profiles.py`` names every shipped profile twice
    -- once as a hyphenated ``name`` field and once as the Python constant bound to
    it -- and this is the rule relating them. ``tests/test_profile_registry.py``
    asserts the two sides against each other (``getattr(profiles, alias)`` is the
    object :data:`PROFILES` resolves that alias to), so the transform cannot quietly
    stop matching how ``profiles.py`` actually spells a constant.
    """
    return name.upper().replace("-", "_").replace(".", "")


#: The CONSTANT-style spellings config files have always used, kept because
#: written config files name them -- a config file may say
#: ``profile = "ORACLES_PRODUCTION"``. They are aliases *of* the registry
#: entries, resolved through it rather than bound to the objects here: this
#: table used to hold the three profiles directly, which made it a second copy
#: of a registry, keyed differently, that nothing compared with the first.
#:
#: **Derived from** :data:`arrayprobe.profiles.SHIPPED` **since 2026-09-20**, and
#: that is a fix, not a tidy-up. The table was hand-written with the three
#: v3.1.4-era profiles in it, so ``STOCK_V35`` -- the spelling
#: ``profiles.py`` and every Python caller use -- was **not an accepted config
#: value**, while ``ORACLES_PRODUCTION`` was, in the same file. A cold-user
#: end-to-end walk in September 2026 found exactly that. The registry two
#: lines below was made derived in September for the same reason
#: and this table was left behind: a fifth profile added to ``profiles.py``
#: joined ``PROFILES`` automatically and silently missed its alias. It cannot now.
_ALIASES: dict[str, str] = {_constant_spelling(n): n for n in sorted(profiles.SHIPPED)}


class _SelectableProfiles(Mapping[str, FidelityProfile]):
    """Every profile a config file may name: the aliases, and the registry.

    Computed on access rather than snapshotted at import, so a profile a fork
    registers with :func:`arrayprobe.profiles.register_profile` can be selected
    by name from a config file without this module having heard of it. It stays
    a *selection*: registering constructs the object in Python, where every
    divergence is named; the file only picks one that already exists.
    """

    def _resolved(self) -> dict[str, FidelityProfile]:
        table = {alias: profiles.PROFILES[target] for alias, target in _ALIASES.items()}
        table.update(profiles.PROFILES)
        return table

    def __getitem__(self, key: str) -> FidelityProfile:
        return self._resolved()[key]

    def __iter__(self):
        return iter(self._resolved())

    def __len__(self) -> int:
        return len(self._resolved())


PROFILES: Mapping[str, FidelityProfile] = _SelectableProfiles()

#: Keys that would change what the port computes if they were honoured outside a profile.
_FORBIDDEN = {"rej_hollow", "max_edge_img_ar", "max_comp_img_ar", "spec_buffer_guard",
              "area_ratio", "z_threshold", "defaultIntArrThresh", "iat_threshold",
              "zero_image_particle_recovery", "hvps_reader"}

_SECTIONS = {"fidelity", "shattering", "masking", "export", "enhancements", "combine", "run",
             "soda2", "thresholds", "v35", "arm", "tas", "outputs", "time_offset"}

#: What ``[thresholds]`` may hold -- the two fields exempt from the no-raw-thresholds rule,
#: plus the regime selector.  Nothing else: a raw ``area_ratio`` (the ``_FORBIDDEN`` spelling)
#: or any S3-level reject field is still refused there, same as everywhere else in the file.
_THRESHOLD_KEYS = {"regime", "area_ratio_z", "default_int_arr_thresh", "tas_max",
                   "pecan_params"}

#: What ``[combine]`` may hold: the one opt-in switch, and nothing else.
#:
#: Added 2026-09-20 after the cold-user walk measured a config carrying
#: ``[combine].totally_made_up_key`` running to ``ALL DONE``, exit 0, silently.
#: Every other table with a fixed key set
#: -- ``[run]``, ``[thresholds]``, ``[v35]`` -- already refuses an unknown key by
#: name; this one kept the remainder in :attr:`RunConfig.combine`, which no
#: consumer reads, so a typo'd ``borrowd = true`` was accepted, stored, and the
#: run stitched the way the file said it should not.
#:
#: ``tests/test_config_keys_are_consumed.py`` could not have caught it and says so
#: in its own LIMIT paragraph: it sweeps ``RunConfig`` *fields*, and the field
#: ``combine`` matches the unrelated ``arrayprobe_uiops.combine`` in a consumer's
#: source. A field-level sweep cannot see a key that never becomes a field.
_COMBINE_KEYS = {"borrowed"}

#: The keys the four remaining fixed-shape UIOOPS sections may hold -- the same refusal
#: ``[combine]`` got on 2026-09-20, extended 2026-09-26 after a cold-user walk measured
#: ``[masking.diode]`` (for ``diodes``), ``[export] formt = ...`` and ``[fidelity]
#: profle_module = ...`` all loading cleanly and being ignored: a typo'd mask section left
#: every diode unmasked while the file said otherwise.
_SECTION_KEYS = {
    "fidelity": {"profile", "profile_module", "authordefaults"},
    "shattering": {"threshold_file", "ia_thresh_type"},
    "masking": {"diodes"},
    "export": {"format"},
}

#: What ``[v35]`` may hold (iQC and iNewHabit configurable) --
#: ``arrayprobe_uiops.imgproc.imgproc_sm_v35``'s two required, no-MATLAB-default switches (its
#: own module docstring): which habit scheme (Holroyd vs. Schima et al. 2024) and whether
#: ``qc_image`` runs. Each is a documented state (0 or 1), never a raw threshold, so the
#: no-raw-thresholds rule does not apply here.
_V35_KEYS = {"iQC", "iNewHabit"}

#: What ``[arm]`` may hold -- the real ARM identifiers
#: ``arrayprobe_enhancements.arm_export.export()`` needs and its own docstring insists are
#: "never invented": ``site_id``/``platform_id``/``facility_id`` are required together, since a
#: two-of-three identifier is not a real ARM identifier either. ``data_level`` is optional --
#: ``export()``'s own default (``"c1"``) is a documented ARM data-level category
#: (DOE/SC-ARM-15-004 S5.1.3), not a site fact, so falling back to it is not a guess the way a
#: missing site/platform/facility id would be. This is a selection, not a description, exactly
#: like ``[v35]``: a config file supplies the user's own real, already-assigned ARM codes for
#: this deployment, it does not derive or compute one, so the no-raw-thresholds rule is not
#: being relaxed here.
_ARM_KEYS = {"site_id", "platform_id", "facility_id", "data_level"}
_ARM_REQUIRED_KEYS = ("site_id", "platform_id", "facility_id")

#: What ``[tas]`` may hold (merged-file airspeed for ORACLES, the non-ORACLES airspeed chain) --
#: the TAS source chain's own opt-in, config-file half of the requirement that the
#: user can select both in config so nothing is hard coded. ``source`` selects a
#: chain mode (:data:`arrayprobe.tools.tas_sources.MODES`: ``auto``, or one pinned tier);
#: ``search`` names the directories the chain's ``merge``/``aircraft`` tiers glob in (resolved
#: relative to this file); ``cutoff_mps``/``default_mps`` are
#: :class:`~arrayprobe.tools.make_tas_file.TasPolicy`'s pair, validated the same way that class
#: validates its own constructor arguments -- a config file selects a policy, it does not describe
#: one differently from how Python does.
_TAS_KEYS = {"source", "search", "cutoff_mps", "default_mps"}

#: What ``[time_offset]`` must hold -- engine 3.5's opt-in whole-second probe-clock offset
#: (``arrayprobe_uiops.sizedist.TimeOffset``), the file's spelling of ``run_flight.py``'s
#: ``--time-offset-s`` / ``--time-offset-evidence`` / ``--time-offset-tas-clock``. All three or
#: none: an offset without its evidence, or without saying which clock the TAS rows carry, is
#: refused by the engine, so it is refused here at load time too.
_TIME_OFFSET_KEYS = ("seconds", "evidence", "tas_clock")

#: What ``[outputs]`` may hold -- which of a run's
#: three artefacts it owes, selected from the file with an explicit opt-out. Only the
#: keys whose effect is built are accepted, so a file cannot name an output the driver would then
#: silently not write: ``faithful_attributed`` is ``--attributed``; ``enhanced_attributed`` is
#: ``--enhancements`` with stage ``c`` (the enhanced combined and its attributed export), refused
#: by the driver before any stage runs when the file names no enhancement to apply. ``arm =
#: "faithful"`` is an ARM-format copy of the port's own sd, which needs ``[arm]``; without it the
#: driver logs a named skip. ``analysis_ready`` (absent = true) writes OUTPUT 2 chunked and
#: compressed; ``false`` writes it plain. ``zarr`` (absent = false) adds an opt-in Zarr copy of
#: each attributed file the run wrote, refused by the driver when no attributed output is selected;
#: ``parquet`` (absent = false) does the same with a directory of Parquet files.
_OUTPUTS_KEYS = {"faithful_attributed", "enhanced_attributed", "arm", "analysis_ready", "zarr",
                 "parquet"}

#: ``[run]`` selects (which engine, which named campaign) and locates (raw
#: files, output directory, which stages) -- it never describes a threshold or
#: assembles a campaign field by field (the no-raw-thresholds rule; ``run_flight.CampaignPreset``'s
#: own docstring: "chosen whole, by name, and never assembled field by field").
#: ``tas_file`` locates an input file, as ``raw`` does; which profile reads it is
#: the profile's own field.
#:
#: ``probe`` names which probe the run follows. A SEA file holds several probes' streams, so a
#: config for one says which it means; the preset already fixes the probe, so this key selects by
#: agreeing with it and ``arrayprobe run`` refuses the run, by name, when the two disagree.
#: ``tas_from_probe`` locates input files as ``raw`` does: the ``<stem>.tas.csv`` airspeed files
#: another probe on the same aircraft wrote (a 2D-S), for a CIP or PIP whose own decode writes
#: none. Each entry is a path or glob relative to this file and must match at least one file.
#: ``presets`` is a TOML file of ``[[campaign]]`` tables (relative to this file) registered before
#: ``preset`` is read; ``probe_case`` and ``probe_case_module`` are ``run_flight``'s
#: ``--probe-case`` / ``--probe-case-module`` (engine 3.5): the registered probe case that fixes the
#: bin table, and the module whose import registers it. Each is forwarded only when set.
_RUN_KEYS = {"engine", "preset", "raw", "out", "stages", "tas_file", "probe", "tas_from_probe",
             "presets", "probe_case", "probe_case_module"}
_ENGINES = {"3.1.4", "3.5", "soda2"}
#: The netCDF format each UIOOPS engine's writers produce, whatever ``[export].format`` says:
#: v3.1.4 MATLAB's bare ``'clobber'`` default, v3.5 its own ``netcdf.create`` calls (decode,
#: proc and sd; the borrowed combine is the fork's and writes NETCDF3_CLASSIC -- measured on the
#: demo flight 2026-09-26).
_ENGINE_FORMAT = {"3.1.4": "NETCDF3_CLASSIC", "3.5": "NETCDF4"}
#: ``"soda2"`` is its own engine, not a UIOOPS version: it runs through
#: ``arrayprobe soda2 run`` and needs a ``[soda2]`` table holding the driver's ``op`` fields.

#: What a ``[run].engine = "soda2"`` file may contain (the SODA-2 port lanes; a project
#: decision of 2026-09-15 that a SODA-2 config names no profile). The SODA-2
#: engine has one source tree, so it reads no :class:`FidelityProfile` -- the ``STOCK_V35``
#: reasoning -- and ``arrayprobe soda2 run`` reads only these sections and, of ``[run]``,
#: only ``engine``. Everything else a UIOOPS file may carry (``[fidelity]``, ``[shattering]``,
#: ``[masking]``, ``[export]``, ``[combine]``, ``[run].raw/out/preset/stages/tas_file``) would
#: be silently ignored, so it is refused -- the same reason a ``[soda2]`` table under a UIOOPS
#: engine is refused.
_SODA2_SECTIONS = {"run", "soda2", "enhancements", "outputs", "arm"}
#: ``jit`` joined ``engine`` on 2026-09-18. It is the one exception to "``[run]`` selects and
#: locates, never describes", and it is not really an exception: ``jit`` selects a *kernel*,
#: not a number. ``arrayprobe_soda2.jit_kernels``' flood fill is exact by construction and
#: ``tests/test_soda2_label_region_jit_identity.py`` asserts the two paths byte-identical with
#: ``np.array_equal``, so a config that sets it and one that does not produce the same PBP
#: files -- nothing about the run's science is described here. It is a config key as well as
#: ``--jit`` because the flag alone left the kernel reachable only from a hand-typed command
#: line, the shape of the silent --jit no-op fix (a capability nothing connects);
#: ``--jobs``/``--chunks`` stay flag-only, being per-machine resources rather than a property
#: of the run.
_SODA2_RUN_KEYS = {"engine", "jit"}


class ConfigError(ValueError):
    """A config that would pick a side silently, or names something the port cannot honour.

    Raised by :func:`load_config` once for the whole file: its first line is the first problem
    and the file's path, any further problems follow numbered, and ``.problems`` lists them all.
    """

    #: Every problem :func:`load_config` found in the file, in the order found; empty for an
    #: error raised before the file's contents could be read (directory, encoding, TOML syntax).
    problems: tuple[str, ...] = ()


class ConfigDecodeError(ConfigError, tomllib.TOMLDecodeError):
    """A config file that is not valid TOML: a :class:`ConfigError`, so every driver reports it
    in one line, and still a ``tomllib.TOMLDecodeError`` for a caller that catches that."""


@dataclass(frozen=True)
class RunConfig:
    """A validated run configuration -- everything a TOML file is allowed to select.

    Frozen, and every fidelity-relevant field is filled by :func:`load_config`
    from an explicit key: there is no constructor path that infers a profile or
    supplies a threshold. That is the rule that a config file may select a named variant but
    never set a threshold, expressed in the type -- a config file selects between
    documented MATLAB behaviours, it never invents one, so a caller reading this object can
    trust that anything affecting a computed number was named in the file.

    ``enhancements`` is a bag of booleans the core deliberately does not
    interpret; it is read only through :meth:`enabled`, by the separately
    installed ``arrayprobe-uiops-enhancements`` layer. ``source`` is the path the
    config was read from, carried so a provenance stamp can name it.
    """

    profile: FidelityProfile | None
    """The named UIOOPS profile. ``None`` only when ``[run].engine = "soda2"``, which reads no
    profile and whose file may not name one (:data:`_SODA2_SECTIONS`, a project decision
    of 2026-09-15); every UIOOPS-engine config still requires it."""
    shattering_threshold_file: str | None
    """The twelfth ``sizeDist`` argument, verbatim; ``None`` means the section was absent."""
    profile_module: str | None = None
    """``[fidelity].profile_module``, if the file named one -- carried for provenance/logging;
    the import already happened during :func:`load_config`, so this field does not need to be
    re-applied by a caller. See that function for why this exists."""
    authordefaults_stamp: str | None = None
    authordefaults_path: Path | None = None
    """The resolved ``[fidelity].authordefaults`` file, ``None`` otherwise (the default, so a
    config without the key behaves as before). ``run_flight`` carries it to ``--chunks`` workers
    as the ``authordefaults=<path>`` tail token, where it is re-loaded and its hash re-checked."""
    shattering_ia_thresh_type: int | None = None
    """``[shattering].ia_thresh_type``: 2 selects engine 3.5's per-second default threshold;
    ``None`` (absent) leaves the driver's choice, 1 with a threshold file and 0 without."""
    """``authordefaults:<path>#<sha>``, when ``[fidelity].authordefaults``
    named an author-editable defaults file -- ``None`` otherwise, including every config that
    predates this field, so the default behaviour is unchanged (:mod:`arrayprobe.authordefaults`).
    A caller that stamps a ``.call`` sidecar appends this verbatim; it is not re-derivable from
    :attr:`profile` alone, because the generated profile's own name already encodes the file's
    hash but not its path."""
    diode_masks: dict[str, tuple[int, ...]] = field(default_factory=dict)
    export_format: str = "NETCDF3_CLASSIC"
    enhancements: dict[str, bool] = field(default_factory=dict)
    enhancements_declared: bool = False
    """Whether the file carried an ``[enhancements]`` section *at all* -- distinct from
    carrying an empty one. The port does not use it: absent and empty mean the same thing
    here (nothing on). It exists because ``arrayprobe-enhanced run`` refuses a config with
    no enhancement policy rather than guessing one (2026-09-16 usability audit), and the
    loader is the only place that still knows the difference."""
    soda2: dict[str, Any] = field(default_factory=dict)
    """``[soda2]`` verbatim -- the SODA-2 driver's ``op`` fields (~40, unlike any UIOOPS
    section), consumed only by ``arrayprobe soda2 run``. Required when ``[run].engine`` is
    ``"soda2"``; the core does not interpret it."""
    combine: dict[str, str] = field(default_factory=dict)
    """Whatever ``[combine]`` held besides ``borrowed`` -- **provably empty since
    2026-09-20**, when :data:`_COMBINE_KEYS` began refusing every other key. Kept
    as a field rather than deleted in the same pass, because deleting a public
    dataclass field is a separate change with its own callers to check; nothing in
    ``src``, ``tools`` or either enhancements package reads it (measured by grep,
    2026-09-20), and the next pass over this class should drop it."""
    run: dict[str, object] = field(default_factory=dict)
    source: str = ""
    borrowed_combine: bool = False
    thresholds_regime: str | None = None
    """``[thresholds].regime``, or ``None`` when absent -- one of
    :data:`arrayprobe.regimes.REGIMES`. Already validated against the registry at load time
    (regime-based configurable thresholds)."""
    thresholds_area_ratio_z: float | None = None
    """``[thresholds].area_ratio_z``, or ``None`` when absent -- a raw override, allowed
    for exactly this field. Already bounds-checked at load time
    (:func:`arrayprobe.regimes.resolve_thresholds`, which raises :class:`ConfigError` here)."""
    thresholds_default_int_arr_thresh: float | None = None
    """``[thresholds].default_int_arr_thresh``, or ``None`` when absent -- as
    :attr:`thresholds_area_ratio_z`, for ``defaultIntArrThresh``."""
    thresholds_tas_max: float | None = None
    """``[thresholds].tas_max`` (m/s), or ``None`` when absent -- ``tasMax`` for an S4 case that
    assigns none (the 2DP), passed to ``sizedist.run(tas_max=)``. Not a fidelity threshold: an
    input MATLAB cannot run without, with no default. Finite and > 0, checked at load time."""
    thresholds_pecan_params: str | None = None
    """``[thresholds].pecan_params``, or ``None`` when absent -- the parameter file standing in
    for ``getPECANparams`` (:mod:`arrayprobe_uiops.pecan_params`), resolved relative to this file
    and parsed at load time."""
    thresholds_declared: bool = False
    """Whether the file carried a ``[thresholds]`` section at all -- distinct from every field in
    it being absent (``regime`` with no raw override is a real, meaningful selection)."""
    v35_i_qc: int | None = None
    """``[v35].iQC`` (iQC and iNewHabit configurable) -- 0 or 1, validated at load time; ``None``
    when the file did not set it, in which case the driver's own ``V35_CALL.i_qc`` default (0)
    applies. Read only when ``[run].engine = "3.5"``."""
    v35_i_new_habit: int | None = None
    """``[v35].iNewHabit`` (iQC and iNewHabit configurable) -- 0 or 1, validated at load time;
    ``None`` when unset, same engine restriction as :attr:`v35_i_qc`."""
    v35_declared: bool = False
    """Whether the file carried a ``[v35]`` section at all -- distinct from a field in it being
    unset (same pattern as :attr:`thresholds_declared`)."""
    arm: dict[str, str] = field(default_factory=dict)
    """``[arm]``, verbatim: ``site_id``/``platform_id``/``facility_id`` (always present
    together when this is non-empty) and optionally ``data_level``. Empty when the file names no
    ``[arm]`` section -- the enhancements driver's ``arm_export`` adapter then names a skip
    rather than falling back to a placeholder identifier (``arm_export.py``'s own rule: these
    three are never invented). Read by
    ``arrayprobe_enhancements.pipeline.apply_enhancements``, never by the port itself."""
    tas_source: str | None = None
    """``[tas].source`` (merged-file airspeed for ORACLES, the non-ORACLES airspeed chain) -- one
    of :data:`arrayprobe.tools.tas_sources.MODES`, or ``None`` when the file names no ``[tas]``
    section (the legacy ``--tas-file`` / ``[run].tas_file`` path, untouched). Read only by
    ``scripts/run_flight.py``."""
    tas_search: tuple[str, ...] = field(default_factory=tuple)
    """``[tas].search`` (the non-ORACLES airspeed chain), resolved relative to this config
    file's own directory (``~`` expanded) -- the directories the ``merge``/``aircraft`` chain
    tiers glob in. Empty when the file names none, which is a real, meaningful selection (no
    directory to search) rather than an omission, exactly as an empty ``[thresholds]`` selection
    would be refused at load time -- see :func:`_load_tas`."""
    outputs: dict[str, bool | str] = field(default_factory=dict)
    """``[outputs]``, verbatim: which of the run's three artefacts the file selects
    (:data:`_OUTPUTS_KEYS`). Empty when the file names no ``[outputs]`` section, and then the run
    writes exactly what it wrote before the section existed. An explicit ``false`` is the opt-out;
    the command line still wins over it. Read only by ``run_flight._apply_config``."""
    tas_cutoff_mps: float | None = None
    """``[tas].cutoff_mps`` -- :class:`~arrayprobe.tools.make_tas_file.TasPolicy`'s ``cutoff_mps``,
    or ``None`` when the file did not set it, in which case the driver's own documented default
    (300 m/s) applies."""
    tas_default_mps: float | None = None
    """``[tas].default_mps`` -- :class:`~arrayprobe.tools.make_tas_file.TasPolicy`'s
    ``default_mps``, or ``None`` when unset (the documented 170 m/s default applies)."""
    time_offset: tuple[int, str, str] | None = None
    """``[time_offset]`` as ``(seconds, evidence, tas_clock)``, already validated by
    ``arrayprobe_uiops.sizedist.TimeOffset.build`` at load time; ``None`` when the file names no
    such section, and then the run passes no offset keyword and stamps nothing. Engine 3.5 only.
    Read by ``run_flight._apply_config``, where any ``--time-offset-*`` flag wins over the
    whole section."""
    tas_declared: bool = False
    """Whether the file carried a ``[tas]`` section at all -- distinct from every field in it
    being unset (same pattern as :attr:`thresholds_declared`, :attr:`v35_declared`)."""
    """``[combine].borrowed`` -- the opt-in for the v3.5 engine's borrowed combine (the first of
    the five path-forward decisions):
    run S4c with the ORACLES fork's ``combine_sizedist.m`` over v3.5 ``sd`` files, labelled so in
    the product's ``.call``. Read only by ``scripts/run_flight.py``/``arrayprobe run``; meaningless
    under the v3.1.4 engine, whose combine is the fork's own already."""

    def enabled(self, enhancement: str) -> bool:
        """Whether ``[enhancements].<name>`` was set true, **for the port**. Absent means off.

        Default-off is the contract, not a convenience: an enhancement changes
        what the port computes away from the MATLAB, so it must be opted into
        by name. An unknown name returns ``False`` rather than raising, because
        the core does not know what enhancement names exist -- validating them
        is the enhancements package's job, and refusing here would couple the
        two in the direction ``test_no_enhancement_coupling.py`` forbids.

        **The enhancements package now answers the same question the same way**
        (the 2026-09-16 cold-start usability audit).
        ``arrayprobe_enhancements.registry.resolve`` reads this same table and also
        defaults every registered enhancement *off*. Between the switchable-enhancements
        rule (2026-09-10) and that audit it defaulted them *on*, opt-out by name, on the
        argument that installing that package was itself the opt-in -- so one TOML
        file meant opposite things to the two drivers. A cold-start usability audit
        measured a config whose only line was ``outoffocus = false`` resolving 31 of
        40 modules ON and applying four. One file, one meaning, since. Both views are
        pinned by ``enhancements_uiops/tests/test_enhancement_opt_in.py``; the reasoning is
        in ``enhancements_uiops/docs/enhancement_registry_design.md``.
        """
        return bool(self.enhancements.get(enhancement, False))


class _Problems:
    """Collects the problems :func:`load_config` finds, so one run reports all of them.

    Each message is today's single-error text, unchanged; :meth:`raise_if_any` joins them into
    one :class:`ConfigError` naming the file, with the list on ``.problems``.
    """

    def __init__(self, path) -> None:
        self.path = path
        self._messages: list[str] = []
        self._cause: BaseException | None = None

    def add(self, msg: str, cause: BaseException | None = None) -> None:
        self._messages.append(msg)
        if cause is not None and self._cause is None:
            self._cause = cause

    def __bool__(self) -> bool:
        return bool(self._messages)

    def __len__(self) -> int:
        return len(self._messages)

    def raise_if_any(self) -> None:
        if not self._messages:
            return
        msgs = self._messages
        n = len(msgs)
        if n == 1:
            text = f"{msgs[0]} (in {self.path})"
        else:
            text = "\n".join([f"{msgs[0]} (in {self.path}; 1 of {n} problems, the others below)"]
                             + [f"  {i}. {m}" for i, m in enumerate(msgs[1:], start=2)])
        exc = ConfigError(text)
        exc.problems = tuple(msgs)
        if self._cause is not None:
            raise exc from self._cause
        raise exc


def _check_forbidden(section: str, table: dict, problems: _Problems) -> None:
    bad = sorted(k for k in table if k in _FORBIDDEN)
    if bad:
        problems.add(
            f"[{section}] sets {bad}: fidelity thresholds are chosen by [fidelity].profile "
            f"(one of {sorted(PROFILES)}), never by a raw key")


def _read_toml(path) -> dict:
    """Parse a TOML file the way a Windows user's editor may have saved it.

    A UTF-8 byte-order mark -- what Windows PowerShell 5.1's ``-Encoding utf8`` writes -- is
    dropped: it carries no content, and ``tomllib`` rejects the whole file over it with
    "Invalid statement (at line 1, column 1)". UTF-16 (PowerShell 5.1's ``>``, Notepad's
    "Unicode") and any other non-UTF-8 bytes are refused by name. Every failure is a
    :class:`ConfigError` (a ``ValueError``, as ``tomllib.TOMLDecodeError`` is, chained from it);
    ``FileNotFoundError`` propagates.
    """
    path = Path(path)
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise ConfigError(f"{path} is saved as UTF-16; TOML must be UTF-8. Re-save it as UTF-8 "
                          f"(in PowerShell: Set-Content -Encoding utf8, or Out-File -Encoding "
                          f"utf8)")
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    try:
        return tomllib.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ConfigError(f"{path} is not UTF-8 text ({exc.reason} at byte {exc.start}); "
                          f"TOML must be UTF-8") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigDecodeError(f"{path} is not valid TOML: {exc}") from exc


def load_config(path) -> RunConfig:
    """Read a run-configuration TOML file into a validated :class:`RunConfig`.

    Not a MATLAB behaviour: UIOOPS has no config file, it has driver scripts
    with the constants written in. This loader exists so a run can be
    *described* without editing code, and it is bounded so that description
    can never become a fidelity decision.

    Every rejection below is a case where accepting the file would let it pick
    a side silently:

    * an unknown top-level section (a typo'd ``[fidelty]`` would otherwise be
      ignored and the run would use different settings than the file says);
    * any key in :data:`_FORBIDDEN` anywhere -- ``rej_hollow``,
      ``max_edge_img_ar`` and the rest are chosen by naming a profile, never by
      a raw value, because their correct values are a measured property of a
      MATLAB tree;
    * a missing ``[fidelity].profile``, since no profile is ever assumed -- except under
      ``[run].engine = "soda2"``, which reads no profile and may not name one
      (:func:`_load_soda2_config`, by design);
    * ``[shattering]`` present without ``threshold_file``, because an absent
      twelfth ``sizeDist`` argument is itself an output-changing call
      (``sizeDist.m:70``, ``:866``) and must be stated rather than defaulted;
    * a diode number outside 1..128, or a non-boolean enhancement switch.

    Returns a :class:`RunConfig`. Raises :class:`ConfigError` for all of the
    above; ``FileNotFoundError`` and ``tomllib.TOMLDecodeError`` propagate.
    Every problem in the file is reported at once in that one error, which names the file and
    lists them on ``.problems``; a file that cannot be read as TOML at all fails at once.
    """
    # (The TOMLDecodeError raised is a ConfigDecodeError, a ConfigError too, so the drivers'
    # one-line refusal catches it; a path that is a directory is a ConfigError. The docstring
    # above is rendered into docs/14-api-io-compat.md, so it changes with that page.)
    path = Path(path)
    if path.is_dir():
        # Windows raises PermissionError for open() on a directory, which read as a permissions
        # problem rather than a wrong argument.
        raise ConfigError(f"{path} is a directory; name the .toml file inside it")
    doc = _read_toml(path)
    # From here every problem is collected and all are raised together, naming the file; a
    # check whose input an earlier problem already broke is skipped rather than reported.
    problems = _Problems(path)
    unknown = sorted(set(doc) - _SECTIONS)
    if unknown:
        problems.add(f"unknown section(s) {unknown}; known: {sorted(_SECTIONS)}")
    not_tables = sorted(name for name, table in doc.items() if not isinstance(table, dict))
    if not_tables:
        # `run = "x"` or `masking = [3]` at the top level: every reader below expects a table,
        # and without this the user saw an AttributeError/ValueError traceback instead.
        problems.add(f"{not_tables} must be table(s), written as a [section] header "
                     f"with key = value lines under it, not a top-level value")
        problems.raise_if_any()
    for name, table in doc.items():
        _check_forbidden(name, table, problems)

    # A [soda2] table with no [run].engine is a SODA-2 file too: `arrayprobe soda2 run` runs it
    # (its engine defaults to "soda2") and a UIOOPS engine refuses [soda2], so the SODA-2 rules
    # apply to every file the SODA-2 engine can run, not only to the ones that say so.
    run_table = doc.get("run")
    engine = run_table.get("engine") if isinstance(run_table, dict) else None
    if engine == "soda2" or (engine is None and "soda2" in doc):
        return _load_soda2_config(doc, path, problems)

    for name, allowed in _SECTION_KEYS.items():
        extra = sorted(set(doc.get(name, {})) - allowed - _FORBIDDEN)
        if extra:
            problems.add(f"[{name}] has unknown key(s) {extra}; known: {sorted(allowed)}")
    diodes_table = doc.get("masking", {}).get("diodes", {})
    diodes_ok = isinstance(diodes_table, dict)
    if not diodes_ok:
        problems.add(f"[masking].diodes must be a table of <file stem> = [diode numbers], "
                          f"e.g. [masking.diodes] with base160906064017 = [1, 128]; got "
                          f"{diodes_table!r}")

    fid: Any = doc.get("fidelity")
    has_profile = bool(fid) and "profile" in fid
    has_authordefaults = bool(fid) and "authordefaults" in fid
    # The profile chain runs only on a well-formed [fidelity] and stops at its first problem:
    # each step reads what the one before it established.
    fid_ok = True
    if not has_profile and not has_authordefaults:
        problems.add("[fidelity].profile or [fidelity].authordefaults is required; no "
                     "profile is ever assumed")
        fid_ok = False
    if has_profile and has_authordefaults:
        problems.add("[fidelity] names both profile and authordefaults; a run selects "
                     "exactly one -- authordefaults already names its own base profile")
        fid_ok = False
    profile: FidelityProfile | None = None
    profile_module = fid.get("profile_module") if fid_ok else None
    if profile_module is not None:
        # Imported for its side effect: a module that calls register_profile()
        # at import time. This is the ONLY way a config file reaches a profile
        # it did not ship with -- it still cannot describe one (the no-raw-thresholds
        # rule is unchanged: the module is Python, written and reviewed like any
        # other registration), but without this a registered profile is
        # invisible to any FRESH process that only has this TOML, which is
        # exactly what every subprocess run_flight.py re-execs is. Found
        # 2026-09-10: a profile registered in the parent process worked with
        # --jobs 1 and silently fell back to the default under --chunks > 1 or
        # --jobs > 1, because each worker re-imports arrayprobe.profiles from
        # scratch and never re-runs whatever registered the profile in the
        # parent. Importing here, in load_config() itself, means every process
        # that loads this same config -- parent or worker -- performs the same
        # registration before resolving [fidelity].profile below.
        try:
            from arrayprobe.selector import canonical_module
            importlib.import_module(canonical_module(str(profile_module)))
        except ImportError as exc:
            # The shipped ARM example keeps its module beside the TOML, and a run from
            # the root without that directory on PYTHONPATH failed here with only "No module
            # named ...": say where the module is and what to set.
            beside = path.resolve().parent / (str(profile_module).replace(".", "/") + ".py")
            hint = (f" -- it is imported by module name, and {beside.name} sits beside this "
                    f"config: put {beside.parent} on PYTHONPATH (entries are separated by "
                    f"{os.pathsep!r} on this platform)"
                    if beside.is_file() else
                    " -- it is imported by module name: put the directory that holds it on "
                    "PYTHONPATH")
            problems.add(
                f"[fidelity].profile_module {profile_module!r} could not be imported: {exc}{hint}",
                exc)
            fid_ok = False
    authordefaults_stamp = None
    authordefaults_path = None
    if fid_ok and has_authordefaults:
        ad_value = fid["authordefaults"]
        if not isinstance(ad_value, str):
            problems.add(f"[fidelity].authordefaults must be a file name in quotes, "
                         f"got {ad_value!r}")
        else:
            ad_path = Path(ad_value)
            if not ad_path.is_absolute():
                ad_path = (path.parent / ad_path).resolve()
            try:
                defaults = load_authordefaults(ad_path)
            except FileNotFoundError as exc:
                problems.add(f"[fidelity].authordefaults {ad_value!r} not found "
                             f"(resolved to {ad_path})", exc)
            except AuthorDefaultsError as exc:
                problems.add(str(exc), exc)
            else:
                profile = resolve_profile(defaults)
                authordefaults_stamp = defaults.stamp()
                authordefaults_path = Path(defaults.path)
    elif fid_ok:
        if fid["profile"] not in PROFILES:
            problems.add(f"unknown profile {fid['profile']!r}; known: {sorted(PROFILES)}")
        else:
            profile = PROFILES[fid["profile"]]

    shat = doc.get("shattering")
    threshold = None
    ia_thresh_type = None
    if shat is not None and "ia_thresh_type" in shat:
        # Engine 3.5's sizeDist type-2 branch (sizeDist.m:1346): the probe case's
        # defaultIntArrThresh per second, no file. Opt-in; absent means the driver's own choice.
        ia_thresh_type = shat["ia_thresh_type"]
        if ia_thresh_type != 2 or isinstance(ia_thresh_type, bool):
            problems.add(f"[shattering].ia_thresh_type must be 2 (the default threshold per "
                              f"second); got {ia_thresh_type!r}. Type 1 is selected by "
                              f"threshold_file, type 0 by leaving both out")
        if "threshold_file" in shat:
            problems.add("[shattering] names both threshold_file and ia_thresh_type = 2: "
                              "type 2 reads no file")
    elif shat is not None:
        if "threshold_file" not in shat:
            problems.add("[shattering] present but threshold_file missing: the twelfth "
                         "sizeDist argument must be explicit (an absent file is itself a "
                         "documented, output-changing call -- see sizeDist.m:70,866)")
        elif not isinstance(shat["threshold_file"], str):
            problems.add(f"[shattering].threshold_file must be a file name in quotes, "
                         f"got {shat['threshold_file']!r}")
        else:
            threshold = shat["threshold_file"]

    masks: dict[str, tuple[int, ...]] = {}
    for stem, diodes in ((diodes_table or {}) if diodes_ok else {}).items():
        if not isinstance(diodes, list) or not all(isinstance(d, int) and 1 <= d <= 128
                                                   for d in diodes):
            problems.add(f"[masking].diodes.{stem} must be a list of 1-based diode "
                         f"numbers in 1..128, got {diodes!r}")
            continue
        masks[str(stem)] = tuple(diodes)

    export = doc.get("export", {})
    fmt = str(export.get("format", "NETCDF3_CLASSIC"))
    fmt_ok = fmt in ("NETCDF3_CLASSIC", "NETCDF4")
    if not fmt_ok:
        problems.add(f"[export].format must be NETCDF3_CLASSIC or NETCDF4, got {fmt!r}")

    enh = _enhancement_switches(doc, problems)

    run = dict(doc.get("run", {}))
    unknown_run = sorted(set(run) - _RUN_KEYS - _FORBIDDEN)
    if unknown_run:
        problems.add(f"[run] has unknown key(s) {unknown_run}; known: {sorted(_RUN_KEYS)}")
    engine_ok = not ("engine" in run and run["engine"] not in _ENGINES)
    if not engine_ok:
        problems.add(f"[run].engine must be one of {sorted(_ENGINES)}, got {run['engine']!r}")
    written = _ENGINE_FORMAT.get(str(run.get("engine")))
    if (fmt_ok and engine_ok and "format" in export and written is not None
            and fmt != written):
        # No writer reads [export].format: the engine fixes it. A file asking for the other
        # format used to load and run, and the products came out in the engine's format anyway.
        problems.add(f"[export].format = {fmt!r} cannot be honoured: engine "
                          f"{run['engine']} writes {written}, and no writer reads this key. "
                          f"Set format = {written!r} or drop the [export] section")
    soda2 = dict(doc.get("soda2", {}))
    if engine_ok and soda2 and run.get("engine") not in (None, "soda2"):
        # The same reason an unknown section is refused: a UIOOPS run would ignore it, so the
        # file would say more than the run did.
        problems.add(f"[soda2] is read only by the SODA-2 engine; this file names "
                          f"[run].engine = {run['engine']!r}")
    if "raw" in run and not (isinstance(run["raw"], list)
                             and all(isinstance(r, str) for r in run["raw"])):
        problems.add("[run].raw must be a list of path strings (globs allowed)")
    if "tas_from_probe" in run and not (isinstance(run["tas_from_probe"], list)
                                        and all(isinstance(r, str)
                                                for r in run["tas_from_probe"])):
        problems.add("[run].tas_from_probe must be a list of path strings (globs allowed)")
    for key in ("preset", "out", "stages", "tas_file", "probe", "presets", "probe_case",
                "probe_case_module"):
        if key in run and not isinstance(run[key], str):
            problems.add(f"[run].{key} must be a string, got {run[key]!r}")

    comb = dict(doc.get("combine", {}))
    unknown_combine = sorted(set(comb) - _COMBINE_KEYS - _FORBIDDEN)
    if unknown_combine:
        problems.add(f"[combine] has unknown key(s) {unknown_combine}; known: "
                          f"{sorted(_COMBINE_KEYS)}")
    borrowed = comb.pop("borrowed", False)
    if not isinstance(borrowed, bool):
        problems.add(f"[combine].borrowed must be true/false, got {borrowed!r}")

    thr_regime, thr_area, thr_iat, thr_declared = _load_thresholds(doc.get("thresholds"), path,
                                                                    problems)
    thr_tas_max, thr_pecan = _load_s4_case_inputs(doc.get("thresholds"), path, problems)
    v35_i_qc, v35_i_new_habit, v35_declared = _load_v35(doc.get("v35"), run, problems,
                                                        engine_ok)
    arm = _load_arm(doc.get("arm"), problems)
    outputs = _load_outputs(doc.get("outputs"), problems)
    (tas_source, tas_search, tas_cutoff, tas_default,
     tas_declared) = _load_tas(doc.get("tas"), path, problems)
    time_offset = _load_time_offset(doc.get("time_offset"), run, problems, engine_ok)

    problems.raise_if_any()
    return RunConfig(profile=profile, shattering_threshold_file=threshold,
                     shattering_ia_thresh_type=ia_thresh_type,
                     profile_module=str(profile_module) if profile_module is not None else None,
                     authordefaults_stamp=authordefaults_stamp,
                     authordefaults_path=authordefaults_path,
                     diode_masks=masks,
                     export_format=fmt, enhancements=enh,
                     enhancements_declared="enhancements" in doc,
                     combine={k: str(v) for k, v in comb.items()},
                     run=run, source=str(path), borrowed_combine=borrowed, soda2=soda2,
                     thresholds_regime=thr_regime, thresholds_area_ratio_z=thr_area,
                     thresholds_default_int_arr_thresh=thr_iat, thresholds_declared=thr_declared,
                     thresholds_tas_max=thr_tas_max, thresholds_pecan_params=thr_pecan,
                     v35_i_qc=v35_i_qc, v35_i_new_habit=v35_i_new_habit,
                     v35_declared=v35_declared, arm=arm, outputs=outputs,
                     tas_source=tas_source, tas_search=tas_search,
                     tas_cutoff_mps=tas_cutoff, tas_default_mps=tas_default,
                     tas_declared=tas_declared, time_offset=time_offset)


def _section_start(table: dict, problems: _Problems) -> tuple[int, bool]:
    """Where a section helper's own problems begin, and whether the section is clean so far.

    A forbidden key in the section was already reported by :func:`_check_forbidden`; it still
    marks the section as broken, so the section's dependent checks (empty, resolver) are skipped
    rather than reporting a consequence of it.
    """
    return len(problems), not (set(table) & _FORBIDDEN)


def _load_thresholds(thr: dict | None, path: Path,
                     problems: _Problems) -> tuple[str | None, float | None, float | None, bool]:
    """``[thresholds]`` (regime-based configurable thresholds) -- the one section exempt from the
    no-raw-thresholds rule.

    Returns ``(regime, area_ratio_z, default_int_arr_thresh, declared)`` -- the RAW selection, not
    a resolved value, so the caller (``run_flight.py``) can let a command-line flag win over a
    config field-by-field before resolving, the same precedence every other ``--config`` value
    already gets (``_apply_config``'s own docstring: "the command line always wins"). Validated
    here regardless -- an unknown regime name or an out-of-bounds raw value fails at load time,
    before any run consumes hours -- by asking :func:`~arrayprobe.regimes.resolve_thresholds` to
    resolve them (result discarded; only used to validate) with an argument set no config file
    can otherwise construct: naming a project/probe/tree here would need this loader to know a
    run's campaign, which it does not and must not (that stays ``[run].preset`` /
    ``CampaignPreset``'s job) -- so this call only ever exercises the regime and override
    branches, never the project/probe-dependent "stock" fallback.
    """
    if thr is None:
        return None, None, None, False
    if not isinstance(thr, dict):
        raise ConfigError(f"[thresholds] must be a table, got {thr!r}")
    start, clean = _section_start(thr, problems)
    extra = sorted(set(thr) - _THRESHOLD_KEYS - _FORBIDDEN)
    if extra:
        problems.add(f"[thresholds] has unknown key(s) {extra}; known: "
                     f"{sorted(_THRESHOLD_KEYS)}")
    regime_name = thr.get("regime")
    if regime_name is not None and (not isinstance(regime_name, str) or not regime_name.strip()):
        problems.add(f"[thresholds].regime must be a non-empty string, got {regime_name!r}")
    area = thr.get("area_ratio_z")
    if area is not None and (not isinstance(area, (int, float)) or isinstance(area, bool)):
        problems.add(f"[thresholds].area_ratio_z must be a number, got {area!r}")
    iat = thr.get("default_int_arr_thresh")
    if iat is not None and (not isinstance(iat, (int, float)) or isinstance(iat, bool)):
        problems.add(f"[thresholds].default_int_arr_thresh must be a number, got {iat!r}")
    if not clean or len(problems) > start:
        # The empty check and the resolver read the values checked above; skip, never report
        # a consequence. Nothing reads the return value: load_config raises before RunConfig.
        return None, None, None, False
    if regime_name is None and area is None and iat is None:
        if "tas_max" in thr or "pecan_params" in thr:
            # Only the S4 case inputs (_load_s4_case_inputs): a declared section, no threshold.
            return None, None, None, True
        problems.add("[thresholds] is present but empty: name a regime, a raw override, "
                     "or both, or omit the section entirely")
        return None, None, None, False
    try:
        resolve_thresholds(
            regime_name=regime_name,
            area_ratio_z_override=float(area) if area is not None else None,
            default_int_arr_thresh_override=float(iat) if iat is not None else None,
            override_source=str(path),
        )
    except (ValueError, ThresholdValidationError) as exc:
        problems.add(f"[thresholds]: {exc}", exc)
        return None, None, None, False
    return (regime_name, float(area) if area is not None else None,
            float(iat) if iat is not None else None, True)


def _load_s4_case_inputs(thr: dict | None, path: Path,
                         problems: _Problems) -> tuple[float | None, str | None]:
    """``[thresholds].tas_max`` and ``[thresholds].pecan_params`` -- the two ``sizeDist`` inputs
    a UIOOPS case can lack (the 2DP's ``tasMax``; PECAN's ``getPECANparams``), as ``(tas_max,
    pecan_params)``. Validated here so a bad value fails before any run spends hours: ``tas_max``
    finite and > 0; ``pecan_params`` a path, relative to this file, that parses as a parameter
    file. Which case needs them is the driver's check, since only it knows the probe."""
    if not isinstance(thr, dict):
        return None, None
    tas_max = thr.get("tas_max")
    if tas_max is not None:
        if (isinstance(tas_max, bool) or not isinstance(tas_max, (int, float))
                or not math.isfinite(tas_max) or tas_max <= 0):
            problems.add(f"[thresholds].tas_max is an airspeed in m/s, finite and > 0; "
                         f"got {tas_max!r}")
            tas_max = None
        else:
            tas_max = float(tas_max)
    pecan = thr.get("pecan_params")
    if pecan is not None:
        if not isinstance(pecan, str) or not pecan.strip():
            problems.add(f"[thresholds].pecan_params must be a path string, got {pecan!r}")
            return tas_max, None
        resolved = (Path(path).parent / Path(pecan).expanduser()).resolve()
        # Imported on use: only a PECAN configuration reaches it.
        from arrayprobe_uiops.pecan_params import load_pecan_params
        try:
            load_pecan_params(resolved)
        except (OSError, ValueError) as exc:
            problems.add(f"[thresholds].pecan_params {pecan!r} ({resolved}): {exc}", exc)
            return tas_max, None
        pecan = str(resolved)
    return tas_max, pecan


def _load_v35(v35: dict | None, run: dict, problems: _Problems,
              engine_ok: bool) -> tuple[int | None, int | None, bool]:
    """``[v35]`` (iQC and iNewHabit configurable) -- ``iQC``/``iNewHabit`` as run configuration.

    Both are required, no-MATLAB-default positional arguments of
    ``arrayprobe_uiops.imgproc.imgproc_sm_v35`` (its own module docstring); this lets a config file
    *select* between the two documented states (0 or 1) the same way ``[fidelity].profile``
    selects a documented profile -- it cannot invent a third state.  Read only under
    ``[run].engine = "3.5"``, because neither key exists under the 3.1.4 engine (v3.1.4 has only
    the Holroyd habit scheme and no ``qc_image`` gate to switch).

    Returns ``(iQC, iNewHabit, declared)`` -- ``None`` for a field the file did not set, so the
    caller (``scripts/run_flight.py``) can leave ``V35_CALL``'s own default (0) in place for it, and
    ``declared`` distinct from either field being set (:func:`_load_thresholds`'s own pattern).
    """
    if v35 is None:
        return None, None, False
    if not isinstance(v35, dict):
        raise ConfigError(f"[v35] must be a table, got {v35!r}")
    start, clean = _section_start(v35, problems)
    # An engine name [run] already refused says nothing about which engine this file meant.
    if engine_ok and run.get("engine") != "3.5":
        problems.add(f"[v35] is read only by the 3.5 engine; this file names "
                     f"[run].engine = {run.get('engine')!r}")
    extra = sorted(set(v35) - _V35_KEYS - _FORBIDDEN)
    if extra:
        problems.add(f"[v35] has unknown key(s) {extra}; known: {sorted(_V35_KEYS)}")

    def _bit(key: str) -> int | None:
        if key not in v35:
            return None
        val = v35[key]
        if isinstance(val, bool) or not isinstance(val, int) or val not in (0, 1):
            problems.add(f"[v35].{key} must be 0 or 1, got {val!r}")
            return None
        return val

    i_qc = _bit("iQC")
    i_new_habit = _bit("iNewHabit")
    if not clean or len(problems) > start:
        return None, None, False
    if i_qc is None and i_new_habit is None:
        problems.add("[v35] is present but empty: set iQC, iNewHabit, or both, or omit "
                     "the section entirely")
        return None, None, False
    return i_qc, i_new_habit, True


def _load_time_offset(sec: dict | None, run: dict, problems: _Problems,
                      engine_ok: bool) -> tuple[int, str, str] | None:
    """``[time_offset]`` -- engine 3.5's probe-clock offset, as ``(seconds, evidence,
    tas_clock)``.

    The three keys are one setting: all present, or the section omitted. Validated at load time
    by the engine's own ``TimeOffset.build`` (whole, non-zero seconds under one day; non-empty
    evidence; ``tas_clock`` one of ``TAS_CLOCKS``), so a bad value fails before any run spends
    hours. Refused unless ``[run].engine = "3.5"``, as ``run_flight.py`` refuses the flags under
    3.1.4 and as :func:`_load_v35` refuses its section.
    """
    if sec is None:
        return None
    if not isinstance(sec, dict):
        raise ConfigError(f"[time_offset] must be a table, got {sec!r}")
    start, clean = _section_start(sec, problems)
    if engine_ok and run.get("engine") != "3.5":
        problems.add(f"[time_offset] is engine 3.5 only (a keyword of arrayprobe_uiops's sizeDist; "
                     f"v3.1.4 reproduces the archived record); this file names "
                     f"[run].engine = {run.get('engine')!r}")
    extra = sorted(set(sec) - set(_TIME_OFFSET_KEYS) - _FORBIDDEN)
    if extra:
        problems.add(f"[time_offset] has unknown key(s) {extra}; known: "
                     f"{list(_TIME_OFFSET_KEYS)}")
    missing = [k for k in _TIME_OFFSET_KEYS if k not in sec]
    if missing:
        problems.add(f"[time_offset] is missing {missing}: seconds, evidence and tas_clock are "
                     f"required together, or omit the section")
    if not clean or len(problems) > start:
        return None
    # Imported on use: only a file with this section reaches it.
    from arrayprobe_uiops.sizedist import TimeOffset
    try:
        off = TimeOffset.build(sec["seconds"], sec["evidence"], sec["tas_clock"])
    except ValueError as exc:
        problems.add(f"[time_offset]: {exc}", exc)
        return None
    return off.seconds, off.evidence, off.tas_clock


def _load_arm(arm: dict | None, problems: _Problems) -> dict[str, str]:
    """``[arm]`` -- the real ARM site/platform/facility identifiers
    ``arrayprobe_enhancements.arm_export`` needs to run through the enhancements driver, and
    never invents on its own (``arm_export.py``'s own docstring: "``site_id``/``facility_id``/
    ``platform_id`` are never invented"). A config file supplies the user's own already-assigned
    ARM codes for a real deployment; this loader does not derive, guess or default any of the
    three -- only ``data_level`` may fall back to ``export()``'s own documented default.

    Returns ``{}`` when the file names no ``[arm]`` section, so
    :meth:`arrayprobe_enhancements.pipeline._apply_arm_export` (the only consumer) can tell
    "no section" from "section present" and name a skip rather than fabricate an identifier.
    """
    if arm is None:
        return {}
    if not isinstance(arm, dict):
        raise ConfigError(f"[arm] must be a table, got {arm!r}")
    extra = sorted(set(arm) - _ARM_KEYS - _FORBIDDEN)
    if extra:
        problems.add(f"[arm] has unknown key(s) {extra}; known: {sorted(_ARM_KEYS)}")
    missing = sorted(k for k in _ARM_REQUIRED_KEYS if not arm.get(k))
    if missing:
        problems.add(
            f"[arm] is missing {missing}: site_id, platform_id and facility_id are required "
            "together when [arm] is present -- they are never invented or defaulted "
            "(arm_export.py's own rule), so a partial identifier is refused rather than "
            "completed with a guess")
    out: dict[str, str] = {}
    for key in _ARM_KEYS:
        if key not in arm or key in missing:
            # A key the missing-identifier problem above already names is not reported twice.
            continue
        val = arm[key]
        if not isinstance(val, str) or not val.strip():
            problems.add(f"[arm].{key} must be a non-empty string, got {val!r}")
            continue
        out[key] = val
    return out


def _load_outputs(outputs: dict | None, problems: _Problems) -> dict[str, bool | str]:
    """``[outputs]`` -- each key a true/false selection of one of the run's artefacts.

    Returns ``{}`` for no section, so the driver can tell "the file says nothing" (today's
    behaviour, unchanged) from "the file opts out" (``false``). A non-boolean or unknown key is a
    problem, never a coercion: ``"yes"`` is not ``true``.
    """
    if outputs is None:
        return {}
    if not isinstance(outputs, dict):
        raise ConfigError(f"[outputs] must be a table, got {outputs!r}")
    extra = sorted(set(outputs) - _OUTPUTS_KEYS - _FORBIDDEN)
    if extra:
        problems.add(f"[outputs] has unknown key(s) {extra}; known: {sorted(_OUTPUTS_KEYS)}")
    out: dict[str, bool | str] = {}
    for key in sorted(_OUTPUTS_KEYS & set(outputs)):
        val = outputs[key]
        if key == "arm":
            # "faithful" or false. "enhanced" is selected today by [enhancements]
            # arm_export = true, so naming it here would be a second switch for one file.
            if val is False or val == "faithful":
                out[key] = val
            else:
                problems.add(f'[outputs].arm must be "faithful" or false, got {val!r} (the '
                             "enhanced ARM file is selected by [enhancements] arm_export = "
                             "true)")
            continue
        if not isinstance(val, bool):
            problems.add(f"[outputs].{key} must be true/false, got {val!r}")
            continue
        out[key] = val
    return out


def _load_tas(tas: dict | None, path: Path, problems: _Problems,
             ) -> tuple[str | None, tuple[str, ...], float | None, float | None, bool]:
    """``[tas]`` (merged-file airspeed for ORACLES, the non-ORACLES airspeed chain) -- the TAS
    source chain's config-file half.

    Returns ``(source, search, cutoff_mps, default_mps, declared)`` -- the raw selection, so
    ``scripts/run_flight.py`` can let a ``--tas-source``/``--tas-search``/``--tas-cutoff-mps``/
    ``--tas-default-mps`` flag win over a config field-by-field, the same precedence every other
    ``--config`` value already gets. ``cutoff_mps``/``default_mps`` are validated here regardless,
    by constructing a :class:`~arrayprobe.tools.make_tas_file.TasPolicy` (result discarded, only
    used to validate) -- an invalid pair fails at load time, before any run consumes hours, the
    same reason :func:`_load_thresholds` validates its own raw overrides early.
    """
    if tas is None:
        return None, (), None, None, False
    if not isinstance(tas, dict):
        raise ConfigError(f"[tas] must be a table, got {tas!r}")
    start, clean = _section_start(tas, problems)
    extra = sorted(set(tas) - _TAS_KEYS - _FORBIDDEN)
    if extra:
        problems.add(f"[tas] has unknown key(s) {extra}; known: {sorted(_TAS_KEYS)}")
    source = tas.get("source")
    if source is not None:
        if not isinstance(source, str) or source not in tas_sources.MODES:
            problems.add(f"[tas].source must be one of {tas_sources.MODES}, got {source!r}")
    search_raw = tas.get("search")
    search: tuple[str, ...] = ()
    if search_raw is not None and not (isinstance(search_raw, list)
                                       and all(isinstance(d, str) for d in search_raw)):
        problems.add(f"[tas].search must be a list of directory path strings, got "
                     f"{search_raw!r}")
    elif search_raw is not None:
        # Resolved relative to the config file's own directory, the same rule [run].raw and
        # [fidelity].profile_module's sibling paths use elsewhere in this loader -- a config
        # names locations relative to itself, not to whatever directory a run happens to start
        # in. `~` is expanded here rather than left for the caller, because tas_sources.SOURCES'
        # own glob (arrayprobe.tools.tas_sources._candidates) expects an already-expanded path.
        search = tuple(str((path.parent / Path(d).expanduser()).resolve())
                       if not Path(d).expanduser().is_absolute()
                       else str(Path(d).expanduser())
                       for d in search_raw)
    cutoff = tas.get("cutoff_mps")
    if cutoff is not None and (not isinstance(cutoff, (int, float)) or isinstance(cutoff, bool)):
        problems.add(f"[tas].cutoff_mps must be a number, got {cutoff!r}")
    default = tas.get("default_mps")
    if default is not None and (not isinstance(default, (int, float)) or isinstance(default, bool)):
        problems.add(f"[tas].default_mps must be a number, got {default!r}")
    if not clean or len(problems) > start:
        # The empty check and TasPolicy read the values checked above; skip, never report a
        # consequence. Nothing reads the return value: load_config raises before RunConfig.
        return None, (), None, None, False
    if source is None and search_raw is None and cutoff is None and default is None:
        problems.add("[tas] is present but empty: name a source, a search directory list, "
                     "a policy override, or some combination, or omit the section entirely")
        return None, (), None, None, False
    try:
        TasPolicy(cutoff_mps=float(cutoff) if cutoff is not None else TasPolicy().cutoff_mps,
                 default_mps=float(default) if default is not None else TasPolicy().default_mps)
    except ValueError as exc:
        problems.add(f"[tas]: {exc}", exc)
        return None, (), None, None, False
    return (source, search, float(cutoff) if cutoff is not None else None,
           float(default) if default is not None else None, True)


def _enhancement_switches(doc: dict, problems: _Problems) -> dict[str, bool]:
    enh = doc.get("enhancements", {})
    for k, v in enh.items():
        if not isinstance(v, bool):
            problems.add(f"[enhancements].{k} must be true/false (opt-in), got {v!r}")
    return {k: bool(v) for k, v in enh.items()}


def _load_soda2_config(doc: dict, path: Path, problems: _Problems) -> RunConfig:
    """The ``[run].engine = "soda2"`` branch of :func:`load_config` (the SODA-2 port
    lanes).

    The author's decision (accepted 2026-09-15) that a SODA-2 config names no profile.
    The SODA-2 engine has one source tree, so no
    :class:`FidelityProfile` is required and none may be named: ``profile`` is ``None``. Only
    :data:`_SODA2_SECTIONS` are accepted, and only ``engine`` in ``[run]``, because
    ``arrayprobe soda2 run`` reads nothing else -- a ``[fidelity]`` table here would be a
    profile the run silently ignored. The raw file and output directory are the driver's own
    ``op`` fields, ``[soda2].fn`` and ``[soda2].outdir``.
    """
    # A section outside _SECTIONS was already reported as unknown by load_config.
    extra = sorted((set(doc) & _SECTIONS) - _SODA2_SECTIONS)
    if extra:
        hint = (" -- the SODA-2 engine has one source tree and reads no UIOPS fidelity profile"
                if "fidelity" in extra else "")
        problems.add(f'[run].engine = "soda2" reads only {sorted(_SODA2_SECTIONS)}; this '
                     f"file also has {extra}, which the SODA-2 engine would ignore{hint}")
    run = dict(doc.get("run", {}))
    extra_run = sorted(set(run) - _SODA2_RUN_KEYS - _FORBIDDEN)
    if extra_run:
        problems.add(f'[run].engine = "soda2" reads only {sorted(_SODA2_RUN_KEYS)} in '
                     f"[run]; this file also sets "
                     f"{extra_run} -- the raw file and output directory are the driver's "
                     f"[soda2].fn and [soda2].outdir (or `arrayprobe soda2 run --out`)")
    if "jit" in run and not isinstance(run["jit"], bool):
        problems.add(f"[run].jit is a switch and takes true or false; this file sets "
                     f"{run['jit']!r}")
    soda2 = doc.get("soda2")
    if not isinstance(soda2, dict) or not soda2:
        problems.add('[run].engine = "soda2" needs a [soda2] table holding the '
                     "driver's op fields")
    enh = _enhancement_switches(doc, problems)
    # [outputs] and [arm] go through the loaders a UIOOPS file uses; which selections the SODA-2
    # engine has built is decided by `arrayprobe soda2 run`, which refuses the rest by name.
    outputs = _load_outputs(doc.get("outputs"), problems)
    arm = _load_arm(doc.get("arm"), problems)
    problems.raise_if_any()
    assert isinstance(soda2, dict)  # the [soda2] check above added a problem otherwise
    return RunConfig(profile=None, shattering_threshold_file=None,
                     enhancements=enh,
                     enhancements_declared="enhancements" in doc,
                     run=run, source=str(path), soda2=dict(soda2),
                     outputs=outputs, arm=arm)
