# SPDX-License-Identifier: BSD-3-Clause
"""Stray-pixel correction for one particle image (library default off,
batch-driver default on for engine 3.5).

An image made of one real particle plus far-off stray pixels is sized by UIOOPS as a whole
(``image_diam_minR`` encloses every shadowed pixel), so a ~200 um drop plus one stray pixel
becomes a 500-1000 um particle. :func:`remove_stray_pixels` zeroes the stray pieces and returns
the main piece, so the engine's unchanged measurement code re-sizes and re-tests it.

Wired into ``arrayprobe_uiops.imgproc`` (``stray_pixel_fix=``; library default off, whereas
``run_flight`` turns it on for every ``--engine 3.5`` run unless ``--stray-pixel off``).
This module does not import
``arrayprobe`` (nothing outside the v3.1.4 engine imports it); its constant-gap grouping is
the same rule as ``arrayprobe.triage_context.piece_groups``.
"""
from __future__ import annotations

from typing import Any

import numpy as np

#: Default gap, in empty diodes, below which pieces are one particle (the triage page's G = 8).
STRAY_GAP_DIODES = 8
#: A group of at most this many pixels, apart from the main piece, is a stray.
N_STRAY_PIXELS = 2
#: The main piece must have at least this many pixels (a 3 x 3 drop), or nothing is corrected.
MIN_MAIN_PIXELS = 9


def _groups(c: np.ndarray, gap: int) -> list[np.ndarray]:
    """8-connected pieces grouped single-linkage when at most ``gap`` empty diodes apart."""
    from scipy import ndimage

    eight = np.ones((3, 3), dtype=int)
    if gap <= 0:
        labels, count = ndimage.label(c, structure=eight)
    else:
        pad = gap + 1
        grown = ndimage.binary_dilation(np.pad(c, pad),
                                        structure=np.ones((gap + 1, gap + 1), dtype=bool))
        labels, count = ndimage.label(grown, structure=eight)
        labels = labels[pad:-pad, pad:-pad] * c
    return [m for m in (labels == lab for lab in range(1, count + 1)) if m.any()]


def remove_stray_pixels(c: Any, gap: int = STRAY_GAP_DIODES, n_stray: int = N_STRAY_PIXELS,
                        min_main: int = MIN_MAIN_PIXELS) -> tuple[np.ndarray, dict[str, Any]]:
    """``(cleaned, record)`` for one particle image ``c`` (nonzero = shadowed).

    Corrected only when, grouped at ``gap``, there are two or more groups, exactly one has more
    than ``n_stray`` pixels and at least ``min_main``, and every other has at most ``n_stray``.
    The strays are zeroed; ``cleaned`` keeps ``c``'s shape and dtype, and is ``c`` itself
    (unchanged, same object) when nothing is removed. ``record``: ``removed`` (pixels zeroed),
    ``pieces`` (stray groups removed), ``positions`` (``(row, col)`` of each zeroed pixel).
    """
    arr = np.asarray(c)
    none: dict[str, Any] = {"removed": 0, "pieces": 0, "positions": []}
    shadow = arr != 0
    if arr.size == 0 or not shadow.any():
        return c, none
    groups = _groups(shadow, gap)
    if len(groups) < 2:
        return c, none
    sizes = [int(g.sum()) for g in groups]
    big = [i for i, s in enumerate(sizes) if s > n_stray]
    if len(big) != 1 or sizes[big[0]] < min_main:
        return c, none
    stray = np.zeros_like(shadow)
    for i, g in enumerate(groups):
        if i != big[0]:
            stray |= g
    cleaned = arr.copy()
    cleaned[stray] = 0
    rr, cc = np.nonzero(stray)
    return cleaned, {"removed": int(rr.size), "pieces": len(groups) - 1,
                     "positions": list(zip(rr.tolist(), cc.tolist(), strict=True))}


#: The ``.call`` stamp / global-attribute value of the default parameters (design, "Stamp").
STAMP_ON = f"on:g{STRAY_GAP_DIODES},n{N_STRAY_PIXELS},m{MIN_MAIN_PIXELS}"
STAMP_OFF = "off"


def correct_engine_image(c: Any) -> tuple[Any, int]:
    """``(c_out, removed)`` for one engine image -- the ``(nslices, ndiodes)`` ASCII ``c``
    (``'0'`` / 48 / ``True`` shadowed), as ``_process_records`` holds it before
    ``measure_record``. Zeroed stray pixels are set to lit (``'1'`` / 49 / ``False``);
    ``c_out`` is ``c`` itself when nothing is removed."""
    arr = np.asarray(c)
    lit: Any  # bool, numpy str/bytes scalar or int, by the image dtype
    if arr.dtype.kind == "b":
        shadow, lit = arr, False
    elif arr.dtype.kind in "US":
        shadow, lit = arr == arr.dtype.type("0"), arr.dtype.type("1")
    else:
        shadow, lit = arr == 48, 49
    _, rec = remove_stray_pixels(shadow.astype(np.uint8))
    if rec["removed"] == 0:
        return c, 0
    out = arr.copy()
    for r, k in rec["positions"]:
        out[r, k] = lit
    return out, int(rec["removed"])
