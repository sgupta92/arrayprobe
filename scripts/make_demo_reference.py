# SPDX-License-Identifier: BSD-3-Clause
"""Build, and check a fresh run against, the tracked demo-flight reference.

**Why this exists.** The author, 2026-09-11: *"just how uiops has example data, we need to
have example data (maybe the same one?) that users can test their run against, or validation
against or test their thresholds, etc."* ``arrayprobe.tools.make_demo_flight`` already answers
"what input do I run" with no campaign data required;
this
answers "what should my output look like" -- a small tracked reference triple a fresh clone can
diff itself against with no campaign data and no Octave.

**What is tracked, and what is digested instead.** Eight small files travel under
``tests/data/demo_flight_v314_*`` (raw ``.2DS``, the decoded ``.cdf``, ``proc.nc``, ``sd.nc``, and
the three ``.call`` sidecars) plus a ``digest.json``. The **combined** flight product
(``base160101000000.combined.H.2DS_2.cdf``) is measured at 68,129,052 bytes for this same 5-second
demo flight -- too large to track sensibly beside 77 other fixtures averaging a few hundred KB --
so it is never committed; instead :func:`digest` records every one of its variables' sha256 over
``np.asarray(v[:]).tobytes()``, plus shape and dtype, which is exactly as strong a guarantee for a
regression test and costs a few KB.

**Determinism, measured 2026-09-13 (three separate-process runs).** Every file above is
byte-identical across runs *except* ``sd.*.nc``, which differs only in the global attributes
``Creation Time`` and ``Data Source`` (``sizedist.py:1843`` writes ``str(infile)``, a path that
varies with the build's own temp directory). Neither attribute is a *variable*, so
:func:`arrayprobe.compare.compare_files` -- which walks named variables, never global attributes --
is already blind to both, and comparing ``.call`` sidecar text (not file attributes) is too. That is
why R2's guard is comparison-by-tolerance-class and sidecar text, not a raw byte-diff of the whole
file.

**The engine decision.** This reference is produced by the **v3.1.4 engine**
(``scripts/run_flight.py``'s stage functions), under the driver's *module defaults* -- because that
is
exactly what a fresh clone's documented quickstart gets today
(``docs/02-user-guide.md``: ``make_demo_flight.py`` then ``run_flight.py``) and what
notebooks 01/03/07 execute. Concretely, from the ``.call`` sidecars this build actually wrote (read,
not assumed):

* ``profile=oracles-production`` (``run_flight.PROFILE``, i.e. ``ORACLES_PRODUCTION`` --
  ``rej_zero_area=True, rej_split=True, rej_hollow=False, shadowed_area=25, max_edge_img_ar=4,
  max_comp_img_ar=4``) -- the ORACLES production reject configuration, because neither this tool nor
  the notebooks call ``run_flight.use_preset(...)``, so ``run_flight.PROFILE`` stays whatever the
  module was imported with.
* ``iat_file=2DS_intArrThreshold_MISSING.cdf`` -- ``sizeDist``'s twelfth-argument call (the ORACLES
  production call).
* The active *campaign preset* is ``run_flight.ACTIVE`` at its module default,
  ``ORACLES_2016_2DS_H`` -- **not** ``DEMO_2DS_H`` -- because nothing here calls ``use_preset``
  either, matching what ``examples/3_validation/01_validate_against_a_product.ipynb``
  cell 2 actually runs.

**This is not a recommendation.** The reject thresholds above are the *ORACLES 2016 production*
configuration, carried here only because it is the driver's compile-time default -- not because it
is the configuration a new user processing their own campaign should choose. The author holds
that the *package's* default thresholds should not be ORACLES-specific; this reference exists to let
anyone check their own install and their own run reproduces *this exact, named, ORACLES-lineage*
call, which is what the v3.1.4 engine exists to validate (author: "only reason and need for 314
port was oracles based validation"). It says nothing about what a fresh campaign should run with.

**Not science.** The demo flight is five synthetic particles over five seconds. ``digest()``'s
``used_bin_count_sum`` is 0 and that is the honest number: none of the five particles is large
enough to reach a used bin (``bin_min[5]`` = 0.055 mm; the demo particle's ``image_diam_minR`` is
0.048 mm). This reference proves the pipe reproduces itself bit-for-bit, not that its output means
anything -- see ``tests/test_end_to_end.py``'s module docstring for the same limit.

**The v3.5 reference (since 2026-09-13).** ``tests/data/demo_flight_v35_*`` is made through **the
one line a user runs** -- ``python -m arrayprobe.cli run demo_flight_v35_run.toml <raw.2DS>``, i.e.
``arrayprobe run`` -- as a **subprocess**, not in-process: ``arrayprobe run`` goes through the
shared ``sys.modules["run_flight"]``, and ``run_flight.main`` rebinds that module's own globals
(``ENGINE``, ``PROFILE``, ``TAS_FILE``, ``ACTIVE``, ...) that every ``test_run_from_config*.py``
binds to, so building the reference in-process would leak into whatever ran before or after it in
the same process (measured: a subprocess build leaves ``"run_flight" in sys.modules`` ``False`` in
the caller; see :func:`build_v35`'s docstring and
``TheSharedDriverIsNeverTouchedByTheV35Build`` in ``tests/test_demo_reference.py``, which mutates
this into an in-process ``cli.main([...])`` call once by hand to confirm the guard actually fires).
``check_v35()`` (one subprocess build plus the comparison) measured 3.5 s on this machine,
2026-09-13.

It runs under **``stock-v3.5``, which IS the configuration a new user should run** -- nothing in
``RUN_TOML_V35`` is ORACLES-specific -- the opposite of the v3.1.4 reference's caveat above, plus a
seeded synthetic aircraft TAS file (:func:`write_aircraft_v35`; seed 143, 130 +/- 1 m/s jitter,
HHMMSS 60638-60647, margin either side of the demo's own decoded HK rows at 60640-60643).

What is tracked and what is digested mirrors the v3.1.4 set's own reasoning: nine small files
(``run.toml``, ``aircraft.cdf``, ``proc.nc``, ``sd.nc``, four ``.call`` sidecars, ``digest.json``)
are tracked; the raw input is **not** tracked a second time -- it is byte-identical to
``demo_flight_v314_raw.2DS`` (measured 2026-09-13) and is digested by sha256 instead; the decoded
image ``.nc`` (343,380 B) and the combined product (15,316,252 B) are too large to track sensibly
and are digested per variable exactly as :func:`digest` does for the v3.1.4 combined product.

**Determinism, measured 2026-09-13 (two separate-process builds).** The v3.5 engine writes
NETCDF4 (HDF5), uncompressed. The combined ``.cdf`` and all four ``.call`` sidecars are
byte-identical across builds. The image/proc/sd ``.nc`` files are **not** byte-identical, but every
variable's *values* are (``np.array_equal``, NaN-aware) and every variable *attribute* is too -- the
only differences are five global attributes: image ``Creation Time``; proc ``Creation Time`` +
``Image Source`` (an absolute path, ``imgproc.py:474``); sd ``Creation_Time`` + ``Data_Source``
(absolute path, ``sizedist.py:672``). So, as for the v3.1.4 set, the guard here compares by
variable/tolerance class and sidecar text, never raw file bytes.

**The four v3.5-only proc variables.** v3.5's ``imgProc_sm`` writes ``image_xpos``, ``image_ypos``,
``fine_detail_ratio`` and ``sphericity``, which v3.1.4 never did (``arrayprobe_uiops/imgproc.py``
``:715-716``, ``:736-737``; v3.5 ``imgProc_sm.m:1359-1360, 1381-1382``). ``compare.PROC_CLASSES``
stays the v3.1.4 table -- ``tests/test_compare.py`` pins it to the v3.1.4 profiles' own variable
lists -- so a v3.5 proc file is compared against ``compare.PROC_CLASSES_V35`` instead, or these
four are reported unclassified and ``accepted()`` is ``False``.

**The bounded 4-vs-5 investigation (2026-09-13), and what it actually found.** Before this
reference was built, the "does the v3.5 sd have fewer ``Time`` rows than the v3.1.4 one for the
same demo flight" question was checked directly, because a reference must not freeze an unexplained
cross-engine difference. **There is no cross-engine difference to explain**: the tracked
``demo_flight_v314_digest.json`` already records ``"n_seconds": 4`` (not 5, as an earlier note
claimed -- read directly off the file, 2026-09-13), and a fresh v3.5 build of the same demo flight
also gives ``n_seconds == 4``. Both engines produce identical ``.tas.csv`` sidecars for this raw
file (rows at HHMMSS 60640.25-60643.25, four rows), traced to ``read_binary_SPEC.m``'s own
housekeeping-packet scan -- ``sizeDist.m`` merely takes ``n_sec = length(tas)`` from whatever S2
wrote (v3.1.4
``sizeDist.m``/``sizedist.py:881``; v3.5 ``sizeDist.m:664`` / ``arrayprobe_uiops/sizedist.py:841``),
so a Time-row count difference could only ever come from S2, not from ``sizeDist.m``/``sizedist.py``
itself. (v3.5's own ``read_binary_SPEC.m:297`` does tighten S2's per-buffer scan bound to
``while iii+4<=2048`` from v3.1.4's ``read_binary_SPEC.m:197`` ``while iii<=2048`` -- a real,
documented v3.5 change, faithfully ported at ``arrayprobe_uiops/spec.py``'s ``get_img_v35`` -- but
it
does not affect this particular demo file: the housekeeping packet in every window here sits at
``iii=1``, nowhere near either bound, so both engines find the same four packets.)


Usage, from the repository root::

    .venv/Scripts/python.exe scripts/make_demo_reference.py               # both engines, v3.5 first
    .venv/Scripts/python.exe scripts/make_demo_reference.py --engine 3.5  # the default engine only
    .venv/Scripts/python.exe scripts/make_demo_reference.py --write --engine 3.5    # (re)write v3.5
    .venv/Scripts/python.exe scripts/make_demo_reference.py --write --engine 3.1.4  # (re)write
    v3.1.4
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import netCDF4
import numpy as np

from arrayprobe_uiops.sizedist_core import GOOD_REJECT_CODES

#: image_auto_reject values sizeDist accepts ("0HhuR"): hollow H/h are kept, not rejected.
_ACCEPTED_CODES = [ord(c) for c in GOOD_REJECT_CODES]

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scrub_paths import scrub_output  # noqa: E402

REF_DIR = Path(__file__).resolve().parents[1] / "tests" / "data"
PREFIX = "demo_flight_v314_"
N_SECONDS = 5
STEM = "base160101000000"

_TOOLS = Path(__file__).resolve().parent

#: The eight tracked filenames (under ``REF_DIR``, prefixed with ``PREFIX``) plus the digest.
TRACKED_NAMES: tuple[str, ...] = (
    "raw.2DS", "image.cdf", "proc.nc", "sd.nc",
    "image.call", "proc.call", "sd.call", "digest.json",
)

PREFIX_V35 = "demo_flight_v35_"

#: The nine tracked v3.5 filenames (under ``REF_DIR``, prefixed ``PREFIX_V35``). The raw input is
#: NOT here: it is byte-identical to ``demo_flight_v314_raw.2DS`` (measured 2026-09-13) and is
#: digested by sha256 instead of being tracked twice. The image ``.nc`` (343 KB) and the combined
#: product (15.3 MB) are digested per variable rather than tracked.
TRACKED_NAMES_V35: tuple[str, ...] = (
    "run.toml", "aircraft.cdf", "proc.nc", "sd.nc",
    "image.call", "proc.call", "sd.call", "combined.call", "digest.json",
)

#: The configuration the v3.5 reference is made with -- and the file a user runs it from. Tracked
#: as ``demo_flight_v35_run.toml`` AND held here, so ``_compare_v35`` can check the tracked file
#: still says what the tool ran (two sides, two places). stock-v3.5 IS the configuration a new user
#: should run: nothing in it is ORACLES-specific (the opposite of the v3.1.4 reference's caveat).
RUN_TOML_V35 = """\
# The v3.5 demo-flight reference's run configuration (built by scripts/make_demo_reference.py).
# stock-v3.5 is the configuration a new user should run: nothing here is ORACLES-specific.
# Paths are relative to this file. `arrayprobe run demo_flight_v35_run.toml <raw.2DS>`.
[fidelity]
profile = "stock-v3.5"

[run]
engine = "3.5"
preset = "DEMO_2DS_H"
out = "_decoded"
stages = "234c"
tas_file = "demo_flight_v35_aircraft.cdf"

[combine]
borrowed = true
"""

#: The synthetic aircraft TAS series v3.5's imgProc_sm always takes. Seeded so the tracked file is
#: reproducible; jittered so the series is not a constant the pipeline could ignore unnoticed.
AIRCRAFT_SEED = 143
AIRCRAFT_TAS_MS = 130.0        # the demo flight's own embedded TAS (make_demo_flight's
                                # default; S2's .tas.csv)
AIRCRAFT_JITTER_MS = 1.0
AIRCRAFT_FIRST_HHMMSS = 60638  # the demo's own HK/TAS rows land at 60640..60643 (measured
                                # 2026-09-13, see the module docstring's "The v3.5 reference"
                                # section); margin each side
AIRCRAFT_N_RECORDS = 10


def write_aircraft_v35(path: Path) -> Path:
    """One NETCDF3_CLASSIC file, dimension ``time``, variables ``Time`` (HHMMSS, f8) and ``TAS``
    (m/s, f8) -- the shape ``tests/test_run_from_config_v35._aircraft`` established the v3.5 run
    accepts. No creation-time attribute is written, so the file is byte-deterministic."""
    rng = np.random.default_rng(AIRCRAFT_SEED)
    n = AIRCRAFT_N_RECORDS
    hhmmss = AIRCRAFT_FIRST_HHMMSS + np.arange(n, dtype=np.float64)
    tas = np.round(AIRCRAFT_TAS_MS + rng.normal(0.0, AIRCRAFT_JITTER_MS, n), 3)
    with netCDF4.Dataset(str(path), "w", format="NETCDF3_CLASSIC") as ds:
        ds.createDimension("time", n)
        ds.createVariable("Time", "f8", ("time",))[:] = hhmmss
        ds.createVariable("TAS", "f8", ("time",))[:] = tas
    return path


def _load_tool_module(name: str):
    """Load ``scripts/<name>.py`` by file path, the way ``tests/test_end_to_end.py`` does.

    Not a package import: ``scripts/`` is a repository directory, never shipped in the
    installed package, so both driver scripts have to be reached by path.

    Registered under a PRIVATE name, never the shared ``run_flight`` /
    ``make_demo_flight`` that ``arrayprobe run`` and the tests drive: this tool
    silences its copy's ``log``, and doing that to the shared object silenced
    every later ``arrayprobe run`` in the same process (found at the pair F merge,
    2026-09-13, as four refusal tests capturing no output). ``sys.modules`` still
    holds the copy while it executes, because a dataclass resolves its module there.
    """
    private = f"_make_demo_reference_{name}"
    spec = importlib.util.spec_from_file_location(private, _TOOLS / f"{name}.py")
    assert spec is not None and spec.loader is not None  # a sibling .py file of this tool
    module = importlib.util.module_from_spec(spec)
    sys.modules[private] = module
    spec.loader.exec_module(module)
    return module


def build(out_dir: Path, n_seconds: int = N_SECONDS) -> dict[str, Path]:
    """Generate the demo flight and run S2 -> S3 -> S4 (production call) -> S4c, exactly the
    way ``examples/3_validation/01_validate_against_a_product.ipynb`` cell 2 does it --
    same stage functions,
    same combine call, no ``use_preset`` -- so a fresh notebook run and this tool's output are
    the same computation.

    Returns a dict of the paths built: ``raw``, ``image``, ``proc``, ``sd``, ``combined``, and
    the three ``.call`` sidecar paths (``image_call``, ``proc_call``, ``sd_call``).
    """
    make_demo_flight = _load_tool_module("make_demo_flight")
    run_flight = _load_tool_module("run_flight")
    run_flight.log = lambda *a, **kw: None  # silence, as test_end_to_end.py does

    out_dir = Path(out_dir)
    raw = out_dir / f"{STEM}.2DS"
    make_demo_flight.build_demo_flight(raw, n_seconds=n_seconds)

    image = run_flight.stage2(raw, out_dir)
    proc = run_flight.stage3(image, out_dir)
    sd = run_flight.stage4(proc, raw.stem, out_dir)

    from arrayprobe import combine_sizedist

    stem = raw.stem
    flight_date = f"20{stem[4:10]}"
    summary_time = "_".join(stem[i:i + 2] for i in range(4, 16, 2))
    combined = out_dir / f"{stem}.combined.H.2DS_2.cdf"
    combine_sizedist([str(sd)], str(combined), flight_date=flight_date,
                     summary_time=summary_time)

    return {
        "raw": raw,
        "image": image,
        "proc": proc,
        "sd": sd,
        "combined": combined,
        "image_call": run_flight.call_path(image),
        "proc_call": run_flight.call_path(proc),
        "sd_call": run_flight.call_path(sd),
    }


#: The load recorder's switch, read by ``scripts/run_flight.py`` (``LOAD_RECORD_ENV`` there). Named
#: here as a literal rather than imported, because importing ``run_flight`` into this process is
#: exactly what ``build_v35`` avoids (its docstring).
LOAD_RECORD_ENV = "ARRAYPROBE_LOAD_RECORD"


def demo_build_env() -> dict[str, str]:
    """The environment ``build_v35``'s subprocess runs under: this process's, with the load
    recorder switched off.

    A demo build's wall-clock time is a budget (the timeouts here and in the tests), never a
    figure anyone quotes, so it needs no load record, and without the switch every build left a
    ``.load.json`` beside the demo outputs and spent the recorder's snapshots (about 3.3 s of CPU
    each on the author's machine). The load-record rule (a
    wall-clock figure is quotable only from a run that recorded the machine's load) is
    unaffected: these timings are not quoted. Only this subprocess's environment changes; the
    caller's ``os.environ`` is untouched.
    """
    env = dict(os.environ)
    env[LOAD_RECORD_ENV] = "off"
    return env


def build_v35(out_dir: Path, n_seconds: int = N_SECONDS) -> dict:
    """Generate the demo flight and the seeded aircraft file into ``out_dir``, write
    ``RUN_TOML_V35`` beside them, and run **the one line a user runs** --
    ``python -m arrayprobe.cli run <toml> <raw>`` -- as a subprocess (see the module docstring
    for why not in-process). Returns the built paths plus ``"command"`` (the line, for display)
    and ``"log"`` (the driver's stdout).

    **Why a subprocess, not ``cli.main`` in-process.** ``arrayprobe run`` goes through the SHARED
    ``sys.modules["run_flight"]``, and ``run_flight.main`` sets that module's own globals
    (``ENGINE``, ``PROFILE``, ``TAS_FILE``, ``ACTIVE``, ...) that every ``test_run_from_config*.py``
    binds to. A subprocess cannot leak into this process (measured: ``"run_flight" in sys.modules``
    stays ``False`` in the caller after a subprocess build), needs no restore list that would rot
    when the driver gains a global, and IS the user's command line. Cost: ~2.0 s per build
    including interpreter start (measured 2026-09-13).
    """
    make_demo_flight = _load_tool_module("make_demo_flight")   # private copy, as build() does
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = out_dir / f"{STEM}.2DS"
    make_demo_flight.build_demo_flight(raw, n_seconds=n_seconds)
    aircraft = write_aircraft_v35(out_dir / f"{PREFIX_V35}aircraft.cdf")
    toml = out_dir / f"{PREFIX_V35}run.toml"
    toml.write_text(RUN_TOML_V35, encoding="utf-8")

    cmd = [sys.executable, "-m", "arrayprobe.cli", "run", str(toml), str(raw)]
    run = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                         errors="replace", timeout=600, env=demo_build_env())
    if run.returncode != 0:
        raise RuntimeError(
            f"`{' '.join(cmd)}` failed with rc={run.returncode}:\n{run.stdout}\n{run.stderr}")

    decoded = out_dir / "_decoded"
    image = decoded / f"{STEM}.H.nc"
    proc = decoded / f"proc.{STEM}.H.nc"
    sd = decoded / f"sd.{STEM}.H.nc"
    # A v3.5 run names its product without ``_2`` since 2026-10-15; accept the older name.
    from arrayprobe_uiops import decode_naming as dn
    combined = dn.existing_combined_path(decoded, STEM)
    missing = [str(p) for p in (image, proc, sd, combined) if not p.is_file()]
    if missing:
        raise RuntimeError(
            f"`arrayprobe run` returned 0 but did not write: {missing}\n{run.stdout}")
    return {
        "raw": raw, "aircraft": aircraft, "toml": toml,
        "image": image, "proc": proc, "sd": sd, "combined": combined,
        # run_flight's sidecar convention is <output>.call (read_stamp/call_path); spelled here
        # rather than imported so the shared driver is never loaded into this process.
        "image_call": Path(f"{image}.call"), "proc_call": Path(f"{proc}.call"),
        "sd_call": Path(f"{sd}.call"), "combined_call": Path(f"{combined}.call"),
        "command": " ".join(cmd), "log": run.stdout,
    }


def digest(paths: dict) -> dict:
    """A JSON-able fingerprint of the combined product, plus headline counts read from the files.

    The combined product (68,129,052 bytes, measured 2026-09-13) is too large to track, so this is
    what a fresh run is checked against instead: every variable's sha256 over
    ``np.asarray(v[:]).tobytes()``, its shape and dtype. The three ``.call`` sidecars' text rides
    along too -- the written statement of which configuration produced this digest, so a reader of
    ``digest.json`` never has to go find the sidecars separately.
    """
    variables: dict[str, dict] = {}
    with netCDF4.Dataset(str(paths["combined"])) as ds:
        for name in sorted(ds.variables):
            arr = np.asarray(ds.variables[name][:])
            variables[name] = {
                "sha256": hashlib.sha256(np.ascontiguousarray(arr).tobytes()).hexdigest(),
                "shape": list(arr.shape),
                "dtype": str(arr.dtype),
            }

    with netCDF4.Dataset(str(paths["proc"])) as ds:
        n_particles = len(ds.dimensions["time"])
        reject = np.asarray(ds.variables["image_auto_reject"][:])
        n_accepted = int(np.count_nonzero(np.isin(reject, _ACCEPTED_CODES)))

    with netCDF4.Dataset(str(paths["sd"])) as ds:
        n_seconds = len(ds.dimensions["Time"])
        # Used bins are 6..128 (1-based, sizeDist's own convention) -> zero-based 5:128.
        count = np.asarray(ds.variables["count"][:])
        used_bin_count_sum = float(np.nansum(count[:, 5:]))

    return {
        "combined": variables,
        "call_sidecars": {
            "image": Path(paths["image_call"]).read_text(),
            "proc": Path(paths["proc_call"]).read_text(),
            "sd": Path(paths["sd_call"]).read_text(),
        },
        "n_particles": n_particles,
        "n_accepted": n_accepted,
        "used_bin_count_sum": used_bin_count_sum,
        "n_seconds": n_seconds,
    }


def write_reference() -> None:
    """Build to a temp dir and copy the eight tracked files (plus ``digest.json``) into
    ``REF_DIR``."""
    REF_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        paths = build(Path(tmp), N_SECONDS)
        shutil.copyfile(paths["raw"], REF_DIR / f"{PREFIX}raw.2DS")
        shutil.copyfile(paths["image"], REF_DIR / f"{PREFIX}image.cdf")
        shutil.copyfile(paths["proc"], REF_DIR / f"{PREFIX}proc.nc")
        shutil.copyfile(paths["sd"], REF_DIR / f"{PREFIX}sd.nc")
        shutil.copyfile(paths["image_call"], REF_DIR / f"{PREFIX}image.call")
        shutil.copyfile(paths["proc_call"], REF_DIR / f"{PREFIX}proc.call")
        shutil.copyfile(paths["sd_call"], REF_DIR / f"{PREFIX}sd.call")
        # path prefixes -> <repo>, <tmp>, ~
        scrub_output(*(REF_DIR / f"{PREFIX}{n}" for n in ("image.cdf", "proc.nc", "sd.nc")))
        d = digest(paths)
        (REF_DIR / f"{PREFIX}digest.json").write_text(
            json.dumps(d, indent=1, sort_keys=True) + "\n")


def _compare(paths: dict, ref_dir: Path) -> list[str]:
    """The comparison ``check()`` runs, factored out so a test can point ``ref_dir`` at a
    deliberately mutated copy of the tracked reference and confirm the guard actually fires
    (``tests/test_demo_reference.py::TheComparisonIsNotVacuous``).

    The two sides always come from different places: ``paths`` is a just-built fresh run;
    ``ref_dir`` is where the tracked (or, in a test, mutated) reference lives.
    """
    from arrayprobe import compare

    problems: list[str] = []

    tracked_raw = ref_dir / f"{PREFIX}raw.2DS"
    fresh_bytes = Path(paths["raw"]).read_bytes()
    tracked_bytes = tracked_raw.read_bytes()
    if fresh_bytes != tracked_bytes:
        problems.append(
            f"raw.2DS: {len(fresh_bytes)} fresh bytes vs {len(tracked_bytes)} tracked bytes "
            f"in {tracked_raw} -- the raw file is no longer byte-identical to the tracked one")

    tracked_image = ref_dir / f"{PREFIX}image.cdf"
    with netCDF4.Dataset(str(paths["image"])) as a, netCDF4.Dataset(str(tracked_image)) as b:
        names_a, names_b = set(a.variables), set(b.variables)
        if names_a != names_b:
            problems.append(
                f"image.cdf: variable sets differ (fresh ^ tracked = "
                f"{sorted(names_a ^ names_b)})")
        for name in sorted(names_a & names_b):
            va = np.asarray(a.variables[name][:])
            vb = np.asarray(b.variables[name][:])
            if not np.array_equal(va, vb):
                problems.append(f"image.cdf: variable {name!r} differs from the tracked file")

    for kind, key in (("proc", "proc"), ("sd", "sd")):
        tracked = ref_dir / f"{PREFIX}{kind}.nc"
        report = compare.compare_files(str(paths[key]), str(tracked))
        if not report.accepted() or report.unclassified:
            problems.append(
                f"{kind}.nc: comparison against {tracked} not accepted -- "
                f"{compare.describe_differences(report)}")

    for kind, key in (("image", "image_call"), ("proc", "proc_call"), ("sd", "sd_call")):
        tracked = ref_dir / f"{PREFIX}{kind}.call"
        fresh_text = Path(paths[key]).read_text()
        tracked_text = tracked.read_text()
        if fresh_text != tracked_text:
            problems.append(
                f"{kind}.call: sidecar text differs -- fresh={fresh_text!r} "
                f"tracked={tracked_text!r} ({tracked})")

    tracked_digest_path = ref_dir / f"{PREFIX}digest.json"
    tracked_digest = json.loads(tracked_digest_path.read_text())
    fresh_digest = digest(paths)
    if fresh_digest != tracked_digest:
        mismatched = sorted(
            set(fresh_digest.get("combined", {})) ^ set(tracked_digest.get("combined", {})))
        changed = sorted(
            name for name in set(fresh_digest.get("combined", {}))
            & set(tracked_digest.get("combined", {}))
            if fresh_digest["combined"][name] != tracked_digest["combined"][name])
        headline_keys = ("n_particles", "n_accepted", "used_bin_count_sum", "n_seconds")
        fresh_headline = {k: fresh_digest[k] for k in headline_keys}
        tracked_headline = {k: tracked_digest[k] for k in headline_keys}
        problems.append(
            f"combined: digest differs from {tracked_digest_path} -- "
            f"variables only on one side: {mismatched}; changed variables: {changed}; "
            f"headline counts fresh={fresh_headline} tracked={tracked_headline}")

    return problems


def check(tmp_dir: Path | None = None) -> list[str]:
    """Regenerate into a temp dir (or ``tmp_dir``, for a caller that wants to inspect it) and
    compare against the tracked reference. Returns a list of problems, ``[]`` when clean.
    """
    owned = None
    if tmp_dir is None:
        owned = tempfile.TemporaryDirectory()
        tmp_dir = Path(owned.name)
    try:
        paths = build(Path(tmp_dir), N_SECONDS)
        return _compare(paths, REF_DIR)
    finally:
        if owned is not None:
            owned.cleanup()


# ---------------------------------------------------------------------------
# The v3.5 reference (since 2026-09-13)
# ---------------------------------------------------------------------------

def _variable_digest(path: Path) -> dict[str, dict]:
    """Every variable's sha256 over ``np.asarray(v[:]).tobytes()``, shape and dtype -- the same
    fingerprint ``digest()`` takes of the v3.1.4 combined product."""
    out: dict[str, dict] = {}
    with netCDF4.Dataset(str(path)) as ds:
        for name in sorted(ds.variables):
            arr = np.asarray(ds.variables[name][:])
            out[name] = {"sha256": hashlib.sha256(np.ascontiguousarray(arr).tobytes()).hexdigest(),
                         "shape": list(arr.shape), "dtype": str(arr.dtype)}
    return out


def digest_v35(paths: dict) -> dict:
    """A JSON-able fingerprint of the v3.5 build, structurally :func:`digest`'s v3.5 counterpart:
    the image and combined products (both too large to track -- see the module docstring) are
    digested per variable; the headline counts are read from the tracked proc/sd files themselves.

    ``count``'s dims come back ``('Time', 'CIPcorrlen')`` from ``netCDF4`` -- i.e. shape
    ``(n_sec, num_bins)`` -- measured 2026-09-13 against a fresh v3.5 build, the same orientation
    the v3.1.4 ``digest()`` above assumes, so ``count[:, 5:]`` slices the bin axis in both.
    """
    with netCDF4.Dataset(str(paths["proc"])) as ds:
        n_particles = len(ds.dimensions["time"])
        n_accepted = int(np.count_nonzero(np.isin(np.asarray(ds.variables["image_auto_reject"][:]),
                                                  _ACCEPTED_CODES)))
    with netCDF4.Dataset(str(paths["sd"])) as ds:
        n_seconds = len(ds.dimensions["Time"])
        # Used bins are 6..128 (1-based, sizeDist's own convention) -> zero-based 5:128, same
        # slice as v3.1.4's digest() -- count's axis order is ('Time', 'CIPcorrlen') here too.
        used_bin_count_sum = float(np.nansum(np.asarray(ds.variables["count"][:])[:, 5:]))
    return {
        "engine": "3.5",
        "raw_sha256": hashlib.sha256(Path(paths["raw"]).read_bytes()).hexdigest(),
        "image": _variable_digest(paths["image"]),
        "combined": _variable_digest(paths["combined"]),
        "call_sidecars": {k: Path(paths[f"{k}_call"]).read_text(encoding="utf-8")
                          for k in ("image", "proc", "sd", "combined")},
        "n_particles": n_particles, "n_accepted": n_accepted,
        "used_bin_count_sum": used_bin_count_sum, "n_seconds": n_seconds,
    }


def write_reference_v35() -> None:
    """Build to a temp dir and copy the nine tracked v3.5 files (plus ``digest.json``) into
    ``REF_DIR``."""
    REF_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        paths = build_v35(Path(tmp))
        shutil.copyfile(paths["toml"], REF_DIR / f"{PREFIX_V35}run.toml")
        shutil.copyfile(paths["aircraft"], REF_DIR / f"{PREFIX_V35}aircraft.cdf")
        shutil.copyfile(paths["proc"], REF_DIR / f"{PREFIX_V35}proc.nc")
        shutil.copyfile(paths["sd"], REF_DIR / f"{PREFIX_V35}sd.nc")
        shutil.copyfile(paths["image_call"], REF_DIR / f"{PREFIX_V35}image.call")
        shutil.copyfile(paths["proc_call"], REF_DIR / f"{PREFIX_V35}proc.call")
        shutil.copyfile(paths["sd_call"], REF_DIR / f"{PREFIX_V35}sd.call")
        shutil.copyfile(paths["combined_call"], REF_DIR / f"{PREFIX_V35}combined.call")
        # path prefixes -> <repo>, <tmp>, ~
        scrub_output(*(REF_DIR / f"{PREFIX_V35}{n}" for n in ("proc.nc", "sd.nc")))
        d = digest_v35(paths)
        (REF_DIR / f"{PREFIX_V35}digest.json").write_text(
            json.dumps(d, indent=1, sort_keys=True) + "\n")


def _compare_v35(paths: dict, ref_dir: Path) -> list[str]:
    """The comparison ``check_v35()`` runs, factored out so a test can point ``ref_dir`` at a
    deliberately mutated copy of the tracked v3.5 reference and confirm the guard actually fires
    (``tests/test_demo_reference.py::TheV35ComparisonIsNotVacuous``).

    The two sides always come from different places: ``paths`` is a just-built fresh run;
    ``ref_dir`` is where the tracked (or, in a test, mutated) reference lives.
    """
    from arrayprobe import compare

    problems: list[str] = []

    tracked_digest_path = ref_dir / f"{PREFIX_V35}digest.json"
    tracked_digest = json.loads(tracked_digest_path.read_text())

    fresh_raw_sha = hashlib.sha256(Path(paths["raw"]).read_bytes()).hexdigest()
    if fresh_raw_sha != tracked_digest["raw_sha256"]:
        problems.append(
            f"raw.2DS: sha256 {fresh_raw_sha} vs tracked {tracked_digest['raw_sha256']} "
            f"in {tracked_digest_path} -- the raw file is no longer byte-identical to the "
            "tracked one")

    tracked_toml = ref_dir / f"{PREFIX_V35}run.toml"
    tracked_toml_text = tracked_toml.read_text(encoding="utf-8")
    fresh_toml_text = Path(paths["toml"]).read_text(encoding="utf-8")
    if tracked_toml_text != fresh_toml_text:
        problems.append(
            f"run.toml: tracked {tracked_toml} differs from the tool's own RUN_TOML_V35 -- "
            "the tracked file no longer says what the tool ran")

    tracked_aircraft = ref_dir / f"{PREFIX_V35}aircraft.cdf"
    fresh_aircraft_bytes = Path(paths["aircraft"]).read_bytes()
    tracked_aircraft_bytes = tracked_aircraft.read_bytes()
    if fresh_aircraft_bytes != tracked_aircraft_bytes:
        problems.append(
            f"aircraft.cdf: {len(fresh_aircraft_bytes)} fresh bytes vs "
            f"{len(tracked_aircraft_bytes)} tracked bytes in {tracked_aircraft} -- the seeded "
            "aircraft file is no longer byte-identical to the tracked one")

    fresh_image_digest = _variable_digest(paths["image"])
    tracked_image_digest = tracked_digest["image"]
    if fresh_image_digest != tracked_image_digest:
        only_one_side = sorted(set(fresh_image_digest) ^ set(tracked_image_digest))
        changed = sorted(
            name for name in set(fresh_image_digest) & set(tracked_image_digest)
            if fresh_image_digest[name] != tracked_image_digest[name])
        problems.append(
            f"image.nc: digest differs -- variables only on one side: {only_one_side}; "
            f"changed variables: {changed}")

    tracked_proc = ref_dir / f"{PREFIX_V35}proc.nc"
    report = compare.compare_files(str(paths["proc"]), str(tracked_proc),
                                   classes=compare.PROC_CLASSES_V35)
    if not report.accepted() or report.unclassified:
        problems.append(
            f"proc.nc: comparison against {tracked_proc} not accepted -- "
            f"{compare.describe_differences(report)}")

    tracked_sd = ref_dir / f"{PREFIX_V35}sd.nc"
    report = compare.compare_files(str(paths["sd"]), str(tracked_sd))
    if not report.accepted() or report.unclassified:
        problems.append(
            f"sd.nc: comparison against {tracked_sd} not accepted -- "
            f"{compare.describe_differences(report)}")

    for kind, key in (("image", "image_call"), ("proc", "proc_call"),
                     ("sd", "sd_call"), ("combined", "combined_call")):
        tracked = ref_dir / f"{PREFIX_V35}{kind}.call"
        fresh_text = Path(paths[key]).read_text(encoding="utf-8")
        tracked_text = tracked.read_text(encoding="utf-8")
        if fresh_text != tracked_text:
            problems.append(
                f"{kind}.call: sidecar text differs -- fresh={fresh_text!r} "
                f"tracked={tracked_text!r} ({tracked})")

    fresh_digest = digest_v35(paths)
    if fresh_digest != tracked_digest:
        mismatched = sorted(
            set(fresh_digest.get("combined", {})) ^ set(tracked_digest.get("combined", {})))
        changed = sorted(
            name for name in set(fresh_digest.get("combined", {}))
            & set(tracked_digest.get("combined", {}))
            if fresh_digest["combined"][name] != tracked_digest["combined"][name])
        headline_keys = ("n_particles", "n_accepted", "used_bin_count_sum", "n_seconds")
        fresh_headline = {k: fresh_digest[k] for k in headline_keys}
        tracked_headline = {k: tracked_digest[k] for k in headline_keys}
        problems.append(
            f"combined: digest differs from {tracked_digest_path} -- "
            f"variables only on one side: {mismatched}; changed variables: {changed}; "
            f"headline counts fresh={fresh_headline} tracked={tracked_headline}")

    return problems


def check_v35(tmp_dir: Path | None = None) -> list[str]:
    """Regenerate the v3.5 reference into a temp dir (or ``tmp_dir``) and compare against the
    tracked reference. Returns a list of problems, ``[]`` when clean."""
    owned = None
    if tmp_dir is None:
        owned = tempfile.TemporaryDirectory()
        tmp_dir = Path(owned.name)
    try:
        paths = build_v35(Path(tmp_dir))
        return _compare_v35(paths, REF_DIR)
    finally:
        if owned is not None:
            owned.cleanup()


# ---------------------------------------------------------------------------
# Real ORACLES example subsets
# ---------------------------------------------------------------------------

SUBSET_DIR = REF_DIR / "oracles_subsets"


def build_oracles_subset(year: int, out_dir: Path) -> dict[str, Path]:
    """Run S2 -> S3 -> S4 (production call) -> S4c on the gated raw subset for ``year``,
    with the driver's module defaults -- the same call ``build()`` above runs, confirmed against
    the `.call` stamps that validated both chosen flights. Raises ``FileNotFoundError``
    naming the manifest when the gated subset is not on disk.

    Returns the same shape as :func:`build`, plus ``manifest`` (the parsed
    ``oracles_<year>_manifest.json``).
    """
    manifest_path = SUBSET_DIR / f"oracles_{year}_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"gated real-data subset manifest not found: {manifest_path} "
            "(the subset is not on disk on this machine)")
    manifest = json.loads(manifest_path.read_text())

    raw_name = manifest["raw_subset_name"]
    raw_src = SUBSET_DIR / raw_name
    if not raw_src.is_file():
        raise FileNotFoundError(
            f"gated real-data subset raw file not found: {raw_src}")

    run_flight = _load_tool_module("run_flight")
    run_flight.log = lambda *a, **kw: None

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = out_dir / raw_name
    shutil.copyfile(raw_src, raw)

    image = run_flight.stage2(raw, out_dir)
    proc = run_flight.stage3(image, out_dir)
    sd = run_flight.stage4(proc, raw.stem, out_dir)

    from arrayprobe import combine_sizedist

    # The subset raw file is named "oracles_<year>_<source-stem>_<t0>-<t1>.2DS", not
    # "base<YYMMDDHHMMSS>" -- derive flight_date/summary_time from the manifest's own
    # SOURCE raw basename (which IS in that shape), not from the cut file's stem.
    source_stem = Path(manifest["source_raw_basename"]).stem
    flight_date = f"20{source_stem[4:10]}"
    summary_time = "_".join(source_stem[i:i + 2] for i in range(4, 16, 2))
    stem = raw.stem
    combined = out_dir / f"{stem}.combined.H.2DS_2.cdf"
    combine_sizedist([str(sd)], str(combined), flight_date=flight_date,
                     summary_time=summary_time)

    return {
        "raw": raw, "image": image, "proc": proc, "sd": sd, "combined": combined,
        "image_call": run_flight.call_path(image),
        "proc_call": run_flight.call_path(proc),
        "sd_call": run_flight.call_path(sd),
        "manifest": manifest,
    }


def check_oracles_subset(year: int, tmp_dir: Path | None = None) -> dict:
    """Build :func:`build_oracles_subset` into a temp dir and compare the resulting combined
    product against the gated cut product, restricted to the interior seconds
    ``[t0, t1]`` (the manifest's window; margin seconds are excluded).

    Returns a dict with the ``ProductComparisonReport`` and the interior-second
    ``non_zero_pct`` for ``Counts`` and ``Size Distribution cm-3``.
    """
    from arrayprobe import validation_report

    owned = None
    if tmp_dir is None:
        owned = tempfile.TemporaryDirectory()
        tmp_dir = Path(owned.name)
    try:
        paths = build_oracles_subset(year, Path(tmp_dir))
        manifest = paths["manifest"]
        product_cut = SUBSET_DIR / manifest["product_subset_name"]
        report = validation_report.compare_to_product(str(paths["combined"]), str(product_cut))

        t0 = int(manifest["t0_hhmmss"][:2]) * 3600 + int(manifest["t0_hhmmss"][2:4]) * 60 \
            + int(manifest["t0_hhmmss"][4:6])
        t1 = int(manifest["t1_hhmmss"][:2]) * 3600 + int(manifest["t1_hhmmss"][2:4]) * 60 \
            + int(manifest["t1_hhmmss"][4:6])
        interior_residual = tuple(s for s in report.residual_seconds if t0 <= s <= t1)

        return {
            "year": year,
            "report": report,
            "counts_non_zero_pct": report.cell("Counts", "used bins 6-128").non_zero_pct,
            "sd_non_zero_pct":
                report.cell("Size Distribution cm-3", "used bins 6-128").non_zero_pct,
            "interior_seconds": (t0, t1),
            "interior_residual_seconds": interior_residual,
        }
    finally:
        if owned is not None:
            owned.cleanup()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Write, or check a fresh run against, the tracked demo-flight reference(s).")
    parser.add_argument("--write", action="store_true",
                        help="(re)write the tracked reference under tests/data/")
    parser.add_argument("--engine", choices=("3.5", "3.1.4", "all"), default="all",
                        help="which reference to check (default: both, v3.5 first); "
                             "--write needs one named")
    args = parser.parse_args(argv)

    if args.write:
        if args.engine == "all":
            parser.error("--write needs --engine 3.5 or --engine 3.1.4: a rewrite names the "
                         "reference it rewrites")
        (write_reference_v35 if args.engine == "3.5" else write_reference)()
        print(f"wrote the v{args.engine} reference under {REF_DIR}")
        return 0

    problems = []
    if args.engine in ("3.5", "all"):
        problems += [f"[3.5] {p}" for p in check_v35()]
    if args.engine in ("3.1.4", "all"):
        problems += [f"[3.1.4] {p}" for p in check()]
    if problems:
        for p in problems:
            print(p)
        return 1
    checked = []
    if args.engine in ("3.5", "all"):
        checked.append(f"v3.5 {len(TRACKED_NAMES_V35)} files")
    if args.engine in ("3.1.4", "all"):
        checked.append(f"v3.1.4 {len(TRACKED_NAMES)} files")
    print(f"ok: {' and '.join(checked)}, digests match")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
