# SPDX-License-Identifier: BSD-3-Clause
"""Generate the API reference pages from ``src/*/**/*.py`` via AST.

Plan S4C ("Reference (generated): API reference..."). AST rather than
import: importing several of these modules reads files or builds state at
import time (``triage_server``, the CLI's own argument defaults), and AST
sees every public name whether or not this environment could actually import
it. Each module's own ``__all__`` is the honesty boundary here too --
:mod:`arrayprobe.readers` (the package ``__init__``) declares an empty one
and is skipped rather than guessed at.

**Docstrings are converted, not reproduced verbatim.** The subset handled:
a `` :role:`name` `` reST role becomes a plain code span (the role itself is
dropped -- this package's docstrings use it as emphasis, not as a resolvable
cross-reference target markdown has no equivalent for), and a paragraph
ending in ``::`` followed by an indented block becomes a fenced code block.
Everything else passes through unchanged, because plain reST prose already
reads as plain text.

**Nine pages across four packages**, grouped by what a reader is actually
looking for rather than alphabetically, because ``docs/_build/build.py``'s
search index only indexes the first 4,000 characters of a page (see its own
module docstring) -- one giant page would leave most of the API unsearchable.
Each page opens with a ``PACKAGE_NOTE`` line saying which engine it documents
and what that engine's validation rests on, because the three are not
interchangeable and only one of them has an archived product behind it.

Needs the venv only insofar as it walks ``src/``; it does not import the
packages themselves, so a module that could not currently import still gets
documented.

Usage, from the repository root::

    .venv/Scripts/python.exe docs/_build/apidoc.py [--check]
"""

from __future__ import annotations

import argparse
import ast
import functools
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC_ROOT = ROOT.parents[1] / "src"
PAGES_DIR = ROOT.parent

#: Packages under ``src/`` that deliberately ship without a generated API
#: reference, each with the reason it is excluded.
#:
#: A package under ``src/`` that appears in neither ``PAGE_GROUPS`` nor this
#: dict is a build failure. The point is that shipping a package with no
#: reference must be a **decision someone recorded**, never an accident of
#: this file's own path constants -- which is what it had been: ``SRC`` was
#: hardcoded to ``arrayprobe``, so ``_check_coverage`` could not see any
#: other package at all, and ``arrayprobe_uiops`` shipped five real modules
#: with no reference while every doc check stayed green.
#:
#: Removing a package from here is a **ratchet**: an entry naming a package
#: that no longer exists is also a failure, so an exclusion cannot outlive
#: the reason for it.
#:
#: **Empty since 2026-09-12**, and that is the point: every package under
#: ``src/`` now has a generated reference. An entry here is a decision to ship
#: one without, which has to be written down before it can happen.
PACKAGES_NOT_DOCUMENTED: dict[str, str] = {}

#: Modules held back from the public release, as (package, module path) ->
#: reason. A held-back module is in no ``PAGE_GROUPS`` entry, so no reference
#: page documents it, and ``_check_coverage`` counts it as classified rather
#: than missing. The entry is checked against the release allow-list
#: (``scripts/release_allowlist.txt``), a different source: where the allow-list
#: is present (the development tree), every held-back module must exist and be
#: carved out by a ``!`` line, so an entry cannot outlive its reason and a
#: module cannot be held back here while still shipping. Where the allow-list is
#: absent (the release tree, which does not ship it), the module must be absent.
MODULES_HELD_BACK: dict[tuple[str, str], str] = {
    ("arrayprobe_uiops", "mass_b26.py"):
        "an unpublished method, "
        "held back until its paper is out",
    ("arrayprobe", "hvps_caveat.py"):
        "the ORACLES HVPS flight caveats, a campaign sub-project that is not part of "
        "this package",
    ("arrayprobe", "hvps_flight_config.py"):
        "the ORACLES HVPS per-flight inter-arrival table, a campaign sub-project "
        "that is not part of this package",
    ("arrayprobe_uiops", "register_oracles_2016_cip_iat.py"):
        "the ORACLES 2016 CIP probe case, a campaign sub-project that is not part of "
        "this package",
    ("arrayprobe_uiops", "populations.py"):
        "the per-second 'all' and 'round' population counts, deferred from the release "
        "with its notebook (06_two_particle_populations)",
    ("arrayprobe", "tools/nasa_ames_tas.py"):
        "the NASA-Ames 1001 aircraft TAS reader, built for UND's 2016 files and not "
        "part of this package; the tas-from-nasa-ames subcommand refuses by name",
}

ALLOWLIST = ROOT.parents[1] / "scripts" / "release_allowlist.txt"
#: The release builder whose own ``parse_allowlist`` / ``allowed`` / ``never_ship`` decide
#: what ships; read here so the API reference and the release share one source of truth.
RELEASE_BUILDER = ROOT.parents[1] / "scripts" / "build_release_tree.py"


@functools.cache
def _release_verdict(allowlist: Path):
    """A ``ships(rel_path) -> bool`` built from the release builder's own allow-list logic,
    or None where the allow-list is absent (a tree with no release builder: nothing is
    filtered, and behaviour is what it was before the allow-list existed)."""
    if not allowlist.is_file():
        return None
    spec = importlib.util.spec_from_file_location("_apidoc_release_builder", RELEASE_BUILDER)
    builder = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = builder  # @dataclass resolves its module through sys.modules
    spec.loader.exec_module(builder)
    rules = builder.parse_allowlist(allowlist.read_text(encoding="utf-8"))
    return lambda rel: (builder.allowed(rel, rules) is not None
                        and builder.never_ship(rel) is None)


def _ships(package: str, module: str) -> bool:
    """Whether ``src/<package>/<module>`` reaches the release (always True with no allow-list)."""
    verdict = _release_verdict(ALLOWLIST)
    return True if verdict is None else verdict(f"src/{package}/{module}")


def _shipped_groups() -> list[tuple[str, str, str, list[str]]]:
    """``PAGE_GROUPS`` with every module the release allow-list excludes removed, and a group
    left with no shipped module dropped, so no reference page documents a module the release
    does not ship. :data:`MODULES_HELD_BACK` keeps its human-readable reasons; this covers
    every other carve-out (the v3.1.4 engine modules, the ARM campaign registrations) from
    the allow-list itself rather than a second hand-kept list."""
    groups = []
    for package, filename, title, modules in PAGE_GROUPS:
        kept = [m for m in modules if _ships(package, m)]
        if kept:
            groups.append((package, filename, title, kept))
    return groups

#: (package, page filename, title, module relative paths in render order).
#: Every *.py under every documented package must appear in exactly one group
#: -- enforced by ``_check_coverage``, so a new module is a build failure, not
#: a silent gap.
#:
#: The package column was added 2026-09-12. Before it, ``SRC`` was hardcoded to
#: ``arrayprobe`` and the other two ports could only ever be *excluded*, which
#: is how ``arrayprobe_uiops`` shipped a finished engine with no reference while
#: every documentation check stayed green.
PAGE_GROUPS: list[tuple[str, str, str, list[str]]] = [
    ("arrayprobe", "14-api-io-compat.md",
     "API reference: I/O and MATLAB compatibility", [
        "__init__.py", "config.py", "profiles.py", "regimes.py",
        "products.py",
        # 2026-09-28: the author-editable defaults file's loader
        # and generator, reached from config.py's [fidelity].authordefaults. Grouped
        # beside config.py and profiles.py, the two modules it sits between.
        "authordefaults.py",
        # The tune settings table: every setting a v3.5 run can change, where it is set,
        # and whether it reaches the output on a probe case. Grouped beside config.py and
        # authordefaults.py, the files most of its rows name. tune/sample.py draws the
        # review queues the triage server reads, from a proc file and time windows;
        # tune/distributions.py reports what is inside those windows, thresholds marked.
        "tune/__init__.py", "tune/settings.py", "tune/sample.py", "tune/distributions.py",
        # tune/score.py crosses the reviewer's labels with each particle's reject code.
        "tune/score.py",
        # tune/diodes.py reads bin_stats as lit counts and flags stuck diodes.
        "tune/diodes.py",
        # 2026-09-21: arrayprobe.engine(), the project-level selector
        # across all three engines. Grouped here because it is the package's
        # front door, beside __init__ and the profiles it sits next to in a
        # user's first few lines.
        "selector.py",
        # The lazy loader for the v3.1.4 engine, beside the selector that reaches it.
        "_v314_lazy.py",
        "ncio.py", "matio.py",
        # 2026-09-18: the one parser for every .call stamp format, returning
        # engine=None on absence rather than guessing -- cli.py had read an ABSENT
        # stamp as engine=3.1.4, which is how a v3.1.4 CIP product was described as
        # v3.5 for a day. Grouped beside ncio.py, the other I/O boundary.
        "provenance.py",
    ]),
    ("arrayprobe", "15-api-readers.md",
     "API reference: raw-format readers", [
        "readers/__init__.py", "readers/spec.py", "readers/dmt.py",
        "readers/sea.py",
        # The raw-file inventory uses the readers' own record-length constants.
        "inventory.py",
    ]),
    ("arrayprobe", "16-api-geometry-particle.md",
     "API reference: geometry and per-particle description", [
        "geometry/__init__.py", "geometry/min_circle.py", "geometry/min_ellipse.py",
        "geometry/min_rectangle.py", "particle.py",
        "particle_physics.py", "masks.py", "render.py",
        "dropsize.py", "habit.py",
    ]),
    ("arrayprobe", "17-api-pipeline.md",
     "API reference: the size-distribution pipeline", [
        "imgproc.py", "jit_kernels.py", "sizedist.py", "sizing.py", "reject.py",
        "attributed_export.py",
        "ai_ready.py",
        "lwc.py", "compare.py",
        "timing_closure.py", "validate_by_condition.py", "validation_report.py",
        "diode_report.py",
        # Read-only product checks beside timing_closure and validation_report.
        "count_closure.py", "reproduce_report.py",
    ]),
    ("arrayprobe", "18-api-cli-tools.md",
     "API reference: the CLI and visualisation tool", [
        "cli.py", "__main__.py", "triage_server.py", "triage_context.py", "run_page.py",
        "diagnostic_views.py",
        "review_sampling.py", "review_agreement.py",
        "tools/__init__.py", "tools/make_demo_flight.py", "tools/make_tas_file.py",
        "tools/probe_comparison.py",
        # Arrived 2026-09-16 with a merged lane. The coverage check refused to
        # build until it was classified, which is the check doing its job: a
        # shipped module with no reference must be a recorded decision, never an
        # accident of this file's path constants.
        "tools/synthetic_truth.py",
        # Arrived via merge-pass7, 2026-09-28: the held-out-evaluation stamp guard
        # (held-out evaluation policy). Grouped in the CLI/tools page,
        # beside the other scripts/*.py modules.
        "tools/heldout_stamp.py",
        # 2026-09-23: the ordered TAS source chain (merge ->
        # aircraft -> probe) that make_tas_file consults; same page, same reason.
        "tools/tas_sources.py",
        # Arrived from a merged lane: the mechanical stamp that marks a
        # held-out-evaluation output so it can never quietly become a tracked
        # fixture (the held-out evaluation policy's owed guard). Same
        # page as the other CLI-adjacent scripts/ modules.
        "tools/heldout_stamp.py",
        # 2026-09-30: the batch driver behind `arrayprobe run` and `arrayprobe reprocess`,
        # a package module so an installed wheel reaches it; scripts/<name>.py stay as thin
        # entry-point shims. Grouped with cli.py, its only package caller.
        "driver/__init__.py", "driver/run_flight.py", "driver/reprocess.py",
        "driver/_load_record.py", "driver/preflight_inputs.py",
        "driver/tas_from_probe_housekeeping.py",
    ]),
    ("arrayprobe", "31-api-friendly.md",
     "API reference: the friendly boundary layer", [
        "friendly.py",
    ]),
    ("arrayprobe_uiops", "19-api-v35-geometry.md",
     "API reference: the v3.5 port -- geometry, habit and measurement", [
        "__init__.py", "min_circle.py", "min_ellipse.py", "min_rectangle.py", "rect_ellipse.py",
        "particle_physics.py", "particle.py", "habit.py", "measure.py", "tas.py",
        # 2026-10-09: shared with v3.1.4 (alias shims at arrayprobe.particle_perimeter and
        # arrayprobe.sample_area), documented here at their home.
        "particle_perimeter.py", "sample_area.py",
        # 2026-10-09: shared leaves the v3.1.4 split moved here verbatim (min-circle and
        # min-ellipse helpers; Holroyd shape statistics); arrayprobe.geometry.min_circle and
        # arrayprobe.habit re-import their names, so they are documented once, at their home.
        "geometry_core.py", "habit_core.py",
    ]),
    ("arrayprobe_uiops", "20-api-v35-pipeline.md",
     "API reference: the v3.5 port -- pipeline, reader and reject", [
        "imgproc.py", "provenance.py", "decode_naming.py", "diode_mask.py",
        # The opt-in export of decoded 2D-S images to NCAR's RAF OAP format, and the reader
        # its round-trip test uses: post-processing beside the S2 decoder.
        "export_oap.py", "oap_read.py",
        # The netCDF layer both engines share (nothing outside v3.1.4 imports it); arrayprobe.ncio
        # re-exports it, so the v3.1.4 page keeps documenting the shim.
        "ncio.py",
        # The fidelity-profile type and the one shared registry (split slice 10a(i));
        # arrayprobe.profiles re-exports them and still holds the variants.
        "profiles.py",
        # 2026-09-18: S3's opt-in JIT kernels, ported alongside v3.1.4's
        # (reusing its proven `dec2bin_concat` and `particle_perimeter`, not
        # re-deriving them). Grouped beside imgproc.py, its only caller, the
        # same way arrayprobe's own jit_kernels.py sits beside imgproc.py above.
        "jit_kernels.py",
        # 2026-10-03: the opt-in stray-pixel correction, called only by imgproc.py.
        "stray_pixel.py",
        # 2026-10-07: the NCAR 2DC timing-word conversion, called only by imgproc.py.
        "ncar_2dc_timing.py",
        "qc.py", "sizedist.py", "sizedist_tables.py", "pecan_params.py", "reject.py", "lwc.py",
        "spec.py", "profile.py",
        # 2026-10-09: shared with v3.1.4, which keeps alias shims at the old arrayprobe paths;
        # documented here at their home.
        "matlab_compat.py", "time_convert.py", "constants.py",
        # 2026-10-09: shared leaves the v3.1.4 split moved here verbatim (reject thresholds and
        # helpers; SPEC record geometry and marker scan); arrayprobe.reject and
        # arrayprobe.readers.spec re-import their names, so they are documented once, here.
        "reject_core.py", "spec_core.py",
        # 2026-10-09: imgProc_sm time-base constants and helpers (split slice 7);
        # arrayprobe.imgproc re-imports them.
        "imgproc_core.py",
        # 2026-10-10: the error both the v3.1.4 lazy loader and the uiops selector raise when
        # the v3.1.4 engine is not installed.
        "engine_absence.py",
        # 2026-10-09: FORK_ONLY utilities (split slice 9);
        # arrayprobe.intarr and arrayprobe.readers.tasinfo are alias shims.
        "intarr.py", "readers/tasinfo.py",
        # 2026-10-09: split slice 9b; arrayprobe.combine,
        # .intarr_analysis and .intarr_plots are alias shims.
        "combine_fork.py", "intarr_analysis.py", "intarr_plots.py",
        # 2026-10-09: sizeDist time-conversion helpers (split slice 8a);
        # arrayprobe.sizedist re-imports them.
        "sizedist_core.py",
        "readers/__init__.py", "readers/pms.py", "readers/mask_csv.py",
        # 2026-09-18: import-time side effect that registers
        # "stock-v3.5-image-assisted" (arrayprobe.profiles.
        # register_stock_v35_image_assisted) in whatever process imports it --
        # named as PROFILE_MODULE so a fresh `run_flight.py --_run-chunk`
        # worker can resolve the profile by name. Grouped beside profile.py,
        # the module it is about.
        "register_image_assisted.py",
        # 2026-09-18: the same mechanism for "arm-ena-stock-v3.5", which
        # exists because ARM's delivery has no aircraft TAS file and v3.5 has no
        # TAS-free branch to flip a behaviour field toward.
        "register_arm_stock.py",
        # 2026-09-18: the size-dependent hollow rule the author's 480 triage
        # labels measured (~155 um switch point, stated with its overlapping
        # intervals). Opt-in, default off; grouped beside reject.py's own decision.
        "hollow_size_rule.py",
        # Upstream 2D-S bin-table finding, 2026-09-21: the named bin-ladder registry, and
        # the import-time module that registers "arm-ena-2ds" so the name
        # survives a --jobs worker's re-exec. Grouped beside sizedist_tables.py,
        # whose vendored tables it deliberately does NOT edit.
        "probe_cases.py",
        "register_arm_ena_2ds.py",
        "register_arm_ena_2ds_cold.py",
        # 2026-10-04: the sd/proc gross-failure sanity check.
        "product_sanity.py",
        "combine.py",
    ]),
    ("arrayprobe_soda2", "21-api-soda2.md",
     "API reference: the SODA-2 port", [
        "__init__.py", "sample_area.py", "min_circle_fast.py", "angles.py",
        "find_radius.py", "princomp.py", "aspect_ratio.py", "findsize.py",
        "fixraking.py", "fixstuckbits.py", "label_blobs.py",
        # 2026-09-18: SODA-2's opt-in flood-fill kernel
        # (label_blobs._label_region, 36.2x, byte-identical). Grouped beside
        # label_blobs.py, its only caller.
        "jit_kernels.py",
        "reject.py", "spec_decompress.py", "spec_readint.py", "spec_read_frame.py",
        "spec_read_hk.py", "spec_index.py", "spec_absolutepointers.py",
        # 2026-10-03: the HVPS-4 frame reader (`hvps4_read_frame.pro`),
        # beside the SPEC reader it parallels.
        "hvps4_read_frame.py",
        "processbuffer_spec.py",
        "processbuffer_tail.py",
        "poisson_spot_correct.py",
        "binary_dof.py",
        "fillholes.py",
        "particlesort.py", "fit_poisson.py",
        "timeconv.py", "read2dbuffer.py", "buildindex.py", "update_op.py",
        "probespecs.py",
        "process_hk.py",
        "pth_readers.py",
        "pbp_writer.py",
        "process_2d.py",
        # 2026-09-17: the driver's buffer loop split across processes.
        # Grouped with `process_2d.py`, its only caller, the way `mass_b26.py`
        # is grouped with `sizedist.py` -- and immediately after it, because a
        # reader of the driver is exactly the person who needs to know what
        # `jobs > 1` does and what it refuses.
        "process_2d_parallel.py",
        # 2026-10-02: the `fn_pbp` reprocess branch's two helpers
        # (`soda2_restore_pbp`, `spec_newtime`); `process_2d.py` is its only caller.
        "reprocess_pbp.py",
        "export_ascii.py",
        "enhancement_hooks.py",
        "save_writer.py",
        "export_ncdf.py",
        # 2026-10-07: its NCAR-RAF/nimbus sibling (`soda2_export_ncdf_raf`),
        # GDL-banked; like `export_ncdf`, no driver call site.
        "export_ncdf_raf.py",
        "sea.py",
        "decompress_dmt.py",
        "processbuffer_cip.py",
        # 2026-10-07: the NCAR RAF Fast-2DC buffer path
        # (`soda2_processbuffer_f2dc`), beside the CIP buffer path it parallels.
        "processbuffer_f2dc.py",
        # The NCAR RAF 2DC buffer path (`soda2_processbuffer.pro:80-127`) and its two
        # helpers: `fix2dimage` (sync repair) and `backfill` (first-slice reconstruction).
        "processbuffer_2dc.py",
        "fix2dimage.py",
        "backfill.py",
    ]),
    ("uiops", "24-api-selector.md",
     "API reference: the version selector", [
        "__init__.py",
    ]),
]

#: A line under each package's page heading. A reader who lands here from
#: search needs to know which engine it is and what its validation rests on
#: before reading a signature -- the three are not interchangeable, and only
#: one of them has an archived product behind it.
PACKAGE_NOTE: dict[str, str] = {
    "arrayprobe":
        "Shared tooling, readers and the command line. An earlier translation "
        "of UIOOPS v3.1.4 reproduced archived products and is not part of this "
        "package; its engine modules are not shipped.",
    "arrayprobe_uiops":
        "The **v3.5 port** -- complete, and the default for new work. "
        "Validated at layer 2 only: every routine on the "
        "**stock v3.5 path** is asserted against GNU Octave running v3.5's own "
        "sources, because no archived campaign product was ever produced by "
        "v3.5 and none can be. The ellipse fit included: `iRectEllipse=1` is "
        "goldened against the real `CGAL_EllipseSize` binary, compiled under "
        "Octave. The opt-in, default-off additions this package carries beyond "
        "any tagged UIOOPS release are each proven bit-identical to stock when "
        "off and validated against its own named oracle instead of the Octave "
        "goldens above; see `TWO_ENGINES.md` §1. One such addition, the mass "
        "dispatch in `mass_b26.py`, is not in this release.",
    "uiops":
        "The **version selector** -- the entry point that returns the UIOOPS "
        "engine; this package ships one, v3.5. It dispatches and computes nothing: "
        "no number changes because a call came through here.",
    "arrayprobe_soda2":
        "The **SODA-2 port** -- NCAR's IDL chain, a third and independent "
        "processing lineage rather than a UIOOPS variant, and an engine on "
        "equal footing with UIOOPS v3.5. Its differential oracle is GDL. "
        "The SPEC path is ported from raw bytes to written output: the buffer "
        "decode (`spec_decompress`, `spec_readint`, `spec_read_frame`, "
        "`spec_read_hk`, `spec_index`, `spec_absolutepointers`); the driver's "
        "pre-loop (`hms2sfm`, `soda2_parsedate`, `soda2_update_op`, "
        "`soda2_buildindex`, `soda2_read2dbuffer`, `spec_process_hk` versions 1 "
        "and 2, `spec_index_hk`); "
        "`soda2_processbuffer.pro` end to end (`processbuffer_spec` and the "
        "shared per-particle tail, `processbuffer_tail`); the particle path "
        "(sample area, the geometry core, sizing and rejection); the per-second "
        "accumulation (`particlesort`, `fit_poisson`); the driver itself "
        "(`process_2d`); the `.pbp.csv` and `.pbp.nc` per-particle writers "
        "(`pbp_writer`); the ASCII size-distribution export (`export_ascii`, "
        "turned on by `asciipsdfile`); the IDL SAVE file (`save_writer`, "
        "`savfile`); and the ASCII/CSV/netCDF PTH (true-airspeed) readers "
        "(`pth_readers`), wired into `process_2d`; and reprocessing from an "
        "existing `.pbp.nc` (`fn_pbp`, `reprocess_pbp`), library-only. "
        "`arrayprobe soda2 run <config>` drives it from a `[soda2]` run "
        "configuration and writes a `.pbp.call` sidecar. The driver takes three "
        "`op.format` families: SPEC; DMT CIP (PIP included) in SEA or DMT "
        "framing (`processbuffer_cip`, `decompress_dmt`, `sea`, GDL-validated), "
        "with the CIP 1-D housekeeping route (`process_cip1d_sea`) when `seatag` "
        "has two or more elements; and RAF Fast-2DC, probetypes `F2DC` and "
        "`F2DC_v2` (`processbuffer_f2dc`), serial only, because the "
        "`f2d_remainder` carry crosses buffers; on a real CAESAR 2024 file its "
        "output is identical to `soda2_process_2d.pro` under GDL in all eight "
        "fields compared (`tests/test_soda2_raf_realfile_gdl.py`). Any other `op.format` raises, "
        "as does any other probetype within a family: SEA CIPG, 2DC, 1D2D, "
        "HVPS and HAIL; DMT CIPG; RAF 2DC, HVPS1 and F2DC66. The HVPS-4 and "
        "3VCPI/Hawkeye SPEC subformats (1 and 2) decode through "
        "`hvps4_read_frame` and `spec_read_frame`'s version-1 path, checked "
        "against GDL on synthetic buffers only. Particle-image output "
        "(`ncdfparticlefile` 2) runs on the serial driver and is refused with "
        "`jobs > 1`; several raw files per run are indexed and concatenated "
        "for the SEA, DMT and RAF formats on the serial driver, "
        "while SPEC stops on the second file "
        "as `soda2_process_2d.pro:376` does. `soda2_export_ncdf.pro` is ported and GDL-banked "
        "(`export_ncdf`), as is its NCAR-RAF sibling `soda2_export_ncdf_raf.pro` "
        "(`export_ncdf_raf`); neither has a driver call site to wire -- the "
        "original `soda2_process_2d.pro` never calls either. Cite SODA-2 as: "
        "Aaron Bansemer. (2026). abansemer/soda2: v2.26.0 (Version v2.26.0) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.18331418",  # noqa: E501
}

_ROLE = re.compile(r":[A-Za-z_][A-Za-z0-9_-]*:`([^`]+)`")


def _docstring_to_md(doc: str) -> str:
    """The reST-to-markdown subset this project's docstrings actually use."""
    doc = _ROLE.sub(r"`\1`", doc)
    lines = doc.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.rstrip().endswith("::") and line.strip() != "::":
            out.append(line[: line.rstrip().rfind("::")].rstrip())
            i += 1
            block = []
            while i < len(lines) and (not lines[i].strip() or lines[i].startswith((" ", "\t"))):
                block.append(lines[i])
                i += 1
            while block and not block[0].strip():
                block.pop(0)
            while block and not block[-1].strip():
                block.pop()
            indent = min((len(b) - len(b.lstrip()) for b in block if b.strip()), default=0)
            out.append("```")
            out.extend(b[indent:] for b in block)
            out.append("```")
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = ast.unparse(node.args)
    returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{prefix} {node.name}({args}){returns}"


def _module_all(tree: ast.Module) -> list[str] | None:
    """The module's ``__all__``, plain or annotated.

    ``AnnAssign`` was added 2026-09-12, when the two new ports joined this
    generator: both write ``__all__: list[str] = [...]``, which the
    ``Assign``-only reader could not see, so ``arrayprobe_soda2``'s nine
    exported submodules rendered as *"No public API declared"* -- a generated
    page confidently understating the package it documents.
    """
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if not (len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == "__all__"):
                continue
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            if not (isinstance(node.target, ast.Name)
                    and node.target.id == "__all__"):
                continue
            value = node.value
        else:
            continue
        if not isinstance(value, (ast.List, ast.Tuple)):
            continue
        return [str(e.value) for e in value.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return None


def _constant_line(node: ast.Assign | ast.AnnAssign, name: str) -> str:
    """The one place that decides what a module constant's page shows.

    Only the name and a type -- the annotation when there is one, otherwise
    a type read from the AST -- never the value. Values carry file paths,
    dated notes and provenance that are not part of the API, and a length
    or character filter on them leaks the next short string that has one.
    """
    if isinstance(node, ast.AnnAssign):
        return f"{name}: {ast.unparse(node.annotation)}"
    return f"{name}: {_infer_type(node.value)}"


def _constant_doc(tree: ast.Module | None, node: ast.AST) -> str | None:
    """The first line of a constant's attribute docstring, or None.

    An attribute docstring is a bare string literal on the statement right
    after the assignment (PEP 257). Only its first line is shown, for the
    same reason the value is not.
    """
    if tree is None:
        return None
    for i, stmt in enumerate(tree.body[:-1]):
        if stmt is not node:
            continue
        nxt = tree.body[i + 1]
        if (isinstance(nxt, ast.Expr) and isinstance(nxt.value, ast.Constant)
                and isinstance(nxt.value.value, str)):
            first = nxt.value.value.strip().splitlines()
            return first[0].strip() if first else None
        return None
    return None


def _infer_type(value: ast.AST | None) -> str:
    """A type name for a constant's value, read from the AST without importing."""
    if isinstance(value, ast.Constant):
        return type(value.value).__name__
    simple = {ast.Dict: "dict", ast.DictComp: "dict", ast.List: "list",
              ast.ListComp: "list", ast.Tuple: "tuple", ast.Set: "set",
              ast.SetComp: "set", ast.JoinedStr: "str"}
    for kind, label in simple.items():
        if isinstance(value, kind):
            return label
    if isinstance(value, ast.Call):
        func = value.func
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
    if isinstance(value, ast.BinOp):
        left = _infer_type(value.left)
        if left in {"str", "list", "tuple", "dict", "set", "frozenset"}:
            return left
    return "object"


def _render_name(node: ast.AST, name: str, tree: ast.Module | None = None) -> list[str]:
    lines = [f"### `{name}`", ""]
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        lines += ["```python", _signature(node), "```", ""]
        doc = ast.get_docstring(node)
    elif isinstance(node, ast.ClassDef):
        bases = ", ".join(ast.unparse(b) for b in node.bases)
        lines += ["```python", f"class {name}({bases})" if bases else f"class {name}", "```", ""]
        doc = ast.get_docstring(node)
    elif isinstance(node, (ast.Assign, ast.AnnAssign)):
        lines += [f"```python\n{_constant_line(node, name)}\n```", ""]
        doc = _constant_doc(tree, node)
    else:
        lines += ["*(re-exported; not a local definition)*", ""]
        doc = None
    if doc:
        lines += [_docstring_to_md(doc), ""]
    return lines


def _find_public_node(tree: ast.Module, name: str) -> ast.AST | None:
    for node in tree.body:
        is_def = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        if is_def and node.name == name:  # type: ignore[attr-defined]
            return node
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name):
            return node
    return None


def _shared_leaf_node(tree: ast.Module, name: str) -> tuple[str, ast.AST] | None:
    """The definition of ``name`` when the module imports it from a v3.5 ``*_core`` leaf.

    The v3.1.4 split (2026-10-09) moved shared code verbatim into
    ``arrayprobe_uiops.<x>_core`` modules, which declare no public API of their own;
    the v3.1.4 module re-imports each name and keeps it in its ``__all__``. Without
    this, a public v3.1.4 name would render as a bare "re-exported" placeholder and
    its documentation would appear on no page.  Scoped to ``*_core`` leaves so no
    other re-export changes.
    """
    for node in tree.body:
        if not (isinstance(node, ast.ImportFrom) and node.level == 0 and node.module
                and node.module.startswith("arrayprobe_uiops.")
                and node.module.endswith("_core")):
            continue
        if not any(alias.name == name and alias.asname is None for alias in node.names):
            continue
        home_path = SRC_ROOT / (node.module.replace(".", "/") + ".py")
        if not home_path.is_file():
            return None
        found = _find_public_node(ast.parse(home_path.read_text(encoding="utf-8")), name)
        return (node.module, found) if found is not None else None
    return None


def _render_module(package: str, relpath: str) -> list[str]:
    path = SRC_ROOT / package / relpath
    tree = ast.parse(path.read_text(encoding="utf-8"))
    dotted = relpath[:-3].replace("/", ".").replace("\\", ".").replace(".__init__", "")
    qualname = f"{package}.{dotted}" if dotted else package
    public = _module_all(tree)
    lines = [f"## `{qualname}`", ""]
    moddoc = ast.get_docstring(tree)
    if moddoc:
        lines += [_docstring_to_md(moddoc.splitlines()[0]), ""]
    if not public:
        lines += ["*No public API declared (`__all__` empty or absent).*", ""]
        return lines
    for name in public:
        node = _find_public_node(tree, name)
        if node is None:
            # A package ``__init__`` whose ``__all__`` names its own
            # submodules -- ``arrayprobe_soda2`` does exactly this. Calling
            # those "re-exported from elsewhere" is true only in the most
            # literal sense and tells a reader nothing; say what they are.
            # Exact case: Windows' is_file() ignores it, so the exported constant
            # PROFILES read as the submodule profiles.py there and not on Linux.
            if (relpath.endswith("__init__.py")
                    and f"{name}.py" in {p.name for p in path.parent.iterdir()}):
                lines += [f"### `{name}`", "",
                          f"*Submodule -- `{package}.{name}`, documented "
                          "below.*", ""]
                continue
            shared = _shared_leaf_node(tree, name)
            if shared is not None:
                home, home_node = shared
                home_path = SRC_ROOT / (home.replace(".", "/") + ".py")
                home_tree = ast.parse(home_path.read_text(encoding="utf-8"))
                rendered = _render_name(home_node, name, home_tree)
                lines += rendered[:2] + [f"*(defined in `{home}`, the shared leaf both "
                                         "engines import; documented here, where it is "
                                         "public)*", ""] + rendered[2:]
                continue
            lines += [f"### `{name}`", "",
                     "*(re-exported from elsewhere; not defined in this module)*", ""]
            continue
        lines += _render_name(node, name, tree)
    return lines


def _all_modules(package: str) -> set[str]:
    root = SRC_ROOT / package
    return {str(p.relative_to(root)).replace("\\", "/")
            for p in root.rglob("*.py")}


def _is_alias_shim(package: str, module: str) -> bool:
    """True for a module that replaces itself in ``sys.modules`` with its home's module.

    Such a shim defines nothing of its own, so it needs no page entry: the home module
    (listed under its own package) is what a reader of the alias actually imports.
    """
    import re
    text = (SRC_ROOT / package / module).read_text(encoding="utf-8")
    return re.search(r"^_?sys\.modules\[__name__\]\s*=", text, re.M) is not None


def _packages() -> set[str]:
    """Every importable package under ``src/`` -- not just the documented one.

    An ``__init__.py`` is what makes a directory a package here, which also
    keeps ``arrayprobe.egg-info`` and other build droppings out without
    naming them.
    """
    return {p.name for p in SRC_ROOT.iterdir()
            if p.is_dir() and (p / "__init__.py").is_file()}


def _check_held_back() -> list[str]:
    problems = []
    carved = None
    if ALLOWLIST.is_file():
        carved = {line[1:].split("	", 1)[0].strip()
                  for line in ALLOWLIST.read_text(encoding="utf-8").splitlines()
                  if line.startswith("!")}
    for package, module in sorted(MODULES_HELD_BACK):
        rel = f"src/{package}/{module}"
        exists = (SRC_ROOT / package / module).is_file()
        if carved is None:
            if exists:
                problems.append(
                    f"{rel} is held back from the release but is present in a tree "
                    f"without the release allow-list")
        elif not exists:
            problems.append(
                f"MODULES_HELD_BACK names {rel}, which does not exist. Drop the "
                f"entry -- a hold must not outlive its reason")
        elif rel not in carved:
            problems.append(
                f"MODULES_HELD_BACK names {rel}, but {ALLOWLIST.name} has no "
                f"'!{rel}' line, so it would ship undocumented")
    return problems


def _check_coverage() -> list[str]:
    problems = []
    documented = {pkg for pkg, _f, _t, _m in PAGE_GROUPS}
    for package in sorted(documented):
        grouped = {m for pkg, _f, _t, mods in PAGE_GROUPS if pkg == package
                   for m in mods}
        actual = _all_modules(package)
        held = {m for pkg, m in MODULES_HELD_BACK if pkg == package}
        held |= {m for m in actual if not _ships(package, m)}
        missing = sorted(m for m in actual - grouped - held
                         if not _is_alias_shim(package, m))
        listed_held = sorted(grouped & {m for pkg, m in MODULES_HELD_BACK
                                        if pkg == package})
        if listed_held:
            problems.append(
                f"{package}: held back from the release but listed in PAGE_GROUPS: "
                f"{listed_held}")
        extra = sorted(grouped - actual)
        if missing:
            problems.append(
                f"{package}: not in any PAGE_GROUPS entry: {missing}")
        if extra:
            problems.append(
                f"{package}: PAGE_GROUPS names a module that does not exist: "
                f"{extra}")
        if package not in PACKAGE_NOTE:
            problems.append(
                f"{package}: no PACKAGE_NOTE. A reference page must say which "
                f"engine it documents and what its validation rests on")

    packages = _packages()
    undeclared = sorted(packages - documented - set(PACKAGES_NOT_DOCUMENTED))
    if undeclared:
        problems.append(
            f"package(s) under src/ with neither an API reference nor a recorded "
            f"reason: {undeclared}. Either add them to PAGE_GROUPS or say why not "
            f"in PACKAGES_NOT_DOCUMENTED -- a package must not ship undocumented "
            f"by accident")
    stale_notes = sorted(set(PACKAGE_NOTE) - packages)
    if stale_notes:
        problems.append(
            f"PACKAGE_NOTE describes a package that no longer exists: "
            f"{stale_notes}")
    problems += _check_held_back()
    departed = sorted(set(PACKAGES_NOT_DOCUMENTED) - packages)
    if departed:
        problems.append(
            f"PACKAGES_NOT_DOCUMENTED names a package that no longer exists: "
            f"{departed}. Drop the entry -- an exclusion must not outlive its reason")
    return problems


def render_page(package: str, title: str, modules: list[str]) -> str:
    lines = [
        f"# {title}",
        f"> Generated from `src/{package}`'s own AST; never hand-typed. "
        "Regenerate with `docs/_build/apidoc.py`.",
        "",
        PACKAGE_NOTE[package],
        "",
        "**See also** [CLI reference](13-cli-reference.md) · [Reference](08-reference.md).",
        "",
    ]
    for m in modules:
        lines += _render_module(package, m)
    return "\n".join(lines).rstrip() + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="fail if any page would change, without writing")
    args = ap.parse_args(argv)

    problems = _check_coverage()
    if problems:
        for p in problems:
            print("PROBLEM:", p)
        return 1

    changed = []
    groups = _shipped_groups()
    for package, filename, title, modules in groups:
        page = PAGES_DIR / filename
        rendered = render_page(package, title, modules)
        if args.check:
            current = page.read_text(encoding="utf-8") if page.is_file() else None
            if current != rendered:
                changed.append(filename)
        else:
            page.write_text(rendered, encoding="utf-8")

    if args.check:
        if changed:
            print(f"STALE: {changed} do not match src/; run docs/_build/apidoc.py")
            return 1
        packages = sorted({pkg for pkg, _f, _t, _m in groups})
        print(f"OK: all API reference pages match {', '.join(packages)}")
        return 0

    print(f"wrote {len(groups)} pages to {PAGES_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
