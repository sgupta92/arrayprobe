# SODA-2 corrections not shipped: what unblocks each

Cite SODA-2 as: Aaron Bansemer. (2026). abansemer/soda2: v2.26.0 (Version v2.26.0) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.18331418

Findings not yet corrected. Of the SODA-2 findings triaged for correction, 14 (10 rows) are
"correction plausible, needs a
design decision or a measurement first". The **Why not yet** column is that triage verbatim; the
two columns after it are this record's. "Developers" means a question for the SODA-2 developers; "maintainers" means a
decision for this package's maintainers.

| Finding | Why not yet (triage, verbatim) | What unblocks it | Owner |
|---|---|---|---|
| the single-precision pi corner count (`!pi` single precision) | fix is clear (double π) but it changes `corners` → `orientation`/`aspr` on **every rectangle-like particle**; ship only after an A/B on the tracked fixtures with the changed-fraction reported (stage 8). Candidate `double_pi_fix`. | **Unblocked and shipped** (stage 8): `double_pi_fix`, opt-in, changed fraction 0 of 28 fixture particles; see `BACKLOG_STATUS.md`. Kept here so the row count matches the plan | -- |
| the mixed-precision aspect ratio, the position-dependent area precision, the single-precision freq (mixed FLOAT/DOUBLE) | last-digit effects; the register itself says "either is defensible". One combined `double_precision` candidate, after the single-precision pi corner count's A/B shows whether anyone would notice. | the single-precision pi corner count's A/B changed nothing on the fixtures, so the measurement that would justify it has to come from a real flight: the per-field changed fraction of a double-precision run on the UND 0914 HVPS-3 comparison. Then a decision whether a last-digit change is worth a correction | maintainers, after S1 |
| the integer TAS exponent (TAS exponent decode) | "reinterpret the two words as IEEE float, or `2.0^exponent`" — two different fixes; needs the SPEC manual's word layout confirmed against a real HK record. | The SPEC 2D-S/HVPS-3 manual's TAS word layout, checked against a real HK record (the UND 0914 raw has HK records) | developers (manual), then maintainers |
| the misattributed pre-housekeeping images + the phantom housekeeping reading (HK attribution before the first HK record / phantom HK reading) | two lines each but they interact; design the pair together, A/B on the S2 fixture. | A design for the pair written first, then the A/B on `s2_spec_raw_fixture` | maintainers |
| the unfilled voltage and temperature columns (TAS gap-fill without paired columns) | the register offers a doc-only fix as an alternative. | A choice between the doc-only fix and a correction | maintainers |
| the late interarrival reject bit (`intcutoff` initialised 0 → bit 2 dead) | needs a **per-probe default value** the register does not state. | A per-probe default `intcutoff`, from the developers or a cited source | developers |
| the oversized multi-buffer frame, the unrolled-back diode offset, the truncated deep-recursion particle (decoder behaviour on over-length runs / split particles) | the register says "needs your design input" for each. | The developers' intended behaviour for each of the three | developers |
| the integer-resolution zero sizes (integer `xres`/`yres`), the FLOAT depth-of-field constant match (DOUBLE wavelength) | latent input-typing hazards; in Python the right shape is an **input validator** in the CLI (stage 10), not a correction. | An input validator in `arrayprobe soda2 run`'s config path -- not a correction here | maintainers (CLI owner) |
| the signed housekeeping time word (HK `time` word) | one word, but no in-tree reader of the tag — nothing observable to A/B. | A reader of the tag, or a real file where it is observable | developers |
| the three NaN reject answers (NaN in three reject criteria) | "two lines, **if you want uniformity**" — which direction is right is the developers' call. | The developers' choice of direction | developers |

## Other items stage 12 was asked to record

| Item | State (2026-09-15) | What unblocks it |
|---|---|---|
| `poisson_fill_guard` (the fill-area Poisson error) | **Shipped**, changes no written value; `BACKLOG_STATUS.md` | -- |
| `TimeInterval` port defect | **Fixed** in the port 2026-09-14 (`TimeInterval`'s field order), pinned in `test_soda2_process_2d_pbp.TimeIntervalFollowsIdlStrmid` | -- |
| `FlushOffsetTrace507` 12-vs-13 artefact | Replaced by a self-consistency proof | -- |
| `ProcessData` op-dtype fidelity: TOML cannot carry an IDL FLOAT `rate` | Open. A FLOAT `rate` still needs a Python call to `soda2_process_2d`; the sidecar's `op_dtypes` records what was used | A typed-value syntax in the `[soda2]` table, or the documented Python route |
| Five corrections the driver adapter does not route (`_adapter.NOT_ROUTED`) | Each callable directly; not applied by `arrayprobe soda2 run` | `rollover_modulus_fix`, `empty_roi_diodegaps_fix`: a function boundary around the inline arithmetic in the port (a byte-identical port refactor, port owner's call). `pbp_inttime_consistent`: the driver passing `interarrival` to the CSV writer (same). `rejection_tally_fix`, `run_diagnostics`: none -- by design they report beside the run |
