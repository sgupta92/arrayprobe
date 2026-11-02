# Add a campaign: from raw files to a checked product
> Seven steps that take a new campaign's raw probe files through arrayprobe and say how to check the result.

This page assumes you have raw files from an optical array probe and have never run the package. It
describes the steps in the order you take them. Each command below is in the
[CLI reference](13-cli-reference.md); nothing here needs a campaign-specific setting except the
preset you declare in step 3.

**See also** [Start here](00b-start-here.md) · [Configuration](06-configuration.md) ·
[Choosing an engine](27-choosing-an-engine.md) · [Probes](33-probes.md).

## 1. Inventory the raw files

```bash
arrayprobe inventory /path/to/raw --out inventory/flights
```

This reads the raw bytes only and writes `inventory/flights.json` and `inventory/flights.csv`, one row
per file: size, SHA-256, a guess at the record format, and two flags, `empty` and `truncated` (the
bytes are not a whole number of records). Add `--format spec`, `dmt` or `pms_2d` when the file
extension does not say which. It prints how many files it flagged.

The driver runs the same check before it decodes anything. It refuses an empty file
(`arrayprobe run <config.toml> --accept-flagged` processes one anyway; look at the flagged rows first), and
decodes a truncated one with a warning, as the original readers do with a trailing partial record.

## 2. Write the run file

A run is one TOML file and one command. The minimum for new data is the engine (`"3.5"`), a profile
(`"stock-v3.5"`), a preset, an output directory, the stages and the aircraft file:

```toml
[fidelity]
profile = "stock-v3.5"

[run]
engine = "3.5"
preset = "MY_CAMPAIGN_2DS_H"
presets = "my_campaigns.toml"      # step 3
out = "output"
stages = "234c"
tas_file = "aircraft.cdf"          # step 4

[combine]
borrowed = true
```

The file can only select among settings the package already has; it cannot set a threshold. Every key
is explained in [Configuration](06-configuration.md), and the `run.toml` that
`arrayprobe make-demo-flight --with-config` writes is a working copy of this file.

## 3. Choose a preset and an engine

`engine` and `preset` are both required; the run refuses to start without them.

- **Engine.** Use `"3.5"` for new data. See [Choosing an engine](27-choosing-an-engine.md).
- **Preset.** A preset is the campaign's probe, channel, size definition, sample-area method and the
  flight-mean pressure and temperature, named once. The shipped presets belong to existing campaigns,
  so declare your own in a file you own (`my_campaigns.toml`), with a `provenance` line saying where
  the numbers came from:

```toml
[[campaign]]
name = "MY_CAMPAIGN_2DS_H"
probe = "2DS"
orientation = "H"
project = "MY_CAMPAIGN"
d_choice = 6
sa_method = 0
pres_pa = 85000.0
temp_c = 5.0
provenance = "from the flight's aircraft file; not validated against a product"
```

Pressure and temperature are flight means and belong to one flight each. A missing field, an unknown
key or an empty `provenance` is refused. The full rules are under *A campaign the driver does not
ship* in [Configuration](06-configuration.md).

## 4. Supply the true-airspeed file

The v3.5 engine refuses to run without one. It is a netCDF file with two 1-D variables, `Time`
(HHMMSS as a number, 06:06:38 is `60638`) and `TAS` (m/s). Make it from the airspeed sidecar the
decode writes, or from a stated constant:

```bash
arrayprobe make-tas-file aircraft.cdf --from-tas-csv decoded/<stem>.tas.csv
arrayprobe make-tas-file aircraft.cdf --constant-tas 130 --start-hhmmss 60600 --seconds 3600
```

A constant is written as a constant and says so, so it cannot pass for a measurement. `make-tas-file`
also reads a merged aircraft file (`--from-merge`, `--from-aircraft`); `tas-from-nasa-ames` turns a
NASA-Ames airspeed file into the `.tas.csv` form. Both are in the [CLI reference](13-cli-reference.md).

## 5. Run, then read the `.call` stamp

The first command is a preflight that decodes nothing; the second is the run.

```bash
arrayprobe run run.toml /path/to/raw/*.2DS --dry-run
arrayprobe run run.toml /path/to/raw/*.2DS
```

Every product has a `<name>.call` sidecar beside it. It records the engine, the profile, the reject
thresholds, the airspeed file, the enhancements that were on and a plausibility line for the size
distribution (`ok` or what failed). To read the stamps for a whole directory:

```bash
arrayprobe provenance output/ --require
```

`provenance` reports each product as stamped, unstamped or orphaned and exits 1 under `--require`
unless every product is stamped. Run one flight at a time and read its stamps before the next.

## 6. Compare with an archived product, where one exists

If an earlier processing of the same flight exists as a netCDF file, compare cell by cell:

```bash
arrayprobe reproduce-report output/sd.<stem>.H.nc /path/to/archived.nc --out report.md --json report.json
```

It reads both files, compares every variable they share and reports the cells compared, the exact
matches, the largest absolute and relative residuals, every differing cell and each file's engine
and `.call` stamp. It exits 0 when the products are identical and 1 otherwise. A difference is not an
error until you know which processing choices differ; the stamps name them. For a finer, particle by
particle join, see `arrayprobe compare` in the [CLI reference](13-cli-reference.md).

## 7. Look at the particles

`arrayprobe triage --decoded-dir output` opens the review server, and `arrayprobe gallery` writes a
static page. See [Visualisation and triage](03-visualisation.md). To adjust thresholds to your cloud
using particles you label, see [Tune thresholds](43-tune-thresholds.md).

## 8. Worked example on the tracked synthetic flight

The commands above, run in a clone on the one-particle-stream synthetic flight the repository ships
(`tests/data/demo_flight_v314_raw.2DS`, its airspeed file
`tests/data/demo_flight_v35_aircraft.cdf` and the run file
`tests/data/demo_flight_v35_run.toml`). Every output block is the command's real
output, trimmed to its first lines; the whole run takes under a minute. The run file ships with
`stages = "234c"`; the combine stage needs a raw file named by its timestamp, which the demo file is
not, so the run below uses a copy with `stages = "234"`, which writes the image, particle and
size-distribution files and stops there.

```bash
arrayprobe inventory raw --out inv/flights
```

```text
1 raw files, 0 flagged empty or truncated; wrote inv/flights.json and inv/flights.csv
```

```bash
arrayprobe run demo_flight_v35_run.toml raw/demo_flight_v314_raw.2DS --dry-run
```

```text
[00:54:44] preset DEMO_2DS_H: probe=2DS channel=H project=DEMO d_choice=6 sa_method=0
...
[00:54:44] === confirm this run ===============================================
[00:54:44]   engine                 3.5
[00:54:44]   fidelity profile       stock-v3.5
[00:54:44]   campaign preset        DEMO_2DS_H  (probe=2DS channel=H project=DEMO)
[00:54:44]   stages                 234c
...
```

```bash
arrayprobe run run234.toml raw/demo_flight_v314_raw.2DS
```

```text
[00:56:32] preset DEMO_2DS_H: probe=2DS channel=H project=DEMO d_choice=6 sa_method=0
...
[00:56:32] running   engine=3.5 profile=stock-v3.5 preset=DEMO_2DS_H
...
[00:56:40] ALL DONE in 0.1 min
```

```bash
arrayprobe provenance _decoded234 --require
```

```text
product                                  state         engine      format        nlink  profile              in-file
--------------------------------------------------------------------------------------------------------------------
demo_flight_v314_raw.H.nc                stamped       3.5         driver            1  stock-v3.5           engine=3.5 profile=stock-v3.5
proc.demo_flight_v314_raw.H.nc           stamped       3.5         driver            1  stock-v3.5           engine=3.5 profile=stock-v3.5
sd.demo_flight_v314_raw.H.nc             stamped       3.5         driver            1  stock-v3.5           engine=3.5 profile=stock-v3.5

counts: stamped=3
```

The archived product here is the tracked reference `tests/data/demo_flight_v35_sd.nc`,
written from the same file by the same configuration, so the comparison is expected to be exact:

```bash
arrayprobe reproduce-report _decoded234/sd.demo_flight_v314_raw.H.nc demo_flight_v35_sd.nc --out report.md --json report.json
```

`report.md` then begins:

```text
# Reproduction report
```

and its verdict line reads `**EXACT**: 21524 of 21524 cells equal; 0 differing.`

```bash
arrayprobe check-counts _decoded234/sd.demo_flight_v314_raw.H.nc _decoded234/proc.demo_flight_v314_raw.H.nc
```

```text
excluded particle 5 at 60644: outside-tas-axis
closure: exact (4 accepted of 5 particles, 4 binned)
probe_reported: not available
```

Every binned count is reconciled with the particle file, and the one particle left out is named
with its cause. The probe's own total is not read by the current readers, so the last line says so
rather than printing a number.
