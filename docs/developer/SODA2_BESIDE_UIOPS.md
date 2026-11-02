# SODA-2 beside UIOOPS

Cite SODA-2 as: Aaron Bansemer. (2026). abansemer/soda2: v2.26.0 (Version v2.26.0) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.18331418

A Markdown twin of the artifact page (not included in this release, "SODA-2 beside
UIOOPS"), for a reader who will never open an artifact. Same content, same citations; written
2026-09-21 and verified against the repository at write time, not transcribed from memory. Every
claim below carries a `file:line` or a named test/document. Where a number could not be re-derived
in the time available, this document says so rather than guessing.

## What each package is, and who wrote it

**UIOOPS** (University of Illinois OAP Processing Software) is a MATLAB package from the McFarquhar
group, University of Illinois. This project ports its v3.1.4 lineage (`UIOPS-v3.1.4/joefinlon-
UIOOPS-ba5e67c/`) and, separately, its v3.5 lineage (`UIOPS-v3.5/joefinlon-UIOPS-039be82/`). It is
licensed **GPLv3** (`UIOPS-v3.1.4/joefinlon-UIOPS-ba5e67c/LICENSE`). The v3.1.4 lineage, with the
five dated ORACLES-specific edits in `uioops_testing/`, is what actually wrote the ORACLES 2016
2D-S/HVPS product of record.

**SODA-2** (System for OAP Data Analysis, version 2) is Aaron Bansemer's IDL package at NCAR
(`SODA2/abansemer-soda2-afcea15/soda2_process_2d.pro:7`), developed by NCAR's Mesoscale and
Microscale Meteorology Laboratory. It is licensed **3-clause BSD**, copyright University
Corporation for Atmospheric Research (UCAR)
(`SODA2/abansemer-soda2-afcea15/LICENSE.txt`). **It shares no source with UIOOPS.** It was written
independently and makes different choices at nearly every stage: one driver and one in-memory
options structure (`op`) instead of four MATLAB programs joined by netCDF files; images decoded on
demand and never stored; an additive reject bitmask instead of one first-match letter; an adaptive
per-second shattering cutoff instead of a fixed threshold. `arrayprobe_soda2` is this project's
third port, a separate package that imports neither UIOOPS engine
(`src/arrayprobe_soda2/`, 49 modules, `find src/arrayprobe_soda2 -maxdepth 1 -name
"*.py"` excluding `__init__.py`).

**SODA-2 is not a UIOOPS derivative, and it is never treated as an oracle for UIOOPS.** It is a
second, independently-written processing chain. When SODA-2's and UIOOPS's numbers disagree on the
same raw file, that disagreement is a finding to investigate — a difference in algorithm, threshold
or convention worth naming — never evidence that either chain is wrong. Only a file a package
itself wrote (a UIOOPS `.cdf`, or a SODA-2 `.dat`/`.sav`) can adjudicate that package's own port; a
cross-chain comparison bounds and motivates investigation, and nothing more.

## Licence consequences

- UIOOPS is GPLv3 and SODA-2 is 3-clause BSD; this project's own code is BSD-3-Clause-licensed, and each
  upstream is credited and its notice kept beside the engine that ports it.
- The two engine packages that reproduce UIOOPS (`arrayprobe` for v3.1.4, `arrayprobe_uiops` for v3.5)
  and the SODA-2 port (`arrayprobe_soda2`) are kept as separate importable packages for this reason
  among others: each carries its own upstream's credit and notice, and neither upstream's terms
  are mixed into the other's engine.
- Enhancements (opt-in corrections, never on by default) are likewise split by upstream:
  `enhancements_uiops/` and `enhancements_soda2/` are separate installable packages, each importing only
  its own engine and never the reverse (`tests/test_no_enhancement_coupling.py`
  guards the UIOOPS side; the SODA-2 side is guarded the same way, `enhancements_soda2/tests/
  test_lineage_isolation.py`).

## How the two pipelines map onto each other, stage by stage

| Stage | UIOOPS (v3.1.4) | SODA-2 |
|---|---|---|
| Configuration | `sizeDist`'s many positional arguments, plus a `FidelityProfile` for the two divergent MATLAB sources | one `op` IDL structure, defaulted by `soda2_update_op.pro:10-44`, saved into the output as `data.op` |
| Raw decode | `read_binary_SPEC.m`, a two-record sliding window, decodes everything up front into `.H.cdf`/`.V.cdf` | `spec_index` records pointers only; frames decode on demand inside the buffer loop and are never stored |
| Per-particle geometry, habit, reject code | `imgProc_sm.m` | `soda2_processbuffer.pro:279-374` (particle time) plus the per-particle tail (`:612-747`): `fillholes`, `poisson_spot_correct`, `soda2_findsize`, `soda2_reject` |
| Size distribution | `sizeDist.m`, 1 s bins, a fixed 6 µs shattering threshold for ORACLES | `soda2_particlesort.pro`, any averaging `rate`, an adaptive double-Poisson shattering cutoff (`intcutoff`) with a multiplicative `corr_fac` |
| Concentration | `sizeDist.m:1757`, written in `cm⁻⁴` | inline at `soda2_process_2d.pro:619-742`, `conc1d`, in `m⁻⁴` |
| Stitching one probe's files | `combine_sizedist.m` | the driver itself handles one run; `merge_main.pro` (not ported) joins two *different probes'* finished products at a size crossover |
| Output | netCDF files with no record of which call made them; the port adds a `.call` sidecar | an IDL SAVE `.dat` (or `.sav`) carrying `data`, including `data.op` — the configuration is saved inside the product itself |

Full function-by-function detail, with `file:line` on both sides for nine pairs (raw decode,
particle time, per-particle size, rejection, shattering, sample area/DOF, concentration,
combine/merge, what the output records): the artifact page's "Side by side, function by function"
section, sourced the same way as this document.

## What each calls the same concept

| Concept | UIOOPS name | SODA-2 name |
|---|---|---|
| The whole run's configuration | `sizeDist` arguments + `FidelityProfile` | `op` structure |
| One raw SPEC record | "record" | "buffer" (4114 bytes: header, 2048 data words, footer) |
| One particle image | — | "frame" (`'2S'`-tagged, inside a buffer) |
| Per-particle intermediate output | `imgProc_sm`'s netCDF (plays this role) | PBP: particle-by-particle (`.pbp.nc`/`.pbp.csv`), optional, written after rejection is known |
| The size-distribution product | `sizeDist`'s netCDF | `.dat`/`.sav` (the IDL SAVE file holding `data`) |
| Which of several size definitions to bin by | `d_choice` (1-6) | `smethod` (7 choices, including 1-D/2-D probe emulations) |
| Effective array width method | `SAmethod` (0/1/2) | `eawmethod` (`centerin`/`allin`/`reconstruct`) |
| Sample-volume accounting | dead-time subtraction inside `sizeDist.m` | `activetime`, `deadtime` — seconds the probe was live in each interval, and the overload time removed |

## Which one to reach for

- **Reproducing an archived UIOPS/ORACLES product, or validating this port against UIOOPS itself:**
  `arrayprobe` (v3.1.4, the ORACLES-validation anchor) or `arrayprobe_uiops` (the default UIOOPS
  engine for new processing). SODA-2 is never a substitute here — it cannot adjudicate a UIOOPS
  port, because it is a different program.
- **Reproducing or cross-checking a SODA-2-produced product (e.g. a UND `.dat`, another group's SODA-2
  product):** `arrayprobe_soda2`, the only engine that can read what SODA-2 itself wrote.
- **A new dataset with no archived product from either chain:** run both where the probe and mode
  allow it (`docs/developer/COVERAGE_MATRIX.md`), and treat agreement as reassuring and
  disagreement as a lead, not a verdict — see the next section.
- **Wanting corrections applied, not just findings reported:** both engines route opt-in,
  default-off corrections through their own enhancement package
  (`enhancements_uiops/` for UIOOPS, `enhancements_soda2/` for SODA-2); `arrayprobe soda2 run` applies
  SODA-2's resolved-ON corrections through `arrayprobe_soda2_enhancements.registry.apply`, which
  substitutes each one into `arrayprobe_soda2.enhancement_hooks` for the duration of the
  `soda2_process_2d` call — 14 of 19 correction/diagnostics modules currently route through a hook
  point this way (`enhancements_soda2/BACKLOG_STATUS.md`, "Applied by `arrayprobe soda2 run`").

## A chain disagreement is a finding, never proof

UIOOPS and SODA-2 use different sizing algorithms, rejection schemes, shattering corrections and
units, so **a numeric difference between their outputs is expected by construction** — not
evidence that either program is wrong. Two illustrations, both verified in the repository at write
time:

- **Per-particle sizing, on real 2D-S data, agrees almost exactly**: matched particle for particle
  (stock UIOOPS thresholds), 38,444 pairs, median diameter difference **0.0000 µm**, ratio **1.0000**.
  Whatever
  the two circle-fit conventions do in principle, on this data they size identically — so a
  chain-level concentration difference on this file is not sizing.
- **Whole-flight concentration, MATLAB (the archived ORACLES product) against UND's SODA-2 output**,
  is size-dependent and far from 1: **5.383×** over all seconds and bins (n=50,808), rising to
  **8.9466×** restricted to used bins ≥ 6 (n=25,651) — two verified cuts on identical underlying
  data move the ratio 66%. The candidate causes — sample-volume definition,
  acceptance thresholds, UIOOPS's fixed 6 µs shattering cut against SODA-2's fitted `corr_fac`, a
  possible `+1`-pixel sizing convention difference — are *listed*, not asserted, because for the
  2D-S file behind this figure the SODA-2 run's exact configuration (`op`) is not known. The gap is
  real and large — not evidence against either program, but exactly what this project exists to
  investigate.
- Where the port's own configuration for the SODA-2 side *is* known — UND's HVPS-3 `.dat` files,
  which carry `op` inside the product — the two chains agree closely once the port emulates the
  exact 2016 SODA-2 revision UND ran: accepted particles 18,017 against UND's 17,817 (ratio 1.0112)
  on 2016-09-12 and 10,796 against 10,821 (0.9977) on 2016-09-14, with `dhist` exactly equal on
  both. The discriminating step behind that emulation being trustworthy, rather
  than a coincidence: the vendored SODA-2 source itself, run unmodified under GDL on the real raw
  buffers, matches the port call for call on both flights' windows (18/18 buffers and 10/10 calls
  on 0914; 1,303/1,303 buffers and 41/41 calls on 0912) — so the residual against UND traces to the
  *2016 SODA-2 revision*, not to a port defect.

The general rule and its traps (which estimator, which cut, which denominator, which engine) apply
to any chain-to-chain ratio: state all four before quoting one.

## Where the port stands today (measured 2026-09-21)

- **Coverage**: the probe × engine × mode matrix (`docs/developer/COVERAGE_MATRIX.md`, generated
  by a script) has 70 cells (the two shipped engines). SODA-2's parallel modes (`--chunks`,
  `--jobs`, `--jit`) are cross-checked for CIP, HVPS and 2D-S (`--s2-jobs` stays untested for
  SODA-2). No cell of the matrix reads `refuses, defect`; PIP under `arrayprobe_soda2` is
  cross-checked in serial mode.
- **Speed, opt-in, proven byte-identical**: `arrayprobe_soda2.jit_kernels` accelerates the
  flood-fill kernel `label_blobs` uses (needs numba, off by default); `arrayprobe soda2 run` also
  takes `--chunks` and `--jobs`. All three are asserted byte-identical to serial, never approximate
  (`tests/test_soda2_jit_product_identity.py`,
  `tests/test_soda2_parallel.py`). A whole real 2D-S flight, every enhancement on,
  `--jobs 10 --jit`, 40 chunks: **21.1 minutes**, 0 cells different from serial across `conc1d`,
  `hist3d` and all 7,930,610 cells of `spec2d_aspr`.
- **I/O routines ported beyond the core chain**: `export_ncdf.py` (`soda2_export_ncdf.pro`, called
  by the GUI's `soda2_export.pro`, not the driver; GDL bank of 16 cases, 13 OK matched variable for
  variable, 3 HALTED cases refused by the port too) and `pth_readers.py` (the ASCII/CSV and netCDF
  true-airspeed readers `soda2_process_2d.pro:147-172` calls when `op.pth` is not a SAVE file; GDL
  bank of 22 cases, 21 OK, 1 HALTED); an IDL SAVE `.dat` writer proven restore-equal under
  `scipy.io.readsav` and GDL `RESTORE`
  (`src/arrayprobe_soda2/save_writer.py`). `[soda2].pth` naming a `pth` file produced
  by `arrayprobe make-tas-file ... --soda2-pth <file>.csv` is documented in
  [TAS.md](TAS.md#7-the-tas-source-chain).
- **Not yet built**: `merge_main.pro` (joining two probes' finished products at a size crossover)
  has no port.

## See also

- `docs/developer/TWO_ENGINES.md` — the equivalent one-page answer for the two *UIOOPS* engines
  (v3.1.4 vs v3.5), a different axis from this document.
