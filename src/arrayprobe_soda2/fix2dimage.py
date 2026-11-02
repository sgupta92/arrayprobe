# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""SODA-2 ``fix2dimage.pro`` (28 lines): rewrites NCAR-format sync/timing slices of
a 2DC buffer into the standard ``0x55`` sync pattern. Called by
``soda2_processbuffer.pro:87`` when a 2DC buffer yields fewer than three syncs.

Line map:
- `:9` candidates: words equal to ``0xFF800000``, ``0``, ``0xFF000000`` or ``0x2A000000``.
- `:10` fewer than five candidates: the image is returned unchanged.
- `:13-15` ``diff``/``good``: keep ``test1[k]`` where ``test1[k+1]-test1[k] > 1``. This
  always drops the last candidate (``good`` indexes ``diff``, one shorter); when no gap
  exceeds one, ``where`` gives -1 and ``test1`` is left whole.
- `:17` ``image[(test1>2)-2] eq 'ffffffff'x or test1 lt 2``: a blank slice two back, or
  an index below 2. ``test1>2`` is IDL's maximum operator.
- `:18` none: unchanged.
- `:25-26` ``(w or 0xFF000000) xor 0xAA000000`` -> top byte ``0x55`` at ``timelines`` and
  ``timelines-1``, both read from the original ``image``. A timeline at index 0 gives
  subscript -1, which IDL clips to 0 for an array subscript (no ``strictarrsubs``), so
  slice 0 is written twice from ``image[0]``; numpy would wrap -1 to the last slice, so
  it is clipped here explicitly (GDL-confirmed, ``tests/test_soda2_fix2dimage_gdl.py``).

Source: ``fix2dimage.pro`` (SODA-2); bare line references here are into that file.
"""
from __future__ import annotations

import numpy as np

__all__ = ["fix2dimage"]

_CANDIDATES = (0xFF800000, 0, 0xFF000000, 0x2A000000)  # :9
_BLANK = np.uint32(0xFFFFFFFF)
_OR = np.uint32(0xFF000000)
_XOR = np.uint32(0xAA000000)


def fix2dimage(image: np.ndarray) -> np.ndarray:
    """Port of ``fix2dimage.pro:1-28``. Returns a new ULONG array (or the input,
    unchanged, on the two early returns, as IDL returns ``image`` itself)."""
    img_in = np.asarray(image, dtype=np.uint32)
    hit = np.zeros(img_in.shape, dtype=bool)
    for c in _CANDIDATES:                                               # :9
        hit |= img_in == np.uint32(c)
    test1 = np.flatnonzero(hit).astype(np.int64)
    num = test1.size
    if num < 5:                                                         # :10
        return img_in

    diff = test1[1:num] - test1[0:num - 1]                              # :13
    good = np.flatnonzero(diff > 1)                                     # :14
    if good.size > 0:                                                   # :15
        test1 = test1[good]

    back = img_in[np.maximum(test1, 2) - 2]                             # :17
    test2 = np.flatnonzero((back == _BLANK) | (test1 < 2))
    if test2.size == 0:                                                 # :18
        return img_in

    timelines = test1[test2]                                            # :20
    img = img_in.copy()                                                 # :22
    img[timelines] = (img_in[timelines] | _OR) ^ _XOR                   # :25
    prev = np.maximum(timelines - 1, 0)  # IDL clips subscript -1 to 0
    img[prev] = (img_in[prev] | _OR) ^ _XOR                             # :26
    return img
