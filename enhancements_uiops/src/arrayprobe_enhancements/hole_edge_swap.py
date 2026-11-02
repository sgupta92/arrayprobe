# SPDX-License-Identifier: BSD-3-Clause
"""Corrects `imgProc_sm.m`'s `max_hole_diameter` / `edge_at_max_hole` write-target swap.


``imgProc_sm.m:919-920`` writes each variable into the other's netCDF slot: every proc file
this port (or MATLAB itself) has ever written carries ``max_hole_diameter`` where
``edge_at_max_hole`` belongs and vice versa. There is nothing to *reprocess* -- the raw diode
scan that produced both quantities was correct; only the final write crossed them. So the
correction here is a relabeling of two already-written columns, not a new computation: see
``enhancements_uiops/docs/CORRECTIONS.md`, part `hole_edge_swap.py`` for the full write-up, including why no MATLAB oracle is
needed (the check is the physical invariant ``max_hole_diameter <= edge_at_max_hole``, not a
diff against a corrected reference run that doesn't exist in any UIOOPS tree).

``src/arrayprobe/`` never imports this module and never applies this correction --
the port's own output keeps reproducing the swap exactly, per the fidelity doctrine.
"""

from __future__ import annotations

import numpy as np

__all__ = ["correct_hole_edge_swap"]


def correct_hole_edge_swap(max_hole_diameter, edge_at_max_hole):
    """Swap the two arrays back into their correctly-labeled positions.

    Accepts anything ``numpy.asarray`` accepts (a scalar, a list, a netCDF4
    Variable's ``[:]`` slice, an existing ndarray) and returns two ndarrays,
    the corrected ``(max_hole_diameter, edge_at_max_hole)`` -- deliberately
    the same order as the input, so a caller can unpack in place.
    """
    max_hole = np.asarray(max_hole_diameter)
    edge = np.asarray(edge_at_max_hole)
    return edge.copy(), max_hole.copy()
