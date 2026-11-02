# Speed — the measured numbers, and what each one is scoped to

**The single source of truth for every speed claim this project makes.** Every outward surface —
README, docs site, deck, artifact pages, readiness matrix — quotes **from here**.

**Takeaway.** The fastest configuration that writes the same bytes as a serial run is engine 3.5
with `--jit`, `--chunks N` for stage 3 and `--s2-jobs N` for the raw decode, `--jobs N` when a run
spans several raw files, and `--enh-jobs N` for the out-of-focus correction pass, with N up to the
machine's physical core count. Every one of these flags is opt-in, defaults to serial, and has a
test asserting the written files are unchanged; none trades accuracy for time. The multipliers
measured so far, each with its scope, are in the sections below; the generated table at the end of
this page, which keeps only runs with a load record, holds no serial and parallel pair yet.

## Speed-ups

Each row: what it speeds, its space, the test that proves it changes no output, how a user turns it
on, and its measured figure. A wall-clock figure is quoted only from a run whose harness recorded
the machine's other processes and load; none of these has one yet.

| change (commit) | speeds | space and proof | turn it on | measured with load recorded |
|---|---|---|---|---|
| Vectorised v3.5 prefix scan (`ea7d7a7`) | the serial scan that primes each `--chunks` chunk on 2D-S/HVPS | the port, byte-identical: `tests/test_v35_prefix_scan_fast.py` against the reference scan | automatic under `--chunks --engine 3.5` | no; the prototype factor (2026-09-30) has no load record |
| `position` stored in `[1024, 2]` blocks (`c07d4d2`, `90e7f1b`) | reading `position` back from a v3.5 proc file | the port's writer layout: values unchanged, file not byte-identical (`tests/test_v35_position_chunking.py`) | default for every v3.5 proc file | no (the 2026-10-01 measurement is a diagnosis, not a benchmark) |
| Stray-pixel variables carried through the chunk merge (`beaed49`) | keeps `--chunks` output equal to serial with the default-on stray-pixel correction, so chunking stays usable with it | the port, byte-identical with the correction on and off: `tests/test_v35_imgproc_merge_chunks.py` (`test_chunked_equals_serial_with_the_stray_pixel_correction_on`, `_off`) | automatic under `--chunks --engine 3.5` | no |
| `--enh-jobs N` on `arrayprobe run` and `run_flight.py` (`e8cbec6`) | the out-of-focus correction pass after every file is done | `enhancements_uiops/`: the parallel loop equals the serial one in the out-of-focus tests of the enhancement package's own suite (not included in this release); forwarding in `tests/test_cli_run_enh_jobs.py`, `tests/test_run_flight_enh_jobs.py` | `--enh-jobs N` (default 1) | no |
| Out-of-focus pool deadline (`9bce974`) | bounds a stalled or dead worker pool instead of waiting forever | `enhancements_uiops/`, same written files, checked by the enhancement package's own out-of-focus tests (not included in this release) | automatic with `--enh-jobs N` above 1 | not a speed figure |
| `arrayprobe tune diodes --jobs N` (`00c2b1c`) | the parallel `position` read in diode tuning, bounded, with a serial fallback giving the same sum | tooling, no written file: `tests/test_tune_diodes.py`, `tests/test_cli_tune.py` | `--jobs N` (1 forces serial) | no; the tuning wall clock below has no load record |
| Launch-width check (`c59e9a7`) | refuses a project run launched without `--jit` or below the physical core count | tooling, no computed number; a test executes the refusal | `launch_detached.sh` runs it; `--width-reason` overrides | not a speed figure |
| Generated speed table (`82368fd`) | quotes only finished runs that carry a clean load record | tooling: generated from the runs' launch logs | regenerate the table at the end of this page | the one quotable row is a serial stage-2 timing |

**The numbers are extracted, not read off by eye.** Each figure is parsed from its run's launch log
parses the per-stage wall clock out of a run's own launch log and emits one row per (flight, stage)
with the configuration that produced it, for per-stage, per-flight and per-campaign averages, and can set one
log against a serial baseline log.

Two rules matter more than the parsing. **A launch log holds every attempt under that name** — the
2026-09-21 launch log carries four exit lines from flag refusals before the launch that ran — so every
`launched detached` header resets the accumulator and the report describes the latest attempt only;
the first version called a working run finished. **A skipped stage is not a fast stage**: `S2 skip`
is recorded as skipped, excluded from totals, and yields no ratio (zero seconds for a stage nothing
executed is an infinite speed-up). A test in the development suite pins both.

**No campaign mean yet.** The five 2D-S flights of a second campaign and two CIP threshold arms (all
`--chunks`/`--jit`) are the first set large enough to average; the serial baselines to divide them
by do not exist yet.

## First measured rows, 2026-09-21/22

Extracted from the runs' own logs, not typed. Engine 3.5
throughout, `--jit` on, `--chunks` as shown; this machine has 12 cores.

| run | probe | chunks | S2 | S3 | S4 | S4c |
|---|---|---|---|---|---|---|
| UND CIP 09-06, stock-v3.5 | CIP (SEA) | 6 | 267 s | 4,758 s | 1 s | — |
| UND CIP 09-06, oracles-production-v3.5 | CIP (SEA) | 6 | reused | 4,717 s | 1 s | — |

These are *timings*, not speed-ups: no serial baseline for the same flight and stage exists, and a
multiplier against a different flight or machine is the kind of number this project has had to
retract. The tool's `--baseline` half is unused.

**S3 dominates** — 80 % of the 2D-S flight's wall clock and 94 % of the CIP's, so it is the only
stage where parallelism pays. **Stage 4 is free** at 1–67 s, so the CIP threshold arms re-run at no
cost. **The two CIP arms differ by 41 s over 4,700** (0.9 %): thresholds change what is kept, not
how much work is done.

**Limitation.** The four remaining flights ran as a *chain* into one launch log, and
`collect_run_timings.py` segments by relaunch, not by flight. They need one log per flight or a
chain-aware reader; neither exists, so they are absent above rather than guessed at.

---

## The claim this package can actually make, in one sentence

**Opt-in parallelism that is provably byte-identical to the serial path, on both engines.**

The standing objection to any fast reimplementation of a scientific code is *"you changed the
answer"*. Here the answer is asserted identical by test, so the speed costs nothing in fidelity.

The speed-work doctrine binds every row below:

1. **Every speed claim names its space** — the port, or `enhancements_uiops/`. All rows below are **in the
   port**: opt-in, default-off, no accuracy traded.
2. **A byte-identical claim is a test, not a sentence.** Each row names the test.
3. Default is serial. Nothing here changes what a user gets unless they ask for it.

**Probetype-2 chunking on engine 3.5 (prefix-priming).** Engine 3.5 accepts
`--chunks` for 2D-S/HVPS/3VCPI (○ cells below), except when `iQC=1`, which stays refused (a prefix scan cannot locate
`imgProc_sm.m:850-853`'s width-mismatch return). **No speed figure exists yet for this path** — the
only number measured is an 11.8 % prefix-scan cost on a 25-record fixture, taken before the scan was
vectorised, an upper bound that does not represent a real file (per-record overhead dominates a
small file). Do not quote a stage-3 chunking multiplier for probetype 2 until one is measured on a
real flight; the measured probetype-2 figure is the stage-2 decode's (`--s2-jobs`, below).

**The prefix scan is vectorised — space: the port.** The serial scan that primes each
chunk (`arrayprobe_uiops.imgproc._scan_seam_states`) reads the seven record-header fields once for the
whole scan, finds each record's boundary rows with one array comparison instead of a Python loop
over all 1,700 slices, and selects the airspeed samples for a record's own second once per record
rather than once per particle. The start bookkeeping and the `Time_in_seconds` fold run unchanged
over the boundary rows only. The literal slice-by-slice walk stays as
`_scan_seam_states_reference`, the oracle: `tests/test_v35_prefix_scan_fast.py` (14 tests) compares
the two by float64 bit pattern at a stop on every record of the 25-record fixture and on synthetic
records reaching each branch of the walk, and a one-ULP perturbation is detected. It runs whenever
`--chunks --engine 3.5` is given on probetype 2, adds no dependency and moves no written byte.
**No quotable speed figure** (a wall-clock figure is quotable only with the machine's
load recorded). Two bounded measurements on the first records of the 2D-S file
`base160906125407`, both on a loaded machine without a clean load record: a scratch prototype
(1,200 records, 34 seams bit-equal) 29.9 → 6.6 ms per record, about 4.5×; the shipped code (600
records, 18 seams bit-equal) 31.5 → 2.6 ms per record. They indicate the scale and are not to be
quoted. On that flight's contaminated run the scan was about a fifth of stage 3 and the serial merge
about a third (measured 2026-09-30); the merge's cost sat in
the `position` variable's one-particle HDF5 chunks, which the next entry addresses.

**The v3.5 writer stores `position` in 1,024-particle blocks — space: the port.** Every
v3.5 proc file written since commit `44af23b` stores `position` as `[1024, 2]` HDF5 chunks (4,096
bytes, the size netCDF-C gives `Date` and `Time_in_seconds` by default) instead of the library's
`[1, 2]`, one chunk per particle (`arrayprobe_uiops.imgproc.WRITER_CHUNKING`, recorded in
`WRITER_GAPS` beside the uncompressed-output gap). It is the default, with
no flag; the v3.1.4 writer is unchanged. **Values are unchanged; the file is not byte-identical**:
the storage layout differs, so this is a writer-layout default rather than a byte-identical speed
path. `tests/test_v35_position_chunking.py` asserts the chunk shape, that every other variable
keeps the library default, and that `position` values read back unchanged on a 3,000-particle
synthetic write; the every-variable comparison across the two layouts on the demo flight
is not built yet. **Why it matters**, measured 2026-10-01 on one file written
before the change, a 2D-S proc file `proc.base180215125340.H.nc` (4.23 GB, 17,815,784
particles stored as 17.8 million `position` chunks): reading `position` cost about 13–32 µs per
particle on 100,000-particle slices (1.3–3.2 s warm, up to 9.5 s cold), roughly 5–6 minutes for
the whole variable in one process, and netCDF read-cache settings made no difference. That is an
order-of-magnitude diagnosis on a loaded machine (a full test suite running, load about 45 %), not
a benchmark; so is the 194 s wall clock of `arrayprobe tune diodes` on that file with 8 worker
processes. **No read-time figure on a new-layout file is quotable yet**: the measurement that
would make one quotable is the three arms `[1, 2]`, `[1024, 2]` and `[2048, 2]` on the same file,
with a load record.

**Runs this project launches are checked for width — space: tooling, no computed number.** A width check, run by `launch_detached.sh` before every launch,
refuses a `run_flight.py` or `arrayprobe soda2 run` command (typed directly or inside a `.sh`
chain) that lacks `--jit`, or whose widest `--jobs`/`--chunks`/`--s2-jobs` is below the physical
core count (the fastest byte-identical configuration the machine can take).
`--width-reason "<why>"` overrides it and writes the reason into the run's log.
A 22-test module executes the refusal. It speeds up nothing;
it stops a narrow run being launched unnoticed.

---

## The cross-product — every engine × probe × dataset cell, and its state

Every engine, every probe tested or testable, every dataset (stock, ORACLES, IMPACTS when raw
is available). Two CIP cells are the only measurements, so this section is **mostly a roadmap**: it
names where a number is not yet measured, what command produces it, and which data would have to be requested.

**Every cell takes exactly one of four states; three are absences.**

| State | Means | Obligation |
|---|---|---|
| ⬤ **MEASURED** | a wall-time pair, a ratio, and its full scope | quotable, *with* the scope |
| ○ **TESTABLE NOW** | raw is held **and** an engine path exists — a measurement is **not yet made** | run the command; no number may be quoted until it is run |
| ▽ **NO RAW HELD** | the engine path exists; the data does not | name what to request, and from whom |
| ✕ **NO ENGINE PATH** | no code route exists, whatever the data | name the specific gap |

**Every cell below is tagged *measured* (a tool was run or opened the file and read the
value), *derived*, or *read* (a named `file:line` or document states it).** No cell is guessed. A
projected ratio is not a measurement anywhere in this document — see the `sea_s2` row.

---

### Table A — capability: engine × probe (24 cells)

Which engine has a **parallel flag that can reach that probe at all**. This is the gate: a dataset
cannot rescue a cell that fails here. Probetypes are `constants.py:76-79` (*read*); flag coverage is
`run_flight.py`'s probe gates (`S2_READERS` drives all four probetypes; `V314_PROBES` scopes the
v3.1.4 engine to 2D-S and HVPS), `arrayprobe_uiops.sizedist`'s probetype dispatch (0-3, all ported)
and `arrayprobe_soda2.read2dbuffer`'s format dispatch (*read*, cited per row).

| Probe (probetype) | `arrayprobe` (v3.1.4) | `arrayprobe_uiops` (v3.5) | `arrayprobe_soda2` |
|---|---|---|---|
| **2D-S** (2) | ○ `--s2-jobs` `--chunks` `--jobs` `--jit` | ⬤ `--s2-jobs` (`read_binary_spec_v35_parallel`, `tests/test_v35_spec_parallel.py`, `tests/test_run_flight_v35_s2_jobs.py`): **4.26×** at 10 parts on an ORACLES 2017 file, stage 2 only (below); ○ `--chunks` via prefix-priming (refused only when `iQC=1`), untimed; ○ `--jit` (measured on a CIP, **not** on this probe) | ○ `--jobs` `--chunks`, `'SPEC'` dispatched (`read2dbuffer.py:271-278`) |
| **HVPS(-3)** (2) | ○ same four flags; **needs a preset, no code change** | ○ same prefix-priming and `--s2-jobs` | ○ `'SPEC'` version 1 = "2DS/HVPS3" (`soda2_process_2d.pro`) |
| **CIP** (1) | ✕ driver gate, by design: `V314_PROBES` scopes v3.1.4 to 2D-S and HVPS; the driver runs this probe under v3.5 | ⬤ **2.62×** — the only UIOOPS stage-3 measurement | ⬤ **3.70×** — the only SODA-2 measurement |
| **PIP** (1) | ✕ same driver gate | ▽ `--chunks` available (probetype 1); S4 ported for probetype 1 (in the v3.1.4 engine, not included in this release) | ○ the DMT (PADS/PACS) path reads PIP as CIP (`read2dbuffer.py:273-274`, `soda2_update_op.pro:49`); no speed figure on it |
| **2DC** (0) | ✕ same driver gate | ▽ `--chunks` at **stage 3 only**; S4 runs probetypes 0 and 3 serially (in the v3.1.4 engine, not included in this release) | ✕ refused: SEA probetypes other than CIP (`read2dbuffer.py:186-188`, `process_2d.py:804-806`) and the RAF/TXT/T28/HVPS1995 formats (`read2dbuffer.py:276-278`) |
| **2DP** (0) | ✕ same driver gate | ▽ as 2DC, stage 3 only | ✕ as 2DC |
| **Fast2DC** (3) | ✕ same driver gate | ▽ as 2DC, stage 3 only | ✕ as 2DC |
| **3VCPI** (2 in UIOOPS) | ✕ no reader; SPEC version-2 frames unported | ✕ no reader (the probetype-2 chunk refusal itself is lifted by prefix-priming) | ✕ the engine decodes SPEC subformats 1 (3VCPI, `spec_read_frame` version 1) and 2 (HVPS-4, `hvps4_read_frame`) (`processbuffer_spec.py:285-295`; only a subformat outside 0-2 raises, `:241-244`), GDL-checked on synthetic data only (no real 3VCPI/HVPS-4 file held, `process_hk.py:6`), but `run_flight.py` names no 3VCPI or HVPS-4 probe, so no parallel flag reaches it |

**Table A: 24 cells — ⬤ 3 · ○ 6 · ▽ 4 · ✕ 11.** The 2D-S v3.5 cell is ⬤ for its stage-2 decode alone; prefix-priming makes the HVPS v3.5 cell ○, and the DMT path the SODA-2 PIP cell; 3VCPI's v3.5 cell stays ✕ for the unrelated no-reader reason, and its SODA-2 cell because the driver names no 3VCPI probe.

**Coverage by probe:** CIP has a figure on both live engines; 2D-S has one on the v3.1.4 engine and,
for the stage-2 decode only, on v3.5 — on SODA-2 the parallel path exists and the raw is held, but
no run has been timed; **HVPS has no speed figure on any engine**, though the same flags reach
it (on v3.1.4 once a preset is added); PIP, 2DC, 2DP and Fast2DC have either no raw held or no
parallel path.

#### The structural finding

**Both UIOOPS engines' parallel paths cover probetype 2.** v3.1.4's four flags all run through
`run_flight.py`, which admits **probetype 2 only**. v3.5's `--chunks` admits every probetype,
probetype 2 through **prefix-priming**, refusing only the `iQC=1` case. So:

- We hold ≈ 59 GB of 2D-S and HVPS raw (ORACLES 2016 + 2017, Table B) — the probetype v3.5 can
  also chunk. v3.1.4's flags *do* cover it and **do** have published whole-flight timings (1.461×
  and 1.575× end to end — see the v3.1.4 section); v3.5's stage-2 decode on this probetype is
  measured (below), and its stage-3 chunking is ○ **TESTABLE NOW**, with no wall-clock number
  measured yet (see the reissue note above).
- v3.5 can chunk both probetype 1 (CIP/PIP) and probetype 2 (2D-S/HVPS/3VCPI, `iQC=0`). Our
  probetype-1 holding is nine `.sea` files from one delivery; the probetype-2 holding is the ≈ 59 GB
  above — the larger of the two by far.

Two of the three *measured* cells are CIP; the third is v3.5's 2D-S decode, stage 2 only.
Probetype 2's stage 3 under v3.5 lacks only the run — the next measurement, not a capability gap.

---

### Table B — what raw is actually held (the data gate)

*Measured* unless marked. Counts from an input manifest (last built 2026-09-14) and from directory listings.

| Dataset | Probes with raw held | Volume | Where | How established |
|---|---|---|---|---|
| **ORACLES 2016** | 2D-S, HVPS (25 × 2D-S, 6 × HVPS) | 31 files, **23.8 GB** | ORACLES archive via `ARRAYPROBE_ORACLES_DATA` | *measured* (manifest §ORACLES 2016) |
| **ORACLES 2016 — SEA/CIP** | **CIP**, 9 `.sea` files | one per flight leg | local reference-data directory (`ARRAYPROBE_REFERENCE_DATA`), `*/PostProcessing/*.sea` | *measured* (listing) |
| **ORACLES 2017** | 2D-S, HVPS3 | 44 files, **35.4 GB** | as above | *measured* (manifest §ORACLES 2017) |
| **ORACLES 2018** | **none** | 0 | — | *read* ("2018 holds no raw"); 31 combined products only |
| **IMPACTS** | **none** | 0 | — | *measured* (no IMPACTS raw anywhere in the holdings) |
| `PECAN` / `GPM` / `SOCRATES` / `otherwise` | **not datasets** — stock `sizeDist.m` project arms | — | `constants.py` (16 `(project, probe)` pairs) | *measured* (enumerated from source) |

**Two things to carry from Table B.** (1) **A second campaign holds 2D-S raw here and nothing else**, so every cell beyond the 2D-S is a data
request, not a run. (2) **The stock arms hold no data of their own**, and they are sparse: `PECAN`
has only CIP and PIP; `SOCRATES` only 2DS, Fast2DC and PIP; `GPM` only 2DS, 2DC, CIP and HVPS. An
unlisted probe *raises* — the inner `switch probename` has no `otherwise` (`sizedist_tables.py:126`,
*read*). So a "PECAN 2D-S" speed cell is not slow to measure; it does not exist.

---

### Table C — the measurable grid: dataset × (engine · probe)

Seven of the engine·probe columns that survived Table A appear here; v3.5 · HVPS, ○ in Table A, is
not yet a column. **56 counted cells.**

| Dataset | v3.1.4 · 2D-S | v3.1.4 · HVPS | v3.5 · 2D-S | v3.5 · CIP | SODA-2 · 2D-S | SODA-2 · HVPS3 | SODA-2 · CIP |
|---|---|---|---|---|---|---|---|
| **ORACLES 2016** (2D-S/HVPS raw) | ○ **×4 flags** | ○ preset first | ○ | ▽ → SEA row | ○ | ○ | ▽ → SEA row |
| **ORACLES 2016 SEA/CIP** (9 `.sea` files) | ▽ SEA files hold no 2D-S | ▽ | ▽ SEA files hold no 2D-S | ⬤ **2.62×** (+ 8 flights and the `sea_s2` denominator not yet measured) | ▽ | ▽ | ⬤ **3.70×** (`--chunks` not yet measured) |
| **ORACLES 2017** | ○ **×4 flags** | ○ preset first | ⬤ **4.26×** stage-2 decode (`--chunks` not yet measured) | ▽ no 2017 SEA delivery held | ○ | ○ | ▽ |
| **ORACLES 2018** | ▽ | ▽ | ▽ | ▽ | ▽ | ▽ | ▽ |
| **IMPACTS** | ▽ | ▽ | ▽ | ▽ | ▽ | ▽ | ▽ |
| `PECAN` arm | ✕ no PECAN/2DS arm | ✕ no arm | ✕ no PECAN/2DS arm | ✕ `getPECANparams` in neither vendored tree (as the v3.1.4 engine's `sizeDist` notes; that engine is not included in this release) | ✕ | ✕ | ✕ |
| `GPM` arm | ▽ arm exists, no raw | ▽ arm exists, no raw | ▽ arm exists, no raw | ▽ arm exists, no raw | ✕ | ✕ | ✕ |
| `SOCRATES` arm | ▽ arm exists, no raw | ✕ no arm | ▽ arm exists, no raw | ✕ no arm | ✕ | ✕ | ✕ |
| `otherwise` arm | *cross-reference* | *cross-reference* | *cross-reference* | *cross-reference* | *cross-reference* | *cross-reference* | *cross-reference* |

**`otherwise` is not counted, on purpose.** It is the arm every ORACLES and UND run **already
resolves to** (`sizedist_tables.py:24`, *read*), so its seven cells are rows 1-4's cells under another
name; counting them would double-count the measurements. The SODA-2 columns in rows 6-8 are ✕
because **SODA-2 has no project-arm table** — its configuration is per-run TOML.

**Table C: 56 counted cells — ⬤ 3 · ○ 9 · ▽ 29 · ✕ 15** (plus 7 uncounted cross-references).

**80 counted cells across Tables A and C. Three measurements fill them, each appearing once in each
table.**

---

## The measured cells, in full scope

Nothing below may be quoted without the scope beside it.

| Engine / stage | Probe | Flag | Serial | Parallel | Speedup | Identical? | Test |
|---|---|---|---|---|---|---|---|
| **UIOOPS v3.5**, stage 3 (`imgproc`) | CIP (probetype 1) | `--chunks 8` | **269.5 s** | **103.0 s** | **2.62×** | all **40** variables byte-equal; every global attribute but `Creation Time`/`Image Source` | `tests/test_v35_imgproc_merge_chunks.py` (26 tests) |
| *same, larger file* — see the note below | CIP | `--chunks 8` | *not measured* | **1,797.6 s** | *no ratio* | — | — |
| **SODA-2**, buffer loop | CIP (SEA) | `--jobs 12` | **413.1 s** | **111.7 s** | **3.70×** | all **35** arrays byte-equal | `tests/test_soda2_parallel.py` |
| **UIOOPS v3.5**, stage 2 (decode) | 2D-S (probetype 2) | `--s2-jobs 10` | **665 s** | **156 s** | **4.26×** | every variable, dimension and attribute but `Creation Time`; the three `.csv` sidecars byte-equal | `tests/test_v35_spec_parallel.py`, `tests/test_run_flight_v35_s2_jobs.py` |

**The larger file has no ratio, deliberately.** `sea_s2.CIP.cdf` (23,939 records, **3,797,537
particles**) completed stage 3 chunked in **1,797.6 s — 30 minutes**, against a *derived* serial
estimate of ≈ 3 h 28 min. Dividing those would give ≈ 6.9×, **and that figure must not be quoted**:
the denominator is a projection from the s1 rate, never run. The run does establish that the
mechanism scales — per-chunk startup amortises on a bigger file.

**The first three rows are CIP.** None may be presented as a 2D-S or HVPS number; Table A explains
why. **The last is a 2D-S decode (stage 2) only**: not a stage-3, size-distribution or whole-flight
figure, and not an HVPS one.

### The scope that must travel with each number

| | UIOOPS v3.5 (CIP) | SODA-2 (CIP) | UIOOPS v3.5 (2D-S decode) |
|---|---|---|---|
| Input | `sea_s1.CIP.cdf`, 950 records, 103 MB | `2016_09_06_06_40_17.sea`, 949 buffers | `base170813113317.2DS`, ORACLES 2017-08-13, 426 MB |
| Work | 82,028 particles | 81,169 particles | 48,652 H / 46,793 V records |
| Machine | 12 logical cores, otherwise idle | 12 logical cores, otherwise idle | 10 physical / 12 logical cores; each run's load record CLEAN (other processes 0.46 and 0.41 core, none at or above 0.25), the two run one after another |
| Profile | `oracles-production-v3.5` | UND CIP SEA config | `oracles-production-v3.5` |
| Recorded | run record of 2026-09-17 | run record of 2026-09-17 | run record of 2026-10-24 |

**A contended measurement is not a measurement.** The SODA-2 measurement re-ran its whole file on the
shipping code and got 554.1 s → 201.3 s, **2.75×** — and marked it *do not quote*, because
`Get-CimInstance Win32_Process` found eight foreign workers at ≈ 577 s CPU each on a 12-core box
(the concurrent UIOOPS CIP run). Contention inflated the serial side 34 %. **A ratio taken while
something else was running is reported and discarded, not quoted** — which is also why the ten ○
cells cannot be measured in parallel with each other.

### One condition on the SODA-2 row that must be published with it

**`arrayprobe soda2 run --jobs N` exits 2 wherever a substitution cannot be rebuilt inside the
worker.** Not a bug — a refusal built on purpose (`refuse_unsplittable`, reading the port's own
`enhancement_hooks.pristine()` and `reconstruction_plan()`). SODA-2's corrections and the 2016 UND
emulation work by **replacing module globals**, and a spawned worker inherits no monkey-patch, so a
parallel run that did nothing about them would silently drop them. **Scope, corrected 2026-09-23
(this paragraph said "when any enhancement is live" for three days after that stopped being true):**
`arrayprobe_soda2_enhancements.registry.apply` (commit `c69bb1e`, 2026-09-20) installs the
shipped corrections with a reconstruction plan. Each worker rebuilds them by name, and the split is
byte-identical to serial with them on (`tests/test_soda2_parallel_enhancements.py`). What is still
refused is the UND emulation's rebound driver call, an ad-hoc callable with no plan,
`op.stuckbits`, `op.activetimefrommissed` and more than one raw file. The four 2D-S runs of
2026-09-22 used `--jobs 10` with every correction live, and were accepted.

**How that was found is the reason to trust the refusal.** A first version of the refactor had the
serial loop call the same two halves as the parallel path. It silently bypassed every correction and
the emulation. **Five tests in the 714-test SODA-2 family caught it while every byte-identity test
stayed green** — the output *was* byte-identical to itself, just computed without the corrections.
Byte-identity is necessary and not sufficient.

The flagship sentence: **3.70× on the stock path, and a hard refusal rather than a silent wrong
answer where a substitution cannot be rebuilt.**

---

## The measurements not yet made, with the command for each

Every ○ cell in Table C is a run, not a research problem. All are launched
detached, **unpiped** (each writes straight to its own log), from the repository root. A serial twin on an
**idle** machine is half of every measurement, and a contended pair is discarded.

**1. v3.5 · CIP · the `sea_s2` serial denominator** — turns 1,797.6 s into the project's largest
measured ratio (3,797,537 particles). Re-run the stage-3
step of `examples/configs/cip_uiops/cip_sea_stage_by_stage.sh` on `sea_s2.CIP.cdf` with chunking **off**
(`chunks <= 1` is the untouched serial path), with the same stage-3 invocation as the chunked run of
2026-09-17 minus `--chunks`. ≈ 3.5 h detached, no code change.

**2. SODA-2 · 2D-S · ORACLES 2016** — the **first non-CIP number on any engine**, on the
product-of-record flight. Path and flag both already exist, so this is a timing run only:

```bash
.venv/Scripts/python.exe -m arrayprobe soda2 run \
    examples/configs/soda2/2ds_spec.toml --out <dir_serial>
.venv/Scripts/python.exe -m arrayprobe soda2 run \
    examples/configs/soda2/2ds_spec.toml --out <dir_par> --jobs 12
```

Run the two one after the other, not at once, since a contended pair is discarded.

**3. v3.1.4 · 2D-S · `--s2-jobs`, isolated** — the flag a new user meets first. The registry gives
`s2_speedup` **1.71×** (457 MB file) and **1.47×** (dense file), both on the i7-1365U, **both with
machine load UNRECORDED** — whole-pipeline runs with several flags on, predating the wait-quiet
control, so neither is isolated or checkable for contention. The pair still shows decode is
I/O-bound (more workers on one disk scale *worse* as the file grows); what is missing is an
**isolated, quiet-machine** run, started only once the machine is quiet. The flag has a byte-identity test and a
production history (a 13.3 GB decode at `--s2-jobs 6`):

**Which raw, and the trap in it.** `base160906064403.2DS` is the 2016-09-06 flight's FIRST leg and
covers **UT 24250.8-28370.5** (measured by indexing it: 75,668 buffers, 9,093,083 images). The CIP
work on the same date uses **UT 28793-52799** -- so this raw **has zero overlap with it and ends
422 s before that window opens**. It suits a *timing* pair and no comparison against the CIP or the
archived product: the
archived stem `base160906064017` is the flight's SUMMARY-FILE timestamp and names no raw at all,
and the archived product is a **five-file combine under a deliberately mixed configuration**
(`064403` at `rej_hollow=1`, the other four at 0), so this one file is roughly **8 % of the flight
by bytes**. The CIP window's own raw is `base160906075333.2DS`. Established 2026-09-19, after a
an earlier attempt nearly built a comparison on disjoint time.

```bash
.venv/Scripts/python.exe scripts/run_flight.py \
    <raw>/base160906064403.2DS --preset ORACLES_2016_2DS_H --engine 3.1.4 --port-validation --out <dir_serial>
.venv/Scripts/python.exe scripts/run_flight.py \
    <raw>/base160906064403.2DS --preset ORACLES_2016_2DS_H --engine 3.1.4 --port-validation --out <dir_par> --s2-jobs 6
```

Run the two one after the other, not at once.

Then `--chunks`, `--jobs` and `--jit` on the same file, one flag per pair — a combined run measures
neither. **4.** The same three flags on a second 2D-S campaign and on
ORACLES 2017. **5.** SODA-2 `--chunks` on CIP, the one flag on a measured path with no number:
`-m arrayprobe soda2 run examples/configs/cip_soda2/und_cip_sea.toml --out <dir> --chunks 12`. **6.** v3.1.4
HVPS, which needs a `CampaignPreset` with an honest provenance line first — ~30 min, no code change
to the gate, and the preset is a scientific claim, so it ships with
provenance or not at all.

## The data that would have to be requested

| Cells it would open | What to ask for | From whom |
|---|---|---|
| 6 (all of row ORACLES 2018) | the UND raw 2D-S/HVPS delivery for the 2018 deployment | UND — the 2016 and 2017 deliveries came from there |
| v3.5 · PIP (▽ in Table A) | any PIP raw at all — the project holds none | UND / the PECAN or SOCRATES campaign archives |
| v3.5 · 2DC / 2DP / Fast2DC | 2DC/2DP/F2DC raw beyond the two files held locally (ACE-1 1995 2DC/2DP; CAESAR 2024 Fast-2DC), **on neither of which either stage has been timed** | campaign archives; `GPM` and `SOCRATES` arms exist in-tree |
| 6 (all of row IMPACTS) | IMPACTS raw. **Note both engines are ✕ on 3VCPI regardless**, so raw alone does not open these | NASA IMPACTS archive |
| the whole probetype-1 axis beyond one delivery | **CIP raw from a second campaign.** Nine `.sea` files from one delivery is the entire evidential base for the only probetype v3.5 can chunk | UND |

---

## The v3.1.4 engine

> The whole-flight, end-to-end timings for the v3.1.4 engine come from the numbers registry
> (the paper's number registry, not included in this release); each key carries its own `provenance` and `limits`.

### Measured, from the registry — whole-flight, 2D-S

*Read from the paper's number registry (not included in this release); each key carries its own `provenance` and `limits`.*

| Measurement | Overall | S2 decode | S3 imgproc | S4 | Registry key |
|---|---|---|---|---|---|
| End to end, 457 MB file (999.8 s → 684.5 s) | **1.461×** | **1.71×** | **1.48×** | — | `performance.end_to_end` |
| End to end, dense file, 1,074 MB (17,083 s → 10,849 s) | **1.575×** | **1.47×** | **1.59×** | **1.24×** | `performance.end_to_end_dense` |
| Cold run, 2017-08-13 | **1.64×** | — | — | — | `performance.cold_run_20170813` |
| S3 alone, `base160914075451` | **3.11×** (37,412 s → 12,011 s, *derived* from those two keys) | — | — | — | `performance.s3_serial_seconds`, `s3_chunked_seconds` |

The 457 MB and dense runs are **the same measurement design on two file sizes**, asking whether the
ratio rises with density. **It does — 1.46× → 1.575× — for the predicted reason:** S3's share of
the serial run rises from **82 % to 92.9 %**. **S2 moves the other way** (1.71× → 1.47×), because
decode is I/O-bound and six workers on one disk scale *worse* as the file grows.

**`cold_run_20170813`'s 1.64× carries the registry's caveat, which travels with it:**
*n=1, on a machine that was not quiet (a suite run and interactive work overlapped it), so it is a
lower bound on what the flags buy rather than a controlled benchmark.* Quote the two `end_to_end`
figures as the benchmark; quote 1.64× only as a floor.

### The flags these figures belong to

| Engine / stage | Flag | Identity test |
|---|---|---|
| v3.1.4 stage 2 decode | `--s2-jobs` | byte-identity test of the parallel decode (v3.1.4 engine, not included in this release) |
| **v3.5 stage 2 decode** (SPEC) | `--s2-jobs` (`readers.spec.read_binary_spec_v35_parallel`; each part primed with the running airspeed, every seam checked by bit pattern) | `tests/test_v35_spec_parallel.py`, `tests/test_run_flight_v35_s2_jobs.py` |
| **CIP/PIP (`.cip`) stage 2 decode**, either engine | `--s2-jobs` (`readers.dmt.read_binary_DMT_parallel`) | `tests/test_dmt_parallel.py`, `tests/test_run_flight_dmt_parallel.py` |
| v3.1.4 stage 3 | `--chunks` | byte-identity test of the chunk merge (v3.1.4 engine, not included in this release) |
| v3.1.4, per raw file | `--jobs` | `tests/test_run_flight_jobs_watchdog.py` |
| v3.1.4 stage 3 hot kernels | `--jit` (needs numba) | byte-identity test of the JIT kernels (v3.1.4 engine, not included in this release) |
| **v3.5 stage 3 hot kernels** | `--jit` (needs numba) | `tests/test_v35_imgproc_jit_identity.py` |
| stage 3 under `--chunks`, either engine | `--resume-chunks`: reuse the chunks an interrupted run finished | `tests/test_run_flight_chunk_resume.py` |
| **v3.5 stage 3 chunk priming** (probetype 2) | none; the vectorised prefix scan runs under `--chunks` | `tests/test_v35_prefix_scan_fast.py`, `tests/test_v35_sizedist_chunk_priming.py` |

The CIP/PIP decode splits a `.cip` file on its 4112-byte record boundaries and re-appends the parts through the one serial writer; the reader carries no state across records, so no priming is needed. Its output is asserted byte-identical to `read_binary_DMT` by test, it is opt-in through `--s2-jobs` (default serial), and a dead pool falls back to the serial decode. **No speed figure is measured for it**; one is quotable only from a real-file run with the machine's load recorded.

`--resume-chunks` saves the chunks' work when a run dies afterwards, for example in the merge. It
reuses a chunk only when the intent recorded before the chunk was built (the worker's argv, the S3
stamp, the source's size and mtime, the TAS file, the port's git tree and library versions)
matches the new run byte for byte, and the worker's completion record carries that intent's hash
and a particle count matching the file. Anything else rebuilds the chunk. A reused chunk merges
byte-identical to a fresh run (asserted with real workers), and the flag is off by default.

**All four v3.1.4 paths are probetype 2 only** — 2D-S and HVPS, because `run_flight.py`'s
`S2_READERS` gate admits nothing else (Table A).

**The v3.5 kernels are not so restricted**: `arrayprobe_uiops.jit_kernels`
measured **1.79x** on S3 of a real CIP production pass — 150 records / 9,245 particles of
`sea_s1.CIP.cdf` under the exact call its `.call` stamp records, 50.86 s serial against 28.49 s
with numba compile pre-warmed outside the timed region. One machine (13th Gen i7-1365U), serial,
**not** extrapolated to another probe or to a chunked run. It reuses v3.1.4's already-proven
`dec2bin_concat` and `particle_perimeter` kernels rather than re-translating them;
`cgal_min_r_v35` is deliberately **not** ported (structurally different in v3.5 — it takes
`tas_ratio` and returns a centre — so it needs new kernel code and its own exactness proof).

**RESULT, 2026-09-18.** `--jit` is worth **1.60x on S3 of a real full flight**, MEASURED on a
machine verified quiet rather than assumed quiet. It supersedes a band measured earlier the same
day under contention; that band is kept intact, as the record of the correction.

- **MEASURED**: `sea_s2.CIP.cdf`, 23,939 records, 3,797,537 particles, CIP,
  `oracles-production-v3.5`, `--chunks 8`, i7-1365U — **1412.5 s -> 880.9 s = 1.60x**.
  Outputs byte-identical across all 40 variables and all 3,797,537 particles
  (`np.array_equal`, `'Creation Time'` excluded).
- **Machine verified quiet, not assumed**: `wait_quiet.py` held the run until four
  consecutive 30 s samples showed no other Python process; 70 of the 71 load samples
  spanning the pair read `other=0` (`machine_load.txt`).
- **Corroborated**, MEASURED: the same flight's smaller file, serial, run straight
  after: 166.9 s -> 107.2 s = **1.56x**. Two chunk counts, two files, both quiet:
  1.60x and 1.56x.
- **The earlier 1.22x pair is CONTAMINATED, not a disagreeing measurement, and must never
  be pooled or averaged with 1.60x**: it was measured while a 4,210-test suite ran
  concurrently on the same 12-thread laptop. Contamination *understated* the flag by 31%.
- **WITHDRAWN**: the "sub-additivity" finding that `--jit` is worth less once `--chunks`
  is on. On a quiet machine the two land together (1.60x chunked, 1.56x serial); the
  apparent gap measured earlier was contention, not the flags interacting.
- **DERIVED**, labelled derived: S2 (271.5 s) and S4 (86.8 s) carry no JIT kernel; S3 is
  79.8% of the pipeline, so S2+S3+S4 goes **1770.8 s -> 1239.2 s = 1.43x**. An infinitely
  fast S3 caps any pipeline ratio at 4.94x.
- **Scope**: one machine (13th Gen i7-1365U), one flight, one probe (CIP), S3 only — S2
  and S4 have no JIT kernel and are not sped up by this flag. Method and full noise
  analysis: `_decoded/speed_e2e/SPEED_E2E.md` (recorded 2026-09-18).

**WITHDRAWN 2026-09-18: the 1.22x full-flight row and the 1.2-1.6x band that replaced it.**
Every wall-clock second behind them was measured while the full test suite ran on the same
laptop; the identical configuration (`s1, chunks=1, jit=off`) measured **913.4 s and 168.2 s**,
a 5.4x spread with nothing changed. Neither the 1.22x nor the 1.2-1.6x range is to be quoted;
the live figure is the 1.60x above. Also withdrawn there: the claim that the contention biased
the figure one way. The fidelity evidence of those runs (all 40 variables and all 3,797,537
particles identical, `jit` off against on and `chunks=1` against `chunks=8`) depends on no
clock and stands.

**The reject path was the bigger win.** `calculate_reject_unified` measured **6.33x** under the production configuration (3.686 s -> 0.582 s) and **4.77x** with `rej_hollow=True`, on 9,245 real captured particles from `sea_s1.CIP.cdf` -- a count matching the imgproc measurement above exactly, which is a useful independent cross-check. i7-1365U, serial, cache pre-warmed. Two things this measurement corrected: the cost was **dispatch and marshalling across 47,198 per-slice calls**, not interpretation (`scan_slice` already numba-dispatches whenever numba is importable), so the fix was fusing the per-particle loop into one compiled call; and the production `.call` sidecar carries `rej_hollow=False`, so the hollow branch never runs in production at all and the scan pass is the entire cost. Byte-identity is proven **transitively**: the v3.5 reject tests already check the non-jit body against real Octave v3.5 output on a 105-particle bank that trips the preserved defects, and the reject jit-identity test proves non-jit == jit on that same bank, so jit == Octave truth.

**SODA-2's flood fill: 36.2x at the kernel, ~1.37x end-to-end (DERIVED, not measured).** `label_blobs._label_region` went from 2399.65 to 66.37 us/call over 103 real particle ROIs captured from an unmodified pipeline run, 600 reps so both sides are multi-second. The first pass is reported rather than hidden: at 40 reps four runs gave 13.1x, 60.0x, 20.2x and 44.3x, because the jit side was sub-second and machine noise dominated -- the 36.2x is the figure taken once both sides were multi-second. The end-to-end ~1.37x is **derived** from the profile's own ~28 % share, not measured, and is labelled as such here because no end-to-end measurement has been run. 14 identity tests via `np.array_equal`/`tobytes`, with two mutation tests (a raster-order swap, a dropped neighbour offset) each proven to DISAGREE with the reference, so the equality assertions are real discriminators rather than tautologies.

**And the profile that produced that figure found a false claim worth naming**: the largest cost
centre on a v3.5 pass is `calculate_reject_unified` at 7.37 s cumulative, which is **plain
Python**, despite `arrayprobe/jit_kernels.py`'s own docstring having claimed reject's kernels were
already compiled. That is the next candidate, not a finished win — no multiplier is claimed for it
here.

**SODA-2's JIT covers the flood fill only.** The function-level profile (below) bounds the
addressable share rather than promising a speedup: `label_blobs._label_region` is ~28 % of a run
and is clean integer flood-fill, provable on the `particle_perimeter` precedent, and is the kernel compiled; `findsize`'s `aspect_ratio`/`min_circle_fast` complex is a larger ~61 % but routes
through law-of-cosines angle computation, the same trig-exactness objection that kept `holroyd`
out of the v3.1.4 JIT work. Ceiling ~85-89 % of wall time addressable at best. **No measured
end-to-end SODA-2 multiplier exists.**

**Not yet measured:** a per-flag attribution on a *quiet* machine. The `end_to_end` keys are
whole-pipeline ratios with the flags on together, so no v3.1.4 figure separates `--jit`'s own
contribution or isolates `--jobs`.

## Function-level profiles

Two cProfile passes ranked the per-function cost in each engine. cProfile inflates functions called
many times, so these tables rank functions and give proportions; they do not time them. Both
verbatim records, with their full tables and reproduce commands, were kept with the project's run
records: the UIOOPS S3 pass of 2026-09-15 and the SODA-2 pass of 2026-09-18.

### UIOOPS S3 (`imgproc_sm`), v3.1.4 engine — space: the port

- **Input.** 100 image records (130000-130099) of the dense ORACLES 2016 file
  `base160906075333.2DS`, **21,916 particles**, profile `oracles-production`,
  profiled after a warm-up call outside the profiler, which excludes numba's compile.
  i7-1365U, shared with about 20 other processes, so the ratio comes from interleaved runs.
- **Reference path, cumulative share:** `_describe_particle` 63 %, `cgal_min_r` 22 %,
  `dec2bin_concat` (framing) 20 %, `MGrowVector.__setitem__` 14 %, `holroyd` 13 %, `dropsize` 6 %,
  `particle_perimeter` 5 %, `_write_block` 5 %, `calculate_reject_unified` 4 %.
- **Compiled behind `jit=True` / `--jit`, default off:** `dec2bin_concat` (one NumPy shift),
  `particle_perimeter` (numba loop), `cgal_min_r` (numba Welzl on homogeneous int64 circles, every
  int64 operation guarded below 2^62 with a `Fraction` fallback). **`holroyd` is left out**: its
  `arctan`/`cos`/`sin` could move one ULP under a different libm or a contracted multiply-add.
  `fastmath` is off everywhere.
- **Result:** interleaved wall 276.16 s → 166.08 s (**1.66x**) and 265.38 s → 163.44 s
  (**1.62x**); the `proc` file byte-identical in both reps; 0 of 21,916 guard fallbacks.
  The JIT byte-identity test (v3.1.4 engine, not included in this release) holds the identity claim (whole file, then per variable, on
  three inputs, plus kernel fuzzing, a tripped int64 guard and two mutations it must catch).
- **Derived, not measured:** S3 is 92.9 % of the densest file's 17,083 s serial run, so a 1.64x S3
  alone gives about 10,900 s serial. `--jit` composes with `--chunks` and `--jobs`.
- **Next, ranked by the post-jit profile (210.9 s profiled):** `MGrowVector` growth 47.4 s (grows
  one element per assignment; geometric capacity would be byte-identical by construction),
  `holroyd` 46.4 s (compile the integer half of `calc_stat` only), `dropsize` 20.7 s and
  `ncio.put_var` 19.8 s, then the `array_equal` boundary scan 9.4 s.

### SODA-2 (`arrayprobe_soda2`) — space: the SODA-2 port

- **Input.** A UND 2016-09-06 CIP SEA file, two windows (66 and 305 particles), both resolving to
  two buffer-records; cProfile on `soda2_process_2d`. The top-level split comes from an unprofiled
  stage timing (2026-09-17: the buffer tail is
  97.3 % of a run).
- **Ranking:** `label_blobs._label_region` ≈ 23.5-28 % of wall time (84.6 % of `fillholes`, which
  is 27.8 % of a run); the `findsize`/`aspect_ratio`/`min_circle_fast` complex ≈ 61 %, of which
  `min_circle_fast` is ≈ 14 %; `poisson_spot_correct` ≈ 2.4 %, not worth compiling; the
  `buildindex`/`read2dbuffer` file scan is I/O-bound.
- **Ceiling:** ≈ 85-89 % of wall time is addressable at best. I/O (≈ 3-4 %) and per-particle
  bookkeeping in `process_buffer_tail` (≈ 6 % of the tail) are not loop-shaped numeric work.
- **Limits:** a small sample (read the percentages to one significant figure); CIP/SEA only — the
  SPEC route shares the same tail code but was not profiled separately.

---

## Where parallelism is refused, and why — state this alongside the wins

A speed table names the cases that do **not** go fast.

| Case | Status | Reason |
|---|---|---|
| `--chunks` on **2D-S / HVPS / 3VCPI** under v3.5, `iQC=1` | **refused** | a prefix scan cannot locate `imgProc_sm.m:850-853`'s width-mismatch return, which only `qc_image` can trigger |
| `--chunks` on **2D-S / HVPS / 3VCPI** under v3.5, `iQC=0` | **lifted 2026-09-18 by prefix-priming** | `sizeDist.m:1131-1180` accumulates `Time_in_seconds` across the whole file; a post-hoc repair cannot reproduce it (float64 addition is not associative), but the two scalars that cross a seam (`part_time_prev`, `time_in_seconds_prev`) come from record/particle headers alone, so a **prefix scan** — no image unpacked, `measure_record` never called (spy-asserted) — primes each chunk exactly. Proven: all 40 variables `np.array_equal`, `Time_in_seconds` equal as bytes, a one-ULP mutation detected, the unprimed control disagrees in `Time_in_seconds` alone (53 of 99 particles, at most 2 ULP; measured by the paper's chunk-priming figure script, not included in this release). New API: `prime=` on `imgproc_sm_v35`, `prefix_scan_v35`, `chunk_primes_v35`, `PRIMABLE_TIMINGS_V35`, `merge_chunks_v35(primed=True)`; `run_flight.py --chunks --engine 3.5` primes automatically. `tests/test_v35_sizedist_chunk_priming.py` (20 tests). **No speed figure measured yet** — see the reissue note above |
| `--s2-jobs` under v3.5 on a PMS or SEA probe (2DC, 2DP, Fast2DC; CIP from `.sea`) | refused, **not built** | those readers have no parallel form; SPEC (2D-S/HVPS) and DMT (`.cip`) decodes do (`run_flight.py`'s stage-2 refusal) |
| `--diode-corrected` under v3.5 | refused, **genuinely absent** | `imgproc_sm_v35` takes no `shadow_diode` parameter |
| **every v3.1.4 flag on a non-SPEC probe** (CIP, PIP, 2DC, 2DP, Fast2DC) | **refused at the driver, by design** | `run_flight.py`'s `V314_PROBES` admits only 2D-S and HVPS under `--engine 3.1.4` (`tests/test_run_flight_v314_probe_gate.py`); v3.1.4 exists to reproduce archived ORACLES products. The driver itself drives all four probetypes (`S2_READERS`) and runs these probes under v3.5. This is why the v3.1.4 column of Table A is 2D-S and HVPS and nothing else |
| **SODA-2 on any SEA probe but CIP** | **refused by name** | `"SEA probetype {!r} not ported (only CIP is)"` (`process_2d.py:804-806`; `read2dbuffer.py:186-188`). A `seatag` with **≥ 2 elements**, including `update_op.py:66`'s default `[33000,0,0]`, runs `process_cip1d_sea` for housekeeping (`process_2d.py:984-988`) |
| **SODA-2 on 3VCPI / HVPS4** | **ported in the engine; GDL-checked on synthetic data only** | SPEC subformats 1 and 2 decode (`processbuffer_spec.py:285-295`; only a subformat outside 0-2 raises, `:241-244`) and version-2 housekeeping is `_spec_read_hk_v2`; no real 3VCPI/HVPS-4 file is held (`process_hk.py:6`), and `run_flight.py` names neither probe |
| **dask** | **declined**, with a reopening condition | S3 reads per-record scalars, so `dask.array` has nothing to attach to; one stage is 92.9 % of a flight run, capping a task graph at ~7 %; and cross-chunk state needs a *merge*, which already exists. Cost was **not** the objection — dask is ~7× lighter than the numba already accepted. |

---

## The trap, named so nobody walks into it

**"arrayprobe is 2.6× faster" is not a claim this project can make.** Every figure above is one
probe, one stage, one file, one core count. The headline is the *mechanism* — byte-identical opt-in
parallelism on both engines, with the tests to prove it — and each number illustrates it with its
scope.

**8 chunks is a measured figure, not an optimum.** 10–12 may do better on 12 cores, changes no
output byte, and is unmeasured. A larger file should beat 2.62× as per-chunk startup amortises — a
reason to re-measure, not to extrapolate.

### Four more, which the matrix itself invites

**3. Do not rank 2.62× against 3.70×.** The matrix puts them in one table and they are not
comparable: different programs (UIOOPS v3.5 vs a SODA-2 port), different input formats (a decoded
`.CIP.cdf` vs a raw `.sea`), different work units (950 *records* vs 949 *buffers*), different stages
(image processing vs the driver's buffer loop) and different mechanisms (`--chunks` splits a file,
`--jobs` splits a loop). "SODA-2 parallelises better" is not a finding this table supports. They
agree on one thing: **both are byte-identical.**

**4. A ▽ or ✕ cell is not a slowness claim.** An empty cell in Tables A and C means *no data held*
or *no code route* — never *measured and disappointing*. Nothing in this document reports a
parallel path that failed to speed up. Say "unmeasured" of the 42 absences, never "no speedup".

**5. CIP measured is not probetype 1 measured.** PIP is the same probetype and shares the `--chunks`
route, but it has a 0.100 mm diode against CIP's 0.025 and a 260 mm arm distance against 100
(`constants.py`), so particles per record differ by a large factor and the chunk-startup amortisation
that gives 2.62× its value is differently placed. **Neither measured row extends to PIP**, and
`PECAN`/`SOCRATES` PIP additionally have no raw.

**6. A single ○ turning into ⬤ does not fill its row.** Each of the four v3.1.4 flags is its own
measurement — one flag per run pair, because a combined run measures neither — and each dataset is
its own file size and particle density. Ten ○ cells are **ten run pairs**, not one afternoon.

<!-- BEGIN speed_table.py (generated; do not edit by hand) -->

## Generated speed table, quotable runs only

The table is generated, not typed: its generator reads every `*.launch.log` in the run-log directory (364 logs at generation) and keeps a run only if it finished with exit 0 and carries a `CLEAN` load record whose `*.load.json` is found (a wall-clock figure is quotable only with a load record). The parallel flags are byte-identical, opt-in mechanisms, so each row's space is the port of the engine that ran. The machine is the one the run's load record names.

| campaign preset | flight file | stage | configuration | space | seconds | log |
|---|---|---|---|---|---|---|
| unstated | base180211140634.H.nc | S2 | serial | port, engine unstated (byte-identical) | 634 | chain_iop2_soda2_r2.launch.log |

Per-campaign mean over the quotable flight files:

| campaign preset | stage | configuration | files | mean seconds |
|---|---|---|---|---|
| unstated | S2 | serial | 1 | 634 |

No speed-up is reported: no quotable serial run shares a flight file and stage with a quotable parallel run.

Runs left out, per reason (stage rows in brackets):

| reason | runs | stage rows |
|---|---|---|
| exited 1 | 47 | 359 |
| exited 10 | 7 | 70 |
| exited 127 | 2 | 2 |
| load record CONTAMINATED | 1 | 1 |
| no exit line (still in flight or killed) | 44 | 370 |
| no load record found | 24 | 179 |

<!-- END speed_table.py -->
