# Start here
> One notebook: process a probe file and look at the output, no Python or OAP background assumed.

One raw probe file goes in. Out come pictures of every particle the probe recorded, a verdict on
each particle (kept or rejected, and why), and the number of particles at each size, second by
second. You need no knowledge of Python or of probe processing: you copy commands and run cells
in order.

The file processed is a synthetic, made-up 5-second flight the package writes for you; its
output shows what the processing writes, not a measurement. A real flight uses the same command.

## 1. Get the repository and install once

The notebook and its settings file are in the repository, not in a `pip install`. Installed
with `pip` and want only a first run? The Quickstart in the [README](../README.md) needs no
clone: two commands in an empty folder. For this page, clone the repository and move into it:

```
git clone https://github.com/sgupta92/arrayprobe.git
cd arrayprobe
```

Then follow [Installation](01-installation.md) from "From a clone", including its last section,
"To run the example notebooks", which adds `xarray`, `matplotlib` and `jupyter`. Every command
here runs from the top-level `arrayprobe` folder the clone made. Commands start with the
installation's Python, whose path depends on the system:

- Windows: `.venv/Scripts/python.exe`
- Linux or macOS: `.venv/bin/python`

## 2. Open the notebook

Start Jupyter from the repository root, with the installation's virtual environment activated:

```
python -m jupyter notebook examples/
```

Open
[`1_getting_started/01_start_here.ipynb`](https://github.com/sgupta92/arrayprobe/blob/main/examples/1_getting_started/01_start_here.ipynb),
the first notebook in the list, and run each cell in order with Shift+Enter. It walks through
four steps:

1. **A file to process.** It writes the synthetic raw 2D-S file and a record of the aircraft's
   airspeed, which the processing needs to turn counts into concentrations.
2. **Run it.** One command does the whole processing, with its settings in a text file,
   `examples/start_here/run.toml`, that carries a comment on every line.
3. **What was written.** Four cells look at the results: the particle pictures, how many
   particles were kept and rejected, the size distribution, and the total concentration over
   time.
4. **Your own file.** What to change to process a flight of your own.

## Without a notebook: three commands

The same run, typed in a terminal. The folder
[`examples/start_here/`](https://github.com/sgupta92/arrayprobe/tree/main/examples/start_here)
holds the settings file and these commands with more explanation. Use the first line of each
pair on Windows, the second on Linux or macOS.

1. Make the folder the results go into:

   ```
   mkdir -p examples/start_here/output     # Linux, macOS (safe to re-run)
   New-Item -ItemType Directory -Force examples/start_here/output     # Windows PowerShell (safe to re-run)
   ```

2. Write the synthetic probe file and the airspeed record into that folder:

   ```
   .venv/Scripts/python.exe -m arrayprobe make-demo-flight --dense examples/start_here/output/base160101000000.2DS
   .venv/bin/python -m arrayprobe make-demo-flight --dense examples/start_here/output/base160101000000.2DS
   ```

3. Process it:

   ```
   .venv/Scripts/python.exe -m arrayprobe run examples/start_here/run.toml examples/start_here/output/base160101000000.2DS --yes
   .venv/bin/python -m arrayprobe run examples/start_here/run.toml examples/start_here/output/base160101000000.2DS --yes
   ```

   The run prints a summary of its settings, then one line per step, and ends with `ALL DONE`.
   Adding `--dry-run` prints the summary and stops without processing anything.

## What comes out

Everything lands in `examples/start_here/output/` (untracked). The four files to know:

| File | What it holds |
|---|---|
| `base160101000000.H.nc` | the pictures: every particle's shadow, as the probe recorded it |
| `proc.base160101000000.H.nc` | one row per particle: its size, shape, and whether it was kept or rejected |
| `sd.base160101000000.H.nc` | one row per second and size range: how many particles per cubic centimetre of air, per size bin |
| `base160101000000.combined.H.2DS.cdf` | the flight's final product, one file |

The other files beside them record how each step was run.

## Your own file

Copy `run.toml` and change what describes your data:

1. **The probe and its settings.** The demo's settings fit only the synthetic file. Your flight
   needs a presets file naming the probe (`2DS` or `HVPS`), its channel (`H` or `V`), a project
   name, and the flight's mean air pressure and temperature from the aircraft's data. A
   settings file like `run.toml` can name only the shipped presets, so a run with your own
   presets file goes through `scripts/run_flight.py --presets <your file>`; see
   [Configuration](06-configuration.md).
2. **The airspeed.** Make an airspeed file from the aircraft's data with
   `arrayprobe make-tas-file` and name it in `tas_file`, or use the airspeed the probe records
   itself (`[tas] source = "probe"`).
3. **The raw file.** Name your own file on the command line in place of the demo's.

CIP and PIP probes are read differently: run them with `arrayprobe run <config.toml>`, `[run].engine = "3.5"` and the probe's format in the config (`examples/configs/cip_uiops/cip_run.toml` is a template).

## Read next

- [Tutorial](02a-tutorial.md): the same demo flight, explained section by section.
- [Glossary](11-glossary.md): the words the output files use.
- [User guide](02-user-guide.md): the four stages, the command line and the records each run
  leaves.
- [Scientist's guide](00a-scientists-guide.md): which engine to use, what has been validated, and
  what the files contain.
- The notebook `1_getting_started/06_read_products.ipynb` explains every variable in the output files.
