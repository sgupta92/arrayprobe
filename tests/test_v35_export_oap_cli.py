# SPDX-License-Identifier: BSD-3-Clause
"""The ``python -m arrayprobe_uiops.export_oap`` entry point, on a synthetic v3.5 S2 decode."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np

from arrayprobe_uiops.export_oap import BOUNDARY_WORD, main
from arrayprobe_uiops.oap_read import read_oap_2ds


def _pack(bits: np.ndarray) -> np.ndarray:
    return np.packbits(bits.astype(np.uint8), bitorder="big").view(">u2").astype(np.int64)


def _write_decode(path: Path, records: list[list[tuple[np.ndarray, int]]],
                  orientation: str = "Horizontal", software: str = "UIOOPS_v3.5") -> None:
    """A minimal file with the v3.5 SPEC decoder's layout: data (time, 1700, 8) and the time
    variables, one canvas per record."""
    with netCDF4.Dataset(path, "w", format="NETCDF4") as ds:
        ds.setncattr("Software", software)
        ds.setncattr("Probe Channel_Orientation", orientation)
        ds.createDimension("time", None)
        ds.createDimension("ImgBlocklen", 1700)
        ds.createDimension("ImgRowlen", 8)
        data = ds.createVariable("data", "i4", ("time", "ImgBlocklen", "ImgRowlen"))
        for name, typ in (("year", "i2"), ("month", "i1"), ("day", "i1"), ("hour", "i1"),
                          ("minute", "i1"), ("second", "i1"), ("millisec", "i2")):
            ds.createVariable(name, typ, ("time",))
        ds.createVariable("tas", "f8", ("time",))
        for t, parts in enumerate(records):
            cols = []
            for img, timing in parts:
                cols += [_pack(row) for row in img]
                cols.append(np.full(8, BOUNDARY_WORD, dtype=np.int64))
                header = np.zeros(8, dtype=np.int64)
                header[6], header[7] = timing >> 16, timing & 0xFFFF
                cols.append(header)
            canvas = np.zeros((8, 1700), dtype=np.int64)
            canvas[:, : len(cols)] = np.column_stack(cols)
            data[t] = np.ascontiguousarray(canvas.T, dtype=np.int32)
            for name, value in (("year", 2016), ("month", 9), ("day", 6), ("hour", 12),
                                ("minute", 34), ("second", 50 + t), ("millisec", 100 * t)):
                ds.variables[name][t] = value
            ds.variables["tas"][t] = 151.6


class TestExportOapEntryPoint(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        rng = np.random.default_rng(5)
        self.records = [
            [((rng.random((n, 128)) < 0.3).astype(np.uint8), timing)
             for n, timing in zip(sizes, timings, strict=True)]
            for sizes, timings in (((2, 4), (10, 0x00020003)), ((1, 6, 3), (77, 0xFFFFFFFF, 5)))
        ]

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, *argv: str) -> int:
        with contextlib.redirect_stdout(io.StringIO()):
            return main(list(argv))

    def test_round_trip_through_the_reader(self) -> None:
        dec = self.dir / "flight.H.nc"
        _write_decode(dec, self.records)
        out = self.dir / "flight.2d"
        self.assertEqual(self._run(str(dec), str(out), "--probe", "2DS",
                                   "--timing-convention", "own"), 0)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["flight.2d", "flight.H.nc"])
        _, _, got = read_oap_2ds(out, probe_id=b"SH")
        want = [p for rec in self.records for p in rec]
        self.assertEqual(len(got), len(want))
        for (img, timing), g in zip(want, got, strict=True):
            self.assertTrue(np.array_equal(g.shaded, img))
            self.assertEqual(g.timing, timing)

    def test_vertical_channel_writes_sv(self) -> None:
        dec = self.dir / "flight.V.nc"
        _write_decode(dec, self.records, orientation="Vertical")
        out = self.dir / "v.2d"
        self._run(str(dec), str(out), "--probe", "2DS")
        _, _, got = read_oap_2ds(out, probe_id=b"SV")
        self.assertEqual(len(got), 5)

    def test_non_2ds_refused(self) -> None:
        dec = self.dir / "flight.H.nc"
        _write_decode(dec, self.records)
        for argv in ((str(dec), str(self.dir / "a.2d"), "--probe", "HVPS"),
                     (str(dec), str(self.dir / "b.2d"))):
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                main(list(argv))
        hv = self.dir / "base.HVPS.H.nc"
        _write_decode(hv, self.records)
        err = io.StringIO()
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(err):
            main([str(hv), str(self.dir / "c.2d"), "--probe", "2DS"])
        self.assertIn("2D-S decodes only", err.getvalue())
        self.assertFalse(any(p.suffix == ".2d" for p in self.dir.iterdir()))

    def test_not_a_decode_and_existing_output_refused(self) -> None:
        bad = self.dir / "x.nc"
        with netCDF4.Dataset(bad, "w") as ds:
            ds.setncattr("Software", "other")
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            main([str(bad), str(self.dir / "x.2d"), "--probe", "2DS"])
        dec = self.dir / "flight.H.nc"
        _write_decode(dec, self.records)
        out = self.dir / "exists.2d"
        out.write_bytes(b"keep")
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            main([str(dec), str(out), "--probe", "2DS"])
        self.assertEqual(out.read_bytes(), b"keep")


if __name__ == "__main__":
    unittest.main()
