# arrayprobe

[![tests](https://github.com/sgupta92/arrayprobe/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/sgupta92/arrayprobe/actions/workflows/tests.yml)
[![PyPI](https://img.shields.io/pypi/v/arrayprobe)](https://pypi.org/project/arrayprobe/)
[![docs](https://github.com/sgupta92/arrayprobe/actions/workflows/pages.yml/badge.svg?branch=main)](https://sgupta92.github.io/arrayprobe/)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23574623.svg)](https://doi.org/10.5281/zenodo.23574623)

**Documentation:** https://sgupta92.github.io/arrayprobe/

`arrayprobe` processes the raw data recorded by airborne optical array probes (OAPs), the
instruments that image cloud and precipitation particles as they pass through a laser beam. It reads
the probe's raw binary files (SPEC, DMT, PMS and SEA record formats: 2D-S, HVPS, CIP, PIP, 2DC, 2DP
and Fast2DC), reconstructs each particle's image, measures and accepts or rejects every particle,
and computes one-second particle size distributions, combined into one product per flight.

It is for anyone who works with OAP data: processing a field campaign's flights, re-processing an
old campaign with documented settings, or checking how a processed product was made. Every run
writes a `.call` record of exactly how each stage was called, so a result can be traced and
repeated.

Two processing engines ship, each a Python translation of an established processing code and
checked against that original running unmodified:

- **UIOOPS v3.5** (its repository is spelled UIOPS; the default), translated from the MATLAB processing code of the McFarquhar
  group, checked stage by stage and end to end against GNU Octave running v3.5's own sources.
- **SODA-2**, translated from NCAR's IDL code, checked against GDL running SODA-2's unmodified
  sources.

**Start here, with no real data:** [`examples/1_getting_started/01_start_here.ipynb`](examples/1_getting_started/01_start_here.ipynb)
processes a synthetic file and plots what came out, explaining each step.

![What a user runs: a raw probe file goes to the UIOOPS engine (v3.5, default) or the SODA-2 engine, both on their latest releases, with opt-in enhancements beside them, to a combined flight product; set apart below, the earlier v3.1.4 port that reproduced archived products is not part of the package and only gives confidence in the engines](docs/figures/package_overview.svg)

### Where to read next

![Three reading paths. To process data: the Quickstart below, then the User guide, Choosing an engine and Configuration. To understand the science: Orientation for OAP scientists, then the Scientist's guide, Known gaps and future work, and Enhancements. To maintain or validate the port: Why reproduce the original first, then Validation, Conventions and terms, and For UIOOPS developers](docs/figures/reading_path.svg)

Looking up a command or a function? The [CLI reference](docs/13-cli-reference.md) lists every `arrayprobe` command and flag, and the [API reference](docs/08-reference.md) links the public Python API, page by page. Each probe has its own page, listed in [The probes](docs/33-probes.md); the whole documentation is indexed in [the docs index](docs/00-index.md).

## Install

Needs Python 3.12 or newer. From PyPI:

```bash
pip install arrayprobe
```

Optional additions:

- `pip install "arrayprobe[extra]"` adds scipy, matplotlib and psutil (the inter-arrival fitting, plots, and the run's machine-load record).
- `pip install arrayprobe-uiops-enhancements arrayprobe-soda2-enhancements` adds the opt-in corrections
  for each engine.
- The example notebooks run from a clone of the repository (`git clone https://github.com/sgupta92/arrayprobe.git`),
  not from a `pip install`, and also need xarray and Jupyter: `pip install "arrayprobe[extra,zarr]" jupyter`.
  [Start here](docs/00b-start-here.md) walks through the first one.

The install also provides `uiops`, a small module that picks an arrayprobe engine; it is not the
UIOOPS MATLAB code. To run the test suite or work on the code, install from a clone as described in
[CONTRIBUTING.md](CONTRIBUTING.md).

## Quickstart

Run these from any empty folder; the same two lines work on Windows, Linux and macOS:

```bash
arrayprobe make-demo-flight --dense --with-config demo/base160101000000.2DS
arrayprobe run demo/run.toml demo/base160101000000.2DS --yes
```

The first command writes a synthetic raw 2D-S file and a settings file, `demo/run.toml`, beside it.
The second runs the full pipeline on it in seconds and ends by printing `ALL DONE`. No campaign data
is needed. The file name carries a flight date because the combine step groups a flight's files by
it.

The run also prints a `LOAD RECORD` line, which says whether other processes were busy during the
run. It matters only for quoting a run time, never for the results, and reads `UNRECORDED` without
psutil.

### What a run does

![A raw .2DS or .HVPS file passes through four stages, run by `arrayprobe run` (the `stages` key of its `run` table selects them): read-binary decodes it, imgproc frames and measures particles, sizedist computes one-second size distributions, and combine stitches a flight's files into one product; every output has a .call sidecar recording how the stage was called](docs/figures/pipeline_stages.svg)

### Look at the particles

A run's output folder can be browsed particle by particle, or rendered as image galleries:

```bash
arrayprobe triage --decoded-dir demo
arrayprobe gallery --decoded-dir demo --flight base160101000000.H --out demo/galleries
```

### Your own data

`arrayprobe run <config.toml> <flight>` processes your own flights: the choices live in the
configuration file ([Configuration](docs/06-configuration.md)), and `arrayprobe --help` lists
every command. If you cloned the source,
[`examples/start_here/README.md`](examples/start_here/README.md) walks through the same run
with its settings file.

## Running it faster

Opt-in parallelism on the default UIOOPS engine and on SODA-2, default serial, part of **this
package, not the enhancements**, because it moves no written byte. Measured, with its scope, in
[Processing speed](docs/32-processing-speed.md): UIOOPS v3.5's `--chunks 8` runs stage 3 (`imgproc`)
on a CIP file **2.5–2.6×** faster, all 40 variables byte-equal to the serial run; SODA-2's
`--jobs 12` runs its buffer loop on a CIP (SEA) file **3.70×** faster, all 35 arrays byte-equal.
The two figures come from different programs and stages and are not to be ranked against each other.

## Test (from a clone)

From a clone of the repository (see [CONTRIBUTING](CONTRIBUTING.md) for the development setup):

```bash
# Linux, macOS
python3.12 -m venv .venv && .venv/bin/python -m pip install -e ".[pinned]" -e enhancements_uiops -e enhancements_soda2
.venv/bin/python -m unittest discover -s tests -p "test_*.py"
.venv/bin/python -m ruff check src tests scripts enhancements_uiops enhancements_soda2
```

```powershell
# Windows, one command per line
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[pinned]" -e enhancements_uiops -e enhancements_soda2
.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.venv\Scripts\python.exe -m ruff check src tests scripts enhancements_uiops enhancements_soda2
```

A full run of the shipped suite: **unittest collects 4,728 tests on this release, and 656 of those skip** (they need an optional dependency, GNU Octave or GDL output, or data files not shipped with the release).

With `ARRAYPROBE_SLOW=1` and `ARRAYPROBE_HYGIENE=1` set, which add the slow and documentation
checks, the first command took 1,403 s (about 23 minutes) on a 10-core laptop (Intel Core
i7-1365U, 64 GB, Windows 11) with no other load, measured 2026-10-17 with the machine's load
recorded every 30 s. The same command run from `enhancements_uiops/` and from
`enhancements_soda2/` took 66 s and 5 s. CI (`.github/workflows/tests.yml`) sets both
variables and runs all three suites.

## Engines, corrections and validation

The package holds two engines: `arrayprobe_uiops`, the default, translated from UIOOPS v3.5, and
`arrayprobe_soda2`, translated from NCAR's SODA-2 (IDL). Translating them surfaced findings about the
original code. On engine 3.5 a batch run corrects data-destroying upstream defects by default,
recorded in each run's `.call` stamp (`--protective off` opts out; stray-pixel removal has its own
`--stray-pixel off`), and probes with no archived product get further corrections; the full list
is in [Choosing an engine](docs/27-choosing-an-engine.md#corrections-engine-35-applies-by-default).
Every other correction is opt-in, in the separate packages `arrayprobe-uiops-enhancements` and
`arrayprobe-soda2-enhancements`; the engines never depend on them.

Neither engine has an archived product of its own to be compared with, because none was ever
written by UIOOPS v3.5 or by this SODA-2 revision, so each is checked against its original running
unmodified. Before the v3.5 translation, an earlier translation of UIOOPS v3.1.4 was built to test
the approach against archived products. It is not part of this package. It reproduced archived
2D-S products from one field campaign on 15 flights, 10 exactly; on the other five, 49 of 55,008
non-zero cells differ (0.09 %). [Validation](docs/04-validation.md)
reports that result and how each engine is checked; findings the UIOOPS developers had already
fixed in v3.5 are marked there. Future UIOOPS and SODA-2 releases will be compared against these
translations and incorporated where relevant.

## Contributing

Questions, bug reports and proposed changes are welcome: email sid.gupta@anl.gov or open a GitHub issue on this repository's Issues page; see [CONTRIBUTING.md](CONTRIBUTING.md).

## Credits

**Author:** Siddhant Gupta (Argonne National Laboratory).
**Advisors and collaborators:** Joe O'Brien and Bobby Jackson (ANL), Greg McFarquhar and Yongjie
Huang (University of Oklahoma), Aaron Bansemer (NCAR MMM).
**Data providers:** Peter Brechner and Saurabh Patil (University of Oklahoma).

This package exists because of UIOOPS and SODA-2 and the work of their developers: the McFarquhar
group's UIOOPS developers, and Aaron Bansemer (NCAR), who wrote and maintains SODA-2. They wrote and
still maintain the originals; credit for the processing methods is theirs.

## Generative AI

Much of the porting, testing and documentation was written with the help of Anthropic's Claude,
under the author's direction; the author reviewed and is responsible for the result.

## Licence and citation

BSD-3-Clause, with the UIOOPS maintainers' permission; derived from UIOOPS (GPLv3 upstream). [LICENSE](LICENSE) and
[NOTICE.md](NOTICE.md) carry the full text and attribution. An independent port; it is not a UIOOPS or SODA-2 release.

Cite this package as: Gupta, S. (2026). arrayprobe (Version 0.1.0) [Computer software]. Zenodo.
[`10.5281/zenodo.23574623`](https://doi.org/10.5281/zenodo.23574623)

Please cite UIOOPS alongside it: McFarquhar et al. (2018),
[`10.5281/zenodo.1285969`](https://doi.org/10.5281/zenodo.1285969) (the methodology), and UIOOPS v3.5,
[`10.5281/zenodo.18945998`](https://doi.org/10.5281/zenodo.18945998) (the release the default engine
ports), and say which engine
produced your numbers.

`arrayprobe_soda2` translates NCAR's SODA-2 (3-clause BSD); a result derived from it cites
SODA-2, as its author asks:

> Aaron Bansemer. (2026). abansemer/soda2: v2.26.0 (Version v2.26.0) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.18331418
