# SPDX-License-Identifier: BSD-3-Clause
"""The package's front door: what ``import arrayprobe`` puts in reach.

Until 2026-09-01 ``arrayprobe/__init__.py`` re-exported nothing but
``__version__``, so every entry point was a submodule a caller had to already
know by name. The curated
``__all__`` added that day is an API decision, not a mechanical one, and this
project's rule is that a decision becomes a test -- otherwise a later session
can quietly widen the surface to "whatever happened to be imported", which is
the failure mode a curated list exists to prevent.

So the expected list is written out here, in a second place, and compared
against the package's own. Adding or removing an export is then a deliberate
two-file edit with a reviewable diff, which is exactly the cost it should have.

The last test is the reason this file lives next to
``test_no_enhancement_coupling.py`` and borrows its subprocess technique: the
front door must not become the thing that drags the optional enhancements
package in. That test asserts the *static* rule (no unguarded reference in the
source); this one asserts the observable consequence -- after ``import
arrayprobe``, ``arrayprobe_enhancements`` is not in ``sys.modules``.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from tests._repo import needs_v314_engine  # noqa: E402

import arrayprobe

_PORT_ROOT = Path(__file__).resolve().parent.parent

#: The curated public surface, restated independently of the package.
EXPECTED_ALL = [
    "__version__",
    "read_binary_SPEC",
    "read_binary_hvps",
    "read_binary_DMT",
    "read_binary_PMS",
    "read_binary_SEA",
    "load_tas_info",
    "imgproc_sm",
    "size_dist",
    "combine_sizedist",
    "FidelityProfile",
    "STOCK_V314",
    "ORACLES_2016",
    "ORACLES_PRODUCTION",
    "PROFILES",
    "profile",
    # Added 2026-09-09. It belongs on the front door because it is how a
    # group running its own UIOOPS fork names that fork without editing this
    # package -- the same standing this list already gives `profile`, which is
    # only useful once there is something to look up. It cannot widen what a
    # config file may do: registration constructs a FidelityProfile in Python,
    # where the dataclass requires every field, and a config file still may not
    # set one.
    "register_profile",
    "RunConfig",
    "ConfigError",
    "load_config",
    "compare_files",
    "format_report",
    "ComparisonReport",
    # Added 2026-09-10: typed results for the same product-comparison
    # gate that a script only prints -- belongs beside
    # `compare_files`/`ComparisonReport` for the same reason those do: a
    # notebook or a caller's own script needs a value to hold onto, not stdout
    # to re-parse.
    "compare_to_product",
    "ProductComparisonReport",
    "CellAgreement",
    # Added 2026-09-10: the McFarquhar et al. (2017) p. 11.20
    # interarrival-closure diagnostic -- reports, changes no computed number.
    "check_closure",
    "ClosureResult",
    # The project-level selector: arrayprobe.engine() reaches all three shipped
    # engines ("3.5" default, "3.1.4", "soda2") one level above uiops.engine(), which
    # reaches only the two UIOOPS versions and refuses SODA-2 by design. Exported and never
    # curated here, so this list has been reporting the selector as an intruder.
    "engine",
    "Engine",
    "ENGINES",
    "DEFAULT_ENGINE",
    "UnknownEngine",
    # reading a product for analysis; engine-neutral.
    "open_product",
]

#: Each export, and the submodule it must still be the *same object* as. This
#: is the half that catches a re-export gone stale: a name that resolves at the
#: package level but no longer points at the implementation callers reach by
#: its module path would pass the "exists" check and be a different function.
EXPECTED_ORIGIN = {
    # The project-level selector, pinned like every other export so a rename cannot move it
    # silently. It dispatches and computes nothing -- tests/test_uiops_selector.py asserts
    # the module contains no arithmetic -- so nothing here can change a number.
    "engine": ("arrayprobe.selector", "engine"),
    "Engine": ("arrayprobe.selector", "Engine"),
    "ENGINES": ("arrayprobe.selector", "ENGINES"),
    "DEFAULT_ENGINE": ("arrayprobe.selector", "DEFAULT_ENGINE"),
    "UnknownEngine": ("arrayprobe.selector", "UnknownEngine"),
    "read_binary_SPEC": ("arrayprobe.readers.spec", "read_binary_SPEC"),
    "read_binary_hvps": ("arrayprobe.readers.spec", "read_binary_hvps"),
    "read_binary_DMT": ("arrayprobe.readers.dmt", "read_binary_DMT"),
    "read_binary_PMS": ("arrayprobe.readers.pms", "read_binary_PMS"),
    "read_binary_SEA": ("arrayprobe.readers.sea", "read_binary_SEA"),
    "load_tas_info": ("arrayprobe.readers.tasinfo", "load_tas_info"),
    "imgproc_sm": ("arrayprobe.imgproc", "imgproc_sm"),
    # sizeDist.m's port is ``sizedist.run``; ``size_dist`` is the package-level
    # snake-case name for it, so this pair also pins the alias.
    "size_dist": ("arrayprobe.sizedist", "run"),
    "combine_sizedist": ("arrayprobe.combine", "combine_sizedist"),
    "FidelityProfile": ("arrayprobe.profiles", "FidelityProfile"),
    "STOCK_V314": ("arrayprobe.profiles", "STOCK_V314"),
    "ORACLES_2016": ("arrayprobe.profiles", "ORACLES_2016"),
    "ORACLES_PRODUCTION": ("arrayprobe.profiles", "ORACLES_PRODUCTION"),
    "PROFILES": ("arrayprobe.profiles", "PROFILES"),
    "profile": ("arrayprobe.profiles", "profile"),
    "register_profile": ("arrayprobe.profiles", "register_profile"),
    "RunConfig": ("arrayprobe.config", "RunConfig"),
    "ConfigError": ("arrayprobe.config", "ConfigError"),
    "load_config": ("arrayprobe.config", "load_config"),
    "compare_files": ("arrayprobe.compare", "compare_files"),
    "format_report": ("arrayprobe.compare", "format_report"),
    "ComparisonReport": ("arrayprobe.compare", "ComparisonReport"),
    "check_closure": ("arrayprobe.timing_closure", "check_closure"),
    "ClosureResult": ("arrayprobe.timing_closure", "ClosureResult"),
    "compare_to_product": ("arrayprobe.validation_report", "compare_to_product"),
    "ProductComparisonReport": ("arrayprobe.validation_report", "ProductComparisonReport"),
    "CellAgreement": ("arrayprobe.validation_report", "CellAgreement"),
    "open_product": ("arrayprobe.products", "open_product"),
}


class PublicSurface(unittest.TestCase):
    def test_all_matches_the_curated_list(self):
        self.assertEqual(
            list(arrayprobe.__all__), EXPECTED_ALL,
            "arrayprobe.__all__ changed. That is an API decision: update "
            "EXPECTED_ALL here in the same commit, and say in the message why "
            "the name belongs on the front door (see the module docstring of "
            "src/arrayprobe/__init__.py for what the list is for).")

    def test_all_has_no_duplicates(self):
        self.assertEqual(len(arrayprobe.__all__), len(set(arrayprobe.__all__)))

    @needs_v314_engine
    def test_every_exported_name_exists(self):
        missing = [n for n in arrayprobe.__all__ if not hasattr(arrayprobe, n)]
        self.assertEqual(missing, [],
                         f"named in __all__ but not bound on the package: {missing}")

    @needs_v314_engine
    def test_star_import_binds_every_exported_name(self):
        """``from arrayprobe import *`` is what ``__all__`` actually governs."""
        namespace: dict[str, object] = {}
        exec("from arrayprobe import *", namespace)  # noqa: S102 -- the thing under test
        namespace.pop("__builtins__", None)
        self.assertEqual(sorted(namespace), sorted(EXPECTED_ALL))

    def test_nothing_private_is_exported(self):
        private = [n for n in arrayprobe.__all__
                   if n.startswith("_") and not n.startswith("__")]
        self.assertEqual(private, [], f"private names on the front door: {private}")

    @needs_v314_engine
    def test_each_export_is_the_submodule_object(self):
        import importlib
        for name, (module_name, attr) in EXPECTED_ORIGIN.items():
            with self.subTest(name=name):
                module = importlib.import_module(module_name)
                self.assertIs(getattr(arrayprobe, name), getattr(module, attr))

    def test_every_export_other_than_version_has_an_origin_pinned(self):
        """No export may slip in without a submodule identity to check it against."""
        unpinned = sorted(set(EXPECTED_ALL) - set(EXPECTED_ORIGIN) - {"__version__"})
        self.assertEqual(unpinned, [], f"exports with no EXPECTED_ORIGIN row: {unpinned}")

    @needs_v314_engine
    def test_the_stage_entry_points_are_callable(self):
        for name in ("read_binary_SPEC", "read_binary_hvps", "read_binary_DMT",
                     "read_binary_PMS", "read_binary_SEA", "load_tas_info",
                     "imgproc_sm", "size_dist", "combine_sizedist",
                     "load_config", "compare_files", "format_report", "profile",
                     "open_product"):
            with self.subTest(name=name):
                self.assertTrue(callable(getattr(arrayprobe, name)))

    def test_the_package_has_a_module_docstring(self):
        doc = arrayprobe.__doc__ or ""
        self.assertGreater(len(doc), 200, "the front door must say what the package is")
        self.assertIn("README", doc, "and where the reader should go next")


class ImportingThePortPullsInNoEnhancements(unittest.TestCase):
    """The observable counterpart of ``test_no_enhancement_coupling``.

    Run in a fresh subprocess, for the same reason the sibling test gives: the
    parent process has already imported half the world, so ``sys.modules`` here
    would say nothing about what ``import arrayprobe`` on its own does.
    """

    def _run(self, script: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-c", script],
                              capture_output=True, text=True, timeout=120,
                              cwd=str(_PORT_ROOT))

    def test_enhancements_is_not_imported_as_a_side_effect(self):
        result = self._run(
            "import sys\n"
            "import arrayprobe\n"
            "leaked = [m for m in sys.modules if m.split('.')[0] == "
            "'arrayprobe_enhancements']\n"
            "assert not leaked, leaked\n"
            "print('clean')\n"
        )
        self.assertEqual(result.returncode, 0,
                         f"import arrayprobe pulled in the enhancements package:\n"
                         f"{result.stdout}{result.stderr}")

    @needs_v314_engine
    def test_the_front_door_still_works_with_enhancements_unimportable(self):
        """Every exported name must resolve with ``enhancements_uiops/`` uninstalled --
        the state a fresh clone of the port alone is actually in."""
        result = self._run(
            "import builtins\n"
            "real_import = builtins.__import__\n"
            "def blocking_import(name, *a, **kw):\n"
            "    if name == 'arrayprobe_enhancements' or name.startswith(\n"
            "            'arrayprobe_enhancements.'):\n"
            "        raise ImportError(name + ' deliberately hidden for this test')\n"
            "    return real_import(name, *a, **kw)\n"
            "builtins.__import__ = blocking_import\n"
            "import arrayprobe\n"
            "missing = [n for n in arrayprobe.__all__ if not hasattr(arrayprobe, n)]\n"
            "assert not missing, missing\n"
            "print('ok')\n"
        )
        self.assertEqual(result.returncode, 0,
                         f"the public surface is incomplete without enhancements:\n"
                         f"{result.stdout}{result.stderr}")


if __name__ == "__main__":
    unittest.main()
