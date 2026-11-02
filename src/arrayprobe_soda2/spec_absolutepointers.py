# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""``spec_absolutepointers.pro`` -- turn a `spec_index` result and a list of
buffer numbers into one flat array of absolute image-frame file offsets
(P-b).

22 lines of IDL. Signature `spec_absolutepointers(buffnum, p)`, where `p` is
an IDL *pointer* to the struct `spec_index.pro` returns and `buffnum` is a
scalar or array of buffer indices. **This port takes the struct itself, not
a pointer to it** -- Python has no equivalent indirection worth reproducing
here, and no test distinguishes "the struct" from "a pointer to the
struct". One caller in the vendored tree: `soda2_bitimage.pro:16`, with an
index built **without** `/absolutepointer`.

Validated against GDL by ``tests/test_soda2_spec_index.py`` (bank at
``gdl_oracle/run_soda2_spec_index_bank.py``, 9 cases, all matching).

**Line-by-line** (IDL 0-based indexing):

- ``:8`` -- `n = (*p).numimages[buffnum]` -- one `numimages` value per
  requested buffer, in `buffnum`'s own order (not sorted).
- ``:9-10`` -- `nt = total(n)` -- **FLOAT**, the count of images across
  every requested buffer; `:10` returns a zero pointer with a zero count when `nt` is 0 -- two
  scalar **INT** zeros (`n_elements(ap)=1`), not empty arrays. Bank-measured
  (`ap_main_5_empty`, buffer 5's own `numimages=0`, the never-walked last
  buffer): `AP=0 N=0 TN=INT,INT NEL=1`.
- ``:11`` -- `ap = ulon64arr(nt)`, pre-sized to the total image count.
- ``:12-20`` -- `FOR i=0, n_elements(buffnum)-1`: skip any buffer with
  `n[i]` (that buffer's own image count) `<= 0`; otherwise `istart =
  firstp[buffnum[i]]`, `istop = firstp[buffnum[i]] + numimages[buffnum[i]] -
  1` (an **inclusive** IDL slice), and `ap[c:c+n[i]-1] =
  pointer[buffnum[i]] + imagep[istart:istop]` -- `pointer` (ULONG64) plus
  `imagep` (INT or LONG64, signed) promotes to ULONG64 (measured, the same
  rule this project's `spec_read_hk` docstring already names for
  ULONG+INT). Results are written **in `buffnum`'s own order**, not sorted
  by buffer number (bank-measured, `ap_main_41` with `buffnum=[4,1]`:
  buffer 4's four pointers come first, then buffer 1's six).
- ``:21`` -- returns `{ap: ULONG64[nt], n: FLOAT(nt)}`.

**Feeding this an index built WITH `/absolutepointer` double-counts**: the
index's own `imagep` is already an absolute file offset, and `:17` adds
`pointer[buffnum[i]]` again on top. Nobody in the vendored tree does this --
`soda2_bitimage.pro:16` always builds its index without the keyword -- but
the bank measures it anyway (`ap_main_1_absindex`): the same six images
that `ap_main_1` reports as `4250,4268,4346,4514,4638,8130` come back as
`8364,8382,8460,8628,8752,12244`, each exactly `4114` (buffer 1's own
`pointer` value) higher. Latent, not a finding of its own -- reported under
"what turned out to be fine" alongside `spec_read_hk`'s own arithmetic
checks, because the routine is doing exactly what its one caller's own
index shape asks of it.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from .spec_index import SpecIndex

__all__ = ["AbsolutePointers", "spec_absolutepointers"]


@dataclass
class AbsolutePointers:
    """`spec_absolutepointers`'s return struct (`:21`). Empty (`nt==0`,
    `:10`) is IDL's own `{ap:0, n:0}`: both fields collapse to a scalar INT
    zero (`n_elements=1`), not a length-0 array -- reproduced here as
    ``np.int16(0)`` rather than ``np.ndarray([])``.

    Source: ``spec_absolutepointers.pro:21`` (SODA-2)."""

    ap: np.ndarray | np.int16   # uint64[nt] non-empty; np.int16(0) when nt==0
    n: np.float32 | np.int16    # float32(nt) non-empty; np.int16(0) when nt==0


def spec_absolutepointers(
    buffnum: int | Sequence[int],
    index: SpecIndex,
) -> AbsolutePointers:
    """``a = spec_absolutepointers(buffnum, p)`` -- `p` is `index` itself
    here, not a pointer to it (see the module docstring). `buffnum` may be
    a single buffer number or a sequence of them; results are written in
    that exact order, never sorted.

    Source: ``spec_absolutepointers.pro`` (SODA-2).
    """
    buffnum_arr = np.atleast_1d(np.asarray(buffnum, dtype=np.int64))
    n = index.numimages[buffnum_arr]  # `:8` -- one count per requested buffer

    nt = int(sum(int(v) for v in n))
    if nt == 0:  # `:10` -- IDL's `{ap:0, n:0}`, both scalar INT.
        return AbsolutePointers(ap=np.int16(0), n=np.int16(0))

    ap = np.zeros(nt, dtype=np.uint64)
    c = 0
    for i in range(len(buffnum_arr)):
        ni = int(n[i])
        if ni > 0:  # `:14`
            b = int(buffnum_arr[i])
            istart = int(index.firstp[b])
            istop = istart + ni  # Python's half-open end == IDL's inclusive istop + 1
            ap[c:c + ni] = (
                np.uint64(index.pointer[b])
                + index.imagep[istart:istop].astype(np.uint64)
            )
            c += ni

    return AbsolutePointers(ap=ap, n=np.float32(nt))
