# SPDX-License-Identifier: BSD-3-Clause
"""Enforces that this package never crosses into the UIOOPS lineage.

``arrayprobe_soda2_enhancements`` imports ``arrayprobe_soda2`` and nothing else from this
repository. SODA-2 and UIOOPS are two independent processing lineages (this package's own
``__init__.py`` docstring; ``arrayprobe_enhancements.applicability``'s ``ENGINES`` excludes
SODA-2 on the same grounds) -- a correction for one must never delegate to or import from the
other, the way ``arrayprobe_enhancements.wide_hollow_fix`` legitimately imports
``arrayprobe_uiops`` (both UIOOPS engines, one lineage). This is the SODA-2-side half of the
coupling check; ``tests/test_no_enhancement_coupling.py`` is the port-side
half (the port must never reference this package unconditionally).
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src" / "arrayprobe_soda2_enhancements"
_FORBIDDEN_ROOTS = ("arrayprobe", "arrayprobe_uiops", "arrayprobe_enhancements")
# `arrayprobe_soda2` (and its submodules) is the one permitted exception -- it is this
# package's whole reason to exist, packaged inside the `arrayprobe` distribution but a
# distinct import root from bare `arrayprobe`/`arrayprobe.*` (the UIOOPS v3.1.4 port).
_PERMITTED = "arrayprobe_soda2"


def _is_forbidden(module_name: str | None) -> bool:
    if not module_name:
        return False
    if module_name == _PERMITTED or module_name.startswith(_PERMITTED + "."):
        return False
    return any(module_name == root or module_name.startswith(root + ".")
               for root in _FORBIDDEN_ROOTS)


class _ForbiddenImportVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.offending_linenos: list[int] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if _is_forbidden(alias.name):
                self.offending_linenos.append(node.lineno)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if _is_forbidden(node.module):
            self.offending_linenos.append(node.lineno)
        self.generic_visit(node)


class VisitorSelfTest(unittest.TestCase):
    """The synthetic self-test the design asks for: prove the visitor actually flags a
    lineage-crossing import rather than trusting a clean sweep of real files alone."""

    def _offenders(self, src: str) -> list[int]:
        v = _ForbiddenImportVisitor()
        v.visit(ast.parse(src))
        return v.offending_linenos

    def test_flags_import_from_arrayprobe_enhancements(self) -> None:
        src = "from arrayprobe_enhancements import registry\n"
        self.assertEqual(self._offenders(src), [1])

    def test_flags_bare_import_of_arrayprobe(self) -> None:
        src = "import arrayprobe\n"
        self.assertEqual(self._offenders(src), [1])

    def test_flags_import_from_arrayprobe_v35(self) -> None:
        src = "from arrayprobe_uiops.reject import is_it_hollow\n"
        self.assertEqual(self._offenders(src), [1])

    def test_does_not_flag_arrayprobe_soda2(self) -> None:
        src = (
            "from arrayprobe_soda2.aspect_ratio import axis_and_ratio\n"
            "import arrayprobe_soda2.processbuffer_spec\n"
        )
        self.assertEqual(self._offenders(src), [])

    def test_does_not_flag_unrelated_imports(self) -> None:
        src = "import numpy as np\nfrom dataclasses import dataclass\n"
        self.assertEqual(self._offenders(src), [])


class LineageIsolationTests(unittest.TestCase):
    def test_no_module_imports_the_uiops_lineage(self) -> None:
        offenders = []
        for path in sorted(_SRC.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            visitor = _ForbiddenImportVisitor()
            visitor.visit(ast.parse(text, filename=str(path)))
            for lineno in visitor.offending_linenos:
                offenders.append(f"{path.relative_to(_SRC)}:{lineno}")
        self.assertEqual(
            offenders, [],
            "arrayprobe_soda2_enhancements/ must never import arrayprobe, arrayprobe_uiops, "
            f"or arrayprobe_enhancements -- SODA-2 and UIOPS are separate lineages. "
            f"Offender(s): {offenders}",
        )


if __name__ == "__main__":
    unittest.main()
