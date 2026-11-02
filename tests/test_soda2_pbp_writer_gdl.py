# SPDX-License-Identifier: BSD-3-Clause
"""``pbp_writer.py`` against the GDL golden
(``gdl_oracle/run_soda2_pbp_writer_bank.py``, ``tests/data/
gdl_soda2_pbp_writer_golden.json``).

**A later pass adds the netCDF side**, which the earlier pass could not run:
the earlier "netCDF is unreachable" reading was a misdiagnosis (any
``ncdf_*`` call makes the GDL *process* deadlock in exit teardown after the
script already ran to completion; ``run_pro(..., sentinel_exit=True)`` kills
it as soon as a trailing sentinel print is seen, rather than waiting for it
to exit). B5, S6-k, S6-o and S6-p are asserted below against the
fresh golden; B8 (``tiny_inttime``) is measured. **B6 (``pthdat``
extrapolation) is measured too, as of Y3/Y3s (2026-09-14)**: the
earlier ``HANG`` was a GDL library-path defect (this build's ``!PATH`` has no
library directory, so GDL's own ``INTERPOL.pro`` -- itself a library routine
-- was undefined; fixed by passing it as ``extra_files``,
``gdl_oracle/probe_pthdat_hang.py``), not a hang in ``ncdf_varget`` or
``interpol`` itself. GDL's ``INTERPOL`` linearly extrapolates outside
``pthdat.time``'s range where ``np.interp`` clamps; the port's
``close_pbp_ncdf`` now reproduces IDL via ``pbp_writer._idl_interpol``.
``csv_only`` (``particlefile:1, ncdfparticlefile:0``) is measured as well.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np

from arrayprobe_soda2 import pbp_writer as pw
from arrayprobe_soda2.particlesort import spec_sort_locals

GOLDEN = (Path(__file__).resolve().parent / "data" / "gdl_soda2_pbp_writer_golden.json")


def _load():
    records = json.loads(GOLDEN.read_text(encoding="utf-8"))
    meta = records[0]
    cases = {r["name"]: r for r in records[1:] if r.get("status") == "OK"}
    return meta, cases


def _default_particle(overrides: dict) -> dict:
    d = {
        "buffertime": 0.5, "probetime": 0.0, "reftime": 0.0, "inttime": 0.01,
        "diam": 120.0, "arearatio": 0.8, "arearatiofilled": 0.8,
        "aspectratio": 0.8, "missed": 0.0, "area": 100.0, "areafilled": 100.0,
        "perimeterarea": 50.0, "area75": 80.0, "allin": 1, "centerin": 1,
        "dofflag": 1, "overloadflag": 0, "probetas": 50.0,
        "rawtime": 0.0, "xsize": 0.0, "ysize": 0.0, "xextent": 0.0,
        "oned": 0.0, "twod": 0.0, "areasize": 0.0, "xpos": 0.0, "ypos": 0.0,
        "edgetouch": 0, "sizecorrection": 0.0, "zd": 0.0, "aircrafttas": 0.0,
        "particlecounter": 0, "orientation": 0.0, "numregions": 0, "diodegaps": 0,
    }
    d.update(overrides)
    return d


@unittest.skipUnless(GOLDEN.exists(), "run gdl_oracle/run_soda2_pbp_writer_bank.py first")
class TestPbpCsvAgainstGdl(unittest.TestCase):
    def _build_x(self, particles: list[dict]) -> dict:
        n = len(particles)
        keys = [name for name, *_ in pw.PBPPROPS if name not in ("time", "rejectionflag")]
        x = {k: np.zeros(n, dtype=np.float64) for k in keys}
        for i, p in enumerate(particles):
            full = _default_particle(p)
            for k in keys:
                x[k][i] = full.get(k, 0.0)
        return x

    def _run_case(self, name: str):
        meta, cases = _load()
        case = cases[name]
        outdir = tempfile.mkdtemp()
        op = {
            "outdir": outdir.replace("\\", "/") + "/", "date": "20160906",
            "starttime": 0.0, "stoptime": 4.0,
        }
        date = {"month": "09", "day": "06", "year": "2016"}
        path = Path(outdir) / "out.pbp.csv"
        f = pw.open_pbp_csv(str(path), op, date)
        ncdf_offset = 0
        for buf in case["buffers"]:
            x = self._build_x(buf)
            truetime, interarrival = spec_sort_locals(x)
            rejectionflag = np.zeros(len(buf), dtype=np.uint8)
            istop = len(buf) - 1
            pw.write_pbp_csv_buffer(f, x, istop, truetime, rejectionflag)
            ncdf_offset += istop + 1
        f.close()
        port_lines = path.read_text().splitlines(keepends=True)
        golden_path = (Path(__file__).resolve().parent / "data" / case["csv_tracked"])
        golden_lines = golden_path.read_text().splitlines(keepends=True)
        return port_lines, golden_lines

    def _assert_matches(self, name: str):
        port_lines, golden_lines = self._run_case(name)
        # Line 3 ("Date Processed: ...") is non-deterministic on both sides.
        # Lines 5-41 (the 37 numbered header rows) carry the bank's own
        # abbreviated longnames -- transcribed into the bank script for
        # brevity, not IDL's actual (verbatim, longer) strings -- so full
        # text is not comparable there; only the leading "<width>. name: "
        # prefix (name comes straight from PBPPROPS on both sides) is
        # checked, which is what B2 (the numbering width) is about.
        self.assertEqual(len(port_lines), len(golden_lines))
        for i, (p, g) in enumerate(zip(port_lines, golden_lines, strict=True)):
            if i == 2:
                continue
            if 4 <= i <= 40:
                p_prefix = p.split(":", 1)[0] + ":"
                g_prefix = g.split(":", 1)[0] + ":"
                self.assertEqual(p_prefix, g_prefix, f"line {i + 1} prefix differs, case {name!r}")
                continue
            self.assertEqual(p, g, f"line {i + 1} differs for case {name!r}")

    def test_one_buffer_3p(self) -> None:
        self._assert_matches("one_buffer_3p")

    def test_two_buffers_offset(self) -> None:
        self._assert_matches("two_buffers_offset")

    def test_negative_inttime(self) -> None:
        self._assert_matches("negative_inttime")

    def test_float_to_int_columns(self) -> None:
        self._assert_matches("float_to_int_columns")

    def test_tiny_inttime(self) -> None:
        """B8, 2026-09-14: GDL's `(e0.5)` on `inttime=1d-120` prints
        `1.00000e-120` -- a three-digit exponent with no width padding, which
        the port's `%02d` minimum-width exponent reproduces."""
        self._assert_matches("tiny_inttime")
        case = _load()[1]["tiny_inttime"]
        golden_path = Path(__file__).resolve().parent / "data" / case["csv_tracked"]
        row = golden_path.read_text().splitlines()[43]  # first data row, after the column header
        inttime_col = [n for n, *_ in pw.PBPPROPS].index("inttime")
        self.assertEqual(row.split(",")[inttime_col], "1.00000e-120")

    def test_csv_only(self) -> None:
        """`csv_only` (2026-09-14): `particlefile:1, ncdfparticlefile:0`
        writes only the CSV, no `.pbp.nc` -- the golden record carries no
        `nc_tracked`, so this case never reaches `TestPbpNcdfAgainstGdl`."""
        _, cases = _load()
        case = cases["csv_only"]
        self.assertNotIn("nc_tracked", case)
        self._assert_matches("csv_only")

    def test_format_probes_recorded_no_hang(self) -> None:
        meta, _ = _load()
        probes = meta["format_probes"]
        self.assertEqual(len(probes), 7)
        for name, verdict in probes.items():
            self.assertTrue(verdict.startswith("ok"), f"{name}: {verdict}")

    # --- Mutations, run and reverted ---

    def test_mutation_header_width_4_fails_against_gdl(self) -> None:
        """Reverting B2's fix (7-char width -> the old 4-char width) must
        disagree with the GDL golden."""
        _, cases = _load()
        case = cases["one_buffer_3p"]
        golden_path = Path(__file__).resolve().parent / "data" / case["csv_tracked"]
        golden_line5 = golden_path.read_text().splitlines()[4]
        wrong_line5 = f"{1:4d}. time: UTC time [seconds]"
        self.assertNotEqual(golden_line5, wrong_line5)

    def test_mutation_int_rounding_would_not_match_gdl_3_5(self) -> None:
        """B3: GDL's (i0) on a FLOAT truncates (measured: 3.5 -> '3'); a
        round()-based port would print '4' and disagree."""
        case = _load()[1]["float_to_int_columns"]
        golden_path = Path(__file__).resolve().parent / "data" / case["csv_tracked"]
        row = golden_path.read_text().splitlines()[43].split(",")
        areafilled_col = [n for n, *_ in pw.PBPPROPS].index("areafilled")
        self.assertEqual(row[areafilled_col], "3")  # truncate(3.5), not round(3.5)==4


# ---------------------------------------------------------------------------
# Round 9: the netCDF side
# ---------------------------------------------------------------------------

#: `op`'s typed record, matching the bank's `_op_block` and the GOLDEN's own
#: measured attribute dtypes -- **not** the plain-Python
#: types a caller would write by hand. `endbins` came back from GDL as an
#: **int16** array (`ENDBINS = array([10, 50, 100, 200, 500], dtype=int16)`,
#: measured this round): the bank's own `_f()` formats `10.0` as `"10"`
#: (`%.9g` drops the trailing `.0`), so IDL parses the literal as INTEGER,
#: not FLOAT -- a bank-formatting artifact, not a SODA-2 fidelity target, but
#: it is what this golden actually contains, so the test matches it rather
#: than the "should be FLOAT" reading the R8B plan guessed at.
def _typed_op(outdir: str) -> dict:
    return {
        "format": "SPEC", "probetype": "2DS", "probeid": "H", "shortname": "2DS",
        "date": "20160906", "starttime": np.float64(0.0), "stoptime": np.float64(4.0),
        "rate": np.float32(1.0), "outdir": outdir, "filetag": "",
        "clusterthresh": np.float32(0.0), "inttime_reject": np.int16(0), "smethod": "diam",
        "apply_psc": np.int16(0), "apply_psc_sizelimit": np.float32(0.0), "water": np.int16(0),
        "endbins": np.array([10, 50, 100, 200, 500], dtype=np.int16),
        "arendbins": np.array([0.0, 0.5, 1.0], dtype=np.float32),
        "eawmethod": "allin", "res": np.float32(10.0),
        "dofreject": np.int16(1), "ncdfparticlefile": np.int16(1), "particlefile": np.int16(1),
    }


@unittest.skipUnless(GOLDEN.exists(), "run gdl_oracle/run_soda2_pbp_writer_bank.py first")
class TestPbpNcdfAgainstGdl(unittest.TestCase):
    """B5, S6-k, S6-o, S6-p against the round-9 netCDF golden."""

    def _build_x(self, particles: list[dict]) -> dict:
        n = len(particles)
        keys = [name for name, *_ in pw.PBPPROPS if name not in ("time", "rejectionflag")]
        x = {k: np.zeros(n, dtype=np.float64) for k in keys}
        for i, p in enumerate(particles):
            full = _default_particle(p)
            for k in keys:
                x[k][i] = full.get(k, 0.0)
        return x

    def _write_port_nc(self, name: str) -> Path:
        meta, cases = _load()
        case = cases[name]
        self.assertTrue(case.get("nc_tracked"), f"{name}: golden has no tracked .nc (HANG/HALTED)")
        pthdat = case.get("pthdat")
        outdir = tempfile.mkdtemp()
        op = _typed_op(outdir.replace("\\", "/") + "/")
        date = {"month": "09", "day": "06", "year": "2016"}
        path = Path(outdir) / "out.pbp.nc"
        ds = pw.open_pbp_ncdf(str(path), op, date, pthdat=pthdat)
        ncdf_offset = 0
        for buf in case["buffers"]:
            x = self._build_x(buf)
            truetime, interarrival = spec_sort_locals(x)
            rejectionflag = np.zeros(len(buf), dtype=np.uint8)
            # dofflag==0, dofreject==1 => code 128 (an uncounted DOF reject; signed int8 on disk),
            # matching `soda2_particlesort.pro`'s own reject-code assembly.
            for i, p in enumerate(buf):
                if int(_default_particle(p).get("dofflag", 1)) == 0 and int(op["dofreject"]) == 1:
                    rejectionflag[i] = 128
            istop = len(buf) - 1
            pw.write_pbp_ncdf_buffer(
                ds, x, istop, truetime, interarrival, rejectionflag, ncdf_offset
            )
            ncdf_offset += istop + 1
        pw.close_pbp_ncdf(ds, pthdat=pthdat)
        return path

    def _compare(self, name: str) -> None:
        port_path = self._write_port_nc(name)
        _meta, cases = _load()
        case = cases[name]
        golden_path = Path(__file__).resolve().parent / "data" / case["nc_tracked"]

        port_ds = netCDF4.Dataset(port_path, "r")
        gold_ds = netCDF4.Dataset(golden_path, "r")
        try:
            self.assertEqual(list(port_ds.variables), list(gold_ds.variables), name)
            for vn in gold_ds.variables:
                pv, gv = port_ds.variables[vn], gold_ds.variables[vn]
                self.assertEqual(pv.dtype, gv.dtype, f"{name}:{vn} dtype")
                # The golden's longnames are the bank's own abbreviated
                # transcriptions, not verbatim IDL text (module docstring
                # above and `run_soda2_pbp_writer_bank.py`'s own docstring);
                # only presence is checked, as for the CSV header prefix.
                self.assertTrue(getattr(gv, "longname", None), f"{name}:{vn} golden longname")
                self.assertTrue(getattr(pv, "longname", None), f"{name}:{vn} port longname")
                self.assertEqual(
                    getattr(pv, "units", None), getattr(gv, "units", None), f"{name}:{vn} units"
                )
                pf, gf = pv.filters() or {}, gv.filters() or {}
                self.assertEqual(bool(pf.get("zlib")), bool(gf.get("zlib")), f"{name}:{vn} zlib")
                # The bank no longer adds its own `/shuffle`, so the golden
                # carries the storage `soda2_process_2d.pro:275-330` requests
                # (shuffle off everywhere); both sides are compared, and the
                # source itself is asserted in
                # `test_soda2_pbp_storage_matches_idl.py`.
                self.assertEqual(
                    bool(pf.get("shuffle")), bool(gf.get("shuffle")), f"{name}:{vn} shuffle"
                )
                self.assertFalse(bool(gf.get("shuffle")), f"{name}:{vn} golden shuffle")
                self.assertEqual(
                    pf.get("complevel"), gf.get("complevel"), f"{name}:{vn} complevel"
                )
                np.testing.assert_array_equal(
                    np.asarray(pv[:]), np.asarray(gv[:]), err_msg=f"{name}:{vn} data"
                )
            for dn in gold_ds.dimensions:
                self.assertEqual(
                    port_ds.dimensions[dn].size, gold_ds.dimensions[dn].size, f"{name}:{dn}"
                )
            # `TimeInterval` is excluded like `DateProcessed`: the bank's
            # `_HEADER_TAIL_TEMPLATE` writes the literal `'x'` for it
            # (`ncdf_attput, ncdf_id, 'TimeInterval', 'x', /global`) as a
            # placeholder, never the real `soda2_process_2d.pro:246-249`
            # computation the port carries out -- comparing it would fail on
            # a difference that is the bank's own simplification, not a port
            # defect (measured this round: port writes the real
            # `'00:00:00-04:00:00'`, golden has `'x'`).
            # `OUTDIR` is excluded too: it is each run's own temp directory
            # path, never equal between the golden run and this test's run.
            _EXCLUDED = ("DateProcessed", "TimeInterval", "OUTDIR",
                         "arrayprobe_engine", "arrayprobe_profile")
            gold_attrs = {a: gold_ds.getncattr(a) for a in gold_ds.ncattrs() if a not in _EXCLUDED}
            port_attrs = {a: port_ds.getncattr(a) for a in port_ds.ncattrs() if a not in _EXCLUDED}
            self.assertEqual(set(port_attrs), set(gold_attrs), name)
            for a in gold_attrs:
                pv2, gv2 = port_attrs[a], gold_attrs[a]
                if isinstance(gv2, np.ndarray):
                    self.assertEqual(
                        str(np.asarray(pv2).dtype), str(gv2.dtype), f"{name}:{a} dtype"
                    )
                    np.testing.assert_array_equal(
                        np.asarray(pv2), gv2, err_msg=f"{name}:{a} value"
                    )
                else:
                    self.assertEqual(type(pv2).__name__, type(gv2).__name__, f"{name}:{a} dtype")
                    self.assertEqual(pv2, gv2, f"{name}:{a} value")
        finally:
            port_ds.close()
            gold_ds.close()

    def test_one_buffer_3p_ncdf(self) -> None:
        self._compare("one_buffer_3p")

    def test_reject_128_ncdf(self) -> None:
        self._compare("reject_128")

    def test_float_to_int_columns_ncdf(self) -> None:
        self._compare("float_to_int_columns")

    def test_tiny_inttime_ncdf(self) -> None:
        """B8's netCDF half: `inttime=1d-120` lands in the float32 `inttime`
        variable as exactly 0.0 (underflow), measured under GDL."""
        self._compare("tiny_inttime")
        case = _load()[1]["tiny_inttime"]
        ds = netCDF4.Dataset(Path(__file__).resolve().parent / "data" / case["nc_tracked"], "r")
        try:
            self.assertEqual(float(ds.variables["inttime"][0]), 0.0)
        finally:
            ds.close()

    def test_pthdat_extrap_ncdf(self) -> None:
        """B6 (`pthdat_extrap`), measured as of Y3/Y3s (2026-09-14):
        the earlier `HANG` was a GDL library-path defect (`INTERPOL` is a
        library `.pro` and this build's `!PATH` carries no library
        directory), fixed in the bank by passing GDL's own `interpol.pro` as
        `extra_files` (`gdl_oracle/probe_pthdat_hang.py`). GDL's `INTERPOL`
        linearly extrapolates `pthdat.time=[1,2]`, `lat=[10,20]`,
        `lon=[100,200]` onto particle times `[0.5, 2.5]` as `lat=[5,25]`,
        `lon=[50,250]` -- confirmed a second time here by reading the golden
        file directly, not only through `_compare`'s generic loop."""
        self._compare("pthdat_extrap")
        case = _load()[1]["pthdat_extrap"]
        ds = netCDF4.Dataset(Path(__file__).resolve().parent / "data" / case["nc_tracked"], "r")
        try:
            np.testing.assert_array_equal(np.asarray(ds.variables["lat"][:]), [5.0, 25.0])
            np.testing.assert_array_equal(np.asarray(ds.variables["lon"][:]), [50.0, 250.0])
        finally:
            ds.close()

    def test_mutation_np_interp_would_clamp_not_extrapolate(self) -> None:
        """Proves the golden discriminates: plain `np.interp` (what the port
        used before Y3s) clamps at the input range instead of extrapolating,
        so it disagrees with GDL's measured `INTERPOL` output."""
        clamped = np.interp([0.5, 2.5], [1.0, 2.0], [10.0, 20.0])
        np.testing.assert_array_equal(clamped, [10.0, 20.0])
        self.assertFalse(np.array_equal(clamped, [5.0, 25.0]))

    # --- Mutations ---

    def test_mutation_lowercase_attr_names_fail_against_gdl(self) -> None:
        """B1: reverting the upper() fix must disagree with the golden's
        upper-case global attribute names. `Source`/`FlightDate`/
        `TimeInterval` are written as string literals, not through the `op`
        tag loop (`:181-184`/`open_pbp_ncdf`'s own four literal lines), so
        only the tag-derived attributes are asserted upper-case here."""
        _, cases = _load()
        case = cases["one_buffer_3p"]
        golden_path = Path(__file__).resolve().parent / "data" / case["nc_tracked"]
        ds = netCDF4.Dataset(golden_path, "r")
        try:
            attrs = {a for a in ds.ncattrs()
                     if a not in ("DateProcessed", "arrayprobe_engine", "arrayprobe_profile")}
        finally:
            ds.close()
        tag_derived = attrs - {"Source", "FlightDate", "TimeInterval"}
        self.assertTrue(all(a == a.upper() for a in tag_derived), tag_derived)
        self.assertIn("RATE", tag_derived)
        self.assertNotIn("rate", attrs)  # the lower-case form the un-fixed port used to write

    def test_mutation_bare_int_would_widen_past_the_golden_int16(self) -> None:
        """B5: a bare Python int attribute widens to int64 under
        `setattr(ds, name, value)`, disagreeing with the golden's int16."""
        outdir = tempfile.mkdtemp()
        op = dict(_typed_op(outdir.replace("\\", "/") + "/"))
        op["dofreject"] = 1  # bare int, not np.int16(1)
        date = {"month": "09", "day": "06", "year": "2016"}
        path = Path(outdir) / "wrong.pbp.nc"
        ds = pw.open_pbp_ncdf(str(path), op, date)
        try:
            dtype = np.asarray(ds.getncattr("DOFREJECT")).dtype
        finally:
            ds.close()
        self.assertNotEqual(str(dtype), "int16")  # bare int -> int64, not the golden's int16


class TestIdlInterpolHelper(unittest.TestCase):
    """`pbp_writer._idl_interpol` in isolation (Y3s) -- no GOLDEN skip,
    since this only exercises the helper, not a GDL fixture. Values pinned
    to the `pthdat_extrap` golden case (`probe_pthdat_hang.py`):
    `x=[1,2]`, `lat=[10,20]` extrapolated at `[0.5, 2.5]` -> `[5, 25]`."""

    def test_extrapolates_below_and_above_range(self) -> None:
        out = pw._idl_interpol([10.0, 20.0], [1.0, 2.0], [0.5, 2.5])
        np.testing.assert_array_equal(out, [5.0, 25.0])

    def test_in_range_point_is_plain_linear_interpolation(self) -> None:
        out = pw._idl_interpol([10.0, 20.0], [1.0, 2.0], [1.5])
        np.testing.assert_array_equal(out, [15.0])

    def test_does_not_clamp_like_np_interp(self) -> None:
        """Discriminating/mutation test: a clamping implementation (plain
        `np.interp`) gives `[10, 20]` for these inputs, not `[5, 25]` --
        this test fails if `_idl_interpol` is replaced by `np.interp`."""
        out = pw._idl_interpol([10.0, 20.0], [1.0, 2.0], [0.5, 2.5])
        self.assertFalse(np.array_equal(out, [10.0, 20.0]))
        clamped = np.interp([0.5, 2.5], [1.0, 2.0], [10.0, 20.0])
        self.assertFalse(np.array_equal(out, clamped))
