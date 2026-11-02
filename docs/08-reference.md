# Reference
> Validation status, design documents, published pages, and where project state lives.

**In short:** validation status, the design records, the published pages, and licence and citation.

**See also** [CLI reference](13-cli-reference.md) ·
[API: I/O & compat](14-api-io-compat.md) · [API: readers](15-api-readers.md) ·
[API: geometry & particle](16-api-geometry-particle.md) · [API: pipeline](17-api-pipeline.md) ·
[API: CLI & tools](18-api-cli-tools.md) ·
[API: v3.5 geometry](19-api-v35-geometry.md) · [API: v3.5 pipeline](20-api-v35-pipeline.md) ·
[API: SODA-2](21-api-soda2.md) · [API: version selector](24-api-selector.md) ·
[Configuration & profiles](06-configuration.md) ·
[Known gaps](10-known-gaps.md) · [Conventions](09-conventions.md).

## Engine API pages

| Page | What it covers |
|---|---|
| [v3.5 geometry](19-api-v35-geometry.md) | the v3.5 port, the default engine: geometry, habit and measurement |
| [v3.5 pipeline](20-api-v35-pipeline.md) | the v3.5 port: pipeline, reader and reject |
| [SODA-2](21-api-soda2.md) | the SODA-2 port, NCAR's IDL chain as an independent lineage |
| [Version selector](24-api-selector.md) | `uiops.engine()`: returns the v3.5 engine and refuses SODA-2 |

## Validation status

Both engines are checked against their original sources executing unmodified: v3.5 under GNU
Octave, SODA-2 under GDL. What each claim rests on is in
[Validation](04-validation.md); what is not yet covered is in [Known gaps](10-known-gaps.md).

## Design documents

One per stage, written before the code, with its provenance (MATLAB tree, lines, what was
measured). Read it before changing behaviour.

| Area | Document |
|---|---|
| Octave as an oracle | `docs/developer/OCTAVE_AS_ORACLE.md` |
| probe × engine × run-mode coverage, generated from the code and real runs | `docs/developer/COVERAGE_MATRIX.md` |
| one page per probe: instrument, what runs, caveats, the ratios it appears in | [the site pages](33-probes.md), generated with `docs/developer/probes/README.md` |
| each enhancement | `enhancements_uiops/docs/CORRECTIONS.md`, a part per module |

## Building these docs

The pages are Markdown files in `docs/`; the rendered site is served by GitHub Pages.

## Licence and citation

**Author:** Siddhant Gupta (Argonne National Laboratory).
**Advisors and collaborators:** Joe O'Brien and Bobby Jackson (ANL), Greg McFarquhar and Yongjie
Huang (University of Oklahoma), Aaron Bansemer (NCAR MMM).
**Data providers:** Peter Brechner and Saurabh Patil (University of Oklahoma).

BSD-3-Clause; see `LICENSE` and `NOTICE.md`. Ported from UIOOPS; original copyright notices, including SODA-2's UCAR notice, are retained and
the MATLAB tree is never edited; attribution and the papers behind the constants are in
`NOTICE.md`. **An independent port; it is not a UIOOPS or SODA-2 release.**

Habit classification: Holroyd (1987), *J. Atmos. Oceanic Technol.* **4**, 498-511
(`holroyd.m`), and Schima et al. (2024), https://doi.org/10.1029/2024JD040895 (`holroyd_new.m`,
`holroyd_new_HVPS.m`, selected by `iNewHabit`).

A result from the SODA-2 engine cites SODA-2 as its author, Aaron Bansemer, asks:

> Aaron Bansemer. (2026). abansemer/soda2: v2.26.0 (Version v2.26.0) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.18331418
