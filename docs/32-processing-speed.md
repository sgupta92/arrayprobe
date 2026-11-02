# Processing speed
> Opt-in parallelism on both engines, proven byte-identical to the serial path by test — default serial, no accuracy traded. Every measured figure, its full scope, every place a parallel run is refused, and every measurement not yet made.

Every figure here is quoted from `docs/developer/SPEED.md`, the source of truth for speed.

## The fastest configuration — in the port

**Fastest configuration that writes the same bytes as serial:** engine 3.5 with `--jit`,
`--chunks N` for stage 3, `--s2-jobs N` for the raw decode, `--jobs N` across raw files and
`--enh-jobs N` for the out-of-focus correction pass, N up to the physical core count. Each flag is
opt-in, defaults to serial and is proven unchanged-output by test; `SPEED.md` lists every recent
speed-up with its test and whether a load-recorded timing exists.

## The claim this package makes, and the one it does not

**Opt-in parallelism that is provably byte-identical to the serial path, on both engines.**

The standing objection to a fast reimplementation is *"you changed the answer"*. Here the answer
is asserted identical by test, so speed costs no fidelity.

Three rules bind every row below:

1. **Default is serial.**
2. **Every speed mechanism here lives in the port**, not in the enhancements: opt-in, default-off,
   no accuracy traded. A change that moved a written byte would belong in `enhancements_uiops/`.
3. **A byte-identical claim is a test, not a sentence.** Each mechanism names its test module.

**And the claim this package does not make:** *"arrayprobe is 2.6× faster"* is not supportable by
anything here. Every figure is one probe, one stage, one file, one core count.

## The mechanisms, and the test behind each — all in the port

| Engine / stage | Flag | Identity test |
|---|---|---|
| v3.5 stage 2 decode (SPEC) | `--s2-jobs` | `tests/test_v35_spec_parallel.py`, `tests/test_run_flight_v35_s2_jobs.py` |
| per raw file, either engine | `--jobs` | `tests/test_run_flight_jobs_watchdog.py` |
| CIP/PIP (`.cip`) stage 2 decode, either engine | `--s2-jobs` | `tests/test_dmt_parallel.py`, `tests/test_run_flight_dmt_parallel.py` |
| v3.5 stage 3 | `--chunks` | `tests/test_v35_imgproc_merge_chunks.py` (26 tests) |
| v3.5 stage 3 chunk priming, 2D-S/HVPS (vectorised prefix scan) | runs under `--chunks` | `tests/test_v35_sizedist_chunk_priming.py`, `tests/test_v35_prefix_scan_fast.py` (14 tests) |
| v3.5 writer, `position` stored in 1,024-particle blocks (values unchanged, file layout differs) | default, no flag | `tests/test_v35_position_chunking.py` |
| stage 3 under `--chunks`, either engine | `--resume-chunks` | `tests/test_run_flight_chunk_resume.py` |
| v3.5 stage 3 hot kernels | `--jit` (needs numba) | `tests/test_v35_imgproc_jit_identity.py` (12 tests) |
| SODA-2 buffer loop | `--jobs` | `tests/test_soda2_parallel.py` |

The v3.5 engine's `--chunks` admits every probetype, probetype 2 through
prefix-priming, refusing only the `iQC=1` case (the UIOOPS quality-control option). Both measured cells below are CIP: that is the
one square where an engine path and raw data we hold intersect.

**`--jit` on v3.5** (`arrayprobe_uiops.jit_kernels`) reuses proven
`dec2bin_concat` and `particle_perimeter` kernels rather than re-deriving them, and compiles
`calculate_reject_unified`'s two per-slice loops; `cgal_min_r_v35`, the other large cost centre on a
real CIP profile, has no kernel (`arrayprobe_uiops/jit_kernels.py`'s module docstring). Byte-identical on the real production CIP file
(`tests/test_v35_imgproc_jit_identity.py`, 12 tests). Its multipliers — one file, one probe, one
machine, serial only — are in `docs/developer/SPEED.md` with their scope.

## The two measured cells, in full scope — both in the port

Nothing in this section may be quoted without the scope beside it.

| Engine / stage | Probe | Flag | Serial | Parallel | Speedup | Identical? |
|---|---|---|---|---|---|---|
| UIOOPS v3.5, stage 3 (`imgproc`) | CIP (probetype 1) | `--chunks 8` | **269.5 s** | **103.0 s** | **2.5–2.6×** (2.62× here; a repeat read 2.48×; a contended run read 5.57× and is discarded) | all **40** variables byte-equal; every global attribute but `Creation Time` / `Image Source` |
| SODA-2, buffer loop | CIP (SEA) | `--jobs 12` | **413.1 s** | **111.7 s** | **3.70×** | all **35** arrays byte-equal |

| | UIOOPS v3.5 | SODA-2 |
|---|---|---|
| Input | a CIP file converted from SEA format¹, 950 records, 103 MB | `2016_09_06_06_40_17.sea`, 949 buffers |
| Work | 82,028 particles | 81,169 particles |
| Machine | 12 logical cores, otherwise idle | 12 logical cores, otherwise idle |
| Profile | `oracles-production-v3.5` | UND CIP SEA configuration |

¹ The file's name in the measurement record is `sea_s1.CIP.cdf`; the larger file below is `sea_s2.CIP.cdf`.

**A larger file, with no ratio, deliberately.** A 23,939-record CIP file of 3,797,537 particles
completed chunked stage 3 in **1,797.6 s** — 30 minutes. Its serial twin was never run, so a ratio
would be a projection; the run shows only that per-chunk startup amortises on a bigger file.

**A contended measurement is not a measurement.** A SODA-2 re-run of the whole file gave 554.1 s →
201.3 s, **2.75×**, and was discarded: eight foreign worker processes on the same 12-core machine
had inflated the serial side by 34 %. A ratio taken under load is reported, never quoted.

## Whole-flight numbers

No whole-flight figure on the v3.5 engine is quoted
here; the per-stage cells above are what this package has measured.

## Where parallelism is refused — the part to read first

**Refusing beats silently returning a fast wrong answer**, so these are capabilities of the port,
not caveats.

| Case | Status | Reason |
|---|---|---|
| `arrayprobe soda2 run --jobs N` with the 2016 UND emulation, or a substitution with no reconstruction plan | **exits 2** | SODA-2's corrections and the UND emulation work by replacing module globals, and a spawned worker inherits no monkey-patch. Where the substitution cannot be rebuilt by name in the worker, a parallel run would silently drop it, so it is refused instead (`process_2d_parallel.refuse_unsplittable`; also refused: `op.stuckbits`, `op.activetimefrommissed`, more than one raw file) |
| `--chunks` on 2D-S / HVPS / 3VCPI under v3.5, `iQC=1` | **refused** | a prefix scan cannot locate `imgProc_sm.m:850-853`'s width-mismatch return, which only `qc_image` can trigger |
| `--chunks` on 2D-S / HVPS / 3VCPI under v3.5, `iQC=0` | **supported** | `sizeDist.m:1131-1180` accumulates `Time_in_seconds` across the whole file; a **prefix scan** of every earlier record's header (no image unpacked, no `measure_record` call) primes each chunk's seam state exactly, because the two carried scalars come from headers alone. Proven by `np.array_equal` on all 40 variables, byte-equal `Time_in_seconds`, and a one-ULP mutation test. No speed figure is measured — only an 11.8 % prefix-scan cost on a 25-record fixture, an upper bound |
| `--s2-jobs` under v3.5 on a PMS or SEA probe (2DC, 2DP, Fast2DC; CIP from `.sea`) | refused, not built | those readers have no parallel form; the SPEC (2D-S/HVPS) and DMT (`.cip`) decodes do |
| SODA-2 on any SEA probe but CIP | refused by name | only CIP is ported from the SEA format |

### The receipt that makes those refusals credible

A tidier first version of the SODA-2 parallel refactor had the serial loop call the same two halves
as the parallel path. It produced **byte-identical output with every correction and the UND
emulation silently bypassed** — identical to itself, just computed without them. Every byte-identity
test stayed green; five tests in the 714-test SODA-2 family caught it.

**Byte-identity is necessary and not sufficient.** The identity tests are paired with behavioural
suites, and the remaining `--jobs` refusal is built into the command, not left as a warning.

### Why dask was declined

Declined for the port, with a reopening condition. Stage 3 reads per-record scalars, so `dask.array` has nothing to attach to; one stage is up to 92.9 % of a
flight run, which caps what a task graph could reach at roughly 7 %; and cross-chunk state needs a
merge step, which the chunking already implements. **Cost was not the objection** — dask is about 7×
lighter than the numba dependency this project already accepts for `--jit`.

## What has not been measured

The measurement grid in `docs/developer/SPEED.md` crosses every engine against every probe and
every dataset, and scores each cell as measured, testable, no raw data held, or no code route.

| Grid | Cells | Measured | Testable | No raw held | No code route |
|---|---|---|---|---|---|
| Engine × probe | 24 | 2 | 4 | 4 | 14 |
| Dataset × engine·probe | 54 | 2 | 10 | 28 | 14 |

**78 counted cells; two are measured.** Fourteen cells have no code route, twenty-eight have no raw
data held, and ten are run pairs nobody has made — a serial twin on an idle machine is half of
every measurement.

The raw held bounds all of this: one field campaign's 2016 (31 files, 23.8 GB of 2D-S and HVPS) and 2017 (44
files, 35.4 GB) deployments, nine CIP `.sea` files from a single delivery, five 2D-S files from a second campaign, and
nothing for that campaign's 2018 deployment or IMPACTS. The only measured probetype-1 evidence is those nine `.sea`
files, from one campaign and one probe.

## The traps, named so nobody walks into them

Six ways to misread the figures above, each making this package sound better than the
measurements allow.

**1. No figure supports "arrayprobe is N× faster".** Each is one probe, one stage, one file, one
core count. The defensible headline is the mechanism.

**2. Eight chunks is a measured figure, not an optimum.** Ten or twelve may do better on twelve
cores, would change no output byte, and are unmeasured.

**3. Do not rank 2.62× against 3.70×.** Different programs, different input formats, different work
units (950 records against 949 buffers), different stages and different mechanisms — `--chunks`
splits a file, `--jobs` splits a loop. "SODA-2 parallelises better" is not a finding these numbers
support; both are byte-identical.

**4. An empty grid cell is not a slowness claim.** It means no data held or no code route — never
"measured and disappointing". Nothing in this project reports a parallel path that failed to speed
up.

**5. CIP measured is not probetype 1 measured.** PIP shares the probetype and the `--chunks` route,
but its 0.100 mm diode against CIP's 0.025, and 260 mm arm distance against 100, put particles per
record and the chunk-startup amortisation somewhere else entirely. Neither measured row extends to
it.

**6. Probetype 2 on v3.5's `--chunks`** (`iQC=0`, prefix-priming) has three cells testable against
the largest raw holding here, and **no wall-clock number is measured**, so none is quoted.
