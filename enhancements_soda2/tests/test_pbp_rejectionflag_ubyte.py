# SPDX-License-Identifier: BSD-3-Clause
"""S6-k (``soda2_process_2d.pro:236``/``:277``'s signed
``rejectionflag``) -- ``pbp_rejectionflag_ubyte.corrected_open_pbp_ncdf``.

``_make_x``/``_write`` are duplicated from ``test_soda2_pbp_writer.py``
rather than imported across the package boundary (the stage 2/3
convention).
"""
from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import contextmanager

import numpy as np
from arrayprobe_soda2 import pbp_writer as pw

from arrayprobe_soda2_enhancements.pbp_rejectionflag_ubyte import (
    corrected_open_pbp_ncdf,
)
from arrayprobe_soda2_enhancements.registry import PROTECTIVE, REGISTRY, resolve


def _make_x(n: int) -> dict:
    return {
        name: np.zeros(n, dtype=np.float64)
        for name, *_ in pw.PBPPROPS
        if name not in ("time", "rejectionflag")
    }


@contextmanager
def _written(opener, x, istop, truetime, interarrival, rejectionflag):
    netCDF4 = __import__("netCDF4")
    fd, path = tempfile.mkstemp(suffix=".pbp.nc")
    os.close(fd)
    os.remove(path)
    op = {"outdir": tempfile.gettempdir() + os.sep, "date": "09062016",
          "starttime": 61.0, "stoptime": 120.0, "shortname": "t",
          "particlefile": 0, "ncdfparticlefile": 1, "filetag": ""}
    date = {"month": "09", "day": "06", "year": "2016"}
    ds = opener(path, op, date)
    pw.write_pbp_ncdf_buffer(ds, x, istop, truetime, interarrival, rejectionflag, 0)
    pw.close_pbp_ncdf(ds)
    ds2 = netCDF4.Dataset(path)
    try:
        yield ds2
    finally:
        ds2.close()
        os.remove(path)


class Equivalence(unittest.TestCase):
    """A rejectionflag value that fits the signed range (bit 128 not
    set) is written and read back identically under both the port's
    own ``i1`` declaration and the correction's ``u1``."""

    def test_matches_port_when_bit_128_is_not_set(self):
        n = 1
        x = _make_x(n)
        truetime, interarrival, rf = (np.array([1.0]), np.array([0.0]),
                                       np.array([7], dtype=np.uint8))

        with _written(pw.open_pbp_ncdf, x, 0, truetime, interarrival, rf) as ds:
            port_value = int(ds.variables["rejectionflag"][0])
            port_dtype = ds.variables["diam"].dtype.name  # sanity: other vars unaffected

        with _written(corrected_open_pbp_ncdf, x, 0, truetime, interarrival, rf) as ds:
            fixed_value = int(ds.variables["rejectionflag"][0])
            fixed_dtype = ds.variables["diam"].dtype.name

        self.assertEqual(fixed_value, port_value)
        self.assertEqual(fixed_dtype, port_dtype)

    def test_every_header_attribute_and_other_type_matches_the_port(self):
        """The module duplicates ``open_pbp_ncdf``, so a later fix to the port's header
        does not reach it unless a test compares the two whole. Found 2026-09-15 on a
        real 2D-S run: after the port's ``TimeInterval`` fix (``8d4a8db``) this copy
        still wrote ``SS:MM:HH`` -- ``00:54:06-00:57:06`` for 06:54:00-06:57:00. The
        fixture's ``starttime`` 61 s (``00:01:01``) reads differently in the two orders."""
        x = _make_x(1)
        args = (np.array([1.0]), np.array([0.0]), np.array([7], dtype=np.uint8))

        def header(ds):
            attrs = {k: str(ds.getncattr(k)) for k in ds.ncattrs() if k != "DateProcessed"}
            types = {k: v.dtype.name for k, v in ds.variables.items() if k != "rejectionflag"}
            return attrs, types

        with _written(pw.open_pbp_ncdf, x, 0, *args) as ds:
            port = header(ds)
        with _written(corrected_open_pbp_ncdf, x, 0, *args) as ds:
            fixed = header(ds)
        self.assertEqual(port[0]["TimeInterval"], "00:01:01-00:02:00")
        self.assertEqual(fixed, port)


class KeepsThePortsSignature(unittest.TestCase):
    """``soda2_process_2d`` passes ``stamp_profile=`` to whichever ``open_pbp_ncdf`` is bound,
    so the drop-in must accept it and write the same in-file
    provenance the port does; a drop-in whose signature drifts fails on its first call."""

    def test_stamp_profile_is_accepted_and_written_like_the_port(self):
        import inspect
        self.assertIn("stamp_profile", inspect.signature(corrected_open_pbp_ncdf).parameters)
        netCDF4 = __import__("netCDF4")
        op = {"starttime": 61.0, "stoptime": 120.0, "ncdfparticlefile": 1}
        date = {"month": "09", "day": "06", "year": "2016"}
        with tempfile.TemporaryDirectory() as tmp:
            got = {}
            for label, opener in (("port", pw.open_pbp_ncdf), ("fixed", corrected_open_pbp_ncdf)):
                path = os.path.join(tmp, f"{label}.pbp.nc")
                opener(path, op, date, stamp_profile="config:ena.toml").close()
                with netCDF4.Dataset(path) as ds:
                    got[label] = (ds.getncattr("arrayprobe_engine"),
                                  ds.getncattr("arrayprobe_profile"))
        self.assertEqual(got["fixed"], ("soda2", "config:ena.toml"))
        self.assertEqual(got["fixed"], got["port"])


class ABConsequence(unittest.TestCase):
    """Bit 128 set: the port's own signed byte reads back -128; the
    correction's unsigned byte reads back 128 -- the same
    ``test_line_236_rejectionflag_byte_is_signed`` construction the
    port's own test uses."""

    def test_bit_128_reads_back_positive_not_negative(self):
        n = 1
        x = _make_x(n)
        truetime, interarrival, rf = (np.array([1.0]), np.array([0.0]),
                                       np.array([128], dtype=np.uint8))

        with _written(pw.open_pbp_ncdf, x, 0, truetime, interarrival, rf) as ds:
            self.assertEqual(ds.variables["rejectionflag"].dtype.name, "int8")
            self.assertEqual(int(ds.variables["rejectionflag"][0]), -128,
                              "the port's own S6-k value")

        with _written(corrected_open_pbp_ncdf, x, 0, truetime, interarrival, rf) as ds:
            self.assertEqual(ds.variables["rejectionflag"].dtype.name, "uint8")
            self.assertEqual(int(ds.variables["rejectionflag"][0]), 128)


class SwitchStates(unittest.TestCase):
    def test_registered_default_off_a14(self):
        self.assertIn("pbp_rejectionflag_ubyte", REGISTRY)
        spec = REGISTRY["pbp_rejectionflag_ubyte"]
        self.assertFalse(spec.default_on)
        self.assertEqual(spec.finding, "S6-k")
        self.assertEqual(spec.reachability, "live")

    def test_resolve_on_through_the_protective_set_false_when_opted_out(self):
        self.assertFalse(resolve({})["pbp_rejectionflag_ubyte"])
        self.assertTrue(resolve({}, protective=PROTECTIVE)["pbp_rejectionflag_ubyte"])
        self.assertFalse(
            resolve({"pbp_rejectionflag_ubyte": False}, protective=PROTECTIVE)["pbp_rejectionflag_ubyte"])
        self.assertFalse(resolve({"pbp_rejectionflag_ubyte": False})["pbp_rejectionflag_ubyte"])


if __name__ == "__main__":
    unittest.main()
