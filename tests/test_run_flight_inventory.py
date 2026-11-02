# SPDX-License-Identifier: BSD-3-Clause
"""The batch driver's raw-input inventory check .

Before any decode, ``run_flight.main`` inventories each raw file with
``arrayprobe.inventory.inventory_row`` (format from the driver's own reader choice, not the
guess), refuses an empty file with exit 2 unless ``--accept-flagged`` and warns about a
trailing partial record. The
row's ``inventory_empty=``/``inventory_truncated=``/``raw_sha256=`` keys go into the S2
``.call`` only, never into a netCDF attribute, and are stripped from staleness comparison.
Synthetic demo flight only (``tools/make_demo_flight.py``), S2 only.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np

from arrayprobe.tools import make_demo_flight

ROOT = Path(__file__).resolve().parents[1]

_RF_SPEC = importlib.util.spec_from_file_location("run_flight", ROOT / "scripts" / "run_flight.py")
run_flight = None


def setUpModule():  # noqa: N802
    global run_flight
    if _RF_SPEC.name in sys.modules:
        run_flight = sys.modules[_RF_SPEC.name]
    else:
        run_flight = importlib.util.module_from_spec(_RF_SPEC)
        sys.modules[_RF_SPEC.name] = run_flight
        _RF_SPEC.loader.exec_module(run_flight)
    from tests import _run_flight_state
    _run_flight_state.preserve_module(run_flight)


def _demo(root: Path, cut: int = 0) -> Path:
    raw = root / "base160101000000.2DS"
    make_demo_flight.build_demo_flight(raw, n_seconds=3)
    if cut:
        data = raw.read_bytes()
        raw.write_bytes(data[:-cut])
    return raw


def _run(raw: Path, out: Path, *extra: str) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = run_flight.main([
            str(raw), "--engine", "3.5", "--preset", "DEMO_2DS_H", "--profile", "stock-v3.5",
            "--out", str(out), "--stages", "2", "--yes", *extra])
    return rc, buf.getvalue()


def _call_text(out: Path) -> str:
    calls = [p for p in out.glob("*.call") if not p.name.startswith("proc")]
    assert len(calls) == 1, calls
    return calls[0].read_text(encoding="utf-8")


def _attrs(nc: Path) -> set[str]:
    with netCDF4.Dataset(nc) as ds:
        names = set(ds.ncattrs())
        for v in ds.variables.values():
            names |= {f"{v.name}:{a}" for a in v.ncattrs()}
    return names


class TestInventoryRefusal(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def test_truncated_input_is_warned_about_and_decoded_without_accept_flagged(self):
        # A trailing partial record is decoded on purpose by every reader (the SPEC reader's
        # ``tail`` branch, the DMT reader's floor to whole records, the PMS reader's EOF
        # outcome), as the original does, so the inventory warns and stamps it, never refuses.
        raw = _demo(self.root, cut=100)
        out = self.root / "_decoded"
        rc, log = _run(raw, out)
        self.assertEqual(rc, 0, log)
        self.assertIn("WARNING", log)
        self.assertIn("truncated", log)
        self.assertNotIn("REFUSED", log)
        self.assertIn("inventory_truncated=1", _call_text(out))

    def test_empty_input_is_refused_by_the_existing_input_preflight(self):
        # A 0-byte file never reaches the inventory check: ``preflight_inputs`` (the existing
        # gate that runs first in main(), exit 1, "is empty (0 bytes)") refuses it, with or
        # without --accept-flagged. That refusal is correct and older than the inventory, so
        # this asserts it rather than moving the inventory ahead of it (which would change an
        # existing exit code); the inventory's own empty branch covers `arrayprobe inventory`.
        raw = self.root / "base160101000000.2DS"
        raw.write_bytes(b"")
        for extra in ((), ("--accept-flagged",)):
            rc, log = _run(raw, self.root / "_decoded", *extra)
            self.assertEqual(rc, 1, log)
            self.assertIn("is empty (0 bytes)", log)

    def test_accept_flagged_proceeds_and_stamps_the_keys(self):
        raw = _demo(self.root, cut=100)
        out = self.root / "_decoded"
        sha = hashlib.sha256(raw.read_bytes()).hexdigest()
        rc, log = _run(raw, out, "--accept-flagged")
        self.assertEqual(rc, 0, log)
        self.assertIn("FLAGGED", log)
        call = _call_text(out)
        self.assertIn("inventory_empty=0", call)
        self.assertIn("inventory_truncated=1", call)
        self.assertIn(f"raw_sha256={sha}", call)


class TestCleanInputUnchanged(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def test_clean_input_stamps_keys_and_adds_no_netcdf_attribute(self):
        raw = _demo(self.root)
        out = self.root / "_decoded"
        rc, log = _run(raw, out)
        self.assertEqual(rc, 0, log)
        self.assertNotIn("REFUSED", log)
        call = _call_text(out)
        self.assertIn("inventory_truncated=0", call)
        ncs = [p for p in out.iterdir() if p.suffix in (".nc", ".cdf")]
        self.assertTrue(ncs, log)
        for nc in ncs:
            names = " ".join(_attrs(nc))
            for key in ("inventory", "raw_sha256", "truncated"):
                self.assertNotIn(key, names, nc)

    def test_clean_product_bytes_equal_a_run_with_the_check_bypassed(self):
        """Byte-identity: the decode with the inventory check equals one where it is bypassed
        (preflight stubbed to proceed and record nothing), 'Creation Time' aside."""
        raw = _demo(self.root)
        a, b = self.root / "a", self.root / "b"
        rc, log = _run(raw, a)
        self.assertEqual(rc, 0, log)
        real = run_flight.inventory_preflight
        run_flight.INVENTORY_ROWS.clear()
        run_flight.inventory_preflight = lambda raws: 0
        try:
            rc, log = _run(raw, b)
        finally:
            run_flight.inventory_preflight = real
        self.assertEqual(rc, 0, log)
        for nc in [p for p in a.iterdir() if p.suffix in (".nc", ".cdf")]:
            other = b / nc.name
            with netCDF4.Dataset(nc) as x, netCDF4.Dataset(other) as y:
                self.assertEqual(set(x.ncattrs()), set(y.ncattrs()), nc.name)
                for name, v in x.variables.items():
                    va, vb = np.ma.asarray(v[:]), np.ma.asarray(y.variables[name][:])
                    self.assertEqual(va.shape, vb.shape, name)
                    self.assertTrue(
                        np.array_equal(np.ma.getmaskarray(va), np.ma.getmaskarray(vb)), name)
                    self.assertTrue(np.array_equal(va.filled(0), vb.filled(0)), name)
        # The stamps differ only by the inventory fragment, which staleness ignores.
        ca, cb = _call_text(a), _call_text(b)
        self.assertNotEqual(ca, cb)
        self.assertTrue(run_flight._stamps_equivalent(ca.strip(), cb.strip()))


class TestInventoryCli(unittest.TestCase):
    def test_cli_writes_the_json(self):
        from arrayprobe import cli
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        (root / "raw").mkdir()
        _demo(root / "raw", cut=10)
        stem = root / "inv"
        with contextlib.redirect_stdout(io.StringIO()):
            rc = cli.main(["inventory", str(root / "raw"), "--out", str(stem)])
        self.assertEqual(rc, 0)
        rows = json.loads((root / "inv.json").read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["truncated"])
        self.assertTrue((root / "inv.csv").exists())


if __name__ == "__main__":
    unittest.main()
