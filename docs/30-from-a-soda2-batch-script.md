# From a SODA-2 batch script
> SODA-2's two GUI-free scripts, `example_script.pro` and `example_batch.pro`, translated field by field into a configuration file and `arrayprobe soda2 run`, with what does not carry over.

SODA-2 ships two scripts that run the processing without the widget interface:
`example_script.pro` (one job) and `example_batch.pro` (a procedure called once per job). Both
build an IDL `op` structure and hand it to `soda2_process_2d`. This page carries each field of
that structure into the `[soda2]` table of a run configuration. The wider story, what the
SODA-2 port is for and what it refuses, is on [Migrating from SODA-2](29-migrating-from-soda2.md).
No validation figure appears here.

**See also** [CLI reference](13-cli-reference.md) · [API reference: the SODA-2 port](21-api-soda2.md) · [Configuration](06-configuration.md)

## `example_script.pro` as a configuration file

The script processes 1,000 s of a 2D-S horizontal-array file at a fixed true airspeed of
20 m/s. Every field it puts into `op` goes into `[soda2]` under the same name with the same
value, and `[run].engine = "soda2"` selects the engine:

```toml
[run]
engine = "soda2"

[soda2]
fn = "base151204165330.2DS"
date = "12042015"
starttime = 65000
stoptime = 66000
project = "MYPROJECT"
outdir = ""
timeoffset = 0.0
format = "SPEC"
subformat = 0
probetype = "2DS"
res = 10
armwidth = 6.3
numdiodes = 128
probeid = "H"
shortname = "2DS"
wavelength = 0.785e-6
seatag = [0]
endbins = [5, 15, 25, 35, 45, 55, 65, 75, 85, 95, 105, 125, 145, 175, 225, 275,
           325, 400, 475, 550, 625, 700, 800, 900, 1000, 1200, 1400, 1600, 1800, 2000]
arendbins = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
rate = 1
smethod = "fastcircle"
pth = ""
particlefile = 1
savfile = 1
inttime_reject = 1
reconstruct = 1
stuckbits = 0
water = 0
fixedtas = 20.0
greythresh = 0
```

Save it as `example_script.toml` and run it:

```bash
arrayprobe soda2 run example_script.toml --out soda2_out
```

The test suite runs this block (`tests/test_cli_soda2_migration.py`) on a tracked 2D-S frame
fixture, with only `fn`, `outdir`, `starttime` and `stoptime` pointed at that fixture, so the
table as printed is one the driver accepts.

Where each field comes from:

| Field | In the IDL script | In the configuration |
|---|---|---|
| `fn`, `date`, `starttime`, `stoptime` | the "Flight details" block | as written; `date` is `mmddyyyy`, times are seconds from midnight |
| `format`, `subformat`, `probetype`, `res`, `armwidth`, `numdiodes`, `probeid`, `shortname`, `wavelength`, `seatag` | `soda2_probespecs(name='2D-S Horizontal Array')` | copied by hand from that probe's entry in `soda2_probespecs.pro`, which the port does not include |
| `endbins`, `arendbins`, `rate`, `smethod`, `particlefile`, `inttime_reject`, `stuckbits`, `water`, `fixedtas`, `timeoffset`, `greythresh` | "Processing details and options" | as written |
| `pth`, `outdir` | `pthfile`, `outdir` | the `op` field is `pth`, not `pthfile`; `--out` overrides `outdir` |
| `project` | project name | accepted and recorded; the driver does not read it (SODA-2's image-dump and merge tools do) |
| `reconstruct` | "particle reconstruction on/off" | accepted and recorded; the vendored `soda2_process_2d` reads no `reconstruct` field. Reconstruction is chosen by `eawmethod = "reconstruct"` |
| `savfile` | "output sav file" | as written: `savfile = 1` (also `soda2_update_op`'s default) writes the IDL SAVE file `<outdir>/<date>_<hhmmss>_<shortname>[_<probeid>].dat` (`soda2_process_2d.pro:729-731`), beside the PBP files (`particlefile`, `ncdfparticlefile`) and the `.pbp.call` sidecar |

Fields the script leaves out, `dofconst` among them, take `soda2_update_op.pro`'s defaults as
they do in IDL. The script does not pass the probe's `dofconst` into `op`, so neither does this
file. The `op` block of the `.pbp.call` sidecar lists every field the driver ended up with.

## `example_batch.pro`: one file per job

`example_batch.pro` calls a `batch_process` procedure twice, once per raw file, with a
different `date` and `fn` each time, on the 2D-S vertical array (`probeid = "V"`). Here each
call becomes its own configuration file, identical to the one above except for those fields,
and the loop becomes one command per file:

```bash
arrayprobe soda2 run sim200.toml --out soda2_out
arrayprobe soda2 run sim400.toml --out soda2_out
```

The PBP files and sidecars are named `<date>_<hhmmss>_<shortname>_<probeid>`, as
`soda2_filename.pro` names them, so two jobs written to one directory do not overwrite each
other.

## What does not carry over

**No `[fidelity]` table.** A UIOOPS configuration names a fidelity profile. The SODA-2 engine
has one source tree and reads none, so a SODA-2 configuration holds only `[run]` (with
`engine` alone), `[soda2]` and, optionally, `[enhancements]`. Any other table is refused with a
message naming it, rather than ignored. This is a deliberate design decision.

**IDL types.** TOML has no IDL types, so every number in `[soda2]` reaches the driver as a
Python integer or float, where the IDL `op` held an `INT` or a `FLOAT`. Two places depend on
the difference:

- `activetime = fltarr(n) + op.rate` is `FLOAT` in IDL unless `op.rate` is `DOUBLE` (`1.0d`).
  The driver reads a Python integer as IDL's `INT`, so the configuration file's `rate = 1`
  gives a `FLOAT` `activetime`, as the script's `rate=1` does; a TOML float such as
  `rate = 1.0` is a double and gives a `DOUBLE` one.
- A nonzero `timeoffset` is a `FLOAT` in IDL, widened to double where it is added to buffer
  times; written in TOML it is a double from the start.

A field left out of the file keeps `soda2_update_op`'s default with IDL's own type. To reproduce
the `FLOAT` values, call the driver from Python and pass NumPy's 32-bit type:

```python
import tomllib

import numpy as np
from arrayprobe_soda2.process_2d import soda2_process_2d

with open("example_script.toml", "rb") as fh:
    op = tomllib.load(fh)["soda2"]
op["rate"] = np.float32(1)          # IDL's rate=1: a FLOAT activetime
op["timeoffset"] = np.float32(0.0)  # IDL's timeoffset=0.0 is a FLOAT
d = soda2_process_2d(op)
print(d.activetime.dtype)           # float32
```

This route writes the same PBP files but no `.pbp.call` sidecar.

**Refused by name.** What the port does not run, a `format` other than SPEC, SEA or DMT among it,
stops the run with the IDL file and line the missing code would port, never with a substitute.
The list is on [Migrating from SODA-2](29-migrating-from-soda2.md) and in the
[API reference](21-api-soda2.md).

A result from `arrayprobe_soda2` cites SODA-2, in the form its author, Aaron Bansemer, provided:

> Aaron Bansemer. (2026). abansemer/soda2: v2.26.0 (Version v2.26.0) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.18331418
