# SPDX-License-Identifier: BSD-3-Clause
"""Known-truth harness: synthetic 2D-S flights through every chain, against the truth.

Tooling. Changes no port output. Builds the flights with
:mod:`arrayprobe.tools.synthetic_truth`, runs each chain on the raw bytes exactly as a user
would, and compares each chain's recovered size distribution with the population that was
drawn -- per bin, with 95 % counting intervals (Garwood, on the recovered count).

Chains (every one runs from the raw ``.2DS`` file):

``v314_stock``
    v3.1.4 port, ``STOCK_V314`` profile throughout (S2, ``imgProc_sm`` with the aircraft TAS
    file it requires, reject thresholds 6/5 and ``rej_hollow = 1``), ``sizeDist`` stock tree
    (``area_ratio < .2``; the 2D-S shattering gate is off in stock, ``applyIntArrThresh = 0``).
``v314_oracles``
    v3.1.4 port as the ORACLES 2016 products were made: ``ORACLES_PRODUCTION`` profile
    (``rej_hollow = 0``, 4/4), ``sizeDist`` production tree (the ``'z'`` edit ``area_ratio <
    .5``) called WITH the twelfth argument (``2DS_intArrThreshold_MISSING.cdf`` -- the 6 us
    shattering gate), which is the product-of-record call.
``v35_stock``
    v3.5 port, ``STOCK_V35`` reject thresholds, v3.5's own defaults (``run_flight.V35_CALL``),
    ``iaThreshType = 0`` (no threshold file).
``soda2_und``
    SODA-2 port with the settings UND's 2016 SODA-2 run most likely used
    (inferred 2026-09-14, medium confidence):
    ``smethod='fastcircle'``, ``inttime_reject=1``, ``water=0``, ``eawmethod='centerin'``,
    the 2D-S probe spec (``dofconst 8.12``, 785 nm, 6.3 cm arms); TAS fixed at the flight's.
``soda2_water``
    The same with ``water=1`` (SODA-2's Korolev Poisson-spot size correction for droplets).

Every chain is binned on the same ``kk`` ladder (``sizeDist``'s 2D-S ladder, 5-1285 um in
10 um bins), so bin j means the same diameter interval for the truth and every chain.

Recovered concentration per bin is the chain's own mean over the flight's seconds
(UIOOPS: ``sum(count) / sum(sample_vol)`` over the seconds' rows -- ``sample_vol`` is constant
in time here; SODA-2: ``mean_t(conc1d) * dD``). True concentration is the drawn droplet count
in the bin over :meth:`TruthManifest.sampled_volume_m3` (fragments excluded).

Usage, from the repository root (bulk output under the gitignored ``../_bench_tt/``)::

    .venv/Scripts/python.exe scripts/truth_harness.py --out ../_bench_tt/run1 [--flights anchor
    truth]
        [--chains v314_stock v314_oracles v35_stock soda2_und soda2_water]
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path

import netCDF4
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from arrayprobe.constants import sizedist_config  # noqa: E402
from arrayprobe.tools.synthetic_truth import (  # noqa: E402
    PSD,
    FlightSpec,
    TruthManifest,
    build_truth_flight,
    write_aircraft_tas,
)
from arrayprobe_uiops.sizedist_core import bin_index  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scrub_paths import scrub_output  # noqa: E402

HERE = Path(__file__).resolve().parent
CHAINS = ("v314_stock", "v314_oracles", "v35_stock", "soda2_und", "soda2_water")
KK_MM = np.asarray(sizedist_config("ORACLES", "2DS", "production").kk, float)
NB = len(KK_MM) - 1
#: Reporting bands (um), each a union of kk bins.
BANDS_UM = (15, 55, 105, 205, 305, 505, 805)
RAW_STEM = "base160101060640"
V35_SOFTWARE = "UIOOPS_v3.5"   # run_flight.V35_CALL.software, the vendored version.txt


def _load_tool(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    assert spec is not None and spec.loader is not None  # a sibling .py file of this tool
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# The flights
# ---------------------------------------------------------------------------

#: The sanity anchor: perfect in-focus disks, centred well inside the array, no bursts, one
#: diameter per population bin centre from 25 to 395 um (every 30 um: 13 diameters).
ANCHOR = FlightSpec(
    n_seconds=15, rate_per_s=120.0, seed=20260915, depth="in_focus", across="mid",
    psd=PSD(kind="discrete", diameters_um=tuple(float(d) for d in range(30, 400, 30))),
)

#: The truth flight: a lognormal droplet population over the whole beam (Z uniform between the
#: arms, centres uniform over the array +- 600 um, so edge clipping and centre-in both act),
#: with shattering bursts.
TRUTH = FlightSpec(
    n_seconds=20, rate_per_s=400.0, seed=20260916, depth="uniform", across="margin",
    margin_um=600.0, psd=PSD(kind="lognormal", median_um=80.0, gsd=1.8, d_min_um=15.0,
                             d_max_um=600.0),
    burst_rate_per_s=2.0,
)

#: A three-second cut of TRUTH, for exercising every chain in seconds (not reported).
SMOKE = dataclasses.replace(TRUTH, n_seconds=3, rate_per_s=150.0)

FLIGHTS = {"anchor": ANCHOR, "truth": TRUTH, "smoke": SMOKE}


def build(flight_dir: Path, spec: FlightSpec) -> tuple[Path, TruthManifest]:
    flight_dir.mkdir(parents=True, exist_ok=True)
    raw = flight_dir / f"{RAW_STEM}.2DS"
    if raw.exists() and Path(str(raw) + ".truth.json").exists():
        m = TruthManifest.from_json(str(raw) + ".truth.json")
        if m.spec == spec:
            return raw, m
    return raw, build_truth_flight(raw, spec)


# ---------------------------------------------------------------------------
# The chains
# ---------------------------------------------------------------------------

def _tas_rows(tas_csv: Path):
    from arrayprobe.readers.tasinfo import load_tas_info
    th, tas = load_tas_info(tas_csv)
    return th, tas


def run_v314(raw: Path, out: Path, spec: FlightSpec, production: bool) -> dict:
    from arrayprobe import imgproc, sizedist
    from arrayprobe.profiles import ORACLES_PRODUCTION, STOCK_V314
    from arrayprobe.readers import spec as spec_reader

    profile = ORACLES_PRODUCTION if production else STOCK_V314
    out.mkdir(parents=True, exist_ok=True)
    proc, sd = out / "proc.nc", out / "sd.nc"
    if not sd.exists():
        spec_reader.read_binary_SPEC(raw, out / raw.stem, profile=profile, channels="H")
        img = out / f"{raw.stem}.H.cdf"
        with netCDF4.Dataset(str(img)) as d:
            n = len(d.dimensions["time"])
        tas_file = None
        if profile.time_in_seconds_from_tas:
            tas_file = str(write_aircraft_tas(out / "aircraft.nc", spec))
        imgproc.imgproc_sm(str(img), str(proc), "2DS", 1, n, "DEMO", profile=profile,
                           tas_file=tas_file, jit=True)
        th, tas = _tas_rows(out / f"{raw.stem}.tas.csv")
        varargin = ("2DS_intArrThreshold_MISSING.cdf",) if production else ()
        sizedist.run(str(proc), str(sd), tas, np.floor(th), "2DS", 6, 0,
                     np.full_like(tas, 9e5), np.full_like(tas, 15.0), "DEMO",
                     "20160906 060640", *varargin,
                     tree="production" if production else "stock",
                     creation_time="synthetic")
    return {"proc": proc, "sd": sd, "tas_csv": out / f"{raw.stem}.tas.csv"}


#: The bin-ladder finding (synthetic-truth review, 2026-09-26): ``run_v35``'s project
#: used to be hard-coded ``DEMO``, whose 2DS
#: case lands ``sizeDist.m`` on
#: the HVPS ladder (200 um-30 mm, 28 bins) instead of the 10 um ``kk`` ladder every
#: other chain reports on. ``SOCRATES`` 2DS gives v3.5 a 256-bin, 10 um ladder whose first 128
#: edges are exactly ``KK_MM`` (see ``TestBinEdgesAgree`` in ``tests/test_truth_harness.py``), so
#: every chain is now binned the same way; ``recovered_uiops`` truncates v3.5's longer array.
V35_PROJECT = "SOCRATES"


def run_v35(raw: Path, out: Path, spec: FlightSpec, project: str = V35_PROJECT) -> dict:
    import uiops
    from arrayprobe.profiles import STOCK_V35

    v35 = uiops.engine("3.5")
    out.mkdir(parents=True, exist_ok=True)
    proc, sd = out / "proc.nc", out / "sd.nc"
    if not sd.exists():
        v35.module("readers.spec").read_binary_spec_v35(
            raw, out / raw.stem, software=V35_SOFTWARE, creation_time="synthetic",
            channels="H")
        img = next(out.glob(f"{raw.stem}.H.nc"))
        with netCDF4.Dataset(str(img)) as d:
            n = len(d.dimensions["time"])
        hh, mm, ss = spec.start
        tod = hh * 3600 + mm * 60 + ss + np.arange(spec.n_seconds)
        tas_time = ((tod // 3600) * 10000 + ((tod // 60) % 60) * 100 + tod % 60).astype(float)
        tas_series = np.full(len(tod), spec.tas_mps)
        v35.module("imgproc").imgproc_sm_v35(
            str(img), str(proc), "2DS", 1, n, project, iRectEllipse=0, iCalcAllDiodeStats=0,
            iQC=0, iNewHabit=0, reject_config=STOCK_V35.reject_thresholds,
            tas_time=tas_time, tas=tas_series, tas_ratio=None, software=V35_SOFTWARE)
        th, tas = _tas_rows(out / f"{raw.stem}.tas.csv")
        v35.module("sizedist").run(
            str(proc), str(sd), tas, np.floor(th), "2DS", 6, 0, np.full_like(tas, 9e5),
            np.full_like(tas, 15.0), 0, 0, 0, 0, project, "20160906 060640",
            software=V35_SOFTWARE, creation_time="synthetic")
    return {"proc": proc, "sd": sd, "tas_csv": out / f"{raw.stem}.tas.csv"}


def soda2_op(raw: Path, spec: FlightSpec, water: int) -> dict:
    hh, mm, ss = spec.start
    t0 = float(hh * 3600 + mm * 60 + ss)
    return dict(
        fn=str(raw), date="20160906", starttime=t0, stoptime=t0 + spec.n_seconds,
        format="SPEC", subformat=0, probetype="2DS", res=10.0,
        endbins=[float(x) for x in np.round(KK_MM * 1000.0, 6)], arendbins=[0.0, 0.5, 1.0],
        rate=1.0, smethod="fastcircle", pth="", particlefile=0, inttime_reject=1,
        stuckbits=0, water=water, fixedtas=float(spec.tas_mps), timeoffset=0.0,
        armwidth=6.3, numdiodes=128, greythresh=0, probeid="H", eawmethod="centerin",
        wavelength=0.785e-6, dofconst=8.12, ncdfparticlefile=0, asciipsdfile=0, savfile=0,
    )


def run_soda2(raw: Path, out: Path, spec: FlightSpec, water: int) -> dict:
    from arrayprobe_soda2.process_2d import soda2_process_2d

    out.mkdir(parents=True, exist_ok=True)
    npz = out / "soda2.npz"
    if not npz.exists():
        d = soda2_process_2d(soda2_op(raw, spec, water))
        if d is None:
            raise RuntimeError("soda2_process_2d returned no output for the flight window")
        keep = {k: np.asarray(getattr(d, k)) for k in
                ("time", "conc1d", "spec1d", "spec2d", "sa", "activetime", "midbins",
                 "count_accepted", "count_rejected", "corr_fac", "intcutoff")}
        np.savez_compressed(npz, **keep)
        scrub_output(npz)  # path prefixes -> <repo>, <tmp>, ~
    return {"npz": npz}


# ---------------------------------------------------------------------------
# F10 (ITEM10): a DMT (CIP/PIP, probetype 1) chain.
#
# ``arrayprobe.tools.synthetic_truth`` renders SPEC/2D-S raw bytes only (a binary-annulus
# Korolev optical model over a 2D-S geometry, `build_truth_flight`'s docstring) -- it has no
# DMT/PADS record format and cannot emit DMT-format raw, so the F10 rehearsal below runs
# instead on the tracked real fixture `tests/data/s6_dmt_raw_fixture`: the first 12 records of
# UIOOPS's own `ImagefileExamplePECAN` (`octave_oracle/run_s6_dmt_bank.py`), a real PECAN
# PIP file byte-for-byte, already used as an Octave oracle input and the SODA-2 DMT
# driver's fixture (`tests/test_soda2_dmt_driver.py`). No engine code changes; this is tooling.
# ---------------------------------------------------------------------------

#: 12 records, subformat 1 (PADS layout) -- see `tests/test_soda2_dmt_driver.py`'s docstring.
DMT_RAW_FIXTURE = HERE.parent / "tests" / "data" / "s6_dmt_raw_fixture"
#: The window `gdl_oracle/run_soda2_dmt_bank.py` uses for this same fixture (UT seconds of day).
DMT_START, DMT_STOP = 22410.0, 22440.0
DMT_FIXED_TAS = 100.0


def run_v35_dmt(out: Path, raw: Path = DMT_RAW_FIXTURE, probe: str = "PIP",
                project: str = "TEST") -> dict:
    """v3.5 imgProc_sm/sizeDist on a DMT (CIP/PIP) raw file. No aircraft TAS series exists for
    a DMT decode (probetype 1's imgProc_sm branches never read tasTime/tas, `imgproc.py`), so
    this passes ``tas_time=None, tas=None`` to imgProc_sm and a constant :data:`DMT_FIXED_TAS`
    to sizeDist -- adequate for an end-to-end rehearsal, not a TAS-dependent comparison."""
    from arrayprobe.profiles import STOCK_V35
    from arrayprobe.readers import dmt
    from arrayprobe_uiops import sizedist as v35s
    from arrayprobe_uiops.imgproc import imgproc_sm_v35

    out.mkdir(parents=True, exist_ok=True)
    decoded, proc, sd = out / "dmt.cdf", out / "proc.nc", out / "sd.nc"
    if not sd.exists():
        n = dmt.read_binary_DMT(str(raw), str(decoded))
        imgproc_sm_v35(str(decoded), str(proc), probe, 1, n, project, iRectEllipse=0,
                       iCalcAllDiodeStats=0, iQC=0, iNewHabit=0,
                       reject_config=STOCK_V35.reject_thresholds,
                       tas_time=None, tas=None, tas_ratio=None, software=V35_SOFTWARE)
        tas = np.full(n, DMT_FIXED_TAS)
        times = np.arange(n, dtype=float)
        v35s.run(str(proc), str(sd), tas, times, probe, 6, 0, np.full(n, 9e5),
                np.full(n, 15.0), 0, 0, 1, 1, project, "20150620 000000",
                software=V35_SOFTWARE, creation_time="synthetic")
    with netCDF4.Dataset(str(decoded)) as d:
        n_records = len(d.dimensions["time"])
    return {"decoded": decoded, "proc": proc, "sd": sd, "n_records": n_records}


def soda2_dmt_op(raw: Path = DMT_RAW_FIXTURE, probe: str = "PIP", water: int = 0) -> dict:
    """The op literal `gdl_oracle/run_soda2_dmt_bank.py` and `tests/test_soda2_dmt_driver.py`
    use for this same fixture (subformat 1, PADS layout), field for field."""
    return dict(
        fn=str(raw), date="06202015", starttime=DMT_START, stoptime=DMT_STOP,
        format="DMT", subformat=1, probetype=probe, res=25.0, yres=25.0,
        armwidth=6.0, numdiodes=64, probeid="", shortname=probe, greythresh=0,
        wavelength=0.658e-6, dofconst=3.0, seatag=np.array([33000], dtype=np.int32),
        endbins=[25, 50, 75, 100, 125, 150, 200, 250, 300, 350, 400, 475, 550, 625,
                700, 800, 900, 1000, 1200, 1400, 1600],
        arendbins=np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0], dtype=np.float32),
        rate=1, smethod="fastcircle", pth="", particlefile=0, inttime_reject=0,
        stuckbits=0, water=water, fixedtas=np.float32(DMT_FIXED_TAS), project="",
        timeoffset=np.float32(0.0), eawmethod="centerin", savfile=0,
    )


def run_soda2_dmt(out: Path, raw: Path = DMT_RAW_FIXTURE, water: int = 0) -> dict:
    """SODA-2's own DMT/PADS route (`arrayprobe_soda2.process_2d`, format ``DMT``) on the same
    fixture as :func:`run_v35_dmt`, so the two engines' DMT chains run on identical raw bytes."""
    from arrayprobe_soda2.process_2d import soda2_process_2d

    out.mkdir(parents=True, exist_ok=True)
    npz = out / "soda2.npz"
    if not npz.exists():
        d = soda2_process_2d(soda2_dmt_op(raw, water=water))
        if d is None:
            raise RuntimeError("soda2_process_2d returned no output for the DMT fixture")
        keep = {k: np.asarray(getattr(d, k)) for k in
                ("time", "conc1d", "spec1d", "spec2d", "sa", "activetime", "midbins",
                 "count_accepted", "count_rejected", "corr_fac", "intcutoff")}
        np.savez_compressed(npz, **keep)
        scrub_output(npz)  # path prefixes -> <repo>, <tmp>, ~
    return {"npz": npz}


# ---------------------------------------------------------------------------
# Recovered and true distributions
# ---------------------------------------------------------------------------

def flight_seconds(spec: FlightSpec) -> np.ndarray:
    hh, mm, ss = spec.start
    return hh * 3600 + mm * 60 + ss + np.arange(spec.n_seconds)


def recovered_uiops(sd: Path, spec: FlightSpec) -> dict:
    """Counts and mean concentration (cm^-3 per bin) over the flight's seconds, each second's
    first row only (a TAS row repeated within a second is a second row for the same second)."""
    with netCDF4.Dataset(str(sd)) as d:
        d.set_auto_mask(False)
        t = np.asarray(d["time"][:], float)
        c = np.nan_to_num(np.asarray(d["count"][:], float))
        # v3.5's sizeDist writes no sample_vol (iSaveIntArrSV = 0); its concentration is
        # read from conc_minR [cm-4] x bin_dD [mm -> cm] instead, the same quantity.
        sv = np.asarray(d["sample_vol"][:], float) if "sample_vol" in d.variables else None
        conc_rows = (np.nan_to_num(np.asarray(d["conc_minR"][:], float))
                     * np.asarray(d["bin_dD"][:], float)[None, :] / 10.0)
        if c.shape[-1] > NB:
            # The bin-ladder fix: the chain's own ladder (v3.5/SOCRATES, 256 bins) is a superset of
            # KK_MM's 128 -- its first NB edges are exactly KK_MM (bin_dD is each bin's
            # width in mm, so the first NB widths must equal KK_MM's own diffs).
            bin_dd = np.asarray(d["bin_dD"][:], float)
            np.testing.assert_allclose(bin_dd[:NB], np.diff(KK_MM), atol=1e-9)
            c = c[..., :NB]
            conc_rows = conc_rows[..., :NB]
            if sv is not None and sv.shape[-1] > NB:
                sv = sv[..., :NB]
    secs = (t // 10000) * 3600 + ((t // 100) % 100) * 60 + t % 100
    want = set(flight_seconds(spec).tolist())
    seen, rows = set(), []
    for i, s in enumerate(secs):
        if s in want and s not in seen:
            seen.add(s)
            rows.append(i)
    counted_rows = c[rows].sum(axis=0)
    total_all_rows = c.sum(axis=0)
    if sv is not None:
        conc = counted_rows / sv[rows].sum(axis=0)      # cm^-3 per bin
    else:
        conc = conc_rows[rows].mean(axis=0)
    return {"counts": counted_rows, "counts_all_rows": total_all_rows, "conc_cm3": conc,
            "sv_cm3_per_s": sv[rows[0]] if (rows and sv is not None) else np.full(NB, np.nan),
            "n_seconds": len(rows)}


def recovered_soda2(npz: Path, spec: FlightSpec) -> dict:
    z = np.load(npz)
    conc1d = np.asarray(z["conc1d"], float)        # m^-4, (time, bin)
    spec1d = np.asarray(z["spec1d"], float)        # counts (corr_fac applied), (time, bin)
    dd_m = np.diff(KK_MM) * 1e-3
    n_t = conc1d.shape[0]
    conc_cm3 = conc1d.mean(axis=0) * dd_m * 1e-6   # m^-4 * m -> m^-3 -> cm^-3
    counts_raw = np.asarray(z["spec2d"], float).sum(axis=(0, 2)) if z["spec2d"].ndim == 3 \
        else spec1d.sum(axis=0)
    return {"counts": counts_raw, "counts_corrected": spec1d.sum(axis=0), "conc_cm3": conc_cm3,
            "n_seconds": n_t, "sa_m2": np.asarray(z["sa"], float),
            "corr_fac": np.asarray(z["corr_fac"], float)}


def true_distribution(m: TruthManifest) -> dict:
    kind = m.array("kind")
    d0 = m.array("d0_um") / 1000.0
    droplet = kind == "droplet"
    idx = bin_index(d0, KK_MM)
    ok = droplet & (idx >= 0)
    drawn = np.bincount(idx[ok], minlength=NB).astype(float)
    out = {"drawn": drawn}
    imaged = m.array("imaged")
    out["imaged"] = np.bincount(idx[ok & imaged], minlength=NB).astype(float)
    if m.spec.depth == "uniform":
        v_cm3 = m.sampled_volume_m3() * 1e6
        out["conc_cm3"] = drawn / v_cm3
        out["volume_cm3"] = v_cm3
    return out


def garwood(n):
    """Two-sided 95 % Poisson interval on a count (Garwood 1936, via the chi-square
    quantiles). ``scipy`` when installed; otherwise the Wilson-Hilferty approximation."""
    n = np.asarray(n, float)
    try:
        from scipy.stats import chi2
        lo = np.where(n > 0, chi2.ppf(0.025, 2 * n) / 2, 0.0)
        hi = chi2.ppf(0.975, 2 * (n + 1)) / 2
    except ImportError:  # pragma: no cover - scipy is in the dev venv
        z = 1.959964
        lo = np.where(n > 0, n * (1 - 1 / (9 * n + 1e-300) - z / (3 * np.sqrt(n + 1e-300))) ** 3, 0)
        n1 = n + 1
        hi = n1 * (1 - 1 / (9 * n1) + z / (3 * np.sqrt(n1))) ** 3
    return lo, hi


def band_edges_bins():
    edges = []
    for a, b in zip(BANDS_UM[:-1], BANDS_UM[1:], strict=True):
        ia = int(np.argmin(np.abs(KK_MM * 1000 - a)))
        ib = int(np.argmin(np.abs(KK_MM * 1000 - b)))
        assert abs(KK_MM[ia] * 1000 - a) < 1e-6 and abs(KK_MM[ib] * 1000 - b) < 1e-6
        edges.append((ia, ib))
    return edges


def bands(x: np.ndarray) -> list[float]:
    return [float(np.asarray(x)[a:b].sum()) for a, b in band_edges_bins()]


# ---------------------------------------------------------------------------
# Attribution: which gate removed which true droplet (v3.1.4 chains)
# ---------------------------------------------------------------------------

def attribute_v314(paths: dict, m: TruthManifest, production: bool) -> dict:
    """Replay ``sizeDist``'s per-particle gates with ``reject_stage_tally``
    and report per size band -- by TRUE diameter -- how many imaged droplets each gate
    removed first, and how many shattering fragments survived.

    The clock-join finding (clock_join): each proc row is joined to its manifest
    particle by
    ``particle_microsec`` == the manifest's ``clock``, nearest-then-exact, never by row order.
    The earlier version assumed ``n_proc == imaged.size`` meant row *i* of the proc file was
    ``imaged[i]``, which broke -- with a shape-mismatch crash, or silent misattribution when the
    counts happened to coincide -- whenever a chain framed fewer particles than were imaged
    (F2, ``read_binary_SPEC.m:96-97``'s 1700-slice canvas truncation). A manifest droplet with
    no matching proc row is now attributed to its own gate, ``never_framed``, keyed by its true
    diameter, instead of being silently dropped or crashing the join.
    """
    rst = _load_tool("reject_stage_tally")
    p = rst.load_proc(paths["proc"])
    with netCDF4.Dataset(str(paths["proc"])) as d:
        d.set_auto_mask(False)
        clock = np.asarray(d["particle_microsec"][:], float).reshape(-1) \
            if "particle_microsec" in d.variables else None
    imaged = np.flatnonzero(m.array("imaged"))
    man_clock = m.array("clock")[imaged].astype(float)
    n_proc = p.sec.size
    joined = n_proc == imaged.size

    if clock is not None and imaged.size and n_proc:
        order = np.argsort(man_clock)
        sorted_clock, sorted_imaged = man_clock[order], imaged[order]
        pos = np.clip(np.searchsorted(sorted_clock, clock), 0, len(sorted_clock) - 1)
        left = np.clip(pos - 1, 0, len(sorted_clock) - 1)
        use_left = np.abs(sorted_clock[left] - clock) < np.abs(sorted_clock[pos] - clock)
        best = np.where(use_left, left, pos)
        exact = sorted_clock[best] == clock
        row_manifest = np.where(exact, sorted_imaged[best], -1)
        clock_match = int(np.sum(exact))
    else:
        # No clock column (an older proc file) or nothing to join: fall back to row order,
        # which is only ever correct when the counts already agree.
        row_manifest = imaged[:n_proc] if joined else np.full(n_proc, -1, dtype=int)
        clock_match = int(joined) if clock is None else 0

    matched = row_manifest >= 0
    safe_row_manifest = np.where(matched, row_manifest, 0)
    never_framed_idx = np.setdiff1d(imaged, row_manifest[matched], assume_unique=False)

    cfg = sizedist_config("DEMO", "2DS", "production" if production else "stock")
    tas = rst.load_tas_csv(paths["tas_csv"])
    flags = rst.replay_flags(
        p, tas=tas, tas_max=cfg.tasMax, res=cfg.res, probetype=cfg.probetype,
        iat_thresh=cfg.default_int_arr_thresh, z_thresh=0.5 if production else 0.2,
        shatter=production)
    kind = np.where(matched, m.array("kind")[safe_row_manifest], "")
    d0 = np.where(matched, m.array("d0_um")[safe_row_manifest] / 1000.0, np.nan)
    tidx = bin_index(d0, KK_MM)
    col = np.where(tidx >= 0, tidx, NB)
    first = np.full(n_proc, "accepted", dtype=object)
    order = (("imgproc", flags.imgproc), ("I", flags.I), ("z", flags.z), ("S", flags.S),
             ("centre_in", flags.off_centre))
    for name, removed in reversed(order):
        first[removed] = name
    codes = np.array([chr(int(c)) if 32 <= c < 127 else str(int(c)) for c in p.code])
    res = {"n_proc": n_proc, "n_imaged": int(imaged.size), "joined_by_order": joined,
           "clock_equal": clock_match, "n_never_framed": int(never_framed_idx.size),
           "by_gate_true_bands": {}, "imgproc_codes": {}, "fragments": {}}
    drop = matched & (kind == "droplet")
    for name in ("accepted", "imgproc", "I", "z", "S", "centre_in"):
        sel = drop & (first == name)
        res["by_gate_true_bands"][name] = bands(np.bincount(col[sel], minlength=NB + 1)[:NB])
    never_kind = m.array("kind")[never_framed_idx]
    never_tidx = bin_index(m.array("d0_um")[never_framed_idx] / 1000.0, KK_MM)
    never_col = np.where(never_tidx >= 0, never_tidx, NB)
    never_drop = never_kind == "droplet"
    res["by_gate_true_bands"]["never_framed"] = bands(
        np.bincount(never_col[never_drop], minlength=NB + 1)[:NB])
    for c in sorted(set(codes[drop & (first == "imgproc")])):
        sel = drop & (first == "imgproc") & (codes == c)
        res["imgproc_codes"][c] = bands(np.bincount(col[sel], minlength=NB + 1)[:NB])
    frag = matched & (kind == "fragment")
    res["fragments"] = {name: int(np.sum(frag & (first == name)))
                        for name in ("accepted", "imgproc", "I", "z", "S", "centre_in")}
    res["fragments"]["never_framed"] = int(np.sum(never_kind == "fragment"))
    # Where true droplets that survive every gate are sized: recovered bin minus true bin.
    acc = drop & (first == "accepted")
    rbin = bin_index(p.diam, KK_MM)
    shift = rbin[acc] - tidx[acc]
    res["size_shift_bins"] = {"median": float(np.median(shift)) if shift.size else math.nan,
                              "p05": float(np.percentile(shift, 5)) if shift.size else math.nan,
                              "p95": float(np.percentile(shift, 95)) if shift.size else math.nan}
    zd = np.where(matched, m.array("zd")[safe_row_manifest], np.nan)
    res["accepted_by_zd"] = {}
    for lo, hi in ((0, 2), (2, 4), (4, 6), (6, 7), (7, 8.2)):
        s = drop & (zd >= lo) & (zd < hi) & (p.centerin == 1)
        res["accepted_by_zd"][f"{lo}-{hi}"] = [int(np.sum(s & (first == "accepted"))),
                                                int(np.sum(s))]
    return res


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def run_chain(name: str, raw: Path, out: Path, spec: FlightSpec) -> dict:
    if name == "v314_stock":
        return run_v314(raw, out, spec, production=False)
    if name == "v314_oracles":
        return run_v314(raw, out, spec, production=True)
    if name == "v35_stock":
        return run_v35(raw, out, spec)
    if name == "soda2_und":
        return run_soda2(raw, out, spec, water=0)
    if name == "soda2_water":
        return run_soda2(raw, out, spec, water=1)
    raise KeyError(name)


def compare(name: str, paths: dict, m: TruthManifest) -> dict:
    truth = true_distribution(m)
    rec = recovered_soda2(paths["npz"], m.spec) if "npz" in paths else \
        recovered_uiops(paths["sd"], m.spec)
    counts = np.asarray(rec["counts"], float)
    lo, hi = garwood(counts)
    row = {"chain": name, "n_seconds": rec["n_seconds"],
           "counts_bins": counts.tolist(), "counts_bands": bands(counts),
           "counts_bands_lo": bands(lo), "counts_bands_hi": bands(hi)}
    if m.spec.depth == "uniform":
        conc = np.asarray(rec["conc_cm3"], float)
        tc = truth["conc_cm3"]
        with np.errstate(divide="ignore", invalid="ignore"):
            row["conc_ratio_bins"] = (conc / tc).tolist()
            # Interval on the ratio from the recovered count's Garwood interval, per band.
            cb, tb = np.array(bands(np.nan_to_num(conc))), np.array(bands(tc))
            nb_ = np.array(bands(counts))
            lob, hib = garwood(nb_)
            ratio = cb / tb
            row["conc_ratio_bands"] = ratio.tolist()
            row["conc_ratio_bands_lo"] = (ratio * lob / nb_).tolist()
            row["conc_ratio_bands_hi"] = (ratio * hib / nb_).tolist()
            row["total_conc_ratio_15_805"] = float(sum(cb) / sum(tb))
    return row


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--flights", nargs="+", default=["anchor", "truth"], choices=list(FLIGHTS))
    ap.add_argument("--chains", nargs="+", default=list(CHAINS), choices=list(CHAINS))
    ap.add_argument("--merge-only", action="store_true",
                    help="only merge the per-chain result.json files already on disk")
    a = ap.parse_args(argv)
    result: dict = {"when": datetime.now().isoformat(timespec="seconds"),
                    "bands_um": list(BANDS_UM), "flights": {}}
    res_path = a.out / "truth_harness.json"
    for fname in a.flights:
        spec = FLIGHTS[fname]
        raw, m = build(a.out / fname, spec)
        truth = true_distribution(m)
        kind = m.array("kind")
        fl = result["flights"].setdefault(fname, {})
        fl.update({
            "spec": dataclasses.asdict(spec), "raw_bytes": raw.stat().st_size,
            "n_particles": len(m), "n_droplets": int(np.sum(kind == "droplet")),
            "n_fragments": int(np.sum(kind == "fragment")),
            "n_imaged": int(np.sum(m.array("imaged"))),
            "n_imaged_droplets": int(np.sum(m.array("imaged") & (kind == "droplet"))),
            "n_clipped": int(np.sum(m.array("clipped"))),
            "n_pushed": int(np.sum(m.array("pushed_us") > 0)),
            "truth_drawn_bands": bands(truth["drawn"]),
            "truth_imaged_bands": bands(truth["imaged"]),
        })
        if "conc_cm3" in truth:
            fl["truth_volume_cm3"] = truth["volume_cm3"]
            fl["truth_conc_bands"] = bands(truth["conc_cm3"])
        chains = fl.setdefault("chains", {})
        for cname in a.chains:
            one = a.out / fname / cname / "result.json"
            if a.merge_only:
                if one.exists():
                    chains[cname] = json.loads(one.read_text(encoding="utf-8"))
                continue
            t0 = time.time()
            print(f"[{datetime.now():%H:%M:%S}] {fname}/{cname} start", flush=True)
            paths = run_chain(cname, raw, a.out / fname / cname, spec)
            row = compare(cname, paths, m)
            if cname.startswith("v314"):
                row["attribution"] = attribute_v314(paths, m, production=cname == "v314_oracles")
            row["seconds_elapsed"] = round(time.time() - t0, 1)
            chains[cname] = row
            # One file per chain, so chains can run as separate processes in parallel and
            # `--merge-only` assembles them.
            one.write_text(json.dumps(row, indent=1, default=float), encoding="utf-8")
            print(f"[{datetime.now():%H:%M:%S}] {fname}/{cname} done "
                  f"{row['seconds_elapsed']} s  counts/band {row['counts_bands']}", flush=True)
    res_path.write_text(json.dumps(result, indent=1, default=float), encoding="utf-8")
    print(f"wrote {res_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
