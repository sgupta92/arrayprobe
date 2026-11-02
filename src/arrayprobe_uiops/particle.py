# SPDX-License-Identifier: BSD-3-Clause
"""The particle-image coercion shared by both UIOOPS ports.

Moved verbatim from ``arrayprobe/particle.py``, which re-exports these names, so
``arrayprobe.particle.shadow_mask is arrayprobe_uiops.particle.shadow_mask``.  The
module imports only NumPy, so the v3.1.4 package can load it without loading the
v3.5 engine.  The encoding and its rationale are documented in
``arrayprobe/particle.py``.
"""

from __future__ import annotations

import numpy as np

__all__ = ["SHADOWED", "LIT", "shadow_mask"]

#: The character MATLAB uses for a shadowed diode -- particle present.
SHADOWED = "0"

#: The character MATLAB uses for a lit diode -- no particle.
LIT = "1"

_SHADOWED_ORD = ord(SHADOWED)


def shadow_mask(c) -> np.ndarray:  # type: ignore[no-untyped-def]
    """Coerce a particle image to the canonical boolean array (``True`` = shadowed).

    Four input forms are recognised, covering everything the pipeline produces:

    * a boolean array -- returned as-is (already canonical);
    * a string/bytes array -- compared against ``'0'``, the MATLAB char matrix;
    * an integer array containing values above 1 -- treated as raw ASCII codes,
      the char matrix as it arrives from a netCDF ``short``/``byte`` variable;
    * any other integer array -- treated as 0/1 truth values.

    The "above 1" test is what separates the last two cases, and it is decidable
    because the two encodings share no values: an ASCII image contains only 48
    and 49, a truth image only 0 and 1.  An all-shadowed ASCII image is all 48s,
    so its maximum is 48; an all-lit truth image is all 0s.  The one genuinely
    ambiguous input is an *empty* array, which both readings send to the same
    empty result.
    """
    a = np.asarray(c)
    if a.dtype.kind == "b":
        return a
    if a.dtype.kind in "SU":
        return a == SHADOWED
    if a.dtype.kind in "iu" and a.size and a.max() > 1:
        return a == _SHADOWED_ORD
    return a.astype(bool)
