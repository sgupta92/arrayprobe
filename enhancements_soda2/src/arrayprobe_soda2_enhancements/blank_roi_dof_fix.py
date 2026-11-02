# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""S4-v: a blank ROI is accepted as within depth of field.

``binary_dof.pro:21-31``: ``area = total(bitimage)`` is 0.0 for an
all-zero image, which matches none of the named ``CASE`` values (1
through 6) and falls to ``ELSE``; ``neighbor_count`` is also 0, and
``0 ge 0`` is true in IDL, so ``dof`` is set to 1 -- a blank image is
accepted as within depth of field.

**Correction**: the register's own suggested edit -- ``IF area eq 0
THEN return, 0`` immediately after ``:21``, before the ``CASE``.

``src/arrayprobe_soda2/binary_dof.py`` is never imported
for writing and never modified. This module calls the real,
unmodified ``binary_dof`` and overrides only the ``dof`` field when
``area == 0``. Tests: ``tests/test_blank_roi_dof_fix.py``.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np
from arrayprobe_soda2.binary_dof import BinaryDof, binary_dof

from arrayprobe_soda2_enhancements.registry import EnhancementSpec, register

__all__ = ["corrected_binary_dof"]


def corrected_binary_dof(bitimage: Any) -> BinaryDof:
    """``d = binary_dof(bitimage, neighbor_count=nc)`` with S4-v
    corrected: a blank (all-zero) ``bitimage`` returns ``dof=0``, not
    the ``ELSE`` branch's ``0 ge 0`` acceptance."""
    result = binary_dof(bitimage)
    if result.area == np.float32(0):
        return replace(result, dof=0)
    return result


register(EnhancementSpec(
    name="blank_roi_dof_fix",
    summary="binary_dof returns dof=0 for a blank (all-zero) image, "
            "instead of falling to the ELSE branch's 0 ge 0 acceptance.",
    finding="S4-v",
    reachability="flagged",
    entry_point="corrected_binary_dof",
))
