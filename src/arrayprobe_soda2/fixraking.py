# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""SODA-2 ``fixraking.pro:1-67`` -- reconstruct raked images (every other
diode undersampled; written for the PIP), bug-for-bug.

Layout as in ``fixstuckbits``: diodes on axis 0, slices on axis 1 (IDL's
``[diode, slice]``); ``(size(image,/dim))[0]`` is the diode count (``:18``).
MATLAB/IDL index conventions are kept visible: IDL indices here are 0-based
already, so ``ieven``/``iodd`` are used as written.

Behaviour reproduced (established by **reading**, then confirmed on all 31
cases of the GDL oracle bank ``gdl_oracle/run_soda2_fixraking_bank.py``,
golden ``tests/data/gdl_soda2_fixraking_golden.json``: 27 run, 4 halt;
item 5's border rule was measured there):

1. ``:10`` ``modetype eq 0`` returns the image unchanged.
2. ``:12`` sets ``mode`` to the truncated ``modetype`` modulo 2: 1 for odd and 0 for even, never
   2, so ``:38`` and ``:60`` (``mode eq 2``) are dead: an even ``modetype``
   copies nothing (2) and masks no diodes before the threshold (4, 6). The
   header comment (``:6``) says even numbers fix even diodes. Preserved.
3. ``:13`` ``type = fix(modetype+1)/2``: 1,2 -> copy; 3,4 -> kernel ``:48``;
   5,6 -> kernel ``:53``; 7 and above reach ``:57`` with ``kernel``
   undefined and IDL halts (``Variable is undefined: KERNEL``) --
   :class:`FixrakingUndefinedKernel`; measured under GDL (modetype 7, 8).
   Negative and non-integer ``modetype`` truncate (-1, -3 -> type 0, no
   fix; 2.5 -> copy with mode 0, no fix; 3.5 -> type 2), measured.
   A 1-D image (IDL ``bytarr(n, 1)`` collapses to 1-D) runs the copy
   branch but halts at ``:57`` in convolution mode (``CONVOL: Incompatible
   dimensions for Array and Kernel``), measured --
   :class:`FixrakingIncompatibleDimensions`.
4. ``:19`` builds the even-diode indices from ``ndiodes/2``, integer division: an odd diode
   count leaves the last diode in neither set.
5. ``:57`` ``convol(float(newimage), kernel, /edge_mirror)``: kernels are
   symmetric, so IDL's no-flip convention is immaterial. The border rule is
   measured under GDL (bank): asymmetric -- the low edge of
   each axis mirrors without repeating (virtual pixel -1 is ``A[1]``, numpy
   ``reflect``), the high edge repeats (virtual pixel n is ``A[n-1]``, numpy
   ``symmetric``), on both axes; the two ``slice_high_edge`` cases pin the
   slice axis's high edge (``reflect`` would set pixel [3, 4]; GDL does not).
   Computed in float32, as IDL's ``float`` and the float32 ``0.7`` literal.
6. ``:62-63`` finds the pixels of ``cimage`` at or above ``thresh``; when nothing crosses,
   ``good`` is the scalar ``-1`` and ``newimage[-1] = 1`` sets the **last
   element** (column-major, i.e. ``[ndiodes-1, nslices-1]``). Derived from
   the measured S4-x precedent (``fixstuckbits.py``: GDL treats a scalar
   negative index as counting from the end); measured under GDL for this
   file by the ``nothing_crosses`` bank cases
   (``tests/test_soda2_fixraking_gdl.py``,
   ``test_nothing_crosses_sets_the_last_element_in_gdl``).
7. Output keeps the input dtype (``newimage = image``, ``:17``).
"""
from __future__ import annotations

import numpy as np

__all__ = ["FixrakingIncompatibleDimensions", "FixrakingUndefinedKernel", "fixraking"]

# `:48` -- float32 because IDL's 0.7 literal is single precision.
_KERNEL_TYPE2 = np.array([[0.7, 1, 0.7], [1, 0, 1], [0.7, 1, 0.7]],
                         dtype=np.float32)
_THRESH_TYPE2 = 2
# `:53`
_KERNEL_TYPE3 = np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]], dtype=np.float32)
_THRESH_TYPE3 = 4


class FixrakingUndefinedKernel(RuntimeError):
    """``fixraking.pro:43-57``: ``type >= 4`` (``modetype >= 7``) enters the
    convolution block with ``kernel`` never assigned; IDL halts at ``:57``."""


class FixrakingIncompatibleDimensions(ValueError):
    """``fixraking.pro:57``: ``convol`` of a 1-D image with the 3x3 kernel;
    GDL halts with ``CONVOL: Incompatible dimensions for Array and Kernel``."""


def _idl_fix(x: float) -> int:
    """IDL ``fix``: truncation toward zero."""
    return int(x)


def _idl_mod(a: int, b: int) -> int:
    """IDL ``mod`` takes the sign of the dividend (C remainder)."""
    r = abs(a) % abs(b)
    return -r if a < 0 else r


def _convol_edge_mirror(a: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    """``convol(a, kernel, /edge_mirror)`` for a 3x3 symmetric kernel,
    no ``/normalize`` (scale 1). See module docstring item 5."""
    # GDL bank (golden gdl_soda2_fixraking_golden.json): the low edge
    # mirrors without repeating (A[-1] = A[1]), the high edge repeats (A[n] = A[n-1]).
    padded = np.pad(a, ((0, 1), (0, 1)), mode="symmetric")
    padded = np.pad(padded, ((1, 0), (1, 0)), mode="reflect")
    out = np.zeros(a.shape, dtype=np.float32)
    n0, n1 = a.shape
    for i in range(3):
        for j in range(3):
            k = kernel[i, j]
            if k == 0:
                continue
            out += k * padded[i:i + n0, j:j + n1]
    return out


def fixraking(image: np.ndarray, modetype: int) -> np.ndarray:
    """``fixraking.pro:1-67``. ``image`` is ``[diode, slice]``."""
    # `:10`
    if modetype == 0:
        # IDL returns the value, and the one caller
        # (soda2_processbuffer.pro:616) calls only when rakefix gt 0 and
        # reassigns bitimage from the result, so aliasing is never visible
        # there; a copy keeps the IDL value semantics for any other caller.
        return np.asarray(image).copy()
    # `:12-13`
    mode = _idl_mod(_idl_fix(modetype), 2)
    type_ = _idl_fix(modetype + 1) // 2 if modetype + 1 >= 0 else \
        -(abs(_idl_fix(modetype + 1)) // 2)

    image = np.asarray(image)
    newimage = image.copy()                      # `:17`
    ndiodes = image.shape[0]                     # `:18`
    ieven = np.arange(ndiodes // 2) * 2          # `:19`
    iodd = ieven + 1                             # `:20`

    # `:36-40` copy mode
    if type_ == 1:
        if mode == 1:
            newimage[iodd, ...] = image[ieven, ...]
        if mode == 2:                            # dead: mode is 0 or 1
            newimage[ieven, ...] = image[iodd, ...]

    # `:43-64` convolution mode
    if type_ >= 2:
        if type_ == 2:
            kernel, thresh = _KERNEL_TYPE2, _THRESH_TYPE2
        elif type_ == 3:
            kernel, thresh = _KERNEL_TYPE3, _THRESH_TYPE3
        else:
            raise FixrakingUndefinedKernel(
                f"fixraking.pro:57: modetype={modetype} gives type={type_}; "
                "kernel is undefined (IDL: Variable is undefined: KERNEL)")
        a = newimage.astype(np.float32)
        if a.ndim != 2:
            raise FixrakingIncompatibleDimensions(
                f"fixraking.pro:57: image has {a.ndim} dimension(s); "
                "IDL: CONVOL: Incompatible dimensions for Array and Kernel")
        cimage = _convol_edge_mirror(a, kernel).reshape(newimage.shape)
        if mode == 1:                            # `:59`
            cimage[ieven, ...] = 0
        if mode == 2:                            # `:60`, dead
            cimage[iodd, ...] = 0
        # `:62-63`, column-major flat order as IDL's where().
        flat_c = cimage.ravel(order="F")
        good = np.nonzero(flat_c >= thresh)[0]
        flat_new = newimage.ravel(order="F").copy()
        if good.size == 0:
            flat_new[-1] = 1                     # where() sentinel -1
        else:
            flat_new[good] = 1
        newimage = flat_new.reshape(newimage.shape, order="F")

    return newimage
