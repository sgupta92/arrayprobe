# SPDX-License-Identifier: BSD-3-Clause
"""``selector.canonical_module`` -- the retired-package-name alias.

A configuration file or command line names a module by its dotted path, and a
package rename would break every one written before it. ``canonical_module``
rewrites a retired leading package name to its replacement, by exact match of
the first dotted segment and nothing else. These tests pin the real table
(``arrayprobe_v35`` is read as ``arrayprobe_uiops``, and no package of the old
name exists to shadow the alias), that the alias is the identity once the table
is emptied, that a planted entry rewrites only an exact first segment, and that
every place a user-named module is imported routes the name through it.
"""
from __future__ import annotations

import ast
import importlib.util
import unittest
from pathlib import Path
from unittest import mock

from tests._repo import PKG_ROOT

import arrayprobe
from arrayprobe import selector
from arrayprobe.selector import canonical_module

PKG = Path(arrayprobe.__file__).resolve().parent
SRC = (PKG_ROOT / "src").resolve()
CONFIG = PKG / "config.py"
RUN_FLIGHT = PKG / "driver" / "run_flight.py"


class TestRealTable(unittest.TestCase):
    def test_old_engine_name_reads_as_the_new_one(self):
        self.assertEqual(selector.RETIRED_PACKAGES,
                         {"arrayprobe_v35": "arrayprobe_uiops"})
        self.assertEqual(canonical_module("arrayprobe_v35.register_arm_stock"),
                         "arrayprobe_uiops.register_arm_stock")
        self.assertEqual(canonical_module("arrayprobe_v35.a.b"),
                         "arrayprobe_uiops.a.b")
        self.assertEqual(canonical_module("arrayprobe_v35"), "arrayprobe_uiops")
        for unchanged in ("arrayprobe_v35x.y", "arrayprobe_uiops.sizedist",
                          "arrayprobe.profiles", "arrayprobe_soda2.process_hk"):
            self.assertEqual(canonical_module(unchanged), unchanged)

    def test_no_package_of_the_old_name_exists(self):
        # A stub package under the old name would be imported directly by any
        # caller that bypasses canonical_module, hiding a missed call site.
        # Another checkout sharing the interpreter may still hold the old
        # directory, so the check is on this checkout's source tree: no
        # directory of the old name in it, and nothing importable under the old
        # name that resolves into it.
        self.assertFalse((SRC / "arrayprobe_v35").exists())
        spec = importlib.util.find_spec("arrayprobe_v35")
        if spec is not None:
            origins = [spec.origin] if spec.origin else []
            origins += list(spec.submodule_search_locations or [])
            for origin in origins:
                path = Path(origin).resolve()
                self.assertFalse(path.is_relative_to(SRC),
                                 f"arrayprobe_v35 resolves into this checkout: {path}")

    def test_the_new_name_imports(self):
        self.assertIsNotNone(importlib.util.find_spec("arrayprobe_uiops"))

    def test_emptied_table_passes_the_old_name_through(self):
        with mock.patch.dict(selector.RETIRED_PACKAGES, {}, clear=True):
            self.assertEqual(canonical_module("arrayprobe_v35.register_arm_stock"),
                             "arrayprobe_v35.register_arm_stock")


class TestIdentityWithEmptyTable(unittest.TestCase):
    def test_every_name_is_unchanged(self):
        with mock.patch.dict(selector.RETIRED_PACKAGES, {}, clear=True):
            for name in ("arrayprobe_uiops.register_arm_stock",
                         "arrayprobe_uiops.register_arm_ena_2ds",
                         "arrayprobe.profiles", "arrayprobe_soda2.process_hk",
                         "mypkg", "a.b.c.d", ""):
                self.assertEqual(canonical_module(name), name)


class TestFirstSegmentExactness(unittest.TestCase):
    def test_planted_entry(self):
        with mock.patch.dict(selector.RETIRED_PACKAGES,
                             {"old_pkg": "new_pkg"}, clear=True):
            self.assertEqual(canonical_module("old_pkg.x"), "new_pkg.x")
            self.assertEqual(canonical_module("old_pkg.x.y"), "new_pkg.x.y")
            self.assertEqual(canonical_module("old_pkg"), "new_pkg")
            for unchanged in ("old_pkgx.y", "new_pkg.x", "other.old_pkg",
                              "xold_pkg.y", "old_pk.y"):
                self.assertEqual(canonical_module(unchanged), unchanged)

    def test_mapping_is_one_direction(self):
        with mock.patch.dict(selector.RETIRED_PACKAGES,
                             {"old_pkg": "new_pkg"}, clear=True):
            self.assertEqual(canonical_module("new_pkg.mod"), "new_pkg.mod")

    def test_a_non_string_passes_through_unchanged(self):
        sentinel = mock.Mock()
        self.assertIs(canonical_module(sentinel), sentinel)
        self.assertIsNone(canonical_module(None))


def _is_alias_call(node: ast.AST) -> bool:
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "canonical_module")


def _is_import_module(call: ast.Call) -> bool:
    return isinstance(call.func, ast.Attribute) and call.func.attr == "import_module"


class TestCallSitesRouteThroughAlias(unittest.TestCase):
    """Every import of a user-named module wraps its name in canonical_module."""

    def _user_named_imports(self, path: Path, names: set[str]) -> list[ast.Call]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_import_module(node) and node.args:
                used = {n.id for n in ast.walk(node.args[0]) if isinstance(n, ast.Name)}
                if used & names:
                    found.append(node)
        return found

    def _assert_all_wrapped(self, path: Path, names: set[str], expected: int):
        sites = self._user_named_imports(path, names)
        self.assertEqual(len(sites), expected,
                         f"{path.name}: expected {expected} import_module site(s) "
                         f"naming {sorted(names)}, found {len(sites)}")
        for site in sites:
            self.assertTrue(_is_alias_call(site.args[0]),
                          f"{path.name}:{site.lineno} imports a user-named module "
                          "without canonical_module")

    def test_config_profile_module(self):
        self._assert_all_wrapped(CONFIG, {"profile_module"}, 1)

    def test_run_flight_worker_profile_module(self):
        self._assert_all_wrapped(RUN_FLIGHT, {"profile_module"}, 1)

    def test_run_flight_probe_case_module(self):
        self._assert_all_wrapped(RUN_FLIGHT, {"PROBE_CASE_MODULE"}, 1)

    def test_run_flight_worker_forward(self):
        tree = ast.parse(RUN_FLIGHT.read_text(encoding="utf-8"))
        forwards = []
        for node in ast.walk(tree):
            if isinstance(node, ast.List) and node.elts:
                first = node.elts[0]
                if isinstance(first, ast.Constant) and first.value == "--probe-case-module":
                    forwards.append(node)
        self.assertEqual(len(forwards), 1, "expected one --probe-case-module forward")
        value = forwards[0].elts[1]
        self.assertTrue(_is_alias_call(value),
                        f"run_flight.py:{forwards[0].lineno} forwards --probe-case-module "
                        "to workers without canonical_module")


if __name__ == "__main__":
    unittest.main()
