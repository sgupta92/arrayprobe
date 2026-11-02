# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""S3-e: the zero-area early return hands back defaults that read as
measurements.

``soda2_findsize.pro:9-13`` predefines the output structure with
``centerin:1b``/``allin:0b`` and returns it unchanged when
``area_original`` (``:11-12``) is 0 -- so a particle the routine never
measured reports *centre-in true*, an assertion it never checked.
Combined with S3-d (an integer ``xres``/``yres`` makes ``:11``'s
division integer and can zero ``area_original`` for a real particle),
this flag then feeds ``soda2_reject.pro:15``'s acceptance test.

**Correction**: the register's own smallest suggested edit --
"initialise ``centerin:0b``... changes nothing for any particle that
reaches the measurement." On the zero-area early return only,
``centerin`` is set to 0. Every other field, and every particle whose
``area_original`` is nonzero, is untouched.

``src/arrayprobe_soda2/findsize.py`` is never imported for
writing and never modified -- ``soda2_findsize`` keeps returning
``centerin=1`` on the zero-area path exactly as written, per the
fidelity doctrine. This module calls the real, unmodified
``soda2_findsize`` and only re-derives whether the early return fired,
using the same ``:11-12`` formula (``_idl_div``, already exposed by
the port for exactly this reason -- S3-d's own finding) -- never
re-deriving the acceptance decision itself. Tests:
``tests/test_zero_area_return_fix.py``.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from arrayprobe_soda2.findsize import FindSizeResult, _as_2d, _idl_div, soda2_findsize

from arrayprobe_soda2_enhancements.registry import EnhancementSpec, register

__all__ = ["corrected_soda2_findsize"]


def corrected_soda2_findsize(
    img: Any, xres: Any, yres: Any, voidarea: Any = 0,
) -> FindSizeResult:
    """``out = soda2_findsize(img, xres, yres, voidarea=voidarea)`` with
    S3-e corrected: ``centerin`` is 0, not 1, on the zero-area early
    return."""
    out = soda2_findsize(img, xres, yres, voidarea)

    im = _as_2d(img)
    total_img = im.sum()
    ratio = _idl_div(yres, xres)
    area_original = np.float32(total_img) * ratio

    if area_original == 0:
        out.centerin = 0
    return out


register(EnhancementSpec(
    name="zero_area_return_fix",
    summary="soda2_findsize's zero-area early return sets centerin=0, "
            "not the default 1 -- an unmeasured particle no longer "
            "reports a positive centre-in assertion it never checked.",
    finding="S3-e",
    reachability="flagged",
    entry_point="corrected_soda2_findsize",
))
