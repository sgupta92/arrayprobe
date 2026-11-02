# SPDX-License-Identifier: BSD-3-Clause
"""S6-i (``soda2_particlesort.pro:198`` vs ``:279-298``'s ``inttime``
disagreement) -- ``pbp_inttime_consistent.corrected_write_pbp_csv_buffer``.

``_make_x``/``_write`` are duplicated from ``test_soda2_pbp_writer.py``
rather than imported across the package boundary (the stage 2/3
convention).
"""
from __future__ import annotations

import os
import tempfile
import unittest

import numpy as np
from arrayprobe_soda2 import pbp_writer as pw

from arrayprobe_soda2_enhancements.pbp_inttime_consistent import (
    corrected_write_pbp_csv_buffer,
)
from arrayprobe_soda2_enhancements.registry import REGISTRY, resolve


def _make_x(n: int) -> dict:
    return {
        name: np.zeros(n, dtype=np.float64)
        for name, *_ in pw.PBPPROPS
        if name not in ("time", "rejectionflag")
    }


def _write(writer, x, istop, truetime, rejectionflag, interarrival=None) -> list[str]:
    fd, path = tempfile.mkstemp(suffix=".pbp.csv")
    os.close(fd)
    op = {"outdir": tempfile.gettempdir() + os.sep, "date": "09062016",
          "starttime": 61.0, "stoptime": 120.0}
    date = {"month": "09", "day": "06", "year": "2016"}
    f = pw.open_pbp_csv(path, op, date)
    if interarrival is None:
        writer(f, x, istop, truetime, rejectionflag)
    else:
        writer(f, x, istop, truetime, rejectionflag, interarrival)
    f.close()
    with open(path) as fh:
        lines = fh.readlines()
    os.remove(path)
    return lines


_INTTIME_COL = [n for n, *_ in pw.PBPPROPS].index("inttime")


class Equivalence(unittest.TestCase):
    """A non-negative inttime: interarrival == x['inttime'] (MAX(x,0)
    changes nothing), so the corrected CSV must be byte-identical to
    the port's own."""

    def test_matches_port_for_nonnegative_inttime(self):
        n = 1
        x = _make_x(n)
        x["inttime"][0] = 0.25
        truetime = np.array([42.5])
        rejectionflag = np.array([7], dtype=np.uint8)

        port_lines = _write(pw.write_pbp_csv_buffer, x, 0, truetime, rejectionflag)
        interarrival = np.maximum(x["inttime"], 0.0)
        fixed_lines = _write(corrected_write_pbp_csv_buffer, x, 0, truetime,
                              rejectionflag, interarrival)

        self.assertEqual(port_lines, fixed_lines)


class ABConsequence(unittest.TestCase):
    """A negative inttime: the port's own CSV prints the raw negative
    tag; the correction prints the clamped interarrival value (0),
    matching what the netCDF writer already writes for the same
    particle (S6-i's own point)."""

    def test_negative_inttime_prints_the_clamped_value(self):
        n = 1
        x = _make_x(n)
        x["inttime"][0] = -0.5
        truetime = np.array([1.0])
        rejectionflag = np.array([0], dtype=np.uint8)

        port_lines = _write(pw.write_pbp_csv_buffer, x, 0, truetime, rejectionflag)
        port_row = port_lines[-1].strip().split(",")
        self.assertEqual(port_row[_INTTIME_COL], "-5.00000e-01",
                          "the port's own S6-i value")

        interarrival = np.maximum(x["inttime"], 0.0)
        self.assertEqual(float(interarrival[0]), 0.0)
        fixed_lines = _write(corrected_write_pbp_csv_buffer, x, 0, truetime,
                              rejectionflag, interarrival)
        fixed_row = fixed_lines[-1].strip().split(",")
        self.assertEqual(fixed_row[_INTTIME_COL], "0.00000e+00")

        # Every other column is unaffected.
        self.assertEqual(port_row[:_INTTIME_COL], fixed_row[:_INTTIME_COL])
        self.assertEqual(port_row[_INTTIME_COL + 1:], fixed_row[_INTTIME_COL + 1:])


class SwitchStates(unittest.TestCase):
    def test_registered_default_off_a14(self):
        self.assertIn("pbp_inttime_consistent", REGISTRY)
        spec = REGISTRY["pbp_inttime_consistent"]
        self.assertFalse(spec.default_on)
        self.assertEqual(spec.finding, "S6-i")
        self.assertEqual(spec.reachability, "live")

    def test_resolve_false_by_default_true_when_opted_in(self):
        self.assertFalse(resolve({})["pbp_inttime_consistent"])
        self.assertTrue(resolve({"pbp_inttime_consistent": True})["pbp_inttime_consistent"])
        self.assertFalse(resolve({"pbp_inttime_consistent": False})["pbp_inttime_consistent"])


if __name__ == "__main__":
    unittest.main()
