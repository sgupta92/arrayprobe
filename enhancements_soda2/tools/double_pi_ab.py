# SPDX-License-Identifier: BSD-3-Clause
"""S2-c A/B measurement -- prints the numbers ``test_double_pi_fix.py`` asserts as literals.

Three populations:

1. The 20 ``gdl_soda2_min_circle_fast_golden.json`` cases -- ``min_circle_fast`` vs
   :func:`corrected_min_circle_fast`, corner-count and diameter changes.
2. The 53 non-F4 ``gdl_soda2_aspect_ratio_golden.json`` cases -- ``aspect_ratio`` vs
   :func:`corrected_aspect_ratio`, the same way ``test_soda2_aspect_ratio.py``'s
   ``WholeRoutineMatchesIdl`` calls the routine.
3. The whole driver (``soda2_process_2d``), both tracked fixtures, run twice each -- once
   unpatched, once with ``arrayprobe_soda2.min_circle_fast.min_circle_fast`` monkey-patched to
   :func:`corrected_min_circle_fast` (legitimate: ``aspect_ratio.py:518`` imports it lazily,
   inside the function, so the module attribute is read at call time) -- at **both** an
   equal-ratio (``yres == xres``, the base op) and an unequal-ratio (``frame_stretch``'s
   overrides, ``stretchcorrect=1, fixedtas=120.0``) setting, per plan uncertainty #1: the
   changed fraction may be governed by ``findsize.py:247``'s float32 ``tas_adjust`` path rather
   than by which branch ``min_circle_fast`` takes.

Run: ``PYTHONPATH=<repo>/src;<repo>/enhancements_uiops/src;<repo>/enhancements_soda2/src
.venv/Scripts/python.exe enhancements_soda2/tools/double_pi_ab.py``
"""

from __future__ import annotations

import csv
import json
import tempfile
import unittest.mock as mock
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "tests" / "data"
MC_GOLDEN = DATA / "gdl_soda2_min_circle_fast_golden.json"
AR_GOLDEN = DATA / "gdl_soda2_aspect_ratio_golden.json"
S2_FIXTURE = DATA / "s2_spec_raw_fixture"
FRAME_FIXTURE = DATA / "soda2_spec_frame_fixture"


def _base_op(**overrides) -> dict:
    op = dict(
        fn=str(S2_FIXTURE), date="20160906", starttime=24240.0, stoptime=24250.0,
        format="SPEC", subformat=0, probetype="2DS", res=10.0,
        endbins=[0.0, 50.0, 100.0, 200.0, 500.0], arendbins=[0.0, 0.5, 1.0],
        rate=1.0, smethod="xy", pth="", particlefile=1, inttime_reject=0,
        stuckbits=0, water=0, fixedtas=0.0, timeoffset=0.0, armwidth=6.3,
        numdiodes=128, greythresh=0, probeid="H", eawmethod="centerin",
        wavelength=0.785e-6, dofconst=8.12, ncdfparticlefile=0, asciipsdfile=0,
    )
    op.update(overrides)
    return op


def population_1() -> dict:
    """The 20 bank cases via ``run_soda2_min_circle_fast_bank.CASES`` (not the tracked JSON
    directly): two cases (``L_shape``, ``column_10010``) omit ``x``/``y`` from the golden file
    (large synthetic arrays) and are only reconstructible through ``CaseSpec.py()``, exactly as
    ``test_soda2_min_circle_fast.py::CharacterisedAgainstTheExactCircle`` does."""
    from arrayprobe_soda2.min_circle_fast import min_circle_fast
    from run_soda2_min_circle_fast_bank import CASES  # noqa: PLC0415

    from arrayprobe_soda2_enhancements.double_pi_fix import corrected_min_circle_fast

    n = len(CASES)
    n_changed_corners = 0
    max_rel_diam = 0.0
    for _name, spec in CASES.items():
        x, y = spec.py()
        port = min_circle_fast(x, y)
        fixed = corrected_min_circle_fast(x, y)
        if len(port.corners) != len(fixed.corners):
            n_changed_corners += 1
        if port.diam != 0:
            rel = abs(fixed.diam - port.diam) / abs(port.diam)
        else:
            rel = abs(fixed.diam - port.diam)
        max_rel_diam = max(max_rel_diam, rel)
    return {"n": n, "n_changed_corners": n_changed_corners, "max_rel_diam": max_rel_diam}


def _ar_y_adjusted(case: dict) -> np.ndarray:
    yi = np.asarray(case["YI"], dtype=np.int64)
    tas_kind = case["tas_kind"]
    if tas_kind == "none":
        return yi.astype(np.int32)
    if tas_kind == "float":
        return (yi.astype(np.float32) * np.float32(case["tas_value"])).astype(np.float32)
    if tas_kind == "double":
        return yi.astype(np.float64) * np.float64(case["tas_value"])
    raise ValueError(tas_kind)


def population_2() -> dict:
    from arrayprobe_soda2.aspect_ratio import ERODE_EDGE_RULE, aspect_ratio

    from arrayprobe_soda2_enhancements.double_pi_fix import corrected_aspect_ratio

    records = json.loads(AR_GOLDEN.read_text(encoding="utf-8"))
    cases = [r for r in records if r.get("status") == "OK" and r.get("family") != "F4"]
    n = len(cases)
    n_changed_corners = 0
    n_changed_aspr = 0
    n_changed_orientation = 0
    max_abs_daspr = 0.0
    max_abs_dorient = 0.0
    for case in cases:
        tas_kind = case["tas_kind"]
        tas_adjust = None
        if tas_kind == "float":
            tas_adjust = np.float32(case["tas_value"])
        elif tas_kind == "double":
            tas_adjust = float(case["tas_value"])
        if case["mode"] == "image":
            img = np.asarray(case["image"], dtype=np.uint8)
            port = aspect_ratio(img, tas_adjust=tas_adjust, coordinates=False,
                                 edge_rule=ERODE_EDGE_RULE)
            fixed = corrected_aspect_ratio(img, tas_adjust=tas_adjust, coordinates=False,
                                            edge_rule=ERODE_EDGE_RULE)
        else:
            coords = np.asarray(case["coords"], dtype=np.int64)
            port = aspect_ratio(coords, tas_adjust=tas_adjust, coordinates=True)
            fixed = corrected_aspect_ratio(coords, tas_adjust=tas_adjust, coordinates=True)

        if len(np.asarray(port.circle.corners).ravel()) != len(np.asarray(fixed.circle.corners).ravel()):
            n_changed_corners += 1
        daspr = abs(float(fixed.aspr) - float(port.aspr))
        dorient = abs(float(fixed.orientation) - float(port.orientation))
        if daspr != 0.0:
            n_changed_aspr += 1
        if dorient != 0.0:
            n_changed_orientation += 1
        max_abs_daspr = max(max_abs_daspr, daspr)
        max_abs_dorient = max(max_abs_dorient, dorient)
    return {
        "n": n, "n_changed_corners": n_changed_corners, "n_changed_aspr": n_changed_aspr,
        "n_changed_orientation": n_changed_orientation, "max_abs_daspr": max_abs_daspr,
        "max_abs_dorient_deg": max_abs_dorient,
    }


#: `test_soda2_process_2d.py::WritersAreWiredIn.CSV_HEADER_LINES`: 4 descriptive lines + 37
#: numbered `PBPPROPS` lines + 1 separator + 1 short (comma-joined) header line, before the
#: first data row.
CSV_HEADER_LINES = 43


def _run_driver_csv(op: dict) -> list[dict]:
    from arrayprobe_soda2.process_2d import soda2_process_2d

    with tempfile.TemporaryDirectory() as tmp:
        run_op = dict(op)
        run_op["outdir"] = tmp + "/"
        run_op["particlefile"] = 1
        d = soda2_process_2d(run_op)
        if d is None:
            return []
        csv_paths = list(Path(tmp).glob("*.pbp.csv"))
        rows: list[dict] = []
        for p in csv_paths:
            lines = p.read_text(encoding="utf-8").splitlines()
            header = lines[CSV_HEADER_LINES - 1].split(",")
            for line in lines[CSV_HEADER_LINES:]:
                if not line.strip():
                    continue
                values = next(csv.reader([line]))
                rows.append(dict(zip(header, values, strict=True)))
        return rows


def _population_3_one(label: str, op: dict) -> dict:
    from arrayprobe_soda2_enhancements.double_pi_fix import corrected_min_circle_fast

    port_rows = _run_driver_csv(op)
    with mock.patch("arrayprobe_soda2.min_circle_fast.min_circle_fast",
                     corrected_min_circle_fast):
        fixed_rows = _run_driver_csv(op)

    n = len(port_rows)
    n_changed = 0
    max_daspr = 0.0
    max_dorient = 0.0
    for pr, fr in zip(port_rows, fixed_rows, strict=True):
        pa, fa = float(pr["aspectratio"]), float(fr["aspectratio"])
        po, fo = float(pr["orientation"]), float(fr["orientation"])
        if pa != fa or po != fo:
            n_changed += 1
        max_daspr = max(max_daspr, abs(fa - pa))
        max_dorient = max(max_dorient, abs(fo - po))
    frac = (n_changed / n) if n else 0.0
    return {
        "label": label, "n_particles": n, "n_changed": n_changed,
        "changed_fraction": frac, "max_abs_daspr": max_daspr, "max_abs_dorient_deg": max_dorient,
    }


def population_3() -> list[dict]:
    results = []
    # S2 fixture, equal yres/xres (base op: yres defaults to res -> both 10.0, no stretch).
    results.append(_population_3_one("s2_fixture_equal_yres_xres", _base_op()))
    # S2 fixture, unequal yres/xres via stretchcorrect (same TAS-stretch knob R8A's own
    # `frame_stretch` case uses, applied here to the S2 fixture).
    results.append(_population_3_one(
        "s2_fixture_unequal_yres_xres",
        _base_op(stretchcorrect=1, fixedtas=120.0)))
    # Frame fixture, equal yres/xres.
    results.append(_population_3_one(
        "frame_fixture_equal_yres_xres",
        _base_op(fn=str(FRAME_FIXTURE))))
    # Frame fixture, unequal yres/xres (its own `frame_stretch` overrides).
    results.append(_population_3_one(
        "frame_fixture_unequal_yres_xres",
        _base_op(fn=str(FRAME_FIXTURE), stretchcorrect=1, fixedtas=120.0)))
    return results


def main() -> None:
    print("=== Population 1: min_circle_fast golden bank (20 cases) ===")
    print(json.dumps(population_1(), indent=2))

    print("\n=== Population 2: aspect_ratio golden bank (non-F4 cases) ===")
    print(json.dumps(population_2(), indent=2))

    print("\n=== Population 3: whole driver, both fixtures, equal/unequal yres:xres ===")
    for row in population_3():
        print(json.dumps(row, indent=2))


if __name__ == "__main__":
    main()
