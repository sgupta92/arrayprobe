# SPDX-License-Identifier: BSD-3-Clause
"""The driver adapter: ``registry.apply`` routes resolved corrections through
``arrayprobe_soda2.enhancement_hooks`` so ``soda2_process_2d`` *applies* them.

Three claims, each against the real, unmodified driver on the tracked fixtures:

* every registered correction is either routed or has a recorded reason (no silent third state);
* with every correction OFF the run is byte-identical to the port (``.pbp.csv`` bytes, every
  ``.pbp.nc`` variable and dtype, every ``ProcessData`` field);
* an ON correction changes exactly its documented output -- ``pbp_rejectionflag_ubyte`` (S6-k)
  turns the driver-written ``rejectionflag`` from ``int8`` into ``uint8``; ``den_clamp_fix``
  (S2-f) reaches the port's own ``aspect_ratio`` call site with the finding's two numbers.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace

import arrayprobe_soda2.aspect_ratio as port_ar
import numpy as np
from arrayprobe_soda2 import enhancement_hooks
from arrayprobe_soda2.process_2d import soda2_process_2d

from arrayprobe_soda2_enhancements import _adapter
from arrayprobe_soda2_enhancements.registry import (
    PROTECTIVE,
    REGISTRY,
    apply,
    load_all,
    resolve,
)

DATA = Path(__file__).resolve().parents[2] / "tests" / "data"
FRAME_FIXTURE = DATA / "soda2_spec_frame_fixture"
AR_GOLDEN = DATA / "gdl_soda2_aspect_ratio_golden.json"


def _base_op(**overrides) -> dict:
    """``tests/test_soda2_process_2d.py::_base_op``, duplicated (fixture plumbing,
    not port logic -- the stage 2/3 convention)."""
    op = dict(
        fn=str(FRAME_FIXTURE), date="20160906", starttime=24240.0, stoptime=24250.0,
        format="SPEC", subformat=0, probetype="2DS", res=10.0,
        endbins=[0.0, 50.0, 100.0, 200.0, 500.0], arendbins=[0.0, 0.5, 1.0],
        rate=1.0, smethod="xy", pth="", particlefile=1, inttime_reject=0,
        stuckbits=1, water=0, fixedtas=0.0, timeoffset=0.0, armwidth=6.3,
        numdiodes=128, greythresh=0, probeid="H", eawmethod="centerin",
        wavelength=0.785e-6, dofconst=8.12, ncdfparticlefile=1, asciipsdfile=0,
        dofreject=3, keeplargest=1,
        # `savfile` defaults to 1 (`update_op`) and the driver now
        # writes the SAVE file, which needs `outdir`; mirrors the port test's _base_op.
        savfile=0,
    )
    op.update(overrides)
    return op


def _run(resolved: dict | None):
    """Driver run into a temp dir, under ``apply(resolved)`` unless ``resolved is None``."""
    netCDF4 = __import__("netCDF4")
    with tempfile.TemporaryDirectory() as tmp:
        op = _base_op(outdir=tmp + os.sep)
        record = None
        if resolved is None:
            d = soda2_process_2d(op)
        else:
            with apply(resolved) as record:
                d = soda2_process_2d(op)
        # `pbp_writer.py:207` stamps the wall clock ("Date Processed:"), like UIOOPS's
        # 'Creation Time' -- excluded from the byte comparison, every other byte kept.
        csv = b"".join(line for p in sorted(Path(tmp).glob("*.pbp.csv"))
                       for line in p.read_bytes().splitlines(keepends=True)
                       if not line.startswith(b"Date Processed:"))
        nc = {}
        for p in sorted(Path(tmp).glob("*.pbp.nc")):
            ds = netCDF4.Dataset(str(p))
            try:
                ds.set_auto_maskandscale(False)
                nc = {k: (v.dtype.str, np.array(v[:])) for k, v in ds.variables.items()}
            finally:
                ds.close()
    return d, csv, nc, record


def _all_off() -> dict[str, bool]:
    load_all()
    return {n: False for n in REGISTRY}


def _assert_same(tc, a, b, where="data"):
    for f in fields(a):
        if f.name in ("date_processed", "pbp_csv_path", "pbp_ncdf_path"):
            continue
        va, vb = getattr(a, f.name), getattr(b, f.name)
        if isinstance(va, np.ndarray):
            tc.assertEqual(va.dtype, vb.dtype, f"{where}.{f.name}")
            np.testing.assert_array_equal(va, vb, err_msg=f"{where}.{f.name}")
        elif f.name == "op":
            tc.assertEqual(sorted(va), sorted(vb))
        elif hasattr(va, "__dataclass_fields__"):
            _assert_same(tc, va, vb, f"{where}.{f.name}")
        else:
            tc.assertEqual(va, vb, f"{where}.{f.name}")


class EveryCorrectionHasADecision(unittest.TestCase):
    def test_routes_and_reasons_partition_the_registry(self):
        load_all()
        routed, reasons = set(_adapter.ROUTES), set(_adapter.NOT_ROUTED)
        self.assertEqual(routed & reasons, set())
        self.assertEqual(routed | reasons, set(REGISTRY))

    def test_every_route_names_a_real_hook_point(self):
        self.assertEqual(set(_adapter.ROUTES.values()) - set(enhancement_hooks.HOOK_POINTS),
                         set())

    def test_the_all_on_table_composes_without_a_stacking_refusal(self):
        load_all()
        with apply(resolve({n: True for n in REGISTRY})) as record:
            self.assertEqual(sorted(record["applied"]), sorted(_adapter.ROUTES))
            self.assertEqual(sorted(record["skipped"]), sorted(_adapter.NOT_ROUTED))
            self.assertEqual(record["hook_points"]["axis_and_ratio"],
                             "aspr_nan_fix, den_clamp_fix")
            self.assertEqual(record["hook_points"]["label_blobs"],
                             "dilation_clamp_fix, label_blobs_int_count")
        self.assertTrue(all(enhancement_hooks.pristine().values()))

    def test_the_default_table_applies_only_the_protective_set(self):
        """A14 (2026-09-28): ordinary corrections are opt-in; the protective set runs by
        default because SODA-2 has no archived product for any probe."""
        load_all()
        self.assertEqual(set(PROTECTIVE) & set(_adapter.NOT_ROUTED), set())
        with apply(resolve({}, protective=PROTECTIVE)) as record:
            self.assertEqual(sorted(record["applied"]), sorted(PROTECTIVE))
            self.assertEqual(dict(record["skipped"]), {})
            self.assertNotIn("axis_and_ratio", record["hook_points"])
            self.assertEqual(record["hook_points"]["label_blobs"], "dilation_clamp_fix")
        self.assertTrue(all(enhancement_hooks.pristine().values()))


class AllOffIsThePort(unittest.TestCase):
    def test_every_correction_off_is_byte_identical_to_the_plain_port(self):
        plain = _run(None)
        off = _run(_all_off())
        self.assertEqual(off[3], {"applied": [], "skipped": {}, "hook_points": {}})
        _assert_same(self, plain[0], off[0])
        self.assertGreater(len(plain[1]), 0)
        self.assertEqual(plain[1], off[1])
        self.assertEqual(sorted(plain[2]), sorted(off[2]))
        for k, (dtype, arr) in plain[2].items():
            self.assertEqual(dtype, off[2][k][0], k)
            np.testing.assert_array_equal(arr, off[2][k][1], err_msg=k)


class AnOnCorrectionChangesItsDocumentedOutput(unittest.TestCase):
    def test_pbp_rejectionflag_ubyte_changes_the_driver_written_dtype(self):
        plain = _run(None)
        only = dict(_all_off(), pbp_rejectionflag_ubyte=True)
        fixed = _run(only)
        self.assertEqual(fixed[3]["applied"], ["pbp_rejectionflag_ubyte"])
        self.assertEqual(plain[2]["rejectionflag"][0], "|i1", "the port's own S6-k type")
        self.assertEqual(fixed[2]["rejectionflag"][0], "|u1")
        # ... and nothing else in the written products moves on this fixture.
        self.assertEqual(plain[1], fixed[1])
        for k in plain[2]:
            if k != "rejectionflag":
                np.testing.assert_array_equal(plain[2][k][1], fixed[2][k][1], err_msg=k)
        _assert_same(self, plain[0], fixed[0])

    def test_den_clamp_fix_reaches_the_ports_own_call_site(self):
        """``aspect_ratio.py:528`` reads ``axis_and_ratio`` from the module; under the adapter
        that read returns S2-f's corrected value on the finding's named golden geometry."""
        golden = {r["name"]: r for r in json.loads(AR_GOLDEN.read_text(encoding="utf-8"))}
        case = golden["den_clamp_bites_tas025_float"]
        x = np.asarray(case["XI"], dtype=np.int32)
        y = (np.asarray(case["YI"], dtype=np.int64).astype(np.float32)
             * np.float32(case["tas_value"])).astype(np.float32)
        circle = SimpleNamespace(diam=float(case["DIAM"]),
                                 center=np.array([case["CX"], case["CY"]], dtype=np.float64),
                                 corners=list(case["CORNERS"]))
        before = float(port_ar.axis_and_ratio(x, y, circle)[0])
        with apply(dict(_all_off(), den_clamp_fix=True)):
            during = float(port_ar.axis_and_ratio(x, y, circle)[0])
        after = float(port_ar.axis_and_ratio(x, y, circle)[0])
        self.assertAlmostEqual(before, 0.6136363636363636, places=9)
        self.assertAlmostEqual(during, 0.7272727272727273, places=9)
        self.assertEqual(before, after)

    def test_the_protective_run_completes_and_leaves_the_port_pristine(self):
        load_all()
        d, csv, nc, record = _run(resolve({}, protective=PROTECTIVE))
        self.assertIsNotNone(d)
        self.assertGreater(len(csv), 0)
        self.assertEqual(nc["rejectionflag"][0], "|u1")
        self.assertTrue(all(enhancement_hooks.pristine().values()))


if __name__ == "__main__":
    unittest.main()
