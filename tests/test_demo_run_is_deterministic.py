# SPDX-License-Identifier: BSD-3-Clause
"""C9 (Windows half): the same demo flight, processed twice, gives the same data.

Runs ``make_demo_flight`` and ``run_flight``'s four stage functions (the chain
``arrayprobe run`` drives) into two separate temporary folders and compares every
netCDF variable and attribute of the four products pairwise. Two attributes are
allowed to differ and are the only ones: the creation-time stamp (wall clock) and
the attributes that record the output file's own path (which differ because the
two folders do). Everything else must be equal, so a hidden clock, a random draw
or a dict-order dependence in a stage fails here.

Measured 2026-10-10 with ``arrayprobe run`` on the start-here demo: identical
except ``Creation Time`` / ``Creation_Time``, ``Image Source`` and ``Data_Source``
(paths). The Linux half needs CI.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np
from tests._repo import needs_v314_engine  # noqa: E402

_TOOLS = Path(__file__).resolve().parent.parent / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _TOOLS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


make_demo_flight = _load("make_demo_flight")
run_flight = _load("run_flight")

_CREATION = {"Creation Time", "Creation_Time"}


def _norm(value, folder: Path) -> str:
    text = str(value)
    for form in (str(folder), str(folder).replace("\\", "/")):
        text = text.replace(form, "<OUT>")
    return text.replace("\\", "/")


def _run(out: Path) -> list[Path]:
    raw = out / "base160101000000.2DS"
    make_demo_flight.build_demo_flight(raw)
    real_log = run_flight.log
    run_flight.log = lambda *a, **kw: None
    try:
        image = run_flight.stage2(raw, out)
        proc = run_flight.stage3(image, out)
        sd = run_flight.stage4(proc, raw.stem, out)
        combined = run_flight.stage_combine([raw.stem], out)
    finally:
        run_flight.log = real_log
    return [image, proc, sd, combined]


class DemoRunIsDeterministic(unittest.TestCase):
    @needs_v314_engine
    def test_two_runs_agree_in_every_variable_and_attribute(self):
        with tempfile.TemporaryDirectory() as ta, tempfile.TemporaryDirectory() as tb:
            a, b = Path(ta), Path(tb)
            pa, pb = _run(a), _run(b)
            self.assertEqual([p.name for p in pa], [p.name for p in pb])
            for fa, fb in zip(pa, pb, strict=True):
                with netCDF4.Dataset(str(fa)) as x, netCDF4.Dataset(str(fb)) as y:
                    for d in (x, y):
                        d.set_auto_mask(False)
                    ga = {k: _norm(x.getncattr(k), a) for k in x.ncattrs()
                          if k not in _CREATION}
                    gb = {k: _norm(y.getncattr(k), b) for k in y.ncattrs()
                          if k not in _CREATION}
                    self.assertEqual(ga, gb, fa.name)
                    self.assertEqual(set(x.variables), set(y.variables), fa.name)
                    for k in x.variables:
                        va, vb = x[k][:], y[k][:]
                        self.assertEqual(va.shape, vb.shape, (fa.name, k))
                        self.assertTrue(np.array_equal(va, vb, equal_nan=va.dtype.kind == "f"),
                                        (fa.name, k))
                        aa = {n: _norm(x[k].getncattr(n), a) for n in x[k].ncattrs()}
                        ab = {n: _norm(y[k].getncattr(n), b) for n in y[k].ncattrs()}
                        self.assertEqual(aa, ab, (fa.name, k))


if __name__ == "__main__":
    unittest.main()
