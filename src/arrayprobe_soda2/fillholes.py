# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""``fillholes.pro`` -- fill interior holes in a binary particle image.

Source: ``SODA2/abansemer-soda2-afcea15/fillholes.pro`` (22 lines). Called
at ``soda2_processbuffer.pro:714`` on ``roi`` (``bitimage[fp:lp,
startline:stopline]``, IDL dims ``[ndiodes, roilen]``);
``area_filled = total(roifilled)`` (``:715``) feeds
``poisson_spot_correct`` (``:716``, ``arrayprobe_soda2.poisson_spot_correct``)
and ``voidarea`` (``:719``). Reaches output.

::

    FUNCTION fillholes, img                                           ; :1
      img = byte(img)                                                 ; :5
      s = size(img)                                                   ; :7
      IF (s[1] lt 4) or (s[2] lt 4) THEN return, img                  ; :8
      reverse = byte(label_blobs(img xor 1b))                         ; :9
      edges = reverse
      f = [transpose(edges[0,*]), edges[*,0],
           transpose(edges[s[1]-1,*]), edges[*,s[2]-1]]                ; :11-12
      f = f[sort(f)]                                                   ; :13
      edge_labels = f[uniq(f)]                                         ; :14
      FOR i=0,n_elements(edge_labels)-1 DO
         reverse[where(reverse eq edge_labels[i])] = 0b                ; :16-18
      newimg = img or (reverse<1b)                                     ; :20
      return, newimg                                                   ; :21
    END

``:7`` ``size(img)`` (no ``/dim``) returns the IDL *dimension-slots* array:
``s[1]`` is the first dimension size, ``s[2]`` the second -- **not**
``size(/dim)``. A 1-slice ROI indexes down to a 1-D IDL array, whose
``size()`` puts the *type code* in slot 2 (BYTE = 1), so it too is
``lt 4`` and returned unchanged -- the same early return, reached through
a different field. Ported on this package's transposed ``(roilen,
ndiodes)`` array as ``if roilen < 4 or ndiodes < 4: return
img.astype(uint8)``.

**``:9`` -- the BYTE wrap (finding S4-u).** ``label_blobs(img xor 1b)`` is
called with **no keywords**, i.e. ``dilatelength=0, integer=0``: 4-connected
``label_region`` on a 1-pixel zero-padded copy of the *negative* image
(``label_blobs.pro:12-28``), cropped, then cast to **BYTE** at
``label_blobs.pro:28`` -- and ``fillholes.pro:9`` casts the (already-byte)
result to byte again. An ROI whose negative decomposes into more than 255
4-connected regions **wraps labels modulo 256**: region 256 becomes label
0 (the value ``label_blobs`` also uses for "no negative pixel here" is
never assigned by ``label_region`` itself, but 0 is also what a removed
edge blob is zeroed to at ``:18``, so a wrapped 256th region is
indistinguishable from "not part of any blob" and is never filled);
region 257 shares label 1's fate (filled if label 1 survives the edge
scan, removed if it does not). See ``label_blobs.py`` for the
labeller itself -- this module cites ``label_blobs.pro:28`` as the line the
wrap is reached through; it is a ``fillholes`` finding (S4-u), not a
duplicate of the geometry port's own finding about ``label_blobs.pro:29``'s BYTE return
type.

**This module lazily imports ``label_blobs``** (ported
in parallel and not present in this worktree before the merge) so that
importing ``fillholes`` itself never fails: ``from .label_blobs import
label_blobs`` is the first statement inside :func:`fillholes`, called with
**defaults only** (``label_blobs(neg)``), matching ``fillholes.pro:9``'s
keyword-less call exactly. ``label_blobs.pro:28``'s own BYTE cast is
the labeller's responsibility under ``integer=False``; ``fillholes.pro:9``'s own
``byte()`` is reproduced here as an explicit ``.astype(np.uint8)`` -- a
no-op on an already-uint8 input, kept so the line stays visible.

**Border-vector mapping.** IDL indexes ``[ndiodes, roilen]``; this
package's array is ``(roilen, ndiodes)``. So ``edges[0,*]`` (IDL: all of
diode-index 0, every slice) is this array's **column 0**, ``edges[*,0]``
(IDL: slice 0, every diode) is this array's **row 0**, and so on for the
opposite edges. ``np.unique`` replaces ``sort`` + ``uniq``: both compute
the *set* of distinct edge labels, and removal at ``:16-18`` is by label
identity, so the order ``uniq`` happens to return in is irrelevant here.

Validated against GDL by ``tests/test_soda2_fillholes.py``; bank at
``gdl_oracle/run_soda2_fillholes_bank.py``.
"""
from __future__ import annotations

import numpy as np

__all__ = ["fillholes"]


def _labelled_negative(img: np.ndarray, *, jit: bool = False) -> np.ndarray:
    """``byte(label_blobs(img xor 1b))`` -- ``fillholes.pro:9`` -- exposed
    separately so the BYTE-wrap case (S4-u) is assertable directly,
    whichever labeller (real or test stub) is behind it.

    **Axis convention mismatch, found at the round-5 merge.**
    ``label_blobs`` (``label_blobs.py``) assumes its caller passes
    an array with axis 0 = diode, axis 1 = slice (IDL-native, matching
    ``label_blobs.pro``'s own ``img[ndiodes, roilen]`` and confirmed
    against GDL's ``label_region`` raster order on the label_blobs bank:
    ``gdl_oracle/run_soda2_label_blobs_bank.py`` builds its ``img`` with
    "rows = diodes (axis0/x), cols = slices (axis1/y)"). This module's own
    ``img``/``arr`` is on this *package's* transposed convention -- axis 0 =
    slice (``roilen``), axis 1 = diode (``ndiodes``), per the module
    docstring's border-vector mapping. Passing ``arr`` straight through
    would scan slice-fastest instead of diode-fastest; the two scan orders
    agree on *which* pixels are connected (so every case below the 256-label
    wrap matched anyway) but disagree on *label numbering order*, which only
    matters once the label count crosses the 255/256 byte-wrap boundary
    (S4-u) -- caught by ``tests/test_soda2_fillholes.py``'s ``many_holes``
    case (400 holes) against the GDL golden. Fixed by transposing into
    label_blobs's expected axis order on the way in and back out."""
    from .label_blobs import label_blobs  # lazy import

    neg = np.asarray(img, dtype=np.uint8) ^ np.uint8(1)
    # neg is (roilen, ndiodes); label_blobs wants (ndiodes, roilen).
    labelled = np.asarray(label_blobs(neg.T, jit=jit))
    return labelled.T.astype(np.uint8)


def fillholes(img: np.ndarray, *, jit: bool = False) -> np.ndarray:
    """``newimg = fillholes(img)``.

    Source: ``fillholes.pro`` (SODA-2).

    ``img`` is a 2-D binary (0/1) array on this package's ``(roilen,
    ndiodes)`` convention (IDL: ``[ndiodes, roilen]``). Returns a uint8
    array of the same shape.
    """
    arr = np.asarray(img, dtype=np.uint8)

    # `:7-8` -- `size(img)` dimension-slot early return; a 1-slice ROI
    # indexes to 1-D in IDL and hits this through the type-code slot.
    if arr.ndim < 2:
        return arr.astype(np.uint8)
    roilen, ndiodes = arr.shape
    if roilen < 4 or ndiodes < 4:
        return arr.astype(np.uint8)

    # `:9`.
    reverse = _labelled_negative(arr, jit=jit)

    # `:11-12` -- border vectors. IDL `edges[0,*]` -> column 0 here;
    # `edges[*,0]` -> row 0; `edges[s[1]-1,*]` -> last column;
    # `edges[*,s[2]-1]` -> last row.
    edges = np.concatenate([
        reverse[:, 0],
        reverse[0, :],
        reverse[:, -1],
        reverse[-1, :],
    ])

    # `:13-14` -- `sort`+`uniq` gives the set of distinct edge labels;
    # `np.unique` gives the same set (order is irrelevant, `:16-18` removes
    # by identity).
    edge_labels = np.unique(edges)

    # `:16-18` -- zero every blob carrying an edge label. `where` at `:17`
    # can never be empty: every edge label was read from `reverse` itself.
    mask = np.isin(reverse, edge_labels)
    reverse = np.where(mask, np.uint8(0), reverse)

    # `:20` -- `img or (reverse<1b)`; `<` is IDL's binary MIN, so
    # `reverse<1b` clips every surviving nonzero label to 1.
    surviving_holes = np.minimum(reverse, np.uint8(1))
    newimg = (arr.astype(bool) | surviving_holes.astype(bool)).astype(np.uint8)
    return newimg
