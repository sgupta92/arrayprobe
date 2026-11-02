# For UIOOPS developers
> What porting UIOOPS found about the MATLAB itself — written to be useful without adopting this port.

| | |
|---|---|
| **Findings** | 123, each with `file:line` and how it was established |
| **Stop a run** | 6 |
| **Change a number** | 19 |
| **Clean bills** | checks that found nothing wrong, reported as such |

**See also** [Enhancements](05-enhancements.md) for which have an opt-in correction.

A port is an unusually thorough code review. The upstream-findings list reports 123
findings and several clean bills, each with a `file:line`, how it was established
(**measured** / **derived** / **read**), what it reaches, and a suggested edit. Read-only items
are flagged for your check, never asserted. Much of this code is inherited; several suspicions
that proved wrong on measurement are reported too.

## Some of these you already fixed

The order was: port UIOOPS v3.1.4 bug-for-bug → validate against the archived product, MATLAB's own
output → write up the findings → **then** port UIOOPS v3.5, on a lineage that diverged
from v3.1.4 years ago. Some findings had been **already repaired upstream**, independently, before
this list was sent.

**Nine so far.** Six are set out in the findings document with the v3.5 line and what changed:
**the diode-32 hollow test** (packing diodes 1-32 only, in v3.5 a
whole-array boolean AND), **the int16 diameter saturation** (`int16 × double` collapsing the size — the cast moved to the
read, dated in your own source), **the double-scaled area-ratio concentration** (`conc_AreaR` scaled by the diode size twice, the second
scaling commented out with the reason beside it), **the all-zero image_hollow** (`image_hollow` written but identically
zero, in v3.5 carrying a real value), **the never-emitted habit C** (habit `'C'` unreachable behind a stub, the stub gone),
and **the inconsistent 2DC diode size** (the 2DC diode size disagreeing between two files, reconciled to 0.03). A seventh,
**the late-start hole window** (the hole-position window comparing an index to a span, so a late-starting particle is
never scanned for holes), went in the same rewrite as the diode-32 hollow test.

**Four of the nine were fixed the way this review would have suggested.**

Two more came from porting v3.5's own `sizeDist.m`. **The missing mean-ratio transpose** — the three
`mean_area_ratio`/`mean_aspect_ratio_*` variables and their `REJ_` twins written without the
transpose their neighbours carry (`sizeDist.m:2124`, `:2147`) — is fixed at `:2412`, `:2434`,
under the comment *"Fixed data structure for netCDF export ~ Joe Finlon 02/13/19"*, the same
date as the fix for the int16 diameter saturation. And **the first-event-only reacceptance scan**, which is only half done:

| Finding | In v3.1.4 | In v3.5 |
|---|---|---|
| **The first-event-only reacceptance scan** — the shattering reacceptance loop scans only the first event (MATLAB's `a:b` uses only a vector operand's first element) | `sizeDist.m:1036`, `:1169` | **Fixed in one branch of three** |

**The first-event-only reacceptance scan is still actionable.** v3.5's new 1-Hz threshold branch (`sizeDist.m:1416-1419`) replaces
the bare colon range from `find(rBegin)` to `find(rEnd)` (v3.1.4 `sizeDist.m:1036`) with one
bracketed from the first `rBegin` index to the last `rEnd` index, under a dated comment — repaired on purpose. **The same construct still
stands at `:1213` and `:1346`**, so two of the three reacceptance paths in the current release
keep the defect.

*This set is read, not generated, and is not claimed complete.* Our classifier establishes only
whether a finding's code is *present* in a later release, and a bug rewritten to fix it still
reads as present, so there may be more than nine.

## Verifiable without Python

Every entry is checkable in MATLAB or Octave on your own data. Three examples:

- **A second that appears twice in the TAS file loses all its particles.** `one_sec_times` is
  the TAS grid floored to whole seconds, so two housekeeping packets in one second give two
  identical entries — the first spanning an empty interval while its particle block is still
  consumed. 6.6–18.2 % of the seconds in every file measured are duplicated; on one dense file
  that is 1.2 million particles, and correcting the grid adds 5.9 % to its used bins. To check,
  floor your `.tas.csv` times to seconds and count `diff(sort(t)) == 0`.

- **The last record of every raw file is never a primary.** The decode loop reads the pair
  (*N*, *N+1*), probes one byte for EOF and breaks, so particles beginning in the final record
  are dropped: 0–235 particles per file across 24 raw 2D-S files. In several it is the five-word
  *packet header* that straddles the record end, which the 2017 bounds guards do not cover.
- **`CGAL_EllipseSize` aborts the interpreter on real 2D-S data.** With `iRectEllipse = 1` and
  the real MEX routines, the unmodified `imgProc_sm` dies on the *first* image record: six of its
  sixteen particles are one pixel wide or tall, and a one-pixel shadow is collinear. The first
  five size bins hold 99.4-100.0 % of all particles, so degenerate geometry is common.

## Selected findings

| | |
|---|---|
| **A duplicated true-airspeed second loses every particle in that second** | 6.6–18.2 % of the seconds in every file measured; the archived products show the same loss |
| The zero-image branch abandons a whole image record | measured at 2.35 % of records on a dense file — about 1.6 % of particles |
| `sum_IntArr` and `sample_vol` are rewritten for seconds that accept no particles | 160 of 313 particle-bearing seconds on one flight |
| A file can report `Shattering Algorithm = 'Applied…'` when no shattering rejection ran | the output cannot say which call produced it |
| The Korolev out-of-focus correction is dead code in every tree | the depth and size factor are computed and never applied |
| Reject code `'t'` is unreachable | the looser threshold is tested second, so it never fires; the netCDF description states the two thresholds the other way round |
| `spot_edge(147)` is the literal `0757` — a missing decimal point | bounded consequence, and measured to affect no particle on six flights |

The document also measures what the *fixes* were worth, running pre-fix and post-fix code side
by side: two of the UIOOPS authors' own repairs matter more than their changelog lines suggest, and
one means particle counts in older products are a lower bound, not recoverable from the product.

A companion page for the same audience is among the [published pages](08-reference.md).
