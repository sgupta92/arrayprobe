# Scientist's guide
> For an atmospheric scientist deciding whether to use arrayprobe: what it does, which engine to pick, what has been validated, and what the files contain.

## What it does

arrayprobe turns raw optical-array-probe imagery into particle size distributions, entirely in
Python, with no MATLAB licence or compiled binary. It ports UIOOPS, the McFarquhar group's MATLAB
processing chain, and runs its four steps: decode raw files into images; describe each particle
(size, habit, reject code, geometry); bin the accepted particles into one-second size
distributions; and stitch a flight's files into one product.

Findings about the MATLAB are written up for its developers ([For UIOOPS
developers](07-findings.md)). The **v3.5 engine** carries the fixes the developers already made;
a separate package of **opt-in corrections** covers the rest. A port of UIOOPS v3.1.4, faults
included, was checked against products the original software wrote; it is not part of this
package ([Validation](04-validation.md)).

## Which engine to use

| You want to… | Use | Why |
|---|---|---|
| process new data | the **v3.5 engine**, the default | it follows the current UIOOPS release |
| regenerate or audit a product UIOOPS already wrote, such as an archived campaign file | not possible with this package | those products were written by an earlier UIOOPS release, which this package does not translate |
| compare against a different processing lineage | the **SODA-2 chain** | NCAR's IDL processing, ported separately; a cross-check, never a reference for UIOOPS |

`arrayprobe run` runs the engine the configuration file names (`[run].engine = "3.5"`; see [Configuration](06-configuration.md)), and `[run].stages` selects which stages it runs; there is
no separate per-stage subcommand. An engine this package does not ship is refused with a usage error. From Python, `uiops.engine()` returns the v3.5 engine; `arrayprobe.engine()` reaches v3.5 and `"soda2"`. To list the engines
(`--catalogue` adds which package implements each module):

```bash
arrayprobe engines
```

**SODA-2.** `arrayprobe soda2 run <config>` takes one raw file (SPEC format, or a CIP or PIP in
SEA or DMT format) through SODA-2's decode, sizing, rejection and accumulation, and writes
per-particle files (CSV and netCDF) with a `.pbp.call` sidecar. `asciipsdfile = 1` in the
`[soda2]` table also writes SODA-2's ASCII size-distribution file (`soda2_export_ascii.pro`, a
`.txt` beside them). With the SODA-2 correction package installed, every correction the
configuration resolves on (those it names, plus the protective set for data-destroying upstream
defects unless `--protective off`) is applied where it has a hook point, and the sidecar lists
which were applied and which skipped. Details: [SODA-2 API](21-api-soda2.md).

## What "validated" means here, and what it does not

The evidence is of three kinds.

- **Reproducing archived products** (the earlier translation, not in this package). 15 field-campaign flights reproduce their
  archived 2D-S products cell by cell, 10 of them exactly (every non-zero cell of `Counts` and
  `Size Distribution` in the used size bins, over the seconds both hold); every residual on the others is
  attributed. [Validation](04-validation.md) has the table and explains how agreement is counted.
- **Running the original code.** Where a UIOOPS routine is plain MATLAB, GNU Octave runs it
  unmodified and the port is asserted against its output. The v3.5 engine is checked this way,
  including whole-program runs of its particle-framing step. No archived product was ever written
  by v3.5, so a v3.5 number cannot be checked against one.
- **Pinned tests** for whatever neither of the above reaches.

**What this establishes.** Reproduction shows the port matches the original software, not that
the original's numbers are correct. If UIOOPS mis-sizes or wrongly rejects a particle, a faithful
port does too; the findings and corrections address that.

**Validating the science** needs an independent measurement of the same cloud: CIP data from the
same campaign, compared with the 2D-S over the sizes both measure. No validation claim on this site
rests on that comparison.

**Scope of the reproduction evidence**: the 2D-S horizontal channel, one field campaign (warm
marine stratocumulus). HVPS output does not reproduce its archived product. CIP, PIP, 2DC and
2DP are ported and were checked against Octave during development (those reference outputs use campaign
data and are not distributed), with no archived product held. [Known
gaps](10-known-gaps.md) lists each.

## Corrections are opt-in

The corrections live in their own package, `arrayprobe-uiops-enhancements`, which the port never
depends on. **On engine 3.5 a batch run corrects data-destroying upstream defects by default
(`--protective off` opts out; stray-pixel removal has its own `--stray-pixel off`), and probes
with no archived product get further corrections; the full list is in
[Choosing an engine](27-choosing-an-engine.md#corrections-engine-35-applies-by-default).** Any
other correction the configuration file does not name is off. To turn one on, name it
in the `[enhancements]` table:

```toml
[enhancements]
outoffocus = true     # the Korolev out-of-focus size correction
```

Then install the package (`pip install arrayprobe-uiops-enhancements`) and run the file with
`arrayprobe run --enhancements run.toml <raw files>` (the same package also installs
`arrayprobe-enhanced run`, which does the same; `arrayprobe run --enhancements` is the primary
form). It writes corrected copies as
`<stem>.enh.<kind>.nc` beside the untouched engine output and records in a sidecar whether each
correction was applied or skipped, and why.

One of the defaults is not in that package: the v3.5 engine's stray-pixel correction. When an image is one particle plus a few far-off stray pixels, it keeps the particle
and sizes it alone. Turn it off with `--stray-pixel off` or `stray_pixel_fix = false` in the
configuration (the command line wins); the `.call` stamp records it (`stray_pixel=on:g8,n2,m9`),
and the output's `image_stray_pixels_removed` says which images it changed. Worked example: `examples/5_data_quality/04_stray_pixel_images.ipynb`.

Where the developers fixed a defect in v3.5, its correction is refused on v3.5, since applying it
would correct twice ([Enhancements by engine](23-enhancements-by-engine.md) lists which). Each
correction states its effect, measured with and without it on the same data, including those that
change nothing ([Enhancements](05-enhancements.md)). The opt-ins notebook
(`examples/2_processing/08_opt_ins.ipynb`) walks through switching them on.

## What you get: files and units

Every stage writes netCDF laid out as UIOOPS lays it out: the same variable names, dimensions and
attribute text. The v3.5 engine writes netCDF-4, as v3.5 does. No CF `Conventions` attribute
is written, and the units are the strings UIOOPS writes, not CF units.

| File | Holds |
|---|---|
| `<stem>.H.nc` | the decoded images |
| `proc.<stem>.H.nc` | one row per particle: size, habit, reject code, geometry, time |
| `sd.<stem>.H.nc` | one-second size distributions |
| `<flight>.combined.H.2DS.cdf` | a flight's size-distribution files stitched into one product |

In the size-distribution file the units read, as written: `conc_minR` in `cm-4`, `n` in `cm-3`,
`mass` in `g/cm4`, the bin edges `bin_min`, `bin_max` and `bin_mid` in `millimeter`, and `time` in
`HHMMSS`. The flight product carries no attributes at all: its units are in the variable names,
such as `Size Distribution cm-3` and `Number Concentration cm-3`, and its `Time Vector` is a
MATLAB serial date number.

Every output has a `<name>.call` sidecar recording which call wrote it (engine, profile, reject
thresholds, aircraft-speed file), because the netCDF file cannot say.


## Where to go deeper

- [Orientation for OAP scientists](12-orientation.md) — the same ground in UIOOPS and SODA-2 terms.
- [Installation](01-installation.md), then the [User guide](02-user-guide.md) — a synthetic flight
  runs with no campaign data.
- [Configuration](06-configuration.md) — the run file, choosing engine and profile.
- [Validation](04-validation.md) and [Known gaps](10-known-gaps.md) — the evidence, and its limits.
- [Enhancements](05-enhancements.md) — every correction and its measured effect.
- [For UIOOPS developers](07-findings.md) — what the port found in the MATLAB.
- [Glossary](11-glossary.md) and [CLI reference](13-cli-reference.md).
