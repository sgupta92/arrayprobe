# 2DS

SPEC Inc. 2D-S. This is the probe the validation used: raw 2D-S data were processed and compared with the archived product that the original MATLAB code wrote. The measured result is on [Validation](../../04-validation.md). That comparison ran on an earlier translation of UIOOPS v3.1.4, which is not part of this package.

## The instrument, as the code sees it

Every row below is read from `constants.IMGPROC_CONFIG`, the port of `imgProc_sm.m`'s own probe switch. None of it is typed into this page.

| | |
|---|---|
| probetype | 2 |
| diodes | 128 |
| diode resolution (`ds`) | 10 um |
| array reach | **1.28 mm** (128 x 10 um) |
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

**Shipped presets naming this probe:** `DEMO_2DS_H`, `ORACLES_2016_2DS_H`, `ORACLES_2017_2DS_V`.

**New data (v3.5): no campaign-neutral preset ships yet.** A preset names the project whose size-bin ladder `sizeDist` uses, and the shipped 2D-S and HVPS presets name one field campaign and a demo only (on v3.5, DEMO bins a 2D-S on the HVPS ladder, a finding reported to the UIOOPS developers). Which ladder a neutral preset carries is an open decision; until one ships, a v3.5 run of new data needs a campaign of your own: a `[[campaign]]` table in your own TOML, named with `[run].presets` (see [Add a campaign](../../44-add-a-campaign.md)).

`[run].engine` is required: `"3.5"` for new work.

Where a cell above reads `refuses (by design)` or `REFUSES (DEFECT)`, the reason is in `docs/developer/COVERAGE_MATRIX.md` for that exact cell. A refusal here is always preferred to a silently wrong fast answer, and the two words are different: *by design* means the combination is meaningless, *defect* means it should work and does not yet.

## Caveats

### Consequences of this probe's own geometry

Computed from the table above, not recalled -- each says which arithmetic produced it.

**The hollow test only packs diodes 1-32, and this array has 128**

`calculate_reject_unified.m:465` packs diodes 1-32 whatever the probe's width. This probe is 128 diodes wide, so a particle imaged entirely beyond diode 32 gives the test two zero operands and is ruled hollow on no evidence. That verdict reaches `auto_reject` AND the Korolev correction, so it moves both acceptance and recorded size. Preserved deliberately; `wide_hollow_fix` in `enhancements_uiops/` is the opt-in, default-off alternative, and v3.5's own rewrite is a DIFFERENT correction from ours (it also drops the middle-third scan restriction -- 745 of 1,080 random particles disagree).

*Computed from:* `constants.IMGPROC_CONFIG['2DS'].diodenum = 128`

**The array images 1.28 mm, and a size ladder must respect that**

128 diodes at 0.01 mm is 1.28 mm across. **That is not a hard ceiling on recorded size**, and it would be an overclaim to say so: a particle that merely has its centre in the array (`sa_method` 0) or is sized through the Heymsfield & Parrish reconstruction (`sa_method` 2) can be recorded LARGER than the array it crossed. The bound that survives is a factor, not an equality -- a centre-in particle reaches about twice the array width, not twenty times it. So the honest reading is: a bin above roughly 2.56 mm on this probe is beyond what any sizing convention here produces, and a ladder whose top lies there is a configuration error rather than a sparse flight. The upstream finding that the default 2D-S bin table became the HVPS one (recorded in the review of the upstream code) is exactly that: a 30 mm ladder handed to a 1.28 mm array, 23x its width, and the symptom was a well-formed file with almost nothing in it.

*Computed from:* `constants.IMGPROC_CONFIG['2DS']: diodenum 128 x ds 0.01 mm = 1.28 mm`

**A run needs a true-airspeed file, and it is not optional**

`needs_tas_file` is True for this probe: its timing reconstruction consumes an external TAS series, so a run without one is refused rather than defaulted. Airspeed feeds sample volume, so two products built from different TAS sources carry an unnamed scale factor in every concentration ratio between them.

*Computed from:* `constants.IMGPROC_CONFIG['2DS'].needs_tas_file is True`

**Chunked stage 3: supported via prefix priming**

Timing family `spec` carries state across the record stream, so a naive `--chunks` split would NOT be byte-identical -- and it is refused rather than approximated. It is instead *primable*: a one-pass prefix scan hands each chunk the two seam values it needs (`part_time_prev`, `time_in_seconds_prev`), which makes the split exact again. The driver does this for you; a library caller must pass `prime=`.

*Computed from:* `constants.IMGPROC_CONFIG['2DS'].timing = 'spec'; CHUNKABLE_TIMINGS_V35 = ('dmt', 'pms', 'fast2dc'); PRIMABLE_TIMINGS_V35 = ('spec',)`

### What a person knows and a constant does not

Curated in `probe_caveats.json` (in `scripts/`). Every citation is re-checked against the real file each time this page is generated.

**A fouled channel looks busy, not quiet**

On one field campaign the vertical channel's receive-side mirror was soot-fouled for a whole deployment. A fouled mirror triggers constantly, so the V channel's HIGH packet rate is the signature of the fault, not of signal. The rule does NOT transfer between deployments: in the same campaign's two later deployments both channels worked (used-bin V/H median 0.94 and 1.01) and V-channel products were delivered.

**Under the v3.5 engine, a campaign upstream does not list gets the HVPS bin table**

sizeDist.m's campaign switch lists only PECAN, GPM, SOCRATES and IMPACTS. Anything else falls to `otherwise`, whose 2DS branch carries the HVPS 0.2-30 mm ladder while diodesize and armdst stay at the 2D-S values. 23 of its 28 bins lie beyond what a 1.28 mm array can reach. On one field-campaign flight, a correctly-configured 2D-S run under v3.5 accepted 14 and 90 particles from ~39,559 in the raw, and the output looked like a quiet flight rather than a broken one. The port reproduces this faithfully; it is the upstream finding that the default 2D-S bin table became the HVPS one (recorded in the feedback register for the developers).

**Call sizeDist WITH the twelfth argument, even though the file it names does not exist**

For the validation campaign, the archived product was made by passing 2DS_intArrThreshold_MISSING.cdf, which is absent -- so :70 sets iaThreshFile = 'NONE' and :874 falls back to the per-probe 6 us default. Passing NOTHING instead skips the entire shattering block at :866 and accepts 58% more particles. The output file cannot record which call made it (an upstream finding, recorded in the feedback register for the developers), which is why run_flight.py writes a .call sidecar.

**The last record of every raw file is never decoded as a primary**

read_binary_SPEC.m decodes the pair (N, N+1), probes one byte for EOF and breaks, so a file of n whole records yields n-1 primaries (n when a partial record follows them: the probe then finds a byte and the loop runs once more). reproduced in readers/spec.iter_record_windows. Separately, .MK.csv housekeeping files have no line terminators at all: twenty %d conversions for nineteen values makes fprintf drop the trailing ' \n'.

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
| 3.1 | as the denominator of the CIP comparison -- the archived 2D-S product |
| 3.10 | within-instrument A/B on this probe: rej_hollow on vs off -- a pure sizing effect, no verdict changes |

## Where to go next

| | |
|---|---|
| Every probe x engine x mode cell, with its reason | `docs/developer/COVERAGE_MATRIX.md` |
| Which engine to use | `docs/developer/TWO_ENGINES.md` |
| The airspeed chain, which sets the sample volume | `docs/developer/TAS.md` |
| How the upstream code was reviewed, and what was found | `docs/developer/UPSTREAM_REVIEW.md` |
| All seven probes at a glance | `docs/developer/probes/README.md` |

**Generated, not hand-maintained,** from `arrayprobe.constants.IMGPROC_CONFIG`, `coverage_matrix.build_matrix()` and the curated caveats in `probe_caveats.json`.

