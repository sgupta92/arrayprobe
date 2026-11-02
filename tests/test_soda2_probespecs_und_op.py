# SPDX-License-Identifier: BSD-3-Clause
"""The probe table against a real `op`: UND's 0914 HVPS-3 SODA-2 SAVE file.

Skips when the gitignored `arrayprobe-local-data/2016-und-data/` tree is not
reachable (a worktree finds it through its main checkout; CI has none). No UND
value is written here: every assertion is an equality between the SAVE file's
`op` and a public SODA-2 source (the table, or `soda2_update_op.pro`'s default).

What it establishes (measured 2026-09-15):

- ten probe fields UND's `op` carries -- `shortname`, `format`, `subformat`,
  `probetype`, `probeid`, `greythresh`, `res`, `yres`, `armwidth`,
  `numdiodes` -- equal the table's `'HVPS-3'` row in value **and** IDL type
  (`numdiodes` FLOAT, as the table has it and `soda2_update_op.pro:23` does
  not);
- `wavelength` does **not**: UND's `op` carries `soda2_update_op.pro:29`'s
  default, not the table's 0.785e-6. Its tag sits among the tags
  `soda2_update_op` appends (`CLUSTERTHRESH, WAVELENGTH, KEEPLARGEST, YRES`,
  in that routine's order), so the 2016 `op` was built without a wavelength
  and the default filled it (derived from tag order, not from a 2016 source).
  A same-code comparison must therefore take `wavelength` from the SAVE file's
  `op`, never from this table -- which is what the comparison
  does;
- UND's `op` has no `DOFCONST`, `TAU`, `SEATAG` or `DIODERANGE` tag;
- every probe field is a one-element array in the SAVE file -- the IDL
  `Array[1]` shape the port's scalars (GDL's reading) do not carry.
"""
from __future__ import annotations

import os
import unittest
from pathlib import Path
from typing import Any

import numpy as np

from arrayprobe_soda2.probespecs import soda2_probespecs

_REL = Path("2016-und-data") / "20160914_075310" / "HVPS3_Data" / "09142016_075310_HVPS3.dat"


def _find_dat() -> Path | None:
    roots = []
    if os.environ.get("ARRAYPROBE_REFERENCE_DATA"):
        roots.append(Path(os.environ["ARRAYPROBE_REFERENCE_DATA"]))
    # A git worktree may sit below the checkout that holds the data, so every parent is tried.
    for parent in Path(__file__).resolve().parents:
        roots.append(parent / "arrayprobe-local-data")
    for root in roots:
        if (root / _REL).is_file():
            return root / _REL
    return None


_DAT = _find_dat()
_SHARED = ("shortname", "format", "subformat", "probetype", "probeid", "greythresh",
           "res", "yres", "armwidth", "numdiodes")


@unittest.skipIf(_DAT is None, "UND 2016 data is not distributed with the package")
class TestUND0914HVPS3Op(unittest.TestCase):

    op: Any  # assigned in setUpClass/setUp; see there for the value
    @classmethod
    def setUpClass(cls):
        from scipy.io import readsav
        restored = readsav(str(_DAT))
        op = restored["data"]["op"] if "data" in restored else restored["op"]
        cls.op = np.asarray(op).reshape(-1)[0]
        cls.tags = set(cls.op.dtype.names)
        cls.table = soda2_probespecs(name="HVPS-3")

    def _und(self, tag: str):
        v = self.op[tag.upper()]
        self.assertEqual(np.shape(v), (1,), f"{tag}: IDL Array[1] in the SAVE file")
        v = v[0]
        return v.decode() if isinstance(v, bytes) else v

    def test_ten_probe_fields_equal_the_table_in_value_and_type(self):
        for tag in _SHARED:
            with self.subTest(tag=tag):
                und, ours = self._und(tag), self.table[tag]
                if isinstance(ours, str):
                    self.assertEqual(und, ours)
                else:
                    self.assertEqual(np.dtype(type(und)).newbyteorder("="),
                                     np.dtype(ours.dtype), tag)
                    self.assertEqual(und, ours)

    def test_wavelength_is_update_ops_default_not_the_table(self):
        from arrayprobe_soda2.update_op import _FLOAT32_DEFAULTS
        und = self._und("wavelength")
        self.assertNotEqual(np.float32(und), self.table["wavelength"])
        self.assertEqual(np.float32(und), np.float32(_FLOAT32_DEFAULTS["wavelength"]))
        names = list(self.op.dtype.names)
        tail = [n for n in names if n in ("CLUSTERTHRESH", "WAVELENGTH", "KEEPLARGEST", "YRES")]
        self.assertEqual(tail, ["CLUSTERTHRESH", "WAVELENGTH", "KEEPLARGEST", "YRES"])
        self.assertEqual(names[-4:], tail)

    def test_the_tags_the_table_has_and_the_op_does_not(self):
        for tag in ("PROBENAME", "TAU", "FIRSTSLICESKIP", "DOFTHRESHOLD", "DOFCONST",
                    "SEATAG", "DIODERANGE"):
            self.assertNotIn(tag, self.tags)


if __name__ == "__main__":
    unittest.main()
