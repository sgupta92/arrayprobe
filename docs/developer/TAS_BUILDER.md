# The TAS sidecar builder: what `make-tas-file --from-tas-csv` does to the S2 series

This page covers the builder's behaviour only. The full account of how TAS reaches the pipeline is
[`TAS.md`](TAS.md). Code: `src/arrayprobe/tools/make_tas_file.py`. Tests:
`tests/test_make_tas_file.py`.

## Why the builder reduces at all

The [S2](../11-glossary.md#pipeline-stages-and-test-terms) (decode stage) `.tas.csv` carries sub-second, jittered times (`124834.999`, `124838.000`, ...).
`imgProc_sm.m:727` (`src/arrayprobe_uiops/imgproc_core.py:32`) matches each image record's integer HHMMSS against `Time`
by exact equality. A fractional `Time` therefore almost never matches, and every record takes
the 170 m/s fallback (`src/arrayprobe_uiops/imgproc_core.py:14`). Measured for every finished
v3.5 product of one 2017 campaign. A
repeated integer `Time` makes MATLAB fail at `:738`, and the port raises there too. The engine's
behaviour is faithful and is not changed. The remedy is in the builder, in three parts.

1. **Every file is checked before it is written.** `write_tas_file` refuses a `Time` that is
   non-finite, non-integer or repeated.
2. **The series is reduced to whole seconds.** The rule is `--second-rule`, default **round**:
   `floor(sod + 0.5)` on seconds of day, so the carry across a minute is correct. The
   alternative is `floor`. Round is used.
3. **Duplicates are resolved from a neighbouring second.** The true airspeed of the
   previous or the next second is compared with each duplicate, and the duplicate that
   matches it is kept.
   "Previous or next" is `--neighbour`, default **adjacent**: the second just before or just
   after. The alternative is `nearest-present`.
   - All candidates identical: one is kept.
   - Exactly one distinct candidate equals the neighbour's TAS: that candidate is kept.
   - Several candidates match, none matches, or there is no neighbour: the second is
     **unsettled**. `--on-unsettled` (default **default**) gives it `--default-mps`, so a
     file is still written; `refuse` keeps the earlier behaviour -- no file is written, the tool
     lists every such second with its candidates and whether an adjacent second is missing, and
     prints `a choice is needed`. It does not guess either way. One option is recorded
     for later and is not implemented: give the non-matching duplicate to the missing
     adjacent second, as the probe's cumulative-distance counter (column 3) suggests.
   - A neighbour second that holds several distinct values counts as having no known TAS.

## Out-of-range TAS: never dropped, a configurable default

Nothing is dropped. A row is out of range when it is above
`--cutoff-mps` (default **300 m/s**, `DEFAULT_CUTOFF_MPS`), at or below 0 m/s (catches the
decode's `-999` "no TAS" marker) or non-finite. An example of the first is 241403 m/s at 163120
of `base170821110122`. Such rows are set aside before the reduction; a second left with no
usable row -- or an unsettled duplicate under `--on-unsettled default` -- takes `--default-mps`
(default **170 m/s**, `DEFAULT_FALLBACK_MPS`, `imgProc_sm.m:365`/`:763`'s own [S3](../11-glossary.md#pipeline-stages-and-test-terms) (framing stage) fallback). Both
values are options (`[tas]` in a run configuration, or `--cutoff-mps`/`--default-mps` here), never
hard-coded; the 300 m/s default is the largest `tas_max` in UIOOPS's probe table
(`constants.py:492`, `:559`).

## What is printed and what is recorded

The builder prints these lines on every run:

- one line naming the rules in force;
- `TAS out-of-range row(s) set aside: <HHMMSS> ...` when other rows still cover the second;
- `TAS substituted: <HHMMSS> <orig> -> <default> m/s (<reason>)` for a second that takes
  the default -- out-of-range with no row left, or an unsettled duplicate;
- `TAS duplicate resolved: <HHMMSS> class=... kept=... candidates=... prev=... next=...`
  for each resolved second;
- one summary line.

The same decisions are written into the file's global attributes: `tas_source`,
`tas_second_rule`, `tas_neighbour_rule`, `tas_duplicate_rule`, `tas_duplicates_resolved`,
`tas_duplicates_resolved_seconds`, `tas_unsettled_rule`, `tas_policy`, `tas_cutoff_mps`,
`tas_default_mps`, `tas_policy_note`, `tas_substituted_count`, `tas_substituted_seconds`
(`HHMMSS:reason,...`) and `tas_out_of_range_rows`. The
engine reads only `Time` and `TAS` (the v3.1.4 engine's TAS reader, not included in this release), so these attributes change no computed
number.

## Sources beyond the probe csv, and the SODA-2 pth file

`--from-merge NC` / `--from-aircraft NC` name a campaign merge file or another registered
aircraft file outright; `--chain {auto,merge,aircraft,probe}` resolves one through the
source chain instead (needs `--date YYYYMMDD` and `--search DIR`, repeatable, and/or
`--probe-csv CSV`). `--soda2-pth CSV` additionally writes the same series as a SODA-2 `op.pth`
ASCII file. The chain, its registry and the run-time `[tas]`/`--tas-*` selection are covered in
[`TAS.md`](TAS.md#7-the-tas-source-chain), "The TAS source chain" -- this page stays about
`--from-tas-csv`'s reduction of the probe's own housekeeping series.

**Not yet done here:** echoing these attributes at stage 3 and in the `.call` stamp for the
plain `--tas-file` path. The chain path (`--chain`/`--tas-source`) carries its own stamp
(`ChainResult.stamp()`); see `TAS.md`.
