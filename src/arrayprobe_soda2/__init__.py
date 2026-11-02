# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""arrayprobe_soda2 -- a from-source Python port of SODA-2's OAP processing.

Scaffolded 2026-09-10 (author-directed) as V0 of a third, separate
package alongside the v3.1.4 port (``arrayprobe``) and the v3.5 port
(``arrayprobe_uiops``), touching neither. SODA-2 (NCAR/MMM, Aaron Bansemer,
``github.com/abansemer/soda2``) is a from-scratch IDL implementation of a
different OAP processing method, not a UIOOPS derivative -- so this is a
faithful *reimplementation* of SODA-2's own algorithm, the same discipline
the v3.1.4/v3.5 ports apply to UIOOPS, not an adaptation of anything already
in this repository.

**Citation.** Cite SODA-2, as its author asks, for anything computed here:
Aaron Bansemer. (2026). abansemer/soda2: v2.26.0 (Version v2.26.0) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.18331418

**Licence, read directly rather than inferred from GitHub's badge** (which
shows ``NOASSERTION``): ``LICENSE.txt`` in the vendored source is a
3-clause BSD licence (UCAR, 2016). This reproduction is distributed under
the same licence (LICENSES/BSD-3-Clause.txt), with the UCAR notice and
conditions kept. Nothing about the licence blocks porting
or incorporating SODA-2's logic.




Modules shipping here: ``sample_area`` (doctrine layer 3 -- no GDL bank),
the GDL-validated ``angles``, ``find_radius``, ``princomp``, ``reject`` and
``findsize`` (the sizing and rejection core), the SPEC
buffer-decode leaves, ``spec_decompress`` and ``spec_readint``, the
`spec_read_frame`, which composes them, `spec_read_hk`, the 53-word
housekeeping record, P-b's `spec_index` and `spec_absolutepointers`,
the buffer walk that produces the pointers all of them consume, and
P-c/P-d's `processbuffer_spec`, the SPEC branch of
`soda2_processbuffer.pro` (`:264-376`), and `poisson_spot_correct`, the
first leaf of its shared tail; the rest of the tail (`:612-747`) and the
driver remain unported. The stage table in the design record is
authoritative; this list is a map.

`binary_dof` and `fillholes`, two more leaves of the
shared tail (`:612-747`); `processbuffer_spec` now honours `dofreject == 3`.

`fixstuckbits` and `label_blobs`, two more tail leaves
(`:615`/`:687-689`). `soda2_backfill` (2DC only, `:678`) is ported in
`backfill`, GDL-matched (`tests/test_soda2_backfill_gdl.py`).

Round 5 (lane 6-B): `particlesort` (`soda2_particlesort.pro:1-171`, the
per-second accumulation) and `fit_poisson` (its
shattering-correction fit; no GDL oracle, since GDL 1.1.2 has no `LMFIT`
-- a documented substitute, see the module docstring).
Round 6, lane B (R6B) added the driver's SPEC pre-loop --
`timeconv` (`hms2sfm`, `soda2_parsedate`), `read2dbuffer`
(`read2dbuffer_spec`), `buildindex`, `update_op`, and `process_hk`
(`spec_process_hk`, both versions, and `spec_index_hk`). `buildindex`
covers the generic walk (`buildindex_generic`) and `read2dbuffer` the SPEC,
SEA (CIP) and DMT formats. Still refused by name: the model `.txt` header
parse (`soda2_update_op.pro:55-84`, `update_op.py`), the legacy SEA probes
(`soda2_read2dbuffer.pro:77-82`) and the remaining formats (T28, HVPS1995).

Round 6-A: `processbuffer_tail`, the shared per-particle tail of
`soda2_processbuffer.pro` (`:612-747`), SPEC path -- `soda2_processbuffer`
(in `processbuffer_spec.py`) now runs the whole function end to end for
SPEC, composing `process_spec_buffer` with `process_buffer_tail`.

Round 7-A (lane A): `process_2d` -- `soda2_process_2d.pro`, SPEC path,
raw bytes to the in-memory `data` struct end to end (`soda2_process_2d`).
Composes every module above with `sample_area` and `particlesort`.
Findings S6-a..S6-d.

Since then (rounds 7-B to 11 and Y1/Y1s, 2026-09-14): `pbp_writer`, the
`.pbp.csv` and `.pbp.nc` per-particle writers, GDL-checked and wired into
`process_2d` (`particlefile`, `ncdfparticlefile` 1); `export_ascii`, the
ASCII size-distribution export (`soda2_export_ascii.pro`, `asciipsdfile`);
the `dat`/`sav` PTH readers; and the CLI, `arrayprobe soda2 run <config>`,
which writes a `.pbp.call` sidecar.

Port lanes (2026-09-15): `save_writer`, the IDL SAVE file (`:729-731`,
`savfile`) written as `<outdir>/<date>_<hhmmss>_<shortname>[_<probeid>].dat`;
`pth_readers`, the ASCII/CSV and netCDF PTH formats (`:147-172`), wired
into `process_2d`; `probespecs`; `enhancement_hooks`, the named hook
points the SODA-2 enhancements adapter substitutes; `reprocess_pbp`,
the reprocess-from-PBP path (`:30-35,584-617`, `spec_newtime.pro`,
`soda2_restore_pbp.pro`), reached through `soda2_process_2d(op, fn_pbp=...)`.
Particle-image output (`ncdfparticlefile` 2, `:286-306`, `:546-553`) is
written on the serial driver (`pbp_writer`); it is refused by name only on
the parallel driver (`soda2_process_2d` with `jobs > 1`) and for a flush
chunk under two slices (`write_pbp_ncdf_images`), whose IDL behaviour is
unmeasured.
"""

import logging

# NullHandler by default, matching ``arrayprobe``'s
# own package logger -- importing this package must never print anything;
# ``arrayprobe.cli`` attaches the real handler for the console script.
logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__: list[str] = [
    "angles",
    "aspect_ratio",
    "binary_dof",
    "buildindex",
    "find_radius",
    "findsize",
    "fillholes",
    "fixraking",
    "fixstuckbits",
    "label_blobs",
    "min_circle_fast",
    "poisson_spot_correct",
    "fit_poisson",
    "particlesort",
    "princomp",
    "process_2d",
    "process_hk",
    "processbuffer_spec",
    "read2dbuffer",
    "processbuffer_tail",
    "reject",
    "sample_area",
    "spec_absolutepointers",
    "spec_decompress",
    "spec_index",
    "spec_read_frame",
    "spec_read_hk",
    "spec_readint",
    "timeconv",
    "update_op",
]

__version__ = "0.1.0"  # the distribution's version; tests/test_version.py
