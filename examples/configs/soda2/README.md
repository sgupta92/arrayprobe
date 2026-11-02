# SODA-2 engine configurations

Cite SODA-2 as: Aaron Bansemer. (2026). abansemer/soda2: v2.26.0 (Version v2.26.0) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.18331418

`2ds_spec.toml` is one config for `arrayprobe soda2 run`: a 2D-S read from a
SPEC raw file. Every probe field is SODA-2's own `'2D-S Horizontal Array'`
probespec row (`soda2_probespecs.pro:939-957`), and every processing option is
SODA-2's `example_script.pro`, itself a 2D-S example. The five places it departs
from that script are listed at the bottom of the `.toml` with the reason for each.

```bash
cd arrayprobe   # the repository root
# Windows spelling; on Linux / macOS use .venv/bin/python
.venv/Scripts/python.exe -m arrayprobe soda2 run \
    examples/configs/soda2/2ds_spec.toml --out <dir>
```

Before running it, edit the five fields that name a file or a time: `fn` (your
`.2DS` raw file), `pth` (your 1 Hz true-airspeed file, or remove it and set
`fixedtas`), `date`, `starttime` and `stoptime`. The getting-started notebooks
`03_choosing_an_engine` and `04_soda2_end_to_end` read this file and replace
exactly those fields, so what they run is this configuration.

A config file selects; it never describes a threshold. Everything that changes a
computed number is a probespec field or a SODA-2 processing option named here.

## The stock 2D-S probespec row runs unmodified

The 2D-S row has `x.seatag=[0]` (`soda2_probespecs.pro:956`), one element, and
`seatag` is consulted only on SODA-2's SEA branch. The SPEC branch of
`soda2_process_2d` has no probe-type gate, so the stock row runs as it stands.

## The output directory

`arrayprobe soda2 run --out DIR` (or `[soda2].outdir`) creates `DIR` before the
driver runs, so it need not exist beforehand.

## Cost

The whole raw file is indexed before the window is selected, so the fixed cost
dominates a short window: on a 1.07 GB raw file, about 5 minutes end to end, of
which about 3 minutes is the index walk.
