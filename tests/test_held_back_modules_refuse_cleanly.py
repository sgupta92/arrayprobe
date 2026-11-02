# SPDX-License-Identifier: BSD-3-Clause
"""Modules held back from the release are absent cleanly.

Each test blocks one held-back module (``sys.modules[name] = None``) and checks that shipped
code still imports, that its default path never reaches the module, and that the opt-in path
refuses with a message naming the option.
"""
from __future__ import annotations

import importlib
import importlib.util
import inspect
import io
import sys
import types
import unittest
from contextlib import contextmanager, redirect_stderr
from unittest import mock

_ABSENT = object()


@contextmanager
def _blocked(*names):
    """Make each module unimportable, as on a tree that does not ship it.

    ``sys.modules[name] = None`` alone is not enough: once an earlier test has imported the
    module, ``from package import leaf`` returns the package attribute without consulting
    ``sys.modules``, so the attribute is hidden for the duration too and then restored.
    """
    hidden = []
    for name in names:
        parent_name, _, leaf = name.rpartition(".")
        parent = sys.modules.get(parent_name)
        if parent is not None and leaf in vars(parent):
            hidden.append((parent, leaf, vars(parent)[leaf]))
            delattr(parent, leaf)
    try:
        with mock.patch.dict(sys.modules, {n: None for n in names}):
            yield
    finally:
        for parent, leaf, value in hidden:
            setattr(parent, leaf, value)


@contextmanager
def _reimported(name):
    """Pop ``name`` so the body re-imports it, then restore BOTH bindings the import touches.

    A fresh import rebinds ``sys.modules[name]`` and the parent package's attribute; restoring
    only the first left two module objects live (and two distinct exception classes), so a later
    module that reached one through the package and the other through ``sys.modules`` failed.
    """
    parent_name, _, leaf = name.rpartition(".")
    parent = importlib.import_module(parent_name)
    saved_mod = sys.modules.pop(name, _ABSENT)
    saved_attr = getattr(parent, leaf, _ABSENT)
    try:
        yield
    finally:
        for store, key, saved in ((sys.modules, name, saved_mod),
                                  (parent.__dict__, leaf, saved_attr)):
            if saved is _ABSENT:
                store.pop(key, None)
            else:
                store[key] = saved


class TasSidecarWriterSurvivesWithoutNasaAmes(unittest.TestCase):
    def test_housekeeping_producer_imports_without_nasa_ames_tas(self):
        with _blocked("arrayprobe.tools.nasa_ames_tas"), \
                _reimported("arrayprobe.driver.tas_from_probe_housekeeping"):
            mod = importlib.import_module("arrayprobe.driver.tas_from_probe_housekeeping")
            self.assertTrue(callable(mod.write_tas_csv))

    @unittest.skipIf(importlib.util.find_spec("arrayprobe.tools.nasa_ames_tas") is None,
                     "arrayprobe.tools.nasa_ames_tas is held back from the public release"
                     "; there is no re-export to check")
    def test_nasa_ames_tas_reexports_the_same_writer(self):
        from arrayprobe.tools import make_tas_file, nasa_ames_tas
        self.assertIs(nasa_ames_tas.write_tas_csv, make_tas_file.write_tas_csv)

    def test_cli_subcommand_refuses_by_name(self):
        from arrayprobe import cli
        args = types.SimpleNamespace(path="x", out="y", flight_date="2016-09-12",
                                     drop_missing=False)
        err = io.StringIO()
        with _blocked("arrayprobe.tools.nasa_ames_tas"), redirect_stderr(err):
            rc = cli._tas_from_nasa_ames(args)
        self.assertEqual(rc, 2)   # printed and returned, like every other cli refusal
        self.assertIn("tas-from-nasa-ames is not available in this release", err.getvalue())


class MmethodRefusesWithoutMassB26(unittest.TestCase):
    def test_import_is_lazy_and_guarded(self):
        from arrayprobe_uiops import sizedist
        src = inspect.getsource(sizedist)
        self.assertNotIn("\nfrom arrayprobe_uiops.mass_b26", src)
        self.assertNotIn("\nimport arrayprobe_uiops.mass_b26", src)
        body = inspect.getsource(sizedist._diameters_and_mass)
        default, _, opt_in = body.partition("from arrayprobe_uiops.mass_b26 import")
        self.assertIn("if mmethod == 0:", default)   # the default branch comes first
        self.assertIn("is not available in this release", opt_in)

    def test_sizedist_imports_with_mass_b26_blocked(self):
        with _blocked("arrayprobe_uiops.mass_b26"), _reimported("arrayprobe_uiops.sizedist"):
            mod = importlib.import_module("arrayprobe_uiops.sizedist")
        self.assertEqual(mod.__name__, "arrayprobe_uiops.sizedist")


class IatSourceRefusesWithoutHvpsFlightConfig(unittest.TestCase):
    def test_run_flight_imports_with_hvps_modules_blocked(self):
        with _blocked("arrayprobe.hvps_flight_config", "arrayprobe.hvps_caveat"), \
                _reimported("arrayprobe.driver.run_flight"):
            mod = importlib.import_module("arrayprobe.driver.run_flight")
        self.assertEqual(mod.__name__, "arrayprobe.driver.run_flight")

    def test_default_path_never_reaches_the_table(self):
        from arrayprobe.driver import run_flight
        args = types.SimpleNamespace(iat_source=None)
        with _blocked("arrayprobe.hvps_flight_config"):
            self.assertIsNone(run_flight._resolve_iat_source(args, []))

    def test_opt_in_refuses_by_name(self):
        from arrayprobe.driver import run_flight
        args = types.SimpleNamespace(iat_source="flight-table")
        with _blocked("arrayprobe.hvps_flight_config"):
            msg = run_flight._resolve_iat_source(args, [])
        self.assertIn("--iat-source flight-table is not available in this release", msg)


class BlockedReimportLeavesOneModule(unittest.TestCase):
    """After a blocked re-import, the package attribute and ``sys.modules`` name one object."""

    NAMES = ("arrayprobe_uiops.sizedist", "arrayprobe.driver.run_flight",
             "arrayprobe.driver.tas_from_probe_housekeeping")

    def test_parent_attribute_is_the_sys_modules_entry(self):
        for name in self.NAMES:
            with self.subTest(name=name):
                parent_name, _, leaf = name.rpartition(".")
                before = importlib.import_module(name)
                with _blocked("arrayprobe_uiops.mass_b26", "arrayprobe.hvps_flight_config",
                              "arrayprobe.hvps_caveat", "arrayprobe.tools.nasa_ames_tas"), \
                        _reimported(name):
                    fresh = importlib.import_module(name)
                    self.assertIsNot(fresh, before)   # the body really re-imported it
                parent = sys.modules[parent_name]
                self.assertIs(sys.modules[name], before)
                self.assertIs(getattr(parent, leaf), sys.modules[name])

    def test_sizedist_tasmax_class_is_one_class_after_the_blocked_test(self):
        MmethodRefusesWithoutMassB26("test_sizedist_imports_with_mass_b26_blocked").debug()
        from arrayprobe_uiops import sizedist as via_package
        from arrayprobe_uiops.sizedist import TasMaxUndefined
        self.assertIs(via_package.TasMaxUndefined, TasMaxUndefined)


if __name__ == "__main__":
    unittest.main()
