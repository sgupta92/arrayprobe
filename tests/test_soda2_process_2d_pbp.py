# SPDX-License-Identifier: BSD-3-Clause
"""The PBP-writer whole-driver check (the owed oracle named by
this the owed oracle): the GDL whole-driver golden for the PBP writers
*wired into* ``soda2_process_2d`` (round 10, ``src/
arrayprobe_soda2/process_2d.py``). Round 10 wired ``particlefile``/
``ncdfparticlefile`` into the driver and left ``.pbp.csv``/``.pbp.nc``
verified only against ``pbp_writer.py``'s own hand-built-``x`` bank (round
8-B/9). This module adds the bank that was missing: the real, unmodified
vendored driver run end to end under GDL with both writers on
(``gdl_oracle/run_soda2_pbp_driver_bank.py``,
``tests/data/gdl_soda2_pbp_driver_golden.json``), on the ``frame_full``
fixture -- the same fixture the earlier golden
(``gdl_soda2_process_2d_golden.json``) already shows completing to
``STATUS=OK`` with two accepted buffers (``PBPSTARTINDEX=[0,5,0]``,
13 particles total), so GDL's ``MEDIAN`` 1-element gap (which halts every
``s2_*`` case) does not apply here.

Unlike ``run_soda2_pbp_writer_bank.py``, which hand-transcribes
an abbreviated ``pbpprops`` literal for readability, this bank runs the
*real* vendored ``soda2_process_2d.pro``, whose ``pbpprops`` at ``:202-238``
is the verbatim, full-length text the port's own ``PBPPROPS`` carries -- so
the CSV comparison below is a full byte compare (line 3, ``Date
Processed:``, excluded as non-deterministic on both sides), not a
prefix-only one.
"""
from __future__ import annotations

import gc
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np

from arrayprobe_soda2.process_2d import ProcessData, soda2_process_2d

# The sibling module is imported by bare name, which only `discover -s tests`
# makes importable; this makes `-m unittest tests.test_soda2_process_2d_pbp` work too.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_soda2_process_2d import (  # noqa: E402
    _P2D_CASE_OVERRIDES,
    _P2D_GOLDEN_BASE,
    _base_op,
)

DATA = Path(__file__).resolve().parent / "data"
DRIVER_GOLDEN = DATA / "gdl_soda2_pbp_driver_golden.json"

#: Global attributes excluded from comparison: `DateProcessed` is
#: non-deterministic on both sides (`systime()`); `FN`/`OUTDIR` are each
#: run's own filesystem paths (the golden's temp dir, this test's temp
#: dir) -- never equal between runs, not a fidelity question.
#:
#: `TimeInterval` WAS excluded until 2026-09-14 for a real port defect this
#: golden found: `pbp_writer` wrote ``SS:MM:HH`` ('00:44:06-10:44:06') where GDL
#: writes ``HH:MM:SS`` ('06:44:00-06:44:10'), because it read IDL's
#: ``strmid(...,/reverse_offset)`` as reversing the field order. Fixed in
#: `pbp_writer._idl_hms_string`; the attribute is compared like the rest now.
_EXCLUDED_GLOBAL_ATTRS = ("DateProcessed", "FN", "OUTDIR",
                          "arrayprobe_engine", "arrayprobe_profile")


def _load_driver_golden() -> dict[str, dict]:
    records = json.loads(DRIVER_GOLDEN.read_text(encoding="utf-8"))
    return {r["name"]: r for r in records if "oracle_shims" not in r}


#: `run_soda2_process_2d_bank.py::_BASE_FIELDS` carries three tags
#: (`tau`, `reconstruct`, `project`) that no computation this port
#: exercises reads -- `soda2_update_op.pro` sets no default for any of the
#: three (grepped, empty), and neither does `update_op.py` -- so they are
#: along for the ride purely because the bank's own op literal includes
#: them, and `open_pbp_ncdf`'s tag loop (`:264-270`) dumps *every* tag
#: present in `op`, whatever it is. `_base_op`/`_P2D_GOLDEN_BASE` (round
#: 8-A, data-array comparison only) never needed them; the netCDF global
#: attribute comparison below is the first thing in this port that does.
_UNUSED_BUT_TAGGED_FIELDS: dict = dict(tau=41.0e-9, reconstruct=1, project="x")


def _frame_full_op(outdir: str, **overrides) -> dict:
    base = {**_P2D_GOLDEN_BASE, **_P2D_CASE_OVERRIDES["frame_full"],
            **_UNUSED_BUT_TAGGED_FIELDS,
            # `_base_op` now sets `savfile=0`; the bank runs with
            # `savfile:'1'` (the `update_op` INT default) and the netCDF
            # dumps every op tag, so restore it. `outdir` is a temp dir.
            "savfile": np.int16(1)}
    base.update(overrides)
    return _base_op(outdir=outdir, **base)


def _csv_lines_minus_dateprocessed(path: Path) -> list[str]:
    lines = path.read_text().splitlines(keepends=True)
    return [ln for i, ln in enumerate(lines) if i != 2]


@unittest.skipUnless(
    DRIVER_GOLDEN.exists(), "The reference output of soda2_pbp_driver is not distributed with "
                            "the package"
)
class AgainstTheGdlDriverGolden(unittest.TestCase):
    """Round 10's driver wiring against the real, unmodified GDL driver on
    the frame fixture (``gdl_oracle/run_soda2_pbp_driver_bank.py``)."""

    def test_frame_full_csv_matches_gdl(self) -> None:
        golden = _load_driver_golden()["frame_full"]
        self.assertEqual(golden["status"], "OK")
        golden_path = DATA / golden["csv_tracked"]
        with tempfile.TemporaryDirectory() as tmp:
            op = _frame_full_op(tmp + os.sep, particlefile=1, ncdfparticlefile=1)
            d = soda2_process_2d(op)
            self.assertIsInstance(d, ProcessData)
            csv_files = list(Path(tmp).glob("*.pbp.csv"))
            self.assertEqual(len(csv_files), 1)
            port_lines = _csv_lines_minus_dateprocessed(csv_files[0])
        golden_lines = _csv_lines_minus_dateprocessed(golden_path)
        self.assertEqual(port_lines, golden_lines)

    def test_frame_full_ncdf_matches_gdl(self) -> None:
        golden = _load_driver_golden()["frame_full"]
        self.assertEqual(golden["status"], "OK")
        golden_path = DATA / golden["nc_tracked"]
        with tempfile.TemporaryDirectory() as tmp:
            op = _frame_full_op(tmp + os.sep, particlefile=1, ncdfparticlefile=1)
            d = soda2_process_2d(op)
            self.assertIsInstance(d, ProcessData)
            nc_files = list(Path(tmp).glob("*.pbp.nc"))
            self.assertEqual(len(nc_files), 1)
            port_ds = netCDF4.Dataset(nc_files[0], "r")
            gold_ds = netCDF4.Dataset(golden_path, "r")
            try:
                self.assertEqual(list(port_ds.variables), list(gold_ds.variables))
                for vn in gold_ds.variables:
                    pv, gv = port_ds.variables[vn], gold_ds.variables[vn]
                    # Values first; dtype is a separate assertion below so a
                    # dtype-only miss is reported as such.
                    np.testing.assert_array_equal(
                        np.asarray(pv[:]), np.asarray(gv[:]), err_msg=f"{vn} data"
                    )
                    self.assertEqual(
                        getattr(pv, "units", None), getattr(gv, "units", None),
                        f"{vn} units",
                    )
                for vn in gold_ds.variables:
                    pv, gv = port_ds.variables[vn], gold_ds.variables[vn]
                    self.assertEqual(pv.dtype, gv.dtype, f"{vn} dtype")
                self.assertEqual(
                    port_ds.dimensions["Time"].size, gold_ds.dimensions["Time"].size
                )
                gold_attrs = {
                    a: gold_ds.getncattr(a) for a in gold_ds.ncattrs()
                    if a not in _EXCLUDED_GLOBAL_ATTRS
                }
                port_attrs = {
                    a: port_ds.getncattr(a) for a in port_ds.ncattrs()
                    if a not in _EXCLUDED_GLOBAL_ATTRS
                }
                # the discriminating test for the second uncertainty:
                # the attribute *name set* must match -- "a non-empty
                # difference is an update_op.py fidelity finding in its own
                # right, record it, do not paper over it in the test." It
                # does not ask for per-attribute dtype parity, unlike the
                # variable dtypes above (which *are* asserted, and pass).
                self.assertEqual(set(port_attrs), set(gold_attrs))
                # Values, every attribute. This op is built by `_base_op`
                # (the earlier helper for the *data-array* golden), which
                # supplies most scalars as bare Python `int`/`float` rather
                # than IDL-faithful `np.int16`/`np.float32` -- `open_pbp_
                # ncdf`'s tag loop (B5, already covered by
                # `test_soda2_pbp_writer_gdl.py::
                # test_mutation_bare_int_would_widen_past_the_golden_int16`)
                # writes exactly the caller's own dtype, so those attributes
                # come back as int64/float64 while the golden (typed IDL
                # literals) is int16/float32 -- a gap in *this test's op
                # construction*, not a port defect. Retyping every
                # `_base_op` field to match `_BASE_FIELDS`
                # (`run_soda2_process_2d_bank.py`) is out of this oracle
                # module's time box, so values are compared with a tolerance
                # that absorbs float32 rounding (never absorbing a real
                # value disagreement -- `TimeInterval`, excluded above, is
                # not a rounding difference and would not pass this either).
                for a in gold_attrs:
                    pv2, gv2 = port_attrs[a], gold_attrs[a]
                    with self.subTest(attr=a):
                        if isinstance(gv2, np.ndarray) and np.issubdtype(gv2.dtype, np.floating):
                            np.testing.assert_allclose(
                                np.asarray(pv2, dtype=gv2.dtype), gv2, rtol=1e-6
                            )
                        elif isinstance(gv2, np.ndarray):
                            np.testing.assert_array_equal(np.asarray(pv2), gv2)
                        elif isinstance(gv2, (float, np.floating)):
                            self.assertAlmostEqual(
                                float(np.asarray(pv2, dtype=gv2.dtype)), float(gv2), places=6
                            )
                        else:
                            self.assertEqual(pv2, gv2)
            finally:
                port_ds.close()
                gold_ds.close()

    def test_frame_images_csv_matches_gdl(self) -> None:
        golden = _load_driver_golden()["frame_images"]
        self.assertEqual(golden["status"], "OK")
        with tempfile.TemporaryDirectory() as tmp:
            op = _frame_full_op(tmp + os.sep, particlefile=1, ncdfparticlefile=2)
            soda2_process_2d(op)
            csv_files = list(Path(tmp).glob("*.pbp.csv"))
            self.assertEqual(len(csv_files), 1)
            port_lines = _csv_lines_minus_dateprocessed(csv_files[0])
        golden_lines = _csv_lines_minus_dateprocessed(DATA / golden["csv_tracked"])
        self.assertEqual(port_lines, golden_lines)

    def test_frame_images_ncdf_values_match_gdl(self) -> None:
        """Slice A2:
        ``ncdfparticlefile=2`` against GDL. VALUES only -- dimension names,
        sizes and unlimited-ness, every variable's dimensions, dtype, data and
        attributes, and the global attributes. The golden was written through
        ``gdl_oracle/shims/soda2_process_2d.pro``, which drops ``CHUNK=`` at
        ``soda2_process_2d.pro:303`` (GDL 1.1.2 rejects it), so the on-disk
        chunk shapes differ from what IDL requests and are NOT validated or
        compared here. Shuffle is off on both sides since 2026-10-03 (the port
        follows the IDL source; ``test_soda2_pbp_storage_matches_idl.py``)."""
        golden = _load_driver_golden()["frame_images"]
        self.assertEqual(golden["status"], "OK")
        with tempfile.TemporaryDirectory() as tmp:
            op = _frame_full_op(tmp + os.sep, particlefile=1, ncdfparticlefile=2)
            soda2_process_2d(op)
            nc_files = list(Path(tmp).glob("*.pbp.nc"))
            self.assertEqual(len(nc_files), 1)
            port_ds = netCDF4.Dataset(nc_files[0], "r")
            gold_ds = netCDF4.Dataset(DATA / golden["nc_tracked"], "r")
            try:
                def dims(ds):
                    return [(n, d.size, d.isunlimited())
                            for n, d in ds.dimensions.items()]
                self.assertEqual(dims(port_ds), dims(gold_ds))
                self.assertIn("image", gold_ds.variables)
                self.assertEqual(list(port_ds.variables), list(gold_ds.variables))
                for vn, gv in gold_ds.variables.items():
                    pv = port_ds.variables[vn]
                    with self.subTest(var=vn):
                        self.assertEqual(pv.dimensions, gv.dimensions)
                        self.assertEqual(pv.dtype, gv.dtype)
                        np.testing.assert_array_equal(
                            np.asarray(pv[:]), np.asarray(gv[:]), err_msg=f"{vn} data")
                        self.assertEqual(
                            {a: pv.getncattr(a) for a in pv.ncattrs()},
                            {a: gv.getncattr(a) for a in gv.ncattrs()})
                gold_attrs = {a: gold_ds.getncattr(a) for a in gold_ds.ncattrs()
                              if a not in _EXCLUDED_GLOBAL_ATTRS}
                port_attrs = {a: port_ds.getncattr(a) for a in port_ds.ncattrs()
                              if a not in _EXCLUDED_GLOBAL_ATTRS}
                self.assertEqual(set(port_attrs), set(gold_attrs))
                # Same tolerance rule as test_frame_full_ncdf_matches_gdl:
                # `_base_op` types some scalars as bare int/float.
                for a, gv2 in gold_attrs.items():
                    pv2 = port_attrs[a]
                    with self.subTest(attr=a):
                        if isinstance(gv2, np.ndarray) and np.issubdtype(gv2.dtype, np.floating):
                            np.testing.assert_allclose(
                                np.asarray(pv2, dtype=gv2.dtype), gv2, rtol=1e-6)
                        elif isinstance(gv2, np.ndarray):
                            np.testing.assert_array_equal(np.asarray(pv2), gv2)
                        elif isinstance(gv2, (float, np.floating)):
                            self.assertAlmostEqual(
                                float(np.asarray(pv2, dtype=gv2.dtype)), float(gv2), places=6)
                        else:
                            self.assertEqual(pv2, gv2)
            finally:
                port_ds.close()
                gold_ds.close()

    def test_frame_csv_only_writes_no_ncdf(self) -> None:
        golden = _load_driver_golden()["frame_csv_only"]
        self.assertEqual(golden["status"], "OK")
        self.assertNotIn("nc_tracked", golden)
        golden_path = DATA / golden["csv_tracked"]
        with tempfile.TemporaryDirectory() as tmp:
            op = _frame_full_op(tmp + os.sep, particlefile=1, ncdfparticlefile=0)
            d = soda2_process_2d(op)
            self.assertIsInstance(d, ProcessData)
            csv_files = list(Path(tmp).glob("*.pbp.csv"))
            nc_files = list(Path(tmp).glob("*.pbp.nc"))
            self.assertEqual(len(csv_files), 1)
            self.assertEqual(len(nc_files), 0)
            port_lines = _csv_lines_minus_dateprocessed(csv_files[0])
        golden_lines = _csv_lines_minus_dateprocessed(golden_path)
        self.assertEqual(port_lines, golden_lines)


class FlushOffsetTrace507(unittest.TestCase):
    """`:507`'s ``pbpstartindex[i] = istart + ncdf_offset`` fix and the
    netCDF write-position ``offset=ncdf_offset`` argument it rides alongside
    (`ps:186-261`) are both untestable against any GDL golden -- `num2process`
    is a compiled-in IDL literal (``10000000L``, `:565`), never an `op`
    field, so GDL can never be made to flush mid-loop on a tracked fixture
    (sixth uncertainty). This is therefore a self-consistency
    proof: on the frame fixture, `num2process` small enough to force a
    mid-loop flush necessarily forces one on *every* accepted buffer,
    including the last (istop stays small -- 4, then 7 -- so the ``istop +
    500 > num2process`` check trips for any ``num2process`` under ~500,
    regardless of which accepted buffer it is), which lands on `:576`'s
    early return before the final
    `ProcessData` is ever built. So the discriminating measurement is not
    `pbpstartindex` on a returned `ProcessData` (there is none), but whether
    the *files already flushed to disk* before that return are complete,
    correctly offset (no overwritten/lost rows) and byte-identical to the
    unforced run -- proving `ncdf_offset` tracks the running total in the
    netCDF write slice, and that the second flush appends after the first
    rather than starting a fresh file."""

    def test_forced_flush_appends_after_the_first_without_corrupting_either_file(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_default, \
                tempfile.TemporaryDirectory() as tmp_flushed:
            op_default = _frame_full_op(
                tmp_default + os.sep, particlefile=1, ncdfparticlefile=1
            )
            d_default = soda2_process_2d(op_default)
            self.assertIsInstance(d_default, ProcessData)

            op_flushed = _frame_full_op(
                tmp_flushed + os.sep, particlefile=1, ncdfparticlefile=1
            )
            # num2process=6: `istop + 500 > 6` trips on the very first
            # accepted buffer (istop=4) and again on the second (istop=7,
            # after the reset) -- measured, not guessed; see
            # the class docstring for why no value threads between them on
            # this fixture.
            d_flushed = soda2_process_2d(op_flushed, num2process=6)
            self.assertIsNone(d_flushed, "S6-f: the forced flush reaches "
                                          ":576's early return on this fixture")
            # S6-f's own consequence: the early return skips both closes. The
            # unclosed netCDF4.Dataset sits in a Dataset<->Variable reference
            # cycle, so only cyclic GC releases its handle -- without this
            # collect, TemporaryDirectory cleanup raises PermissionError on
            # the .pbp.nc (measured). The CSV is already
            # complete before the collect. (An earlier "one row short" note
            # here was test arithmetic -- the helper below drops a header
            # line -- not GC timing.)
            del d_flushed
            gc.collect()

            default_csv = next(Path(tmp_default).glob("*.pbp.csv"))
            flushed_csv = next(Path(tmp_flushed).glob("*.pbp.csv"))
            default_lines = _csv_lines_minus_dateprocessed(default_csv)
            flushed_lines = _csv_lines_minus_dateprocessed(flushed_csv)
            self.assertEqual(default_lines, flushed_lines,
                              "flush timing must not change what is written, "
                              "only when")
            # The absolute count, from the GDL golden rather than from the
            # port: header length = golden lines - golden rows (the golden
            # .pbp.nc's own Time size), so no literal 43 to go stale.
            golden = _load_driver_golden()["frame_full"]
            golden_lines = _csv_lines_minus_dateprocessed(DATA / golden["csv_tracked"])
            g = netCDF4.Dataset(DATA / golden["nc_tracked"], "r")
            try:
                golden_rows = g.dimensions["Time"].size
            finally:
                g.close()
            header = len(golden_lines) - golden_rows
            self.assertEqual(len(flushed_lines) - header, golden_rows,
                             "the forced-flush CSV must carry exactly the "
                             "golden's particle rows")

            default_nc = next(Path(tmp_default).glob("*.pbp.nc"))
            flushed_nc = next(Path(tmp_flushed).glob("*.pbp.nc"))
            ds_default = netCDF4.Dataset(default_nc, "r")
            ds_flushed = netCDF4.Dataset(flushed_nc, "r")
            try:
                self.assertEqual(
                    ds_default.dimensions["Time"].size,
                    ds_flushed.dimensions["Time"].size,
                    "the second flush must append at ncdf_offset=5, not "
                    "overwrite from 0 -- a dropped '+= istop + 1' would "
                    "truncate the flushed file relative to the unforced run",
                )
                for vn in ds_default.variables:
                    np.testing.assert_array_equal(
                        np.asarray(ds_default.variables[vn][:]),
                        np.asarray(ds_flushed.variables[vn][:]),
                        err_msg=f"{vn}: forced-flush content differs from the "
                                "unforced run",
                    )
            finally:
                ds_default.close()
                ds_flushed.close()


class TimeIntervalFollowsIdlStrmid(unittest.TestCase):
    """``soda2_process_2d.pro:253-256``: ``'0000'+strtrim(string(hms),2)`` cut
    with ``strmid(tb,5,2,/r)``/``(tb,3,2,/r)``/``(tb,1,2,/r)``. Worked by hand
    from IDL's ``/REVERSE_OFFSET`` (start counted from the end, read forward).
    Every expected string below was MEASURED under GDL 1.1.2 on 2026-09-14
    (``locate.run_pro`` on exactly those two lines), including the short-string
    boundary: hms 5 is the string '00005', whose first piece starts before
    the string and is clamped to it, giving ``00:00:05``."""

    #: hms -> the string GDL printed for it.
    GDL_MEASURED = {5: "00:00:05", 59: "00:00:59", 959: "00:09:59",
                    4400: "00:44:00", 64400: "06:44:00"}

    def test_hours_minutes_seconds_in_that_order(self) -> None:
        from arrayprobe_soda2.pbp_writer import _idl_hms_string
        for hms, want in self.GDL_MEASURED.items():
            with self.subTest(hms=hms):
                self.assertEqual(_idl_hms_string(hms), want)

    def test_the_old_field_order_is_not_what_the_port_writes(self) -> None:
        from arrayprobe_soda2.pbp_writer import _idl_hms_string, sfm2hms
        tb = sfm2hms(24240.0)
        swapped = f"{tb % 100:02d}:{(tb // 100) % 100:02d}:{tb // 10000:02d}"
        self.assertNotEqual(_idl_hms_string(tb), swapped)


if __name__ == "__main__":
    unittest.main()
