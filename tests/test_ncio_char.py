# SPDX-License-Identifier: BSD-3-Clause
"""``netcdf.defVar(...,'char',...)`` -- held to an Octave-written file.

No UIOOPS call site defines a char variable, so the mapping is measured under
Octave's ``netcdf`` package (``octave_oracle/run_defvar_char_bank.py``): the
tracked file ``tests/data/defvar_char_octave.nc`` is what Octave wrote, and
``defvar_char_octave_golden.json`` holds Octave's own ``inqVar``/``getVar``
read-back plus the raw on-disk view. The port repeats the same call sequence
through :mod:`arrayprobe.ncio` and must produce the same file.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from netCDF4 import Dataset

from arrayprobe import ncio

DATA = Path(__file__).resolve().parent / "data"
GOLDEN = json.loads((DATA / "defvar_char_octave_golden.json").read_text(encoding="utf-8"))
OCTAVE_NC = DATA / "defvar_char_octave.nc"


def _on_disk(path: Path) -> dict:
    """The same raw view the bank records (``run_defvar_char_bank.on_disk``)."""
    out: dict = {}
    with Dataset(path, "r") as ds:
        out["data_model"] = ds.data_model
        out["dimensions"] = {n: (None if d.isunlimited() else len(d))
                             for n, d in ds.dimensions.items()}
        out["unlimited_length"] = {n: len(d) for n, d in ds.dimensions.items()
                                   if d.isunlimited()}
        out["variables"] = {}
        for name, var in ds.variables.items():
            var.set_auto_maskandscale(False)
            var.set_auto_chartostring(False)
            out["variables"][name] = {
                "dtype": var.dtype.str,
                "dimensions": list(var.dimensions),
                "shape": list(var.shape),
                "bytes_hex": var[...].tobytes().hex(),
                "attributes": {a: var.getncattr(a) for a in var.ncattrs()},
            }
    return out


def _write_like_octave(path: Path) -> None:
    """``run_defvar_char_oracle.m``'s write sequence, line for line."""
    f = ncio.create(path)
    d_len = ncio.def_dim(f, "strlen", 5)
    d_n = ncio.def_dim(f, "n", 3)
    d_w = ncio.def_dim(f, "w", 4)
    d_p = ncio.def_dim(f, "p", 6)
    d_t = ncio.def_dim(f, "time", ncio.NC_UNLIMITED)
    v_mat = ncio.def_var(f, "names", "char", [d_len, d_n])
    v_row = ncio.def_var(f, "word", "char", d_w)
    v_part = ncio.def_var(f, "partial", "char", d_p)
    v_rec = ncio.def_var(f, "tags", "char", [d_len, d_t])
    ncio.put_att(f, v_mat, "units", "none")
    ncio.end_def(f)
    names = np.array([list("abcde"), list("fghij"), list("klmno")])  # 3x5 'U1'
    ncio.put_var(f, v_mat, names.T)
    ncio.put_var(f, v_row, "wxyz")
    ncio.put_var(f, v_part, [1], [3], "QRS")
    ncio.put_var(f, v_rec, [0, 0], [5, 2], np.array([list("uvwxy"), list("z0123")]).T)
    ncio.close(f)


class TestCharMapping(unittest.TestCase):
    def test_char_maps_to_S1_which_octave_writes_as_NC_CHAR(self):
        self.assertEqual(ncio.MATLAB_NC_TYPES["char"], "S1")
        self.assertEqual(GOLDEN["NC_CHAR"], 2)
        for row in GOLDEN["getVar"]:
            self.assertEqual(row["xtype"], GOLDEN["NC_CHAR"], row["name"])
        for name, var in GOLDEN["on_disk"]["variables"].items():
            self.assertEqual(var["dtype"], "|S1", name)


class TestWriteMatchesOctave(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.path = Path(self._td.name) / "char.nc"
        _write_like_octave(self.path)

    def tearDown(self):
        self._td.cleanup()

    def test_types_dimensions_and_bytes_match_the_octave_file(self):
        self.assertEqual(_on_disk(self.path), GOLDEN["on_disk"])

    def test_the_tracked_octave_file_is_the_golden(self):
        self.assertEqual(_on_disk(OCTAVE_NC), GOLDEN["on_disk"])

    def test_the_file_is_byte_identical_to_octaves(self):
        self.assertEqual(self.path.read_bytes(), OCTAVE_NC.read_bytes())

    def test_unwritten_char_elements_are_nul(self):
        part = bytes.fromhex(GOLDEN["on_disk"]["variables"]["partial"]["bytes_hex"])
        self.assertEqual(part, b"\x00QRS\x00\x00")


class TestReadBackMatchesOctaveGetVar(unittest.TestCase):
    def test_get_var_has_octaves_size_and_characters(self):
        f = ncio.open(OCTAVE_NC)
        try:
            for row in GOLDEN["getVar"]:
                got = ncio.get_var(f, ncio.inq_var_id(f, row["name"]))
                self.assertEqual(got.dtype, np.dtype("S1"), row["name"])
                self.assertEqual(list(got.shape), row["size"], row["name"])
                codes = [b[0] if b else 0 for b in got.reshape(-1, order="F").tolist()]
                self.assertEqual(codes, row["codes_colmajor"], row["name"])
        finally:
            ncio.close(f)


class TestCharPutVarRefusals(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.f = ncio.create(Path(self._td.name) / "x.nc")
        d = ncio.def_dim(self.f, "w", 2)
        self.v = ncio.def_var(self.f, "s", "char", [d])
        ncio.end_def(self.f)

    def tearDown(self):
        ncio.close(self.f)
        self._td.cleanup()

    def test_multi_character_elements_are_refused(self):
        with self.assertRaises(ValueError):
            ncio.put_var(self.f, self.v, np.array(["ab", "cd"]))

    def test_numeric_data_is_refused(self):
        with self.assertRaises(TypeError):
            ncio.put_var(self.f, self.v, np.array([1, 2]))


if __name__ == "__main__":
    unittest.main()
