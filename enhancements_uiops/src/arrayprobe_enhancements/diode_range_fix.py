# SPDX-License-Identifier: BSD-3-Clause
"""F3 -- validate a shadow-diode list against the probe width instead of widening the image.

**What it corrects.**  In the nine-argument ``imgProc_sm.m:290``, ``c(:,shadow_diode)='1'``
assigns into a char array by column number.  MATLAB *grows* a char array on out-of-range
assignment, padding the new columns with ``char(0)``::

    >> c = ['0101';'1010']; c(:,[2 6]) = '1'; size(c)
    ans =    2   6
    >> double(c(1,:))
    ans =   48   49   48   49    0   49

So a ``shadow_diode`` entry above the probe's diode count does not raise.  The image simply
becomes too wide, and four lines later (``:272-276``) the image width is compared with
``diodenum``; on a mismatch the code prints a (misspelt) "not equal to diode number" message
and returns.

That ``return`` exits ``imgProc_sm`` **entirely**, part-way through the file.  The netCDF keeps
however many particles had been written, the process exit status is success, and the only
evidence is a line on stdout.  A mask generated against a 128-diode probe and applied to a
64-diode one does this on the first particle.

The port reproduces the widening on purpose -- ``arrayprobe.masks.reilluminate`` pads with
``char(0)`` and says why: reproducing the growth is what lets the width guard fire here too,
instead of being pre-empted by an ``IndexError`` of our own invention.  This module is F3's
suggested edit, opt-in and outside the port.

**What it changes.**  :func:`validate_diodes` is the ``assert`` the finding asks for --
``all(shadow_diode >= 1 & shadow_diode <= diodenum)`` -- raising :class:`DiodeRangeError` with
the offending entries and the truncation they would have caused.
:func:`reilluminate_checked` is the drop-in for ``masks.reilluminate``: it validates, then calls
the port's own unmodified function, so the assignment itself is never reimplemented here.
``validate=False`` turns the check off and delegates straight to the port, which is the faithful
behaviour -- both states are tested.

**What this module does NOT claim.**

* **No ORACLES product is known to have been truncated by this.**  The 09/06/2016 2D-S masks
  recovered here are *empty*, and the 09/06 HVPS mask names diodes 2 and 128 -- both in range
  for a 128-diode probe.  The module is therefore a validated *guard*, not a recovery: it has
  no truncated file on this machine to point at, and it makes no estimate of how often the
  failure has occurred in the field.
* **It cannot repair a file that was already truncated.**  The evidence needed -- how many
  records the run got through before ``return`` -- is not in the product.  Re-running with a
  corrected mask is the only remedy, and that is the caller's decision.
* **It does not decide what the right mask is.**  An out-of-range entry could mean a
  wrong-probe mask, a 1-vs-0-based mix-up, or a corrupt file; the module reports the numbers
  and the probe width and stops there.
* **The widening behaviour it guards against is measured, not assumed** -- the Octave snippet
  above is the port's own recorded measurement (``masks.py``, ``_CHAR_PAD``), and
  :func:`would_widen` is asserted against ``masks.reilluminate``'s real output in the tests
  rather than against a description of it.
"""

from __future__ import annotations

import numpy as np
from arrayprobe.masks import ShadowDiodeMask, reilluminate

__all__ = [
    "DiodeRangeError",
    "as_diode_array",
    "out_of_range",
    "would_widen",
    "validate_diodes",
    "reilluminate_checked",
]


class DiodeRangeError(ValueError):
    """A ``shadow_diode`` entry that ``imgProc_sm.m:290`` would silently widen the image with."""


def as_diode_array(diodes) -> np.ndarray:
    """The diode list as MATLAB holds it -- float64, column-major flattened.

    Unrounded, exactly as ``masks.load_shadow_diode_mask`` keeps it, so a fractional entry is
    caught at use rather than being floored out of sight here.
    """
    if isinstance(diodes, ShadowDiodeMask):
        diodes = diodes.diodes
    return np.asarray(diodes, dtype=np.float64).ravel(order="F")


def out_of_range(diodes, diodenum: int) -> dict:
    """The three ways an entry can be unusable, separated because they fail differently.

    ``above`` widens the image and truncates the run (F3, silent).  ``below`` (zero or
    negative) and ``fractional`` stop MATLAB at the assignment with a subscript error, which
    the port already reproduces as ``MatlabIndexError`` -- loud, and therefore not F3's
    problem, but reported here so one call answers "is this mask usable at all".
    """
    idx = as_diode_array(diodes)
    return {
        "above": idx[idx > diodenum].tolist(),
        "below": idx[idx < 1].tolist(),
        "fractional": idx[(idx >= 1) & (idx != np.floor(idx))].tolist(),
    }


def would_widen(diodes, diodenum: int) -> int:
    """How many columns ``c(:,shadow_diode)='1'`` would add to a ``diodenum``-wide image.

    ``0`` when the mask is in range -- i.e. when the width guard at ``:272-276`` would not
    fire and the run would not end early.
    """
    idx = as_diode_array(diodes)
    if idx.size == 0:
        return 0
    need = float(idx.max())
    return int(max(0.0, np.ceil(need) - diodenum))


def validate_diodes(diodes, diodenum: int, *, source: str | None = None) -> np.ndarray:
    """F3's suggested edit: ``assert(all(shadow_diode >= 1 & shadow_diode <= diodenum))``.

    Returns the validated diode array so the call can be used inline.  Raises
    :class:`DiodeRangeError` naming every offending entry, the probe width, and -- for the
    silent case -- the truncation it would have caused.
    """
    idx = as_diode_array(diodes)
    bad = out_of_range(idx, diodenum)
    if not any(bad.values()):
        return idx
    where = f" in {source}" if source else ""
    parts = []
    if bad["above"]:
        extra = would_widen(idx, diodenum)
        parts.append(
            f"{len(bad['above'])} entry/entries above the probe's {diodenum} diodes "
            f"({', '.join(f'{v:g}' for v in bad['above'])}): MATLAB would widen the image "
            f"by {extra} column(s) of char(0), imgProc_sm.m:272-276 would then print "
            "'Not equal to doide number' and RETURN, truncating the run part-way through "
            "the file with a success exit status")
    if bad["below"]:
        parts.append(f"{len(bad['below'])} non-positive entry/entries "
                     f"({', '.join(f'{v:g}' for v in bad['below'])})")
    if bad["fractional"]:
        parts.append(f"{len(bad['fractional'])} fractional entry/entries "
                     f"({', '.join(f'{v:g}' for v in bad['fractional'])})")
    raise DiodeRangeError(f"shadow_diode{where} is not usable on a {diodenum}-diode probe: "
                          + "; ".join(parts))


def reilluminate_checked(c: np.ndarray, diodes, diodenum: int | None = None, *,
                         validate: bool = True, source: str | None = None) -> np.ndarray:
    """``masks.reilluminate`` with the range check in front of it.

    ``diodenum`` defaults to the image's own width, which is what ``imgProc_sm`` compares
    against at ``:272-276``.  With ``validate=False`` this is the port's function and nothing
    else -- the faithful state, widening included.
    """
    if diodenum is None:
        diodenum = int(c.shape[1])
    if validate:
        validate_diodes(diodes, diodenum, source=source)
    return reilluminate(c, diodes)
