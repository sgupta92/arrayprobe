# SPDX-License-Identifier: BSD-3-Clause
"""Liquid water content from a particle size distribution.

Ported from: lwc_calc.m (UIOOPS v3.1.4; byte-identical in v3.5, so one translation serves both).
This is its one home: ``arrayprobe.lwc`` re-exports it lazily, on first access (nothing outside
the v3.1.4 package imports it, and code the engines share lives in the v3.5 engine).
"""

#: Declared so the public surface is explicit rather than whatever happens not to
#: start with an underscore. The Phase-1 shims at ``<name>.py`` in the original flat layout import
#: these names directly, CONSTANTS INCLUDED -- omitting a constant here would not
#: break them, but omitting one from a shim does, which is why they are listed.
__all__ = [
    "lwc_calc",
]

import math
from collections.abc import Iterable


def lwc_calc(conc: Iterable[Iterable[float]], bins: Iterable[float]) -> list[float]:
    """Liquid water content (g/m^3) from concentration and bin diameters.

    Direct port of lwc_calc.m.

    conc: sequence of rows (one per time step), each a sequence of
          concentrations (cm^-3) per bin.
    bins: sequence of bin (mid-point) diameters, in microns.

    Returns a list of LWC values, one per row of `conc`.

    Note: unlike single_vt.m, the original lwc_calc.m does NOT
    override MATLAB's built-in `pi`, so it gets full double-precision
    pi -- this port uses math.pi accordingly (not the 3.1415926
    literal used elsewhere in the source).
    """
    bins = list(bins)
    volume_cm3 = [(math.pi / 6) * (b * 1e-4) ** 3 for b in bins]

    lwc = []
    for row in conc:
        # ``strict=False`` is stated explicitly, and it is NOT a formality.
        #
        # ``row`` and ``volume_cm3`` are not provably the same length here:
        # ``conc`` and ``bins`` are both caller-supplied and this function is
        # public API (re-exported by the Phase-1 ``lwc`` shim).  The port's only
        # internal caller -- ``sizedist.py:1379``, ``sizeDist.m:1627`` -- does
        # pass matched lengths, but the zip cannot see that.
        #
        # What MATLAB does on a mismatch is a *third* thing, neither truncation
        # nor a Python exception.  ``lwc_calc.m:6`` reads
        #
        #     sum(conc(:,:) .* pi/6 * (bins(:)*(1e-4)) .^3, 2)
        #
        # and ``.*`` / ``*`` share precedence left-to-right, so the last operator
        # is a *matrix* product ``(T,N) * (N,1)``, not an element-wise one; the
        # trailing ``sum(...,2)`` is then a no-op on the resulting column.  A
        # length mismatch is therefore MATLAB's "Inner matrix dimensions must
        # agree" error, i.e. it is outside the original's contract entirely.
        #
        # Turning this into ``strict=True`` would convert today's silent
        # truncation into a Python exception.  That is a behaviour change on an
        # input the original refuses to process at all, so it is a fidelity
        # decision (what should the port do where MATLAB dies?) and not a lint
        # autofix: any behavior-changing deviation must be an
        # opt-in flag.  Left as-is deliberately; the explicit ``False`` records
        # that the default was chosen rather than overlooked.
        total = sum(c * v for c, v in zip(row, volume_cm3, strict=False))
        lwc.append(total * 1e6)
    return lwc
