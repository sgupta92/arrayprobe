# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""SODA-2 sample area — a port of ``soda2_samplearea.pro``.

Source: ``SODA2/abansemer-soda2-afcea15/soda2_samplearea.pro`` (35 lines),
Aaron Bansemer, NCAR, 2010. Copyright (C) 2016 UCAR, 3-clause BSD (see that
tree's ``LICENSE.txt``); this file is a from-source reimplementation, and the
BSD notice rides with it under that licence's clause 1.

Chosen as the port's first stage because it calls nothing else, and because
every constant in it is attributable to published literature the IDL source
itself cites.

**This docstring said the opposite for a day.** As written on 2026-09-10 it
gave the stage's reason as "no IDL interpreter is installed on this machine and
doctrine layer 2 (a differential oracle) is therefore unavailable". That became
false on 2026-09-11, when GDL ``v1.1.2-52-gfa46d3a4`` was installed and
confirmed running routines out of the vendored tree (``scripts/validation/gdl/``,
and ``tests/test_gdl_oracle.py`` asserts
sixteen bit-decoder cases against answers derived in Python rather than against
the fixture's own contents). The literature-attributable reason above stands on
its own and is why the stage order does not change; the missing-oracle reason
is gone. **A later stage of this port may and should use the differential
oracle** -- the stage order in V1.4 was derived from its absence and is no
longer forced by it.

**The two IDL clamps this routine carries.** In IDL, ``<`` and ``>`` are the
binary MIN and MAX operators, not comparisons -- the single most dangerous
idiom in this codebase to port (design record V1.3). Both appear here:

    dof = dof < prht                  ->  min(dof, prht)
    sa  = (dof*eff_wid * 1e-12) > 0   ->  max(..., 0)

A porter who reads them as Python comparisons gets a boolean where a clamped
float belongs, and nothing raises. ``tests/test_soda2_sample_area.py`` drives
both operands past their clamp boundaries rather than only testing nominal
values, because inside the boundary the two readings can agree by accident.

**One deliberate, documented divergence.** The IDL reaches
``ELSE: stop, 'Sample volume method not supported'`` for an unrecognised
``eawmethod``. IDL's ``stop`` halts into the interactive debugger; it is not
an exception. Measured under GDL on 2026-09-12 (`unsupported_method` in the
bank), the run comes back with no result at all, recorded as ``status=ERROR``.
This port raises ``UnsupportedSampleVolumeMethod`` instead. That is a
divergence, named here rather than left implicit -- the shape of the failure
changes, the fact that it fails does not.

**Precision: this routine runs in SINGLE precision, and that is not cosmetic.**
Established 2026-09-12 by ``gdl_oracle/run_soda2_sample_area_bank.py``, GDL
running the unmodified source. Two separate things were measured, and they
cost very different amounts:

1. **The arithmetic is FLOAT.** ``:17-18`` force ``float(diam)`` and
   ``float(res)``, and every literal in the chain (``1e6``, ``2.0``, ``1.0e4``,
   ``1e-12``) is a bare decimal, which IDL types as FLOAT. Every field this
   routine is fed from ``soda2_probespecs.pro`` is declared ``0.0`` in that
   file's ``base`` structure (``:9-10``), so ``res``, ``armwidth``,
   ``numdiodes``, ``dofconst`` and ``wavelength`` all arrive as FLOAT in
   production. A float64 port disagreed with GDL by **1.4e-7 relative**, which
   is one float32 epsilon and exactly what that reading predicts.
2. **The Lawson sentinel at ``:14`` is type-sensitive, and it costs a factor of
   2.7.** ``IF (wavelength eq 0.785e-6)`` compares against a **FLOAT** literal.
   Fed the same physical wavelength as a DOUBLE, GDL does **not** take the
   branch: ``dofconst`` stays at Knollenberg's 3.0 instead of Lawson's 8.12,
   and every sample area comes out **2.707x** too small. Measured, same
   geometry, only the literal's type changed:

   ==========================  ==========  =====================
   bank case                   dofconst    ``sa[0]``
   ==========================  ==========  =====================
   ``wavelength_float_lawson``  8.12       6.620126927e-09
   ``wavelength_double_lawson`` 3.0        2.445859853e-09
   ==========================  ==========  =====================

   Production takes the FLOAT branch, because probespecs' field is FLOAT. This
   is finding **S1-a**.

**How the port models an IDL type without an IDL type system.** ``diam`` and
``res`` are narrowed to ``float32`` unconditionally, because the source does
that itself. Every other numeric input keeps whatever dtype the caller gives
it, and a plain Python ``float`` is taken as **FLOAT**, since that is what
every caller in the SODA-2 tree passes. NumPy's promotion rules then reproduce
IDL's: pass ``np.float64(0.785e-6)`` and the sentinel misses, exactly as GDL
does. There is no flag for this and there should not be -- a flag would let a
caller select a precision, where the original lets a caller select a *type* and
derives the precision from it.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray

__all__ = [
    "EAW_METHODS",
    "UnsupportedSampleVolumeMethod",
    "sample_area",
]

#: The three effective-array-width methods ``soda2_samplearea.pro``'s CASE
#: block accepts. Any other value reaches its ``stop``.
EAW_METHODS = ("reconstruct", "centerin", "allin")

#: Knollenberg (1970), the IDL's own attribution at ``:12``. FLOAT, as written.
_DOFCONST_DEFAULT = np.float32(3.0)

#: Lawson (2006), for SPEC probes, applied by the source only when the
#: wavelength matches this value exactly (``:14``) -- an exact float compare
#: on a physical constant, preserved as written rather than widened to a
#: tolerance, since widening it would change which probes take this branch.
#:
#: **A float32, deliberately.** ``0.785e-6`` in the IDL is a bare decimal and
#: therefore FLOAT. Written as ``np.float32`` here so NumPy's own promotion
#: reproduces IDL's: against a float32 wavelength the comparison happens in
#: float32 and matches; against a float64 one both widen to float64 and it
#: does *not*. Measured under GDL -- see the module docstring, finding S1-a.
#: A plain ``0.785e-6`` here would have made the port take the SPEC branch in
#: a case where the original does not, by a factor of 2.707.
_SPEC_WAVELENGTH = np.float32(0.785e-6)
_DOFCONST_SPEC = np.float32(8.12)


def _F(value: float) -> np.float32:
    """A bare IDL decimal literal, which is FLOAT and not DOUBLE.

    Spelled out at every site rather than left to NumPy, because a Python
    literal in the same expression would silently promote the whole thing to
    float64 and quietly undo the single precision this routine runs in.
    """
    return np.float32(value)


def _as_idl(value: Any) -> Any:
    """Keep the caller's dtype, treating a plain Python value as IDL FLOAT.

    IDL derives an expression's precision from its operands, and every field
    ``soda2_probespecs.pro`` feeds this routine is declared ``0.0`` -- FLOAT.
    A caller who genuinely means an IDL DOUBLE passes ``np.float64(...)`` (or
    a float64 array), and NumPy's promotion then reproduces what GDL does with
    a DOUBLE, including missing the Lawson sentinel.

    A bare Python list is FLOAT for the same reason a bare Python float is:
    ``np.asarray([...])`` would otherwise default to float64 and silently
    promote the whole computation. That is not hypothetical -- it is what the
    ``dof_supplied_*`` bank cases caught in this module on 2026-09-12.
    """
    if isinstance(value, (np.generic, np.ndarray)):
        return value
    if isinstance(value, (list, tuple)):
        return np.asarray(value, dtype=np.float32)
    # Note, recorded because a mutation that does not fire is a finding and not
    # a detail: deleting the branch above breaks nothing on NumPy 2.5, where
    # ``np.float32([...])`` happens to return a float32 *array* rather than
    # raising. The branch stays because that coincidence is not a documented
    # guarantee, and `TheIdlTypeRule` pins the behaviour directly instead of
    # relying on a mutation to guard it.
    return np.float32(value)


class UnsupportedSampleVolumeMethod(ValueError):
    """Raised where ``soda2_samplearea.pro`` reaches its ``stop`` statement.

    See this module's docstring: IDL's ``stop`` is an interactive debugger
    halt, so this exception is a deliberate divergence, not a reproduction.
    """


def sample_area(
    diam: ArrayLike,
    res: Any,
    armwidth: Any,
    numdiodes: Any,
    eawmethod: str,
    wavelength: Any,
    dofconst: Any = 0.0,
    dof: ArrayLike | None = None,
) -> tuple[NDArray[Any], NDArray[Any], NDArray[Any]]:
    """Sample area in m^2, per ``soda2_samplearea.pro``.

    Returns ``(sa, dof, eff_wid)``. The IDL returns ``sa`` and passes ``dof``
    and ``eff_wid`` back through keyword outputs; a tuple is the Python
    equivalent, and callers that want only the area take ``[0]``.

    Units, as the IDL's own header states them: ``diam`` in micrometres,
    ``res`` in micrometres, ``armwidth`` in centimetres, ``wavelength`` in
    metres. The returned ``dof`` is in micrometres and ``sa`` in m^2.

    ``dofconst=0.0`` means "not specified in the original op structure" and
    selects the literature default, exactly as the IDL's ``IF dofconst eq 0``
    does -- zero is a sentinel here, not a value.

    ``dof=None`` (or an all-zero array) means "compute it", mirroring the
    source's ``IF total(dof) eq 0`` test. Note that test is on the *total*:
    a caller supplying a mixed array of zeros and non-zeros gets the whole
    array kept, not the zeros filled in. Preserved as written.
    """
    if eawmethod not in EAW_METHODS:
        raise UnsupportedSampleVolumeMethod(
            f"Sample volume method not supported: {eawmethod!r}. "
            f"soda2_samplearea.pro accepts {EAW_METHODS}."
        )

    # `diam=float(diam)` / `res=float(res)` at :17-18. These two narrowings
    # are unconditional in the source -- IDL's `float()` is a cast to single
    # precision, not Python's "make it a real number" -- so they happen here
    # whatever the caller passed, and they are why a float64 caller still gets
    # a single-precision answer.
    diam_arr = np.asarray(diam, dtype=np.float32)
    res_f = np.float32(res)

    # Everything below keeps the dtype the caller supplied, because IDL does:
    # the type of `wavelength` is the type of the probespecs field it came
    # from. `_as_idl` turns a plain Python float into FLOAT, which is what
    # every caller in the SODA-2 tree passes.
    wl = _as_idl(wavelength)
    arm = _as_idl(armwidth)
    ndiodes = _as_idl(numdiodes)
    dconst: Any = _as_idl(dofconst)

    if dconst == 0.0:
        dconst = _DOFCONST_DEFAULT
        # `:14` compares against a FLOAT literal. Against a float64 wavelength
        # both widen and this is FALSE even for the same physical value --
        # measured under GDL, finding S1-a. Do not "fix" it with np.isclose.
        if wl == _SPEC_WAVELENGTH:
            dconst = _DOFCONST_SPEC

    # r^2/lambda, in metres: (diam[um] -> m, halved for radius), squared.
    # `1e6` and `2.0` are bare IDL decimals, hence FLOAT.
    r2overlam = (diam_arr / _F(1e6) / _F(2.0)) ** 2 / wl

    dof_arr = np.zeros_like(r2overlam) if dof is None else np.asarray(_as_idl(dof))
    if dof_arr.sum() == 0:
        # *2 is for the +/-; 1e6 converts metres to micrometres.
        dof_arr = 2 * dconst * r2overlam * _F(1.0e6)

    prht = arm * _F(1.0e4)  # cm -> um

    # IDL `dof = dof < prht` -- MIN, not a comparison. Limits depth of field
    # to the physical distance between the probe arms.
    dof_arr = np.minimum(dof_arr, prht)

    eff_wid: Any
    if eawmethod == "reconstruct":
        # Heymsfield & Parrish (1978) eq. 17, the source's own citation.
        eff_wid = res_f * ndiodes + _F(0.72) * diam_arr
    elif eawmethod == "centerin":
        # A SCALAR, and deliberately: `eff_wid=res*numdiodes` at :28 has no
        # `diam` in it, so IDL produces one number however many particles were
        # passed, and a caller reading the `eff_wid` keyword output gets one
        # number back. Broadcasting into `sa` below is unaffected. Measured
        # under GDL -- the golden's `EW` list is length 1 for every `centerin`
        # case and length n for the other two methods.
        eff_wid = res_f * ndiodes
    else:  # "allin" -- the membership check above leaves no other case.
        eff_wid = res_f * (ndiodes - _F(1.0)) - diam_arr

    # IDL `sa = (...) > 0` -- MAX, not a comparison. Forbids a negative
    # sample area, which `allin` produces once diam exceeds the array width.
    sa = np.maximum(dof_arr * eff_wid * _F(1e-12), 0)

    return np.asarray(sa), np.asarray(dof_arr), np.asarray(eff_wid)
