# Poisson restoration of falsely-rejected intact particles — design record

Written 2026-09-10.

## Citation, verified against the primary source directly (not a secondary summary)

Korolev & Field 2015, *AMT* 8, 761–777, doi:10.5194/amt-8-761-2015 (open access; fetched and
read as page images — the paper is not held under `developer/literature/` on this machine, so it should be
added there). Exact equations, quoted from the real text:

- **Eq. 1, p. 764** (Sect. 3, opening): the inter-arrival time of intact particles is modelled as
  a Poisson process, `dP(dt)/dt = exp(-dt/tau) / tau`, where `tau = 1/(n*S*u)` — `n` the intact
  particle concentration, `S` the probe's sample area, `u` the true air speed.
- **Eq. 2, p. 764** (Sect. 3.1, "Naturally occurring particles with inter-arrival times shorter
  than the cut-off-time interval"): the probability that two intact particles arrive within the
  shattering cut-off time `tau*` of each other — and are therefore misclassified as one
  shattered pair — is `P2(dt < tau*) = (1/2) * (tau*/tau)**2 * exp(-tau*/tau)`. The text states
  explicitly, directly below the equation, that this probability increases with concentration
  (shorter `tau`) and with the cut-off time `tau*`; both directions are pinned by this module's
  tests.
- **The paper's own proposed use of Eq. 2**, last paragraph of Sect. 3.1, citing Field et al.
  (2006): *"It is possible to attempt to correct for the removal of intact particles using
  Poisson statistics to estimate the fraction of intact particles rejected and then scale the
  remaining intact size distribution."* This is a **population-level scaling correction**, not a
  rule for choosing which specific rejected particles to re-accept — the paper does not describe
  a per-particle restoration method anywhere in Sects. 3–4, so this module does not invent one.

## What the module implements

`enhancements_uiops/src/arrayprobe_enhancements/poisson_restore.py`:

- `mean_intact_interarrival_time(n, S, u)` — Eq. 1's `tau`.
- `poisson_pair_false_rejection_probability(tau, tau_star)` — Eq. 2 exactly.
- `restoration_scale_factor(f)` = `1 / (1 - f)`, and `scale_size_distribution(conc, f)` applying
  it uniformly across bins — the paper's own "scale the remaining intact size distribution",
  literally. Refuses `f >= 1` (the model is undefined there) rather than returning `inf`.
- `large_particle_reacceptance_floor(diameters, floor, rejected_mask=None)` — see below.

## What is NOT resolved here — the >500 µm floor, flagged rather than guessed

The plan row names three possible sources for a ">500 µm re-acceptance floor": Korolev & Field
2015 Eq. 2 itself, Field et al. 2006, and the McFarquhar/Baumgardner monograph ch. 11 p. 11.21.
**Having now actually read Korolev & Field (2015) directly, that paper does not state a 500 µm
figure anywhere.** Its closest related content is on p. 768, in the closing paragraph of
Sect. 4.2.1 immediately above the "4.2.2 Large particles" heading (an earlier revision of this document
placed it inside 4.2.2; the page is right, the section number was one heading out), which
hypothesizes — on
different grounds (Vidaurre & Hallett 2009's finding that shattered fragments are characteristically
tens to hundreds of microns) — that rejected particles larger than **approximately 1 mm** are
more likely intact than shattered. That is a different number and a different argument (a
threshold from fragment-size statistics, not from the Eq. 2 Poisson pair-arrival model), and it is
not itself the >500 µm floor the plan row names — whether the two are the same claim from a
different source, or genuinely separate, is unresolved.

Field et al. (2006) and the monograph page have not been checked against their text. Per this
project's "never invent a fact to fill a gap" rule, `large_particle_reacceptance_floor`'s `floor`
parameter has **no default** — callers must supply a value they have independently confirmed; 500
µm (or any other number) is not hardcoded anywhere in this module. Whoever confirms the citation
should also settle whether Korolev & Field's own ~1 mm figure is the same claim under a different
number, or a distinct finding worth keeping as a second, independent option.

**The monograph page, read 2026-09-14 for `intarr_policy`.** McFarquhar et al. (2017) ch. 11
p. 11.21: *"some algorithms (but not all) reaccept these particles when their size is above a
selected threshold since most shattered particles are smaller than 500 µm (Korolev et al.
2013b,c)."* So the 500 µm figure is on that page, attributed to Korolev et al. 2013b,c — but as the
characteristic size of shattered fragments that motivates "a selected threshold", not as the
threshold itself. `floor` therefore keeps no default. Field et al. (2006) remains unread.

## A cross-cutting finding for row 25 (distance rejection) — RAISED HERE, RESOLVED THERE

This document originally flagged that Korolev & Field (2015) prints `Δx = Δt/u` (p. 765) and
`χ* = τ*/u` (p. 766), both dimensionally inconsistent with a distance, and left open whether that
was intentional notation or an error in the paper.

**Resolved 2026-09-10: it is an error in the published paper.** The full finding, with the three
independent confirmations from the paper's own content, lives in
`enhancements_uiops/docs/distance_rejection_design.md` § "RESOLVED — a finding about the published
paper". In brief: `u` is defined on p. 764 as "the sampling speed" (and `τ = 1/nSu` only yields
seconds on that reading); the same paper writes the identical relation *correctly* in the inverse
direction on p. 764 (`Δt_sh = L_sh/u`, a duration from "the spatial length of the shattering
event along the flight direction"); and its own Fig. 5 plots inter-particle distance and `χ*` on a
~10⁻³–10² m axis, which the printed division form could not produce. The paper contradicts itself
two pages earlier, which is the signature of a typesetting slip rather than a different convention.

Two consequences worth carrying forward:

- **This project's transcription was faithful.** The plan row quoting `χ* = τ*/u` correctly
  reproduces what the paper prints; there was no project-side error to fix.
- **`distance_rejection.py` was already correct** — it implements `Δx = Δt·u`, having declined to
  copy the inconsistent form — so no computed number changed anywhere. The risk that remains is a
  future reader "fixing" the code to match the printed equation, and
  `tests/test_distance_rejection.py::ThePaperPrintsThisEquationWrong` is the guard against it.

This module (Poisson restoration) uses only Eqs. 1–2, which are printed correctly and are verified
above, so nothing here depended on the answer.
