# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe-enhanced run`` -- drive a whole flight through the port, then apply every
enhancement that :mod:`arrayprobe_enhancements.registry` resolves ON for the engine named in
the config file, one correction per output, with a machine-readable record of what happened.

Built 2026-09-14.

**The port is never called in-process.** ``scripts/make_demo_reference.py:279-328``
(``build_v35``) found the reason first: ``scripts/run_flight.py`` sets module globals
(``ENGINE``, ``PROFILE``, ``ACTIVE``, ...) on its own shared module object, and every
in-process test that has ever bound to it needed a snapshot/restore list. A subprocess needs
none of that, cannot leak into this process, and *is* the line a user actually runs:
``python -m arrayprobe.cli run <config.toml> <raw...>``. Cost measured there: ~2 s per build.

**Resolution happens before the subprocess, and before any directory is created.** This is
the driver's whole answer to the double-correction hazard
(``arrayprobe_enhancements.applicability``'s whole reason for existing): an enhancement a
config file switched on explicitly, that the target engine does not cover, raises
:class:`~arrayprobe_enhancements.applicability.NotApplicableToEngine` out of
:func:`resolve_for_run` -- which runs first in :func:`apply_enhancements`, before
``run_port`` is even called and before ``out_dir`` exists.

**Reader-stage enhancements are not applied by this driver -- decided 2026-09-21.**
A reader enhancement (``last_record_fix``, ``pms_c6_routing_fix``, and, since 2026-09-21, any
future module registered with ``stage="reader"``) replaces the decode itself and cannot be
bolted on after the port has already written its files -- there is nothing post hoc to
correct, the file the port wrote already lacks the particles the enhancement would have
recovered. The investigation found a re-decode path *mechanically reachable*
(``run_flight.py`` already accepts a pre-existing image file for stages 3 onward), but the
author closed the decision the other way: a re-decode path is a larger change and stays out
of scope. So the refusal is permanent policy, not a placeholder -- :func:`_reader_stage_reason`
names the specific module, states that it acts during decode, and points at its own entry
point to call directly instead. It is recorded in the provenance sidecar's ``skipped`` map
(never silently dropped) rather than raised, because the same run may legitimately apply other,
reachable enhancements alongside a named-but-unreachable reader-stage one -- the same idiom
``_NO_ADAPTER_REASON_BY_NAME`` already uses for modules with no proc/sd/product adapter yet.
The classification is read from :attr:`~arrayprobe_enhancements.registry.EnhancementSpec.stage`,
never a name list here, so a new reader-stage registration is refused automatically.

**Locating a subprocess run's outputs cannot go through run_flight's own path helpers.**
``run_flight.proc_path``/``sd_path`` compute their engine-specific suffix from the module
global ``ENGINE``, which is set inside the *subprocess* by ``--engine`` and never reaches
this process (the same isolation ``build_v35`` relies on). So :func:`locate_outputs` globs
the output directory for the raw stem instead, and reads each ``.call`` sidecar's *text*
(``run_flight.py:680-686`` ``call_path``, one line) rather than importing ``run_flight`` at
all.

**The stamp-prefix check is written against what was measured, not against the plan's first
guess.** ``run_flight.py:542-545`` (``_engine_prefix``) returns ``"engine=3.5 "`` under the
v3.5 engine and the **empty string** under v3.1.4 -- so a v3.1.4 stamp never starts with
``"engine=3.1.4 "``; only a v3.5 stamp carries an ``engine=`` prefix at all. A refusal test
written as "the stamp must start with ``f'engine={engine} '``" would therefore reject every
correct v3.1.4 output. :func:`_stamp_engine` reads the fact instead of the plan's literal
wording: a stamp starting with ``"engine=3.5 "`` is a v3.5 output, anything else -- including
no ``engine=`` token at all -- is v3.1.4, because those are ``applicability.ENGINES``'s only
two members.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as _dt
import json
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast

import netCDF4
import numpy as np
from arrayprobe.config import ConfigError, RunConfig, load_config

from arrayprobe_enhancements import applicability, registry

__all__ = [
    "Lineage",
    "UIOPS",
    "ApplierSkip",
    "NoEnhancementPolicy",
    "OutputMissing",
    "resolve_for_run",
    "require_enhancement_policy",
    "format_resolution",
    "run_port",
    "locate_outputs",
    "apply_enhancements",
    "apply_to_outputs",
    "main",
]

# --- The injected lineage, for the SODA-2 driver to copy the shape of without importing this module ---
#
# `enhancements_soda2/src/arrayprobe_soda2_enhancements/registry.py:1-6` states its registry is
# "copied, not imported" and has "no engine matrix" -- so every function
# below takes `lineage` rather than reaching for `registry`/`applicability` as module-level
# names, and a SODA-2 driver can hold the same three attributes on its own copied registry
# module without this file ever being on its import graph.


@dataclass(frozen=True)
class Lineage:
    """The registry/applicability pair a driver resolves against, plus which engines it covers.

    Exists so :func:`apply_enhancements` (and any driver that copies its shape, as the SODA-2 one does) never
    hard-codes ``arrayprobe_enhancements.registry``/``.applicability`` as module-level names --
    every function here takes ``lineage`` and reaches the two modules through it.
    """

    registry: ModuleType
    applicability: ModuleType
    engines: tuple[str, ...]


#: The UIOOPS enhancements lineage this file drives. The only lineage that ships today.
UIOPS = Lineage(registry=registry, applicability=applicability, engines=applicability.ENGINES)


class ApplierSkip(Exception):
    """An applier determined, at apply time, that it cannot correct this particular output.

    Raised by an entry in :data:`_APPLIERS` rather than letting the underlying exception
    propagate, so :func:`apply_enhancements` can record one reason string in the provenance
    sidecar's ``skipped`` map without knowing each applier's own failure modes.
    """


class NoEnhancementPolicy(RuntimeError):
    """The config file carried no ``[enhancements]`` section, so it states no policy.

    the 2026-09-16 cold-start usability audit. Absent used to mean "apply everything"; it now means nothing at
    all would be applied, which is a run the user probably did not intend to make through
    *this* driver. Rather than pick either reading silently, the driver refuses and says
    what to write -- an empty ``[enhancements]`` table is the explicit way to say "the
    port, unmodified".
    """


class OutputMissing(RuntimeError):
    """``locate_outputs`` could not find (or could not trust the stamp of) a required output."""


# --- Resolution, before anything is created -------------------------------------------------


def resolve_for_run(cfg: RunConfig, engine: str, lineage: Lineage = UIOPS) -> dict[str, bool]:
    """Resolve ``cfg.enhancements`` for ``engine``, raising before any subprocess or write.

    A thin call onto ``lineage.registry.resolve_from_config`` -- the double-correction guard
    lives entirely in that function's own ``applicability.check`` call
    (``registry.py:522-524``), triggered only for a name the config file explicitly switched
    on. Called first in :func:`apply_enhancements`, before ``out_dir`` exists.
    """
    return lineage.registry.resolve_from_config(cfg, engine)


def require_enhancement_policy(cfg, config_path) -> None:
    """Refuse a config file that carries no ``[enhancements]`` section (2026-09-16 usability audit).

    The audit's finding was not only that the default was wrong -- it was that *the file
    did not say*, and the driver decided for it. So an absent section is now a refusal
    with the two things a user needs: what to add, and what each spelling means.
    ``arrayprobe.config.RunConfig.enhancements_declared`` is the loader's own record of
    whether the section was present; read through ``getattr`` so this module keeps working
    against a ``RunConfig``-shaped object from an older port (there it is absent, which is
    read as "not declared" -- the refusing side, never the applying side).
    """
    if getattr(cfg, "enhancements_declared", False):
        return
    raise NoEnhancementPolicy(
        f"{config_path}: no [enhancements] section, so the file states no policy and "
        "this driver will not choose one for you.\n"
        "  Add an empty table to run the port with no corrections at all:\n"
        "      [enhancements]\n"
        "  or name the corrections you want, one per line -- every enhancement is OFF "
        "unless named true:\n"
        "      [enhancements]\n"
        "      hole_edge_swap = true\n"
        "  `arrayprobe-enhanced enhancements` lists every module that can be named here."
    )


def format_resolution(resolved: dict[str, bool], engine: str, config_path,
                      lineage: Lineage = UIOPS) -> str:
    """The resolved-ON set, printed on every run (2026-09-16 usability audit) so a user cannot be wrong about
    what was applied.

    Names every ON module explicitly rather than counting them: the audit's user read
    "opt-in" on four public pages and would have read a count as agreeing with it. The
    off set is given as a count and a pointer, because forty names of things that did not
    happen is not information.
    """
    on = sorted(n for n, v in resolved.items() if v)
    lines = [
        f"enhancements: {len(on)} of {len(resolved)} ON for engine {engine} "
        f"(from {config_path})",
    ]
    if on:
        wired = set(_APPLIERS)
        for name in on:
            mark = "applies" if name in wired else "no driver adapter"
            lines.append(f"  ON   {name:30s} ({mark})")
    else:
        lines.append("  ON   (none -- the port's own output, unmodified)")
    off = len(resolved) - len(on)
    if off:
        lines.append(f"  OFF  {off} not named true in [enhancements] "
                     f"(or not applicable to engine {engine})")
    return "\n".join(lines)


# --- Running the port, as a subprocess --------------------------------------------------------


def run_port(config_path, raws, *, chunks: int = 1, jobs: int = 1, s2_jobs: int = 1,
             python: str = sys.executable, log_path=None,
             timeout: float = 600.0, enhancements: bool = False,
             port_validation: bool = False) -> subprocess.CompletedProcess:
    """``python -m arrayprobe.cli run <config_path> <raws...> --jobs J --s2-jobs S --chunks C``.

    The one line a user runs (``scripts/make_demo_reference.py:303``'s own comment), as a
    subprocess for the isolation reasons in the module docstring. ``--jobs``/``--s2-jobs``/
    ``--chunks`` are forwarded unconditionally by ``arrayprobe run`` regardless of value
    (``cli.py:690-691``), so passing the defaults costs nothing and needs no special-casing.
    Writes combined stdout+stderr to ``log_path`` if given, then raises ``RuntimeError`` on a
    nonzero return code with the log attached -- never partially applies enhancements to a run
    that did not finish.

    ``port_validation`` forwards ``--port-validation``, which ``arrayprobe run`` requires when
    ``[run].engine`` is 3.1.4 and refuses under any other engine. It is never inferred from the
    config's engine: the caller declares a v3.1.4 run port validation, as a user typing the
    command does.
    """
    cmd = [python, "-m", "arrayprobe.cli", "run", str(config_path),
           *(str(r) for r in raws),
           "--jobs", str(jobs), "--s2-jobs", str(s2_jobs), "--chunks", str(chunks)]
    if enhancements:
        # The enhancement chain runs INSIDE the driver, which holds the run's own S4
        # arguments and so can rebuild the sd from enh.proc (see apply_enhancements).
        cmd.append("--enhancements")
    if port_validation:
        cmd.append("--port-validation")
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=timeout)
    log = f"$ {' '.join(cmd)}\n\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}\n"
    if log_path is not None:
        Path(log_path).write_text(log, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"`{' '.join(cmd)}` failed with rc={result.returncode}:\n{log}")
    return result


# --- Locating what the subprocess wrote --------------------------------------------------------


def _stamp_engine(stamp: str) -> str:
    """Which engine wrote a ``.call`` stamp -- see the module docstring for why this is not a
    literal ``startswith(f"engine={engine} ")`` on both sides. ``run_flight.py:542-545``."""
    return "3.5" if stamp.startswith("engine=3.5 ") else "3.1.4"


def _read_stamp(output_path: Path) -> str | None:
    """The text of ``<output_path>.call``, or ``None`` if it does not exist.

    Reads the sidecar directly (``run_flight.call_path``'s own rule: ``output.name + ".call"``,
    ``run_flight.py:680-686``) rather than importing ``run_flight`` -- see the module docstring
    on why this process never binds to that module's globals.
    """
    sidecar = output_path.with_name(output_path.name + ".call")
    if not sidecar.exists():
        return None
    return sidecar.read_text().strip()


@dataclass(frozen=True)
class _RunOutputs:
    out_dir: Path
    raw_stem: str
    engine: str
    image: Path | None
    proc: Path | None
    sd: Path | None
    combined: Path | None
    #: ``<raw_stem>.tas.csv`` (S4's reader sidecar), if the run wrote one.
    tas_csv: Path | None = None
    #: Per-correction keyword policies, e.g. ``{"particle_time_glitch_fix":
    #: {"policy": "drop"}}`` from ``registry.PROTECTIVE_POLICY``. Empty means each applier's own
    #: default, so every caller that predates these policies is unchanged.
    policies: dict = dataclasses.field(default_factory=dict)
    #: ``arrayprobe.constants.imgproc_config(preset.probe).probetype``, resolved from
    #: ``[run].preset`` via ``run_flight.PRESETS`` (never from the ``.call`` stamp, which
    #: does not carry it -- a measured fact, plan section 2 step 2). ``None`` if the config
    #: names no preset or the preset is unknown.
    preset_probetype: int | None = None
    #: The run's static pressure in Pa, from ``PRESETS[preset].pres_pa``.
    #:
    #: **Carried, but NOT the route `pressure_units_fix` should take, and that is deliberate.**
    #: Added 2026-09-21 after four corrections skipped on a real ARM run needing a run
    #: pressure. Wiring it into `_apply_pressure_units_fix` was then *reverted the same hour*,
    #: because that applier's own docstring refuses a preset-sourced pressure on principle:
    #: it would "pass it off as provenance-verified" when nothing in the product records it,
    #: and the ORACLES value would be "numerically right for the demo and wrong in general,
    #: which is worse than a named gap". That reasoning is correct and outranks the
    #: convenience of having the number to hand.
    #:
    #: **The real fix is the one that applier already names**: stamp the preset's pressure
    #: into the sd ``.call``, give `_stamps_equivalent` a third additive
    #: generation so older stamps stay current, and let the applier read it from the stamp
    #: where it is provenance-verified. Not done here; recorded so the next attempt does not
    #: rediscover the objection from scratch.
    #:
    #: ``None`` when the config names no preset -- never a default. Pressure enters sample
    #: volume, so a guessed value would move every concentration while looking ordinary.
    preset_pres_pa: float | None = None
    #: The flight's UTC date as ``YYYYMMDD``, parsed from the raw stem the run was launched on
    #: (``base170707102822`` -> ``20170707``), which is the same derivation
    #: ``run_flight.stage4`` already does for ``sizeDist``'s own ``ddate`` argument.
    #:
    #: Needed by ``cf_export`` for the CF time axis, which skipped with *"needs the flight
    #: date ... never read off a file name"*. It is read off the file name here, deliberately
    #: and in exactly one place, with the stem's shape asserted rather than assumed --
    #: see :func:`_flight_date_from_stem`.
    flight_date: str | None = None
    #: ``cfg.arm`` -- the run config's ``[arm]`` table, verbatim, or ``{}`` when the file
    #: named no section. The one config-sourced value threaded into a driver adapter's own
    #: fields rather than resolved from the ``.call`` stamp or the raw stem, because an ARM
    #: site/platform/facility id is not a fact any output file or raw filename carries -- it is
    #: assigned by the ARM Data Center and supplied by the author, the same reason
    #: ``arm_export.py``'s own ``export()`` takes it as a required call-time argument with no
    #: default. Empty means :func:`_apply_arm_export` names a skip, never a placeholder.
    arm: dict[str, str] = dataclasses.field(default_factory=dict)
    #: Worker processes for the out-of-focus reject loop (``outoffocus.hollow_diagnostics``'s
    #: ``jobs``). 1 is the serial loop; any value gives the same output and none is written
    #: into a product or its record.
    jobs: int = 1
    #: Which ``<stem>.enh.<kind>.nc`` files THIS run has written (``"proc"``, ``"sd"``).
    #: The chain rule used to be "an enh file exists", which chained a new correction
    #: onto a previous run's output left in the same directory (a second ``hole_edge_swap``
    #: onto an already-swapped copy un-swaps it). Mutable inside a frozen record on purpose:
    #: it is the one field the applier loop updates.
    fresh: set[str] = dataclasses.field(default_factory=set)
    #: The chain so far, filled by :func:`apply_to_outputs` as stages complete: the names
    #: applied at each stage, and which port stages were re-run on the enhanced input. Read by
    #: the product-stage exporters so a product states its own lineage.
    chain: dict = dataclasses.field(default_factory=dict)


def _sd_lineage(outputs: _RunOutputs) -> str:
    """``"enhanced"`` when the sd a product is built from is this run's ``enh.sd``, else
    ``"port"`` -- stamped into OUTPUT 3 (the ARM file) so a reader can tell the two apart."""
    return "enhanced" if "sd" in outputs.fresh else "port"


class StageRunner(Protocol):
    """What a driver that holds the run's own S4 arguments lends the chain.

    ``scripts/run_flight.py``'s ``EnhancedStages`` is the implementation. It lives in the driver,
    not here, because the arguments (engine, preset, pressure, threshold file, v3.5 call
    switches) are module state of that driver, which this process never binds to -- see the
    module docstring. The port's stages are called unmodified through it.
    """

    def sizedist(self, proc: Path, raw_stem: str, dst: Path) -> None:
        """Run the port's own S4 on ``proc`` with this run's arguments, writing ``dst``."""

    def stamp(self, target: Path, source: Path, names: Sequence[str],
              rebuilt: Sequence[str] = ()) -> None:
        """Write ``target``'s ``.call``: ``source``'s stamp plus the enhancement block."""


def _flight_date_from_stem(raw_stem: str) -> str | None:
    """``base170707102822`` -> ``"20170707"``; anything else -> ``None``.

    SPEC raw stems are ``base`` + ``YYMMDDhhmmss``. ``run_flight.stage4`` builds sizeDist's
    ``ddate`` from exactly these characters (``f"20{raw_stem[4:10]} {raw_stem[10:16]}"``), so
    this is the same fact read the same way rather than a second convention.

    **Returns None rather than guessing**, and that is the point: a stem this does not
    recognise yields no date, and `cf_export` then skips exactly as it does today. Inventing a
    date would put a wrong time axis on a file that looks standards-conformant, which is worse
    than not writing one. The digits are range-checked because ``base999999999999`` is a
    well-formed stem and not a date.
    """
    if not raw_stem.startswith("base") or len(raw_stem) < 16:
        return None
    digits = raw_stem[4:16]
    if not digits.isdigit():
        return None
    yy, mm, dd = digits[0:2], digits[2:4], digits[4:6]
    if not ("01" <= mm <= "12" and "01" <= dd <= "31"):
        return None
    return f"20{yy}{mm}{dd}"


def locate_outputs(out_dir, raw_stem: str, engine: str) -> _RunOutputs:
    """Find the image/proc/sd/combined files a subprocess run wrote for ``raw_stem``, refusing
    any whose stamp names a different engine.

    Globs ``<out_dir>/*<raw_stem>*`` rather than calling ``run_flight.proc_path()`` in this
    process -- see the module docstring. Sorted, so results are deterministic across a
    filesystem's own directory-listing order.
    """
    out_dir = Path(out_dir)
    found: dict[str, Path] = {}
    for p in sorted(out_dir.glob(f"*{raw_stem}*")):
        name = p.name
        if name.endswith((".call", ".call.partial", ".json", ".enhancements")):
            continue
        if not p.is_file():
            continue
        if ".enh." in name or name.endswith(".attributed.nc"):
            # This chain's own products (enh.proc/sd/combined, and the attributed
            # siblings, which carry no .call of their own) are never the port's outputs.
            continue
        if name == f"{raw_stem}.tas.csv":
            # No .call sidecar of its own (S4's reader sidecar) -- collected without the
            # engine-stamp check the other four kinds require.
            found.setdefault("tas_csv", p)
            continue
        if name.startswith("proc."):
            kind = "proc"
        elif name.startswith("sd."):
            kind = "sd"
        elif ".combined." in name:
            kind = "combined"
        elif name in (f"{raw_stem}.H.nc", f"{raw_stem}.V.nc",
                     f"{raw_stem}.H.cdf", f"{raw_stem}.V.cdf"):
            # v3.5's S2 writes ``.H.nc``/``.V.nc``; v3.1.4's writes ``.H.cdf``/``.V.cdf``
            # (``run_flight.py:439``'s own docstring, ``image_path``). found missing
            # for v3.1.4 -- the ``outoffocus`` adapter needs ``outputs.image`` on both
            # engines and silently got ``None`` on v3.1.4 before this fix.
            kind = "image"
        else:
            continue
        stamp = _read_stamp(p)
        if stamp is None:
            raise OutputMissing(f"{p} has no .call sidecar; refusing an unstamped output")
        if _stamp_engine(stamp) != engine:
            raise OutputMissing(
                f"{p} is stamped for engine {_stamp_engine(stamp)!r}, expected {engine!r}: "
                f"{stamp}")
        found.setdefault(kind, p)
    return _RunOutputs(
        out_dir=out_dir, raw_stem=raw_stem, engine=engine,
        image=found.get("image"), proc=found.get("proc"),
        sd=found.get("sd"), combined=found.get("combined"),
        tas_csv=found.get("tas_csv"))


def _preset(cfg: RunConfig):
    """``run_flight.PRESETS[cfg.run['preset']]``, or ``None`` if the config names no preset
    or the preset is unrecognised.

    Reads ``PRESETS`` (a plain dict, built at import time) from
    ``arrayprobe.driver.run_flight``; ``run_flight.main`` is never called and no driver
    global is written. A failed import raises ``ImportError`` with an install instruction
    rather than returning ``None``. Shared by :func:`_preset_probetype` and
    :func:`_preset_pres_pa`.
    """
    preset_name = cfg.run.get("preset")
    if not preset_name:
        return None
    # Read from the installed driver module, so a released (non-checkout) install resolves
    # presets too; only the plain ``PRESETS`` dict is read, no driver global is touched.
    try:
        from arrayprobe.driver.run_flight import PRESETS
    except ImportError as exc:
        raise ImportError(
            "arrayprobe_enhancements.pipeline cannot read the campaign presets: "
            f"arrayprobe.driver.run_flight failed to import ({exc}). Install the core "
            "package (`pip install arrayprobe`) into this environment.") from exc
    return PRESETS.get(cast(str, preset_name))


def _preset_probetype(cfg: RunConfig) -> int | None:
    """``arrayprobe.constants.imgproc_config(PRESETS[cfg.run['preset']].probe).probetype``,
    or ``None`` if the config names no preset or the preset is unrecognised."""
    preset = _preset(cfg)
    if preset is None:
        return None
    from arrayprobe.constants import imgproc_config
    return imgproc_config(preset.probe).probetype


def _preset_pres_pa(cfg: RunConfig) -> float | None:
    """``PRESETS[cfg.run['preset']].pres_pa``, or ``None`` if no preset resolves.

    Deliberately reuses :func:`_preset_probetype`'s private-module loader rather than opening
    a second route to ``run_flight.PRESETS``: two loaders would be two things to keep in step,
    and this module's whole contract is that it never binds to that module's shared globals.

    **Why the value is worth carrying.** Four corrections skipped on a real ARM run with
    *"needs a run pressure not recoverable from the .call stamp"*. The stamp genuinely does not
    carry it -- but the preset does, and the preset name IS in the config. Nothing was missing;
    nothing crossed the boundary.

    ``None`` on any failure, never a default. Pressure enters sample volume, so a guessed
    value would move every concentration in the file while looking entirely ordinary.
    """
    preset = _preset(cfg)
    return None if preset is None else float(preset.pres_pa)


# --- Applying the two wired corrections ---------------------------------------------------


def _copy_netcdf(src, dst) -> None:
    """Byte-for-byte copy of ``src`` to ``dst``; callers then edit it in place (``"r+"``).

    Was a variable-by-variable rebuild (the ``int_arr_rollback_fix.py:265-286`` pattern). That
    preserved format, dimensions, dtypes, attributes and values, and cost 35 min on ARM 07-06's
    810 MB v3.5 proc (2026-09-23 queue log, ``S4c done`` 18:16:14 to the first ``ENHANCED``
    18:51:26), because writing a large unlimited-dimension variable through netCDF4 is slow; the
    corrections that follow touch two variables. A file copy preserves strictly more
    (every byte, including anything the rebuild did not name) at disk speed, and every caller
    opens the copy ``"r+"`` and overwrites the variables it corrects. This function itself
    changes nothing.
    """
    import shutil

    shutil.copyfile(src, dst)


def _stamp_applied(path, names: list[str]) -> None:
    """Append ``names`` to ``enhancements_applied``, never overwrite it.

    reads whatever the file already carries (copied over verbatim by :func:`_copy_netcdf`
    from a prior applier's output, per the chain rule below) and appends only the names not
    already present, so two proc-stage appliers composing onto the same ``.enh.proc.nc`` both
    leave their names in the attribute, comma-joined, in the order they ran
    (:func:`_ordered_for_stage`).
    """
    with netCDF4.Dataset(path, "r+") as ds:
        existing = ds.getncattr("enhancements_applied") if "enhancements_applied" in ds.ncattrs() else ""
        existing_names = [n for n in existing.split(",") if n]
        combined = existing_names + [n for n in names if n not in existing_names]
        ds.enhancements_applied = ",".join(combined)


def _enh_path(outputs: _RunOutputs, kind: str) -> Path:
    """The stage's canonical corrected-file path, ``<stem>.enh.<kind>.nc``."""
    return outputs.out_dir / f"{outputs.raw_stem}.enh.{kind}.nc"


def _enhanced_or_original(outputs: _RunOutputs, kind: str) -> Path | None:
    """Chain rule (plan section 2 step 2): a second proc-stage applier must
    operate on the file the FIRST one already wrote, so corrections compose rather
    than each applier re-deriving from the port's own output. Returns
    ``<stem>.enh.<kind>.nc`` if a prior applier -- or, for ``"sd"``, the S4 rebuild from
    ``enh.proc`` -- wrote it **in this run** (``outputs.fresh``), otherwise the port's own
    ``proc``/``sd`` output (``None`` if that is missing too). A file left by an earlier run
    is never chained onto.
    """
    candidate = _enh_path(outputs, kind)
    if kind in outputs.fresh and candidate.exists():
        return candidate
    return outputs.proc if kind == "proc" else outputs.sd


def _tmp_for(dst: Path) -> Path:
    return dst.with_name(dst.name + ".tmp")


def _tas_qc_path(product: Path) -> Path:
    """``<product>.tasqc.json`` -- the TAS quality record S4 writes beside an sd
    (``arrayprobe.tools.tas_sources.qc_sidecar_path``'s own rule), read by the CF and ARM
    exports."""
    return product.with_name(product.name + ".tasqc.json")


def _carry_tas_qc(record: Path, dst: Path, *, move: bool) -> None:
    """Make ``dst``'s TAS quality record the one at ``record``: moved (an S4 rebuild wrote it
    beside its temporary file) or copied (an sd-stage correction's copy keeps the record of
    the sd it copied). With no record at ``record``, a record left beside ``dst`` by an
    earlier run is removed, because it would describe a different S4 call."""
    import shutil

    target = _tas_qc_path(dst)
    if record.is_file() and target.is_file() and record.resolve() == target.resolve():
        # An sd-stage correction composing onto this run's own `.enh.sd.nc` (the chain
        # rule): the record already sits beside dst, and copying it onto itself raises.
        return
    if not record.is_file():
        target.unlink(missing_ok=True)
    elif move:
        record.replace(target)
    else:
        shutil.copyfile(record, target)


#: One copy of the proc file per stage: a proc-stage applier that edits the file in place
#: (``hole_edge_swap``, ``outoffocus``) edits this run's ``.enh.proc.nc`` directly when an
#: earlier applier in the same stage already wrote it, instead of copying it again. Every byte
#: written is the same either way (``test_pipeline_one_copy_per_stage``); ``False`` restores
#: the copy-per-applier path that test compares against.
_ONE_COPY_PER_STAGE = True


def _proc_edit_target(src: Path, dst: Path) -> Path:
    """The file an in-place proc-stage applier opens ``"r+"``.

    ``dst`` itself when ``src`` is ``dst`` (this run's ``.enh.proc.nc``, written by an earlier
    applier in the stage -- the chain rule) and :data:`_ONE_COPY_PER_STAGE` is on; otherwise a
    full copy of ``src`` at ``dst``'s temporary path, as before. Every in-place applier reads
    and checks before its first write, so a skip leaves ``dst`` untouched.
    """
    if _ONE_COPY_PER_STAGE and Path(src) == Path(dst):
        return dst
    tmp = _tmp_for(dst)
    _copy_netcdf(src, tmp)
    return tmp


def _discard_edit_target(target: Path, dst: Path) -> None:
    """Remove a temporary copy on a skip; never ``dst`` itself, which holds earlier work."""
    if target != dst and target.exists():
        target.unlink()


def _finish_enh_copy(tmp: Path, dst: Path, names: list[str]) -> Path:
    """Stamp ``tmp`` (appending, see :func:`_stamp_applied`) and atomically become ``dst``.

    When ``tmp`` is ``dst`` (an in-place edit, :func:`_proc_edit_target`) it is only stamped.

    ``tmp`` is a fresh file, never ``dst`` itself -- so when a second proc-stage applier
    composes onto the first's output (``src == dst``), the write never opens the same file
    for both read and write at once. Callers must clean up ``tmp`` themselves on any path
    that raises before reaching here (an :class:`ApplierSkip`, in particular).
    """
    _stamp_applied(tmp, names)
    if tmp == dst:
        return dst
    if dst.exists():
        dst.unlink()
    tmp.rename(dst)
    return dst


def _apply_hole_edge_swap(outputs: _RunOutputs) -> Path:
    """C5 -- copy the proc file and un-swap ``max_hole_diameter``/``edge_at_max_hole``.

    ``registry.py:193-201``: stage ``proc``, entry point ``correct_hole_edge_swap``
    (``hole_edge_swap.py:24-34``). Returns ``(edge_at_max_hole, max_hole_diameter)``'s
    corrected values in the same order as its input -- see that function's own docstring.
    """
    from arrayprobe_enhancements.hole_edge_swap import correct_hole_edge_swap
    src = _enhanced_or_original(outputs, "proc")
    if src is None:
        raise ApplierSkip("no proc output found for this raw stem")
    dst = _enh_path(outputs, "proc")
    tmp = _proc_edit_target(src, dst)
    with netCDF4.Dataset(tmp) as ds:
        missing = ("max_hole_diameter" not in ds.variables
                   or "edge_at_max_hole" not in ds.variables)
    if missing:
        _discard_edit_target(tmp, dst)
        raise ApplierSkip("proc file has no max_hole_diameter/edge_at_max_hole")
    with netCDF4.Dataset(tmp, "r+") as ds:
        new_max_hole, new_edge = correct_hole_edge_swap(
            ds.variables["max_hole_diameter"][:], ds.variables["edge_at_max_hole"][:])
        ds.variables["max_hole_diameter"][:] = new_max_hole
        ds.variables["edge_at_max_hole"][:] = new_edge
    return _finish_enh_copy(tmp, dst, ["hole_edge_swap"])


def _apply_overload_accounting_fix(outputs: _RunOutputs) -> Path:
    """A8 -- recompute ``sum_IntArr``/``sample_vol`` for overload-reset seconds.

    ``registry.py:265-274``: stage ``sd``, entry point ``apply_overload_accounting``
    (``overload_accounting_fix.py:83-113``). **Conditional on the run**
    -- a default v3.5 ``sd`` carries neither variable
    (``i_save_int_arr_sv=0`` pinned by ``scripts/run_flight.py``'s ``V35_CALL``,
    ``arrayprobe_uiops/sizedist.py:706``'s write gate) -- until a later change turns that into a named
    refusal inside the enhancement itself, this applier catches the resulting ``KeyError`` and
    turns it into an :class:`ApplierSkip` with the reason string that refusal is expected to
    reuse, so a rename there is caught by whichever test pins this string.
    """
    proc = _enhanced_or_original(outputs, "proc")
    sd = _enhanced_or_original(outputs, "sd")
    if proc is None or sd is None:
        raise ApplierSkip("no proc/sd output pair found for this raw stem")
    from arrayprobe_enhancements.overload_accounting_fix import apply_overload_accounting
    # The proc/sd pair this run's chain holds (enh.proc and the sd rebuilt from it,
    # when a proc-stage correction ran), written through a temp file because `sd` may be
    # the destination itself.
    dst = _enh_path(outputs, "sd")
    tmp = _tmp_for(dst)
    try:
        apply_overload_accounting(proc, sd, tmp)
    except KeyError:
        if tmp.exists():
            tmp.unlink()
        raise ApplierSkip(
            "sd lacks sum_IntArr/sample_vol (iSaveIntArrSV=0)") from None
    return _finish_enh_copy(tmp, dst, ["overload_accounting_fix"])


def _apply_particle_number_all_fix(outputs: _RunOutputs) -> Path:
    """C5b -- drop the always-fill-valued ``Particle_number_all`` column, where the file
    was written by a probetype the module's own write guard never fills it for.

    ``registry.py:328-335``: stage ``proc``, entry point ``corrected_proc_file``
    (``particle_number_all_fix.py:135``). **No-op on the 2D-S demo, by construction**: probe
    type 2 writes the column correctly (audited, not assumed -- ``audit_proc_file`` reports
    ``all_fill=False`` on the tracked demo proc files), so ``corrected_proc_file`` would
    refuse (it declines to drop a variable that carries real data) -- this applier checks the
    audit first and records that refusal as a named, expected skip rather than letting the
    module's ``ValueError`` propagate.
    """
    from arrayprobe_enhancements.particle_number_all_fix import (
        audit_proc_file,
        corrected_proc_file,
    )
    src = _enhanced_or_original(outputs, "proc")
    if src is None:
        raise ApplierSkip("no proc output found for this raw stem")
    report = audit_proc_file(src)
    if not report["present"]:
        # Nothing to drop: an applied copy would be stamped with a correction that changed
        # nothing, and would trigger an S4 rebuild of an unchanged proc.
        raise ApplierSkip("Particle_number_all is absent from this proc file: nothing to drop")
    if not report["all_fill"]:
        raise ApplierSkip(
            "Particle_number_all carries real values (C5b no-op: this probetype "
            "writes it correctly, nothing to drop)")
    dst = _enh_path(outputs, "proc")
    tmp = _tmp_for(dst)
    corrected_proc_file(src, tmp)
    return _finish_enh_copy(tmp, dst, ["particle_number_all_fix"])


def _apply_particle_time_glitch_fix(outputs: _RunOutputs):
    """A5 at the probetype-1 site -- repair glitched header particle times, drop only
    the unrecoverable particles, so ``sizeDist.m:544-545`` cannot cascade.

    ``registry.py``: stage ``proc``, entry point ``corrected_proc_file``
    (``particle_time_glitch_fix.py``). Probetype from ``[run].preset``, as for
    ``particle_time_int8_fix``; every probetype but 1 is a named skip, because only probetype 1
    files particles on the header clock. Runs **before** ``int_arr_rollback_fix`` in
    :data:`_APPLIERS` order: a glitched ``Time_in_seconds`` (0, or 115444 for the all-ones header)
    is a backward step that module would otherwise read as a clock rollback. Returns the path and
    the module's counts, which :func:`apply_enhancements` records under ``details`` in the
    provenance sidecar -- the dropped count travels with the file.
    """
    from arrayprobe_enhancements.particle_time_glitch_fix import corrected_proc_file
    if outputs.preset_probetype is None:
        raise ApplierSkip(
            "probetype not recoverable: no [run].preset in the config, or the preset "
            "is unrecognised, and the .call stamp does not carry probetype")
    if outputs.preset_probetype != 1:
        raise ApplierSkip(f"probetype {outputs.preset_probetype} files on the record Time, "
                          "not the particle header clock (sizeDist.m:515-537)")
    src = _enhanced_or_original(outputs, "proc")
    if src is None:
        raise ApplierSkip("no proc output found for this raw stem")
    dst = _enh_path(outputs, "proc")
    tmp = _tmp_for(dst)
    policy = (outputs.policies.get("particle_time_glitch_fix") or {}).get("policy")
    report = (corrected_proc_file(src, tmp, 1) if policy is None
              else corrected_proc_file(src, tmp, 1, policy=policy))
    side = Path(f"{tmp}.particle_time_glitch_fix.json")
    if side.exists():
        side.unlink()   # the counts travel in the provenance sidecar instead
    # ``policy`` and ``applied`` (what the policy did) travel with ``counts``: under
    # ``policy="drop"`` the classifier's ``counts`` still say how many particles could have
    # been recovered, and read alone they describe a repair that never happened.
    details = {"policy": report["policy"], "applied": report["applied"],
               "counts": report["counts"], "written": report["written"],
               "port_cascade_before": report["port_cascade_before"],
               "port_cascade_after": report["port_cascade_after"]}
    return _finish_enh_copy(tmp, dst, ["particle_time_glitch_fix"]), details


def _apply_int_arr_rollback_fix(outputs: _RunOutputs) -> Path:
    """D3c -- give probetype 1 the clock-rollback correction probetype 0 and 2 already have.

    ``registry.py:360-367``: stage ``proc``, entry point ``proc_file_with_rollback_corrected``
    (``int_arr_rollback_fix.py:255``), called with ``step=SECONDS_PER_DAY`` -- the midnight
    reading, the same value the in-test proof used.

    **Gated on probetype since 2026-09-23**, as ``particle_time_int8_fix`` already is:
    until then this adapter ran unconditionally and applied a probetype-1 midnight step to
    every 2D-S (probetype 2) file, measured on ACE-ENA 0707 as a ``Time_in_seconds`` ending at
    17,194,735 s. That was inert only because no sd was rebuilt from ``enh.proc``; the chain
    below now rebuilds one, so the gate is what keeps a wrong correction out of every
    concentration. On an affected probetype, 0 rollbacks is still a valid applied outcome.
    """
    from arrayprobe_enhancements.int_arr_rollback_fix import (
        AFFECTED_PROBETYPES,
        SECONDS_PER_DAY,
        proc_file_with_rollback_corrected,
    )
    if outputs.preset_probetype is None:
        raise ApplierSkip(
            "probetype not recoverable: no [run].preset in the config, or the preset "
            "is unrecognised, and the .call stamp does not carry probetype")
    if outputs.preset_probetype not in AFFECTED_PROBETYPES:
        raise ApplierSkip(
            f"probetype {outputs.preset_probetype} not affected (D3c is probetype "
            f"{AFFECTED_PROBETYPES[0]}'s missing branch; this probetype's clock is corrected "
            "by sizeDist.m:852-856 itself or is not a time of day)")
    src = _enhanced_or_original(outputs, "proc")
    if src is None:
        raise ApplierSkip("no proc output found for this raw stem")
    dst = _enh_path(outputs, "proc")
    tmp = _tmp_for(dst)
    proc_file_with_rollback_corrected(src, tmp, step=SECONDS_PER_DAY,
                                      probetype=outputs.preset_probetype)
    return _finish_enh_copy(tmp, dst, ["int_arr_rollback_fix"])


def _apply_particle_time_int8_fix(outputs: _RunOutputs) -> Path:
    """A15 -- recover ``particle_time`` for 2DC/2DP/Fast2DC (probetype 0/3) where an int8
    hour/minute/second seed saturates it to 127.

    ``registry.py:277-285``: stage ``proc``, entry point ``corrected_proc_file``
    (``particle_time_int8_fix.py:410``). **Probetype comes from ``[run].preset``**
    (``outputs.preset_probetype``, resolved in :func:`apply_enhancements`) -- the ``.call``
    stamp does not carry it (measured: neither tracked demo ``.call`` sidecar mentions
    ``probetype``). The module's own guard (``AFFECTED_PROBETYPES = (0, 3)``) refuses every
    other probetype; this applier checks that guard itself first so the 2D-S demo's
    probetype-2 case is a *named* skip rather than a caught ``ValueError``.
    """
    from arrayprobe_enhancements.particle_time_int8_fix import (
        AFFECTED_PROBETYPES,
        corrected_proc_file,
    )
    if outputs.preset_probetype is None:
        raise ApplierSkip(
            "probetype not recoverable: no [run].preset in the config, or the preset "
            "is unrecognised, and the .call stamp does not carry probetype")
    probetype = outputs.preset_probetype
    if probetype not in AFFECTED_PROBETYPES:
        raise ApplierSkip(f"probetype {probetype} not affected (A15)")
    src = _enhanced_or_original(outputs, "proc")
    if src is None:
        raise ApplierSkip("no proc output found for this raw stem")
    dst = _enh_path(outputs, "proc")
    tmp = _tmp_for(dst)
    try:
        corrected_proc_file(src, tmp, probetype, require_exact_replay=True)
    except ValueError as exc:
        if tmp.exists():
            tmp.unlink()
        raise ApplierSkip(str(exc)) from None
    return _finish_enh_copy(tmp, dst, ["particle_time_int8_fix"])


def _apply_outoffocus(outputs: _RunOutputs) -> Path:
    """A12 -- rerun the reject stage with the hollow block forced on, recompute
    ``part_z``/``size_factor``, and apply the correction to ``image_diam_minR`` and
    ``image_area`` with the module defaults: ``direction="korolev"`` (``D_0 = D_m /
    size_factor``, Korolev 2007 §2 p. 377; the dead ``sizeDist.m:793`` multiply ran the wrong
    way, K2x 2026-09-15) and ``area_mode="sphere"`` (an open question).
    Both mode values are written into the copy as global attributes
    ``outoffocus_direction`` / ``outoffocus_area_mode``.

    ``registry.py:256-263``: stage ``proc``, entry point ``apply_outoffocus``
    (``outoffocus.py:134``). The reject configuration is the pair
    ``scripts/outoffocus_ab.py`` already selects by engine:
    ``ORACLES_PRODUCTION_REJECT_CONFIG`` (v3.1.4) or
    ``arrayprobe_uiops.measure.STOCK_V35_REJECT_CONFIG`` (v3.5) -- imported by the same names
    so a change there is not silently missed here.
    """
    try:
        from arrayprobe_enhancements.outoffocus import apply_outoffocus
    except ModuleNotFoundError as exc:
        if exc.name != "arrayprobe_enhancements.outoffocus":
            raise
        raise ImportError(
            "outoffocus is missing from this installation: it ships with the enhancements "
            "package and runs on both engines (--engine 3.5 or 3.1.4), so reinstall "
            "arrayprobe-enhancements"
        ) from exc
    if outputs.image is None:
        raise ApplierSkip("no image output found for this raw stem")
    src = _enhanced_or_original(outputs, "proc")
    if src is None:
        raise ApplierSkip("no proc output found for this raw stem")
    if outputs.engine == "3.5":
        from arrayprobe_uiops.measure import STOCK_V35_REJECT_CONFIG as config
    else:
        from arrayprobe_uiops.reject_core import (
            ORACLES_PRODUCTION_REJECT_CONFIG as config,  # type: ignore[no-redef]  # engine-selected constant, one branch runs
        )
    dst = _enh_path(outputs, "proc")
    tmp = _proc_edit_target(src, dst)
    try:
        with netCDF4.Dataset(outputs.image) as image_ds, netCDF4.Dataset(tmp, "r+") as proc_ds:
            if "image_diam_minR" not in proc_ds.variables:
                raise ApplierSkip("proc file has no image_diam_minR")
            res = apply_outoffocus(image_ds, proc_ds, config=config, engine=outputs.engine,
                                   jobs=outputs.jobs)
            proc_ds.variables["image_diam_minR"][res.indices] = res.corrected_diam
            proc_ds.variables["image_area"][res.indices] = res.corrected_area
            proc_ds.setncattr("outoffocus_direction", res.direction)
            proc_ds.setncattr("outoffocus_area_mode", res.area_mode)
    except ApplierSkip:
        _discard_edit_target(tmp, dst)
        raise
    return _finish_enh_copy(tmp, dst, ["outoffocus"])


def _apply_pressure_units_fix(outputs: _RunOutputs) -> Path:
    """B7 -- rerun ``sizedist.run()`` with a pressure in hPa, as ``single_vt.m``'s own
    docstring documents, instead of the ORACLES drivers' raw ``9e5``.

    ``registry.py:380-387``: stage ``sd``, entry point ``sd_file_at_pressure``
    (``pressure_units_fix.py:186``). **Stop condition** (plan section 2 step 2, ranked
    uncertainty 2): the run's own pressure/projectname/iat_file live in
    ``scripts/run_flight.py``'s ``CampaignPreset``, never in the ``.call`` stamp (measured:
    neither tracked demo ``.call`` sidecar mentions a pressure field) -- so this applier
    refuses rather than reach into the preset for ``pres_pa`` and pass it off as
    provenance-verified. Guessing the ORACLES-preset value (``9e5``) would happen to be
    numerically right for the demo and wrong in general, which is worse than a named gap.
    """
    if outputs.sd is None:
        raise ApplierSkip("no sd output found for this raw stem")
    stamp = _read_stamp(outputs.sd) or ""
    # If a future .call stamp starts carrying "pres=" (or "pressure="), wiring the actual
    # correction from it is deliberately left to a later change (stamping the preset's
    # pressure in the sd .call) -- this applier only checks and refuses today.
    if "pres=" in stamp.lower() or "pressure=" in stamp.lower():
        raise ApplierSkip("run pressure found in the .call stamp, but no adapter is wired to use it yet")
    raise ApplierSkip("run pressure not recoverable from the .call stamp")


def _apply_arco_export(outputs: _RunOutputs) -> Path:
    """Analysis-ready (chunked, per-variable-compressed) re-encode of the sd output.

    ``registry.py:400-407``: stage ``product``, entry point ``export`` (``arco_export.py:141``).
    Operates on this run's most-corrected ``sd`` (a prior sd-stage applier's ``.enh.sd.nc`` if
    one ran, else the port's own ``sd``) -- a product export is a terminal step, not itself
    chained onto by anything else, so no round-trip temp file is needed here.
    """
    from arrayprobe_enhancements.arco_export import export
    src = _enhanced_or_original(outputs, "sd")
    if src is None:
        raise ApplierSkip("no sd output found for this raw stem")
    dst = outputs.out_dir / f"{outputs.raw_stem}.enh.arco.nc"
    export(src, dst)
    _stamp_applied(dst, ["arco_export"])
    return dst


def _apply_arm_export(outputs: _RunOutputs) -> Path:
    """An ARM Data File Standards structural copy of the sd output.

    ``registry.py:459-466``: stage ``product``, entry point ``export`` (``arm_export.py:141``).
    Operates on this run's most-corrected ``sd``, the same source :func:`_apply_arco_export`
    reads -- a product export, so no round-trip temp file is needed here either.

    **Refuses rather than invents**, on two independent facts neither the ``.call`` stamp nor
    the raw file can supply: the real ARM ``site_id``/``platform_id``/``facility_id``
    (``outputs.arm``, threaded from the config's ``[arm]`` table -- see :class:`_RunOutputs`)
    and the flight's UTC date (``outputs.flight_date``, read off the raw stem, ``None`` for a
    stem :func:`_flight_date_from_stem` does not recognise). ``arm_export.py``'s own rule is
    that the three identifiers are "never invented"; this adapter is what closes the ARM export site ids without
    weakening that rule -- absent ``[arm]`` is a named skip, exactly as it was before this
    adapter existed, never a placeholder identifier. ``data_level`` falls back to
    ``export()``'s own default (``"c1"``, DOE/SC-ARM-15-004 S5.1.3's "derived/calculated VAP
    output") when the config names none -- a documented category, not a site fact, so that
    fallback is not the kind of guess the three required ids are refused for making.
    """
    from arrayprobe_enhancements.arm_export import export
    src = _enhanced_or_original(outputs, "sd")
    if src is None:
        raise ApplierSkip("no sd output found for this raw stem")
    if not outputs.arm:
        raise ApplierSkip(
            "no [arm] section in the run config: site_id/platform_id/facility_id are never "
            "invented or defaulted (arm_export.py's own rule) -- add [arm] with the real ARM "
            "identifiers for this deployment to enable this export")
    missing = sorted(k for k in ("site_id", "platform_id", "facility_id")
                     if not outputs.arm.get(k))
    if missing:
        # Defence in depth: arrayprobe.config._load_arm already refuses a partial [arm] table
        # at load time, so a valid RunConfig can never reach here with any of these three
        # missing -- this is the same "assert what an earlier check already guarantees" pattern
        # cf_export.write_variables uses for its own unmapped-name invariant.
        raise ApplierSkip(f"[arm] is missing {missing}; refusing rather than guessing a real "
                          "ARM identifier")
    if outputs.flight_date is None:
        raise ApplierSkip(f"flight date could not be read from the raw stem "
                          f"{outputs.raw_stem!r}; arm_export needs an explicit date and "
                          "never guesses one")
    fd = outputs.flight_date
    flight_date = _dt.date(int(fd[0:4]), int(fd[4:6]), int(fd[6:8]))
    dst = outputs.out_dir / f"{outputs.raw_stem}.enh.arm.nc"
    lineage = _sd_lineage(outputs)
    # OUTPUT 3: the ARM file carries the same call stamp and the same chain record the
    # attributed enhanced combined (OUTPUT 2) carries, plus which sd it was built from.
    from arrayprobe_enhancements.cf_export import CfExportError
    try:
        export(src, dst, flight_date=flight_date,
              site_id=outputs.arm["site_id"], platform_id=outputs.arm["platform_id"],
              facility_id=outputs.arm["facility_id"],
              data_level=outputs.arm.get("data_level", "c1"),
              engine=outputs.engine, stage="sd", call_stamp=_read_stamp(src),
              enhancements_report=json.dumps(outputs.chain, sort_keys=True))
    except CfExportError as exc:
        # The variable pass is cf_export's (a unit or variable it will not map), so its refusal
        # is handled as _apply_cf_export handles it: a skip of this one export, recorded in the
        # provenance, never a failure of every other correction in the pass or a half-written
        # file left behind.
        dst.unlink(missing_ok=True)
        raise ApplierSkip(f"arm_export refused this output: {exc}") from exc
    with netCDF4.Dataset(dst, "r+") as ds:
        ds.setncattr("arrayprobe_sd_lineage", lineage)
        ds.setncattr("arrayprobe_sd_source", src.name)
    _stamp_applied(dst, ["arm_export"])
    return dst


def export_faithful_arm(out_dir, raw_stem: str, engine: str, arm: dict) -> Path:
    """OUTPUT 3 from the faithful lineage: an ARM-format copy of the port's own ``sd``.

    Selected by ``[outputs] arm = "faithful"``. The same ``arm_export.export`` call and the
    same refusals as :func:`_apply_arm_export` (no ``[arm]`` identifiers, no flight date, a
    variable ``cf_export`` will not map: each an :class:`ApplierSkip` naming why), but the
    source is always the port's ``sd`` -- never an ``enh.*`` file, even one left on disk -- and
    the product is ``<raw_stem>.arm.nc`` with ``arrayprobe_lineage = "faithful"`` and
    ``arrayprobe_sd_lineage = "port"``. Its ``.call`` is the sd's stamp, verbatim: nothing was
    applied, so no enhancement block is added. The port's ``sd`` is only read.
    """
    outputs = locate_outputs(out_dir, raw_stem, engine)
    src = outputs.sd
    if src is None:
        raise ApplierSkip("no sd output found for this raw stem")
    if not arm:
        raise ApplierSkip(
            "no [arm] section in the run config: site_id/platform_id/facility_id are never "
            "invented or defaulted (arm_export.py's own rule) -- add [arm] with the real ARM "
            "identifiers for this deployment to enable this export")
    fd = _flight_date_from_stem(raw_stem)
    if fd is None:
        raise ApplierSkip(f"flight date could not be read from the raw stem {raw_stem!r}; "
                          "arm_export needs an explicit date and never guesses one")
    from arrayprobe_enhancements.arm_export import export
    from arrayprobe_enhancements.cf_export import CfExportError
    dst = outputs.out_dir / f"{raw_stem}.arm.nc"
    stamp = _read_stamp(src)
    try:
        export(src, dst, flight_date=_dt.date(int(fd[0:4]), int(fd[4:6]), int(fd[6:8])),
               site_id=arm["site_id"], platform_id=arm["platform_id"],
               facility_id=arm["facility_id"], data_level=arm.get("data_level", "c1"),
               engine=engine, stage="sd", call_stamp=stamp)
    except CfExportError as exc:
        dst.unlink(missing_ok=True)
        raise ApplierSkip(f"arm_export refused this output: {exc}") from exc
    with netCDF4.Dataset(dst, "r+") as ds:
        ds.setncattr("arrayprobe_lineage", "faithful")
        ds.setncattr("arrayprobe_sd_lineage", "port")
        ds.setncattr("arrayprobe_sd_source", src.name)
    if stamp is not None:
        dst.with_name(dst.name + ".call").write_text(stamp + "\n")
    return dst


def _apply_cf_export(outputs: _RunOutputs) -> Path:
    """A CF-1.10 sibling of the sd output, with a real CF time axis.

    ``registry.py:473-482``: stage ``product``, entry point ``export`` (``cf_export.py:311``).
    Operates on this run's most-corrected ``sd``, the same source :func:`_apply_arm_export`
    reads -- a product export, so no round-trip temp file is needed here either.

    **Refuses rather than invents**, on the one fact neither the ``.call`` stamp nor the raw
    file itself can supply reliably: the flight's UTC date (``outputs.flight_date``, read off
    the raw stem, ``None`` for a stem :func:`_flight_date_from_stem` does not recognise).
    ``cf_export.py``'s own rule is the same as ``arm_export``'s -- "a date is never read off a
    file name" inside that module, so this adapter supplies the one already derived for the
    whole run rather than guessing a second time.
    """
    from arrayprobe_enhancements.cf_export import CfExportError, export
    src = _enhanced_or_original(outputs, "sd")
    if src is None:
        raise ApplierSkip("no sd output found for this raw stem")
    if outputs.flight_date is None:
        raise ApplierSkip(f"flight date could not be read from the raw stem "
                          f"{outputs.raw_stem!r}; cf_export needs an explicit date and "
                          "never guesses one")
    fd = outputs.flight_date
    flight_date = _dt.date(int(fd[0:4]), int(fd[4:6]), int(fd[6:8]))
    dst = outputs.out_dir / f"{outputs.raw_stem}.enh.cf.nc"
    try:
        export(src, dst, flight_date=flight_date, engine=outputs.engine,
              call_stamp=_read_stamp(src))
    except CfExportError as exc:
        # A refusal about this file's content (e.g. a repeated second the port preserves,
        # sizeDist.m:98-99) is a skip of this one export, recorded in the provenance -- not a
        # failure of every other correction in the pass. ARM 2017-07-08, 2026-09-24: time
        # repeated at 82944 and the refusal aborted the whole enhancement pass.
        dst.unlink(missing_ok=True)
        raise ApplierSkip(f"cf_export refused this output: {exc}") from exc
    _stamp_applied(dst, ["cf_export"])
    return dst


def _apply_published_dof(outputs: _RunOutputs) -> Path:
    """airspeed and size-dependent depth of field -- rescale the sd file's volume-normalised variables to Gurganus & Lawson
    (2018)'s 2D-S depth of field. **ON by default** (it was default-OFF earlier):
    a config isolates it with ``published_dof = false``.

    TAS comes from the run's own ``<stem>.tas.csv`` (the reader sidecar), used only to check
    G&L's 190 m/s envelope; ``armdst`` from ``arrayprobe_uiops.sizedist_tables.probe_defaults``
    for the sd file's own ``Project`` / probe attributes and this run's engine -- the same
    table the engine read. Refusals (HVPS, CIP, TAS > 190 m/s) become named skips.
    """
    from arrayprobe.readers.tasinfo import load_tas_info
    from arrayprobe_uiops.sizedist_tables import probe_defaults

    from arrayprobe_enhancements.published_dof import ProbeNotCovered, corrected_sd_file
    src = _enhanced_or_original(outputs, "sd")
    if src is None:
        raise ApplierSkip("no sd output found for this raw stem")
    if outputs.tas_csv is None:
        raise ApplierSkip("no <stem>.tas.csv: TAS is needed to check Gurganus & Lawson "
                          "(2018)'s 190 m/s envelope")
    _t, tas = load_tas_info(outputs.tas_csv)
    with netCDF4.Dataset(src) as ds:
        attrs = ds.ncattrs()
        probe = str(ds.getncattr("Probe Type" if "Probe Type" in attrs else "Probe_Type"))
        project = str(ds.getncattr("Project"))
    armdst = probe_defaults(project, probe, version=outputs.engine).armdst
    dst = _enh_path(outputs, "sd")
    tmp = _tmp_for(dst)
    try:
        corrected_sd_file(src, tmp, armdst=armdst, tas=tas, enabled=True)
    except ProbeNotCovered as exc:
        if tmp.exists():
            tmp.unlink()
        raise ApplierSkip(str(exc)) from None
    return _finish_enh_copy(tmp, dst, ["published_dof"])


def _hhmmss_to_seconds(hhmmss: np.ndarray) -> np.ndarray:
    """An sd ``time`` axis (``HHMMSS``, past 240000 after midnight) as seconds of day."""
    v = np.asarray(hhmmss, dtype=np.float64).astype(np.int64)
    return (v // 10000) * 3600 + (v // 100 % 100) * 60 + v % 100


def _apply_field2006_shatter(outputs: _RunOutputs) -> Path:
    """Process2D-derived (NCAR ``aircraft_oap``, Apache-2.0) Field et al. (2006) per-second
    inter-arrival fit -- an opt-in enhancement, never part of an engine.

    Reads every particle's ``inter_arrival`` and ``Time_in_seconds`` from the proc file, in
    file order, runs :func:`arrayprobe_enhancements.field2006_shatter.apply`, and writes a copy
    of the sd as ``<stem>.enh.sd.nc`` holding the five per-second fit diagnostics
    (``write_diagnostics``) and every ``conc*`` variable on the ``Time`` dimension multiplied
    by Process2D's ``corrfac`` (NaN read as 1, ``process2d.cpp:1075-1079``). The engine's own
    proc and sd are never opened for writing. The engine's shattering pass is left as it ran:
    this applies the Field-2006 count correction to its distribution and records the fit; the
    per-particle Process2D mask is not re-applied to the sd. The copy carries the
    ``field2006_stamp`` global attribute (``field2006=process2d-derived ...``).
    """
    from arrayprobe_enhancements import field2006_shatter as f06
    proc = _enhanced_or_original(outputs, "proc")
    if proc is None:
        raise ApplierSkip("no proc output found for this raw stem")
    src = _enhanced_or_original(outputs, "sd")
    if src is None:
        raise ApplierSkip("no sd output found for this raw stem")
    with netCDF4.Dataset(proc) as ds:
        missing = [v for v in ("inter_arrival", "Time_in_seconds") if v not in ds.variables]
        if missing:
            raise ApplierSkip(f"proc file has no {', '.join(missing)}")
        inttime = np.asarray(ds.variables["inter_arrival"][:], dtype=np.float64).reshape(-1)
        tsec = np.asarray(ds.variables["Time_in_seconds"][:], dtype=np.float64).reshape(-1)
    second = np.floor(tsec)
    if second.size and np.any(np.diff(second) < 0):
        raise ApplierSkip("proc Time_in_seconds is not in time order; the Process2D queue "
                          "needs particles in arrival order")
    result = f06.apply(inttime, second)
    with netCDF4.Dataset(src) as ds:
        if "Time" not in ds.dimensions or "time" not in ds.variables:
            raise ApplierSkip("sd file has no Time dimension or time variable")
        axis = _hhmmss_to_seconds(ds.variables["time"][:])
    diagnostics = f06.align_to_axis(result, axis)
    factor = f06.applied_corrfac(diagnostics["field2006_corrfac"])
    dst = _enh_path(outputs, "sd")
    tmp = _tmp_for(dst)
    if tmp.exists():
        tmp.unlink()
    f06.write_diagnostics(str(src), str(tmp), "Time", diagnostics)
    with netCDF4.Dataset(tmp, "r+") as ds:
        for name, var in ds.variables.items():
            if "conc" not in name.lower() or "Time" not in var.dimensions:
                continue
            if var.dtype.kind != "f":
                continue
            shape = [1] * var.ndim
            shape[var.dimensions.index("Time")] = factor.size
            var[:] = np.asarray(var[:], dtype=np.float64) * factor.reshape(shape)
        ds.setncattr("field2006_concentrations", "conc* variables on Time multiplied by "
                     "the Process2D-derived corrfac (NaN read as 1)")
    _carry_tas_qc(_tas_qc_path(src), dst, move=False)
    return _finish_enh_copy(tmp, dst, ["field2006_shatter"])


#: name -> callable(outputs) -> Path | raises ApplierSkip. S3 wired the first two; later work adds
#: six more (plan section 2, step 2) -- ``particle_number_all_fix`` and
#: ``int_arr_rollback_fix`` and ``particle_time_int8_fix`` and ``outoffocus`` compose onto the
#: same ``.enh.proc.nc`` in this dict's iteration order (the chain rule, ``_enhanced_or_original``);
#: ``pressure_units_fix`` always records a named skip today (no adapter reaches the run's own
#: pressure -- see its docstring); ``arco_export`` and ``arm_export`` are the two
#: product-stage adapters. Every other registered, entry-pointed enhancement is still recorded
#: ``"no driver adapter yet"``.
_APPLIERS = {
    "hole_edge_swap": _apply_hole_edge_swap,
    "particle_number_all_fix": _apply_particle_number_all_fix,
    "particle_time_glitch_fix": _apply_particle_time_glitch_fix,
    "int_arr_rollback_fix": _apply_int_arr_rollback_fix,
    "particle_time_int8_fix": _apply_particle_time_int8_fix,
    "outoffocus": _apply_outoffocus,
    "overload_accounting_fix": _apply_overload_accounting_fix,
    "published_dof": _apply_published_dof,
    "field2006_shatter": _apply_field2006_shatter,
    "pressure_units_fix": _apply_pressure_units_fix,
    "arco_export": _apply_arco_export,
    "arm_export": _apply_arm_export,
    "cf_export": _apply_cf_export,
}

#: Modules with no driver adapter, and why -- the design record's "Not wired" list (section 2 step 2).
#: Read by :func:`apply_enhancements` only when a name is both resolved ON and absent from
#: :data:`_APPLIERS`, so the sidecar's ``skipped`` reason is self-explaining instead of the
#: generic ``_NO_ADAPTER_REASON``.
_NO_ADAPTER_REASON_BY_NAME: dict[str, str] = {
    "dmax_sensitivity": "no driver adapter: reports a spread across definitions, writes no "
                        "corrected file",
    "spot_edge_fix": "no driver adapter: needs area_ratio, not a stored proc/sd column",
    "wide_hollow_fix": "no driver adapter: needs a reconstructed particle image, not a "
                       "proc/sd column",
    "rollover_fix": "no driver adapter: in-memory time-array correction, no proc/sd file "
                    "shape to copy-then-correct",
    "tas_grid_fix": "no chain adapter: run_flight.py applies it inside S4 itself "
                    "(DRIVER_PROTECTIVE; regular grid with a TAS chain, collapsed probe grid "
                    "without), stamped tas_grid= in the sd .call",
    "effective_density": "no driver adapter: needs area_ratio, not a stored proc/sd column",
    "distance_rejection": "no driver adapter: needs tas and a threshold_distance, neither a "
                          "proc/sd column",
    "poisson_restore": "no driver adapter: needs false_rejection_fraction from a separate "
                       "inter-arrival analysis",
    "intarr_policy": "no driver adapter: the rule acts on the threshold file sizeDist reads "
                     "(write_threshold_file) and the neighbour count inside sizeDist's "
                     "per-second flagging, both before any sd file exists",
    "analysis": "no driver adapter: an analysis, not a correction; writes no file",
    "poisson_uncertainty": "no driver adapter: an analysis, not a correction; writes no file",
    "probe_crossover": "no driver adapter: compares two probes' sd files, and a run "
                       "processes one probe; writes no file",
    "particle_clustering": "no driver adapter: an analysis, writes a labels sidecar rather "
                           "than a corrected proc/sd file; whether the driver should run "
                           "analyses at all is not yet decided",
    "ml_accept_reject": "no driver adapter: an analysis (CNN suggestion), writes no "
                        "corrected file",
    "spec_artefact_filter": "no driver adapter: an analysis, writes no corrected file",
    "reaccept_every_event_fix": "no driver adapter: re-running sizeDist needs the run's own "
                                "call arguments (pressure, threshold file), not recoverable "
                                "from the .call stamp -- same gap as pressure_units_fix; use "
                                "reaccept_every_event_fix.run_sizedist(..., "
                                "reaccept_every_event=True) from Python",
    "partial_image_habit": "no driver adapter: a population analysis that writes no "
                           "corrected file, and no retrieval matrix is held for any probe "
                           "this driver runs -- Korolev & Sussman (2000)'s are the "
                           "OAP-2DC's and do not transfer (p. 1057)",
}

_STAGE_ORDER = ("proc", "sd", "product")


def _ordered_for_stage(reg, stage: str) -> list[str]:
    """The registered names at ``stage``, in the order the chain applies them: every name with
    an adapter in :data:`_APPLIERS`'s order, then the rest in registry order (those are only
    ever recorded as skips, so their order changes nothing).

    The chain composes onto one ``enh.proc``/``enh.sd``, so the order is part of the result.
    It is :data:`_APPLIERS`'s, not the registry's: ``particle_time_glitch_fix`` must repair a
    glitched probetype-1 header time before ``int_arr_rollback_fix`` reads the clock, or the
    glitch is taken for a midnight crossing and a day is added to every later particle --
    and the registry lists the two the other way round.
    """
    rank = {name: i for i, name in enumerate(_APPLIERS)}
    names = [name for name, spec in reg.items() if spec.stage == stage]
    return sorted(names, key=lambda name: rank.get(name, len(rank)))

_NO_STAGE_REASON = "no file stage"
_NO_ENTRY_POINT_REASON = "no entry_point"
_NO_ADAPTER_REASON = "no driver adapter yet"


def _reader_stage_reason(spec) -> str:
    """Why a reader-stage enhancement (``spec.stage == "reader"``) cannot be applied by this
    driver (2026-09-21), refusal idiom matching :data:`_NO_ADAPTER_REASON_BY_NAME`'s
    named, explanatory skip strings.

    Built from ``spec`` alone (never a name list), so a new module registered with
    ``stage="reader"`` is refused with its own name and its own entry point the moment it is
    registered -- no edit here. Names the module, states plainly that it acts during decode
    rather than on a finished output, and says what to do instead: call the module's own
    entry point directly, before ``arrayprobe-enhanced run``, rather than after it.
    """
    call = (f"arrayprobe_enhancements.{spec.name}.{spec.entry_point}"
            if spec.entry_point else f"arrayprobe_enhancements.{spec.name}")
    return (
        f"{spec.name} is reader-stage: it acts during decode, before the port ever ran, "
        f"and this driver only corrects proc/sd/product files the port already wrote -- "
        f"there is nothing post hoc to correct here. A re-decode path is out of scope; "
        f"run the decode with the correction active instead -- call {call} "
        f"yourself, in place of the port's own reader, before running "
        f"`arrayprobe-enhanced run`."
    )


def _package_version(name: str) -> str:
    try:
        from importlib.metadata import version
        return version(name)
    except Exception:
        return "unknown"


def _build_provenance(engine: str, config_path, resolved: dict[str, bool],
                      applied: list[str], skipped: dict[str, str],
                      lineage: Lineage, outputs: dict[str, str] | None = None,
                      details: dict[str, dict] | None = None,
                      stages: dict[str, list[str]] | None = None,
                      rebuilt: dict[str, str] | None = None,
                      chain_error: str | None = None) -> dict:
    """The ``.enhancements.json`` payload -- deterministic (sorted keys, no timestamps) so
    the chunked-run identity test (plan section 2, test ``test_sidecar_identical_for_chunks_1_
    and_2``) is a byte compare.

    ``outputs`` maps each *applied* name to the file name it wrote, relative to
    ``out_dir`` -- the half of the upstream misreported shattering attribute's complaint the ``applied`` list alone leaves open:
    a list of names says what ran, not which file each one produced.

    ``details`` maps an applied name to the counts its applier reported -- e.g.
    ``particle_time_glitch_fix``'s recovered and dropped particles -- so what a correction
    removed is recorded beside the file it wrote. Empty for appliers that report nothing.
    """
    applicability_for_engine = {
        name: entry.state.get(engine, "unestablished")
        for name, entry in sorted(lineage.applicability.APPLICABILITY.items())
    }
    tags = {
        name: sorted(entry.tags)
        for name, entry in sorted(lineage.applicability.APPLICABILITY.items())
    }
    return {
        "engine": engine,
        "config_path": str(config_path),
        "resolved": dict(sorted(resolved.items())),
        "applied": sorted(applied),
        "outputs": dict(sorted((outputs or {}).items())),
        "details": dict(sorted((details or {}).items())),
        "skipped": dict(sorted(skipped.items())),
        # Which names acted at which stage (in the order applied), which port stages
        # were re-run on the enhanced input and the file each wrote, and -- when a proc-stage
        # correction ran but no sd could be rebuilt from it -- why. An enhanced product is
        # traceable to its chain from this record alone.
        "stages": {k: list(v) for k, v in (stages or {}).items()},
        "rebuilt": dict(sorted((rebuilt or {}).items())),
        "chain_error": chain_error,
        "applicability": applicability_for_engine,
        "tags": tags,
        "versions": {
            "arrayprobe": _package_version("arrayprobe"),
            "arrayprobe_enhancements": _package_version("arrayprobe-uiops-enhancements"),
        },
    }


# --- The orchestrator ------------------------------------------------------------------------


def apply_enhancements(config_path, raws, *, chunks: int = 1, jobs: int = 1, s2_jobs: int = 1,
                       python: str = sys.executable, lineage: Lineage = UIOPS,
                       port_validation: bool = False) -> list[dict]:
    """Run the port on ``raws`` under ``config_path``, then apply every ON, wired enhancement.

    Returns one provenance dict per raw stem found, in the same order as ``locate_outputs``
    sorts its glob. Raises before creating anything if an explicitly-requested enhancement is
    not applicable to the config's engine (:func:`resolve_for_run`, called first).
    ``port_validation`` is forwarded to :func:`run_port` (required for a v3.1.4 config).
    """
    config_path = Path(config_path)
    cfg = load_config(config_path)
    # cfg.run is `dict[str, object]` (RunConfig's own deliberately uninterpreted bag), but
    # load_config (already called, above) refuses to return a `cfg` whose "engine" key is not
    # a member of config.py's `_ENGINES` -- so this is always a str; str() on an already-str
    # value is a no-op, it just gives the type checker the same guarantee load_config enforces
    # at runtime.
    engine = str(cfg.run.get("engine", lineage.applicability.DEFAULT_ENGINE))
    require_enhancement_policy(cfg, config_path)
    resolved = resolve_for_run(cfg, engine, lineage)
    print(format_resolution(resolved, engine, config_path, lineage), flush=True)

    base = config_path.resolve().parent
    out_dir = (base / str(cfg.run["out"])).resolve() if "out" in cfg.run else base

    log_path = None
    if raws:
        # Written into out_dir once it exists; run_port itself creates nothing beforehand.
        log_path = base / "enhanced.launch.log"
    stems = sorted({Path(r).stem for r in raws})
    if not any(resolved.values()):
        # Nothing is ON: the port alone, then the (empty) records, exactly as before.
        run_port(config_path, raws, chunks=chunks, jobs=jobs, s2_jobs=s2_jobs, python=python,
                 log_path=log_path, port_validation=port_validation)
        return apply_to_outputs(config_path, engine, out_dir, stems, resolved,
                                lineage=lineage, preset_probetype=_preset_probetype(cfg),
                                preset_pres_pa=_preset_pres_pa(cfg), arm_config=dict(cfg.arm))
    # The chain has to re-run the port's S4 (and S4c) on the enhanced files, with the
    # run's own arguments -- which only the driver holds, as module state this process never
    # binds to (module docstring). So the port subprocess is asked to run the chain itself
    # (`--enhancements`, scripts/run_flight.py's apply_enhancements_to_run, which calls
    # apply_to_outputs below with a StageRunner), and the records it wrote are read back. One
    # applier loop, one chain, whichever command a user typed.
    run_port(config_path, raws, chunks=chunks, jobs=jobs, s2_jobs=s2_jobs, python=python,
             log_path=log_path, enhancements=True, port_validation=port_validation)
    reports = []
    for stem in stems:
        outputs = locate_outputs(out_dir, stem, engine)
        target = outputs.sd if outputs.sd is not None else out_dir / stem
        record = Path(f"{target}.enhancements.json")
        if not record.is_file():
            raise OutputMissing(f"the enhanced run wrote no {record.name} for {stem}")
        reports.append(json.loads(record.read_text(encoding="utf-8")))
    return reports


def _rebuild_sd(outputs: _RunOutputs, runner: StageRunner | None, proc_names: list[str],
                rebuilt: dict[str, str]) -> str | None:
    """Run the port's S4 on this run's ``enh.proc``, writing ``<stem>.enh.sd.nc``.

    Returns ``None`` when there was nothing to rebuild (no proc-stage correction wrote an
    ``enh.proc`` in this run) or the rebuild succeeded, and otherwise the reason it could not
    run -- which :func:`apply_to_outputs` turns into a named skip for every later-stage
    correction and ``chain_error`` in the record, never a silent fall-back to the port's sd.
    """
    if "proc" not in outputs.fresh:
        return None
    if runner is None:
        return ("no stage runner: this caller did not lend the port's S4, so the sd cannot be "
                "rebuilt -- run through `arrayprobe run --enhancements` or "
                "`arrayprobe-enhanced run`")
    enh_proc, dst = _enh_path(outputs, "proc"), _enh_path(outputs, "sd")
    tmp = _tmp_for(dst)
    try:
        runner.sizedist(enh_proc, outputs.raw_stem, tmp)
    except Exception as exc:                                 # noqa: BLE001 -- recorded, named
        if tmp.exists():
            tmp.unlink()
        _tas_qc_path(tmp).unlink(missing_ok=True)
        return f"S4 on {enh_proc.name} failed: {type(exc).__name__}: {exc}"
    _finish_enh_copy(tmp, dst, proc_names)
    # S4 wrote its TAS quality record beside the temporary file it was handed; it belongs to
    # the file that temporary became, or the enhanced chain's exports report it absent.
    _carry_tas_qc(_tas_qc_path(tmp), dst, move=True)
    outputs.fresh.add("sd")
    rebuilt["S4"] = dst.name
    return None


def _stamp_stage(outputs: _RunOutputs, runner: StageRunner, stage: str,
                 by_stage: dict[str, list[str]], rebuilt: dict[str, str],
                 written: dict[str, Path]) -> None:
    """Write the ``.call`` of every file this stage produced, through the driver's labeller.

    Stamped as each stage finishes rather than after the run, so a later stage reads a current
    stamp from its input: ``arm_export`` embeds its source sd's ``.call`` text, which until
    now was stamped only after every applier had run (so it read none, or a previous run's).
    The base is always the port file the enhanced one descends from -- ``proc`` for ``enh.proc``,
    ``sd`` for the rest -- so stripping the enhancement block gives the port's own stamp back,
    which is what the one-run test (D5) checks.
    """
    if stage == "proc":
        if "proc" in outputs.fresh and outputs.proc is not None:
            runner.stamp(_enh_path(outputs, "proc"), outputs.proc, by_stage["proc"])
        return
    if outputs.sd is None:
        return
    lineage_names = by_stage["proc"] + by_stage["sd"]
    s4 = ["S4"] if "S4" in rebuilt else []
    if stage == "sd" and "sd" in outputs.fresh:
        runner.stamp(_enh_path(outputs, "sd"), outputs.sd, lineage_names, s4)
    elif stage == "product":
        for name in by_stage["product"]:
            runner.stamp(written[name], outputs.sd, lineage_names + [name], s4)


def apply_to_outputs(config_path, engine: str, out_dir, stems, resolved: dict[str, bool], *,
                     lineage: Lineage = UIOPS,
                     preset_probetype: int | None = None,
                     preset_pres_pa: float | None = None,
                     arm_config: dict[str, str] | None = None,
                     runner: StageRunner | None = None,
                     policies: dict | None = None, jobs: int = 1) -> list[dict]:
    """Apply every ON, wired enhancement to products **that already exist** on disk.

    ``jobs`` (default 1, the serial loop) is the worker count for the out-of-focus reject loop;
    output is identical for every value and it is recorded nowhere.

    ``policies`` maps a correction name to keyword options its applier reads,
    e.g. ``registry.PROTECTIVE_POLICY``; ``None`` keeps every applier's default.

    The second half of :func:`apply_enhancements`, lifted out unchanged (2026-09-20)
    so a driver that has just written its own outputs in this process -- ``scripts/run_flight.py
    --enhancements`` -- can reach the same appliers, the same chain rule, the same provenance
    sidecars, without :func:`run_port` running the port a second time. ``apply_enhancements``
    is now exactly ``run_port`` followed by this call, so the two paths cannot drift: there is
    one applier loop, not two.

    ``out_dir`` is where the run wrote; ``stems`` are the raw stems to look for; ``resolved``
    is :func:`resolve_for_run`'s answer, which the caller must already have obtained (it
    raises before anything is created, which is the whole point of resolving first).
    ``preset_probetype`` is the probetype the two probetype-gated appliers need, which no
    ``.call`` stamp carries -- the in-process driver knows it directly and passes it, where
    :func:`apply_enhancements` recovers it with :func:`_preset_probetype`.
    ``arm_config`` is ``cfg.arm`` verbatim, threaded the same way rather than reloaded
    here -- one config load, the reason :func:`test_run_context_carries_date_and_pressure`
    gives for ``preset_probetype``/``preset_pres_pa`` applies just as much to a second
    ``[arm]`` id a caller already has in hand. ``None``/absent means "no [arm] section", same
    as every other caller of this function that predates it and passes nothing.
    """
    out_dir = Path(out_dir)
    reports = []
    for stem in stems:
        outputs = locate_outputs(out_dir, stem, engine)
        # The two values added 2026-09-21 travel the same way `preset_probetype` does, and for
        # the same reason: the `.call` stamp carries neither, while the run that wrote the
        # products knew both. `flight_date` comes off the stem itself (one place, range-checked,
        # None rather than a guess); `preset_pres_pa` is passed in by the caller, which is the
        # only party that has resolved the preset. `arm` travels the same way, for the
        # same reason: an ARM site/platform/facility id is not recoverable from the stamp or
        # the stem either, it is a fact only the run's own config carries.
        outputs = dataclasses.replace(
            outputs,
            preset_probetype=preset_probetype,
            preset_pres_pa=preset_pres_pa,
            flight_date=_flight_date_from_stem(stem),
            arm=dict(arm_config) if arm_config else {},
            policies=dict(policies) if policies else {},
            jobs=jobs,
        )
        applied: list[str] = []
        skipped: dict[str, str] = {}
        written: dict[str, Path] = {}
        details: dict[str, dict] = {}
        by_stage: dict[str, list[str]] = {s: [] for s in _STAGE_ORDER}
        rebuilt: dict[str, str] = {}
        chain_error: str | None = None
        outputs.chain.update({"stages": by_stage, "rebuilt": rebuilt})
        for stage in _STAGE_ORDER:
            if stage == "sd":
                # The port's own S4, unmodified, on this run's enh.proc, so
                # every proc-stage correction reaches the sd -- and every sd- and product-stage
                # correction then acts on THAT sd, never on the port's.
                t0 = _clock()
                chain_error = _rebuild_sd(outputs, runner, by_stage["proc"], rebuilt)
                if "S4" in rebuilt or chain_error is not None:
                    _log_module(stem, "S4 (sd rebuild)",
                                "failed" if chain_error is not None else "done", _clock() - t0)
            for name in _ordered_for_stage(lineage.registry.REGISTRY, stage):
                spec = lineage.registry.REGISTRY[name]
                if not resolved.get(name):
                    continue
                if spec.entry_point is None:
                    skipped[name] = _NO_ENTRY_POINT_REASON
                    _log_module(stem, name, "skipped (not run)")
                    continue
                if name not in _APPLIERS:
                    skipped[name] = _NO_ADAPTER_REASON_BY_NAME.get(name, _NO_ADAPTER_REASON)
                    _log_module(stem, name, "skipped (not run)")
                    continue
                if chain_error is not None:
                    skipped[name] = (
                        f"not applied: proc-stage corrections ({', '.join(by_stage['proc'])}) "
                        f"were applied but no sd was rebuilt from them ({chain_error}), and "
                        "this correction on the port's own sd would silently drop them")
                    _log_module(stem, name, "skipped (not run)")
                    continue
                sd_source = _enhanced_or_original(outputs, "sd")
                _log_module(stem, name, "start")
                t0 = _clock()
                try:
                    result = _APPLIERS[name](outputs)
                except ApplierSkip as exc:
                    skipped[name] = str(exc)
                    _log_module(stem, name, "skipped", _clock() - t0)
                else:
                    _log_module(stem, name, "done", _clock() - t0)
                    # An applier returns its output path, or (path, details) when it has
                    # counts the provenance must carry (particle_time_glitch_fix's drops).
                    dst, info = result if isinstance(result, tuple) else (result, None)
                    if (Path(dst) == _enh_path(outputs, "sd") and sd_source is not None
                            and Path(sd_source) != Path(dst)):
                        # An sd-stage correction's first copy of the port's sd: the TAS
                        # record describes the same S4 call, so it travels with the copy.
                        _carry_tas_qc(_tas_qc_path(Path(sd_source)), Path(dst), move=False)
                    applied.append(name)
                    written[name] = Path(dst)
                    by_stage[stage].append(name)
                    for kind in ("proc", "sd"):
                        if Path(dst) == _enh_path(outputs, kind):
                            outputs.fresh.add(kind)
                    if info is not None:
                        details[name] = info
            if runner is not None:
                _stamp_stage(outputs, runner, stage, by_stage, rebuilt, written)
        for name, spec in lineage.registry.REGISTRY.items():
            if not resolved.get(name):
                continue
            if spec.stage == "reader":
                skipped[name] = _reader_stage_reason(spec)
            elif spec.stage == "none":
                skipped[name] = _NO_STAGE_REASON
        provenance = _build_provenance(
            engine, config_path, resolved, applied, skipped, lineage,
            outputs={name: p.name for name, p in written.items()}, details=details,
            stages=by_stage, rebuilt=rebuilt, chain_error=chain_error)
        text = json.dumps(provenance, indent=2, sort_keys=True) + "\n"
        sd_target = outputs.sd if outputs.sd is not None else out_dir / stem
        Path(f"{sd_target}.enhancements.json").write_text(text, encoding="utf-8")
        # The record travels with every enhanced output, not only beside the
        # port's own sd file -- one sidecar per written file, named the way run_flight names
        # its `.call` (`output.name + suffix`), plus the engine and both package versions as
        # global attributes inside the file itself, so a copied-out `.enh.*.nc` still says
        # what made it. `enhancements_applied` stays the applier's own single name.
        # A file a port stage REBUILT from enhanced input (enh.sd from S4) carries the
        # same record, whether or not an sd-stage applier then wrote over it.
        carriers = {p for p in written.values()}
        carriers |= {out_dir / f for f in rebuilt.values() if (out_dir / f).exists()}
        for p in sorted(carriers):
            Path(f"{p}.enhancements.json").write_text(text, encoding="utf-8")
            _stamp_provenance(p, provenance)
        # 2026-09-16 usability audit, §3.1: this command used to print nothing on success, so the
        # only record of what it did was a JSON sidecar the user had to know to open.
        print(f"{stem}: applied {len(applied)} of {sum(resolved.values())} resolved ON; "
              f"{len(skipped)} skipped", flush=True)
        for name in sorted(applied):
            print(f"  applied {name:30s} -> {written[name].name}")
        for name, reason in sorted(skipped.items()):
            print(f"  skipped {name:30s} {reason}")
        print(f"  record: {Path(f'{sd_target}.enhancements.json').name}", flush=True)
        reports.append(provenance)
    return reports


# The pass log's per-module clock. Log-only: no elapsed time reaches a file, a record or a
# return value, which ``test_pipeline_module_timing`` checks by swapping this clock.
_clock = time.perf_counter


def _log_module(stem: str, name: str, event: str, seconds: float | None = None) -> None:
    """One pass-log line per module: ``<stem>: module <name> <event> (<s> s)``."""
    elapsed = "" if seconds is None else f" ({seconds:.3f} s)"
    print(f"{stem}: module {name} {event}{elapsed}", flush=True)


def _stamp_provenance(path, provenance: dict) -> None:
    with netCDF4.Dataset(path, "r+") as ds:
        ds.enhancements_engine = provenance["engine"]
        ds.arrayprobe_version = provenance["versions"]["arrayprobe"]
        ds.arrayprobe_enhancements_version = provenance["versions"]["arrayprobe_enhancements"]


def main(argv: list[str] | None = None) -> int:
    """``arrayprobe-enhanced run <config.toml> <raw...> [--chunks N] [--jobs N] [--s2-jobs N]
    [--engine ID]``, or ``arrayprobe-enhanced enhancements`` to list what a config may name.
    Tests call this or the installed script's entry point, not a subprocess of themselves.

    A configuration refusal is printed as one line and returned as exit 2, the way the
    port's own CLI reports one -- the audit (2026-09-16, §3.2) measured this command
    answering a bad config with a raw ``RuntimeError`` traceback instead.
    """
    parser = argparse.ArgumentParser(
        prog="arrayprobe-enhanced",
        description="Run the port, then apply the enhancements the config names. "
                    "Every enhancement is OFF unless [enhancements] names it true.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run", help="run a flight and apply the named enhancements")
    run_p.add_argument("config", type=Path)
    run_p.add_argument("raw", nargs="*", type=Path)
    run_p.add_argument("--chunks", type=int, default=1)
    run_p.add_argument("--jobs", type=int, default=1)
    run_p.add_argument("--s2-jobs", type=int, default=1)
    run_p.add_argument("--engine", default=None)
    run_p.add_argument("--port-validation", action="store_true",
                       help="forwarded to `arrayprobe run`: required when [run].engine is 3.1.4 "
                            "(an earlier translation, not part of this package), refused under any other engine")
    sub.add_parser("enhancements",
                   help="list every enhancement a config's [enhancements] table may name")
    args = parser.parse_args(argv)

    if args.cmd == "enhancements":
        for name, spec in sorted(registry.REGISTRY.items()):
            wired = "applies" if name in _APPLIERS else "no driver adapter"
            print(f"{name:30s} stage={spec.stage:8s} {wired:18s} {spec.summary}")
        print(f"\n{len(registry.REGISTRY)} modules; every one is OFF unless "
              "[enhancements].<name> = true names it.")
        return 0

    try:
        # Loaded once up front so a missing, malformed or refused file is a one-line exit 2,
        # not a traceback out of apply_enhancements (the 2026-09-16 audit's rule, §3.2).
        cfg = load_config(args.config)
    except (ConfigError, FileNotFoundError) as exc:
        print(f"arrayprobe-enhanced run: {exc}", file=sys.stderr)
        return 2
    if args.engine is not None:
        declared = cfg.run.get("engine", applicability.DEFAULT_ENGINE)
        if args.engine != declared:
            print(f"arrayprobe-enhanced run: --engine {args.engine} disagrees with "
                  f"[run].engine = {declared!r} in {args.config}", file=sys.stderr)
            return 2

    try:
        apply_enhancements(args.config, args.raw, chunks=args.chunks, jobs=args.jobs,
                           s2_jobs=args.s2_jobs, port_validation=args.port_validation)
    except (NoEnhancementPolicy, registry.UnknownEnhancement,
            applicability.NotApplicableToEngine) as exc:
        print(f"arrayprobe-enhanced run: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
