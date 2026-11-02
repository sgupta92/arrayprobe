# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe_uiops.combine`` -- the ORACLES fork's combine, borrowed for v3.5.

2026-09-13: v3.5 gets the fork's ``combine_sizedist.m``, run over
v3.5 ``sd`` output, labelled as borrowed and opt-in (default OFF). This module
adds no arithmetic of its own -- it guards the input schema and delegates to
:func:`arrayprobe.combine.combine_sizedist`, reused rather than copied.

**Measurement made before this test or the module it
tests was written:** the only open question was whether v3.5
writes ``mean_area_ratio`` with a different on-disk orientation than v3.1.4,
which would make the unmodified fork combine silently mis-read it. Measured
against the tracked Octave goldens ``tests/data/v35_sizedist/main.nc`` (v3.5)
and ``tests/data/s4_sizedist_octave_golden.nc`` (v3.1.4): both declare
``mean_area_ratio`` with the identical on-disk dimension order
(``Time``, ``CIPcorrlen``), and :func:`arrayprobe.ncio.get_var` -- which
reverses on-disk order back to MATLAB order for both engines, since both go
through the one shared ``ncio`` module -- returns it as the same
``(bin, time)`` MATLAB shape for both. **Same orientation; no adapter
arithmetic needed.** (Full measurement, including why v3.5's own upstream fix
to this variable does not change that on-disk contract: see
``arrayprobe_uiops/combine.py``'s module docstring and the P7 report.)
"""

from __future__ import annotations

import ast
import inspect
import tempfile
import unittest
from pathlib import Path

from tests._repo import needs_source

try:
    import netCDF4
except ImportError:  # pragma: no cover
    netCDF4 = None

import numpy as np

import arrayprobe.combine as v314_combine
import arrayprobe_uiops.combine as v35_combine
from arrayprobe import ncio

DATA = Path(__file__).resolve().parent / "data"
GOLDEN = DATA / "v35_sizedist" / "main.nc"

#: main.nc's own six stamps (164128..164133 -> 16:41:28..16:41:33); the
#: summary matches the FIRST one exactly, so no summary-sync padding is
#: added and the identity comparison below isolates the combine step itself.
FLIGHT_DATE = "20160906"
SUMMARY = "16_09_06_16_41_28"


def _write_sd(path, *, time, bin_mid, order, values):
    """A minimal sd-shaped file: only the variables named in ``order`` (write
    order determines on-disk index, exactly like the real ``sizeDist.m``
    output ``combine_sizedist.m`` reads by hard-coded index). ``values[name]``
    is a ``(T,)`` array for a time-only variable or a ``(B, T)`` array
    (MATLAB order: bin, time) for a two-dimensional one.
    """
    T, B = len(time), len(bin_mid)
    f = ncio.create(str(path), "clobber")
    t_dim = ncio.def_dim(f, "Time", T)
    b_dim = ncio.def_dim(f, "CIPcorrlen", B)
    dims = {}
    for name in order:
        arr = np.asarray(values[name])
        if arr.ndim == 2:
            dims[name] = [b_dim, t_dim]
        elif arr.shape[0] == T:
            dims[name] = [t_dim]
        else:
            dims[name] = [b_dim]
    varids = {name: ncio.def_var(f, name, "double", dims[name]) for name in order}
    ncio.end_def(f)
    for name in order:
        ncio.put_var(f, varids[name], np.asarray(values[name], dtype=np.float64))
    ncio.close(f)


def _minimal_values(time, bin_mid):
    """Every name :data:`arrayprobe.combine.MATLAB_VARID` and its fillers
    need, at sizes consistent with ``time``/``bin_mid`` -- values themselves
    are arbitrary, only shape and NAME matter to the schema check."""
    T, B = len(time), len(bin_mid)
    rng = np.random.default_rng(0)
    values = {
        "time": np.asarray(time, dtype=np.float64),
        "bin_min": bin_mid - 0.005,
        "bin_max": bin_mid + 0.005,
        "bin_mid": bin_mid,
        "bin_dD": np.full(B, 0.01),
        "conc_minR": rng.random((B, T)),
        "area": np.zeros((B, T)),
        "conc_AreaR": rng.random((B, T)),
        "n": rng.random(T),
        "Reject_ratio": rng.random(T),
        "count": rng.integers(0, 5, size=(B, T)).astype(np.float64),
        "mean_area_ratio": rng.random((B, T)),
    }
    for i in range(9, 15):
        values[f"_filler{i}"] = np.zeros(T)
    for i in range(16, 20):
        values[f"_filler{i}"] = np.zeros((B, T))
    return values


def _correct_order():
    """The real ``sizeDist.py`` write order for indices 0-21 (only the
    variables the fork combine ever touches, plus the fillers between them,
    so the 11 read variables land at the exact indices ``MATLAB_VARID``
    names)."""
    order = ["time", "bin_min", "bin_max", "bin_mid", "bin_dD",
             "conc_minR", "area", "conc_AreaR", "n"]
    order += [f"_filler{i}" for i in range(9, 15)]
    order += ["Reject_ratio"]
    order += [f"_filler{i}" for i in range(16, 20)]
    order += ["count", "mean_area_ratio"]
    return order


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
class OptInOff(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_default_refuses_and_writes_nothing(self):
        out = self.tmp / "out.nc"
        with self.assertRaises(v35_combine.BorrowedCombineNotEnabled) as ctx:
            v35_combine.combine_sizedist(
                [GOLDEN], out, flight_date=FLIGHT_DATE, summary_time=SUMMARY,
            )
        self.assertIn("borrowed_combine", str(ctx.exception))
        self.assertFalse(out.exists())
        self.assertFalse(out.with_name(out.name + ".call").exists())

    def test_explicit_false_is_the_same_refusal(self):
        out = self.tmp / "out.nc"
        with self.assertRaises(v35_combine.BorrowedCombineNotEnabled):
            v35_combine.combine_sizedist(
                [GOLDEN], out, flight_date=FLIGHT_DATE, summary_time=SUMMARY,
                borrowed_combine=False,
            )
        self.assertFalse(out.exists())


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
class OptInOn(unittest.TestCase):
    def setUp(self):
        if not GOLDEN.is_file():
            self.skipTest("The input is a is not distributed with the package")
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_is_byte_identical_to_the_v314_combine_on_the_same_input(self):
        a = self.tmp / "a.nc"
        b = self.tmp / "b.nc"
        v314_combine.combine_sizedist(
            [GOLDEN], a, flight_date=FLIGHT_DATE, summary_time=SUMMARY,
        )
        v35_combine.combine_sizedist(
            [GOLDEN], b, flight_date=FLIGHT_DATE, summary_time=SUMMARY,
            borrowed_combine=True,
        )
        self.assertEqual(a.read_bytes(), b.read_bytes())

    def test_sidecar_records_the_borrowing(self):
        b = self.tmp / "b.nc"
        v35_combine.combine_sizedist(
            [GOLDEN], b, flight_date=FLIGHT_DATE, summary_time=SUMMARY,
            borrowed_combine=True,
        )
        sidecar = b.with_name(b.name + ".call")
        self.assertTrue(sidecar.is_file())
        text = sidecar.read_text()
        self.assertIn("borrowed-oracles-fork", text)
        self.assertIn("combine_sizedist.m", text)
        self.assertIn("engine=3.5", text)
        self.assertIn("main.nc", text)

    def test_output_is_netcdf3_classic_like_the_fork_script(self):
        b = self.tmp / "b.nc"
        v35_combine.combine_sizedist(
            [GOLDEN], b, flight_date=FLIGHT_DATE, summary_time=SUMMARY,
            borrowed_combine=True,
        )
        # combine_sizedist.m's own 'clobber' default -- unaffected by v3.5's
        # sd files being NETCDF4 (see test_reads_a_netcdf4_input below): the
        # fork script's OWN output format is what this asserts, not its
        # input's.
        with netCDF4.Dataset(b) as ds:
            self.assertEqual(ds.data_model, "NETCDF3_CLASSIC")

    def test_reads_a_netcdf4_input(self):
        with netCDF4.Dataset(GOLDEN) as ds:
            self.assertEqual(ds.data_model, "NETCDF4")
        b = self.tmp / "b.nc"
        out = v35_combine.combine_sizedist(
            [GOLDEN], b, flight_date=FLIGHT_DATE, summary_time=SUMMARY,
            borrowed_combine=True,
        )
        self.assertTrue(Path(out).is_file())


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
class Schema(unittest.TestCase):
    def setUp(self):
        if not GOLDEN.is_file():
            self.skipTest("The input is a is not distributed with the package")
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.time = np.array([64403.0, 64404.0, 64405.0])
        self.bin_mid = np.round(np.arange(0.005, 0.005 + 0.01 * 6, 0.01), 6)

    def test_v35_golden_variables_sit_at_the_indices_the_fork_reads(self):
        ds = ncio.open(str(GOLDEN), "nowrite")
        try:
            for name, expected_idx in v314_combine.MATLAB_VARID.items():
                self.assertEqual(
                    ncio.inq_var_id(ds, name), expected_idx,
                    f"{name}: v3.5 golden does not match combine_sizedist.m's "
                    f"hard-coded index",
                )
        finally:
            ncio.close(ds)

    def test_a_reordered_file_is_refused(self):
        values = _minimal_values(self.time, self.bin_mid)
        order = _correct_order()
        # Swap the last two -- count and mean_area_ratio trade places, so
        # combine_sizedist.m's index-21 read would land on Counts instead of
        # Mean Area Ratio.
        order[-1], order[-2] = order[-2], order[-1]
        path = self.tmp / "reordered.nc"
        _write_sd(path, time=self.time, bin_mid=self.bin_mid, order=order,
                  values=values)
        with self.assertRaises(v35_combine.SdSchemaMismatch) as ctx:
            v35_combine.check_sd_schema(path)
        msg = str(ctx.exception)
        self.assertTrue("count" in msg or "mean_area_ratio" in msg, msg)

    def test_a_file_missing_a_read_variable_is_refused(self):
        values = _minimal_values(self.time, self.bin_mid)
        order = [n for n in _correct_order() if n != "Reject_ratio"]
        path = self.tmp / "missing_var.nc"
        _write_sd(path, time=self.time, bin_mid=self.bin_mid, order=order,
                  values=values)
        with self.assertRaises(v35_combine.SdSchemaMismatch) as ctx:
            v35_combine.check_sd_schema(path)
        self.assertIn("Reject_ratio", str(ctx.exception))

    def test_a_correctly_ordered_file_passes(self):
        values = _minimal_values(self.time, self.bin_mid)
        order = _correct_order()
        path = self.tmp / "ok.nc"
        _write_sd(path, time=self.time, bin_mid=self.bin_mid, order=order,
                  values=values)
        v35_combine.check_sd_schema(path)  # must not raise


class ReuseNotCopy(unittest.TestCase):
    @needs_source
    def test_module_contains_no_arithmetic_and_delegates(self):
        src = (Path(__file__).resolve().parents[1] / "src" / "arrayprobe_uiops"
               / "combine.py")
        tree = ast.parse(src.read_text(encoding="utf-8"))
        # Same operator set and same caveat as uiops/__init__.py's own
        # "computes nothing" test: arithmetic operators only, so a `str |
        # None` annotation (a BinOp too, PEP 604) does not false-positive.
        arithmetic = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv,
                      ast.Mod, ast.Pow)
        offending = [
            ast.unparse(n) for n in ast.walk(tree)
            if (isinstance(n, ast.BinOp) and isinstance(n.op, arithmetic))
            or (isinstance(n, ast.AugAssign) and isinstance(n.op, arithmetic))]
        self.assertEqual(
            offending, [],
            f"arrayprobe_uiops.combine contains arithmetic ({offending}); it "
            f"must stay a guard + label + delegation")
        self.assertIs(v35_combine._fork_combine, v314_combine)

    def test_defaults_are_off(self):
        sig = inspect.signature(v35_combine.combine_sizedist)
        self.assertIs(sig.parameters["borrowed_combine"].default, False)


if __name__ == "__main__":
    unittest.main()
