# SPDX-License-Identifier: BSD-3-Clause
"""The canonical in-memory particle image, and the MATLAB char matrix it replaces.

UIOOPS carries a particle as a MATLAB **char matrix** ``c`` of shape
``(n_slices, diodenum)`` whose entries are the characters ``'0'`` and ``'1'``.
The encoding is the one photodiodes actually report and is the opposite of the
intuitive reading:

* ``'0'`` -- the diode was **shadowed**: particle present.
* ``'1'`` -- the diode was lit: no particle.

Every ported routine that touches an image agrees on that, because MATLAB spells
it out at each site (``holroyd.m:139``, ``calculate_reject_unified.m:386``,
``imgProc_sm.m:801`` ``sum(c=='0',1)``, ``CGAL_minR.cpp:63`` comparing to 48).

The plan's canonical representation is a boolean array, ``True`` = shadowed, and
:func:`shadow_mask` is the one place that conversion happens.  It accepts the
char matrix too, so a call site can pass whichever form it is holding without
each module inventing its own coercion.

**Why the char matrix cannot simply be dropped.**  Two ported routines do
*bit* arithmetic on it -- ``calculate_reject_unified.m:465-491`` packs sixteen
characters at a time through ``bin2dec`` -- and there the polarity inverts once
more: ``bin2dec`` reads ``'1'`` as a set bit, so the packed integers have bits
set where the particle is **absent**.  :func:`as_char` exists so that layer can
be read against the MATLAB line by line; the packing itself lives with its only
caller, as :func:`arrayprobe.reject._pack`, because it needs that module's
1-based window arguments and its out-of-range behaviour.
"""

from __future__ import annotations

import numpy as np

from arrayprobe_uiops.particle import (  # noqa: F401 -- shared leaf
    _SHADOWED_ORD,
    LIT,
    SHADOWED,
    shadow_mask,
)

__all__ = ["SHADOWED", "LIT", "shadow_mask", "as_char"]


def as_char(shadow) -> np.ndarray:
    """The MATLAB char matrix for a boolean shadow array -- the fidelity view.

    Inverse of :func:`shadow_mask` for boolean input.  Serves to read ported code
    against the MATLAB it came from, and by tests that need to hand a literal
    ``'0'``/``'1'`` matrix to a routine.
    """
    shadow = np.asarray(shadow, dtype=bool)
    return np.where(shadow, SHADOWED, LIT)


