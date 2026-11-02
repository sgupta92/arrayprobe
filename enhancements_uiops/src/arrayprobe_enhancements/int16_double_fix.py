# SPDX-License-Identifier: BSD-3-Clause
"""Double-precision `d_choice` size definitions.

`sizeDist.m:756-766`'s five non-default `d_choice` branches (1, 2, 3, 4, 5) multiply
`image_width`/`image_length` -- `int16` in stock UIOOPS's netCDF -- by `diodesize`. MATLAB keeps
the integer type across that multiply and saturates, collapsing `particle_diameter_minR` toward
zero for `d_choice` 1, 2, 3, 5 (4 escapes via `sqrt` promotion but still saturates inside the
radicand above 181 diodes). See `enhancements_uiops/docs/CORRECTIONS.md`, part `int16_double_fix.py` for the full write-up,
including two independent reasons this has never touched a real ORACLES product: no real
ORACLES flight ever used a non-default `d_choice`, and the ORACLES variant declares
`image_width`/`image_length` `'double'` from the start (`imgproc_output_typing="all-double"`),
so the int16 trap this module corrects cannot even fire on ORACLES data.

`src/arrayprobe/` never imports this module. As of this same session, the port's own
`sizedist.py` `_d_length`/`_d_width`/`_d_mean`/`_d_hypot`/`_d_max` correctly *reproduce* the
saturating bug (via `arrayprobe.matlab_compat`'s `mmul`/`madd`/`mdiv`/`mpow`/`msqrt`) -- this
module is the separate, opt-in corrected counterpart, not a patch to the port.
"""

from __future__ import annotations

import numpy as np

__all__ = [
    "corrected_d_length",
    "corrected_d_width",
    "corrected_d_mean",
    "corrected_d_hypot",
    "corrected_d_max",
]


def corrected_d_length(image_length, diodesize):
    """``:756`` -- ``d_choice == 1``, cast to double before the multiply."""
    return np.asarray(image_length, dtype=np.float64) * diodesize


def corrected_d_width(image_width, diodesize):
    """``:758`` -- ``d_choice == 2``, cast to double before the multiply."""
    return np.asarray(image_width, dtype=np.float64) * diodesize


def corrected_d_mean(image_length, image_width, diodesize):
    """``:760`` -- ``d_choice == 3``, cast to double before any arithmetic."""
    length = np.asarray(image_length, dtype=np.float64)
    width = np.asarray(image_width, dtype=np.float64)
    return (length + width) / 2 * diodesize


def corrected_d_hypot(image_length, image_width, diodesize):
    """``:762`` -- ``d_choice == 4``.

    Already escapes the zero-collapse in MATLAB (``sqrt`` promotes), but the
    radicand still saturates above 181 diodes there. Casting first removes
    that ceiling too.
    """
    length = np.asarray(image_length, dtype=np.float64)
    width = np.asarray(image_width, dtype=np.float64)
    return np.sqrt(width ** 2 + length ** 2) * diodesize


def corrected_d_max(image_length, image_width, diodesize):
    """``:764`` -- ``d_choice == 5``, cast to double before the multiply."""
    length = np.asarray(image_length, dtype=np.float64)
    width = np.asarray(image_width, dtype=np.float64)
    return np.maximum(width, length) * diodesize
