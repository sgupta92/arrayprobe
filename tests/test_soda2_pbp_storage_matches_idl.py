# SPDX-License-Identifier: BSD-3-Clause
"""The port's ``.pbp.nc`` storage settings are what IDL REQUESTS
(``soda2_process_2d.pro:240-333``), read off the vendored source rather than
off a GDL golden: the driver golden was written through
``gdl_oracle/shims/soda2_process_2d.pro``, which drops ``CHUNK=`` at ``:303``
(GDL 1.1.2 rejects it), so its chunk shapes are GDL's, not IDL's.

Two sides from two places: the expected settings are parsed from every
``ncdf_vardef`` call in the IDL source; the measured settings are the port's
own file's ``filters()`` / ``chunking()``.

- ``GZIP=``: 5 on every 1-D variable (``:275-279``, ``:290-299``,
  ``:311-326``), 8 on ``image`` (``:303``).
- ``/SHUFFLE``: passed by no call, so off everywhere. netCDF4-python turns it
  on by default for ``zlib=True``; the port pins it off.
- ``CHUNK=``: only ``image``, ``[op.numdiodes, 1024]`` (column-major), so the
  port's slice-first ``(Slice, Diode)`` variable is chunked ``[1024, numdiodes]``.
"""
from __future__ import annotations

import os
import re
import tempfile
import unittest

from tests import _upstream  # noqa: E402
from tests._repo import repo_only

from arrayprobe_soda2 import pbp_writer as pw

IDL_SOURCE = (
    _upstream.source("soda2") / "soda2_process_2d.pro"
)
_VARDEF = re.compile(r"ncdf_vardef\((.*)\)", re.IGNORECASE)


def setUpModule():
    # Raised here rather than at import: an import-time SkipTest crashes
    # ``python -m unittest tests.<module>``, where ``discover`` reports it as a skip.
    _upstream.require("soda2")


def _idl_vardef_calls() -> list[tuple[int, str]]:
    """(line number, argument text) of every ``ncdf_vardef`` in the pbp setup."""
    lines = IDL_SOURCE.read_text(encoding="utf-8", errors="replace").splitlines()
    out = []
    for i, line in enumerate(lines, start=1):
        if 240 <= i <= 333:
            m = _VARDEF.search(line.split(";")[0])
            if m:
                out.append((i, m.group(1)))
    return out


def _idl_requests() -> dict[str, dict]:
    """Variable name -> {'gzip': int, 'shuffle': bool, 'chunk': list | None}."""
    req: dict[str, dict] = {}
    for lineno, args in _idl_vardef_calls():
        gz = re.search(r"gzip\s*=\s*(\d+)", args, re.IGNORECASE)
        chunk = re.search(r"chunk\s*=\s*\[([^\]]*)\]", args, re.IGNORECASE)
        entry = {
            "line": lineno,
            "gzip": int(gz.group(1)) if gz else None,
            "shuffle": re.search(r"/shuffle|shuffle\s*=", args, re.IGNORECASE) is not None,
            "chunk": [c.strip() for c in chunk.group(1).split(",")] if chunk else None,
        }
        name = re.match(r"\s*ncdf_id\s*,\s*'([^']+)'", args)
        if name:
            req[name.group(1)] = entry
        else:  # :275-279, the pbpprops loop: `tagnames[i]`
            assert "tagnames[i]" in args, (lineno, args)
            for pname, *_ in pw.PBPPROPS:
                prev = req.setdefault(pname, entry)
                assert (prev["gzip"], prev["shuffle"]) == (entry["gzip"], entry["shuffle"])
    return req


@repo_only
class TestPbpStorageMatchesIdlRequest(unittest.TestCase):
    NUMDIODES = 64

    @classmethod
    def setUpClass(cls) -> None:
        import netCDF4

        cls.requests = _idl_requests()
        cls._tmp = tempfile.TemporaryDirectory()
        path = os.path.join(cls._tmp.name, "layout.pbp.nc")
        op = {"outdir": cls._tmp.name + os.sep, "date": "09062016",
              "starttime": 61.0, "stoptime": 120.0, "ncdfparticlefile": 2,
              "numdiodes": cls.NUMDIODES}
        date = {"month": "09", "day": "06", "year": "2016"}
        pthdat = {"time": [61.0, 62.0], "lat": [1.0, 2.0], "lon": [3.0, 4.0],
                  "galt": [5.0, 6.0], "t": [7.0, 8.0]}
        pw.open_pbp_ncdf(path, op, date, pthdat).close()
        cls.ds = netCDF4.Dataset(path)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.ds.close()
        cls._tmp.cleanup()

    def test_the_idl_source_was_parsed(self) -> None:
        # 5 type branches of the loop + starty/stopy/startx/stopx + image + lat/lon/alt/t.
        self.assertEqual(len(_idl_vardef_calls()), 14)
        self.assertEqual(self.requests["image"]["line"], 303)
        self.assertEqual(self.requests["image"]["chunk"], ["op.numdiodes", "1024"])

    def test_idl_requests_no_shuffle_anywhere(self) -> None:
        self.assertFalse(any(r["shuffle"] for r in self.requests.values()))

    def test_every_variable_is_one_idl_defines(self) -> None:
        self.assertEqual(set(self.ds.variables), set(self.requests))

    def test_filters_are_what_idl_requests(self) -> None:
        for name, req in self.requests.items():
            f = self.ds.variables[name].filters()
            with self.subTest(var=name, idl_line=req["line"]):
                self.assertTrue(f["zlib"])
                self.assertEqual(f["complevel"], req["gzip"])
                self.assertEqual(bool(f["shuffle"]), req["shuffle"])

    def test_image_chunk_is_idls_chunk_reversed_to_slice_first(self) -> None:
        # `chunk=[op.numdiodes, 1024]` on IDL's column-major [Diode, Slice].
        self.assertEqual(self.ds.variables["image"].dimensions, ("Slice", "Diode"))
        self.assertEqual(self.ds.variables["image"].chunking(), [1024, self.NUMDIODES])


if __name__ == "__main__":
    unittest.main()
