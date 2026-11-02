# PIP

DMT PIP. Same probetype, reader and timing family as the CIP, four times coarser. Runs under both UIOOPS engines and the SODA-2 port's DMT path.

## The instrument, as the code sees it

Every row below is read from `constants.IMGPROC_CONFIG`, the port of `imgProc_sm.m`'s own probe switch. None of it is typed into this page.

| | |
|---|---|
| probetype | 1 |
| diodes | 64 |
| diode resolution (`ds`) | 100 um |
| array reach | **6.4 mm** (64 x 100 um) |
| timing family | `dmt` |
| needs a TAS file | no |
| Stage-2 reader | `arrayprobe.readers.dmt.read_binary_DMT` |
| image word | 8-bit, not inverted |

## What runs today

Imported from the coverage matrix rather than restated, so this table and `docs/developer/COVERAGE_MATRIX.md` cannot disagree.

| Engine | serial | --chunks | --jobs | --s2-jobs | --jit |
|---|---|---|---|---|---|
| `arrayprobe_uiops` | CROSS-CHECKED | CROSS-CHECKED | CROSS-CHECKED | CROSS-CHECKED | CROSS-CHECKED |
| `arrayprobe_soda2` | CROSS-CHECKED | CROSS-CHECKED | CROSS-CHECKED | untested | CROSS-CHECKED |

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
- `arrayprobe_uiops` -- the UIOOPS v3.5 port, the default for new work.
- `arrayprobe_soda2` -- the SODA-2 port.

No shipped preset names this probe. A run needs a campaign preset declared in your own TOML (`[run].presets`), and `[run].preset` is required -- it has no default.

Where a cell above reads `refuses (by design)` or `REFUSES (DEFECT)`, the reason is in `docs/developer/COVERAGE_MATRIX.md` for that exact cell. A refusal here is always preferred to a silently wrong fast answer, and the two words are different: *by design* means the combination is meaningless, *defect* means it should work and does not yet.

## Caveats

### Consequences of this probe's own geometry

Computed from the table above, not recalled -- each says which arithmetic produced it.

**The hollow test only packs diodes 1-32, and this array has 64**

`calculate_reject_unified.m:465` packs diodes 1-32 whatever the probe's width. This probe is 64 diodes wide, so a particle imaged entirely beyond diode 32 gives the test two zero operands and is ruled hollow on no evidence. That verdict reaches `auto_reject` AND the Korolev correction, so it moves both acceptance and recorded size. Preserved deliberately; `wide_hollow_fix` in `enhancements_uiops/` is the opt-in, default-off alternative, and v3.5's own rewrite is a DIFFERENT correction from ours (it also drops the middle-third scan restriction -- 745 of 1,080 random particles disagree).

*Computed from:* `constants.IMGPROC_CONFIG['PIP'].diodenum = 64`

**The array images 6.4 mm, and a size ladder must respect that**

64 diodes at 0.1 mm is 6.4 mm across. **That is not a hard ceiling on recorded size**, and it would be an overclaim to say so: a particle that merely has its centre in the array (`sa_method` 0) or is sized through the Heymsfield & Parrish reconstruction (`sa_method` 2) can be recorded LARGER than the array it crossed. The bound that survives is a factor, not an equality -- a centre-in particle reaches about twice the array width, not twenty times it. So the honest reading is: a bin above roughly 12.8 mm on this probe is beyond what any sizing convention here produces, and a ladder whose top lies there is a configuration error rather than a sparse flight. The upstream finding that the default 2D-S bin table became the HVPS one (recorded in the review of the upstream code) is exactly that: a 30 mm ladder handed to a 1.28 mm array, 23x its width, and the symptom was a well-formed file with almost nothing in it.

*Computed from:* `constants.IMGPROC_CONFIG['PIP']: diodenum 64 x ds 0.1 mm = 6.4 mm`

**Chunked stage 3: supported**

Timing family `dmt` is in `CHUNKABLE_TIMINGS_V35`, so `--chunks` splits stage 3 with no carried state and the result is byte-identical to a serial run.

*Computed from:* `constants.IMGPROC_CONFIG['PIP'].timing = 'dmt'; CHUNKABLE_TIMINGS_V35 = ('dmt', 'pms', 'fast2dc'); PRIMABLE_TIMINGS_V35 = ('spec',)`

### What a person knows and a constant does not

Curated in `probe_caveats.json` (in `scripts/`). Every citation is re-checked against the real file each time this page is generated.

**The SODA-2 engine reads the PIP through its DMT path, checked on a synthetic file only**

PIP data arrive in DMT (PADS/PACS) format; SODA-2 rewrites probetype PIP to CIP (soda2_update_op.pro:49) and the port follows it, matching the original under GDL bit for bit on a synthetic 12-record fixture. No real PIP recording has been run through it here.

*Source:* `docs/developer/COVERAGE_MATRIX.md`

**Reject code 't' is never emitted, on any probe**

calculate_reject_unified.m:269 rejects on the tighter threshold (max_comp_img_ar) before :272 tests the looser one (max_edge_img_ar), so the second branch is unreachable and image_auto_reject never contains 116. The netCDF Description attribute at imgProc_sm.m:325-329 states the two thresholds the other way round. Both are preserved verbatim -- this is a faithfully reproduced upstream defect, not a port bug. If you are tabulating reject codes, 't' is structurally absent rather than merely rare.

**Trust the .call sidecar, not the filename**

Every stage stamps its configuration into a .call sidecar and refuses an input that disagrees or carries no stamp. If you write products with your own script instead of `arrayprobe run`, you inherit this problem.

## Ratios this probe appears in

None. No ratio measured so far has this probe on either side -- which follows from the data held: a ratio needs two chains over the same raw, and there is no raw here to run two chains over.

## Where to go next

| | |
|---|---|
| Every probe x engine x mode cell, with its reason | `docs/developer/COVERAGE_MATRIX.md` |
| Which engine to use | `docs/developer/TWO_ENGINES.md` |
| The airspeed chain, which sets the sample volume | `docs/developer/TAS.md` |
| How the upstream code was reviewed, and what was found | `docs/developer/UPSTREAM_REVIEW.md` |
| All seven probes at a glance | [The seven probes](33-probes.md) |

**Generated, not hand-maintained,** from `arrayprobe.constants.IMGPROC_CONFIG`, `coverage_matrix.build_matrix()` and the curated caveats in `probe_caveats.json`.

