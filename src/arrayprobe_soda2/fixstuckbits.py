# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""``fixstuckbits.pro`` -- work around bits stuck 'on' in an OAP image
buffer.

30 lines of IDL. Signature ``fixstuckbits(image, h=h)``. Callers:
``soda2_processbuffer.pro:615`` (all probes, gated by
``(*pop).stuckbits``, default 0 at ``soda2_update_op.pro:23``) and
``soda2_bitimage.pro:43``. Neither caller passes ``h``.

**Line-by-line** (IDL 1-based diode indexing kept visible; converted to
0-based only where NumPy requires it):

- ``:8`` -- ``h=total(image,2)`` when omitted: a per-diode-column total
  across slices, FLOAT (IDL's ``total`` promotes).
- ``:11-13`` -- ``pad=7``; ``h2`` is a **LONG** (``lonarr``) array of
  ``len(h)+14`` with ``h`` written into the middle -- assigning a FLOAT
  ``h`` into a LONG array **truncates toward zero** (totals are
  non-negative, so this is ``floor``).
- ``:14`` -- ``hf=median(h2,7)``, IDL's width-7 median filter, returns
  FLOAT. Implemented here as the plain interior 7-window median (see
  :func:`_median_filter_7`); the padded region's own value never crosses
  the threshold below (the 7-element pad on each side is wider than the
  filter's half-width 3), so this port does not reproduce IDL's edge rule
  for a shortened window -- pinned by ``test_pad_region_never_crosses_threshold``.
- ``:15`` -- ``diff=abs(h2-hf)``.
- ``:17`` -- the stuck diodes are those whose ``diff`` exceeds ten times the
  root of the median of ``h``, offset by ``pad``. IDL's
  scalar ``median`` **without ``/EVEN`` takes the upper of the two middle
  values** for an even count (measured: ``median([1,2,3,4]) = 3``):
  ``np.sort(h)[n // 2]``.
- **``:19`` -- the no-match case is S4-x, and GDL measurement overturned
  the first-pass reading (a halt) below.** IDL's ``where`` with no match
  returns the scalar ``-1``; ``- pad`` makes it the scalar ``-8``; ``:19``
  tests ``stuck[0] eq -1``, the *pre-subtraction* sentinel, so it is
  always false; ``:20`` then subscripts ``image`` with the scalar ``-8``.
  **Measured under GDL (this bank): a scalar index of ``-8`` is a normal
  IDL negative index -- it counts from the end of the array -- so for any
  image with 8 or more diodes, ``:20`` silently zeroes diode column
  ``n - 8`` (not a real stuck diode) and reconstructs it from its own
  neighbour at ``n - 9``, exactly as if that column had been flagged.**
  Only when the diode count is *under* 8 does ``-8`` fall outside the
  array and GDL actually halt: ``% FIXSTUCKBITS: Subscript out of range
  [-i]`` (measured on a 5-diode image). This port reproduces the silent
  corruption for ``n >= 8`` by using the same negative-index arithmetic
  NumPy already applies, and raises :class:`NoStuckBitsHalt` only for
  ``n < 8``, matching the genuine halt.
- ``:20-27`` -- for each stuck column: zero it, then copy the **left**
  neighbour (or the right one for column 0), reading from the
  already-zeroed ``image`` -- two adjacent stuck columns leave the
  *second* one blank. IDL mutates the caller's array in place at ``:20``
  (both call sites immediately reassign their own variable to the
  return value, so the mutation is unobservable there); this port
  **copies** ``image`` first and never mutates the caller's array.
"""
from __future__ import annotations

import numpy as np

__all__ = ["NoStuckBitsHalt", "fixstuckbits"]


class NoStuckBitsHalt(RuntimeError):
    """``fixstuckbits.pro:17-20`` -- when no diode crosses the threshold
    and the image has **fewer than 8 diodes**, IDL's scalar index ``-8``
    (the where() sentinel ``-1`` minus ``pad=7``) falls outside the array
    and GDL halts: ``% FIXSTUCKBITS: Subscript out of range [-i]``
    (measured on a 5-diode image). This is the genuine-halt half of SODA-2 register entry S4-x;
    for 8 or more diodes, ``-8`` is a valid negative index and the
    routine silently corrupts diode column ``n - 8`` instead -- see the
    module docstring and the non-halting half of that entry."""


def _median_filter_7(h2: np.ndarray) -> np.ndarray:
    """Plain width-7 median over the interior of ``h2`` (indices
    ``3..len-4``); the 3 outermost positions on each end are never read by
    ``:15`` because the pad is wider than the filter half-width -- see the
    module docstring and ``test_pad_region_never_crosses_threshold``."""
    n = len(h2)
    out = np.zeros(n, dtype=np.float32)
    for i in range(3, n - 3):
        window = h2[i - 3:i + 4]
        out[i] = np.sort(window)[3].astype(np.float32)
    return out


def fixstuckbits(image: np.ndarray, h: np.ndarray | None = None) -> np.ndarray:
    """``fixstuckbits(image, h=h)`` (``fixstuckbits.pro:8-29``).

    ``image`` is a 2-D array, diode axis first (axis 0), matching
    ``findsize.py`` / ``processbuffer_spec.py``'s ``[x, y]`` convention.
    ``h`` is an ``intarr`` (``(*pmisc).lastdhist``) at the one call site
    that supplies it; when omitted, ``h = total(image, 2)`` (a per-column
    sum over slices).

    Raises :class:`NoStuckBitsHalt` where IDL itself would halt (SODA-2 register entry S4-x),
    rather than silently returning ``image`` unchanged.

    The input is never mutated; the return is always a fresh array.
    """
    image = np.asarray(image)
    n = image.shape[0]

    if h is None:
        h_float = image.sum(axis=1).astype(np.float64)
    else:
        h_float = np.asarray(h, dtype=np.float64)

    pad = 7
    h2 = np.zeros(n + 2 * pad, dtype=np.int32)
    h2[pad:pad + n] = h_float.astype(np.int32)  # LONG truncation, :12-13

    hf = _median_filter_7(h2)
    diff = np.abs(h2.astype(np.float32) - hf)

    med_h = np.sort(h_float)[len(h_float) // 2]  # IDL scalar median, upper-middle
    threshold = np.float32(10) * np.float32(np.sqrt(med_h))

    stuck_idx = np.where(diff > threshold)[0]
    if stuck_idx.size == 0:
        # `:17-20`, S4-x: IDL's where() sentinel -1 minus pad(7) = -8, a
        # scalar negative index. For n < 8 diodes that is genuinely out
        # of range and GDL halts (measured); for n >= 8 it silently
        # corrupts diode column n-8 instead of returning the image
        # unchanged. NumPy's own negative indexing reproduces the n >= 8
        # branch exactly, so only the n < 8 branch needs an explicit guard.
        if n < 8:
            raise NoStuckBitsHalt(
                "fixstuckbits.pro:17-20: no diode crossed the threshold "
                "and the image has fewer than 8 diodes, so IDL's scalar "
                "index -8 falls outside the array -- GDL halts with "
                "'Subscript out of range [-i]' (measured); SODA-2 "
                "finding S4-x")
        stuck = np.array([-8])
    else:
        stuck = stuck_idx - pad  # :17, back into diode-column space

    out = image.copy()
    out[stuck, :] = 0
    newimage = out.copy()
    for s in stuck:
        if s == 0:
            newimage[0, :] = out[1, :]
        else:
            newimage[s, :] = out[s - 1, :]
    return newimage
