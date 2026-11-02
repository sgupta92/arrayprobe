# Start here, without a notebook

The same processing as [`../1_getting_started/01_start_here.ipynb`](../1_getting_started/01_start_here.ipynb), as three commands typed in a
terminal, on a shorter demo file: the notebook writes a 20-second flight, this page a 5-second one,
so the notebook's counts are larger. No Python knowledge is needed: you copy the lines.

The file processed is a small synthetic probe file (a made-up flight, 5 seconds long) that the
package writes for you, because real probe data cannot be shipped with it. Its output shows that
the processing runs and what it writes; it is not a measurement of anything.

## Before you start

Install the package once, as described in
the [README](../../README.md#install) and the documentation site's *Installation* page. Then open a
terminal in the root folder of this repository. Every command below is run from there.

The commands start with the program that runs Python inside the installation. It has a different
path on each system:

- Windows: `.venv/Scripts/python.exe`
- Linux or macOS: `.venv/bin/python`

## The three commands

1. Make the folder the results go into:

   ```
   mkdir -p examples/start_here/output     # Linux, macOS (re-runnable); PowerShell: New-Item -ItemType Directory -Force examples/start_here/output; Windows cmd: if not exist examples\start_here\output mkdir examples\start_here\output
   ```

2. Write the synthetic probe file and the aircraft's airspeed record into that folder:

   Windows:

   ```
   .venv/Scripts/python.exe -m arrayprobe make-demo-flight --dense examples/start_here/output/base160101000000.2DS
   ```

   Linux or macOS:

   ```
   .venv/bin/python -m arrayprobe make-demo-flight --dense examples/start_here/output/base160101000000.2DS
   ```

3. Process it, with the settings in [`run.toml`](run.toml):

   Windows:

   ```
   .venv/Scripts/python.exe -m arrayprobe run examples/start_here/run.toml examples/start_here/output/base160101000000.2DS --yes
   ```

   Linux or macOS:

   ```
   .venv/bin/python -m arrayprobe run examples/start_here/run.toml examples/start_here/output/base160101000000.2DS --yes
   ```

   The run prints a summary of
   its settings first, then one line per step, and ends with `ALL DONE`. Adding `--dry-run`
   prints the summary and stops without processing anything.

## What comes out

Everything lands in `examples/start_here/output/` (this folder is not tracked by git). The four
files to know:

| File | What it holds |
|---|---|
| `base160101000000.H.nc` | the pictures: every particle's shadow, as the probe recorded it |
| `proc.base160101000000.H.nc` | one row per particle: its size, shape, and whether it was kept or rejected |
| `sd.base160101000000.H.nc` | one row per second and size range: how many particles per litre of air |
| `base160101000000.combined.H.2DS.cdf` | the flight's final product, one file |

The other files beside them are small records of how each step was run.

To look at the output as pictures and plots, open [`../1_getting_started/01_start_here.ipynb`](../1_getting_started/01_start_here.ipynb).
To process your own probe file, read its "Step 4".
