# SPDX-License-Identifier: BSD-3-Clause
"""The attributed export of a SODA-2 size-distribution netCDF (``<stem>.nc``).

Built on the SODA-2 frame fixture ``tests/test_cli_soda2.py`` uses: a real run writes ``<stem>.nc``
through ``arrayprobe_soda2.export_ncdf.write_run_psd``, and the export of that file must keep every
value, dtype and dimension list, label every variable from the writer's own tables, and carry the
SODA-2 citation exactly.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
from netCDF4 import Dataset
from tests.test_cli_soda2 import _write_config

from arrayprobe import attributed_export as ae
from arrayprobe.config import load_config

_CITATION = ("Aaron Bansemer. (2026). abansemer/soda2: v2.26.0 (Version v2.26.0) [Computer "
             "software]. Zenodo. https://doi.org/10.5281/zenodo.18331418")


def _psd(tmp: str) -> Path:
    from arrayprobe_soda2.export_ncdf import write_run_psd
    from arrayprobe_soda2.process_2d import soda2_process_2d
    d = soda2_process_2d(dict(load_config(_write_config(tmp, ncdf=1)).soda2))
    return Path(write_run_psd(d, outdir=tmp, date_created="Thu Oct 08 00:00:00 2026"))


class TheSoda2PsdExport(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.src = _psd(cls._tmp.name)
        cls.out = ae.export(cls.src, accept_unstamped=True, export_time="2026-10-08T00:00:00Z")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_values_dtypes_and_dimensions_equal_the_source(self):
        with Dataset(str(self.src)) as s, Dataset(str(self.out)) as o:
            s.set_auto_maskandscale(False)
            o.set_auto_maskandscale(False)
            self.assertEqual(set(s.variables), set(o.variables))
            for name, v in s.variables.items():
                w = o.variables[name]
                self.assertEqual(v.dtype, w.dtype, name)
                self.assertEqual(v.dimensions, w.dimensions, name)
                np.testing.assert_array_equal(np.asarray(v[...]), np.asarray(w[...]), name)

    def test_every_variable_carries_the_writers_units_and_long_name(self):
        with Dataset(str(self.src)) as s, Dataset(str(self.out)) as o:
            for name, v in s.variables.items():
                w = o.variables[name]
                self.assertEqual(w.units, v.getncattr("units"), name)
                self.assertEqual(w.long_name, v.getncattr("long_name"), name)
                self.assertIn("export_ncdf.py", w.getncattr("arrayprobe_units_basis"), name)

    def test_the_table_entries_are_imported_from_the_writer(self):
        from arrayprobe_soda2 import export_ncdf as w
        with Dataset(str(self.out)) as o:
            for name in o.variables:
                if name in w._BULK_SIMPLE:
                    self.assertEqual((o[name].long_name, o[name].units), w._BULK_SIMPLE[name])
                if name in w._MAIN_SIMPLE:
                    self.assertEqual((o[name].long_name, o[name].units),
                                     w._MAIN_SIMPLE[name][:2])

    def test_citation_is_byte_equal(self):
        with Dataset(str(self.out)) as o:
            self.assertEqual(o.getncattr("arrayprobe_engine_citation"), _CITATION)
            self.assertEqual(o.getncattr("references"), _CITATION)
            self.assertEqual(o.getncattr("arrayprobe_engine"), "soda2")
        self.assertEqual(ae.SODA2_CITATION, _CITATION)

    def test_ai_ready_check_passes(self):
        from arrayprobe import ai_ready
        self.assertEqual(ai_ready.check(self.out), [])

    def test_an_unknown_tag_is_refused(self):
        with self.assertRaises(ae.UnknownProductError):
            ae.soda2_shape({"elapsed_time": {"units": "s", "long_name": "Elapsed time"},
                            "FOO": {"units": "Unknown", "long_name": "Unknown"}})

    def test_the_writers_own_source_global_is_recognised(self):
        self.assertTrue(ae.is_soda2_psd([], {"Source": "SODA-2 OAP Processing Software"}))
        self.assertFalse(ae.is_soda2_psd(["time"], {}))


if __name__ == "__main__":
    unittest.main()
