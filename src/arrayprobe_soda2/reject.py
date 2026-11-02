# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""``soda2_reject.pro`` -- SODA-2's per-particle accept/reject decision.

38 lines of IDL, no callees. Returns a **bit sum**, not a code: the source's
own comment calls the criteria *"in increasing order of importance"*, which
describes a priority the code does not implement. It adds. A particle failing
five criteria comes back as the sum of five powers of two, and the caller is
left to decode it.

Provenance: ``SODA2/abansemer-soda2-afcea15/soda2_reject.pro`` (whole file),
Aaron Bansemer, NCAR, 2009. Copyright (C) 2016 UCAR, 3-clause BSD.
Validated against GDL by ``tests/test_soda2_reject.py``; bank at
``gdl_oracle/run_soda2_reject_bank.py``, 31 cases, all matching.

**The bits, and which of them are mutually exclusive.**

======  ==========================================  ==========================
bit     criterion                                   gated by
======  ==========================================  ==========================
1       area ratio < 0.10 or > 1.0                  --
2       interarrival below cutoff (either side)     --
4       binning size outside the bin ladder         --
8       all-in / centre-in violated                 ``eawmethod``
16      cluster of two or more                      ``clusterthresh > 0``
32      water-droplet rejection                     ``water`` in {1, 2}
64      irregular-only rejection                    ``water == -1``
128     depth-of-field flag clear                   ``dofreject >= 1``
======  ==========================================  ==========================

Bits 32 and 64 are **mutually exclusive by construction** -- one needs
``water`` positive and the other needs it negative -- so **255 is unreachable**
and the true ceiling is 223. Measured: the bank's ``all_eight_bits_is_unreachable``
case drives every reachable criterion at once and returns **222**, not 223,
because an ``arearatio`` high enough to trip bit 64 is by definition inside
bit 1's accepted band. A port that summed all eight would still pass every
single-bit case, which is why that case exists.

**``eawmethod`` gates bit 8 in a way that has no default.** ``'centerin'``
tests ``a.centerin``, ``'allin'`` tests ``a.allin``, and ``'reconstruct'``
matches neither -- so under reconstruction bit 8 is unreachable however the
particle sits on the array. That is correct (a reconstructed particle is
*meant* to be partial), and it is worth knowing it is achieved by falling off
the end of two `IF`s rather than by an explicit branch.

**NaN is not handled uniformly, and this is preserved.** Measured under GDL:

- ``arearatio`` NaN -> bit 1 does **not** fire. ``lt`` and ``gt`` are both
  false for NaN, so a particle with an unmeasurable area ratio is *accepted*
  by the criterion meant to catch bad area ratios.
- ``inttime`` NaN -> bit 2 does **not** fire, same reason.
- ``binningsize`` NaN -> bit 4 **does** fire. This is the one place the
  routine tests ``finite()`` explicitly.

Finding **S3-b**. The port reproduces all three,
which in NumPy means the comparisons must be left as plain ``<``/``>`` on
values that may be NaN and must not be pre-screened.

**The return type changes with the answer.** ``reject=0b`` is BYTE; every
``reject+=N`` adds an untyped IDL literal, which is INT, and ``BYTE + INT``
promotes. Measured: ``size(r,/tname)`` is ``BYTE`` for an accepted particle and
``INT`` for a rejected one. Finding **S3-a**. This port returns a plain Python
``int`` and records the IDL type alongside it in ``RejectResult.idl_type``,
because reproducing a type that varies with the value is not something a
Python ``int`` can do, and silently picking one would misreport the other.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import NamedTuple

import numpy as np

__all__ = [
    "EAW_METHODS",
    "Particle",
    "RejectOptions",
    "RejectResult",
    "REJECT_BITS",
    "soda2_reject",
]

#: The three values ``eawmethod`` takes. Only two of them reach bit 8.
EAW_METHODS = ("reconstruct", "centerin", "allin")

#: bit -> what it means, in the source's own words. Exposed so a caller can
#: decode a sum without re-deriving the table from the comments.
REJECT_BITS: dict[int, str] = {
    1: "low area ratio",
    2: "below interarrival",
    4: "out of size range",
    8: "all-in / centre-in",
    16: "cluster",
    32: "water",
    64: "irregular-only",
    128: "depth-of-field flag",
}


@dataclass
class Particle:
    """The tags of ``soda2_readpbp``'s per-particle structure that this
    routine reads. Deliberately only those six: a fuller record would invite
    the port to consult a field the original does not."""

    arearatio: float
    arearatiofilled: float
    allin: int
    centerin: int
    diam: float
    dofflag: int


@dataclass
class RejectOptions:
    """The tags of ``op`` that this routine reads, through ``(*pop)``.

    ``clusterthresh`` has a default here for the same reason
    ``soda2_update_op.pro:22`` gives it one: it is absent from ``op`` as built
    by ``soda2.pro:455`` and is added later, so a caller that skipped that
    step would hit a missing-tag error rather than a disabled feature.
    """

    endbins: Sequence[float] | np.ndarray
    eawmethod: str
    water: int = 0
    res: float = 0.0
    dofreject: int = 0
    clusterthresh: float = 0.0


class RejectResult(NamedTuple):
    """``reject`` plus the IDL type the original would have returned.

    ``idl_type`` is not decoration: it is the one thing about this routine's
    output that a Python ``int`` cannot carry, and it is measurably
    value-dependent (SODA-2 register entry S3-a). Callers comparing against an IDL run need
    it; callers doing arithmetic can ignore it.
    """

    reject: int
    idl_type: str

    def reasons(self) -> list[str]:
        """The set bits, in the source's own words. A convenience, and not a
        reproduction of anything -- the IDL returns only the sum."""
        return [text for bit, text in REJECT_BITS.items() if self.reject & bit]


def _res_times_ten(res: float) -> float:
    """``(*pop).res*10.0`` (`:20`, `:24`, `:29`). ``10.0`` is a FLOAT
    literal, so a FLOAT ``res`` -- a plain Python number here, as everywhere
    this package reads the op -- multiplies in single precision; only a
    ``numpy.float64`` (an IDL DOUBLE ``res``) keeps the product double. The
    difference is a comparison boundary: FLOAT 2.3 (2.2999999523) times 10 is
    23.0 in single precision and 22.9999995 in double, so a ``diam`` of 23.0
    is not above it in IDL (GDL-measured,
    ``tests/test_soda2_reject.py::TheWaterSizeThresholdIsAFloatProduct``)."""
    if isinstance(res, np.float64):
        return float(res * 10.0)
    return float(np.float32(res) * np.float32(10.0))


def soda2_reject(
    a: Particle,
    inttime: float,
    nextinttime: float,
    cutoff: float,
    clustercount: int,
    binningsize: float,
    pop: RejectOptions,
) -> RejectResult:
    """``r = soda2_reject(a, inttime, nextinttime, cutoff, clustercount,
    binningsize, pop)``.

    Source: ``soda2_reject.pro`` (SODA-2).

    Argument order and names follow the IDL exactly. ``pop`` is a pointer
    there and a plain object here; nothing in this routine mutates it.

    Every comparison below is written as the source writes it, including the
    strictness of each boundary -- measured at the boundary in the bank rather
    than inferred, because ``lt``/``le`` is the kind of detail a reader
    reconstructs wrongly and a test at the midpoint never catches:

    - ``arearatio`` exactly 0.10 or exactly 1.0 is **accepted**.
    - ``binningsize`` exactly ``min(endbins)`` is **accepted**; exactly
      ``max(endbins)`` is **rejected**. The ladder is half-open at the top and
      closed at the bottom, which is the opposite of what most bin conventions
      do and is preserved.
    """
    reject = 0

    # :11 -- `lt`/`gt` are both false for NaN, so a NaN area ratio survives.
    if a.arearatio < 0.10 or a.arearatio > 1.0:
        reject += 1

    # :12 -- either side of the particle. Same NaN behaviour.
    if inttime < cutoff or nextinttime < cutoff:
        reject += 2

    # :13 -- the only explicit `finite()` test in the routine.
    if (binningsize < min(pop.endbins)
            or binningsize >= max(pop.endbins)
            or not math.isfinite(binningsize)):
        reject += 4

    # :14-15 -- two `IF`s, not a CASE: 'reconstruct' falls off the end and
    # bit 8 is then unreachable for it.
    if pop.eawmethod == "allin" and a.allin == 0:
        reject += 8
    if pop.eawmethod == "centerin" and a.centerin == 0:
        reject += 8

    # :16
    if pop.clusterthresh > 0 and clustercount >= 2:
        reject += 16

    # :19-26 -- water 1 and 2 differ in one threshold, 0.50 against 0.70.
    res10 = _res_times_ten(pop.res)
    if pop.water == 1:
        if (a.arearatiofilled < 0.40
                or (a.arearatiofilled < 0.50 and a.diam > res10)
                or binningsize > 6000):
            reject += 32
    if pop.water == 2:
        if (a.arearatiofilled < 0.40
                or (a.arearatiofilled < 0.70 and a.diam > res10)
                or binningsize > 6000):
            reject += 32

    # :29-31 -- the inverse selection: keep the irregulars, drop the round.
    if pop.water == -1:
        if (a.arearatio >= 0.50
                or (a.arearatio >= 0.40 and a.diam <= res10)):
            reject += 64

    # :34-36
    if pop.dofreject >= 1 and a.dofflag == 0:
        reject += 128

    # See RejectResult: BYTE until the first `+=`, INT thereafter. Measured,
    # not derived from a promotion table.
    return RejectResult(reject, "BYTE" if reject == 0 else "INT")
