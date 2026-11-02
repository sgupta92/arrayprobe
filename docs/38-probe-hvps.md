# HVPS

SPEC Inc. HVPS-3. Same probetype and reader as the 2D-S, fifteen times coarser optics. The second probe with field-campaign raw data and an archived product, and the one whose particle counts match the archive only under an inferred per-flight inter-arrival setting.

## The instrument, as the code sees it

Every row below is read from `constants.IMGPROC_CONFIG`, the port of `imgProc_sm.m`'s own probe switch. None of it is typed into this page.

| | |
|---|---|
| probetype | 2 |
| diodes | 128 |
| diode resolution (`ds`) | 150 um |
| array reach | **19.2 mm** (128 x 150 um) |
| timing family | `spec` |
| needs a TAS file | yes |
| Stage-2 reader | `arrayprobe_uiops.spec.read_binary_spec_v35` |
| image word | 16-bit, inverted |

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

**The hollow test only packs diodes 1-32, and this array has 128**

`calculate_reject_unified.m:465` packs diodes 1-32 whatever the probe's width. This probe is 128 diodes wide, so a particle imaged entirely beyond diode 32 gives the test two zero operands and is ruled hollow on no evidence. That verdict reaches `auto_reject` AND the Korolev correction, so it moves both acceptance and recorded size. Preserved deliberately; `wide_hollow_fix` in `enhancements_uiops/` is the opt-in, default-off alternative, and v3.5's own rewrite is a DIFFERENT correction from ours (it also drops the middle-third scan restriction -- 745 of 1,080 random particles disagree).

*Computed from:* `constants.IMGPROC_CONFIG['HVPS'].diodenum = 128`

**The array images 19.2 mm, and a size ladder must respect that**

128 diodes at 0.15 mm is 19.2 mm across. **That is not a hard ceiling on recorded size**, and it would be an overclaim to say so: a particle that merely has its centre in the array (`sa_method` 0) or is sized through the Heymsfield & Parrish reconstruction (`sa_method` 2) can be recorded LARGER than the array it crossed. The bound that survives is a factor, not an equality -- a centre-in particle reaches about twice the array width, not twenty times it. So the honest reading is: a bin above roughly 38.4 mm on this probe is beyond what any sizing convention here produces, and a ladder whose top lies there is a configuration error rather than a sparse flight. The upstream finding that the default 2D-S bin table became the HVPS one (recorded in the review of the upstream code) is exactly that: a 30 mm ladder handed to a 1.28 mm array, 23x its width, and the symptom was a well-formed file with almost nothing in it.

*Computed from:* `constants.IMGPROC_CONFIG['HVPS']: diodenum 128 x ds 0.15 mm = 19.2 mm`

**A run needs a true-airspeed file, and it is not optional**

`needs_tas_file` is True for this probe: its timing reconstruction consumes an external TAS series, so a run without one is refused rather than defaulted. Airspeed feeds sample volume, so two products built from different TAS sources carry an unnamed scale factor in every concentration ratio between them.

*Computed from:* `constants.IMGPROC_CONFIG['HVPS'].needs_tas_file is True`

**Chunked stage 3: supported via prefix priming**

Timing family `spec` carries state across the record stream, so a naive `--chunks` split would NOT be byte-identical -- and it is refused rather than approximated. It is instead *primable*: a one-pass prefix scan hands each chunk the two seam values it needs (`part_time_prev`, `time_in_seconds_prev`), which makes the split exact again. The driver does this for you; a library caller must pass `prime=`.

*Computed from:* `constants.IMGPROC_CONFIG['HVPS'].timing = 'spec'; CHUNKABLE_TIMINGS_V35 = ('dmt', 'pms', 'fast2dc'); PRIMABLE_TIMINGS_V35 = ('spec',)`

### What a person knows and a constant does not

Curated in `probe_caveats.json` (in `scripts/`). Every citation is re-checked against the real file each time this page is generated.

**Particle counts match the archived product only under an inferred configuration**

Under a per-flight inter-arrival call chosen by comparison, our accepted-particle counts match the archived product's to within 0.5 % on four of the six 2016 flights and on 2017-08-26; 2016-09-10, 2016-09-25 and 2017-08-13 stay open (Known gaps). Under one fixed call, the 1 us default for every flight, they differ by a per-flight factor that is neither constant nor year-linked (2016-09-06: 41,601 against 33,543, ratio 1.2402, size-dependent, with the size distribution timed on the HVPS's own airspeed record; an earlier 1.4625, timed on the 2D-S's, is superseded because that grid added one-sided seconds). The difference is in the accepted particle set, concentrated in a minority of seconds, with Reject Ratio moving the way a per-flight, time-dependent inter-arrival threshold file would move it in over 99 % of the differing seconds. A re-simulation of sizeDist.m's accept/reject/shattering step reproduces our own 170826 product in 99.96 % of comparable cells, and a single per-hour threshold explains 2016's quiet hours (91.8-100 % of populated cells) but not its three busiest (64.0-77.3 %), and timing the flight on its own airspeed record leaves those three unchanged. Narrowed to a leading hypothesis, not solved. What would close it: a TAS-based second resync in the diagnostic, or the operator's 2020 MATLAB logs, which would name the inter-arrival file used. The per-flight inter-arrival threshold configuration that produced the archived product survives in no file, so any configuration that matches it is inferred by comparison, not recovered. Treat HVPS counts as cross-checked, never as validated.

**The manufacturer's own manual prints 2D-S constants in the HVPS appendix**

The HVPS Post-Processing manual's Appendix A gives the default sample area with pxs = 0.01 mm, described as the optically realized array element size. That is the 2D-S's resolution. SPEC's own HVPS technical manual states 150 um/pixel, fifteen times coarser. Read in both PDFs directly. If you take a sample area from that appendix you are off by a factor of fifteen in one term.

**An all-zero DMT_DOF_SPEC_OVERLOAD column can be faithful or a decoder gap**

A variable holding one value for every particle is what a decoder that never wrote it looks like, and on one field campaign's HVPS it was exactly that: the hvps reader left SliceCount, DMT_DOF_SPEC_OVERLOAD and Particle_number_all identically zero where the spec reader fills them. On the OLYMPEX HVPS file shipped in UIOOPS's own minimal_working_example, DMT_DOF_SPEC_OVERLOAD is zero for every particle as well, and there it is faithful: unmodified imgProc_sm.m under Octave writes zero too, because the overload flag is absent from that input. So an all-zero column settles nothing by itself; run the original on the same input before calling it a gap either way.

**Reject code 't' is never emitted, on any probe**

calculate_reject_unified.m:269 rejects on the tighter threshold (max_comp_img_ar) before :272 tests the looser one (max_edge_img_ar), so the second branch is unreachable and image_auto_reject never contains 116. The netCDF Description attribute at imgProc_sm.m:325-329 states the two thresholds the other way round. Both are preserved verbatim -- this is a faithfully reproduced upstream defect, not a port bug. If you are tabulating reject codes, 't' is structurally absent rather than merely rare.

**A flight crossing midnight is corrected once, not every time**

sizeDist.m:98-99 and :657-658 apply the +240000 rollover only to the FIRST decrease in the time vector, because MATLAB's a:b uses only the first element of a vector operand. A flight with more than one backward time step keeps the later ones. Preserved deliberately.

**Trust the .call sidecar, not the filename**

Every stage stamps its configuration into a .call sidecar and refuses an input that disagrees or carries no stamp. If you write products with your own script instead of `arrayprobe run`, you inherit this problem.

## Ratios this probe appears in

Each ratio is defined by the two chains it compares. **Read how each was built before comparing any two of them** -- the usual correct answer to "can I put these side by side" is no.

| Section | What it is |
|---|---|
| 3.7 | excess-count ratios, ours divided by the archived accepted-particle count |

## Where to go next

| | |
|---|---|
| Every probe x engine x mode cell, with its reason | `docs/developer/COVERAGE_MATRIX.md` |
| Which engine to use | `docs/developer/TWO_ENGINES.md` |
| The airspeed chain, which sets the sample volume | `docs/developer/TAS.md` |
| How the upstream code was reviewed, and what was found | `docs/developer/UPSTREAM_REVIEW.md` |
| All seven probes at a glance | [The seven probes](33-probes.md) |

**Generated, not hand-maintained,** from `arrayprobe.constants.IMGPROC_CONFIG`, `coverage_matrix.build_matrix()` and the curated caveats in `probe_caveats.json`.

