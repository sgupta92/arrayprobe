# SPDX-License-Identifier: BSD-3-Clause
"""Which ``soda2_particlesort.pro`` timing branch each ``op.format`` takes.

``soda2_particlesort.pro:12-16`` set ``truetime = probetime + median(buffertime
- reftime)`` and ``interarrival = difftime`` for every format; only ``SPEC``
(``:21-29``), ``SEA`` (``:30-41``) and ``TXT`` (``:43-46``) override them. The
port's :func:`spec_sort_locals` once routed only ``DMT`` to that default, so
``RAF`` fell through to the SPEC branch (``truetime = buffertime``,
``interarrival = inttime``) and the CAESAR rf05 Fast-2DC real file differed
from GDL in five per-second fields (``tests/test_soda2_raf_realfile_gdl.py``).

Two checks: RAF equals DMT and not SPEC on one input; and a class guard that
every format :func:`soda2_particlesort` admits has its own explicit branch in
:func:`spec_sort_locals` (``SPEC`` being the fall-through), so a format added
to the admission gate without a routing decision fails here.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

import numpy as np

from arrayprobe_soda2 import particlesort
from arrayprobe_soda2.particlesort import spec_sort_locals

SOURCE = Path(particlesort.__file__)


def _x() -> dict[str, np.ndarray]:
    # buffertime - reftime has median 100.25 (upper-middle of four), so the
    # :12 default gives probetime + 100.25; inttime is distinct from the
    # probetime differences so the SPEC branch is distinguishable.
    return {
        "probetime": np.array([1.0, 1.5, 1.25, 2.0]),
        "reftime": np.array([0.0, 0.0, 0.5, 0.25]),
        "buffertime": np.array([100.0, 100.5, 100.75, 100.25]),
        "inttime": np.array([0.0, 0.125, 0.0625, 0.375]),
    }


class RafTakesThePreBranchDefault(unittest.TestCase):
    def test_raf_equals_dmt(self) -> None:
        t_raf, i_raf = spec_sort_locals(_x(), format="RAF")
        t_dmt, i_dmt = spec_sort_locals(_x(), format="DMT")
        np.testing.assert_array_equal(t_raf, t_dmt)
        np.testing.assert_array_equal(i_raf, i_dmt)

    def test_raf_is_probetime_plus_median_and_difftime(self) -> None:
        x = _x()
        truetime, interarrival = spec_sort_locals(x, format="RAF")
        # IDL median of [100, 100.5, 100.25, 100] is the upper middle, 100.25.
        np.testing.assert_array_equal(truetime, x["probetime"] + 100.25)
        np.testing.assert_array_equal(interarrival, [0.0, 0.5, 0.0, 0.75])

    def test_raf_is_not_buffertime_and_inttime(self) -> None:
        x = _x()
        truetime, interarrival = spec_sort_locals(x, format="RAF")
        self.assertFalse(np.array_equal(truetime, x["buffertime"]))
        self.assertFalse(np.array_equal(interarrival, x["inttime"]))

    def test_spec_negative_control_is_buffertime_and_inttime(self) -> None:
        x = _x()
        truetime, interarrival = spec_sort_locals(x, format="SPEC")
        np.testing.assert_array_equal(truetime, x["buffertime"])
        np.testing.assert_array_equal(interarrival, x["inttime"])


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {SOURCE.name}")


def _str_consts(node: ast.AST) -> set[str]:
    return {n.value for n in ast.walk(node)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def admitted_formats(source: str) -> set[str]:
    """The tuple in ``soda2_particlesort``'s ``op.format not in (...)`` gate."""
    fn = _function(ast.parse(source), "soda2_particlesort")
    for n in ast.walk(fn):
        if (isinstance(n, ast.Compare) and isinstance(n.left, ast.Attribute)
                and n.left.attr == "format" and isinstance(n.ops[0], ast.NotIn)):
            return _str_consts(n.comparators[0])
    raise AssertionError("soda2_particlesort's `op.format not in (...)` gate not found")


def routed_formats(source: str) -> set[str]:
    """Every format ``spec_sort_locals`` compares its ``format`` argument with."""
    fn = _function(ast.parse(source), "spec_sort_locals")
    out: set[str] = set()
    for n in ast.walk(fn):
        if (isinstance(n, ast.Compare) and isinstance(n.left, ast.Name)
                and n.left.id == "format"):
            for c in n.comparators:
                out |= _str_consts(c)
    return out


def unrouted_formats(source: str) -> set[str]:
    """Admitted formats with no explicit branch; SPEC is the fall-through."""
    return admitted_formats(source) - routed_formats(source) - {"SPEC"}


class EveryAdmittedFormatIsRouted(unittest.TestCase):
    def setUp(self) -> None:
        self.source = SOURCE.read_text(encoding="utf-8")

    def test_gate_and_routing_are_found(self) -> None:
        self.assertIn("RAF", admitted_formats(self.source))
        self.assertIn("RAF", routed_formats(self.source))

    def test_no_admitted_format_falls_to_the_spec_default(self) -> None:
        self.assertEqual(unrouted_formats(self.source), set())

    def test_guard_fires_on_a_planted_unrouted_format(self) -> None:
        gate = 'if op.format not in ("SPEC", "SEA", "DMT", "RAF"):'
        self.assertEqual(self.source.count(gate), 1)
        planted = self.source.replace(
            gate, 'if op.format not in ("SPEC", "SEA", "DMT", "RAF", "TXT"):')
        self.assertEqual(unrouted_formats(planted), {"TXT"})

    def test_guard_fires_when_raf_routing_is_removed(self) -> None:
        branch = 'if format in ("DMT", "RAF"):'
        self.assertEqual(self.source.count(branch), 1)
        planted = self.source.replace(branch, 'if format == "DMT":')
        self.assertEqual(unrouted_formats(planted), {"RAF"})


if __name__ == "__main__":
    unittest.main()
