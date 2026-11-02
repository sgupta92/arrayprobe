# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""S6-i: ``.pbp.csv`` and ``.pbp.nc`` write two different values for
the same ``inttime`` column.

The netCDF writer's ``inttime`` variable is populated from
``interarrival[0:istop]`` (``soda2_particlesort.pro:198``), the local
``:22``'s ``x.inttime > 0`` clamps to a floor of 0 for negative values.
The ASCII/CSV writer's ``inttime`` column is *not* one of the two
hand-written special cases at ``:293-294`` (only ``time`` and
``rejectionflag`` are, because they are not tags of ``x``) --
``inttime`` falls through to the generic ``nw eq 1`` branch at
``:289-290`` and prints ``x[i].inttime``, the raw, unclamped tag. A
negative interarrival time therefore appears as the true negative
value in the CSV and as ``0`` in the netCDF file, for the same
particle in the same run.

**Correction**: the register's own suggested edit -- have the CSV
writer print ``interarrival[i]`` for the ``inttime`` column, the same
value the netCDF writer already uses.

``src/arrayprobe_soda2/pbp_writer.py`` is never imported
for writing and never modified -- this module re-derives
``write_pbp_csv_buffer``'s per-row loop (the fix is inside the
column-selection branch itself, not selectable by keyword) with one
extra parameter, ``interarrival``, reusing the port's own
``PBPPROPS``/``_idl_format_scalar``. Tests:
``tests/test_pbp_inttime_consistent.py``.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import IO

import numpy as np
from arrayprobe_soda2.pbp_writer import PBPPROPS, _idl_format_scalar

from arrayprobe_soda2_enhancements.registry import EnhancementSpec, register

__all__ = ["corrected_write_pbp_csv_buffer"]


def corrected_write_pbp_csv_buffer(
    f: IO[str],
    x: Mapping[str, np.ndarray],
    istop: int,
    truetime: np.ndarray,
    rejectionflag: np.ndarray,
    interarrival: np.ndarray,
) -> None:
    """``write_pbp_csv_buffer`` with S6-i corrected: the ``inttime``
    column prints ``interarrival[i]`` -- the same clamped value the
    netCDF writer already uses -- instead of the raw ``x['inttime'][i]``
    tag."""
    numparticles = istop + 1
    for i in range(numparticles):
        parts = []
        for name, _longname, _unit, _dtype, fmt in PBPPROPS:
            if name == "rejectionflag":
                parts.append(_idl_format_scalar(int(rejectionflag[i]), "i0"))
            elif name == "time":
                parts.append(_idl_format_scalar(float(truetime[i]), "f0.5"))
            elif name == "inttime":
                parts.append(_idl_format_scalar(float(interarrival[i]), fmt))
            else:
                parts.append(_idl_format_scalar(x[name][i], fmt))
        f.write(",".join(parts) + "\n")


register(EnhancementSpec(
    name="pbp_inttime_consistent",
    summary=".pbp.csv's inttime column prints the clamped interarrival "
            "value, matching .pbp.nc, instead of the raw (possibly "
            "negative) x['inttime'] tag.",
    finding="S6-i",
    reachability="live",
    entry_point="corrected_write_pbp_csv_buffer",
))
