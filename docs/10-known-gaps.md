# Known gaps

**In short:** every case either engine does not port raises an exception naming the source line
it would need; none guesses. The one result that does not fail loudly is the HVPS particle count,
which disagrees with an archived product and carries a runtime warning. Everything else here is a
refusal with a workaround, or a limit of the method rather than the port.

**See also** [Reference](08-reference.md#validation-status) for what is complete.

## UIOOPS v3.5 (the default engine)

The engine refuses these cases, each where the original MATLAB itself dies or needs a file no
release ships.

| Refused | Raised by | What it means for you |
|---|---|---|
| 2DP without `tas_max` | `sizedist.run` (no release assigns `tasMax` for 2DP) | Pass the airspeed ceiling from your instrument's specification as `tas_max=` (`--tas-max`); the code path is in place and there is no default |
| Probe type 0 with shattering re-acceptance or `iaThreshType = 2` | `arrayprobe_uiops/sizedist.py:740`, `arrayprobe_uiops/sizedist.py:1467` (`int_arr3`/`int_arr2` never assigned) | MATLAB dies here too; choose another shattering option |
| `applyIntArrThresh = 1` with no `intar_threshold` assigned | `arrayprobe_uiops/sizedist.py:788` | MATLAB dies here too; supply a threshold file |
| The whole-workspace `.mat` dump (`save_workspace_mat`) | not offered: no option exists, see `arrayprobe_uiops/sizedist.py:86` | Nothing reads it; the netCDF output is complete without it |
| `--chunks` with `iQC = 1` (v3.5) | `run_flight.py` | Run that file unchunked; output is identical, only slower |

**PECAN projects take a parameter file you supply.** `getPECANparams.m` ships in no release, so
`sizedist.run` stops on a PECAN project until you pass `pecan_params=` (`--pecan-params`): a CSV
of spiral `start_s`, `end_s` and `intar_threshold_s`, the format the refusal message names
(`arrayprobe_uiops.pecan_params`). This is an input, not a gap the package pursues.

**The v3.1.4 port is not in this package.** It is the separate validation anchor that reproduced
the archived products; this package ships the v3.5 and SODA-2 engines, so use v3.5 for new
data.

**v3.5 has no reference pair and cannot get one.** No archived product was written by v3.5, so it
is validated against Octave runs of its own sources (whole-program reference outputs, zero disagreeing
items; the `imgProc_sm` reference output is distributed, the `sizeDist` and combine reference outputs are not). The ellipse fit (`iRectEllipse=1`) agrees with the compiled CGAL binary within 1e-2 on the
axes and 1e-3 on the angle, not exactly.

## SODA-2

The driver (`arrayprobe soda2 run <config>`) runs the SPEC path and the CIP/PIP path under the SEA
and DMT formats end to end. Reprocessing from an existing PBP file is ported
(`arrayprobe_soda2.reprocess_pbp`) and reached from Python, not the CLI.

| Not ported | Raised by | What it means for you |
|---|---|---|
| Particle-image output (`ncdfparticlefile == 2`) on the parallel driver (`jobs > 1`), or for an image chunk of fewer than two slices | `PbpImagesNotPorted` (`process_2d`, `pbp_writer`) | Run with `jobs=1`; the serial driver writes the images |
| More than one raw file per run: SPEC, or any format with `jobs > 1` | `process_2d` | SPEC stops where the IDL does; DMT/CIP/SEA run serially (`jobs=1`) |
| SEA/DMT probe types other than CIP (CIPG, 2DC, 1D2D, HVPS, HAIL), other `op.format`, `probetype == "2DC"` | `process_2d`, `processbuffer_cip`, `particlesort` | Run these probes on UIOOPS |
| Compressed (`.gz`) raw input: indexing is ported; the SPEC/2D-S buffer read is not, and `process_2d` keeps the upstream reopen without decompression | `read2dbuffer`, `process_2d` | Decompress first |
| `greythresh`, `restore_slice` | `processbuffer_tail` | Leave at defaults (no SPEC probe sets them); `rakefix` is ported (`fixraking`, matches GDL) |
| 1D2D housekeeping in the ASCII export with non-integer edge-reject fields; `pthfile` and non-numeric `noskip` in the netCDF export | `export_ascii`, `export_ncdf` | No driver path reaches them |

**`aspect_ratio.pro` is checked with a stand-in above two slices.** GDL has no `ERODE`; those cases
run against a shim with an unconfirmed border rule, labelled `zero_outside_shim_unconfirmed` and
not counted as oracle evidence; the border rule is being settled from IDL's documentation of
`ERODE`. SODA-2 is compared beside UIOOPS, never used as its oracle.

## HVPS particle counts disagree with an archived product

**Do not publish HVPS counts or concentrations as validated output.** The UIOOPS HVPS chain lands on
the archived product's exact time grid and bin ladder. Under one fixed inter-arrival call, the 1 µs
default for every flight, it accepts a different number of particles, by a different factor per
flight; the per-flight call that matches the archive is described below the table:

| Flight | Ours | Archived | Ratio |
|---|---|---|---|
| 2016-09-06 | 41,601 | 33,543 | 1.2402 |
| 2017-08-13 | 17,470 | 16,094 | 1.0855 |
| 2017-08-26 | 9,150 | 9,162 | 0.9987 |

The difference is in the accepted particle set, in a minority of seconds where the archive's reject
ratio is higher; the 2D-S, through the same chain, reproduces exactly.

**What is inferred: the HVPS inter-arrival thresholds.** The archived HVPS products were written in July 2020 by a campaign variant of UIOOPS
(its `sizeDist.m:64` reads a per-flight inter-arrival threshold file), and no threshold
file from that run survives. The archive's counts are matched under one of two calls per flight:
the 1 µs default on 2017-08-26 (0.9987) or the port's own threshold file on 2016-09-06 (1.0043).
Nothing in the data decides which call a flight got, so this is a per-flight run configuration,
inferred by comparison with the archive and recorded with the output, not an independent
reproduction. The 0.43 % residual on 2016-09-06 sits in the blocks where the fits agree and its
cause is open; 2017-08-13 is untested under the call its job log records. Across all six 2016
flights, with the port's threshold file fitted in five blocks, four flights (2016-09-06, -12, -14
and -20) match the archive to within 0.5 %; 2016-09-10 (+9.96 %, its blocks fitted across two raw
files) and 2016-09-25 (−69.7 %) stay open.

**The Octave oracle's limit.** The unmodified `IntArrAnalysis_time.m` under Octave writes the
port's thresholds in all five blocks on 2017-08-26 and in blocks 2-5 on 2016-09-06. Block 1 of
2016-09-06 differs (Octave 2.5653e-4 s, the port 4.12125e-4 s) because Octave ignores the fit's
`'Robust','on'` (the campaign variant's `IntArrAnalysis_time.m:153`) and the port honours it; with the
robust option off, the port gives Octave's threshold exactly. Octave therefore cannot confirm the
robust fit MATLAB ran. The archive favours the port's value: under it, block 1's hours differ from
the archive by one particle. **What would settle it:** the threshold file from the archive's own
run, which does not survive; for the robust fit alone, re-running 2016-09-06 with Octave's block-1
threshold — if block 1's residual grows, MATLAB's threshold is the robust one (not yet run).

## Open limits and what would close them

Five limits, each stated with its cause and what to do. The first two are inputs you supply, not
gaps the package pursues; the last three need an input from outside the package.

| Limit | Why | What you should do | Status |
|---|---|---|---|
| PECAN projects need a parameter file | `getPECANparams.m` ships in no release, and the package holds no PECAN data | Supply the spiral CSV as `pecan_params=` (`--pecan-params`) | Closed: a user input |
| 2DP has no airspeed ceiling | No release assigns `tasMax` for 2DP; the code path is in place, and the one real 2DP file held (ACE-1, 1995) has had only its reader checked | Pass your instrument's ceiling as `tas_max=` (`--tas-max`) | Closed: a user input |
| SODA-2 `ERODE` border rule unconfirmed | GDL has no `ERODE`, so `aspect_ratio.pro` above two slices is checked against a shim, not counted as oracle evidence | Treat SODA-2 aspect ratios of images longer than two slices as unconfirmed | Open: settled from IDL's documentation of `ERODE` first, then `ERODE` run under IDL on a few small images if needed |
| HVPS counts match the archive only under an inferred configuration | Under one fixed call, 1.24, 1.09 and 1.00 times the archived count on three flights; under a per-flight call chosen by comparison, within 0.5 % on four of the six 2016 flights and on 2017-08-26, with 2016-09-10, 2016-09-25 and 2017-08-13 open; the matching configuration is inferred, not recovered (section above) | Do not publish HVPS counts or concentrations as validated output | Open. |
| No reference pair for CIP, PIP, 2DC or 2DP | No archived raw plus UIOOPS-processed pair is held; these paths were checked only against the original code under Octave, during development (reference outputs not distributed) | Treat their output as faithful to the original code, not validated against an archived product | Open until one pair per probe arrives, CIP first |

## Other limits

- **A fitted inter-arrival threshold needs `scipy>=1.16`.** Below it the tau-derived threshold
  lands 47.6 % from the Octave reference ([Installation](01-installation.md)); the default call
  uses the fixed per-probe value and is unaffected.
- **Parallel decoding can die at worker start-up on Windows** (`WinError 6`, `BrokenProcessPool`).
  It is opt-in (`--s2-jobs`, `--jobs`); `run_flight.py` retries, then falls back to the
  byte-identical serial decode and records it in a `.decode` sidecar. Root cause not established.
- **Method limits however faithful the port.** O'Shea et al. (2019, *AMT* 12, 3067–3079) advise
  against monoscale OAP data below ~100 µm, above this package's ≈55 µm used-bin floor
  ([Glossary](11-glossary.md)); McFarquhar et al. (2017, *Meteor. Monogr.* 58, ch. 11) report UIOOPS
  and OASIS sizing one particle up to 20 % apart; Jaffeux et al. (2022, *AMT* 15, 5141–5157) report
  58.2 % (2D-S) habit agreement between a classifier and ten scientists' majority label, which
  bounds visible algorithm–human agreement and is not an inter-annotator figure.
