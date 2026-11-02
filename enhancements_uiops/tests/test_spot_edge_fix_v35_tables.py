# SPDX-License-Identifier: BSD-3-Clause
"""spot_edge_fix reads its Korolev tables from the v3.5 engine, and runs without
the v3.1.4 engine. Oracles: the vendored v3.5 MATLAB source (dev and CI) and a
golden JSON the same parser wrote from it (shipped, so the oracle fires in the
release tree too)."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import _upstream  # noqa: E402

_GOLDEN = _HERE / "data" / "korolev_tables_v35.json"
_VENDORED = _upstream.source("uiops35") / "calculate_reject_unified.m"


def parse_korolev_tables(m_path: Path) -> dict:
    """Numeric tokens of ``edge_0`` and ``spot_edge`` from a
    ``calculate_reject_unified.m``, each from its ``name =`` line through the
    next ``];``, converted with ``float()`` so ``0757`` reads as 757.0."""
    text = m_path.read_text(encoding="utf-8", errors="replace")
    out = {}
    for name in ("edge_0", "spot_edge"):
        m = re.search(r"^\s*" + name + r"\s*=\s*\[(.*?)\];", text, re.S | re.M)
        assert m, name
        body = re.sub(r"%[^\n]*", "", m.group(1)).replace("...", " ")
        out[name] = [float(t) for t in re.findall(r"\d+(?:\.\d*)?|\.\d+", body)]
    return out


def write_golden() -> None:
    """Regenerate the golden from the vendored tree (never typed by hand)."""
    tables = parse_korolev_tables(_VENDORED)
    tables["source"] = "UIOPS-v3.5/joefinlon-UIOPS-039be82/calculate_reject_unified.m"
    _GOLDEN.write_text(json.dumps(tables, indent=1) + "\n", encoding="utf-8")


def _module():
    from arrayprobe_enhancements import spot_edge_fix
    return spot_edge_fix


class GoldenTables(unittest.TestCase):
    def test_tables_equal_golden_json(self):
        mod = _module()
        golden = json.loads(_GOLDEN.read_text(encoding="utf-8"))
        self.assertEqual(len(golden["spot_edge"]), 164)
        self.assertTrue(np.array_equal(mod.SPOT_EDGE, np.asarray(golden["spot_edge"])))
        self.assertTrue(np.array_equal(mod.EDGE_0, np.asarray(golden["edge_0"])))
        self.assertTrue(np.array_equal(mod.Z_D, np.arange(164) * 0.05))
        for arr in (mod.SPOT_EDGE, mod.EDGE_0, mod.Z_D):
            self.assertIsInstance(arr, np.ndarray)
            self.assertEqual(arr.dtype, np.float64)

    def test_tables_equal_vendored_matlab(self):
        if not _VENDORED.is_file():
            self.skipTest("vendored UIOPS v3.5 tree absent (release tree)")
        mod = _module()
        parsed = parse_korolev_tables(_VENDORED)
        self.assertTrue(np.array_equal(mod.SPOT_EDGE, np.asarray(parsed["spot_edge"])))
        self.assertTrue(np.array_equal(mod.EDGE_0, np.asarray(parsed["edge_0"])))
        golden = json.loads(_GOLDEN.read_text(encoding="utf-8"))
        self.assertEqual(parsed["spot_edge"], golden["spot_edge"])
        self.assertEqual(parsed["edge_0"], golden["edge_0"])

    def test_tables_equal_v314_port(self):
        try:
            from arrayprobe import reject as r314
        except ImportError:
            self.skipTest("v3.1.4 engine absent (release tree)")
        mod = _module()
        self.assertTrue(np.array_equal(mod.Z_D, r314.Z_D))
        self.assertTrue(np.array_equal(mod.EDGE_0, r314.EDGE_0))
        self.assertTrue(np.array_equal(mod.SPOT_EDGE, r314.SPOT_EDGE))

    def test_fixed_table_differs_in_one_entry(self):
        mod = _module()
        self.assertEqual(list(np.flatnonzero(mod.SPOT_EDGE != mod.SPOT_EDGE_FIXED)), [146])
        self.assertEqual(mod.SPOT_EDGE[146], 757.0)


class MatchesV35Engine(unittest.TestCase):
    def test_matches_v35_engine_lookup_when_typo_not_reached(self):
        from arrayprobe_uiops import reject as r35
        mod = _module()
        for ratio in np.linspace(0.0031, 1.0, 4001):
            fixed = float(mod.Z_D[mod._find_last(mod.SPOT_EDGE_FIXED < ratio)])
            stock = float(mod.Z_D[mod._find_last(mod.SPOT_EDGE < ratio)])
            engine = r35._z_d_lookup(float(ratio))
            self.assertEqual(stock, engine)  # off: bit-identical to the engine
            if 0.757 < ratio <= 0.763:
                self.assertEqual(fixed, mod.Z_D[mod._find_last(mod.Z_D <= engine) + 1])
            else:
                self.assertEqual(fixed, engine)
            self.assertEqual(float(mod.EDGE_0[mod._find_last(mod.Z_D <= fixed)]),
                             r35._edge_0_lookup(fixed))

    def test_find_last_raises_on_empty(self):
        with self.assertRaises(ValueError):
            _module()._find_last(np.zeros(3, dtype=bool))


class ImportsWithoutV314(unittest.TestCase):
    def test_imports_without_v314_reject(self):
        code = (
            "import sys\n"
            "class B:\n"
            "    def find_spec(self, name, path=None, target=None):\n"
            "        if name == 'arrayprobe.reject' or name.startswith('arrayprobe.reject.'):\n"
            "            raise ModuleNotFoundError(name)\n"
            "sys.meta_path.insert(0, B())\n"
            "import arrayprobe_enhancements.spot_edge_fix as m\n"
            "assert m.SPOT_EDGE[146] == 757.0\n"
        )
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                              timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
