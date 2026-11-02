# The seven probes

One page per probe: what the instrument is, what runs on it today under each engine, the caveats that follow from its own geometry, and the ones a person had to learn.

**Start here if you have raw data and do not know what this package will do with it.** Find your probe, read its page, and the answer is one table down.

| Probe | probetype | diodes x resolution | array reach | default engine, serial | checked against (v3.5) | raw held here |
|---|---|---|---|---|---|---|
| [2DC](34-probe-2dc.md) | 0 | 32 x 25 um | 0.8 mm | CROSS-CHECKED | stage 4 vs Octave running v3.5's sources, synthetic input only | yes |
| [2DP](35-probe-2dp.md) | 0 | 32 x 200 um | 6.4 mm | CROSS-CHECKED | no 2D-P case run; shares the 2D-C's stage-4 path | yes |
| [CIP](36-probe-cip.md) | 1 | 64 x 25 um | 1.6 mm | CROSS-CHECKED |  | yes |
| [PIP](37-probe-pip.md) | 1 | 64 x 100 um | 6.4 mm | CROSS-CHECKED |  | no |
| [HVPS](38-probe-hvps.md) | 2 | 128 x 150 um | 19.2 mm | CROSS-CHECKED |  | yes |
| [2DS](39-probe-2ds.md) | 2 | 128 x 10 um | 1.28 mm | CROSS-CHECKED | imgProc_sm vs Octave running v3.5's sources, 6,819 real field-campaign particles | yes |
| [Fast2DC](40-probe-fast2dc.md) | 3 | 64 x 25 um | 1.6 mm | CROSS-CHECKED | stage 4 vs Octave running v3.5's sources, synthetic input only | yes |

**How to read this table.** *probetype* is the UIOOPS family number that picks the raw reader (next table). *array reach* is diodes x resolution, the width the array images. *default engine, serial* is the UIOOPS v3.5 port run in one process; *checked against (v3.5)* says what that path was compared with, from the validation page and the probe's own page, and is blank where they state no v3.5-specific check. The status words mean:

- **VALIDATED** -- the output was compared with an archived product the original code wrote, and every difference is accounted for.
- **CROSS-CHECKED** -- the path runs, and its code is asserted against the original MATLAB/IDL executing under Octave/GDL -- on fixtures, not necessarily on real data from this instrument.
- **unvalidated** -- the path runs, but nothing independent has been compared with its output.
- **refuses (by design)** -- the driver stops with a message, because the combination is meaningless or out of that engine's scope.
- **refused (not built)** -- the driver stops with a message because the code for the combination has not been written; nothing known makes it impossible.
- **REFUSES (DEFECT)** -- the driver stops with a message, but the combination should work and does not yet.
- **untested** -- no test exercises this combination, so nothing is claimed either way.

**Reading the status and raw-held columns together is the point.** Four of the seven probes have no raw data on this machine at all -- so a cell that says a path runs is saying the code reaches it, not that anyone has ever put that instrument's bytes through it. The coverage matrix keeps those two claims in separate words (`untested` vs `runs and cross-checked` vs `runs and validated against an archived product`) and so do these pages.

## The three probetype families, and why they are not interchangeable

| probetype | Probes | Reader | Driver output shape |
|---|---|---|---|
| 0 | 2DC, 2DP | `read_binary_PMS` | one raw file to **three** outputs -- the driver renames the one asked for and publishes the other two as unstamped siblings |
| 1 | CIP, PIP | `read_binary_DMT` | one raw file to one output |
| 2 | HVPS, 2DS | `read_binary_SPEC` | one raw file to an **H/V pair** |
| 3 | Fast2DC | `read_binary_PMS` | one raw file to **three** outputs -- the driver renames the one asked for and publishes the other two as unstamped siblings |

The third shape needs one rename inside the driver's stage 2 (the raw decode) (`_PMS_NATIVE_SUFFIX`, `run_flight.py`): `read_binary_PMS` writes its three outputs under its own lowercase names, and stage 2 renames the one a run asked for to the driver's own naming convention. All four probetypes open at stage 2 under every engine, and v3.5's stage 4 runs all four (probetypes 0 and 3 checked against Octave on synthetic input; see each probe's own page).

