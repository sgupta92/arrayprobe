# Why reproduce the original first
> How a port with no MATLAB licence can say it matches MATLAB, why the findings came from reproducing the original rather than improving it, and what the validation does and does not establish.

**The order of the work is the argument.** This package began as a port of UIOOPS. Porting it
line by line surfaced [findings](07-findings.md) about the MATLAB — places where the code does
something its comments, documentation or authors' evident intent say it should not. Those findings
are fixed: in the v3.5 engine, the package default, wherever the UIOOPS developers fixed them in
their later release, and in the opt-in [enhancements](05-enhancements.md) wherever they did not.
Each correction is measured by running the same data both ways.

The method started from a translation that deliberately fixed nothing: an earlier translation of
UIOOPS v3.1.4 reproduced archived products from a field campaign, including where the original is
wrong. It is not part of this package; the measured result is on the
[Validation](04-validation.md) page. This page explains why it had to come first.

**See also** [Validation](04-validation.md) · [Findings](07-findings.md) · [Choosing an engine](27-choosing-an-engine.md) · [Known gaps](10-known-gaps.md)

## Why the faithful reproduction came first

Three reasons, each sufficient alone.

**The archive was written by the code as it behaved.** A field campaign's size-distribution products,
and the papers written from them, came from UIOOPS v3.1.4 running a campaign fork's settings. A
port that corrected a defect would differ from the archive exactly where the defect acted, and a
reader could not tell "the port is wrong" from "the original was".

**A finding needs a baseline.** "The reacceptance loop only scans the first shattering event" is a
claim about the MATLAB; to say how much it matters, you run the original and corrected behaviour
on the same particles and count the difference. The original behaviour is one half of every such
comparison; the enhancement is the other half, and the enhancements depend on the engine, never the
reverse.

**A port that matches the archive exactly has been checked by the archive.** Agreement to the last
cell of `Counts` and `Size Distribution`, over whole flights, is far stronger than agreement within
a tolerance, and only a port that changed nothing can have it. Every later departure is then a
named, tested, opt-in decision rather than drift — or, on a probe with no archived product to
reproduce, a named correction the run applies by default and records in its stamp, never on the
2D-S/HVPS lineage the validation rests on.

Each reproduced defect carries a regression test named after the MATLAB line it protects, and a
test checks that every one of those named tests still exists.

## How it is checked without MATLAB

This project has no MATLAB licence and will not have one. "Matches MATLAB" rests on three layers,
each covering what the one above cannot reach.

1. **Archived products written by MATLAB.** Raw probe files paired with the size-distribution
   products UIOOPS wrote from them before the licence lapsed. The translation processed the raw
   file and the two products' `Counts` and `Size Distribution` were compared cell by cell over the
   seconds both hold — the whole chain, on real data, against the original program. This layer
   applied to the earlier v3.1.4 translation, because only v3.1.4 wrote a campaign product this
   project holds.
2. **GNU Octave running the unmodified MATLAB source.** Octave executes MATLAB code with MATLAB's
   integer arithmetic, so each routine runs as its authors wrote it and the port is asserted
   against that real output, with no hand-transcribed expected values. The routines UIOOPS ships
   only as compiled binaries compile from their C++ sources under Octave's MEX compiler. The
   reference outputs that do not depend on campaign data are committed, so a fresh clone runs those
   comparisons with no Octave; the rest are not distributed and their tests skip with the reason.
3. **Documented semantics and pinned tests**, for the little neither layer reaches.

Where Octave and MATLAB genuinely compute differently (one accumulator in `mean`, one
colon-operator fill order), the port follows MATLAB by default and exposes an opt-in switch that
reproduces Octave, used only so an Octave reference output can be compared to the last bit. Every place the
two were found to differ is recorded in the developer documentation.

## What the validation establishes, and what it does not

**It established**, for the earlier v3.1.4 translation: that on the field-campaign 2D-S flights
listed on [Validation](04-validation.md), it wrote the `Counts` and `Size Distribution` UIOOPS
wrote — cell by cell, every residual attributed — and that each pure-MATLAB routine in the chain
matched Octave running the original. **It establishes**, for the v3.5 engine in this package: that
each routine, and the whole framing stage on a real flight cut, matches Octave running v3.5's own
source.

**It does not establish:**

- **That the science is right.** Matching the original inherits its physics, thresholds and
  defects. The findings and enhancements argue "right"; the validation only says "the same".
- **That a v3.5 number matches any campaign product.** No archived product was written by v3.5, so
  the v3.5 engine is validated against Octave, never against the archived product.
- **Anything outside the conditions tested.** The archived pairs are warm marine stratocumulus.
  For habit, hollowness and shattering — the routines that matter most in ice — the evidence is
  Octave on constructed input. Probes with no raw-plus-product pair (2DC, 2DP, CIP, PIP) are
  Octave-checked but pinned to no real archive, and the HVPS does not reproduce its archived product.
  [Known gaps](10-known-gaps.md) keeps the full list.
- **That another chain agrees.** SODA-2 and ADPAA products are an independent cross-check on the
  physics, never a bit-fidelity target: only files UIOOPS wrote can adjudicate a UIOOPS port.

In practice: cite the [Validation](04-validation.md) results for *does the method reproduce the
archive?*, the v3.5 engine as
Octave-equivalent for *what does current UIOOPS compute?*, and an enhancement's A/B table for *how
much does this correction change?*
