# SPDX-License-Identifier: BSD-3-Clause
"""Every first-party package is imported from this checkout.

A shared virtual environment can hold editable installs that point at another checkout of
this repository. With only ``src`` on PYTHONPATH, the engines then come from this tree and the
enhancement packages from the other one, and the suite tests code it never meant to. This
check runs in every suite.
"""
import importlib
import os
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]   # tests/<this> -> repository root

# package -> the directory (relative to REPO_ROOT) its source lives under
PACKAGES = {
    "arrayprobe": "src",
    "arrayprobe_uiops": "src",
    "arrayprobe_soda2": "src",
    "uiops": "src",
    "arrayprobe_enhancements": "enhancements_uiops/src",
    "arrayprobe_soda2_enhancements": "enhancements_soda2/src",
}


def _fix_hint():
    roots = sorted({str(REPO_ROOT / d) for d in PACKAGES.values()})
    return 'PYTHONPATH="' + os.pathsep.join(roots) + '"'


class TestPackagesImportFromThisCheckout(unittest.TestCase):
    def test_every_first_party_package_resolves_inside_this_repository(self):
        wrong = []
        for name, rel in PACKAGES.items():
            if not (REPO_ROOT / rel / name).is_dir():
                continue   # package not shipped in this tree
            with self.subTest(package=name):
                mod = importlib.import_module(name)
                origin = Path(mod.__file__).resolve()
                try:
                    origin.relative_to(REPO_ROOT)
                except ValueError:
                    wrong.append(f"{name} imported from {origin}")
        self.assertEqual(
            wrong, [],
            f"first-party packages imported from outside {REPO_ROOT}: {wrong}. "
            f"Current PYTHONPATH={os.environ.get('PYTHONPATH', '')!r}. Fix: {_fix_hint()}")

    def test_the_package_table_covers_every_package_under_a_src_root(self):
        for rel in sorted(set(PACKAGES.values())):
            src = REPO_ROOT / rel
            if not src.is_dir():
                continue
            for d in src.iterdir():
                if (d / "__init__.py").is_file():
                    self.assertIn(d.name, PACKAGES,
                                  f"{d} is a first-party package this check does not cover")


if __name__ == "__main__":
    unittest.main()
