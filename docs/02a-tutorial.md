# Tutorial: a 2D-S file end to end
> Process one raw 2D-S recording on the default v3.5 engine, from install to a first plot, with every command runnable as written.

This page runs the whole chain once on the built-in demo flight, before you point it at your own
raw SPEC 2D-S file.

**The demo flight is synthetic** (five seconds, 60 particles, a flat 130 m/s airspeed; the size distribution has 4 seconds, not 5:
the reader never decodes a raw file's last record, here the fifth second's housekeeping packet, so
the 1 Hz grid ends at the fourth second): it proves
the chain runs, and its numbers are not cloud physics.

Every command runs from one working directory, which section 1 makes; no clone of the repository is needed. On Windows use `.venv\Scripts\python.exe` for
`.venv/bin/python` and `.venv\Scripts\arrayprobe.exe` for `.venv/bin/arrayprobe`.

## 1. Install

Python 3.12 or newer; on an older interpreter pip stops with
`No matching distribution found for numpy==2.5.3`, which does not name the cause.

```bash
mkdir arrayprobe-tutorial
cd arrayprobe-tutorial
python3.12 -m venv .venv                                   # Windows: py -3.12 -m venv .venv
.venv/bin/python -m pip install arrayprobe
.venv/bin/python -m pip install arrayprobe-uiops-enhancements  # only for section 9
.venv/bin/python -m pip install "arrayprobe[extra]"           # matplotlib, for section 10
.venv/bin/python -m arrayprobe --version
```

`python -m pip install "arrayprobe[extra]"` adds matplotlib (section 10), scipy and psutil, and
`"arrayprobe[jit]"` adds numba; the port needs only numpy
and netCDF4.

```
arrayprobe 0.1.0 (UIOOPS v3.5 engine)
```

`arrayprobe run` uses the engine its configuration file names, v3.5 in the run below.
`.venv/bin/python -m arrayprobe engines` prints which engine to use for what.

## 2. A working directory and a raw file

Make one directory per flight and put the raw `.2DS` file in it, named
`base<YYMMDDhhmmss>.2DS` from the flight's start time: the combine stage reads the date from the
stem, and the combined product's time axis starts at the stem's clock (section 7). Here, build the
demo instead:

```bash
mkdir myflight
.venv/bin/python -m arrayprobe make-demo-flight --dense myflight/base160101000000.2DS
```

```
wrote myflight/base160101000000.2DS (DENSE: 5 synthetic seconds, TAS=130.0 m/s) ...
wrote myflight/base160101000000.aircraft.cdf (aircraft TAS for engine 3.5: ...)
```

Without `--dense` the demo's particles arrive so close together that the shattering filter
rejects every one.

## 3. Airspeed: what you must supply

Sizing slices and converting counts to concentrations needs the aircraft's true airspeed (TAS)
every second; the v3.5 engine refuses to run without a source for it.

| Option | What it is | When to use it |
|---|---|---|
| `--tas-file <file>` / `[run].tas_file` | A netCDF file with two 1-Hz variables: `Time` (HHMMSS, e.g. `60638` for 06:06:38) and `TAS` (m/s) | You have aircraft data. **The normal case.** |
| `--tas-source auto` (+ `--tas-search <dir>`) | Walks a chain (campaign merge file, aircraft file, the probe's own housekeeping) and takes the first that passes its checks | A campaign whose merge or aircraft files the package recognises |
| `--tas-grid probe` or `regular` | With `--tas-source`: the probe's own housekeeping seconds, or one regular second grid valued from the chain | `probe` reproduces an archived product's timing; use `regular` for new data with no archived product |
| `--tas-cutoff-mps` (300), `--tas-default-mps` (170) | A second whose TAS is missing, non-finite, non-positive or above the cutoff is sized at the default | Change only with a reason; both are recorded |

Build the aircraft file with `.venv/bin/python -m arrayprobe make-tas-file` (from a CSV of
`timehhmmss, tas`, from a campaign merge file, or `--constant-tas` for a flat series, which is not a
measurement). The demo's `base160101000000.aircraft.cdf` has the right shape.

**Which seconds fell back to the default is recorded** in a `<file>.tasqc.json` sidecar on every
`sd` and combined product. On the demo the record is all zeros; a real flight with gaps in the
aircraft feed lists them by HHMMSS range under `tas_substituted_ranges` and `tas_missing_ranges`,
with a non-zero `tas_defaulted_fraction`.

## 4. The run configuration

One TOML file per flight, beside the raw file. Save as `myflight/run.toml`:

```toml
[fidelity]
profile = "stock-v3.5"          # the v3.5 engine's only profile

[run]
engine = "3.5"                  # the default engine; "3.1.4" is not part of this package
preset = "DEMO_2DS_H"           # probe, orientation, sizing method, ambient P/T for the sample volume
out = "_decoded"                # outputs land in myflight/_decoded/
stages = "234c"                 # 2 decode, 3 frame particles, 4 size distributions, c combine
tas_file = "base160101000000.aircraft.cdf"   # aircraft true airspeed, 1 Hz: Time (HHMMSS) and TAS (m/s)

[combine]
borrowed = true                 # v3.5 has no combine stage of its own; borrow the earlier fork's, labelled so in the .call
```

`borrowed = true` lets stage `c` run on the v3.5 engine: no stock v3.5 release has a combine
routine, so the run uses the `combine_sizedist.m` that wrote an archived product, and the
combined product's `.call` records that it was borrowed. Without it, `stages` containing `c` on
engine 3.5 stops with a message asking for it.

Three keys are required; a run missing one exits 2 before decoding:

- **`engine`**: different engines compute different numbers from the same file, so every output
  names its engine.
- **`preset`**: probe, channel (H or V), diameter definition and the pressure and temperature used
  for the sample volume. For your own file, copy `DEMO_2DS_H` and change the ambient values, or
  register a preset for your campaign ([how](44-add-a-campaign.md)).
- **`profile`**: the thresholds the code carries. The v3.5 engine accepts only `stock-v3.5`.

Cloud-regime thresholds (`--regime ice|liquid-warm|mixed`) work on both engines; a regime carries
the eight thresholds in [What a regime carries](06-configuration.md#what-a-regime-carries), and a
command-line value still wins. `--area-ratio-z` alone also works on both. On v3.5 it replaces the
literal `.2` at `sizeDist.m:1162`, takes a value in `[0, 1]` (`0` turns the gate off), and is
written to the sd `.call` stamp only when given.

## 5. Run it

`--dry-run` prints the resolved configuration and disk estimate without decoding:

```bash
.venv/bin/python -m arrayprobe run --dry-run --yes myflight/run.toml myflight/base160101000000.2DS
.venv/bin/python -m arrayprobe run --yes myflight/run.toml myflight/base160101000000.2DS
```

```
[03:02:43] S2 done   base160101000000.H.nc  5 H / 0 V records  (0 s, mode=serial jobs=1)
[03:02:44] S3 done   proc.base160101000000.H.nc (1 s)
[03:02:44] S4 done   sd.base160101000000.H.nc (0 s, engine=3.5 iat_file=<none> profile=stock-v3.5 ...)
[03:02:44] S4c done  base160101000000.combined.H.2DS.cdf (0 s)
[03:02:44] ALL DONE in 0.0 min
```

`--yes` accepts the printed configuration without a prompt (needed in scripts and detached runs).
A real flight takes hours: run it detached, with `--s2-jobs N` for one large file or `--jobs N` for
many; both are proven byte-identical to the serial run.

## 6. What was written

```
myflight/_decoded/
  base160101000000.H.nc                      decoded images, one row per particle slice   (+ .call, .decode)
  base160101000000.tas.csv                   the probe's own per-second housekeeping: HHMMSS, TAS, ...
  base160101000000.NV.csv                    per image record: HHMMSS and the V channel's slice-count word
  proc.base160101000000.H.nc                 one row per particle: size, area, habit, reject code  (+ .call)
  sd.base160101000000.H.nc                   one row per second x 28 size bins                  (+ .call, .tasqc.json)
  base160101000000.combined.H.2DS.cdf      the flight product on a full-day time axis         (+ .call, .tasqc.json)
  base160101000000.load.json                 what else the machine was doing while this ran
```

Each output's **`.call` sidecar** records how it was made. The `sd` one:

```
engine=3.5 iat_file=<none> profile=stock-v3.5 reject=(rej_zero_area=True,rej_split=True,rej_hollow=True,
shadowed_area=25,max_edge_img_ar=6,max_comp_img_ar=5) shadow_diode=none tas_file=base160101000000.aircraft.cdf
call=(iRectEllipse=0,iCalcAllDiodeStats=0,iQC=0,iNewHabit=0,tas_ratio=off) software=UIOOPS_v3.5
sizedist=(iaThreshType=0,iCreateAspectRatio=0,iCreateBad=0,iSaveIntArrSV=0)
```

The combined product's stamp records the borrowed combine
(`engine=3.5 combine=borrowed-oracles-fork:combine_sizedist.m opt_in=borrowed_combine=True`), the
files it stitched (`inputs=`) and their stamps (`inputs_built_with=`). A re-run redoes the combine
when any of these differs from what it would write now. `borrowed-oracles-fork` means the combine
step was taken, opt-in, from the ORACLES fork of UIOOPS (`combine_sizedist.m` ships in no stock
release); the name is part of the stamp format and stays as written. That `combine_sizedist.m`
is translated to Python and ships inside the v3.5 engine as an opt-in, while the v3.1.4 engine
itself does not ship with this package.

## 7. The variables that matter

`sd.<stem>.H.nc` is per second (`time`, HHMMSS) by size bin (`bin_min`, `bin_mid`, `bin_max`,
`bin_dD`, all mm; 28 bins from 10 µm), and every variable carries `units`. What each moment means
physically and where it is used in cloud science is in the
[microphysics moments notebook](../examples/6_science/01_microphysics_moments.ipynb).

| Variable | Units | Meaning |
|---|---|---|
| `conc_minR` | cm⁻⁴ | N(D) with D the minimum enclosing circle (the preset's `d_choice=6`) |
| `conc_AreaR` | cm⁻⁴ | N(D) with D the area-equivalent diameter |
| `count` | 1 | raw accepted count per bin, no sample-volume correction |
| `n` | cm⁻³ | total number concentration |
| `total_area` | mm² cm⁻⁴ | projected area per bin |
| `mass`, `massBL` | g cm⁻⁴ | mass per bin from mass–diameter relations (habit-based; Baker & Lawson) |
| `re` | mm | effective radius |
| `Reject_ratio` | 1 | rejected over all particles in the second |
| `habitsd` | cm⁻⁴ | N(D) split by the 10 Holroyd habit classes |

The combined product (`Bin Midpoints`, `Size Distribution cm-3`, `Number Concentration cm-3`,
`Counts`, `Reject Ratio`, `Time Vector`) carries **no units and no attributes**: the original
combine wrote none and the file reproduces it. Its time axis runs from the stem's 00:00:00 to the
last record: 22,004 s here, 4 with data, the rest fill. Naming the file from the true start time
(`base160101060640.2DS`) removes the padding.

On the demo: 4 seconds, 15 accepted particles in 2 of 28 bins.

## 8. Check the run reproduces itself

```bash
.venv/bin/python -m arrayprobe reprocess myflight/_decoded/sd.base160101000000.H.nc --preset DEMO_2DS_H
.venv/bin/python -m arrayprobe reprocess myflight/_decoded/proc.base160101000000.H.nc --preset DEMO_2DS_H --tas-file myflight/base160101000000.aircraft.cdf
```

```
result  : IDENTICAL (every dimension, variable and attribute; Creation Time skipped, source paths compared by basename)
```

`reprocess` re-runs the stage as the `.call` stamp records and compares every value (exit 0 on
`IDENTICAL`, 1 on the first disagreement), with no reference product. The `proc` stage reads the
aircraft file and takes `--tas-file`; the `sd` stage does not and **refuses** it (exit 2), even
though its stamp names the file.

## 9. Turn an enhancement on, and off

On engine 3.5 a batch run corrects data-destroying upstream defects by default (`--protective off`
opts out; stray-pixel removal has its own `--stray-pixel off`), and probes with no archived product
get further corrections; the full list is in
[Choosing an engine](27-choosing-an-engine.md#corrections-engine-35-applies-by-default). Other
corrections are named in the config, applied only with `--enhancements`, and written to
**separate files** beside the engine's own.
[Enhancements](05-enhancements.md) lists the 36 modules.

Append to `myflight/run.toml` (any correction that is not a default and is not named stays off):

```toml
[enhancements]
published_dof = true        # Gurganus & Lawson (2018) depth of field
```

```bash
.venv/bin/python -m arrayprobe run --yes myflight/run.toml myflight/base160101000000.2DS
.venv/bin/python -m arrayprobe run --yes --enhancements myflight/run.toml myflight/base160101000000.2DS
```

The first logs `enhancements requested: published_dof -- NOT applied: this run did not pass
--enhancements` and writes section 6's files. The second adds
`base160101000000.enh.sd.nc` (with a `.call` and an `.enhancements.json` naming every module and
its on/off state) and `base160101000000.enh.combined.H.2DS.cdf`; the faithful `sd.*.nc` is
untouched. `published_dof = false`, or removing the line, turns it off.

On the demo `published_dof` changes no concentration, because its particles sit where the two
depth-of-field formulas agree; on real data it moves the sample volume.

## 10. A first plot

Save this as `myflight/plot_sd.py`:

```python
"""First look at a size distribution: mean N(D) over the flight's seconds, from the sd file."""
import sys
import netCDF4
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sd = netCDF4.Dataset(sys.argv[1])
d_mm = sd["bin_mid"][:]                                # bin midpoint, mm
conc = np.ma.filled(sd["conc_minR"][:], np.nan)        # N(Dmax), cm-4, (time, bin)
mean = np.nanmean(conc, axis=0)
fig, ax = plt.subplots(figsize=(6, 4))
ax.step(d_mm * 1000, mean, where="mid")
ax.set(xscale="log", yscale="log", xlabel="Dmax (µm)", ylabel="N(D) (cm$^{-4}$)",
       title=f"Mean size distribution over {conc.shape[0]} s")
fig.tight_layout()
fig.savefig(sys.argv[2], dpi=120)
print(f"{conc.shape[0]} seconds, {int(np.count_nonzero(mean > 0))} of {len(d_mm)} bins populated; "
      f"total N = {np.nanmean(sd['n'][:]):.4g} cm-3; wrote {sys.argv[2]}")
```

```bash
.venv/bin/python myflight/plot_sd.py myflight/_decoded/sd.base160101000000.H.nc myflight/sd_first_look.png
```

```
4 seconds, 2 of 28 bins populated; total N = 0.0003577 cm-3; wrote myflight/sd_first_look.png
```

Two populated bins is expected from 60 synthetic particles; the plot checks axes and units.

## 11. Common errors

| Message (first line) | Exit | Meaning |
|---|---|---|
| `REFUSED   no --engine was given for preset ...` | 2 | Add `[run].engine` or `--engine`; nothing defaults it |
| `error: the following arguments are required: --preset` | 2 | Add `[run].preset` or `--preset` |
| `profile stock-v3.5 builds Time_in_seconds from an aircraft TAS file ... and none was given` | 2 | v3.5 needs `tas_file` or `--tas-source` |
| ``--engine 3.5 needs a v3.5 profile; none was named, and the preset's profile <name> is not one (no profile is ever defaulted).`` | 2 | Set `[fidelity].profile = "stock-v3.5"` (or `--profile stock-v3.5`) |
| `PREFLIGHT ... 0 file(s) to process ... NOT OK / aborting` | 1 | The raw path does not exist |
| `preflight  REFUSED: N of M input(s) could not be read` | 1 | A raw, TAS or interarrival file exists but cannot be opened; nothing was decoded, and each refused input is listed beneath |
| `reprocess: REFUSED -- --tas-file given, but S4 never reads the aircraft file` | 2 | Drop `--tas-file` when reprocessing an `sd` product |
| `No matching distribution found for numpy==2.5.3` (pip) | 1 | The venv is on Python older than 3.12; recreate it |
| `LOAD RECORD: UNRECORDED -- psutil not importable` | 0 | Informational: `psutil` (in the `extra` extra) adds the machine-load record beside timings |

Next: [User guide](02-user-guide.md) for real flights,
[Configuration](06-configuration.md) for every TOML key, [Choosing an engine](27-choosing-an-engine.md).
