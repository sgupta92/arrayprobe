# Design docs — index

**17 files.** Each describes what is true now.

**Where to start, by who you are.** Someone deciding whether to *adopt* the package reads the repository `README.md`,
then [`COVERAGE_MATRIX.md`](COVERAGE_MATRIX.md) (can it read my data) and
[`ADOPTING_ARRAYPROBE.md`](ADOPTING_ARRAYPROBE.md) (what it will do to my numbers) — laid out as one
path for using it on your own data. `TWO_ENGINES.md` answers the next question most people ask
(which engine do I want). The rest are reference pages: reach for one when you already know which
question it answers.

| File | What it is |
|---|---|
| `HISTORY.md` | The project's change history, release by release. |
| `OCTAVE_AS_ORACLE.md` | The methodology answer to "but Octave isn't MATLAB" — where it is trusted, where it is not, and the falsification recipe. |
| `SPIF_INTEROP.md` | Whether to write the community Single Particle Image Format, assessed rather than planned. States what our two image layers are, and — from the specification itself — that SPIF's `core` group is pre-framing, confirming this project's own reasoning and settling it as one writer, at S2. Its two narrower questions are closed, from SPIFpy's own real writer source: neither config provenance nor the stuck-diode mask is representable in the current schema, so a writer would need a companion `.call`-style sidecar for both. |
| `ATTRIBUTED_EXPORT.md` | The attributed second output: a self-describing sibling written beside a faithful product, carrying the whole `.call` sidecar and a sourced unit on every variable, so a recipient can re-derive the number from one file. The faithful file is never modified. |
| `TWO_ENGINES.md` | The one-page user answer on what the shipped v3.5 engine is validated against, how it relates to the earlier v3.1.4 translation (not shipped) that reproduced archived products, and what a user may rely on from v3.5's Octave-only validation. |
| `UPSTREAM_REVIEW.md` | What the review of the upstream UIOOPS and SODA-2 code is, where it is kept, and what it means for a user of this package. |
| `COVERAGE_MATRIX.md` | Which probe runs under which engine in which mode, **generated** from the code and from real runs rather than asserted in prose, so it cannot drift from what the package does. Each cell is validated / cross-checked / unvalidated / deliberately refused / refused-as-a-defect / untested, and a cell that cannot be filled by measurement says `untested` rather than guessing. |
| `ADOPTING_ARRAYPROBE.md` | The page for a potential user deciding whether to adopt the package — not a fidelity audit or a changelog. What the newest completed correction (image-assisted CIP) does to a user's own numbers, whether any correction is on by default (checked against `registry.py`: none is), the coverage-matrix headline, and the speed figures, each labelled with its scope and sourced to `COVERAGE_MATRIX.md` / `SPEED.md` rather than retyped. |
| `SPEED.md` | **The single source of truth for every speed claim.** Each measured speedup with the scope that must travel with it (probe, stage, file, core count, what was held identical) and the byte-identity test behind it; the opt-in paths that ship byte-identity-tested but have **no published multiplier**; where parallelism is refused and whether that is genuine or untried; and the trap named &mdash; no figure here supports "arrayprobe is N&times; faster". Outward surfaces quote from here so a number cannot drift between them. |
| `TAS.md` | **True airspeed, end to end**: what it is; where it enters S3 (exact-match lookup, silent 170 m/s fallback), S4 (the probe's own series, sample volume) and SODA-2; `tasMax` per probe versus the fallback; every known per-source issue (sub-second S2 times, duplicated seconds, corrupt rows, the stuck 6 m/s on one flight, CIP knots); a worked case of sub-second times in a `.tas.csv`; each decision with where it is announced. |
| `TAS_BUILDER.md` | What `make-tas-file --from-tas-csv` does to the sub-second S2 TAS series: the whole-second reduction (rounding), the duplicate rule (adjacent neighbour, ambiguous seconds refused), the >300 m/s drop (`--cutoff-mps`, default 300 m/s), and the log lines and netCDF attributes that record each decision. |
| `LABELLING_PROTOCOL.md` | **How an eye-adjudication pass is run when there is no product of record and no truth**. The queue built from *chain disagreement*, one seeded sample per (UIOOPS verdict, SODA-2 verdict) cell rather than at random; how many labels a cell needs and why the ~20-to-hundreds extrapolation, not the Wilson interval, is the dominant uncertainty; the four-verdict vocabulary with `unsure` counted and kept out of every denominator; the provenance a label set carries, pinned to a proc by sha256; per-cell reporting with n, never pooled; the four failure modes and what is done about each. Every claim tagged measured / derived / read, and each gap marked **not established** rather than filled — including that `reviewer` and `queue` are null on every existing label because no rendered page posts them. |
| `ARM_OUTPUT_FORMAT.md` | A design document, no code changed: what it would take to treat "ARM Data File Standards conformant output" as a first-class fourth output category alongside UIOOPS, SODA-2 and the port's own `.call`-stamped files. Reads the existing `arm_export.py` implementation against the actual ARM standard, names the gaps precisely, and proposes closing them without inventing anything not already in the standard or the repo. |
| `PACKAGE_README.md` | The short pointer README that `pyproject.toml`'s `readme` names, because packaging metadata needs a file inside the project root; it carries no counts and sends the reader to the repository-root `README.md`. |
| `SODA2_BESIDE_UIOPS.md` | What each package is and who wrote it, the GPLv3/3-clause-BSD licence split and its consequence for how the packages are structured, the two pipelines mapped stage by stage, shared-concept terms across both names, which engine to reach for, and why a chain-to-chain disagreement is a finding to investigate, never proof one chain is wrong. |
| `CONSTANT_PROVENANCE.md` | Every physical constant and lookup table in the port, with the MATLAB `file:line` it is taken from and its published source — stated only where the MATLAB names one or a repo-cited paper was opened; otherwise "unverified". `tests/test_constant_provenance.py` opens every cited line and checks the value is on it. |

## Elsewhere

| Where | What |
|---|---|
| `probes/` | One page per probe type, with its own index. |
| `../../enhancements_uiops/docs/` | The opt-in corrections: `CORRECTIONS.md` (a part per module), plus the ML, config and applicability documents |
| `../../docs/` | Sources for the public documentation site; `docs/` is generated and never edited by hand |
