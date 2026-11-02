# SPDX-License-Identifier: BSD-3-Clause
"""Corrects `calculate_reject_unified.m`'s `spot_edge(147)` decimal-point typo
(the upstream missing decimal in spot_edge), for particles that reached the Korolev out-of-focus depth
lookup.

``:54`` declares the table with a missing decimal point (``0757`` parsed as the integer 757,
not ``0.757``); the lookup table is searched with ``find(spot_edge < ratio, 1, 'last')``, so a
value a thousand times too large is skipped, and any particle whose hole-to-edge ``ratio``
falls in ``(0.757, 0.763]`` gets a ``part_z`` one grid step (0.05) too low.

**Depends on C5's correction as a building block.** The lookup ratio is
``max_hole_diameter / edge_at_max_hole`` -- an internal value, never itself written to a proc
file -- but the two variables that feed it are the ones C5 (`hole_edge_swap.py`) found written
to each other's netCDF slot. Recovering the true ratio from a proc file's raw columns means
undoing that swap first; see ``enhancements_uiops/docs/CORRECTIONS.md`, part `spot_edge_fix.py`` for the full derivation and the
real-data check that reproduces every stored ``part_z`` exactly (across all 11,684
Korolev-branch particles in the six validated flights) before any correction is applied,
confirming the mechanism itself is right independent of whether the A3 fix changes anything.

**Reuses the v3.5 engine's own tables** (``arrayprobe_uiops.reject``'s ``_Z_D``, ``_EDGE_0``,
``_SPOT_EDGE``, as float64 arrays) and runs the same ``find(spot_edge < ratio, 1, 'last')``
search that ``arrayprobe_uiops.reject._z_d_lookup`` runs, so only the one table entry differs.
The tables equal the v3.1.4 port's and the vendored v3.5 MATLAB's
(``tests/test_spot_edge_fix_v35_tables.py``), so the module needs no v3.1.4 engine.

Neither engine imports this module or applies this correction -- both engines' ``SPOT_EDGE``
keep the literal ``757.0``, per the fidelity doctrine.
"""

from __future__ import annotations

import numpy as np
from arrayprobe_uiops import reject as _v35_reject

from .hole_edge_swap import correct_hole_edge_swap

__all__ = ["EDGE_0", "SPOT_EDGE", "SPOT_EDGE_FIXED", "Z_D", "correct_part_z_size_factor"]

Z_D = np.asarray(_v35_reject._Z_D, dtype=np.float64)
EDGE_0 = np.asarray(_v35_reject._EDGE_0, dtype=np.float64)
SPOT_EDGE = np.asarray(_v35_reject._SPOT_EDGE, dtype=np.float64)  # [146] stays 757.0


def _find_last(mask) -> int:
    """MATLAB ``find(mask, 1, 'last')`` as a 0-based index; raises when empty."""
    idx = np.flatnonzero(np.asarray(mask, dtype=bool))
    if idx.size == 0:
        raise ValueError("find(..., 1, 'last') is empty")
    return int(idx[-1])


#: SPOT_EDGE with the one-entry decimal-point typo corrected (index 146: 757.0 -> 0.757).
#: A copy; the engines' own tables stay untouched.
SPOT_EDGE_FIXED = SPOT_EDGE.copy()
SPOT_EDGE_FIXED[146] = 0.757


def correct_part_z_size_factor(raw_max_hole_diameter, raw_edge_at_max_hole, stored_part_z):
    """Recompute ``part_z``/``size_factor`` with the A3 typo fixed, for every
    particle that reached the Korolev branch (``stored_part_z > 0`` -- every
    other code path in ``calculate_reject_unified.m`` sets ``part_z`` to
    ``0.0`` or ``-1.0``, per ``reject.py``). Particles that didn't reach the
    branch pass through unchanged (``part_z`` copied as-is, ``size_factor``
    returned as NaN -- this module doesn't know what the port stored there
    for a particle it didn't recompute; a caller wanting the full column
    should combine this with the proc file's own ``size_factor``).

    Takes the raw (still C5-swapped) proc-file columns -- this function
    undoes that swap internally, since the lookup ratio needs the true
    values, not the mislabeled ones.
    """
    raw_max_hole = np.asarray(raw_max_hole_diameter, dtype=np.float64)
    raw_edge = np.asarray(raw_edge_at_max_hole, dtype=np.float64)
    part_z = np.asarray(stored_part_z, dtype=np.float64).copy()
    size_factor = np.full_like(part_z, np.nan)

    true_max_hole, true_edge = correct_hole_edge_swap(raw_max_hole, raw_edge)

    for i in np.flatnonzero(part_z > 0):
        ratio = 0.0 if true_edge[i] <= 0 else true_max_hole[i] / true_edge[i]
        corrected = float(Z_D[_find_last(SPOT_EDGE_FIXED < ratio)])
        part_z[i] = corrected
        size_factor[i] = float(EDGE_0[_find_last(Z_D <= corrected)])

    return part_z, size_factor
