# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""S4-n: the 2D-S/3VCPI/HVPS4 rollover constant is 2**32 - 1, one tick short of the true
32-bit modulus.

``soda2_processbuffer.pro:318`` (ported at ``processbuffer_spec.py:301``) sets
``rollovervalue = 4294967295.`` (2**32 - 1) for every SPEC probe except HVPS3, whose 16-bit
counter correctly uses ``65536.``. The 32-bit slice counter this branch corrects for wraps at
2**32, not 2**32 - 1, so a real wrap (``x.time < lastclock``) computes an interarrival time
one clock tick short (finding S4-n, measured case ``s2_rollover`` --
``tests/data/gdl_soda2_processbuffer_spec_golden.json``).

**Pure re-derivation, not a driver-loop fork.** ``process_spec_buffer``'s
``SpecBufferParticles`` result already carries everything the non-HVPS3 branch's rollover
arithmetic needs -- ``rawtime`` (== ``x.time``, the branch's own ``xtime`` outside the HVPS3
case) and ``clocktas`` (== ``hk.tas``) -- so :func:`corrected_inttime` recomputes ``inttime``
from those two arrays plus ``op.probetype``/``op.yres`` and the caller's own starting
``lastclock`` (``SpecMisc.lastclock`` *before* the call), reusing the port's own ``_freq``
helper (S4-p) so the only arithmetic difference from ``process_spec_buffer`` is the one
constant this finding names. This is the pattern the fidelity doctrine's "post-processes a
written file" carve-out describes, not a fork of ``processbuffer_spec.py``'s per-image loop
(``:242-310``) -- **HVPS3 is out of scope for this correction**: its branch uses
``x.timetrunc``, which ``SpecBufferParticles`` does not carry, so there is nothing to
recompute from, and S4-n's own finding is specifically about the *other* branch's constant.

``src/arrayprobe_soda2/processbuffer_spec.py`` is never imported for writing and
never modified -- ``:301`` keeps ``rollovervalue = 4294967295.0`` exactly as written, per the
fidelity doctrine. Tests: ``tests/test_rollover_modulus_fix.py``, against the real port run on
the tracked ``s2_spec_raw_fixture``.
"""

from __future__ import annotations

import numpy as np
from arrayprobe_soda2.processbuffer_spec import _freq

from arrayprobe_soda2_enhancements.registry import EnhancementSpec, register

__all__ = ["ROLLOVER_FIXED", "corrected_inttime"]

#: 2**32, the true modulus of the SPEC 2D-S/3VCPI/HVPS4 32-bit slice counter --
#: `processbuffer_spec.py:301`'s `4294967295.0` (2**32 - 1) is one tick short (S4-n).
ROLLOVER_FIXED = 4294967296.0


def corrected_inttime(rawtime, clocktas, probetype: str, yres: float,
                       initial_lastclock: float, *,
                       rollover_constant: float = ROLLOVER_FIXED,
                       res: float | None = None) -> np.ndarray:
    """Recompute the non-HVPS3 SPEC branch's ``inttime`` array with the rollover constant
    corrected. ``res`` (``op.res``, default ``yres``) gates the 3VCPI and HVPS4 clock
    overrides exactly as ``process_spec_buffer`` does.

    ``rawtime``/``clocktas`` are ``SpecBufferParticles.rawtime``/``.clocktas`` -- already
    trimmed to ``num_images``, one entry per kept frame. ``initial_lastclock`` is
    ``SpecMisc.lastclock`` as it stood *before* the ``process_spec_buffer`` call being
    recomputed (mutated in place by that call, so the caller must capture it first).

    ``rollover_constant`` defaults to the fix (:data:`ROLLOVER_FIXED`); pass the port's own
    ``4294967295.0`` to reproduce ``process_spec_buffer``'s ``inttime`` bit for bit --
    ``test_rollover_modulus_fix.py``'s ``Equivalence`` class does exactly that, against a
    real ``process_spec_buffer`` run.

    Raises :class:`ValueError` for ``probetype == "HVPS3"`` -- see the module docstring for
    why that branch cannot be recomputed from ``rawtime`` alone, and is out of scope for S4-n
    besides.
    """
    if probetype == "HVPS3":
        raise ValueError(
            "S4-n is about the non-HVPS3 rollover constant (processbuffer_spec.py:301); "
            "HVPS3 uses x.timetrunc, which SpecBufferParticles does not carry, so "
            "corrected_inttime cannot recompute its inttime from rawtime/clocktas alone.")

    array_res = yres if res is None else res
    rawtime = np.asarray(rawtime)
    clocktas = np.asarray(clocktas, dtype=np.float32)
    n = len(rawtime)
    inttime = np.zeros(n, dtype=np.float64)
    lastclock = float(initial_lastclock)
    for c in range(n):
        xtime = int(rawtime[c])
        # `soda2_processbuffer.pro:309-313`, as `process_spec_buffer` reads them.
        freq = _freq(yres, float(clocktas[c]))
        if probetype == "3VCPI" and array_res == 50:
            freq = _freq(10.0, float(clocktas[c]))
        if probetype == "HVPS4" and array_res == 150:
            freq = _freq(50.0, float(clocktas[c]))
        if xtime < lastclock:
            inttime[c] = ((xtime + rollover_constant) - lastclock) * freq
        else:
            inttime[c] = (xtime - lastclock) * freq
        lastclock = xtime
    return inttime


register(EnhancementSpec(
    name="rollover_modulus_fix",
    summary="The non-HVPS3 SPEC rollover constant is 2**32 (4294967296.0), not "
            "2**32-1 -- a real 32-bit wrap recovers the one clock tick "
            "processbuffer_spec.py:301's 4294967295.0 loses.",
    finding="S4-n",
    reachability="live",
    entry_point="corrected_inttime",
))
