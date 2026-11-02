# Release notes — arrayprobe

Release notes, in [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) shape.

**What belongs here:** what a user of the package needs to know. What changed, and whether it can
change their numbers. Design reasoning lives under `docs/developer/`.

**Does it change my numbers?** Each entry says so. Unless an entry says otherwise, no default
run and no validated flight is affected.

This is the first public release, 0.1.0.

## [Unreleased]

## [0.1.0] - 2026-11-02

### Release summary — **0.1.0**

**What it contains.** Two engines behind one driver: the UIOOPS engine, a port of UIOOPS v3.5
and the default for new data, and the SODA-2 engine, the independent second opinion. The earlier
port of UIOOPS v3.1.4, the anchor that reproduces archived UIOOPS products, is the validation
reference and is not part of this package. See the "Choosing an engine" documentation page.

**Validation.** Each engine is checked against the original it reproduces. The v3.1.4 port, kept outside this
package as the validation anchor, reproduces archived MATLAB products cell by cell — on one flight 33,027 of 33,027 cells, with
15,987,236 particles matching to the particle; the v3.5 and SODA-2 engines match their original
sources executing under Octave and GDL; and SODA-2 beside an independently archived SODA-2 output
accepts 18,017 particles against 17,817 on one flight (figures in `docs/04-validation.md`; the
SODA-2 comparison in `docs/developer/SODA2_BESIDE_UIOPS.md`).

**Citation.** SODA-2 is cited as Aaron Bansemer. (2026). abansemer/soda2: v2.26.0 (Version v2.26.0) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.18331418 — the form its author, Aaron Bansemer, provided (2026-10-06); `CITATION.cff` carries it as a reference.

**Corrections on by default (engine 3.5 only; the v3.1.4 validation port never applies them).** Detail in
[`docs/developer/TWO_ENGINES.md`](TWO_ENGINES.md).

| Correction | Probes | Opt-out |
|---|---|---|
| Stray-pixel removal before sizing | every engine-3.5 run | `--stray-pixel off` or `[enhancements] stray_pixel_fix = false` |
| 2D-S sized on the 2D-S bin table, not HVPS's | 2D-S whose project name falls to v3.5's `otherwise` branch | `--protective off` or `[enhancements] bin_table_fix = false` |
| Particle-clock offset derived from the data | probetype 1 (CIP/PIP) outside UIOOPS's clock-offset table | `--protective off` |
| Zero-sample-volume seconds written `NaN`; duplicated seconds moved into the gap | probetype 2 (2D-S/HVPS) | `--protective off` |

**Corrections on by default for probes with no archived product.** On CIP/PIP, 2DC/2DP and
Fast2DC the driver also writes each of these as a separate `enh` product, recorded in the `.call`
stamp; `--protective off` skips them, and the 2D-S/HVPS lineage that reproduces archived products
never gets them. Detail in [`enhancements_uiops/docs/CORRECTIONS.md`](../../enhancements_uiops/docs/CORRECTIONS.md).

| Correction | Probes |
|---|---|
| Glitched header times dropped before they cascade into a 24-hour time error | CIP/PIP |
| `particle_time` recovered from its 8-bit integer collapse | 2DC/2DP, Fast2DC |
| Duplicated airspeed seconds collapsed onto a regular one-second grid | CIP/PIP, 2DC/2DP, Fast2DC |

**Limits of this release.**
- The engine and package rename follows in a later release; import names are unchanged here.
- Re-validation of the archived reference flights on current code covers 13 of 14, not counting the
  product of record.
- The held-out synthetic-dataset test is pending.
- Known gaps needing outside input: PECAN runs need a user-supplied parameter file; 2DP needs a
  user-supplied `tas_max`; SODA-2's `ERODE` border rule is unconfirmed under GDL; HVPS counts
  match the archived product only under a per-flight inter-arrival call inferred by comparison
  (within 0.5 % on four of the six 2016 flights and on 2017-08-26; 2016-09-10, 2016-09-25 and
  2017-08-13 open), while one fixed call gives 1.24 and 1.09 times the archived count on two
  flights; the archive's per-flight configuration is not recorded, so HVPS counts are not
  quoted as validated; CIP, PIP, 2DC and 2DP have no raw-plus-product reference pair, so they are
  checked at code level only. See the "Known gaps" documentation page.

**What changed.** This is the first release of the package, so there is no earlier release to
compare against: everything above is new in 0.1.0.

**Does it change my numbers?** Not applicable: there are no earlier released numbers for this
release to change.

### Added

- `arrayprobe inventory` lists every raw input with its size and flags empty or truncated files.
  The driver runs the same check before decoding: an empty file is refused unless
  `--accept-flagged` is given, a file ending in a partial record is decoded with a warning, and
  the run's `.call` stamp records what was found.
- `arrayprobe reproduce-report` writes a report of what a run used and produced, for checking a
  result against another run.
- `arrayprobe check-counts` and the `count_closure` module show, second by second, that the binned
  counts add up to the accepted particles, with every excluded particle attributed to its reason.
  The comparison against a probe's own reported total is not available yet.
- `arrayprobe attributed --layout particles` writes one Parquet row per particle (needs the
  `[parquet]` extra); the default per-dimension layout is unchanged.
- Triage: an optional habit label per particle, from the UIOOPS v3.5 habit vocabulary, and the
  agreement between two reviewers as Cohen's kappa.
- Documentation: an "Add a campaign" page with a worked example whose output is checked by a
  test; inventory, particle-layout, reproduce-report and count-closure sections; the opt-ins
  notebook shows `--accept-flagged`; the installation page explains how to verify a download.
- Release workflow: build-provenance attestations (Sigstore) for every distribution file,
  checkable with `gh attestation verify`.
