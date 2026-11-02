# arrayprobe
> arrayprobe turns raw optical-array-probe imagery into particle size distributions in Python, with no licensed software anywhere in the chain. It ports two independent chains behind one selector: UIOOPS, the MATLAB code of the McFarquhar group and its developers (the v3.5 engine), and NCAR's SODA-2. Each engine is checked against the original source running under Octave or GDL. An earlier translation of UIOOPS v3.1.4 reproduced archived products and is not part of this package ([what that covers](04-validation.md)). You get size distributions, a record of every call, and findings about the originals written for their developers; begin with [Start here](00b-start-here.md), then [Installation](01-installation.md).

| | |
|---|---|
| **Why it exists** | the community's review of ice-cloud probe processing (McFarquhar et al. 2017, *Meteorol. Monogr.* **58**, ch. 11) called for a common reference library of processing algorithms, documented assumptions, and open, version-controlled, modular community software in Python |
| **What it is** | a Python port of UIOOPS v3.5 and of SODA-2, with the findings about the MATLAB fixed in the v3.5 engine and the opt-in enhancements |
| **Validated** | the v3.5 and SODA-2 engines against the original source running under Octave or GDL ([what that covers](04-validation.md)) |
| **Fast, identically** | opt-in parallelism on both engines, proven byte-identical to the serial path by test; default serial, no accuracy traded. Measured on CIP: v3.5 stage 3 **2.5–2.6×** (`--chunks 8`; 2.62× and a 2.48× repeat, a contended 5.57× discarded), the SODA-2 buffer loop **3.70×** (`--jobs 12`) — and a refusal where identity cannot be proven |
| **Requires** | Python. No MATLAB, no toolboxes, no compiled binaries, no reference data |
| **Tests** | 5,254 test methods counted from source in the shipped modules; unittest collects 4,728 tests on the built release, 656 of which skip, each with its reason |
| **Licence** | BSD-3-Clause |

### The evidence ladder

![The evidence ladder: layer 1 reproduces an archived product (an earlier v3.1.4 translation not part of this package; 0 of the shipped probe-and-check combinations); layer 2 matches the original source executing under Octave or GDL (the v3.5 and SODA-2 engines shipped here; 49 probe-and-check combinations); layer 3 is adjudicated by eye with n and the labeller stated.](figures/evidence_ladder.svg)

Every validation claim on this site rests on one of three kinds of evidence — not three grades
of the same thing, but three different questions:

- **Layer 1 — archived product.** Checked against an archived product a campaign actually
  published. No engine in this package has this; it is the strongest evidence, reached only by an earlier
  v3.1.4 translation (not shipped), so it holds for 0 of the 70 combinations of engine, probe and
  check that the validation tracks.
- **Layer 2 — original source executing.** Checked against the original source code running: GNU
  Octave for the MATLAB (UIOOPS), GDL for the IDL (SODA-2).
- **Layer 3 — adjudicated by eye.** A person judging particle images directly in
  `arrayprobe.triage_server` — the only admissible evidence where neither an archived product nor
  the original source exists. Every citation states **n and the labeller**.

Layer 2 is not a weaker layer 1 — it answers a different question, and for both shipped
engines it is the only question answerable at all, because no archived product was ever written
by v3.5 or by this SODA-2 revision. Full statement:
[Validation](04-validation.md#the-evidence-ladder).

### Two independent chains, one codebase, one selector

This package translates **two independent OAP processing chains** — UIOOPS (the default engine)
and SODA-2 — written by different groups, in different languages, runnable from one raw input
through one selector, so the same file can go through both lineages and be compared. Both shipped engines are validated at layer 2: Octave running UIOOPS v3.5's own sources, and
GDL running SODA-2's own unmodified sources. A chain-to-chain difference is a finding to investigate, never proof that one chain is wrong, and
the finding registers are independent and never summed: **123 UIOOPS, 123 SODA-2**. The sharpest
demonstration is the Same Image, Two Verdicts comparison,
described under [Visualisation](03-visualisation.md).

**Deciding whether to use it?** Read the two-page [Scientist's guide](00a-scientists-guide.md) first.

**Start with** [Start here](00b-start-here.md), one notebook from a raw file to a first look at the output, no Python or probe background assumed. Then [Installation](01-installation.md) → [User guide](02-user-guide.md) → [Validation](04-validation.md). New to the terminology? [Glossary](11-glossary.md).

### Fast, and provably the same answer

**Opt-in parallelism on both engines, proven byte-identical to the serial path by test — default
serial, no accuracy traded.** The standing objection to a fast reimplementation of a scientific
code is *"you changed the answer"*; here the answer is asserted identical by test. Because none of
it moves a written byte, all of it lives in the port itself, not in the enhancements package.

Two measured illustrations, each carrying its scope. **UIOOPS v3.5, stage 3, CIP (probetype 1):**
269.5 s → 103.0 s, **2.5–2.6×** with `--chunks 8` (2.62× here; a repeat read 2.48×; a contended run
read 5.57× and is discarded) on 950 records / 82,028 particles, all 40 netCDF
variables byte-equal (`tests/test_v35_imgproc_merge_chunks.py`). **SODA-2, buffer loop, CIP (SEA):**
413.1 s → 111.7 s, **3.70×** with `--jobs 12` on 949 buffers / 81,169 particles, all 35 arrays
byte-equal (`tests/test_soda2_parallel.py`). Both on 12 logical cores, otherwise idle. **Both are
CIP.** Neither is a 2D-S or HVPS number, and *"arrayprobe is 2.6× faster"* is not a claim this
project makes: every figure is one probe, one stage, one file, one core count.

**Where a parallel run cannot be proven identical, it refuses.** `arrayprobe soda2 run --jobs N`
exits 2 on more than one raw file and on the SODA-2 options listed under
[Processing speed](32-processing-speed.md). It does **not** refuse the shipped SODA-2
corrections: each worker rebuilds them by name, and the split stays
byte-identical to serial with them on. The v3.5 engine refuses `--chunks` only under `iQC=1` (the UIOOPS quality-control option).
A prefix scan primes the chunk seam on 2D-S/HVPS/3VCPI exactly. Every figure, its scope and
every refusal: [Processing speed](32-processing-speed.md).

### Why two version numbers

The reproduction targets v3.1.4 and the findings are anchored on v3.5, because they answer different questions: [Validation](04-validation.md#why-two-version-numbers-and-why-that-is-not-a-contradiction) explains why.

### The two engines

The v3.5 and SODA-2 engines shipped here are validated at layer 2; the per-flight figures on
[Validation](04-validation.md) come from the earlier translation that is not part of this package.

**The v3.5 engine** (`arrayprobe_uiops`) translates the current UIOOPS release as its own engine,
not as a configuration of an earlier release — v3.5 removes five diameter variables, adds thirteen and changes
the output container, which is an output-contract change rather than a threshold change. The habit
scheme, the reject codes, the smallest-enclosing-circle routine, the true-airspeed machinery, the
size-distribution bin tables and the per-particle measurement block are ported and asserted against
Octave runs of v3.5's own sources, and **so is the driver half of each of the three large files** —
the record loops, the changed variable sets and the netCDF writers (asserted against Octave runs
during development; the imgProc_sm reference output ships with the package, while the sizeDist and combine
reference outputs are cut from campaign data and are not distributed, so those tests skip). **End-to-end validation
is done**: the port reproduces three whole-program Octave runs of v3.5's own
`imgProc_sm.m`, on 6,819 real field-campaign particles through the real compiled `CGAL_minR` MEX,
with zero disagreeing items across 40 variables and every attribute, under stock reject, a
campaign's modified reject thresholds and the new habit scheme. The two reject configurations disagree with each other
on 2,945 of those 6,819 particles, so matching both is a constraint rather than a tautology.
**No archived campaign product anywhere was produced by v3.5** — it
was released after every campaign whose data this package uses — so a v3.5 number is validated against Octave and
never against an archived product. That is permanent.

**A SODA-2 port** (`arrayprobe_soda2`) has its **whole particle path** in place — sample area,
geometry, sizing and rejection: `soda2_samplearea.pro`, `min_circle_fast.pro`, both of its angle routines, `find_radius.pro`, `aspect_ratio.pro`, `soda2_findsize.pro` and `soda2_reject.pro`, each with its own GDL bank and tracked reference output.
Its SPEC buffer chain, and the CIP route for SEA- and DMT-format files, run **raw through to
output**: the buffer decoders, the `soda2_processbuffer.pro` accumulation/merge stages and the
`.pbp.nc`/`.pbp.csv` PBP writers are all ported and GDL-checked stage by stage, including a
driver-level bank against the netCDF PBP path bit-exact on 37 variables. `arrayprobe soda2 run
<config>` drives the chain from a `[soda2]` run configuration and writes a `.pbp.call` sidecar
beside its output, and the ASCII size-distribution export (`soda2_export_ascii.pro`, turned on by
`asciipsdfile`) is ported too. The driver-level reference output caught one port defect, `TimeInterval`'s
field order; the attribute is part of the comparison.
SODA-2 is NCAR's IDL chain, 3-clause BSD; it is an independent *second* chain to compare against,
never an oracle for this one. Its differential oracle is GDL, which runs SODA-2's own `.pro`
sources exactly as Octave runs UIOOPS's `.m` files. Porting it has produced 123 findings for NCAR,
written for people who will keep running the IDL and collected the same way the UIOOPS ones are.

Optical array probes are how aircraft measure cloud particle sizes and shapes. Most complete
raw→PSD chains run on a licensed language: UIOOPS (MATLAB), SODA-2 (IDL), OASIS (IGOR Pro),
WOPRS (MATLAB). There are open exceptions — NCAR EOL's Process2D (`NCAR/aircraft_oap`,
Apache-2.0, C++) is the clearest, a complete chain from translators to size distributions in
production use at NCAR's Research Aviation Facility, and ADPAA is open too, though its own project page lists its languages as IDL, Python
and shell, so it is not straightforwardly an exception to *licensed language*. Two open Python
packages decode these probes without computing a size distribution: `oap` (MIT) and SPIFpy (MIT,
which reads 2DC, 2DP, 2DS, CIP, PIP and HVPS). So the gap this fills is narrower and more
specific than "no free software exists":

**No open, licence-free implementation reproduced the UIOOPS algorithm family, and none could
regenerate the archived UIOOPS products a large body of published results rests on.** An earlier
translation behind this package showed it can be done ([Validation](04-validation.md)); that
translation is not shipped, so this package does not regenerate archived products. The shipped
v3.5 engine is checked against v3.5's own source.

The one open-source Python library in this space, [`oap`](https://oap.readthedocs.io/) (MIT), is
not a raw→PSD chain: it decompresses and analyses individual images, for DMT greyscale probes
only, with no rejection, habit classification, sample area or size-distribution binning.

> **Beta (0.1.0).** A run collects 4,728 tests on the built release (5254 test methods in source). An independent port; it is not a UIOOPS or SODA-2 release.

## Where it stands

One line per workstream, pinned to the measurement behind it. **Layer 1** means checked against an
archived product a campaign published; **layer 2** means checked against the original source code
executing — Octave for MATLAB, GDL for IDL. Layer 2 is not a weaker layer 1; for both shipped
engines it is the only question that can be asked. **Layer 3** means a person adjudicating the
particle images directly, with *n* and the labeller stated — the only admissible evidence where
neither an archived product nor the original source exists, such as a chain disagreement with no
archived product.

| Workstream | State | What pins it |
|---|---|---|
| **v3.5 engine** — the default | Complete, **layer 2 permanently** | whole-program Octave reference outputs of v3.5's own sources, zero disagreeing items (the `imgProc_sm` reference output is distributed; the `sizeDist` and combine ones are not). No archived product was ever written by v3.5, so layer 1 cannot exist for it |
| **SODA-2 port** | SPEC chain raw → output, **layer 2** | GDL on SODA-2's unmodified `.pro`: `spec_index` identical over 75,668 buffers; `soda2_processbuffer` identical on 500 of 500 and 400 of 400 calls |
| **Enhancements** | 36 modules, plus a SODA-2 suite | each classified against v3.5; the port never imports them, enforced by test |
| **Findings** | 123 UIOOPS, 123 SODA-2 | two registers, never added together |
| **Probes** | 2D-S end to end; HVPS runs end to end; five more ported | the five are layer 2 on synthetic fixtures — **no reference pair exists** for them |

Only UIOOPS-written files adjudicate the UIOOPS engines. See [Validation](04-validation.md) and
[Known gaps](10-known-gaps.md).

## Start here

**First run, in order:**

- **1 · Install** — [Installation](01-installation.md).
- **2 · The quickstart, with no real data** — the [User guide](02-user-guide.md)'s "Quickstart":
  three commands, a synthetic flight, run to the end.
- **3 · A first real file** — the User guide's "Real-data tour", a genuinely recorded flight that
  needs no campaign access.
- **4 · Choose an engine, and name it every time** — `[run].engine = "3.5"` in the run file for new
  data (the default engine). The shipped package runs the stages through `arrayprobe run`
  (`[run].stages` selects them), which reads the preset and engine from its run file; there is
  no separate per-stage subcommand. v3.5 on a 2D-S or HVPS also needs
  an aircraft TAS source (`--tas-file` or `--tas-source`). [Choosing an engine](27-choosing-an-engine.md).
- **5 · Where the outputs go** — `--out`, default `../_decoded`, beside the folder you run from, with a
  `.call` sidecar beside every output.
- **6 · Read the `.call` stamp** — it names the engine and the exact call;
  `arrayprobe reprocess <output>` re-runs the stage under it and diffs the result
  ([User guide](02-user-guide.md), "Watch it, then check it").

| | |
|---|---|
| [Scientist's guide](00a-scientists-guide.md) | Two pages: what it does, which engine to use, what "validated" means and does not, what the files contain |
| [Orientation for OAP scientists](12-orientation.md) | You know the probes and another chain; you do not know this package. Start here |
| [Migrating from UIOOPS](28-migrating-from-uiops.md) · [from SODA-2](29-migrating-from-soda2.md) · [from a SODA-2 batch script](30-from-a-soda2-batch-script.md) | Every MATLAB or IDL call mapped to its Python, command-line and configuration form, with code the test suite runs |
| [How a size distribution is built](22-how-a-size-distribution-is-built.md) | From shadow images to concentration per bin: what each stage decides |
| [Choosing an engine](27-choosing-an-engine.md) · [Why reproduce the original first](26-why-reproduce-first.md) | Which engine answers your question, and what the validation does and does not establish |
| [Installation](01-installation.md) | Get it running, from a clone or a virtual environment |
| [Conventions and terms](09-conventions.md) | File names, stage names and measurement terms, defined once |
| [User guide](02-user-guide.md) | Process a flight, or drive each stage yourself |
| [Tutorial: a 2D-S file end to end](02a-tutorial.md) | One raw 2D-S file on the default engine, install to first plot, every command runnable as written |
| [Example notebooks](https://github.com/sgupta92/arrayprobe/blob/main/examples/README.md) | Runnable notebooks in seven tracks; almost all build their own small input, so none needs campaign data. New readers start with the first notebook, [`1_getting_started/01_start_here.ipynb`](https://github.com/sgupta92/arrayprobe/blob/main/examples/1_getting_started/01_start_here.ipynb) |
| [Visualisation and triage](03-visualisation.md) | Look at the particles — the package's own review tool, and the flagship two-package comparison, Same Image, Two Verdicts |
| [Validation](04-validation.md) | What the port reproduces, and how that is established |
| [What 1.0 promises](42-what-1-0-promises.md) | The claims this package makes, the ones it does not, and how to cite each |
| [Probes](33-probes.md) | One page per probe, with its validation tier and caveats: [2DC](34-probe-2dc.md) · [2DP](35-probe-2dp.md) · [CIP](36-probe-cip.md) · [PIP](37-probe-pip.md) · [HVPS](38-probe-hvps.md) · [2D-S](39-probe-2ds.md) · [Fast2DC](40-probe-fast2dc.md) |
| [Processing speed](32-processing-speed.md) | Every speed figure with its scope, the opt-in flag and byte-identity test behind each, where a parallel run is refused, and what is still unmeasured |
| [Configuration](06-configuration.md) | The TOML run file: selecting a profile, masks, enhancements |
| [Tune thresholds on your own flight](43-tune-thresholds.md) | Which settings you can change, whether each acts on your probe, and how to check a change against particles you labelled |
| [Add a campaign](44-add-a-campaign.md) | Seven steps from a new campaign's raw probe files to a checked product: inventory, run file, preset and engine, airspeed file, the `.call` stamp, comparison with an archived product |
| [Enhancements](05-enhancements.md) | Corrections and new science, strictly outside the port |
| [Which enhancements apply to which engine](23-enhancements-by-engine.md) | For each enhancement, whether it applies on the default v3.5 engine and, where it does not, why |
| [Which enhancements act at which stage](25-enhancements-by-stage.md) | The UIOOPS enhancements by processing-chain stage (decode, framing, size distribution, combine, export), and the SODA-2 corrections, which have no per-stage split |
| [All-on sets, per probe and engine](41-all-on-sets.md) | What a run gets when every enhancement is switched on, for 2D-S, HVPS, CIP and PIP on the v3.5 engine, and SODA-2 separately |
| [For UIOOPS developers](07-findings.md) | What the port found about the MATLAB itself |
| [CLI reference](13-cli-reference.md) | Every `arrayprobe` command and flag |
| [API reference](08-reference.md) | The public Python API, page by page. The default engines: [v3.5 geometry](19-api-v35-geometry.md) · [v3.5 pipeline](20-api-v35-pipeline.md) · [SODA-2](21-api-soda2.md) · [version selector](24-api-selector.md). |
| [Reference](08-reference.md) | The CLI and API references, design documents, project state, published pages |

## What it does

```
raw .2DS / .HVPS / DMT / PMS / SEA
        │  read-binary (read_binary_*)   decode to per-record images
        ▼
   .H.cdf / .V.cdf
        │  imgproc (imgProc_sm)          frame particles, describe each one
        ▼
   proc.*.nc                      per-particle: size, habit, reject code, geometry
        │  sizedist (sizeDist)           accept/reject, bin, concentrations
        ▼
   sd.*.nc                        1 Hz size distributions
        │  combine                       a flight's files into one product
        ▼
   <flight>.combined.<channel>.<probe>.cdf
```

## Why it exists

**The original cannot run on many machines.** UIOOPS's three geometry routines ship only as
compiled Linux/macOS MEX binaries. One produces the pipeline's primary particle size, so its
absence stops a run outright; it is reimplemented here exactly — the smallest enclosing circle is
unique, so agreement is a theorem, not a tolerance.

**Reproducibility is limited by the least available component** — a MATLAB seat, a toolbox, a
Linux box for the MEX files. A reviewer cannot re-run the analysis.

**A codebase without tests cannot be audited.** Porting UIOOPS wrapped two decades of behaviour in
an executable specification and surfaced a good deal that is not documented in the package. Those
findings are [written up for the original authors](07-findings.md), usable without adopting this
port at all.

**Citing.** Please cite UIOOPS alongside this package. A result from `arrayprobe_soda2` also cites SODA-2, in the form its author, Aaron Bansemer, provided:

> Aaron Bansemer. (2026). abansemer/soda2: v2.26.0 (Version v2.26.0) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.18331418
