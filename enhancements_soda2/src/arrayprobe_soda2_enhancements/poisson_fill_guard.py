# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""S4-t -- ``poisson_spot_correct.pro:26``'s condition guarded with ``img_fill gt img_orig``.

Finding: a zero or shrinking fill area drives ``:27`` to ``0/0``
or the square root of a negative, and ``:28``'s ``where``/clamp then lands on index 0 --
``(correction, zd) = (1.0, 0.0)``, the routine's own no-spot default reached by a different
route. The suggested edit: guard ``:26`` with ``img_fill gt img_orig`` (and ``img_fill gt 0``)
so a degenerate area is handled explicitly rather than falling through the clamp.

**Decided (closing the earlier deferral): shipped, and it changes no written value.** For
every finite input the guarded routine returns the same ``correction`` and ``zd`` as the port
-- the equivalence test sweeps a grid of integer areas and the GDL bank's three degenerate
cases. What moves is only the route, visible in the port-tooling field
:attr:`~arrayprobe_soda2.poisson_spot_correct.PoissonCorrection.ip`: ``-1`` ("branch at
``:26`` not taken") instead of ``0`` ("taken, clamped to the first entry"), and no ``0/0`` or
negative square root is evaluated. ``ip`` is not part of IDL's return and the driver reads
only ``correction`` and ``zd`` (``processbuffer_tail.py:290-291``), so applying this
correction through the driver adapter is byte-identical by construction. **Opt-in since
2026-09-28**, not one of ``registry.PROTECTIVE``: measured on real UND 2016-09-14 HVPS-3
data (600 s window, ``CORRECTIONS.md``'s own report) to move zero written bytes with the
correction applied, so there is nothing here confirmed to destroy or corrupt written data.
"""

from __future__ import annotations

import numpy as np
from arrayprobe_soda2.poisson_spot_correct import PoissonCorrection, poisson_spot_correct

from arrayprobe_soda2_enhancements.registry import EnhancementSpec, register

__all__ = ["guarded_poisson_spot_correct"]


def guarded_poisson_spot_correct(img_orig, img_fill) -> PoissonCorrection:
    """``poisson_spot_correct(img_orig, img_fill)`` with S4-t's guard on ``:26``.

    A degenerate area (``img_fill`` not greater than ``img_orig``, or not positive) returns the
    routine's own ``:24-25`` defaults directly with ``ip = -1``; anything else is the port's
    own call, unmodified.
    """
    orig32 = np.float32(img_orig)
    fill32 = np.float32(img_fill)
    if not (fill32 > orig32 and fill32 > 0 and orig32 >= 0):
        return PoissonCorrection(correction=np.float32(1.0), zd=np.float32(0.0), ip=-1)
    return poisson_spot_correct(img_orig, img_fill)


register(EnhancementSpec(
    name="poisson_fill_guard",
    summary="poisson_spot_correct's :26 condition is guarded with img_fill > img_orig >= 0, "
            "so a zero or shrinking fill area takes the explicit no-spot branch instead of "
            "0/0 -> NaN -> the where/clamp at :28. Same correction and zd on every input; "
            "only the route (PoissonCorrection.ip, -1 not 0) differs.",
    finding="S4-t",
    reachability="live",
    entry_point="guarded_poisson_spot_correct",
))
