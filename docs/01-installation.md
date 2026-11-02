# Installation
> Python 3.12 or newer, one dependency set, no compiler and no licensed software.

**In short:** `pip install arrayprobe`, plus `pip install arrayprobe-uiops-enhancements arrayprobe-soda2-enhancements` for the optional corrections packages. To run the suite or work on the code, the editable install is described in [CONTRIBUTING](../CONTRIBUTING.md). Nothing else is required; `[pinned]` installs every pinned dependency (numpy, netCDF4, scipy, matplotlib, numba, psutil, the optional zarr, xarray and pyarrow writers, and the test, lint and build tools); the two corrections packages are separate installs, and the suite needs them.

**The speed comes with this package's base install, and costs nothing in fidelity.** Both engines take
**opt-in parallelism proven byte-identical to the serial path by test — default serial, no accuracy
traded** — with no extra dependency: `--chunks` and `--jobs` are stdlib `multiprocessing`. Measured on CIP: v3.5 stage 3 **2.5–2.6×** (`--chunks 8`, 269.5 s → 103.0 s = 2.62×; a repeat read
2.48×; a contended run read 5.57× and is discarded, all 40
netCDF variables byte-equal) and the SODA-2 buffer loop **3.70×** (`--jobs 12`, 413.1 s → 111.7 s,
all 35 arrays byte-equal), on 12 logical cores. Both are CIP, one stage, one file — not a
package-wide multiplier. Only `--jit` needs anything more (numba). Every figure, its scope and
every case where a parallel run is **refused** rather than returning a fast wrong answer:
[Processing speed](32-processing-speed.md).

**See also** [User guide](02-user-guide.md) for what to run next · [Known gaps](10-known-gaps.md) for what is not implemented.

## From PyPI

Make a venv from Python 3.12 or newer, then install the package and, if you want them, the two
optional corrections packages:

```bash
py -3.12 -m venv .venv                                            # Windows
# python3.12 -m venv .venv                                         # Linux / macOS
.venv\Scripts\Activate.ps1                                         # Windows PowerShell (cmd: .venv\Scripts\activate)
# source .venv/bin/activate                                        # Linux / macOS
python -m pip install arrayprobe
python -m pip install arrayprobe-uiops-enhancements arrayprobe-soda2-enhancements   # optional
```

`arrayprobe` is enough to process data. `arrayprobe-uiops-enhancements` carries the opt-in
corrections for the UIOOPS engines and `arrayprobe-soda2-enhancements` those for the SODA-2 engine;
each depends on `arrayprobe` and is never imported by it.

## From a clone

The developer route: an editable install with every pinned dependency, the two corrections
packages and the test suite.

```bash
git clone https://github.com/sgupta92/arrayprobe.git
cd arrayprobe

py -3.12 -m venv .venv                                            # Windows
# python3.12 -m venv .venv                                         # Linux / macOS
.venv\Scripts\Activate.ps1                                         # Windows PowerShell (cmd: .venv\Scripts\activate)
# source .venv/bin/activate                                        # Linux / macOS
```

The editable install of the package and its two corrections packages, and running the suite, are described in [CONTRIBUTING](../CONTRIBUTING.md).

**Make the venv from Python 3.12 or newer.** `python --version` (`python3 --version` on Linux
and macOS) says which interpreter `venv` will copy; many Linux distributions still ship 3.11. On
an older interpreter pip stops with `No matching distribution found for numpy==2.5.3`, which does
not name the cause: delete the `.venv` and recreate it from 3.12 (`python3.12 -m venv .venv`, or
`py -3.12 -m venv .venv` on Windows).

**Windows and Linux/macOS differ in one path.** The venv is activated with
`.venv\Scripts\Activate.ps1` (PowerShell) or `.venv\Scripts\activate` (cmd) on Windows and `source .venv/bin/activate` on Linux and macOS. After
activation, `python` and `arrayprobe` are the venv's; the commands on this page and the rest of the
site use those two names.
To skip activation, call the venv's interpreter by path:

```bash
.venv/Scripts/python.exe -m arrayprobe --help   # Windows
# .venv/bin/python -m arrayprobe --help         # Linux / macOS
```

Check that the command line answers, in either of its two equivalent forms:

```bash
python -m arrayprobe --help
# or the console script: arrayprobe --help
```

From a clone, confirm the install by running the suite — **a run collects 4,728 tests on this release, no MATLAB, no Octave, no reference
data required** (the shipped source holds 5254 test methods; modules that need the undistributed upstream source trees skip as a whole, so a run counts fewer. How many of the collected tests skip is given below). The upstream sources (UIOOPS v3.5, SODA-2, and UIOOPS v3.1.4, kept only as the provenance record of an earlier translation used to validate the port and not shipped as an engine) are not redistributed; `scripts/upstream/` holds one SHA-256 manifest per source tree, listing the pinned upstream files, and `python scripts/fetch_upstream.py --dest <dir>` downloads them at the pinned commit, checks every hash and prints the environment-variable lines the skipped modules read. Most differential-oracle reference outputs are committed and run on a fresh clone.
Reference outputs cut from real campaign data are not distributed, so the checks that need them (among them the v3.5 sizeDist and combine drivers, the CIP/PIP/2DC/Fast2DC paths and the SODA-2 real-file runs) report as skipped, with the reason; those checks were run against Octave during development.

```bash
python -m unittest discover -s tests -p "test_*.py"
```

## From a source distribution

Build a source distribution from a clone and install it anywhere:

```bash
cd arrayprobe
python -m pip install build
python -m build                       # writes dist/*.whl and dist/*.tar.gz
pip install dist/arrayprobe-*.tar.gz  # into any environment you like
```

The tarball carries the tests **and the 72 tracked oracle fixtures**, so the suite means the same
there as in a clone. Run it from the unpacked directory; from a clone the tests would import the
source tree instead of what you installed:

```bash
tar xzf dist/arrayprobe-*.tar.gz && cd arrayprobe-*/
pip install ".[pinned]"   # the pinned dependency set
python -m unittest discover -s tests -p "test_*.py"
```

**unittest collects 4,728 tests on this release, and 656 of those skip** — measured on Python 3.12, the
declared floor. The skips are the gitignored campaign data and the optional pieces, each named in
its own skip message.

The shortfall against a clone is not a gap: thirty test modules check that *this
repository's* documents agree with each other, which means nothing outside a working tree, so they
do not ship.
`MANIFEST.in` names them and says why.

## Verifying a download

`SHA256SUMS` is not in the source tree: it is attached to the [v0.1.0 GitHub Release](https://github.com/sgupta92/arrayprobe/releases/tag/v0.1.0), one `<sha256>  <path>` line for every file of the source, sorted by path. Download it from that release page into the root of the unpacked source (the zip or tar.gz GitHub offers for the tag, or a clone with LF line endings), then run the check from that root.

```bash
sha256sum -c SHA256SUMS          # Linux; on macOS: shasum -a 256 -c SHA256SUMS
```

```powershell
Get-Content SHA256SUMS | ForEach-Object { $h, $p = $_ -split '  ', 2; if ((Get-FileHash -Algorithm SHA256 -LiteralPath $p -ErrorAction SilentlyContinue).Hash -eq $h) { "OK      $p" } else { "FAILED  $p" } }
```

Success: `sha256sum` prints `<path>: OK` for every file and no `FAILED` line (a mismatch or a missing file prints `FAILED` and the run ends with a `WARNING` line); the PowerShell loop prints a line beginning `OK` for every file and none beginning `FAILED`. A file that differs, or is missing, is reported by name. The manifest guards against a damaged or altered download; it is not a signature. A git clone on Windows with `core.autocrlf=true` rewrites text files to CRLF, so its hashes differ from the manifest's; use `git clone -c core.autocrlf=false`, or rely on the commit hash.

The wheels and source distributions of a release also carry Sigstore build attestations, signed by the release workflow itself with no key held by anyone. Download a file and check it with `gh attestation verify <file> --repo sgupta92/arrayprobe`. A passing check proves that the file was built by that repository's release workflow, from the commit the attestation names, and that it has not changed since. It says nothing about who the author is, and it does not vouch for the code's correctness.

## Why the floor is 3.12

The `[pinned]` extra pins numpy exactly, because a floating numpy is a silent fidelity risk for a
package whose claim is about specific numbers, and the pinned version needs Python 3.12. The
package may import under 3.11 with an older numpy, but no validated figure on this site was
measured there. All three `pyproject.toml` files declare `>=3.12` and a test asserts they agree with
each other and with this page.

## How the suite is verified

The tests run in [GitHub Actions](https://github.com/sgupta92/arrayprobe/actions/workflows/tests.yml)
on **Linux, macOS and Windows**, against **Python 3.12 and 3.13** — the port's suite and the
enhancements' suite, plus a job that builds the source distribution and installs it clean: eleven
jobs on a manual dispatch or a release tag, five on a branch push. A branch push or pull request runs the Linux legs; a manual dispatch
and a release tag run all three operating systems (macOS and Windows on Python 3.12), so the cross-platform claim is anchored to a
named run rather than the latest commit.

Before comparing your own run to a figure quoted here:

- **Line coverage is platform-dependent.** Linux reports 91 % where one Windows machine
  reports 92 % — 24 statements' difference. Any single coverage number needs the
  platform named beside it. Coverage is reported and never enforced.
- **Two derived variables are not bit-identical across platforms**, as expected: `massBL` is a
  fractional power and `vt` comes out of `single_vt.m`, so both resolve to the platform's `pow()`,
  which glibc, Apple's libm and Microsoft's UCRT need not agree on in the last bit. The measured differences are ~1e-15 relative, four orders
  of magnitude inside the tolerance class they are checked against. See
  [Conventions](09-conventions.md).

## Requirement sets

The `[pinned]` extra in `pyproject.toml` pins every runtime, development and optional dependency
exactly, and is what this project runs. For a reproducible environment, install it from a checkout:

```bash
pip install -e ".[pinned]"
```

It covers `numpy` and `netCDF4` (runtime); `pytest`, `ruff`, `mypy`, `reportlab` and `pypdf` (the
suite itself is stdlib `unittest`; the last two build and read back the package's software-paper
PDF under `paper/`); `scipy` and `matplotlib`, needed only by the inter-arrival fit and plotting;
`numba`, which compiles two hot reject kernels (`--jit`); and `psutil`, which records the
machine's load beside a run's timings (without it each run prints `LOAD RECORD: UNRECORDED`).

`scipy` and `numba` are imported lazily, so the core installs and runs — more slowly, in numba's
case — without a compiler toolchain.

### Installing from the pins or from the metadata is not the same thing

The `[pinned]` extra pins exact versions and is what this project runs. `pip install arrayprobe[extra]`
resolves the *ranges* in `pyproject.toml` instead, and the two are deliberately not identical:

- **`scipy>=1.16`** is a real floor, not a formality. Below it, `scipy.optimize.least_squares`
  converges elsewhere on the inter-arrival fit, with numpy held fixed:
  scipy 1.13, 1.14 and 1.15 each move the tau-derived shattering threshold by more than this
  project's own tolerance, and 1.16 does not. It affects only a run that supplies a real threshold
  file, not one that takes the 6 µs default.
- **`numba` is in `[pinned]` and not in `[extra]`; it has its own `[jit]` extra
  instead.** `pip install arrayprobe[extra]` alone leaves `HAVE_NUMBA` false, the pure-Python
  kernels in use, and **nine kernel-equivalence tests skipping rather than running**. numba stays
  out of `[extra]` because it constrains numpy from *above*, and folding it in could make that
  extra unresolvable on a numpy the core supports; `tests/test_dependency_declarations.py` holds
  the decision. `--jit` needs `pip install arrayprobe[jit]` as well (or `[extra,jit,zarr]` together; the example notebooks need `[zarr]`, which carries xarray);
  the driver names that command and stops before decoding anything if numba is missing.
- **`netCDF4>=1.7.2`** is the first release with wheels on every supported Python. On 3.13 an
  older one builds from source and fails with *did not find netCDF version 4 headers*.

## To run the example notebooks, add three things

The port and its suite need none of `xarray`, `matplotlib` and `jupyter`; the
[example notebooks](../examples/) need all three. **The notebooks run from a clone of the
repository**: they start at the repository root and read its `scripts/` and `tests/data/`
folders, which a PyPI install does not contain. A PyPI install still needs the packages below;
the `extra` and `zarr` extras bring `matplotlib` and `xarray`:

```bash
python -m pip install "arrayprobe[extra,zarr]" jupyter
```

From a clone, `".[pinned]"` already holds `matplotlib` and `xarray`, so only
`python -m pip install jupyter` is needed.

Then **start Jupyter from the repository root**, not from `examples/`:

```bash
python -m jupyter notebook examples/
```

Jupyter sets each notebook's working directory to the folder it was launched in, and the
notebooks reach the repository's driver scripts by relative path (`sys.path.insert(0, "scripts")`).
Launched from `examples/`, every one of them fails on its second cell with
`ModuleNotFoundError: No module named 'make_demo_flight'`, which looks like a broken install and
is not.

## Enhancements (optional)

Corrections and new science live in **two separate packages** that the port never depends on:

```bash
python -m pip install arrayprobe-uiops-enhancements arrayprobe-soda2-enhancements
```

`enhancements_uiops` is the corrections package for UIOOPS; `enhancements_soda2` holds opt-in corrections for findings against `arrayprobe_soda2` (NCAR SODA-2's Python port). They install into the same virtual environment on purpose — see
[Enhancements](05-enhancements.md). Uninstalling either leaves the port's suite untouched, which is
asserted by a test rather than assumed.

## Octave and GDL (optional, for the differential oracles)

Neither is needed to run the port or its tests — only to *regenerate* reference outputs. **GNU Octave**
(`winget install GNU.Octave` on Windows, or your package manager's `octave` on Linux and macOS) runs the UIOOPS v3.5 `.m` sources unmodified; add `pkg load netcdf` for the netCDF-reading oracles, and the three `CGAL_*` MEX sources
compile unmodified under `mkoctfile --mex`. **GDL** (GNU Data Language) plays the same part for the
SODA-2 port's IDL `.pro` sources.

## Do I need CGAL?

**No** — not to install, not to run, not to reproduce anything in the validation. The original
ships three geometry routines as compiled MEX binaries for Linux and Intel Mac only, and one of
them produces the default particle size, so their absence stops a MATLAB run outright on any
other platform. This package computes all three in pure Python and NumPy: no C++ dependency, no
MEX, no compiler step.

Only *two* of the three are CGAL at all: the third, `CGAL_minR`, calls Bernd Gärtner's standalone
`Miniball`.
