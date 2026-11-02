# What 1.0 promises
> The claims this package makes, the ones it does not, and how to cite each.

**In short:** the v3.5 and SODA-2 engines compute what their original code computes; archived
UIOOPS products were reproduced by an earlier translation of UIOOPS v3.1.4 that is not part
of this package; nothing here claims the science is right.

**See also** [Why reproduce first](26-why-reproduce-first.md) ·
[Choosing an engine](27-choosing-an-engine.md) · [Validation](04-validation.md) ·
[Known gaps](10-known-gaps.md) · [The seven probes](33-probes.md).

## What it promises

| Claim | Engine | Evidence |
|---|---|---|
| Each routine computes what the original MATLAB computes | v3.5 | Octave running the unmodified source; most reference outputs tracked in `tests/data/` run on a fresh clone; those cut from campaign data are not distributed |
| Each ported routine computes what the original IDL computes; an unported probetype or format raises by name | SODA-2 | GDL running the unmodified source; the refusals listed on [API: SODA-2](21-api-soda2.md) |
| An enhancement changes nothing unless you turn it on, and says what it changed | all | bit-identity tests with each enhancement off; the `.call` stamp records what ran |
| Parallel processing gives the same bytes as serial | where offered | byte-identity tests named on [Processing speed](32-processing-speed.md) |
| A run records its engine, profile and corrections | all | the `.call` sidecar beside every product; `arrayprobe run` refuses an input that disagrees with it |
| Every known divergence from the original fails loudly or is listed | all | [Known gaps](10-known-gaps.md) |

## What it does not promise

- **That the science is right.** Matching the original inherits its thresholds and defects. The
  findings and the opt-in corrections argue for better numbers; the validation only says "the same".
- **That a v3.5 or SODA-2 number matches a campaign product.** No archived product was written by
  UIOOPS v3.5, so that engine is checked against Octave, never against an archived product. SODA-2
  products from other chains are a cross-check, not a fidelity target.
- **HVPS counts.** The HVPS chain lands on the archived grid but does not reproduce its counts on
  every flight; the package warns whenever it writes HVPS output ([Known gaps](10-known-gaps.md)).
- **Real-data validation for 2DC, 2DP, Fast2DC, CIP and PIP.** These run and are checked against
  the original code, but no archived product exists for any of them to validate against.
- **Conditions outside those tested.** The archived pairs are warm marine stratocumulus; ice-phase
  routines are checked on constructed input.
- **A stable import path before 1.0.** Module and package names may still change before the 1.0
  release.

## How to cite a number

| Question | Engine to use | What to cite |
|---|---|---|
| What does current UIOOPS compute? | v3.5 | Octave equivalence (`uiops.engine().validation`) |
| What does SODA-2 compute? | SODA-2 | GDL equivalence |
| How much does a correction change? | the engine it ran in | that enhancement's A/B table ([Enhancements](05-enhancements.md)) |
