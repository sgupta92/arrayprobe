# SPDX-License-Identifier: BSD-3-Clause
"""Optical Array Probe sample-area geometry.

Ported from: calc_sa_randombins.m (UIOOPS v3.1.4)

Reference: Heymsfield & Parrish (1978) sample-area formulation. The
sa_method=2 correction's 0.72 coefficient is attributed by McFarquhar
et al. (2017, Meteor. Monogr. 58, ch. 11, Eqs. 11-7/11-8) to a separate
1979 NCAR technical note by the same two authors (TN-137+IA), not the
1978 J. Appl. Meteorol. paper -- read directly, not carried from the
1978 citation by assumption.
"""

#: Declared so the public surface is explicit rather than whatever happens not to
#: start with an underscore. The Phase-1 shims at ``<name>.py`` in the original flat layout import
#: these names directly, CONSTANTS INCLUDED -- omitting a constant here would not
#: break them, but omitting one from a shim does, which is why they are listed.
__all__ = [
    "calc_sa_randombins",
]


def calc_sa_randombins(bins_mid, res, armdst, num_diodes, sa_method, probetype):
    """OAP sample area (mm^2) per bin, per Heymsfield & Parrish
    (1978, 1979 -- see this module's docstring for which is which).

    Direct port of calc_sa_randombins.m.

    bins_mid  : sequence of bin midpoints, in MILLIMETRES.
    res       : photodiode resolution / bin width, microns.
    armdst    : probe arm separation, mm.
    num_diodes: number of active photodiodes.
    sa_method : 0 = center-in, 1 = entire-in, 2 = with correction.
    probetype : 2 selects the alternate depth-of-field formula.

    Returns a list of sample areas, one per entry in bins_mid.

    THE UNITS OF ``bins_mid`` are millimetres, not "photodiode-number
    units (not microns -- see original comment)", which is the opposite
    of what the only call site passes. ``sizeDist.m:1562``
    hands it ``cip2_binmid``, built at ``:1541-1543`` from ``kk``, and
    every probe block defines ``kk`` in millimetres -- the 2D-S as
    ``diodesize/2 : diodesize : ...`` with ``diodesize = .010`` mm, the
    HVPS as an explicit micron list divided by 1000. The source's comment
    "you can use this one if you provide midpoint in doide number"
    describes the *commented-out* ``radius = bins_mid .* res/2``, not the
    live ``radius = bins_mid/2``.

    Nothing computed changes either way -- the function does arithmetic on
    whatever it is handed, which is why the wrong reading survived. What
    it would have changed is a caller's. ``tests/test_sample_area_oracle.
    SampleAreaUnitsTest`` pins the reading that is dimensionally coherent:
    ``bins_mid/res`` at ``:29`` is a diode count only if ``bins_mid`` is a
    length in mm.

    Note: the original MATLAB `switch` has no `otherwise` clause, so an
    unsupported sa_method leaves EAWci/EAWri undefined and MATLAB dies at
    `:49` with "'EAWri' undefined" (measured under Octave, and recorded in
    the oracle bank as a status=ERROR case). This port raises ValueError
    explicitly instead -- an intentional, documented deviation, not a
    behavior change for any valid input.
    """
    if sa_method not in (0, 1, 2):
        raise ValueError(f"Unsupported sa_method {sa_method!r}; expected 0, 1, or 2")

    res_mm = res * 1e-3  # microns -> mm
    lambda_mm = 680 * 1e-6  # laser wavelength, mm

    sa = []
    for bin_mid in bins_mid:
        radius = bin_mid / 2
        diameter = 2 * radius

        if sa_method == 0:
            eaw_ci = num_diodes * res_mm
            eaw_ri = eaw_ci
        elif sa_method == 1:
            eaw_ci = (num_diodes - (bin_mid / res_mm) + 1) * res_mm
            eaw_ci = max(eaw_ci, 0)
            eaw_ri = eaw_ci
        else:  # sa_method == 2
            eaw_ci = num_diodes * res_mm
            eaw_ri = eaw_ci + 0.72 * diameter

        if probetype == 2:
            dof = 20.52 * radius ** 2 * 1000
        else:
            dof = 6 * radius ** 2 / lambda_mm
        dof = min(dof, armdst)

        sa.append(dof * eaw_ri)

    return sa
