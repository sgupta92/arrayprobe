# SPDX-License-Identifier: BSD-3-Clause
"""A published per-instrument-class uncertainty table, shipped with the outputs.

**The gap it fills**: nothing in UIOOPS's output says how far to trust a size,
a concentration or a shape classification -- these are read directly from
Baumgardner et al. (2017, *Meteor. Monogr.* 58, ch. 9, Table 9-2, DOI
10.1175/AMSMONOGRAPHS-D-16-0011.1), the community's own review of measurement
limitations across every in-situ cloud-particle technique, and from Vaillant
de Guélis et al. (2019, *AMT* 12, 2513-2529), a bench-validated per-particle
sizing envelope specific to the 2D-S.

**Table 9-2 gives ranges, not point estimates, and this module does not
narrow them.** The published numbers are 10-50 % (light-scattering size),
10-100 % (imaging size and concentration) and 10-30 %/5-30 % (evaporation and
diffraction water content) -- wide because they cover many instrument models
and cloud regimes at once. Reporting a single invented number inside that
range would be exactly the kind of fabricated precision this project's own
doctrine refuses; :data:`IMAGING_UNCERTAINTY` carries the published bounds
verbatim, and a caller decides what to do with a range, not this module.

**The "5-12 pixels" shape floor is the one number in the table with a direct,
computable consequence for a specific probe**, because a pixel is a physical
size once a probe's diode resolution is known: :func:`shape_floor_diameter_um`
turns it into a micron threshold. For the 2D-S (10 um resolution) that is
50-120 um -- inside this port's own bins 1-5 (below ~55 um), which is *why*
those bins are excluded from the used-bin convention (`docs/
11-glossary.md`), read here as a consequence of the published table rather
than only as a project convention.

**Vaillant de Guélis's envelope is reported only at the two ranges the paper
actually measured**, not interpolated between them -- the paper is a bench
calibration at specific diameters, not a continuous fit, and inventing a
curve through two points the source does not draw would be exactly the kind
of overreach this module exists to avoid. :func:`vaillant_de_guelis_envelope`
returns ``None`` for any diameter outside the two measured bands, honestly,
rather than extrapolating.

Changes no computed number -- reference data and two small computed
consequences of it, the same space as `arm_export.py` and
`poisson_uncertainty.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "UncertaintyRange",
    "IMAGING_UNCERTAINTY",
    "LIGHT_SCATTERING_UNCERTAINTY",
    "shape_floor_diameter_um",
    "vaillant_de_guelis_envelope",
]


@dataclass(frozen=True)
class UncertaintyRange:
    """One instrument class's published uncertainty, Table 9-2 verbatim.

    ``size_pct``/``concentration_pct`` are ``(low, high)`` percent bounds on
    the propagated uncertainty; ``shape_min_pixels`` is ``(low, high)`` pixels
    needed to resolve shape, or ``None`` if the technique cannot derive shape
    at all (Table 9-2 says exactly this of light scattering: "Only SID can
    derive shape").
    """

    size_pct: tuple[float, float]
    concentration_pct: tuple[float, float]
    shape_min_pixels: tuple[float, float] | None


#: Table 9-2's "Imaging" row -- this project's own instrument class (2D-S,
#: HVPS, CIP, PIP). Limitations cited: out of focus, time response,
#: shattering, discretization (size); variable DOF, shattering
#: (concentration); requires 5-12 pixels, out-of-focus drops may look
#: nonspherical (shape).
IMAGING_UNCERTAINTY = UncertaintyRange(
    size_pct=(10.0, 100.0),
    concentration_pct=(10.0, 100.0),
    shape_min_pixels=(5.0, 12.0),
)

#: Table 9-2's "Light scattering" row, for comparison (e.g. against an FCDP
#: or CDP measurement of the same cloud). Cannot derive shape at all.
LIGHT_SCATTERING_UNCERTAINTY = UncertaintyRange(
    size_pct=(10.0, 50.0),
    concentration_pct=(10.0, 30.0),
    shape_min_pixels=None,
)


def shape_floor_diameter_um(diode_resolution_um: float,
                            pixels: tuple[float, float] = (5.0, 12.0)
                            ) -> tuple[float, float]:
    """The physical diameter (um) Table 9-2's pixel-count shape floor implies
    for a probe with the given diode resolution.

    ``pixels`` defaults to :data:`IMAGING_UNCERTAINTY`'s own ``(5, 12)``. For
    the 2D-S (``diode_resolution_um=10``) this returns ``(50.0, 120.0)`` --
    inside this port's own bins 1-5 (below the ~55 um used-bin floor,
    `docs/11-glossary.md`), which is why they are excluded rather
    than only conventionally so.
    """
    lo, hi = pixels
    return (lo * diode_resolution_um, hi * diode_resolution_um)


#: Vaillant de Guélis et al. (2019, *AMT* 12, 2513-2529), read directly and
#: quoted near-verbatim, not carried from a paraphrase: (1) "for the three
#: largest short columnar particles with true D_eq ... 112.8-159.6 ... an
#: uncertainty that spans from -23% to +35% in D_eq" -- non-spherical
#: (columnar) particles; (2) "Circular particles with diameters larger than
#: 806 um are theoretically always recorded by the 2D-S probe without
#: noteworthy size deformation (< 10%)" -- a magnitude bound on circular
#: (near-spherical) particles specifically, represented symmetrically here.
#: The two bands are for different particle shapes, not one continuous curve
#: across all shapes -- see the module docstring for why this stays two
#: measured points rather than an interpolated function.
_VAILLANT_DE_GUELIS_2DS_BANDS: dict[tuple[float, float], tuple[float, float]] = {
    (112.8, 159.6): (-23.0, 35.0),
    (806.0, float("inf")): (-10.0, 10.0),
}


def vaillant_de_guelis_envelope(diameter_um: float) -> tuple[float, float] | None:
    """The measured 2D-S sizing error envelope (percent) at ``diameter_um``,
    or ``None`` if it falls outside the two bands Vaillant de Guélis et al.
    (2019) actually measured -- not extrapolated or interpolated.
    """
    for (lo, hi), envelope in _VAILLANT_DE_GUELIS_2DS_BANDS.items():
        if lo <= diameter_um <= hi:
            return envelope
    return None
