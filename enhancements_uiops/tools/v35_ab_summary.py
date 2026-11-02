# SPDX-License-Identifier: BSD-3-Clause
"""measure the A/B consequence of each wired driver adapter on the v3.5 dense
reference, and write the results into ``docs/measurements.json`` as new top-level
``v35_<module>`` keys.

Builds the v3.5 dense reference in a fresh tempdir
(``demo_flight_dense_raw.2DS`` through ``pipeline.apply_enhancements``,
``[run].preset = "DEMO_2DS_H"``), then measures each wired adapter's real
effect on the resulting
``.enh.proc.nc``/``.enh.sd.nc`` files -- never by hand.

Usage, from the repository root::

    python enhancements_uiops/tools/v35_ab_summary.py --write
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

import netCDF4
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
PY_PORT = REPO_ROOT  # the package tree sits at the repository root
DENSE_RAW = PY_PORT / "tests" / "data" / "demo_flight_dense_raw.2DS"
STEM = "base160101000000"
MEASUREMENTS = Path(__file__).resolve().parents[1] / "docs" / "measurements.json"

_MDR_SPEC = importlib.util.spec_from_file_location(
    "_v35_ab_summary_make_demo_reference", PY_PORT / "scripts" / "make_demo_reference.py")
assert _MDR_SPEC is not None and _MDR_SPEC.loader is not None  # the file path is fixed and exists
mdr = importlib.util.module_from_spec(_MDR_SPEC)
sys.modules[_MDR_SPEC.name] = mdr
_MDR_SPEC.loader.exec_module(mdr)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from arrayprobe_enhancements import pipeline  # noqa: E402


def _toml(root: Path) -> Path:
    lines = [
        "[fidelity]", 'profile = "stock-v3.5"',
        "[run]", 'engine = "3.5"', 'preset = "DEMO_2DS_H"',
        'out = "_decoded"', 'stages = "234c"', 'tas_file = "aircraft.cdf"',
        "[combine]", "borrowed = true",
    ]
    p = root / "run.toml"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def build_dense_v35(root: Path) -> dict:
    raw = root / f"{STEM}.2DS"
    shutil.copyfile(DENSE_RAW, raw)
    mdr.write_aircraft_v35(root / "aircraft.cdf")
    toml = _toml(root)
    report = pipeline.apply_enhancements(toml, [raw])[0]
    out_dir = root / "_decoded"
    outputs = pipeline.locate_outputs(out_dir, STEM, "3.5")
    return {"report": report, "outputs": outputs, "out_dir": out_dir}


def measure(outputs, out_dir: Path, report: dict) -> dict:
    date = "2026-09-14"
    results: dict[str, dict] = {}

    proc = outputs.proc
    with netCDF4.Dataset(proc) as ds:
        n_particles = int(ds.dimensions["particle"].size) if "particle" in ds.dimensions else len(
            np.asarray(ds.variables["image_auto_reject"][:]))
        part_z = np.asarray(ds.variables["part_z"][:]) if "part_z" in ds.variables else None

    enh_proc = out_dir / f"{STEM}.enh.proc.nc"

    # hole_edge_swap -- count of particles where the two columns differ (C5)
    with netCDF4.Dataset(proc) as ds_src, netCDF4.Dataset(enh_proc) as ds_enh:
        src_edge = np.asarray(ds_src.variables["edge_at_max_hole"][:])
        src_max_hole = np.asarray(ds_src.variables["max_hole_diameter"][:])
        differ = int(np.count_nonzero(~np.isclose(src_edge, src_max_hole, equal_nan=True)))
    results["v35_hole_edge_swap"] = {
        "engine": "3.5", "reference": "demo_flight_dense_raw.2DS", "measured": date,
        "n_particles": n_particles, "n_swapped": differ,
        "description": "count of particles where edge_at_max_hole != max_hole_diameter "
                       "on the port's own proc file (the C5 swap this corrects)",
    }

    # outoffocus -- count changed, median size_factor among the affected
    if "outoffocus" in report["applied"]:
        with netCDF4.Dataset(proc) as ds_src, netCDF4.Dataset(enh_proc) as ds_enh:
            src_diam = np.asarray(ds_src.variables["image_diam_minR"][:])
            enh_diam = np.asarray(ds_enh.variables["image_diam_minR"][:])
        changed_mask = ~np.isclose(src_diam, enh_diam, equal_nan=True)
        n_changed = int(np.count_nonzero(changed_mask))
        ratio = np.divide(enh_diam, src_diam, out=np.ones_like(enh_diam), where=src_diam != 0)
        median_factor = float(np.median(ratio[changed_mask])) if n_changed else None
        part_z_gt0 = int((part_z > 0).sum()) if part_z is not None else None
        results["v35_outoffocus"] = {
            "engine": "3.5", "reference": "demo_flight_dense_raw.2DS", "measured": date,
            "n_particles": n_particles, "n_changed": n_changed,
            "median_size_factor_among_changed": median_factor,
            "n_with_part_z_gt0": part_z_gt0,
        }
    else:
        results["v35_outoffocus"] = {
            "engine": "3.5", "reference": "demo_flight_dense_raw.2DS", "measured": date,
            "vacuous": True, "reason": report["skipped"].get("outoffocus", "not applied"),
        }

    # int_arr_rollback_fix -- 0 rollbacks (vacuous by construction on this flight)
    if "int_arr_rollback_fix" in report["applied"]:
        from arrayprobe_enhancements.int_arr_rollback_fix import rollback_indices
        with netCDF4.Dataset(enh_proc) as ds:
            t = np.asarray(ds.variables["Time_in_seconds"][:], dtype=np.float64).ravel()
        idx = rollback_indices(t)
        results["v35_int_arr_rollback_fix"] = {
            "engine": "3.5", "reference": "demo_flight_dense_raw.2DS", "measured": date,
            "n_particles": n_particles, "rollbacks": int(idx.size),
            "vacuous": bool(idx.size == 0),
            "reason": ("no midnight rollover in this raw's 20-second span; an input that "
                       "would not be vacuous: a raw spanning 24:00 UTC" if idx.size == 0
                       else None),
        }
    else:
        results["v35_int_arr_rollback_fix"] = {
            "engine": "3.5", "reference": "demo_flight_dense_raw.2DS", "measured": date,
            "vacuous": True,
            "reason": report["skipped"].get("int_arr_rollback_fix", "not applied"),
        }

    # particle_number_all_fix -- no-op by construction on probetype 2 (2D-S)
    from arrayprobe_enhancements.particle_number_all_fix import audit_proc_file
    audit = audit_proc_file(proc)
    results["v35_particle_number_all_fix"] = {
        "engine": "3.5", "reference": "demo_flight_dense_raw.2DS", "measured": date,
        "vacuous": True,
        "reason": f"probetype 2 (2D-S) writes Particle_number_all correctly "
                  f"({audit['n_real']} of {audit['n']} real values) -- C5b applies to "
                  "probetype 0/3 only",
    }

    # particle_time_int8_fix -- refused, probetype 2 not affected
    results["v35_particle_time_int8_fix"] = {
        "engine": "3.5", "reference": "demo_flight_dense_raw.2DS", "measured": date,
        "vacuous": True,
        "reason": report["skipped"].get("particle_time_int8_fix",
                                        "probetype 2 not affected (A15)"),
    }

    # pressure_units_fix -- refused, pressure not in the .call stamp
    results["v35_pressure_units_fix"] = {
        "engine": "3.5", "reference": "demo_flight_dense_raw.2DS", "measured": date,
        "vacuous": True,
        "reason": report["skipped"].get("pressure_units_fix",
                                        "run pressure not recoverable from the .call stamp"),
    }

    # overload_accounting_fix -- conditional refusal on the default run
    results["v35_overload_accounting_fix"] = {
        "engine": "3.5", "reference": "demo_flight_dense_raw.2DS", "measured": date,
        "vacuous": "overload_accounting_fix" not in report["applied"],
        "reason": report["skipped"].get(
            "overload_accounting_fix",
            "applied" if "overload_accounting_fix" in report["applied"] else None),
    }

    # arco_export -- size effect, real
    enh_arco = out_dir / f"{STEM}.enh.arco.nc"
    if enh_arco.is_file():
        sd_size = outputs.sd.stat().st_size
        arco_size = enh_arco.stat().st_size
        results["v35_arco_export"] = {
            "engine": "3.5", "reference": "demo_flight_dense_raw.2DS", "measured": date,
            "sd_bytes": sd_size, "arco_bytes": arco_size,
            "ratio": round(arco_size / sd_size, 3) if sd_size else None,
        }
    else:
        results["v35_arco_export"] = {
            "engine": "3.5", "reference": "demo_flight_dense_raw.2DS", "measured": date,
            "vacuous": True, "reason": report["skipped"].get("arco_export", "not applied"),
        }

    return results


def archive_superseded_before_overwrite(registry: dict, key: str) -> str | None:
    """If ``registry[key]`` already carries a ``"superseded"`` marker, move it to
    ``<key>_superseded_<date>`` (never deleted, never silently overwritten) before ``key`` is
    replaced by a fresh measurement. Returns the archive key used, or ``None`` if there was
    nothing superseded to archive.

    Since 2026-09-15: a rerun of this tool regenerates ``v35_outoffocus`` wholesale via
    plain ``dict.update``, which would have dropped the ``superseded``/``superseded_reason``
    fields added when the wrong-direction A/B was marked superseded, along with the old
    figures themselves -- the exact "history silently overwritten" failure the rest of this
    project's registries are built to refuse. This is the guard.
    """
    existing = registry.get(key)
    if not isinstance(existing, dict) or "superseded" not in existing:
        return None
    date = existing["superseded"]
    archive_key = f"{key}_superseded_{date}"
    suffix = 2
    while archive_key in registry:
        archive_key = f"{key}_superseded_{date}_{suffix}"
        suffix += 1
    registry[archive_key] = existing
    return archive_key


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true",
                        help="write the measured keys into docs/measurements.json")
    args = parser.parse_args(argv)

    root = Path(tempfile.mkdtemp())
    try:
        built = build_dense_v35(root)
        results = measure(built["outputs"], built["out_dir"], built["report"])
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print(json.dumps(results, indent=2, default=str))

    if args.write:
        registry = json.loads(MEASUREMENTS.read_text(encoding="utf-8"))
        archived = []
        for key in results:
            moved = archive_superseded_before_overwrite(registry, key)
            if moved:
                archived.append(moved)
        registry.update(results)
        MEASUREMENTS.write_text(
            json.dumps(registry, indent=2, sort_keys=False) + "\n", encoding="utf-8")
        print(f"wrote {len(results)} keys to {MEASUREMENTS}")
        if archived:
            print(f"archived superseded entries before overwrite: {archived}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
