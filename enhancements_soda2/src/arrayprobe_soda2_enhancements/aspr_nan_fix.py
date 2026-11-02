# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""S2-d: a non-finite ``aspr`` stops being silently read as a perfectly round particle.

``aspect_ratio.pro:105`` -- ``return, aspr < 1.0`` -- is IDL's MIN operator, and for a
non-finite ``aspr`` it returns the *other* (finite) operand: measured under GDL,
``!values.d_nan < 1.0d`` is ``1.0``, not NaN (
``tests/test_soda2_aspect_ratio.py::IdlSemanticsRecorded::
test_nan_lt_one_is_exactly_one`` pins the same IDL fact this port's
``arrayprobe_soda2.aspect_ratio.axis_and_ratio`` faithfully reproduces). That makes
``aspr == 1.0`` overloaded: it means indistinguishably a genuinely round particle, a
single-pixel particle, an empty outline, *or* a circle-fit that never converged and came back
non-finite.

**Correction**: a non-finite ``aspr`` stays non-finite (NaN) instead of being clamped to 1.0,
so a caller histogramming ``aspr`` can tell "round" from "the fit failed" -- exactly the
suggested edit in the finding (``IF finite(aspr) eq 0 THEN return, !values.f_nan``, applied
before the round-off clamp the line was actually written for, which this correction leaves
untouched).

``src/arrayprobe_soda2/aspect_ratio.py`` is never imported for writing and never
modified -- ``axis_and_ratio`` keeps clamping every non-finite ``aspr`` to 1.0, per the
fidelity doctrine. Tests: ``tests/test_aspr_nan_fix.py``.
"""

from __future__ import annotations

import numpy as np

from arrayprobe_soda2_enhancements.registry import EnhancementSpec, register

from ._aspect_ratio_recompute import recompute

__all__ = ["corrected_aspr"]


def corrected_aspr(x_ind, y_ind_adjusted, circle) -> tuple[np.float64, np.float32]:
    """``(aspr, orientation)`` with S2-d corrected: a non-finite ``aspr`` returns NaN
    rather than being clamped to 1.0. S2-f's clamp (`den`, `:66`) is left exactly as the
    port computes it -- this module corrects one finding only; see :mod:`den_clamp_fix` for
    the other, and note the two compose (both flags can be set together via
    :func:`arrayprobe_soda2_enhancements._aspect_ratio_recompute.recompute` directly, should a
    caller ever want both S2-d and S2-f applied at once)."""
    result = recompute(x_ind, y_ind_adjusted, circle, aspr_nan_passthrough=True)
    return result.aspr, result.orientation


register(EnhancementSpec(
    name="aspr_nan_fix",
    summary="A non-finite aspect ratio returns NaN instead of being clamped to the "
            "ordinary value 1.0 (aspect_ratio.pro:105's `<` is MIN, and IDL's `<` "
            "resolves a NaN operand to the OTHER, finite side).",
    finding="S2-d",
    reachability="live",
    entry_point="corrected_aspr",
))
