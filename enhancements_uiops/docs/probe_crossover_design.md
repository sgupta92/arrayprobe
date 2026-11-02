# `probe_crossover.py`, and design notes for morphology-specific PSDs

Written 2026-09-14. The missing-work inventory names two items from the development plan:
a 2D-S/HVPS crossover diagnostic, which is built and described in Part 1; and
morphology-specific PSDs from habit codes, for which Part 2 gives design notes only.

## Part 1 — the crossover diagnostic (built)

### What was there before

No UIOOPS release merges two probes. `combine_sizedist.m` (`arrayprobe.combine`, and
`arrayprobe_uiops.combine`, which borrows it) stitches one probe's several `sd` files into one
flight product. A 2D-S and an HVPS product therefore sit side by side, and a user who merges
them does so outside UIOOPS with no check. Before this module, no code in the repository
compared two probes: a search for `crossover` found only the midnight date-crossover logic and
`intarr_threshold_fix`'s inter-arrival crossover. SODA-2's `merge_spectra.pro` does merge two
probes at a fixed crossover size (default 1000 µm, `:10`). It warns when the crossover is not a
common bin edge (`:48-49`) but tests no agreement.

### Decisions

| # | Decision | Why |
|---|---|---|
| 1 | Compare **integrated number concentration over one range**, not bin by bin | The two ladders differ (10 µm and 150 µm in the field-campaign data). A per-bin comparison would need one ladder re-binned onto the other, which assumes a within-bin distribution. |
| 2 | **Snap the default range to shared edges** | In the field-campaign data every HVPS edge from 0.075 to 1.275 mm is also a 2D-S edge (measured), so each bin lies wholly inside or outside the range. A caller range that cuts a bin gets a fractional weight, which assumes a uniform spread inside that bin, and the result reports `edges_aligned = False`. |
| 3 | Take counting error from `count`, per bin: `sigma_b = n_b / sqrt(C_b)` | `count` is `dist_minR * binwidth / 10` (the engines' size distribution, the `"count"` output): the tally `conc_minR` is divided out of. So `n_b / C_b` is that bin's inverse sample volume, and the relation is `poisson_uncertainty.per_bin_absolute_uncertainty`, reused rather than rewritten. |
| 4 | Test the **log ratio**, with delta-method error `sqrt(1/K_a + 1/K_b)` | This is symmetric in the two probes and independent of units. The effective count `K = N^2 / var` equals the plain summed count when every bin shares one sample volume (tested). |
| 5 | Report `insufficient`, not `disagree`, when either probe has fewer than `min_count` effective particles, **including zero** | A probe that counted nothing carries no sample volume from which to predict its expected count. The one-sided case (500 particles against 0) is therefore not tested, and the module says so. |
| 6 | `z_threshold = 3`, `min_count = 10`, both stated as conventions | No paper sets either value. With thousands of seconds tested, `expected_false_flags` (`n_tested * erfc(z / sqrt 2)`) gives the chance level. A seeded 40,000-second simulation from one true concentration flags within 5 sigma of that level (tested). |
| 7 | `window_s` pools seconds, using only the seconds where both probes are present | In the field-campaign data the meaningful overlap (above the HVPS's first bins) is too sparse per second. A block's mean has variance `sum(var) / m^2`. Dropping one probe's missing second from the other keeps the two averages over the same instants (tested). |
| 8 | Refuse to mix an `sd` file (HHMMSS time) with a combined product (datenum time) | The two time keys cannot be aligned without a flight date, which the `sd` file does not carry. |
| 9 | No pipeline adapter, and no opt-in flag | It compares two probes' files, while a run processes one probe. It writes nothing and plugs into no pipeline, so there is nothing to default OFF. Registered at `stage="sd"` with a named no-adapter reason in `pipeline.py`. |

### Engines

It reads six variables (`time`, `bin_min`, `bin_max`, `bin_dD`, `conc_minR`, `count`), which
both `sizeDist` translations write under the same names. `test_v35_inputs.py` sweeps the
registry's `consumes` against the v3.5 demo `sd` file. `test_probe_crossover.py` reads the
v3.1.4 and v3.5 goldens and checks the per-bin concentration against `netCDF4` reading the
same variables oriented by dimension *name*, a different route from `ncio`'s. It also builds a
combined product from the v3.1.4 golden with `arrayprobe.combine.combine_sizedist` and reads it
back to the same numbers.

### Real-data consequence (one pair)

This was measured on 2016-09-06, the only flight held with both a `2DS_H_current` product and
an HVPS product. The numbers are in `enhancements_uiops/README.md`. In short: over the full shared
range the 2D-S exceeds the HVPS in 287 of 290 tested seconds, and the HVPS exceeds the 2D-S in
none. The excess sits in the HVPS's one- and two-pixel bins. Above 0.375 mm the flight-average
ratio is 1.63 with z = 2.7, which is within counting statistics. Above 0.525 mm the 2D-S holds
no particles on this flight. The field campaign's 2D-S ladder ends at 1.285 mm, so Schima et al.'s
1–1.6 mm overlap does not exist in this data.

**How this bears on the HVPS over-count question** (known gaps). That question compares
the port's HVPS run against the archived HVPS, one probe through two chains. This diagnostic
compares two probes. On this one flight the archived HVPS is never higher than the archived
2D-S in a tested second, which is a fact about the archive and does not settle the port's
over-count.

## Part 2 — morphology-specific PSDs from habit codes (design notes only, not built)

**Source.** The plan's literature row for Jaffeux et al. (2025, *AMT* 18, 2311–2331) describes a
five-step recipe that turns per-particle habit labels into morphology-specific PSDs: normalise
the class fractions per bin, then apply them to the routinely processed total PSD. The row adds
that this "works with the port's *existing* Holroyd codes today, no ML needed". The paper itself
was not re-opened for these notes, so the five steps are not restated here. That is the first
item for whoever builds this.

**What UIOOPS already writes.** `sizeDist` already writes a habit-resolved number PSD, `habitsd`
(`Time × CIPcorrlen × Habit`, ten habits in `HABIT_ORDER`). It bins each particle on the same
diameter as `conc_minR` (`sel.diameter` and `sel.diameter_minR` are both `d_all[locs]`,
the earlier translation's `_Selection` construction), and normalises it by the same
per-bin sample volume (`svol2a`, the `svol2_t` repeated ten times). **Measured on both tracked
goldens:** summing `habitsd` over habit reproduces `conc_minR` bit-exactly on the v3.1.4 golden
(4 non-zero cells) and within 3.5e-18 cm⁻⁴ on the v3.5 golden (11 non-zero cells). Both
fixtures are tiny.

**Consequence for the design.** Applied to `conc_minR` itself, the Jaffeux recipe (per-bin
fractions `f_h = habitsd_h / sum_h habitsd_h`, times the total) returns `habitsd` unchanged, so
a module doing only that would add nothing. It has value only where the total PSD is *not* the
one the fractions came from:

1. a **corrected** total, such as `poisson_restore`'s restoration or `conc_arear_fix`'s
   output, where the habit split should follow the correction;
2. a **merged 2D-S/HVPS** total, once `probe_crossover` shows the two agree in a range, where
   each probe's fractions apply on its own side of the crossover;
3. **multi-second aggregates**, where the fractions should be count-weighted (`sum_t habitsd *
   svol`) and not averaged as ratios.

**Open questions, to settle before building:**

- **Which habit scheme?** The v3.1.4 Holroyd codes (`holroyd.m`; habit `'C'` is never emitted,
  a preserved bug) or v3.5's `holroyd_new.m` / Schima et al. (2024) tree, which has
  its own 300 µm and 1 mm floors. The development plan notes that habit codes
  below 300 µm on the 2D-S are not comparable to the modern literature. A per-engine habit map
  belongs in `applicability.py`.
- **Uncertainty.** Each fraction carries binomial counting error, `sqrt(f(1 - f) / C)`, on top
  of the total's Poisson error. `poisson_uncertainty` covers only the latter.
- **Rejected particles.** v3.5 also writes `REJ_habitsd`, so the scheme must state whether
  fractions come from accepted particles only. They should, to match `conc_minR`.

**Size.** One small module, in the same space as `analysis.py`, plus tests on the two goldens
(the `sum_h` identity, which is measured above) and a synthetic corrected total.
