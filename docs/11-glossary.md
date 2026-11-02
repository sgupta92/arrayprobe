# Glossary

**In short:** one fixed meaning for *cell*, *bin*, *second*, *boundary*, *non-zero* and *counts*, plus the four nested denominators an agreement figure can be computed over. A percentage means nothing until you know which one it used.

**See also** [Validation](04-validation.md), which uses every term defined here.

This page is the single definition. The paper's number registry carries the same definitions
under `validation.vocabulary`, and the manuscript restates them; if the three disagree, this page
and the registry are right.

Two terms are easy to confuse in a way that changes a headline: the share of *cells* where both
files record zero and the share of *particles* in the excluded bins are different quantities over
different populations, and both land near the same number.

## The grid

A **flight product** is a two-dimensional grid of numbers, plus its axes.

| Term | Definition |
|---|---|
| **second** | One row. One second of flight time — the product's native time step. A flight has ~30,000 of them. |
| **bin** | One column. One particle-size interval. The 2D-S grid has **128**, smallest first. |
| **cell** | One row–column pair: a single number. *One second, one size bin.* A flight grid holds ~3.8 million cells. |
| **counts** | The `Counts` variable: whole particles recorded in that cell. An **integer** — which is why agreement can be exact equality rather than a tolerance. |
| **size distribution** | The `Size Distribution cm-3` variable: the same grid, as a concentration. Both are compared; both give the same headline. |

## Which cells get counted

Four **populations**, each a strict subset of the one before. Numbers are from one 2D-S flight of a field campaign (20 September 2016) in the [validation](04-validation.md) set.

| Population | Cells | What it is |
|---|---|---|
| grid | 3,846,656 | every second × every bin |
| **both-present** | 3,202,944 | both files hold a value rather than fill (`NaN`) |
| non-zero | 55,017 | both-present, and at least one side is non-zero |
| **used-bin non-zero** | 13,039 | the same, restricted to bins 6 and above |

- **both-present** is the widest honest denominator, but **95.8–98.8 % of it is zero equals
  zero** — agreement about *absence*. A percentage over it looks excellent almost regardless of
  what the code does.
- **used-bin non-zero** is the **headline denominator**: only cells where at least one file
  recorded a particle, in the bins the science uses. It is ~200× smaller and correspondingly harder
  to satisfy.

**The two are never mixed, and both are always printed.** A check prints both every
time and names what the looser one is made of.

## The boundary

**Bins 1–5 are excluded from every headline figure.** They sit at the diode-pitch noise floor and
the science does not use them — the field's convention, not a threshold tuned here. *Boundary*,
unqualified, always means the line between bin 5 and bin 6.

**Bins 1–5 also hold 99.4–99.8 % of all particles by count**, which is what makes the headline
denominator small. That is *not* the ~98 % zero-equals-zero share above; the two are different
populations, each measured on its own.

| Quantity | Value | Population |
|---|---|---|
| share of *particles* in bins 1–5 | **99.4–99.8 %** | all particles in the archived product |
| share of *cells* that are zero==zero | **95.8–98.8 %** | both-present cells |

## Agreement

| Term | Definition |
|---|---|
| **agreeing cell** | Both files hold the same value. Exact equality, not within a tolerance. |
| **differing cell** | Both files hold a value and the values differ. |
| **uncovered second** | A second present in one file and absent from the other. Invisible to any cell-wise percentage, so coverage is always reported separately. |
| **used-bin residual** | The differing cells that survive into bins 6+. Across the six validated **2D-S** flights of the [validation](04-validation.md) set: **48 cells, of which none has both sides non-zero** — the two implementations differ only on *whether* a second has particles, never on *how many*. **This is a 2D-S result and does not transfer**: on the HVPS most differing cells are the other kind, both sides non-zero and disagreeing, and bins 6+ is not a usable HVPS range, since it puts almost nothing there. |

## Files

| Term | Definition |
|---|---|
| **archived product** | The archived MATLAB output the published science was written from. For the validated 2D-S flights these are `base*.combined.H.2DS_2.cdf`. **All 29 held products carry the `_2` suffix**, hardcoded in the validation tool so nothing else can be compared against by accident. |
| **`proc` file** | Per-particle output of stage 3 (framing): one row per particle, ~40 variables. |
| **`sd` file** | Per-second size distribution, stage 4: one file per raw file. |
| **combined product** | The combine stage: one flight's `sd` files stitched into the single product a paper cites, and what validation compares. |
| **`.call` sidecar** | A text file beside every output recording exactly how the stage was invoked, because no UIOOPS output records which call produced it and two reachable calls give a 58 % difference in accepted particles. |

## Pipeline stages and test terms

| Term | Definition |
|---|---|
| **golden** | A stored file of expected output, written by running the original's own code on a fixed input — the UIOOPS `.m` sources under GNU Octave, or SODA-2's IDL `.pro` sources under GDL — that a test compares the port's output against. Most are committed and run on a fresh clone; goldens cut from real campaign data are not distributed, so the checks that need them report as skipped. Octave and GDL are needed only to regenerate goldens ([Installation](01-installation.md)). |
| **`iQC`** | A v3.5 `imgProc_sm` switch, default `0`. `iQC=1` runs a denoise pass on each particle image (`imgProc_sm.m:801-846`, ported as `arrayprobe_uiops.qc.qc_image`) before any measurement is taken from it, and adds the `subparticle_num` and `subparticle_mindist` variables to the `proc` file. The value is recorded in the `.call` sidecar; the v3.5 engine refuses `--chunks` when it is `1`. |
| **S2** | The decode stage (`2` in the `stages` setting of `arrayprobe run`): turns a raw probe file into a decoded image file plus its `.tas.csv` true-air-speed sidecar. The driver's log lines for it begin `S2`. |
| **S3** | The framing stage (`3` in `stages`): frames particles out of the decoded images and writes the per-particle `proc` file. |
| **S4** | The size-distribution stage (`4` in `stages`): computes one-second size distributions and writes the `sd` file. The combine step that follows is `c` in `stages` and has no S number. |

## Evidence

| Term | Definition |
|---|---|
| **archived product** | The strongest layer: output written by the original MATLAB. Limited to the configurations one campaign used. |
| **differential oracle** | The original's own `.m` files run unmodified under Octave. Reaches configurations no product covers, including inputs that crash the original. |
| **documented semantics** | The weakest layer: a reading of the source plus a pinned test, labelled as such wherever it carries a claim, because both sides come from the same reading. |
| **measured / derived / read** | How a finding was established. *Measured*: run on real data; *derived*: computed from measured quantities; *read*: established by reading the source and flagged for the reader's own check, never asserted. |

## Probe and microphysics terms

Definitions as used in [How a size distribution is built](22-how-a-size-distribution-is-built.md).

| Term | Definition |
|---|---|
| **optical array probe** | An airborne instrument that records particle shadows on a row of photodiodes across the airflow; its raw file holds images, not sizes or concentrations. |
| **diode** | One photodiode in the probe's array; the number of diodes times the resolution is the width the array images ([Probes](33-probes.md)). |
| **slice** | One clock of the array: the record of which diodes were shadowed at that instant. A particle passing through becomes a stack of slices. |
| **habit** | A particle's shape class, assigned after Holroyd (1987) and written per particle to the `proc` file. |
| **reject code** | The per-particle code that decides whether a particle is accepted into the size distribution. |
| **inter-arrival time** | The time between one particle and the next; the shattering test and the live time are both built from it. |
| **shattering** | An ice crystal striking the probe tips breaks into fragments that arrive in a burst; particles whose inter-arrival time is shorter than a threshold are removed as fragments. |
| **sample area** | The effective area over which a particle of a given size is counted, set by `sa_method`: *centre-in*, *entire-in*, or the reconstruction correction that widens the array. |
| **true air speed (TAS)** | The aircraft's speed through the air, from the probe's own record in the decode's `.tas.csv` sidecar. |
| **live time** | The part of each second the probe could record: the sum of inter-arrival times less the time lost to overloads; written as `sum_IntArr`. |
| **sample volume** | Sample area × true air speed × live time, per bin; it turns a count into a concentration and is written as `sample_vol`. |
