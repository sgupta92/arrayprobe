# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""S2-f: the `den` clamp guards a 0/0 that cannot happen, and bites a real, small circle.

``aspect_ratio.pro:66`` -- ``den = sqrt(a^2+b^2) > 1`` -- is IDL's MAX, i.e. ``max(den, 1)``,
written to keep the perpendicular-distance formula at ``:68`` from dividing by zero for a
single-point outline (where ``a == b == 0``, so ``den`` is genuinely 0). It also fires whenever
``sqrt(a^2+b^2)`` is merely *less than* 1 -- a real 3-point circle of radius below one pixel,
reachable once ``yres < xres`` compresses the y axis. There the clamp does not prevent a
division by zero; it inflates the divisor, and every perpendicular distance -- so ``aspr`` --
comes back too small, with no warning.

Measured on the tracked GDL golden (reproduced here against the
real port function rather than transcribed): the clamped and unclamped ``ASPR`` for the same
geometry are 0.6136363636363636 and 0.7272727272727273 -- a 16% understatement.

**Correction**: ``den`` is set to 1 only when it is exactly 0 (the case the clamp actually
guards against), never merely when it is less than 1 -- the finding's own suggested edit,
``IF den eq 0 THEN den = 1``.

``src/arrayprobe_soda2/aspect_ratio.py`` is never imported for writing and never
modified -- ``axis_and_ratio`` keeps the ``> 1`` clamp exactly as written, per the fidelity
doctrine. Tests: ``tests/test_den_clamp_fix.py``.
"""

from __future__ import annotations

import numpy as np

from arrayprobe_soda2_enhancements.registry import EnhancementSpec, register

from ._aspect_ratio_recompute import recompute

__all__ = ["corrected_aspr"]


def corrected_aspr(x_ind, y_ind_adjusted, circle) -> tuple[np.float64, np.float32]:
    """``(aspr, orientation)`` with S2-f corrected: ``den`` is clamped to 1 only when it is
    exactly 0, not whenever it is merely below 1. S2-d's clamp (the final ``aspr < 1.0``,
    ``:105``) is left exactly as the port computes it -- see :mod:`aspr_nan_fix` for that
    finding; the two compose via
    :func:`arrayprobe_soda2_enhancements._aspect_ratio_recompute.recompute` directly."""
    result = recompute(x_ind, y_ind_adjusted, circle, den_zero_guard=True)
    return result.aspr, result.orientation


register(EnhancementSpec(
    name="den_clamp_fix",
    summary="`den` is clamped to 1 only when it is exactly 0 (a single-point outline), "
            "not whenever sqrt(a^2+b^2) < 1 (a real, small 3-point circle, reachable "
            "when yres < xres) -- aspect_ratio.pro:66's `>` is MAX.",
    finding="S2-f",
    reachability="live",
    entry_point="corrected_aspr",
))
