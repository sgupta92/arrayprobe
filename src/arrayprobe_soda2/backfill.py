# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""Bug-for-bug port of ``SODA2/abansemer-soda2-afcea15/soda2_backfill.pro``.

Reconstructs a 2DC particle's unrecorded first slice from an eroded copy of
the first recorded one (``soda2_processbuffer.pro:678``, reached whenever
``restore_slice`` is set -- every particle of the 2DC branch,
``soda2_processbuffer.pro:114-115``).

Layout. IDL's ``image`` is ``[diode, slice]``; the port's ROI is
``(slice, diode)``, so IDL ``image[*,k]`` is ``image[k, :]`` here and
``s[1]`` (the diode count) is ``image.shape[-1]``.

Line map (``soda2_backfill.pro``):

- ``:14-15`` ``s[0] eq 1`` -- a 1-D (one-slice) image is returned unchanged.
- ``:16`` a zero-area image is returned unchanged.
- ``:18-23`` ``temp=image``; ``orig=temp[*,1]``; ``origtot=total(...)``
  (FLOAT); fewer than two pixels on the first recorded slice returns
  ``image`` unchanged.
- ``:24-33`` the REPEAT loop: ``es`` grows by one element per pass (first
  pass length 2); origin ``x0`` is ``count/2.0`` (FLOAT), 0 when the first
  diode is shadowed, ``count`` when the last diode is (the last test wins);
  ``:31``'s erosion of ``orig`` written into ``temp`` overwrites slice 0 (IDL assignment keeps
  ``temp``'s type); the loop runs until ``total(temp[*,0]) lt origtot/2.0``.
  The test is REPEAT...UNTIL, so the body runs at least once.

**The oracle gap: GDL has no ``ERODE``** (measured, GDL 1.1.2). The binary
1-D erosion here is this package's reading of IDL's documented ``ERODE``,
``result[i] = 1`` iff ``orig[i + j - long(x0)] ne 0`` for every ``j`` of the
all-ones structuring element, with a neighbour outside the array read as 0
(``ERODE_EDGE_RULE = "zero_outside"``, the same unconfirmed edge rule
``aspect_ratio.py`` uses) and a FLOAT origin truncated toward zero. The GDL
bank (``gdl_oracle/run_soda2_backfill_bank.py``) supplies an ``erode.pro``
shim implementing exactly this reading, so its golden confirms everything in
``soda2_backfill.pro`` *around* the erosion (layer 1 for the control flow,
types and stopping rule; layer 3 for ``ERODE`` itself). Under the
``zero_outside`` rule the loop always terminates: once ``es`` is longer than
the slice, the erosion is all zero and ``0 < origtot/2.0``.
"""

from __future__ import annotations

import numpy as np

#: Edge rule for the 1-D ``ERODE`` stand-in; see the module docstring.
ERODE_EDGE_RULE = "zero_outside"


def _erode_1d(orig: np.ndarray, n: int, x0: float) -> np.ndarray:
    """Binary 1-D erosion by an all-ones element of length ``n``, origin
    ``long(x0)`` (truncation), outside read as 0. Returns BYTE."""
    ox = int(x0)  # IDL LONG() of a FLOAT truncates toward zero; x0 >= 0 here
    fg = np.asarray(orig) != 0
    nx = fg.size
    out = np.zeros(nx, dtype=np.uint8)
    for i in range(nx):
        ok = True
        for j in range(n):
            k = i + j - ox
            if k < 0 or k >= nx or not fg[k]:
                ok = False
                break
        out[i] = 1 if ok else 0
    return out


def soda2_backfill(image: np.ndarray) -> np.ndarray:
    """``soda2_backfill.pro:1-36``. ``image`` is ``(slice, diode)``; a 1-D
    array is a one-slice image. Returns ``image`` itself on the early
    returns (``:15``, ``:16``, ``:23``), else a modified copy."""
    image = np.asarray(image)
    if image.ndim == 1:                                     # :15
        return image
    if image.max() == 0:                                    # :16
        return image

    temp = image.copy()                                     # :18
    count = 1                                               # :20
    orig = temp[1, :].copy()                                # :21
    origtot = np.float32(temp[1, :].sum(dtype=np.float64))  # :22 total -> FLOAT
    if origtot < 2:                                         # :23
        return image
    nes = 1                                                 # :24 es=[1]
    nx = image.shape[-1]                                    # s[1]

    while True:                                             # :27 REPEAT
        nes += 1                                            # :28
        if orig[0] == 1:                                    # :29
            x0: float = 0
        else:
            x0 = float(np.float32(count) / np.float32(2.0))
        if orig[nx - 1] == 1:                               # :30
            x0 = count
        temp[0, :] = _erode_1d(orig, nes, x0)               # :31
        count += 1                                          # :32
        tot0 = np.float32(temp[0, :].sum(dtype=np.float64))
        if tot0 < origtot / np.float32(2.0):                # :33
            break
    return temp                                             # :35
