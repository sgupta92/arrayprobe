# SPDX-License-Identifier: BSD-3-Clause
"""arrayprobe -- a Python port of UIOOPS. Porting v3.1.4 line by line surfaced a
set of findings about the MATLAB; those findings are fixed in the v3.5 engine
(``arrayprobe_uiops``, the default) where the developers addressed them, and in
the opt-in ``arrayprobe-enhancements`` package otherwise.

UIOOPS (University of Illinois / Oklahoma OAP Processing Software, McFarquhar
group, GPLv3) turns raw optical-array-probe buffers into particle-by-particle
records and then into size distributions.  This package -- the v3.1.4 engine
-- reproduces that original's behaviour first, bugs included: a "fix" that
changes a computed value is a defect here, because the archived campaign
products were written by the MATLAB as it actually behaves, and reproducing
that behaviour exactly is what let every fix above be checked against the
archived record before it was trusted.  See the repository ``README.md`` for
the validation evidence, the known gaps, and the fidelity doctrine, and
``docs/developer/`` for the per-stage design documents.

The names re-exported below are the package's public front door -- the four
pipeline stages, the fidelity profiles that select between the MATLAB source
trees, and the run-configuration and comparison entry points.  Everything else
remains reachable by its submodule (``arrayprobe.reject``,
``arrayprobe.habit``, ``arrayprobe.geometry`` and the rest); this list is the
subset a caller running or checking a flight actually needs.

To process data, use the default engine, UIOOPS v3.5, which :func:`engine`
returns. The shortest route is a run configuration and ``arrayprobe run
<config.toml>`` (``examples/configs/`` has configs). The same chain from
Python, for a CIP recorded in a SEA file::

    import importlib

    import netCDF4
    import numpy as np

    import arrayprobe as ap

    eng = ap.engine()                          # "3.5", the default engine
    imgproc = importlib.import_module(f"{eng.package}.imgproc")
    sizedist = importlib.import_module(f"{eng.package}.sizedist")

    # Decode: one file per probe in the SEA container (decoded.CIP.cdf,
    # decoded.2DC.cdf). The SEA reader is the same code under both engines.
    ap.read_binary_SEA("flight.sea", "decoded")
    with netCDF4.Dataset("decoded.CIP.cdf") as nc:
        n_records = len(nc.dimensions["time"])

    # Frame particles. A CIP takes no airspeed here (tas_time/tas are None).
    imgproc.imgproc_sm_v35(
        "decoded.CIP.cdf", "proc.nc", "CIP", 1, n_records, "UND2016",
        iNewHabit=0, reject_config=ap.profile("stock-v3.5").reject_thresholds,
        tas_time=None, tas=None, software="UIOOPS_v3.5")

    # One-second size distributions. The airspeed series must be in the CIP's
    # own clock (see examples/configs/cip_uiops/README.md).
    timehhmmss, tas = ap.load_tas_info("airspeed.tas.csv")
    sizedist.run(
        "proc.nc", "sd.nc", tas, np.floor(timehhmmss), "CIP", 6, 0,
        np.full_like(tas, 9e5), np.full_like(tas, 15.0), 0, 0, 0, 0,
        "UND2016", "20160906 064017", software="UIOOPS_v3.5")

``tests/test_package_docstring_example.py`` runs that block as written.

**The validation path.** The names re-exported below are the v3.1.4 engine,
used to reproduce archived UIOOPS products such as the ORACLES 2016 2D-S
record, not to process new data. Its chain, exactly as the reproduction was
checked, including the twelfth ``sizeDist`` argument that names a file which
must not exist (``sizedist.run``'s docstring says why)::

    import arrayprobe as ap

    ap.read_binary_SPEC("base160906064403.2DS", "decoded",
                        profile=ap.ORACLES_PRODUCTION)
    ap.imgproc_sm("decoded.H.cdf", "proc.nc", "2DS", 1, 1, "ORACLES",
                  profile=ap.ORACLES_PRODUCTION)
    ap.size_dist("proc.nc", "sd.nc", tas, timehhmmss, "2DS", 6, 2,
                 pres, temp, "ORACLES", "20160906",
                 "2DS_intArrThreshold_MISSING.cdf",
                 tree="production")
    ap.combine_sizedist([...], "flight.nc", flight_date=..., summary_time=...)

``read_binary_SPEC`` keeps the MATLAB's own capitalisation, as the porting
convention requires; ``size_dist`` is ``sizeDist.m`` under the package's
snake-case rule and is the same object as :func:`arrayprobe.sizedist.run`.
"""

from __future__ import annotations

import logging

from .combine import combine_sizedist
from .compare import ComparisonReport, compare_files, format_report
from .config import ConfigError, RunConfig, load_config
from .products import open_product
from .profiles import (
    ORACLES_2016,
    ORACLES_PRODUCTION,
    PROFILES,
    STOCK_V314,
    FidelityProfile,
    profile,
    register_profile,
)
from .readers.dmt import read_binary_DMT
from .readers.pms import read_binary_PMS
from .readers.sea import read_binary_SEA
from .readers.tasinfo import load_tas_info
from .selector import DEFAULT_ENGINE, ENGINES, Engine, UnknownEngine, engine
from .timing_closure import ClosureResult, check_closure
from .validation_report import CellAgreement, ProductComparisonReport, compare_to_product

# The v3.1.4 validation engine is not part of the public distribution
#: its top-level names load on first access (PEP 562).
_V314_NAMES = {
    "imgproc_sm": (".imgproc", "imgproc_sm"),
    "read_binary_SPEC": (".readers.spec", "read_binary_SPEC"),
    "read_binary_hvps": (".readers.spec", "read_binary_hvps"),
    "size_dist": (".sizedist", "run"),
}
from arrayprobe_uiops.engine_absence import ABSENT_MESSAGE as _V314_ABSENT  # noqa: E402


def __getattr__(name: str):
    spec = _V314_NAMES.get(name)
    if spec is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    modname, attr = spec
    try:
        module = importlib.import_module(modname, __name__)
    except ModuleNotFoundError as exc:
        if exc.name in (f"{__name__}{modname}", f"{__name__}.{modname.lstrip('.')}"):
            raise ImportError(_V314_ABSENT) from exc
        raise
    value = getattr(module, attr)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_V314_NAMES))


#: The first release, ``0.1.0``: usable, open and still in development.
#:
#: What the number claims: the ORACLES 2D-S lineage is feature-complete and
#: validated against the archived MATLAB products cell by cell on whole
#: flights.  What ``0.x`` withholds: the interface may still change before
#: 1.0, the stock-tree ``sizeDist`` control flow
#: is not implemented, and the probes no UIOOPS product exists for
#: here are validated against Octave oracles and synthetic fixtures only.
#: ``pyproject.toml``'s ``version`` carries the same string, and
#: ``tests/test_version.py`` reads the two from different places so they
#: cannot drift.
__version__ = "0.1.0"

# 2026-09-15: the library never configures its own handler --
# a bare ``import arrayprobe`` must stay silent for a notebook, a pipeline
# caller, or a future ``xarray`` user, matching the same "no default silently
# picks a side" discipline :mod:`arrayprobe.profiles` applies to fidelity
# choices. ``arrayprobe.cli`` attaches a real handler for the console script;
# nothing here does. ``print()`` remains the output channel for the CLI
# modules themselves (``cli.py``, ``triage_server.py``,
# ``scripts/make_demo_flight.py``) -- those are user-facing console text, not
# library progress, and stay untouched.
logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [
    "__version__",
    # -- Stage 2: raw probe buffer -> uncompressed image netCDF -------------
    "read_binary_SPEC",
    "read_binary_hvps",
    "read_binary_DMT",
    "read_binary_PMS",
    "read_binary_SEA",
    "load_tas_info",
    # -- Stage 3: images -> per-particle records ----------------------------
    "imgproc_sm",
    # -- Stage 4: per-particle records -> size distributions ----------------
    "size_dist",
    # -- Stage 8: several sd files -> one flight product --------------------
    "combine_sizedist",
    # -- Which MATLAB is being reproduced ----------------------------------
    "FidelityProfile",
    "STOCK_V314",
    "ORACLES_2016",
    "ORACLES_PRODUCTION",
    "PROFILES",
    "profile",
    "register_profile",
    # -- Run configuration (selection only; never sets a threshold) --------
    "RunConfig",
    "ConfigError",
    "load_config",
    # -- Checking a run against a reference product ------------------------
    "compare_files",
    "format_report",
    "ComparisonReport",
    # -- Checking a run against the archived product, typed -----------------
    "compare_to_product",
    "ProductComparisonReport",
    "CellAgreement",
    # -- Diagnostic: particle clock vs. housekeeping clock ------------------
    "check_closure",
    "ClosureResult",
    # -- The project-level engine selector -----------------------------------
    # Dispatches across all three engines, SODA-2 included, and computes
    # nothing. `uiops.engine()` still answers the narrower question of which
    # UIOOPS release. See selector.py's docstring for why this name and not
    # that one.
    "engine",
    "Engine",
    "ENGINES",
    "DEFAULT_ENGINE",
    "UnknownEngine",
    # -- Reading a product for analysis -------------------------------------
    # Engine-neutral: opens a file written by any engine, exactly as written.
    "open_product",
]
