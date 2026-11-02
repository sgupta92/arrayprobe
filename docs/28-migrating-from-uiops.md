# Migrating from UIOOPS
> For a `runImgProc` / `runSizeDist` user: every MATLAB call mapped to its Python function, command and configuration key, where the outputs land, and how to check them against what MATLAB wrote.

If you have run UIOOPS, you already know this pipeline: the same four MATLAB functions, in the
same order, writing the same netCDF variables. What changes is how the calls are made. Porting
UIOOPS surfaced a set of [findings](07-findings.md) about the MATLAB; the v3.5 engine carries the
developers' own fixes and the opt-in [enhancements](05-enhancements.md) carry the rest. Every
function on this page is the v3.5 engine's (`arrayprobe_uiops`), the default for new data. An earlier
translation of UIOOPS v3.1.4 reproduced archived products and is not part of this package;
see [Choosing an engine](27-choosing-an-engine.md).

**See also** [Orientation](12-orientation.md) for the concepts side by side · [User guide](02-user-guide.md) · [Configuration](06-configuration.md) · [CLI reference](13-cli-reference.md)

## Three differences to know before the first call

1. **Nothing fidelity-sensitive has a default.** Where a choice changes the output and the MATLAB
   sources disagree on it, you name the side: reject thresholds for particle framing, and the
   `iNewHabit` switch and the aircraft airspeed series for `imgProc_sm`. A MATLAB script that
   "just worked" was silently choosing; here the choice is written down.
2. **Every stage writes a `.call` sidecar** beside its output recording the call that made it,
   because a netCDF file cannot be asked afterwards whether it was made with the threshold-file
   argument or which reject thresholds framed it.
3. **You name the output files.** The MATLAB drivers built names like `proc2.<date>.<n>.<probe>.cdf`
   inside the script; here every output path is an argument. The batch driver names them for you
   (see [Where the outputs land](#where-the-outputs-land)).

## The call mapping

The positional arguments keep v3.5's MATLAB order. On the command line, the 2D-S/HVPS decode,
particle framing and size distribution run through `arrayprobe run` with the stages named in the
run file.

| UIOOPS (MATLAB) | Python (`arrayprobe_uiops`) | Command line |
|---|---|---|
| `read_binary(infile, outfile, platform)` → `read_binary_SPEC` / `_DMT` / `_PMS` / `_SEA` | `spec.read_binary_spec_v35(infile, outfile, software=…, creation_time=…, channels=…, flt_time=…, flt_tas=…)`; `readers.pms.read_binary_PMS(infile, outfile)` | `arrayprobe run <config.toml>` with `[run].engine = "3.5"` and `[run].stages = "2"` (any format: SPEC, DMT, PMS, SEA) |
| `imgProc_sm(infile, outfile, probename, n, nEvery, projectname, iRectEllipse, iCalcAllDiodeStats, iQC, iNewHabit, tasTime, tas)` | `imgproc.imgproc_sm_v35(infile, outfile, probename, n, nEvery, projectname, iRectEllipse=…, iCalcAllDiodeStats=…, iQC=…, iNewHabit=…, reject_config=…, tas_time=…, tas=…, software=…)` | `arrayprobe run <config.toml>` |
| `sizeDist(infile, outfile, tas, timehhmmss, probename, d_choice, SAmethod, Pres, Temp, iaThreshType, iCreateAspectRatio, iCreateBad, iSaveIntArrSV, projectname, ddate, varargin)` | `sizedist.run(infile, outfile, tas, timehhmmss, probename, d_choice, sa_method, pres, temp, ia_thresh_type, i_create_aspect_ratio, i_create_bad, i_save_int_arr_sv, projectname, ddate, *varargin, software=…)` | `arrayprobe run <config.toml>` |
| `loadTASinfo_2DS(filename)` | `arrayprobe_uiops.readers.tasinfo.load_tas_info(path)` → `(timehhmmss, tas)` | read for you by `arrayprobe run` |
| `combine_sizedist` (the campaign variant's) | `combine.combine_sizedist(sd_files, outfile, flight_date=…, summary_time=…, borrowed_combine=True)` | `arrayprobe run <config.toml>` (stage `c`) |
| a `runImgProc` / `runSizeDist` script | none; the run file replaces the script | `arrayprobe run <config.toml>` with `[run].engine = "3.5"` and `[run].stages` |

**The positional arguments keep their MATLAB order and meaning**, including MATLAB's 1-based
chunk index `n`. Everything after them is a keyword, and the ones that change the output have no
default, so a call cannot be silently shifted by one argument or fall back to a guessed value.

### `imgProc_sm`, argument by argument

| MATLAB | Here | Notes |
|---|---|---|
| `infile`, `outfile`, `probename`, `projectname` | same, positional | `probename` is one of UIOOPS's names (`2DS`, `HVPS`, `CIP`, `PIP`, `2DC`, `2DP`, `Fast2DC`) |
| `n`, `nEvery` | same, positional | a whole-file run is `n = 1`, `nEvery` = the file's record count. The `parfor` over chunks in `runImgProc_example.m` becomes `arrayprobe run <config.toml> --chunks N`, which merges the chunk files into output byte-identical to a single-pass run |
| `iRectEllipse`, `iCalcAllDiodeStats`, `iQC` | `iRectEllipse=`, `iCalcAllDiodeStats=`, `iQC=` | keywords, each defaulting to `0`, v3.5's released value |
| `iNewHabit` | `iNewHabit=` | keyword, required: it selects the habit scheme |
| `tasTime`, `tas`, the aircraft airspeed series | `tas_time=`, `tas=` | required; `arrayprobe.tools.tas_sources.read_aircraft` reads an aircraft file into them |
| *(which thresholds)* | `reject_config=` | required; take it from a profile, e.g. `profile("stock-v3.5").reject_thresholds`. The profiles for this engine are `stock-v3.5`, `oracles-production-v3.5` and `stock-v3.5-image-assisted`, or one you register — see [Configuration](06-configuration.md) |
| the `Software` attribute (from `version.txt`) | `software=` | required |

### `sizeDist`, argument by argument

v3.5's `sizeDist.m` takes `iaThreshType`, `iCreateAspectRatio`, `iCreateBad` and `iSaveIntArrSV`
as positional arguments ten to thirteen, and the threshold file as an optional sixteenth.
`sizedist.run` keeps that signature, so the four switches are passed positionally:

| MATLAB | Here | Notes |
|---|---|---|
| `tas`, `timehhmmss` | arrays, positional | from `load_tas_info` on the decode's `.tas.csv`; pass `floor(timehhmmss)` as the campaign variant's driver did |
| `d_choice`, `SAmethod` | positional, required | the two arguments that change the science most — [what each value means](06-configuration.md) |
| `Pres`, `Temp` | arrays, positional | one value per second |
| `iaThreshType` | positional (tenth) | `0`, `1` or `2` |
| `iCreateAspectRatio`, `iCreateBad`, `iSaveIntArrSV` | positional (eleventh to thirteenth) | `0` or `1` each |
| `projectname`, `ddate` | positional | `ddate` is `'YYYYMMDD HHMMSS'` |
| the threshold file (`varargin`) | the optional trailing positional | **a name that does not exist is not the same as no argument**: it enables shattering on the per-probe default, while passing nothing skips the block. The campaign variant's archived products were made with a missing file name |
| the `Software` attribute | `software=` | required |

## The whole chain, in Python

This runs as written, from an empty directory, with no campaign data: `build_demo_flight`
writes a synthetic raw `.2DS` file shaped like a real 2D-S recording. It is checked by the
test suite (`tests/test_guide_pages_execute.py`), so it cannot go stale silently. The
arguments are stock v3.5's own: every switch at its released default, the `stock-v3.5` reject
thresholds, and a project name no table knows, so `sizeDist`'s `otherwise` branch applies. v3.5's
`imgProc_sm` takes the aircraft airspeed series as arguments, so the block writes the demo's
aircraft file first. No stock UIOOPS release has a combine step; v3.5 borrows a campaign fork's,
and only when asked (`borrowed_combine=True`).

```python
from pathlib import Path

import numpy as np

from arrayprobe.profiles import profile
from arrayprobe.tools.make_demo_flight import build_demo_flight, write_demo_aircraft
from arrayprobe.tools.tas_sources import read_aircraft
from arrayprobe_uiops import combine, imgproc, sizedist, spec
from arrayprobe_uiops.readers.tasinfo import load_tas_info

SOFTWARE = "UIOOPS_v3.5"  # the Software attribute UIOOPS reads from version.txt
raw = build_demo_flight(Path("base160101000000.2DS"), n_seconds=5)
aircraft = read_aircraft(write_demo_aircraft(raw, n_seconds=5))  # Time (HHMMSS), TAS (m/s)

# read_binary_SPEC(raw, 'base160101000000')  -> .H.nc, plus the .tas.csv sidecar
n_h, n_v = spec.read_binary_spec_v35(raw, "base160101000000", channels="H",
                                     software=SOFTWARE, creation_time="2016/01/01 00:00:00")

# imgProc_sm(infile, outfile, '2DS', 1, nEvery, project, iRectEllipse, iCalcAllDiodeStats,
#            iQC, iNewHabit, tasTime, tas) -- one chunk, the whole file
imgproc.imgproc_sm_v35("base160101000000.H.nc", "proc.H.nc", "2DS", 1, n_h, "DEMO",
                       iRectEllipse=0, iCalcAllDiodeStats=0, iQC=0, iNewHabit=0,
                       reject_config=profile("stock-v3.5").reject_thresholds,
                       tas_time=aircraft.time_hhmmss, tas=aircraft.tas_mps,
                       software=SOFTWARE)

# [timehhmmss, tas] = loadTASinfo_2DS(...);
# sizeDist(..., 6, 0, pres, temp, iaThreshType, iCreateAspectRatio, iCreateBad,
#          iSaveIntArrSV, project, ddate)
timehhmmss, tas = load_tas_info("base160101000000.tas.csv")
sizedist.run("proc.H.nc", "sd.H.nc", tas, np.floor(timehhmmss), "2DS", 6, 0,
             np.full_like(tas, 9e5), np.full_like(tas, 15.0), 0, 0, 0, 0,
             "DEMO", "20160101 000000", software=SOFTWARE)

# combine_sizedist -- files IN ORDER; summary_time is the summary file's YY_MM_DD_HH_MM_SS.
# No stock UIOOPS release has a combine step: v3.5 borrows a campaign fork's, opt-in.
combine.combine_sizedist(["sd.H.nc"], "base160101000000.combined.H.2DS.cdf",
                         flight_date="20160101", summary_time="16_01_01_00_00_00",
                         borrowed_combine=True)
```


This block deliberately uses the **plain** `build_demo_flight`, because what it is showing is the
shape of the calls. The demo particle is synthetic, and on this call every one is rejected (reject code `h`,
measured): this proves the calls fit together, not that the output means anything. For a flight whose size distribution actually
has particles in it, use `build_dense_demo_flight` from the same module (`--dense` on the command
line) — that is what the [User guide](02-user-guide.md) quickstart runs, and its text explains the
long NaN-padded time axis every combined demo product carries. [Validation](04-validation.md) is
where the science claims live.

## The same chain on the command line

```bash
arrayprobe make-demo-flight --dense examples/start_here/output/base160101000000.2DS
arrayprobe run examples/start_here/run.toml examples/start_here/output/base160101000000.2DS --yes
```

The run file names the stages: `stages = "234c"` is decode, particle framing, size distribution
and combine, and naming fewer (`"2"`, `"23"`) stops after them, so a stage's output can be
inspected before the next runs. Every format decodes through `run`, stage `2`; a SPEC (2D-S, HVPS) file needs it, because the v3.5 decoder needs the flight's
airspeed series, which the run file names. Or
put the campaign call in a [configuration file](06-configuration.md) once and run a flight with
`arrayprobe run <config.toml>` — the `runSizeDist` script's job, with every choice named in the
file rather than in code.

## Where the outputs land

| Stage | MATLAB wrote | This package writes |
|---|---|---|
| decode | `<outfile>.H.nc`, `<outfile>.V.nc`, `<outfile>.tas.csv` and the other housekeeping CSVs (v3.5's `read_binary_SPEC.m`) | the same names and layouts |
| frame | whatever `outfile` the script built (`proc2.….cdf` in the examples) | the path you give; the batch driver writes `proc.<stem>.<channel>.nc` |
| size distribution | `outfile` (`sdistCI.….cdf` in the examples) | the path you give; the batch driver writes `sd.<stem>.<channel>.nc` |
| combine | `base<first stem>.combined.<channel>.<probe>_2.cdf` (the campaign variant) | the path you give; the batch driver writes `base<first stem>.combined.<channel>.<probe>.cdf` |

Variable names, dimensions, attribute names — including the ones with spaces, like
`'Creation Time'` — and the `Units`/`units` inconsistency between modules are kept, so a script
that reads UIOOPS output by variable name reads these files unchanged. The files themselves are
NETCDF4 with compression, where MATLAB's bare `'clobber'` wrote NETCDF3 classic; a reader that
opens them through a netCDF library sees no difference.

## Checking a run against what MATLAB wrote

```bash
arrayprobe compare proc.H.nc reference_proc.H.cdf
arrayprobe compare sd.H.nc reference_sd.H.cdf --var conc_minR
```

`compare` aligns the two files first — a per-particle file on particle identity, a one-second
file positionally on its time index, deciding which from the file's dimensions — and then
diffs every variable by a named tolerance class; its exit status is 0 only when the comparison is
accepted, so it can gate a script. Read the join block first: a value difference against a bad
join is an artefact of the alignment, not a finding. For a combined flight product,
`arrayprobe.compare_to_product(ours, theirs)` reports agreement over both
[denominators](04-validation.md) as a Python object. `examples/3_validation/01_validate_against_a_product.ipynb#validate-your-own-run` does this for two
files you supply.

## Reproducing an archived product you hold

This package does not reproduce byte for byte a product UIOOPS wrote before v3.3. With the v3.5 engine you
can reprocess the same raw file with the call you recover from the run script (`d_choice`,
`SAmethod`, the project and probe names, and whether the threshold-file argument was passed) and
compare the result with `compare` as above: the per-particle file first, since a disagreement
there is upstream of every size distribution. Expect differences, because v3.5 carries the
developers' fixes to faults the older products contain; [Findings](07-findings.md) lists them, and
a residual it does not explain is worth reporting with the raw file and product, the evidence the
[Orientation](12-orientation.md) page asks for.
