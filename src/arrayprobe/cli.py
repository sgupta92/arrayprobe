# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe`` -- the command-line front door.

Each subcommand is an argparse wrapper around one already-validated
function -- this module adds no new pipeline logic, only argument parsing
and dispatch:

``run``
    One line: a configuration file -> the whole chain of the engine the file names
    (``[run].engine``, 3.1.4 or 3.5), via :mod:`arrayprobe.driver.run_flight`; every choice --
    engine, profile, campaign preset -- is named in the file (:mod:`arrayprobe.config`).
``reprocess``
    A proc/sd product -> the same stage re-run exactly as its ``.call`` stamp records, and a
    verdict on whether the fresh file is identical (:mod:`arrayprobe.driver.reprocess`).
    Refuses unless the driver regenerates the recorded stamp exactly.
``read-binary``
    A raw OAP file -> a decoded netCDF, via one of the four raw-format
    readers (:mod:`arrayprobe.readers.spec`/``dmt``/``pms``/``sea``).
``imgproc``
    A decoded image file -> a per-particle proc file
    (:func:`arrayprobe.imgproc.imgproc_sm`).
``sizedist``
    A proc file -> a one-second size-distribution file
    (:func:`arrayprobe.sizedist.run`). Reads the TAS/time arrays from a
    ``.tas.csv`` sidecar via :func:`arrayprobe.readers.tasinfo.load_tas_info`.
``combine``
    Several ``sd`` files from one flight -> the single stitched product
    (:func:`arrayprobe.combine.combine_sizedist`).

**The per-stage subcommands stay explicit-argument, on purpose.** Each one
takes every fidelity-sensitive parameter (``profile``, ``tree``, ``d_choice``,
``sa_method``, ...) as a required argument, never a default -- matching the
same "no default silently picks a side" rule :mod:`arrayprobe.profiles`
states for :class:`~arrayprobe.profiles.FidelityProfile`. A general front door
must never default a fidelity choice; getting one of these wrong is exactly
the failure mode this module refuses to make easy.

``run`` is the same rule applied to a *file* instead of a command line: it
drives :mod:`arrayprobe.driver.run_flight` (the batch driver -- probe,
orientation and every fidelity-sensitive constant fixed in one place, on
purpose, so a wrong value can't silently produce a plausible answer) but
every choice still has to be *named*, this time in the config file rather
than as flags. :mod:`arrayprobe.config` bounds what a file may do to
selection only -- it cannot set a threshold, only choose
among documented profiles and presets -- so this is not a loosening of the
explicit-argument rule above, it is the rule's file-shaped form.

``intarr-threshold``
    A per-particle file -> the inter-arrival threshold file ``sizeDist``
    reads as its optional twelfth argument
    (:mod:`arrayprobe.intarr_analysis`). The rest of the same MATLAB script
    is reachable opt-in, every flag default OFF: ``--plot`` (B8's axis
    reproduced unless ``--fix-b8``), ``--mat-workspace`` and
    ``--extra-thresholds-json``.
``compare``
    Two output files -> a join-then-diff report by tolerance class
    (:mod:`arrayprobe.compare`). The handler is below, and there is one of it.
    A second copy would be a
    second place for the acceptance rule
    to drift.
``gallery``
    A flight's particles -> a directory of rendered images with index pages
    (:mod:`arrayprobe.render`). Visualisation changes no computed number, so
    it is core rather than an enhancement -- the same reason
    :mod:`arrayprobe.triage_server` is.
``triage``
    Starts the review server (:mod:`arrayprobe.triage_server`).

    That module's own ``main`` says it is deliberately **not** a console
    script, because it needs a decoded directory to point at and a bare
    command "makes it look like a command that works anywhere". That
    objection is answered rather than overruled: ``--decoded-dir`` is
    **required** here, with no default, so the subcommand cannot be run
    somewhere it would silently find nothing. ``python -m
    arrayprobe.triage_server`` keeps its ``../_decoded`` default and is
    unchanged.
``validate``
    Diagnostic checks on files the pipeline already wrote. Nothing here
    computes a pipeline number or writes one; every check reads output and
    reports a comparison. Added 2026-09-10 so the checks the literature asks
    for are reachable from the front door rather than only from a script in
    ``scripts/`` that a new user has no reason to find -- the same argument
    that put ``read-binary`` here rather than leaving it an import.

    ``validate timing-closure``
    (:mod:`arrayprobe.timing_closure`, McFarquhar et al. 2017 p. 11.20). It
    **reports and does not verdict**: no published tolerance exists for how
    closely the probe's particle clock and its housekeeping clock should
    agree, so the exit status is 0 on any successful comparison. A check
    that invented a threshold would be worse than no check, because the
    threshold would then be cited.
``view``
    Diagnostic views of the port's own outputs (:mod:`arrayprobe.diagnostic_views`):
    ``view strip`` draws whole image records with their particles in place, coloured by
    reject code or habit; ``view second`` sets one second of two ``sd`` files side by side,
    bin by bin, and lists the particles behind the differing cells. Visualisation only, so
    core, like ``gallery``.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np

from . import __version__, provenance
from . import combine as combine_module
from . import compare as compare_module
from . import render as render_module
from . import timing_closure as timing_closure_module
from . import triage_server as triage_module
from . import validate_by_condition as by_condition_module
from ._v314_lazy import ABSENT_MESSAGE as _V314_ABSENT_MESSAGE
from ._v314_lazy import engine_present as _v314_engine_present
from ._v314_lazy import lazy_module as _lazy_module
from .matlab_compat import MatlabIndexError
from .profiles import profile as lookup_profile
from .readers import dmt, pms, sea
from .readers.tasinfo import load_tas_info

# v3.1.4 engine modules are absent from the public distribution: load on first use.
imgproc_module = _lazy_module("arrayprobe.imgproc")
sizedist_module = _lazy_module("arrayprobe.sizedist")
spec = _lazy_module("arrayprobe.readers.spec")

__all__ = ["build_parser", "main"]

_FORMATS = {"spec": spec, "dmt": dmt, "pms": pms, "sea": sea}

_RUN_FLIGHT_MODULE = "run_flight"


def _load_reprocess():
    """``arrayprobe.driver.reprocess``, also bound in ``sys.modules`` as
    ``_arrayprobe_cli_reprocess`` so repeated calls share one object. It loads its OWN private
    copy of the driver per call, so it never touches the shared ``run_flight`` module the tests
    and ``run`` bind to."""
    import importlib
    name = "_arrayprobe_cli_reprocess"
    mod = sys.modules.get(name)
    if mod is not None:
        return mod
    mod = importlib.import_module("arrayprobe.driver.reprocess")
    return sys.modules.setdefault(name, mod)


def _load_run_flight():
    """The batch driver, ``arrayprobe.driver.run_flight``, as the one module object bound to
    ``sys.modules["run_flight"]``.

    The tests and the ``scripts/run_flight.py`` shim (a source checkout only) bind the driver
    under that name, so when it is already
    loaded this command returns that object and shares its ``PROFILE`` and ``ENGINE`` globals;
    otherwise it imports the package module and binds it there, so exactly one object answers
    to the name. The driver ships inside the package, so an installed wheel or sdist reaches it
    with no ``scripts/`` directory present.
    """
    import importlib
    mod = sys.modules.get(_RUN_FLIGHT_MODULE)
    if mod is not None:
        return mod
    mod = importlib.import_module("arrayprobe.driver.run_flight")
    return sys.modules.setdefault(_RUN_FLIGHT_MODULE, mod)


def _profile_names() -> list[str]:
    """Every fidelity profile name the CLI accepts: the shipped ones and any a fork registered."""
    from .profiles import PROFILES
    return sorted(PROFILES)


def _check_read_binary(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """``--profile`` is required with ``--format spec`` and refused with the other formats.

    argparse cannot express a requirement that depends on another option's value, so it is
    enforced here, through ``parser.error`` -- the same usage line and exit status 2 as any
    other missing argument -- and the message lists the names a user can give.
    """
    names = ", ".join(_profile_names())
    if args.format == "spec" and not args.profile:
        parser.error(f"read-binary --format spec needs --profile (no default); one of: {names}")
    if args.format != "spec" and args.profile:
        parser.error(f"read-binary --format {args.format} takes no --profile: only the SPEC "
                     f"reader reads one, and a profile given here would be ignored")
    if args.profile and args.profile not in _profile_names():
        parser.error(f"unknown --profile {args.profile!r}; one of: {names}")
    if args.format != "spec" and args.channels is not None:
        parser.error(f"read-binary --format {args.format} takes no --channels: only the SPEC "
                     f"reader splits H and V, and a channel given here would be ignored")
    if args.format == "spec" and args.channels is None:
        args.channels = "HV"


def _offered_engines() -> tuple[str, ...]:
    """The ``--engine`` values a per-stage command offers: ``3.1.4`` only where it is installed.

    A distribution without the v3.1.4 engine offers ``3.5`` alone, so its ``--help`` never
    advertises an engine it cannot run (engine-exposure Option 2, author 2026-10-15).
    """
    return ("3.1.4", "3.5") if _v314_engine_present() else ("3.5",)


def _engine_value(text: str) -> str:
    """``type=`` for every ``--engine``: accepts the offered values and ``3.1.4`` by name.

    ``3.1.4`` is accepted even where absent so that :func:`main` prints ``ABSENT_MESSAGE``
    and exits 2, instead of argparse's bare "invalid choice". Anything else is refused here.
    """
    if text in _offered_engines() or text == "3.1.4":
        return text
    raise argparse.ArgumentTypeError(
        f"invalid choice: {text!r} (choose from {', '.join(_offered_engines())})")


def _engine_metavar() -> str:
    return "{" + ",".join(_offered_engines()) + "}"


def _stage_engine_help() -> str:
    if _v314_engine_present():
        return ("which UIOPS engine this stage runs: 3.1.4 (the validation engine) or 3.5. "
                "Required, with no default, so no run silently picks a side; recorded in the "
                ".call stamp. A top-level --uiops-version naming the other engine is refused, "
                "never overridden.")
    return ("which UIOOPS engine this stage runs: 3.5. Required, with no default, so no run "
            "silently picks a side; recorded in the .call stamp.")


def _add_stage_engine(p: argparse.ArgumentParser) -> None:
    """``--engine`` for read-binary, sizedist and combine (review item 2, 2026-09-26).

    Required, as the batch driver's ``--engine`` is: omitting it exits 2.
    """
    p.add_argument("--engine", required=True, type=_engine_value, metavar=_engine_metavar(),
                   help=_stage_engine_help())


def _stage_engine(args: argparse.Namespace) -> str:
    """The engine a per-stage command runs: its required ``--engine``."""
    return str(args.engine)


def _add_read_binary(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "read-binary",
        help="decode a raw OAP file into netCDF",
        description="Dispatches to one of the four raw-format readers by "
                    "--format, explicitly -- never inferred from the file "
                    "name or extension, since a wrong guess would silently "
                    "decode a file as the wrong format. These are the "
                    "readers of the v3.1.4 validation engine, which this distribution does "
                    "not include; the dmt, pms "
                    "and sea readers are the same code under v3.5, whose "
                    "MATLAB is byte-identical. To process data on the default "
                    "engine, use `arrayprobe run <config.toml>`.",
    )
    p.add_argument("infile", help="raw binary file")
    # The help below is wrong for pms and sea (see _read_binary_outputs); it is left as is
    # because docs/13-cli-reference.md is generated from it, and the page and the
    # help change together (python docs/_build/clidoc.py).
    p.add_argument("outfile", help="output path: spec writes <outfile>.H.cdf / <outfile>.V.cdf, "
                                   "pms <outfile>.2dc.cdf / .f2dc.cdf / .2dp.cdf, sea "
                                   "<outfile>.CIP.cdf / .2DC.cdf; dmt writes exactly this path")
    p.add_argument("--format", required=True, choices=sorted(_FORMATS),
                   help="raw format family: spec (2D-S/HVPS), dmt (CIP/PIP), "
                        "pms (2DC/2DP/Fast2DC), sea")
    p.add_argument("--profile",
                   help="fidelity profile name, required with --format spec and refused with "
                        "the other formats, whose readers take none. No default: the "
                        "profile selects the SPEC decoder's record-buffer guard, on which the "
                        "MATLAB sources differ. One of: "
                        + ", ".join(_profile_names()))
    p.add_argument("--channels", default=None, choices=("HV", "H", "V"),
                   help="which SPEC channel(s) to write (spec only, "
                        "default HV; refused with the other formats)")
    _add_stage_engine(p)
    p.set_defaults(func=_run_read_binary)


def _stamp(outputs, *, engine: str, stage: str, profile: str | None,
           extra: dict[str, str] | None = None) -> None:
    """Record what wrote each path in ``outputs`` that actually exists.

    **Why every writer here calls this** (2026-09-18). Before it, the only stamp writer
    in the whole pipeline was the batch driver's ``write_stamp``, called after each of
    the driver's stages. Every other caller -- including these shipped subcommands, which the
    documentation offers as the way to run one stage -- produced a product with nothing beside
    it saying what had made it. Provenance was a property of one driver's happy path rather
    than of the product, so the repository documented a way to make exactly what the driver
    refuses. A stamp written here is not as complete as the driver's (it records this verb's
    arguments, not a campaign preset), and ``reprocess`` will still refuse to re-run from it,
    which is correct: it says what it knows and nothing it does not.

    A path that does not exist is skipped rather than stamped -- an orphan stamp would assert
    a product that is not there, which is the one failure state :func:`provenance.state`
    exists to name.
    """
    fields = {"writer": "arrayprobe-cli"}
    fields.update(extra or {})
    for out in outputs:
        path = Path(out)
        if path.exists():
            provenance.write(path, engine=engine, profile=profile, stage=stage,
                             extra=dict(fields))


def _read_binary_outputs(args: argparse.Namespace) -> list[Path]:
    """Which files ``read-binary`` actually wrote.

    SPEC writes ``<outfile>.H.cdf`` / ``<outfile>.V.cdf`` per ``--channels``, PMS
    ``<outfile>.2dc.cdf`` / ``.f2dc.cdf`` / ``.2dp.cdf`` and SEA ``<outfile>.CIP.cdf`` /
    ``.2DC.cdf`` (each reader's own docstring); DMT writes ``outfile`` verbatim -- stated once
    here so the stamp lands on the product and not on a path nobody created. Until 2026-09-26
    PMS and SEA were listed as ``outfile`` verbatim: the command printed ``wrote <outfile>``, a
    file that never existed, and their real products were left unstamped.
    """
    out = Path(args.outfile)
    suffixes = {"spec": [f"{c}.cdf" for c in (args.channels or "HV")],
                "pms": ["2dc.cdf", "f2dc.cdf", "2dp.cdf"],
                "sea": ["CIP.cdf", "2DC.cdf"]}.get(args.format)
    if suffixes is None:
        return [out]
    return [out.with_name(f"{out.name}.{s}") for s in suffixes]


def _run_read_binary(args: argparse.Namespace) -> int:
    engine = _stage_engine(args)
    if engine == "3.5" and args.format == "spec":
        print("arrayprobe read-binary --engine 3.5 --format spec: not wired here. "
              "arrayprobe_uiops.spec.read_binary_spec_v35 requires `software` (the Software "
              "attribute upstream reads from a cwd-relative version.txt) and the flight's "
              "TAS series, each a choice this command's flags do not carry and none of them "
              "defaultable. Run the v3.5 chain through `arrayprobe run <config>` with "
              "[run].engine = \"3.5\". The dmt, pms and sea readers do run on 3.5 here.",
              file=sys.stderr)
        return 2
    if not Path(args.infile).is_file():
        # Before any reader runs: SPEC creates its .H/.V.cdf files first and then raised
        # FileNotFoundError, leaving two empty products behind a traceback.
        print(f"arrayprobe read-binary: not a file: {args.infile}", file=sys.stderr)
        return 2
    try:
        if args.format == "spec":
            if not args.profile:
                # main() refuses this before dispatch; kept for a caller that builds args itself.
                raise SystemExit("--format spec needs --profile "
                                 "(no default -- see FidelityProfile)")
            counts = spec.read_binary_SPEC(
                args.infile, args.outfile,
                profile=lookup_profile(args.profile), channels=args.channels or "HV",
            )
        elif args.format == "dmt":
            counts = (dmt.read_binary_DMT(args.infile, args.outfile),)
        elif args.format == "pms":
            counts = pms.read_binary_PMS(args.infile, args.outfile)
        else:
            n_cip, _n_weird, n_2dc = sea.read_binary_SEA(args.infile, args.outfile)
            counts = (n_cip, n_2dc)
    except (ValueError, sea.SeaUndefinedVariableError, MatlabIndexError) as exc:
        # The readers' own refusals (DecompressionError, a missing </OAP> terminator, the
        # MATLAB error a SEA reader raises where read_binary_SEA.m dies, ...) --
        # usually a --format that does not match the file. One line, not a traceback.
        print(f"arrayprobe read-binary --format {args.format}: {args.infile} did not decode: "
              f"{exc}. Check that --format matches the file", file=sys.stderr)
        return 1
    written = [p for p in _read_binary_outputs(args) if p.exists()]
    print(f"wrote {', '.join(str(p) for p in written)} (records: "
          f"{', '.join(str(int(n)) for n in counts)})")
    # These readers are `arrayprobe`'s, so engine=3.1.4 is a statement about the code that ran,
    # not a claim that no other release shares it: uiops.CATALOGUE marks read_binary_DMT/PMS/SEA
    # SHARED (the MATLAB is byte-identical between v3.1.4 and v3.5, so one translation serves
    # both) and read_binary_SPEC OVERRIDDEN. `catalogue=` carries that distinction into the
    # stamp rather than letting `engine=` overstate it.
    # Under --engine 3.5 only the SHARED readers reach this line (SPEC is refused above), so
    # engine=3.5 names the same translation, whose MATLAB the catalogue measures byte-identical.
    catalogue = "overridden" if args.format == "spec" else "shared"
    _stamp(_read_binary_outputs(args), engine=engine, stage="S2",
           profile=args.profile,
           extra={"format": args.format, "catalogue": catalogue, "raw": Path(args.infile).name,
                  **({"channels": args.channels or "HV"} if args.format == "spec" else {})})
    if not any(counts):
        # A SEA or PMS reader handed a file of another format finds no record it recognises
        # and writes empty products, exit 0, with nothing to say it read nothing.
        print(f"arrayprobe read-binary: no records decoded from {args.infile} -- is "
              f"--format {args.format} right for this file?", file=sys.stderr)
        return 1
    return 0


def _add_imgproc(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "imgproc",
        help="frame particles out of a decoded image file (imgProc_sm) on the v3.1.4 "
             "validation engine, which this distribution does not include; use "
             "`arrayprobe run`",
        description="Frame particles out of a decoded image file (imgProc_sm) on the "
                    "v3.1.4 validation engine, which this distribution does not include. To "
                    "process data on the default engine, v3.5, use `arrayprobe run "
                    "<config.toml>`; to run a "
                    "single stage there, use [run].stages in the config.",
    )
    p.add_argument("infile")
    p.add_argument("outfile")
    p.add_argument("probename")
    p.add_argument("n", type=int, help="chunk index, 1-based (n=1 for a "
                                       "whole-file run)")
    p.add_argument("every", type=int, help="records per chunk (nEvery; the "
                                           "whole file's record count for "
                                           "a whole-file run)")
    p.add_argument("projectname")
    p.add_argument("--profile", required=True,
                   help="fidelity profile name -- no default")
    p.add_argument("--engine", required=True, type=_engine_value, metavar=_engine_metavar(),
                   help="which UIOOPS engine frames the particles; required, no default, and "
                        "recorded in the .call stamp. "
                        + ("3.1.4 is the validation engine and runs here; "
                           if _v314_engine_present() else
                           "3.1.4, the validation engine this command runs, is not in this "
                           "distribution; ")
                        + "3.5 is refused with the reason, because its image processing "
                        "needs choices this command's flags do not carry. For 3.5 use "
                        "`arrayprobe run` with [run].engine = \"3.5\".")
    p.add_argument("--i-rect-ellipse", type=int, default=0, choices=(0, 1))
    p.add_argument("--i-calc-all-diode-stats", type=int, default=0,
                   choices=(0, 1))
    p.add_argument("--tas-file", default=None,
                   help="aircraft TAS file (only if the profile's "
                        "time_in_seconds_from_tas is set)")
    p.set_defaults(func=_run_imgproc)


#: What ``imgProc_sm`` needs under v3.5 that this subcommand's flag surface does not carry.
#: Each is a fidelity decision with no defensible default (``arrayprobe_uiops.imgproc:489-510``
#: makes all four keyword-only and required for the same reason), so the verb refuses rather
#: than inventing them -- the module docstring's "a general front door must never default a
#: fidelity choice", applied to the engine that has more of them.
_V35_IMGPROC_UNCARRIED = ("iNewHabit", "reject_config", "tas_time/tas", "software")


def _v35_stage_route(stage: str, name: str) -> str:
    """The v3.5 route for one stage: `arrayprobe run` with that stage selected."""
    return (f"To run {name} on v3.5, use `arrayprobe run <config.toml>` with "
            f'[run].engine = "3.5" and [run].stages = "{stage}" (or "234" for the whole chain); '
            f"examples/configs/cip_uiops/cip_run.toml is a template.")


#: The stage each per-stage verb runs, for the refusal a distribution without the engine prints.
_STAGE_VERB_ROUTES = {"imgproc": ("3", "image processing"),
                      "sizedist": ("4", "the size distribution")}


def _absent_engine_refusal(command: str | None) -> str:
    """What a per-stage verb prints where the engine it runs is absent: the shared absence
    message, plus, for a verb that is one stage, the working route (`arrayprobe run` with that
    stage), so the refusal never leaves the user without a command that works. Names no
    engine version beyond v3.5, as the rest of a distribution without the engine does."""
    route = _STAGE_VERB_ROUTES.get(command or "")
    if route is None:
        return _V314_ABSENT_MESSAGE
    return _V314_ABSENT_MESSAGE + " " + _v35_stage_route(*route)


def _run_imgproc(args: argparse.Namespace) -> int:
    import uiops  # local, matching every other uiops use here (`:1525`, `:1587`)

    engine = uiops.engine(args.engine)
    if engine.version == "3.5":
        print(f"arrayprobe imgproc --engine 3.5: not wired here. "
              f"{engine.dotted('imgproc')}.imgproc_sm_v35 requires "
              f"{', '.join(_V35_IMGPROC_UNCARRIED)}, each of them a fidelity choice this "
              f"subcommand's flags do not carry and none of them defaultable -- inventing one "
              f"would silently pick a side. "
              + _v35_stage_route("3", "image processing"),
              file=sys.stderr)
        return 2
    try:
        chosen = lookup_profile(args.profile)
    except KeyError as exc:
        print(f"arrayprobe imgproc: {exc.args[0]}", file=sys.stderr)
        return 2
    # The library's own rule (imgproc.py): the TAS file is needed only when the profile builds
    # Time_in_seconds from it AND the probe reads it (probetype 2); a PIP or CIP run under the same
    # profile needs none. Checking the profile alone refused the documented PECAN PIP tour.
    needs_tas = (chosen.time_in_seconds_from_tas
                 and imgproc_module.imgproc_config(args.probename).needs_tas_file)
    if needs_tas and args.tas_file is None:
        # Checked here so the refusal names the flag; the library's own ValueError names its
        # keyword (`tas_file=`), which a command-line user cannot type.
        print(f"arrayprobe imgproc: --profile {args.profile} builds Time_in_seconds from the "
              f"aircraft TAS file (imgProc_sm.m:183-185); pass --tas-file", file=sys.stderr)
        return 2
    written = imgproc_module.imgproc_sm(
        args.infile, args.outfile, args.probename, args.n, args.every,
        args.projectname,
        profile=lookup_profile(args.profile),
        iRectEllipse=args.i_rect_ellipse,
        iCalcAllDiodeStats=args.i_calc_all_diode_stats,
        tas_file=args.tas_file,
    )
    print(f"wrote {written} particles to {args.outfile}")
    _stamp([args.outfile], engine=args.engine, stage="S3", profile=args.profile,
           extra={"probe": args.probename, "n": str(args.n), "every": str(args.every),
                  "iRectEllipse": str(args.i_rect_ellipse),
                  "iCalcAllDiodeStats": str(args.i_calc_all_diode_stats),
                  "tas_file": Path(args.tas_file).name if args.tas_file else "<none>"})
    return 0


def _add_sizedist(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "sizedist",
        help="compute one-second size distributions from a proc file (sizeDist) on the "
             "v3.1.4 validation engine, which this distribution does not include; use "
             "`arrayprobe run`",
        description="Compute one-second size distributions from a proc file (sizeDist) on "
                    "the v3.1.4 validation engine, which this distribution does not include. "
                    "To process data on the default engine, v3.5, use `arrayprobe run "
                    "<config.toml>`; to run a "
                    "single stage there, use [run].stages in the config.",
    )
    p.add_argument("infile", help="proc file (imgproc's output)")
    p.add_argument("outfile")
    p.add_argument("--tas-csv", required=True,
                   help="the .tas.csv sidecar written alongside the "
                        "decoded image file (read-binary --format spec)")
    p.add_argument("probename")
    p.add_argument("d_choice", type=int)
    p.add_argument("sa_method", type=int)
    p.add_argument("pres", type=float, help="pressure, Pa, applied uniformly")
    p.add_argument("temp", type=float, help="temperature, C, applied uniformly")
    p.add_argument("projectname")
    p.add_argument("ddate", help="'YYYYMMDD HHMMSS'")
    p.add_argument("--iat-file", default=None,
                   help="inter-arrival threshold file (sizeDist's optional "
                        "twelfth argument). Passing nothing is NOT the same "
                        "as passing a name that does not exist -- see "
                        "sizedist.run's own docstring.")
    p.add_argument("--tree", required=True, choices=("stock", "production"),
                   help="which sizeDist.m lineage's project/probe switch and "
                        "reject thresholds to use -- no default, the two "
                        "disagree on whether the 2D-S applies shattering "
                        "identification at all. NOTE: this selects those "
                        "TABLES, not the whole lineage's control flow, which "
                        "is the production one throughout. See README's "
                        "'Known gaps' for the two measured places that "
                        "matters.")
    _add_stage_engine(p)
    p.set_defaults(func=_run_sizedist)


def _run_sizedist(args: argparse.Namespace) -> int:
    import numpy as np

    if _stage_engine(args) == "3.5":
        print("arrayprobe sizedist --engine 3.5: not wired here. v3.5's sizeDist takes three "
              "output switches and no --tree (one source tree), each a fidelity choice this "
              "command's flags do not carry. "
              + _v35_stage_route("4", "the size distribution"), file=sys.stderr)
        return 2

    timehhmmss, tas = load_tas_info(args.tas_csv)
    varargin = (args.iat_file,) if args.iat_file else ()
    sizedist_module.run(
        args.infile, args.outfile, tas, np.floor(timehhmmss), args.probename,
        args.d_choice, args.sa_method,
        np.full_like(tas, args.pres), np.full_like(tas, args.temp),
        args.projectname, args.ddate, *varargin,
        tree=args.tree,
    )
    print(f"wrote {args.outfile}")
    _stamp([args.outfile], engine="3.1.4", stage="S4", profile=None,
           extra={"probe": args.probename, "tree": args.tree,
                  "d_choice": str(args.d_choice), "sa_method": str(args.sa_method),
                  "iat_file": Path(args.iat_file).name if args.iat_file else "<none>",
                  "proc": Path(args.infile).name})
    return 0


def _add_combine(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "combine",
        help="stitch a flight's sd files into one product (combine_sizedist)",
    )
    p.add_argument("sd_files", nargs="+",
                   help="sd files, IN ORDER (see combine_sizedist's own "
                        "docstring -- order is a contract, not a convenience)")
    p.add_argument("outfile")
    p.add_argument("--flight-date", required=True, help="'YYYYMMDD', full year")
    p.add_argument("--summary-time", required=True,
                   help="'YY_MM_DD_HH_MM_SS', the campaign summary file's own "
                        "basename")
    _add_stage_engine(p)
    p.add_argument("--borrowed-combine", action="store_true",
                   help="with --engine 3.5 only, and required there: opt in to a campaign "
                        "fork's combine_sizedist over v3.5 sd files. No stock UIOOPS release "
                        "ships a combine step, so on 3.5 it is borrowed and off by default.")
    p.set_defaults(func=_run_combine)


def _run_combine(args: argparse.Namespace) -> int:
    engine = _stage_engine(args)
    if engine == "3.5":
        if not args.borrowed_combine:
            print("arrayprobe combine --engine 3.5 needs --borrowed-combine: no stock UIOPS "
                  "release ships a combine step, so on v3.5 a campaign fork's is borrowed, "
                  "opt-in and off by default. Nothing was written.", file=sys.stderr)
            return 2
        import uiops  # local, as in _run_imgproc

        uiops.engine("3.5").get("combine", "combine_sizedist")(
            args.sd_files, args.outfile,
            flight_date=args.flight_date, summary_time=args.summary_time,
            borrowed_combine=True,
        )
    elif args.borrowed_combine:
        print("arrayprobe combine: --borrowed-combine applies to --engine 3.5 only; on 3.1.4 "
              "the fork's combine is the port's own.", file=sys.stderr)
        return 2
    else:
        combine_module.combine_sizedist(
            args.sd_files, args.outfile,
            flight_date=args.flight_date, summary_time=args.summary_time,
        )
    print(f"wrote {args.outfile}")
    # combine_sizedist.m is FORK_ONLY (uiops.CATALOGUE): it exists in no stock UIOOPS release,
    # so the engine named here is the port that ran, arrayprobe's.
    extra = {"flight_date": args.flight_date, "summary_time": args.summary_time,
             "inputs": ",".join(Path(p).name for p in args.sd_files),
             "catalogue": "fork-only"}
    if engine == "3.5":
        extra["borrowed_combine"] = "1"
    _stamp([args.outfile], engine=engine, stage="S4c", profile=None, extra=extra)
    return 0


def _add_intarr(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "intarr-threshold",
        help="per-particle inter-arrival thresholds (IntArrAnalysis_time)",
        description="Fit each population of inter-arrival times and write the threshold file "
                    "sizeDist accepts as its optional twelfth argument. NOTE: the "
                    "production call behind the archived products this port is validated "
                    "against passed a threshold file that does not exist, so nothing in them "
                    "depends on this stage.",
    )
    p.add_argument("proc_file", help="a per-particle file (proc.*.nc) or a combined one")
    p.add_argument("outfile", help="threshold .cdf for sizeDist's optional twelfth argument")
    p.add_argument("--probe", required=True, help="probe name, e.g. 2DS")
    p.add_argument("--flight-date", required=True, help="'YYYYMMDD', full year")
    p.add_argument("--blocks", type=int, default=5,
                   help="number of populations to split the file into (the source's fileNum); "
                        "the block size is derived from it exactly as IntArrAnalysis_time does")
    p.add_argument("--extra-thresholds-json", default=None,
                   help="opt-in: write the two thresholds the source computes but never writes "
                        "(threshold, threshold_ww) to this JSON sidecar, never a netCDF file "
                        "(arrayprobe.intarr_analysis.write_extra_thresholds_sidecar)")
    p.add_argument("--plot", default=None,
                   help="opt-in: render IntArrAnalysis_time.m's contour figure "
                        "(arrayprobe.intarr_plots.plot_intarr_contour) to this image path "
                        "(matplotlib; requires the scipy/matplotlib extras)")
    p.add_argument("--fix-b8", action="store_true",
                   help="with --plot: use the corrected time axis instead of reproducing "
                        "the original's NaN gaps before 10:00:00 (a defect in the original "
                        "time axis)")
    p.add_argument("--mat-workspace", default=None,
                   help="opt-in: write IntArrAnalysis_time.m's :331 workspace dump "
                        "(arrayprobe.intarr_analysis.write_mat_workspace) to this .mat path "
                        "(requires the scipy extra)")
    p.set_defaults(func=_run_intarr)


def _run_intarr(args: argparse.Namespace) -> int:
    import netCDF4

    from . import intarr_analysis

    try:
        with netCDF4.Dataset(args.proc_file) as d:
            times = np.asarray(d.variables["Time"][:], dtype=float).reshape(-1)
            seconds = np.asarray(d.variables["Time_in_seconds"][:], dtype=float).reshape(-1)
            # Read only when an opt-in output needs them, so the default call
            # touches exactly the variables it always did.
            need_extras = args.plot or args.mat_workspace
            dates = (np.asarray(d.variables["Date"][:], dtype=float).reshape(-1)
                     if need_extras else None)
            dmax = (np.asarray(d.variables["image_diam_minR"][:], dtype=float).reshape(-1)
                    if args.mat_workspace else None)
    except FileNotFoundError:
        raise  # main()'s handler prints "arrayprobe intarr-threshold: No such file ..."
    except OSError as exc:
        print(f"arrayprobe intarr-threshold: {args.proc_file} is not a readable netCDF "
              f"file: {exc}", file=sys.stderr)
        return 2
    except KeyError as exc:
        print(f"arrayprobe intarr-threshold: {args.proc_file} has no variable {exc}; pass "
              f"the proc file the image-processing stage wrote", file=sys.stderr)
        return 2
    arr = intarr_analysis.inter_arrival(seconds)
    result = intarr_analysis.analyse(arr, times, n_blocks=args.blocks)
    intarr_analysis.write_threshold_file(
        args.outfile, times, result["threshold_ak"],
        probename=args.probe, flight_date=args.flight_date,
        data_source=os.path.basename(args.proc_file),
        population_size=result["population_size"],
    )
    print(f"wrote {args.outfile} "
          f"({result['block_starts'].size} population(s) of {result['population_size']})")

    if args.extra_thresholds_json:
        intarr_analysis.write_extra_thresholds_sidecar(
            args.extra_thresholds_json, times, result["threshold"], result["threshold_ww"],
            threshold_ak=result["threshold_ak"])
        print(f"wrote {args.extra_thresholds_json}")

    if args.plot:
        import matplotlib.pyplot as plt

        from . import intarr_plots
        fig, _ax = intarr_plots.plot_intarr_contour(
            arr, times, dates, result["threshold"], result["threshold_ww"],
            result["threshold_ak"], population_size=result["population_size"],
            date_string=args.flight_date, fix_b8=args.fix_b8)
        fig.savefig(args.plot)
        plt.close(fig)
        print(f"wrote {args.plot}")

    if args.mat_workspace:
        intarr_analysis.write_mat_workspace(
            args.mat_workspace, timehhmmss=times, date=dates, time_in_seconds=seconds,
            dmax=dmax, probe_name=args.probe, date_string=args.flight_date,
            infile=os.path.basename(args.proc_file), n_blocks=args.blocks)
        print(f"wrote {args.mat_workspace}")

    return 0


def _compare(args) -> int:
    """``arrayprobe compare`` -- the comparison handler.

    Moved verbatim on 2026-09-10 rather than reimplemented, so there
    is one copy. Two copies of an acceptance rule is two places for it to
    drift, and this particular rule is one the tool's own comments call out as
    easy to get wrong.
    """
    # The console on Windows defaults to cp1252 and would raise on any
    # non-ASCII byte the report contains. Done here rather than at import so
    # importing the CLI never has a side effect on someone else's stdout.
    try:
        # `type: ignore` because sys.stdout is only TextIO to mypy, and
        # `reconfigure` is TextIOWrapper-only -- which is exactly why
        # this is wrapped in a try at all.
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):  # pragma: no cover -- odd stdout
        pass

    if args.classes:
        for key, tc in compare_module.CLASSES.items():
            proc = sorted(n for n, c in compare_module.PROC_CLASSES.items()
                          if c == key)
            sd = sorted(n for n, c in compare_module.SD_CLASSES.items()
                        if c == key)
            print(f"{key}  {tc.name}  "
                  f"({'asserts' if tc.asserts else 'informational'})")
            print(f"    {tc.rule}")
            print(f"    proc-file variables: {', '.join(proc) if proc else '-'}")
            print(f"    sizeDist variables : {', '.join(sd) if sd else '-'}")
            print()
        return 0

    for path in (args.left, args.right):
        if not os.path.isfile(path):
            print(f"not a file: {path}", file=sys.stderr)
            return 2

    # The kind is read out of the file's dimensions, never out of its name --
    # the S2 rule that a filename is not evidence. Only these refusals sit in
    # the try: reading each file's kind opens it (the right-hand one included),
    # so a file that is not netCDF, or two files of different kinds, is one line
    # and exit 2. An error raised inside the comparison itself propagates with
    # its traceback, so an internal defect is never reported as bad input.
    try:
        kind = compare_module.file_kind(args.left)
        kind_right = compare_module.file_kind(args.right)
        if kind != kind_right:
            raise ValueError(f"cannot compare a {kind} file against a {kind_right} file: "
                             f"{args.left} vs {args.right}")
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    except OSError as exc:
        # netCDF4 raises OSError (errno -51) for a file that is not netCDF; the
        # isfile check above has already ruled out a missing path.
        print(f"arrayprobe compare: not a readable netCDF file: {exc}", file=sys.stderr)
        return 2
    # A file whose header opens but whose variable data does not (a corrupt
    # netCDF4/HDF5 chunk) fails only here: netCDF4 raises RuntimeError ("NetCDF:
    # HDF error") for a failed variable read, OSError only for a failed open.
    # Either is bad input: one line and exit 2. A ValueError from inside the
    # comparison is an internal defect and keeps its traceback, and so do the two
    # RuntimeError subclasses that only a defect raises. (A truncated netCDF4 file
    # never gets this far: HDF5 refuses it at open, above.)
    try:
        report = compare_module.compare_files(args.left, args.right)
    except (NotImplementedError, RecursionError):
        raise
    except (OSError, RuntimeError) as exc:
        print(f"arrayprobe compare: not a readable netCDF file: {exc}", file=sys.stderr)
        return 2
    print(f"kind : {kind} file\n")

    # Acceptance is ALWAYS computed over the whole file, before any --var
    # filtering. Otherwise `--var image_auto_reject` -- a class E variable that
    # never asserts -- reports ACCEPTED: True while forty other variables went
    # unexamined, which is the precise kind of report this exists to stop
    # anyone writing.
    accepted = report.accepted(min_join=args.min_join)

    wanted = None
    if args.var:
        wanted = set(args.var)
        unknown = wanted - {v.name for v in report.variables}
        if unknown:
            print(f"no such variable(s): {', '.join(sorted(unknown))}",
                  file=sys.stderr)
            return 2
        report.variables = [v for v in report.variables if v.name in wanted]

    print(compare_module.format_report(
        report, verbose=args.verbose or bool(args.var), accepted=accepted))
    if wanted:
        print(f"\n  (the table above is filtered to "
              f"{len(wanted)} variable(s); "
              "the verdict above it is for the WHOLE file)")
    return 0 if accepted else 1


def _add_compare(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "compare",
        help="join two output files on particle identity, then diff by "
             "tolerance class",
        description="Read the join block first, always. A value difference "
                    "reported against a bad join is an artefact of the "
                    "alignment, not a finding, and the two are "
                    "indistinguishable once you are looking at a column of "
                    "numbers. Exit status is 0 when the comparison is "
                    "ACCEPTED (>=--min-join join, no failure in an asserting "
                    "tolerance class, no unclassified variable, no duplicate "
                    "join keys) and 1 otherwise, so it can gate a run without "
                    "anyone reading the output; 2 is a usage or file error.",
    )
    p.add_argument("left", nargs="?", help="the file under test (usually ours)")
    p.add_argument("right", nargs="?", help="the reference file")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="list bit-exact variables too, not only the differing ones")
    p.add_argument("--var", action="append", default=None, metavar="NAME",
                   help="restrict the value comparison to these variables "
                        "(repeatable); the join is always computed in full")
    p.add_argument("--classes", action="store_true",
                   help="print the tolerance classes and what each one means, "
                        "then exit")
    p.add_argument("--min-join", type=float, default=0.999,
                   help="join fraction required for acceptance (default 0.999)")
    p.set_defaults(func=_compare)


def _gallery(args) -> int:
    """``arrayprobe gallery`` -- render one flight's particle gallery to disk.

    Moved 2026-09-10, script kept as a shim. Same reasoning as ``compare``:
    the rendering engine was always in the package, but nothing in
    ``arrayprobe --help`` said the package could render a flight at all.
    """
    import json
    import time

    import netCDF4

    from arrayprobe_uiops.decode_naming import decode_path

    # The decode is named from the proc file's own stamp (engine and reader together),
    # never from which file exists; no stamp reads as v3.1.4, as the triage server does.
    proc_path = os.path.join(args.decoded_dir, f"proc.{args.flight}.nc")
    if not os.path.exists(proc_path):
        print(f"missing input: {proc_path}; --decoded-dir {args.decoded_dir} must hold the "
              f"decoded proc.{args.flight}.nc (pass the folder the decode wrote)",
              file=sys.stderr)
        return 2
    try:
        image_path = str(decode_path(proc_path, assume_engine="3.1.4"))
    except ValueError as exc:
        print(f"--flight must be <stem>.<channel>: {exc}", file=sys.stderr)
        return 2
    if not os.path.exists(image_path):
        print(f"missing input: {image_path}", file=sys.stderr)
        return 2

    verdict_path = os.path.join(args.decoded_dir, "triage_verdicts",
                                f"{args.flight}.json")
    verdicts = {}
    if os.path.exists(verdict_path):
        with open(verdict_path, encoding="utf-8") as fh:
            verdicts = json.load(fh)
    print(f"verdicts: {len(verdicts)} human labels from "
          f"{verdict_path if verdicts else '(none on disk)'}", flush=True)

    out_dir = os.path.join(args.out, args.flight)
    started = time.time()

    def progress(done, total, counts):
        rate = done / max(time.time() - started, 1e-9)
        left = (total - done) / rate if rate else 0
        print(f"  {done}/{total} ({100 * done / total:.1f}%) "
              f"{rate:.0f}/s  eta {left / 60:.1f} min  {counts}", flush=True)

    with netCDF4.Dataset(image_path) as image_ds:
        with netCDF4.Dataset(proc_path) as proc_ds:
            counts = render_module.render_flight_to_disk(
                image_ds, proc_ds, out_dir, verdicts=verdicts,
                classes=tuple(args.classes), scale=args.scale,
                crop=not args.no_crop, limit=args.limit, progress=progress)

    print(f"done in {(time.time() - started) / 60:.1f} min: {counts}", flush=True)
    if not args.no_index:
        pages = render_module.write_flight_index(out_dir, title=args.flight)
        print(f"wrote {len(pages)} index pages; "
              f"open {os.path.join(out_dir, 'index.html')}", flush=True)
    return 0


def _inventory(args: argparse.Namespace) -> int:
    from arrayprobe import inventory as inventory_module
    if not Path(args.dir).exists():
        print(f"arrayprobe inventory: {args.dir}: no such file or directory", file=sys.stderr)
        return 2
    rows = inventory_module.inventory(args.dir, fmt=args.format)
    jpath, cpath = inventory_module.write_inventory(rows, args.out)
    flagged = sum(1 for r in rows if r.get("empty") or r.get("truncated"))
    print(f"{len(rows)} raw files, {flagged} flagged empty or truncated; "
          f"wrote {jpath} and {cpath}")
    return 0


def _add_inventory(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "inventory",
        help="list raw files with size, SHA-256 and empty/truncated flags (JSON + CSV)",
        description="Reads raw bytes only; writes <out>.json and <out>.csv, one row per "
                    "file. Computes no product and changes nothing.",
    )
    p.add_argument("dir", help="directory of raw files (or one file)")
    p.add_argument("--out", required=True,
                   help="output stem; writes <stem>.json and <stem>.csv")
    p.add_argument("--format", default=None, choices=["spec", "dmt", "pms_2d"],
                   help="record format for every file (default: guessed per file)")
    p.set_defaults(func=_inventory)


def _check_counts(args: argparse.Namespace) -> int:
    """Reconcile an sd product's binned counts with its proc file, second by second.

    Read only.  Exit 0 when every second's residual is within ``--tolerance``
    (default 0, exact), 1 otherwise.  The probe's own housekeeping total is not
    written by any reader this package ships, so that line reads "not available".
    """
    import json

    from arrayprobe.count_closure import NOT_AVAILABLE, count_closure
    r = count_closure(args.sd, args.proc)
    tol = float(args.tolerance)
    differing = 0
    for t, b, a, d in zip(r["time"], r["binned_per_second"], r["accepted_per_second"],
                          r["residual_per_second"], strict=True):
        if abs(float(d)) > tol:
            differing += 1
            print(f"{t:g} binned={float(b):g} accepted={int(a)} residual={float(d):+g}")
    for e in r["excluded"]:
        print(f"excluded particle {e['index'] + 1} at {e['time']:g}: {e['cause']}")
    if differing == 0:
        print(f"closure: exact ({r['total_accepted']} accepted of {r['total_in_proc']} "
              f"particles, {r['total_binned']:g} binned)")
    else:
        print(f"closure: {differing} seconds differ (residual {r['residual']:+g})")
    probe = r["probe_reported"]
    print(f"probe_reported: {NOT_AVAILABLE if probe is None else probe}")
    if args.out:
        payload = {k: (v.tolist() if hasattr(v, "tolist") else v) for k, v in r.items()}
        payload["differing_seconds"] = differing
        payload["tolerance"] = tol
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        print(f"wrote {args.out}")
    return 0 if differing == 0 else 1


def _add_check_counts(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "check-counts",
        help="reconcile a size-distribution file's binned counts with its particle file, "
             "second by second, naming the cause of every excluded particle",
        description="Reads the sd and proc files only and writes nothing but --out. "
                    "Prints every second whose binned count differs from the accepted "
                    "particle count, each excluded particle with its cause, a closure "
                    "line and the probe's own reported total (not available until a "
                    "reader writes it). Exit 0 when closure is exact, 1 otherwise.",
    )
    p.add_argument("sd", help="size-distribution netCDF (its .call sidecar beside it)")
    p.add_argument("proc", help="the per-particle netCDF the sd file was made from")
    p.add_argument("--out", default=None, help="write the full reconciliation as JSON")
    p.add_argument("--tolerance", default=0.0, type=float,
                   help="largest per-second residual still counted as closed (default 0)")
    p.set_defaults(func=_check_counts)


def _add_gallery(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "gallery",
        help="render a whole flight's particles to disk, with index pages",
        description="Visualisation only -- it reads a decoded file and its "
                    "proc file and writes images; it computes nothing and "
                    "changes nothing.",
    )
    p.add_argument("--decoded-dir", required=True,
                   help="directory holding <flight>.cdf and proc.<flight>.nc")
    p.add_argument("--flight", required=True,
                   help="flight stem including the channel, e.g. "
                        "base170817073523.H")
    p.add_argument("--out", required=True,
                   help="output root; a <flight>/ subdirectory is created "
                        "under it")
    p.add_argument("--classes", nargs="+", default=["accepted"],
                   choices=render_module.PARTICLE_CLASSES,
                   help="which classes to write (default: accepted only, which "
                        "keeps a large flight's gallery a manageable size)")
    p.add_argument("--scale", type=int, default=3, help="pixel scale (default 3)")
    p.add_argument("--no-crop", action="store_true",
                   help="keep the full diode-search window instead of cropping "
                        "to the particle. The window can vastly exceed the "
                        "shadow right after a record reset, which is why "
                        "cropping is the default")
    p.add_argument("--limit", type=int, default=None,
                   help="stop after N particles")
    p.add_argument("--no-index", action="store_true",
                   help="skip the index pages")
    p.set_defaults(func=_gallery)


def _triage(args) -> int:
    # `Path.resolve()`, not `os.path.abspath`: `run` is annotated for a Path
    # and, on Windows, only resolve() expands an 8.3 short path -- so abspath
    # would hand the server a directory string that differs from the one every
    # other part of the tool prints and stores verdicts under.
    queue = Path(args.queue_file) if args.queue_file else None
    if not Path(args.decoded_dir).is_dir():
        print(f"arrayprobe triage: --decoded-dir {args.decoded_dir} is not a directory; "
              "point it at the folder holding the decoded proc.*.nc files", file=sys.stderr)
        return 2
    triage_module.run(Path(args.decoded_dir).resolve(), args.port, queue, args.reviewer,
                      accept_unstamped=args.accept_unstamped,
                      met_dir=Path(args.met_dir) if args.met_dir else None,
                      state_file=Path(args.state_file) if args.state_file else None,
                      state_var=args.state_var,
                      run_root=Path(args.run_root).resolve() if args.run_root else None)
    return 0


_STAMP = re.compile(r"(\d{6})(\d{6})\.([HV])[._]")


def _add_diode_masks(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "diode-masks",
        help="find the stuck diodes in first-pass proc files (find_shadow_diodes.m) "
             "and show the per-diode occupancy beside them",
        description="Runs masks.find_shadow_diodes -- a field-campaign fork's "
                    "find_shadow_diodes.m, bug for bug -- on each --proc, writing "
                    "the diode.<date><time>.<or>[empty].mat MATLAB writes (an upstream defect: an "
                    "empty result is named ...<or>empty.mat, which the second pass "
                    "never loads) and nothing else. Beside it, prints bin_stats and, "
                    "when --image is given, diode_report's occupancy and SPEC's "
                    "noisy-diode flags. The mask reaches a second pass only when "
                    "the diodes are declared in [run].diode_masks AND the run is "
                    "given --diode-corrected.",
    )
    p.add_argument("--proc", action="append", required=True, type=Path,
                   help="a first-pass proc file; repeat for several")
    p.add_argument("--image", action="append", type=Path, default=None,
                   help="the decoded image .cdf for the matching --proc, in the "
                        "same order; enables the occupancy / SPEC view")
    p.add_argument("--date", help="'YYMMDD'; default: parsed from the proc name")
    p.add_argument("--time", help="'HHMMSS'; default: parsed from the proc name")
    p.add_argument("--orientation", choices=("H", "V"),
                   help="default: parsed from the proc name")
    p.add_argument("--out-dir", type=Path, default=None,
                   help="where the .mat goes; default the proc's own directory "
                        "(MATLAB's `path`, which it both reads from and saves to)")
    p.add_argument("--no-write", action="store_true",
                   help="report only; write no .mat")
    p.add_argument("--profile", default=None, metavar="NAME",
                   help=("the v3.1.4 fidelity profile, when the proc file's stamp names none "
                         "(it decides whether bin_stats counts lit or shadowed slices)"
                         if _v314_engine_present() else
                         "the fidelity profile, when the proc file's stamp names none "
                         "(it decides whether bin_stats counts lit or shadowed slices)"))
    p.add_argument("--probe", default=None, metavar="NAME",
                   help="the probe whose image_slice_offset enters S for a shadow count")
    p.set_defaults(func=_run_diode_masks)


def _run_diode_masks(args: argparse.Namespace) -> int:
    from . import diode_report
    from . import masks as masks_module
    from .tune import diodes as tune_diodes

    images = args.image or []
    if images and len(images) != len(args.proc):
        print("arrayprobe diode-masks: give one --image per --proc, or none",
              file=sys.stderr)
        return 2
    status = 0
    for i, proc in enumerate(args.proc):
        stamp = _STAMP.search(proc.name)
        date = args.date or (stamp.group(1) if stamp else None)
        time_ = args.time or (stamp.group(2) if stamp else None)
        orientation = args.orientation or (stamp.group(3) if stamp else None)
        if not (date and time_ and orientation):
            print(f"arrayprobe diode-masks: cannot read <date><time>.<H|V> from "
                  f"{proc.name}; pass --date, --time and --orientation", file=sys.stderr)
            return 2
        out_dir = args.out_dir or proc.parent
        print(f"== {proc}  (date {date}, time {time_}, orientation {orientation})")
        # Polarity is read exactly as `tune diodes` reads it (one helper, no second copy).
        try:
            conv = tune_diodes.counting_convention(proc, args.profile)
            find_kw: dict = {}
            if conv["shadowed"]:
                bs, _ = tune_diodes._read(proc)
                offset, _src = tune_diodes.slice_offset(bs.size, args.probe)
                total = tune_diodes.position_slice_total(proc, offset)
                if total is None:
                    raise tune_diodes.DiodeReportError(
                        f"{proc.name}: a shadow count needs the proc file's position "
                        "to compute S")
                find_kw = {"counts": "shadowed", "slice_total": int(total)}
        except (ValueError, KeyError, OSError) as exc:
            print(f"arrayprobe diode-masks: {exc}", file=sys.stderr)
            return 2
        try:
            found = masks_module.find_shadow_diodes(
                date, time_, orientation, path=str(out_dir) + "/", infile=proc,
                write=not args.no_write, **find_kw)
        except masks_module.ShadowDiodeSearchError as exc:
            print(f"  find_shadow_diodes: {exc}")
            status = 1
            continue
        a = found.bin_stats.astype(float)
        kind = ("shadowed-slice count per diode, converted to lit"
                if conv["shadowed"] else "lit-slice count per diode")
        print(f"  bin_stats ({kind}): {a.size} diodes, "
              f"mean {a.mean():.1f}, min {a.min():.0f} (diode {int(a.argmin()) + 1}), "
              f"max {a.max():.0f} (diode {int(a.argmax()) + 1})")
        if found.ill_diode.size:
            print(f"  over 1.2 x mean (masked in flight, replaced): "
                  f"{found.ill_diode.astype(int).tolist()}")
        rule = "0.80 x mean" if found.branch == "mean" else "0.80 x max"
        print(f"  find_shadow_diodes: stuck = below {rule} = {found.threshold:g}")
        print(f"  shadow_diode (1-based): {found.shadow_diode.astype(int).tolist()}")
        if found.written is not None:
            note = ("  <- F2: this name is never loaded; an empty mask is inert"
                    if not found.shadow_diode.size else "")
            print(f"  wrote {found.written}{note}")
        if images:
            report = diode_report.report_from_files(images[i], proc)
            flagged, threshold, mean_count = diode_report.flag_noisy_diodes(report)
            print("  diode_report: " + report.summary().replace("\n", "\n  "))
            print(f"  SPEC noisy-diode test (report only): threshold {threshold:.2f} "
                  f"images over mean {mean_count:.2f}; flagged (1-based): "
                  f"{(flagged + 1).tolist()}")
    return status


def _add_triage(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "triage",
        help="start the particle review and labelling server",
        description="Manual labelling and visualisation. It writes verdicts "
                    "to <decoded-dir>/triage_verdicts/ and changes no "
                    "computed number. --decoded-dir is required, as it is "
                    "for `python -m arrayprobe.triage_server`.",
    )
    p.add_argument("--decoded-dir", required=True,
                   help="directory containing proc.*.H.nc files and their decodes "
                        + ("(*.H.nc from v3.5, *.H.cdf from v3.1.4)"
                           if _v314_engine_present() else "(*.H.nc)"))
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--queue-file", default=None,
                   help="JSON file of named curated particle lists for a "
                        "specific review pass")
    # Required to save a label, but not `required=True` at startup: refusing to
    # start would stop a read-only viewer another agent is demoing, so the server
    # starts and refuses every save with HTTP 400 instead. Not defaulted from
    # the OS username either -- that would attribute a label to someone who
    # never said it was theirs, which is worse than recording nothing.
    p.add_argument("--reviewer", default=os.environ.get(triage_module.REVIEWER_ENV),
                   help="who is labelling; REQUIRED to save labels and recorded "
                        f"with every verdict (or set {triage_module.REVIEWER_ENV}). "
                        "With neither, the server starts but refuses every save "
                        "(HTTP 400) -- the id is never guessed")
    p.add_argument("--met-dir", default=None,
                   help="folder of ARM AAF merged files (enaaafmergedF1.c1.*.nc); the particle "
                        "page then shows the air temperature at the particle's record time")
    p.add_argument("--state-file", default=None,
                   help="netCDF state-variable file for the air temperature (any names: the "
                        "temperature is chosen by units and standard_name/long_name, and a "
                        "file with several candidates is refused, listing them). Takes precedence "
                        "over --met-dir. With neither, the index page asks for the file")
    p.add_argument("--state-var", default=None,
                   help="the temperature variable in --state-file (default: chosen by content)")
    p.add_argument("--accept-unstamped", action="store_true",
                   help="index products whose provenance is unrecorded. WITHOUT this flag they "
                        "are refused and listed by name on the index page under 'Refused: no "
                        "provenance' -- never silently dropped. Labels attached to a product of "
                        "unknown configuration cannot be traced afterwards. Pass this when you "
                        "know what you are looking at and the stamp is simply absent.")
    p.add_argument("--run-root", default=None,
                   help="folder whose _runs/ the Run page lists at /runs (default: the output "
                        "folder of the first run launched from /run)")
    p.set_defaults(func=_triage)


def _triage_recheck(args) -> int:
    from .review_agreement import recheck_queue
    data = recheck_queue(Path(args.decoded_dir), args.flight, Path(args.out),
                         fraction=args.fraction, seed=args.seed)
    about = data["_about"]
    name = next(k for k in data if not k.startswith("_"))
    print(f"wrote {args.out}: queue {name}, {about['drawn']} of "
          f"{about['of_human_labelled']} human-labelled particles (seed {args.seed})")
    print(f"review it blind: arrayprobe triage --decoded-dir {args.decoded_dir} "
          f"--queue-file {args.out}")
    return 0


def _triage_agreement(args) -> int:
    from .review_agreement import agreement
    r = agreement(Path(args.decoded_dir), args.flight)
    if r.n == 0:
        print(f"{args.flight}: no particle has both a first and a re-check human label yet")
        return 0
    kappa = "undefined (one label throughout)" if r.kappa is None else f"{r.kappa:.2f}"
    print(f"{args.flight}: {r.n} re-checked particles; observed agreement {r.observed:.2f}, "
          f"chance {r.expected:.2f}, Cohen's kappa {kappa}")
    width = max(len(x) for x in r.labels)
    print(" " * (width + 2) + "  ".join(f"{x:>{width}}" for x in r.labels) + "   (re-check)")
    for a in r.labels:
        print(f"{a:>{width}}  " + "  ".join(f"{r.confusion[a][b]:>{width}}" for b in r.labels))
    return 0


def _add_triage_agreement(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "triage-recheck",
        help="write a blind re-check queue of particles a person already labelled",
        description="Draws a seeded random fraction of one flight's human labels into a "
                    "queue file whose name starts 'recheck-'. The triage server stores its "
                    "verdicts separately (triage_verdicts/<flight>.recheck.json) and hides "
                    "the first label, so the second is blind. Changes no computed number.",
    )
    p.add_argument("--decoded-dir", required=True, help="the directory the triage server uses")
    p.add_argument("--flight", required=True, help="flight name as the triage server shows it")
    p.add_argument("--out", required=True, help="queue file to write (JSON)")
    p.add_argument("--fraction", type=float, default=0.2,
                   help="share of the human-labelled particles to re-show (default 0.2)")
    p.add_argument("--seed", type=int, default=0, help="random seed, recorded in the file")
    p.set_defaults(func=_triage_recheck)
    q = sub.add_parser(
        "triage-agreement",
        help="report label agreement (Cohen's kappa) between first and re-check labels",
        description="Pairs each re-checked particle's first human label with its re-check "
                    "label and prints the observed and chance agreement, Cohen's kappa and "
                    "the confusion matrix.",
    )
    q.add_argument("--decoded-dir", required=True, help="the directory the triage server uses")
    q.add_argument("--flight", required=True, help="flight name as the triage server shows it")
    q.set_defaults(func=_triage_agreement)


def _add_provenance(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "provenance",
        help="what wrote these products, read from their .call sidecars",
        description="Per file: the engine, profile and stage its stamp records, the stamp's "
                    "format, its link count, and its state -- stamped, unstamped, orphan-stamp "
                    "(a sidecar whose product is gone), in-flight, legacy-json or unparseable. "
                    "A directory expands to every .nc/.cdf in it plus every orphan sidecar. "
                    "Nothing here infers an engine from a date, a filename or a neighbouring "
                    "file: a product whose stamp does not name one is reported as unrecorded, "
                    "which is the true answer. The git revision printed at the end is THIS "
                    "CHECKOUT's, not the product's -- no stamp records the revision that wrote "
                    "it.",
    )
    p.add_argument("paths", nargs="+", type=Path, help="products or directories")
    p.add_argument("--require", action="store_true",
                   help="exit 1 unless every path is 'stamped' -- the form a script wants, and "
                        "the form that makes 'all clear' mean something")
    p.set_defaults(func=_run_provenance)


def _run_provenance(args: argparse.Namespace) -> int:
    # A path with neither a file nor a sidecar behind it is a typo, not an unstamped product:
    # reported as one, a mistyped path printed a table row and exited 0.
    missing = [str(p) for p in args.paths
               if not p.exists() and not Path(str(p) + provenance.CALL_SUFFIX).exists()]
    if missing:
        print(f"arrayprobe provenance: not found (no file, directory or .call sidecar): "
              f"{', '.join(missing)}", file=sys.stderr)
        return 2
    text, code = provenance.report(args.paths, require=args.require)
    print(text)
    return code


def _attributed(args) -> int:
    """``arrayprobe attributed`` -- the self-describing sibling of a faithful product.

    Delegates to :func:`arrayprobe.attributed_export.main` rather than reimplementing the
    flag surface, the same way :func:`_make_demo_flight` does, so the subcommand and
    ``python -m arrayprobe.attributed_export`` cannot drift into accepting different
    arguments. The module form stays supported and is what ``docs/developer/ATTRIBUTED_EXPORT.md``
    cites; this is the way in for someone who installed the package and never reads it.
    """
    from arrayprobe import attributed_export

    if getattr(args, "layout", "dimensions") == "particles":
        # Opt-in: one row per particle from a proc file, straight to Parquet; the default
        # path below is unchanged. The two flags of the default path have no meaning here
        # and are refused rather than parsed and dropped.
        if args.accept_unstamped or args.enhancements:
            print("arrayprobe attributed: --accept-unstamped and --enhancements apply to "
                  "--layout dimensions only; drop them for --layout particles",
                  file=sys.stderr)
            return 2
        try:
            written = attributed_export.export_parquet(args.source, args.out,
                                                       layout="particles")
        except (ValueError, ImportError, OSError,
                attributed_export.AttributedExportError) as exc:
            print(f"arrayprobe attributed: {exc}", file=sys.stderr)
            return 2
        print(f"wrote {written}")
        return 0
    argv = [str(args.source)]
    if args.out is not None:
        argv.append(str(args.out))
    if args.accept_unstamped:
        argv.append("--accept-unstamped")
    if args.enhancements:
        argv += ["--enhancements", args.enhancements]
    return attributed_export.main(argv)


def _add_attributed(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "attributed",
        help="write the self-describing sibling of a faithful product",
        description="Writes a SECOND file beside a faithful product, carrying the same "
                    "values plus the whole .call sidecar and a sourced unit on every "
                    "variable, so a recipient can answer 'where did this number come "
                    "from' from one file. The faithful product is opened READ-ONLY and "
                    "never modified -- it is the byte-comparison artefact and carries no "
                    "attributes because the MATLAB combine step writes none. Every unit "
                    "is quoted from the MATLAB line that writes it; a product shape with "
                    "no sourced unit table is refused by name rather than exported with "
                    "a guess. Design: docs/developer/ATTRIBUTED_EXPORT.md.",
    )
    p.add_argument("source", help="the faithful product (its .call sidecar is read too)")
    p.add_argument("out", nargs="?", default=None,
                   help="output path (default: <source>.attributed.nc)")
    p.add_argument("--accept-unstamped", action="store_true",
                   help="export a product with no .call sidecar; the file then RECORDS "
                        "that its provenance is not established, rather than staying "
                        "silent about the gap")
    p.add_argument("--enhancements", default="",
                   help="comma-separated names of enhancements the producing chain "
                        "applied; empty (the default) means none, which is the port's "
                        "own case by construction")
    p.add_argument("--layout", choices=("dimensions", "particles"), default="dimensions",
                   help="'dimensions' (the default, unchanged) writes the attributed netCDF4 "
                        "sibling; 'particles' instead reads a proc (per-particle) file and "
                        "writes one Parquet table, one row per particle (default "
                        "<source>.particles.parquet); needs the [parquet] extra")
    p.set_defaults(func=_attributed)


def _make_demo_flight(args) -> int:
    """``arrayprobe make-demo-flight`` -- the quickstart input, no data needed.

    Delegates to :mod:`arrayprobe.tools.make_demo_flight`'s own ``main`` rather
    than reimplementing the flag surface, so the tool and the subcommand cannot
    drift into accepting different arguments.
    """
    from arrayprobe.tools import make_demo_flight

    argv = [str(args.path), "--seconds", str(args.seconds),
            "--tas-mps", str(args.tas_mps)]
    if args.dense:
        argv.append("--dense")
    if getattr(args, "distinct_counters", False):
        argv.append("--distinct-counters")
    if getattr(args, "with_config", False):
        argv.append("--with-config")
    return make_demo_flight.main(argv)


def _add_make_demo_flight(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "make-demo-flight",
        help="write a synthetic raw .2DS file (no campaign data required)",
        description="Builds a raw SPEC-shaped .2DS recording from nothing -- "
                    "the quickstart input, so the pipeline can be exercised "
                    "without any archived data or Octave. Synthetic, not "
                    "validated science: it proves the chain runs and writes "
                    "valid files, and is not a stand-in for the oracle-backed "
                    "validation the fidelity claims rest on. Name the output "
                    "base<YYMMDDhhmmss>.2DS if you intend to reach the combine "
                    "stage, which reads the flight date from the stem. "
                    "WITHOUT --dense the flight is deliberately sparse: its one "
                    "particle per second has an arbitrary inter-arrival time, so "
                    "sizeDist rejects every particle as sub-6 us and the combined "
                    "product is all fill value. Pass --dense for a run that yields "
                    "a real size distribution.",
    )
    p.add_argument("path", help="output path, e.g. base160101000000.2DS")
    p.add_argument("--seconds", type=int, default=5,
                   help="number of one-second records to write (default: 5)")
    p.add_argument("--tas-mps", type=float, default=130.0,
                   help="synthetic true airspeed in m/s (default: 130.0)")
    # Exposed on the subcommand by the 2026-09-16 usability audit (2.3): the tool
    # has had this
    # flag since 2026-09-13, but `arrayprobe make-demo-flight --help` did not forward
    # it, so the only demo a CLI-only user could reach produced a 68 MB all-NaN
    # product, and the one that yields a plottable PSD was undiscoverable.
    p.add_argument("--dense", action="store_true",
                   help="write the DENSE demo instead: many particles per second with "
                        "realistic inter-arrival gaps, so the size distribution comes "
                        "out populated. This is the demo to run first.")
    p.add_argument("--distinct-counters", action="store_true",
                   help="give each image packet its own particle counter (default: "
                        "the constant 7), so SODA-2's spec_index keeps every "
                        "particle; changes the written bytes")
    p.add_argument("--with-config", action="store_true",
                   help="also create the output folder if needed and write a "
                        "ready-to-run run.toml beside the flight, so `arrayprobe run "
                        "<folder>/run.toml <flight> --yes` works from a plain "
                        "pip install, without the repository's examples/ folder")
    p.set_defaults(func=_make_demo_flight)


def _make_tas_file(args) -> int:
    """``arrayprobe make-tas-file`` -- write the aircraft file the v3.5 engine requires.

    Delegates to :mod:`arrayprobe.tools.make_tas_file`'s own ``main``, the same way
    ``make-demo-flight`` does, so the tool and the subcommand cannot accept different
    arguments.
    """
    from arrayprobe.tools import make_tas_file

    argv = [str(args.path)]
    if args.from_tas_csv is not None:
        argv += ["--from-tas-csv", str(args.from_tas_csv)]
    if args.constant_tas is not None:
        argv += ["--constant-tas", str(args.constant_tas)]
    if args.start_hhmmss is not None:
        argv += ["--start-hhmmss", str(args.start_hhmmss)]
    if args.seconds is not None:
        argv += ["--seconds", str(args.seconds)]
    if args.second_rule is not None:
        argv += ["--second-rule", str(args.second_rule)]
    if args.neighbour is not None:
        argv += ["--neighbour", str(args.neighbour)]
    if args.on_unsettled is not None:
        argv += ["--on-unsettled", str(args.on_unsettled)]
    for flag in ("from_merge", "from_aircraft", "chain", "date", "probe_csv", "cutoff_mps",
                 "default_mps", "soda2_pth"):
        if getattr(args, flag) is not None:
            argv += [f"--{flag.replace('_', '-')}", str(getattr(args, flag))]
    for d in args.search or ():
        argv += ["--search", str(d)]
    return make_tas_file.main(argv)


def _add_make_tas_file(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "make-tas-file",
        help="write the aircraft TAS file the v3.5 engine requires",
        description="Writes the aircraft file stock imgProc_sm.m reads as varargin{1}: a "
                    "netCDF file with two 1-D f8 variables, `Time` (HHMMSS, e.g. 60638 for "
                    "06:06:38) and `TAS` (m/s); the image-processing stage reads those "
                    "exact names. The v3.5 engine -- the package default -- refuses "
                    "to run without one. Build it from the .tas.csv sidecar the decode "
                    "already wrote, or state a constant speed explicitly.",
    )
    p.add_argument("path", help="output path, e.g. aircraft_160906.cdf")
    p.add_argument("--from-tas-csv", default=None,
                   help="the <stem>.tas.csv the decode wrote (columns: timehhmmss, tas)")
    p.add_argument("--constant-tas", type=float, default=None,
                   help="flat series at this speed, NOT a measurement "
                        "(needs --start-hhmmss and --seconds)")
    p.add_argument("--start-hhmmss", type=float, default=None,
                   help="first sample's time as HHMMSS")
    p.add_argument("--seconds", type=int, default=None,
                   help="number of 1-Hz samples for --constant-tas")
    p.add_argument("--second-rule", choices=("round", "floor"), default=None,
                   help="fractional HHMMSS to whole seconds; default round (this package's choice)")
    p.add_argument("--neighbour", choices=("adjacent", "nearest-present"), default=None,
                   help="the neighbouring second the duplicate-second rule compares against; "
                        "default adjacent (this package's choice)")
    p.add_argument("--on-unsettled", choices=("default", "refuse"), default=None,
                   help="a duplicated second the duplicate-second rule cannot settle; default: "
                        "it takes --default-mps (this package's choice)")
    p.add_argument("--from-merge", default=None,
                   help="a campaign merge file, e.g. mrg1_<platform>_<yyyymmdd>_R*.nc")
    p.add_argument("--from-aircraft", default=None,
                   help="another registered aircraft file, e.g. ARM enaaafmergedF1.c1.*.nc")
    p.add_argument("--chain", choices=("auto", "merge", "aircraft", "probe"), default=None,
                   help="resolve the source through the fallback chain "
                        "(merge -> aircraft -> probe)")
    p.add_argument("--date", default=None, help="--chain: the flight date YYYYMMDD")
    p.add_argument("--search", action="append", default=None,
                   help="--chain: a directory holding merge/aircraft files (repeatable)")
    p.add_argument("--probe-csv", default=None, help="--chain: the decode's <stem>.tas.csv")
    p.add_argument("--cutoff-mps", type=float, default=None,
                   help="TAS above this takes --default-mps; default 300 (this package's choice)")
    p.add_argument("--default-mps", type=float, default=None,
                   help="the fall-back value; default 170, UIOOPS's own fall-back airspeed")
    p.add_argument("--soda2-pth", default=None,
                   help="also write the series as a SODA-2 op.pth ASCII file")
    p.set_defaults(func=_make_tas_file)


def _tas_from_nasa_ames(args) -> int:
    """``arrayprobe tas-from-nasa-ames`` -- a MEASURED 1 Hz TAS series for the SEA/CIP chain.

    Delegates to :mod:`arrayprobe.tools.nasa_ames_tas`'s own ``main``, the same way
    ``make-tas-file`` does, so the tool and the subcommand cannot accept different arguments.
    """
    try:
        import importlib

        nasa_ames_tas = importlib.import_module("arrayprobe.tools.nasa_ames_tas")
    except ImportError:
        print("arrayprobe tas-from-nasa-ames is not available in this release: it needs "
              "arrayprobe.tools.nasa_ames_tas, which this distribution does not ship. "
              "Use `make-tas-file` with a TAS series of your own.", file=sys.stderr)
        return 2

    argv = [str(args.path), "--out", str(args.out),
            "--flight-date", str(args.flight_date)]
    if args.drop_missing:
        argv.append("--drop-missing")
    if getattr(args, "variable", None):
        argv += ["--variable", args.variable]
    if getattr(args, "round_seconds", False):
        argv.append("--round-seconds")
    if getattr(args, "assume_units", "as-declared") != "as-declared":
        argv += ["--assume-units", args.assume_units]
    return nasa_ames_tas.main(argv)


def _add_tas_from_nasa_ames(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "tas-from-nasa-ames",
        help="convert a NASA-Ames 1001 true-air-speed file into the .tas.csv sidecar",
        description="Reads a NASA-Ames 1001 aircraft true-air-speed file (plain or .gz) and "
                    "writes the .tas.csv sidecar arrayprobe.readers.tasinfo.load_tas_info "
                    "reads, which `make-tas-file --from-tas-csv` then turns into the aircraft "
                    "netCDF the v3.5 engine requires. This is the SEA/CIP chain's route to a "
                    "MEASURED TAS: `make-tas-file --constant-tas` fabricates one and says so, "
                    "and nothing on that chain writes a sidecar of its own.",
    )
    p.add_argument("path", help="the NASA-Ames 1001 file, e.g. <stem>.SODA2_TAS.1Hz.gz")
    p.add_argument("--out", required=True, help="the .tas.csv to write")
    p.add_argument("--flight-date", required=True, metavar="YYYY-MM-DD",
                   help="the flight this series is for; must equal the file's own DATE")
    p.add_argument("--drop-missing", action="store_true",
                   help="leave out rows carrying the file's missing-value code instead of "
                        "refusing")
    p.add_argument("--variable", default=None, metavar="SUBSTRING",
                   help="name which true-air-speed variable to use, when the file declares "
                        "more than one (UND's own .basic.1Hz declares two). The reader still "
                        "refuses to choose on its own; this is how an operator chooses, and "
                        "the full name of the column used is reported")
    p.add_argument("--assume-units", default="as-declared", choices=("as-declared", "knots"),
                   help="declare the column's REAL units when they contradict the file's "
                        "header; 'knots' multiplies by 0.514444 and reports it")
    p.add_argument("--round-seconds", action="store_true",
                   help="attribute each sample to its nearest whole second, for a file whose "
                        "1 Hz grid is offset from the integer second (UND's .basic.1Hz sits "
                        "0.21 s off on the 2016 flights). The shift is reported")
    p.set_defaults(func=_tas_from_nasa_ames)


def _run(args: argparse.Namespace) -> int:
    """``arrayprobe run`` -- one line: a configuration file names the
    engine and the campaign, and this builds the batch driver's (``arrayprobe.driver.run_flight``)
    argv from it and calls its unmodified ``main()``. No pipeline logic here."""
    import glob as glob_module

    from .config import ConfigError, load_config
    try:
        cfg = load_config(args.config)
    except FileNotFoundError:
        print(f"arrayprobe run: config file {args.config} does not exist; pass the path of a "
              f"run configuration (a starting point: examples/start_here/run.toml)",
              file=sys.stderr)
        return 2
    except ConfigError as exc:
        print(f"arrayprobe run: {exc}", file=sys.stderr)
        return 2
    run = cfg.run
    if run.get("engine") == "3.1.4" and not _v314_engine_present():
        print(f"arrayprobe run: {args.config} names [run].engine = \"3.1.4\". "
              + _V314_ABSENT_MESSAGE, file=sys.stderr)
        return 2
    if run.get("engine") == "soda2":
        # Before the preset check: a SODA-2 config has no campaign preset to be missing.
        print(f"arrayprobe run: {args.config} names [run].engine = \"soda2\", which is not a "
              f"UIOPS engine and does not run through the UIOPS batch driver; use "
              f"`arrayprobe soda2 run {args.config}`", file=sys.stderr)
        return 2
    missing = [k for k in ("engine", "preset") if k not in run]
    if missing:
        print(f"arrayprobe run: {args.config} has no [run].{' / [run].'.join(missing)}; "
              f"the engine and the campaign preset are chosen by name in the file, never assumed",
              file=sys.stderr)
        return 2
    if args.uiops_version != "3.1.4" and args.uiops_version != run["engine"]:
        print(f"arrayprobe run: --uiops-version {args.uiops_version} disagrees with "
              f"[run].engine = {run['engine']!r} in {args.config}", file=sys.stderr)
        return 2
    base = Path(args.config).resolve().parent
    raw_globs = run.get("raw", [])
    assert isinstance(raw_globs, list), "config.py validates [run].raw as a list"
    raws = [str(p) for p in args.raw] or sorted(
        str(p) for pattern in raw_globs for p in glob_module.glob(str(base / str(pattern))))
    if not raws:
        print(f"arrayprobe run: no raw files -- give them on the command line or as [run].raw "
              f"globs relative to {base}", file=sys.stderr)
        return 2
    run_flight = _load_run_flight()
    preset = run_flight.PRESETS.get(str(run["preset"]))
    if "probe" in run and preset is not None and preset.probe != run["probe"]:
        # A SEA file carries several probes; the preset fixes which one the run follows, so a
        # [run].probe that names another would be silently ignored if it were not refused.
        matching = sorted(p.name for p in run_flight.PRESETS.values()
                          if p.probe == run["probe"])
        print(f"arrayprobe run: [run].probe = {run['probe']!r} but preset "
              f"{preset.name!r} processes the {preset.probe}; "
              + (f"presets for the {run['probe']}: {', '.join(matching)}" if matching
                 else f"no shipped preset processes the {run['probe']!r}"),
              file=sys.stderr)
        return 2
    tas_from_probe: list[str] = []
    probe_tas_globs = run.get("tas_from_probe", []) or []
    assert isinstance(probe_tas_globs, list), "config.py validates [run].tas_from_probe as a list"
    for pattern in probe_tas_globs:
        hits = sorted(glob_module.glob(str(base / str(pattern))))
        if not hits:
            print(f"arrayprobe run: [run].tas_from_probe entry {pattern!r} matches no file "
                  f"(relative to {base}); nothing was run", file=sys.stderr)
            return 2
        tas_from_probe += hits
    argv = [*raws, "--config", str(args.config), "--preset", str(run["preset"])]
    for hk in tas_from_probe:
        # Another probe's airspeed record on the same aircraft, for a CIP or PIP whose own
        # decode writes none; run_flight refuses it on a probe that writes its own.
        argv += ["--tas-from-probe", hk]
    if "presets" in run:
        argv += ["--presets", str((base / str(run["presets"])).resolve())]
    if "probe_case" in run:
        argv += ["--probe-case", str(run["probe_case"])]
    if "probe_case_module" in run:
        argv += ["--probe-case-module", str(run["probe_case_module"])]
    # No [run].out: the output goes beside the config, at <config dir>/output, rather than
    # falling to the driver's own default (../_decoded from the current directory).
    argv += ["--out", str((base / str(run.get("out", "output"))).resolve())]
    if "stages" in run:
        argv += ["--stages", str(run["stages"])]
    if "tas_file" in run:
        # Relative to the config, like `out`; run_flight refuses it under a
        # profile that never reads it and requires it under one that does.
        argv += ["--tas-file", str((base / str(run["tas_file"])).resolve())]
    argv += ["--engine", str(run["engine"])]
    if getattr(args, "port_validation", False):
        # R4. Forwarded, never added from the engine: the refusal (v3.1.4 without
        # the flag, or the flag under any other engine) lives in run_flight.main, so
        # `arrayprobe run` and a direct batch-driver invocation cannot disagree.
        argv.append("--port-validation")
    if cfg.borrowed_combine:
        argv.append("--borrowed-combine")
    if args.dry_run:
        argv.append("--dry-run")
    if getattr(args, "yes", False):
        # Forwarded rather than answered here: the gate, the panel and the refusal all
        # live in one place (run_flight.confirm_or_declare), so `arrayprobe run` and a direct
        # batch-driver invocation cannot come to different conclusions about the same
        # configuration. A config that declares [thresholds] is never gated at all.
        argv.append("--yes")
    for flag in ("jobs", "s2_jobs", "chunks", "enh_jobs"):
        argv += [f"--{flag.replace('_', '-')}", str(getattr(args, flag))]
    if getattr(args, "jit", False):
        argv.append("--jit")
    if getattr(args, "enhancements", False):
        # Forwarded, never decided here: the flag only says *whether* to apply, and
        # which modules, the resolution, the appliers and the refusals all live on the
        # batch-driver side (`apply_enhancements_to_run`) behind its guarded import --
        # so this module still references nothing in arrayprobe_enhancements, which is what
        # tests/test_no_enhancement_coupling.py sweeps this package's source for.
        argv.append("--enhancements")
    for flag in _RUN_OVERRIDES:
        # Forwarded, never decided here: each refusal these overrides answer lives in
        # tools/run_flight.py and names the flag, so `arrayprobe run` must accept every one
        # (tests/test_run_accepts_refusal_flags.py). Per-run decisions, flag-only, default off.
        if getattr(args, flag.replace("-", "_"), False):
            argv.append(f"--{flag}")
    for flag in _RUN_VALUE_OVERRIDES:
        # Same rule, for run_flight options that take a value: default None, so nothing is
        # forwarded unless the user names it, and run_flight's own default stands.
        value = getattr(args, flag.replace("-", "_"), None)
        if value is not None:
            argv.extend([f"--{flag}", value])
    return run_flight.main(argv)


#: run_flight's refusal overrides that `arrayprobe run` forwards, each opt-in and default off.
_RUN_OVERRIDES = {
    "accept-preset-mismatch": "run a raw file whose extension names a different probe than "
                              "the preset (a renamed file); recorded as "
                              "accept_preset_mismatch=on in the .call stamps",
    "accept-unstamped": "accept an input product with no .call stamp instead of refusing it",
    "accept-flagged": "process a raw file the input inventory flags as empty instead of "
                      "refusing it; the decode .call records the inventory flags "
                      "(inventory_empty=1), not the override",
    "accept-implausible": "accept a size distribution the plausibility gate refuses; the "
                          "override is recorded in the .call stamps",
    "allow-mixed-config": "allow inputs stamped with differing configurations to be combined",
    "libm-pow": "engine 3.1.4 only: compute S4's massBL power with libm's pow, as MATLAB "
                "does; stamped libm_pow=on into the sd .call",
}

#: run_flight options that take a value and that its messages tell the user to pass; forwarded
#: only when given (default None), so run_flight's own default applies otherwise.
#: flag -> (choices or None, help).
_RUN_VALUE_OVERRIDES = {
    "tas-grid": (("probe", "regular"), "the time vector the size-distribution stage gets under "
                 "a TAS source; run_flight's default when not given"),
    "tas-ratio": (("off", "on"), "v3.5 only: write tasRatio from an aircraft airspeed source "
                  "(changes the product); run_flight's default (off) when not given"),
    "iat-file": (None, "sizeDist's twelfth argument, the inter-arrival threshold file; "
                 "run_flight's default (a threshold file that does not exist, so the per-probe "
                 "default threshold applies) when not given"),
}


def _add_run(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "run",
        help="the one line: run a whole flight from one configuration file "
             "(the [run] table in the file drives it)",
        description="One line of code to run and one file to configure. "
                    "Every choice -- engine, fidelity profile, campaign preset, "
                    "output directory, which stages -- is named in the file "
                    "(arrayprobe.config); nothing here is assumed. Without "
                    "[run].out, output goes to an 'output' folder beside the "
                    "config file. Runs the batch driver "
                    "(arrayprobe.driver.run_flight) with every setting read from "
                    "[run] -- no new pipeline logic.",
    )
    p.add_argument("config", type=Path, help="a run configuration TOML (arrayprobe.config)")
    p.add_argument("raw", nargs="*", type=Path,
                   help="raw files; wins over [run].raw in the file")
    p.add_argument("--dry-run", action="store_true", help="preflight only, decode nothing")
    p.add_argument("--yes", "-y", action="store_true",
                   help="accept the configuration this prints without being asked. A "
                        "config that declares [thresholds] needs no confirmation and ignores "
                        "this; one that declares none is confirmed before the run starts, and "
                        "where stdin is not a terminal (a detached run, CI) it refuses to start "
                        "without this flag rather than blocking on a prompt nobody can answer.")
    p.add_argument("--jobs", type=int, default=1, metavar="N",
                   help="process N raw files at once, one worker process each (default 1). "
                        "Helps a flight recorded as many files; outputs are the same as a "
                        "one-at-a-time run.")
    p.add_argument("--enh-jobs", type=int, default=1, metavar="N",
                   help="run the out-of-focus correction across N worker processes when "
                        "--enhancements applies it (default 1). Separate from --jobs, which "
                        "spreads raw files: the corrections run after every file is done. "
                        "The written files are the same for any N.")
    p.add_argument("--s2-jobs", type=int, default=1, metavar="N",
                   help="decode one raw file across N worker processes (default 1). Helps a "
                        "flight recorded as one large file, where --jobs has nothing to "
                        "spread; the decoded file is byte-identical to a one-process decode. "
                        "2D-S/HVPS (SPEC) files only: where the engine or format has no "
                        "parallel decoder the run refuses the flag rather than ignore it.")
    p.add_argument("--chunks", type=int, default=1, metavar="N",
                   help="split each file's image processing (particle framing) into N "
                        "record ranges run in parallel and merged (default 1); the merged "
                        "file is byte-identical to an unsplit run. Independent of --jobs, "
                        "which spreads files rather than one file's records.")
    p.add_argument("--jit", action="store_true",
                   help="speed only, default off: the image-processing stage's hot kernels "
                        "through numba "
                        "(arrayprobe.jit_kernels); the proc file is byte-identical, "
                        "which the test suite checks")
    # Parsed either way, so a stale script gets run_flight's refusal (which names the reason)
    # rather than argparse's unknown-flag error; listed in --help only with the engine present.
    p.add_argument("--port-validation", action="store_true",
                   help=("forwarded to the batch driver: required when [run].engine is 3.1.4 "
                         "and refused under any other engine. The v3.1.4 engine is "
                         "the ORACLES-validation anchor only; this flag declares the run port "
                         "validation and stamps port_validation=on into every .call it writes, "
                         "marking the output not for quoting. Changes no computed byte. "
                         "Where the v3.1.4 engine is not installed, the run exits 2 saying so.")
                   if _v314_engine_present() else argparse.SUPPRESS)
    p.add_argument("--enhancements", action="store_true",
                   help="default off: after the stages finish, apply the corrections this "
                        "config's [enhancements] table names to the products the run wrote, "
                        "each into its own <stem>.enh.<stage>.nc with an `enhancements=` "
                        "fragment in its .call. Off, the run is byte-identical to one "
                        "without the flag; the port's own outputs are never overwritten "
                        "either way. Needs `pip install arrayprobe-uiops-enhancements`.")
    for flag, why in _RUN_OVERRIDES.items():
        p.add_argument(f"--{flag}", action="store_true",
                       help=(argparse.SUPPRESS
                             if flag == "libm-pow" and not _v314_engine_present()
                             else f"default off, forwarded to the batch driver: {why}"))
    for flag, (choices, why) in _RUN_VALUE_OVERRIDES.items():
        p.add_argument(f"--{flag}", choices=choices, default=None,
                       help=f"forwarded to the batch driver only when given: {why}")
    p.set_defaults(func=_run)


def _reprocess(args: argparse.Namespace) -> int:
    """``arrayprobe reprocess`` -- the body is ``scripts/reprocess.py``'s ``run``; the engine comes
    from the product's own stamp, so a top-level ``--uiops-version`` that disagrees is refused
    rather than silently overridden (the rule ``run`` applies to ``[run].engine``).

    **The stamp is now read before anything runs, and an absent one refuses** (since
    2026-09-18). Until then this function read the sidecar itself with
    ``stamp.startswith("engine=3.5 ")``, under which a missing sidecar, a lane script's JSON
    sidecar and a truncated sidecar all answered ``"3.1.4"`` -- and the whole check was skipped
    unless the user had passed ``--uiops-version``, which is its default. So the common case
    was: no check, and a wrong answer available if there had been one.
    :func:`arrayprobe.provenance.engine_of` answers ``None`` by raising instead.
    """
    tool = _load_reprocess()
    try:
        stamped = provenance.engine_of(args.product)
    except (provenance.Unstamped, provenance.EngineUnrecorded) as exc:
        print(f"arrayprobe reprocess: {exc}", file=sys.stderr)
        print(f"Nothing was run. `arrayprobe provenance {args.product}` shows the state; there "
              f"is no --accept-unstamped here, on purpose: a product of unknown configuration "
              f"cannot be re-run 'exactly as recorded'.", file=sys.stderr)
        return 2
    if args.uiops_version != "3.1.4" and args.uiops_version != stamped:
        print(f"arrayprobe reprocess: --uiops-version {args.uiops_version} disagrees with the "
              f"UIOPS {stamped} engine {args.product.name}'s stamp records", file=sys.stderr)
        return 2
    return tool.run(args)


def _add_reprocess(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "reprocess",
        help="re-run the stage that wrote a proc/sd product, exactly as its .call stamp "
             "records, and report whether the result is identical",
        description="Reads the product's .call sidecar, re-runs the one stage that wrote it "
                    "(image processing for proc.*, size distribution for sd.*; either engine, "
                    "from the stamp) under exactly that "
                    "configuration, from the input beside it, and diffs the fresh file against "
                    "the product. Refuses -- exit 2, nothing run -- unless the batch driver's "
                    "own label function regenerates the recorded stamp character for character, "
                    "and unless the stage's input carries the matching stamp. Exit 0 identical "
                    "(Creation Time skipped, source paths compared by basename), 1 differs. The "
                    "fresh file is written to a temporary directory and discarded; the product "
                    "is never modified. Decode and combine products are refused: their stamps do "
                    "not record the raw file or the combine call.",
    )
    p.add_argument("product", type=Path,
                   help="a proc.*.nc (image processing) or sd.*.nc (size distribution) file "
                        "with its .call sidecar beside it")
    p.add_argument("--preset", required=True,
                   help="the campaign preset the product was run under (the batch driver's "
                        "PRESETS). REQUIRED: no stamp records the preset, so it is named, never "
                        "assumed")
    p.add_argument("--tas-file", type=Path, default=None,
                   help="the aircraft TAS file, for a proc.* product whose stamp names one (the "
                        "stamp records its basename only, which must match). Not needed for a "
                        "product made under a TAS source chain: the chain's own "
                        "<stem>.tas_<tier>.cdf beside it is read instead")
    p.set_defaults(func=_reprocess)


def _soda2_enhancement_table(cfg, protective_mode: str | None = None) -> dict:
    """The SODA-2 correction registry as the ``.pbp.call`` sidecar and ``soda2 enhancements``
    report it. The port never imports ``arrayprobe_soda2_enhancements`` unguarded: the
    package is optional, and its absence is a recorded state, not an error. Now
    the corrections are **applied**: ``_soda2_run`` wraps the driver in the
    package's ``registry.apply``, which substitutes each routable resolved-ON correction at
    an ``arrayprobe_soda2.enhancement_hooks`` point and fills ``applied``/``skipped``/
    ``hook_points`` here from its record.

    ``protective_mode`` is ``None`` (no command-line flag: the config's ``[enhancements]
    protective = true/false`` selects ``"on"``/``"off"``, and its absence ``"auto"``), ``"auto"``
    (resolve ``registry.protective_set`` for this run's probe), ``"on"`` (every
    :data:`registry.PROTECTIVE` name, ignoring ``registry.LINEAGE_PROBES``) or ``"off"``
    (none). This is A14's SODA-2 equivalent of the UIOOPS batch driver's ``--protective``.
    An explicit ``[enhancements] <name> = false`` in the config still wins over a protective
    default, exactly as :func:`registry.resolve` states.

    Registration is an import-time side effect of each correction module, so every module of
    the package is imported before the registry is read -- importing ``registry`` alone
    leaves ``REGISTRY`` empty (measured 2026-09-14). ``requested`` is the file's own
    ``[enhancements]`` table, kept even when the package is absent so an opt-out the file
    states is never lost from the record. Raises the registry's ``UnknownEnhancement`` for a
    name the package does not ship."""
    requested = dict(sorted((getattr(cfg, "enhancements", None) or {}).items()))
    if protective_mode is None:
        # No --protective on the command line: the config's `[enhancements] protective = …`
        # decides, as in the UIOOPS batch driver (`run_flight.py`'s PROTECTIVE_MODE); the
        # command line wins when given.
        declared = requested.get("protective")
        protective_mode = "auto" if declared is None else ("on" if declared else "off")
    import importlib
    import pkgutil
    try:
        import arrayprobe_soda2_enhancements as soda2_enh
        from arrayprobe_soda2_enhancements import registry as soda2_registry
    except ImportError:
        return {"package": "not installed", "requested": requested, "resolved": {},
                "applied": [], "skipped": {}, "protective_mode": protective_mode,
                "protective_set": []}
    # Outside the guard on purpose: a correction module that fails to import in an INSTALLED
    # package is a real error, not "package not installed".
    for mod in pkgutil.iter_modules(soda2_enh.__path__):
        if mod.name != "registry" and not mod.name.startswith("_"):
            importlib.import_module(f"arrayprobe_soda2_enhancements.{mod.name}")
    probe = str((getattr(cfg, "soda2", None) or {}).get("probetype", ""))
    if protective_mode == "off":
        protective: frozenset[str] = frozenset()
    elif protective_mode == "on":
        protective = soda2_registry.PROTECTIVE
    else:
        protective = soda2_registry.protective_set(probe=probe)
    try:
        resolved = soda2_registry.resolve_from_config(cfg, protective=protective)
    except soda2_registry.UnknownEnhancement as exc:
        from .config import ConfigError
        raise ConfigError(str(exc.args[0]) if exc.args else str(exc)) from exc
    return {
        "package": "installed",
        "requested": requested,
        "resolved": dict(sorted(resolved.items())),
        "reachability": {n: s.reachability for n, s in sorted(soda2_registry.REGISTRY.items())},
        "protective_mode": protective_mode,
        "protective_set": sorted(protective),
        # Filled by `_soda2_run` from `registry.apply`'s record: the driver
        # adapter applies every resolved-ON correction it can route.
        "applied": [],
        "skipped": {},
    }


def _soda2_versions() -> dict[str, str]:
    from importlib import metadata
    out: dict[str, str] = {}
    for dist in ("arrayprobe", "arrayprobe-soda2-enhancements"):
        try:
            out[dist] = metadata.version(dist)
        except metadata.PackageNotFoundError:
            out[dist] = "not installed"
    return out


def _soda2_jsonable(v):
    """One resolved ``op`` value as JSON: arrays as lists, NumPy scalars as their Python value.
    The NumPy dtype is recorded separately (``op_dtypes``), because in SODA-2 it is part of
    what the run computed -- e.g. a FLOAT vs DOUBLE ``op.rate`` sets ``activetime``'s dtype
    (``process_2d.py``, S6-e) -- and ``str()`` of an ``np.int16`` would record ``"0"``, a
    string, where the driver saw an INT16."""
    if isinstance(v, np.ndarray):
        return v.tolist()
    if isinstance(v, np.generic):
        return v.item()
    if isinstance(v, (list, tuple)):
        return [_soda2_jsonable(x) for x in v]
    return v


def _soda2_run(args: argparse.Namespace) -> int:
    """``arrayprobe soda2 run <config> [--out DIR]``: ``load_config`` -> ``op = [soda2]`` ->
    the enhancement table (resolved when the optional package is installed, and then applied
    through its ``registry.apply`` around the driver call) -> ``soda2_process_2d(op)`` ->
    ``<stem>.pbp.call`` beside the outputs, where
    ``<stem>`` is the PBP files' own (``soda2_filename.pro``: ``<date>_<hhmmss>_<shortname>
    [_<probeid>]``), so two windows written to one directory never share a sidecar. The
    sidecar is deterministic (no timestamp): two runs of one config are byte-identical.

    Exit 2 for a config this command cannot run; exit 1 when the driver returns no data
    (``soda2_process_2d.pro:430-433`` / ``:576``, the IDL ``return`` with no output) -- no
    sidecar is written then, and any PBP file the driver opened is left as S6-f leaves it."""
    import json

    from arrayprobe_soda2.pbp_writer import pbp_filename, soda2_stamp_profile
    from arrayprobe_soda2.process_2d import (
        REPORT_EVERY_BUFFERS,
        soda2_process_2d,
    )
    from arrayprobe_soda2.process_2d_parallel import Soda2ParallelRefused

    from .config import ConfigError, load_config
    try:
        cfg = load_config(args.config)
    except (ConfigError, FileNotFoundError) as exc:
        print(f"arrayprobe soda2 run: {exc}", file=sys.stderr)
        return 2
    if cfg.run.get("engine", "soda2") != "soda2":
        print(f"arrayprobe soda2 run: {args.config} names [run].engine = "
              f"{cfg.run['engine']!r}; this command runs the SODA-2 engine only", file=sys.stderr)
        return 2
    if not cfg.soda2:
        print(f"arrayprobe soda2 run: {args.config} has no [soda2] table (the driver's op "
              f"fields)", file=sys.stderr)
        return 2
    # [outputs] selections the SODA-2 engine has not built yet are refused by name, never
    # ignored; an all-false [outputs] runs exactly as a file without the section. [arm] is read
    # only by an ARM output, so it is refused while that output is unbuilt. Built:
    # `faithful_attributed` (the run's `<stem>.nc` and its attributed sibling) and
    # `analysis_ready` (how that attributed file is stored).
    built = {"faithful_attributed", "analysis_ready", "enhanced_attributed"}
    unbuilt = sorted(k for k, v in cfg.outputs.items() if v is not False and k not in built)
    if unbuilt:
        print(f"arrayprobe soda2 run: {args.config}: [outputs] {unbuilt} not yet implemented "
              f"for engine soda2; set them false or remove them", file=sys.stderr)
        return 2
    if cfg.arm:
        print(f"arrayprobe soda2 run: {args.config}: [arm] is read only by the ARM output, "
              f"not yet implemented for engine soda2; remove [arm]", file=sys.stderr)
        return 2
    protective_mode = getattr(args, "protective", None)
    try:
        enh = _soda2_enhancement_table(cfg, protective_mode=protective_mode)
    except ConfigError as exc:
        print(f"arrayprobe soda2 run: {args.config}: {exc}", file=sys.stderr)
        return 2
    # `[outputs] enhanced_attributed = true` makes the run two passes: the faithful pass below
    # runs with the protective corrections OFF and no [enhancements] (today's file names), and
    # a corrected pass after it carries the resolved set under `<stem>.enh.*`. A run without
    # that selection is one pass, exactly as before.
    two_pass = cfg.outputs.get("enhanced_attributed") is True
    enh_corrected = enh
    if two_pass:
        enh = {"package": enh["package"], "pass": "faithful", "requested": {}, "resolved": {},
               "applied": [], "skipped": {}, "protective_mode": "off", "protective_set": []}
    op = dict(cfg.soda2)
    if args.out is not None:
        op["outdir"] = str(Path(args.out).resolve()) + os.sep
    if op.get("outdir"):
        # Before the driver runs, not only after it returns: with particlefile = 1 the driver
        # opens the per-particle CSV itself partway through, and a directory that did not yet
        # exist failed there with FileNotFoundError (the "--out trap" the SODA-2 example READMEs
        # told users to work around with mkdir).
        Path(str(op["outdir"])).mkdir(parents=True, exist_ok=True)
    apply = None
    if enh["package"] == "installed":
        try:
            # Sentinel-then-conditional-import: `apply` is `None` above so the
            # name always exists whether or not the optional package is
            # installed, and TheCliNeverImportsTheSoda2PackageUnguarded (see
            # tests/test_cli_soda2.py) depends on this exact
            # try/except ImportError shape -- restructure the guard and that
            # AST sweep stops seeing it as guarded. mypy has no way to type an
            # import that may or may not rebind a name to a different type
            # than its sentinel; the code itself is correct, so this is a
            # scoped ignore rather than a rewrite.
            from arrayprobe_soda2_enhancements.registry import (  # type: ignore[no-redef,assignment]
                apply,
            )
        except ImportError:  # keeps TheCliNeverImportsTheSoda2PackageUnguarded green
            apply = None
    if apply is None and not two_pass and enh.get("requested"):
        # The one-pass path says what the two-pass path says when the config asks for
        # [enhancements] the optional package cannot supply, rather than running silently.
        print("ENHANCED skipped: no correction applies to this run (the optional SODA-2 "
              "enhancements package is not installed); no <stem>.enh.* written",
              file=sys.stderr)
    # `--jobs`/`--chunks` are resource knobs: they reach the driver as call
    # arguments and are NOT written into `op`, so the `.pbp.call` sidecar's `op`
    # record stays the IDL struct and two runs at different `--jobs` produce the
    # same sidecar -- which is the honest record, because they produce the same
    # numbers (tests/test_soda2_parallel.py).
    jobs, chunks = int(getattr(args, "jobs", 1) or 1), int(getattr(args, "chunks", 0) or 0)
    # `--jit` is the same kind of knob, and is ORed with `[run].jit` rather than
    # overriding it: the flag can only turn the kernel ON, so a config that asks
    # for it cannot be silently switched off by a command line that omits it.
    # It is likewise not written into `op` -- it moves no written byte.
    jit = bool(getattr(args, "jit", False)) or bool(cfg.run.get("jit", False))
    # In-file provenance: SODA-2 has no fidelity profile, so the name a run is made under is its
    # config file's -- written as `.pbp.nc`'s `arrayprobe_profile`, never into `op`.
    stamp = soda2_stamp_profile(args.config)
    try:
        if apply is not None and not two_pass:
            with apply(enh["resolved"]) as applied_record:
                d = soda2_process_2d(op, report_every=REPORT_EVERY_BUFFERS,
                                     jobs=jobs, chunks=chunks, jit=jit,
                                     stamp_profile=stamp)
            enh["applied"] = applied_record["applied"]
            enh["skipped"] = applied_record["skipped"]
            enh["hook_points"] = applied_record["hook_points"]
        else:
            d = soda2_process_2d(op, report_every=REPORT_EVERY_BUFFERS,
                                 jobs=jobs, chunks=chunks, jit=jit,
                                 stamp_profile=stamp)
    except Soda2ParallelRefused as exc:
        print(f"arrayprobe soda2 run: {exc}", file=sys.stderr)
        return 2
    if d is None:
        print(f"arrayprobe soda2 run: soda2_process_2d returned no data for {args.config} "
              f"(no buffers in [starttime, stoptime], soda2_process_2d.pro:430-433/:576); "
              f"no .pbp.call written", file=sys.stderr)
        return 1
    outdir = str(d.op.get("outdir") or (str(Path(args.config).resolve().parent) + os.sep))
    Path(outdir).mkdir(parents=True, exist_ok=True)
    sidecar = Path(pbp_filename(d.op, str(d.op["shortname"]), extension=".pbp.call",
                                outdir=outdir))
    # The probe the run decoded, named at the top level beside `engine` so a reader of the
    # sidecar sees `format=RAF probetype=F2DC_v2 subformat=3` without walking `op`; the values
    # are `op`'s own after `update_op`, so the two cannot disagree.
    record = _soda2_record(d, args.config, enh,
                           {"pbp_csv": d.pbp_csv_path, "pbp_ncdf": d.pbp_ncdf_path})
    sidecar.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {sidecar}")
    if cfg.outputs.get("faithful_attributed") is True:
        # After the sidecar: the attributed export reads `<stem>.pbp.call` as the run record.
        _soda2_write_attributed(d, outdir,
                                analysis_ready=cfg.outputs.get("analysis_ready") is not False)
    if two_pass:
        return _soda2_corrected_pass(
            op, enh_corrected, apply, config_path=args.config, outdir=outdir,
            jobs=jobs, chunks=chunks, jit=jit, stamp=stamp,
            analysis_ready=cfg.outputs.get("analysis_ready") is not False)
    return 0


def _soda2_record(d, config_path, enh: dict, outputs: dict) -> dict:
    """The ``.pbp.call`` record of one SODA-2 pass (the same shape for both passes)."""
    return {
        "engine": "soda2",
        "probe": {k: _soda2_jsonable(d.op.get(k)) for k in ("format", "probetype", "subformat")},
        "config_path": str(Path(config_path).resolve()),
        "op": {k: _soda2_jsonable(v) for k, v in d.op.items()},
        "op_dtypes": {k: str(np.asarray(v).dtype) for k, v in d.op.items()
                      if isinstance(v, (np.ndarray, np.generic))},
        "enhancements": enh,
        "versions": _soda2_versions(),
        "outputs": outputs,
    }


def _soda2_corrected_pass(op: dict, enh: dict, apply, *, config_path, outdir: str, jobs: int,
                          chunks: int, jit: bool, stamp, analysis_ready: bool) -> int:
    """The corrected pass of a two-pass ``[outputs] enhanced_attributed = true`` run.

    Runs the driver again inside ``apply(...)`` with the resolved set (the protective
    corrections for the probe and any ``[enhancements]`` the config selects), with the same
    ``jobs``/``chunks``/``jit`` as the faithful pass. The driver writes into a private
    subdirectory of ``outdir``, and each file is then moved beside the faithful ones under
    ``<stem>.enh.<rest>``, so the faithful pass's files are never touched. Its record is
    ``<stem>.enh.pbp.call``, then ``<stem>.enh.nc`` and its attributed sibling.

    When no correction applies (the optional package is not installed, or the resolved set is
    empty), the pass is skipped with a named line and no copy of the faithful files is
    written. Returns the run's exit code."""
    import json

    from arrayprobe import attributed_export
    from arrayprobe_soda2.export_ncdf import write_run_psd
    from arrayprobe_soda2.pbp_writer import pbp_filename
    from arrayprobe_soda2.process_2d import REPORT_EVERY_BUFFERS, soda2_process_2d

    on = sorted(n for n, v in (enh.get("resolved") or {}).items() if v)
    if apply is None or not on:
        why = ("the optional SODA-2 enhancements package is not installed" if apply is None
               else "the resolved set is empty for this probe and config")
        print(f"ENHANCED skipped: no correction applies to this run ({why}); "
              f"no <stem>.enh.* written")
        return 0
    work = Path(outdir) / ".enh_pass"
    work.mkdir(parents=True, exist_ok=True)
    op2 = dict(op)
    op2["outdir"] = str(work.resolve()) + os.sep
    enh = dict(enh, **{"pass": "corrected"})
    with apply(enh["resolved"]) as applied_record:
        d = soda2_process_2d(op2, report_every=REPORT_EVERY_BUFFERS, jobs=jobs, chunks=chunks,
                             jit=jit, stamp_profile=stamp)
    enh["applied"] = applied_record["applied"]
    enh["skipped"] = applied_record["skipped"]
    enh["hook_points"] = applied_record["hook_points"]
    if d is None:
        print("arrayprobe soda2 run: the corrected pass returned no data; no <stem>.enh.* "
              "written", file=sys.stderr)
        return 1
    stem = Path(pbp_filename(d.op, str(d.op["shortname"]), extension="", outdir="")).name

    def _move(path) -> str | None:
        if not path:
            return None
        src = Path(str(path))
        if not src.is_file():
            return str(path)
        rest = src.name[len(stem):] if src.name.startswith(stem) else "." + src.name
        dst = Path(outdir) / f"{stem}.enh{rest}"
        os.replace(src, dst)
        return str(dst)

    outputs = {"pbp_csv": _move(d.pbp_csv_path), "pbp_ncdf": _move(d.pbp_ncdf_path)}
    sidecar = Path(outdir) / f"{stem}.enh.pbp.call"
    record = _soda2_record(d, config_path, enh, outputs)
    sidecar.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {sidecar}")
    psd: Path | None
    try:
        psd = Path(str(_move(write_run_psd(d, outdir=str(work) + os.sep))))
    except Exception as exc:  # noqa: BLE001 -- never lose the finished run to an extra file
        print(f"arrayprobe soda2 run: PSD <stem>.enh.nc skipped: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        psd = None
    if psd is not None:
        print(f"wrote {psd}")
        try:
            written = attributed_export.export(psd, analysis_ready=analysis_ready)
            print(f"wrote {written}")
        except Exception as exc:  # noqa: BLE001 -- the same rule
            print(f"arrayprobe soda2 run: ATTRIBUTED skipped for {psd.name}: "
                  f"{type(exc).__name__}: {exc}", file=sys.stderr)
    for left in sorted(work.iterdir()):
        # the driver's other files (housekeeping and the like) take the same .enh. name
        if left.is_file():
            print(f"wrote {_move(left)}")
    try:
        work.rmdir()  # only when empty: anything unexpected the driver left is kept
    except OSError:
        pass
    return 0


def _soda2_write_attributed(d, outdir: str, *, analysis_ready: bool) -> Path | None:
    """``[outputs] faithful_attributed = true`` for a SODA-2 run: the run's size-distribution
    file ``<stem>.nc`` (:func:`arrayprobe_soda2.export_ncdf.write_run_psd` on the struct the
    driver returned) and its attributed sibling beside it, named by
    :func:`arrayprobe.attributed_export.default_output_path` exactly as the UIOOPS driver names
    its own.

    A failure of either is logged by name and never fails the run, as in the UIOOPS driver's
    ``write_attributed``: the faithful PBP files and their ``.pbp.call`` are already written.
    Returns the attributed path, or ``None`` when it was not written."""
    from arrayprobe import attributed_export
    from arrayprobe_soda2.export_ncdf import write_run_psd

    try:
        psd = Path(write_run_psd(d, outdir=outdir))
    except Exception as exc:  # noqa: BLE001 -- never lose the finished run to an extra file
        print(f"arrayprobe soda2 run: PSD <stem>.nc skipped: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return None
    print(f"wrote {psd}")
    try:
        written = attributed_export.export(psd, analysis_ready=analysis_ready)
    except Exception as exc:  # noqa: BLE001 -- the same rule
        print(f"arrayprobe soda2 run: ATTRIBUTED skipped for {psd.name}: "
              f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return None
    print(f"wrote {written}")
    return written


def _soda2_enhancements(args: argparse.Namespace) -> int:
    """``arrayprobe soda2 enhancements [config]``: the registry with reachability and, given
    a config, each correction's resolved state; or "package not installed"."""
    from .config import ConfigError, load_config
    cfg = None
    if args.config is not None:
        try:
            cfg = load_config(args.config)
        except (ConfigError, FileNotFoundError) as exc:
            print(f"arrayprobe soda2 enhancements: {exc}", file=sys.stderr)
            return 2
    try:
        table = _soda2_enhancement_table(cfg, protective_mode=getattr(args, "protective", None))
    except ConfigError as exc:
        print(f"arrayprobe soda2 enhancements: {args.config}: {exc}", file=sys.stderr)
        return 2
    if table["package"] == "not installed":
        print("arrayprobe_soda2_enhancements: package not installed "
              "(pip install arrayprobe-soda2-enhancements)")
        return 0
    try:
        from arrayprobe_soda2_enhancements._adapter import NOT_ROUTED
    except ImportError:  # keeps TheCliNeverImportsTheSoda2PackageUnguarded green
        NOT_ROUTED = {}
    print(f"protective: mode={table['protective_mode']} "
          f"set={','.join(table['protective_set']) or '(none)'}")
    print(f"{'name':32s} {'reachability':12s} {'resolved':8s} applied")
    for name, reach in table["reachability"].items():
        on = table["resolved"].get(name, False)
        if not on:
            state = "-"
        elif name in NOT_ROUTED:
            state = f"no ({NOT_ROUTED[name]})"
        else:
            state = "yes"
        print(f"{name:32s} {reach:12s} {str(on):8s} {state}")
    return 0


#: The two things a SODA-2 user needs before writing a config. Shown under
#: `soda2 run --help`, and so on the generated CLI reference page. The GDL measurement behind
#: the FLOAT claim: `help, fltarr(3)+{rate:1}.rate` is FLOAT, `...{rate:1.0d}...` DOUBLE.
_SODA2_CONFIG_NOTE = """\
The config file: [run] holds engine = "soda2" and, optionally, jit = true
(the same switch as --jit, and the two are ORed); [soda2] holds the op
fields, names unchanged from IDL; [enhancements] is optional. No [fidelity]
table: the SODA-2 engine has one source tree and reads no UIOOPS profile, so
naming one is refused. Raw file and output
directory are [soda2].fn and [soda2].outdir (--out overrides outdir).

IDL types: TOML carries no IDL type, so every [soda2] number arrives as a
Python int or float, where the IDL op held INT or FLOAT. A field left out
takes soda2_update_op's default with IDL's own dtype. In IDL, activetime =
fltarr(n) + op.rate is FLOAT unless op.rate is DOUBLE (1.0d). The driver
reads a Python int rate as INT, so rate = 1 gives FLOAT as example_batch.pro's
rate=1 does; a TOML float such as rate = 1.0 is DOUBLE. A nonzero FLOAT
timeoffset is widened from FLOAT in IDL; to reproduce it, call the driver
from Python with numpy.float32 values, e.g. op["timeoffset"] =
numpy.float32(0.5):
  from arrayprobe_soda2.process_2d import soda2_process_2d
"""


def _reproduce_report(args: argparse.Namespace) -> int:
    from arrayprobe.reproduce_report import render_markdown, write_report

    rep = write_report(args.product, args.archived, out_md=args.out, out_json=args.json)
    if not args.out:
        print(render_markdown(rep), end="")
    return 0 if rep["identical"] else 1


def _add_reproduce_report(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "reproduce-report",
        help="compare a product with an archived product, listing every differing cell",
        description="Read-only. Compares every variable the two netCDF files share, cell "
                    "by cell, and reports cells compared, exact matches, max absolute and "
                    "relative residual, every differing cell, and the engine and .call "
                    "stamp of each file. Exits 0 when exact, 1 otherwise.",
    )
    p.add_argument("product", help="the product to check (netCDF)")
    p.add_argument("archived", help="the archived product (netCDF)")
    p.add_argument("--out", help="write the Markdown report here (default: stdout)")
    p.add_argument("--json", help="also write the report as JSON here")
    p.set_defaults(func=_reproduce_report)


def _add_soda2(sub: argparse._SubParsersAction) -> None:
    import textwrap

    # Filled here, not by argparse, because the raw formatter (kept for the epilog's code
    # line) would otherwise print the description as one unwrapped line.
    p = sub.add_parser(
        "soda2",
        help="the SODA-2 engine (arrayprobe_soda2, a faithful port of NCAR's IDL): "
             "run a config, or list its enhancements",
        description=textwrap.fill(
            "`soda2 run` reads [soda2] (the driver's op fields) from a config whose "
            "[run].engine is \"soda2\", runs soda2_process_2d and writes a deterministic "
            "<stem>.pbp.call sidecar beside the PBP outputs, <stem> being theirs. "
            "With the optional correction package installed, every resolved-ON "
            "correction the driver adapter can route is applied and the sidecar records "
            "which were applied and which skipped, with the reason. "
            "`soda2 enhancements` lists the optional correction package's "
            "registry. The UIOOPS version options do not apply to this engine, and `arrayprobe "
            "run` refuses a soda2 config with a pointer here. What a soda2 config may "
            "hold, and the IDL-type limit on op.rate: `soda2 run --help`.", width=76),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    verbs = p.add_subparsers(dest="verb", required=True)
    r = verbs.add_parser("run", help="run soda2_process_2d from a config file",
                         description=textwrap.fill(
                             "Run soda2_process_2d with op = the file's [soda2] table and "
                             "write <stem>.pbp.call beside the PBP outputs. Exit 2 for a "
                             "config it cannot run, 1 when the driver returns no data.",
                             width=76),
                         epilog=_SODA2_CONFIG_NOTE,
                         formatter_class=argparse.RawDescriptionHelpFormatter)
    r.add_argument("config", type=Path, help="a run configuration TOML with a [soda2] table")
    r.add_argument("--out", type=Path, default=None,
                   help="output directory; overrides [soda2].outdir")
    r.add_argument("--jobs", type=int, default=1, metavar="N",
                   help="split soda2_process_2d's buffer loop across N processes "
                        "(default 1, serial). Byte-identical to serial -- asserted by "
                        "tests/test_soda2_parallel.py, not claimed here -- and refused "
                        "by name where it would not be (op.stuckbits, "
                        "op.activetimefrommissed, more than one raw file). It "
                        "composes with the correction package: the enhancements are "
                        "rebuilt by name inside each worker and the split stays "
                        "byte-identical to serial with them ON "
                        "(tests/test_soda2_parallel_enhancements.py), so --jobs is not "
                        "a choice between fast and corrected. A resource "
                        "knob, not a threshold: it is a flag and not a config key, "
                        "because a config file may select a run's science and never "
                        "describe it")
    r.add_argument("--chunks", type=int, default=0, metavar="N",
                   help="how many contiguous buffer ranges --jobs splits the loop into "
                        "(default 0 = 4 per job). More than one per job because a "
                        "buffer's cost is its particle count, so equal buffer counts "
                        "are not equal work. SODA-2 engine only, and read ONLY when "
                        "--jobs > 1: with --jobs left at 1 this value is accepted and "
                        "never looked at (process_2d.py's `if jobs > 1:` is its one "
                        "reader), so it is a balance knob for the split and not a way "
                        "to break one long run into resumable pieces")
    r.add_argument("--jit", action="store_true",
                   help="SODA-2 engine only. Speed only, default off: route "
                        "label_blobs's flood fill -- and fillholes' own call to it -- "
                        "through numba (arrayprobe_soda2.jit_kernels; needs "
                        "pip install \"arrayprobe[jit]\"). The PBP files are byte-identical to a "
                        "run without it, asserted in "
                        "tests/test_soda2_jit_product_identity.py (the written product, "
                        "off against on) over tests/test_soda2_label_region_jit_identity.py "
                        "(the kernel's own array) and not claimed here, so it is not "
                        "written into op and the .pbp.call sidecar is "
                        "the same either way. Measured 36.2x at the kernel. It installs "
                        "no substitution (a --jit run leaves every enhancement_hooks "
                        "point pristine, measured), so it composes with --jobs and "
                        "--chunks at the engine level and the same module asserts that. "
                        "With arrayprobe-soda2-enhancements installed, the two speedups "
                        "and the corrections compose in one run. "
                        "`[run].jit = true` in the config does "
                        "the same thing; the two are ORed, so this flag can turn the "
                        "kernel on and never off")
    r.add_argument("--protective", choices=("auto", "on", "off"), default=None,
                   help="The protective-corrections rule applied to SODA-2: which of "
                        "arrayprobe_soda2_enhancements.registry.PROTECTIVE (the corrections "
                        "for data-destroying upstream defects) run by default. 'auto' (the "
                        "default) resolves registry.protective_set for this config's "
                        "[soda2].probetype; 'on' applies every PROTECTIVE name regardless of "
                        "probe; 'off' applies none of them. Omitted, the config's "
                        "[enhancements] protective = true/false decides (else 'auto'). "
                        "An explicit "
                        "[enhancements] <name> = false in the config still wins over a "
                        "protective default. Recorded in the .pbp.call sidecar's "
                        "enhancements.protective_mode/protective_set")
    r.set_defaults(func=_soda2_run)
    e = verbs.add_parser("enhancements",
                         help="list the SODA-2 corrections (reachability; resolved state "
                              "from a config if given)")
    e.add_argument("config", nargs="?", type=Path, default=None)
    e.add_argument("--protective", choices=("auto", "on", "off"), default=None,
                   help="same meaning as `soda2 run --protective`")
    e.set_defaults(func=_soda2_enhancements)


def _pct(a: float, b: float) -> str:
    return f"{100 * a / b:6.1f}%" if b else "   nan%"


def _validate_by_condition(args) -> int:
    """``arrayprobe validate by-condition`` -- formatting only.

    Every number comes from :func:`arrayprobe.validate_by_condition.stratify`,
    which is where it moved on 2026-09-10 so that something could assert on it.
    This function decides column widths and nothing else.
    """
    try:
        ref = args.product or by_condition_module.find_product(
            args.combined, args.product_dir)
    except ValueError as e:  # no --product-dir and no ARRAYPROBE_PRODUCT_DIR
        print(e, file=sys.stderr)
        return 2
    if not ref:
        print("no archived product found", file=sys.stderr)
        return 2
    if not os.path.isfile(args.combined):
        print(f"not a file: {args.combined}", file=sys.stderr)
        return 2

    st = by_condition_module.stratify(
        args.combined, ref, args.window, args.drop_bins)

    print(f"ours {os.path.basename(st.ours_path)}")
    print(f"ref  {os.path.basename(st.ref_path)}")
    line = f"shared seconds {st.shared_seconds:,}"
    if args.window:
        line += f", in window {st.window_seconds:,}"
    print(line)
    print()
    print(f"{'condition':20s} {'secs':>6s} {'all: ours/ref':>20s} "
          f"{'ratio':>7s}   {'used: ours/ref':>18s} {'ratio':>7s}   "
          f"{'exact secs':>12s}")
    for b in (*st.bands, st.overall):
        print(f"{b.label:20s} {b.seconds:6,} "
              f"{b.all_ours:10,.0f}/{b.all_ref:<9,.0f} "
              f"{_pct(b.all_ours, b.all_ref)}   "
              f"{b.used_ours:8,.0f}/{b.used_ref:<9,.0f} "
              f"{_pct(b.used_ours, b.used_ref)}   "
              f"{b.exact_seconds:6,}/{b.seconds:<,}")
    return 0


def _validate_timing_closure(args) -> int:
    for path in (args.decoded, args.proc):
        if not os.path.isfile(path):
            print(f"not a file: {path}", file=sys.stderr)
            return 1
    try:
        r = timing_closure_module.check_closure(
            args.decoded, args.proc, day_rollover_h=args.day_rollover_h)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"decoded file : {args.decoded}  ({r.n_records} records)")
    print(f"proc file    : {args.proc}  ({r.n_particles} particles)")
    print(f"particle-clock span : {r.particle_clock_span_s:.3f} s")
    print(f"record-clock span   : {r.record_clock_span_s:.3f} s")
    print(f"difference          : {r.difference_s:+.3f} s")
    print(f"ratio (particle/record) : {r.ratio:.4f}")
    print()
    print("No published tolerance exists for this check "
          "(McFarquhar et al. 2017 states the check, not a number) -- "
          "this reports, it does not verdict.")
    return 0


#: Why the PER-STAGE pipeline SUBCOMMANDS run the v3.1.4 engine and refuse ``3.5`` -- ``run`` is
#: unaffected (it dispatches on ``[run].engine``, wired to both engines since 2026-09-13; see
#: :func:`_refuse_unwired_engine`'s docstring). Each clause is a separate reason.
_V35_PIPELINE_GAPS = (
    "`combine` wraps the v3.1.4 signature of the ORACLES fork's `combine_sizedist.m`; for v3.5 the "
    "same fork combine is BORROWED, opt-in and labelled (arrayprobe_uiops.combine), reached only "
    "through `arrayprobe run` with [run].engine = \"3.5\" and [combine].borrowed = true",
    "`read-binary`, `imgproc` and `sizedist` take v3.1.4's arguments (a profile, a tree); the v3.5 "
    "stage functions take the reject thresholds of a v3.5-flavoured profile -- STOCK_V35, or "
    "ORACLES_PRODUCTION_V35 for the ORACLES thresholds on the v3.5 engine -- plus v3.5-only "
    "switches, named whole as scripts/run_flight.py's V35_CALL and stamped in every .call; not "
    "exposed per stage here",
    "scripts/run_flight.py runs the v3.5 chain only when told --engine 3.5, which `arrayprobe run` "
    "passes from [run].engine; the per-stage subcommands never reach it",
)


#: The decision ``arrayprobe engines`` prints first: which engine for which job, and the command
#: that runs it. Plain words for a first-time user; the per-module catalogue is behind
#: ``--catalogue``.
ENGINE_DECISION = (
    ("UIOPS v3.5 (the default)",
     "new data from any campaign and any probe",
     'arrayprobe run <config.toml>   with [run].engine = "3.5"'),
    ("SODA-2",
     "an independent second processing of the same raw file, to cross-check a UIOPS result",
     "arrayprobe soda2 run <config.toml>"),
    ("UIOPS v3.1.4",
     "only to reproduce an archived UIOPS product, such as the ORACLES 2D-S/HVPS record, "
     "or to check the port against one",
     'arrayprobe run <config.toml> --port-validation   with [run].engine = "3.1.4"'),
)


def _print_engine_decision() -> None:
    print("Which engine to use")
    for name, use, command in ENGINE_DECISION:
        if name == "UIOPS v3.1.4" and not _v314_engine_present():
            continue
        print(f"  {name}")
        print(f"      use for: {use}")
        print(f"      run:     {command}")
    print()


def _engines(args: argparse.Namespace) -> int:
    """Print which engine to use for what, then what the chosen engine rests on.

    With ``--catalogue`` (or ``--module``), also print which package implements
    each module for that UIOOPS version, and why. Imported inside the handler so
    the CLI's own import stays light and ``arrayprobe`` takes no module-level
    dependency on the selector.
    """
    import uiops

    # `engines` describes rather than runs, so it defaults to the package
    # default (v3.5) and not to the pipeline's wired engine.
    engine = uiops.engine(args.engines_version)
    entries = uiops.CATALOGUE
    if args.module:
        unknown = [m for m in args.module if m not in entries]
        if unknown:
            print(f"no such module(s): {unknown}. Run with --catalogue for "
                  f"the full list.", file=sys.stderr)
            return 2
    catalogue = bool(args.catalogue or args.module)
    if not args.module:
        _print_engine_decision()
    print(f"UIOPS {engine.version}"
          f"{'  (the default)' if engine.is_default else ''}")
    print(f"  validation: {engine.validation}")
    if not catalogue:
        print()
        print("Which package implements each module for this engine, and why: "
              "arrayprobe engines --catalogue")
        return 0
    print()
    names = args.module or sorted(n for n in entries if n)
    for name in names:
        print(f"{name}")
        print(f"    {engine.provenance(name)}")
    if not args.module:
        print()
        print(f"{len(names)} modules. States: "
              f"overridden = v3.5 has its own translation; "
              f"shared = the MATLAB source is byte-identical, so one "
              f"translation serves both; "
              f"tooling = no MATLAB counterpart; "
              f"fork-only = the file is in no stock UIOPS release; "
              f"read-shared = the file changed but this region did not.")
    return 0


def _add_engines(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "engines",
        help="which engine to use for what; --catalogue for the per-module detail",
        description=("Prints which engine to use for what: UIOPS v3.5 (the "
                     "default) for new data, SODA-2 as an independent second "
                     "processing, and UIOPS v3.1.4 only to reproduce an "
                     "archived UIOPS product. Then states what the chosen "
                     "engine's results rest on. --catalogue adds, per module, "
                     "which package implements it for that UIOPS version and "
                     "why: many MATLAB files are byte-identical between the "
                     "two releases, so v3.5 often uses the v3.1.4 translation. "
                     "Reads nothing and writes nothing."
                     if _v314_engine_present() else
                     "Prints which engine to use for what: UIOOPS v3.5 (the "
                     "default) for new data and SODA-2 as an independent second "
                     "processing. Then states what the chosen engine's results rest on. "
                     "--catalogue adds, per module, which package implements it "
                     "and why. Reads nothing and writes nothing."),
    )
    # Its own dest: `--uiops-version` also exists on the top-level parser,
    # and a subparser sharing the dest overwrites whatever was given before
    # the subcommand with its own default. Same flag to type, two stores.
    p.add_argument("--uiops-version", dest="engines_version",
                   choices=list(uiops_versions()), default=None,
                   help=("which UIOOPS engine to describe (default: the package "
                         "default, v3.5)") if _v314_engine_present() else argparse.SUPPRESS)
    p.add_argument("--catalogue", action="store_true",
                   help="also list every module and which package implements "
                        "it for that engine, and why")
    p.add_argument("--module", action="append", metavar="NAME",
                   help="describe only this module; repeatable")
    p.set_defaults(func=_engines)


def uiops_versions() -> tuple[str, ...]:
    """The selectable UIOOPS versions, read from :mod:`uiops` rather than
    retyped -- a second list here would be one more thing to keep true."""
    import uiops

    return uiops.VERSIONS


def _tune_settings(args: argparse.Namespace) -> int:
    """Print :data:`arrayprobe.tune.settings.SETTINGS`, as text or JSON.

    Read-only: runs nothing and writes nothing. With ``--probe-case`` each row also says whether
    it changes the output on that case (:meth:`~arrayprobe.tune.settings.Setting.effect`).
    """
    import json

    from arrayprobe.tune import settings as tune_settings

    case = args.probe_case
    effects: dict[str, Any] = {}
    if case is not None:
        from arrayprobe_uiops import probe_cases

        try:
            effects = {s.name: s.effect(case, args.ia_thresh_type)
                       for s in tune_settings.SETTINGS}
        except probe_cases.UnknownProbeCase as exc:
            print(f"arrayprobe tune settings: {exc}", file=sys.stderr)
            return 2
    if args.json:
        rows = []
        for s in tune_settings.SETTINGS:
            row: dict[str, Any] = {
                "name": s.name, "does": s.does, "default": s.default, "where": list(s.where),
                "engine_3_5": s.engine_35, "sources": [str(c) for c in s.cites]}
            if case is not None:
                eff = effects[s.name]
                row["effect"] = {"effective": eff.effective, "reason": eff.reason}
            rows.append(row)
        print(json.dumps({"engine": "3.5", "probe_case": case,
                          "ia_thresh_type": args.ia_thresh_type, "settings": rows}, indent=2))
        return 0
    print("Settings a run on the default engine (UIOPS v3.5) can change.")
    if case is not None:
        print(f"Effect column: probe case {case!r}, iaThreshType {args.ia_thresh_type}.")
    print()
    for s in tune_settings.SETTINGS:
        print(s.name)
        print(f"    what it does:  {s.does}")
        print(f"    default:       {s.default}")
        print(f"    where to set:  {'; '.join(s.where)}")
        print(f"    engine 3.5:    {s.engine_35}")
        if case is not None:
            print(f"    on {case}:  {effects[s.name].reason}")
        print(f"    source:        {s.cites[0]}")
        print()
    print(f"{len(tune_settings.SETTINGS)} settings. Where: TOML = a key in the run file "
          "(`arrayprobe run run.toml`); CLI = a batch-driver (`arrayprobe run`) flag; "
          "probe case and "
          "profile = registered from Python. --json lists every source line.")
    return 0


def _tune_sample(args: argparse.Namespace) -> int:
    """Draw the two review queues from one proc file and merge them into ``--queue-out``.

    Reads three columns of the proc file and writes only the queue file
    (:mod:`arrayprobe.tune.sample`); the proc file and every product are left unchanged.
    """
    from arrayprobe.tune import sample

    try:
        windows = sample.read_windows(args.windows)
        edges = (sample.check_edges(args.size_edges) if args.size_edges is not None
                 else sample.SIZE_EDGES_MM)
        if args.per_bin < 1:
            raise ValueError("--per-bin must be at least 1")
    except ValueError as exc:
        print(f"arrayprobe tune sample: {exc}", file=sys.stderr)
        return 2
    if not args.proc.is_file():
        print(f"arrayprobe tune sample: no proc file at {args.proc}", file=sys.stderr)
        return 2
    flight = args.flight or sample.flight_from_proc_name(args.proc.name)
    t, diam, rej = sample.read_proc_columns(args.proc)
    try:
        queues, coverage = sample.build(
            args.proc.name, t, diam, rej, route=args.route, flight=flight, windows=windows,
            queue_stem=args.queue_stem, edges=edges, per_bin=args.per_bin, seed=args.seed)
        sample.write_queues(args.queue_out, queues, coverage)
    except ValueError as exc:
        print(f"arrayprobe tune sample: {exc}", file=sys.stderr)
        return 2
    for line in sample.summary_lines(coverage):
        print(line)
    print(f"wrote {args.queue_out} (open it with: arrayprobe triage --decoded-dir <dir> "
          f"--queue-file {args.queue_out})")
    return 0


def _tune_distributions(args: argparse.Namespace) -> int:
    """Write the per-particle distributions inside the windows of one proc file to ``--out``.

    Reads eight columns of the proc file (:mod:`arrayprobe.tune.distributions`) and writes only
    the JSON report; the proc file and every product are left unchanged.
    """
    import json

    from arrayprobe.tune import distributions, sample

    try:
        windows = sample.read_windows(args.windows)
        edges = (sample.check_edges(args.size_edges) if args.size_edges is not None
                 else distributions.SIZE_EDGES_MM)
        marks = distributions.threshold_marks(args.probe_case, args.area_ratio_z)
    except (ValueError, KeyError) as exc:
        print(f"arrayprobe tune distributions: {exc}", file=sys.stderr)
        return 2
    if not args.proc.is_file():
        print(f"arrayprobe tune distributions: no proc file at {args.proc}", file=sys.stderr)
        return 2
    try:
        cols = distributions.read_proc_columns(args.proc)
    except ValueError as exc:
        print(f"arrayprobe tune distributions: {exc}", file=sys.stderr)
        return 2
    rep = distributions.report(cols, windows=windows, marks=marks, edges=edges,
                               proc_name=args.proc.name)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rep, indent=1), encoding="utf-8")
    for line in distributions.summary_lines(rep):
        print(line)
    print(f"wrote {args.out}")
    return 0


def _tune_score(args: argparse.Namespace) -> int:
    """Cross the reviewer's labels with each particle's reject code and size bin.

    Reads the queue file and the triage verdict store (:mod:`arrayprobe.tune.score`) and
    writes only the JSON report, when ``--out`` is given; nothing else is changed.
    """
    import json

    from arrayprobe.triage_server import VerdictStoreError, _load_queue_file
    from arrayprobe.tune import score

    if not args.queue_file.is_file():
        print(f"arrayprobe tune score: no queue file at {args.queue_file}", file=sys.stderr)
        return 2
    if not args.decoded_dir.is_dir():
        print(f"arrayprobe tune score: no decoded directory at {args.decoded_dir}",
              file=sys.stderr)
        return 2
    pv = tuple(v.strip() for v in args.phase_verdicts.split(",") if v.strip())
    try:
        data = _load_queue_file(args.queue_file)
        rep = score.score_file(data, args.decoded_dir, pv)
    except (ValueError, VerdictStoreError) as exc:
        print(f"arrayprobe tune score: {exc}", file=sys.stderr)
        return 2
    if not rep["queues"]:
        print(f"arrayprobe tune score: no queue in {args.queue_file}", file=sys.stderr)
        return 2
    for line in score.summary_lines(rep):
        print(line)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(rep, indent=1), encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


def _tune_diodes(args: argparse.Namespace) -> int:
    """Report stuck diodes in each proc file and print the run-file lines that mask them.

    Reads ``bin_stats`` (and ``position`` for a shadow count) through
    :mod:`arrayprobe.tune.diodes`; the proc files and every product are left unchanged.
    """
    import json
    import re

    from arrayprobe.tune import diodes

    reports = []
    for proc in args.proc:
        if not proc.is_file():
            print(f"arrayprobe tune diodes: no proc file at {proc}", file=sys.stderr)
            return 2
        stem = args.stem
        if stem is None:
            hit = re.search(r"base\d{12}", proc.name)
            if hit is None:
                print(f"arrayprobe tune diodes: {proc.name} names no raw stem "
                      "(base<12 digits>); pass --stem", file=sys.stderr)
                return 2
            stem = hit.group(0)
        try:
            rep = diodes.report(proc, profile=args.profile, probe=args.probe,
                                jobs=args.jobs)
        except (ValueError, KeyError, OSError) as exc:
            print(f"arrayprobe tune diodes: {exc}", file=sys.stderr)
            return 2
        rep["stem"] = stem
        rep["toml"] = diodes.toml_line(stem, rep["flagged"])
        reports.append(rep)
    if args.json:
        print(json.dumps(reports if len(reports) > 1 else reports[0], indent=1))
        return 0
    for rep in reports:
        for line in diodes.summary_lines(rep):
            print(line)
        print("  run-file lines (apply with --diode-corrected):")
        for line in rep["toml"].splitlines():
            print(f"    {line}")
    return 0


def _add_tune(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "tune",
        help="what a user can change for the default engine, and whether it has any effect",
        description="Tuning a run on the default engine (UIOOPS v3.5). Nothing here runs the "
                    "pipeline or changes a product; `sample` writes only a review queue file "
                    "and `distributions` and `score` only a JSON report.",
    )
    verbs = p.add_subparsers(dest="verb", required=True)
    s = verbs.add_parser(
        "settings",
        help="list every setting: what it does, its default, where to set it",
        description="Lists every setting a run on the default engine (UIOOPS v3.5) can "
                    "change: what it does, its default, where it is set (run file, "
                    "run_flight.py flag, probe case, profile or preset), and whether "
                    "engine 3.5 accepts it. Given a probe case, it also says whether each "
                    "setting has any effect there: the shattering settings change nothing "
                    "where the case's applyIntArrThresh is 0, or where the run's "
                    "iaThreshType is 0 (engine 3.5's default without a threshold file). "
                    "Each default is cited to "
                    "the source line it was read from; the JSON form lists them all.",
    )
    s.add_argument("--probe-case", default=None, metavar="NAME",
                   help="also say whether each setting has any effect on this registered "
                        "probe case (v35-2ds-ladder-fix is always available)")
    s.add_argument("--ia-thresh-type", type=int, choices=(0, 1, 2, 3), default=0,
                   help="the run's iaThreshType for the effect column (default 0, engine "
                        "3.5's default without a threshold file; 2 is "
                        "[shattering].ia_thresh_type = 2)")
    s.add_argument("--json", action="store_true",
                   help="print the table as JSON, with every source line")
    s.set_defaults(func=_tune_settings)

    m = verbs.add_parser(
        "sample",
        help="draw review queues from a proc file: particles inside time windows, per size bin",
        description="From one proc file, take the particles whose record header time (Time, "
                    "HHMMSS) falls inside any window (seconds of day, both ends included) "
                    "and whose image_diam_minR is at least the first size edge, and draw up "
                    "to --per-bin of each size bin at random with a fixed seed. Two queues: "
                    "the accepted image codes only (0HhuR), and every code. They are merged "
                    "into --queue-out, the file `arrayprobe triage --queue-file` reads, with "
                    "a coverage block per queue; other queues in that file are kept.",
    )
    m.add_argument("--proc", type=Path, required=True, help="the proc file to draw from")
    m.add_argument("--windows", required=True, metavar="W",
                   help="time windows as lo-hi seconds of day ('47925-47959,51671-51797'), "
                        "or a file of such pairs (one or more per line, # for comments)")
    m.add_argument("--queue-out", type=Path, required=True, metavar="Q",
                   help="queue file to write, or to add the two queues to")
    m.add_argument("--route", default="unspecified", metavar="R",
                   help="how the proc file was made, recorded in the coverage")
    m.add_argument("--flight", default=None,
                   help="flight name the triage server knows the particles by (default: "
                        "the proc file name without 'proc.' and '.nc')")
    m.add_argument("--queue-stem", default="sample",
                   help="queue name prefix; the queues are <stem>-accepted-n<N>-s<seed> "
                        "and <stem>-all-n<N>-s<seed> (default: sample)")
    m.add_argument("--size-edges", type=float, nargs="+", default=None, metavar="MM",
                   help="size-bin edges in mm, increasing; the first is the size floor "
                        "and 'inf' closes the last bin (default: 0.055 0.1 0.2 0.4 1.0 inf)")
    m.add_argument("--per-bin", type=int, default=40,
                   help="particles drawn per size bin (default: 40)")
    m.add_argument("--seed", type=int, default=20260930,
                   help="random seed; the same seed and inputs give the same queues "
                        "(default: 20260930)")
    m.set_defaults(func=_tune_sample)

    d = verbs.add_parser(
        "distributions",
        help="per-particle distributions inside time windows of a proc file, thresholds marked",
        description="From one proc file, for the particles whose record header time (Time, "
                    "HHMMSS) falls inside any window (seconds of day, both ends included): "
                    "particles per second, inter-arrival time, area ratio and axis ratio per "
                    "size bin, the reject codes in words, habit codes and the hollow fraction. "
                    "Each active threshold is marked where it cuts, with where its value was "
                    "read from: the area-ratio cut, the image-stage aspect-ratio ceilings and, "
                    "given --probe-case, the shattering threshold, with whether it has any "
                    "effect on that case. Non-finite diameters get their own size bin. Writes "
                    "only the JSON report.",
    )
    d.add_argument("--proc", type=Path, required=True, help="the proc file to read")
    d.add_argument("--windows", required=True, metavar="W",
                   help="time windows as lo-hi seconds of day ('47925-47959,51671-51797'), "
                        "or a file of such pairs (one or more per line, # for comments)")
    d.add_argument("--out", type=Path, required=True, metavar="REPORT",
                   help="JSON report to write")
    d.add_argument("--probe-case", default=None, metavar="NAME",
                   help="mark this registered probe case's shattering threshold and say "
                        "whether its gate is on (v35-2ds-ladder-fix is always available)")
    d.add_argument("--area-ratio-z", type=float, default=None, metavar="Z",
                   help="the area-ratio cut to mark: the value the run passes for this "
                        "flag (default: v3.5's stock cut)")
    d.add_argument("--size-edges", type=float, nargs="+", default=None, metavar="MM",
                   help="size-bin edges in mm, increasing; 'inf' closes the last bin "
                        "(default: 0 0.055 0.1 0.2 0.4 1.0 inf)")
    d.set_defaults(func=_tune_distributions)

    g = verbs.add_parser(
        "diodes",
        help="stuck diodes from a proc file's bin_stats, with the run-file lines that mask them",
        description="For each proc file, read bin_stats as lit counts (a shadow count is "
                    "converted as S - shadow, S the particles' slice total from "
                    "position) and apply the archived-product variant's stuck-diode rule "
                    "(find_shadow_diodes.m:66-97): below 0.80 x max, or below 0.80 x mean when "
                    "a diode reads above 1.2 x mean. The engine and profile come from the "
                    "file's provenance; an unstamped file needs "
                    "--profile. Prints a [masking.diodes] entry per file, applied by a run "
                    "given --diode-corrected. Reads only.",
    )
    g.add_argument("--proc", type=Path, required=True, action="append",
                   help="a proc file to read (repeatable)")
    g.add_argument("--profile", default=None, metavar="NAME",
                   help=("the v3.1.4 fidelity profile, when the file's stamp names none"
                         if _v314_engine_present() else
                         "the fidelity profile, when the file's stamp names none"))
    g.add_argument("--probe", default=None, metavar="NAME",
                   help="the probe whose image_slice_offset enters S (default: the offset "
                        "every probe of the file's diode count shares)")
    g.add_argument("--stem", default=None, metavar="STEM",
                   help="the raw stem the [masking.diodes] entry is keyed by (default: the "
                        "base<12 digits> in the proc file's name)")
    g.add_argument("--json", action="store_true",
                   help="print the full report as JSON instead of the summary")
    g.add_argument("--jobs", type=int, default=None, metavar="N",
                   help="worker processes reading position for S (default: up to 8 above "
                        "2 M particles, else 1; 1 forces a serial read). A parallel read that "
                        "fails or stalls falls back to the serial one; S is identical either way")
    g.set_defaults(func=_tune_diodes)

    c = verbs.add_parser(
        "score",
        help="the reviewer's labels per reject code and size bin: what each code rejected "
             "that was labelled real, and accepted that was labelled artifact",
        description="For each queue in --queue-file, join the verdicts and phases recorded "
                    "in `arrayprobe triage` (the verdict store under --decoded-dir; a "
                    "recheck- queue reads its own store) to the queue's particles, and count "
                    "them per size bin and per reject code (the code each particle carried "
                    "when the queue was drawn). For a rejecting code: how many it rejected "
                    "that were labelled real; for an accepted code: how many it accepted that "
                    "were labelled artifact. Per size bin, the ice fraction ice / (ice + "
                    "drizzle) with a Wilson 95 % interval. Writes only the JSON report.",
    )
    c.add_argument("--queue-file", type=Path, required=True, metavar="Q",
                   help="the queue file the labels were made from")
    c.add_argument("--decoded-dir", type=Path, required=True, metavar="D",
                   help="the directory `arrayprobe triage --decoded-dir` was given; verdicts "
                        "are read from its triage_verdicts/")
    c.add_argument("--out", type=Path, default=None, metavar="REPORT",
                   help="JSON report to write (default: print the summary only)")
    c.add_argument("--phase-verdicts", default="real", metavar="V",
                   help="comma-separated verdicts whose phase enters the ice fraction "
                        "(default: real)")
    c.set_defaults(func=_tune_score)


def _add_validate(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "validate",
        help="diagnostic checks on files the pipeline already wrote",
        description="Read-only checks. Nothing here computes or writes a "
                    "pipeline number. Each check reports a comparison and "
                    "returns 0 on success -- none of them issues a pass/fail "
                    "verdict, because none of the sources they implement "
                    "publishes a tolerance.",
    )
    checks = p.add_subparsers(dest="check", required=True)
    tc = checks.add_parser(
        "timing-closure",
        help="does the probe's particle clock agree with its housekeeping clock?",
        description="McFarquhar et al. (2017) ch. 11 p. 11.20. Compares the "
                    "proc file's particle-clock time span against the decoded "
                    "file's own record-clock span, which is measured by a "
                    "different clock in the instrument. Probetype 2 (2D-S / "
                    "HVPS) only -- see arrayprobe.timing_closure for why.",
    )
    tc.add_argument("decoded",
                    help="the decoded file the proc file was framed from "
                         "(.H.nc/.V.nc from engine 3.5, or an archived "
                         ".H.cdf/.V.cdf); pairing them correctly is the "
                         "caller's responsibility")
    tc.add_argument("proc", help="the proc (image-processing) file")
    tc.add_argument("--day-rollover-h", type=float, default=24.0,
                    help="hours added once if the record span looks negative "
                         "(a single midnight crossing); default 24.0")
    tc.set_defaults(func=_validate_timing_closure)

    bc = checks.add_parser(
        "by-condition",
        help="per-second agreement against the archived product, split by "
             "how much cloud the probe was in",
        description="A single headline percentage can hide a whole regime. "
                    "The band for each second is decided by the REFERENCE's "
                    "own per-second particle total, never by ours -- using "
                    "ours would make the stratification depend on the thing "
                    "being tested.",
    )
    bc.add_argument("combined", help="our combined product")
    bc.add_argument("--product",
                    help="the archived product; when omitted, found by date "
                         "in --product-dir")
    bc.add_argument("--product-dir",
                    default=by_condition_module.DEFAULT_PRODUCTS)
    bc.add_argument("--window", help="HHMMSS-HHMMSS, inclusive-exclusive, so a "
                                     "partially processed flight is compared "
                                     "only where its raw files are all present")
    bc.add_argument("--drop-bins", type=int, default=5,
                    help="bins excluded from the 'used' columns (default 5)")
    bc.set_defaults(func=_validate_by_condition)


def _view_strip(args) -> int:
    """``arrayprobe view strip`` -- :func:`arrayprobe.diagnostic_views.record_strip`, to a file."""
    import netCDF4

    from . import diagnostic_views as views

    with netCDF4.Dataset(args.image) as im, netCDF4.Dataset(args.proc) as pr:
        strip = views.record_strip(im, pr, args.record, args.n_records,
                                   colour_by=args.colour_by)
    out = Path(args.out)
    if out.suffix.lower() == ".png":
        out.write_bytes(views.record_strip_png(strip))
    else:
        title = f"{Path(args.image).name}: records {strip.records[0]}-{strip.records[-1]}"
        out.write_text(f"<!doctype html><meta charset='utf-8'><title>{title}</title>"
                       + views.record_strip_html(strip, title=title), encoding="utf-8")
    print(f"records {strip.records[0]}-{strip.records[-1]}: {len(strip.particles)} "
          f"particle(s), {int(strip.boundary.sum())} boundary slice(s); wrote {out}",
          flush=True)
    return 0


def _view_second(args) -> int:
    """``arrayprobe view second`` -- :func:`arrayprobe.diagnostic_views.compare_second`."""
    from . import diagnostic_views as views

    cmp = views.compare_second(args.ours, args.theirs, args.second, variable=args.variable,
                               proc=args.proc, diameter_var=args.diameter_var,
                               rtol=args.rtol)
    print(cmp.summary(), flush=True)
    if args.out:
        Path(args.out).write_text(
            f"<!doctype html><meta charset='utf-8'><title>second {cmp.second:06d}</title>"
            + views.second_comparison_html(cmp, ours_label=Path(args.ours).name,
                                           theirs_label=Path(args.theirs).name),
            encoding="utf-8")
        print(f"wrote {args.out}", flush=True)
    return 0


def _view_hollow(args: argparse.Namespace) -> int:
    import netCDF4
    import numpy as np

    from . import diagnostic_views as views

    if args.edges_um is not None:
        edges = [float(x) for x in args.edges_um.split(",") if x.strip()]
    else:
        with netCDF4.Dataset(args.edges_from) as d:
            d.set_auto_maskandscale(False)
            bmin = np.asarray(d.variables["Bin Minimum"][:], dtype=np.float64)
            bmax = np.asarray(d.variables["Bin Maximum"][:], dtype=np.float64)
        edges = list(np.concatenate([bmin, bmax[-1:]]) * 1000.0)
    kw = {} if args.min_fraction is None else {"min_fraction": args.min_fraction}
    print(views.hollow_share_text(views.hollow_share(args.proc, edges, **kw)), flush=True)
    return 0


def _add_view(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "view",
        help="diagnostic views of files the pipeline already wrote",
        description="Visualisation only: each view reads the port's own outputs "
                    "and computes no pipeline number (arrayprobe.diagnostic_views). "
                    "The triage server serves the record strip at /strip/<flight>.",
    )
    views = p.add_subparsers(dest="view", required=True)
    s = views.add_parser(
        "strip",
        help="whole image records with their particles in place (HydroViewer's view)",
        description="Consecutive 1700-slice records stacked one above the next, "
                    "boundary slices marked, each particle's shadow coloured by its "
                    "reject code or habit, and every fifth particle ticked in red.",
    )
    s.add_argument("image", help=("the decoded image file (.H.nc from engine 3.5, "
                                  ".H.cdf from engine 3.1.4)"
                                  if _v314_engine_present() else
                                  "the decoded image file (.H.nc)"))
    s.add_argument("proc", help="the proc file framed from it")
    s.add_argument("--record", type=int, default=1, help="first record, 1-based (default 1)")
    s.add_argument("--n-records", type=int, default=6, help="records to show (default 6)")
    s.add_argument("--colour-by", choices=("reject", "habit"), default="reject")
    s.add_argument("--out", required=True,
                   help="output file: .png for the image alone, anything else for an "
                        "HTML page with the legend and particle table")
    s.set_defaults(func=_view_strip)

    c = views.add_parser(
        "second",
        help="one second of two sd files bin by bin, with the particles behind the "
             "differing cells",
        description="For validation: the port's second beside the archive's. Exact "
                    "comparison unless --rtol is given. The particle list is where to "
                    "look, not what was counted: `count` also requires the reject "
                    "codes, centre-in and time window to pass.",
    )
    c.add_argument("ours", help="our sd (or combined) file")
    c.add_argument("theirs", help="the file to compare against, e.g. the archived product")
    c.add_argument("--second", type=int, required=True, help="the second, as HHMMSS")
    c.add_argument("--variable", default="count", help="a (time, bin) variable (default count)")
    c.add_argument("--proc", default=None,
                   help="the proc file behind OURS; lists the particles in differing bins")
    c.add_argument("--diameter-var", default="image_diam_minR",
                   help="the proc variable particles are placed in bins by "
                        "(default image_diam_minR); printed with every listing")
    c.add_argument("--rtol", type=float, default=0.0,
                   help="relative tolerance; 0 (default) is an exact comparison")
    c.add_argument("--out", default=None, help="also write an HTML page here")
    c.set_defaults(func=_view_second)

    h = views.add_parser(
        "hollow",
        help="how much of a between-engine difference hollow ('H') particles can make",
        description="Reads one UIOOPS v3.5 proc file. Per size bin: accepted particles, "
                    "accepted 'H' (hollow, Poisson-spot) particles, their share, how many the "
                    "Korolev size correction moves out of and into the bin, and the count "
                    "with the correction undone. Ends with a verdict: whether hollow sizing "
                    "can explain a difference between engines (SODA-2 does not divide) in "
                    "this size range. Reads the file and writes nothing.",
    )
    h.add_argument("proc", help="the v3.5 proc file (proc.<stem>.<channel>.nc)")
    edges = h.add_mutually_exclusive_group(required=True)
    edges.add_argument("--edges-um", default=None,
                       help="comma-separated bin edges in micrometres, e.g. 55,65,75,85,95,105,115")
    edges.add_argument("--edges-from", default=None,
                       help="a size-distribution file whose Bin Minimum/Bin Maximum (mm) give "
                            "the bins")
    h.add_argument("--min-fraction", type=float, default=None,
                   help="verdict threshold as a fraction of the range's count (default 0.05)")
    h.set_defaults(func=_view_hollow)


def _stage_commands_sentence() -> str:
    """What the per-stage commands run, true in the tree this file is installed in."""
    if _v314_engine_present():
        return ("The per-stage commands (read-binary, imgproc, sizedist, "
                "combine) run the validation engine, UIOPS v3.1.4, which "
                "reproduces archived UIOPS products such as the ORACLES "
                "2D-S/HVPS record; use them to check one stage against "
                "that record, not to process new data. ")
    return ("To run one stage at a time, use `arrayprobe run` with "
            "[run].stages. ")


def _uiops_version_help() -> str:
    """Help for the top-level ``--uiops-version``, true in the tree this file is installed in."""
    if _v314_engine_present():
        return ("which UIOPS engine the per-stage commands run. They "
                "run 3.1.4, the validation engine, only; naming "
                "another version refuses with the reason and runs "
                "nothing. For the default engine (3.5) use "
                "`arrayprobe run` with [run].engine = \"3.5\".")
    return argparse.SUPPRESS


_V314_ONLY_SUBCOMMANDS = ("read-binary", "imgproc", "sizedist")


def build_parser() -> argparse.ArgumentParser:
    """The whole command surface: one subcommand per pipeline stage.

    Separate from :func:`main` so the argument surface can be inspected and
    tested without running anything -- the fidelity-sensitive defaults are the
    part worth pinning, and the tests assert what is *required* rather than what
    a run produces.

    **Every fidelity-sensitive argument is required, never defaulted**, and that
    is the CLI's one real design decision. A default profile, tree or
    ``d_choice`` would let someone process a campaign under a configuration
    nobody chose, and a wrong reject threshold applied that way changes every
    concentration without a warning. Convenience defaults belong in a
    config file the user writes, not in the front door.
    """
    p = argparse.ArgumentParser(
        prog="arrayprobe",
        description="Start with `arrayprobe make-demo-flight`, which writes a small "
                    "synthetic raw file, then process a flight with `arrayprobe run "
                    "<config.toml>`: it runs every stage on the engine the file names "
                    "([run].engine, required; use \"3.5\", UIOOPS v3.5, for new data; "
                    "examples/configs/ has configs). "
                    + _stage_commands_sentence()
                    + "`arrayprobe engines` says which engine does what.",
    )
    # `--version` matters more here than in most packages: the whole claim is
    # that specific numbers come out, so "which version produced this" is a
    # question a user has to be able to answer from the command that produced
    # it. The `.call` sidecar records the arguments; this records the code.
    p.add_argument("--version", action="version",
                   version=f"arrayprobe {__version__} (UIOOPS "
                           f"v{'3.1.4' if _v314_engine_present() else '3.5'} engine)")
    # Naming a version the pipeline cannot run must fail loudly. The
    # alternative -- accepting `3.5` and quietly running v3.1.4 -- is the
    # shape of failure this project keeps building checks against: an
    # explicit instruction silently not happening. Same reasoning as the
    # enhancements resolver, which raises rather than dropping a switched-on
    # enhancement that does not apply to the engine.
    p.add_argument("--uiops-version", default="3.1.4",
                   help=_uiops_version_help())
    # Since 2026-09-15 the four library packages (``arrayprobe``,
    # ``arrayprobe_uiops``, ``arrayprobe_soda2``, ``uiops``) route their
    # progress/warning messages through ``logging`` and install only a
    # ``NullHandler`` on import, so a bare library import stays silent. This
    # console script is where a real handler belongs -- these flags control
    # its level; they do not touch this module's own ``print()`` output
    # (subcommand results, help text, error banners), which is unaffected by
    # either flag.
    verbosity = p.add_mutually_exclusive_group()
    verbosity.add_argument(
        "--quiet", action="store_true",
        help="suppress informational/warning library logging (errors still "
             "show); does not affect a subcommand's own print() output.")
    verbosity.add_argument(
        "--verbose", action="store_true",
        help="show DEBUG-level library logging in addition to the default "
             "INFO/WARNING messages.")
    sub = p.add_subparsers(dest="command", required=True)
    _add_run(sub)
    _add_reprocess(sub)
    if _v314_engine_present():
        _add_read_binary(sub)
        _add_imgproc(sub)
        _add_sizedist(sub)
    # combine runs on v3.5 too (--engine 3.5 --borrowed-combine, the user guide's per-stage line)
    _add_combine(sub)
    _add_compare(sub)
    _add_gallery(sub)
    _add_inventory(sub)
    _add_check_counts(sub)
    _add_triage(sub)
    _add_triage_agreement(sub)
    _add_provenance(sub)
    _add_diode_masks(sub)
    _add_validate(sub)
    _add_view(sub)
    _add_intarr(sub)
    _add_attributed(sub)
    _add_make_demo_flight(sub)
    _add_make_tas_file(sub)
    _add_tas_from_nasa_ames(sub)
    _add_engines(sub)
    _add_tune(sub)
    _add_soda2(sub)
    _add_reproduce_report(sub)
    return p


#: Subcommands left out of ``arrayprobe --help``'s listing: maintainer and review-workflow tools
#: Each still runs and keeps its own
#: ``--help``, and :func:`build_parser` still registers it, so the CLI reference pages
#: generated from the parser list it. Only :func:`main`'s top-level listing leaves it out.
_UNLISTED_SUBCOMMANDS = ("check-counts", "triage-recheck", "triage-agreement", "attributed",
                         "reproduce-report")


def _hide_unlisted(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """``parser`` with :data:`_UNLISTED_SUBCOMMANDS` dropped from its help listing only."""
    for action in parser._actions:  # noqa: SLF001
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            shown = [a for a in action._choices_actions  # noqa: SLF001
                     if a.dest not in _UNLISTED_SUBCOMMANDS]
            action._choices_actions = shown  # noqa: SLF001
            action.metavar = "{" + ",".join(a.dest for a in shown) + "}"
    return parser


#: The per-stage commands whose own ``--engine`` resolves through :func:`_stage_engine`.
_STAGE_ENGINE_COMMANDS = ("read-binary", "sizedist", "combine")


def _refuse_unwired_engine(args: argparse.Namespace) -> int | None:
    """``None`` to proceed, or an exit status if the named engine is not wired.

    ``engines`` is exempt: it *describes* an engine rather than running one,
    and refusing to describe v3.5 would make the one command that explains
    the situation the one command that cannot mention it. ``run`` is exempt for a related but
    different reason (2026-09-13): it dispatches on ``[run].engine`` itself, through
    the batch driver's ``--engine``, so a v3.5 config file is not "an unwired engine" at all --
    without this exemption a user who also passed ``--uiops-version 3.5`` at the top level
    (redundantly agreeing with a v3.5 config) would be refused here, before ``_run`` even ran,
    by this function's OWN top-level call in :func:`main`.
    """
    # ``soda2`` is its own engine, not a UIOOPS version: ``--uiops-version``
    # has no bearing on it, so it is exempt like ``run``.
    # ``reprocess`` reads its engine from the product's stamp and checks a disagreeing
    # ``--uiops-version`` itself (``_reprocess``), as ``run`` does against ``[run].engine``.
    if getattr(args, "command", None) in ("engines", "run", "reprocess", "soda2", "tune"):
        return None
    wanted = getattr(args, "uiops_version", "3.1.4")
    # read-binary, sizedist and combine carry their own --engine (review item 2). Given, it
    # decides; a top-level --uiops-version naming the other engine is refused, as `run` refuses
    # one that disagrees with [run].engine. Omitted, the unchanged rule below applies.
    stage_engine = getattr(args, "engine", None)
    if getattr(args, "command", None) in _STAGE_ENGINE_COMMANDS and stage_engine is not None:
        if wanted in ("3.1.4", stage_engine):
            return None
        print(f"arrayprobe {args.command}: --uiops-version {wanted} disagrees with "
              f"--engine {stage_engine}; nothing was run.", file=sys.stderr)
        return 2
    if wanted == "3.1.4":
        return None
    reasons = "\n".join(f"  - {why}" for why in _V35_PIPELINE_GAPS)
    print(
        f"arrayprobe: the per-stage commands cannot run UIOPS {wanted}.\n"
        f"They run the validation engine, UIOPS 3.1.4, which reproduces archived UIOPS "
        f"products (the ORACLES 2D-S/HVPS record); they are not the way to process new data.\n"
        f"To process data on UIOPS 3.5, the default engine, name it in a config file and run "
        f"that file:\n"
        f"    [run]\n    engine = \"3.5\"\n\n"
        f"    arrayprobe run <config.toml>\n"
        f"examples/configs/ has configs to start from (examples/configs/cip_uiops/cip_run.toml "
        f"for a CIP).\n"
        f"Why the per-stage commands stop at 3.1.4:\n"
        f"{reasons}\n"
        f"Nothing was run. Use --uiops-version 3.1.4 to check a stage on the validation "
        f"engine; `arrayprobe engines --catalogue --uiops-version 3.5` lists the v3.5 "
        f"modules for calling from Python.",
        file=sys.stderr)
    return 2


#: The four packages whose module logger the CLI configures a handler for
#: ``arrayprobe_soda2`` and ``uiops`` carry no converted
#: ``print()`` today (R6 counted zero in each), but are included so a future
#: message in either reaches the same default visibility without a second
#: place to remember to add it.
_LIBRARY_LOGGER_NAMES = ("arrayprobe", "arrayprobe_uiops", "arrayprobe_soda2", "uiops")


def _configure_logging(*, quiet: bool, verbose: bool) -> None:
    """Attach one ``stderr`` handler per library logger, for this process only.

    Each package's ``__init__`` installs a ``NullHandler`` and nothing else
    (constraint: a plain ``import arrayprobe`` must never print), so without
    this call a converted message would be silently dropped -- worse
    than the ``print()`` it replaced. Default level is ``INFO``, which is
    where every message converted so far (``logging.warning``) already
    shows; ``--quiet`` raises it to ``ERROR`` (informational/warning messages
    are suppressed, an ``.error()`` call would still show); ``--verbose``
    lowers it to ``DEBUG``. This does not touch a worker subprocess spawned
    through ``ProcessPoolExecutor`` -- ``readers/spec.py``'s
    ``_report_part_progress`` configures its own handler for exactly that
    reason (see its module comment) and is unaffected by these flags, same
    as it was unaffected by anything before this change.
    """
    level = logging.DEBUG if verbose else (logging.ERROR if quiet else logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    for name in _LIBRARY_LOGGER_NAMES:
        logger = logging.getLogger(name)
        logger.setLevel(level)
        logger.addHandler(handler)
        logger.propagate = False


def main(argv=None) -> int:
    """Entry point for the ``arrayprobe`` console script (see ``pyproject.toml``).

    Returns a process exit status rather than raising, so a shell pipeline can
    branch on it; each subcommand's own handler returns 0 for success. ``argv``
    is accepted explicitly so tests drive the real parser instead of patching
    ``sys.argv``.
    """
    parser = _hide_unlisted(build_parser())
    if not _v314_engine_present():
        # The three v3.1.4-only stage commands are unregistered without the engine; a stale script
        # naming one gets the reason, not argparse's "invalid choice".
        tokens = list(sys.argv[1:] if argv is None else argv)
        i = 0
        while i < len(tokens):
            tok = str(tokens[i])
            if tok == "--uiops-version":
                i += 2
                continue
            if tok.startswith("-"):
                i += 1
                continue
            if tok in _V314_ONLY_SUBCOMMANDS:
                print(_absent_engine_refusal(tok), file=sys.stderr)
                return 2
            break
    args = parser.parse_args(argv)
    if getattr(args, "engine", None) == "3.1.4" and not _v314_engine_present():
        print(_absent_engine_refusal(getattr(args, "command", None)), file=sys.stderr)
        return 2
    if getattr(args, "command", None) == "read-binary":
        sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
        _check_read_binary(sub.choices["read-binary"], args)
    _configure_logging(quiet=args.quiet, verbose=args.verbose)
    refusal = _refuse_unwired_engine(args)
    if refusal is not None:
        return refusal
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        # A missing input reaching the top of a subcommand is a mistyped path, not a bug: one
        # line naming it, exit 2, rather than the traceback imgproc, sizedist and combine
        # printed for it (cold-user walk, 2026-09-26).
        what = f"{exc.strerror}: {exc.filename}" if exc.filename else str(exc)
        print(f"arrayprobe {getattr(args, 'command', '')}: {what}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
