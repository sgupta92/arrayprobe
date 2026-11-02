# A CIP from a SEA file, on the UIOOPS v3.5 engine

`cip_run.toml` processes a CIP recorded in a SEA file from raw to one-second size distributions
on the default engine, UIOOPS v3.5, in one command:

```bash
arrayprobe run cip_run.toml
```

`tests/test_example_cip_config.py` runs this file, unedited, on the tracked SEA fixture
(a CIP and a 2DC) and checks that it writes a v3.5 size
distribution with counts in it. That is a check that the chain runs, not a validation: no CIP
raw+processed reference pair exists, so no CIP number from this package has been compared
against an archived UIOOPS product.

## Laying out the files

Paths in `cip_run.toml` are relative to the file:

```
cip_run.toml
data/2016_09_06_06_40_17.sea          # the SEA file ([run].raw = ["data/*.sea"])
data/base160906064017.tas.csv         # the 2D-S airspeed ([run].tas_from_probe)
out/                                  # written by the run ([run].out)
```

Edit the paths rather than moving data, if that suits you better; a raw file named on the command
line (`arrayprobe run cip_run.toml my.sea`) wins over `[run].raw`.

## What the config selects

| Key | Value | Why |
|---|---|---|
| `[fidelity].profile` | `stock-v3.5` | UIOOPS v3.5 as released. The campaign profiles carry threshold edits made for one 2D-S campaign. |
| `[run].engine` | `3.5` | The default engine. |
| `[run].preset` | `UND_2016_CIP` | The CIP call, chosen whole: size definition 6, sample-area method 0, and the pressure and temperature of the same campaign's 2D-S call. Its project name selects UIOOPS's generic CIP row: probetype 1, 64 diodes, 25 µm, 19 bins. |
| `[run].probe` | `CIP` | A SEA file holds several probes. The decode writes one file per probe (`<stem>.CIP.cdf`, `<stem>.2DC.cdf`) and the run follows this one. It must be the preset's probe: `probe = "2DC"` with this preset is refused by name. |
| `[run].tas_from_probe` | `data/*.tas.csv` | The CIP decode writes no airspeed. These are the `<stem>.tas.csv` files the 2D-S on the same aircraft wrote when it was decoded; the run merges them (per-second median, no gap filling) into the CIP's `<stem>.tas.csv`. Each entry must match a file, or nothing runs. |
| `[run].stages` | `234` | Decode, image processing, size distribution. |

The run also applies the corrections for data-destroying upstream defects that are on by default
for probes with no archived product, each into its own `<stem>.enh.*.nc`; the port's own
`proc.*` and `sd.*` files are left as UIOOPS writes them. To skip them, add
`[enhancements]` with `protective = false` to the config. These corrections live in the
`arrayprobe-uiops-enhancements` package: on a base install the run refuses to start until you either
install it (`pip install arrayprobe-uiops-enhancements`) or set `protective = false`.

## Airspeed and the CIP clock

v3.5 matches the airspeed series to the CIP's particle blocks by the **CIP's own clock**
(`sizeDist.m:758-759`, `:913-918`), not by UTC. A 2D-S airspeed file is in UTC. Where the CIP
clock has not been set to UTC the two do not overlap and stage 4 stops with an index error at
`sizeDist.m:918`, as UIOOPS itself does.

The tracked fixture is such a case: it is the first minutes of a 2016 flight, and its CIP clock
reads 00:00:13 to 00:01:49, hours away from the SEA records' UTC times. The test therefore writes
its airspeed file over the CIP-clock span, at a constant 100 m/s that is not a measurement.
Whether a whole flight's CIP clock later carries UTC has not been measured. Before trusting a
concentration, compare `particle_time` in `out/proc.<stem>.CIP.nc` with the times in your
airspeed file.

Pressure and temperature are applied uniformly from the preset, not from this flight's record.

## The stage-by-stage script

`cip_sea_stage_by_stage.sh` is a per-stage recipe, kept because `docs/developer/SPEED.md`
cites a timing taken with it. It runs image processing on the
validation engine (v3.1.4), which is not used for CIP science. Process a CIP with `cip_run.toml`.
