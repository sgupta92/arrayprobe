# SPDX-License-Identifier: BSD-3-Clause
"""The declared public surface of the three packages beside ``arrayprobe``.

``test_public_api.py`` pins ``arrayprobe.__all__`` against a list restated here in a
second place, so widening or narrowing the front door is a deliberate two-file edit.
``uiops``, ``arrayprobe_uiops`` and ``arrayprobe_soda2`` each declare an ``__all__`` too,
and until this file nothing checked any of them: a name could be dropped, renamed or
left pointing at nothing, and a new SODA-2 module could ship without anyone deciding
whether it is part of the declared surface.

What is pinned, per package:

* ``uiops`` -- the version selector. Its ``__all__`` is restated and every name must
  resolve; ``from uiops import *`` must bind exactly that list.
* ``arrayprobe_uiops`` -- deliberately exports nothing at package level; its modules are
  reached through ``uiops.engine()`` or by module path. An export appearing there is a
  surface decision, so it fails here until it is made on purpose.
* ``arrayprobe_soda2`` -- ``__all__`` names submodules. Every one must import, and every
  public submodule *not* in ``__all__`` must be listed in :data:`SODA2_UNDECLARED`, so a
  new module forces a choice (declare it, or record it as undeclared) instead of arriving
  unclassified. Which undeclared modules belong on the declared surface is a packaging
  decision that travels with the package rename; this file records the current split and
  does not make that decision.

Nothing here computes anything, so no number can change because of it.
"""

from __future__ import annotations

import importlib
import pkgutil
import unittest

import arrayprobe_soda2
import arrayprobe_uiops
import uiops

UIOPS_ALL = [
    "VERSIONS",
    "DEFAULT_VERSION",
    "Engine",
    "engine",
    "UnknownVersion",
    "UnknownModule",
    "CATALOGUE",
    "Entry",
    "OVERRIDDEN",
    "SHARED",
    "TOOLING",
    "FORK_ONLY",
    "READ_SHARED",
]

SODA2_ALL = [
    "angles", "aspect_ratio", "binary_dof", "buildindex", "find_radius", "findsize",
    "fillholes", "fixraking", "fixstuckbits", "label_blobs", "min_circle_fast",
    "poisson_spot_correct",
    "fit_poisson", "particlesort", "princomp", "process_2d", "process_hk",
    "processbuffer_spec", "read2dbuffer", "processbuffer_tail", "reject", "sample_area",
    "spec_absolutepointers", "spec_decompress", "spec_index", "spec_read_frame",
    "spec_read_hk", "spec_readint", "timeconv", "update_op",
]

#: Public ``arrayprobe_soda2`` submodules that ship and are tested but are not named in
#: its ``__all__``. Recorded, not endorsed: moving one into ``__all__`` (or making it
#: private) is the decision this list keeps visible.
SODA2_UNDECLARED = frozenset({
    "decompress_dmt", "enhancement_hooks", "export_ascii", "export_ncdf", "export_ncdf_raf",
    "jit_kernels",
    "hvps4_read_frame", "pbp_writer", "probespecs", "process_2d_parallel", "processbuffer_cip",
    "processbuffer_f2dc", "processbuffer_2dc", "backfill", "fix2dimage",
    "pth_readers",
    "reprocess_pbp", "save_writer", "sea",
})


def public_submodules(package) -> set[str]:
    """Names of a package's direct submodules that do not start with an underscore."""
    return {m.name for m in pkgutil.iter_modules(package.__path__)
            if not m.name.startswith("_")}


def unclassified(package, declared, undeclared) -> list[str]:
    """Public submodules in neither the declared nor the recorded-undeclared set."""
    return sorted(public_submodules(package) - set(declared) - set(undeclared))


def _star(module_name: str) -> set[str]:
    namespace: dict[str, object] = {}
    exec(f"from {module_name} import *", namespace)  # noqa: S102 -- the thing under test
    namespace.pop("__builtins__", None)
    return set(namespace)


class UiopsSurface(unittest.TestCase):
    def test_all_matches_the_restated_list(self):
        self.assertEqual(list(uiops.__all__), UIOPS_ALL,
                         "uiops.__all__ changed: update UIOPS_ALL in the same commit")

    def test_every_name_resolves(self):
        self.assertEqual([n for n in uiops.__all__ if not hasattr(uiops, n)], [])

    def test_star_import_binds_exactly_the_list(self):
        self.assertEqual(_star("uiops"), set(UIOPS_ALL))


class V35Surface(unittest.TestCase):
    def test_package_level_exports_nothing(self):
        self.assertEqual(list(arrayprobe_uiops.__all__), [])
        self.assertEqual(_star("arrayprobe_uiops"), set())


class Soda2Surface(unittest.TestCase):
    def test_all_matches_the_restated_list(self):
        self.assertEqual(list(arrayprobe_soda2.__all__), SODA2_ALL,
                         "arrayprobe_soda2.__all__ changed: update SODA2_ALL in the same "
                         "commit, and SODA2_UNDECLARED if a module moved between them")

    def test_no_duplicates(self):
        self.assertEqual(len(SODA2_ALL), len(set(SODA2_ALL)))

    def test_every_declared_name_is_an_importable_submodule(self):
        for name in arrayprobe_soda2.__all__:
            with self.subTest(name=name):
                module = importlib.import_module(f"arrayprobe_soda2.{name}")
                self.assertEqual(module.__name__, f"arrayprobe_soda2.{name}")

    def test_declared_and_undeclared_do_not_overlap(self):
        self.assertEqual(sorted(set(SODA2_ALL) & SODA2_UNDECLARED), [])

    def test_every_undeclared_entry_still_exists(self):
        """A stale entry would let the list grow into a place names go to be forgotten."""
        self.assertEqual(sorted(SODA2_UNDECLARED - public_submodules(arrayprobe_soda2)), [])

    def test_every_public_submodule_is_classified(self):
        self.assertEqual(unclassified(arrayprobe_soda2, SODA2_ALL, SODA2_UNDECLARED), [],
                         "a new arrayprobe_soda2 module: add it to __all__ (and SODA2_ALL) "
                         "or to SODA2_UNDECLARED")

    def test_the_classification_check_fires_on_a_missing_entry(self):
        """The guard is executed, not only read: drop one recorded module and it is named."""
        dropped = sorted(SODA2_UNDECLARED)[0]
        self.assertEqual(
            unclassified(arrayprobe_soda2, SODA2_ALL, SODA2_UNDECLARED - {dropped}),
            [dropped])


if __name__ == "__main__":
    unittest.main()
