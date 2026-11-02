# CIP

DMT CIP, read out of SEA records. The probe the SODA-2 port was validated on, and the one where the two packages can be compared end to end on the same raw. No archived UIOOPS product exists for any CIP anywhere, so no CIP result can ever be layer-1 validated -- that is a known-empty cell, not a gap to fill.

## The instrument, as the code sees it

Every row below is read from `constants.IMGPROC_CONFIG`, the port of `imgProc_sm.m`'s own probe switch. None of it is typed into this page.

| | |
|---|---|
| probetype | 1 |
| diodes | 64 |
| diode resolution (`ds`) | 25 um |
| array reach | **1.6 mm** (64 x 25 um) |
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

**Shipped presets naming this probe:** `UND_2016_CIP`.

Run with `arrayprobe run <config.toml>`, where the config holds:

```toml
[fidelity]
profile = "stock-v3.5"

[run]
engine = "3.5"
preset = "UND_2016_CIP"
raw = ["<raw files>"]
stages = "234"
```

`[run].engine` is required: `"3.5"` for new work.

Where a cell above reads `refuses (by design)` or `REFUSES (DEFECT)`, the reason is in `docs/developer/COVERAGE_MATRIX.md` for that exact cell. A refusal here is always preferred to a silently wrong fast answer, and the two words are different: *by design* means the combination is meaningless, *defect* means it should work and does not yet.

## Caveats

### Consequences of this probe's own geometry

Computed from the table above, not recalled -- each says which arithmetic produced it.

**The hollow test only packs diodes 1-32, and this array has 64**

`calculate_reject_unified.m:465` packs diodes 1-32 whatever the probe's width. This probe is 64 diodes wide, so a particle imaged entirely beyond diode 32 gives the test two zero operands and is ruled hollow on no evidence. That verdict reaches `auto_reject` AND the Korolev correction, so it moves both acceptance and recorded size. Preserved deliberately; `wide_hollow_fix` in `enhancements_uiops/` is the opt-in, default-off alternative, and v3.5's own rewrite is a DIFFERENT correction from ours (it also drops the middle-third scan restriction -- 745 of 1,080 random particles disagree).

*Computed from:* `constants.IMGPROC_CONFIG['CIP'].diodenum = 64`

**The array images 1.6 mm, and a size ladder must respect that**

64 diodes at 0.025 mm is 1.6 mm across. **That is not a hard ceiling on recorded size**, and it would be an overclaim to say so: a particle that merely has its centre in the array (`sa_method` 0) or is sized through the Heymsfield & Parrish reconstruction (`sa_method` 2) can be recorded LARGER than the array it crossed. The bound that survives is a factor, not an equality -- a centre-in particle reaches about twice the array width, not twenty times it. So the honest reading is: a bin above roughly 3.2 mm on this probe is beyond what any sizing convention here produces, and a ladder whose top lies there is a configuration error rather than a sparse flight. The upstream finding that the default 2D-S bin table became the HVPS one (recorded in the review of the upstream code) is exactly that: a 30 mm ladder handed to a 1.28 mm array, 23x its width, and the symptom was a well-formed file with almost nothing in it.

*Computed from:* `constants.IMGPROC_CONFIG['CIP']: diodenum 64 x ds 0.025 mm = 1.6 mm`

**Chunked stage 3: supported**

Timing family `dmt` is in `CHUNKABLE_TIMINGS_V35`, so `--chunks` splits stage 3 with no carried state and the result is byte-identical to a serial run.

*Computed from:* `constants.IMGPROC_CONFIG['CIP'].timing = 'dmt'; CHUNKABLE_TIMINGS_V35 = ('dmt', 'pms', 'fast2dc'); PRIMABLE_TIMINGS_V35 = ('spec',)`

### What a person knows and a constant does not

Curated in `probe_caveats.json` (in `scripts/`). Every citation is re-checked against the real file each time this page is generated.

**No CIP can ever be validated against an archived product**

This project holds no archived UIOOPS product for any CIP, and none is known to exist. A CIP run can be cross-checked (against the original IDL SODA-2 under GDL, or against UND's delivery) and never validated in the layer-1 sense. The coverage matrix marks this known-empty rather than untested, so nobody spends a week trying to close it.

*Source:* `docs/developer/COVERAGE_MATRIX.md`

**347 impossible particle_time values, cause not established**

The 2016-09-06 CIP carries 347 particle_time values with mm or ss > 59. One proposed explanation, a misaligned SEA record byte grid, is ruled out: measured with the reader's own record-boundary lock, particles per record is flat across all eight sync-byte residues, nothing like the ~300x spread that explanation needs. The cause is unknown.

**The CIP-vs-2D-S ladder is a compound effect, not a count effect**

36,639 of 3,797,537 particles (0.97%) disagree on recorded DIAMETER between the stock and image-assisted arms, because the Korolev correction rewrites size. A bin's ratio can therefore move with no particle changing verdict. Count effects and sizing effects are not separated in those numbers.

**Reject code 't' is never emitted, on any probe**

calculate_reject_unified.m:269 rejects on the tighter threshold (max_comp_img_ar) before :272 tests the looser one (max_edge_img_ar), so the second branch is unreachable and image_auto_reject never contains 116. The netCDF Description attribute at imgProc_sm.m:325-329 states the two thresholds the other way round. Both are preserved verbatim -- this is a faithfully reproduced upstream defect, not a port bug. If you are tabulating reject codes, 't' is structurally absent rather than merely rare.

**Trust the .call sidecar, not the filename**

Every stage stamps its configuration into a .call sidecar and refuses an input that disagrees or carries no stamp. If you write products with your own script instead of `arrayprobe run`, you inherit this problem.

## Ratios this probe appears in

Each ratio is defined by the two chains it compares. **Read how each was built before comparing any two of them** -- the usual correct answer to "can I put these side by side" is no.

| Section | What it is |
|---|---|
| 3.1 | CIP divided by the archived 2D-S product, per 50 um bin, stock and image-assisted |
| 3.3 | the SODA-2 side of the same flight |

## Where to go next

| | |
|---|---|
| Every probe x engine x mode cell, with its reason | `docs/developer/COVERAGE_MATRIX.md` |
| Which engine to use | `docs/developer/TWO_ENGINES.md` |
| The airspeed chain, which sets the sample volume | `docs/developer/TAS.md` |
| How the upstream code was reviewed, and what was found | `docs/developer/UPSTREAM_REVIEW.md` |
| All seven probes at a glance | [The seven probes](33-probes.md) |

**Generated, not hand-maintained,** from `arrayprobe.constants.IMGPROC_CONFIG`, `coverage_matrix.build_matrix()` and the curated caveats in `probe_caveats.json`.

