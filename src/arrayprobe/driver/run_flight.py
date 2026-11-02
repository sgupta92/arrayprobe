# SPDX-License-Identifier: BSD-3-Clause
"""Take raw ``.2DS`` files through S2 -> S3 -> S4, one flight at a time.

The first driver in the project that runs the whole chain, and it exists because
only one of the 09/06/2016 flight's five raw files had ever been through it.
Reproducing the archived product needs all five, and the combine step (S4c)
needs them before it can be validated on anything real.

Written as a batch runner rather than a CLI, and kept small enough to read in one
sitting.  The proper front door arrived later and wraps this one: ``arrayprobe run
<config.toml>`` builds this script's argv from a file and calls ``main()`` (
2026-09-13).  Running the script directly is unchanged and still supported.

Each stage is skipped when its output already exists *and was produced by the
same call under the same fidelity configuration*, so an interrupted run resumes
by being started again while a configuration change does not quietly inherit the
old output.  Every stage writes a ``.call`` sidecar recording how it was
produced, and an output whose provenance cannot be established is refused rather
than guessed at -- see :func:`config_label` for the incident that made this a
control instead of something to remember.  Every step prints a timestamped line,
so a log tail says where a long run has got to.

Usage, from the repository root.  ``--preset`` is required and has no default, because a campaign is
chosen by name or not at all (2026-09-15); ``--regime`` declares the S4 threshold policy, and a run
that declares none stops to ask before it starts.  Every example below is parsed and
executed by ``tests/test_run_flight_help_examples.py``, so a required flag added later cannot leave
this block showing commands that exit 2 -- which is exactly what these three did between 2026-09-15
and 2026-09-17, on the first screen a new reader sees:

    .venv/Scripts/python.exe scripts/run_flight.py --preset ORACLES_2016_2DS_H --engine 3.5 \
        --profile stock-v3.5 --tas-source auto --regime liquid-warm ../base160906*.2DS
    .venv/Scripts/python.exe scripts/run_flight.py --preset ORACLES_2016_2DS_H --engine 3.5 \
        --profile stock-v3.5 --tas-source auto --regime liquid-warm --stages 23 ../base1609060*.2DS
    .venv/Scripts/python.exe scripts/run_flight.py --preset ORACLES_2016_2DS_H --engine 3.5 \
        --profile stock-v3.5 --tas-source auto --regime liquid-warm --jobs 4 ../base*.2DS

``--engine`` is required (no default), and ``--engine 3.5`` is the engine for all work; it takes a
v3.5 profile (``stock-v3.5``, or ``oracles-production-v3.5`` for the ORACLES thresholds).
Reproducing the archived ORACLES 2016 product bit for bit needs the v3.1.4 validation engine,
which is not included in this package: here ``--engine 3.1.4`` exits 2 with a message saying so.

``--jobs N`` is S3p tier 1, formalized: files are independent until the combine
step (nothing shared, no argument about correctness), so
this re-execs the script as N subprocesses, round-robins the file list across
them, and waits. It replaces what was previously done by hand with several
``nohup ... &`` invocations one at a time.

``--chunks N`` is S3p tier 3, wired in: splits *one file's* S3 pass across N
subprocesses (each an ordinary ``imgproc_sm`` call over a disjoint record
range -- the same ``n``/``nEvery`` API a single-chunk run already uses) and
merges the results with ``merge_chunks`` in the v3.1.4 validation engine (not included in this
package), which is
proven bit-for-bit equal to the single-chunk result at full production scale
(S3p tier 3). Combine with ``--jobs`` freely: ``--jobs`` spreads
files across workers, ``--chunks`` spreads one file's records across workers,
and neither shares state with the other.

Since 2026-09-13 the console entry is ``arrayprobe run <config.toml>`` (``arrayprobe.cli``), which
builds this script's argv from the file's ``[run]`` section and calls ``main()``; running the
script directly is unchanged.

Phase 2b, the same day: ``--tas-file`` / ``[run].tas_file`` threads stock ``imgProc_sm``'s
aircraft file through S3, so ``STOCK_V314`` runs end to end.

Since 2026-09-13 ``--engine 3.5`` / ``[run].engine = "3.5"`` runs the v3.5 engine through the same
four stages (S4c only with ``[combine].borrowed = true``); every stamp carries ``engine=3.5``.
Since 2026-09-15 every v3.1.4 stamp names its own engine too (``engine=3.1.4``), so
"what wrote this product" is answerable from the sidecar alone under either engine; an older
v3.1.4 stamp with no ``engine=`` key at all is still read as ``engine=3.1.4`` by the resume logic
(``_stamps_equivalent``), so no existing product looks stale over this wording change alone.

Since 2026-09-15, ``--preset`` has no default: the accidental "silently reproduces ORACLES 2016"
fallback a bare ``python scripts/run_flight.py raw.2DS`` used to fall into is now a refusal naming
the choices. ``arrayprobe run`` is unaffected -- it has always passed ``--preset`` explicitly from
the config file's required ``[run].preset``. Since 2026-09-23 ``--engine`` has no default either
(the author's decision): it had kept a ``3.1.4`` default per an earlier memo,
which let an ORACLES run pick the v3.1.4 engine without saying so. ``arrayprobe run`` already
required ``[run].engine``.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import concurrent.futures.process
import contextlib
import dataclasses
import hashlib
import importlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import netCDF4
import numpy as np

from arrayprobe import combine, constants, regimes
from arrayprobe._v314_lazy import ABSENT_MESSAGE as _V314_ABSENT_MESSAGE
from arrayprobe._v314_lazy import engine_present as _v314_engine_present
from arrayprobe._v314_lazy import lazy_module as _lazy_module

# Load record: the run's stage timings are what SPEED.md quotes, so the run records what else the
# machine was doing.
from arrayprobe.driver._load_record import LoadRecorder  # noqa: E402
from arrayprobe.profiles import ORACLES_PRODUCTION, SHIPPED, STOCK_V35, is_v35_flavoured
from arrayprobe.readers.tasinfo import load_tas_info
from arrayprobe.regimes import ResolvedThresholds, ThresholdValidationError
from arrayprobe.tools import make_tas_file as _mtf
from arrayprobe.tools import tas_sources as _tas_sources
from arrayprobe_uiops.spec_core import SpawnRetryWarning

# The v3.1.4 engine modules are absent from the public distribution: load on first use.
# A library caller reaches these only when the module-level ENGINE is still 3.1.4, i.e. it
# skipped use_engine_35(); the message names that call.
_V314_ABSENT_LIBRARY = (
    _V314_ABSENT_MESSAGE + " A library caller of this module's stage functions selects it "
    "by calling run_flight.use_engine_35(<output directory>) first."
)
imgproc = _lazy_module("arrayprobe.imgproc", _V314_ABSENT_LIBRARY)
sizedist = _lazy_module("arrayprobe.sizedist", _V314_ABSENT_LIBRARY)
spec = _lazy_module("arrayprobe.readers.spec", _V314_ABSENT_LIBRARY)

#: Seconds between the load recorder's samples in a flight run. One snapshot costs about
#: 3.3 s of CPU on the author's machine (``_load_record``'s docstring), so the harnesses'
#: 60 s default would add ~0.06 core to a run lasting hours; 300 s adds ~0.01. The entry
#: and exit snapshots bracket the window whatever the interval, and a contaminant that
#: holds a core for a flight's stages is not missed by sampling every five minutes.
LOAD_INTERVAL_S = 300.0

#: The characters ``--stages`` / ``[run].stages`` may contain: 2 decode, 3 image processing,
#: 4 size distribution, c combine. ``main`` refuses anything else before a stage runs.
STAGE_CODES = ("2", "3", "4", "c")

#: Environment switch for the load recorder (author's answer, 2026-09-26).
#: ``ARRAYPROBE_LOAD_RECORD=off`` (case and surrounding space ignored) makes the recorder a
#: no-op: no ``.load.json``, no ``LOAD RECORD:`` line, and no snapshot cost.
#: Any other value, or the variable unset, leaves it on. It exists for
#: builds whose timings are budgets, never quoted figures -- ``scripts/make_demo_reference.py``'s
#: v3.5 demo build sets it for its own subprocess only. A run with it off has no load record, so
#: under the recorded-load timing rule its wall-clock figures are not quotable; the rule is
#: unchanged by the switch.
LOAD_RECORD_ENV = "ARRAYPROBE_LOAD_RECORD"


def load_record_switched_off(environ=None) -> bool:
    """``True`` when ``ARRAYPROBE_LOAD_RECORD`` is ``off``; see :data:`LOAD_RECORD_ENV`."""
    env = os.environ if environ is None else environ
    return env.get(LOAD_RECORD_ENV, "").strip().lower() == "off"


@dataclass(frozen=True)
class CampaignPreset:
    """One campaign's production call, named as a single unit.

    WHY A UNIT AND NOT EIGHT ARGUMENTS.  These values are not independent knobs.
    They are one call, transcribed from one driver script, and getting any one of
    them wrong silently produces a plausible answer -- which is why they were
    constants here rather than command-line options in the first place.  That
    reasoning is preserved: a preset is still chosen whole, by name, and never
    assembled field by field at the command line.

    WHY IT IS A REGISTRY NOW (2026-09-08, campaign-neutral driver).  The eight constants named one
    campaign, one probe and one channel, so the driver served ORACLES 2016 and
    nothing else -- a package meant for every campaign, probe and hydrometeor
    type cannot have its only end-to-end driver hard-wired to one deployment.
    Adding a campaign is now adding a ``CampaignPreset`` beside this one, with
    its own provenance line saying which script it was transcribed from; it is
    not editing the driver's logic.  Since 2026-09-09 it need not be added here
    at all: :func:`load_presets` reads campaigns from a TOML file the user owns,
    on the same terms -- every field required, provenance required, and no
    shadowing of a name this driver ships.

    ``provenance`` is required rather than optional on purpose: a preset whose
    origin nobody can name is a set of numbers somebody guessed.
    """

    name: str
    probe: str
    orientation: str
    project: str
    d_choice: int
    sa_method: int
    pres_pa: float
    temp_c: float
    provenance: str


ORACLES_2016_2DS_H = CampaignPreset(
    name="ORACLES_2016_2DS_H",
    probe="2DS",
    orientation="H",        # 2016: the V channel's mirror was soot-fouled
    project="ORACLES",
    d_choice=6,             # D of the minimum enclosing circle
    sa_method=0,            # centre-in
    pres_pa=9e5,            # as the driver passes it
    temp_c=15.0,
    provenance=("runsizedist.m in a field campaign's modified UIOOPS tree, which "
                "produced the archived "
                "ORACLES 2016 products. Reproduces the archived product exactly."),
)

ORACLES_2017_2DS_V = CampaignPreset(
    name="ORACLES_2017_2DS_V",
    probe="2DS",
    orientation="V",
    project="ORACLES",
    d_choice=6,
    sa_method=0,
    pres_pa=9e5,
    temp_c=15.0,
    provenance=(
        "Same call as ORACLES_2016_2DS_H, whose values reproduce nine 2017 "
        "HORIZONTAL products exactly, on the vertical channel -- which is a "
        "separate channel in 2017 rather than a fouled one: the 2016 V mirror "
        "was soot-fouled for the whole IOP and its data is not used, while both "
        "channels worked in 2017 and 2018 (used-bin V/H median 0.94 and 1.01; "
        "the campaign delivered V products for those years and none for 2016) "
        "-- so the 2016 rule does not transfer to 2017. "
        "NOT YET VALIDATED: no 2017 V product has been reproduced with it. The "
        "nine V products of record exist, so the run that would settle it is "
        "available; until it is done this preset makes the channel REACHABLE, "
        "which is all it claims. Do not quote a result from it as validated."),
)

DEMO_2DS_H = CampaignPreset(
    name="DEMO_2DS_H",
    probe="2DS",
    orientation="H",
    project="DEMO",
    d_choice=6,             # D of the minimum enclosing circle -- as ORACLES_2016_2DS_H
    sa_method=0,            # centre-in
    pres_pa=9e5,            # arbitrary sea-level-ish default; the demo flight is synthetic
    temp_c=15.0,
    provenance=("synthetic -- scripts/make_demo_flight.py, for the ten-minute quickstart. "
                "No campaign data required. NOT VALIDATED SCIENCE: the "
                "demo particle's inter-arrival times are arbitrary incrementing "
                "constants, so the production shattering configuration rejects it -- "
                "this preset proves the pipeline runs end to end and writes valid "
                "files, not that its output means anything. See "
                "tests/test_end_to_end.py's module docstring."),
)

UND_2016_CIP = CampaignPreset(
    name="UND_2016_CIP",
    probe="CIP",
    orientation="none",     # probetype 1: the format has no channel split at all
    project="ORACLES",
    d_choice=6,
    sa_method=0,
    pres_pa=9e5,
    temp_c=15.0,
    provenance=(
        "Transcribed from the hand-written lane scripts that produced the only CIP "
        "products this project holds -- the .call sidecars of "
        "_decoded/cip160906/proc.cip_s1.nc and sd.cip_s1.nc (2026-09-14): probename CIP, "
        "projectname ORACLES, d_choice 6, sa_method 0, 9e5 Pa, 15 C, profile "
        "oracles-production. Those sidecars label the same values 'copied from the 2D-S "
        "ORACLES_2016_2DS_H call; decisions (1)-(3) open', and that is still true: "
        "NOT VALIDATED. No CIP raw+processed reference pair exists on this machine, so no "
        "CIP output of any kind has been compared against an archived UIOPS product, and "
        "none can be until such a pair is held. `projectname` is load-bearing and not "
        "cosmetic -- UIOPS switches on (project, probe) and only PECAN and GPM have their "
        "own CIP rows, so ORACLES falls to constants.py's `otherwise` branch: probetype 1, "
        "64 diodes, 25 um, 19 bins. This preset makes the probe REACHABLE FROM THE DRIVER, "
        "which is all it claims; it replaces a hand-written script, not a validation."),
)

#: Every campaign call this driver knows. A new campaign is a new entry, not an edit.
#: (`ENGINE_DEFAULT_OK_PROJECTS`, the projects that could leave `--engine` at its old 3.1.4
#: default, was removed on 2026-09-23: `--engine` is now required for every preset.)
PRESETS: dict[str, CampaignPreset] = {
    p.name: p for p in (ORACLES_2016_2DS_H, ORACLES_2017_2DS_V, DEMO_2DS_H, UND_2016_CIP)
}

#: The preset in force. Module-level so the names below stay importable unchanged.
ACTIVE: CampaignPreset = ORACLES_2016_2DS_H

# Kept as module names because the rest of this file and its tests read them.
# They are derived from ACTIVE rather than typed twice, so the two cannot drift.
PROBE = ACTIVE.probe
ORIENTATION = ACTIVE.orientation
PROJECT = ACTIVE.project
D_CHOICE = ACTIVE.d_choice
SA_METHOD = ACTIVE.sa_method
PRES_PA = ACTIVE.pres_pa
TEMP_C = ACTIVE.temp_c


def use_preset(name: str) -> CampaignPreset:
    """Make ``name`` the campaign call in force for the rest of this process.

    **Why rebinding module names rather than threading an argument.** Every
    function here reads ``PROBE``, ``ORIENTATION`` and their siblings as module
    globals, and so do the tests and the two flat re-export shims. Threading a
    preset parameter through the call graph would change a dozen signatures at
    once in the one driver that produced every validated product; rebinding the
    names the code already reads changes none of them, and the constants remain
    derived from ``ACTIVE`` rather than typed twice.

    **The trap this had to avoid, and it is why the default below is a sentinel.**
    A rebound global does not reach a default argument: ``def f(x=ORIENTATION)``
    captures the value at *definition* time, so ``image_call_label`` would have
    gone on stamping ``H`` after a switch to a V preset, and the stamp is what
    the next stage checks its input against. That is a silent wrong answer of
    exactly the kind this driver's ``.call`` sidecars exist to prevent, so the
    one preset-derived default in this file resolves from ``ACTIVE`` at call
    time instead. ``tests/test_run_flight_preset.py`` executes the switch and
    asserts the stamp follows it.

    Call this **before** anything else runs -- ``main`` does it immediately after
    parsing, before any path is built -- because output paths carry the
    orientation.
    """
    global ACTIVE, PROBE, ORIENTATION, PROJECT, D_CHOICE, SA_METHOD, PRES_PA, TEMP_C
    if name not in PRESETS:
        known = ", ".join(sorted(PRESETS))
        raise KeyError(f"unknown preset {name!r}; this driver knows: {known}. "
                       f"A new campaign is a new CampaignPreset with its own "
                       f"provenance line, not an edit to a call site -- declare "
                       f"one in a TOML file and pass --presets, or add it to "
                       f"PRESETS above.")
    ACTIVE = PRESETS[name]
    PROBE = ACTIVE.probe
    ORIENTATION = ACTIVE.orientation
    PROJECT = ACTIVE.project
    D_CHOICE = ACTIVE.d_choice
    SA_METHOD = ACTIVE.sa_method
    PRES_PA = ACTIVE.pres_pa
    TEMP_C = ACTIVE.temp_c
    return ACTIVE


def use_engine_35(directory, *, tas_mps: float = 130.0, tas_file=None) -> str:
    """Run this process's in-process stage calls on the v3.5 engine; return the TAS file used.

    The module defaults (``ENGINE = "3.1.4"``, ``PROFILE = ORACLES_PRODUCTION``) reproduce the
    archived ORACLES record and are left alone; a public installation carries no v3.1.4 engine, so a
    notebook that calls :func:`stage2` / :func:`stage3` / :func:`stage4` directly calls this first,
    the in-process equivalent of ``--engine 3.5 --profile stock-v3.5 --tas-file <file>``.

    ``stock-v3.5`` reads the aircraft true airspeed from a file. With ``tas_file=None`` a constant
    ``tas_mps`` series covering the whole day (one record per second, ``Time`` as HHMMSS) is written
    to ``<directory>/aircraft.cdf``, which suits synthetic flights; pass a real aircraft file to
    use it instead.
    """
    global ENGINE, PROFILE, TAS_FILE
    if tas_file is None:
        secs = np.arange(86400)
        hhmmss = (secs // 3600) * 10000 + (secs % 3600 // 60) * 100 + secs % 60
        path = Path(directory) / "aircraft.cdf"
        with netCDF4.Dataset(str(path), "w", format="NETCDF3_CLASSIC") as ds:
            ds.createDimension("time", secs.size)
            ds.createVariable("Time", "f8", ("time",))[:] = hhmmss.astype(float)
            ds.createVariable("TAS", "f8", ("time",))[:] = np.full(secs.size, float(tas_mps))
        tas_file = path
    ENGINE, PROFILE, TAS_FILE = "3.5", STOCK_V35, str(tas_file)
    return TAS_FILE


class PresetFileError(ValueError):
    """A campaign file that would register a preset nobody could trust."""


#: The fields a declared campaign must state, derived from the dataclass rather
#: than typed again -- a field added to :class:`CampaignPreset` is required of a
#: declared campaign in the same edit, with no second list to remember.
PRESET_FIELDS: tuple[str, ...] = tuple(f.name for f in dataclasses.fields(CampaignPreset))


class UnsupportedProbe(ValueError):
    """This driver has no S2 it can run for that probe.

    Separate from :class:`PresetFileError` because it is not a fact about a
    file: a built-in preset, a ``--presets`` entry and a ``--config`` run all
    reach the same wall, and the wall is the *driver's* S2 contract.
    """


class ProfileNotReachableInChunkWorkers(ValueError):
    """``--chunks`` is about to re-exec this script into fresh subprocesses, and
    :data:`PROFILE` is a profile none of them would know by name.

    Raised in :func:`stage3` **before** any worker is spawned. A shipped profile
    (:data:`arrayprobe.profiles.SHIPPED`) needs nothing -- every fresh interpreter
    already has it. A profile reached through ``register_profile()`` needs
    :data:`PROFILE_MODULE` (``[fidelity].profile_module``) so each worker can
    import the same registration the parent ran; without it, ``cmd_base`` would
    hand every worker a name its own ``PROFILES`` dict has never heard of, and
    each would raise a bare ``KeyError`` about two seconds in -- a failure mode
    the incident this class is named for hit on all 11 workers of an 8-chunk
    launch before a single record was written. Same shape, same reason, as the
    ``ChunkingNotEquivalent`` check just above this one's call site: fail before
    spawning, not after N processes have each run to completion.
    """


@dataclass(frozen=True)
class S2Reader:
    """Which decoder this driver would call for a probe, and whether it can.

    One table, read by both gates.  Before 2026-09-17 the "probetype 2 only"
    rule was an inline ``!= 2`` inside :func:`load_presets` (``:365``) and
    nothing at all inside :func:`stage2`, so the rule was enforced on the
    path a *declared* campaign takes and on no other path -- a built-in
    preset naming a CIP would have decoded a CIP file with
    ``read_binary_SPEC`` and written a plausible, wrong ``.H.cdf``.

    **Probetype 1 became drivable on 2026-09-18 (CIP work).**  What changed is not
    the reader -- ``readers.dmt`` and ``readers.sea`` were already live -- but
    :func:`channel_token`, which gave the driver a name for a file that was
    never split into channels.

    **Probetypes 0 and 3 became drivable on 2026-09-19 (non-SPEC driver path).**
    ``channel_token`` needed no change -- it was already probetype-agnostic
    beyond the SPEC case. What was missing was entirely inside :func:`stage2`:
    ``read_binary_PMS`` writes three probe-identity outputs from one decode,
    under its own lowercase names, which do not match the (already-correct)
    target name -- a one-rename gap, not a naming-schema one (naming decision,
    2026-09-19).
    This closes the S2/S3 half only; the v3.5 S4 guard for these probetypes is
    untouched (no Octave oracle bank yet), and v3.1.4 S4's own support for
    them predates this table but is not reachable through this
    driver under the engine-scope rule policy, which scopes v3.1.4 to 2D-S/HVPS.
    """

    probe: str
    probetype: int
    #: Dotted name of the reader that decodes this probe's raw format.  Every
    #: probetype has one; having a reader is not the same as this driver being
    #: able to drive it, which is what ``supported`` says.
    reader: str
    supported: bool
    #: Empty when ``supported``.  Names the structural blocker, not a to-do.
    blocker: str
    #: Raw-file extension -> dotted reader, for a probetype whose raw data
    #: arrives in more than one *container* (CIP: a ``.sea`` tagged container
    #: holding several probes' streams, or a flat ``.cip`` DMT record stream).
    #: Empty for a probetype with one format, where :attr:`reader` is the answer.
    formats: dict[str, str] = dataclasses.field(default_factory=dict)


#: Which reader decodes which probetype, and what stops this driver driving it.
#:
#: **The blocker was a contract mismatch, not a missing reader.**  ``readers.dmt``
#: and ``readers.pms`` are ported, tested and live.  What they do not do is the
#: H/V channel split this driver's S2 contract used to be built on:
#: ``read_binary_SPEC`` takes ``channels=`` and returns ``(n_h, n_v)``, while
#: ``read_binary_DMT`` and ``read_binary_PMS`` each decode with no channel split
#: of their own (see :data:`_NON_SPEC_READER_DETAIL` for which does what), so the
#: driver had no name for the file it would produce.
#:
#: :func:`channel_token` is that name, and probetype 1 was opened on it
#: (CIP work, 2026-09-18): the path segment is the **channel** for a SPEC probe and
#: the **probe** for a single-channel one -- it needed no change for probetypes
#: 0 and 3 either, since it was already probetype-agnostic beyond the SPEC
#: case. **Probetypes 0 and 3 were opened 2026-09-19**: the actual
#: gap was inside :func:`stage2`, which renames the one PMS output matching the
#: requested probe into the name :func:`channel_token` already built --
#: the naming decision of 2026-09-19.
#: This table's entries below are therefore dead for every probetype now (all
#: four are ``supported``); kept for the blocker text's own record of what each
#: reader's shape is, in case a future probetype needs the same reasoning.
#: ``tests/test_run_flight_non_spec_probes.py`` asserts the channel-split
#: difference against the readers' real signatures, so this table cannot quietly
#: stop being true.
_NON_SPEC_READER_DETAIL: dict[str, tuple[str, str]] = {
    # (what the reader does instead of an H/V pair, where its own docstring says so).
    # Kept per-reader rather than one shared sentence (CIP work, 2026-09-18): a PMS-backed
    # probetype's refusal used to cite "(readers/dmt.py:245-249)" regardless -- a file it
    # never touches, wrong for probetypes 0 and 3 -- because one template was written
    # against DMT and reused verbatim for PMS, whose mismatch is bigger (three output
    # files and a 4-tuple, not one file and one count).
    "arrayprobe.readers.dmt.read_binary_DMT": (
        "decodes one file with no channel split and returns one count",
        "readers/dmt.py:246-253"),
    "arrayprobe.readers.pms.read_binary_PMS": (
        "writes three probe-type outputs (<stem>.2dc.cdf, .f2dc.cdf, .2dp.cdf) with no "
        "channel split and returns a 4-tuple of counts, not one file and one count",
        "readers/pms.py:152-159"),
}

_NON_SPEC_BLOCKER = (
    "this driver's S2 writes an H/V pair -- read_binary_SPEC takes channels= and "
    "returns (n_h, n_v), and S3 reads <stem>.<ORIENTATION>.cdf -- while {reader} "
    "{behavior} (its own docstring, {citation}), so the driver has no name for the file it "
    "would write. The reader is live and correct; it is the driver that cannot yet drive it. "
    "A hand-written per-flight script outside this driver is today's route around the gap; "
    "probetype 1 was closed the same way on 2026-09-18, which is the template for closing it "
    "here"
)

#: The only probes this driver runs under ``--engine 3.1.4``. The v3.1.4 engine exists to
#: reproduce the archived ORACLES 2D-S and HVPS products and to validate the port against them;
#: every other probe (CIP, PIP, 2DC, 2DP, Fast2DC) is processed with engine 3.5 or SODA-2, and
#: :func:`main` refuses it before any stage runs. The library port's readers for those probes
#: stay ported and tested; only this driver's gate is closed to them.
#: ``tests/test_run_flight_v314_probe_gate.py`` asserts the set and the refusal for each probe.
V314_PROBES: frozenset[str] = frozenset({"2DS", "HVPS"})

S2_READERS: dict[int, tuple[str, bool]] = {
    0: ("arrayprobe.readers.pms.read_binary_PMS", True),       # 2DC, 2DP
    1: ("arrayprobe.readers.dmt.read_binary_DMT", True),       # CIP, PIP
    2: ("arrayprobe.readers.spec.read_binary_SPEC", True),     # 2DS, HVPS
    3: ("arrayprobe.readers.pms.read_binary_PMS", True),       # Fast2DC
}

#: The suffix ``read_binary_PMS`` appends to whatever base path it is given
#: (``pms.py:154-155``, ``:161-163``) -- its own convention, lowercase, unlike
#: the uppercase probe token this driver names everything else with.
#: :func:`stage2`'s PMS branch renames the ONE output matching the requested
#: probe to :func:`channel_token`'s name; the other two are published
#: untouched, as unstamped siblings -- the same shape as ``read_binary_SEA``'s
#: sibling (CIP work, 2026-09-18), one rename where SEA needed none (naming
#: decision, 2026-09-19).
_PMS_NATIVE_SUFFIX: dict[str, str] = {"2DC": "2dc", "2DP": "2dp", "Fast2DC": "f2dc"}

#: Which raw-file extension names which decoder, for a probetype whose raw data
#: reaches this project in more than one container.
#:
#: **Why an explicit table rather than "try one and fall back".**  A `.sea` and a
#: `.cip` are different formats, not two flavours of one: SEA is a tagged
#: container walked by directory records, holding a CIP stream and a 2DC stream
#: side by side, while a `.cip` is the flat 4112-byte DMT record sequence.  Each
#: would decode the other into plausible nonsense.  An extension not listed here
#: is refused **by name** in :func:`s2_reader_for_raw`, because "decoded by the
#: wrong reader" is exactly the silent-wrong-output failure this gate exists for.
#:
#: ``read_binary_SEA.m`` is **byte-identical between UIOOPS v3.1.4 and v3.5**
#: (measured 2026-09-18, ``cmp`` over the two vendored trees), so the same
#: translation serves both engines -- the ``SHARED`` state of ``uiops.CATALOGUE``.
#: The engine still reaches the ``.call`` stamp, because S3 and S4 downstream are
#: not shared.
S2_FORMATS: dict[int, dict[str, str]] = {
    1: {".sea": "arrayprobe.readers.sea.read_binary_SEA",
        ".cip": "arrayprobe.readers.dmt.read_binary_DMT"},
}


#: Raw-file extensions that name one probe unambiguously, for the preset/raw mismatch check
#: (:func:`preset_raw_mismatch`).  ``.2ds`` is the demo and ORACLES 2D-S naming and ``.hvps`` the
#: ORACLES HVPS naming (``tests/data/demo_flight_*_raw.2DS``, ``readers/spec.py``).  ``.sea`` and
#: ``.cip`` are the probetype-1 containers already in :data:`S2_FORMATS`.  PMS (2DC/2DP) and 3VCPI
#: raw naming is not established in this tree, so those extensions are absent and pass unchecked.
RAW_EXTENSION_PROBES: dict[str, frozenset[str]] = {
    ".2ds": frozenset({"2DS"}),
    ".hvps": frozenset({"HVPS"}),
}


#: Deployment windows of shipped CAMPAIGN presets, ``{preset name: (first day, last day, source)}``,
#: for :func:`preset_date_warning`.  Kept apart from :data:`PRESETS` so user-written TOML presets
#: are never checked.  Each window is the P-3 deployment period NASA's ESPO archive lists
#: (https://espoarchive.nasa.gov/archive/browse/oracles, read 2026-10-10); UND_2016_CIP is the
#: 2016 P-3's CIP, so it takes the 2016 window.  DEMO_2DS_H is synthetic and has none by design.
_ESPO = "NASA ESPO archive, ORACLES-{n} P-3 Orion deployment"
PRESET_FLIGHT_WINDOWS: dict[str, tuple[date, date, str]] = {
    "ORACLES_2016_2DS_H": (date(2016, 8, 19), date(2016, 10, 27), _ESPO.format(n=1)),
    "UND_2016_CIP": (date(2016, 8, 19), date(2016, 10, 27), _ESPO.format(n=1)),
    "ORACLES_2017_2DS_V": (date(2017, 8, 1), date(2017, 9, 4), _ESPO.format(n=2)),
}


def preset_date_warning(preset_name: str, raw, windows=None) -> str | None:
    """A one-line warning when the flight date in ``raw``'s ``base<YYMMDDhhmmss>`` stem lies outside
    the preset's recorded window, else ``None``.  Only a log line: never a refusal, and it reaches
    no computed number or ``.call`` stamp.  A preset without a window, or a stem that does not
    parse, is not checked."""
    table = PRESET_FLIGHT_WINDOWS if windows is None else windows
    window = table.get(preset_name)
    if window is None:
        return None
    m = re.fullmatch(r"base(\d{12})", Path(raw).stem)
    if m is None:
        return None
    try:
        day = datetime.strptime(m.group(1), "%y%m%d%H%M%S").date()
    except ValueError:
        return None
    first, last, source = window
    if first <= day <= last:
        return None
    return (f"{Path(raw).name}: flight date {day.isoformat()} is outside the {preset_name} "
            f"deployment window {first.isoformat()} to {last.isoformat()} ({source}). Check that "
            f"the preset matches this campaign; the run continues")


def preset_raw_mismatch(probe: str, raw) -> str | None:
    """One line saying why ``raw``'s extension contradicts the preset's ``probe``, else ``None``.

    Only a positive contradiction is reported: an extension no table lists passes, so a renamed
    or unusual file is never refused for its name alone.
    """
    suffix = Path(raw).suffix.lower()
    named: frozenset[str] | None = RAW_EXTENSION_PROBES.get(suffix)
    if named is None and suffix in S2_FORMATS[1]:
        try:
            if constants.imgproc_config(probe).probetype == 1:
                return None
        except Exception:                                         # noqa: BLE001
            return None
        label = "CIP/PIP (probetype 1)"
    elif named is None or probe in named:
        return None
    else:
        label = "/".join(sorted(named))
    return (f"{Path(raw).name}: the preset's probe is {probe!r}, but the {suffix} extension names "
            f"{label} data. Running it would write a plausible-looking product for the wrong "
            f"probe. Choose a preset for {label}, or pass --accept-preset-mismatch if this file "
            f"was renamed and really is {probe} data")


def s2_reader_for(probe: str) -> S2Reader:
    """The S2 decoder this driver would call for ``probe``.

    The single place the question is answered.  Raises
    :class:`UnsupportedProbe` for a probe name no release knows; a probe that
    is known but undrivable comes back with ``supported=False`` and a
    ``blocker``, because the two gates want to say different things about it.
    """
    try:
        probetype = constants.imgproc_config(probe).probetype
    except Exception as exc:                                      # noqa: BLE001
        raise UnsupportedProbe(f"probe {probe!r}: {exc}") from None
    reader, supported = S2_READERS[probetype]
    blocker = ""
    if not supported:
        behavior, citation = _NON_SPEC_READER_DETAIL[reader]
        blocker = _NON_SPEC_BLOCKER.format(reader=reader, behavior=behavior, citation=citation)
    return S2Reader(
        probe=probe, probetype=probetype, reader=reader, supported=supported,
        blocker=blocker, formats=dict(S2_FORMATS.get(probetype, {})),
    )


_DMT_READER = "arrayprobe.readers.dmt.read_binary_DMT"


def _decode_dmt_parallel(raw, out_path, s2_jobs, workdir, dotted):
    """Decode a DMT ``.cip`` file across ``s2_jobs`` processes; ``(n, decode_record)``.

    ``readers.dmt.read_binary_DMT_parallel`` is byte-identical to serial
    (tests/test_dmt_parallel.py). A pool that dies after its own spawn retries
    falls back to the serial reader, so the worst case is slow rather than lost,
    the same last resort as the SPEC branch.
    """
    import warnings as _warnings

    from arrayprobe.readers import dmt as _dmt

    log(f"  S2 parallel, {s2_jobs} workers")

    def progress(i):
        if i and i % 20000 == 0:
            log(f"  ...{i} records")

    with _warnings.catch_warnings(record=True) as caught:
        _warnings.simplefilter("always", SpawnRetryWarning)
        try:
            n = _dmt.read_binary_DMT_parallel(
                str(raw), str(out_path), jobs=s2_jobs, workdir=str(workdir),
                progress=progress, report_every=20000)
        except concurrent.futures.process.BrokenProcessPool:
            log(f"  FALLBACK parallel decode's worker pool died after exhausting its "
                f"own retries; falling back to serial (s2_jobs=1) for {raw.name} -- "
                f"slower, not lost")
            n = _dmt.read_binary_DMT(str(raw), str(out_path), progress=progress)
            return n, f"mode=serial_fallback(from_parallel) jobs={s2_jobs} reader={dotted}"
    retries = 0
    for w in caught:
        if issubclass(w.category, SpawnRetryWarning):
            retries += 1
            log(f"  RETRY   {w.message}")
    return n, f"mode=parallel jobs={s2_jobs} retries={retries} reader={dotted}"


def s2_reader_for_raw(probe: str, raw) -> str:
    """The dotted reader this driver will call for **this file**, not just this probe.

    For a probetype with one container (SPEC) the answer is the table's, and the
    file name is not consulted.  For a probetype with several (CIP), the raw
    file's extension selects, and an extension the driver cannot identify is an
    :class:`UnsupportedProbe` rather than a guess -- see :data:`S2_FORMATS`.
    """
    plan = s2_reader_for(probe)
    if not plan.formats:
        return plan.reader
    suffix = Path(raw).suffix.lower()
    if suffix not in plan.formats:
        known = ", ".join(sorted(plan.formats))
        raise UnsupportedProbe(
            f"{Path(raw).name}: probe {probe!r} (probetype {plan.probetype}) reaches this "
            f"driver in more than one raw container, and {suffix or '(no extension)'!r} names "
            f"none of them. Known: {known}. Decoding it with the wrong reader would write a "
            f"plausible, wrong file, so the driver refuses rather than choosing for you")
    return plan.formats[suffix]


def load_presets(path) -> tuple[CampaignPreset, ...]:
    """Register the campaigns declared in a TOML file, and return them.

    **Why this exists (campaign-neutral driver, 2026-09-09).**  Making the campaign call a named
    preset stopped the driver serving exactly one deployment, but adding a
    campaign still meant editing ``PRESETS`` in this file -- so a group with
    their own probe, channel and project could not describe their run without
    patching a driver that fifteen validated flights came out of.  A declared
    campaign lives in a file the user owns.

    **What it does not relax.**  A preset is still chosen *whole* and by name:
    every field is required, so there is no path here to override one value of a
    built-in call, which is the failure mode the eight constants were protecting
    against in the first place.  ``provenance`` is required and must say
    something, because a preset whose origin nobody can name is a set of numbers
    somebody guessed.

    The file is a list of tables::

        [[campaign]]
        name = "ORACLES_2018_2DS_H"
        probe = "2DS"
        orientation = "H"
        project = "ORACLES"
        d_choice = 6
        sa_method = 0
        pres_pa = 9e5
        temp_c = 15.0
        provenance = "transcribed from <script>; not yet validated against a product"

    Every rejection below is a case where accepting the file would let a run be
    wrong quietly:

    * an unknown table or an unknown key -- a typo'd ``orientaton`` would leave
      the real field missing and, if the missing one were tolerated, the run
      would take some other value than the file appears to state;
    * a missing field, since a preset is one call and not a partial one;
    * a name a built-in already uses.  Shadowing ``ORACLES_2016_2DS_H`` would
      make the name that reproduces the archived products mean whatever the file
      said, in logs and ``.call`` stamps that all record the *name*;
    * an orientation other than ``H`` or ``V``.  ``read_binary_SPEC`` accepts
      ``"HV"``, but S3 reads the ``<stem>.<ORIENTATION>`` decode (:func:`stage3` and
      :func:`image_path`) and S2 writes only ``.H`` and ``.V`` ones (``.nc`` from
      engine 3.5, ``.cdf`` from 3.1.4), so ``"HV"`` names a file nothing ever writes;
    * a probe this driver cannot decode at all -- an unknown probe name, checked
      against :data:`S2_READERS` via :func:`s2_reader_for` the same way
      :func:`stage2` does, so a campaign file cannot register a probe the driver
      would then fail to run.  (Every probetype S2 knows -- SPEC, DMT/SEA, PMS --
      is drivable as of 2026-09-19; this gate now only catches a probe
      name no release's ``imgproc_config`` recognises at all.)

    Raises :class:`PresetFileError` for all of the above, and for a file that is not valid
    UTF-8 TOML (a UTF-8 byte-order mark, as Windows PowerShell 5.1 writes, is accepted --
    :func:`arrayprobe.config._read_toml`).  ``FileNotFoundError`` propagates.
    """
    from arrayprobe.config import ConfigError, _read_toml

    path = Path(path)
    try:
        doc = _read_toml(path)
    except ConfigError as exc:
        raise PresetFileError(str(exc)) from exc
    unknown = sorted(set(doc) - {"campaign"})
    if unknown:
        raise PresetFileError(
            f"{path}: unknown table(s) {unknown}; a campaign file holds [[campaign]] only")
    entries = doc.get("campaign")
    if not entries:
        raise PresetFileError(f"{path}: no [[campaign]] entry")

    loaded: list[CampaignPreset] = []
    for entry in entries:
        missing = sorted(set(PRESET_FIELDS) - set(entry))
        extra = sorted(set(entry) - set(PRESET_FIELDS))
        if missing or extra:
            raise PresetFileError(
                f"{path}: [[campaign]] {entry.get('name', '<unnamed>')!r} "
                f"{'is missing ' + str(missing) if missing else ''}"
                f"{' and ' if missing and extra else ''}"
                f"{'does not know ' + str(extra) if extra else ''}"
                f"; a campaign states all of {list(PRESET_FIELDS)}, whole")
        for key in ("name", "probe", "orientation", "project", "provenance"):
            if not isinstance(entry[key], str) or not entry[key].strip():
                raise PresetFileError(
                    f"{path}: {key} must be a non-empty string, got {entry[key]!r}"
                    + ("; a preset whose origin nobody can name is a set of numbers "
                       "somebody guessed" if key == "provenance" else ""))
        for key in ("d_choice", "sa_method"):
            if not isinstance(entry[key], int) or isinstance(entry[key], bool):
                raise PresetFileError(f"{path}: {key} must be an integer, got {entry[key]!r}")
        for key in ("pres_pa", "temp_c"):
            if not isinstance(entry[key], (int, float)) or isinstance(entry[key], bool):
                raise PresetFileError(f"{path}: {key} must be a number, got {entry[key]!r}")

        name = entry["name"]
        if name in PRESETS:
            raise PresetFileError(
                f"{path}: {name!r} is already a preset this driver ships. A declared "
                f"campaign may not shadow a built-in name: logs and .call stamps record "
                f"the name, so the name has to keep meaning one call")
        try:
            plan = s2_reader_for(entry["probe"])
        except UnsupportedProbe as exc:
            raise PresetFileError(f"{path}: {exc}") from None
        if not plan.supported:
            raise PresetFileError(
                f"{path}: probe {entry['probe']!r} is probetype {plan.probetype}; "
                f"{plan.blocker}")
        # The orientation rule is per probetype, because orientation is a fact
        # about the FORMAT and not about the campaign (CIP work, 2026-09-18).
        if plan.probetype == 2 and entry["orientation"] not in ("H", "V"):
            raise PresetFileError(
                f"{path}: orientation must be 'H' or 'V' for probe {entry['probe']!r}, got "
                f"{entry['orientation']!r}; S2 writes only .H and .V decodes (.nc from "
                f"engine 3.5, .cdf from 3.1.4) and S3 reads <stem>.<orientation>, so "
                f"nothing would ever write the file 'HV' names")
        if plan.probetype != 2 and entry["orientation"] != "none":
            raise PresetFileError(
                f"{path}: orientation must be 'none' for probe {entry['probe']!r} (probetype "
                f"{plan.probetype}), got {entry['orientation']!r}. That format has no channel "
                f"split -- read_binary_SEA and read_binary_DMT take no channels argument -- so "
                f"a preset naming 'H' would put a letter into every file name and .call stamp "
                f"asserting a stream separation that never happened")

        preset = CampaignPreset(**{f: entry[f] for f in PRESET_FIELDS if f
                                   not in ("pres_pa", "temp_c")},
                                pres_pa=float(entry["pres_pa"]),
                                temp_c=float(entry["temp_c"]))
        PRESETS[preset.name] = preset
        loaded.append(preset)
    return tuple(loaded)


IAT_FILE = "2DS_intArrThreshold_MISSING.cdf"
"""``sizeDist``'s optional twelfth argument, as the ORACLES production call passes it.

The named file does not exist, and that is the point: ``sizeDist.m:70`` sets
``iaThreshFile = 'NONE'`` and ``:874`` falls back to the per-probe default of
6 us, which is what the published product was made with.  Verified against the
archived product -- 493,312 of 493,312 cells of both ``Size Distribution cm-3``
and ``Counts``, exactly.

Omitting the argument entirely is a *different* call: ``:866`` short-circuits and
the whole shattering block is skipped, accepting 58% more particles.  Reachable
via ``--iat-file ''``, tested, and not the one that made any published product.
"""


def log(msg: str) -> None:
    """Print one progress line prefixed with the wall-clock time, flushed at once."""
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def _clear(directory: Path, stem: str) -> None:
    """Remove any leftovers from a previous killed attempt at this file."""
    for stale in directory.glob(f"{stem}*"):
        stale.unlink(missing_ok=True)


def _publish(staging: Path, out_dir: Path, stem: str) -> None:
    """Move a completed stage's outputs out of staging, atomically per file.

    WHY THIS EXISTS.  The runner decides what to redo by asking whether the
    output already exists, which is the right question only if an existing file
    is necessarily a finished one.  A run killed six hours in -- the exact
    scenario this driver is for -- would otherwise leave a truncated
    decode (``.H.nc`` from engine 3.5, ``.H.cdf`` from 3.1.4), and restarting
    would skip straight past it and build a proc file
    from half a flight.  Silently, and with plausible-looking output, which is
    the worst combination.

    So nothing lands under its real name until the stage returns.
    """
    for produced in sorted(staging.glob(f"{stem}*")):
        os.replace(produced, out_dir / produced.name)


PROFILE = ORACLES_PRODUCTION
"""The one fidelity profile this driver runs.

Named rather than reached for inline, because it is half of what every
provenance stamp below records: the *configuration* an output was produced
under, which an output cannot be asked about afterwards.
"""

PROFILE_MODULE: str | None = None
"""``[fidelity].profile_module`` from the active ``--config``, if any -- the module
``arrayprobe.config.load_config`` already imported to make ``PROFILE`` (above) resolvable by
name. Carried at module level, the same as ``PROFILE`` itself, so stage3's chunk-worker re-exec
(which cannot pass ``--config`` -- the ``--_run-chunk`` mode never runs ``_apply_config``, it
resolves a profile by bare name) can still make ``PROFILES[profile_name]`` succeed in that fresh
subprocess by re-importing this module first. ``None`` for a shipped profile, which every fresh
process already knows about without importing anything."""

AUTHORDEFAULTS_STAMP: str | None = None
"""``authordefaults:<path>#<sha>``, from ``cfg.authordefaults_stamp`` when the
active ``--config`` named ``[fidelity].authordefaults`` -- ``None`` otherwise, which is every run
that predates this feature and every run that names ``[fidelity].profile`` instead. Appended to
:func:`config_label` so it reaches every ``proc``/``sd`` ``.call`` sidecar this driver writes;
absent, the stamp is byte-identical to what this driver wrote before this field existed."""

AUTHORDEFAULTS_PATH: str | None = None
"""The resolved path of the ``[fidelity].authordefaults`` file, from ``cfg.authordefaults_path``;
``None`` otherwise. It travels to ``--_run-chunk`` workers the same way ``PROFILE_MODULE`` does
(an ``authordefaults=<path>`` tail token), so a worker can re-register the
``authordefaults-<hash>`` profile and carry :data:`AUTHORDEFAULTS_STAMP`, after re-checking the
file still hashes to the profile name the parent ran (the author-editable thresholds file work)."""

TAS_FILE: str | None = None
# --tas-ratio on: pass the aircraft TAS series to v3.5's decoder, which writes tasRatio
# (read_binary_SPEC.m:176-193). Off by default; off leaves every v3.5 stamp unchanged.
TAS_RATIO: bool = False
"""The aircraft TAS file stock ``imgProc_sm.m:183-185`` reads as ``varargin{1}``: ``--tas-file`` /
``[run].tas_file`` resolved to an absolute path, or ``None``. The port reads it only under a profile
whose ``time_in_seconds_from_tas`` is set, on a probe whose ``imgproc_config().needs_tas_file`` is
set (``imgproc.py:512``); :func:`main` refuses the other combinations before preflight, so a run
never carries an input it ignores and never discovers a missing one after S2. Module-level like
``PROFILE`` because the ``--_run-chunk`` re-exec carries it the same way (see ``cmd_base``)."""

TAS_SOURCE: str | None = None
"""``--tas-source`` / ``[tas].source`` (the airspeed source chain) -- one of
:data:`arrayprobe.tools.tas_sources.MODES`, or ``None``, which keeps the legacy behaviour: whatever
``--tas-file`` names (or nothing) is used as given, and S4 reads the probe's own ``<stem>.tas.csv``.
When set, the serial per-file loop resolves the chain itself before S3 (see the loop in
:func:`main`) rather than trusting whatever ``--tas-file`` was passed."""

TAS_SEARCH: list[str] = []
"""``--tas-search`` (repeatable) / ``[tas].search`` -- the directories :func:`resolve_chain`
globs the ``merge``/``aircraft`` tiers' file patterns in. Empty means no search directory is
configured, which the chain reports as a ``skipped`` step for each tier, never a silent guess."""

TAS_FROM_PROBE: list[str] = []
"""``--tas-from-probe`` (repeatable): the ``<stem>.tas.csv`` files another probe's S2
wrote on the SAME aircraft -- the 2D-S's housekeeping airspeed, already in m/s. For a probe whose
own S2 writes no airspeed sidecar (probetype 1: CIP, PIP), the serial per-file loop merges them with
``arrayprobe.driver.tas_from_probe_housekeeping`` (per-second median, no gap fill) into this probe's
``<stem>.tas.csv`` before S3, so S4 and the protective set's own S4 have an airspeed. Opt-in, never
discovered: which 2D-S files belong to which CIP file is the caller's statement, not a guess.
Stamped into every sd ``.call`` as ``tas_series=probe_hk:<names>`` (:func:`sd_call_label`). Empty =
the legacy behaviour (S4 reads whatever ``<stem>.tas.csv`` is in ``--out``)."""

TAS_GRID: str = "probe"
"""``--tas-grid`` (2026-09-25): which time vector S4 hands ``sizeDist`` under a TAS source chain.
``"probe"`` (the default) keeps the probe's own ``<stem>.tas.csv`` seconds and swaps only the
values (:func:`~arrayprobe.tools.tas_sources.series_for_sizedist`). That axis repeats and skips
seconds, and ``sizeDist``'s block walk then files no particle of either (v3.5
``sizeDist.m:913-927``, measured under Octave; 4.4-8.5 % of particles on the five ARM 2017
flights).
``"regular"`` hands it every second of the probe's span once, valued from the chain
(:func:`~arrayprobe.tools.tas_sources.regular_series_for_sizedist`), and is stamped
``tas_grid=regular`` into the sd ``.call``. Needs ``--tas-source``: with no chain there is no
series to value the added seconds from. Off by default on every probe; the design and the
reason no default changes were written up with the time-grid loss design
(2026-09-25)."""

NO_ARCHIVE_PROFILES: frozenset[str] = frozenset({"arm-ena-stock", "arm-ena-stock-v3.5"})
"""The profiles whose 2D-S data has NO archived product, so the
data-destroying-defect corrections default ON for it even on probetype 2. Keyed on the profile
because the profile is the one ARM-identifying input every ARM run must name (``[fidelity].profile``
in an ARM run configuration, or ``--profile``), it is already in every ``.call`` stamp, and no
ORACLES preset can carry it -- a probe name, preset or stem cannot tell ARM's 2D-S from ORACLES'.
The only such correction that reaches a 2D-S today is A17's time grid, which the driver applies
itself as ``--tas-grid regular`` (:func:`default_tas_grid`); no ``registry.PROTECTIVE`` row covers
probetype 2, so :func:`resolve_protective`'s enhancement set stays empty here."""


def has_archived_product() -> bool:
    """Whether the active run is on a lineage with an archived product to reproduce: False for an
    :data:`NO_ARCHIVE_PROFILES` profile (ARM) and for every non-probetype-2 probe."""
    if PROFILE.name in NO_ARCHIVE_PROFILES:
        return False
    return s2_plan_is_lineage()


def default_tas_grid(tas_source) -> str:
    """``--tas-grid`` when the command line and config leave it unset. ``"regular"`` for a
    run with no archived product (:func:`has_archived_product` False on probetype 2, i.e. ARM
    2D-S), unless ``--protective off`` or there is no ``--tas-source`` chain to value the added
    seconds from (then ``"probe"``, logged). ``"probe"`` everywhere else, so ORACLES is
    unchanged."""
    if PROTECTIVE_MODE == "off":
        return "probe"
    if PROFILE.name not in NO_ARCHIVE_PROFILES:
        # Probetypes 0/1/3 (no archived product): tas_grid_fix's regular-grid form when a chain
        # can value the added seconds; without one S4 collapses the probe grid instead.
        if tas_grid_fix_on() and tas_source is not None:
            log("tas-grid  probe -> regular (tas_grid_fix: no archived product; "
                "--tas-grid probe or --protective off to opt out)")
            return "regular"
        return "probe"
    if "tas_grid_fix" in ENHANCEMENTS_DECLARED_OFF:
        # The regular grid is tas_grid_fix's form here, so the config's explicit opt-out wins
        # on this profile exactly as it does on probetypes 0/1/3 (resolve_protective).
        log(f"tas-grid  profile {PROFILE.name}: the config sets tas_grid_fix = false, which "
            "wins; using 'probe'")
        return "probe"
    if tas_source is None:
        log(f"tas-grid  profile {PROFILE.name} defaults to --tas-grid regular, but this "
            "run has no --tas-source chain to value the added seconds from; using 'probe'")
        return "probe"
    log(f"tas-grid  probe -> regular (profile {PROFILE.name}: no archived product; "
        "--tas-grid probe or --protective off to opt out)")
    return "regular"


JIT: bool = False
"""``--jit`` (a speed option): route S3's measured-hot kernels through
:mod:`arrayprobe.jit_kernels`. Speed only and byte-identical
(``tests/test_imgproc_jit_identity.py``), so it is **not** stamped into any ``.call``: a
``proc`` made with it is the same file as one made without. Default off; both engines (engine
3.5 through :mod:`arrayprobe_uiops.jit_kernels`, ``tests/test_v35_imgproc_jit_identity.py``).
Module-level like ``PROFILE`` because the ``--_run-chunk`` re-exec carries it the same way."""

LIBM_POW: bool = False
"""``--libm-pow`` (B9): S4's ``massBL`` power (``sizeDist.m:844``) through
libm's ``pow`` instead of numpy's SIMD ``power`` (:func:`arrayprobe.sizedist._libm_pow`). Engine
3.1.4 only -- engine 3.5 always uses libm. Default off and bit-identical when off; when on it can
move a last bit of ``massBL``, so it is stamped (`` libm_pow=on``) into the sd ``.call``, and absent
at the default so no earlier stamp goes stale."""

PORT_VALIDATION: bool = False
"""``--port-validation`` (R4). Required with
``--engine 3.1.4``, refused with any other engine. Stamped ``port_validation=on`` right after
``engine=3.1.4`` in every ``.call`` the run writes (:func:`_engine_prefix`). Changes no computed
byte, so :func:`_stamps_equivalent` ignores it in both directions."""
PORT_VALIDATION_STAMP_KEY = "port_validation="

WRITE_PROVENANCE: bool = False
"""``--write-provenance`` (the in-file provenance decision): stamp S3's ``proc`` file with
``arrayprobe_*`` netCDF global attributes naming the engine and profile that wrote it, **as well
as** the ``.call`` sidecar. Since 2026-09-26 (airspeed QC in file metadata) S4's ``sd`` file gets
the same attributes (stage ``S4``) and, when the run names a TAS source, the ``.tasqc.json``
record's keys as ``arrayprobe_tas_*`` attributes, so
which seconds were sized with a default airspeed travels inside the file (:func:`_sizedist_call`).
The combined product is not stamped: ``combine_sizedist.m`` writes no global attributes.

Default OFF, and that is not a convenience: adding a global attribute changes the file's bytes,
so a run reproducing an archived MATLAB product must leave it off -- which is why nothing in the
port calls :func:`arrayprobe.ncio.put_provenance` on its own. The capability landed 2026-09-20 and
sat unreachable from this driver until 2026-09-20; a capability no command can turn on produces no
product that carries it.

v3.1.4 only, and serial S3 only. Under ``--engine 3.5`` it is redundant: since 2026-09-24 every
v3.5 ``proc`` and ``sd``, every v3.5 SPEC decode, and every SODA-2 product writes
``arrayprobe_engine`` and ``arrayprobe_profile`` unconditionally (a v3.5 run's non-SPEC decode goes
through the v3.1.4 reader and carries neither), so this flag is the opt-in for the v3.1.4 lineage
alone, whose default output stays byte-faithful to MATLAB. ``merge_chunks`` in the v3.1.4 validation
engine (not included in this package)
does not forward it to ``_create_output`` (its own docstring says so), so
``--chunks``/``--jobs`` would silently produce an unstamped file. Both combinations are
**refused** in :func:`main` rather than accepted and ignored --
the silent ``--jit`` no-op's "accepted, does nothing, says nothing" shape."""

STRAY_PIXEL: bool = False
"""The stray-pixel rules: whether S3 runs ``arrayprobe_uiops``'s stray-pixel correction
(``imgproc_sm_v35(..., stray_pixel_fix=)``).
False at import (the library default,
so a caller that never runs :func:`main` is unchanged); :func:`main` resolves it through
:func:`resolve_stray_pixel` -- ON for every ``--engine 3.5`` run, ARM, CIP and ORACLES alike, unless
``--stray-pixel off`` or ``[enhancements] stray_pixel_fix = false``; always off under ``--engine
3.1.4 --port-validation``, which reproduces the archived record. Stamped ``stray_pixel=`` into every
v3.5 ``proc`` and ``sd`` ``.call`` (:func:`stray_pixel_fragment`)."""

STRAY_PIXEL_DECLARED: bool | None = None
"""``[enhancements] stray_pixel_fix`` as the config file declared it, or None when it did not;
the command line's ``--stray-pixel`` wins over it (:func:`resolve_stray_pixel`)."""

STRAY_PIXEL_STAMP_KEY = "stray_pixel="

NCAR_2DC_TIMING: bool = False
"""The NCAR 2DC timing-word conversion: whether S3 runs ``arrayprobe_uiops``'s
``ncar_2dc_timing`` (``imgproc_sm_v35(..., ncar_2dc_timing_fix=)``), which turns NCAR's 2DC
sync/timing words into the 0x55 boundary UIOOPS ``imgProc_sm.m:754`` frames on (as SODA-2's
``fix2dimage.pro`` does); without it UIOOPS frames no particle on NCAR 2DC data. False at import
(the library default); :func:`main` resolves it through :func:`resolve_ncar_2dc_timing` -- ON for
every ``--engine 3.5`` run unless ``--ncar-2dc-timing off`` or ``[enhancements]
ncar_2dc_timing_fix = false``; always off under ``--engine 3.1.4 --port-validation``. It reaches
probetype 0 only (2DC, 2DP: :func:`_probetype0`), the only probetype the engine converts and the
only one whose stamps carry ``ncar_2dc_timing=`` (:func:`ncar_2dc_timing_fragment`)."""

NCAR_2DC_TIMING_DECLARED: bool | None = None
"""``[enhancements] ncar_2dc_timing_fix`` as the config file declared it, or None when it did not;
the command line's ``--ncar-2dc-timing`` wins over it (:func:`resolve_ncar_2dc_timing`)."""

NCAR_2DC_TIMING_STAMP_KEY = "ncar_2dc_timing="


def _probetype0() -> bool:
    """Whether this run is engine 3.5 on a probetype-0 probe (2DC, 2DP; ``PROBES_V35``), the only
    case the NCAR 2DC timing conversion reaches. ``imgproc_sm_v35`` writes its
    ``arrayprobe_ncar_2dc_timing`` global for every probetype when asked, so the driver asks only
    here."""
    if ENGINE != "3.5":
        return False
    probes = _v35().module("imgproc").PROBES_V35
    return PROBE in probes and probes[PROBE].probetype == 0

ACCEPT_IMPLAUSIBLE: bool = False
"""``--accept-implausible``: keep an sd the post-S4 plausibility gate refuses. Recorded
as :data:`ACCEPT_IMPLAUSIBLE_STAMP` in every sd stamp of the run, and never stripped by
:func:`_stamps_equivalent`, so an overridden product is never current for a run without it."""

ACCEPT_IMPLAUSIBLE_STAMP = "accept_implausible=on"

ACCEPT_PRESET_MISMATCH: bool = False
"""``--accept-preset-mismatch``: run a raw file whose extension names a different probe than the
preset's (:func:`preset_raw_mismatch`).  Recorded as :data:`ACCEPT_PRESET_MISMATCH_STAMP` in the
S2/S3/S4 stamps, only when used, so a matching run's stamps are unchanged."""
ACCEPT_PRESET_MISMATCH_STAMP = "accept_preset_mismatch=on"
PLAUSIBILITY_STAMP_KEY = "plausibility=("


def _plausibility_gate_applies() -> bool:
    """Whether the post-S4 plausibility gate runs (and its ``plausibility=`` /
    ``accept_implausible=`` tokens are written): engine 3.5 only. Engine 3.1.4 reproduces the
    archived record, so its sd stamp and exit status stay what they were before the gate."""
    return ENGINE == "3.5"


def _strip_plausibility(stamp: str) -> str:
    """``stamp`` without its ``plausibility=(...)`` token (from the post-S4 plausibility
    gate): a measurement of the written
    file, not a configuration, so it never makes two stamps differ. The token is space-free."""
    return " ".join(t for t in stamp.split(" ") if not t.startswith(PLAUSIBILITY_STAMP_KEY))


def resolve_stray_pixel(engine: str, cli: str | None = None,
                        declared: bool | None = None) -> bool:
    """Whether this run applies the stray-pixel correction (both stray-pixel rules).

    ``cli`` is ``--stray-pixel`` (``"on"``/``"off"``/None), ``declared`` the config's
    ``stray_pixel_fix`` (True/False/None); the command line wins. Engine 3.5 defaults ON. Engine
    3.1.4 (port validation only) is never corrected: ``--stray-pixel on`` or a config ``true`` is
    refused with ValueError, anything else resolves off."""
    if engine != "3.5":
        if cli == "on" or (cli is None and declared is True):
            raise ValueError(
                f"the stray-pixel correction is engine 3.5 only: --engine {engine} "
                "--port-validation reproduces the archived record and is never corrected "
                "(the stray-pixel rule). Drop --stray-pixel on / "
                "[enhancements] stray_pixel_fix = true, "
                "or run --engine 3.5")
        return False
    if cli is not None:
        return cli == "on"
    if declared is not None:
        return bool(declared)
    return True


def stray_pixel_fragment() -> str:
    """`` stray_pixel=on:g8,n2,m9`` or `` stray_pixel=off`` for a v3.5 stamp; ``""`` for v3.1.4,
    whose stamps never carry the key (that engine is never corrected)."""
    if ENGINE != "3.5":
        return ""
    # Through the selector (_v35()), via imgproc's re-export: stray_pixel has no v3.1.4
    # counterpart, so it is not in uiops.CATALOGUE (the probe_cases route through sizedist).
    ip = _v35().module("imgproc")
    stamp = ip.STRAY_PIXEL_STAMP_ON if STRAY_PIXEL else ip.STRAY_PIXEL_STAMP_OFF
    return f" {STRAY_PIXEL_STAMP_KEY}{stamp}"


def resolve_ncar_2dc_timing(engine: str, cli: str | None = None,
                            declared: bool | None = None) -> bool:
    """Whether this run applies the NCAR 2DC timing-word conversion.

    ``cli`` is ``--ncar-2dc-timing`` (``"on"``/``"off"``/None), ``declared`` the config's
    ``ncar_2dc_timing_fix`` (True/False/None); the command line wins. Engine 3.5 defaults ON (it
    reaches probetype 0 only, :func:`_probetype0`). Engine 3.1.4 (port validation only) is never
    corrected: ``--ncar-2dc-timing on`` or a config ``true`` is refused with ValueError, anything
    else resolves off."""
    if engine != "3.5":
        if cli == "on" or (cli is None and declared is True):
            raise ValueError(
                f"the NCAR 2DC timing conversion is engine 3.5 only: --engine {engine} "
                "--port-validation reproduces the archived record and is never corrected. "
                "Drop --ncar-2dc-timing on / [enhancements] ncar_2dc_timing_fix = true, "
                "or run --engine 3.5")
        return False
    if cli is not None:
        return cli == "on"
    if declared is not None:
        return bool(declared)
    return True


def ncar_2dc_timing_fragment() -> str:
    """`` ncar_2dc_timing=on:fix2dimage`` or `` ncar_2dc_timing=off`` for a v3.5 probetype-0
    stamp; ``""`` otherwise (v3.1.4, and every probe the conversion cannot reach), so no other
    stamp changes."""
    if not _probetype0():
        return ""
    ip = _v35().module("imgproc")
    stamp = ip.NCAR_2DC_TIMING_STAMP_ON if NCAR_2DC_TIMING else ip.NCAR_2DC_TIMING_STAMP_OFF
    return f" {NCAR_2DC_TIMING_STAMP_KEY}{stamp}"


PROTECTIVE_MODE: str = "auto"
"""``--protective {auto,on,off}`` or ``[enhancements] protective``. ``auto`` (the
default) runs the protective corrections (``arrayprobe_enhancements.registry.PROTECTIVE``) on every
probetype except 2 (2D-S/HVPS, the ORACLES validation lineage), whatever the engine; ``on`` is the
same set, stated; ``off`` runs none. On probetype 2 the set is always empty, so no ORACLES 2D-S/HVPS
stamp or byte changes."""

ATTRIBUTED_ANALYSIS_READY: bool = True
"""``[outputs] analysis_ready``: OUTPUT 2 chunked and compressed (true, the default) or
plain (false). Reset to true by :func:`main` before any config is folded."""

ATTRIBUTED_ZARR: bool = False
"""``[outputs] zarr``: also write each attributed file as a Zarr store. Opt-in, default off;
reset to false by :func:`main` before any config is folded."""

ATTRIBUTED_PARQUET: bool = False
"""``[outputs] parquet``: also write each attributed file as a directory of Parquet files.
Opt-in, default off; reset to false by :func:`main` before any config is folded."""

PROTECTIVE_ON: tuple[str, ...] = ()
"""The protective set :func:`resolve_protective` decided for this run, sorted; empty on probetype 2
or with ``--protective off``."""

ENGINE: str = "3.1.4"
"""Which UIOOPS engine this process runs: ``--engine``. ``"3.1.4"`` (the argparse default, like
``--preset``'s) reproduces every validated run and leaves every call site and stamp below
byte-identical. ``"3.5"`` switches the four stage calls to the v3.5 engine, resolved through
``uiops.engine("3.5")`` -- this module never imports ``arrayprobe_uiops``
(``tests/test_run_from_config_v35.py`` asserts it), so the selector stays the one place that says
which module implements what. Module-level for the reason ``PROFILE`` is: read live at every call
site."""

TREE: str = "production"
"""The ``sizeDist.m`` project/probe switch table S4 reads (``constants.sizedist_config``'s
``tree``). Named as its own module global, like ``ENGINE``, so the startup print and the ``.call``
stamp read the one value in force rather than the literal ``"production"`` that used to be
buried at the S4 call site. Not yet a command-line switch (the regime pass was scoped to the two
threshold fields below, which is what an unrecognised project was found silently inheriting from
this tree's ``otherwise`` branch); changing it remains a larger fidelity decision -- it also picks
each probe's bin ladder and shattering gate -- than this pass makes."""

PROBE_CASE: str | None = None
"""``--probe-case``: which registered :class:`arrayprobe_uiops.probe_cases.ProbeCase`
supplies S4's ``num_bins``/``kk`` and the eleven constants beside them, INSTEAD of v3.5's own
``switch projectname``/``switch probename`` lookup.

``None`` -- the default, and what every run before 2026-09-21 did -- means the switch decides,
bit for bit. Engine 3.5 only: v3.1.4's ``sizeDist.m`` has the correct 2D-S ladder for an
unlisted campaign already, which is the whole reason the ARM case borrows v3.1.4's line.

A **name**, never a description: a bin ladder is a set of constants, so the
no-raw-thresholds rule applies to it exactly as to a threshold. Registration is from Python
(``arrayprobe_uiops/probe_cases.py``)."""

IA_THRESH_TYPE: int | None = None

#: ``--iat-source flight-table`` (engine 3.1.4, HVPS): the recorded per-flight source from
#: :mod:`arrayprobe.hvps_flight_config` (``port_fit_blocks5`` / ``none_default``), or None.
#: Stamped only when set, so every sd stamp written without it is byte-identical.
IAT_SOURCE: str | None = None
"""``[shattering].ia_thresh_type``: the ``iaThreshType`` engine 3.5's ``sizeDist`` is called with,
when the run file chose one. ``None`` -- the default -- keeps the plain call: 1 with a threshold
file, 0 without. Only 2 is accepted (``sizeDist.m:1346``, the probe case's ``defaultIntArrThresh``
per second); it appears in the ``.call`` stamp only when chosen. Refused under engine 3.1.4,
whose driver makes the ORACLES fork's call, which takes no ``iaThreshType``."""

TIME_OFFSET: tuple[int, str, str] | None = None
"""``--time-offset-s`` / ``--time-offset-evidence`` / ``--time-offset-tas-clock``: engine 3.5's
opt-in whole-second probe-clock offset (``arrayprobe_uiops.sizedist.TimeOffset``), as
``(seconds, evidence, tas_clock)`` after the engine's own validation, or ``None`` -- the default,
which passes no keyword and adds nothing to the sd ``.call`` stamp. Refused under engine 3.1.4.
A config file's ``[time_offset]`` sets it (:func:`_apply_config`) unless a flag is given."""

PROBE_CASE_MODULE: str | None = None
"""``--probe-case-module``: a dotted module whose import registers the case
:data:`PROBE_CASE` names (e.g. ``mypkg.register_my_case``).

Exists for the reason :data:`PROFILE_MODULE` does, and it is the same gap: a ``--jobs`` worker
is a fresh subprocess that re-imports ``arrayprobe_uiops.probe_cases`` and so starts with an EMPTY
registry, in which ``--probe-case my-case`` resolves nowhere. The name alone does not
survive the re-exec; the module does. Both are forwarded to every worker by
:func:`_spawn_flight_worker`."""

REGIME_NAME: str | None = None
"""``--regime`` / ``[thresholds].regime``: which named cloud-regime bundle
(:data:`arrayprobe.regimes.REGIMES`) supplies :data:`AREA_RATIO_Z_OVERRIDE` /
:data:`DEFAULT_IAT_OVERRIDE` where those are not themselves overridden. ``None`` (the default)
means neither a regime nor a raw override was named -- :func:`_resolve_thresholds` then falls back
to exactly the hard-coded values every run before 2026-09-17 used, so nothing about an existing
validated run changes on this alone (the regime thresholds' fidelity requirement)."""

AREA_RATIO_Z_OVERRIDE: float | None = None
"""``--area-ratio-z`` / ``[thresholds].area_ratio_z``: a raw value, exempt from the
no-raw-thresholds rule for this field only. Wins over :data:`REGIME_NAME` for this one field."""

DEFAULT_IAT_OVERRIDE: float | None = None
"""``--default-int-arr-thresh`` / ``[thresholds].default_int_arr_thresh``: as
:data:`AREA_RATIO_Z_OVERRIDE`, for ``defaultIntArrThresh``."""

AREA_RATIO_Z_SOURCE: str = "cli"
"""Where :data:`AREA_RATIO_Z_OVERRIDE` came from, embedded in its ``.call`` tag as
``user:<this>``. ``"cli"`` for ``--area-ratio-z``; a ``--config`` file's own path when it came
from ``[thresholds].area_ratio_z`` (:func:`_apply_config` sets this) -- kept separate from
:data:`DEFAULT_IAT_SOURCE` because a run may mix sources, one field from the command line and the
other from a config file, and each must be tagged with its own origin, never the other's."""

DEFAULT_IAT_SOURCE: str = "cli"
"""As :data:`AREA_RATIO_Z_SOURCE`, for :data:`DEFAULT_IAT_OVERRIDE`."""

TAS_MAX: float | None = None
"""``--tas-max`` / ``[thresholds].tas_max`` (m/s): ``tasMax`` for a ``sizeDist`` case that assigns
none (the 2DP), passed as ``sizedist.run(tas_max=)``. ``None`` passes no keyword, so every other
run's call and ``.call`` stamp are unchanged; a 2DP run without it is refused at preflight."""

PECAN_PARAMS: str | None = None
"""``--pecan-params`` / ``[thresholds].pecan_params``: the parameter file standing in for
``getPECANparams`` on the PECAN CIP/PIP cases (:mod:`arrayprobe_uiops.pecan_params`), passed as
``sizedist.run(pecan_params=)``. ``None`` passes no keyword."""

CONFIG_PATH: str | None = None
"""The ``--config`` file in force, or ``None`` for a run configured entirely from the command
line. Set by :func:`_apply_config`; read by :func:`confirmation_lines`, which points the
operator at the file they are being asked to confirm."""

ENHANCEMENTS_DECLARED: bool = False
"""Whether the ``--config`` file carried an ``[enhancements]`` section at all
(:attr:`arrayprobe.config.RunConfig.enhancements_declared`) -- distinct from carrying an empty
one. The port treats absent and empty identically (nothing on, always); this records which of the
two the operator actually wrote, because the confirmation asks whether the enhancement policy
is *evident* in the file, and an absent section states nothing."""

ENHANCEMENTS_DECLARED_OFF: tuple[str, ...] = ()
"""``[enhancements]`` entries the ``--config`` file sets **false**. A protective correction named
here is left out of :data:`PROTECTIVE_ON` by :func:`resolve_protective` -- an explicit
``<name> = false`` wins over the default-on protective set -- so it neither runs nor appears in
the ``protective=on:`` stamp. Set by :func:`_apply_config`, reset by :func:`main`."""

ENHANCEMENTS_REQUESTED: tuple[str, ...] = ()
"""``[enhancements]`` entries set true in the ``--config`` file. **This driver applies none of
them** -- it runs the port, and the port is the faithful reproduction (enhancements
live outside the port). Named in the confirmation panel so a config that asks for enhancements
cannot be mistaken for a run that performed them."""

THRESHOLDS_DECLARED: bool = False
"""Whether the ``--config`` file carried a ``[thresholds]`` section at all
(:attr:`arrayprobe.config.RunConfig.thresholds_declared`). One of the two ways an operator
declares a threshold policy without being prompted (:func:`needs_confirmation`); the other is a
command-line ``--regime`` / ``--area-ratio-z`` / ``--default-int-arr-thresh``."""


def _resolve_thresholds() -> ResolvedThresholds:
    """The two S4 threshold fields in force right now, tagged with where each came from.

    Reads the module globals above live (the same reason :func:`config_label` resolves ``PROFILE``
    at call time rather than at a default argument) so a ``--config``/``--regime`` switch applied
    after import is picked up by both the startup print and every ``.call`` stamp this process
    writes.
    """
    return regimes.resolve_thresholds(
        regime_name=REGIME_NAME,
        area_ratio_z_override=AREA_RATIO_Z_OVERRIDE,
        default_int_arr_thresh_override=DEFAULT_IAT_OVERRIDE,
        area_ratio_z_source=AREA_RATIO_Z_SOURCE,
        default_int_arr_thresh_source=DEFAULT_IAT_SOURCE,
        projectname=PROJECT, probename=PROBE, tree=TREE,
    )


def _selected_regime() -> regimes.Regime | None:
    """The :class:`~arrayprobe.regimes.Regime` named by ``--regime`` / ``[thresholds].regime``,
    or ``None``. Read live, like :func:`_resolve_thresholds`."""
    return regimes.REGIMES[REGIME_NAME] if REGIME_NAME is not None else None


def _resolve_reject(profile=None):
    """The S3 :class:`~arrayprobe_uiops.reject_core.RejectConfig` this run uses: the selected
    regime's cited reject slots over ``profile.reject_thresholds``, resolved by
    :func:`arrayprobe.regimes.resolve_reject`.

    Every reject read in this driver goes through here (``tests/test_regime_reject_driver.py``
    sweeps the module). With no regime, or a shipped regime (all six slots INHERIT), it returns
    ``profile.reject_thresholds`` itself, so the computation and the stamp are unchanged.
    ``profile`` defaults to the active :data:`PROFILE`, resolved at call time.
    """
    if profile is None:
        profile = PROFILE
    return regimes.resolve_reject(_selected_regime(), profile.reject_thresholds)


def _reject_sources() -> dict[str, str]:
    """``{field: "regime:<name>"}`` for each reject slot the selected regime sets; empty with no
    regime or an all-INHERIT one."""
    return regimes.regime_reject_sources(_selected_regime())


def reject_sources_text() -> str:
    """Each of the six reject fields with where its value came from: ``regime:<name>`` for a slot
    the regime sets, ``profile:<name>`` for every other (confirmation panel and startup print)."""
    sources = _reject_sources()
    return ", ".join(f"{f}={sources.get(f, f'profile:{PROFILE.name}')}"
                     for f in regimes.REJECT_FIELDS)


def _reject_sources_stamp() -> str:
    """The additive `` regime=<name> reject_sources=(...)`` stamp fragment, or ``""``.

    Absent unless a regime is selected AND sets a reject slot, so a no-regime run and a
    shipped-regime run write the stamp they wrote before the reject slots existed, byte for byte
    (the ``probe_case=`` / ``area_ratio_z=`` absent-when-unused pattern)."""
    sources = _reject_sources()
    if not sources:
        return ""
    body = ",".join(f"{f}={src}" for f, src in sources.items())
    return f" regime={REGIME_NAME} reject_sources=({body})"


def _v35_s4_thresholds() -> dict[str, tuple[float, str]]:
    """Engine 3.5's two S4 threshold keywords for ``sizedist.run``, as ``{name: (value, source)}``.

    Per field, design record section 3's order: ``user:<cli|config>`` > ``regime:<name>``; a
    field neither sets is ABSENT, and v3.5's own case value stands (it is the floor, not a tier
    this driver supplies). So a run with no regime and no override gets ``{}`` and calls
    ``sizedist.run`` exactly as before (``tests/test_regime_v35_driver.py``). Values are passed
    through unconverted, as ``area_ratio_z=AREA_RATIO_Z_OVERRIDE`` always was.
    """
    out: dict[str, tuple[float, str]] = {}
    regime = _selected_regime()
    if AREA_RATIO_Z_OVERRIDE is not None:
        out["area_ratio_z"] = (AREA_RATIO_Z_OVERRIDE, f"user:{AREA_RATIO_Z_SOURCE}")
    elif regime is not None:
        out["area_ratio_z"] = (regime.area_ratio_z, f"regime:{REGIME_NAME}")
    if DEFAULT_IAT_OVERRIDE is not None:
        out["default_int_arr_thresh"] = (DEFAULT_IAT_OVERRIDE, f"user:{DEFAULT_IAT_SOURCE}")
    elif regime is not None:
        out["default_int_arr_thresh"] = (regime.default_int_arr_thresh, f"regime:{REGIME_NAME}")
    return out


def _v35_iat_unused_note() -> str | None:
    """``"unused, applyIntArrThresh=0"`` when this run's v3.5 case has the shattering gate off, so
    a supplied ``default_int_arr_thresh`` changes nothing (design record section 2: said, not
    refused, or every regime would be unusable on a probe whose stock gate is 0); else ``None``.
    A case this process cannot resolve gives ``None`` -- S4 itself raises on it."""
    sd = _v35().module("sizedist")
    try:
        cfg = (sd.resolve_probe_case(PROBE_CASE).defaults if PROBE_CASE is not None
               else sd.probe_defaults(PROJECT, PROBE, version="3.5"))
    except LookupError:
        return None
    return None if cfg.applyIntArrThresh else "unused, applyIntArrThresh=0"


def _v35_otherwise_hvps_bins_on_2ds() -> bool:
    """True when this engine-3.5 S4 run sizes a 2D-S on the HVPS bin table (an upstream defect).

    Stock v3.5 ``sizeDist.m``'s ``otherwise`` branch carries the HVPS ladder under
    ``case '2DS'`` (``:497``, ``:502-505``: 28 bins, 0.2-30 mm), so a 2D-S run under an unlisted
    project with no ``--probe-case`` bins nearly every particle out of range. Detected from the
    resolved table (:func:`arrayprobe_uiops.sizedist_tables.probe_defaults`), never from project
    names. A case this process cannot resolve gives ``False`` -- S4 itself raises on it."""
    if ENGINE != "3.5" or PROBE_CASE is not None or PROBE != "2DS":
        return False
    try:
        cfg = _v35().module("sizedist").probe_defaults(PROJECT, PROBE, version="3.5")
    except LookupError:
        return False
    microns = getattr(cfg.bins, "microns", None)
    return microns is not None and len(microns) == 29 and microns[0] == 200.0


BIN_TABLE_FIX = "bin_table_fix"
"""The bin-table correction's name: default ON for an engine-3.5 2D-S that resolves to
the otherwise branch's HVPS table with no ``--probe-case``; off under ``--protective off`` or
``[enhancements] bin_table_fix = false``. Applied by this driver (:data:`DRIVER_PROTECTIVE`)."""


def bin_table_fix_on() -> bool:
    """Whether S4 sizes this run on the 2D-S ladder instead of the HVPS table."""
    return (_v35_otherwise_hvps_bins_on_2ds() and PROTECTIVE_MODE != "off"
            and BIN_TABLE_FIX not in ENHANCEMENTS_DECLARED_OFF)


def _s4_probe_case() -> str | None:
    """The probe case S4 hands engine 3.5: ``--probe-case`` when given, else
    ``v35-2ds-ladder-fix`` when :func:`bin_table_fix_on`, else None (v3.5's own switch)."""
    if PROBE_CASE is not None or not bin_table_fix_on():
        return PROBE_CASE
    return _v35().module("sizedist").register_v35_2ds_ladder_fix().name


V11_BINS_WARNING = (
    "WARNING (upstream bin-table defect): engine 3.5 is sizing this 2D-S on stock "
    "sizeDist.m's otherwise-branch "
    "bin table, which is the HVPS one -- 28 bins, 0.2-30 mm (v3.5 sizeDist.m:497, :502-505). Most "
    "2D-S particles are below 0.2 mm, so the size distribution will be nearly empty. Remedy: "
    "--probe-case with a registered 2D-S case (and --probe-case-module), or --engine 3.1.4 for "
    "ORACLES "
    "validation. Proceeding with stock behaviour; the sd stamp records bins=v35-otherwise-hvps.")


def _v35_s4_stamp() -> str:
    """The sd stamp's v3.5 threshold fragment: `` area_ratio_z=<v>`` then
    `` default_int_arr_thresh=<v>``, each only when :func:`_v35_s4_thresholds` supplies it.

    A user-set value is written bare, exactly as ``area_ratio_z=`` always was, so every sd built
    with ``--area-ratio-z`` keeps its stamp; a regime-supplied value carries ``(regime:<name>)``,
    and a ``default_int_arr_thresh`` the case's gate ignores says so (design record section 3)."""
    s4 = _v35_s4_thresholds()
    out = ""
    for name in ("area_ratio_z", "default_int_arr_thresh"):
        if name not in s4:
            continue
        value, source = s4[name]
        tags = [] if source.startswith("user:") else [source]
        if name == "default_int_arr_thresh":
            note = _v35_iat_unused_note()
            if note is not None:
                tags.append(note)
        out += f" {name}={value!r}" + (f" ({'; '.join(tags)})" if tags else "")
    return out


def _profile_with_resolved_reject(profile=None):
    """``profile`` with ``reject_thresholds`` replaced by :func:`_resolve_reject`, for the v3.1.4
    S3 call (``imgproc.py:1334`` reads ``profile.reject_thresholds``). The profile object itself
    when the regime sets no slot, so the default path passes exactly what it always passed."""
    if profile is None:
        profile = PROFILE
    rc = _resolve_reject(profile)
    if rc is profile.reject_thresholds:
        return profile
    return dataclasses.replace(profile, reject_thresholds=rc)


def thresholds_stamp() -> str:
    """``"tree=<tree> area_ratio_z=<v> (<source>) default_int_arr_thresh=<v> (<source>)"`` -- the
    S4 threshold fragment the ``.call`` sidecar was missing before the regime work (measured: an
    ARM-ENA ``sd`` file's stamp carried neither value, so a reader could not tell how
    ORACLES-flavoured the run was). Engine 3.5 reads no ``tree``, so this fragment is v3.1.4-only
    and :func:`sd_call_label` only appends it there; engine 3.5 writes :func:`_v35_s4_stamp`.
    """
    r = _resolve_thresholds()
    return (f"tree={TREE} area_ratio_z={r.area_ratio_z.render()} "
            f"default_int_arr_thresh={r.default_int_arr_thresh.render()}")


def _legacy_thresholds_stamp() -> str:
    """What :func:`thresholds_stamp` would have said for THIS PROJECT/PROBE had every run before
    2026-09-17 stamped it -- i.e. always ``tree=production`` with no regime and no override.  Used
    only to make an OLDER stamp (which has no ``tree=`` key at all) compare equal to a current one
    when nothing about the run's actual configuration changed, the same precedent
    :func:`_engine_prefix`/``_stamps_equivalent`` set for ``engine=`` on 2026-09-15.
    """
    r = regimes.resolve_thresholds(projectname=PROJECT, probename=PROBE, tree="production")
    return (f"tree=production area_ratio_z={r.area_ratio_z.render()} "
            f"default_int_arr_thresh={r.default_int_arr_thresh.render()}")


#: Where an operator reads about the things the confirmation panel names. Kept as data rather
#: than interpolated prose so a moved document is one edit here, and so
#: ``tests/test_run_flight_confirm.py`` can assert every path still exists in the repository
#: (a pointer to a file that is gone is worse than no pointer).
CONFIRM_REFERENCES: tuple[tuple[str, str], ...] = (
    ("regimes and what each threshold is justified by",
     "src/arrayprobe/regimes.py"),
    ("what a config file may set, and the two fields it may state raw",
     "docs/06-configuration.md"),
    ("enhancements: what exists, and how to run them",
     "enhancements_uiops/docs/CORRECTIONS.md"),
    ("which engine reproduces what",
     "docs/developer/TWO_ENGINES.md"),
)


def confirmation_lines(args, resolved: ResolvedThresholds | None) -> list[str]:
    """Every run-shaping decision in force, as the operator is asked to confirm it.

    This is the *whole* configuration in one block -- engine, profile, preset, the S4 thresholds
    with the ``stock``/``regime:``/``user:`` tag attached to each, the enhancement policy,
    and where to read more. The startup print above announces the same facts; this panel exists
    because announcing is not the same as being asked, and the ARM-ENA defect (an unrecognised
    project silently inheriting ORACLES's own tuning for months) was announced to nobody.

    ``resolved`` is ``None`` for ``--engine 3.5``, which reads no ``tree``; its S4 values come
    from :func:`_v35_s4_thresholds`.
    """
    out = [
        "",
        "=== confirm this run " + "=" * 47,
        f"  engine                 {ENGINE}",
        f"  fidelity profile       {PROFILE.name}",
        f"  campaign preset        {args.preset}  "
        f"(probe={PROBE} channel={ORIENTATION} project={PROJECT})",
        f"  stages                 {args.stages}",
        f"  config file            {CONFIG_PATH or '(none -- command line only)'}",
    ]
    if resolved is not None:
        rc = _resolve_reject()
        out += [
            "  S3 reject set          "
            + ", ".join(f"{f.name}={getattr(rc, f.name)}" for f in dataclasses.fields(rc)),
        ]
        if _reject_sources():
            # Design record section 3: where each reject value came from, shown only when a
            # regime supplies one (an all-INHERIT regime leaves the panel as it always was).
            out.append("  S3 reject sources      " + reject_sources_text())
        out += [
            f"  S4 tree                {TREE}",
            f"  area_ratio_z           {resolved.area_ratio_z.render()}",
            f"  default_int_arr_thresh {resolved.default_int_arr_thresh.render()}",
        ]
        if any(regimes.is_default_source(s) for s in (resolved.area_ratio_z.source,
                                                      resolved.default_int_arr_thresh.source)):
            # The sentence the confirmation exists to force somebody to read. `default` does not
            # mean
            # "neutral": it is ORACLES's own warm-liquid tuning, which is correct for ORACLES
            # and was never chosen by any other campaign that inherited it.
            out += [
                "  ^ a value tagged 'default' was chosen by nobody for this campaign: it is the",
                "    historical hard-coded fallback, which for project/probe rows with no entry",
                "    of their own is ORACLES's warm-liquid tuning. Name --regime, or state the",
                "    value in [thresholds], if this is not an ORACLES-like case.",
            ]
    else:
        s4 = _v35_s4_thresholds()
        if not s4:
            out.append("  S4 thresholds          "
                       "n/a under --engine 3.5 (no regime, no tree switch)")
        else:
            out.append("  S4 thresholds          "
                       "v3.5 case values, except as listed (no tree switch)")
        if _reject_sources():
            out.append("  S3 reject sources      " + reject_sources_text())
        if "area_ratio_z" in s4:
            value, source = s4["area_ratio_z"]
            who = "user-set" if source.startswith("user:") else source
            out.append(f"  area_ratio_z           {value!r} (v3.5 sizeDist.m:1162, "
                       f"{who}; stock .2 when unset)")
        if "default_int_arr_thresh" in s4:
            value, source = s4["default_int_arr_thresh"]
            note = _v35_iat_unused_note()
            out.append(f"  default_int_arr_thresh {value!r} ({source}; replaces the case's "
                       "defaultIntArrThresh" + (f"; {note}" if note else "") + ")")
    if getattr(args, "enhancements", False):
        # Still default OFF; this branch is only reached because the operator asked.
        out.append("  enhancements           ON -- --enhancements was given. The stages below "
                   "write the port's")
        out.append("                         own faithful output first, unchanged and stamped "
                   "as always; each")
        out.append("                         correction then writes a SEPARATE "
                   "<stem>.enh.<stage>.nc beside it.")
        if ENHANCEMENTS_REQUESTED:
            out.append("                         the config names "
                       + ", ".join(ENHANCEMENTS_REQUESTED) + ";")
            out.append("                         every other registered module stays OFF.")
        else:
            out.append("                         the config names NONE, so nothing will be "
                       "applied -- the flag")
            out.append("                         selects no corrections by itself.")
    else:
        out.append("  enhancements           OFF -- the default, and this run did not pass "
                   "--enhancements.")
        out.append("                         The port is the faithful reproduction and is what "
                   "runs here.")
        if ENHANCEMENTS_REQUESTED:
            out.append("                         the config asks for "
                       + ", ".join(ENHANCEMENTS_REQUESTED)
                       + " -- NOT applied by this run;")
            out.append("                         add --enhancements, or run "
                       "`arrayprobe-enhanced run`.")
        elif CONFIG_PATH is not None and not ENHANCEMENTS_DECLARED:
            out.append("                         the config states no [enhancements] policy at "
                       "all; add an")
            out.append("                         explicit (even empty) section so the file says "
                       "so on its face.")
    out.append("  read more:")
    for what, where in CONFIRM_REFERENCES:
        out.append(f"    - {what}")
        out.append(f"      {where}")
    out.append("=" * 68)
    return out


def needs_confirmation(args) -> bool:
    """Whether this run must be confirmed before it starts.

    **Not every run.** A run whose threshold policy the operator actually stated -- a ``--regime``
    or a raw override on the command line, or a ``--config`` carrying a ``[thresholds]`` section --
    has already been declared in writing, which is exactly what the confirmation is meant
    to achieve (*"or ask them to confirm the config file first where all thresholds and an
    enhancement flag are obvious and evident"*). Confirming it again would train the reflex of
    dismissing the panel, which is how a gate stops being a gate.

    So the prompt fires for the **under-declared** run: no regime, no override, no ``[thresholds]``
    section -- the shape that silently inherited ORACLES's tuning for every ARM-ENA run to date.
    ``--engine 3.5`` resolves no regime at all and is never gated here.
    """
    if ENGINE == "3.5":
        return False
    if THRESHOLDS_DECLARED:
        return False
    return (REGIME_NAME is None
            and AREA_RATIO_Z_OVERRIDE is None
            and DEFAULT_IAT_OVERRIDE is None)


def confirm_or_declare(args, resolved: ResolvedThresholds | None) -> int:
    """Print the configuration and get assent. Returns ``0`` to proceed, non-zero to stop.

    Two paths, and the second one is not a fallback but the normal case for this project:

    * **stdin is a terminal** -- ask, and read the answer.
    * **stdin is not a terminal** -- a detached run (in the background),
      CI, or a script. There is nobody to ask: ``nohup`` redirects stdin, so a
      blocking prompt would hang the run for as long as anyone left it, which is a far worse
      failure than the silent default this gate exists to catch. Assent is declared in the
      command line instead, with ``--yes``; without it the run **refuses to start**, having
      printed everything it would have done. Failing here costs seconds; the ARM-ENA defect
      this replaces cost months of runs nobody could tell apart from correct ones.
    """
    for line in confirmation_lines(args, resolved):
        log(line)
    if args.yes:
        log("confirmed by --yes (no prompt shown)")
        return 0
    if not sys.stdin.isatty():
        log("this run is not configured explicitly (see above) and stdin is not a terminal, so "
            "there is nobody to ask.")
        log("Declare the configuration and re-run: pass --regime <name> (or --area-ratio-z / "
            "--default-int-arr-thresh, or a --config with a [thresholds] section), or pass "
            "--yes to accept exactly what is printed above.")
        return 2
    try:
        answer = input("proceed with this configuration? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        log("no answer; not starting")
        return 2
    if answer in ("y", "yes"):
        log("confirmed at the prompt")
        return 0
    log("not confirmed; nothing ran")
    return 2


def _decode_naming():
    """:mod:`arrayprobe_uiops.decode_naming`, the one place a stage-2 decode is named.

    It is shared code (engine and reader decide the extension together, for both engines), not
    the v3.5 engine, so it is the one ``arrayprobe_uiops`` module this driver imports by name
    rather than through :func:`_v35`'s selector; ``uiops.CATALOGUE`` lists the v3.1.4 port's
    modules and has no entry for it. Deferred, so loading the driver loads nothing from that
    package."""
    from arrayprobe_uiops import decode_naming
    return decode_naming


def image_suffix_for_probe(probe: str | None = None) -> str:
    """The extension S2 actually leaves on disk for ``probe`` under :data:`ENGINE`:
    :func:`arrayprobe_uiops.decode_naming.decode_suffix` of the engine and :func:`channel_token`.

    Only probetype 2 (2DS/HVPS/3VCPI) has a v3.5 decoder of its own, so only its suffix moves
    with the engine (channel ``H``/``V``). Every other probetype goes through a reader this
    project ships once for both engines -- ``read_binary_SEA`` is byte-identical between the two
    vendored MATLAB trees, and ``read_binary_PMS``/``read_binary_DMT`` have no v3.5 variant --
    and those readers write ``.cdf`` whatever ``--engine`` says.

    **The suffix is the reader's, not the engine's, and reading it as the engine's was a real
    defect** (found 2026-09-21 by running CIP through this driver for the first time):
    an engine-keyed table made a CIP run under ``--engine 3.5`` decode 23,939 records into
    ``<stem>.CIP.cdf`` and then fail with *"S2 did not leave a current <stem>.CIP.nc -- a
    prerequisite was silently missing"*: 4.4 minutes and 2.6 GB spent producing exactly the right
    file under a name the next stage did not look for. The rule now lives in one module for every
    caller (``tests/test_decode_suffix_single_source.py``).
    """
    return _decode_naming().decode_suffix(ENGINE, channel_token(probe))


@dataclass(frozen=True)
class V35Call:
    """The switches v3.5's ``imgProc_sm``/``sizeDist`` take that the v3.1.4 call hard-codes or
    lacks -- one record, chosen whole and stamped, never assembled at the command line (the
    ``CampaignPreset`` rule).

    Every value here is **v3.5's own vendored default** where the vendored source states one
    (``UIOPS-v3.5/joefinlon-UIOPS-039be82/``): a user running this engine gets v3.5's behaviour,
    not a v3.1.4 imitation. ``i_rect_ellipse``/``i_calc_all_diode_stats`` and the three ``sizeDist``
    switches were commented-out hardcoded variables before Joe Finlon moved them into the argument
    list (``imgProc_sm.m:86``, ``sizeDist.m:91``), and those commented lines are literally captioned
    "default"/"Default" -- the strongest evidence the vendored tree offers. ``i_qc``/``i_new_habit``
    are positional arguments added directly (2023/2024) with no MATLAB-side default ever stated;
    ``0`` is kept as the baseline behaviour each docstring line describes first ("Do not QC image",
    "Use existing Holroyd scheme" -- the only scheme v3.1.4 has at all). ``tas_ratio`` is v3.5's own
    fallback when the optional third ``varargin`` element is omitted (``iTAS = 0``, ``:242-247``).
    ``software`` has no MATLAB default at all (a bare, unchecked ``fopen('version.txt')``); its
    value is the vendored file's own contents, verbatim.

    ``iaThreshType`` is not here: it is derived per run from ``--iat-file`` (1 with a file, 0
    without, v3.5 ``sizeDist.m:79,99-101``), or 2 by :data:`IA_THRESH_TYPE`."""

    i_rect_ellipse: int          # imgProc_sm.m:115  "iRectEllipse = 0;  % Set defualt to no
                                  # Rectangle fit and Ellipse fit" (commented out at :86's move
                                  # into input parameters; v3.5's own default)
    i_calc_all_diode_stats: int  # imgProc_sm.m:117-120  "Only enable if actually needed" /
                                  # "iCalcAllDiodeStats = 0;" (same commented-out block; v3.5's
                                  # own default)
    i_qc: int                 # imgProc_sm.m:20  "0 - Do not QC image (EXPERIMENTAL)"; a required
                               # argument added 2023 (ED/JF 12/27/23) with no MATLAB-side default
    i_new_habit: int          # imgProc_sm.m:21  "0 - Use existing Holroyd scheme"; v3.1.4 has
                               # only Holroyd; a required argument with no MATLAB-side default
    i_create_aspect_ratio: int  # sizeDist.m:93  "iCreateAspectRatio = 0; % Default not to
                                 # process aspect ratio info" -- v3.5's own default
    i_create_bad: int         # sizeDist.m:92  "iCreateBad = 0; % Default not to output bad
                               # particles PSDs and other info" -- v3.5's own default
    i_save_int_arr_sv: int    # sizeDist.m:94  "iSaveIntArrSV = 0; % Default not to save
                               # inter-arrival time and sample volume information" -- v3.5's own
                               # default. NOT the ORACLES fork's value (ORACLES-variant sizeDist.m
                               # hard-codes 1 there): see the coordinator note in this module's
                               # provenance string below.
    software: str             # UIOPS-v3.5/joefinlon-UIOPS-039be82/version.txt, verbatim
    provenance: str

    def imgproc_stamp(self, tas_ratio: str = "off") -> str:
        """The v3.5 imgProc_sm switches and software version, as written into the proc .call
        stamp. ``tas_ratio`` is ``off`` (the default, verbatim) or ``on``: whether
        ``varargin{3}`` carried the decode's ``tasRatio``."""
        return (f"call=(iRectEllipse={self.i_rect_ellipse},"
                f"iCalcAllDiodeStats={self.i_calc_all_diode_stats},"
                f"iQC={self.i_qc},iNewHabit={self.i_new_habit},tas_ratio={tas_ratio}) "
                f"software={self.software}")

    def sizedist_stamp(self, iat_file: str | None, ia_thresh_type: int | None = None) -> str:
        """The v3.5 sizeDist switches for the sd .call stamp; iaThreshType defaults to 1 when a
        threshold file is named, else 0."""
        if ia_thresh_type is None:
            ia_thresh_type = 1 if iat_file else 0
        return (f"sizedist=(iaThreshType={ia_thresh_type},"
                f"iCreateAspectRatio={self.i_create_aspect_ratio},iCreateBad={self.i_create_bad},"
                f"iSaveIntArrSV={self.i_save_int_arr_sv})")


V35_CALL = V35Call(
    i_rect_ellipse=0, i_calc_all_diode_stats=0, i_qc=0, i_new_habit=0,
    i_create_aspect_ratio=0, i_create_bad=0, i_save_int_arr_sv=0,
    software="UIOOPS_v3.5",
    provenance=("every field is v3.5's OWN vendored default, not a v3.1.4 imitation (coordinator "
                "check, 2026-09-13): imgProc_sm.m's iRectEllipse/iCalcAllDiodeStats were "
                "hardcoded 0 before being moved into the argument list (:86,:115,:117-120, both "
                "commented lines captioned 'default'); iQC/iNewHabit are required arguments added "
                "later with no MATLAB-side default, kept at 0 (the baseline each docstring line "
                "names first: 'Do not QC image', 'Use existing Holroyd scheme'); tas_ratio=None is "
                "v3.5's own fallback when the optional third varargin is omitted (:242-247, "
                "iTAS=0). sizeDist's iCreateAspectRatio/iCreateBad/iSaveIntArrSV were similarly "
                "hardcoded before being moved into the argument list, and the commented-out lines "
                "(:91-94) are literally captioned 'Default': all three are 0. DEVIATION FROM THE "
                "PLAN OF RECORD: the plan pinned iSaveIntArrSV=1, the ORACLES fork's own "
                "hard-coded production value (campaign-fork:sizeDist.m:60), describing all "
                "three sizeDist "
                "switches as 'the values that select v3.1.4's behaviour' rather than v3.5's own "
                "defaults. Two of those three (iCreateAspectRatio, iCreateBad) happen to be 0 "
                "either way; iSaveIntArrSV does not (fork: 1, v3.5's own default: 0). Since the "
                "vendored source states an unambiguous default, this driver runs v3.5 AS v3.5 -- "
                "iSaveIntArrSV=0, not 1 -- so a v3.5 engine run gets v3.5's own behaviour rather "
                "than a value chosen to imitate the v3.1.4/fork call. software='UIOOPS_v3.5' is "
                "the vendored version.txt's own contents; it has no MATLAB default at all (a bare, "
                "unchecked fopen('version.txt'))."),
)


def _v35():
    """The v3.5 engine, through the selector -- the only way this module reaches
    ``arrayprobe_uiops``."""
    import uiops
    return uiops.engine("3.5")


def _at_least_one(text: str) -> int:
    """argparse ``type`` for ``--jobs``/``--chunks``/``--s2-jobs``: a whole number of at least 1.

    Zero or a negative count used to fall through the ``> 1`` tests and run serially without a
    word (P7 catalogue, 2026-09-29); now it is refused in one line, like any other bad value.
    """
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"{value} is less than 1; use 1 for a serial run")
    return value


def _engine_choices() -> tuple[str, ...]:
    """``--engine``'s ``choices``, read from the selector rather than spelled out here a second
    time -- ``uiops.VERSIONS`` is the one place that says which engines exist."""
    import uiops
    return uiops.VERSIONS


def _engine_prefix() -> str:
    """``"engine=<ENGINE> "``, always -- since 2026-09-15 (R4s), a v3.1.4 stamp names its
    own engine too, the same as v3.5's always has.  Before that date ``_engine_prefix()`` returned
    ``""`` under v3.1.4, so an OLDER stamp on disk carries no ``engine=`` key at all; a reader
    (``_stamps_equivalent`` below) treats that absence as ``engine=3.1.4`` rather than as a
    mismatch, so a pre-existing v3.1.4 product does not go stale on this change alone.

    R4: a v3.1.4 run made with ``--port-validation`` (which
    ``main()`` requires of every v3.1.4 run) writes ``engine=3.1.4 port_validation=on `` -- the
    output is port validation, not for quoting. The token lives in this one prefix, so it reaches
    every v3.1.4 stamp writer (image, proc, sd, combine, enhanced) at once; it changes no computed
    byte, so :func:`_stamps_equivalent` ignores it in both directions."""
    if ENGINE == "3.1.4" and PORT_VALIDATION:
        return f"engine={ENGINE} {PORT_VALIDATION_STAMP_KEY}on "
    return f"engine={ENGINE} "


#: Variable names an aircraft file may use for true airspeed and its time base.
#:
#: **The first pair is UIOOPS's own** (``flightData_*.cdf``) and is what
#: ``imgproc.py:518-519`` reads. The rest are aliases met on real files from
#: other providers, each recorded with the file that forced it -- **never
#: guessed**, and each added only after being read out of an actual dataset.
#:
#: Added 2026-09-21, and the incident is the reason: running ARM ACE-ENA
#: through the v3.5 engine died with ``KeyError: 'TAS'`` after a 754-second
#: decode. ARM's merged aircraft file calls it ``true_airspeed`` on a ``time``
#: axis. The v3.1.4 path never met this, because ``stock-v3.5`` is the profile
#: that *requires* an aircraft file at all -- so the gap appeared exactly when
#: the author ruled that non-ORACLES data must run on v3.5.
#: Derived from :data:`arrayprobe.tools.tas_sources.SOURCES` since 2026-09-23: one
#: registry, each entry read off a real file (tas name, time name, the file that forced it).
_TAS_VARIANTS = tuple((_src.tas_var, _src.time_var, _src.evidence)
                      for _src in _tas_sources.SOURCES)

#: The airspeed cutoff and default for every aircraft series this driver reads: the documented
#: defaults (300 / 170 m/s) until a run names others.
TAS_POLICY = _mtf.TasPolicy()

TAS_CHAIN: _tas_sources.ChainResult | None = None


def _tas_ratio_stamp() -> str:
    """The S2 stamp's TAS-ratio field: ``tas_ratio=off`` verbatim when off."""
    if not TAS_RATIO:
        return "tas_ratio=off"
    if TAS_SOURCE is not None:
        # Under a source chain the series is resolved per raw file (its own date), so the stamp
        # names the chain, not a file: this label is also computed with no raw file in hand
        # (preflight, the post-S2 check, reprocess), and the per-file chain path the loop later
        # assigns to TAS_FILE would otherwise make every file but the first read stale.
        return f"tas_ratio=on tas_ratio_src=chain:{TAS_SOURCE}"
    return f"tas_ratio=on tas_ratio_src={Path(TAS_FILE).name if TAS_FILE else 'none'}"


def _s3_tas_ratio(image_file: Path) -> Any:
    """``imgProc_sm``'s ``varargin{3}`` for engine 3.5: the per-record ``tasRatio`` the S2 decode
    wrote under --tas-ratio on, else ``None`` (the ``iTAS == 0`` path, byte-identical to a run
    without the flag).

    Refuses a decode whose stamp disagrees with the run: ``--tas-ratio on`` over a decode stamped
    ``tas_ratio=off`` (it holds no ratio), and ``off`` over one stamped ``tas_ratio=on`` (its
    ratio would be silently dropped). An unstamped decode under ``off`` passes, as before."""
    stamp = read_stamp(image_file) or ""
    if not TAS_RATIO:
        if "tas_ratio=on" in stamp:
            raise UnverifiableProvenance(
                f"{image_file.name} was decoded with tas_ratio=on but this run is "
                "--tas-ratio off; re-run S2, or pass --tas-ratio on")
        return None
    if "tas_ratio=on" not in stamp:
        raise UnverifiableProvenance(
            f"{image_file.name} was not decoded with tas_ratio=on (stamp: {stamp or 'none'}), "
            "so it holds no tasRatio; re-run S2 with --tas-ratio on")
    with netCDF4.Dataset(str(image_file)) as ds:
        if "tasRatio" not in ds.variables:
            raise UnverifiableProvenance(
                f"{image_file.name} is stamped tas_ratio=on but has no tasRatio variable")
        var = ds.variables["tasRatio"]
        var.set_auto_maskandscale(False)
        return np.asarray(var[:], dtype=float)


def _tas_ratio_series(raw: Path | None = None) -> tuple[Any, Any]:
    """(flt_time, flt_tas) for v3.5's decoder under --tas-ratio on, else (None, None).

    With ``--tas-source`` the aircraft series is resolved here, for ``raw``'s own date: the
    decoder (S2) needs it before the per-file loop in :func:`main` resolves the chain for S3/S4,
    which happens after S2, when ``TAS_FILE`` is still ``None``. ``probe_csv`` is not passed: the
    probe's ``<stem>.tas.csv`` is what this decode is about to write, and the ratio is aircraft
    TAS over probe TAS, so the ``probe`` tier can never supply it.
    """
    if not TAS_RATIO:
        return None, None
    if TAS_SOURCE is not None:
        if raw is None:
            raise RuntimeError("--tas-ratio on with --tas-source needs the raw file's date "
                               "to resolve the aircraft airspeed series")
        res = _tas_sources.resolve_chain(
            TAS_SOURCE, yyyymmdd="20" + Path(raw).stem[4:10], search_dirs=TAS_SEARCH,
            probe_csv=None, policy=TAS_POLICY)
        for line in res.lines:
            log(f"S2 tasRatio: {line}")
        if res.tier == "probe":
            raise RuntimeError("--tas-ratio on needs an aircraft airspeed series; the TAS "
                               "source chain resolved to the probe's own airspeed")
        return list(res.time), list(res.tas)
    if not TAS_FILE:
        raise RuntimeError("--tas-ratio on needs the aircraft airspeed series: "
                           "give --tas-source or --tas-file")
    series = _tas_sources.read_aircraft(TAS_FILE)
    tas, _subs = _tas_sources.substitute(series.time_hhmmss, series.tas_mps, TAS_POLICY)
    return list(series.time_hhmmss), list(tas)
"""What :data:`TAS_SOURCE` resolved to for the file currently in flight, or ``None`` when
no source chain is in effect (``TAS_SOURCE`` is ``None``, the legacy ``--tas-file`` path). Set in
the serial per-file loop before S3, read by :func:`config_label` (the ``.call`` stamp) and
:func:`stage4` (which TAS series ``sizeDist`` is handed). Module-level for the same reason
``TAS_FILE`` is: nothing else carries per-file state across S3 -> S4 in this driver."""


def _s3_tas_qc_v35(image_file, tas_time, tas) -> dict | None:
    """The v3.5 stage-3 airspeed record, or None when S3 reads no aircraft series.

    ``imgProc_sm.m:727`` looks each image record's HHMMSS up in the aircraft series by exact
    equality, and a record with no sample (or only NaN) times its particles at
    ``TAS_FALLBACK`` (170 m/s, ``:730-733``/``:763``). Which records those are depends only on
    the decode file's ``hour``/``minute``/``second`` and the series, so it is computed here once,
    before S3, and the same record reaches every chunk and the merged file. Records with no
    particle are counted too: the record, not the particle, is what the lookup keys on.
    """
    if tas_time is None:
        return None
    import netCDF4
    with netCDF4.Dataset(str(image_file)) as ds:
        ds.set_auto_mask(False)
        rec = (np.asarray(ds.variables["hour"][:], dtype=np.float64) * 10000
               + np.asarray(ds.variables["minute"][:], dtype=np.float64) * 100
               + np.asarray(ds.variables["second"][:], dtype=np.float64)).ravel()
    t = np.asarray(tas_time, dtype=np.float64).ravel()
    v = np.asarray(tas, dtype=np.float64).ravel()
    good = set(t[~np.isnan(v)].tolist())    # :1136 tests isnan only, so Inf is used
    miss = ~np.isin(rec, np.asarray(sorted(good), dtype=np.float64))
    secs = sorted({int(x) for x in rec[miss]})
    n, total = int(miss.sum()), int(rec.size)
    fb = _imgproc_tas_fallback()
    return {
        "tas_s3_source": Path(TAS_FILE).name if TAS_FILE else "none",
        "tas_s3_records_total": total,
        "tas_s3_fallback_records": n,
        "tas_s3_fallback_seconds": _mtf.second_ranges(secs) or "none",
        "tas_s3_uncertainty": (
            f"{n} of {total} image records had no aircraft TAS sample at their second, so "
            f"imgProc_sm timed their particles at {fb:g} m/s; inter-arrival times, and so the "
            "shattering rejection, are uncertain there" if n
            else "every image record matched an aircraft TAS sample"),
    }


def _imgproc_tas_fallback() -> float:
    from arrayprobe_uiops.imgproc_core import TAS_FALLBACK
    return float(TAS_FALLBACK)


def _aircraft_series():
    """``(tas_time, tas)`` from :data:`TAS_FILE`.

    Read as ``imgproc.py:518-519`` reads it for v3.1.4; v3.5's ``imgProc_sm``
    takes the two arrays as ``varargin{1..2}`` (``imgProc_sm.m:187``).

    **Resolves the variable names rather than assuming them, and says which it
    used.** A provider's aircraft file is not obliged to use UIOOPS's names, and
    ARM's does not. The alternative -- failing with ``KeyError: 'TAS'`` after
    the decode has already run -- is what this replaces.

    It does **not** guess: only the pairs in :data:`_TAS_VARIANTS` are tried,
    each one read off a real file before being added, and a file matching none
    of them raises with the names it does carry, so the next variant is added
    from evidence instead of from a hunch.
    """
    # Read, converted and identified by the shared registry (arrayprobe.tools.tas_sources,
    # 2026-09-23), so this driver and `make-tas-file` cannot read one file two ways.
    series = _tas_sources.read_aircraft(TAS_FILE)
    name = Path(TAS_FILE).name
    if series.source.tas_var != _TAS_VARIANTS[0][0]:
        log(f"aircraft  {name}: true airspeed read as '{series.source.tas_var}'/"
            f"'{series.source.time_var}' ({series.source.name}), not UIOPS's 'TAS'/'Time'")
    for note in series.notes:
        log(f"aircraft  {name}: {note}")
    # Author's airspeed ruling: never drop -- an out-of-range sample takes the configured default.
    tas, subs = _tas_sources.substitute(series.time_hhmmss, series.tas_mps, TAS_POLICY)
    for sec, orig, why in subs:
        log(f"aircraft  {name}: TAS substituted: {sec:06d} {orig!r} -> "
            f"{TAS_POLICY.default_mps:g} m/s ({why})")
    # The same fail-closed check the sidecar builder applies before it writes: whole,
    # unique, clock-valid HHMMSS, or the exact-match lookup silently misses.
    return _mtf.check_tas_series(series.time_hhmmss, tas)


class UnverifiableProvenance(RuntimeError):
    """An existing stage output whose configuration cannot be established.

    Raised rather than worked around, because both alternatives are worse:
    using the file assumes a configuration nobody recorded (the 2026-08-30
    trap, below), and recomputing it silently spends hours and overwrites
    evidence.  The operator decides -- see ``--accept-unstamped``.
    """


def config_label(profile=None, shadow_diode=None) -> str:
    """The fidelity configuration an output was produced under, as one line.

    WHY THIS EXISTS, AND IT IS A REAL INCIDENT.  On 2026-08-30 flight 09/14 was
    started and two of its four files were skipped as already done.  Their
    ``proc``/``sd`` files were dated Aug 20-21; the reject-threshold correction
    landed Aug 28 (``2d0544f``), so those files carried the *stock* thresholds
    while the new ones would carry the production ones.  Combining them would
    have mixed two configurations inside one flight product -- the exact error
    class this project spent a week untangling on 09/06.  It was caught by
    reading a directory listing, which is not a control.

    The skip is by *existence*, and existence does not record configuration.  So
    the configuration is written beside the output and compared on the next run:
    every field of the profile's :class:`~arrayprobe_uiops.reject_core.RejectConfig` (read
    off the dataclass, so a field added later enters the stamp without anyone
    remembering to add it), the profile's name, and the diode mask, which is the
    other opt-in that changes ``proc`` contents.

    ``profile`` defaults to the **active** :data:`PROFILE`, resolved here rather
    than as ``profile=PROFILE`` in the signature -- a rebound global does not
    reach a default argument (the exact trap :func:`image_call_label`'s
    ``channels`` parameter already documents), so a ``--config``-driven profile
    switch would otherwise go on being stamped with whatever profile was active
    when this module was imported.

    Since 2026-09-13 the aircraft TAS file's basename is appended *only* when
    the profile reads one (``time_in_seconds_from_tas``), because a different
    file changes ``Time_in_seconds``.
    """
    if profile is None:
        profile = PROFILE
    rc = _resolve_reject(profile)
    fields = ",".join(f"{f.name}={getattr(rc, f.name)}"
                      for f in dataclasses.fields(rc))
    diodes = ",".join(str(d) for d in shadow_diode) if shadow_diode else "none"
    label = f"{_engine_prefix()}profile={profile.name} reject=({fields}) shadow_diode={diodes}"
    # Regime reject slots (design record section 3): absent unless a regime sets one.
    label += _reject_sources_stamp()
    if TAS_FILE is not None and profile.time_in_seconds_from_tas:
        # Only when the file reaches the computation (imgproc.py:512): a profile
        # that never reads one -- every ORACLES profile -- keeps the stamp each
        # validated flight was written under, byte for byte
        # (tests/test_run_from_config.py::ValidatedCallStampsAreByteIdentical).
        label += f" tas_file={Path(TAS_FILE).name}"
    if TAS_CHAIN is not None and profile.time_in_seconds_from_tas:
        # The airspeed source chain's own decision record -- which tier, which file, and the
        # policy it ran under -- on top of the bare tas_file basename above. Absent whenever
        # TAS_SOURCE is None (the legacy --tas-file path, untouched), so every default stamp
        # this run ever wrote before the airspeed chain stays byte-identical.
        label += " " + TAS_CHAIN.stamp()
    if ENGINE == "3.5":
        label += " " + V35_CALL.imgproc_stamp("on" if TAS_RATIO else "off")
        # Stray-pixel rule: changes proc bytes, so it is NOT stripped by _stamps_equivalent.
        label += stray_pixel_fragment()
        # NCAR 2DC timing conversion: probetype 0 only; "" for every other probe, so no other
        # stamp changes. Changes proc bytes, so it is NOT stripped by _stamps_equivalent.
        label += ncar_2dc_timing_fragment()
    if AUTHORDEFAULTS_STAMP is not None:
        label += " " + AUTHORDEFAULTS_STAMP
    if ACCEPT_PRESET_MISMATCH:
        label += " " + ACCEPT_PRESET_MISMATCH_STAMP
    return label


def image_call_label(profile=None, channels: str | None = None) -> str:
    """The S2 stamp, plus the preset-mismatch override marker when (and only when) it was used."""
    label = _image_call_label(profile, channels)
    if ACCEPT_PRESET_MISMATCH:
        label += " " + ACCEPT_PRESET_MISMATCH_STAMP
    return label


def _image_call_label(profile=None, channels: str | None = None) -> str:
    """The stamp for an S2 output -- the decode, which is configuration-dependent
    for reasons that have nothing to do with the reject thresholds.

    ``read_binary_SPEC`` reads exactly two profile fields: ``spec_buffer_guard``
    at ``spec.py:412``, and ``hvps_reader`` at ``:848`` to refuse a profile that
    routes HVPS elsewhere. The buffer guard is not cosmetic -- the ORACLES
    lineage predates Finlon's 2017-03-08 guards, so it **dies** on a packet
    stock skips, which is a different file (or no file). ``channels`` decides
    which channel files are written at all.

    So a ``.H.cdf`` is exactly as unaskable about its own provenance as a
    ``proc`` file is, one stage earlier.  ``test_run_flight_provenance.py``
    pins the field list against ``spec.py``'s own attribute accesses, so a
    profile field that starts reaching the decoder fails the suite until it is
    stamped here.

    ``channels`` defaults to the **active preset's** orientation, resolved here
    rather than in the signature: a default argument binds at definition time,
    so ``channels=ORIENTATION`` would have gone on stamping the orientation this
    module was imported with even after ``use_preset`` switched it -- writing a
    ``.V.cdf`` stamped ``H``, which the next stage would then accept as matching.
    """
    if channels is None:
        channels = channel_token()
    if profile is None:
        profile = PROFILE
    plan = s2_reader_for(PROBE)
    if plan.probetype != 2:
        # A single-channel decode (CIP through .sea or .cip, CIP work 2026-09-18).
        # Deliberately NOT the SPEC wording with a substituted token: neither
        # read_binary_SEA nor read_binary_DMT takes a profile or a `channels`
        # argument at all, so `profile=` and `channels=H` here would both name
        # something the decode never read -- the same class of false statement
        # as an `.H.cdf` file name for a stream that was never split. What IS
        # stamped is what decided the bytes: the ENGINE -- the key the
        # hand-written lane scripts omitted, which is how a v3.1.4 CIP product
        # came to be described as v3.5 for a full day (the stamping audit) -- and the probe
        # stream taken out of the container.
        #
        # The dispatched reader is recorded in the `.decode` sidecar instead of
        # here, for the reason that sidecar exists: this label is compared for
        # EXACT equality to decide staleness, and it is computed both before a
        # decode (stage2) and afterwards from the output path alone (main,
        # preflight, reprocess), where no raw file is in hand. A key only some
        # of those callers could fill in would make a current file read stale.
        return f"{_engine_prefix()}probe={plan.probe} channels=none"
    if ENGINE == "3.5":
        # v3.5's reader reads neither spec_buffer_guard nor hvps_reader; it takes `software` and,
        # optionally, the flight series that writes tasRatio (--tas-ratio on; off by default).
        # Stamp what it consumes, not the v3.1.4 fields it never reaches.
        return (f"{_engine_prefix()}profile={profile.name} software={V35_CALL.software} "
                f"{_tas_ratio_stamp()} channels={channels}")
    return (f"{_engine_prefix()}profile={profile.name} "
            f"spec_buffer_guard={profile.spec_buffer_guard} "
            f"hvps_reader={profile.hvps_reader} channels={channels}")


def proc_call_label(profile=None, shadow_diode=None) -> str:
    """The stamp for an S3 output.  S3 is where the reject thresholds bite
    (``imgProc_sm`` calls ``calculate_reject_unified``), so the configuration
    alone identifies the call; ``sizeDist``'s twelfth argument does not reach it."""
    return config_label(profile, shadow_diode) + protective_fragment()


def sd_call_label(iat_file: str | None, profile=None, shadow_diode=None) -> str:
    """The stamp for an S4 output: the twelfth-argument call *and* the
    configuration of the ``proc`` file it was built from.

    Both halves matter and neither implies the other -- the 58% twelfth-argument
    difference (the misreported shattering attribute) and the ~40%-of-large-particles
    reject-threshold difference are independent, and an sd file records neither.

    :func:`config_label` already carries its own ``_engine_prefix()`` at the front (both engines,
    since 2026-09-15), so it is stripped here before this function adds its own once at the front
    -- otherwise the label would read ``engine=3.1.4 iat_file=... engine=3.1.4 profile=...``,
    doubled.
    """
    inner = config_label(profile, shadow_diode).removeprefix(_engine_prefix())
    label = f"{_engine_prefix()}{iat_call_label(iat_file)} {inner}"
    if ENGINE == "3.5":
        label += " " + V35_CALL.sizedist_stamp(iat_file, IA_THRESH_TYPE)
        if PROBE_CASE is not None:
            # The retracted 2D-S bin table: the bin ladder is the single largest thing about an sd
            # file that the file itself cannot be asked -- a product built on a registered case and
            # one built on v3.5's own switch are different science on the same raw bytes (11168.6
            # against 0.0100 on ARM ACE-ENA 2017-07-07), so the stamp has to separate them.
            #
            # Absent for a run that names no case, deliberately: adding an unconditional
            # `probe_case=stock` key would make every v3.5 sd file written before today read as
            # stale against its own stamp, which is exactly what `_stamps_equivalent`'s two
            # additive generations exist to avoid. An absent key means "v3.5's own switch",
            # which is what it always meant.
            label += f" probe_case={PROBE_CASE}"
        if _v35_otherwise_hvps_bins_on_2ds():
            # upstream bin-table defect: a 2D-S on the otherwise branch's HVPS ladder,
            # corrected by default on engine 3.5 or kept under the protective opt-out.
            # Present only in that case, so
            # every other stamp is byte-identical to before the key existed.
            label += (" bins=2ds-ladder(V11-fix)" if bin_table_fix_on()
                      else " bins=v35-otherwise-hvps")
        # v3.5 sizeDist.m:1162's literal `.2` and the case's defaultIntArrThresh, each replaced
        # for this run by a user override or the selected regime. Absent for every run that
        # sets neither, so every v3.5 sd file written before these keys existed still reads as
        # current, the `probe_case` pattern above (_v35_s4_stamp).
        label += _v35_s4_stamp()
        if TIME_OFFSET is not None:
            # Absent when unset, so every existing v3.5 sd stamp stays current; the evidence is
            # JSON-quoted so a statement with spaces or newlines keeps the stamp one line.
            seconds, evidence, tas_clock = TIME_OFFSET
            label += (f" time_offset_s={seconds} time_offset_tas_clock={tas_clock}"
                      f" time_offset_evidence={json.dumps(evidence)}")
        # Engine-3.5 defect correction: whether the time-grid and zero-sample-volume
        # corrections ran. Unlike their
        # counts this is configuration, so an input made under the other setting reads stale; a
        # stamp written before the marker existed was made without them and reads as off
        # (_stamps_equivalent).
        label += f" {TIME_SV_FIX_STAMP_KEY}{'on' if v35_time_sv_fix_active() else 'off'}"
    else:
        if LIBM_POW:
            label += " libm_pow=on"
        # tree/area_ratio_z/default_int_arr_thresh were computed by S4 but never recorded,
        # so a reader of the sidecar alone could not tell an ORACLES-flavoured run from one that
        # chose those values. v3.5 has no `tree` and reads neither field (its own sizeDist.m
        # switch is a different mechanism), so this fragment is v3.1.4-only.
        label += " " + thresholds_stamp()
    # Both engines; absent unless set, so every stamp written without them is unchanged.
    label += _s4_case_inputs_stamp()
    if ACCEPT_IMPLAUSIBLE and _plausibility_gate_applies():
        label += " " + ACCEPT_IMPLAUSIBLE_STAMP
    if IAT_SOURCE is not None:
        label += f" iat_source={IAT_SOURCE} basis=configuration"
    if TAS_CHAIN is not None:
        # The airspeed chain and the author's E2 ruling (2026-09-23): S4 always swaps in the chain's
        # own policy-substituted TAS series in place of the raw <stem>.tas.csv once a run
        # opts into a chain (TAS_SOURCE set) -- including a probe-tier chain, which used to
        # read the file's own -999/241,403 m/s rows unmodified. So this key names which
        # series built the file for every tier the chain can resolve to, probe included.
        # `config_label` (via `inner` above) already named which chain ran.
        label += f" tas_series={TAS_CHAIN.tier}:{TAS_CHAIN.source}"
        if not (profile or PROFILE).time_in_seconds_from_tas:
            # The series S4 sizes on is the policy-substituted one, but config_label names the
            # chain and its policy only for a profile that reads an aircraft file. Without this
            # a run under another cutoff/default read the old sd as current. An older stamp
            # without it reads as the default policy (_stamps_equivalent).
            label += f" {TAS_SERIES_POLICY_KEY}({TAS_CHAIN.policy.token()})"
    if TAS_FROM_PROBE:
        # Author decision 2026-09-24: the CIP's airspeed is the 2D-S's record of the same
        # aircraft. The sd file cannot say which series sized it, so the stamp does -- and a sd
        # built on some other <stem>.tas.csv reads stale against this one and is rebuilt.
        label += " tas_series=probe_hk:" + ",".join(Path(p).name for p in TAS_FROM_PROBE)
    if TAS_CHAIN is not None and TAS_GRID == "regular":
        # Absent at the default, so every sd stamp written before --tas-grid existed stays
        # current; present, it makes a probe-grid sd read stale and be rebuilt.
        label += " tas_grid=regular"
    elif TAS_CHAIN is None and tas_grid_fix_on():
        label += " tas_grid=collapse"
    return label + protective_fragment()


def protective_fragment() -> str:
    """`` protective=on:<names>`` or `` protective=off`` for a run off the ORACLES lineage; ``""``
    on probetype 2, so no 2D-S/HVPS stamp changes. Ignored by :func:`_stamps_equivalent`:
    the protective correction writes separate files and changes no port byte."""
    try:
        if s2_reader_for(PROBE).probetype == 2:
            return ""
    except UnsupportedProbe:
        return ""
    if PROTECTIVE_ON:
        return f" {PROTECTIVE_STAMP_KEY}on:{','.join(PROTECTIVE_ON)}"
    return f" {PROTECTIVE_STAMP_KEY}off"


PROTECTIVE_STAMP_KEY = "protective="

#: The sd stamp's key for the TAS policy of a chain run whose profile reads no aircraft file.
TAS_SERIES_POLICY_KEY = "tas_series_policy="


def _strip_protective(stamp: str) -> str:
    """``stamp`` without its ``protective=`` token, wherever it sits."""
    return " ".join(t for t in stamp.split(" ") if not t.startswith(PROTECTIVE_STAMP_KEY))


#: The S2 ``.call`` keys the raw-input inventory adds. They describe the INPUT
#: (its checksum and whether it was empty or cut mid-record), not the configuration, so
#: :func:`_stamps_equivalent` strips them from both sides: an older stamp without them is current.
#: No earlier ``.call`` key recorded a raw checksum, so ``raw_sha256=`` is new. Never a netCDF
#: attribute: faithful products stay byte-identical.
INVENTORY_STAMP_KEYS = ("inventory_empty=", "inventory_truncated=", "raw_sha256=")

#: ``--accept-flagged``: run a raw file the inventory flags as empty (a partial last record warns).
ACCEPT_FLAGGED = False

#: Inventory rows by resolved raw path, filled by :func:`inventory_preflight` before any decode.
INVENTORY_ROWS: dict[str, dict] = {}


def _strip_inventory(stamp: str) -> str:
    """``stamp`` without the raw-input inventory tokens (:data:`INVENTORY_STAMP_KEYS`)."""
    return " ".join(t for t in stamp.split(" ") if not t.startswith(INVENTORY_STAMP_KEYS))


def _inventory_fmt(raw: Path) -> str | None:
    """The inventory format the driver's own reader choice implies, or ``None`` (use the guess).

    Read from the S2 reader the active probe routes to (the same lookup :func:`stage2` makes),
    never from the file name: SPEC readers -> ``spec``, ``read_binary_DMT`` -> ``dmt``,
    ``read_binary_PMS`` -> ``pms_2d``; SEA and anything else -> ``None``."""
    try:
        plan = s2_reader_for(PROBE)
        if not plan.supported:
            return None
        dotted = s2_reader_for_raw(PROBE, raw) if plan.formats else plan.reader
    except Exception:  # noqa: BLE001 - the decode's own gates report these, with their messages
        return None
    if plan.probetype == 2:
        return "spec"
    if dotted == _DMT_READER:
        return "dmt"
    if dotted and dotted.endswith("read_binary_PMS"):
        return "pms_2d"
    return None


def inventory_preflight(raws) -> int:
    """Inventory each raw file before any decode; 0 to proceed, 2 to refuse.

    An empty file is refused unless ``--accept-flagged`` (:data:`ACCEPT_FLAGGED`). A file
    whose size is not whole records of the format the driver will read it with (a trailing
    partial record, which a logger leaves on every file cut at power-off) is only warned
    about: the readers decode that tail on purpose, exactly as the MATLAB does, so it is
    logged and stamped, never refused. The row is kept in :data:`INVENTORY_ROWS` so
    :func:`stage2` stamps it into the decode's ``.call``."""
    from arrayprobe.inventory import inventory_row
    refused = 0
    for raw in raws:
        if not Path(raw).is_file():
            continue  # the per-file loop reports MISSING itself
        row = inventory_row(raw, fmt=_inventory_fmt(Path(raw)))
        INVENTORY_ROWS[str(Path(raw).resolve())] = row
        flags = [k for k in ("empty", "truncated") if row.get(k)]
        if not flags:
            continue
        what = (f"{Path(raw).name}: inventory flags it {' and '.join(flags)} "
                f"(size {row['size']} bytes, format {row['format_guess']}, "
                f"record {row.get('record_bytes')} bytes, trailing "
                f"{row.get('trailing_bytes')} bytes)")
        if ACCEPT_FLAGGED:
            log(f"FLAGGED   {what}; proceeding under --accept-flagged")
        elif flags == ["truncated"]:
            log(f"WARNING   {what}; the reader decodes the partial trailing record as the "
                f"original does, so proceeding (recorded in the decode's .call)")
        else:
            log(f"REFUSED   {what}. Re-run with --accept-flagged to process it anyway")
            refused += 1
    return 2 if refused else 0


def _inventory_fragment(raw: Path) -> str:
    """The S2 ``.call`` fragment for ``raw``'s inventory row, or ``""`` when none was taken."""
    row = INVENTORY_ROWS.get(str(Path(raw).resolve()))
    if row is None:
        return ""
    def b(v):
        return "na" if v is None else ("1" if v else "0")
    return (f" inventory_empty={b(row.get('empty'))}"
            f" inventory_truncated={b(row.get('truncated'))}"
            f" raw_sha256={row['sha256']}")


def _strip_port_validation(stamp: str) -> str:
    """``stamp`` without its ``port_validation=`` token, wherever it sits (top level or inside
    ``inputs_built_with=(...)``). The token always directly follows ``engine=3.1.4``, so it is
    never adjacent to a parenthesis and a space-split removes it cleanly."""
    return " ".join(t for t in stamp.split(" ") if not t.startswith(PORT_VALIDATION_STAMP_KEY))


def s2_plan_is_lineage() -> bool:
    """Whether the active probe is on the ORACLES 2D-S/HVPS lineage (probetype 2)."""
    try:
        return s2_reader_for(PROBE).probetype == 2
    except UnsupportedProbe:
        return False


_ENHANCEMENTS_MISSING = ("arrayprobe-enhancements is not installed; install it with "
                         "`pip install arrayprobe-uiops-enhancements` (or `pip install "
                         "\"arrayprobe[enhancements]\"`; from a source checkout, "
                         "`pip install -e enhancements_uiops`)")
"""The one-line refusal for an optional-dependency import that fails: the package to install
and how. The port never needs ``arrayprobe_enhancements``; only a run that applies a correction
does, so each such import is guarded (tests/test_no_enhancement_coupling.py)."""


def resolve_protective(mode: str | None = None) -> tuple[str, ...]:
    """The protective set for the active probe and engine under ``mode`` (default
    :data:`PROTECTIVE_MODE`). On probetype 2 it is empty except on engine 3.5, where it holds
    :data:`BIN_TABLE_FIX` when :func:`bin_table_fix_on` (an upstream bin-table defect, corrected
    by default on engine 3.5). Raises
    ``ImportError`` when a non-empty set is due and ``arrayprobe_enhancements`` is not importable
    -- the caller refuses with exit 2 before any stage runs."""
    mode = PROTECTIVE_MODE if mode is None else mode
    plan = s2_reader_for(PROBE)
    if mode == "off":
        return ()
    if plan.probetype == 2:
        # The lineage exception is engine 3.1.4's (port validation) alone: on engine 3.5 a
        # data-destroying upstream defect is corrected by default. Only the
        # driver-applied bin-table fix reaches probetype 2 today.
        if ENGINE != "3.5":
            return ()
        return (BIN_TABLE_FIX,) if bin_table_fix_on() else ()
    try:
        from arrayprobe_enhancements import pipeline, registry
    except ImportError as exc:
        raise ImportError(f"{_ENHANCEMENTS_MISSING} ({exc})") from exc
    # Every protective name is applied, either by the post-stage chain (a pipeline adapter)
    # or by this driver itself (DRIVER_PROTECTIVE). A name that is neither is refused by name
    # rather than dropped: until 2026-09-26 tas_grid_fix was filtered out here silently and
    # never ran on the probetypes registry.PROTECTIVE lists it for.
    due = registry.protective_set(ENGINE, PROBE, plan.probetype)
    # An explicit `<name> = false` in the config wins (the plan of record for this switch): the
    # name leaves the set here, so it is not applied, not stamped as protective=on, and -- for
    # tas_grid_fix, which S4 applies itself -- not applied inside S4 either.
    opted_out = sorted(n for n in due if n in ENHANCEMENTS_DECLARED_OFF)
    if opted_out:
        log(f"PROTECTIVE {', '.join(opted_out)} off: the config sets "
            f"{'it' if len(opted_out) == 1 else 'them'} false, which wins")
        due = frozenset(n for n in due if n not in opted_out)
    unapplied = sorted(n for n in due
                       if n not in pipeline._APPLIERS and n not in DRIVER_PROTECTIVE)
    if unapplied:
        raise RuntimeError(f"protective correction(s) {', '.join(unapplied)} are due on "
                           f"{PROBE} (probetype {plan.probetype}) but neither the "
                           "enhancement chain nor this driver applies them")
    return tuple(sorted(due))


DRIVER_PROTECTIVE: frozenset[str] = frozenset({"tas_grid_fix", BIN_TABLE_FIX})
"""Protective names this driver applies itself inside S4 rather than through the post-stage
enhancement chain. ``tas_grid_fix`` (a repeated TAS second files none of its particles):
with a ``--tas-source`` chain S4 sizes on the regular one-second grid (:func:`default_tas_grid`),
which removes every repeated second; without one S4 hands ``sizeDist`` the probe's own
``<stem>.tas.csv`` collapsed to its first row per second
(``arrayprobe_enhancements.tas_grid_fix.collapse_tas_grid``), stamped ``tas_grid=collapse``."""


def pipeline_protective(names) -> tuple[str, ...]:
    """``names`` without the ones this driver applies itself: what the enhancement chain gets."""
    return tuple(n for n in names if n not in DRIVER_PROTECTIVE)


def drop_opted_out_tas_grid_fix(tas_grid: str, tas_source) -> None:
    """``--tas-grid probe`` with a ``--tas-source`` chain opts out of ``tas_grid_fix``: the chain
    keeps the probe's own grid, so neither the regular grid nor the collapse (which needs
    ``TAS_CHAIN is None``) runs, and the ``.call`` stamp must not say it was applied (cloud pass 8
    review F2, 2026-09-27). Removes it from :data:`PROTECTIVE_ON`, logged."""
    if tas_grid == "probe" and tas_source is not None and "tas_grid_fix" in PROTECTIVE_ON:
        globals()["PROTECTIVE_ON"] = tuple(n for n in PROTECTIVE_ON if n != "tas_grid_fix")
        log("PROTECTIVE tas_grid_fix off: --tas-grid probe with a --tas-source chain keeps the "
            "probe's grid, so neither the regular grid nor the collapse runs")


def tas_grid_fix_on() -> bool:
    """Whether this run's S4 applies ``tas_grid_fix`` (resolved into :data:`PROTECTIVE_ON`)."""
    return "tas_grid_fix" in PROTECTIVE_ON


def _collapse_probe_grid(timehhmmss, tas, tag: str):
    """``tas_grid_fix`` on the probe's own TAS rows, for a run with no TAS source chain."""
    try:
        from arrayprobe_enhancements.tas_grid_fix import collapse_tas_grid
    except ImportError as exc:
        raise SystemExit(f"{_ENHANCEMENTS_MISSING} ({exc})") from exc
    tas, timehhmmss, report = collapse_tas_grid(tas, timehhmmss)
    log(f"{tag} tas_grid_fix: {report['removed']} repeated second(s) collapsed "
        f"({report['rows_in']} -> {report['rows_out']} rows; --protective off to skip)")
    return timehhmmss, tas


def call_path(output: Path) -> Path:
    """Where an output's provenance stamp lives: beside it, never inside it.

    An attribute of our own would break the byte-fidelity with MATLAB that the
    package exists to demonstrate -- see :func:`iat_call_label`.
    """
    return output.with_name(output.name + ".call")


def read_stamp(output: Path) -> str | None:
    """The recorded stamp for ``output``, or ``None`` if it has none."""
    sidecar = call_path(output)
    if not sidecar.exists():
        return None
    return sidecar.read_text().strip()


def write_stamp(output: Path, label: str) -> None:
    """Record ``label`` beside ``output``, partial-then-rename.

    Not a bare ``write_text``: a kill mid-write would leave a truncated stamp,
    which compares unequal and silently costs a redo -- or, worse, compares
    equal to a prefix of some future label.
    """
    sidecar = call_path(output)
    partial = sidecar.with_name(sidecar.name + ".partial")
    partial.write_text(label + "\n")
    os.replace(partial, sidecar)


_LEGACY_DEFAULT_TAG = re.compile(r"(\S) \(stock\)")


def _normalize_default_tag(stamp: str) -> str:
    """Read the pre-2026-10-16 threshold source tag ``(stock)`` as ``(default)``."""
    return _LEGACY_DEFAULT_TAG.sub(r"\1 (default)", stamp)


def _stamps_equivalent(got: str, want: str) -> bool:
    """Whether a recorded stamp ``got`` matches ``want``, treating an OLDER stamp that predates a
    field this module later started naming as equivalent to one that names it explicitly with the
    value that field always had before it was named.

    Three additive generations handled here, composably (a stamp may be missing any, all, or
    none):

    * ``engine=`` (added 2026-09-15, R4s) -- every v3.1.4 stamp written before that day has
      no ``engine=`` key at all.
    * ``tree=``/``area_ratio_z=``/``default_int_arr_thresh=`` (added 2026-09-17) -- every
      v3.1.4 ``sd`` stamp written before today has none of the three: S4 always ran
      ``tree="production"`` with no regime or override, so that is the value an absent fragment is
      read as (:func:`_legacy_thresholds_stamp`), not a mismatch.

    * ``port_validation=on`` (added 2026-09-30, R4) -- every v3.1.4 run now carries it;
      stripped from both sides like the protective fragment, because it changes no byte and
      ``scripts/reprocess.py`` computes its want labels without ``main()`` (token absent) while
      the file on disk has it.

    Without this, every pre-existing v3.1.4 product would compare unequal to the newly-worded
    ``want`` and the runner would treat perfectly current output as stale on wording alone --
    exactly the "mixed configuration" failure class this sidecar exists to prevent, self-inflicted.
    A v3.5 stamp carries neither addition (``engine=3.5`` since it was introduced; it never gets
    the threshold fragment at all, :func:`sd_call_label`), so it never needs either fallback.
    """
    if got == want:
        return True
    # Raw-input inventory keys describe the input, not the configuration.
    got, want = _strip_inventory(got), _strip_inventory(want)
    if got == want:
        return True
    # 2026-10-16 (author): the threshold source tag ``stock`` was renamed ``default``; a stamp
    # written under the old spelling is the same run, not a stale one.
    got, want = _normalize_default_tag(got), _normalize_default_tag(want)
    if got == want:
        return True
    # The protective fragment names post-stage corrections written to separate files; it
    # changes no port byte, so it never makes a product stale.
    got, want = _strip_protective(got), _strip_protective(want)
    if got == want:
        return True
    # Plausibility gate: the plausibility token measures the written sd; the override marker
    # is kept.
    got, want = _strip_plausibility(got), _strip_plausibility(want)
    if got == want:
        return True
    # Engine-3.5 defect correction: the time/sample-volume counts report what a run found,
    # not its configuration.
    got, want = _strip_time_sv_counts(got), _strip_time_sv_counts(want)
    if got == want:
        return True
    # Engine-3.5 defect correction: the derived particle-clock offset is measured from each
    # proc file, not configured, so
    # it never makes an sd stale. Before this, S4's own post-write currency check compared the
    # written stamp (which carries the offset) with a want that does not, and failed every
    # clock-fixed run (CIP 2016-09-06, 2026-10-05 00:09).
    got, want = _strip_particle_clock_fix(got), _strip_particle_clock_fix(want)
    if got == want:
        return True
    # Engine-3.5 defect correction: a v3.5 stamp written before the time_sv_fix marker existed
    # was made without the
    # corrections, so it reads as time_sv_fix=off -- never as on.
    if TIME_SV_FIX_STAMP_KEY not in got and f" {TIME_SV_FIX_STAMP_KEY}off" in want:
        want = want.replace(f" {TIME_SV_FIX_STAMP_KEY}off", "")
        if got == want:
            return True
    # R4: the port_validation token names a gate, not a configuration; it changes no
    # byte, so it is stripped from both sides (top level and inside inputs_built_with=(...)),
    # and before the v314_prefix expansion below so a pre-2026-09-15 stamp still matches.
    got, want = _strip_port_validation(got), _strip_port_validation(want)
    if got == want:
        return True
    # Stray-pixel rule (2026-10-03): a v3.5 stamp written before the stray-pixel correction
    # carries no stray_pixel= key and was made uncorrected, so it reads as stray_pixel=off --
    # never as on.
    if STRAY_PIXEL_STAMP_KEY not in got and f" {STRAY_PIXEL_STAMP_KEY}off" in want:
        want = want.replace(f" {STRAY_PIXEL_STAMP_KEY}off", "")
        if got == want:
            return True
    # NCAR 2DC timing conversion (2026-10-07): a v3.5 2DC/2DP stamp written before it carries
    # no ncar_2dc_timing= key and was made unconverted, so it reads as ncar_2dc_timing=off --
    # never as on.
    if NCAR_2DC_TIMING_STAMP_KEY not in got and f" {NCAR_2DC_TIMING_STAMP_KEY}off" in want:
        want = want.replace(f" {NCAR_2DC_TIMING_STAMP_KEY}off", "")
        if got == want:
            return True
    candidates = {want}
    v314_prefix = "engine=3.1.4 "
    for c in tuple(candidates):
        if c.startswith(v314_prefix):
            candidates.add(c.removeprefix(v314_prefix))
    # An sd stamp from a chain run on a profile that reads no aircraft file gained its policy
    # on 2026-09-28; one written before carries none and was built under the default policy,
    # the only one a run could then leave unnamed and still have stamped nowhere.
    legacy_policy = f" {TAS_SERIES_POLICY_KEY}({_mtf.TasPolicy().token()})"
    for c in tuple(candidates):
        if legacy_policy in c:
            candidates.add(c.replace(legacy_policy, ""))
    threshold_suffix = " " + _legacy_thresholds_stamp()
    for c in tuple(candidates):
        if c.endswith(threshold_suffix):
            candidates.add(c[: -len(threshold_suffix)])
    # A v3.5 combined product's stamp gained a third line, its inputs' own stamps, on
    # 2026-09-27; before that it carried only the combine module's two lines. The absent line
    # reads as "not recorded", not as a mismatch -- ``combine_state``'s age check still catches
    # an input rebuilt after the product was written.
    legacy_combine_sep = "\n" + COMBINE_INPUTS_KEY
    for c in tuple(candidates):
        if c.startswith("engine=3.5 ") and legacy_combine_sep in c:
            candidates.add(c.rsplit(legacy_combine_sep, 1)[0])
    return got in candidates


def output_state(output: Path, want: str, source: Path | None = None) -> str:
    """``absent`` | ``current`` | ``stale`` | ``outdated`` | ``unstamped``, for one output.

    ``unstamped`` is deliberately its own state rather than folded into
    ``stale``.  They call for different answers: a stale file is *known* to have
    been built with something else and can be redone with the cost known, while
    an unstamped one is unknown -- it may be perfectly current (every output
    written before this stamp existed is in that state) and redoing it may cost
    hours for nothing.  Collapsing the two would make the runner either destroy
    good work or trust unknown work; both are failures this exists to prevent.

    ``outdated`` is its own state for the same reason, added 2026-09-19 after it
    was measured breaking the **documented quickstart**.  The stamp records the
    *configuration* a file was built with and deliberately not its inputs
    (``reprocess.py``'s own docstring says so).  So when the configuration is
    unchanged and only the RAW INPUT is new, every stamp comparison says
    ``current`` and the stage is skipped:

        S3 skip   proc.base160101000000.H.nc exists
        S4 skip   sd.base160101000000.H.nc exists

    Measured 2026-09-19 on a clean checkout: the quickstart's own two documented
    commands wrote a fresh raw file at 14:26 and then stitched a ``proc``/``sd``
    pair **from 2026-09-10, nine days old**, printed ``ALL DONE``, and produced a
    well-formed 68 MB combined product with **zero particles counted into any
    bin**.  Nothing was misconfigured; the two runs' configurations were
    identical, which is exactly why the stamp could not see it.  That is the same
    shape as the HVPS default 2D-S bins -- a user does not get an obviously broken file,
    they get a plausible one that is empty -- and it reaches a new user on the
    first thing the documentation asks them to run.

    Passing ``source`` makes the check possible: an output older than the input it
    was built from is ``outdated`` however well its stamp matches.  ``source`` stays
    optional so a caller with no single input (S4c stitches many) is unchanged
    rather than silently given a wrong answer.
    """
    if not output.exists():
        return "absent"
    got = read_stamp(output)
    if got is None:
        return "unstamped"
    if not _stamps_equivalent(got, want):
        return "stale"
    if source is not None and source.exists():
        try:
            if output.stat().st_mtime < source.stat().st_mtime:
                return "outdated"
        except OSError:
            # A stat that fails is not evidence of currency.  Fall through to
            # the stamp's answer rather than inventing a state from an error.
            pass
    return "current"


def channel_token(probe: str | None = None) -> str:
    """The segment every path this driver builds carries between stem and suffix.

    **One function, because a half-applied naming convention is worse than none**
    (CIP work, 2026-09-18).  Four sites build or read that segment -- :func:`image_path`,
    :func:`proc_path` (and :func:`sd_path` through it), :func:`stage3`'s input and
    :func:`image_call_label`'s stamp -- and before today all four hard-coded
    :data:`ORIENTATION`.

    For a SPEC probe the segment is the **channel**: ``read_binary_SPEC`` takes
    ``channels=`` and writes an ``H`` decode and a ``V`` decode, so ``H`` in the name is a
    true statement about which of two streams the file holds.  For a probe whose
    format has no channel split, ``H`` would assert something false about a file
    that was never split -- misleading provenance, which is the whole failure this
    driver's ``.call`` machinery exists to stop.  So the segment is the **probe**
    instead: ``<stem>.CIP.cdf``, which says which probe's stream came out of the
    container and claims no channel at all.  ``read_binary_SEA`` already writes
    exactly that name (it suffixes ``.CIP.cdf`` / ``.2DC.cdf`` per probe found),
    so the convention is the reader's own, not one imposed on it.

    Probetype 2 is unchanged byte for byte, which is what keeps the fifteen
    validated flights' file names and ``.call`` stamps exactly as they were.
    """
    plan = s2_reader_for(probe or PROBE)
    return ORIENTATION if plan.probetype == 2 else plan.probe


def proc_path(raw_stem: str, out_dir: Path, shadow_diode=None) -> Path:
    """Where S3's output for this raw file lives -- the ``.diodecorrected.nc``
    name when a mask is applied, which is a different file precisely so the
    fidelity-faithful default is never shadowed by it (see
    :func:`stage3_corrected`)."""
    suffix = ".diodecorrected.nc" if shadow_diode else ".nc"
    return out_dir / f"proc.{raw_stem}.{channel_token()}{suffix}"


def sd_path(raw_stem: str, out_dir: Path, shadow_diode=None) -> Path:
    """Where S4's output lives, derived from S3's so the two names cannot drift."""
    proc = proc_path(raw_stem, out_dir, shadow_diode)
    return out_dir / ("sd." + proc.name.removeprefix("proc."))


def image_path(raw_stem: str, out_dir: Path) -> Path:
    """Where S2's output for this raw file lives -- each engine's own suffix
    (:func:`image_suffix_for_probe`), and :func:`channel_token` for the segment before it."""
    return out_dir / f"{raw_stem}.{channel_token()}{image_suffix_for_probe()}"


def proc_path_for_decode(image_file: Path, out_dir: Path) -> Path:
    """``proc.<decode name less its decode suffix>.nc`` in ``out_dir``: S3's output for the decode
    ``image_file``, the inverse of :func:`image_path`'s naming.

    Strips whichever of :data:`arrayprobe_uiops.decode_naming.DECODE_SUFFIXES` the decode carries:
    a v3.5 SPEC decode already ends in ``.nc`` and a v3.1.4 or shared-reader decode in ``.cdf``,
    and both give ``proc.<stem>.<token>.nc``, the name the former in-place suffix swap gave."""
    name = image_file.name
    for suffix in _decode_naming().DECODE_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return out_dir / f"proc.{name}.nc"


def sd_is_current(out_dir: Path, raw_stem: str, iat_file: str | None,
                  profile=None, shadow_diode=None) -> bool:
    """Is there a finished sd file for this raw file, built with *this* call
    and *this* configuration?

    Separated out so the "an existing output is a finished output" assumption the
    whole runner rests on can be tested without a flight's worth of data.
    """
    target = sd_path(raw_stem, out_dir, shadow_diode)
    want = sd_call_label(iat_file, profile, shadow_diode)
    return output_state(target, want) == "current"


def _diodes_for(raw_stem: str, diode_corrected: bool):
    """The mask this run would apply to ``raw_stem``, or ``None``.

    One place, because the mask decides which *file names* a run reads and
    writes as well as what it computes -- and a preflight looking at the
    uncorrected proc while the run writes the corrected one would report on a
    file the run never touches.
    """
    return SHADOW_DIODE_OVERRIDES.get(raw_stem) if diode_corrected else None


def preflight(raws, out_dir: Path, iat_file: str | None = IAT_FILE,
              diode_corrected: bool = False,
              accept_unstamped: bool = False) -> bool:
    """Check what the run needs before committing hours to it.

    Reports rather than guesses: which files are present, what is already done,
    what an existing intermediate was *built with*, how much disk the remainder
    wants against what is free, and the estimate.  Returns False if something
    would certainly fail -- or if an existing ``proc`` file's configuration
    cannot be established, which is the one case where continuing would produce
    a plausible-looking wrong answer rather than an error (see
    :func:`config_label`).
    """
    log("stages: S2 read raw, S3 image processing, S4 size distribution, S4c combine")
    log("PREFLIGHT")
    ok = True
    total_mb = 0.0
    todo = 0
    unstamped = []
    for raw in raws:
        if not raw.is_file():
            log(f"  MISSING  {raw}")
            ok = False
            continue
        _why = preset_raw_mismatch(PROBE, raw)
        if _why and not ACCEPT_PRESET_MISMATCH:
            log(f"  MISMATCH {_why}")
            ok = False
            continue
        if _why:
            log(f"  WARNING  {_why} (accepted: --accept-preset-mismatch)")
        _date_why = preset_date_warning(ACTIVE.name, raw)
        if _date_why:
            log(f"  WARNING  {_date_why}")
        mb = raw.stat().st_size / 1e6
        shadow_diode = _diodes_for(raw.stem, diode_corrected)
        want_proc = proc_call_label(shadow_diode=shadow_diode)
        done = sd_is_current(out_dir, raw.stem, iat_file, shadow_diode=shadow_diode)
        proc_state = output_state(proc_path(raw.stem, out_dir, shadow_diode), want_proc)
        # The decode is only checked when S3 would actually read it (stage2's
        # `enforce_provenance`), so the preflight must apply the same rule --
        # a preflight that refuses what the run would accept is worse than none.
        if proc_state != "current":
            image = image_path(raw.stem, out_dir)
            image_state = output_state(image, image_call_label())
            if image_state == "unstamped" and not accept_unstamped:
                unstamped.append((raw.stem, "decode"))
                log(f"  {'UNSTAMPED':9s} {raw.name:28s} {mb:7.0f} MB  (the decode)")
                ok = False
                continue
            if image_state == "stale":
                log(f"  {'STALE':9s} {raw.name:28s} {mb:7.0f} MB  "
                    f"(decoded with {read_stamp(image)})")
                ok = False
                continue
        if proc_state == "unstamped" and not accept_unstamped:
            unstamped.append((raw.stem, "proc"))
            log(f"  {'UNSTAMPED':9s} {raw.name:28s} {mb:7.0f} MB  (the proc file)")
            ok = False
            continue
        # An sd file built with the other twelfth-argument call has to be redone,
        # but S3's output is unaffected by it -- and S3 is 96% of the cost. Say so,
        # rather than quoting an eight-hour estimate for 53 seconds of work.
        # A *stale* proc file is a different matter: its configuration is known
        # and known to be wrong, so S3 is priced in full.
        s4_only = not done and proc_state in ("current", "unstamped")
        state = "done " if done else ("S4 only" if s4_only else "to do")
        log(f"  {state:7s} {raw.name:28s} {mb:7.0f} MB")
        if proc_state == "stale":
            was = read_stamp(proc_path(raw.stem, out_dir, shadow_diode))
            log(f"          (proc will be REDONE -- it was built with {was})")
        if not done and not s4_only:
            total_mb += mb
            todo += 1
        elif s4_only:
            todo += 1
    if unstamped:
        kinds = ", ".join(sorted({kind for _, kind in unstamped}))
        log(f"  REFUSING: {len(unstamped)} existing output(s) carry no provenance "
            f"stamp ({kinds}), so which fidelity configuration produced them "
            "cannot be established")
        log("  (every output written before 2026-08-30 is in this state; the "
            "reject-threshold correction landed 2026-08-28, so some proc files "
            "are stock-threshold files and some are not)")
        log("  (delete them to have them rebuilt, or pass --accept-unstamped if "
            "you have established their configuration by other means)")

    # TIMING, and it has the same flaw the disk estimate had. S2 scales with the
    # raw file (~40 rec/s), but S3 scales with the number of H IMAGE RECORDS and
    # with how much is in them -- 114 ms/record on base160906064403 (7.5 particles
    # per record) against 510 ms/record measured on base160906075333 (147 per
    # record). Extrapolating S3 from raw megabytes understated it by ~4.5x per
    # record and ~35x in record count, i.e. two orders of magnitude combined.
    #
    # So: when the .H.cdf already exists, price S3 off its real record count at
    # the slower measured rate. Otherwise say the estimate is S2-only and label
    # the S3 figure as unknown rather than inventing one.
    s2_hours = total_mb * 32 / 60 / 297
    s3_hours = 0.0
    s3_known = True
    for raw in raws:
        if not raw.is_file():
            continue
        img = image_path(raw.stem, out_dir)
        shadow_diode = _diodes_for(raw.stem, diode_corrected)
        proc = proc_path(raw.stem, out_dir, shadow_diode)
        # A proc file whose stamp says another configuration is not a saving:
        # S3 runs again for it, so it is priced like a file with no proc at all.
        if output_state(proc, proc_call_label(shadow_diode=shadow_diode)) in (
                "current", "unstamped"):
            continue
        if img.exists():
            s3_hours += image_record_count(img) * 0.51 / 3600
        else:
            s3_known = False
    hours = s2_hours + s3_hours

    # DISK IS ESTIMATED AT THE WORST CASE, NOT THE TYPICAL ONE, and that is a
    # correction. The old figure was 1.22x the raw size, extrapolated from
    # base160906064403 -- where the H channel carries only 8.8% of records
    # (6,643 of 75,705). In base160906075333 and base160906095907 it carries
    # ~90%, and the .H.cdf came out at 12.4 GB and 14.1 GB from 1.07 GB of raw:
    # 11.6x, not 1.22x. The run went from 57 GB free to 21 GB and would have
    # exhausted the disk on the two files it never reached.
    #
    # A record costs the same whichever channel triggers it (MATLAB declares
    # `data` as int32 at 1700x8 = 54.4 kB), so the ceiling is "every record is an
    # H record" and nothing can exceed it. Estimating the ceiling turns a
    # silent overrun into a refusal.
    need_gb = total_mb * 12.0 / 1000
    free_gb = shutil.disk_usage(out_dir).free / 1e9
    log(f"  {todo} file(s) to process, {total_mb:.0f} MB")
    log(f"  estimate {'~' if s3_known else '>='}{hours:.1f} h"
        f"   <={need_gb:.1f} GB needed (worst case)   {free_gb:.1f} GB free")
    if not s3_known:
        log("  note: at least one file is not decoded yet, so its S3 cost is "
            "unknown -- the hours above are a LOWER BOUND")
    if need_gb > free_gb * 0.8:
        log("  REFUSING: not enough free disk with margin for the worst case")
        # S9r: this hint used to say "*.V.cdf are the soot-fouled channel" as
        # though that were a general fact.  It is a property of ORACLES 2016 --
        # that campaign's vertical mirror was fouled, so its V output records
        # the fault rather than the cloud.  On any other campaign the V channel
        # is real data, and telling someone to delete it would be advice to
        # destroy their own measurements.  The generally-true half is kept.
        log("  (reclaimable: any decoded .H/.V file (.nc from engine 3.5, .cdf from 3.1.4) "
            "whose proc file is already written -- those regenerate from the raw file)")
        log("  (one field campaign only: its .V.cdf is a soot-fouled channel and is "
            "not usable science -- see readers/spec.py's `channels` note)")
        ok = False
    leftovers = list((out_dir / "_inflight").glob("*")) if (out_dir / "_inflight").is_dir() else []
    if leftovers:
        log(f"  note: {len(leftovers)} file(s) in _inflight/ from a previous "
            "killed run; they will be cleared per file, not reused")
    # The input preflight: open every raw file, the output directory, the
    # --tas-file and the IAT file the way the stages will, so an empty or unreadable raw, an
    # unwritable --out, or a TAS file without
    # UIOOPS's variable names is refused now rather than after the S2 decode (a KeyError
    # 754 s into a run, 2026-09-20). An IAT file that does not exist passes, as it does in
    # sizeDist.m:65: the ORACLES call names a missing file on purpose.
    # Only a file that IS netCDF/HDF5 is opened here: the driver also reads text TAS files
    # (the demo flight's aircraft.cdf is one), and a preflight that refuses what the run
    # accepts is worse than none. Those stay with the reader that consumes them.
    tas_nc = TAS_FILE if TAS_FILE and _is_netcdf(TAS_FILE) else None
    pf = _preflight_inputs_module()
    problems = pf.check_inputs(raws=[r for r in raws if r.is_file()], tas_file=tas_nc,
                               iat_file=iat_file, out_dir=out_dir)
    if problems:
        n_checked = len(raws) + 1 + bool(tas_nc) + bool(iat_file)
        for line in pf.report(problems, n_checked).splitlines():
            log(f"  {line}")
        ok = False
    log("  OK" if ok else "  NOT OK")
    return ok


def _is_netcdf(path) -> bool:
    """True when ``path`` starts with a netCDF-3 (``CDF``) or HDF5/netCDF-4 signature."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(8)
    except OSError:
        return True  # unreadable: let check_inputs say so
    return head[:3] == b"CDF" or head[:4] == b"\x89HDF"


def _preflight_inputs_module():
    """``arrayprobe.driver.preflight_inputs``, imported on first use."""
    from arrayprobe.driver import preflight_inputs
    return preflight_inputs


def stage2(raw: Path, out_dir: Path, accept_unstamped: bool = False,
           enforce_provenance: bool = True, s2_jobs: int = 1,
           worker_stall_min: float = 30.0) -> Path:
    """Raw ``.2DS`` -> the stage-2 decode plus the three sidecars.

    The decode is ``<base>.H.nc`` from engine 3.5 and ``<base>.H.cdf`` from 3.1.4
    (:func:`image_path`).

    Writes into ``_inflight/`` and moves the results into place only on success,
    so a run killed mid-decode leaves nothing that ``skip-if-exists`` would
    mistake for a finished file.  See :func:`_publish`.

    ``enforce_provenance=False`` says this decode will not be *read* by this run
    -- its ``proc`` file is already current, so S3 will not open it.  The
    provenance of a file nothing consumes cannot affect an output, and refusing
    on it would make the twelve decodes already on disk un-resumable for no
    gain.  The check is where the consequence is, not everywhere it could be
    written.
    """
    # The probe gate, on the path a decode actually takes (2026-09-17). It was
    # only ever inside load_presets, so it guarded a --presets file and nothing
    # else: a built-in or --config preset naming a CIP reached read_binary_SPEC
    # and would have written a plausible, wrong .H.cdf. Refusing here costs one
    # dict lookup per flight and makes the wall the same on every path.
    plan = s2_reader_for(PROBE)
    if not plan.supported:
        raise UnsupportedProbe(
            f"preset {ACTIVE.name!r} names probe {PROBE!r} (probetype "
            f"{plan.probetype}); {plan.blocker}")
    # The format gate sits HERE, beside the probe gate, for the same reason the
    # probe gate does: both must fire before this function touches the raw file
    # at all. Resolving the reader inside the decode branch instead put it after
    # `raw.stat()`, so an unidentifiable container raised FileNotFoundError --
    # a different error, about a different thing, for a file the driver was
    # never going to be able to decode. Caught by the test that pins the
    # ordering rather than only the refusal (CIP pipeline work, 2026-09-18).
    dotted = s2_reader_for_raw(PROBE, raw) if plan.formats else plan.reader
    if plan.probetype != 2 and s2_jobs > 1 and dotted != _DMT_READER:
        # Refused, not ignored: read_binary_SEA and read_binary_PMS have no
        # parallel form -- only the SPEC readers and read_binary_DMT (.cip) do --
        # and a flag that silently means nothing is how a speed claim becomes untrue.
        raise UnsupportedProbe(
            f"--s2-jobs {s2_jobs}: probe {PROBE!r} (probetype {plan.probetype}) decodes "
            f"through {dotted}, which has no parallel form. Re-run with --s2-jobs 1 "
            f"rather than have the flag quietly mean nothing")
    target = image_path(raw.stem, out_dir)
    want = image_call_label()
    if target.exists() and not enforce_provenance:
        log(f"S2 skip   {target.name} exists (not read this run; provenance "
            f"{output_state(target, want)})")
        return target
    if _check_proc_state(target, want, "S2", accept_unstamped, source=raw):
        return target
    if target.exists():
        # A decode built under another profile is NOT redone here: re-decoding is
        # hours, and unlike a proc file the runner cannot tell whether the
        # difference matters to what the operator wants. Say so and stop.
        raise UnverifiableProvenance(
            f"{target.name} was decoded with {read_stamp(target)}, but this run "
            f"wants {want}; delete it to have it re-decoded")
    staging = out_dir / "_inflight"
    staging.mkdir(exist_ok=True)
    _clear(staging, raw.stem)
    log(f"S2 start  {raw.name} ({raw.stat().st_size / 1e6:.0f} MB)")
    t0 = time.time()
    decode_record = "mode=serial jobs=1"
    if plan.probetype != 2:
        # The single-channel branch (CIP pipeline, 2026-09-18). It writes ONE image
        # file, `<stem>.<PROBE>.cdf`, which is what channel_token() named above;
        # there is no second channel, so the log line says one count rather
        # than "H / V". `dotted` and the --s2-jobs refusal were both resolved at
        # the top of this function, before the raw file was touched.
        module_name, _, attr = dotted.rpartition(".")
        reader = getattr(importlib.import_module(module_name), attr)
        if dotted.endswith("read_binary_SEA"):
            # SEA suffixes its own `.<PROBE>.cdf` per probe found in the container,
            # so the base path is passed WITHOUT the suffix and the reader writes
            # exactly the name channel_token() built. It also writes a sibling
            # `.2DC.cdf` -- a second probe's stream, not a second channel -- which
            # _publish moves alongside and nothing downstream reads.
            n_cip, n_weird, n_2dc = reader(str(raw), str(staging / raw.stem))
            n = n_cip
            decode_record = (f"mode=serial jobs=1 reader={dotted} "
                             f"n_weird={n_weird} n_2dc={n_2dc}")
        elif dotted.endswith("read_binary_PMS"):
            # One decode writes all three probe-identity outputs (pms.py:151-159); this run
            # asked for PROBE, so rename that ONE output to the name channel_token() built and
            # publish the other two untouched, as unstamped siblings -- same shape as SEA's
            # sibling above, except PMS's own suffixes are lowercase and do not already match
            # the uppercase probe-name convention, so one rename is needed where SEA needed none.
            n_2dc, n_f2dc_c6, n_f2dc_c4, n_2dp = reader(str(raw), str(staging / raw.stem))
            native = staging / f"{raw.stem}.{_PMS_NATIVE_SUFFIX[PROBE]}.cdf"
            os.replace(native, staging / target.name)
            n = {"2DC": n_2dc, "2DP": n_2dp}.get(PROBE, n_f2dc_c6 + n_f2dc_c4)
            decode_record = (f"mode=serial jobs=1 reader={dotted} n_2dc={n_2dc} "
                             f"n_f2dc_c6={n_f2dc_c6} n_f2dc_c4={n_f2dc_c4} n_2dp={n_2dp}")
        elif dotted == _DMT_READER and s2_jobs > 1:
            n, decode_record = _decode_dmt_parallel(
                raw, staging / target.name, s2_jobs, staging, dotted)
        else:
            n = reader(str(raw), str(staging / target.name))
            decode_record = f"mode=serial jobs=1 reader={dotted}"
        _publish(staging, out_dir, raw.stem)
        write_stamp(target, want + _inventory_fragment(raw))
        (out_dir / f"{target.name}.decode").write_text(decode_record + "\n", encoding="utf-8")
        log(f"S2 done   {target.name}  {n} {PROBE} records  "
            f"({time.time() - t0:.0f} s, {decode_record})")
        return target
    if s2_jobs > 1:
        # Completion is reported per part (parts finish out of order); each part's
        # own liveness is the line it prints every 20 000 windows (report_every
        # below, the serial branch's interval) into this process's stdout -- i.e.
        # a --jobs worker's log, which _await_workers watches. Without it a worker
        # is silent for a whole part: 8.9 min measured on ~1 GB files, ~2 h derived
        # for the 13.3 GB file, against a 30-min default budget (pair J, 2026-09-13).
        log(f"  S2 parallel, {s2_jobs} workers")
        import warnings as _warnings
        v35_spec = _v35().module("readers.spec") if ENGINE == "3.5" else None
        # The serial branch's flight series (--tas-ratio on), resolved once and handed to the
        # parallel decode AND its serial fallback: without it both wrote no tasRatio under a
        # stamp saying tas_ratio=on. The parallel reader primes every part from the same
        # series (tests/test_v35_spec_parallel.py, flight-series cases, byte-identical).
        flt_time, flt_tas = _tas_ratio_series(raw) if v35_spec is not None else (None, None)
        with _warnings.catch_warnings(record=True) as caught:
            _warnings.simplefilter("always", SpawnRetryWarning)
            if v35_spec is not None:
                _warnings.simplefilter("always", v35_spec.SeamRerunWarning)
            try:
                def parts_progress(done, total, _counts):
                    log(f"  ...part {done}/{total} decoded")

                seam_note = ""
                # The parts' merge (spec._merge_parts) prints nothing and ran ~30 min on
                # 160925, past --worker-stall-min, so the parent killed a live --jobs
                # worker (2026-10-08). Logging only; the decode's bytes are untouched.
                s2_beat = _log_heartbeat("S2 parallel decode",
                                         _heartbeat_interval(worker_stall_min * 60))
                if v35_spec is not None:
                    # The v3.5 decoder carries the running airspeed across windows; its
                    # parallel form primes each part and checks every seam by bit pattern
                    # (tests/test_v35_spec_parallel.py). `software`, `creation_time` and the
                    # flight series are the serial branch's below.
                    stats: dict = {}
                    with s2_beat:
                        n_h, n_v = v35_spec.read_binary_spec_v35_parallel(
                            raw, staging / raw.stem, jobs=s2_jobs,
                            software=V35_CALL.software,
                            flt_time=flt_time, flt_tas=flt_tas,
                            creation_time=f"{datetime.now():%Y/%m/%d %H:%M:%S}",
                            channels=ORIENTATION, stamp_profile=PROFILE.name,
                            workdir=str(staging), progress=parts_progress,
                            report_every=20000, stats=stats,
                        )
                    seam_note = f" seam_reruns={stats.get('reruns', 0)}"
                else:
                    with s2_beat:
                        n_h, n_v = spec.read_binary_SPEC_parallel(
                            raw, staging / raw.stem, jobs=s2_jobs, profile=PROFILE,
                            channels=ORIENTATION, workdir=str(staging),
                            progress=parts_progress, report_every=20000,
                        )
                retries = sum(1 for w in caught if issubclass(w.category, SpawnRetryWarning))
                for w in caught:
                    if issubclass(w.category, SpawnRetryWarning):
                        log(f"  RETRY   {w.message}")
                    elif v35_spec is not None and issubclass(w.category,
                                                             v35_spec.SeamRerunWarning):
                        log(f"  SEAM    {w.message}")
                decode_record = f"mode=parallel jobs={s2_jobs} retries={retries}{seam_note}"
            except concurrent.futures.process.BrokenProcessPool:
                # spec.py's own spawn_retries are already exhausted by the time
                # this reaches here -- this is the fallback of last resort, not
                # a second retry loop. `--s2-jobs 1` is asserted byte-identical
                # (test_spec_parallel.py), so the worst case becomes slow
                # instead of lost -- the single highest-value piece of the ARM
                # driver-defect fix (2026-09-11, coordinated with the session
                # that found the same shape independently in its own regression).
                log(f"  FALLBACK parallel decode's worker pool died after "
                    f"exhausting its own retries; falling back to serial "
                    f"(s2_jobs=1) for {raw.name} -- slower, not lost")
                if v35_spec is not None:
                    n_h, n_v = v35_spec.read_binary_spec_v35(
                        raw, staging / raw.stem, software=V35_CALL.software,
                        flt_time=flt_time, flt_tas=flt_tas,
                        creation_time=f"{datetime.now():%Y/%m/%d %H:%M:%S}",
                        channels=ORIENTATION, stamp_profile=PROFILE.name,
                        progress=lambda i, h, v: (
                            log(f"  ...{i} records, {h} H / {v} V")
                            if i and i % 20000 == 0 else None),
                    )
                else:
                    n_h, n_v = spec.read_binary_SPEC(
                        raw, staging / raw.stem, profile=PROFILE, channels=ORIENTATION,
                        progress=lambda i, h, v: (
                            log(f"  ...{i} records, {h} H / {v} V")
                            if i and i % 20000 == 0 else None),
                    )
                decode_record = f"mode=serial_fallback(from_parallel) jobs={s2_jobs}"
    elif ENGINE == "3.5":
        # v3.5's own decoder (arrayprobe_uiops.spec, through the selector). `software` and
        # `creation_time` are required there, no defaults (spec.py:547-561). The flight series
        # that writes tasRatio is passed only under --tas-ratio on (the aircraft file, never the
        # probe-time-regridded series); off is the iTAS==0 path.
        flt_time, flt_tas = _tas_ratio_series(raw)
        n_h, n_v = _v35().module("readers.spec").read_binary_spec_v35(
            raw, staging / raw.stem, software=V35_CALL.software,
            flt_time=flt_time, flt_tas=flt_tas,
            creation_time=f"{datetime.now():%Y/%m/%d %H:%M:%S}", channels=ORIENTATION,
            stamp_profile=PROFILE.name,
            progress=lambda i, h, v: (
                log(f"  ...{i} records, {h} H / {v} V") if i and i % 20000 == 0 else None),
        )
        decode_record = "mode=serial jobs=1"
    else:
        n_h, n_v = spec.read_binary_SPEC(
            raw, staging / raw.stem, profile=PROFILE, channels=ORIENTATION,
            progress=lambda i, h, v: (
                log(f"  ...{i} records, {h} H / {v} V") if i and i % 20000 == 0 else None),
        )
    _publish(staging, out_dir, raw.stem)
    write_stamp(target, want + _inventory_fragment(raw))
    # A SEPARATE sidecar, deliberately never merged into `.call`: `.call` is
    # compared for exact equality to decide staleness (output_state() above),
    # and decode mode is a performance fact, not a fidelity one -- putting it
    # there would make a byte-identical parallel and serial-fallback decode of
    # the SAME file compare unequal and trigger a pointless hours-long redo on
    # the next resume. This sidecar is read deliberately (by a benchmark or a
    # later stage), never compared for staleness.
    (out_dir / f"{target.name}.decode").write_text(decode_record + "\n", encoding="utf-8")
    log(f"S2 done   {target.name}  {n_h} H / {n_v} V records  "
        f"({time.time() - t0:.0f} s, {decode_record})")
    return target


def _progress_every(step: int):
    """A throttled S3 progress callback, one line per ``step`` records."""
    def report(i: int, last: int) -> None:
        if i % step == 0:
            log(f"  ...S3 {i}/{last} records ({100.0 * i / last:.1f}%)")
    return report


def _chunk_plan(n_records: int, chunks: int) -> tuple[int, int]:
    """``(n_every, chunks)`` for a ``--chunks`` run: no chunk starts past the file.

    ``n_every`` is ``ceil(n_records / chunks)``, as it always was, so every chunk's
    records are unchanged; the count is then the number of chunks that ``n_every``
    needs.  Taking ``min(chunks, n_records)`` instead left trailing chunks empty
    (5 records, 4 chunks: chunk 4 started at record 7), and engine 3.5's seam scan
    raised ``IndexError`` on them (measured 2026-10-18)."""
    n_every = -(-n_records // chunks) if chunks > 0 else n_records  # ceil division
    if n_every <= 0:
        return n_every, 1
    return n_every, -(-n_records // n_every)


def image_record_count(image_file: Path) -> int:
    """How many image records the decode ``image_file`` holds -- its ``time`` dimension."""
    with netCDF4.Dataset(str(image_file)) as ds:
        return len(ds.dimensions["time"])


def _imgproc_sm_chunk(image_file: Path, out_path: Path, n: int, n_every: int,
                      progress=None, shadow_diode=None, prime=None) -> int:
    """One ordinary ``imgproc_sm`` call over records ``(n-1)*n_every+1 ..
    min(n*n_every, img_count)`` -- the same call a single-chunk run makes with
    ``n=1``, just narrowed to one slice of the file.

    ``shadow_diode`` defaults to ``None`` for the reason given in
    :func:`stage3`'s docstring: that is what reproduces the archived
    product's fidelity-faithful behaviour. A caller that has confirmed a
    real, applicable mask (see ``SHADOW_DIODE_OVERRIDES`` below) may pass
    the diode list explicitly -- see :func:`stage3_corrected`, which always
    writes to a DIFFERENT output file than the faithful default and never
    overwrites it, so both variants exist side by side.

    ``tas_file`` is the module-level :data:`TAS_FILE`, read live for the same
    reason ``PROFILE`` is.

    Returns the particle count ``imgproc_sm`` wrote (P10, 2026-09-13): the
    ``--_run-chunk`` worker uses it to write its own completion record, which
    ``stage3``'s chunk path now refuses to merge without.

    Under engine 3.5 this dispatches to ``arrayprobe_uiops.imgproc.imgproc_sm_v35`` through the
    selector instead, with ``V35_CALL``'s switches and the aircraft series read live from
    :data:`TAS_FILE`. ``shadow_diode`` is forwarded to ``imgproc_sm_v35``'s own ``shadow_diode=``,
    which re-illuminates the masked diodes right after the image is decoded into characters and
    before the iQC clean-up (``arrayprobe_uiops.diode_mask.reilluminate``); ``None`` and an empty
    mask write the same bytes as a run without it (``tests/test_v35_shadow_diode.py``). Until
    that parameter existed ``main()`` refused ``--diode-corrected`` under this engine and this
    branch asserted the mask ``None``. ``JIT`` is no longer asserted falsy here and is
    forwarded instead: :mod:`arrayprobe_uiops.jit_kernels` landed 2026-09-18, so v3.5 has its own
    kernels (measured 1.79x on a real CIP production pass; byte-identity proven on the real file
    by ``tests/test_v35_imgproc_jit_identity.py``, which also checks the window exercises v3.5's
    rewritten ``[EXPERIMENTAL]`` hollow override). Until that day the combination was refused in
    ``main()`` and asserted against here, because ``imgproc_sm_v35`` had no ``jit`` parameter to
    give it to -- an accepted-and-ignored flag being the "accepted, does nothing, says nothing"
    failure. The ``--_run-chunk`` worker branch still parses ``JIT``/``ENGINE`` from
    trailing argv tokens with no validation of its own, so the forwarding has to be correct on
    both paths -- see ``main()``'s ``--_run-chunk`` branch and :func:`stage3`'s
    ``cmd_base``/``jit_tail``.
    """
    if ENGINE == "3.5":
        v35_imgproc = _v35().module("imgproc")
        # prime= is the probetype-2 chunk seam state. imgproc_sm_v35 refuses it
        # for every other timing and for n=1, so it is forwarded unvalidated here
        # deliberately: one refusal, in the engine, rather than two that can drift
        # apart -- which is the docstring-vs-code failure that put a false claim on
        # two shared pages on 2026-09-18.
        # imgProc_sm.m assigns tasTime/tas (varargin{1,2}) only in its probetype-2 case
        # arms (:167-170, :180-185, :196-199, :211-214), and imgproc_sm_v35 REFUSES them
        # for any other probetype rather than accepting an input the MATLAB never reads.
        # So a CIP/PIP, 2DC/2DP or Fast2DC run passes None. Unconditional until
        # 2026-09-17 (CIP end-to-end): _aircraft_series() reads TAS_FILE, which main() has already
        # refused to let those probes set, so this branch could only ever have run a
        # probetype 2 -- it raised on TAS_FILE=None before imgproc_sm_v35 could refuse
        # the arguments. That made `--engine 3.5` unable to run a CIP at all, which is
        # what the chunked CIP pass needs.
        if v35_imgproc.PROBES_V35[PROBE].probetype == 2:
            tas_time, tas = _aircraft_series()
        else:
            tas_time, tas = None, None
        return v35_imgproc.imgproc_sm_v35(
            str(image_file), str(out_path), PROBE, n, n_every, PROJECT,
            stamp_profile=PROFILE.name,
            iRectEllipse=V35_CALL.i_rect_ellipse,
            iCalcAllDiodeStats=V35_CALL.i_calc_all_diode_stats,
            iQC=V35_CALL.i_qc, iNewHabit=V35_CALL.i_new_habit,
            prime=prime,
            reject_config=_resolve_reject(), tas_time=tas_time, tas=tas,
            tas_ratio=_s3_tas_ratio(image_file),
            software=V35_CALL.software, progress=progress, jit=JIT,
            tas_qc=_s3_tas_qc_v35(image_file, tas_time, tas), shadow_diode=shadow_diode,
            ncar_2dc_timing_fix=NCAR_2DC_TIMING and _probetype0(),
            stray_pixel_fix=STRAY_PIXEL)
    return imgproc.imgproc_sm(str(image_file), str(out_path), PROBE, n, n_every,
                              PROJECT, profile=_profile_with_resolved_reject(),
                              tas_file=TAS_FILE,
                              shadow_diode=shadow_diode, progress=progress, jit=JIT,
                              write_provenance=WRITE_PROVENANCE)


#: Confirmed, real, whole-file-persistent stuck diodes -- NOT applied by
#: default (see stage3's docstring for why ``shadow_diode=None`` is the
#: fidelity-faithful choice). User-directed 2026-08-22: "I still think this
#: is an issue that needs to be corrected nevertheless. Apply this
#: correction regardless and re-process data when possible." Established by
#: computing bin_stats occupancy directly from each flight's own proc
#: output (not just trusting the recovered .mat file): base160910124240's
#: diode 95 sits at 42.5% of the file-mean lit-rate, base160910071623's
#: diode 77 at 66.5% -- both comfortably under find_shadow_diodes.m's own
#: 80% threshold, so both are real, not measurement noise.
#: The correction does not depend on whether the
#: real 2017 production run applied it; it is
#: scientifically justified on its own: both diodes are
#: confirmed stuck, and re-illuminating them is not a
#: fidelity change to the default path, just a new
#: opt-in one.
SHADOW_DIODE_OVERRIDES: dict[str, list[int]] = {
    "base160910124240": [95],
    "base160910071623": [77],
}


def _check_proc_state(target: Path, want: str, label: str,
                      accept_unstamped: bool, source: Path | None = None) -> bool:
    """Decide what an existing S3 output means.  Returns True to skip it.

    Four answers, one per state, and the reason each is what it is:

    * ``current`` -- skip, which is the resume story the runner is built on;
    * ``outdated`` -- redo, because the input is NEWER than this output, whatever
      its stamp says.  ``source`` is what makes that visible; see
      :func:`output_state` for the quickstart it was measured breaking;
    * ``stale`` -- redo, because the configuration it was built with is
      recorded, differs, and the cost of being wrong is a mixed-configuration
      flight product;
    * ``unstamped`` -- **refuse**, unless the operator has said otherwise.  It
      may be current and it may not, and this driver cannot tell.  Redoing it
      unasked would spend hours and overwrite what may be evidence; using it
      unasked is the 2026-08-30 trap.
    """
    state = output_state(target, want, source)
    if state == "current":
        log(f"{label} skip   {target.name} exists")
        return True
    if state == "outdated":
        log(f"{label} redo   {target.name} is older than its input "
            f"{source.name if source else '?'}, so it cannot be a product of it "
            "(the .call stamp records configuration, not inputs, and the "
            "configuration here is unchanged)")
        return False
    if state == "unstamped":
        if not accept_unstamped:
            raise UnverifiableProvenance(
                f"{target.name} exists with no .call sidecar, so the fidelity "
                "configuration that produced it is unknown; delete it to have it "
                "rebuilt, or pass --accept-unstamped")
        log(f"{label} skip   {target.name} exists, provenance UNSTAMPED "
            "(accepted on the operator's say-so, not verified here)")
        return True
    if state == "stale":
        log(f"{label} redo   {target.name} was built with {read_stamp(target)}, "
            f"want {want}")
    return False


def stage3_corrected(image_file: Path, out_dir: Path,
                     accept_unstamped: bool = False) -> Path | None:
    """Like :func:`stage3`, but applies a confirmed stuck-diode correction
    from :data:`SHADOW_DIODE_OVERRIDES` if this file has one, writing to a
    ``.diodecorrected.nc``-suffixed file so the fidelity-faithful default
    output (from :func:`stage3`) is never touched or shadowed by it.

    Returns ``None`` (does nothing) for a file with no registered override.
    """
    stem = image_file.name.split(".")[0]
    diodes = SHADOW_DIODE_OVERRIDES.get(stem)
    if diodes is None:
        return None
    # Named from proc_path_for_decode, which strips either engine's decode suffix: the former
    # in-place suffix swap did nothing to a v3.5 SPEC decode (<stem>.H.nc), so a corrected
    # engine-3.5 run would have overwritten the faithful proc.<stem>.H.nc.
    default = proc_path_for_decode(image_file, out_dir)
    target = default.with_name(default.name.removesuffix(".nc") + ".diodecorrected.nc")
    want = proc_call_label(shadow_diode=diodes)
    if _check_proc_state(target, want, "S3-corrected", accept_unstamped,
                         source=image_file):
        return target
    if not image_file.exists():
        log(f"S3-corrected SKIP   no {image_file.name} (S2 must run first)")
        return target
    n_records = image_record_count(image_file)
    partial = target.with_name(target.name + ".partial")
    partial.unlink(missing_ok=True)
    t0 = time.time()
    step = max(1, n_records // 100)
    log(f"S3-corrected start  {image_file.name} ({n_records} records, "
        f"diode(s) {diodes} re-illuminated)")
    _imgproc_sm_chunk(image_file, partial, 1, n_records, _progress_every(step),
                      shadow_diode=diodes)
    os.replace(partial, target)
    write_stamp(target, want)
    log(f"S3-corrected done   {target.name} ({time.time() - t0:.0f} s)")
    return target


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill a worker AND its children.

    2026-09-13 (P10, 0704/H): ``sys.executable`` inside a venv on Windows is
    a launcher whose child is the real interpreter (measured: PID 100536 ->
    PID 61876) -- a plain ``proc.kill()`` only kills the launcher and would
    orphan the interpreter actually holding the output file open. ``taskkill
    /T`` walks the process tree instead. MSYS ``ps -ef`` cannot see that
    grandchild at all; ``Get-CimInstance Win32_Process`` / ``tasklist`` can.

    """
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        log(f"  worker pid {proc.pid} did not die within 30 s of kill")


def _heartbeat_interval(stall_s: float) -> float:
    """Seconds between ``_await_workers``'s heartbeat lines: a quarter of the
    stall budget, capped at five minutes. A quarter, because the SAME
    ``--worker-stall-min`` value is forwarded to a --jobs worker's own nested
    --chunks wait (pair G, 2026-09-13), so the inner heartbeat must always
    land well inside the outer budget whatever the operator chose."""
    return min(300.0, stall_s / 4) if stall_s > 0 else 300.0


@contextlib.contextmanager
def _log_heartbeat(label: str, interval_s: float, watch: Path | None = None):
    """Log ``<label> alive`` every ``interval_s`` seconds while the block runs.

    For a silent step inside a ``--jobs`` worker, whose own log is its
    liveness signal to the parent's :func:`_await_workers`. Measured on
    2016-09-12 (the v3.1.4 re-validation, 2026-09-23): the chunk merge after a chunked S3 wrote no
    line, ran past the 30-min ``--worker-stall-min`` on files of 9.5-13.3 GB
    raw, and the parent killed all three workers mid-merge with every chunk
    finished (``_decoded/reval_160912``, ``queue_0923.launch.log`` 17:39-21:40).
    ``watch`` names the file being written, so each line also says it grows.
    Logging only; the block's output is untouched. ``interval_s <= 0`` disables.
    """
    import threading
    stop = threading.Event()

    def beat() -> None:
        while not stop.wait(interval_s):
            size = ""
            if watch is not None and watch.exists():
                size = f" ({watch.stat().st_size / 1e6:,.0f} MB written)"
            log(f"{label} alive{size}")

    thread = threading.Thread(target=beat, daemon=True) if interval_s > 0 else None
    if thread is not None:
        thread.start()
    try:
        yield
    finally:
        stop.set()
        if thread is not None:
            thread.join()


def _await_workers(workers, *, stall_s: float, poll_s: float = 2.0,
                   what: str, on_fail_kill_all: bool = True,
                   heartbeat_s: float | None = None,
                   held: dict | None = None) -> dict:
    """Wait for every ``(label, proc, log_f, log_path)`` in ``workers``;
    bounded and fail-closed, unlike a bare ``proc.wait()``.

    2026-09-13 (P10): a chunk worker deadlocked inside a DLL load
    (numba's lazy first-call JIT pulling in ``scipy.linalg.lapack`` on the
    chunk's first particle) and the parent's ``proc.wait()`` blocked for
    6 h 25 min with no liveness criterion at all.


    Liveness is the worker's OWN log growing: ``log()`` flushes every line
    and a chunk prints ~1% of its records per line, so a log that has not
    grown for ``stall_s`` seconds means the worker is wedged. ``stall_s <= 0``
    disables the watchdog and reproduces the old unbounded wait.

    Writes a heartbeat line to THIS process's own log at most every
    ``heartbeat_s`` seconds (default :func:`_heartbeat_interval`), and only
    when at least one pending worker's log grew since the last heartbeat --
    so the line means "my workers are progressing", not "my loop is alive".
    Pair G (2026-09-13): measured on the 14 real --jobs worker logs on disk, a
    --jobs worker's own log is silent for its ENTIRE nested chunked S3 (264,
    170, 136, 132, 99, 73, 45, 44 and 34 min on nine of them), because chunk
    progress goes to the chunk logs. This heartbeat is what makes that
    worker's log a valid liveness signal for the --jobs parent's own
    ``_await_workers``, which uses the same ``stall_s``. ``heartbeat_s <= 0``
    disables it.

    Returns ``{label: rc}`` (a killed worker's rc is ``None``). Raises
    ``RuntimeError`` naming every failed/stalled worker; on the first such
    worker, every OTHER still-running worker is tree-killed too (unless
    ``on_fail_kill_all`` is False), so nothing is left holding an output file
    a caller is about to refuse to use anyway.

    Each failure is logged (``FAILED``, and when ``held`` maps its label to
    the files it held, a ``held`` line naming them) at the poll that detects
    it, once per worker; the summary after the loop restates them.
    2026-10-08, C3 flight 160925: with ``on_fail_kill_all=False`` a worker
    the stall watchdog killed at 09:36 was reported FAILED only at 18:02,
    when its sibling finished, so the launch log showed no failure for 8.5 h
    (the C3 flight 160925 dead-worker incident).
    """
    pending = {label: (proc, log_f, log_path) for label, proc, log_f, log_path in workers}
    last_size = {label: -1 for label in pending}
    last_growth = {label: time.monotonic() for label in pending}
    rcs: dict = {}
    failed = []
    if heartbeat_s is None:
        heartbeat_s = _heartbeat_interval(stall_s)
    last_beat = time.monotonic()
    grew_since_beat: set = set()

    def _record_failure(label, why, log_path):
        failed.append((label, why, log_path))
        log(f"{what} FAILED {label}: {why} -- see {log_path.name}")
        if held and label in held:
            log(f"  {label} held: {held[label]} -- these files are not done; rerun them")

    while pending:
        for label in list(pending):
            proc, log_f, log_path = pending[label]
            rc = proc.poll()
            if rc is not None:
                log_f.close()
                rcs[label] = rc
                del pending[label]
                if rc != 0:
                    _record_failure(label, f"exit {rc}", log_path)
                continue
            size = log_path.stat().st_size if log_path.exists() else 0
            if size != last_size[label]:
                if last_size[label] >= 0:   # the first reading is a baseline, not growth
                    grew_since_beat.add(label)
                last_size[label] = size
                last_growth[label] = time.monotonic()
            elif stall_s > 0 and time.monotonic() - last_growth[label] > stall_s:
                log(f"{what} STALLED {label}: no output for {stall_s / 60:.0f} min "
                    f"(pid {proc.pid}, log {log_path.name}) -- killing the worker tree")
                _kill_tree(proc)
                log_f.close()
                rcs[label] = None
                del pending[label]
                _record_failure(label, f"stalled {stall_s / 60:.0f} min", log_path)
        if failed and on_fail_kill_all and pending:
            for label, (proc, log_f, _log_path) in list(pending.items()):
                log(f"{what} KILLING {label}: a sibling failed, no merge is possible")
                _kill_tree(proc)
                log_f.close()
                rcs[label] = None
            pending.clear()
        if (heartbeat_s > 0 and pending and grew_since_beat
                and time.monotonic() - last_beat >= heartbeat_s):
            log(f"{what} alive     {len(pending)} running, "
                f"{len(grew_since_beat)} log(s) grew: "
                + ", ".join(str(lbl) for lbl in sorted(grew_since_beat, key=str)))
            last_beat = time.monotonic()
            grew_since_beat.clear()
        if pending:
            time.sleep(poll_s)
    if failed:
        for label, why, log_path in failed:
            log(f"{what} FAILED {label}: {why} -- see {log_path.name}")
        raise RuntimeError(f"{what}: {len(failed)} worker(s) failed: "
                           + ", ".join(f"{lbl} ({why})" for lbl, why, _ in failed))
    return rcs


#: First line of a chunk's intent file. A change to what the intent records changes this,
#: so no chunk written under an older format is ever reused.
CHUNK_INTENT_FORMAT = "format=chunk-resume-1"


def _git_tree_identity(directory: Path) -> str | None:
    """``<tree sha>`` of ``directory`` at HEAD, or ``None`` when git cannot vouch for it.

    ``None`` when git is missing, ``directory`` is outside a work tree, or anything under it
    differs from HEAD (a modified or untracked file), so an unverifiable tree is never
    reusable. A tree sha rather than HEAD, so a commit that touches only documents does not
    force a recompute.
    """
    try:
        top = subprocess.run(["git", "-C", str(directory), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, check=True).stdout.strip()
        rel = Path(directory).resolve().relative_to(Path(top).resolve()).as_posix()
        tree = subprocess.run(["git", "-C", top, "rev-parse", f"HEAD:{rel}"],
                              capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", top, "status", "--porcelain", "--", rel],
                               capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError, ValueError):
        return None
    return None if dirty or not tree else tree


def _code_identity() -> str | None:
    """What code and libraries a chunk worker runs, as one token, or ``None`` if unknown.

    Covers the imported port (``arrayprobe``'s own ``src`` tree, wherever it was imported from:
    a wrong ``PYTHONPATH`` imports another checkout, which is exactly what must not match),
    this driver's ``tools`` tree, and the interpreter, numpy and netCDF4 versions.
    """
    import arrayprobe
    src = Path(arrayprobe.__file__).resolve().parent.parent
    trees = [_git_tree_identity(src), _git_tree_identity(Path(__file__).resolve().parent)]
    if any(t is None for t in trees):
        return None
    return (f"src={src.as_posix()}:{trees[0]} tools={trees[1]} python={sys.version.split()[0]} "
            f"numpy={np.__version__} netCDF4={netCDF4.__version__}")


def _chunk_intent_text(cmd: list[str], s3_label: str, image_file: Path, n_records: int,
                       n_chunks: int, code: str) -> str:
    """The ``.chunkN.call`` text: everything that decides a chunk file's bytes.

    Built from the worker's own argv, so no field can reach a worker without being recorded
    here (the argv holds the record range, profile, TAS file, engine, jit, TAS policy and
    prime). Beside it: the parent's S3 stamp, the source file's size and mtime, the TAS file's
    when one is set, and the code identity.
    """
    st = image_file.stat()
    lines = [CHUNK_INTENT_FORMAT,
             "argv=" + json.dumps(cmd),
             f"s3={s3_label}",
             f"n_records={n_records}",
             f"n_chunks={n_chunks}",
             f"source_size={st.st_size}",
             f"source_mtime_ns={st.st_mtime_ns}"]
    if TAS_FILE:
        tst = Path(TAS_FILE).stat()
        lines += [f"tas_size={tst.st_size}", f"tas_mtime_ns={tst.st_mtime_ns}"]
    lines.append(f"code={code}")
    return "\n".join(lines) + "\n"


def _chunk_reuse_refusal(chunk_path: Path, text: str) -> str | None:
    """``None`` when a chunk left by an earlier attempt may be merged as is; else why not.

    Two sides from two places: the intent file the parent wrote before spawning, and the
    completion record the worker wrote after finishing, which carries the hash of the intent
    it was started under and its own particle count, checked against the file.
    """
    call = chunk_path.with_name(chunk_path.name + ".call")
    done = chunk_path.with_name(chunk_path.name + ".done")
    for p in (chunk_path, done, call):
        if not p.exists():
            return f"no {p.name}"
    if call.read_text() != text:
        old = call.read_text().splitlines()
        new = text.splitlines()
        first = next((n.split("=", 1)[0] for o, n in zip(old, new, strict=False) if o != n),
                     "line count")
        return f"intent differs ({first})"
    lines = done.read_text().splitlines()
    sha = hashlib.sha256(text.encode()).hexdigest()
    if f"intent={sha}" not in lines[1:]:
        return "completion record is not from this intent"
    try:
        claimed = int(lines[0].strip())
        with netCDF4.Dataset(str(chunk_path)) as ds:
            actual = len(ds.dimensions["time"])
    except (ValueError, IndexError, OSError, KeyError) as exc:
        return f"unreadable ({exc})"
    if claimed != actual:
        return f"count {claimed} != file {actual}"
    return None


def stage3(image_file: Path, out_dir: Path, chunks: int = 1,
           accept_unstamped: bool = False, worker_stall_min: float = 30.0,
           resume_chunks: bool = False) -> Path:
    """``image_file``, the stage-2 decode, -> ``proc.<base>.H.nc``, the per-particle file.

    ``imgProc_sm``'s ``n`` and ``nEvery`` select a CHUNK, not a stride: the loop
    runs records ``(n-1)*nEvery + 1`` through ``min(n*nEvery, img_count)``.  So
    processing a whole file in one pass is ``n = 1`` with ``nEvery`` at least the
    record count -- which is also what the ORACLES production run did, since a
    chunked run would have left ``bin_stats`` partial.

    THIS WAS A BUG UNTIL 2026-08-20, and a quiet one.  The runner passed
    ``n = nEvery = 1``, which is the chunk containing record 1 and nothing else,
    so every file it processed yielded the particles of its FIRST RECORD: 1 for
    ``base160906075333``, 122 for ``base160906095907``.  It produced a valid,
    plausible-looking proc file every time and never errored.  The 49,637-particle
    proc file for ``base160906064403`` predates this driver and was written by a
    correct hand invocation, which is why the defect survived a comparison against
    it.

    ``chunks > 1`` is S3p tier 3, wired in here: splits the file's records
    across ``chunks`` subprocesses (this script re-exec'd with the hidden
    ``--_run-chunk`` mode, the same re-exec pattern ``--jobs`` already uses),
    waits, bounded by ``--worker-stall-min``, and refuses to merge an
    incomplete chunk, then merges with ``merge_chunks`` in the v3.1.4 validation engine (not
    included in this package)
    -- proven bit-for-bit equal to the ``chunks=1`` result at full production
    scale (S3p tier 3).
    """
    target = proc_path_for_decode(image_file, out_dir)
    want = proc_call_label()
    if _check_proc_state(target, want, "S3", accept_unstamped, source=image_file):
        return target
    if not image_file.exists():
        log(f"S3 SKIP   no {image_file.name} (S2 must run first)")
        return target
    n_records = image_record_count(image_file)
    partial = target.with_name(target.name + ".partial")
    partial.unlink(missing_ok=True)
    t0 = time.time()

    if chunks <= 1:
        step = max(1, n_records // 100)
        log(f"S3 start  {image_file.name} ({n_records} records, one chunk)")
        # shadow_diode is left None deliberately: S3o established that no diode
        # re-illumination reached the 09/06/2016 2D-S product, by two independent
        # routes (the final 80%-threshold masks are empty, and their names carry
        # no orientation letter so imgProc_sm.m:288's lookup would have missed
        # them).
        #
        # The progress step is ~1% of the file rather than a fixed count: a
        # fixed 2,000 would be one line every 17 minutes on a 20k-record file
        # and a wall of them on a 250k one.
        _imgproc_sm_chunk(image_file, partial, 1, n_records, _progress_every(step))
    else:
        if ENGINE == "3.5":
            # Fail before spawning, not after N workers have each run to completion:
            # merge_chunks_v35 refuses a probetype-2 merge, and main() refuses the flag,
            # but stage3 is also reached DIRECTLY by scripts and tests, and on that path
            # the refusal would otherwise arrive hours later with the work already spent.
            v35_imgproc = _v35().module("imgproc")
            timing = v35_imgproc.PROBES_V35[PROBE].timing
            if (timing not in v35_imgproc.CHUNKABLE_TIMINGS_V35
                    and timing not in v35_imgproc.PRIMABLE_TIMINGS_V35):
                raise v35_imgproc.ChunkingNotEquivalent(
                    f"{PROBE} is {timing!r} timing: a chunked v3.5 S3 pass cannot reproduce "
                    "the serial run (imgProc_sm.m:1131-1180 accumulates Time_in_seconds over "
                    f"the whole file). Chunkable: {sorted(v35_imgproc.CHUNKABLE_TIMINGS_V35)}; "
                    f"chunkable when primed: {sorted(v35_imgproc.PRIMABLE_TIMINGS_V35)}")
            if timing in v35_imgproc.PRIMABLE_TIMINGS_V35 and V35_CALL.i_qc == 1:
                # The one case priming cannot reach: qc_image can change an image's
                # width, so imgProc_sm.m:850-853's return can fire mid-file and a
                # prefix scan cannot locate it without doing the work it exists to
                # skip. Refused here rather than discovered by every worker.
                raise v35_imgproc.ChunkingNotEquivalent(
                    f"{PROBE} is {timing!r} timing and iQC=1: chunking this combination would "
                    "need a prefix scan that unpacks every image, which is the serial run. "
                    "Run iQC=1 serially.")
        elif PROFILE.time_in_seconds_from_tas:
            # main() refuses this too; stage3 is also reached directly by scripts
            # and tests, so the refusal is repeated here before any worker is spawned.
            raise ValueError(
                f"S3 --chunks under engine 3.1.4 with profile {PROFILE.name}: Time_in_seconds "
                "is a running sum over the whole file (imgProc_sm.m:724-778) and a chunk seam "
                "restarts it, so the merge would not equal the serial run. Run serially.")
        # Fail before spawning, same reason as the v3.5 check just above: a chunk
        # worker is a fresh subprocess whose own PROFILES dict starts with only the shipped
        # four. PROFILE_MODULE (below, in cmd_base) is how a registered profile's own module
        # travels there -- but it can only travel if it is SET, and nothing upstream of this
        # point can see whether it should be: config.py's own [fidelity].profile check passes
        # for a profile some out-of-band code already registered in THIS process, whether or
        # not profile_module named the module that did it (config.py:315-337). This is
        # the one place that knows a fresh subprocess is about to be asked to resolve
        # PROFILE.name, so it is the one place that can catch the gap -- refusing beats
        # letting every worker discover it independently, each with a bare KeyError ~2s in
        # and nothing written (measured: 11 of 11 workers, an 8-chunk launch).
        if PROFILE.name not in SHIPPED and not PROFILE_MODULE and not AUTHORDEFAULTS_PATH:
            raise ProfileNotReachableInChunkWorkers(
                f"--chunks {chunks} cannot run with profile {PROFILE.name!r}: it is not one "
                f"of the four shipped profiles ({sorted(SHIPPED)}), and PROFILE_MODULE is not "
                "set, so a fresh chunk-worker subprocess has no way to make PROFILES"
                f"[{PROFILE.name!r}] resolve -- it would raise a bare KeyError instead, "
                "separately, in each of the workers this call is about to start. Set "
                "[fidelity].profile_module in the run's --config to the dotted name of a "
                f"module whose import calls register_profile() for {PROFILE.name!r} (see "
                "arrayprobe.config's own [fidelity] docstring), or reach it through "
                "[fidelity].authordefaults, or run with chunks=1.")
        requested_chunks = chunks
        n_every, chunks = _chunk_plan(n_records, chunks)
        if chunks < requested_chunks:
            log(f"S3 chunks: {requested_chunks} requested, {chunks} used -- {n_records} "
                f"records at {n_every} per chunk leave no records for the rest")
        log(f"S3 start  {image_file.name} ({n_records} records, {chunks} chunks)")
        chunk_paths = [target.with_name(target.name + f".chunk{i}")
                       for i in range(1, chunks + 1)]
        if resume_chunks:
            # Each chunk is judged one by one below, against the intent computed fresh; here
            # only the chunks beyond this run's count go, left by an attempt with more.
            keep = {p.name for p in chunk_paths}
            for p in target.parent.glob(target.name + ".chunk*"):
                base = p.name.removesuffix(".done").removesuffix(".call")
                if base not in keep and base.removeprefix(target.name + ".chunk").isdigit():
                    p.unlink(missing_ok=True)
            for p in out_dir.glob(f"{image_file.stem}.chunk*.log"):
                idx = p.name.removeprefix(f"{image_file.stem}.chunk").removesuffix(".log")
                if idx.isdigit() and int(idx) > len(chunk_paths):
                    p.unlink(missing_ok=True)
        else:
            for p in chunk_paths:
                p.unlink(missing_ok=True)
                # The completion record a worker writes on success (P10 below) --
                # cleared here too, or a stale one from a previous killed attempt
                # could make a freshly-truncated chunk look complete.
                p.with_name(p.name + ".done").unlink(missing_ok=True)
                p.with_name(p.name + ".call").unlink(missing_ok=True)
        # PROBE, PROJECT and PROFILE are passed explicitly: each chunk worker is a
        # fresh subprocess that re-imports this module from scratch, so it starts
        # at this module's *defaults* (ACTIVE = ORACLES_2016_2DS_H, PROFILE =
        # ORACLES_PRODUCTION) regardless of what --preset/--config the parent
        # process is actually running. Found while generalising PROFILE to any
        # registered profile (2026-09-10): the merge step
        # below already reads the parent's live PROFILE, so an un-threaded
        # profile would have silently merged chunks built under the WRONG
        # profile with a merge stamped as the RIGHT one. PROBE/PROJECT had the
        # identical gap already, for the same reason, and are fixed the same way
        # rather than left inconsistent now that this path is exercised for the
        # first time under a non-default profile.
        #
        # PROFILE_MODULE travels the same way, for a narrower reason (2026-09-10):
        # PROFILE.name alone resolves in the chunk worker only if PROFILE is one
        # of the shipped module-level constants. A profile reached via
        # register_profile() is not in a fresh process's PROFILES dict at all,
        # so the worker must import the same module the parent's --config did
        # before it can look the name up -- "" (never a valid module name)
        # stands for "nothing to import", not the empty string as a real value.
        # TAS_FILE travels the same way, "" for none (2026-09-13, one-config-file Phase 2b).
        cmd_base = [sys.executable, str(Path(__file__).resolve()), "--_run-chunk",
                    str(image_file), PROBE, PROJECT, PROFILE.name, PROFILE_MODULE or "",
                    TAS_FILE or "", str(worker_stall_min)]
        workers = []
        # --jit rides as an optional trailing "jit" token (argv[11]) so the
        # ten-field positional shape older callers use stays valid.
        #
        # ENGINE rides the same way, as `engine=<v>` (2026-09-17). It is
        # NOT optional in effect: a worker is a fresh subprocess that re-imports
        # this module and so starts at ENGINE's import-time default "3.1.4",
        # exactly the gap the comment beside cmd_base describes for
        # PROBE/PROJECT/PROFILE. Until --chunks was refused under --engine 3.5
        # that gap was unreachable; wiring the two together makes it live, and
        # an unthreaded ENGINE would have had v3.5 chunk workers writing
        # v3.1.4 output into a merge stamped engine=3.5. Keyed rather than
        # positional so the trailing tokens stay order-independent.
        jit_tail = ["jit"] if JIT else []
        jit_tail.append(f"engine={ENGINE}")
        # Author-editable thresholds: the authordefaults file rides as a tail token
        # (cmd_base is positional), only when set, so a run without the file keeps its
        # chunk intent byte-identical.
        if AUTHORDEFAULTS_PATH is not None:
            jit_tail.append(f"authordefaults={AUTHORDEFAULTS_PATH}")
        # Airspeed policy: a chunk worker re-imports this module from scratch and would otherwise
        # start at TAS_POLICY's own default (300/170 m/s) regardless of what this run's TAS
        # chain resolved to -- see the --_run-chunk tail parser's tas_policy= branch.
        jit_tail.append(f"tas_policy={TAS_POLICY.token()}")
        if ENGINE == "3.5":
            # The two v3.5 switches a run may set ([v35] in a config). A worker starts at
            # V35_CALL's own defaults, so without this it would compute every chunk with
            # iQC=0/iNewHabit=0 while the merge below and the proc stamp name this run's values.
            jit_tail.append(f"v35_call=iQC:{V35_CALL.i_qc},iNewHabit:{V35_CALL.i_new_habit}")
            # The stray-pixel correction rule: a worker starts at STRAY_PIXEL's import-time False.
            jit_tail.append(f"stray_pixel={'on' if STRAY_PIXEL else 'off'}")
            # --tas-ratio on: a worker starts at TAS_RATIO's import-time False and would pass
            # tasRatio=None (the iTAS == 0 path) for its records while the merge stamps
            # tas_ratio=on. Appended only when on, so an off run's chunk intent is unchanged.
            if TAS_RATIO:
                jit_tail.append("tas_ratio=on")
        # Probetype 2 accumulates Time_in_seconds across the whole file, so a
        # chunk that starts with part_time_prev unset restarts the sum and every
        # particle after the seam differs. Priming hands each worker the two float64
        # scalars a serial run held at its first record, after which the worker
        # performs the IDENTICAL IEEE operations on identical operands -- bit-exact by
        # construction, where a post-hoc offset re-rounds. One pass over the file here
        # rather than one per worker: the arithmetic is the same either way (asserted
        # in tests/test_v35_sizedist_chunk_priming.py), but N workers each scanning
        # their own prefix would read the file N/2 times over and leave the last
        # worker scanning almost all of it before starting.
        #
        # float.hex() rather than repr(): both round-trip exactly, but hex says so on
        # its face, and this is a fidelity seam where "close" is a wrong answer.
        primes: list[tuple[float, float] | None] = [None] * len(chunk_paths)
        if ENGINE == "3.5" and timing in v35_imgproc.PRIMABLE_TIMINGS_V35:
            t_scan = time.time()
            tas_time, tas = _aircraft_series()
            primes = v35_imgproc.chunk_primes_v35(
                str(image_file), PROBE, n_every, len(chunk_paths),
                tas_time=tas_time, tas=tas, iQC=V35_CALL.i_qc,
                progress=_progress_every(max(1, n_records // 20)))
            log(f"S3 prefix scan: {len(chunk_paths)} chunk seams primed "
                f"({time.time() - t_scan:.0f} s)")
        code = None
        if resume_chunks:
            code = _code_identity()
            if code is None:
                log("S3 resume: the code's git state is unknown or modified, so no chunk "
                    "is reused")
        for i, chunk_path in enumerate(chunk_paths, start=1):
            tail = list(jit_tail)
            prime = primes[i - 1]
            if prime is not None:
                ptp, tisp = prime
                tail.append(f"prime={float(ptp).hex()},{float(tisp).hex()}")
            cmd = [*cmd_base, str(chunk_path), str(i), str(n_every), *tail]
            if resume_chunks:
                # --resume-chunks: reuse a chunk only when the intent it was built under
                # equals this run's, byte for byte, and its completion record says so.
                # Otherwise all three files go and the chunk is rebuilt, as without the flag.
                text = _chunk_intent_text(cmd, want, image_file, n_records, len(chunk_paths),
                                          code or "unknown")
                reason = ("code state unknown" if code is None
                          else _chunk_reuse_refusal(chunk_path, text))
                if reason is None:
                    with netCDF4.Dataset(str(chunk_path)) as ds:
                        log(f"S3 resume chunk {i}: reused ({len(ds.dimensions['time'])} "
                            "particles)")
                    continue
                log(f"S3 resume chunk {i}: recomputed ({reason})")
                for p in (chunk_path, chunk_path.with_name(chunk_path.name + ".done"),
                          chunk_path.with_name(chunk_path.name + ".call")):
                    p.unlink(missing_ok=True)
                if code is not None:
                    chunk_path.with_name(chunk_path.name + ".call").write_text(text)
                    cmd.append(f"intent={hashlib.sha256(text.encode()).hexdigest()}")
            log_path = out_dir / f"{image_file.stem}.chunk{i}.log"
            log_f = open(log_path, "w")
            proc = subprocess.Popen(cmd, stdout=log_f, stderr=subprocess.STDOUT)
            workers.append((i, proc, log_f, log_path))
        # Bounded, fail-closed wait (P10, 2026-09-13): a bare
        # `proc.wait()` here is what let a deadlocked chunk worker block this
        # parent for 6 h 25 min with no error and no way to notice.
        #
        # `worker_stall_min <= 0` reproduces that old unbounded wait.
        _await_workers(workers, stall_s=worker_stall_min * 60, what="S3 chunk")
        # Refuse to merge a chunk that exited 0 but never actually wrote its
        # records -- the failure mode `_await_workers` alone cannot see, since
        # rc==0 was previously the only gate before merge_chunks. Two sides
        # from two places: the worker's own claim (`.done`) vs. what the file
        # holds (its `time` dimension), so a worker that lied or a truncated
        # write are both caught.
        stopped_at = None
        for i, chunk_path in enumerate(chunk_paths, start=1):
            done = chunk_path.with_name(chunk_path.name + ".done")
            if not done.exists():
                raise RuntimeError(
                    f"S3 chunk {i} of {image_file.name} exited 0 but wrote no "
                    f"completion record ({done.name}); refusing to merge a partial chunk")
            lines = done.read_text().splitlines()
            claimed = int(lines[0].strip())
            if "width-mismatch-return" in lines[1:] and stopped_at is None:
                stopped_at = i
            with netCDF4.Dataset(str(chunk_path)) as ds:
                actual = len(ds.dimensions["time"])
            if claimed != actual:
                raise RuntimeError(
                    f"S3 chunk {i}: worker reported {claimed} particles, file holds "
                    f"{actual}; refusing to merge")
        log(f"S3 merge  {len(chunk_paths)} chunks -> {partial.name}")
        beat = _log_heartbeat("S3 merge", _heartbeat_interval(worker_stall_min * 60), partial)
        if ENGINE == "3.5":
            if stopped_at is not None:
                log(f"S3 merge: chunk {stopped_at} hit imgProc_sm.m:850-853's width-mismatch "
                    f"return, so chunks {stopped_at + 1}..{len(chunk_paths)} are DROPPED -- "
                    "MATLAB exits the whole function there and never processes those records")
            with beat:
                _v35().module("imgproc").merge_chunks_v35(
                    [str(p) for p in chunk_paths], str(partial),
                    projectname=PROJECT, infile=str(image_file), probename=PROBE,
                    stamp_profile=PROFILE.name,
                    iRectEllipse=V35_CALL.i_rect_ellipse,
                    iCalcAllDiodeStats=V35_CALL.i_calc_all_diode_stats,
                    iQC=V35_CALL.i_qc, iNewHabit=V35_CALL.i_new_habit,
                    software=V35_CALL.software, stopped_at=stopped_at,
                    stray_pixel_fix=STRAY_PIXEL,
                    tas_qc=(_s3_tas_qc_v35(image_file, *_aircraft_series())
                            if _v35().module("imgproc").PROBES_V35[PROBE].probetype == 2
                            else None),
                    # merge_chunks_v35 cannot verify this -- nothing on disk records
                    # whether a chunk was primed, exactly as nothing records which
                    # record range it covers. This call site is the one that knows,
                    # because it computed the pairs twenty lines above.
                    primed=any(p is not None for p in primes))
        else:
            with beat:
                imgproc.merge_chunks([str(p) for p in chunk_paths], str(partial),
                                     PROFILE, PROJECT, str(image_file), PROBE)
        for p in chunk_paths:
            p.unlink(missing_ok=True)
            p.with_name(p.name + ".done").unlink(missing_ok=True)
            p.with_name(p.name + ".call").unlink(missing_ok=True)
        # Every chunk's log, including a reused chunk's from the attempt that built it.
        for i in range(1, len(chunk_paths) + 1):
            (out_dir / f"{image_file.stem}.chunk{i}.log").unlink(missing_ok=True)

    os.replace(partial, target)
    write_stamp(target, want)
    log(f"S3 done   {target.name} ({time.time() - t0:.0f} s)")
    return target


def _s4_case_inputs() -> dict[str, Any]:
    """``sizedist.run``'s ``tas_max`` / ``pecan_params`` keywords for this run, each present only
    when set (:data:`TAS_MAX`, :data:`PECAN_PARAMS`), so the default call is unchanged."""
    out: dict[str, Any] = {}
    if TAS_MAX is not None:
        out["tas_max"] = TAS_MAX
    if PECAN_PARAMS is not None:
        out["pecan_params"] = PECAN_PARAMS
    return out


def _s4_case_inputs_stamp() -> str:
    """The sd stamp's `` tas_max=<v>`` / `` pecan_params=<name>@sha256:<12>`` fragment, each only
    when set, so every stamp written without them stays byte-identical. The parameter file is
    named by its content hash as well as its name: a changed file must read stale."""
    out = ""
    if TAS_MAX is not None:
        out += f" tas_max={TAS_MAX!r}"
    if PECAN_PARAMS is not None:
        digest = hashlib.sha256(Path(PECAN_PARAMS).read_bytes()).hexdigest()[:12]
        out += f" pecan_params={Path(PECAN_PARAMS).name}@sha256:{digest}"
    return out


def _s4_case_inputs_problem() -> str | None:
    """Why this run's ``sizeDist`` case cannot run with the ``tas_max``/``pecan_params`` it has,
    or ``None``. Asked at preflight so a refusal comes before S2/S3 spend hours. A case this
    process cannot resolve gives ``None`` -- S4 itself raises on it."""
    try:
        if ENGINE == "3.5":
            sd = _v35().module("sizedist")
            cfg = (sd.resolve_probe_case(PROBE_CASE).defaults if PROBE_CASE is not None
                   else sd.probe_defaults(PROJECT, PROBE, version="3.5"))
            case_tas_max, needs_pecan = cfg.tasMax, bool(cfg.calls_getPECANparams)
        else:
            cfg = constants.sizedist_config(PROJECT, PROBE, TREE)
            case_tas_max, needs_pecan = cfg.tas_max, bool(cfg.needs_pecan_params)
    except (LookupError, ValueError, NotImplementedError):
        return None
    case = f"{PROJECT!r}/{PROBE!r}"
    if TAS_MAX is not None:
        if isinstance(TAS_MAX, bool) or not (math.isfinite(TAS_MAX) and TAS_MAX > 0.0):
            return f"--tas-max is an airspeed in m/s, finite and > 0; got {TAS_MAX!r}"
        if case_tas_max is not None:
            return (f"--tas-max supplies a tasMax the case leaves unassigned (2DP); {case} "
                    f"assigns tasMax = {case_tas_max:g}. Drop --tas-max / [thresholds].tas_max")
    elif case_tas_max is None:
        return (f"{case} assigns no tasMax (the 2DP, in every UIOPS release), and sizeDist "
                "reads it, so MATLAB dies there; there is no default. Give the probe's own value "
                "with --tas-max <m/s> or [thresholds].tas_max in the --config file")
    if PECAN_PARAMS is not None and not needs_pecan:
        return (f"--pecan-params replaces getPECANparams, which only the PECAN CIP/PIP cases "
                f"call; {case} does not. Drop --pecan-params / [thresholds].pecan_params")
    if PECAN_PARAMS is None and needs_pecan:
        return (f"{case} calls getPECANparams, which ships in no UIOPS release. Give the spiral "
                "parameters with --pecan-params <file> or [thresholds].pecan_params")
    return None


def iat_call_label(iat_file: str | None) -> str:
    """How ``sizeDist`` was called, as one line, for the ``.call`` sidecar.

    WHY A SIDECAR AND NOT THE FILE'S OWN ATTRIBUTES.  ``sizeDist.m:1693-1704``
    writes ``Shattering Algorithm`` from ``applyIntArrThresh`` alone, while the
    block that applies it is gated at ``:866`` on ``applyIntArrThresh &&
    length(varargin) == 1``.  So an sd file made with *no* threshold argument
    says "Applied without reacceptance of particles" and had no shattering
    rejection run over it -- measured (the misreported shattering attribute).  The two calls are
    indistinguishable from inside the product and differ by 58% of the accepted
    particles, so which one produced a given file has to be recorded somewhere.
    Adding an attribute of our own would break byte-fidelity with MATLAB, so the
    provenance goes beside the file instead of in it.
    """
    return "iat_file=" + (iat_file if iat_file else "<none>")


def stage4(proc_file: Path, raw_stem: str, out_dir: Path,
           iat_file: str | None = IAT_FILE, shadow_diode=None,
           accept_unstamped: bool = False) -> Path:
    """``proc.*.nc`` + the TAS sidecar -> ``sd.*.nc``, 25 one-second variables.

    ``iat_file`` is ``sizeDist``'s optional twelfth argument.  **Passing nothing
    is not the same as passing a name that does not exist**: a name that does not
    exist sets ``iaThreshFile = 'NONE'`` and ``:874`` falls back to the per-probe
    6 us default and rejects on it, while passing nothing skips the whole
    shattering block via the ``&&`` short-circuit at ``:866``.

    The archived product was made with the threshold-file form, so that
    is the default (S4c design doc SS6).  ``--iat-file ''`` selects the other
    call, which is a legitimate configuration and not one that reproduces any
    published product.
    """
    target = out_dir / f"sd.{proc_file.name.removeprefix('proc.')}"
    tas_csv = out_dir / f"{raw_stem}.tas.csv"
    want = sd_call_label(iat_file, shadow_diode=shadow_diode)

    # THE INPUT IS CHECKED BEFORE THE OUTPUT.  `--stages 4` skips S3 entirely,
    # so this is the only place that can notice an sd file about to be built
    # from a proc file made under different reject thresholds -- which is what
    # would have happened on flight 09/14 on 2026-08-30 had a directory listing
    # not been read by hand.  An sd file cannot be asked which proc made it.
    proc_state = output_state(proc_file, proc_call_label(shadow_diode=shadow_diode))
    if proc_state == "unstamped" and not accept_unstamped:
        raise UnverifiableProvenance(
            f"{proc_file.name} carries no .call sidecar, so the configuration "
            f"behind {target.name} would be unknown; delete the proc file to have "
            "it rebuilt, or pass --accept-unstamped")
    if proc_state == "stale":
        raise UnverifiableProvenance(
            f"{proc_file.name} was built with {read_stamp(proc_file)}, but this "
            f"run wants {proc_call_label(shadow_diode=shadow_diode)}; run S3 for "
            "it again rather than building an sd file on top of it")

    if target.exists():
        got = read_stamp(target) or "<unrecorded>"
        if _particle_clock_fix_allowed():
            # Engine-3.5 defect correction: an sd built with the derived clock fix is current
            # against a want that
            # does not yet know the fix (it is derived below, from the proc); the outdated
            # check that follows still catches a proc newer than the sd.
            got = _strip_particle_clock_fix(got)
        if ",IMPLAUSIBLE)" in got and not ACCEPT_IMPLAUSIBLE:
            log(f"S4 redo   {target.name} was refused by the plausibility gate when written")
        elif _stamps_equivalent(got, want):
            # The same input-newer-than-output check S2/S3 make through
            # output_state(..., source=).  Written inline here because this
            # branch compares the stamp itself rather than calling that
            # helper; the quickstart failure of 2026-09-19 skipped BOTH this
            # stage and S3, so fixing only S3 would have left an sd file from
            # 2026-09-10 being stitched by S4c and the product still empty.
            try:
                outdated = target.stat().st_mtime < proc_file.stat().st_mtime
            except OSError:
                outdated = False
            if not outdated:
                log(f"S4 skip   {target.name} exists")
                return target
            log(f"S4 redo   {target.name} is older than its input "
                f"{proc_file.name}, so it cannot be a product of it (the .call "
                "stamp records configuration, not inputs)")
        else:
            log(f"S4 redo   {target.name} was built with {got}, want {want}")
        # Deliberately NOT deleted here.  A redo needs a proc file and a TAS
        # sidecar to actually succeed; if either is gone (checked next), there
        # is nothing to replace this file WITH, and deleting it now would
        # destroy the only surviving copy for nothing.  `os.replace(partial,
        # target)` below already overwrites it atomically once a new one is
        # actually ready -- an explicit unlink here was never load-bearing for
        # the success path and was the whole bug on the failure path.  Real
        # incident, 2026-08-27: this exact ordering deleted
        # sd.base160906075333.H.nc and sd.base160906095907.H.nc when a
        # --stages 4 diagnostic run hit "redo" for both and their proc files
        # had already been lost separately -- the SKIP fired immediately
        # after, but only once the delete had already happened.
    if not tas_csv.exists():
        decoded = sorted(out_dir.glob(f"{raw_stem}.*{image_suffix_for_probe()}"))
        if decoded:
            # S2 did run: blaming it for not running sent a user who had just watched
            # "S2 done" back to re-run it (cold-user walk, 2026-09-26, a 1-second demo).
            log(f"S4 SKIP   {target.name}: S2's decode ({decoded[0].name}) is here but wrote "
                f"no {tas_csv.name} -- the raw file held no airspeed record S2 could read, "
                "so S4 has no TAS to size with (a CIP/PIP decode never writes one: pass "
                "--tas-from-probe)")
        else:
            log(f"S4 SKIP   {target.name}: no {tas_csv.name} (S2 must run first)")
        return target
    if not proc_file.exists():
        log(f"S4 SKIP   no {proc_file.name} (S3 must run first)")
        return target
    log(f"S4 start  {proc_file.name}")
    if bin_table_fix_on():
        log("bin_table_fix (corrected by default on engine 3.5): sizing this 2D-S on the "
            "2D-S 128-bin ladder "
            "upstream commented out at v3.5 sizeDist.m:506-507, not the otherwise branch's "
            "HVPS table (:502-505); --protective off to keep stock behaviour")
    elif _v35_otherwise_hvps_bins_on_2ds():
        log(V11_BINS_WARNING)
    t0 = time.time()
    timehhmmss, tas = load_tas_info(tas_csv)
    if TAS_CHAIN is None and tas_grid_fix_on():
        timehhmmss, tas = _collapse_probe_grid(timehhmmss, tas, "S4 tas   ")
    probe_time = timehhmmss
    tas_missing: list[int] = []
    if TAS_CHAIN is not None:
        # The airspeed policy and the author's E2 ruling (2026-09-23, "S4's probe path ALSO gets the
        # cutoff/default policy, so there is one TAS series per run"): once a run opts into a
        # chain (TAS_SOURCE set), sizeDist is handed the chain's own policy-substituted series
        # -- via the same series_for_sizedist path -- for EVERY tier the chain can resolve to,
        # including "probe". A probe-tier chain already ran the raw <stem>.tas.csv through
        # TasPolicy in reduce_probe_csv (resolve_chain's own "probe" branch); this hands S4
        # that substituted result instead of re-reading the file's own -999/241,403 m/s rows.
        # By default the time axis stays the probe's own (floored) axis -- series_for_sizedist's
        # own docstring -- so `np.floor(timehhmmss)` downstream in _sizedist_call is a no-op
        # here. `--tas-grid regular` (TAS_GRID) swaps it for every second of the probe's span
        # once, because sizeDist files no particle of a repeated or skipped probe second.
        timehhmmss, tas, tas_missing = _chain_series_for_sizedist(timehhmmss, "S4 tas   ")
        probe_time = timehhmmss if TAS_GRID == "regular" else probe_time
        if tas_missing:
            log(f"S4 tas    {len(tas_missing)} second(s) with no {TAS_CHAIN.tier} sample -> "
                f"{TAS_POLICY.default_mps:g} m/s: {_mtf.second_ranges(tas_missing)}")
    # Fail closed on a particle clock that misses the TAS axis (2026-10-04,
    # CIP_V35_SD_EMPTY_1830): sizeDist would otherwise write an all-NaN sd and exit 0.
    off_axis = _s4_particle_clock_problem(proc_file, timehhmmss)
    clock_fix: tuple[int, str] | None = None
    if off_axis is not None:
        # Engine-3.5 defect correction: a data-destroying defect is corrected by default --
        # here the raw
        # probe clock, when the offset is unambiguous in the proc itself. Otherwise refuse.
        clock_fix = (_s4_derive_particle_clock_fix(proc_file, timehhmmss)
                     if _particle_clock_fix_allowed() else None)
        if clock_fix is None:
            raise ParticleClockOffAxis(off_axis)
        log(f"S4 clock  {proc_file.name}: {off_axis.split('; ')[0]}; applying the derived "
            f"particle-clock offset {clock_fix[0]:+d} s ({clock_fix[1]}; --protective off to "
            "refuse instead)")
        want += f" {PARTICLE_CLOCK_FIX_KEY}{clock_fix[0]:+d}s"
    partial = target.with_name(target.name + ".partial")
    partial.unlink(missing_ok=True)
    # Built before the sizeDist call so --write-provenance can carry it inside the sd file too
    # as metadata; the sidecar below is written from the same dict either way.
    tas_qc = _tas_qc_record(probe_time, tas_missing)
    global TIME_OFFSET
    saved_offset = TIME_OFFSET
    if clock_fix is not None:
        # The same path --time-offset-s takes (sizeDist's time_offset_s keyword), for this call
        # only, so the next flight of the run is checked afresh.
        TIME_OFFSET = (clock_fix[0], clock_fix[1], "aircraft")
    try:
        counts = _sizedist_call(proc_file, partial, raw_stem, timehhmmss, tas, iat_file,
                                tas_qc=tas_qc)
    finally:
        TIME_OFFSET = saved_offset
    os.replace(partial, target)
    # Same partial-then-rename pattern as `target` above, not a bare write_text:
    # a kill between the sd file landing and this sidecar being written left the
    # target correct but the .call missing before this fix too, self-healing
    # (sd_is_current() just redoes S4 next run) but wasted compute either way.
    if _plausibility_gate_applies():
        stamp, refusal = _s4_plausibility_gate(target, proc_file, want + counts)
    else:
        # Engine 3.1.4 reproduces the archived record: no plausibility token, no refusal.
        stamp, refusal = want + counts, None
    write_stamp(target, stamp)
    _store_tas_qc(target, tas_qc)
    if refusal is not None:
        raise ImplausibleProduct(refusal)
    log(f"S4 done   {target.name} ({time.time() - t0:.0f} s, {want})")
    return target


class ImplausibleProduct(UnverifiableProvenance):
    """S4 refused its own output: the sd is empty or near-empty while its proc accepted particles
    (the post-S4 plausibility gate). The file is kept, stamped IMPLAUSIBLE; the run exits 2."""


def _s4_plausibility_gate(target: Path, proc_file: Path, want: str) -> tuple[str, str | None]:
    """The stamp to write for the sd ``target`` and, when the post-S4 plausibility gate
    refuses it, why.

    Reads the written sd and its proc (``arrayprobe_uiops.product_sanity``, netCDF4/numpy only),
    appends a ``plausibility=(...)`` token to ``want``, and logs a WARNING (never a refusal) for
    non-finite/realmax and duplicated seconds. Refuses (second element not None) when fewer than
    ``MIN_FRAC_SECONDS_WITH_PARTICLES`` of the seconds that could carry particles (the axis, or the
    proc's accepted seconds when fewer) do, while the proc accepted at least
    ``MIN_ACCEPTED_FOR_REFUSAL`` particles, unless :data:`ACCEPT_IMPLAUSIBLE`. Never deletes the
    file."""
    from arrayprobe_uiops import product_sanity as _ps  # shared, engine-free (T9's SHARED set)

    try:
        accepted = _ps.accepted_particles(proc_file) if proc_file.exists() else None
        acc_secs = _ps.accepted_seconds(proc_file) if proc_file.exists() else None
    except OSError:
        accepted, acc_secs = None, None
    try:
        p = _ps.sd_plausibility(target, accepted, accepted_secs=acc_secs)
    except OSError as exc:
        # Not this gate's question (an empty or near-empty sd): an unreadable file is S4's own
        # write failing, and stubbed sizeDist calls in tests write placeholders. Never refuse here.
        log(f"S4 WARNING {target.name}: not readable as netCDF ({exc}); plausibility not measured")
        return want, None
    if p.nonfinite_seconds or p.duplicated_seconds:
        log(f"S4 WARNING {target.name}: {p.nonfinite_seconds} second(s) hold non-finite or "
            f"realmax values, {p.duplicated_seconds} second(s) are duplicated")
    stamp = f"{want} {p.token()}"
    if not p.implausible:
        return stamp, None
    why = (f"{target.name} is implausible: {p.reason}, while {proc_file.name} accepted "
           f"{'an unknown number of' if accepted is None else accepted} particle(s). Likely "
           "causes: a particle clock never shifted to the TAS clock (check time_offset), or a "
           "bin table that does not match the probe. The file is kept; pass "
           "--accept-implausible to keep it as current")
    if ACCEPT_IMPLAUSIBLE:
        log(f"S4 WARNING {why} (accepted: --accept-implausible)")
        return stamp, None
    return stamp, why


#: Below this fraction of a proc's particles landing on a TAS-axis second, S4 refuses: the
#: particle clock and the axis are not the same clock. Measured 2026-10-04 on the driver's
#: v3.5 CIP proc of 2016-09-06 07:59:50 (raw probe clock, never shifted): 557 of 3,797,537
#: particles (0.015 %) landed on its 28,533-second axis, and its sd was all NaN.
S4_MIN_PARTICLES_ON_AXIS = 0.01


class ParticleClockOffAxis(UnverifiableProvenance):
    """S4 refused: the proc's particle times miss the TAS time axis, so the sd would be empty."""


#: Engine-3.5 defect correction: the share of a proc's particles that must land on the TAS
#: axis after the derived
#: offset is applied before S4 applies it by default (engine 3.5); below it S4 refuses.
S4_CLOCK_FIX_MIN_ON_AXIS = 0.99

#: The sd ``.call`` key naming a derived particle-clock offset, e.g. ``particle_clock_fix=+24570s``.
PARTICLE_CLOCK_FIX_KEY = "particle_clock_fix="


def _particle_clock_fix_allowed() -> bool:
    """Whether S4 may derive and apply a particle-clock offset (a default-on defect
    correction): engine 3.5 only, and not
    under ``--protective off`` (the opt-out, which keeps the refusal). v3.1.4 always refuses."""
    return ENGINE == "3.5" and PROTECTIVE_MODE != "off"


def _strip_particle_clock_fix(stamp: str) -> str:
    """``stamp`` without its ``particle_clock_fix=`` token."""
    return " ".join(tok for tok in stamp.split(" ") if not tok.startswith(PARTICLE_CLOCK_FIX_KEY))


def _on_axis(t, axis) -> np.ndarray:
    """Which of the HHMMSS times ``t`` fall on a second of ``axis`` (modulo the day)."""
    return np.isin(np.mod(np.floor(t), 240000), np.mod(axis, 240000))


def _s4_derive_particle_clock_fix(proc_file: Path, timehhmmss) -> tuple[int, str] | None:
    """``(seconds, evidence)`` to add to the proc's ``particle_time``, or ``None`` if ambiguous.

    The offset is the mode, across particles, of the whole-second difference between each
    particle's record ``Time`` (aircraft time) and its ``particle_time`` (the probe's clock), and
    it is accepted only if at least :data:`S4_CLOCK_FIX_MIN_ON_AXIS` of the particles land on
    the TAS axis once shifted. Probetype 1 only: elsewhere sizeDist reads ``Time`` itself, so
    there is no second clock to derive from.
    """
    try:
        probetype = constants.imgproc_config(PROBE).probetype
    except Exception:                                    # noqa: BLE001 -- no config: no fix
        return None
    if probetype != 1:
        return None
    with netCDF4.Dataset(proc_file) as nc:
        if "particle_time" not in nc.variables or "Time" not in nc.variables:
            return None
        arrs = []
        for name in ("particle_time", "Time"):
            var = nc.variables[name]
            var.set_auto_mask(False)
            arrs.append(np.asarray(var[:], dtype=np.float64).reshape(-1))
    pt, rec = arrs
    if pt.size == 0 or pt.size != rec.size:
        return None
    ok = np.isfinite(pt) & np.isfinite(rec)
    pt, rec = pt[ok], rec[ok]
    if pt.size == 0:
        return None
    sizedist_v35 = _v35().module("sizedist")
    from arrayprobe_uiops.sizedist_core import _hhmmss_to_insec as to_insec
    diff = np.mod(to_insec(np.floor(rec)) - to_insec(np.floor(pt)), 86400.0).astype(np.int64)
    values, counts = np.unique(diff, return_counts=True)
    seconds = int(values[np.argmax(counts)])
    # Unambiguous: >= 99 % of particles within one second of the mode (a dense axis lands
    # almost any shift, so the on-axis share alone cannot tell a real offset from noise).
    near = np.abs(((diff - values[np.argmax(counts)]) + 43200) % 86400 - 43200) <= 1
    share = float(near.mean())
    if share < S4_CLOCK_FIX_MIN_ON_AXIS:
        return None
    if seconds > 43200:
        seconds -= 86400
    if seconds == 0:
        return None
    axis = np.floor(np.asarray(timehhmmss, dtype=np.float64).reshape(-1))
    frac = float(_on_axis(sizedist_v35.shift_hhmmss(pt, seconds), axis).mean())
    if frac < S4_CLOCK_FIX_MIN_ON_AXIS:
        return None
    return seconds, (f"derived by the driver: mode of Time - particle_time over "
                     f"{pt.size} particles ({100 * share:.2f} % within 1 s of the mode); "
                     f"{100 * frac:.2f} % on the TAS axis after the shift")


def _s4_particle_clock_problem(proc_file: Path, timehhmmss) -> str | None:
    """Why S4 must not run on ``proc_file`` against ``timehhmmss``, or ``None``.

    A driver-level check that reads the same particle-time variable sizeDist reads
    (``particle_time`` for probetype 1, ``Time`` otherwise; v3.5 ``sizeDist.m:758-781``), applies
    this run's :data:`TIME_OFFSET` as the engine would, and counts the particles whose whole
    second (modulo the day, so midnight carry-over is not a miss) is a second of the axis.
    Computes nothing sizeDist uses and changes no output; a proc with no particles, or without
    the variable, is left to sizeDist.
    """
    try:
        probetype = constants.imgproc_config(PROBE).probetype
    except Exception:                                    # noqa: BLE001 -- no config: no check
        return None
    name = "particle_time" if probetype == 1 else "Time"
    with netCDF4.Dataset(proc_file) as nc:
        if name not in nc.variables:
            return None
        var = nc.variables[name]
        var.set_auto_mask(False)
        t = np.asarray(var[:], dtype=np.float64).reshape(-1)
    t = t[np.isfinite(t)]
    if t.size == 0:
        return None
    axis = np.floor(np.asarray(timehhmmss, dtype=np.float64).reshape(-1))
    if TIME_OFFSET is not None:
        shift = _v35().module("sizedist").shift_hhmmss
        t = shift(t, TIME_OFFSET[0])
        if TIME_OFFSET[2] == "probe":
            axis = shift(axis, TIME_OFFSET[0])
    on_axis = np.isin(np.mod(np.floor(t), 240000), np.mod(axis, 240000))
    frac = float(on_axis.mean())
    if frac >= S4_MIN_PARTICLES_ON_AXIS:
        return None
    return (f"{proc_file.name}: {int(on_axis.sum()):,} of {t.size:,} particles "
            f"({100 * frac:.3f} %) have a {name} second on the TAS axis ({axis.size:,} s, "
            f"{axis.min():.0f}-{axis.max():.0f} hhmmss); their {name} spans "
            f"{t.min():.0f}-{t.max():.0f}. sizeDist would write an empty sd. Probable cause: the "
            "probe's own clock was never shifted to aircraft time. Measure the offset and pass "
            "--time-offset-s with --time-offset-evidence and --time-offset-tas-clock (engine 3.5), "
            "or check that the TAS file belongs to this flight")


def _chain_series_for_sizedist(probe_time, tag: str):
    """``(time, tas, missing)`` for ``sizeDist`` from :data:`TAS_CHAIN`, on the probe's own axis
    (``TAS_GRID == "probe"``, the default) or on a regular one-second grid over the probe's span
    (``"regular"``). One function for :func:`stage4` and :meth:`EnhancedStages.sizedist`, so
    the ordinary and enhanced products of one run are always sized on the same vector."""
    chain = TAS_CHAIN
    # Both callers (stage4, EnhancedStages.sizedist) call this only under `TAS_CHAIN is not None`.
    assert chain is not None
    if TAS_GRID == "regular":
        t, tas, missing = _tas_sources.regular_series_for_sizedist(
            probe_time, chain.time, chain.tas, TAS_POLICY)
        n_probe = int(np.asarray(probe_time).size)
        n_unique = int(np.unique(np.floor(np.asarray(probe_time, dtype=np.float64))).size)
        log(f"{tag} regular grid: {t.size} one-second rows over the probe's span, in place of "
            f"{n_probe} probe rows ({n_probe - n_unique} repeated, {t.size - n_unique} absent)")
        return t, tas, missing
    return _tas_sources.series_for_sizedist(probe_time, chain.time, chain.tas, TAS_POLICY)


def _write_tas_qc(product: Path, probe_time, tas_missing) -> None:
    """``<product>.tasqc.json``: which seconds ``sizeDist`` was handed a default TAS for.

    Written only when a run names a TAS source (``TAS_CHAIN`` or ``TAS_FILE``); the legacy
    probe-only path gets none, and a record left by an earlier source run is removed so it
    cannot describe this product. A separate sidecar, never the ``.call``: ``.call`` equality
    decides staleness, so a count inside it would restamp every product.
    """
    _store_tas_qc(product, _tas_qc_record(probe_time, tas_missing))


def _store_tas_qc(product: Path, rec: dict | None) -> None:
    """Write ``rec`` as ``<product>.tasqc.json``, or remove a stale one when ``rec`` is None."""
    if rec is None:
        _tas_sources.qc_sidecar_path(product).unlink(missing_ok=True)
        return
    _tas_sources.write_qc_sidecar(product, rec)


def _tas_qc_record(probe_time, tas_missing) -> dict | None:
    """The record :func:`_write_tas_qc` writes, or None when there is none to write: the run
    named no TAS source, or its aircraft file cannot be read (a record built without it would
    be invented)."""
    if TAS_CHAIN is None and TAS_FILE is None:
        return None
    legacy = None
    if TAS_CHAIN is None:
        # --tas-file without a chain: S4 sizes on the probe csv, and the aircraft file's own
        # substitutions (_aircraft_series) are the record of what took the default.
        try:
            series = _tas_sources.read_aircraft(TAS_FILE)
        except (FileNotFoundError, OSError) as exc:
            # A missing record is stated downstream ("absent"); a record built without the
            # aircraft file would be invented. Never fail the stage over its sidecar.
            log(f"S4 TAS QC record not written: cannot read {TAS_FILE} ({exc})")
            return None
        _t, legacy = _tas_sources.substitute(series.time_hhmmss, series.tas_mps, TAS_POLICY)
    return _tas_sources.qc_record(TAS_CHAIN, TAS_POLICY, probe_time, tas_missing, legacy)


def _sizedist_call(proc_file: Path, out_file: Path, raw_stem: str, timehhmmss, tas,
                   iat_file: str | None, tas_qc: dict | None = None) -> str:
    """The one ``sizeDist`` call S4 makes, with this run's arguments, writing ``out_file``.

    Factored out of :func:`stage4` unchanged (2026-09-23) so the enhancement chain's
    :class:`EnhancedStages` re-runs S4 on an enhanced proc through the very same call -- two
    copies of these arguments would be two things to keep in step, and the enhanced sd is only
    comparable to the faithful one if nothing but the input differs
    (``tests/test_enhanced_chain.py`` asserts the rebuild on an unchanged proc is bit-identical).

    Under :data:`WRITE_PROVENANCE` (v3.1.4 only; the flag is refused under 3.5) the sd file
    also carries ``arrayprobe_*`` global attributes: engine, profile and stage, plus ``tas_qc``
    (this run's :func:`_tas_qc_record`) when the run named a TAS source. Without
    the flag the call passes no provenance keyword at all, so the default call is unchanged.
    Under engine 3.5 ``tas_qc`` is always passed and written as ``arrayprobe_tas_*`` attributes,
    beside the engine attributes that engine already writes unconditionally.
    """
    ddate = f"20{raw_stem[4:10]} {raw_stem[10:16]}"
    partial = out_file
    varargin = (iat_file,) if iat_file else ()
    if ENGINE == "3.5":
        # Engine-3.5 defect correction: on this engine two data-destroying upstream defects
        # are corrected by default
        # (opt out with --protective off): a duplicated floor(t) second moves into the skipped
        # one beside it (fix_time_grid) and a zero-sample-volume second is NaN rather than
        # an infinite concentration (zero_sv_nan). The counts go into the .call stamp.
        v35sd = _v35().module("sizedist")
        t_axis = np.floor(timehhmmss)
        fix_on = v35_time_sv_fix_active()
        n_moved = n_unresolved = 0
        if fix_on:
            t_axis, n_moved = v35sd.fix_time_grid(t_axis)
            n_unresolved = v35sd.count_duplicate_seconds(t_axis)
        # v3.5's own positional signature (sizeDist.m:90): iaThreshType 1 with a file, 0 without
        # (:79,:99-101); the three literals from V35_CALL; `software` required
        # (sizedist.py:748-756).
        out = v35sd.run(
            str(proc_file), str(partial), tas, t_axis, PROBE, D_CHOICE, SA_METHOD,
            np.full_like(tas, PRES_PA), np.full_like(tas, TEMP_C),
            (IA_THRESH_TYPE if IA_THRESH_TYPE is not None else 1 if iat_file else 0),
            V35_CALL.i_create_aspect_ratio, V35_CALL.i_create_bad,
            V35_CALL.i_save_int_arr_sv, PROJECT, ddate, *varargin, software=V35_CALL.software,
            # None on every run that names no case, which is the whole default path: the
            # driver then resolves the ladder through v3.5's own switch exactly as before
            # (the retracted 2D-S bin table; test_v35_probe_cases.py::TestDefaultIsBitIdentical).
            probe_case=_s4_probe_case(),
            stamp_profile=PROFILE.name,
            # The airspeed data-quality record goes into the sd file by default on this
            # engine (None when the run named no TAS source, which writes nothing).
            tas_qc=tas_qc,
            # area_ratio_z (the literal .2 of sizeDist.m:1162) and default_int_arr_thresh (the
            # case's defaultIntArrThresh), each passed only when a user override or the selected
            # regime supplies it (_v35_s4_thresholds); with neither, no keyword is passed and the
            # call is the one every run before the regime reached this engine made.
            **{name: value for name, (value, _src) in _v35_s4_thresholds().items()},
            # tas_max (2DP) / pecan_params (PECAN CIP/PIP), each only when the run sets it.
            **_s4_case_inputs(),
            # The opt-in probe-clock offset, passed only when set (TIME_OFFSET).
            **({} if TIME_OFFSET is None else dict(
                zip(("time_offset_s", "time_offset_evidence", "time_offset_tas_clock"),
                    TIME_OFFSET, strict=True))),
            **({"zero_sv_nan": True} if fix_on else {}),
        )
        if not fix_on:
            return ""
        return time_sv_counts_stamp(int(out.get("_zero_sv_seconds", 0)), n_moved, n_unresolved)
    else:
        # area_ratio_z/default_int_arr_thresh are resolved through _resolve_thresholds()
        # -- regime, then raw override, then (unchanged from every run before 2026-09-17) the
        # hard-coded tree/project/probe lookup -- rather than the bare `tree="production"` this
        # call used to pass with nothing else. When neither a regime nor an override is named the
        # resolved values are numerically identical to what this call always computed
        # (tests/test_regimes.py::TestFidelity), so this is a bit-identical no-op by default.
        resolved = _resolve_thresholds()
        provenance_kw: dict[str, Any] = (
            {"write_provenance": True, "provenance_profile": PROFILE.name,
             "provenance_tas_qc": tas_qc} if WRITE_PROVENANCE else {})
        sizedist.run(
            str(proc_file), str(partial), tas, np.floor(timehhmmss), PROBE, D_CHOICE,
            SA_METHOD, np.full_like(tas, PRES_PA), np.full_like(tas, TEMP_C),
            PROJECT, ddate, *varargin,
            tree=TREE,
            reject=sizedist.RejectThresholds(
                area_ratio_z=resolved.area_ratio_z.value,
                provenance=f"{resolved.area_ratio_z.source}: {resolved.area_ratio_z.justification}",
            ),
            default_int_arr_thresh_override=resolved.default_int_arr_thresh.value,
            # Stock sizeDist.m:1729-1741 substitutes NaN TAS; the ORACLES tree does not. The
            # profile decides (False on both ORACLES profiles, so their products are unchanged).
            nan_tas_substitution=PROFILE.nan_tas_substitution,
            libm_pow=LIBM_POW,
            **provenance_kw,
            **_s4_case_inputs(),
        )
        return ""


#: The count keys an engine-3.5 sd stamp carries when the time/sample-volume fixes ran.
#: They report what the run found, not how it was configured, so :func:`_stamps_equivalent`
#: strips them from both sides before comparing.
TIME_SV_COUNT_KEYS = ("zero_sv_seconds", "time_grid_fix", "time_grid_unresolved")

#: The engine-3.5 sd stamp's on/off marker for the time-grid and zero-sample-volume fixes.
#: Configuration, so it is
#: compared (an absent marker reads as ``off``), where the counts above are stripped.
TIME_SV_FIX_STAMP_KEY = "time_sv_fix="


def v35_time_sv_fix_active() -> bool:
    """Whether S4 applies the time-grid and zero-sample-volume fixes: engine 3.5 and a
    protective mode other than ``off``. Never on engine 3.1.4, whose stamps and arrays stay
    byte-identical."""
    return ENGINE == "3.5" and PROTECTIVE_MODE != "off"


def time_sv_counts_stamp(zero_sv: int, moved: int, unresolved: int) -> str:
    """The stamp fragment for the time-grid and zero-sample-volume fixes, leading space included."""
    return "".join(f" {k}={v}" for k, v in zip(TIME_SV_COUNT_KEYS, (zero_sv, moved, unresolved),
                                                strict=True))


def _strip_time_sv_counts(label: str) -> str:
    """``label`` without its time/sample-volume count tokens (:data:`TIME_SV_COUNT_KEYS`)."""
    return " ".join(t for t in label.split(" ")
                    if not t.startswith(tuple(f"{k}=" for k in TIME_SV_COUNT_KEYS)))


def flight_group(raw_stem: str) -> str:
    """``base<YYMMDD><HHMMSS>`` -> ``<YYMMDD>``, the key several raw files of one
    flight share (S4c design doc: a flight arrives as several time-chunked raw
    files, distinguished only by their embedded start time)."""
    return raw_stem[4:10]


def combine_out_path(raw_stems: list[str], out_dir: Path) -> Path:
    """``base<first file's YYMMDDHHMMSS>.combined.<H/V>.<PROBE>.cdf``, built from the
    flight's first raw file (in filename order) exactly as ``summary_time`` below is.

    Only an engine 3.1.4 run (port validation) appends ``_2``
    (``...<PROBE>_2.cdf``), ``combine_sizedist.m:199``'s own naming, so its products
    keep matching the archived ORACLES products by name. Every other engine writes
    no ``_2``. The name is the only difference."""
    first = sorted(raw_stems)[0]
    return out_dir / _decode_naming().combined_name(f"base{first[4:16]}", ORIENTATION, PROBE,
                                                    ENGINE)


def check_combine_provenance(present, allow_mixed: bool = False,
                             accept_unstamped: bool = False) -> None:
    """Refuse to stitch a flight product out of files built differently.

    THIS IS WHERE THE 2026-08-30 TRAP WOULD HAVE BECOME A NUMBER.  A stale
    ``sd`` file is harmless while it sits on disk; it does damage at the combine,
    which merges a flight's files into the one product a paper is written from.
    Two configurations inside that file are invisible afterwards -- the product
    carries ten variables and no global attributes at all, so it cannot be asked.

    **Mixing is not forbidden, it is made explicit.**  The validated 09/06
    archived product *is* a deliberate mixture (``064403`` under
    ``rej_hollow=1``, the other four under 0 -- a deliberate choice, and the mixed
    combine is the better reproduction, measured).  So the rule is not "never
    mix": it is that a mixture must be asked for, and that the log names what
    went in either way.  ``--allow-mixed-config`` is that request.
    """
    stamps = {stem: read_stamp(f) for stem, f in present}
    missing = sorted(stem for stem, s in stamps.items() if s is None)
    if missing and not accept_unstamped:
        raise UnverifiableProvenance(
            f"{len(missing)} of {len(stamps)} sd file(s) carry no provenance stamp "
            f"({', '.join(missing)}), so this product's configuration would be "
            "unknown; rebuild them, or pass --accept-unstamped")
    # Canonicalized for the dedup, not for the log below: an older v3.1.4 file (built before
    # 2026-09-15, R4s) carries no `engine=` key at all, which would otherwise make it look
    # "mixed" against a freshly-built file that says `engine=3.1.4` for the identical
    # configuration -- see _stamps_equivalent.
    # R4: the port_validation token is dropped too, so a flight with some sd files from before the
    # gate and some from after does not read as MIXED.
    # Engine-3.5 defect correction: the time/sample-volume counts differ file by file and
    # name no configuration.
    distinct = sorted({_strip_plausibility(_strip_time_sv_counts(_strip_port_validation(
                           s if "engine=" in s else f"engine=3.1.4 {s}")))
                       for s in stamps.values() if s is not None})
    if len(distinct) <= 1:
        if distinct:
            log(f"S4c prov  all {len(stamps)} file(s): {distinct[0]}")
        return
    for stem, stamp in sorted(stamps.items()):
        log(f"S4c prov  {stem}: {stamp}")
    if not allow_mixed:
        raise UnverifiableProvenance(
            f"this flight's sd files were built {len(distinct)} different ways "
            "(listed above); combining them puts two configurations in one "
            "product. Rebuild the odd ones out, or pass --allow-mixed-config if "
            "the mixture is what you mean (as the 09/06 archived product is)")
    log(f"S4c prov  MIXED: {len(distinct)} configurations, allowed on the "
        "command line")


def _combine_stamp(sd_files: list[Path]) -> str:
    """The combined product's ``.call`` stamp, for the active engine (the 2026-09-16 cold-start
    usability audit; the v3.5 form gained its inputs' stamps on 2026-09-27).

    Shaped like :data:`arrayprobe_uiops.combine.CALL_STAMP` so the two engines' products read the
    same way: an ``engine=`` key first, then what the combine was, then the inputs. The inputs'
    own configuration is carried through verbatim from their ``sd`` stamps rather than
    re-derived here -- :func:`check_combine_provenance` has already refused a mixture (or logged
    an allowed one), so there is one configuration to name and it is the one the files record.
    An ``--accept-unstamped`` input contributes ``<unstamped>``, said rather than hidden.
    """
    names = ",".join(f.name for f in sd_files)
    # Engine-3.5 defect correction: the per-file time/sample-volume counts are dropped; the
    # on/off marker stays.
    stamps = {_strip_plausibility(_strip_time_sv_counts(read_stamp(f) or "<unstamped>"))
              for f in sd_files}
    if len({_strip_port_validation(s) for s in stamps}) == 1:
        # R4: stamps differing only by the port_validation token are one configuration; take one
        # deterministically (max puts the token-bearing form first) rather than naming a MIXED.
        stamps = {max(stamps)}
    inputs_cfg = (next(iter(stamps)) if len(stamps) == 1
                  else f"MIXED({len(stamps)} configurations, --allow-mixed-config)")
    if ENGINE == "3.5":
        # The combine module's own two lines, verbatim (its ``_write_call_sidecar``), then the
        # inputs' configuration on a third, so a v3.5 product names what it stitched the same
        # way a v3.1.4 one does and S4c can decide its currency from it.
        module = _v35().module("combine")
        return (f"{module.CALL_STAMP}\ninputs={names}\n"
                f"{COMBINE_INPUTS_KEY}({inputs_cfg})")
    return (f"{_engine_prefix()}combine=oracles-fork:combine_sizedist.m "
            f"inputs={names} {COMBINE_INPUTS_KEY}({inputs_cfg})")


#: The key under which a combined product's stamp carries its constituent sd files' stamps.
COMBINE_INPUTS_KEY = "inputs_built_with="


def combine_state(target: Path, sd_files: list[Path]) -> str:
    """``absent`` | ``current`` | ``stale`` | ``outdated`` | ``unstamped`` for a combined product,
    in :func:`output_state`'s vocabulary and through the same comparison.

    ``want`` is the stamp :func:`stage_combine` would write now (:func:`_combine_stamp`): the
    engine, the combine, the files stitched and their own ``sd`` stamps. So a product built by
    the other engine, or from inputs since rebuilt under another configuration, is ``stale``.
    ``outdated`` is :func:`output_state`'s input-newer-than-output rule applied to every
    constituent, because a stamp records configuration, not inputs: an ``sd`` file rewritten
    under the same configuration after the product was written is not in it.
    """
    state = output_state(target, _combine_stamp(sd_files))
    if state != "current":
        return state
    try:
        product_mtime = target.stat().st_mtime
        if any(product_mtime < f.stat().st_mtime for f in sd_files):
            return "outdated"
    except OSError:
        pass  # as in output_state: a failed stat is not evidence either way
    return "current"


def _files_stitched(product: Path) -> int:
    """How many raw files an existing combined product was built from.

    ``files_stitched`` is the dimension the original writes for exactly this,
    and it is the only thing in the file that says whether it covers the whole
    flight. Returns 0 when it cannot be read, so an unreadable or truncated
    product is treated as stale and rebuilt rather than trusted.

    **Failing toward a rebuild is deliberate and stays** -- it is the cheap
    direction to be wrong in, and it is what caught 20170824's partial product.
    What changed on 2026-09-06 is that the failure is no longer *silent*.

    A source audit flagged the bare ``except Exception: return 0`` for marking a
    good product stale on any read error, and the risk is specific rather than
    theoretical: this machine reads the archive over a Box mount, and 20170824's
    first run died with a Windows page-in fault (``0xC0000006``) on a file that
    then re-read end to end in 24 s. A transient mount fault and a genuinely
    truncated product produced *identical* behaviour here -- a silent decision
    to reprocess a flight for about three hours. So the exception is now logged
    with its type and message, which is the one thing that makes the two
    distinguishable in the run log afterwards.
    """
    try:
        with netCDF4.Dataset(os.fspath(product)) as ds:
            dim = ds.dimensions.get("files_stitched")
            if dim is None:
                log(f"  ! {product.name}: no files_stitched dimension -- "
                    "treating as stale")
                return 0
            return len(dim)
    except Exception as e:
        # Still 0, still a rebuild. The log line is the whole fix: an OSError
        # here is probably the mount, and a rebuild triggered by the mount is
        # worth knowing about before it costs three hours again.
        log(f"  ! {product.name}: could not read files_stitched "
            f"({type(e).__name__}: {e}) -- treating as stale and rebuilding. "
            "If this is an OSError on a network or Box mount, the product is "
            "probably fine and the read should be retried instead.")
        return 0


def attributed_sibling_of(target: Path) -> Path:
    """Where ``--attributed`` puts the sibling of ``target`` -- asked of the exporter, not spelled
    out here, so :func:`main`'s "was it written?" check cannot drift from what writes it."""
    from arrayprobe import attributed_export

    return attributed_export.default_output_path(target)


def write_attributed(target: Path, accept_unstamped: bool = False) -> Path | None:
    """``--attributed``: the self-describing sibling, written BESIDE ``target``.

    **The faithful product is not touched.** ``attributed_export.export`` opens it read-only
    and writes a second file; its own tests hash the source either side of the call. That is
    the invariant the whole package rests on -- byte-identity against the archived ORACLES
    products compares attributes too, and ``combine_sizedist.m:202-231`` writes none -- so
    the attributed output can only ever be an addition, never a modification.

    **Opt-in and default OFF.** Not because the file is risky, but because a run that writes
    an extra product nobody asked for is a run whose output directory stops matching what the
    driver said it would write. ``tests/test_run_flight_attributed.py`` asserts both states:
    off, the directory holds exactly the faithful product and its ``.call``; on, one more file.

    A failure here is logged and swallowed rather than failing the flight: the faithful
    product is already written and validated at this point, and losing a finished flight to a
    metadata step would invert the priority the module exists to protect. The return is the
    path written, or ``None`` if it was not.

    **Swallowed is not unreported** (2026-09-21). Until that date the exception died here and
    :func:`main` still returned 0, so a run that was asked for the sibling and produced none
    reported success -- the same family as the quickstart that wrote an empty product for nine
    days. ``main`` now checks :func:`attributed_sibling_of` on the filesystem and returns 1, the
    value every other "asked for a file, did not get it" case returns. The exception is still
    not raised: the flight survives, the exit status tells the truth.
    """
    from arrayprobe import attributed_export

    try:
        written = attributed_export.export(target, accept_unstamped=accept_unstamped,
                                           analysis_ready=ATTRIBUTED_ANALYSIS_READY)
    except Exception as exc:  # noqa: BLE001 -- see the docstring: never lose the flight
        log(f"S4c ATTRIBUTED skipped for {target.name}: {type(exc).__name__}: {exc}")
        return None
    log(f"S4c attributed {written.name}")
    return written


def stage_combine(raw_stems: list[str], out_dir: Path, allow_mixed: bool = False,
                  accept_unstamped: bool = False,
                  diode_corrected: bool = False, borrowed: bool = False,
                  attributed: bool = False) -> Path | None:
    """Every ``sd.*`` file for one flight -> the one product a paper is written
    from. ``:31,:37`` glob a directory in alphabetical order; passing an
    explicit list sorted by raw stem reproduces that order without depending
    on directory iteration (the combine design's first decision, and ``test_combine.py``
    pins the product-of-record's own order matches alphabetical globbing).

    Skips a flight with zero completed ``sd`` files rather than raising --
    a partial run (some of a flight's raw files not through S4 yet) is normal
    mid-campaign, not an error; it just has nothing to combine yet.

    ``borrowed`` is engine-3.5-only (``--borrowed-combine`` / ``[combine].borrowed``): under
    engine 3.5 the ORACLES fork's ``combine_sizedist.m`` is BORROWED and opt-in
    (``arrayprobe_uiops.combine``); that module writes its own labelled ``.call``
    sidecar beside ``partial``, moved to the product's name below rather than written twice.
    """
    ordered = sorted(raw_stems)
    # Through sd_path, so a stem with a stuck-diode override stitches its
    # `.diodecorrected` sd under --diode-corrected. Until 2026-09-06 this
    # built the plain name for every stem, so the flag reached S3 and S4 and
    # not the combine: the 2016-09-10 review run re-processed both masked
    # files correctly and then stitched the uncorrected ones, reproducing the
    # uncorrected product's 12 differing cells exactly, while its own
    # provenance line said shadow_diode=none. The fourth flag of the day to
    # go missing from one link of the chain.
    sd_files = [sd_path(stem, out_dir, _diodes_for(stem, diode_corrected)) for stem in ordered]
    present = [(stem, f) for stem, f in zip(ordered, sd_files, strict=True) if f.exists()]
    if not present:
        return None
    check_combine_provenance(present, allow_mixed, accept_unstamped)
    target = combine_out_path(ordered, out_dir)
    if target.exists():
        # Existence is NOT enough. A product left behind by a run in which some
        # of the flight's files had failed stitches only the files that got
        # through, and skipping on existence lets that partial product block
        # its own replacement -- silently, and forever.
        #
        # This is not hypothetical. 20170824's first run lost one of two files
        # to a page-in fault, wrote a one-file product, and reported 100.0000 %
        # against the reference; the figure was real but covered only what that
        # one file spanned. The relaunch reprocessed the missing file correctly
        # and then skipped the combine, because the bad product was still on
        # disk. The flight looked finished and was not.
        #
        # Nor is the count. A v3.5 run then a v3.1.4 run into one directory rebuilt every sd
        # file under the second engine, stitched the same number of them, and kept the first
        # engine's product -- so the stamp decides too, as it does for every other stage.
        stitched = _files_stitched(target)
        state = combine_state(target, [f for _, f in present])
        if stitched == len(present) and state == "current":
            log(f"S4c skip  {target.name} exists ({stitched} file(s), current)")
            # The sibling is written on the skip path too: a re-run with --attributed on a
            # directory whose combine is already current must still produce the attributed
            # file, or the flag would silently do nothing on exactly the run a user reaches
            # for it (the product is finished; that is when you go to hand it over).
            if attributed:
                write_attributed(target, accept_unstamped)
            return target
        if stitched != len(present):
            log(f"S4c STALE {target.name} stitched {stitched} file(s) but "
                f"{len(present)} are ready -- rebuilding")
        elif state == "outdated":
            log(f"S4c STALE {target.name} is older than an sd file it stitches -- rebuilding")
        else:
            log(f"S4c STALE {target.name} ({state}): built with {read_stamp(target)}, "
                f"want {_combine_stamp([f for _, f in present])} -- rebuilding")
        # Asked before the old product goes and before anything is written: a refusal must
        # neither destroy the only copy nor leave a product the next run reads as current.
        tas_qc = _combined_tas_qc(target, [f for _, f in present])
        target.unlink()
    else:
        tas_qc = _combined_tas_qc(target, [f for _, f in present])
    if len(present) < len(ordered):
        missing = [stem for stem in ordered if stem not in {p[0] for p in present}]
        log(f"S4c PARTIAL {target.name}: {len(present)}/{len(ordered)} files ready "
            f"(missing S4 for {', '.join(missing)})")
    log(f"S4c start {target.name} ({len(present)} file(s))")
    t0 = time.time()
    partial = target.with_name(target.name + ".partial")
    partial.unlink(missing_ok=True)
    _combine_call([f for _, f in present], partial, ordered[0], borrowed)
    if ENGINE == "3.5":
        # The ORACLES fork's combine over v3.5 sd files, borrowed and opt-in; the
        # module writes its own labelled .call beside `partial`, moved to the product's name below.
        os.replace(partial, target)
        os.replace(call_path(partial), call_path(target))
        # The module's own lines plus the inputs' stamps (:func:`_combine_stamp`), so the next
        # run can tell whether this product still matches what it stitched.
        write_stamp(target, _combine_stamp([f for _, f in present]))
    else:
        os.replace(partial, target)
        # 2026-09-16 cold-start usability audit, 2.6. Until this line the v3.1.4 combine wrote
        # NO sidecar, while the v3.5 branch above did -- so on the engine that carries the
        # layer-1 validation claim, the one file a paper is written from was the one file with
        # no record of how it was made, contradicting README's "every stage writes a .call
        # sidecar beside its output". The sidecar is a file of our own beside the product, so
        # it changes not one byte of the product itself (`call_path`'s own docstring: "beside
        # it, never inside it"), and combine_sizedist.m writes no attributes to put it in.
        # The inputs' own stamp is named because check_combine_provenance above has already
        # proved the inputs agree -- `distinct[0]` is that agreed configuration.
        write_stamp(target, _combine_stamp([f for _, f in present]))
    _store_tas_qc(target, tas_qc)
    log(f"S4c done  {target.name} ({time.time() - t0:.0f} s)")
    if attributed:
        write_attributed(target, accept_unstamped)
    return target



def _write_combined_tas_qc(product: Path, sd_files: list[Path]) -> None:
    """``<combined>.tasqc.json``: the constituent sd records merged by
    :func:`tas_sources.merge_qc_records`, parts named in stitch order. None is written when no
    constituent has a record (the legacy probe-only path), and a record left by an earlier
    combine is removed so it cannot describe this product. A part without a record beside parts
    with one is refused: a merged count silently missing a file's seconds would understate the
    defaulted fraction."""
    _store_tas_qc(product, _combined_tas_qc(product, sd_files))


def _combined_tas_qc(product: Path, sd_files: list[Path]) -> dict | None:
    """The merged record :func:`_write_combined_tas_qc` writes, or None; raises ``SystemExit``
    on a part without a record beside parts with one. :func:`stage_combine` asks this BEFORE it
    combines, so a refused combine leaves no product and ``.call`` for the next run to read as
    current and skip."""
    recs = [(f.name, _tas_sources.read_qc_sidecar(f)) for f in sd_files]
    have = [(name, rec) for name, rec in recs if rec is not None]
    if not have:
        return None
    if len(have) != len(recs):
        lacking = [name for name, rec in recs if rec is None]
        raise SystemExit(f"S4c {product.name}: TAS QC record missing for {', '.join(lacking)} "
                         f"while other parts have one; re-run S4 on those files")
    return _tas_sources.merge_qc_records(have)

def _combine_call(sd_files: list[Path], partial: Path, first_stem: str, borrowed: bool) -> None:
    """The one combine call S4c makes, writing ``partial`` (and, under engine 3.5, the combine
    module's own ``.call`` beside it). Factored out of :func:`stage_combine` unchanged so
    the enhancement chain combines its enhanced sd files through the same call."""
    summary_time = (f"{first_stem[4:6]}_{first_stem[6:8]}_{first_stem[8:10]}_"
                    f"{first_stem[10:12]}_{first_stem[12:14]}_{first_stem[14:16]}")
    flight_date = f"20{first_stem[4:10]}"
    if ENGINE == "3.5":
        _v35().module("combine").combine_sizedist(
            list(sd_files), str(partial), flight_date=flight_date,
            summary_time=summary_time, borrowed_combine=borrowed)
    else:
        combine.combine_sizedist(list(sd_files), str(partial),
                                 flight_date=flight_date, summary_time=summary_time)


def partition_round_robin(files: list[Path], n_jobs: int) -> list[list[Path]]:
    """Split ``files`` across ``n_jobs`` workers, round-robin.

    Round-robin rather than contiguous chunks: raw files are usually listed in
    date order, and consecutive files from the same flight tend to be similar
    sizes, so a contiguous split would cluster the biggest files onto whichever
    worker gets that stretch. Round-robin spreads them out without the
    complexity of bin-packing by actual size, which is more precision than
    this needs. Empty groups (more workers than files) are dropped.
    """
    groups: list[list[Path]] = [[] for _ in range(n_jobs)]
    for i, f in enumerate(files):
        groups[i % n_jobs].append(f)
    return [g for g in groups if g]


def _spawn_worker(group: list[Path], args, log_path: Path):
    """One subprocess: this same script, re-invoked on a subset of files.

    Re-execs rather than using a thread/process pool internally, because the
    existing per-file log format (plain timestamped lines, ``=== file ===``
    section headers) is what ``watch_run.py`` already parses -- a worker
    covering several files just gets several sections in its one log, exactly
    as a single-job run covering several files already does today.
    """
    # "c" (combine) is never delegated to a worker: it operates on a whole
    # flight's files, which round-robin can split across several workers, so
    # only the parent (which sees the full file list) may run it -- see main().
    worker_stages = args.stages.replace("c", "")
    cmd = [sys.executable, str(Path(__file__).resolve()),
           "--out", str(args.out), "--stages", worker_stages,
           "--chunks", str(args.chunks),
           # --worker-stall-min bounds THIS worker's own nested --chunks wait
           # and, in run_parallel, the parent's wait on this worker; both
           # levels read the one value (pair G, 2026-09-13; P10 had left it
           # at the 30-min default inside --jobs workers, a documented gap).
           "--worker-stall-min", str(args.worker_stall_min),
           # --s2-jobs was missing from this list until 2026-09-06: under
           # --jobs > 1 every worker decoded serially while the parent's log
           # said nothing, the same silent-drop shape as --diode-corrected
           # below. Found by reading the list before launching the review
           # run, not by a test -- so it now has one.
           "--s2-jobs", str(args.s2_jobs),
           *((["--iat-source", args.iat_source]) if getattr(args, "iat_source", None)
             else ["--iat-file", args.iat_file]),
           # --preset was missing entirely until 2026-09-10 -- the fourth flag
           # to go missing from this list (after --diode-corrected,
           # --accept-unstamped, --s2-jobs), and the most severe: every worker
           # silently fell back to the argparse default campaign whenever the
           # parent was run with a non-default --preset, which is a wrong
           # PROJECT/PROBE/d_choice/sa_method combination processed without
           # any error. Always forwarded, unconditionally, because --preset
           # always has a value (the default itself if nothing else).
           "--preset", args.preset]
    if getattr(args, "jit", False):  # a hand-built args (tests) may predate --jit
        cmd += ["--jit"]
    if getattr(args, "libm_pow", False):
        cmd += ["--libm-pow"]
    if getattr(args, "port_validation", False):
        cmd += ["--port-validation"]
    if getattr(args, "stray_pixel", None) is not None:
        # Stray-pixel rule: the parent's resolved value (main() writes it back to args), so a
        # --jobs worker never re-resolves from its own default.
        cmd += ["--stray-pixel", str(args.stray_pixel)]
    if getattr(args, "ncar_2dc_timing", None) is not None:
        # NCAR 2DC timing conversion: the parent's resolved value, as for --stray-pixel.
        cmd += ["--ncar-2dc-timing", str(args.ncar_2dc_timing)]
    if getattr(args, "resume_chunks", False):
        cmd += ["--resume-chunks"]
    if getattr(args, "protective", None) is not None:
        # A worker stamps its own proc/sd, and the stamp carries the protective fragment.
        cmd += ["--protective", args.protective]
    # The protective set is applied once, by the parent, after every worker --
    # the same reason --enhancements is not forwarded (below).
    cmd += ["--_protective-worker"]
    # --enhancements is DELIBERATELY not in this list, and this comment is here because four
    # flags have already gone missing from it by accident (see --preset above). Enhancements
    # act on products that already exist, so the parent applies them to every stem after
    # every worker has finished -- the same reason "c" is never delegated. A worker that
    # applied them too would race the parent onto the same <stem>.enh.*.nc.
    # --enhancements is DELIBERATELY not in this list, and this comment is here because four
    # flags have already gone missing from it by accident (see --preset above). Enhancements
    # act on products that already exist, so the parent applies them to every stem after
    # every worker has finished -- the same reason "c" is never delegated. A worker that
    # applied them too would race the parent onto the same <stem>.enh.*.nc.
    if args.tas_file is not None:
        # Forwarded like --config: a worker without it would refuse (exit 2) the
        # same STOCK_V314 run the parent's preflight had just accepted.
        cmd += ["--tas-file", str(args.tas_file)]
    # Airspeed policy: the same reason --tas-file is forwarded above -- a worker without these
    # would either refuse the run the parent's preflight already accepted, or resolve a
    # DIFFERENT chain (module defaults) for the files it was handed.
    if getattr(args, "tas_source", None) is not None:
        cmd += ["--tas-source", args.tas_source]
    if getattr(args, "tas_ratio", "off") == "on":
        cmd += ["--tas-ratio", "on"]
    if getattr(args, "tas_grid", None) is not None:
        # The grid main() resolved, whichever it is. A worker left to resolve its own would
        # size its files on the probe grid under a parent's `regular`, and -- on a profile
        # whose own default is `regular` -- on the regular grid under a parent's explicit
        # `--tas-grid probe`, stamping tas_grid=regular for a run that opted out of it.
        cmd += ["--tas-grid", str(args.tas_grid)]
    _hks = getattr(args, "tas_from_probe", None)
    for _hk in _hks if isinstance(_hks, (list, tuple)) else ():
        cmd += ["--tas-from-probe", str(_hk)]
    for _dir in getattr(args, "tas_search", None) or ():
        cmd += ["--tas-search", str(_dir)]
    if getattr(args, "tas_cutoff_mps", None) is not None:
        cmd += ["--tas-cutoff-mps", repr(float(args.tas_cutoff_mps))]
    if getattr(args, "tas_default_mps", None) is not None:
        cmd += ["--tas-default-mps", repr(float(args.tas_default_mps))]
    # --engine always has a value by the time a worker is spawned (it is required since
    # 2026-09-23, and main() refuses a run without it), so it is always forwarded: a worker that
    # fell back to some default under a v3.5 parent would stamp v3.1.4 output engine=3.5.
    # Attribute access, not getattr with a default: a fallback here would stamp a worker's output
    # engine=3.1.4 whatever the parent ran, so a caller whose args lack --engine must raise
    # (tests/test_run_flight_engine_never_defaults.py).
    cmd += ["--engine", args.engine]
    if getattr(args, "profile", None) is not None:
        # Forwarded from the day the flag existed (2026-09-20), because the five flags that
        # went missing from this list before it each produced silent wrong output, and this
        # one would too: a worker without it falls back to the argparse default profile
        # (oracles-production) and stamps its proc/sd files with a profile the parent never
        # ran. Under --engine 3.5 it would not even fail loudly in every case -- the worker's
        # own is_v35_flavoured gate would refuse, so the parent would report N failed workers
        # for a run the parent itself had accepted. tests/test_run_flight_profile_flag.py
        # asserts the forward.
        cmd += ["--profile", str(args.profile)]
    if args.presets is not None:
        # Must travel with --preset: a campaign declared in a --presets file
        # is registered before the *worker's own* parser fixes --preset's
        # `choices`, so without this the worker's parser would reject a
        # custom campaign name as unknown before main() ever runs.
        cmd += ["--presets", str(args.presets)]
    if args.config is not None:
        # Carries [fidelity].profile_module too (config.py's own
        # load_config()), which is what makes a registered-but-unshipped
        # profile survive into a worker process at all -- see that module's
        # docstring for the incident this closes.
        cmd += ["--config", str(args.config)]
    if args.allow_mixed_config:
        cmd.append("--allow-mixed-config")
    if getattr(args, "accept_implausible", False):
        # Plausibility gate: a worker without it would refuse the sd the parent's operator
        # accepted, and
        # stamp its sds without the override marker.
        cmd.append("--accept-implausible")
    if getattr(args, "accept_preset_mismatch", False):
        # A worker runs its own preflight; without the flag it would refuse the file the
        # parent's operator accepted.
        cmd.append("--accept-preset-mismatch")
    if args.accept_unstamped:
        # Forwarded for the same reason --diode-corrected is, below: a worker
        # that did not get it would refuse the files the parent's preflight had
        # already accepted, and the run would fail per-file with a message the
        # operator had already answered.
        cmd.append("--accept-unstamped")
    if getattr(args, "accept_flagged", False):
        cmd.append("--accept-flagged")
    if args.diode_corrected:
        # Was silently dropped here until 2026-08-27: a worker subprocess got
        # none of the flags this process didn't explicitly list, so
        # `--diode-corrected --jobs N` quietly produced ordinary uncorrected
        # output with no error -- exactly the kind of silent-wrong-output bug
        # this project's fidelity doctrine treats as serious. Caught by a
        # release-readiness audit, not by use.
        cmd.append("--diode-corrected")
    # The three regime threshold flags, forwarded 2026-09-17. They were missing from this list
    # for the whole of the day they existed: `--regime ice --jobs 4` would have run the parent's
    # regime nowhere, every worker silently falling back to the stock ORACLES-tuned pair and
    # stamping its own `sd` files with it -- the fifth flag to go missing here, and the same
    # silent-wrong-output shape as --preset's (above). A config file escaped this because
    # --config is forwarded; the command-line form did not.
    if getattr(args, "regime", None) is not None:
        cmd += ["--regime", args.regime]
    # The retracted 2D-S bin table: both halves are load-bearing. The NAME alone would resolve
    # nowhere in a worker:
    # a probe case lives in the registering process's dict only, so the MODULE has to travel with
    # it, exactly as PROFILE_MODULE does for a registered profile (see PROBE_CASE_MODULE's own
    # docstring). Forwarded here at the same time the flags were added rather than discovered
    # missing later, which is what happened to --preset, --diode-corrected and the three regime
    # threshold flags above.
    if getattr(args, "probe_case", None) is not None:
        cmd += ["--probe-case", args.probe_case]
    if getattr(args, "probe_case_module", None) is not None:
        from arrayprobe.selector import canonical_module
        cmd += ["--probe-case-module", canonical_module(args.probe_case_module)]
    if getattr(args, "area_ratio_z", None) is not None:
        cmd += ["--area-ratio-z", repr(float(args.area_ratio_z))]
    if getattr(args, "default_int_arr_thresh", None) is not None:
        cmd += ["--default-int-arr-thresh", repr(float(args.default_int_arr_thresh))]
    # S4's two case inputs; a config-sourced value travels with --config.
    if getattr(args, "tas_max", None) is not None:
        cmd += ["--tas-max", repr(float(args.tas_max))]
    if getattr(args, "pecan_params", None) is not None:
        cmd += ["--pecan-params", str(args.pecan_params)]
    # The probe-clock offset: S4 runs in the worker, so a worker without it would build and
    # stamp an unshifted sd under a parent that asked for the shift.
    if getattr(args, "time_offset_s", None) is not None:
        cmd += ["--time-offset-s", repr(float(args.time_offset_s)),
                "--time-offset-evidence", str(args.time_offset_evidence),
                "--time-offset-tas-clock", str(args.time_offset_tas_clock)]
    # The parent has already passed the confirmation gate -- a worker cannot reach
    # run_parallel otherwise -- and a worker's stdin is a pipe, so it could never be asked.
    # Carrying the parent's assent is the only correct answer; making the worker ask would
    # deadlock the run, and letting it decide for itself would re-open the gate the parent shut.
    cmd.append("--yes")
    cmd += [str(f) for f in group]
    log_f = open(log_path, "w")
    proc = subprocess.Popen(cmd, stdout=log_f, stderr=subprocess.STDOUT)
    return proc, log_f


def run_parallel(args, files: list[Path]) -> int:
    """Dispatch ``files`` across ``args.jobs`` worker subprocesses and wait.

    Disk is not re-derived here: the preflight the caller already ran covers
    the WORST CASE for the whole file list, and that figure does not change
    with how many of them happen to run at once -- nothing in this runner
    frees a file's decode until its own S4 finishes, sequential or not, so
    the peak disk footprint is the same either way. ``--jobs`` only changes
    wall-clock time, never the disk bound.
    """
    n_jobs = min(args.jobs, len(files))
    groups = partition_round_robin(files, n_jobs)
    log(f"JOBS      {n_jobs} worker(s) for {len(files)} file(s)")

    workers = []
    for k, group in enumerate(groups, start=1):
        # Keyed on the worker's own first file, not just its index.
        #
        # It used to be `run_job{k}.log`, which is fine for one invocation and
        # actively harmful for two: running a second flight concurrently -- one
        # invocation per flight, because the combine stitches whatever file list
        # it is given -- had both invocations opening the SAME run_job1.log and
        # run_job2.log. On 2026-09-03 two flights launched three seconds apart,
        # and the second truncated the first's job logs. The first flight then
        # failed with its chunk 3 never starting on either file, and the
        # traceback that would have said why had been overwritten. Diagnosis had
        # to proceed from process CPU samples instead.
        #
        # The stem makes the path unique per file, so concurrent invocations
        # cannot collide and a failure keeps its own evidence.
        log_path = args.out / f"run_job{k}_{group[0].stem}.log"
        names = ", ".join(f.name for f in group)
        log(f"  worker {k}: {names} -> {log_path.name}")
        proc, log_f = _spawn_worker(group, args, log_path)
        workers.append((k, proc, log_f, log_path))

    # The follow-along viewer is not part of this package; name it only where it exists,
    # so an installed or public copy does not print a command that cannot run.
    watch = Path(__file__).resolve().parents[3] / "scripts" / "watch_run.py"
    if watch.is_file():
        log(f"  follow with: .venv/Scripts/python.exe scripts/{watch.name} --compact "
            + " ".join(str(w[3]) for w in workers))
    else:
        log("  follow the worker logs: " + " ".join(str(w[3]) for w in workers))

    held = {k: ", ".join(f.name for f in group)
            for k, group in enumerate(groups, start=1)}
    # Bounded, fail-closed wait -- the same helper stage3's --chunks path has
    # used since P10 (2026-09-13); this loop was a bare proc.wait() until pair
    # G the same day. Siblings are NOT killed when one worker fails: each
    # holds different files, and one bad file must not take the others down
    # (main()'s per-file catch-all makes the same choice). A --jobs worker's
    # own log is silent for its whole nested chunked S3 (measured: up to 264
    # min), so its liveness here is the heartbeat its nested _await_workers
    # writes -- see _heartbeat_interval.
    try:
        _await_workers([(f"worker {k}", proc, log_f, log_path)
                        for k, proc, log_f, log_path in workers],
                       stall_s=args.worker_stall_min * 60, what="JOBS",
                       on_fail_kill_all=False,
                       held={f"worker {k}": files for k, files in held.items()})
    except RuntimeError as exc:
        log(f"JOBS      {exc}")
        failed = [k for k, proc, _log_f, _log_path in workers if proc.poll() != 0]
        for k in failed:
            log(f"  worker {k} held: {held[k]} -- these files are not "
                "done; rerun them")
        log(f"JOBS      {len(failed)} of {n_jobs} worker(s) failed: {failed}")
        return 1
    for k, _proc, _log_f, _log_path in workers:
        log(f"  worker {k} done")
    log("JOBS      all workers done")
    return 0


def _apply_profile_flag(name: str) -> int:
    """``--profile <name>``: switch :data:`PROFILE` for the rest of this process.

    **Why this exists, and why it is not a new kind of thing.** Until 2026-09-20 a
    profile could be named in a ``--config`` file and nowhere else, so
    ``--engine 3.5`` -- the project's *default* engine -- was unreachable from any
    command line: it requires a v3.5-citing profile (``is_v35_flavoured``), the only
    demo preset runs under the v3.1.4-era default, and no flag could change it. The
    published quickstart therefore demonstrated the non-default engine, and the only
    route to the default one was hand-writing TOML
    (found by the cold-user end-to-end test, 2026-09-21).

    **Why a flag rather than a v3.5 demo preset.** A :class:`CampaignPreset` carries
    no profile field, deliberately -- presets and profiles answer different questions
    (which campaign's numbers vs. which MATLAB variant's behaviour) -- so a
    ``DEMO_2DS_H_V35`` preset would have run under ``oracles-production`` exactly like
    the existing one and hit the same refusal. Giving it one would add a required
    field to :data:`PRESET_FIELDS`, which every ``--presets`` file in the world must
    then state, to express something a preset is documented not to express.

    **It selects; it cannot describe.** The name is resolved through
    ``arrayprobe.config.PROFILES`` -- the same mapping and the same spellings a
    config file gets, aliases included -- so there is exactly one name space for
    profiles and a flag cannot reach a profile a file could not. Decision #10 bounds
    what a *description* may do, not which file a *selection* is written in; this
    driver already hands ``PROFILE.name`` to every ``--chunks`` worker on a command
    line (:func:`stage3`'s ``cmd_base``).

    Returns 0, or 2 with a logged reason -- 2 because nothing has run yet: this is a
    refusal of the command line, not a failed flight.
    """
    global PROFILE
    from arrayprobe.config import PROFILES as SELECTABLE

    try:
        chosen = SELECTABLE[name]
    except KeyError:
        log(f"--profile {name!r} is not a profile this package ships or has registered. "
            f"Known: {sorted(SELECTABLE)} -- each profile answers to its hyphenated name and "
            "to its Python constant's spelling. A fork's own variant is reachable here only "
            "once something has imported the module that calls register_profile() for it; "
            "--config with [fidelity].profile_module guarantees that in every process, "
            "including the ones --chunks/--jobs re-exec")
        return 2
    if chosen is not PROFILE:
        log(f"profile   {PROFILE.name} -> {chosen.name} (--profile) -- every stage call and "
            "provenance stamp for the rest of this run uses it")
    PROFILE = chosen
    return 0


def _fold_run_table(cfg, args, given):
    """Fold ``[run]``'s preset/probe/out/stages/tas_file into a direct ``--config`` run.

    ``arrayprobe run`` turns these keys into flags; until 2026-09-26 a direct
    ``scripts/run_flight.py --config`` read only ``[run].engine`` and dropped the rest without a
    word, so the file's preset could differ from the one that ran, its ``out`` and ``stages``
    were replaced by the argparse defaults, and a v3.5 run refused for want of a TAS file while
    telling the user to "set [run].tas_file" -- which the file already did.

    The preset and probe are refused on disagreement, as the engine is: each is a campaign
    choice the command line must restate, never override. ``out``, ``stages`` and ``tas_file``
    fold in when the flag is absent (paths relative to the config file, as ``arrayprobe run``
    resolves them), and the command line wins when it is present. ``raw`` and
    ``tas_from_probe`` stay ``arrayprobe run``'s: the direct run's files are its positional
    arguments, and saying so is logged. Returns ``None`` on a refusal.
    """
    def flag_given(flag):
        return any(t == flag or t.startswith(flag + "=") for t in given)

    run = cfg.run
    base = Path(cfg.source).resolve().parent
    if "preset" in run and PRESETS.get(str(run["preset"])) is not PRESETS.get(str(args.preset)):
        log(f"config    [run].preset = {run['preset']!r} but this run is --preset {args.preset}; "
            f"arrayprobe run passes the file's preset, a direct run must say "
            f"--preset {run['preset']}")
        return None
    if "probe" in run and run["probe"] != ACTIVE.probe:
        log(f"config    [run].probe = {run['probe']!r} but preset {ACTIVE.name!r} processes "
            f"the {ACTIVE.probe}; name a preset for the {run['probe']}")
        return None
    for key, flag in (("out", "--out"), ("stages", "--stages"), ("tas_file", "--tas-file")):
        if key not in run:
            continue
        value = run[key] if key == "stages" else (base / str(run[key])).resolve()
        if flag_given(flag) or (key == "tas_file" and flag_given("--tas-source")):
            current = getattr(args, key)
            same = (str(current) == value if key == "stages" else
                    current is not None and Path(current).resolve() == value)
            if not same:      # `arrayprobe run` passes the file's own value: nothing to say
                winner = flag if flag_given(flag) else "--tas-source"
                log(f"config    [run].{key} given but the command line's {winner} wins")
            continue
        log(f"config    {key}: {str(getattr(args, key))!r} -> {str(value)!r} ([run].{key})")
        setattr(args, key, value)
    for key in ("raw", "tas_from_probe"):
        if key in run:
            log(f"config    [run].{key} is read by `arrayprobe run` only; this direct run "
                "uses the files on its command line")
    return args


def _fold_enhanced_attributed(cfg, args, enabled):
    """``[outputs].enhanced_attributed``: the file selects the enhanced combined and its
    attributed export, which a run writes when it applies enhancements with stage ``c``.

    ``true`` turns ``--enhancements`` on, and is refused -- ``None``, so :func:`main` returns 2
    before any stage runs -- when the selection could not be honoured: the ``[enhancements]``
    table switches nothing on, the run's stages leave out ``c`` (no combine, so nothing to
    export), or ``arrayprobe_enhancements`` is not installed. ``false`` is an explicit opt-out
    that overrides nothing the command line asked for: ``--enhancements`` given wins, logged.
    An absent key leaves ``args`` exactly as given. Returns ``args`` otherwise.
    """
    if getattr(args, "protective_worker", False):
        # A --jobs worker: only the parent applies enhancements (see _spawn_worker), and a
        # worker's stages never include 'c', so the selection is the parent's to honour.
        return args
    want = cfg.outputs.get("enhanced_attributed")
    given = getattr(args, "enhancements", False)
    if want is False and given:
        log("config    [outputs].enhanced_attributed = false, but --enhancements was given: "
            "the command line wins")
    if not want:
        return args
    problems = []
    if not enabled:
        problems.append("the [enhancements] table switches no enhancement on, so there is "
                        "nothing to apply")
    if "c" not in str(getattr(args, "stages", "")):
        problems.append(f"the run's stages ({getattr(args, 'stages', '')!r}) leave out 'c', so "
                        "no enhanced combined is written to export")
    from importlib.util import find_spec
    if find_spec("arrayprobe_enhancements") is None:
        problems.append(_ENHANCEMENTS_MISSING)
    if problems:
        for p in problems:
            log(f"config    [outputs].enhanced_attributed = true cannot be honoured: {p}")
        log("config    refused before any stage ran. Nothing was run")
        return None
    if not given:
        log("config    [outputs].enhanced_attributed = true -> --enhancements")
        args.enhancements = True
    return args


HVPS_IAT_MISSING = "HVPS_intArrThreshold_MISSING.V_1.cdf"


def _resolve_iat_source(args, argv) -> str | None:
    """Resolve ``--iat-source flight-table`` into ``args.iat_file``; a refusal string or None.

    Engine 3.1.4 and the HVPS only. ``none_default`` names a threshold file that does not
    exist, so ``sizeDist.m:70`` falls back to the per-probe default -- never an omitted
    argument, which skips the whole shattering block (``sizeDist.m:866``), a different call.
    """
    global IAT_SOURCE
    if getattr(args, "iat_source", None) is None:
        return None
    try:
        from arrayprobe import hvps_flight_config as hfc
    except ImportError:
        return ("--iat-source flight-table is not available in this release: it needs "
                "arrayprobe.hvps_flight_config, which this distribution does not ship; "
                "pass --iat-file instead")
    if any(a == "--iat-file" or a.startswith("--iat-file=") for a in (argv or ())):
        return "--iat-source and --iat-file are mutually exclusive"
    if args.engine != "3.1.4":
        return f"--iat-source flight-table is engine 3.1.4 only (this run: {args.engine})"
    if ACTIVE.probe != "HVPS":
        return f"--iat-source flight-table is HVPS only (this preset's probe: {ACTIVE.probe})"
    rows = []
    for raw in args.raw:
        try:
            rows.append((Path(raw).stem.split(".")[0], hfc.resolve(Path(raw).stem.split(".")[0])))
        except hfc.UnknownHvpsFlightError as exc:
            return str(exc.args[0])
    sources = {row.iat_source for _stem, row in rows}
    if len(sources) != 1 or len({stem for stem, _row in rows}) != 1:
        return "--iat-source flight-table resolves one flight per run; run each flight separately"
    stem, row = rows[0]
    if row.iat_source == "none_default":
        args.iat_file = HVPS_IAT_MISSING
    else:
        args.iat_file = str(Path(args.out) / f"HVPS_intArrThreshold_{stem}.V_1.cdf")
        if not Path(args.iat_file).is_file():
            # Never fall through to sizeDist.m:70's 'NONE' path: that is the other source.
            return (f"{stem} is port_fit_blocks5 but its threshold file {args.iat_file} does not "
                    f"exist; write it first with `arrayprobe intarr-threshold <{stem} proc file> "
                    f"{args.iat_file} --probe HVPS --flight-date 20{stem[4:10]} --blocks 5`")
    IAT_SOURCE = row.iat_source
    log(f"iat-source flight-table: {stem} -> {row.iat_source} (iat-file {args.iat_file!r})")
    return None


def _apply_config(args, parser, argv):
    """Fold a ``--config`` TOML into ``args``; the command line always wins.

    Returns the mutated ``args``, or ``None`` if ``[run].engine`` disagrees with ``--engine`` --
    the direct-invocation half of the same guard ``arrayprobe.cli._run`` applies for
    ``--uiops-version`` (2026-09-13): a config file names the engine and a caller must say so too,
    rather than a v3.5 config silently running under whatever ``--engine`` happened to default to.

    The loader (``arrayprobe.config``) can only *select*: it refuses a raw fidelity threshold
    anywhere in the file, so the worst a config can do here is name a different profile, a
    different shattering-threshold argument, or a diode mask. Which of those actually took
    effect is logged, because a run steered by an invisible setting is the failure mode the
    config file exists to avoid -- not one it is allowed to introduce.

    **Any registered profile runs (since 2026-09-10).** Until this date the
    only way past this point was ``cfg.profile is ORACLES_PRODUCTION`` -- everything else
    raised ``SystemExit(2)`` with "use arrayprobe.cli or the library instead", which is exactly
    why A10's whole-file measurement on a non-production profile was never free: the one driver
    fifteen validated flights came out of could not run it. ``PROFILE`` (below) is now a
    genuine run-time switch, not a fixed constant -- every stage call site reads it live
    (:func:`stage2`, :func:`_imgproc_sm_chunk`, :func:`stage3`'s chunk merge), and the four
    provenance-label functions resolve it at call time rather than at their own definition time,
    the same trap :func:`image_call_label`'s ``channels`` parameter already had to avoid.
    **What did NOT change**: every default -- no ``--config``, no ``--preset`` naming anything
    else -- still resolves to ``ORACLES_PRODUCTION``, so the fifteen already-validated flights'
    behaviour is provably unchanged (``tests/test_run_flight_any_profile.py`` re-runs a real
    validated flight through the unmodified default path and diffs it byte-for-byte against a
    pre-change golden). A campaign preset (``CampaignPreset``/``--preset``/``--presets``) still
    carries no profile field, deliberately: presets and profiles answer different questions
    (which campaign's numbers vs. which MATLAB variant's behaviour), and ``--config`` remains
    the one place a profile is named, exactly as ``docs/06-configuration.md``
    already documents.
    """
    from arrayprobe.config import load_config

    global PROFILE, PROFILE_MODULE, REGIME_NAME, AREA_RATIO_Z_OVERRIDE, DEFAULT_IAT_OVERRIDE
    global AREA_RATIO_Z_SOURCE, DEFAULT_IAT_SOURCE, TAS_MAX, PECAN_PARAMS
    global CONFIG_PATH, ENHANCEMENTS_DECLARED, ENHANCEMENTS_REQUESTED, THRESHOLDS_DECLARED
    global ENHANCEMENTS_DECLARED_OFF
    global V35_CALL
    global AUTHORDEFAULTS_STAMP, AUTHORDEFAULTS_PATH
    global IA_THRESH_TYPE
    global TIME_OFFSET

    cfg = load_config(args.config)
    if cfg.profile is None:
        # Only a [run].engine = "soda2" file loads with no profile (the SODA-2 config names
        # no profile).
        log(f"config    {args.config} names [run].engine = 'soda2'; the SODA-2 engine runs "
            f"through `arrayprobe soda2 run`, never this driver")
        return None
    log(f"config    {args.config} -> profile {cfg.profile.name}")
    if cfg.profile is not ORACLES_PRODUCTION:
        log(f"config    profile switched: {PROFILE.name} -> {cfg.profile.name} -- every "
            f"stage call and provenance stamp for the rest of this run uses it")
    PROFILE = cfg.profile
    PROFILE_MODULE = cfg.profile_module
    AUTHORDEFAULTS_STAMP = cfg.authordefaults_stamp
    AUTHORDEFAULTS_PATH = str(cfg.authordefaults_path) if cfg.authordefaults_path else None

    given = set(argv or sys.argv[1:])
    # Attribute access, never getattr with a default: --engine is required (since 2026-09-23),
    # so a Namespace without it is a caller bug and raises AttributeError here rather than
    # silently running and stamping v3.1.4 (tests/test_run_flight_config.py pins both states).
    engine = args.engine
    wanted = cfg.run.get("engine")
    if wanted is not None and wanted != engine:
        log(f"config    [run].engine = {wanted!r} but this run is --engine {engine}; "
            f"arrayprobe run passes the file's engine, a direct run must say --engine {wanted}")
        return None
    if _fold_run_table(cfg, args, given) is None:
        return None
    if cfg.borrowed_combine and not getattr(args, "borrowed_combine", False):
        log("config    [combine].borrowed = true -> --borrowed-combine")
        args.borrowed_combine = True
    # [outputs]: the file selects which artefacts the run owes; the command line wins,
    # and an absent section leaves the run exactly as it was.
    if cfg.outputs.get("faithful_attributed") and not getattr(args, "attributed", False):
        log("config    [outputs].faithful_attributed = true -> --attributed")
        args.attributed = True
    elif cfg.outputs.get("faithful_attributed") is False and getattr(args, "attributed", False):
        log("config    [outputs].faithful_attributed = false, but --attributed was given: "
            "the command line wins")
    global ATTRIBUTED_ANALYSIS_READY, ATTRIBUTED_ZARR, ATTRIBUTED_PARQUET
    if cfg.outputs.get("analysis_ready") is False:
        log("config    [outputs].analysis_ready = false -> OUTPUT 2 written plain")
        ATTRIBUTED_ANALYSIS_READY = False
    if cfg.outputs.get("zarr"):
        if not (getattr(args, "attributed", False) or cfg.outputs.get("enhanced_attributed")
                or getattr(args, "enhancements", False)):
            log("config    [outputs].zarr = true cannot be honoured: no attributed output is "
                "selected (faithful_attributed / --attributed, or enhanced_attributed), so "
                "there is no file to copy into Zarr")
            log("config    refused before any stage ran. Nothing was run")
            return None
        log("config    [outputs].zarr = true -> a Zarr store beside each attributed file")
        ATTRIBUTED_ZARR = True
    if cfg.outputs.get("parquet"):
        if not (getattr(args, "attributed", False) or cfg.outputs.get("enhanced_attributed")
                or getattr(args, "enhancements", False)):
            log("config    [outputs].parquet = true cannot be honoured: no attributed output is "
                "selected (faithful_attributed / --attributed, or enhanced_attributed), so "
                "there is no file to copy into Parquet")
            log("config    refused before any stage ran. Nothing was run")
            return None
        log("config    [outputs].parquet = true -> a Parquet directory beside each attributed "
            "file")
        ATTRIBUTED_PARQUET = True
    if cfg.outputs.get("arm") == "faithful" and not getattr(args, "protective_worker", False):
        # The parent writes the faithful ARM files once every worker has finished; a --jobs
        # worker leaves them alone.
        if cfg.arm:
            log("config    [outputs].arm = \"faithful\" -> <stem>.arm.nc from the port's own sd")
            args.faithful_arm = dict(cfg.arm)
        else:
            log("config    [outputs].arm = \"faithful\" SKIPPED: no [arm] section, and the ARM "
                "site/platform/facility identifiers are never invented")
    if engine == "3.5" and cfg.shattering_threshold_file is None and not (given & {"--iat-file"}):
        # v3.5's plain call: no threshold file -> iaThreshType 0 (sizeDist.m:79). The argparse
        # default names the ORACLES fork's non-existent file, which v3.5 would OPEN (:1179, no
        # existence check).
        log(f"config    iat-file {args.iat_file!r} -> '' (engine 3.5: no [shattering] section, "
            "iaThreshType 0)")
        args.iat_file = ""
    if cfg.shattering_threshold_file is not None and not (given & {"--iat-file"}):
        if cfg.shattering_threshold_file != args.iat_file:
            log(f"config    iat-file {args.iat_file!r} -> {cfg.shattering_threshold_file!r}")
        args.iat_file = cfg.shattering_threshold_file
    elif cfg.shattering_threshold_file is not None:
        log(f"config    iat-file from the command line wins ({args.iat_file!r})")
    if cfg.shattering_ia_thresh_type is not None:
        if engine != "3.5":
            log("config    [shattering].ia_thresh_type is engine 3.5 only: --engine 3.1.4 "
                "makes the archived product's sizeDist call, which takes no iaThreshType")
            return None
        if args.iat_file:
            log(f"config    [shattering].ia_thresh_type = {cfg.shattering_ia_thresh_type} reads "
                f"no threshold file, but --iat-file {args.iat_file!r} names one")
            return None
        log(f"config    iaThreshType {cfg.shattering_ia_thresh_type} "
            "([shattering].ia_thresh_type)")
        IA_THRESH_TYPE = cfg.shattering_ia_thresh_type

    for stem, diodes in cfg.diode_masks.items():
        current = SHADOW_DIODE_OVERRIDES.get(stem)
        if current is None:
            log(f"config    diode mask {stem}: {list(diodes)} (new)")
        elif list(current) != list(diodes):
            log(f"config    diode mask {stem}: {current} -> {list(diodes)}")
        SHADOW_DIODE_OVERRIDES[stem] = list(diodes)
    if cfg.diode_masks and not args.diode_corrected:
        log("config    masks declared but --diode-corrected not given; they stay unused "
            "(masking is opt-in, and a config may not turn it on silently)")

    global PROTECTIVE_MODE, STRAY_PIXEL_DECLARED, NCAR_2DC_TIMING_DECLARED
    if isinstance(cfg.enhancements, dict) and "stray_pixel_fix" in cfg.enhancements:
        # Stray-pixel rule: an engine switch resolved in main() (resolve_stray_pixel), not a
        # post-stage enhancement name; the command line wins.
        STRAY_PIXEL_DECLARED = bool(cfg.enhancements.pop("stray_pixel_fix"))
        log(f"config    stray_pixel_fix = {STRAY_PIXEL_DECLARED}")
    if isinstance(cfg.enhancements, dict) and "ncar_2dc_timing_fix" in cfg.enhancements:
        # NCAR 2DC timing conversion: an engine switch resolved in main()
        # (resolve_ncar_2dc_timing), not a post-stage enhancement name; the command line wins.
        NCAR_2DC_TIMING_DECLARED = bool(cfg.enhancements.pop("ncar_2dc_timing_fix"))
        log(f"config    ncar_2dc_timing_fix = {NCAR_2DC_TIMING_DECLARED}")
    if isinstance(cfg.enhancements, dict) and "protective" in cfg.enhancements:
        # The data-destroying-defect corrections: a driver switch, not an enhancement name;
        # the command line wins.
        declared = cfg.enhancements.pop("protective")
        if getattr(args, "protective", None) is None:
            PROTECTIVE_MODE = "on" if declared else "off"
            log(f"config    protective = {bool(declared)} -> --protective {PROTECTIVE_MODE}")
    enabled = sorted(k for k, v in cfg.enhancements.items() if v)
    # An explicit `<name> = false` is an opt-out that must also reach the protective set, which
    # runs with or without --enhancements (resolve_protective).
    ENHANCEMENTS_DECLARED_OFF = tuple(sorted(k for k, v in cfg.enhancements.items()
                                             if v is False))
    if _fold_enhanced_attributed(cfg, args, enabled) is None:
        return None
    if enabled and getattr(args, "enhancements", False):
        # The flag says whether to apply; the file says which -- the same division
        # [masking]/--diode-corrected uses twelve lines above, and for the same reason: a
        # config file may not switch on a behaviour change silently.
        log(f"config    enhancements requested: {', '.join(enabled)} -- --enhancements given, "
            "so they are applied to this run's products after the stages finish")
    elif enabled:
        log(f"config    enhancements requested: {', '.join(enabled)} -- NOT applied: this run "
            "did not pass --enhancements (add it, or run `arrayprobe-enhanced run`)")
    # Remember what the file DECLARED, not only what it switched on. The confirmation
    # panel reports the policy, and `needs_confirmation` treats a declared [thresholds] section
    # as the operator having already stated their policy in writing.
    CONFIG_PATH = str(args.config)
    ENHANCEMENTS_DECLARED = cfg.enhancements_declared
    ENHANCEMENTS_REQUESTED = tuple(enabled)
    THRESHOLDS_DECLARED = cfg.thresholds_declared

    # [thresholds], field by field -- a command-line flag always wins, the same rule
    # every other --config value gets (this function's own docstring). A regime for one field
    # and a raw override for the other, one from the file and one from the flag, is normal and
    # expected: they are independent fields with independent justifications.
    if cfg.thresholds_declared:
        if cfg.thresholds_regime is not None and not (given & {"--regime"}):
            if REGIME_NAME != cfg.thresholds_regime:
                log(f"config    regime: {REGIME_NAME!r} -> {cfg.thresholds_regime!r}")
            REGIME_NAME = cfg.thresholds_regime
        elif cfg.thresholds_regime is not None:
            log(f"config    [thresholds].regime given but the command line's --regime "
                f"{REGIME_NAME!r} wins")
        if cfg.thresholds_area_ratio_z is not None and not (given & {"--area-ratio-z"}):
            log(f"config    area_ratio_z override: {cfg.thresholds_area_ratio_z}")
            AREA_RATIO_Z_OVERRIDE = cfg.thresholds_area_ratio_z
            AREA_RATIO_Z_SOURCE = str(args.config)
        elif cfg.thresholds_area_ratio_z is not None:
            log(f"config    [thresholds].area_ratio_z given but the command line's "
                f"--area-ratio-z {AREA_RATIO_Z_OVERRIDE} wins")
        _iat_given = given & {"--default-int-arr-thresh"}
        if cfg.thresholds_default_int_arr_thresh is not None and not _iat_given:
            log("config    default_int_arr_thresh override: "
                f"{cfg.thresholds_default_int_arr_thresh}")
            DEFAULT_IAT_OVERRIDE = cfg.thresholds_default_int_arr_thresh
            DEFAULT_IAT_SOURCE = str(args.config)
        elif cfg.thresholds_default_int_arr_thresh is not None:
            log(f"config    [thresholds].default_int_arr_thresh given but the command line's "
                f"--default-int-arr-thresh {DEFAULT_IAT_OVERRIDE} wins")
        if cfg.thresholds_tas_max is not None and not (given & {"--tas-max"}):
            log(f"config    tas_max (S4 tasMax): {cfg.thresholds_tas_max}")
            TAS_MAX = cfg.thresholds_tas_max
        elif cfg.thresholds_tas_max is not None:
            log(f"config    [thresholds].tas_max given but the command line's --tas-max "
                f"{TAS_MAX} wins")
        if cfg.thresholds_pecan_params is not None and not (given & {"--pecan-params"}):
            log(f"config    pecan_params: {cfg.thresholds_pecan_params}")
            PECAN_PARAMS = cfg.thresholds_pecan_params
        elif cfg.thresholds_pecan_params is not None:
            log(f"config    [thresholds].pecan_params given but the command line's "
                f"--pecan-params {PECAN_PARAMS} wins")

    # [v35] iQC/iNewHabit -- a documented v3.5 state (0/1) selected in the file, applied
    # to this run's own V35_CALL exactly as PROFILE is switched above (config.py already refused
    # this section unless [run].engine = "3.5", and the engine-mismatch guard earlier in this
    # function already returned before here if --engine disagreed with the file). No
    # --i-qc/--i-new-habit flag exists, so there is no command-line-wins race to arbitrate --
    # the file is the only way to set these today.
    if cfg.v35_declared:
        new_i_qc = V35_CALL.i_qc if cfg.v35_i_qc is None else cfg.v35_i_qc
        new_i_new_habit = (V35_CALL.i_new_habit if cfg.v35_i_new_habit is None
                           else cfg.v35_i_new_habit)
        if new_i_qc != V35_CALL.i_qc or new_i_new_habit != V35_CALL.i_new_habit:
            log(f"config    v35: iQC {V35_CALL.i_qc} -> {new_i_qc}, "
                f"iNewHabit {V35_CALL.i_new_habit} -> {new_i_new_habit}")
        V35_CALL = dataclasses.replace(V35_CALL, i_qc=new_i_qc, i_new_habit=new_i_new_habit)

    # [tas], field by field -- a command-line flag always wins, the same rule
    # every other --config value gets (this function's own docstring). Mutates
    # args.tas_source/args.tas_search/args.tas_cutoff_mps/args.tas_default_mps directly, the
    # same pattern args.iat_file uses above, so main() builds the run's one TasPolicy once,
    # after this function has already resolved which side -- flag or file -- won for each field.
    if cfg.tas_declared:
        if cfg.tas_source is not None and not (given & {"--tas-source"}):
            if args.tas_source != cfg.tas_source:
                log(f"config    tas source: {args.tas_source!r} -> {cfg.tas_source!r}")
            args.tas_source = cfg.tas_source
        elif cfg.tas_source is not None:
            log(f"config    [tas].source given but the command line's --tas-source "
                f"{args.tas_source!r} wins")
        if cfg.tas_search and not (given & {"--tas-search"}):
            log(f"config    tas search dirs: {list(cfg.tas_search)}")
            args.tas_search = list(cfg.tas_search)
        elif cfg.tas_search:
            log(f"config    [tas].search given but the command line's --tas-search "
                f"{args.tas_search} wins")
        if cfg.tas_cutoff_mps is not None and not (given & {"--tas-cutoff-mps"}):
            log(f"config    tas cutoff_mps: {args.tas_cutoff_mps} -> {cfg.tas_cutoff_mps}")
            args.tas_cutoff_mps = cfg.tas_cutoff_mps
        elif cfg.tas_cutoff_mps is not None:
            log(f"config    [tas].cutoff_mps given but the command line's --tas-cutoff-mps "
                f"{args.tas_cutoff_mps} wins")
        if cfg.tas_default_mps is not None and not (given & {"--tas-default-mps"}):
            log(f"config    tas default_mps: {args.tas_default_mps} -> {cfg.tas_default_mps}")
            args.tas_default_mps = cfg.tas_default_mps
        elif cfg.tas_default_mps is not None:
            log(f"config    [tas].default_mps given but the command line's --tas-default-mps "
                f"{args.tas_default_mps} wins")

    # [time_offset]: one setting, so it is taken or overridden whole. Any --time-offset-* flag
    # means main() has already built TIME_OFFSET from all three flags (or refused them), and the
    # section yields to it entirely; config.py already validated the section and refused it
    # unless [run].engine = "3.5", and a mismatched --engine returned above.
    if cfg.time_offset is not None:
        if given & {"--time-offset-s", "--time-offset-evidence", "--time-offset-tas-clock"}:
            log(f"config    [time_offset] given but the command line's --time-offset-* "
                f"{TIME_OFFSET} wins")
        else:
            log(f"config    time_offset: {cfg.time_offset[0]} s, TAS clock "
                f"{cfg.time_offset[2]!r}, evidence {cfg.time_offset[1]!r}")
            TIME_OFFSET = cfg.time_offset
    return args


#: ``SetThreadExecutionState`` flags. ``ES_CONTINUOUS`` makes the request stick
#: until it is cleared rather than resetting one timer; ``ES_SYSTEM_REQUIRED``
#: asks that the system not sleep. Display sleep is deliberately NOT requested:
#: a run does not need the screen on, and asking for it would be rude on a
#: laptop.
#: The ``.call`` fragment an enhanced product carries and the port's own never does.
#: Read by anything that has to tell the two arms apart -- which is the whole reason it exists:
#: a number quoted off an ``.enh.*.nc`` and a number quoted off the port's own file are two
#: different claims, and until 2026-09-20 nothing written to disk said which was which.
ENHANCEMENTS_STAMP_KEY = "enhancements="

#: The fragment naming which of the port's own stages were RE-RUN on enhanced input to make a
#: file: ``S4`` for an sd rebuilt from ``enh.proc``, ``S4c`` for the enhanced combined.
REBUILT_STAMP_KEY = "rebuilt="


def enhanced_call_label(base_stamp: str, names, rebuilt=(), inputs=()) -> str:
    """The ``.call`` stamp for an enhanced product: its SOURCE product's stamp, plus one
    ``enhancements=`` fragment naming what ran, comma-joined in the order applied.

    Built by appending to the source stamp rather than composing a new label from scratch, so
    an enhanced file records the entire configuration the port ran under **and** the arm --
    which is what makes a number traceable to a command. The fragment is a suffix, so
    :func:`_stamps_equivalent`'s existing prefix/suffix reasoning about the port's own stamps
    is untouched: the port's outputs never carry it, and this driver never compares an
    enhanced product against a port-stage label.

    Two optional fragments follow it, still a suffix: ``rebuilt=`` names the port
    stages re-run on enhanced input, and ``enhanced_inputs=`` names the files a rebuilt combine
    actually read. :func:`strip_enhancement_block` removes all three and must give back the
    source stamp exactly -- the "one run, no drift" control (three-outputs design D5).
    """
    label = f"{base_stamp} {ENHANCEMENTS_STAMP_KEY}{','.join(names)}"
    if rebuilt:
        label += f" {REBUILT_STAMP_KEY}{','.join(rebuilt)}"
    if inputs:
        label += f" enhanced_inputs={','.join(inputs)}"
    return label


def strip_enhancement_block(stamp: str) -> str:
    """The source stamp an :func:`enhanced_call_label` was built on (three-outputs design D5)."""
    head, sep, _ = stamp.partition(f" {ENHANCEMENTS_STAMP_KEY}")
    return head if sep else stamp


class EnhancedStages:
    """The port's own S4, and this driver's stamp labeller, lent to the enhancement chain.

    Built 2026-09-23, design D1 of the three-outputs design
    record. ``arrayprobe_enhancements.pipeline.apply_to_outputs`` calls
    :meth:`sizedist` once its proc-stage corrections have written ``enh.proc``, so those
    corrections reach an sd at all -- until this date nothing re-ran ``sizeDist`` on
    ``enh.proc``, and the only enhanced-sd effect on any run was ``published_dof``'s uniform
    rescale. The call is :func:`_sizedist_call`, the same one :func:`stage4` makes, with this
    run's module-level arguments: **the port runs unmodified, only its input differs**.

    Lives here, not in the enhancements package, because the arguments are this module's state
    (engine, preset, pressure, threshold file, the v3.5 call switches), which that package never
    binds to. It holds no reference to the enhancements package either -- the chain receives it
    as a duck-typed object.
    """

    def __init__(self, out_dir: Path, iat_file: str | None):
        self.out_dir = Path(out_dir)
        self.iat_file = iat_file

    def sizedist(self, proc: Path, raw_stem: str, dst: Path) -> None:
        """Run the port's S4 unmodified on a corrected proc file, with this run's TAS series
        and threshold file."""
        tas_csv = self.out_dir / f"{raw_stem}.tas.csv"
        if not tas_csv.exists():
            raise FileNotFoundError(f"no {tas_csv.name} (S2 must run first)")
        log(f"S4 enh    {Path(proc).name} -> {Path(dst).name} (port S4, unmodified)")
        t0 = time.time()
        timehhmmss, tas = load_tas_info(tas_csv)
        if TAS_CHAIN is None and tas_grid_fix_on():
            timehhmmss, tas = _collapse_probe_grid(timehhmmss, tas, "S4 enh   ")
        probe_time = timehhmmss
        tas_missing: list[int] = []
        if TAS_CHAIN is not None:
            # The same swap stage4 makes (the author's E2 ruling: one TAS series
            # per run). Without it the enhanced sd and combined products of a chain run were
            # sized on the probe's raw .tas.csv while the ordinary ones used the chain -- on
            # ARM 07-06 that is the stuck 6.0 m/s housekeeping value instead of ARM's
            # true_airspeed. Found by the ARM queue preparation, 2026-09-23.
            timehhmmss, tas, tas_missing = _chain_series_for_sizedist(timehhmmss, "S4 enh   ")
            probe_time = timehhmmss if TAS_GRID == "regular" else probe_time
            if tas_missing:
                log(f"S4 enh    tas {len(tas_missing)} second(s) with no {TAS_CHAIN.tier} "
                    f"sample -> {TAS_POLICY.default_mps:g} m/s: "
                    f"{_mtf.second_ranges(tas_missing)}")
        tas_qc = _tas_qc_record(probe_time, tas_missing)
        _sizedist_call(Path(proc), Path(dst), raw_stem, timehhmmss, tas, self.iat_file,
                       tas_qc=tas_qc)
        _store_tas_qc(Path(dst), tas_qc)
        log(f"S4 enh    done ({time.time() - t0:.0f} s)")

    def stamp(self, target: Path, source: Path, names, rebuilt=()) -> None:
        """Write the enhanced product's .call stamp: the source's stamp plus the corrections
        applied and the stages rebuilt."""
        base = read_stamp(Path(source)) or f"(source {Path(source).name} carried no stamp)"
        write_stamp(Path(target), enhanced_call_label(base, list(names), list(rebuilt)))
        log(f"ENHANCED  {Path(target).name} <- {', '.join(names)}"
            + (f" (rebuilt {', '.join(rebuilt)})" if rebuilt else ""))


def enhanced_combine_path(product: Path) -> Path:
    """``<base>.combined.<...>`` -> ``<base>.enh.combined.<...>``, beside the faithful one."""
    head, sep, tail = product.name.partition(".combined.")
    if not sep:
        raise ValueError(f"{product.name} is not a combined product name")
    return product.with_name(f"{head}.enh.combined.{tail}")


def stage_combine_enhanced(stems: list[str], out_dir: Path, reports: dict[str, dict],
                           borrowed: bool = False) -> Path | None:
    """The port's own S4c, unmodified, over this run's enhanced sd files.

    Each stem contributes the sd its chain ended on -- ``<stem>.enh.sd.nc`` when a correction
    or the S4 rebuild wrote one in this run (the record's ``rebuilt``/``outputs`` say so), else
    the port's own sd, which is then what the enhanced chain holds for that file. The faithful
    combined must already exist: its stamp is the base of this product's stamp, so the D5 test
    can strip the enhancement block and compare. Returns the path written, or ``None`` (logged)
    when there is nothing to combine.
    """
    ordered = sorted(stems)
    faithful = combine_out_path(ordered, out_dir)
    if not faithful.exists():
        log(f"S4c enh   SKIP: no faithful {faithful.name} to build the enhanced one beside")
        return None
    inputs, names = [], []
    for stem in ordered:
        port_sd = sd_path(stem, out_dir)
        enh_sd = out_dir / f"{stem}.enh.sd.nc"
        report = reports.get(stem, {})
        wrote_sd = (enh_sd.name in report.get("rebuilt", {}).values()
                    or enh_sd.name in report.get("outputs", {}).values())
        inputs.append(enh_sd if wrote_sd and enh_sd.exists() else port_sd)
        for stage in ("proc", "sd"):
            names += [n for n in report.get("stages", {}).get(stage, []) if n not in names]
    present = [f for f in inputs if f.exists()]
    if len(present) != len(inputs):
        log(f"S4c enh   SKIP: {len(inputs) - len(present)} of {len(inputs)} sd file(s) missing")
        return None
    target = enhanced_combine_path(faithful)
    partial = target.with_name(target.name + ".partial")
    partial.unlink(missing_ok=True)
    log(f"S4c enh   start {target.name} ({len(present)} file(s): "
        f"{', '.join(f.name for f in present)})")
    _combine_call(present, partial, ordered[0], borrowed)
    os.replace(partial, target)
    call_path(partial).unlink(missing_ok=True)   # engine 3.5's own; replaced by the label below
    base = read_stamp(faithful) or f"(source {faithful.name} carried no stamp)"
    write_stamp(target, enhanced_call_label(
        base, names, ["S4", "S4c"] if any(r.get("rebuilt") for r in reports.values())
        else ["S4c"], [f.name for f in present]))
    log(f"S4c enh   done  {target.name}")
    return target


def _enhancement_names_and_record(reports: dict[str, dict]) -> tuple[list[str], str]:
    """The enhancement names (proc then sd stage, first seen first) and the chain record JSON
    that OUTPUT 2 carries -- one derivation, so OUTPUT 3's enhanced block cannot drift from it."""
    names: list[str] = []
    for report in reports.values():
        for stage in ("proc", "sd"):
            names += [n for n in report.get("stages", {}).get(stage, []) if n not in names]
    record = json.dumps({stem: reports[stem] for stem in sorted(reports)}, sort_keys=True)
    return names, record


def write_attributed_enhanced(target: Path, reports: dict[str, dict]) -> Path | None:
    """OUTPUT 2: the attributed export of the enhanced combined, carrying its ``.call``
    and every stem's enhancement record. Read from files; nothing imported from the
    enhancements package (``attributed_export`` is the port's own exporter)."""
    from arrayprobe import attributed_export

    names, record = _enhancement_names_and_record(reports)
    try:
        written = attributed_export.export(target, enhancements=names,
                                           enhancements_record=record,
                                           analysis_ready=ATTRIBUTED_ANALYSIS_READY)
    except Exception as exc:  # noqa: BLE001 -- the same "never lose the flight" rule
        log(f"S4c enh   ATTRIBUTED skipped for {target.name}: {type(exc).__name__}: {exc}")
        return None
    log(f"S4c enh   attributed {written.name}")
    return written


def protective_to_apply(args) -> tuple[str, ...]:
    """Step 4: the protective names this process applies after its stages -- the resolved
    :data:`PROTECTIVE_ON` in the parent, nothing in a ``--jobs`` worker (the parent applies them
    once, after every worker, as for ``--enhancements``). Empty on the ORACLES lineage."""
    if getattr(args, "protective_worker", False):
        return ()
    return pipeline_protective(PROTECTIVE_ON)


def write_tas_from_probe(out_dir: Path, raw_stem: str) -> Path:
    """Write ``<out_dir>/<raw_stem>.tas.csv`` from :data:`TAS_FROM_PROBE` (author, 2026-09-24).

    The merge is ``tas_from_probe_housekeeping``'s own (per-second median over every
    input, no unit conversion -- the inputs are SPEC S2 sidecars, already m/s), so the driver and
    the stand-alone tool cannot build two different series from one set of files. **No gap policy
    is applied**: a second no input covers is absent from the output, exactly as the tool writes
    it; a gap policy is still the author's decision.

    **Clock frame, not checked here.** The 2D-S sidecar is UTC. v3.5 ``sizeDist.m:758-759`` keys
    probetype 1's particle blocks on the CIP's own clock word and ``:913-918`` compares the two
    with no frame check; where the CIP clock is not UTC, S4 dies
    at ``:918`` as upstream does, and the port preserves that.
    """
    from arrayprobe.driver import tas_from_probe_housekeeping as mod
    seconds, tas, n_raw = mod.merge([Path(p) for p in TAS_FROM_PROBE])
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    target = Path(out_dir) / f"{raw_stem}.tas.csv"
    rows = mod.write_tas_csv(target, mod._hhmmss(seconds), tas, seconds_of_day=seconds)
    log(f"TAS       {target.name}: {rows} whole-second rows from {n_raw} sample(s) in "
        f"{', '.join(Path(p).name for p in TAS_FROM_PROBE)} (the 2D-S's record of the same "
        "aircraft, m/s; no gap fill)")
    return target


def _faithful_combined(out_dir: Path) -> Path | None:
    """The run's one stamped faithful combined product in ``out_dir``, or ``None``.

    Excludes the ``.enh.`` lineage (and, by its ``.nc`` ending, the attributed sibling); more
    than one candidate is ambiguous and returns ``None``, which the caller logs before falling
    back to the ``sd``'s own block.
    """
    found = [p for p in sorted(Path(out_dir).glob("*.combined.*.cdf"))
             if ".enh." not in p.name and Path(f"{p}.call").is_file()]
    return found[0] if len(found) == 1 else None


def write_faithful_arm(args, raw_stems) -> int:
    """``[outputs] arm = "faithful"``: an ARM-format copy of each stem's port sd.

    Through the same guarded import :func:`apply_enhancements_to_run` uses, so the port never
    imports the enhancements package. A missing ``[arm]`` table, an unreadable flight date or an
    export ``arm_export`` refuses is a named skip, logged, never a placeholder file. Returns 0, or
    1 when the package is missing or an export failed outright.
    """
    try:
        from arrayprobe_enhancements import pipeline
    except ImportError as exc:
        log(f"ARM faithful refused: {_ENHANCEMENTS_MISSING} ({exc})")
        return 1
    rc = 0
    for stem in sorted(set(raw_stems)):
        try:
            dst = pipeline.export_faithful_arm(args.out, stem, ENGINE, args.faithful_arm)
        except pipeline.ApplierSkip as exc:
            log(f"ARM faithful SKIP {stem}: {exc}")
            continue
        except Exception as exc:                             # noqa: BLE001 -- a batch run
            log(f"FAILED    ARM faithful {stem}: {type(exc).__name__}: {exc}")
            rc = 1
            continue
        try:
            # The run-level block the attributed combined also carries (engine, the sd
            # configuration, enhancements, airspeed QC, package version), written from the port
            # side so the enhancements package needs nothing of attributed_export.
            from arrayprobe import attributed_export
            with netCDF4.Dataset(dst, "r") as ds:
                sd_name = str(ds.getncattr("arrayprobe_sd_source"))
            # The author's option (a): the run's combined product supplies the block, so OUTPUT 3
            # carries OUTPUT 2's provenance and the combined airspeed-QC summary (with the
            # merged-parts key a per-sd record lacks).
            combined = _faithful_combined(Path(args.out))
            if combined is None:
                log(f"ARM faithful {stem}: no single stamped combined product in {args.out}; "
                    "the run-level block is read from the sd instead")
            attributed_export.stamp_shared_attributes(dst, dst.parent / sd_name, combined)
        except Exception as exc:                             # noqa: BLE001 -- a batch run
            log(f"FAILED    ARM faithful run-level attributes {stem}: "
                f"{type(exc).__name__}: {exc}")
            rc = 1
            continue
        log(f"ARM faithful {dst.name} (lineage faithful, from the port's sd)")
    return rc


def _netcdf_encoding(path: Path) -> str | None:
    """``"netcdf4-analysis-ready"`` or ``"netcdf4-plain"`` from an attributed file's own
    ``arrayprobe_encoding`` attribute; ``None`` when it carries neither."""
    from arrayprobe import attributed_export

    try:
        import netCDF4
        with netCDF4.Dataset(path) as ds:
            enc = getattr(ds, "arrayprobe_encoding", None)
    except Exception:  # noqa: BLE001 -- the manifest never fails the run
        return None
    if enc == attributed_export.ENCODING_PLAIN:
        return "netcdf4-plain"
    if enc == attributed_export.ENCODING_ANALYSIS_READY:
        return "netcdf4-analysis-ready"
    return None


def _manifest_entries(out_dir: Path, raw_stems, since: float | None = None) -> list[dict]:
    """Every output file of the run in ``out_dir``: the combined products (OUTPUT 1, role
    ``original``), their attributed siblings (OUTPUT 2) and each raw stem's ARM files
    (OUTPUT 3), each with its lineage, sha256, size and ``.call`` text (``None`` without one).

    ``since`` (the run's start, epoch seconds) keeps only files this run wrote: a file, or a
    Zarr store's newest file, modified at or after ``since`` less two seconds of filesystem
    timestamp granularity. The rule is the modification time rather than the stems, because
    a combined product is named for the flight's summary-file timestamp, not any raw stem, so
    a stem rule would either drop this run's combined or keep another run's. ``None`` lists
    every match in ``out_dir``."""
    from arrayprobe import attributed_export

    out_dir = Path(out_dir)
    found: list[tuple[Path, str]] = []
    found += [(p, "original") for p in sorted(out_dir.glob("*.combined.*.cdf"))]
    found += [(p, "attributed") for p in sorted(out_dir.glob("*.attributed.nc"))]
    found += [(p, "attributed") for p in sorted(out_dir.glob("*.attributed.zarr"))]
    found += [(p, "attributed") for p in sorted(out_dir.glob("*.attributed.parquet"))]
    for stem in sorted(set(raw_stems)):
        found += [(p, "arm") for p in (out_dir / f"{stem}.arm.nc", out_dir / f"{stem}.enh.arm.nc")]
    entries = []
    for path, role in found:
        encoding: str | None = None
        if path.is_dir() and path.suffix == ".zarr":
            # A directory store: digest and size per _directory_digest (sha256 over the sorted
            # (relative path, file sha256) list; total bytes of every file under it).
            digest, size = _directory_digest(path)
            encoding = "zarr"
        elif path.is_dir() and path.suffix == ".parquet":
            # A directory of Parquet files: digested the same way as a Zarr store.
            digest, size = _directory_digest(path)
            encoding = "parquet"
        elif path.is_file():
            digest, size = attributed_export.sha256_of(path), path.stat().st_size
            if role == "attributed":
                encoding = _netcdf_encoding(path)
        else:
            continue
        if since is not None and _newest_mtime(path) < since - 2.0:
            continue                         # written by an earlier run into the same --out
        call = Path(f"{path}.call")
        entry = {
            "path": path.relative_to(out_dir).as_posix(),
            "role": role,
            "lineage": "enhanced" if ".enh." in path.name else "faithful",
            "sha256": digest,
            "size": size,
            "call": (call.read_text(encoding="utf-8", errors="replace")
                     if call.is_file() else None),
        }
        if encoding is not None:
            entry["encoding"] = encoding
        entries.append(entry)
    return entries


def write_attributed_zarr(out_dir: Path) -> list[Path]:
    """``[outputs] zarr = true``: a Zarr copy of each attributed file in ``out_dir``
    (faithful and enhanced), via :func:`arrayprobe.attributed_export.export_zarr`. A missing
    zarr/xarray install, or any other failure, is a logged named skip that never fails the run."""
    from arrayprobe import attributed_export

    written: list[Path] = []
    for nc in sorted(Path(out_dir).glob("*.attributed.nc")):
        try:
            store = attributed_export.export_zarr(nc)
        except Exception as exc:  # noqa: BLE001 -- the same "never lose the flight" rule
            log(f"ZARR      skipped for {nc.name}: {type(exc).__name__}: {exc}")
            continue
        log(f"ZARR      {store.name}")
        written.append(store)
    return written


def write_attributed_parquet(out_dir: Path) -> list[Path]:
    """``[outputs] parquet = true``: a Parquet directory for each attributed file in ``out_dir``
    (faithful and enhanced), via :func:`arrayprobe.attributed_export.export_parquet`. A missing
    pyarrow install, or any other failure, is a logged named skip that never fails the run."""
    from arrayprobe import attributed_export

    written: list[Path] = []
    for nc in sorted(Path(out_dir).glob("*.attributed.nc")):
        try:
            out = attributed_export.export_parquet(nc)
        except Exception as exc:  # noqa: BLE001 -- the same "never lose the flight" rule
            log(f"PARQUET   skipped for {nc.name}: {type(exc).__name__}: {exc}")
            continue
        log(f"PARQUET   {out.name}")
        written.append(out)
    return written


def _newest_mtime(path: Path) -> float:
    """A file's modification time; for a directory store, the newest of it and its files."""
    if not path.is_dir():
        return path.stat().st_mtime
    return max([path.stat().st_mtime] + [p.stat().st_mtime for p in path.rglob("*")])


def _directory_digest(store: Path) -> tuple[str, int]:
    """A directory store (Zarr) has no single file to hash, so its digest is the sha256 over the
    sorted list of (relative POSIX path, that file's sha256) pairs, one ``path<TAB>sha256<LF>``
    line each, and its size is the total byte size of every file under it."""
    import hashlib

    from arrayprobe import attributed_export

    files = sorted((p.relative_to(store).as_posix(), p) for p in store.rglob("*") if p.is_file())
    h = hashlib.sha256()
    size = 0
    for rel, p in files:
        h.update(f"{rel}\t{attributed_export.sha256_of(p)}\n".encode())
        size += p.stat().st_size
    return h.hexdigest(), size


def write_outputs_manifest(out_dir: Path, raw_stems,
                           since: float | None = None) -> Path | None:
    """``<out_dir>/<base>.outputs.json``: one manifest of every file the run produced, written
    only when the run wrote an OUTPUT 2 or OUTPUT 3 file (so the default run's file set is
    unchanged). ``base`` is the combined product's stem, else the first raw stem. Never fails
    the run: an error is logged and ``None`` returned, as the other writers do. ``since``
    restricts it to this run's files (see :func:`_manifest_entries`)."""
    try:
        entries = _manifest_entries(Path(out_dir), raw_stems, since=since)
        if not any(e["role"] in ("attributed", "arm") for e in entries):
            return None
        originals = [e["path"] for e in entries
                     if e["role"] == "original" and e["lineage"] == "faithful"]
        if originals:
            base = Path(originals[0]).name.split(".combined.")[0]
        else:
            base = list(raw_stems)[0]
        target = Path(out_dir) / f"{base}.outputs.json"
        target.write_text(json.dumps({"outputs": entries}, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 -- the same "never lose the flight" rule
        log(f"MANIFEST  skipped: {type(exc).__name__}: {exc}")
        return None
    log(f"MANIFEST  {target.name} ({len(entries)} file(s))")
    return target


def apply_enhancements_to_run(args, raw_stems, protective=()) -> int:
    """``--enhancements``: apply what ``[enhancements]`` names to the products this run wrote.

    Added 2026-09-20. Until then no driver path ran a UIOOPS engine with enhancements at
    all: :func:`_apply_config` read the config's ``[enhancements]`` table, logged it, and
    declined to honour it, and the confirmation panel said ``OFF -- always``. So "v3.5 with
    all enhancements" -- what every non-ORACLES number is supposed to come from -- was not
    producible by any command that existed.

    **Since 2026-09-23: each correction at its own stage, and every downstream stage re-run.**
    Proc-stage corrections write ``enh.proc``; the port's own S4 then runs on it
    (:class:`EnhancedStages`); sd-stage corrections act on that sd; product exports read it; and,
    when this run combined, the port's own S4c combines the enhanced sd files into
    ``<base>.enh.combined.*`` (:func:`stage_combine_enhanced`), exported with metadata as OUTPUT 2
    of the three outputs per run (:func:`write_attributed_enhanced`). A chain that could not be
    completed -- a proc-stage correction ran but its sd could not be rebuilt -- returns 1.

    **The port is not imported into, and does not import, the enhancements package.** The
    guarded import below lives in ``scripts/``, which is the driver and not the port, and it is
    the same shape ``arrayprobe.cli``'s SODA-2 path already uses (the sentinel, the ``try``,
    the ``except ImportError`` that turns a missing package into a named refusal rather than
    a traceback).

    **The port's own outputs are never touched.** Every applier copies its source and writes a
    separate ``<stem>.enh.<stage>.nc``; the faithful ``proc.*``/``sd.*`` files and their
    stamps are exactly what a run without this flag produces, byte for byte. What this adds is
    files, and each new file gets a ``.call`` of its own carrying
    :data:`ENHANCEMENTS_STAMP_KEY`.

    Resolution happens per stem inside ``apply_to_outputs``, but the *refusals* that must
    happen before anything is written -- an unknown name, a name not applicable to this engine
    -- come out of ``resolve_for_run``, called once here first.

    **The data-destroying-defect corrections: ``protective``** is :data:`PROTECTIVE_ON`, the
    resolved protective set. Its names are merged into ``resolved`` (an explicit
    ``<name> = false`` in the config still wins), with
    :data:`arrayprobe_enhancements.registry.PROTECTIVE_POLICY`'s keyword policies passed
    through to the appliers, and with no ``--enhancements``/``--config`` the run applies the
    protective set alone -- so a ``protective=on:<names>`` stamp names corrections that ran.

    Returns 0, or 1 with a logged reason.
    """
    protective = tuple(protective or ())
    if args.config is None and not protective:
        # Unreachable from main() since 2026-09-20: the same refusal is made up front, before
        # any stage runs, and exits 2 there (see main()). This is the same check kept for a
        # library caller who reaches this function directly, and 1 is the right answer HERE --
        # the return of this function is a run outcome folded into rc, not an exit code, and
        # by the time a caller is in it the stages have already run. The exit-code convention
        # the driver keeps: 2 = the command line or config was refused and NOTHING ran;
        # 1 = something ran and failed.
        log("ENHANCEMENTS refused: --enhancements needs --config. The flag says whether to "
            "apply; the [enhancements] table in the file says which, and a run with no file "
            "names none")
        return 1
    try:
        # Guarded exactly as cli.py guards the SODA-2 registry: an uninstalled optional
        # package is a refusal with an instruction, never an ImportError out of a driver,
        # and tests/test_run_flight_enhancements.py asserts this shape by AST.
        from arrayprobe_enhancements import pipeline
    except ImportError as exc:
        log(f"ENHANCEMENTS refused: arrayprobe_enhancements is not installed ({exc}); "
            "install it with `pip install arrayprobe-uiops-enhancements` (from a source "
            "checkout, `pip install -e enhancements_uiops`). The port "
            "itself never needs it -- that is why this import is guarded")
        return 1

    from arrayprobe.config import load_config
    engine = ENGINE
    cfg = None
    resolved: dict[str, bool] = {}
    declared: dict = {}
    if args.config is not None and getattr(args, "enhancements", False):
        cfg = load_config(args.config)
        if isinstance(cfg.enhancements, dict):
            cfg.enhancements.pop("protective", None)   # the protective switch, not a module name
            declared = dict(cfg.enhancements)
        try:
            resolved = pipeline.resolve_for_run(cfg, engine)
        except Exception as exc:                             # noqa: BLE001
            # UnknownEnhancement / NotApplicableToEngine, both of which the enhancements
            # package defines; caught by shape rather than by name so this module never has
            # to import them (which would defeat the guard above).
            log(f"ENHANCEMENTS refused: {type(exc).__name__}: {exc}")
            return 1
    policies: dict[str, dict] = {}
    if protective:
        try:
            from arrayprobe_enhancements.registry import PROTECTIVE_POLICY
        except ImportError as exc:
            raise SystemExit(f"{_ENHANCEMENTS_MISSING} ({exc})") from exc
        for name in protective:
            if declared.get(name) is False:
                log(f"PROTECTIVE {name}: the config sets it false, which wins")
                continue
            resolved[name] = True
            if name in PROTECTIVE_POLICY:
                policies[name] = dict(PROTECTIVE_POLICY[name])
    on = sorted(n for n, v in resolved.items() if v)
    if not on:
        log("ENHANCEMENTS none: [enhancements] names no module true, so there is nothing to "
            "apply -- this run's products are the port's own, unmodified")
        return 0
    log(f"ENHANCEMENTS {len(on)} ON for engine {engine}: {', '.join(on)}")

    probetype = constants.imgproc_config(PROBE).probetype
    runner = EnhancedStages(args.out, getattr(args, "iat_file", IAT_FILE))
    rc = 0
    reports: dict[str, dict] = {}
    for stem in sorted(set(raw_stems)):
        try:
            got = pipeline.apply_to_outputs(
                args.config, engine, args.out, [stem], resolved,
                preset_probetype=probetype, preset_pres_pa=float(PRES_PA),
                arm_config=dict(getattr(cfg, "arm", {}) or {}), runner=runner,
                policies=policies or None,
                jobs=int(getattr(args, "enh_jobs", 1) or 1))
        except Exception as exc:                             # noqa: BLE001 -- a batch run
            log(f"FAILED    enhancements {stem}: {type(exc).__name__}: {exc}")
            rc = 1
            continue
        for report in got:
            reports[stem] = report
            if report.get("chain_error"):
                log(f"FAILED    enhancements {stem}: the chain is incomplete -- "
                    f"{report['chain_error']}")
                rc = 1

    if "c" in str(getattr(args, "stages", "")) and reports:
        groups: dict[str, list[str]] = {}
        for stem in reports:
            groups.setdefault(flight_group(stem), []).append(stem)
        for date, stems in sorted(groups.items()):
            try:
                product = stage_combine_enhanced(
                    stems, Path(args.out), {s: reports[s] for s in stems},
                    borrowed=getattr(args, "borrowed_combine", False))
            except Exception as exc:                         # noqa: BLE001 -- see above
                log(f"FAILED    enhanced combine {date}: {type(exc).__name__}: {exc}")
                rc = 1
                continue
            if product is None:
                continue
            if write_attributed_enhanced(product, {s: reports[s] for s in stems}) is None:
                log(f"FAILED    enhanced attributed {date}: OUTPUT 2 was not written")
                rc = 1
            rc |= stamp_enhanced_arm(Path(args.out), stems, product,
                                     {s: reports[s] for s in stems})
    return rc


def stamp_enhanced_arm(out_dir: Path, stems, enh_combined: Path,
                       reports: dict[str, dict]) -> int:
    """OUTPUT 3, enhanced lineage: stamp the run-level block OUTPUT 2 carries (engine, the sd
    configuration, enhancements, airspeed QC, package version) into each ``<stem>.enh.arm.nc``
    this run wrote, read from the enhanced combined -- :func:`write_faithful_arm`'s option (a)
    for the other lineage. Written from the port side, so the enhancements package needs
    nothing of ``attributed_export``. Never fails the flight: an error is logged and returns 1.
    """
    from arrayprobe import attributed_export
    rc = 0
    for stem in sorted(set(stems)):
        dst = Path(out_dir) / f"{stem}.enh.arm.nc"
        if not dst.is_file():
            continue
        try:
            with netCDF4.Dataset(dst, "r") as ds:
                sd_name = (str(ds.getncattr("arrayprobe_sd_source"))
                           if "arrayprobe_sd_source" in ds.ncattrs() else f"{stem}.enh.sd.nc")
            # The combined's stamp does not name the corrections; OUTPUT 2 takes them from the
            # chain records (write_attributed_enhanced), so the same derivation feeds the block.
            names, record = _enhancement_names_and_record(reports)
            attributed_export.stamp_shared_attributes(
                dst, dst.parent / sd_name, enh_combined,
                enhancements=names, enhancements_record=record)
        except Exception as exc:                             # noqa: BLE001 -- a batch run
            log(f"FAILED    ARM enhanced run-level attributes {stem}: "
                f"{type(exc).__name__}: {exc}")
            rc = 1
            continue
        log(f"ARM enh   {dst.name}: run-level block from {Path(enh_combined).name}")
    return rc


_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001


@contextlib.contextmanager
def keep_awake(enabled: bool = True):
    """Ask the OS not to sleep while a run is in flight.

    **Why this exists, measured rather than assumed.** Reading the progress
    timestamps out of every campaign run log on 2026-09-01 and differencing
    consecutive lines shows **39.8 hours** of wall-clock lost to the machine
    suspending mid-run -- 15.6 h in flight 09/20 alone, 13.1 h in 09/25's first
    file. The processes resume correctly and lose no *work*; they lose days.

    (The first version of that measurement said 4 days, because it summed the
    six chunk logs of one file and each records the same suspend. Six chunk
    subprocesses are one suspend, not six.)

    The project's own doctrine is that a standing instruction addressed to
    attention is not a control -- and "do not negotiate that the machine will be
    awake" was exactly such an instruction. So the runner holds the lock itself.

    Windows only, by design: ``ctypes.windll`` does not exist elsewhere, and on
    Linux/macOS this is a no-op rather than an error, because the alternative
    (``caffeinate``, ``systemd-inhibit``) is not always installed and a runner
    that refuses to start over a power hint would be worse than one that sleeps.
    Yields True when the lock was actually taken, so a caller can say which.
    """
    taken = False
    if enabled and sys.platform == "win32":
        try:
            import ctypes
            ok = ctypes.windll.kernel32.SetThreadExecutionState(
                _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED)
            taken = bool(ok)
        except (AttributeError, OSError):
            taken = False
    try:
        yield taken
    finally:
        if taken and sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS)
            except (AttributeError, OSError):
                pass


def main(argv=None) -> int:
    """Command line: run the named raw files through the requested stages and return the
    exit status."""
    argv = sys.argv[1:] if argv is None else list(argv)

    # A hidden mode, never used directly: stage3's --chunks re-execs this
    # script with it to run exactly one chunk of one file in its own
    # subprocess, the same way _spawn_worker re-execs for --jobs. Intercepted
    # before the normal parser, which has a completely different argument
    # shape (a list of raw files, not one image file plus chunk indices).
    if argv and argv[0] == "--_run-chunk":
        global PROBE, PROJECT, PROFILE, TAS_FILE, JIT, ENGINE, TAS_POLICY
        global AUTHORDEFAULTS_STAMP, AUTHORDEFAULTS_PATH
        (image_file, probe, project, profile_name, profile_module, tas_file,
         worker_stall_min, out_path, n, n_every) = argv[1:11]
        # Trailing tokens, order-independent: the bare "jit" flag and
        # `engine=<v>`. ENGINE must be set from the parent's value, not left at
        # this fresh subprocess's import-time "3.1.4" -- see cmd_base's comment.
        tail = argv[11:]
        JIT = "jit" in tail
        prime = None
        intent = None
        ad_path = None
        for token in tail:
            if token.startswith("intent="):
                # --resume-chunks: the sha256 of the .chunkN.call the parent wrote before
                # spawning, copied into .done so the parent can tell which intent built it.
                intent = token.split("=", 1)[1]
            elif token.startswith("authordefaults="):
                # Author-editable thresholds: the parent's [fidelity].authordefaults file
                # (see stage3's jit_tail).
                ad_path = token.split("=", 1)[1]
            elif token.startswith("engine="):
                ENGINE = token.split("=", 1)[1]
            elif token.startswith("prime="):
                # v3.5 chunk prefix-priming. Validated here rather than parsed and trusted:
                # this token decides the absolute time of every particle in the chunk, and a
                # malformed one that fell through as None would produce a file that
                # looks like a serial run and is not. Two float64s as float.hex(),
                # which round-trips exactly.
                parts = token.split("=", 1)[1].split(",")
                if len(parts) != 2:
                    raise SystemExit(
                        f"--_run-chunk: prime= needs two comma-separated hex floats, got "
                        f"{token!r}. The parent writes it in stage3; a hand-built command "
                        "line is not a supported entry point.")
                try:
                    prime = (float.fromhex(parts[0]), float.fromhex(parts[1]))
                except ValueError as exc:
                    raise SystemExit(
                        f"--_run-chunk: prime= is not a pair of float.hex() values "
                        f"({token!r}): {exc}") from None
            elif token.startswith("tas_policy="):
                # The airspeed source chain: without this, a chunk worker's own prefix scan
                # (chunk_primes_v35, which reads _aircraft_series() -- see stage3) would apply
                # the module's default TasPolicy while the parent applies a custom one, so a
                # substituted second would land at the wrong value in a chunked run only.
                TAS_POLICY = _mtf.TasPolicy.parse(token.split("=", 1)[1])
            elif token == "tas_ratio=on":
                # The parent's --tas-ratio on (see stage3's jit_tail); absent means off.
                globals()["TAS_RATIO"] = True
            elif token.startswith("stray_pixel="):
                value = token.split("=", 1)[1]
                if value not in ("on", "off"):
                    raise SystemExit(f"--_run-chunk: stray_pixel= needs on|off, got {token!r}")
                globals()["STRAY_PIXEL"] = value == "on"
            elif token.startswith("v35_call="):
                # The parent's iQC/iNewHabit (see stage3's jit_tail). Validated, not trusted:
                # both switch what every particle of the chunk is computed as.
                fields = dict(part.split(":", 1) for part in token.split("=", 1)[1].split(","))
                if set(fields) != {"iQC", "iNewHabit"} or not all(
                        v in ("0", "1") for v in fields.values()):
                    raise SystemExit(f"--_run-chunk: v35_call= needs iQC:<0|1>,"
                                     f"iNewHabit:<0|1>, got {token!r}")
                globals()["V35_CALL"] = dataclasses.replace(
                    V35_CALL, i_qc=int(fields["iQC"]), i_new_habit=int(fields["iNewHabit"]))
        # PROBE/PROJECT/PROFILE are set from the parent's own values (passed on
        # the command line, see stage3's cmd_base) rather than left at this
        # fresh subprocess's import-time defaults -- see the comment beside
        # cmd_base for the incident this fixes.
        PROBE, PROJECT = probe, project
        if profile_module:
            # Registers a profile register_profile() put in the PARENT's
            # PROFILES dict but never this fresh subprocess's -- see
            # PROFILE_MODULE's own module-level docstring for why this is
            # necessary at all.
            import importlib

            from arrayprobe.selector import canonical_module
            importlib.import_module(canonical_module(profile_module))
        if ad_path:
            # Re-load the file (which re-checks its name against its content) and refuse
            # when it no longer hashes to the profile the parent ran: an edit between the
            # parent's launch and this worker's start must not build a chunk with other
            # thresholds. Registers the same authordefaults-<hash> profile and stamp.
            from arrayprobe.authordefaults import load_authordefaults, resolve_profile
            _ad = load_authordefaults(ad_path)
            if f"authordefaults-{_ad.hash}" != profile_name:
                raise SystemExit(f"--_run-chunk: authordefaults file {ad_path} hashes to "
                                 f"{_ad.hash}, but the parent ran profile {profile_name!r}")
            resolve_profile(_ad)
            AUTHORDEFAULTS_STAMP = _ad.stamp()
            AUTHORDEFAULTS_PATH = ad_path
        from arrayprobe.profiles import PROFILES
        PROFILE = PROFILES[profile_name]
        TAS_FILE = tas_file or None   # "" stands for "no file", as for profile_module
        # A chunk used to run silently, so its per-chunk log file stayed empty
        # for the whole pass and a chunked run could only be followed by
        # watching output files grow -- on a 222,693-record file that is two
        # hours of no information at all. Same throttled callback a
        # single-chunk run uses, ~1% of the chunk per line.
        n_every_i = int(n_every)
        # P10 (2026-09-13): a C-level crash inside this worker's own record
        # loop is invisible to the parent's log-growth watchdog until the
        # parent's stall budget elapses. faulthandler writes every thread's
        # Python stack straight into this chunk's log with write(2) --
        # needing neither the GIL nor a loader lock, so it works precisely in
        # the state that wedged 2026-09-13 (a deadlocked DLL load). It does
        # NOT exit: termination stays the parent's job (_kill_tree), because
        # ExitProcess from inside a wedged loader can itself block. Rearmed
        # on every record so the deadline tracks "no record processed for
        # stall_s*0.9 seconds", the same liveness signal the parent's log-size
        # watchdog uses, just measured from inside the process instead of
        # from its log file.
        import faulthandler
        faulthandler.enable()
        stall_s = float(worker_stall_min) * 60
        progress = _progress_every(max(1, n_every_i // 100))
        if stall_s > 0:
            faulthandler.dump_traceback_later(stall_s * 0.9, repeat=False)

            def _progress_and_rearm(i, last):
                progress(i, last)
                faulthandler.cancel_dump_traceback_later()
                faulthandler.dump_traceback_later(stall_s * 0.9, repeat=False)
            progress_cb = _progress_and_rearm
        else:
            progress_cb = progress
        # The timer is cancelled however the chunk ends: a raise left it armed
        # in the calling process, and its dump, which reads every thread's
        # stack without the GIL, crashed a test suite that called this path
        # in-process when it fired 27 minutes later (2026-10-13).
        try:
            written = _imgproc_sm_chunk(Path(image_file), Path(out_path), int(n), n_every_i,
                                        progress_cb, prime=prime)
        finally:
            if stall_s > 0:
                faulthandler.cancel_dump_traceback_later()
        # The completion record stage3's chunk path refuses to merge without
        # (P10): two sides from two places, this worker's own count vs. what
        # the file actually holds.
        #
        # Second line, engine 3.5 only (CIP end-to-end): whether this chunk hit
        # imgProc_sm.m:850-853's width-mismatch `return`, which exits the WHOLE
        # function in MATLAB and so leaves every later record unprocessed. A
        # chunked run cannot see that -- its later workers have their own
        # ranges and never reach the mismatch -- so the fact has to travel to
        # the merge, which drops the chunks MATLAB would never have written.
        # The first line stays the bare count, so an older reader still parses.
        record = f"{written}\n"
        if ENGINE == "3.5" and _v35().module("imgproc").WIDTH_MISMATCH_RETURNS:
            record += "width-mismatch-return\n"
            log(f"S3 chunk {n}: imgProc_sm.m:850-853 width-mismatch return at "
                f"{_v35().module('imgproc').WIDTH_MISMATCH_RETURNS[0]} -- every later "
                "record is unprocessed in MATLAB, so the merge will drop later chunks")
        if intent is not None:
            record += f"intent={intent}\n"
        Path(str(out_path) + ".done").write_text(record)
        log(f"S3 chunk {n} done: {written} particles")
        return 0

    # --presets is read BEFORE the real parser is built, because --preset's
    # `choices` is fixed when the argument is added: a campaign registered
    # afterwards would be rejected by the parser as unknown, and would not
    # appear in --help either. A throwaway parser reads it and nothing else.
    #
    # allow_abbrev=False is load-bearing, and executing this is what found it:
    # a parser that knows only `--presets` matches `--preset NAME` to it as an
    # abbreviation, so `--presets camps.toml --preset X` read *X* as the file
    # path and died on "No such file or directory: 'X'". With more than one
    # unique prefix the abbreviation is ambiguous instead -- also wrong, and
    # only ever a runtime error. tests/test_campaign_preset_file.py drives both
    # flags together for exactly this reason.
    pre = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    pre.add_argument("--presets", type=Path)
    known, _ = pre.parse_known_args(argv)
    if known.presets is not None:
        try:
            declared = load_presets(known.presets)
        except (PresetFileError, OSError, tomllib.TOMLDecodeError) as exc:
            log(str(exc))
            return 2
        for p in declared:
            log(f"declared campaign {p.name}: probe={p.probe} channel={p.orientation} "
                f"project={p.project} d_choice={p.d_choice} sa_method={p.sa_method}")
            log(f"  provenance: {p.provenance}")

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("raw", nargs="+", type=Path,
                    help="raw probe files: .2DS for a SPEC preset, .sea or .cip for a CIP "
                         "one (S2_FORMATS). The extension selects the decoder for a probe "
                         "that has more than one container, and an extension the driver "
                         "cannot identify is refused rather than guessed at; it is NOT yet "
                         "cross-checked against the preset's probe, so pointing a 2D-S "
                         "preset at a CIP file still decodes it as SPEC")
    ap.add_argument("--out", type=Path, default=Path("../_decoded"))
    ap.add_argument("--stages", default="234",
                    help="which stages to run, e.g. '234' (default) or '34'. "
                         "'c' (the combine step) groups the raw files "
                         "given by their embedded YYMMDD and stitches each "
                         "flight's sd.* files into the one product a paper is "
                         "written from; it needs the whole file list in one "
                         "invocation, so it always runs in the parent process "
                         "even under --jobs, after every worker finishes.")
    ap.add_argument("--yes", "-y", action="store_true",
                    help="accept the printed configuration without being asked. A run "
                         "that states no threshold policy (no --regime, no raw override, no "
                         "[thresholds] section) prints everything it is about to do and asks "
                         "before starting; where stdin is not a terminal -- every detached run, "
                         "CI, any script -- there is nobody to ask, so it refuses to start "
                         "without this flag. Declaring the thresholds instead of passing --yes "
                         "is the better answer; this exists so 'exactly what is printed' can be "
                         "accepted deliberately, in a command line somebody can read afterwards.")
    ap.add_argument("--dry-run", action="store_true",
                    help="run the preflight checks and stop")
    ap.add_argument("--_protective-worker", dest="protective_worker", action="store_true",
                    help=argparse.SUPPRESS)
    ap.add_argument("--stray-pixel", dest="stray_pixel", choices=("on", "off"), default=None,
                    help="engine 3.5's stray-pixel correction: removes 1-2 pixel "
                         "specks separated from a particle's main piece before sizing, and "
                         "records each in image_stray_pixels_removed. Default ON for every "
                         "--engine 3.5 run; off is the stock v3.5 path. Overrides "
                         "[enhancements] stray_pixel_fix. Refused as on under --engine 3.1.4 "
                         "--port-validation, which is never corrected. Stamped stray_pixel= "
                         "into every v3.5 proc and sd .call")
    ap.add_argument("--ncar-2dc-timing", dest="ncar_2dc_timing", choices=("on", "off"),
                    default=None,
                    help="v3.5 only: convert NCAR 2DC timing/sync words to the 0x55 form "
                         "before framing (UIOPS imgProc_sm.m:754 frames no particle on them; "
                         "SODA-2 fix2dimage.pro semantics). Default on for v3.5 2DC/2DP.")
    ap.add_argument("--protective", choices=("auto", "on", "off"), default=None,
                    help="the protective corrections for data-destroying upstream "
                         "defects (arrayprobe_enhancements.registry.PROTECTIVE). auto (the "
                         "default) runs them on every probetype except 2D-S/HVPS, whatever the "
                         "engine; off runs none. None of the registry's corrections runs on "
                         "2D-S/HVPS. One driver-applied correction does: bin_table_fix, on "
                         "an engine-3.5 2D-S that would otherwise be sized on the HVPS bin "
                         "table (no --probe-case), which is why such a run prints "
                         "'PROTECTIVE on: bin_table_fix'; off (or [enhancements] "
                         "bin_table_fix = false) skips it. Engine 3.1.4 ORACLES "
                         "products and stamps are unchanged. Overrides [enhancements] "
                         "protective in --config. Refused (exit 2) before any stage when the "
                         "set is non-empty and arrayprobe_enhancements is not installed.")
    ap.add_argument("--enhancements", action="store_true",
                    help="after the stages finish, apply the corrections [enhancements] names "
                         "in --config to the products this run wrote, through "
                         "arrayprobe_enhancements.pipeline. DEFAULT OFF, and off it "
                         "changes nothing: the port's own proc/sd/combined files are written "
                         "and stamped exactly as before, and nothing here imports the "
                         "enhancements package. On, each correction writes a SEPARATE "
                         "<stem>.enh.<stage>.nc beside them -- the faithful output is never "
                         "overwritten -- with its own .call stamp carrying an "
                         "`enhancements=` fragment naming what ran. Requires --config: the "
                         "flag says whether to apply, the file says which, the same division "
                         "--diode-corrected and [masking] already use. Separately, "
                         "--protective (default auto) applies the corrections for "
                         "data-destroying defects without this flag on probes with no "
                         "archived product (CIP/PIP, 2DC/2DP, Fast2DC), never on 2D-S/HVPS.")
    ap.add_argument("--jobs", type=_at_least_one, default=1,
                    help="run N files concurrently as N subprocesses, files "
                         "round-robinned across them (whole-file parallelism). Files are "
                         "independent until the combine step, so this is free "
                         "-- disk is the real constraint, and the preflight's "
                         "worst-case estimate for the whole file list already "
                         "covers it regardless of how many run at once.")
    ap.add_argument("--enh-jobs", type=_at_least_one, default=1,
                    help="run the out-of-focus correction's reject loop across N processes "
                         "when --enhancements (or the protective set) applies it (default 1, "
                         "serial). Distinct from --jobs, which runs N files at once: the "
                         "corrections run in this parent process after every file's worker "
                         "has finished, so the two never nest. The written files are the same "
                         "for any N, and N is recorded in none of them.")
    ap.add_argument("--s2-jobs", type=_at_least_one, default=1,
                    help="decode ONE file across N processes (the decode stage). Distinct from "
                         "--jobs, which runs N files at once: --s2-jobs is what "
                         "helps when a flight has one large raw file, where "
                         "--jobs has nothing to spread. The output is "
                         "byte-identical to the serial decode under either engine -- "
                         "asserted in tests/test_spec_parallel.py (3.1.4) and "
                         "tests/test_v35_spec_parallel.py (3.5) on every channel selection "
                         "and every sidecar -- so this is a speed switch, not a "
                         "fidelity one. 2DS/HVPS/3VCPI, and CIP/PIP .cip files "
                         "(tests/test_dmt_parallel.py; no speed figure measured). "
                         "Engine 3.1.4 measured 1.7-1.9x on "
                         "six workers against real full ORACLES flight files; the merge is "
                         "serial, so the return diminishes past that. No 3.5 figure is "
                         "measured yet.")
    ap.add_argument("--chunks", type=_at_least_one, default=1,
                    help="split EACH file's framing-stage pass across N subprocesses "
                         "(chunked framing) and merge the results -- proven "
                         "bit-for-bit equal to chunks=1 at full production "
                         "scale. Independent of --jobs: that spreads FILES "
                         "across workers, this spreads one file's RECORDS. "
                         "Under --engine 3.5 it covers every probe: CIP/PIP, "
                         "2DC/2DP and Fast2DC directly, because their written "
                         "values are record-local, and 2DS/HVPS/3VCPI by "
                         "priming each chunk seam with a prefix scan that "
                         "carries imgProc_sm.m:1131-1180's whole-file "
                         "Time_in_seconds sum across it. The one refusal is "
                         "2DS/HVPS/3VCPI with iQC=1: qc_image can change an "
                         "image's width mid-file where the header-only scan "
                         "cannot see it; run that serially.")
    # Parsed either way, so a stale script gets the refusal that names the reason; listed in
    # --help only with the v3.1.4 engine present, as cli.py's run does.
    ap.add_argument("--libm-pow", action="store_true",
                    help=("engine 3.1.4 only: compute S4's massBL power (sizeDist.m:844) with "
                          "libm's pow rather than numpy's SIMD power, as MATLAB does. Default "
                          "off (bit-identical when off); stamped libm_pow=on into the sd .call.")
                    if _v314_engine_present() else argparse.SUPPRESS)
    ap.add_argument("--port-validation", action="store_true",
                    help=("required with --engine 3.1.4 and refused with any other engine. "
                          "The v3.1.4 engine is the ORACLES-validation anchor only: "
                          "this flag declares the run port validation and stamps "
                          "port_validation=on into every .call it writes, marking the output "
                          "not for quoting. Changes no computed byte.")
                    if _v314_engine_present() else argparse.SUPPRESS)
    ap.add_argument("--jit", action="store_true",
                    help="route the framing stage's measured-hot per-particle kernels (framing "
                         "dec2bin, perimeter, minimum circle) through numba "
                         "(arrayprobe.jit_kernels; needs numba: pip install arrayprobe[jit]). "
                         "Speed only, default off, lives in the port: the proc "
                         "file is byte-identical to a run without it -- asserted "
                         "in tests/test_imgproc_jit_identity.py -- so it is not "
                         "stamped. Measured 1.6x on the framing stage on a dense ORACLES window. "
                         "Composes "
                         "with --chunks and --jobs, under either engine (3.5: "
                         "tests/test_v35_imgproc_jit_identity.py).")
    ap.add_argument("--write-provenance", action="store_true",
                    help="stamp the framing stage's proc file and the size-distribution "
                         "stage's sd file with arrayprobe_* netCDF GLOBAL ATTRIBUTES "
                         "naming the engine and profile that wrote it (the sd file also "
                         "carries the airspeed record, which seconds took a default TAS, "
                         "when the run names a TAS source), as well as "
                         "the .call sidecar -- an attribute survives the rename, copy or "
                         "hardlink that separates a product from a sidecar keyed by its "
                         "filename. Default OFF and NOT byte-identical: this adds bytes, so "
                         "a run reproducing an archived MATLAB product must leave it off (a "
                         "layer-1 comparison excludes arrayprobe_* names, "
                         "provenance.is_provenance_attr, precisely because the archive "
                         "cannot carry them). v3.1.4 engine and SERIAL framing only: refused "
                         "under --engine 3.5 (redundant: every v3.5 proc and sd, and every "
                         "SODA-2 product, carries arrayprobe_engine/arrayprobe_profile "
                         "unconditionally) and "
                         "with --chunks/--jobs (merge_chunks does not forward it), rather "
                         "than accepted and quietly doing nothing.")
    ap.add_argument("--resume-chunks", action="store_true",
                    help="with --chunks, reuse the chunk files an interrupted run left "
                         "(killed during the merge, or with some chunks finished) instead of "
                         "rebuilding every chunk. A chunk is reused only when the intent file "
                         "written before it was built (argv, framing-stage stamp, source size and "
                         "mtime, "
                         "TAS file, the port's git tree, library versions) equals this run's "
                         "byte for byte, and its completion record carries that intent's hash "
                         "and a particle count matching the file; anything else is rebuilt. "
                         "A modified or untracked file in the port's src or tools tree turns "
                         "reuse off. Speed only, default off: a correct resume is "
                         "byte-identical to a fresh run, so it is logged, not stamped. Chunks "
                         "written by a driver without this flag are never reused.")
    ap.add_argument("--worker-stall-min", type=float, default=30.0,
                    help="kill and fail a --chunks worker whose own log has not "
                         "grown for this many minutes, instead of waiting on it "
                         "forever (P10, 2026-09-13: a chunk worker deadlocked "
                         "inside a DLL load and the parent's unbounded proc.wait() "
                         "blocked for 6 h 25 min). Pass 0 to restore the old "
                         "unbounded wait. Applies to --jobs workers too, and is "
                         "forwarded to them, so a --jobs worker's own nested "
                         "--chunks wait uses the same value; a --jobs worker's "
                         "liveness is the heartbeat its nested chunk wait writes "
                         "into its log (at most every min(5 min, budget/4)).")
    ap.add_argument("--iat-file", default=IAT_FILE,
                    help="sizeDist's optional twelfth argument, the inter-arrival "
                         "threshold file. Defaults to the ORACLES production call, "
                         "which names a file that does not exist so the per-probe "
                         "6 us default applies. Pass '' to omit the argument "
                         "entirely -- a different call, NOT the same thing, and not "
                         "the one that made the published product (see stage4).")
    ap.add_argument("--iat-source", default=None, choices=("flight-table",),
                    help="engine 3.1.4, HVPS only, opt-in: take the twelfth argument from the "
                         "recorded per-flight table (arrayprobe.hvps_flight_config) -- "
                         "port_fit_blocks5 passes <out>/HVPS_intArrThreshold_<stem>.V_1.cdf "
                         "(written by `arrayprobe intarr-threshold --blocks 5`), none_default "
                         "passes HVPS_intArrThreshold_MISSING.V_1.cdf. An unrecorded stem is "
                         "refused, never defaulted. Excludes --iat-file.")
    ap.add_argument("--tas-file", type=Path, default=None,
                    help="the aircraft TAS file stock imgProc_sm.m:183-185 reads as "
                         "varargin{1}: netCDF with 'TAS' and 'Time' (HHMMSS, one sample "
                         "per second). Required under a profile whose "
                         "time_in_seconds_from_tas is set (STOCK_V314) and refused under "
                         "one that never reads it (every ORACLES profile: imgProc_sm.m:365 "
                         "hard-wires 170 m/s), so a run never carries an input it ignores. "
                         "One file per run, hence one flight per run under such a profile: "
                         "the file has no date, only HHMMSS. [run].tas_file in a config "
                         "reaches this only through `arrayprobe run`; --config alone does "
                         "not read [run].")
    ap.add_argument("--tas-ratio", choices=("off", "on"), default="off",
                    help="v3.5 only: pass the aircraft true-airspeed series to the decoder so it "
                         "writes tasRatio (probe TAS / aircraft TAS), which changes the product. "
                         "Needs an aircraft airspeed source (--tas-source or --tas-file). "
                         "Reaches the serial and the --s2-jobs parallel decode alike. "
                         "Default off.")
    ap.add_argument("--tas-source", choices=_tas_sources.MODES, default=None,
                    help="resolve the merge/aircraft/probe TAS source chain instead of trusting "
                         "--tas-file as given: 'auto' walks merge -> aircraft -> probe "
                         "and uses the first source that "
                         "is available and passes its checks; 'merge'/'aircraft'/'probe' "
                         "pins one tier and refuses rather than falling through. Refused "
                         "together with --tas-file (name one or the other). "
                         "[tas].source in a config reaches this only through `arrayprobe run`.")
    ap.add_argument("--tas-from-probe", action="append", type=Path, default=[],
                    help="probetype 1 (CIP, PIP) only: a <stem>.tas.csv another probe's decode "
                         "stage "
                         "wrote on the SAME aircraft (the 2D-S's housekeeping airspeed, m/s; "
                         "repeatable). Merged by arrayprobe.driver.tas_from_probe_housekeeping "
                         "(per-"
                         "second median, no gap fill) into this probe's <stem>.tas.csv before "
                         "the framing stage, so the size-distribution stage has an airspeed; "
                         "stamped as tas_series=probe_hk:<names>. "
                         "Refused on a probe whose decode stage "
                         "writes its "
                         "own, and together with --tas-source.")
    ap.add_argument("--tas-grid", choices=("probe", "regular"), default=None,
                    help="the time vector the size-distribution stage gets under --tas-source. "
                         "'probe' (default) keeps the probe's own <stem>.tas.csv seconds, which "
                         "repeat and skip seconds, and the stage then counts no particle in a "
                         "repeated or skipped second (UIOPS sizeDist.m's own block walk, "
                         "measured under Octave). 'regular' gives it every second of the "
                         "probe's span once, valued from the chain's airspeed, as UIOPS's own "
                         "worked example passes aircraft Time with TAS; stamped tas_grid=regular. "
                         "Needs --tas-source. Changes the product; default 'probe', except "
                         "'regular' for the ARM profiles (no archived product) when "
                         "--tas-source is given.")
    ap.add_argument("--tas-search", action="append", default=[],
                    help="a directory the chain's merge/aircraft tiers glob in for a "
                         "campaign's own aircraft file (repeatable). [tas].search in a "
                         "config file is resolved relative to that file; this flag is "
                         "used as given.")
    ap.add_argument("--tas-cutoff-mps", type=float, default=None,
                    help="TasPolicy's cutoff_mps for this run's TAS chain; "
                         "documented default 300 m/s (the largest UIOPS tas_max) "
                         "applies when neither this flag nor "
                         "[tas].cutoff_mps names one.")
    ap.add_argument("--tas-default-mps", type=float, default=None,
                    help="TasPolicy's default_mps for this run's TAS chain; "
                         "documented default 170 m/s (imgProc_sm.m:365/:763's own "
                         "fallback) applies when neither this flag nor "
                         "[tas].default_mps names one.")
    ap.add_argument("--diode-corrected", action="store_true",
                    help="run stage3_corrected() instead of stage3() for any file "
                         "with an entry in SHADOW_DIODE_OVERRIDES, writing "
                         "proc.*.diodecorrected.nc / sd.*.diodecorrected.nc -- an "
                         "opt-in variant, never touching the default fidelity-faithful "
                         "output. A file with no override entry is skipped "
                         "with a log line, not silently run uncorrected under this flag.")
    ap.add_argument("--accept-implausible", action="store_true",
                    help="keep an sd the post-S4 plausibility gate refuses (no second, or under "
                         "0.1 %% of seconds, carries particles while its proc accepted some); "
                         "recorded as accept_implausible=on in the sd .call stamp")
    ap.add_argument("--accept-preset-mismatch", action="store_true",
                    help="run a raw file whose extension names a different probe than the "
                         "preset's (e.g. .HVPS under a 2D-S preset); use only for a renamed file. "
                         "Recorded as accept_preset_mismatch=on in the .call stamps")
    ap.add_argument("--accept-flagged", action="store_true",
                    help="process a raw file the input inventory flags as empty (a trailing "
                         "partial record is only warned about and decoded). Without it an "
                         "empty file is refused with exit 2 before any decode; the flags go "
                         "into the S2 .call only")
    ap.add_argument("--accept-unstamped", action="store_true",
                    help="use existing proc files that carry no provenance sidecar. "
                         "Without it they are REFUSED: which fidelity configuration "
                         "produced them cannot be established, and a proc file from "
                         "before the 2026-08-28 reject-threshold correction carries "
                         "the stock thresholds -- combining one with newly produced "
                         "files mixes two configurations inside one flight product. "
                         "Pass this only when you have established their configuration "
                         "by other means; nothing is written to claim they were verified.")
    ap.add_argument("--allow-mixed-config", action="store_true",
                    help="permit the combine step to stitch a flight product out of sd files "
                         "built under DIFFERENT fidelity configurations. Refused "
                         "by default, because the product cannot be asked which "
                         "configuration made it afterwards. A deliberate mixture "
                         "is legitimate -- the 09/06/2016 archived product is one "
                         "-- but it has to be asked for, and every file's "
                         "configuration is logged either way.")
    ap.add_argument("--preset", required=True,
                    choices=sorted(PRESETS),
                    help="the campaign call to run: probe, channel, project, size "
                         "definition, sample-area method, pressure and temperature, "
                         "chosen WHOLE and by name. These are not independent knobs "
                         "-- they are one call transcribed from one driver script, "
                         "and getting one wrong produces a plausible wrong answer -- "
                         "so there is no way to set them individually here. A new "
                         "campaign, probe or channel is a new CampaignPreset with "
                         "its own provenance line, shipped here or declared in a "
                         "--presets file. REQUIRED since 2026-09-15: "
                         "there is no default, because a driver-supplied default "
                         "silently picked ORACLES_2016_2DS_H for anyone who forgot "
                         "the flag -- the exact failure this project's 'no default "
                         "silently picks a side' rule exists to prevent. "
                         "'arrayprobe run' is unaffected -- it always passes this "
                         "from the config file's required [run].preset. Name "
                         "ORACLES_2016_2DS_H to reproduce the archived ORACLES 2016 "
                         "2D-S products exactly; ORACLES_2017_2DS_V reaches the "
                         "vertical channel and is NOT yet validated against a V "
                         "product, which its own provenance says.")
    ap.add_argument("--presets", type=Path,
                    help="a TOML file of [[campaign]] tables to register before "
                         "--preset is read, so a campaign this driver does not ship "
                         "can be run without editing it. Every field is required and "
                         "a declared campaign may not shadow a built-in name -- a "
                         "preset is still one call chosen whole, it just no longer "
                         "has to live in this file. See load_presets().")
    # 3.1.4 is always accepted, so naming it without the engine reaches the refusal after
    # parse_args that says why; the usage line lists only the engines installed.
    ap.add_argument("--engine", default=None,
                    choices=tuple(dict.fromkeys(_engine_choices() + ("3.1.4",))),
                    metavar="{" + ",".join(_engine_choices()) + "}",
                    help="which UIOPS engine runs decode through combine. REQUIRED, no default: "
                         "a run without it exits 2 naming the choice. 3.5 "
                         "is the choice for all new work. 3.1.4 reproduces archived pre-v3.3 "
                         "UIOPS products (the ORACLES validation) and is the only engine with "
                         "an archived product behind it; 3.5 runs "
                         "arrayprobe_uiops through uiops.engine('3.5') under profile stock-v3.5, "
                         "stamps engine=3.5 in every .call, and refuses "
                         "--diode-corrected and a threshold file that does not exist. --jit IS "
                         "accepted under 3.5 (arrayprobe_uiops.jit_kernels, since 2026-09-18: "
                         "1.79x measured, byte-identical -- "
                         "tests/test_v35_imgproc_jit_identity.py). "
                         "--chunks works for CIP/PIP, 2DC/2DP and Fast2DC, and for "
                         "2DS/HVPS/3VCPI by prefix-priming each chunk seam (refused "
                         "only with iQC=1). arrayprobe run passes "
                         "[run].engine here.")
    ap.add_argument("--attributed", action="store_true",
                    help="after the combine, also write the SELF-DESCRIBING SIBLING of the "
                         "product: <product>.attributed.nc, same values, plus the whole .call "
                         "sidecar and a sourced unit on every variable, so a recipient can "
                         "re-derive the number from one file ("
                         "docs/developer/ATTRIBUTED_EXPORT.md). The faithful product is "
                         "opened READ-ONLY and never modified -- it stays the byte-comparison "
                         "artefact. Off by default: a run writes what it says it writes")
    ap.add_argument("--borrowed-combine", action="store_true",
                    help="engine 3.5 only: run 'c' with an archived product's combine_sizedist.m, "
                         "borrowed and labelled so in the product's .call (arrayprobe_uiops.combine"
                         "); no stock v3.5 release has a combine. [combine].borrowed = "
                         "true in a config sets this.")
    ap.add_argument("--probe-case", default=None, metavar="NAME",
                    help="ENGINE 3.5 ONLY (probe-case lookup): select a registered probe case "
                         "(arrayprobe_uiops.probe_cases) for the size-distribution stage's bin "
                         "ladder and the constants "
                         "beside it, instead of v3.5's own switch. Exists because v3.5's "
                         "otherwise/'2DS' case carries the HVPS 28-bin 0.2-30 mm ladder "
                         # `%%` because argparse %-formats every help string: a literal `%` here
                         # made `run_flight.py --help` raise `TypeError: must be real number, not
                         # dict` for EVERY flag, not just this one -- a total CLI outage, caught
                         # by the first full-suite run on a quiet tree (2026-09-21).
                         "(sizeDist.m:497-505, headed '%% For the HVPS'), so an unlisted "
                         "campaign's "
                         "2D-S size distribution is empty -- measured on a 2D-S file from a "
                         "campaign "
                         "with no regime entry: "
                         "summed Size Distribution 11168.6 on v3.1.4, 0.0100 on v3.5. Omit to let "
                         "the switch decide, bit-identically to every run before 2026-09-21. A "
                         "NAME only: a config file may select a named variant but never set a "
                         "threshold -- a ladder is a set of constants, so it is "
                         "registered from Python and selected here, never described here. Recorded "
                         "in the sd .call stamp.")
    ap.add_argument("--time-offset-s", type=float, default=None, metavar="SECONDS",
                    help="ENGINE 3.5 ONLY: a whole number of seconds added to every particle "
                         "time in the size-distribution stage, for a probe whose clock is measured "
                         "off aircraft time. Needs --time-offset-evidence and "
                         "--time-offset-tas-clock. Recorded in the sd .call stamp; omit for the "
                         "stock call.")
    ap.add_argument("--time-offset-evidence", default=None, metavar="TEXT",
                    help="ENGINE 3.5 ONLY: how the --time-offset-s value was measured "
                         "(required with it; written into the sd file and its .call stamp).")
    ap.add_argument("--time-offset-tas-clock", default=None, metavar="probe|aircraft",
                    help="ENGINE 3.5 ONLY: 'probe' when the per-second time/TAS rows come from "
                         "the probe's own record (shifted with the particles), 'aircraft' when "
                         "they come from an aircraft file (left alone). Required with "
                         "--time-offset-s.")
    ap.add_argument("--probe-case-module", default=None, metavar="DOTTED.MODULE",
                    help="a module to import before resolving --probe-case, e.g. mypkg."
                         "register_my_case. Required for any case this package "
                         "does not register on its own, and for EVERY case under --jobs: a worker "
                         "is a fresh process with an empty registry, so the name alone does not "
                         "survive the re-exec (the same gap --config's [fidelity].profile_module "
                         "closes for a registered profile).")
    ap.add_argument("--regime", choices=sorted(regimes.REGIMES), default=None,
                    help="BOTH ENGINES. Engine 3.5: the regime's area_ratio_z and "
                         "default_int_arr_thresh replace sizeDist.m:1162's .2 and the case's "
                         "defaultIntArrThresh, and its reject slots reach S3. Which named "
                         "cloud-regime bundle (arrayprobe.regimes.REGIMES) "
                         "supplies the two size-distribution threshold fields (area_ratio_z, "
                         "default_int_arr_thresh) that constants.sizedist_config's project/probe "
                         "switch otherwise supplies from ORACLES's own tuning for any project it "
                         "does not recognise -- the defect this flag exists to stop being silent. "
                         "Omit to keep exactly the hard-coded values every run before 2026-09-17 "
                         "used (bit-identical); --area-ratio-z / --default-int-arr-thresh win "
                         "over a named regime per field. [thresholds].regime sets this from a "
                         "config file.")
    ap.add_argument("--area-ratio-z", type=float, default=None,
                    help="BOTH ENGINES. Raw override for the size-distribution 'z' reject "
                         "threshold. Engine 3.1.4: sizeDist.m:849 / :985, validated to fall in "
                         "(0, 1], the range an area ratio is bounded to by its own definition; "
                         "wins over --regime for this field; [thresholds].area_ratio_z sets it "
                         "from a config file (the same (0, 1] there). Engine 3.5: replaces the "
                         "literal .2 at sizeDist.m:1162 for this run, validated to fall in "
                         "[0, 1] where 0 turns the gate off (command line only; "
                         "[thresholds].area_ratio_z also works and keeps (0, 1]); it is written "
                         "to the sd .call stamp only when given, so an sd built without it "
                         "keeps its stamp. The rule that a config file selects, never "
                         "describes, a fidelity threshold is lifted for exactly this field.")
    ap.add_argument("--default-int-arr-thresh", type=float, default=None,
                    help="BOTH ENGINES (engine 3.5: replaces the case's defaultIntArrThresh, "
                         "finite and >= 0). Raw override for the size-distribution shattering "
                         "inter-arrival "
                         "threshold "
                         "(sizeDist.m:269, seconds). Same lift of that rule as --area-ratio-z; "
                         "must be positive and finite, no upper bound asserted (none is held by "
                         "this repository). Wins over --regime for this field. "
                         "[thresholds].default_int_arr_thresh sets this from a config file.")
    ap.add_argument("--tas-max", type=float, default=None,
                    help="BOTH ENGINES. tasMax (m/s) for a sizeDist case that assigns none -- the "
                         "2DP, in every UIOPS release -- passed to S4; a 2DP run without it is "
                         "refused, and a case that assigns its own refuses it. Finite and > 0. "
                         "Written to the sd .call stamp only when given. "
                         "[thresholds].tas_max sets it from a config file.")
    ap.add_argument("--pecan-params", default=None,
                    help="BOTH ENGINES. A parameter file (CSV of spiral start_s, end_s, "
                         "intar_threshold_s; arrayprobe_uiops.pecan_params) standing in for "
                         "getPECANparams, which ships in no UIOPS release, on the PECAN CIP/PIP "
                         "cases; refused on any other case. Written to the sd .call stamp by "
                         "name and content hash only when given. [thresholds].pecan_params sets "
                         "it from a config file.")
    ap.add_argument("--profile", default=None,
                    help="which FidelityProfile this run uses, BY NAME -- the same names "
                         "[fidelity].profile accepts, in either spelling (stock-v3.5 or "
                         "STOCK_V35). Default: oracles-production, unchanged, so every run "
                         "that does not pass this is bit-identical to one from before the "
                         "flag existed. It SELECTS a profile that already exists and cannot "
                         "describe one -- the select-never-describe rule is about description, "
                         "not about which "
                         "file the selection is written in (arrayprobe.profiles."
                         "register_profile's own docstring: 'arrayprobe.config will happily "
                         "select a registered profile by name; it still refuses to describe "
                         "one'), and this driver already passes PROFILE.name across a command "
                         "line to every --chunks worker. Exists because --engine 3.5 needs a "
                         "v3.5-citing profile and, until 2026-09-20, no command line could "
                         "name one: the default engine was unreachable without hand-writing a "
                         "TOML file. A fork's own "
                         "registered profile is reachable here only if something already "
                         "imported its registration; --config's [fidelity].profile_module is "
                         "still the way to guarantee that in a fresh process. --config's "
                         "profile is overridden by this flag, and the override is logged.")
    ap.add_argument("--config", type=Path,
                    help="a run configuration file (TOML) read by arrayprobe.config. It can "
                         "only SELECT -- a named FidelityProfile, the explicit shattering "
                         "threshold argument, per-file diode masks -- and a raw fidelity "
                         "threshold anywhere in it is refused at load time, EXCEPT "
                         "[thresholds].area_ratio_z / [thresholds].default_int_arr_thresh "
                         "(the select-never-describe rule lifted for exactly those two). "
                         "Values given on "
                         "the command line win, and each override is logged, so a run is "
                         "never steered by a setting nobody can see.")
    args = ap.parse_args(argv)
    if getattr(args, "engine", None) == "3.1.4" and not _v314_engine_present():
        print(_V314_ABSENT_MESSAGE, file=sys.stderr)
        return 2

    # `--engine` is REQUIRED, for every preset (author, 2026-09-23, config
    # file and required engine): "require it like --preset". Until then it defaulted to 3.1.4,
    # and from 2026-09-21 (the engine-scope rule) only a non-ORACLES preset refused the
    # default. An ORACLES run without the flag still ran v3.1.4 silently, although v3.5 is
    # the project default -- a silent choice of side that this project forbids.
    #
    # **The default is removed, not flipped**: flipping it to 3.5 would change what every
    # existing command line means, including those in archived run logs that reproduce
    # published figures. Refusing makes each of them fail loudly instead, the same shape
    # `--preset` took on 2026-09-15. `--engine 3.1.4` written out works exactly as before.
    # The refusal is ours rather than argparse's `required=True`, so it can say which engine
    # to choose and why.
    if args.engine is None:
        _p = PRESETS.get(getattr(args, "preset", None) or "")
        _proj = f" (project {_p.project!r})" if _p is not None else ""
        log(f"REFUSED   no --engine was given for preset {args.preset}{_proj}.")
        # A config file that names its engine gets the specific instruction _apply_config used to
        # give for this case, since this refusal now runs first. Any config error surfaces on the
        # corrected run; the run is refused here either way.
        _wanted = None
        if getattr(args, "config", None):
            from arrayprobe.config import ConfigError, load_config
            try:
                _wanted = load_config(args.config).run.get("engine")
            except (ConfigError, OSError):
                _wanted = None  # only a hint; the refusal stands regardless
        if _wanted is not None:
            log(f"          {args.config} names [run].engine = {_wanted!r}: arrayprobe run passes "
                f"the file's engine, a direct run must say --engine {_wanted}")
        log("          --engine is required (since 2026-09-23); there is no default. "
            "Say which engine you mean:")
        log("            --engine 3.5      the default for all new work (add --probe-case "
            "if the campaign is not in sizeDist's switch)")
        if _v314_engine_present():
            log("            --engine 3.1.4 --port-validation   only to reproduce an archived "
                "pre-v3.3 UIOPS product, e.g. the ORACLES validation; the engine-scope rule "
                "permits quoting it only for ORACLES 2D-S/HVPS")
        return 2
    # R4. First of the refusals after the missing-engine
    # one, so a v3.1.4 run without the flag is told the root cause first. Reads only ``args``.
    if args.engine == "3.1.4" and not args.port_validation:
        log("REFUSED   --engine 3.1.4 needs --port-validation: it reproduces an archived "
            "product only, and its output is stamped port validation, not for quoting. "
            "Add --port-validation, "
            "or run --engine 3.5")
        return 2
    if args.port_validation and args.engine != "3.1.4":
        log(f"--port-validation is engine 3.1.4 only: it marks an engine 3.1.4 run as "
            f"port validation, and --engine {args.engine} is not that engine. "
            "Drop --port-validation")
        return 2

    # ENGINE is declared global at the top of the --_run-chunk branch above, which
    # runs earlier in this same function -- Python allows only one declaration per
    # name per function, and re-declaring it here is a SyntaxError.
    global REGIME_NAME, AREA_RATIO_Z_OVERRIDE, DEFAULT_IAT_OVERRIDE
    global AREA_RATIO_Z_SOURCE, DEFAULT_IAT_SOURCE, TAS_MAX, PECAN_PARAMS
    # WRITE_PROVENANCE is not in the --_run-chunk branch's global list because a chunk
    # worker never writes it: merge_chunks does not forward it, and main() refuses the
    # --chunks combination below rather than let a worker stamp a file the merge discards.
    global WRITE_PROVENANCE, LIBM_POW, PORT_VALIDATION
    global PROBE_CASE, PROBE_CASE_MODULE
    global TAS_SOURCE, TAS_SEARCH, TAS_CHAIN
    ENGINE = args.engine
    globals()["PROTECTIVE_MODE"] = "auto"  # protective mode: no leak between in-process calls
    globals()["ENHANCEMENTS_DECLARED_OFF"] = ()  # set again by _apply_config from this run's file
    globals()["IA_THRESH_TYPE"] = None  # set again by _apply_config from this run's [shattering]
    PROBE_CASE = args.probe_case
    PROBE_CASE_MODULE = args.probe_case_module
    if PROBE_CASE_MODULE:
        # Before the refusals below, so a mistyped module name fails here with its own
        # ImportError rather than as "no probe case X is registered" three checks later.
        #
        # Imported here rather than used from the module-level `import importlib`: the
        # --_run-chunk branch earlier in this same function has its own `import importlib`,
        # which makes the name function-local for the WHOLE of main() -- so the module-level
        # one is unreachable from here and reading it raises UnboundLocalError. Measured,
        # not guessed: that is exactly how this line failed first.
        import importlib as _importlib

        from arrayprobe.selector import canonical_module
        _importlib.import_module(canonical_module(PROBE_CASE_MODULE))
    if PROBE_CASE is not None:
        if args.engine != "3.5":
            log("--probe-case is engine 3.5 only: engine 3.1.4's sizeDist.m already carries the "
                "128-bin 10 um ladder for an unlisted campaign's 2D-S (sizeDist.m:374,:376), "
                "which is the ladder the ARM case borrows. Drop --probe-case, or --engine 3.5")
            return 2
        # Through the selector, like every other reach into arrayprobe_uiops from this module
        # (_v35()'s own docstring) -- never a direct `import arrayprobe_uiops...`.
        probe_cases = _v35().module("sizedist")
        try:
            resolve_run_probe_case(PROBE_CASE)
        except probe_cases.UnknownProbeCase as exc:
            # Refused at preflight, never at S4: a run that decodes for twelve minutes and
            # then cannot resolve its own ladder has wasted the decode.
            log(str(exc))
            log("Name the module that registers it with --probe-case-module "
                "(e.g. --probe-case-module mypkg.register_my_case)")
            return 2
    globals()["TIME_OFFSET"] = None
    _offset_args = (args.time_offset_s, args.time_offset_evidence, args.time_offset_tas_clock)
    if any(a is not None for a in _offset_args):
        if args.engine != "3.5":
            log("--time-offset-s/--time-offset-evidence/--time-offset-tas-clock are engine 3.5 "
                "only: the probe-clock offset is a keyword of arrayprobe_uiops's sizeDist, and "
                "v3.1.4 reproduces the archived record. Drop them, or --engine 3.5")
            return 2
        if args.time_offset_s is None:
            log("--time-offset-evidence/--time-offset-tas-clock given without --time-offset-s")
            return 2
        try:
            _off = _v35().module("sizedist").TimeOffset.build(*_offset_args)
        except ValueError as exc:
            log(f"--time-offset-s refused: {exc}")
            return 2
        globals()["TIME_OFFSET"] = (_off.seconds, _off.evidence, _off.tas_clock)
    REGIME_NAME = args.regime
    AREA_RATIO_Z_OVERRIDE = args.area_ratio_z
    DEFAULT_IAT_OVERRIDE = args.default_int_arr_thresh
    AREA_RATIO_Z_SOURCE = "cli"
    DEFAULT_IAT_SOURCE = "cli"
    TAS_MAX = args.tas_max
    PECAN_PARAMS = (str(Path(args.pecan_params).expanduser().resolve())
                    if args.pecan_params is not None else None)
    JIT = args.jit  # declared global with the --_run-chunk branch's names above
    # Aliased: a bare `import importlib.util` would rebind main()'s local `importlib`.
    import importlib.util as _importlib_util
    if JIT and _importlib_util.find_spec("numba") is None:
        # Fail before S2, not at S3: on a real flight the decode before S3 can take
        # hours, and the numba message otherwise surfaces mid-log under a traceback.
        log("--jit needs numba, which is not installed in this environment "
            f"({sys.executable}). Install it with `{sys.executable} -m pip install "
            "\"arrayprobe[jit]\"` (`\"arrayprobe[pinned]\"` installs the tested pins), or drop "
            "--jit: the default path writes the same bytes, only slower.")
        return 2
    WRITE_PROVENANCE = args.write_provenance
    LIBM_POW = args.libm_pow
    PORT_VALIDATION = args.port_validation
    if LIBM_POW and args.engine != "3.1.4":
        log("--libm-pow is engine 3.1.4 only: engine 3.5 already computes massBL through libm's "
            "pow (arrayprobe_uiops.sizedist._libm_pow). Drop --libm-pow, or --engine 3.1.4")
        return 2
    if WRITE_PROVENANCE:
        # The silent --jit no-op's shape, applied before the flag can mislead anybody: every
        # combination this driver cannot actually stamp is refused here, not accepted and dropped.
        if args.engine == "3.5":
            log("--write-provenance is not available under --engine 3.5, because it is "
                "redundant there: every v3.5 proc and sd, and every v3.5 SPEC decode, already "
                "carries arrayprobe_engine and arrayprobe_profile as netCDF global attributes, "
                "unconditionally, as every SODA-2 .pbp.nc and export does. The flag is the "
                "opt-in for the v3.1.4 engine alone, whose products carry no such attribute "
                "by default so they stay byte-faithful to MATLAB; drop it, or run "
                "--engine 3.1.4")
            return 2
        if args.chunks > 1 or args.jobs > 1:
            log("--write-provenance is serial-S3 only: arrayprobe.imgproc.merge_chunks does "
                "not forward it to _create_output, so a chunked or multi-file-parallel run "
                "would write an UNSTAMPED proc and report success; drop --chunks/--jobs, or "
                "drop --write-provenance")
            return 2
    # Before anything else: output paths, stamps and the S4 call all read the
    # preset-derived module constants, so the switch has to happen before the
    # first path is built rather than at the first use.
    if args.preset != ACTIVE.name:
        try:
            chosen = use_preset(args.preset)
        except KeyError as exc:
            log(str(exc.args[0]))
            return 2
        log(f"preset {chosen.name}: probe={chosen.probe} channel={chosen.orientation} "
            f"project={chosen.project} d_choice={chosen.d_choice} "
            f"sa_method={chosen.sa_method}")
        log(f"  provenance: {chosen.provenance}")
    global ATTRIBUTED_ANALYSIS_READY, ATTRIBUTED_ZARR, ATTRIBUTED_PARQUET
    ATTRIBUTED_ANALYSIS_READY, ATTRIBUTED_ZARR, ATTRIBUTED_PARQUET = True, False, False
    if args.config is not None:
        from arrayprobe.config import ConfigError
        try:
            args = _apply_config(args, ap, argv)
        except (ConfigError, FileNotFoundError) as exc:
            # The same one-line refusal `arrayprobe run` gives for the same file, not a
            # traceback out of load_config.
            log(f"--config {args.config}: {exc}. Nothing was run")
            return 2
        if args is None:
            return 2
    _iat_problem = _resolve_iat_source(args, argv)
    if _iat_problem is not None:
        log(f"REFUSED   {_iat_problem}. Nothing was run")
        return 2
    try:
        _stray = resolve_stray_pixel(args.engine, getattr(args, "stray_pixel", None),
                                     STRAY_PIXEL_DECLARED)
    except ValueError as exc:
        log(f"REFUSED   {exc}")
        return 2
    globals()["STRAY_PIXEL"] = _stray
    if args.engine == "3.5":
        # Written back so --jobs workers and the stage-3 re-exec receive the resolved value.
        args.stray_pixel = "on" if _stray else "off"
        log(f"stray-pixel {args.stray_pixel} (default on; --stray-pixel off for the stock path)")
    try:
        _ncar = resolve_ncar_2dc_timing(args.engine, getattr(args, "ncar_2dc_timing", None),
                                        NCAR_2DC_TIMING_DECLARED)
    except ValueError as exc:
        log(f"REFUSED   {exc}")
        return 2
    globals()["NCAR_2DC_TIMING"] = _ncar
    if args.engine == "3.5":
        # Written back so --jobs workers receive the resolved value.
        args.ncar_2dc_timing = "on" if _ncar else "off"
        if _probetype0():
            log(f"ncar-2dc-timing {args.ncar_2dc_timing} "
                "(default on; --ncar-2dc-timing off for the stock path)")
    if _ncar and _probetype0() and getattr(args, "chunks", 1) > 1:
        log(f"REFUSED   --chunks {args.chunks} with the NCAR 2DC timing conversion on: the "
            "chunk workers and their merge do not carry it. Run --chunks 1, or "
            "--ncar-2dc-timing off for the stock path. Nothing was run")
        return 2
    if "4" in str(args.stages):
        # S4's case inputs (tas_max, pecan_params), refused here rather than after S2/S3.
        _problem = _s4_case_inputs_problem()
        if _problem is not None:
            log(f"{_problem}. Nothing was run")
            return 2
    if args.engine == "3.5" and args.config is None and "--iat-file" not in set(argv):
        # Same rule as _apply_config's, for a direct run with no config: the argparse default
        # names the ORACLES fork's non-existent file, which v3.5 WOULD open (sizeDist.m:1179,
        # no existence check) rather than silently falling back, as v3.1.4's MISSING-file
        # idiom relies on. Here, before the probe-case refusals: below them, the iaThreshType
        # refusal read the default as a threshold file (type 1) and could never fire on a
        # direct run.
        args.iat_file = ""
    if PROBE_CASE is not None:
        # A case whose constants act only under one iaThreshType (a gate-on cold-cloud case,
        # D1) is refused without it: under the plain call no shattering block runs, and the
        # run would write the warm case's numbers under the cold case's name.
        _need = _v35().module("sizedist").REQUIRED_IA_THRESH_TYPE.get(PROBE_CASE)
        if _need is not None and IA_THRESH_TYPE != _need:
            log(f"--probe-case {PROBE_CASE} needs iaThreshType {_need}, and this run selects "
                f"{IA_THRESH_TYPE if IA_THRESH_TYPE is not None else 'none'}: set "
                f"[shattering].ia_thresh_type = {_need} in the --config file. Nothing was run")
            return 2
        # A case whose constants act under several iaThreshTypes (e.g. 1 with
        # a --iat-file, 2 with its own defaultIntArrThresh) is refused under any other: under
        # iaThreshType 0 no shattering block runs and the run would write stock numbers under
        # a gate-on name. The effective type is sizedist_stamp's own rule.
        _accept = _v35().module("sizedist").ACCEPTED_IA_THRESH_TYPES.get(PROBE_CASE)
        _effective = (IA_THRESH_TYPE if IA_THRESH_TYPE is not None
                      else 1 if args.iat_file else 0)
        if _accept is not None and _effective not in _accept:
            log(f"--probe-case {PROBE_CASE} acts only under iaThreshType "
                f"{' or '.join(str(t) for t in sorted(_accept))}, and this run selects "
                f"{_effective}: set [shattering].ia_thresh_type = 2 in the --config file, or "
                "name a threshold file with --iat-file. Nothing was run")
            return 2
    # After the config, so a [run].stages value is checked the same way as the flag. Every
    # stage test below is `"<n>" in args.stages`, so an unknown character ('9', '1', 'S3') or
    # an empty string matched none of them and the run printed ALL DONE, exit 0, having run
    # nothing.
    unknown_stages = sorted(set(str(args.stages)) - set(STAGE_CODES))
    if unknown_stages or not str(args.stages):
        log(f"--stages {args.stages!r} names no stage this driver runs"
            + (f" (unknown: {', '.join(unknown_stages)})" if unknown_stages else "")
            + f". Use any of {', '.join(STAGE_CODES)}: 2 decode, 3 image processing, "
            "4 size distribution, c combine -- e.g. --stages 234c. Nothing was run")
        return 2
    # A flag that only acts inside a stage this run does not include did nothing, silently:
    # `--borrowed-combine --stages 234` wrote no combined product and said ALL DONE.
    for flag, active, stage in (("--borrowed-combine", getattr(args, "borrowed_combine", False),
                                 "c"),
                                ("--chunks", (getattr(args, "chunks", 1) or 1) > 1, "3"),
                                ("--s2-jobs", (getattr(args, "s2_jobs", 1) or 1) > 1, "2")):
        if active and stage not in str(args.stages):
            log(f"NOTE      {flag} has no effect on this run: it acts in stage {stage}, and "
                f"--stages {args.stages} does not include it")
    if args.profile is not None:
        # After the config, so the command line wins -- the same precedence every other
        # --config value already has (_apply_config's own docstring), and the switch is
        # logged either way.
        rc_profile = _apply_profile_flag(args.profile)
        if rc_profile:
            return rc_profile
    if args.protective is not None:
        globals()["PROTECTIVE_MODE"] = args.protective
    try:
        globals()["PROTECTIVE_ON"] = resolve_protective()
    except ImportError:
        log("PROTECTIVE: this probe's protective corrections need the "
            "arrayprobe_enhancements package, which is not importable. Install it, or pass "
            "--protective off to run without them.")
        return 2
    except UnsupportedProbe:
        globals()["PROTECTIVE_ON"] = ()
    except RuntimeError as exc:
        log(f"PROTECTIVE: {exc}. Nothing was run (--protective off to run without them)")
        return 2
    if PROTECTIVE_ON:
        log(f"PROTECTIVE on: {', '.join(PROTECTIVE_ON)} (--protective off to skip)")
    elif s2_plan_is_lineage() and PROFILE.name in NO_ARCHIVE_PROFILES:
        # ARM 2D-S has no archived product: its one data-destroying-defect correction
        # is the regular time grid, applied at S4 (default_tas_grid), not a probe-level module.
        log("PROTECTIVE: no probe-level correction applies to 2D-S/HVPS; this profile has no "
            "archived product, so with an airspeed chain S4 sizes on the regular time grid "
            "(tas_grid_fix)")
    elif s2_plan_is_lineage():
        log("PROTECTIVE off (2D-S/HVPS probe type, kept on the archived-product lineage): "
            "no protective correction applies")
    if args.enhancements and args.config is None:
        # Refused HERE, before any stage runs, and with exit 2. Until 2026-09-20 this was
        # the only configuration refusal in the driver that came out as exit 1 -- and it
        # came out at the very END, after every stage had already run, from
        # apply_enhancements_to_run(). A caller scripting on the exit status could not tell
        # "you asked for something impossible" (2) from "a flight failed" (1), which is the
        # distinction every other refusal in this function keeps
        # (found by a cold end-to-end user test).
        log("--enhancements needs --config: the flag says whether to apply, the "
            "[enhancements] table in the file says which, and a run with no file names "
            "none. Nothing was run")
        return 2
    if getattr(args, "tas_ratio", "off") == "on":
        if args.engine == "3.1.4":
            log("--tas-ratio on is a UIOPS v3.5 input; --engine 3.1.4 has no TAS ratio. "
                "Nothing was run")
            return 2
        if args.tas_file is None and args.tas_source is None:
            log("--tas-ratio on needs the aircraft airspeed series: give --tas-source or "
                "--tas-file. Nothing was run")
            return 2
    if args.tas_file is not None and args.tas_source is not None:
        log("--tas-file and --tas-source both name where TAS comes from; name one. "
            "--tas-source resolves the airspeed source chain and writes its own aircraft file, "
            "which is what --tas-file would otherwise point at")
        return 2
    tas_from_probe = list(getattr(args, "tas_from_probe", None) or ())
    if tas_from_probe:
        if args.tas_source is not None:
            log("--tas-from-probe and --tas-source both name the series S4 sizes on; name one. "
                "Nothing was run")
            return 2
        try:
            probetype = s2_reader_for(PROBE).probetype
        except UnsupportedProbe:
            probetype = None
        if probetype != 1:
            log(f"--tas-from-probe is for a probe whose S2 writes no airspeed sidecar "
                f"(probetype 1: CIP, PIP); {PROBE}'s S2 writes its own <stem>.tas.csv, "
                "which this would overwrite. Nothing was run")
            return 2
        absent = [str(p) for p in tas_from_probe if not Path(p).is_file()]
        if absent:
            log(f"--tas-from-probe: not found: {', '.join(absent)}. Nothing was run")
            return 2
    globals()["TAS_FROM_PROBE"] = [str(Path(p).resolve()) for p in tas_from_probe]
    TAS_FILE = str(args.tas_file.resolve()) if args.tas_file is not None else None
    globals()["TAS_RATIO"] = getattr(args, "tas_ratio", "off") == "on"
    tas_grid = getattr(args, "tas_grid", None)
    if tas_grid is None:
        tas_grid = default_tas_grid(args.tas_source)
    args.tas_grid = tas_grid  # stage-3 re-exec and --jobs workers see the resolved grid
    if tas_grid == "regular" and args.tas_source is None:
        log("--tas-grid regular needs --tas-source: the added seconds take their airspeed from "
            "the chain's series, and a run without a chain has none. Nothing was run")
        return 2
    globals()["TAS_GRID"] = tas_grid
    globals()["ACCEPT_IMPLAUSIBLE"] = bool(getattr(args, "accept_implausible", False))
    globals()["ACCEPT_PRESET_MISMATCH"] = bool(getattr(args, "accept_preset_mismatch", False))
    drop_opted_out_tas_grid_fix(tas_grid, args.tas_source)
    TAS_SOURCE = args.tas_source
    TAS_SEARCH = list(args.tas_search)
    if args.tas_cutoff_mps is not None or args.tas_default_mps is not None:
        # A command-line flag with no --config: _apply_config never ran, so TAS_POLICY is
        # still its own default here -- build it fresh from whichever of the two flags was
        # given, the same "only what's named changes" rule _apply_config's own [tas] folding
        # follows when a config file is in play.
        TAS_POLICY = _mtf.TasPolicy(
            cutoff_mps=(args.tas_cutoff_mps if args.tas_cutoff_mps is not None
                       else TAS_POLICY.cutoff_mps),
            default_mps=(args.tas_default_mps if args.tas_default_mps is not None
                        else TAS_POLICY.default_mps))
    # One line, printed before any stage runs, naming the three things a reader of a log or a
    # terminal cannot otherwise get without opening source (R4s, engine named in stamps,
    # Option 1 of R4's memo):
    # which engine, which fidelity profile (post any --config override above), which campaign
    # preset. Every `.call` sidecar already answers this for a FINISHED product
    # (:func:`_engine_prefix`); this is the same answer at the moment a run starts.
    log(f"running   engine={ENGINE} profile={PROFILE.name} preset={args.preset}")
    if ENGINE == "3.1.4" and PROBE not in V314_PROBES:
        # The author's rule: "cip should only be processed with 3.5 and soda2, it has nothing
        # to do with 314 ... 3.1.4 shouldn't be used for anything except oracles 2ds/hvps
        # validation and port validation", restated as "V314 is only to test Oracle's 2DS and
        # HVPS pre-processing". An explicit `--engine 3.1.4` on a CIP was once accepted, which
        # is how `_decoded/cip160906_driver/` came to hold a driver-written
        # `engine=3.1.4 probe=CIP` stamp. Refused here, after preset/--config/--profile have
        # settled PROBE, so every route to a probe outside V314_PROBES (shipped preset,
        # campaign file, config) meets the same gate before S2.
        log(f"REFUSED   probe {PROBE} (probetype {s2_reader_for(PROBE).probetype}) under "
            f"--engine 3.1.4: the v3.1.4 engine runs only {', '.join(sorted(V314_PROBES))} "
            "(ORACLES validation and port validation). Process this probe with --engine 3.5 "
            "--profile stock-v3.5, or with arrayprobe-soda2.")
        return 2
    if ENGINE == "3.5" and s2_reader_for(PROBE).probetype == 3:
        # A Fast-2DC v2 raw file (RAF OAP preamble `<probe ... type="Fast2DC_v2">`, read from a
        # real CAESAR 2024 file) frames particles with a two-byte AA AA word and a 33.333 MHz
        # 44-bit clock; the v3.5 engine's v1 framing finds none and would write an empty
        # product without an error. Refused before any stage runs.
        # oap_read is v3.5-only, so the catalogue has no row for it: the package name
        # still comes from the selector, never from a literal import here.
        import importlib as _il  # aliased: main() binds a local `importlib` elsewhere

        _v35_pkg = _v35().dotted("imgproc").rpartition(".")[0]
        _oap_read = _il.import_module(_v35_pkg + ".oap_read")
        UnsupportedProbeVersion = _oap_read.UnsupportedProbeVersion
        refuse_unsupported_raf_probe = _oap_read.refuse_unsupported_raf_probe
        for raw in args.raw:
            if raw.suffix.lower() != ".2d" or not raw.is_file():
                continue
            try:
                refuse_unsupported_raf_probe(raw)
            except UnsupportedProbeVersion as exc:
                log(f"REFUSED   {exc}")
                return 2
    if ENGINE == "3.1.4" and args.chunks > 1 and PROFILE.time_in_seconds_from_tas:
        # The v3.1.4 --chunks ulp check (2026-09-23): under a profile that accumulates
        # Time_in_seconds from a TAS file
        # (imgProc_sm.m:724-778; STOCK_V314), each chunk restarts that running sum at its first
        # particle, so every particle after a seam differs from the serial run -- measured 2 ulp
        # at a constant TAS and 5.65 s at a varying one
        # (both measured 2026-09-23). v3.5 primes the seam
        # (prefix-priming); v3.1.4 is kept for ORACLES validation, whose profiles leave the flag
        # off and chunk byte-identically, so this combination is refused, not primed.
        log(f"--chunks is not available under --engine 3.1.4 with profile {PROFILE.name}: it "
            "builds Time_in_seconds from a TAS file by a running sum (imgProc_sm.m:724-778), "
            "which a chunk seam restarts, so the chunked output would differ from the serial "
            "run. Run serially, or use --engine 3.5, which primes the seam.")
        return 2
    if ENGINE != "3.5":
        # Regime-based thresholds, step 1: print the thresholds in force and where each came
        # from BEFORE any
        # stage runs -- the cheapest part of the whole fix and the one that would have caught
        # the ARM-ENA defect on day one (an unrecognised project silently getting ORACLES's own
        # tuning, with nothing printed or stamped to say so). Validated here, not deferred to
        # the S4 call several stages later, so a bad --area-ratio-z/--default-int-arr-thresh
        # fails before S2/S3 spend any time.
        try:
            resolved = _resolve_thresholds()
        except (ThresholdValidationError, ValueError) as exc:
            log(f"thresholds {exc}")
            return 2
        reject_set = _resolve_reject()
        reject_fields = ", ".join(f"{f.name}={getattr(reject_set, f.name)}"
                                  for f in dataclasses.fields(reject_set))
        log(f"thresholds tree={TREE} project={PROJECT} probe={PROBE}")
        log(f"  reject set (S3, profile={PROFILE.name}): {reject_fields}")
        if _reject_sources():
            log(f"  reject sources (S3): {reject_sources_text()}")
        log(f"  area_ratio_z (S4, 'z' reject) = {resolved.area_ratio_z.render()}")
        log(f"    {resolved.area_ratio_z.justification}")
        log("  default_int_arr_thresh (S4, shattering) = "
            f"{resolved.default_int_arr_thresh.render()}")
        log(f"    {resolved.default_int_arr_thresh.justification}")
    if ENGINE == "3.5":
        # Was `PROFILE is not STOCK_V35` until 2026-09-17 (CIP end-to-end). The v3.5 engine
        # reads only `reject_thresholds` from a profile, so pinning the identity
        # pinned the thresholds too -- and CIP results are wanted under
        # stock AND ORACLES-production thresholds side by side. The same refusal
        # had already parked CMP-2, where it would have confounded engine with
        # profile. `is_v35_flavoured` is the narrower test the gate always meant:
        # the profile must DECLARE v3.5 citations and its behaviour fields must
        # match stock-v3.5's, leaving reject_thresholds free. It still refuses
        # stock-v3.1.4 -- which is field-identical to stock-v3.5 by construction
        # and so indistinguishable by value, only by declaration.
        if not is_v35_flavoured(PROFILE):
            _named = getattr(args, "profile", None) is not None or PROFILE is not ORACLES_PRODUCTION
            _opts = "Name a profile with `--profile`, e.g. --profile stock-v3.5."
            if _named:
                log(f"--engine 3.5 needs a v3.5 profile; {PROFILE.name} is not one. {_opts}")
            else:
                log(f"--engine 3.5 needs a v3.5 profile; none was named, and the preset's "
                    f"profile {PROFILE.name} is not one (no profile is ever defaulted). {_opts}")
            return 2
        # --jit (arrayprobe_uiops.jit_kernels, tests/test_v35_imgproc_jit_identity.py) and
        # --s2-jobs (arrayprobe_uiops.spec.read_binary_spec_v35_parallel,
        # tests/test_v35_spec_parallel.py) are accepted under 3.5, each byte-identical to the
        # serial path; so is --s2-jobs for CIP/PIP .cip files
        # (arrayprobe.readers.dmt.read_binary_DMT_parallel, tests/test_dmt_parallel.py and
        # tests/test_run_flight_dmt_parallel.py). So is --diode-corrected: imgproc_sm_v35
        # takes shadow_diode= (tests/test_v35_shadow_diode.py).
        # The silent --jit no-op's sibling, found by the same sweep (Task 2): the S4
        # threshold-override
        # fields are read into these globals from EITHER --regime/--area-ratio-z/
        # --default-int-arr-thresh on the command line (:2961-2963 above) OR a --config file's
        # [thresholds] section (_apply_config, which writes the same globals directly rather
        # than args.regime/args.area_ratio_z/args.default_int_arr_thresh -- so this check has to
        # read the globals, not args, to see a config-sourced override too). Both paths land here
        # unconsumed: _resolve_thresholds()/thresholds_stamp() are only ever called
        # `if ENGINE != "3.5"` (see thresholds_stamp()'s own docstring -- "Engine 3.5 is
        # untouched: it reads no tree and no regime, its own sizeDist.m switch is a different
        # mechanism"), so before this check existed the override was accepted, silently unused,
        # and the only trace was a generic "n/a under --engine 3.5" line in the confirmation
        # panel that never named the flag the operator actually passed -- the same "accepted,
        # does nothing, says nothing" shape as the silent --jit no-op.
        # --area-ratio-z is NOT in this loop: v3.5's sizeDist.m:1162 has one literal, `.2`, and
        # `arrayprobe_uiops.sizedist.run(area_ratio_z=)` replaces it opt-in, default off, against
        # an Octave shadowing-copy oracle (tests/test_v35_area_ratio_z_oracle.py). It is
        # validated just below instead. --regime and --default-int-arr-thresh left the refusal
        # too: a regime's area_ratio_z and
        # default_int_arr_thresh reach sizedist.run's two opt-in keywords through
        # _v35_s4_thresholds() (user override > regime > the case's own value), and its reject
        # slots reach S3 through _resolve_reject(); tests/test_regime_v35_driver.py.
        if DEFAULT_IAT_OVERRIDE is not None:
            # The engine keyword's own range (arrayprobe_uiops.sizedist.run: finite, >= 0),
            # checked here so a bad value fails before S2/S3 spend any time.
            _t = DEFAULT_IAT_OVERRIDE
            if isinstance(_t, bool) or not (math.isfinite(_t) and _t >= 0.0):
                log(f"--default-int-arr-thresh must be a finite number of seconds >= 0 under "
                    f"--engine 3.5 (it replaces the case's defaultIntArrThresh); got {_t!r}")
                return 2
        for _name, (_value, _source) in _v35_s4_thresholds().items():
            if _name == "area_ratio_z" and _source.startswith("user:"):
                continue  # its own validated line follows
            log(f"thresholds {_name} (S4, v3.5) = {_value!r} ({_source})")
        if AREA_RATIO_Z_OVERRIDE is not None:
            # Validated here, before S2/S3 spend any time, with the range the engine's own
            # keyword enforces ([0, 1]; 0 is the gate off, which v3.1.4's (0, 1] refuses).
            _z = AREA_RATIO_Z_OVERRIDE
            if not (math.isfinite(_z) and 0.0 <= _z <= 1.0):
                log(f"--area-ratio-z must be a finite number in [0, 1] under --engine 3.5 "
                    f"(v3.5 sizeDist.m:1162; 0 turns the gate off); got {_z!r}")
                return 2
            log(f"thresholds area_ratio_z (S4, 'z' reject, v3.5 sizeDist.m:1162) = {_z!r} "
                f"(user:{AREA_RATIO_Z_SOURCE}); stock .2 when unset")
        # --chunks IS available under 3.5 since 2026-09-17 (CIP end-to-end) -- for the
        # probetypes whose written values are record-local, and since 2026-09-18 for
        # probetype 2 as well, by priming. The gate is asked here, before S2 runs for
        # hours, rather than at the merge after S3 has already spent them.
        if args.chunks > 1:
            v35_imgproc = _v35().module("imgproc")
            timing = v35_imgproc.PROBES_V35[PROBE].timing
            primable = timing in v35_imgproc.PRIMABLE_TIMINGS_V35
            if timing not in v35_imgproc.CHUNKABLE_TIMINGS_V35 and not primable:
                log(f"--chunks is not available for {PROBE} under --engine 3.5: it is probetype "
                    f"{v35_imgproc.PROBES_V35[PROBE].probetype} ({timing!r} timing), and "
                    "imgProc_sm.m:1131-1180 accumulates Time_in_seconds across the WHOLE file, "
                    "so a chunk restarts that running sum and every particle after a seam gets a "
                    "different time -- measured, 53 of 99 particles on the 25-record 2DS "
                    "fixture. Not a gap to widen a tolerance over: the chunked result would be "
                    "different output. Run this probe serially, or use --jobs to spread FILES. "
                    f"Chunkable under 3.5: {sorted(v35_imgproc.CHUNKABLE_TIMINGS_V35)} "
                    "(CIP/PIP, 2DC/2DP, Fast2DC); chunkable when primed: "
                    f"{sorted(v35_imgproc.PRIMABLE_TIMINGS_V35)}.")
                return 2
            # The one primable case that still cannot chunk, refused here for the same
            # reason -- before S2, not at the merge.
            if primable and V35_CALL.i_qc == 1:
                log(f"--chunks is not available for {PROBE} under --engine 3.5 with iQC=1: the "
                    "chunk seam is primed by a prefix scan that reads headers only, and "
                    "qc_image (imgProc_sm.m:801-846) can change an image's width, so "
                    ":850-853's width-mismatch return can fire mid-file where the scan cannot "
                    "see it. Run iQC=1 serially, or run with iQC=0.")
                return 2
        if "c" in args.stages and not args.borrowed_combine:
            log("stage c under --engine 3.5 needs [combine].borrowed = true (or "
                "--borrowed-combine): no stock v3.5 release has a combine; the ORACLES fork's "
                "combine_sizedist.m is borrowed, opt-in, and labelled so in the product's .call")
            return 2
        # A direct run with no config and no --iat-file had its argparse default cleared above,
        # before the probe-case refusals read it.
        if args.iat_file and not Path(args.iat_file).is_file():
            log(f"--iat-file {args.iat_file!r} does not exist: v3.5's sizeDist.m:95-110 has no "
                "existence check and :1179 opens the file (MATLAB would die); the v3.1.4 fork's "
                "MISSING-file idiom is not a v3.5 call. Omit [shattering] (iaThreshType 0) or "
                "name a real file")
            return 2
    elif PROFILE is STOCK_V35:
        log("profile stock-v3.5 describes the v3.5 tree; run it with --engine 3.5, or name "
            "stock-v3.1.4")
        return 2
    elif args.borrowed_combine:
        log("--borrowed-combine applies to --engine 3.5 only; --engine 3.1.4 already runs the "
            "archived product's own combine")
        return 2
    if "3" in args.stages:
        # The port's own gate (imgproc.py:512), asked here so the answer comes
        # before preflight rather than after S2 has run for hours.
        needs_tas = (constants.imgproc_config(PROBE).needs_tas_file
                     and PROFILE.time_in_seconds_from_tas)
        if needs_tas and TAS_FILE is None and TAS_SOURCE is None:
            # TAS_SOURCE resolves an aircraft file itself, per raw file, in the serial loop
            # below (after S2, before S3) -- TAS_FILE is legitimately still None here in that
            # case, not a missing input.
            log(f"profile {PROFILE.name} builds Time_in_seconds from an aircraft TAS file "
                "(imgProc_sm.m:183-185, varargin{1}) and none was given: pass --tas-file, "
                "--tas-source, or set [run].tas_file -- nothing is assumed")
            return 2
        if TAS_FILE is not None and not needs_tas:
            log(f"--tas-file given, but profile {PROFILE.name} on {PROBE} never reads one "
                "(time_in_seconds_from_tas=False: imgProc_sm.m:365 hard-wires 170 m/s); "
                "drop it rather than carry an input the run ignores")
            return 2
        if TAS_FILE is not None and not Path(TAS_FILE).is_file():
            log(f"--tas-file {TAS_FILE} does not exist")
            return 2
        if TAS_FILE is not None and len({flight_group(r.stem) for r in args.raw}) > 1:
            log("--tas-file names ONE aircraft file but the raw files span more than one "
                "flight; the file carries HHMMSS only (imgProc_sm.m:726-727), so a second "
                "flight would silently read the first flight's TAS. One flight per run")
            return 2
    if args.diode_corrected and args.chunks > 1:
        # stage3_corrected() has no chunks parameter and always runs its one
        # _imgproc_sm_chunk() call serially -- silently ignoring --chunks
        # here would produce correct output slower and undocumented, rather
        # than the fast chunked run the flag promised. Fail loud instead.
        # Exit 2 since 2026-09-20, not 1: this fires before preflight, nothing has run,
        # and it is a refusal of the command line -- the same class as every other
        # refusal in this function. It was the second of two places where a refusal
        # came out with the code a FAILED FLIGHT uses (the other was --enhancements
        # without --config, above), which left a script unable to tell "you asked for
        # something impossible" from "the run broke".
        # THE CONVENTION, now true of every path out of main(): 2 = the command line or
        # config was refused and nothing ran; 1 = something ran, or was checked against
        # the data (preflight), and failed; 0 = it worked.
        log("--diode-corrected does not support --chunks (stage3_corrected() "
            "has no chunked path yet) -- drop one flag or the other")
        return 2
    if (ENGINE == "3.5" and not args.diode_corrected and "3" in args.stages
            and not getattr(args, "protective_worker", False)):
        # Masking
        # stays off by default on every probe, and a v3.5 run says how to find a mask. Printed
        # only; the .call stamp of an unmasked run is unchanged.
        log("diode masking: off (suggested: run `arrayprobe tune diodes` on this flight's "
            "proc file)")
    args.out.mkdir(parents=True, exist_ok=True)

    ok = preflight(args.raw, args.out, args.iat_file,
                   diode_corrected=args.diode_corrected,
                   accept_unstamped=args.accept_unstamped)
    # The confirm-before-run panel is what --dry-run was always for: show the operator the
    # whole run without
    # performing it. Printed here (never asked) so the two paths cannot drift apart -- a dry run
    # shows exactly the block a real run asks about.
    _resolved = _resolve_thresholds() if ENGINE != "3.5" else None
    if args.dry_run:
        for _line in confirmation_lines(args, _resolved):
            log(_line)
        return 0 if ok else 1
    if not ok:
        log("aborting; fix the above or pass a smaller file list")
        return 1
    # The gate: after preflight (so nothing is confirmed that would have failed anyway) and
    # before the first stage spends any time.
    if needs_confirmation(args):
        rc_confirm = confirm_or_declare(args, _resolved)
        if rc_confirm:
            return rc_confirm

    started = time.time()
    # Raw-input inventory: before any decode, refuse an empty raw file unless --accept-flagged
    # and warn about a trailing partial record. Reads raw bytes only; the flags reach the S2
    # .call, no product.
    globals()["ACCEPT_FLAGGED"] = bool(getattr(args, "accept_flagged", False))
    if "2" in str(getattr(args, "stages", "2")) and inventory_preflight(args.raw):
        return 2
    rc = 0
    implausible_seen = False
    # Load record: in the PARENT only. A --jobs worker (always passed --_protective-worker) is the
    # parent's timed work, excluded from its record as a descendant, as are --chunks
    # subprocesses (which never reach this line: --_run-chunk returns above). The record is a
    # sidecar, never part of any product or .call stamp, and the recorder turns any error of
    # its own into UNRECORDED rather than failing the run.
    _stems = [r.stem for r in args.raw]
    _load_name = _stems[0] if len(_stems) == 1 else f"{_stems[0]}+{len(_stems) - 1}"
    _record_off = load_record_switched_off()
    if _record_off and not getattr(args, "protective_worker", False):
        log(f"LOAD RECORD: OFF -- {LOAD_RECORD_ENV}=off; this run's timings are not quotable")
    with LoadRecorder(Path(args.out) / f"{_load_name}.load.json", interval=LOAD_INTERVAL_S,
                      label=f"run_flight {' '.join(_stems)} stages={args.stages}",
                      enabled=not (getattr(args, "protective_worker", False) or _record_off)):
        if args.jobs > 1:
            rc = run_parallel(args, args.raw)
        else:
            for raw in args.raw:
                if not raw.is_file():
                    log(f"MISSING   {raw}")
                    rc = 1
                    continue
                log(f"=== {raw.name} ===")
                diodes = (SHADOW_DIODE_OVERRIDES.get(raw.stem)
                          if args.diode_corrected else None)
                try:
                    # Does S3 need to open the decode this run? If its proc file is
                    # already current, no -- see stage2's `enforce_provenance`.
                    proc_current = output_state(
                        proc_path(raw.stem, args.out, diodes),
                        proc_call_label(shadow_diode=diodes)) == "current"
                    image = (stage2(raw, args.out, args.accept_unstamped,
                                    enforce_provenance=not proc_current,
                                    s2_jobs=args.s2_jobs,
                                    worker_stall_min=args.worker_stall_min)
                             if "2" in args.stages
                             else image_path(raw.stem, args.out))
                    if "2" in args.stages and output_state(
                            image, image_call_label()) != "current":
                        log(f"FAILED    {raw.name}: S2 did not leave a current "
                            f"{image.name} -- a prerequisite was silently missing")
                        rc = 1
                        continue
                    if TAS_FROM_PROBE:
                        # Author decision 2026-09-24: before S3 and whatever --stages says, so S4
                        # and the protective set's own S4 both find the same airspeed file.
                        write_tas_from_probe(args.out, raw.stem)
                    if TAS_SOURCE is not None:
                        # Airspeed source chain: resolve the TAS chain for THIS flight file
                        # (each raw file
                        # gets its own date, so its own chain), after S2 (its <stem>.tas.csv, the
                        # probe tier's input and the clock the other tiers must share) and before
                        # S3 (which reads TAS_FILE when the profile needs one).
                        tas_res = _tas_sources.resolve_chain(
                            TAS_SOURCE, yyyymmdd="20" + raw.stem[4:10], search_dirs=TAS_SEARCH,
                            probe_csv=args.out / f"{raw.stem}.tas.csv", policy=TAS_POLICY)
                        for tas_line in tas_res.lines:
                            log(tas_line)
                        tas_chain_path = args.out / f"{raw.stem}.tas_{tas_res.tier}.cdf"
                        _tas_sources.write_chain_file(tas_chain_path, tas_res)
                        if PROFILE.time_in_seconds_from_tas:
                            TAS_FILE = str(tas_chain_path)
                        TAS_CHAIN = tas_res
                    if args.diode_corrected:
                        if raw.stem not in SHADOW_DIODE_OVERRIDES:
                            log(f"SKIP      {raw.name}: no SHADOW_DIODE_OVERRIDES entry, "
                                f"nothing to correct")
                            continue
                        proc = stage3_corrected(
                            image, args.out, args.accept_unstamped
                        ) if "3" in args.stages else proc_path(raw.stem, args.out, diodes)
                        if proc is None:
                            continue
                    else:
                        proc = (stage3(image, args.out, args.chunks, args.accept_unstamped,
                                      args.worker_stall_min,
                                      resume_chunks=getattr(args, "resume_chunks", False))
                                if "3" in args.stages
                                else proc_path(raw.stem, args.out))
                    if "3" in args.stages and output_state(
                            proc, proc_call_label(shadow_diode=diodes)) != "current":
                        log(f"FAILED    {raw.name}: S3 did not leave a current "
                            f"{proc.name} -- a prerequisite was silently missing")
                        rc = 1
                        continue
                    if "4" in args.stages:
                        sd_target = stage4(proc, raw.stem, args.out, args.iat_file,
                                            diodes, args.accept_unstamped)
                        if output_state(sd_target, sd_call_label(
                                args.iat_file, shadow_diode=diodes)) != "current":
                            log(f"FAILED    {raw.name}: S4 did not leave a current "
                                f"{sd_target.name} -- a prerequisite was silently missing "
                                "(see the S4 SKIP line above for which one)")
                            rc = 1
                except ImplausibleProduct as exc:
                    log(f"REFUSED   {raw.name}: {exc}")
                    implausible_seen = True
                    rc = 1
                except (UnverifiableProvenance, UnsupportedProbe) as exc:
                    # UnsupportedProbe joins this branch (2026-09-17) rather than the
                    # catch-all: both are the runner declining to produce output it
                    # cannot vouch for, and REFUSED is the honest label for a probe
                    # this driver's S2 cannot name a file for. rc is 1 either way.
                    # NOT folded into the catch-all below.  A batch run tolerating one
                    # bad file is right for a decode that failed; this is the runner
                    # declining to produce output it could not vouch for, and the run
                    # must exit non-zero so a script or an overnight queue notices
                    # rather than reporting a flight "done" with files missing.
                    log(f"REFUSED   {raw.name}: {exc}")
                    rc = 1
                except Exception as exc:                 # noqa: BLE001 -- a batch run
                    # One bad file must not take the other four down with it; the
                    # whole point of an overnight run is that the morning has results.
                    # It still must not report success: the regression-admission
                    # incident (2026-09-10) was exactly this branch leaving rc at 0.
                    log(f"FAILED    {raw.name}: {type(exc).__name__}: {exc}")
                    import traceback
                    traceback.print_exc()
                    rc = 1

        if "c" in args.stages:
            groups: dict[str, list[str]] = {}
            for raw in args.raw:
                groups.setdefault(flight_group(raw.stem), []).append(raw.stem)
            for date, stems in sorted(groups.items()):
                try:
                    product = stage_combine(stems, args.out, args.allow_mixed_config,
                                            args.accept_unstamped, args.diode_corrected,
                                            borrowed=args.borrowed_combine,
                                            attributed=getattr(args, "attributed", False))
                    # stage_combine's zero-file and partial-stitch cases are
                    # legitimate mid-campaign states when THIS run never asked for
                    # S4 on these stems (a bare "--stages c" re-combine, catching up
                    # on whatever prior runs have finished). They are this run's own
                    # failure when "4" was requested -- the stems above were just
                    # supposed to reach S4 a few lines up.
                    if "4" in args.stages:
                        if product is None:
                            log(f"FAILED    combine {date}: no sd.* file was ready to "
                                "stitch, though this run just requested S4 for these "
                                "raw files")
                            rc = 1
                        elif _files_stitched(product) != len(stems):
                            # Mirrors stage_combine's own "S4c PARTIAL" log line -- that
                            # line already said which stems are missing; this is what
                            # makes the omission visible to something other than a
                            # human reading the log (an automated completeness check).
                            log(f"FAILED    combine {date}: {product.name} stitched "
                                f"{_files_stitched(product)} of {len(stems)} file(s) "
                                "this run just requested S4 for")
                            rc = 1
                    if getattr(args, "attributed", False) and product is not None \
                            and not attributed_sibling_of(product).exists():
                        # A requested artefact that was not written. `write_attributed`
                        # deliberately swallows its own exception -- the faithful product is
                        # already on disk and a metadata step must not lose a finished flight --
                        # but swallowing it into rc=0 told a user scripting on exit status that
                        # the sibling exists. From 2026-09-21 it does not: rc=1, the same value
                        # every other "this run asked for a file and did not get it" case returns
                        # (the two FAILED branches above, and MISSING/FAILED on a raw file).
                        # NOT 2: 2 is this driver's configuration refusal -- a bad --preset, an
                        # unreadable config, a flag combination it will not run (`main`'s early
                        # returns) -- and it is returned BEFORE any work.
                        # The flags here were valid and the run happened; what failed is the work.
                        #
                        # The two sides of the check come from different places: the request is the
                        # parsed flag, the outcome is the filesystem, and the path is asked of the
                        # exporter rather than spelled out here.
                        log(f"FAILED    attributed {date}: --attributed was requested and "
                            f"{attributed_sibling_of(product).name} was not written (the "
                            "'S4c ATTRIBUTED skipped' line above says why). The faithful product "
                            f"{product.name} is written and is unaffected.")
                        rc = 1
                except UnverifiableProvenance as exc:
                    log(f"REFUSED   combine {date}: {exc}")
                    rc = 1
                except Exception as exc:                 # noqa: BLE001 -- see above
                    log(f"FAILED    combine {date}: {type(exc).__name__}: {exc}")
                    import traceback
                    traceback.print_exc()
                    rc = 1

        protective_now = protective_to_apply(args)
        protective_stems = [r.stem for r in args.raw]
        if protective_now and "4" not in args.stages:
            # Plan of record 2026-09-24 section 1 item 4: a protective proc-stage correction
            # (particle_time_glitch_fix) rebuilds its sd through the port's own S4, which needs
            # <stem>.tas.csv -- and a CIP run of --stages 23 failed here on a file its own S2 never
            # writes. A run that did not ask for S4 does not get one through the back door: the set
            # is deferred to the run that does, which applies it to the proc this run left.
            log(f"PROTECTIVE deferred: {', '.join(protective_now)} rebuild S4, and --stages "
                f"{args.stages} does not include 4; they apply on the run that does")
            protective_now = ()
        elif protective_now:
            missing = [s for s in protective_stems
                       if not (Path(args.out) / f"{s}.tas.csv").exists()]
            for s in missing:
                # Its faithful S4 already logged SKIP and FAILED for the same missing file; a second
                # failure out of the protective chain would say nothing new.
                log(f"PROTECTIVE skip {s}: no {s}.tas.csv, so neither S4 nor the protective "
                    "set's S4 can run (--tas-from-probe supplies one for a CIP/PIP)")
            protective_stems = [s for s in protective_stems if s not in missing]
            if not protective_stems:
                protective_now = ()
        if getattr(args, "enhancements", False) or protective_now:
            # The data-destroying-defect corrections run here too, with or without
            # --enhancements, so a `protective=on:` stamp never names a correction that did not
            # run. Enhancements run last: after every stage and every worker, in the PARENT
            # only, so a
            # --jobs run applies each correction once rather than racing N workers onto the
            # same <stem>.enh.*.nc (see _spawn_worker's comment). Runs even when rc is
            # already 1 -- a batch where one file failed still has the others' products,
            # and locate_outputs refuses anything unstamped or stamped for another engine
            # rather than guessing.
            stems_now = ([r.stem for r in args.raw] if getattr(args, "enhancements", False)
                         else protective_stems)
            if apply_enhancements_to_run(args, stems_now, protective=protective_now):
                rc = 1
        if (getattr(args, "faithful_arm", None) is not None
                and not getattr(args, "protective_worker", False)):
            if write_faithful_arm(args, [r.stem for r in args.raw]):
                rc = 1
        if not getattr(args, "protective_worker", False) and args.raw:
            if ATTRIBUTED_ZARR:
                write_attributed_zarr(Path(args.out))
            if ATTRIBUTED_PARQUET:
                write_attributed_parquet(Path(args.out))
            write_outputs_manifest(Path(args.out), [r.stem for r in args.raw], since=started)

    # The outcome, not just the elapsed time. Until 2026-09-18 this line read
    # "ALL DONE in X min" unconditionally -- including immediately after a fatal
    # error caught by the handlers above, which set rc=1 and then fell through to
    # here. A sweep of 274 launch logs found that exact sequence three times, once
    # after `RuntimeError: No space left on device` killed a 5.3-hour batch: the
    # traceback, then "ALL DONE in 29.4 min". So "grep ALL DONE" was not a valid
    # completion check, and twice this week a run was reported finished on the
    # strength of a log line or a file's mtime when it had died (the stamping audit's family:
    # the cheap wrong check was available and the right one was not).
    #
    # The word DONE is kept so existing greps still match the successful case, and
    # the failing case now says so in the same line rather than requiring the
    # reader to have seen the traceback scroll past.
    elapsed = (time.time() - started) / 60
    if rc:
        log(f"ALL DONE WITH FAILURES in {elapsed:.1f} min -- rc={rc}; "
            "at least one flight above logged FAILED or REFUSED, and this run's "
            "outputs are incomplete. Read the FAILED/REFUSED lines, not this one.")
    else:
        log(f"ALL DONE in {elapsed:.1f} min")
    return 2 if implausible_seen else rc


def _run_with_wakelock(fn, *a, **kw):
    """Wrap a run in :func:`keep_awake` and say in the log which way it went.

    Saying so matters: a run that silently failed to take the lock would look
    exactly like one that took it, right up until the next 13-hour gap.
    """
    with keep_awake() as taken:
        log("sleep inhibited for the duration of this run" if taken
            else "NOT inhibiting sleep (not Windows, or the request was refused)"
                 " -- a long run may lose wall-clock to a suspend")
        return fn(*a, **kw)


def resolve_run_probe_case(name: str):
    """The registered probe case ``name`` for this run, or ``UnknownProbeCase``: main()'s
    preflight resolver. The shipped ``v35-2ds-ladder-fix`` registers on first use, through the
    same helper ``tune settings`` uses (``probe_cases.resolve_shipped_probe_case``), which the
    catalogued ``sizedist`` re-exports as it does the other probe-case names."""
    return _v35().module("sizedist").resolve_shipped_probe_case(name)


if __name__ == "__main__":
    # The wake lock wraps the entry point rather than main() itself, so that
    # importing this module for a test never touches the OS power state.
    raise SystemExit(_run_with_wakelock(main))
