# Orientation for OAP scientists
> You know optical array probes and at least one processing chain. You do not know this package. Start here.

**In short:** this is UIOOPS — the McFarquhar-group MATLAB chain — re-implemented in Python, its v3.5 release as the engine, validated against Octave runs of v3.5's own sources. An earlier translation of UIOOPS v3.1.4 reproduced archived products and is not part of this package ([Validation](04-validation.md)). It is not a new processing philosophy. What is new: the chain runs without a licence, every accept/reject and sizing decision is a tested line of code you can read, and what the reproduction found in the original is written up for its authors.

**See also** [User guide](02-user-guide.md) · [Validation](04-validation.md) · [Glossary](11-glossary.md) · [Known gaps](10-known-gaps.md)

## In your terms

| If you use… | Then `arrayprobe` is… |
|---|---|
| **UIOOPS** | the same algorithms — `read_binary_*`, `imgProc_sm`, `sizeDist`, the combine — with the same outputs, one MATLAB `file:line` cited per function. The shattering gate, the six `d_choice` sizing definitions, Holroyd habits, the reject ladder and the sample-area methods behave as in the MATLAB, and the [findings](07-findings.md) say where that behaviour is not what the code comments say |
| **SODA-2** | a different chain with a narrower purpose. SODA-2 offers several sizing methods, water processing with the Korolev correction, stuck-bit correction and a GUI; this translates one chain exactly, puts corrections in a [separate opt-in package](05-enhancements.md), and reviews particles in a [browser tool](03-visualisation.md) rather than a processing GUI |
| **OASIS or a lab-internal chain** | an open, tested reference you can run beside your own and diff against, on any machine with Python |
| **NCAR's Process2D (`NCAR/aircraft_oap`)** | an independent open chain: Process2D is complete in its own right (C++, Apache-2.0; translators into the RAF OAP file format, then `process2d` to size distributions) and in production use at NCAR's Research Aviation Facility under its own algorithm family; this one translates UIOOPS and SODA-2 instead, so the two are separate opinions on the same instrument |
| **SPIF / SPIFpy** | complementary: SPIF standardises the *decoded-image* layer; this one carries a decode through to size distributions under one published algorithm family |

The shape of the work: **the port surfaced findings about the MATLAB, and those findings are fixed** — in the v3.5 engine, the default, where the developers addressed them, and otherwise in the opt-in enhancements, each correction measured by running both ways on the same data. In the v3.5 engine, preserved upstream behaviour is likewise kept unless it destroys data, and each case carries a regression test. See [Choosing an engine](27-choosing-an-engine.md), [CLI reference](13-cli-reference.md) and [Which enhancements apply to which engine](23-enhancements-by-engine.md).

## Running NCAR's Process2D on the same images

Two chains given the same raw file differ in decoding as well as in algorithms, so a difference
in their size distributions cannot be pinned on either. Exporting this package's decoded 2D-S
images in NCAR's RAF OAP file format (`.2d`) lets Process2D run on the identical images, so what
remains between the two is attributable to the algorithms.

```bash
python -m arrayprobe_uiops.export_oap DECODE OUT --probe 2DS
```

- **Input and output.** `DECODE` is the v3.5 decoder's output for one channel (`<flight>.H.nc` or
  `.V.nc`); `OUT` is the `.2d` file, one channel per file. It writes an XML preamble, 4116-byte
  records (probe id `SH`/`SV`, the record time, TAS, the 4096-byte slice stream) and one sync
  slice after each particle carrying its 32-bit timing counter. `--timing-convention` chooses
  whether the sync closing a particle carries the next particle's time (`translate2ds`, the
  default, as NCAR's own translator writes it) or its own (`own`); which one Process2D expects
  of a 2D-S file is not yet settled. `--project`, `--platform`, `--flight-number` and `--serial`
  fill the preamble.
- **Refusals.** An existing `OUT`; a file that is not a v3.5 2D-S decode (no `data` variable, or
  another probe named); a `--probe` other than `2DS`.
- **Pixel inversion.** The decode stores 1 = shaded; the OAP format stores 1 = clear, so every
  pixel is inverted on the way out.
- **Open question: diode order.** `process2d` unpacks diode 0 from byte 15 bit 7; NCAR's
  `translate2ds` packs it into byte 0 bit 0. One of the two therefore reads the other's images
  mirrored across the array. The export follows `process2d`'s order; whether a
  `translate2ds`-written file and this one agree byte for byte stays open until both are run on
  the same raw file.
- **What it loses, stated.** Record time is per record, not per particle; TAS is one 16-bit word;
  housekeeping and mask packets are not carried; the upper 16 bits of the 2D-S's 48-bit timing
  word are not stored at decode and are not reconstructed.

The reader `arrayprobe_uiops.oap_read` (`read_oap_2ds`) decodes a `.2d` file by `process2d`'s rule,
written independently of the exporter, so the round trip checks the export against code it does
not share. Neither module computes a number used by any product.

**From Process2D into this package.** [`field2006_shatter`](https://github.com/sgupta92/arrayprobe/blob/main/enhancements_uiops/src/arrayprobe_enhancements/field2006_shatter.py)
transcribes Process2D's Field et al. (2006) per-second inter-arrival fit (a double-Poisson fit
over the last 400 inter-arrival times, cutoff at 1/20 of the first mode's peak) as an opt-in
enhancement. It runs beside a size distribution and writes its fit to a copy; the batch driver
runs it when a run's configuration names it.

**Procedures learned from comparing chains**, each a notebook on demo data:

- [31 — Is the probe clock on the aircraft's clock?](https://github.com/sgupta92/arrayprobe/blob/main/examples/5_data_quality/03_clock_offsets.ipynb#is-the-probe-clock-on-the-aircrafts-clock)
- [32 — Sample-area conventions: centre-in, all-in and reconstruction](https://github.com/sgupta92/arrayprobe/blob/main/examples/4_methods_and_literature/02_sample_area_conventions.ipynb)

## What has been shown, and what has not

Fifteen flights of one field campaign — six from 2016, nine from 2017 — reproduce their archived 2D-S products cell by cell, ten of them exactly — every non-zero cell of `Counts` and `Size Distribution` in bins 6+ equal, over the seconds both products hold; the table with every residual attributed is [Validation](04-validation.md). Read it with the [Glossary](11-glossary.md) open: a percentage there is computed over one of four nested cell populations spanning three orders of magnitude, and the headline is always the smallest and hardest — non-zero cells in the used size bins.

What has **not** been shown:

- **The HVPS matches the archive only under an inferred configuration.** It lands on the archive's time grid and bin ladder. Under one fixed inter-arrival call it accepts 1.24 and 1.09 times the archived count on two flights and 0.9987 times on a third; under a per-flight call chosen by comparison it matches to within 0.5 % on four of the six 2016 flights and on 2017-08-26, while 2016-09-10, 2016-09-25 and 2017-08-13 stay open. The archive's per-flight inter-arrival threshold choice survives in no file, so the matching configuration is inferred, not recovered, and HVPS counts are not quoted as validated. [Known gaps](10-known-gaps.md).
- **Every measured consequence is warm marine stratocumulus.** For habit, hollowness and ice shattering — the routines that matter most in ice — the evidence is Octave running the original code on constructed input, not campaign products.
- **2DC, 2DP, CIP and PIP** are ported and were Octave-checked during development (reference outputs not distributed), but no raw-plus-product pair for them is held, so nothing pins them to a real archive.

## The thirty-minute tour

```bash
git clone https://github.com/sgupta92/arrayprobe && cd arrayprobe
python -m venv .venv
# install the clone as CONTRIBUTING.md describes          # Linux / macOS: .venv/bin/python
.venv/Scripts/python.exe -m unittest discover -s tests -p "test_*.py"     # ~10 min, no data needed
```

The suite needs no MATLAB, no Octave and no campaign data: most Octave reference files are committed and run on a fresh clone. Reference outputs cut from real campaign data are not distributed, so the checks that need them (among them the v3.5 sizeDist and combine drivers, the CIP/PIP/2DC/Fast2DC paths and the SODA-2 real-file runs) report as skipped, with the reason; those checks were run against Octave during development. On Linux and macOS read `.venv/bin/python` for `.venv/Scripts/python.exe`.

**Ten minutes, not two.** 589 s measured for the *default* run, which gates out ~51 tests whose cost is their own subject (stall-timer watchdogs, subprocess-driven notebook and paper-build checks). `ARRAYPROBE_SLOW=1` runs those too, a further ~119 s, as CI does; the number of tests executed (collected minus skipped) matches the project's only with that variable set. A full run of the shipped suite collects 4,728 tests on this release.

Then process a flight. `arrayprobe run` takes raw `.2DS` files through decode, particle framing, size distributions and the combine, with every choice — engine, campaign preset, profile, output folder, stages — named in one run file. Copy `examples/start_here/run.toml`, set its preset, airspeed source and `out` for your campaign; a campaign the package does not ship is declared in a file you own ([Configuration](06-configuration.md)):

```bash
.venv/Scripts/python.exe -m arrayprobe run my_run.toml raw/base*.2DS --yes --chunks 8 --s2-jobs 8
```

**Why `--yes`.** A run that names no threshold policy prints the configuration it will use and asks before starting; `--yes` answers in advance. Where stdin is not a terminal — `nohup`, CI, any script, which is how a multi-hour run is launched — it **refuses to start and exits 2**. Declaring `--regime` or a `[thresholds]` section in a config file removes the question; see [Configuration](06-configuration.md).

Before the first run: **Disk** — the decoded image file is UIOOPS's own int32 layout and can reach twelve times the raw size, the per-particle file several times more; the driver estimates the worst case and refuses to start without room. **Time** — particle framing is about 80 % of a run (on the one 2D-S flight timed by stage, engine v3.5, [Speed](developer/SPEED.md)); a 1.5 GB two-file flight took 5.3 hours on 12 cores with the parallel flags above, and the flags never change a written byte — a test, not a claim.

Finally look at the particles, because a size distribution cannot tell you whether the particles behind it were framed and accepted correctly:

```bash
.venv/Scripts/python.exe -m arrayprobe triage --decoded-dir <your run's out folder>
```

**`--decoded-dir` is the run's `out` folder, and it must still hold the decode images.** The
viewer pairs each `proc.<flight>.<channel>.nc` with the decode `<flight>.<channel>.nc` beside it.
If the decode was deleted to reclaim disk, the flight is indexed but reads `no matching raw/image file
found`. Point the viewer where both files survive, or re-run stage 2. A self-contained example needing no campaign
data is on the [visualisation page](03-visualisation.md).

## Knobs you already know, and where they live

| In UIOOPS you set… | Here it is… |
|---|---|
| `d_choice` (sizing definition) | a named entry in the size-definition registry; the driver's preset fixes 6, the minimum enclosing circle, because that is the call it was transcribed from — a preset for another campaign names its own |
| `SAmethod` | never defaulted, any more than `d_choice` is; with `arrayprobe run <config.toml>` (`[run].engine = "3.5"`, `[run].stages = "4"` for the size distribution alone) both come from the preset, which fixes centre-in. |
| the twelfth `sizeDist` argument (inter-arrival threshold file) | `[shattering].threshold_file` in the run file, and it matters more than it looks: naming a file *that does not exist* enables shattering on the per-probe default, while passing nothing skips the block and accepts ~58 % more particles. The output cannot say which happened, so every stage writes a `.call` sidecar that can |
| reject thresholds (`rej_hollow`, `max_edge_img_ar`, …) | fields of a named `FidelityProfile`, never a free number. The archived products behind the validation used three thresholds that differ from the released defaults; both profiles ship and the choice is explicit |
| `probeName` / `projectName` | rows in a configuration table — a project the table does not name falls through to its `otherwise` branch exactly as `sizeDist.m` does. A campaign needs a new row only if its probe constants differ |
| stuck-diode masks | `--diode-corrected`, off by default, always writing to a separate file |

Every fidelity-sensitive argument is required rather than defaulted, so a run cannot quietly acquire someone else's configuration. [Configuration](06-configuration.md) has the run-file form.

## Reading the repository

Three directories are the package; the rest can wait.

| Read | Skip on a first pass |
|---|---|
| `src/` — the engines | `tests/` — read a test when you doubt a claim |
| the upstream-findings list — what reproducing UIOOPS found in the MATLAB, for its authors | `scripts/` — the batch driver and helpers behind the CLI |
| these pages and `examples/` — the notebooks, each on demo data | the upstream MATLAB sources; each engine cites them by `file:line` |
| `enhancements_uiops/` — corrections and new science, separate from the port | |

## What would help most

One **raw-plus-product pair** for any probe or campaign this project does not hold — a full ice-phase 2D-S raw-plus-UIOOPS-product pair, or any CIP/PIP/2DC pair — closes a gap the port cannot close alone. Second, an answer to the **HVPS count question** from anyone who processed HVPS data with UIOOPS. Third, a reading of the [findings](07-findings.md) by someone who runs the MATLAB: each is checkable in Octave in a minute, and the items marked *read* are flagged for that check.
