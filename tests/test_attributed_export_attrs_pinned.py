# SPDX-License-Identifier: BSD-3-Clause
"""The UIOOPS attributed export's every attribute, value and order, pinned to a golden.

The golden ``tests/data/attributed_export_uiops_attrs_golden.json`` was written by the module as it
stood before the time and missing-value conventions became per-shape fields and before source
variable attributes were copied through. A refactor of the export must leave the UIOOPS product's
attributes unchanged; this test is that check. Attributes whose value is the package version are
compared by name and position only, so a version bump does not fail it.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from netCDF4 import Dataset

from arrayprobe import attributed_export as ae

try:  # `unittest discover -s tests` puts tests/ on the path; `-m unittest tests.x` does not
    from test_attributed_export import _faithful
except ModuleNotFoundError:
    from tests.test_attributed_export import _faithful

GOLDEN = Path(__file__).parent / "data" / "attributed_export_uiops_attrs_golden.json"
EXPORT_TIME = "2026-09-17T00:00:00+00:00"


def _jsonable(value):
    return value.tolist() if hasattr(value, "tolist") else value


def _dump(path: Path) -> dict:
    with Dataset(str(path)) as ds:
        dump = {
            "global": [[k, _jsonable(ds.getncattr(k))] for k in ds.ncattrs()],
            "variables": {n: [[k, _jsonable(v.getncattr(k))] for k in v.ncattrs()]
                          for n, v in ds.variables.items()},
        }
    # Round-trip through JSON so tuples and lists compare the way the golden stores them.
    return json.loads(json.dumps(dump))


def _version_blind(pairs: list) -> list:
    return [[k, None if "version" in k.lower() else v] for k, v in pairs]


class TheUiopsExportAttributesAreUnchanged(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as d:
            source = _faithful(Path(d))
            out = ae.export(source, Path(d) / "out.nc", export_time=EXPORT_TIME)
            cls.got = _dump(out)

    def test_global_attributes_names_values_and_order(self) -> None:
        self.assertEqual(_version_blind(self.got["global"]),
                         _version_blind(self.golden["global"]))

    def test_variable_attributes_names_values_and_order(self) -> None:
        self.assertEqual(list(self.got["variables"]), list(self.golden["variables"]))
        for name, pairs in self.golden["variables"].items():
            with self.subTest(variable=name):
                self.assertEqual(self.got["variables"][name], pairs)

    def test_the_conventions_now_come_from_the_shape(self) -> None:
        got = dict(self.got["global"])
        shape = ae.COMBINED_SHAPE
        self.assertEqual(got[f"{ae.ATTR_PREFIX}time_convention"], shape.time_convention)
        self.assertEqual(got[f"{ae.ATTR_PREFIX}missing_value_convention"],
                         shape.missing_value_convention)


class SourceVariableAttributesAreCopiedThrough(unittest.TestCase):

    def test_an_attribute_the_export_does_not_set_survives_after_its_own(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            source = _faithful(Path(d))
            with Dataset(str(source), "a") as ds:
                var = ds.variables["Reject Ratio"]
                var.setncattr("comment", "from the source")
                var.setncattr("units", "source-units-must-not-win")
            out = ae.export(source, Path(d) / "out.nc", export_time=EXPORT_TIME)
            with Dataset(str(out)) as ds:
                var = ds.variables["Reject Ratio"]
                self.assertEqual(var.getncattr("comment"), "from the source")
                self.assertEqual(var.getncattr("units"),
                                 ae.COMBINED_SIZEDIST["Reject Ratio"].units)
                self.assertEqual(var.ncattrs()[-1], "comment")


if __name__ == "__main__":
    unittest.main()
