# SPIF interoperability — an assessment, not a plan

**Written 2026-09-09.** The instruction that produced it: *"all of this review
and literature learnings … must be applied to the port and the code in the package … not just for
the paper."* SPIF is a community single-particle image format that this package has never
considered, and the plan scoped the response as *"assess SPIF interop as a design note (build only
if cheap)"*.

**Nothing is built. This says what interop would mean, what it would be worth, and — the part that
matters most — what cannot be settled without a document this project does not hold.**

---

## What is established, and from where

| Fact | Source, and when it was checked |
|---|---|
| **SPIFpy** decodes 2DC, 2DP, 2DS, CIP, PIP and HVPS into the Single Particle Image Format | a literature index (not included in this release), added 2026-09-05 |
| Python, **MIT**, National Research Council Canada; `github.com/nrc-cnrc/NRC-SPIFpy` | same |
| **DOI 10.4224/40002712** (Wolde, Bliankinshtein, Bala and Nichman, NRC Canada, 2021) | resolved 2026-09-05 |
| Like `oap`, SPIFpy **stops at decoding** — it does not compute size distributions | same |
| Its probe coverage **overlaps this project's raw readers almost exactly** | same |

**The specification has been read** (2026-09-10) — `github.com/FAAM-146/spif` (only `standard/v0/` exists despite a v1 README claim; last push
2024-05-13, 0 stars) and the older rendered docs at `graemenott.github.io/SPIF/spif_definition.html`
(v0.86, 2021-05-06). **SPIFpy's own source (the NRC Canada writer) is not vendored here**; it has been read for the
two narrower questions below, via `gh api`, and for nothing else.

**The schema, read rather than guessed:** root → one group per imager (`instrument_name`,
`group_type="imager"`) → a required `core` group, plus optional `auxiliary`, `level-0/1/2` and a
root `platform` group. Root attrs carry `Conventions` (`SPIF-m.n`) and `imager_groups`. Imager
variables: `color_level` f4, `color_value` u1, `array_size`/`image_size` i4, `resolution`/
`wavelength`/`pathlength` f4; v0.86 adds `arm_separation`, `array_rate`, `antishatter_tips`,
`start_time`. `core` has `image_num` (unlimited) and `pixel` (unlimited) dims; `image` u1(pixel)
flattened row by row; `timestamp`(image_num) with UDUNITS units; `startpixel`, `width`, `height`,
`overload` (0 good / 1 bad), optional `timestamp_flag`. `platform` carries `Time`,
`altitude`/`latitude`/`longitude`, and `tas` (`standard_name = platform_speed_wrt_air`).
**Unresolved in the standard itself, so a writer here would have to decide and record which
reading it took**: `timestamp` is u8 in the FAAM YAML vs f4 in the v0.86 docs; `width`/`height` are
u1 vs u4; the shipped examples say `Conventions: SPIF-0.1` against the root-attribute grammar
above. The project is unmaintained enough that nobody will adjudicate this for us.

## What this package would map *from*, and why the choice is the whole question

The pipeline has **two** places a particle image exists, and they are not interchangeable.

**S2, the decoded record layer** (the v3.1.4 engine's SPEC reader, `_ImageFile`, not included in this release) — what `.H.cdf` holds:

| | |
|---|---|
| Dimensions | `time` (unlimited), `ImgRowlen`, `ImgBlocklen` |
| Variables | `year` (short), `month` `day` `hour` `minute` `second` (byte), `millisec` (short), `wkday` (byte), all on `time` |
| Image data | `data` (int), on `[ImgRowlen, ImgBlocklen, time]` |

This is a **buffer**, not a particle. One record is a block of slices as the probe emitted them.
**Particles do not exist yet** — framing happens in S3.

**S3, the per-particle layer** (`proc.*.nc`) — one row per particle, with every computed
description beside it: position, sizes, habit, reject code, diode statistics.

**A format called *Single Particle* Image Format plainly wants the second.** But for the one
experiment that would be worth doing, the second is the wrong layer — and that is the finding of
this note.

## Why it would be worth doing: the 5.383× that nobody can currently locate

Against UND's independent SODA-2/ADPAA processing of the same flight, this port and the MATLAB it
reproduces agree to a **median ratio of 1.0000**, while both differ from UND by **5.383×** — and
the difference is **size-dependent**: 17× at 55–75 µm, falling to 1.01× by 300 µm
(mechanism **deliberately not asserted**).

A difference that vanishes at large sizes and explodes at small ones does not look like a decode
difference; it looks like framing or acceptance. But that is a reading of a shape, not a
measurement, and this project does not assert it.

**An exchange format is what turns that reading into an experiment**, and the layer decides which
experiment you get:

| What you hand another chain | What you learn | What you lose |
|---|---|---|
| **The decoded buffer** (S2) | Both chains frame the same bits independently, so a residual difference is *theirs and ours downstream of decode* — the hypothesis above becomes testable | Nothing; this is the clean comparison |
| **Framed particles** (S3) | Only what happens *after* framing | **Framing itself**, which is precisely what the size-dependence points at. Handing over our particles imposes our framing and quietly removes the variable under test |

**Answered, 2026-09-10: SPIF's `core` group is pre-framing.** Its own documentation says so
directly — "no processing to split out the multiple particles from a single image" — which is
exactly the S2 buffer layer, confirming what this note reasoned from our side alone before the
spec was read. So SPIF *is* the right target for the experiment above, and this is **one writer**,
at S2, not two: the `aircraft_oap` OAP format the external review named for the same layer
(an external review of 2026-09-06, its improvement 7) is a second candidate for the same job rather
than a fallback for a job SPIF could not do.

## What it would cost, honestly

Unknown, and it would be dishonest to put a number on it. What *can* be said:

- The external review sized an OAP/SPIF writer at **medium** effort and placed it in
  `enhancements_uiops/`, not the port — correct on the project's own rule, since it is a new output and
  not a UIOOPS contract, so it cannot touch the fidelity claim either way.
- The data it needs is already in hand: S2 writes the buffer, S3 writes the particles. This is a
  serialisation exercise, not new science.
- It buys the **cheapest route to a real three-chain inter-comparison on identical images**, which
  is a thing this project currently cannot do at all and has an open, measured question waiting on.

## The next step, and it is still not code

**Both narrower questions are closed (2026-09-10) — read from SPIFpy's real writer source
(`nrc-cnrc/NRC-SPIFpy`, `nrc_spifpy/spif.py` and the shipped `config/*.ini` instrument profiles),
fetched via `gh api` rather than guessed, since the source itself had never been vendored or read
before now.** Both answers are **no**:

1. **Does SPIF have a place to record which configuration produced a file? No.** `SPIFFile`'s
   `root_attrs` come straight from the `.ini`'s `[root]` section (`title`, `institution`,
   `references`, `project`) plus a `history` attribute the writer sets to the current
   timestamp at creation time — a *when*, not a *how*. The `.ini` schema (checked against
   `config/HVPS.ini`) otherwise carries only fixed **instrument** physical properties —
   `resolution`, `arm_separation`, `antishatter_tips`, `bpp`, `wavelength` — none of them a
   per-run processing choice. Nothing plays the role this package's `.call` sidecar does: there
   is no field for a reject threshold, a sizing convention, a software version, or a command
   line. A SPIF file cannot say which of two runs over the same raw data produced it.
2. **Can it represent the stuck-diode mask? No.** Neither `spif.py` (the netCDF schema and
   variable definitions) nor `images.py` (the per-particle image decoder) contains the words
   "mask", "stuck" or "shadow" anywhere; "diode" appears only in image-array reshaping
   (`reshape_image`, `conv_to_array`), never as a per-diode quality flag. A writer built from
   this schema would silently drop the mask, exactly the "worse record than the `.H.cdf`
   it replaced" this note warned about before checking.

**Both are real, checkable findings for the (unmaintained) `FAAM-146/spif` project** — the same
"objective, non-harsh, checkable" standard this project holds its UIOOPS findings to, applied to a
second piece of software instead. Neither closes the door on writing SPIF from this project: an
OAP-processing writer with fields the schema does not define is exactly the situation a config
provenance gap and a missing mask channel describe, not a reason the format can't be used — it
means whichever exchange format this project eventually writes needs a companion sidecar (this
port's own `.call` file, alongside the SPIF export) for the two properties SPIF cannot carry on
its own. The cost and placement of the writer itself are unchanged by this reading — see above.
