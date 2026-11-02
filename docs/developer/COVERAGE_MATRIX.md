# Coverage matrix: probe x engine x mode

**Generated, not hand-maintained.** Every cell below is produced by a development tool from the repository's own facts and checked against a fresh build; this page is not edited by hand.

The package ships two engines, `arrayprobe_uiops` (UIOOPS v3.5, the default) and `arrayprobe_soda2` (SODA-2). An earlier translation of UIOOPS v3.1.4 reproduced archived ORACLES 2D-S/HVPS products and validated this work; it is not part of the package, and its cells are summarised in one note below rather than tabulated.

## Validation depth: three modes, not two

The status vocabulary below reaches only two of them: `runs and validated against an archived product` is layer 1 (an archived product), `runs and cross-checked` is layer 2 (the original MATLAB/IDL executing under Octave/GDL). **A third mode exists and has no column here because it does not run through a probe x engine x mode cell: layer 3, adjudicated by eye** -- a person judging the particle images directly through `arrayprobe.triage_server`, the only admissible evidence where neither an archived product nor the original source exists. It applies where this grid does not: new-campaign processing and any chain-disagreement cell with no product of record. Every citation of it states **n and the labeller** -- the first-flight pass (371 labels) and the hollow-rejection threshold pass (480 labels across 16 cells in two rounds) were both labelled by one person, this project's only labeller to date. It settles what a particle *is*; it does not substitute for layer 1 or layer 2 and is never a pipeline-vs-reference check. Full detail: `docs/04-validation.md`, "Layer 3: adjudicated by eye".

## Status counts

**70 cells** (7 probes x 2 engines x 5 modes).

| Status | Cells |
|---|---|
| runs and validated against an archived product | 0 |
| runs and cross-checked | 49 |
| runs, unvalidated | 0 |
| refuses, deliberately | 0 |
| refuses, not built | 5 |
| refuses, defect | 0 |
| untested | 16 |

**Known-empty, not a gap:** no archived UIOOPS product exists for any CIP, so no CIP cell can ever read `runs and validated against an archived product`; 2018 holds no raw.

**What a `runs and cross-checked` cell does and does not mean for 2DC, 2DP and Fast2DC.** Their cells read cross-checked because the reader is asserted against the original executing under Octave and the stages run. **One real 2DC/2DP raw file is held** (1995, NCAR/EOL's ACE-1 archive, outside the repository) and only its reader has been checked (30 of 30 variables equal to Octave); imgProc and sizeDist have not been run on it in a validated way, and no archived UIOOPS product exists for it. Fast-2DC raw is held locally, UIOOPS has not been run on it, and one real Fast-2DC window is identical between the SODA-2 port and SODA-2's IDL under GDL (`tests/test_soda2_raf_realfile_gdl.py`), but no product of record is held for it -- so nothing in the UIOOPS cells has been validated from a real instrument. The claim is layer 2 on fixtures, which is what it says, and it is worth stating plainly because the count of cross-checked cells rose by nine in one change and a reader could reasonably infer more evidence arrived than did. v3.5's stage 4 (size distribution) runs all four probetypes, probetypes 0 and 3 asserted against an Octave run of the unmodified v3.5 `sizeDist.m` on synthetic fixtures (`tests/test_v35_sizedist_probetype03.py`).

**How to read this table.**

- **VALIDATED** -- the output was compared with an archived product the original code wrote, and every difference is accounted for.
- **CROSS-CHECKED** -- the path runs, and its code is asserted against the original MATLAB/IDL executing under Octave/GDL -- on fixtures, not necessarily on real data from this instrument.
- **unvalidated** -- the path runs, but nothing independent has been compared with its output.
- **refuses (by design)** -- the driver stops with a message, because the combination is meaningless or out of that engine's scope.
- **refused (not built)** -- the driver stops with a message because the code for the combination has not been written; nothing known makes it impossible.
- **REFUSES (DEFECT)** -- the driver stops with a message, but the combination should work and does not yet.
- **untested** -- no test exercises this combination, so nothing is claimed either way.
- `serial` column -- one process, the reference way to run.
- `--chunks` column -- stage 3 (image processing) of each file split across N processes and merged.
- `--jobs` column -- N raw files processed at once, one process each.
- `--s2-jobs` column -- stage 2 (the raw decode) of one large file split across N processes.
- `--jit` column -- stage 3's hottest per-particle kernels compiled with numba.

## arrayprobe_uiops (UIOOPS v3.5, default)

| Probe (probetype) | serial | --chunks | --jobs | --s2-jobs | --jit |
|---|---|---|---|---|---|
| 2DC (0) | CROSS-CHECKED | CROSS-CHECKED | CROSS-CHECKED | refused (not built) | CROSS-CHECKED |
| 2DP (0) | CROSS-CHECKED | CROSS-CHECKED | CROSS-CHECKED | refused (not built) | CROSS-CHECKED |
| CIP (1) | CROSS-CHECKED | CROSS-CHECKED | CROSS-CHECKED | CROSS-CHECKED | CROSS-CHECKED |
| PIP (1) | CROSS-CHECKED | CROSS-CHECKED | CROSS-CHECKED | CROSS-CHECKED | CROSS-CHECKED |
| HVPS (2) | CROSS-CHECKED | CROSS-CHECKED | CROSS-CHECKED | CROSS-CHECKED | CROSS-CHECKED |
| 2DS (2) | CROSS-CHECKED | CROSS-CHECKED | CROSS-CHECKED | CROSS-CHECKED | CROSS-CHECKED |
| Fast2DC (3) | CROSS-CHECKED | CROSS-CHECKED | CROSS-CHECKED | refused (not built) | CROSS-CHECKED |

## arrayprobe_soda2 (SODA-2)

| Probe (probetype) | serial | --chunks | --jobs | --s2-jobs | --jit |
|---|---|---|---|---|---|
| 2DC (0) | untested | untested | untested | untested | untested |
| 2DP (0) | untested | untested | untested | untested | untested |
| CIP (1) | CROSS-CHECKED | CROSS-CHECKED | CROSS-CHECKED | untested | CROSS-CHECKED |
| PIP (1) | CROSS-CHECKED | CROSS-CHECKED | CROSS-CHECKED | untested | CROSS-CHECKED |
| HVPS (2) | CROSS-CHECKED | CROSS-CHECKED | CROSS-CHECKED | untested | CROSS-CHECKED |
| 2DS (2) | CROSS-CHECKED | CROSS-CHECKED | CROSS-CHECKED | untested | CROSS-CHECKED |
| Fast2DC (3) | CROSS-CHECKED | refused (not built) | refused (not built) | untested | untested |

## Earlier v3.1.4 translation (not shipped)

Validated against archived products with an earlier v3.1.4 translation (not shipped): on 2D-S serial it reproduced the ORACLES product of record (the one VALIDATED cell); its HVPS cells and its 2D-S parallel modes were cross-checked byte-identical to serial. It was scoped to ORACLES 2D-S/HVPS data and port validation, so it refused every other probe by design. None of this is selectable in the package.

## Profile coverage

Profile selects reject thresholds and a handful of behaviour switches -- the same fields regardless of which probe is running -- so it is kept as its own table rather than a fourth full axis.

| Profile | Engine | Status |
|---|---|---|
| oracles-2016 | arrayprobe_uiops | refuses (by design) |
| oracles-production | arrayprobe_uiops | refuses (by design) |
| oracles-production-v3.5 | arrayprobe_uiops | CROSS-CHECKED |
| stock-v3.1.4 | arrayprobe_uiops | refuses (by design) |
| stock-v3.5 | arrayprobe_uiops | CROSS-CHECKED |
| (any) | arrayprobe_soda2 | untested |

**Known defect (RESOLVED 2026-09-18):** A REGISTERED (non-shipped) profile x --chunks: a chunk worker is a fresh run_flight.py --_run-chunk process whose PROFILES registry starts with only the shipped profiles, so any profile made with register_profile() -- the documented way to fork -- raised KeyError in every worker within ~2s, before a single record is written. RESOLVED 2026-09-18 (adecdb1) by refusing before the spawn: stage3 raises ProfileNotReachableInChunkWorkers, naming profile_module, when a non-shipped profile is used without it. Set [fidelity].profile_module and --chunks works. Subprocess-tested in tests/test_run_flight_chunks_registered_profile.py.

## Cells classified `refuses, defect`

Every cell in this status is a real finding of this sweep -- a refusal the project's own records call unfinished rather than intended.

(none)

## Reasons, by cell

Grouped by engine and probe; `untested` cells are omitted here (the table above already says so) except where the reason states a specific negative finding.

### arrayprobe_uiops (UIOOPS v3.5, default)

- **2DC / serial** -- _CROSS-CHECKED_: v3.5's own probetype-2 timing block is asserted against Octave goldens of the v3.5 MATLAB sources themselves -- not against the archived v3.1.4-era product, which v3.5 does not attempt to reproduce byte-for-byte; archived-product validation was done with an earlier v3.1.4 translation (not shipped).
- **2DC / --chunks** -- _CROSS-CHECKED_: 2DC timing 'pms' is in CHUNKABLE_TIMINGS_V35: its written values are record-local, and the chunked stage-3 files of the v3.5 engine are asserted byte-identical to a serial run for 2DC (test_2dc_probetype_0, on a tracked Octave-decoded fixture).
- **2DC / --jobs** -- _CROSS-CHECKED_: --jobs forwarding to per-file workers under --engine 3.5 is asserted to forward to per-file workers; each worker runs the ordinary serial per-file v3.5 pipeline.
- **2DC / --s2-jobs** -- _refused (not built)_: stage2 refuses --s2-jobs > 1 for 2DC (probetype 0), under either engine: its raw reader has no parallel form. Nothing known makes one impossible; the reader's carried state has not been assessed.
- **2DC / --jit** -- _CROSS-CHECKED_: arrayprobe_uiops.jit_kernels uses S3 kernels (particle_perimeter, dec2bin_concat) proven byte-identical in the earlier v3.1.4 translation (not shipped), from imgproc_sm_v35's own call sites; test_v35_imgproc_jit_identity.py asserts jit=True writes the same bytes as jit=False on a real production CIP file, including the [EXPERIMENTAL] hollow-override path (measure.py:1218-1236) that jit_kernels does not itself accelerate.
- **2DP / serial** -- _CROSS-CHECKED_: v3.5's own probetype-2 timing block is asserted against Octave goldens of the v3.5 MATLAB sources themselves -- not against the archived v3.1.4-era product, which v3.5 does not attempt to reproduce byte-for-byte; archived-product validation was done with an earlier v3.1.4 translation (not shipped).
- **2DP / --chunks** -- _CROSS-CHECKED_: 2DP timing 'pms' is in CHUNKABLE_TIMINGS_V35: its written values are record-local, and the chunked stage-3 files of the v3.5 engine are asserted byte-identical to a serial run for 2DP (test_2dp_probetype_0, on a tracked Octave-decoded fixture).
- **2DP / --jobs** -- _CROSS-CHECKED_: --jobs forwarding to per-file workers under --engine 3.5 is asserted to forward to per-file workers; each worker runs the ordinary serial per-file v3.5 pipeline.
- **2DP / --s2-jobs** -- _refused (not built)_: stage2 refuses --s2-jobs > 1 for 2DP (probetype 0), under either engine: its raw reader has no parallel form. Nothing known makes one impossible; the reader's carried state has not been assessed.
- **2DP / --jit** -- _CROSS-CHECKED_: arrayprobe_uiops.jit_kernels uses S3 kernels (particle_perimeter, dec2bin_concat) proven byte-identical in the earlier v3.1.4 translation (not shipped), from imgproc_sm_v35's own call sites; test_v35_imgproc_jit_identity.py asserts jit=True writes the same bytes as jit=False on a real production CIP file, including the [EXPERIMENTAL] hollow-override path (measure.py:1218-1236) that jit_kernels does not itself accelerate.
- **CIP / serial** -- _CROSS-CHECKED_: v3.5's own probetype-2 timing block is asserted against Octave goldens of the v3.5 MATLAB sources themselves -- not against the archived v3.1.4-era product, which v3.5 does not attempt to reproduce byte-for-byte; archived-product validation was done with an earlier v3.1.4 translation (not shipped).
- **CIP / --chunks** -- _CROSS-CHECKED_: CIP timing 'dmt' is in CHUNKABLE_TIMINGS_V35: its written values are record-local, and the chunked stage-3 files of the v3.5 engine are asserted byte-identical to a serial run for CIP (test_five_uneven_chunks_match_single_chunk, on a tracked Octave-decoded fixture).
- **CIP / --jobs** -- _CROSS-CHECKED_: --jobs forwarding to per-file workers under --engine 3.5 is asserted to forward to per-file workers; each worker runs the ordinary serial per-file v3.5 pipeline.
- **CIP / --s2-jobs** -- _CROSS-CHECKED_: arrayprobe.readers.dmt.read_binary_DMT_parallel splits the .cip file on 4112-byte record boundaries and re-appends the parts through the one serial writer; its output is asserted byte-identical to read_binary_DMT on every split of the twelve-record fixture, on truncated tails, on a failing record, on a synthetic 620-record file with seams at 255/256/257, and through the driver's own stage 2 (including the serial fallback on a dead pool).
- **CIP / --jit** -- _CROSS-CHECKED_: arrayprobe_uiops.jit_kernels uses S3 kernels (particle_perimeter, dec2bin_concat) proven byte-identical in the earlier v3.1.4 translation (not shipped), from imgproc_sm_v35's own call sites; test_v35_imgproc_jit_identity.py asserts jit=True writes the same bytes as jit=False on a real production CIP file, including the [EXPERIMENTAL] hollow-override path (measure.py:1218-1236) that jit_kernels does not itself accelerate.
- **PIP / serial** -- _CROSS-CHECKED_: v3.5's own probetype-2 timing block is asserted against Octave goldens of the v3.5 MATLAB sources themselves -- not against the archived v3.1.4-era product, which v3.5 does not attempt to reproduce byte-for-byte; archived-product validation was done with an earlier v3.1.4 translation (not shipped).
- **PIP / --chunks** -- _CROSS-CHECKED_: PIP timing 'dmt' is in CHUNKABLE_TIMINGS_V35: its written values are record-local, and the chunked stage-3 files of the v3.5 engine are asserted byte-identical to a serial run for PIP (test_pip_shares_the_branch_and_matches_too, on a tracked Octave-decoded fixture).
- **PIP / --jobs** -- _CROSS-CHECKED_: --jobs forwarding to per-file workers under --engine 3.5 is asserted to forward to per-file workers; each worker runs the ordinary serial per-file v3.5 pipeline.
- **PIP / --s2-jobs** -- _CROSS-CHECKED_: arrayprobe.readers.dmt.read_binary_DMT_parallel splits the .cip file on 4112-byte record boundaries and re-appends the parts through the one serial writer; its output is asserted byte-identical to read_binary_DMT on every split of the twelve-record fixture, on truncated tails, on a failing record, on a synthetic 620-record file with seams at 255/256/257, and through the driver's own stage 2 (including the serial fallback on a dead pool).
- **PIP / --jit** -- _CROSS-CHECKED_: arrayprobe_uiops.jit_kernels uses S3 kernels (particle_perimeter, dec2bin_concat) proven byte-identical in the earlier v3.1.4 translation (not shipped), from imgproc_sm_v35's own call sites; test_v35_imgproc_jit_identity.py asserts jit=True writes the same bytes as jit=False on a real production CIP file, including the [EXPERIMENTAL] hollow-override path (measure.py:1218-1236) that jit_kernels does not itself accelerate.
- **HVPS / serial** -- _CROSS-CHECKED_: v3.5's own probetype-2 timing block is asserted against Octave goldens of the v3.5 MATLAB sources themselves -- not against the archived v3.1.4-era product, which v3.5 does not attempt to reproduce byte-for-byte; archived-product validation was done with an earlier v3.1.4 translation (not shipped).
- **HVPS / --chunks** -- _CROSS-CHECKED_: HVPS is v3.5 timing 'spec', in PRIMABLE_TIMINGS_V35 = ['spec']: chunk_primes_v35 computes each seam's (part_time_prev, time_in_seconds_prev) pair in one prefix pass over the file, and imgproc_sm_v35(prime=...) resumes each worker from it. Primed chunks are asserted byte-identical to a serial run -- all variables, Time_in_seconds compared as bytes, a one-ULP mutation of the prime detected -- both in-process and through a real run_flight.py --_run-chunk subprocess round trip, with an unprimed control confirmed to disagree (confined to Time_in_seconds/int_arrival). Refused only when iQC=1 -- deliberate, not a defect.
- **HVPS / --jobs** -- _CROSS-CHECKED_: --jobs forwarding to per-file workers under --engine 3.5 is asserted to forward to per-file workers; each worker runs the ordinary serial per-file v3.5 pipeline.
- **HVPS / --s2-jobs** -- _CROSS-CHECKED_: arrayprobe_uiops.spec.read_binary_spec_v35_parallel primes each part with the running airspeed the serial loop carries into it and checks every seam by bit pattern; whole-file digests of the NETCDF4 outputs and the sidecars are asserted equal to the serial decode, on every split of the ten-record fixture and on a synthetic file with seams on the hard cases, and through the driver's own stage 2.
- **HVPS / --jit** -- _CROSS-CHECKED_: arrayprobe_uiops.jit_kernels uses S3 kernels (particle_perimeter, dec2bin_concat) proven byte-identical in the earlier v3.1.4 translation (not shipped), from imgproc_sm_v35's own call sites; test_v35_imgproc_jit_identity.py asserts jit=True writes the same bytes as jit=False on a real production CIP file, including the [EXPERIMENTAL] hollow-override path (measure.py:1218-1236) that jit_kernels does not itself accelerate.
- **2DS / serial** -- _CROSS-CHECKED_: v3.5's own probetype-2 timing block is asserted against Octave goldens of the v3.5 MATLAB sources themselves -- not against the archived v3.1.4-era product, which v3.5 does not attempt to reproduce byte-for-byte; archived-product validation was done with an earlier v3.1.4 translation (not shipped).
- **2DS / --chunks** -- _CROSS-CHECKED_: 2DS is v3.5 timing 'spec', in PRIMABLE_TIMINGS_V35 = ['spec']: chunk_primes_v35 computes each seam's (part_time_prev, time_in_seconds_prev) pair in one prefix pass over the file, and imgproc_sm_v35(prime=...) resumes each worker from it. Primed chunks are asserted byte-identical to a serial run -- all variables, Time_in_seconds compared as bytes, a one-ULP mutation of the prime detected -- both in-process and through a real run_flight.py --_run-chunk subprocess round trip, with an unprimed control confirmed to disagree (confined to Time_in_seconds/int_arrival). Refused only when iQC=1 -- deliberate, not a defect.
- **2DS / --jobs** -- _CROSS-CHECKED_: --jobs forwarding to per-file workers under --engine 3.5 is asserted to forward to per-file workers; each worker runs the ordinary serial per-file v3.5 pipeline.
- **2DS / --s2-jobs** -- _CROSS-CHECKED_: arrayprobe_uiops.spec.read_binary_spec_v35_parallel primes each part with the running airspeed the serial loop carries into it and checks every seam by bit pattern; whole-file digests of the NETCDF4 outputs and the sidecars are asserted equal to the serial decode, on every split of the ten-record fixture and on a synthetic file with seams on the hard cases, and through the driver's own stage 2.
- **2DS / --jit** -- _CROSS-CHECKED_: arrayprobe_uiops.jit_kernels uses S3 kernels (particle_perimeter, dec2bin_concat) proven byte-identical in the earlier v3.1.4 translation (not shipped), from imgproc_sm_v35's own call sites; test_v35_imgproc_jit_identity.py asserts jit=True writes the same bytes as jit=False on a real production CIP file, including the [EXPERIMENTAL] hollow-override path (measure.py:1218-1236) that jit_kernels does not itself accelerate.
- **Fast2DC / serial** -- _CROSS-CHECKED_: v3.5's own probetype-2 timing block is asserted against Octave goldens of the v3.5 MATLAB sources themselves -- not against the archived v3.1.4-era product, which v3.5 does not attempt to reproduce byte-for-byte; archived-product validation was done with an earlier v3.1.4 translation (not shipped).
- **Fast2DC / --chunks** -- _CROSS-CHECKED_: Fast2DC timing 'fast2dc' is in CHUNKABLE_TIMINGS_V35: its written values are record-local, and the chunked stage-3 files of the v3.5 engine are asserted byte-identical to a serial run for Fast2DC (test_fast2dc_probetype_3, on a tracked Octave-decoded fixture).
- **Fast2DC / --jobs** -- _CROSS-CHECKED_: --jobs forwarding to per-file workers under --engine 3.5 is asserted to forward to per-file workers; each worker runs the ordinary serial per-file v3.5 pipeline.
- **Fast2DC / --s2-jobs** -- _refused (not built)_: stage2 refuses --s2-jobs > 1 for Fast2DC (probetype 3), under either engine: its raw reader has no parallel form. Nothing known makes one impossible; the reader's carried state has not been assessed.
- **Fast2DC / --jit** -- _CROSS-CHECKED_: arrayprobe_uiops.jit_kernels uses S3 kernels (particle_perimeter, dec2bin_concat) proven byte-identical in the earlier v3.1.4 translation (not shipped), from imgproc_sm_v35's own call sites; test_v35_imgproc_jit_identity.py asserts jit=True writes the same bytes as jit=False on a real production CIP file, including the [EXPERIMENTAL] hollow-override path (measure.py:1218-1236) that jit_kernels does not itself accelerate.

### arrayprobe_soda2 (SODA-2)

- **2DC / serial** -- _untested_: particlesort.py branches on probetype=='2DC' in one place, but this sweep found no run or test establishing an end-to-end 2DC decode through arrayprobe_soda2.
- **2DC / --chunks** -- _untested_: --chunks is a split-balance knob for --jobs (cli.py: read only when --jobs > 1, how many contiguous buffer ranges each job's own loop is split into), not a resumable chunk-shaped parallel mode -- so its status follows --jobs, on the same evidence: serial itself is untested/refused for this probe; no basis to claim more for --jobs.
- **2DC / --jobs** -- _untested_: serial itself is untested/refused for this probe; no basis to claim more for --jobs.
- **2DC / --s2-jobs** -- _untested_: --s2-jobs names run_flight.py's SPEC S2-decode parallel knob specifically; arrayprobe_soda2 exposes no flag by this name and splits work with its own --jobs/--chunks pair instead.
- **2DC / --jit** -- _untested_: arrayprobe_soda2.jit_kernels exists and is proven byte-identical for the runnable 2D-S/HVPS/CIP path (test_soda2_jit_product_identity.py), but serial itself is untested/refused for this probe, so there is no run here to accelerate.
- **2DP / serial** -- _untested_: arrayprobe_soda2/probespecs.py names 2DP among its own probe entries, but this sweep found no probetype dispatch or test that runs a 2DP decode through arrayprobe_soda2 end to end.
- **2DP / --chunks** -- _untested_: --chunks is a split-balance knob for --jobs (cli.py: read only when --jobs > 1, how many contiguous buffer ranges each job's own loop is split into), not a resumable chunk-shaped parallel mode -- so its status follows --jobs, on the same evidence: serial itself is untested/refused for this probe; no basis to claim more for --jobs.
- **2DP / --jobs** -- _untested_: serial itself is untested/refused for this probe; no basis to claim more for --jobs.
- **2DP / --s2-jobs** -- _untested_: --s2-jobs names run_flight.py's SPEC S2-decode parallel knob specifically; arrayprobe_soda2 exposes no flag by this name and splits work with its own --jobs/--chunks pair instead.
- **2DP / --jit** -- _untested_: arrayprobe_soda2.jit_kernels exists and is proven byte-identical for the runnable 2D-S/HVPS/CIP path (test_soda2_jit_product_identity.py), but serial itself is untested/refused for this probe, so there is no run here to accelerate.
- **CIP / serial** -- _CROSS-CHECKED_: The SEA/DMT CIP path (CIP-1) runs end to end on real UND 2016 data and is validated against the original IDL SODA-2 under GDL.
- **CIP / --chunks** -- _CROSS-CHECKED_: --chunks is a split-balance knob for --jobs (cli.py: read only when --jobs > 1, how many contiguous buffer ranges each job's own loop is split into), not a resumable chunk-shaped parallel mode -- so its status follows --jobs, on the same evidence: process_2d_parallel.py's ProcessPoolExecutor split of the buffer loop is asserted byte-identical to the serial SODA-2 path -- every ProcessData field compared with np.array_equal (never allclose), plus the written .pbp.csv/.pbp.nc files -- and stays byte-identical with the correction package composed in (tests/test_soda2_parallel_enhancements.py).
- **CIP / --jobs** -- _CROSS-CHECKED_: process_2d_parallel.py's ProcessPoolExecutor split of the buffer loop is asserted byte-identical to the serial SODA-2 path -- every ProcessData field compared with np.array_equal (never allclose), plus the written .pbp.csv/.pbp.nc files -- and stays byte-identical with the correction package composed in (tests/test_soda2_parallel_enhancements.py).
- **CIP / --s2-jobs** -- _untested_: --s2-jobs names run_flight.py's SPEC S2-decode parallel knob specifically; arrayprobe_soda2 exposes no flag by this name and splits work with its own --jobs/--chunks pair instead.
- **CIP / --jit** -- _CROSS-CHECKED_: arrayprobe_soda2.jit_kernels routes label_blobs's flood fill (and fillholes' own call to it) through numba; the written PBP is asserted byte-identical on/off (test_soda2_jit_product_identity.py's JitProductIdenticalSpec/JitProductIdenticalCip, the written product, not just the kernel's own array).
- **PIP / serial** -- _CROSS-CHECKED_: PIP data arrive in DMT (PADS/PACS) format; soda2_update_op.pro:49 rewrites probetype 'PIP' to 'CIP', and the DMT path through particlesort matches the original under Windows GDL bit for bit in every field (cloud pass 6, landed 2026-09-27).
- **PIP / --chunks** -- _CROSS-CHECKED_: --chunks is a split-balance knob for --jobs (cli.py: read only when --jobs > 1, how many contiguous buffer ranges each job's own loop is split into), not a resumable chunk-shaped parallel mode -- so its status follows --jobs, on the same evidence: process_2d_parallel.py's ProcessPoolExecutor split of the buffer loop is asserted byte-identical to the serial SODA-2 path -- every ProcessData field compared with np.array_equal (never allclose), plus the written .pbp.csv/.pbp.nc files -- and stays byte-identical with the correction package composed in (tests/test_soda2_parallel_enhancements.py).
- **PIP / --jobs** -- _CROSS-CHECKED_: process_2d_parallel.py's ProcessPoolExecutor split of the buffer loop is asserted byte-identical to the serial SODA-2 path -- every ProcessData field compared with np.array_equal (never allclose), plus the written .pbp.csv/.pbp.nc files -- and stays byte-identical with the correction package composed in (tests/test_soda2_parallel_enhancements.py).
- **PIP / --s2-jobs** -- _untested_: --s2-jobs names run_flight.py's SPEC S2-decode parallel knob specifically; arrayprobe_soda2 exposes no flag by this name and splits work with its own --jobs/--chunks pair instead.
- **PIP / --jit** -- _CROSS-CHECKED_: arrayprobe_soda2.jit_kernels routes label_blobs's flood fill (and fillholes' own call to it) through numba; the written PBP is asserted byte-identical on/off (test_soda2_jit_product_identity.py's JitProductIdenticalSpec/JitProductIdenticalCip, the written product, not just the kernel's own array).
- **HVPS / serial** -- _CROSS-CHECKED_: Same processbuffer_spec.py branch, keyed on soda2's own 'HVPS3'/'HVPS4' probetype strings rather than a bare 'HVPS'.
- **HVPS / --chunks** -- _CROSS-CHECKED_: --chunks is a split-balance knob for --jobs (cli.py: read only when --jobs > 1, how many contiguous buffer ranges each job's own loop is split into), not a resumable chunk-shaped parallel mode -- so its status follows --jobs, on the same evidence: process_2d_parallel.py's ProcessPoolExecutor split of the buffer loop is asserted byte-identical to the serial SODA-2 path -- every ProcessData field compared with np.array_equal (never allclose), plus the written .pbp.csv/.pbp.nc files -- and stays byte-identical with the correction package composed in (tests/test_soda2_parallel_enhancements.py).
- **HVPS / --jobs** -- _CROSS-CHECKED_: process_2d_parallel.py's ProcessPoolExecutor split of the buffer loop is asserted byte-identical to the serial SODA-2 path -- every ProcessData field compared with np.array_equal (never allclose), plus the written .pbp.csv/.pbp.nc files -- and stays byte-identical with the correction package composed in (tests/test_soda2_parallel_enhancements.py).
- **HVPS / --s2-jobs** -- _untested_: --s2-jobs names run_flight.py's SPEC S2-decode parallel knob specifically; arrayprobe_soda2 exposes no flag by this name and splits work with its own --jobs/--chunks pair instead.
- **HVPS / --jit** -- _CROSS-CHECKED_: arrayprobe_soda2.jit_kernels routes label_blobs's flood fill (and fillholes' own call to it) through numba; the written PBP is asserted byte-identical on/off (test_soda2_jit_product_identity.py's JitProductIdenticalSpec/JitProductIdenticalCip, the written product, not just the kernel's own array).
- **2DS / serial** -- _CROSS-CHECKED_: processbuffer_spec.py ports the CASE branch for probetype in {'HVPS3','2DS','HVPS4','3VCPI'}; decode asserted against synthetic + real-file GDL oracle runs.
- **2DS / --chunks** -- _CROSS-CHECKED_: --chunks is a split-balance knob for --jobs (cli.py: read only when --jobs > 1, how many contiguous buffer ranges each job's own loop is split into), not a resumable chunk-shaped parallel mode -- so its status follows --jobs, on the same evidence: process_2d_parallel.py's ProcessPoolExecutor split of the buffer loop is asserted byte-identical to the serial SODA-2 path -- every ProcessData field compared with np.array_equal (never allclose), plus the written .pbp.csv/.pbp.nc files -- and stays byte-identical with the correction package composed in (tests/test_soda2_parallel_enhancements.py).
- **2DS / --jobs** -- _CROSS-CHECKED_: process_2d_parallel.py's ProcessPoolExecutor split of the buffer loop is asserted byte-identical to the serial SODA-2 path -- every ProcessData field compared with np.array_equal (never allclose), plus the written .pbp.csv/.pbp.nc files -- and stays byte-identical with the correction package composed in (tests/test_soda2_parallel_enhancements.py).
- **2DS / --s2-jobs** -- _untested_: --s2-jobs names run_flight.py's SPEC S2-decode parallel knob specifically; arrayprobe_soda2 exposes no flag by this name and splits work with its own --jobs/--chunks pair instead.
- **2DS / --jit** -- _CROSS-CHECKED_: arrayprobe_soda2.jit_kernels routes label_blobs's flood fill (and fillholes' own call to it) through numba; the written PBP is asserted byte-identical on/off (test_soda2_jit_product_identity.py's JitProductIdenticalSpec/JitProductIdenticalCip, the written product, not just the kernel's own array).
- **Fast2DC / serial** -- _CROSS-CHECKED_: RAF format, probetype F2DC_v2: the RAF reader (soda2_read2dbuffer.pro:19-66) and the Fast-2DC buffer processing (soda2_processbuffer.pro:28-78) are ported; the buffer step matches the original IDL under GDL on 10 of 10 synthetic buffers, and on a real file (CAESAR 2024 rf05, probe C4, 35480-35540 s) the serial driver's output is identical to soda2_process_2d.pro run under GDL in all eight fields (TIME, TAS, SPEC2D, COUNT_ACCEPTED, ACTIVETIME, INTSPEC_ALL, COUNT_MISSED, MISSED_HIST). That is SODA-2's own code, not an archived product. HVPS1 and F2DC66 over RAF are refused by name (soda2_processbuffer.pro:22-127).
- **Fast2DC / --chunks** -- _refused (not built)_: --chunks is read only when --jobs > 1, and RAF Fast-2DC refuses --jobs > 1 (soda2_process_2d.pro:39, the f2d_remainder carry).
- **Fast2DC / --jobs** -- _refused (not built)_: RAF Fast-2DC with --jobs > 1 is refused by name: the f2d_remainder carry crosses buffer-range boundaries (soda2_process_2d.pro:39); run --jobs 1.
- **Fast2DC / --s2-jobs** -- _untested_: --s2-jobs names run_flight.py's SPEC S2-decode parallel knob specifically; arrayprobe_soda2 exposes no flag by this name and splits work with its own --jobs/--chunks pair instead.
- **Fast2DC / --jit** -- _untested_: arrayprobe_soda2.jit_kernels is proven byte-identical for the 2D-S/HVPS/CIP path; no test runs a RAF Fast-2DC file with --jit on and off.

### Earlier v3.1.4 translation (not shipped)

Its refusals covered every probe other than 2D-S and HVPS, by design: it was scoped to ORACLES 2D-S/HVPS validation and port validation. CIP and the other probes are processed with engine 3.5 and SODA-2. Its 2D-S and HVPS `--chunks` cells were cross-checked byte-identical to the serial merge.
