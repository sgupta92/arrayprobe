# SPDX-License-Identifier: BSD-3-Clause
"""airspeed and size-dependent depth of field -- the depth of field from the published literature instead of the engine's constant.

**Opt-in, individually selectable**: the registry row is ``default_on=False``, so
``arrayprobe-enhanced run`` applies it only when a config names ``published_dof = true``.
This module rescales the ``sd`` file's volume-normalised variables, so it *moves numbers*.
It was registered default-OFF, then flipped ON (author, 2026-09-15: *"it
should be for all by default, but users should be able to specify individual ones if someone
is an expert user or wants to isolate impact of each of them"*) under the then-current
opt-out scheme, and returned to OFF on 2026-09-16 when a cold-start usability audit measured
that scheme applying it to a run whose config named only ``outoffocus``. The author's operative
half -- *specify individual ones* -- is now the only route. Every public entry point here
keeps ``enabled=False``; OFF returns the engine's own value unchanged
(byte-identical, tested).

What the engine does
--------------------
``calc_sa_randombins.m`` (byte-identical v3.1.4 <-> v3.5; ported once, at
``src/arrayprobe_uiops/sample_area.py:66,84-88`` and shared by both engines):
``:40`` ``lambda = 680e-6`` mm; ``:42`` ``DOF = 20.52*radius.^2*1000`` for ``probetype == 2``
(the SPEC 2D-S and HVPS, ``sizeDist.m`` probe blocks); ``:44`` ``DOF = 6*radius.^2/lambda``
otherwise; ``:47`` capped at ``armdst``. No airspeed enters it anywhere.

What the two papers say (both opened and read, 2026-09-14)
----------------------------------------------------------
**Gurganus & Lawson (2018)**, JTECH 35, 1533-1553, doi:10.1175/JTECH-D-17-0202.1.

* **Eq. (1), p. 1534**: ``DOF = ± c r^2 / lambda`` -- r the drop radius, lambda the laser
  wavelength, c "a 'constant' that can vary with different optical configurations".
* **c = 8 ± 0.2** for the SPEC **2D-128** (a single-channel 2D-S; p. 1533 §1, p. 1538 §4),
  measured with a droplet generator on drops **29 to 67 µm** in diameter and agreeing with a
  Zemax simulation (p. 1534). Fig. 2 (p. 1536) gives the two fits: droplets ``c = 8.11 ± 0.19``,
  Zemax ``c = 8.05 ± 0.09``; the paper quotes Korolev et al. (1998)'s Fresnel value ``8.18``.
* **The ± is a half-width.** Fig. 2's ordinate is ``DOF_50% / 2``; Fig. A2 (p. 1552) draws the
  2D-S's "Theoretical DOF (±8 r^2/lambda)" as a box whose full width is twice ``8 r^2/lambda``.
  So the total depth of field is ``2 c r^2 / lambda`` (*derived* from those two figures; SODA-2's
  ``soda2_samplearea.pro:20`` writes the same ``2*dofconst*r2overlam``, "*2 is for the +/-").
* **CIP: no constant is determined.** The manufacturer's ``c = 3`` (p. 1534-1535); the CIP17's
  measured DOF was about twice that idealised value (Fig. A2, p. 1552), and "a more thorough
  study of the DOF of modern CIPs is warranted". Refused below.
* **Airspeed**, conclusions, p. 1550: "2D-S particle data >= 10 µm in size ... which are collected
  at airspeeds up to 190 m s-1 (and possibly as high as 230 m s-1 based on previous results from
  Lawson et al. 2006), are not degraded by the time response of the probe electronics." For the
  2D-S the published airspeed dependence is therefore **none, inside that envelope**; this module
  refuses a TAS above 190 m/s rather than extend the claim.
* **The 2D-S wavelength is not in this paper** (nor in Baumgardner & Korolev, whose probes are
  HeNe). This module takes ``0.785 µm`` from two sources, neither of them the two papers:
  SODA-2 ``SODA2/abansemer-soda2-afcea15/soda2_probespecs.pro:955`` (``x.wavelength=0.785e-6``,
  "2D-S Horizontal Array") and the Jeju-2024 workshop README's probe table (Bansemer, NSF-NCAR),
  which lists "SPEC 2D-S ... 785".
  Lawson et al. (2006, JTECH 23, p. 1463) writes only "for the sake of example ... lambda = 0.8".
  **Flagged for the author**: a SPEC-published wavelength would be the better citation.

**Baumgardner & Korolev (1997)**, JTECH 14, 1224-1229 (the "airspeed" paper).

* Their probes are the PMS **260X** (1D) and **2D-C** (p. 1225), with HeNe lambda = 0.6328 µm
  (p. 1225, below Eq. 1; p. 1226). Knollenberg's ``Z = ±3 r^2 / lambda`` is their Eq. (1).
* The algorithm (§3, pp. 1226-1228): the Fresnel shadow of an opaque disc, Eqs. (2)-(5); a
  first-order electronic roll-off ``V_m(t) = V_0 (1 - exp(-t/tau))``, Eq. (6), with the NCAR
  260X's measured ``tau ≈ 0.4 µs`` (p. 1227); Z is iterated until the rolled-off profile just
  meets the 50 % (2D) or 67 % (1D) threshold (p. 1228).
* Their fit, **Eq. (7), p. 1228**: ``DOF = C0(v) + C1(v) D + ... + C5(v) D^5``, coefficients in
  **Table 1 (67 %, p. 1227)** and **Table 2 (50 %, p. 1228)**, at v = 20, 40, ..., 160 m/s, "only
  valid for DOF <= 61 mm". Units are not printed beside Eq. (7); Fig. 5's axes (Droplet Diameter
  (µm), Depth-of-Field (mm)) give D in µm and DOF in mm -- *derived*, and the tabulated
  curves are checked to fall monotonically with airspeed (``test_published_dof``), which a
  wrong unit or a lost minus sign would break.

What this module will and will not do
-------------------------------------
* **2D-S (probetype 2, probename "2DS") -- built.** Replace the engine's DOF with
  ``min(2 c r^2 / lambda, armdst)``, c = 8 (± 0.2 exposed as :data:`GL2018_C_SIGMA`), lambda =
  0.785 µm. Airspeed-independent by G&L's measurement; TAS > 190 m/s is refused.
* **HVPS -- refused.** The engine applies its probetype-2 constant to the HVPS as well
  (``sizeDist.m`` HVPS blocks set ``probetype = 2``), but neither paper measured an HVPS.
* **CIP / PIP -- refused**: G&L determine no constant (above).
* **2D-C -- the Baumgardner & Korolev tables are transcribed** (:func:`bk1997_dof_mm`) **but not
  wired into the sample area**, for two reasons neither paper resolves, both **named for the
  author**: (1) the tables exist only at eight airspeeds and the paper gives no rule between them
  -- a real flight's TAS is never exactly 100 m/s; (2) they were computed for tau = 0.4 µs,
  while Lawson et al. (2006, p. 1464) measured a 2D-C's 1/e response as 760 ns and quote
  Strapp et al. (2001)'s 600 ns average -- so the table is the paper's 260X-like probe, not a
  given 2D-C. Reproducing Eqs. (2)-(6) directly would need a third missing piece: how Eq. (6) is
  applied to a *profile* (Fig. 4 suggests a first-order filter in time; the text says only "this
  profile is then modified with Eq. (6)").

Everything else in the sample area (the effective array width, ``sa_method``) is the engine's own:
the correction multiplies the engine's ``sa`` by ``DOF_new / DOF_old`` per bin, so the only number
it changes is the depth of field.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

__all__ = [
    "GL2018_C",
    "GL2018_C_SIGMA",
    "GL2018_TAS_MAX_MS",
    "GL2018_FIT_DIAMETER_UM",
    "SPEC_2DS_WAVELENGTH_UM",
    "ENGINE_PT2_COEFF_PER_MM",
    "BK1997_TABLE1_67PCT",
    "BK1997_TABLE2_50PCT",
    "BK1997_DOF_MAX_MM",
    "ProbeNotCovered",
    "engine_dof_mm",
    "published_dof_mm",
    "dof_ratio",
    "published_sample_area",
    "bk1997_dof_mm",
    "corrected_sd_file",
    "VOLUME_NORMALISED",
]

#: Gurganus & Lawson (2018) p. 1534: "c = 8 ± 0.2" for the 2D-128 (single-channel 2D-S).
GL2018_C = 8.0
GL2018_C_SIGMA = 0.2
#: G&L (2018) p. 1550: 2D-S data >= 10 µm are not degraded by time response "at airspeeds up
#: to 190 m s-1". Above this the paper makes no claim, so this module refuses.
GL2018_TAS_MAX_MS = 190.0
#: G&L (2018) p. 1534: "Droplets ranging from 29 to 67 µm in diameter" -- the range c was fit on.
GL2018_FIT_DIAMETER_UM = (29.0, 67.0)
#: NOT from either paper -- SODA-2 soda2_probespecs.pro:955 and the Jeju-2024 README
#: probe table. See the module docstring.
SPEC_2DS_WAVELENGTH_UM = 0.785
#: calc_sa_randombins.m:42 -- ``DOF = 20.52*radius.^2*1000`` (radius in mm, DOF in mm).
ENGINE_PT2_COEFF_PER_MM = 20.52 * 1000

#: Baumgardner & Korolev (1997) Table 1 (67 % threshold, p. 1227): airspeed (m/s) ->
#: for Eq. (7). Transcribed from the printed table; the PDF's text
#: layer renders every minus sign as a leading "2", so each sign was read off the page image
#: and checked against the column's significant-figure count.
BK1997_TABLE1_67PCT: dict[int, tuple[float, ...]] = {
    20: (1.3964, -0.10214, 4.1531e-4, 1.1465e-4, -1.1330e-6, 3.7223e-9),
    40: (-5.7719, 0.52910, -1.7377e-2, 2.6352e-4, -1.4367e-6, 2.9751e-9),
    60: (-9.2140, 0.53279, -1.0145e-2, 7.8102e-5, -1.1907e-8, -6.3819e-10),
    80: (28.411, -1.9376, 4.8343e-2, -5.4732e-4, 2.9583e-6, -5.7928e-9),
    100: (86.900, -4.5545, 8.9680e-2, -8.1728e-4, 3.5481e-6, -5.7224e-9),
    120: (55.890, -2.2446, 3.1339e-2, -1.7650e-4, 3.7742e-7, 0.0),
    140: (-183.100, 7.6788, -0.12551, 9.9483e-4, -3.7501e-6, 5.4632e-9),
    160: (-86.398, 3.1253, -4.4865e-2, 3.1517e-4, -1.0242e-6, 1.2817e-9),
}
#: Baumgardner & Korolev (1997) Table 2 (50 % threshold -- the 2D probes, p. 1228).
BK1997_TABLE2_50PCT: dict[int, tuple[float, ...]] = {
    20: (1.6357, -0.26909, 1.4332e-2, -1.2411e-4, 9.9836e-7, -3.1903e-9),
    40: (1.4101, -0.14014, 2.4316e-3, 1.1017e-4, -9.6296e-7, 2.9412e-9),
    60: (-2.0261, 0.29372, -1.5199e-2, 3.6032e-4, -2.6309e-6, 7.3223e-9),
    80: (-13.340, 1.2062, -4.1064e-2, 6.5974e-4, -4.2674e-6, 1.0707e-8),
    100: (-17.934, 1.3219, -3.6523e-2, 4.7391e-4, -2.4150e-6, 4.7395e-9),
    120: (-19.326, 1.1053, -2.3048e-2, 2.1603e-4, -5.4557e-7, 0.0),
    140: (46.943, -3.4065, 9.2008e-2, -1.1651e-3, 7.2186e-6, -1.6605e-8),
    160: (125.88, -7.7577, 0.18109, -2.0087e-3, 1.0829e-5, -2.2128e-8),
}
#: B&K (1997) p. 1228, under Eq. (7): "this is only valid for DOF <= 61 mm".
BK1997_DOF_MAX_MM = 61.0

#: Every sd variable the engine divides by ``svol2`` (the v3.1.4 engine's size distribution and
#: ``arrayprobe_uiops/sizedist.py:1138-1150``), and so scales as 1/DOF per bin. ``count``,
#: ``re``, ``ar``, ``mean_*`` and ``Reject_ratio`` are computed before ``sa2`` exists and do not.
VOLUME_NORMALISED = ("conc_minR", "conc_AreaR", "total_area", "Calcd_area", "mass", "massBL",
                     "vt", "Prec_rate", "area", "habitsd", "habitmsd")


class ProbeNotCovered(ValueError):
    """The probe (or the flight's airspeed) is outside what the two papers measured."""


def _refuse_probe(probe: str) -> None:
    reasons = {
        "HVPS": "neither Gurganus & Lawson (2018) nor Baumgardner & Korolev (1997) measured an "
                "HVPS depth of field (the engine applies its 2D-S constant to it, "
                "calc_sa_randombins.m:42 via probetype 2)",
        "CIP": "Gurganus & Lawson (2018) determine no CIP constant: the manufacturer's c = 3 "
               "(p. 1534-1535) and a CIP17 measured at about twice it (Fig. A2, p. 1552)",
        "PIP": "neither paper measured a PIP",
        "2DC": "Baumgardner & Korolev (1997) tabulate Eq. (7) at eight airspeeds with no rule "
               "between them, for tau = 0.4 us (a 2D-C measured 760 ns, Lawson et al. 2006 "
               "p. 1464) -- unresolved; bk1997_dof_mm() evaluates the table as printed",
    }
    if probe != "2DS":
        raise ProbeNotCovered(
            f"published_dof: probe {probe!r} is not covered: "
            + reasons.get(probe, "neither paper measured it"))


def _check_tas(tas) -> None:
    tas = np.asarray(tas, dtype=float)
    if tas.size == 0 or not np.all(np.isfinite(tas)):
        raise ProbeNotCovered(
            "published_dof: a finite TAS is required to check Gurganus & Lawson (2018)'s "
            "190 m/s envelope (p. 1550)")
    if np.any(tas > GL2018_TAS_MAX_MS):
        raise ProbeNotCovered(
            f"published_dof: TAS up to {float(tas.max()):.1f} m/s exceeds the "
            f"{GL2018_TAS_MAX_MS:g} m/s to which Gurganus & Lawson (2018, p. 1550) found the "
            "2D-S free of time-response degradation")


def engine_dof_mm(bins_mid_mm, armdst: float, probetype: int) -> np.ndarray:
    """``calc_sa_randombins.m:40-47``'s DOF, capped at ``armdst`` -- the engine's number."""
    radius = np.asarray(bins_mid_mm, dtype=float) / 2
    if probetype == 2:
        dof = ENGINE_PT2_COEFF_PER_MM * radius ** 2
    else:
        dof = 6 * radius ** 2 / (680 * 1e-6)
    return np.minimum(dof, armdst)


def published_dof_mm(bins_mid_mm, armdst: float, *, c: float = GL2018_C,
                     wavelength_um: float = SPEC_2DS_WAVELENGTH_UM) -> np.ndarray:
    """G&L (2018) Eq. (1), total width ``2 c r^2 / lambda``, capped at ``armdst`` as the engine
    caps its own (``calc_sa_randombins.m:47``)."""
    radius = np.asarray(bins_mid_mm, dtype=float) / 2
    return np.minimum(2 * c * radius ** 2 / (wavelength_um * 1e-3), armdst)


def dof_ratio(bins_mid_mm, armdst: float, *, probe: str, tas, c: float = GL2018_C,
              wavelength_um: float = SPEC_2DS_WAVELENGTH_UM) -> np.ndarray:
    """``DOF_published / DOF_engine`` per bin, after the probe and TAS refusals."""
    _refuse_probe(probe)
    _check_tas(tas)
    return (published_dof_mm(bins_mid_mm, armdst, c=c, wavelength_um=wavelength_um)
            / engine_dof_mm(bins_mid_mm, armdst, probetype=2))


def published_sample_area(bins_mid, res, armdst, num_diodes, sa_method, probetype, *,
                          probe: str, tas=None, enabled: bool = False,
                          c: float = GL2018_C,
                          wavelength_um: float = SPEC_2DS_WAVELENGTH_UM) -> list[float]:
    """Drop-in for ``arrayprobe.sample_area.calc_sa_randombins`` with the DOF replaced.

    ``enabled=False`` (the default) returns the engine's own list, unchanged. ON multiplies each
    engine sample area by :func:`dof_ratio`, so the effective array width is the engine's.
    """
    from arrayprobe.sample_area import calc_sa_randombins
    sa = calc_sa_randombins(bins_mid, res, armdst, num_diodes, sa_method, probetype)
    if not enabled:
        return sa
    if probetype != 2:
        raise ProbeNotCovered(f"published_dof: probetype {probetype} is not the 2D-S's (2)")
    ratio = dof_ratio(bins_mid, armdst, probe=probe, tas=tas, c=c, wavelength_um=wavelength_um)
    return [float(s * r) for s, r in zip(sa, ratio, strict=True)]


def bk1997_dof_mm(diameter_um, airspeed_ms: int, *, threshold: int) -> np.ndarray:
    """Baumgardner & Korolev (1997) Eq. (7) at a TABULATED airspeed, as printed.

    ``threshold`` is 50 (Table 2, the 2D probes) or 67 (Table 1, the 1D probes). An airspeed
    the tables do not list is refused -- the paper gives no rule between rows -- and so is any
    result above 61 mm or below zero (outside the fit's stated validity).
    """
    table = {50: BK1997_TABLE2_50PCT, 67: BK1997_TABLE1_67PCT}.get(threshold)
    if table is None:
        raise ValueError(f"threshold must be 50 or 67 (B&K 1997 Tables 2 and 1), got {threshold}")
    if airspeed_ms not in table:
        raise ProbeNotCovered(
            f"B&K (1997) tabulate Eq. (7) only at {sorted(table)} m/s; {airspeed_ms!r} is not a "
            "row and the paper gives no rule between rows")
    d = np.asarray(diameter_um, dtype=float)
    dof = sum(cn * d ** n for n, cn in enumerate(table[airspeed_ms]))
    dof = np.asarray(dof, dtype=float)
    if np.any(dof > BK1997_DOF_MAX_MM) or np.any(dof < 0):
        raise ProbeNotCovered(
            "B&K (1997) Eq. (7) is 'only valid for DOF <= 61 mm' (p. 1228); this diameter/"
            "airspeed gives a value outside [0, 61] mm")
    return dof


def corrected_sd_file(sd_path, dst, *, armdst: float, tas, enabled: bool = False,
                      c: float = GL2018_C,
                      wavelength_um: float = SPEC_2DS_WAVELENGTH_UM) -> Path:
    """Write a copy of an sd file with every volume-normalised variable rescaled to the
    published DOF. ``enabled=False`` writes a byte-for-byte variable copy.

    Probe comes from the file's own ``Probe Type`` / ``Probe_Type`` attribute (v3.1.4 / v3.5
    spelling). ``n`` is recomputed from the corrected ``conc_minR`` by the engine's own formula
    (``nansum(conc_minR * bin_dD) / 10``, ``sizedist.py:1557``); ``sample_vol``, where written,
    is multiplied by the ratio.
    """
    import netCDF4

    from arrayprobe_enhancements.pipeline import _copy_netcdf  # one copier, not two
    dst = Path(dst)
    if not enabled:
        _copy_netcdf(sd_path, dst)
        return dst
    with netCDF4.Dataset(sd_path) as src:
        attrs = src.ncattrs()
        probe = src.getncattr("Probe Type" if "Probe Type" in attrs else "Probe_Type")
        bins_mid = np.asarray(src.variables["bin_mid"][:], dtype=float)
    # refusals happen before anything is written
    ratio = dof_ratio(bins_mid, armdst, probe=str(probe), tas=tas, c=c,
                      wavelength_um=wavelength_um)
    _copy_netcdf(sd_path, dst)
    with netCDF4.Dataset(dst, "r+") as ds:
        for prefix in ("", "REJ_"):
            for name in VOLUME_NORMALISED:
                var = ds.variables.get(prefix + name)
                if var is None:
                    continue
                var.set_auto_mask(False)
                vals = np.asarray(var[:])
                # the bin axis is the 'CIPcorrlen' dimension in every such variable
                axis = var.dimensions.index("CIPcorrlen")
                shape = [1] * vals.ndim
                shape[axis] = ratio.size
                var[:] = vals / ratio.reshape(shape)
            if prefix + "n" in ds.variables and prefix + "conc_minR" in ds.variables:
                conc = np.asarray(ds.variables[prefix + "conc_minR"][:])
                dd = np.asarray(ds.variables["bin_dD"][:], dtype=float)
                ds.variables[prefix + "n"][:] = np.nansum(conc * dd[None, :], 1) / 10
        if "sample_vol" in ds.variables:
            sv = ds.variables["sample_vol"]
            sv.set_auto_mask(False)
            axis = sv.dimensions.index("CIPcorrlen")
            vals = np.asarray(sv[:])
            shape = [1] * vals.ndim
            shape[axis] = ratio.size
            sv[:] = vals * ratio.reshape(shape)
    return dst
