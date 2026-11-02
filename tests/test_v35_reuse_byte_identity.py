# SPDX-License-Identifier: BSD-3-Clause
"""Guards the licence for arrayprobe_uiops's reuse of the v3.1.4 port.

WHAT THIS PROTECTS. arrayprobe_uiops (started 2026-09-10, the real v3.5 port) reuses several
v3.1.4-port Python modules wholesale rather than re-translating them, on the
grounds that their MATLAB/C++ source is byte-identical between v3.1.4 and
v3.5 -- see ``arrayprobe_uiops.__init__``.
That claim was true when measured on 2026-09-10; nothing pins it. If a future
UIOOPS point release (or a local edit to either tree) makes one of these files
diverge, the reuse silently stops being licensed and nothing would notice --
the same shape of failure the project's own doctrine names directly ("a rule
addressed to attention is not a control"; ``guards-must-be-executed`` memory).
This test hashes every file in the reuse list against both trees and fails
the moment any pair disagrees, rather than trusting the list to stay true.

Both trees are vendored and tracked in git (``UIOPS-v3.1.4/``, ``UIOPS-v3.5/``),
so this test runs on every clone rather than being skipped;
``test_upstream_tree_is_unmodified.py`` is what guards against either tree being locally edited.
"""

import hashlib
import unittest
from pathlib import Path

from tests import _upstream  # noqa: E402
from tests._repo import repo_only

REPO_ROOT = Path(__file__).resolve().parents[1]
V314_TREE = _upstream.source("uiops314")
V35_TREE = _upstream.source("uiops35")

# The 18 shared files measured byte-identical between v3.1.4 and v3.5 on
# 2026-09-10. Only files this
# package (or a module it re-exports from) actually reuses belong here --
# this is a licence list, not a full identical-file inventory.
REUSED_FILES = [
    "IntArrAnalysis.m",
    "ParticlePerimeter.m",
    "calc_sa_randombins.m",
    "dropsize.m",
    "hhmmss2insec.m",
    "insec2hhmmss.m",
    "loadTASinfo.m",
    "lwc_calc.m",
    "read_binary.m",
    "read_binary_DMT.m",
    "read_binary_PMS.m",
    "read_binary_SEA.m",
    "runImgProc.m",
    "runImgProc_example.m",
    "runSizeDistPECAN.m",
    "runSizeDist_example.m",
    "single_vt.m",
    "CGAL_RectSize.cpp",
]


def setUpModule():
    # Raised here rather than at import: an import-time SkipTest crashes
    # ``python -m unittest tests.<module>``, where ``discover`` reports it as a skip.
    _upstream.require("uiops314")
    _upstream.require("uiops35")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@repo_only
@unittest.skipUnless(V35_TREE.is_dir(), f"{V35_TREE} is not distributed with the package")
class TestReuseIsStillLicensed(unittest.TestCase):
    def test_every_reused_file_is_still_byte_identical(self):
        mismatches = []
        for name in REUSED_FILES:
            a = V314_TREE / name
            b = V35_TREE / name
            if not a.is_file():
                mismatches.append(f"{name}: missing from v3.1.4 tree ({a})")
                continue
            if not b.is_file():
                mismatches.append(f"{name}: missing from v3.5 tree ({b})")
                continue
            if _sha256(a) != _sha256(b):
                mismatches.append(f"{name}: diverged between v3.1.4 and v3.5")
        self.assertEqual(
            mismatches, [],
            "arrayprobe_uiops's reuse-from-v3.1.4-port licence no longer holds "
            "for: " + "; ".join(mismatches) + ". Re-translate the affected "
            "file for v3.5 rather than reusing arrayprobe's version.",
        )

    def test_reused_list_is_a_subset_of_the_measured_identical_set(self):
        # Guards the list itself, not just its members: every name here must
        # actually be identical right now, independent of the assertion above
        # (so a typo'd filename that happens to not exist can't hide inside
        # a passing "missing from both trees" pair).
        for name in REUSED_FILES:
            a = V314_TREE / name
            b = V35_TREE / name
            self.assertTrue(a.is_file(), f"{a} does not exist")
            self.assertTrue(b.is_file(), f"{b} does not exist")


if __name__ == "__main__":
    unittest.main()
