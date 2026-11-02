# Migrating from SODA-2
> For a SODA-2 user: how an IDL `op` structure becomes a configuration file, what the Python port of SODA-2 runs today, and what it refuses by name.

`arrayprobe_soda2` is a from-source Python port of NCAR's SODA-2, the IDL chain — a separate
processing lineage from UIOOPS, not a UIOOPS version, so `uiops.engine()` never returns it and
nothing on the UIOOPS pages applies to it unchanged. Porting it surfaced findings for NCAR; corrections live in a separate optional package,
`arrayprobe_soda2_enhancements`, never in the port. Its differential oracle is GDL, which runs
SODA-2's own `.pro` sources the way Octave runs UIOOPS's `.m` files, and each ported routine is
asserted against GDL's output.

**See also** [Choosing an engine](27-choosing-an-engine.md) · [API reference: the SODA-2 port](21-api-soda2.md) · [CLI reference](13-cli-reference.md)

## What it is for

SODA-2 and UIOOPS make different choices at almost every stage — sizing, rejection, sample area,
the shattering treatment — so the two chains disagree on the same raw file by design. That
disagreement is informative: it is the spread between two defensible answers. It also means a
SODA-2 product and a UIOOPS v3.5 product come from two engines on equal footing, and neither is a
bit-fidelity target for the other. Use this port to reproduce what SODA-2 computes from a raw file, without an
IDL licence, and to put that answer beside the UIOOPS engines'.

## The `op` structure becomes a `[soda2]` table

A SODA-2 run is driven by one IDL structure, `op`, handed to `soda2_process_2d`. Here the same
fields, with the same names, go in the `[soda2]` table of a run configuration, and
`[run].engine = "soda2"` selects the SODA-2 engine. The driver fills the fields you leave out the
way `soda2_update_op.pro` does, and the resolved `op` — every field, with its IDL type — is what
the run records.

```toml
[run]
engine = "soda2"

[soda2]
fn = "base160906064403.2DS"
date = "09062016"
starttime = 24240.0
stoptime = 24250.0
format = "SPEC"
subformat = 0
probetype = "2DS"
res = 10.0
endbins = [0.0, 50.0, 100.0, 200.0, 500.0]
arendbins = [0.0, 0.5, 1.0]
rate = 1.0
smethod = "xy"
pth = ""
particlefile = 1
inttime_reject = 0
stuckbits = 0
water = 0
fixedtas = 0.0
timeoffset = 0.0
armwidth = 6.3
numdiodes = 128
greythresh = 0
probeid = "H"
eawmethod = "centerin"
wavelength = 0.785e-6
dofconst = 8.12
ncdfparticlefile = 0
asciipsdfile = 0
shortname = "x1frame"
outdir = "soda2_out/"
```

A SODA-2 configuration has no `[fidelity]` table: the engine has one source tree and reads no
UIOOPS profile (by design). `date` is `mmddyyyy`, as in SODA-2. `starttime` and `stoptime` are seconds from midnight, as
in SODA-2. This block is executed by the test suite (`tests/test_guide_pages_execute.py`) against
a tracked 2D-S frame fixture, with only `fn` and `outdir` pointed at it, so the table as printed
is one the driver accepts.

## Running it

```bash
arrayprobe soda2 run soda2.toml --out soda2_out
arrayprobe soda2 enhancements soda2.toml
```

`soda2 run` runs `soda2_process_2d` and writes the particle-by-particle (PBP) output SPEC's path
produces, named as `soda2_filename.pro` names it — `<date>_<hhmmss>_<shortname>_<probeid>` — plus
a `<stem>.pbp.call` sidecar beside it recording the resolved `op`, the enhancement table and the
package versions. The sidecar carries no timestamp, so two runs of one configuration write
identical bytes. `--out` overrides `outdir`. If no buffer falls in `[starttime, stoptime]` the
command exits 1 and writes no sidecar, where SODA-2 returns with no output.

The IDL SAVE file (`.dat`) of two runs on one input is not byte-identical, and that is faithful to SODA-2, not a defect. Every array in it is equal; three things differ. The SAVE file's TIMESTAMP record holds the save time, user and host, as IDL's own `save` writes it. `data.date_processed` holds the wall-clock time of the run (`soda2_process_2d.pro` writes it from `systime`). `op.outdir` is the output folder, which differs when the runs use different folders. Each record is compressed separately, so these few bytes change the compressed file throughout. To compare two files, read both with `scipy.io.readsav` and ignore `date_processed` and `outdir`; the package's own determinism test does exactly that.

`soda2 enhancements` lists the optional correction package's registry and, given a
configuration, which corrections it switches on. With the package installed, `soda2 run` applies
every switched-on correction the driver adapter can route (14 of the 19), and the sidecar lists
which were applied and which were skipped, with the reason for each.

`arrayprobe run` refuses a configuration whose engine is `soda2` and points here.

## What runs today, and what is refused by name

The SPEC path (`format = "SPEC"`, the SPEC Inc. raw format the 2D-S writes) and the CIP route
under `format = "SEA"` and `"DMT"` (PIP reaches it as `CIP`) run from raw bytes through the driver
to the PBP writers. Anything outside them raises with the IDL file and line it would need, rather
than running something else:

| Asked for | What happens |
|---|---|
| `format` other than SPEC, SEA or DMT | refused: those three branches of the driver are the ones ported |
| a SEA or DMT probe type other than CIP (CIPG, 2DC, 1D2D, HVPS, HAIL) | refused: only the CIP read and process branches are ported |
| a SEA run with two or more `seatag` entries | runs: the CIP-1D housekeeping is processed as `soda2_process_2d.pro:397-398` does, matching GDL on every field |
| several raw files in `fn` | SEA and DMT runs concatenate the files as `soda2_process_2d.pro:364-391` does, matching GDL field for field; SPEC stops with the IDL's own message (`:376`); `jobs > 1` on a multi-file run is refused |
| reprocessing from an existing PBP file | ported, from Python only (the driver's `fn_pbp=` keyword); not checked against GDL |

What is and is not ported, routine by routine, is the opening of the
[API reference](21-api-soda2.md).

## Moving a SODA-2 analysis across

1. Copy the `op` fields your IDL call set into `[soda2]`, names unchanged. Leave out the ones you
   left at SODA-2's defaults.
2. Run `arrayprobe soda2 run` and read the `op` block of the `.pbp.call` sidecar: it is the fully
   resolved structure, so it shows every default the driver filled in — the fastest way to find a
   field your IDL call set implicitly.
3. Compare the PBP output against the one IDL wrote from the same raw file and window. A
   disagreement is worth a look in the SODA-2 findings list before it is called a port defect: several
   findings describe IDL behaviour that depends on precision or on operator semantics
   (`<` and `>` are minimum and maximum in IDL, not comparisons).

## Citing SODA-2

A result from `arrayprobe_soda2` cites SODA-2, not this package, in the form its author, Aaron Bansemer, provided:

> Aaron Bansemer. (2026). abansemer/soda2: v2.26.0 (Version v2.26.0) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.18331418
