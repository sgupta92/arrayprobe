# SPDX-License-Identifier: BSD-3-Clause
"""Choose which UIOOPS translation processes your data.

This is a selector, not the UIOOPS MATLAB code. ``engine()`` returns the
translation of UIOOPS v3.5, the engine this package offers; ``versions()``
lists the versions installed. An earlier translation of UIOOPS v3.1.4
reproduced archived products and is not part of this package; its entries in
``CATALOGUE`` record which v3.5 module replaced each of its modules. SODA-2 is
a separate engine, reached through ``arrayprobe.engine("soda2")``.
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from types import ModuleType
from typing import Any

# NullHandler by default, matching the engine packages' loggers: importing
# this selector prints nothing. ``arrayprobe.cli`` attaches the real handler
# for the console script.
logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [
    "VERSIONS",
    "DEFAULT_VERSION",
    "Engine",
    "engine",
    "UnknownVersion",
    "UnknownModule",
    "CATALOGUE",
    "Entry",
    "OVERRIDDEN",
    "SHARED",
    "TOOLING",
    "FORK_ONLY",
    "READ_SHARED",
]



def versions() -> tuple[str, ...]:
    """The UIOOPS versions installed: v3.5 always, v3.1.4 only where its engine is."""
    from arrayprobe_uiops.engine_absence import engine_present
    return ("3.1.4", "3.5") if engine_present() else ("3.5",)


#: The UIOOPS versions installed, computed at import (see :func:`versions`).
VERSIONS = versions()

#: What :func:`engine` returns when the caller names nothing.
DEFAULT_VERSION = "3.5"

OVERRIDDEN = "overridden"
SHARED = "shared"
TOOLING = "tooling"
FORK_ONLY = "fork-only"
READ_SHARED = "read-shared"


class UnknownVersion(ValueError):
    """A version string that is not one of :data:`VERSIONS`."""


class UnknownModule(KeyError):
    """A module name that is not in :data:`CATALOGUE`."""


@dataclass(frozen=True)
class Entry:
    """One module of the UIOOPS v3.1.4 translation, and how v3.5 covers it.

    ``sources`` names the MATLAB/C++ file(s) the module translates, so the
    classification can be checked against the UIOOPS v3.1.4 and v3.5 sources.
    ``v35`` is the v3.5 module that replaces it, if there is one.
    """

    state: str
    sources: tuple[str, ...] = ()
    v35: str | None = None
    note: str = ""


def _t(note: str = "") -> Entry:
    return Entry(TOOLING, note=note)


def _shared(*sources: str) -> Entry:
    return Entry(SHARED, sources=sources)


def _over(v35: str, *sources: str, note: str = "") -> Entry:
    return Entry(OVERRIDDEN, sources=sources, v35=v35, note=note)


def _fork(*sources: str, v35: str | None = None, note: str = "") -> Entry:
    return Entry(FORK_ONLY, sources=sources, v35=v35, note=note)


#: Every module of the v3.1.4 port, keyed by its dotted name below
#: ``arrayprobe``. Complete by test: a module on disk that is missing here, or
#: an entry naming a module that no longer exists, fails the suite.
CATALOGUE: dict[str, Entry] = {
    # --- v3.5 has its own translation, because the source changed ----------
    "reject": _over("arrayprobe_uiops.reject", "calculate_reject_unified.m"),
    "habit": _over("arrayprobe_uiops.habit", "holroyd.m",
                   note="v3.5 also adds holroyd_new.m and "
                        "holroyd_new_HVPS.m, both ported into the same module"),
    "imgproc": _over("arrayprobe_uiops.imgproc", "imgProc_sm.m",
                     note="the per-particle measurement block lives in "
                          "arrayprobe_uiops.measure"),
    "sizedist": _over("arrayprobe_uiops.sizedist", "sizeDist.m",
                      note="the bin tables live in "
                           "arrayprobe_uiops.sizedist_tables"),
    "particle_physics": _over("arrayprobe_uiops.particle_physics",
                              "single_area.m", "single_mass.m",
                              note="single_vt.m is byte-identical; the "
                                   "override exists for the other two, which "
                                   "gained the iNewHabit argument"),
    "readers.spec": _over("arrayprobe_uiops.spec", "read_binary_SPEC.m",
                          note="the TAS machinery is "
                               "arrayprobe_uiops.tas"),
    "geometry.min_circle": _over("arrayprobe_uiops.min_circle", "CGAL_minR.cpp"),
    "geometry.min_ellipse": _over("arrayprobe_uiops.min_ellipse",
                                  "CGAL_EllipseSize.cpp",
                                  note="layer 3 for both engines: the real "
                                       "CGAL headers are unavailable here, so "
                                       "this is documented semantics and "
                                       "pinned tests, not an oracle"),

    # --- the MATLAB source is byte-identical, so one translation serves ----
    "dropsize": _shared("dropsize.m"),
    "geometry.min_rectangle": _shared("CGAL_RectSize.cpp"),
    "lwc": _shared("lwc_calc.m"),
    "particle_perimeter": _shared("ParticlePerimeter.m"),
    "readers.dmt": _shared("read_binary_DMT.m"),
    "readers.pms": _shared("read_binary_PMS.m"),
    "readers.sea": _shared("read_binary_SEA.m"),
    "sample_area": _shared("calc_sa_randombins.m"),
    "time_convert": _shared("hhmmss2insec.m", "insec2hhmmss.m"),

    # --- the file changed; the region this module ports did not ------------
    "readers.mask_csv": Entry(
        READ_SHARED, sources=("read_binary_SPEC.m",),
        note="the .MK.csv and .NV.csv sidecars are untouched by the v3.5 "
             "diff and are inherited -- established by reading, at "
             "arrayprobe_uiops/spec.py:219, while porting v3.5's reader. The enclosing "
             "file changed, so this cannot be settled by hashing"),

    # --- the ORACLES production fork: in no stock UIOOPS release ------------
    "combine": _fork("combine_sizedist.m", v35="arrayprobe_uiops.combine",
                     note="held in uioops_testing/delivered_2026-08-20/ and "
                          "recovered from the dissertation; stock UIOPS ships "
                          "no such file in either release. For v3.5 it is "
                          "BORROWED from the fork and opt-in "
                          "(borrowed_combine=True), 2026-09-13"),
    "intarr": _fork("IntArrAnalysis_time.m",
                    note="stock ships IntArrAnalysis.m, which is a different "
                         "file and is byte-identical between the releases"),
    "intarr_analysis": _fork("IntArrAnalysis_time.m"),
    "intarr_plots": _fork("IntArrAnalysis_time.m",
                          note="the interarrival-time diagnostic contour plot, opt-in; the "
                               "faithful mode keeps the upstream NaN axis "
                               "(2026-09-13)"),
    "readers.tasinfo": _fork("loadTASinfo_2DS.m",
                             note="stock ships loadTASinfo.m, byte-identical "
                                  "between the releases; the _2DS variant is "
                                  "the fork's"),
    "masks": _fork("find_shadow_diodes.m",
                   note="the nine-argument imgProc_sm that made the ORACLES "
                        "products, and find_shadow_diodes.m that wrote its "
                        "masks (find_shadow_diodes()); both survive "
                        "only as dissertation Appendix-B extractions "
                        "(archive/staging_variant_raw/)"),

    # --- shim and tooling: one implementation, both engines ----------------
    "": _t("the package root"),
    "cli": _t("the command-line front door"),
    "__main__": _t("`python -m arrayprobe`, delegating to cli.main"),
    # 2026-10-01: the batch flight driver moved here from scripts/ (scripts/<name>.py are now
    # shims that exec these files). It sequences the engines' stages and stamps their
    # configuration; it reproduces no MATLAB file -- UIOOPS ships no driver.
    "driver": _t("the batch flight driver's package root"),
    "driver.run_flight": _t("the batch flight driver: runs a flight's stages and stamps them"),
    "driver.reprocess": _t("re-runs one product's stage under the configuration its stamp "
                           "records"),
    "driver.preflight_inputs": _t("opens every input a long run needs before the run starts"),
    "driver.tas_from_probe_housekeeping": _t(
        "builds an aircraft TAS sidecar from another probe's housekeeping airspeed"),
    "driver._load_record": _t("records the machine's other load while a timing runs"),
    "compare": _t("diff-triage between two output files"),
    "config": _t("run-configuration loading; selection only"),
    "constants": _t("probe and project tables"),
    "diagnostic_views": _t("the record strip and one-second comparison views"),
    "diode_report": _t("per-diode occupancy reporting"),
    "friendly": _t("a boundary layer re-viewing four raw contracts; off the reproduction path"),
    "geometry": _t("the geometry package root"),
    "jit_kernels": _t("opt-in numba kernels for S3's hot loops; speed only, byte-identical"),
    "matio": _t("reading MATLAB .mat sidecars"),
    "matlab_compat": _t("MATLAB language semantics NumPy does not reproduce"),
    "ncio": _t("MATLAB netcdf.* semantics; an alias of arrayprobe_uiops.ncio since "
               "2026-10-03, where the code both engines share lives"),
    "particle": _t("the in-memory particle image"),
    "profiles": _t("which MATLAB variant a run reproduces"),
    "provenance": _t("the one parser for every .call sidecar; absence is None, never an "
                     "engine; an alias of arrayprobe_uiops.provenance since 2026-09-30, "
                     "where the code both engines share lives"),
    "count_closure": _t("checks that an S4 product's binned counts sum to the particles its "
                        "S3 file holds; read-only, reproduces no MATLAB file"),
    "inventory": _t("raw-file inventory flagging empty and truncated raw files before "
                    "processing; reproduces no MATLAB file and computes nothing"),
    "reproduce_report": _t("compares a product against an archived product cell by cell; "
                           "read-only, reproduces no MATLAB file"),
    "readers": _t("the readers package root"),
    "regimes": _t("named cloud-regime S4 threshold bundles; selects, computes nothing"),
    "attributed_export": _t("a self-describing sibling of a faithful product; reads it "
                            "read-only and computes nothing"),
    "ai_ready": _t("checks an attributed export against the metadata and storage it claims; "
                   "reads files only, computes nothing"),
    "hvps_caveat": _t("the HVPS count caveat; a warning, changes no number"),
    "hvps_flight_config": _t("per-flight HVPS inter-arrival source table; records a "
                             "configuration, computes nothing"),
    "authordefaults": _t("loads the author-editable defaults file; selects a profile, "
                         "computes nothing"),
    "render": _t("particle visualisation"),
    "review_sampling": _t("stratified review samples"),
    "review_agreement": _t("re-check queues and label agreement (Cohen's kappa)"),
    "sizing": _t("the size-definition registry"),
    "_v314_lazy": _t("lazy access to the v3.1.4 modules the public distribution omits"),
    "timing_closure": _t("the interarrival closure check"),
    "tools": _t("tooling shipped inside the package"),
    "tools.make_demo_flight": _t("the synthetic raw-file generator"),
    "tools.heldout_stamp": _t("stamps held-out evaluation outputs; computes nothing"),
    "tools.synthetic_truth": _t("known-truth synthetic 2D-S flights for accuracy checks"),
    # 2026-09-16, from the cold-start usability audit: the v3.5 engine refuses to
    # run without an aircraft TAS file whose schema no page stated and no tool
    # wrote. This writes one. Tooling -- it produces an input, computes nothing.
    "tools.make_tas_file": _t("writes the aircraft TAS file the v3.5 engine requires"),
    "tools.tas_sources": _t("the TAS source chain: finds, reads and checks a run's airspeed"),
    # 2026-09-17: the SEA/CIP chain had no measured TAS at all -- nothing on it writes a
    # .tas.csv, and --constant-tas fabricates one. This reads the aircraft data system's own
    # NASA-Ames 1001 series into that sidecar. Tooling -- it converts a time base and
    # copies an aircraft measurement; no UIOOPS release reads this format.
    "tools.nasa_ames_tas": _t("reads a NASA-Ames 1001 aircraft TAS file into a .tas.csv"),
    "tools.probe_comparison": _t(
        "puts two probes' written products on a common size grid and time axis for "
        "comparison; reproduces no MATLAB file"),
    "products": _t(
        "arrayprobe.open_product, opens a written product as written, engine-neutral. "
        "TOOLING: it reproduces no MATLAB file and computes nothing"),
    "selector": _t(
        "the project-level engine selector, arrayprobe.engine() -- spans all "
        "three engines where this module spans the two UIOPS ones. "
        "TOOLING: it reproduces no MATLAB file and computes nothing"),
    "triage_server": _t("the triage GUI"),
    "run_page": _t("the triage GUI's Run page"),
    "triage_context": _t("what the triage pages show beside a particle"),
    "tune": _t("the tune package root"),
    "tune.settings": _t(
        "lists every setting a v3.5 run can change, cited to file:line, and whether it "
        "reaches the output on a given probe case; reproduces no MATLAB file and computes "
        "nothing"),
    "tune.sample": _t(
        "draws triage review queues from a proc file inside time windows; reads only and "
        "computes no product"),
    "tune.distributions": _t(
        "reports per-particle distributions inside time windows with each threshold marked; "
        "reads only and computes no product"),
    "tune.score": _t(
        "crosses a reviewer's triage labels with each particle's reject code and size bin; "
        "reads only and computes no product"),
    "tune.diodes": _t(
        "reports stuck diodes from a proc file's bin_stats, delegating the rule to "
        "arrayprobe_uiops.diode_mask; reads only and computes no product"),
    "validate_by_condition": _t("stratified agreement against a product"),
    "validation_report": _t("typed comparison results"),
}

#: One line per engine on what its results rest on. Stated at the point of
#: selection because "default" and "authoritative" are different here, and a
#: user who only reads the default would draw the wrong conclusion.
_VALIDATION = {
    "3.1.4": "layer 1 -- reproduces a field campaign's archived products bit "
             "for bit in the validated flights. The only engine with an "
             "archived product behind it; it exists to validate against that "
             "record, not as a general-purpose alternative to v3.5.",
    "3.5": "layer 2 only -- every routine is asserted against GNU Octave "
           "running v3.5's own sources. No archived campaign product was ever "
           "produced by v3.5, so there is nothing to make a layer-1 claim "
           "against, and there never will be. Its profile is STOCK_V35 "
           "(stock-v3.5): every field read from the v3.5 sources and checked "
           "against an Octave parse of the same lines; its values equal "
           "stock-v3.1.4's, cited to v3.5 lines.",
}


@dataclass(frozen=True)
class Engine:
    """A chosen UIOOPS version, and the modules that implement it."""

    version: str

    @property
    def validation(self) -> str:
        """What results from this engine rest on, in one line."""
        return _VALIDATION[self.version]

    @property
    def is_default(self) -> bool:
        """True when this engine is ``DEFAULT_VERSION``, the one ``engine()`` returns with no
        argument."""
        return self.version == DEFAULT_VERSION

    def _entry(self, name: str) -> Entry:
        if name not in CATALOGUE:
            raise UnknownModule(
                f"no module {name!r} in the v3.1.4 port. Known: "
                f"{sorted(n for n in CATALOGUE if n)}")
        return CATALOGUE[name]

    def dotted(self, name: str) -> str:
        """The importable name of the module implementing ``name`` here."""
        entry = self._entry(name)
        if self.version == "3.5" and entry.v35:
            return entry.v35
        return f"arrayprobe.{name}" if name else "arrayprobe"

    def module(self, name: str) -> ModuleType:
        """Import and return the module implementing ``name`` here.  A v3.1.4 module missing
        because the v3.1.4 engine is not installed raises ``V314EngineAbsent``, naming why."""
        dotted = self.dotted(name)
        try:
            return importlib.import_module(dotted)
        except ModuleNotFoundError as exc:
            if self.version == "3.1.4" and exc.name == dotted:
                from arrayprobe_uiops.engine_absence import ABSENT_MESSAGE, V314EngineAbsent
                raise V314EngineAbsent(ABSENT_MESSAGE) from exc
            raise

    def get(self, name: str, attribute: str) -> Any:
        """One attribute of :meth:`module` -- the common two-step, in one."""
        return getattr(self.module(name), attribute)

    def provenance(self, name: str) -> str:
        """One line on where this engine's implementation of ``name`` comes
        from, and what that means -- the thing a reader could not previously
        find out without reading ``arrayprobe_uiops``'s import list."""
        entry = self._entry(name)
        dotted = self.dotted(name)
        sources = ", ".join(entry.sources) or "no MATLAB source"
        if self.version == "3.1.4":
            if entry.state == FORK_ONLY:
                return (f"{dotted} -- translates {sources} from the field "
                        f"campaign's production variant, which made the "
                        f"archived products")
            if entry.state == TOOLING:
                return f"{dotted} -- {entry.note or 'tooling'}, no MATLAB source"
            return f"{dotted} -- ports {sources} as of v3.1.4"
        if entry.state == OVERRIDDEN:
            return (f"{dotted} -- v3.5's own translation of {sources}, which "
                    f"changed between the releases")
        if entry.state == SHARED:
            return (f"{dotted} -- the v3.1.4 port's translation, reused "
                    f"because {sources} is byte-identical in v3.5")
        if entry.state == READ_SHARED:
            return (f"{dotted} -- the v3.1.4 port's translation. {entry.note}")
        if entry.state == FORK_ONLY:
            borrowed = (" Borrowed for v3.5, opt-in, and labelled so in its "
                        ".call sidecar." if entry.v35 else "")
            return (f"{dotted} -- ports {sources}, which exists in NO stock "
                    f"UIOPS release. There is no v3.5 counterpart to be "
                    f"faithful to.{borrowed}")
        return f"{dotted} -- {entry.note or 'tooling'}, shared by both engines"

    def catalogue(self) -> dict[str, str]:
        """Every module name mapped to :meth:`provenance`."""
        return {name: self.provenance(name) for name in sorted(CATALOGUE)}

    def overrides(self) -> tuple[str, ...]:
        """The modules where this engine differs from the other one."""
        if self.version == "3.1.4":
            return ()
        return tuple(sorted(n for n, e in CATALOGUE.items() if e.v35))


def engine(version: str | None = None) -> Engine:
    """The engine for ``version``, or :data:`DEFAULT_VERSION` if none is named."""
    chosen = DEFAULT_VERSION if version is None else str(version)
    if chosen in ("soda2", "soda-2", "SODA-2", "SODA2"):
        raise UnknownVersion(
            "SODA-2 is not a UIOOPS version and is not selectable here -- it is "
            "a separate processing lineage (NCAR, IDL) whose port covers the "
            "particle path only. Import arrayprobe_soda2 directly.")
    if chosen == "3.1.4" and "3.1.4" not in versions():
        from arrayprobe_uiops.engine_absence import ABSENT_MESSAGE, V314EngineAbsent
        raise V314EngineAbsent(ABSENT_MESSAGE)
    if chosen not in ("3.1.4", "3.5"):
        raise UnknownVersion(
            f"unknown UIOOPS version {chosen!r}; this package offers "
            f"{list(versions())}. The default is {DEFAULT_VERSION}.")
    return Engine(chosen)
