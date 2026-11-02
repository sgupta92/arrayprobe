# SPDX-License-Identifier: BSD-3-Clause
"""Recovers `sizeDist.m`'s scrambled `mean_area_ratio` (and, unverified against real data,
its `REJ_`/`mean_aspect_ratio_*` siblings) -- the upstream missing mean-ratio transpose.

``sizeDist.m:1981`` (and ``:2002-2004``) writes these variables without the transpose every
neighbouring `putVar` call has. MATLAB does not error on a shape mismatch with the right
element count -- it fills the variable in column-major linear order from the array's own
column-major order, so the result is a **reshape**, not a transpose: values land at
essentially arbitrary ``(time, bin)`` coordinates, including seconds and bins with no
particles at all.

See ``enhancements_uiops/docs/CORRECTIONS.md`, part `reshape_fix.py`` for the full derivation: the correcting reshape was found
by brute-force search against a physical-invariant ground truth (a second either has
particles or it doesn't) and verified three independent ways on real data (perfect row match
against ``n > 0``, exact bin-count match against the correctly-written sibling
``mean_perimeter``, physically plausible recovered value range).

``src/arrayprobe/`` never imports this module and never applies this correction --
the port's own output keeps reproducing the scrambled write exactly, per the fidelity
doctrine.
"""

from __future__ import annotations

import numpy as np

__all__ = ["correct_reshaped_time_bin_array"]


def correct_reshaped_time_bin_array(raw_array, n_bins: int):
    """Recover the correct ``(n_time, n_bins)`` array from a `sizeDist.m` write
    scrambled by the A6 reshape bug.

    ``raw_array`` is the ``(n_time, n_bins)`` array as read from the sd file
    (this port's/ncio's convention -- the same shape ``mean_area_ratio``
    comes back in). ``n_bins`` is the declared bin count, needed because
    reversing a reshape (unlike C5's shape-symmetric swap) requires knowing
    the shape the variable was actually declared with.
    """
    arr = np.asarray(raw_array)
    if arr.ndim != 2:
        raise ValueError(f"expected a 2-D (time, bin) array, got shape {arr.shape}")
    n_time = arr.shape[0]
    if arr.shape[1] != n_bins:
        raise ValueError(f"raw_array has {arr.shape[1]} bins, n_bins={n_bins} was given")
    return arr.reshape(n_bins, n_time, order="C").T
