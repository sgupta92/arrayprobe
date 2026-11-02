# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""`soda2_update_op.pro:1-53` (`:55-84`, the `.txt` model-header
parse, is refused here by name).

Vendored source: `SODA2/abansemer-soda2-afcea15/soda2_update_op.pro`. Bank:
`gdl_oracle/run_soda2_preloop_bank.py`, golden
`tests/data/gdl_soda2_preloop_golden.json`.
"""
from __future__ import annotations

import copy

import numpy as np

#: `:10-42`'s literal defaults, in source order, keyed by lower-case tag name.
#: Every scalar `0`/`0.0` keeps IDL's own literal dtype (bare `0` is INT16,
#: `0.0` is FLOAT32) because `soda2_read2dbuffer.pro:116`'s FLOAT-widening
#: quirk (T7) depends on `timeoffset` staying FLOAT32 here, not Python float.
_INT16_DEFAULTS: dict[str, int] = {
    "greythresh": 0, "water": 0, "subformat": 0, "particlefile": 0,
    "ncdfparticlefile": 0, "asciipsdfile": 0, "stuckbits": 0, "savfile": 1,
    "rakefix": 0, "keeplargest": 0, "juelichfilter": 0, "ignoredeadtime": 0,
    "apply_psc": 0, "apply_psc_sizelimit": 0, "dofconst": 0, "dofreject": 0,
    "stretchcorrect": 0, "strictcounter": 0, "activetimefrommissed": 0,
}
_FLOAT32_DEFAULTS: dict[str, float] = {
    "timeoffset": 0.0, "fixedtas": 0.0, "armwidth": 0.0,
    "clusterthresh": 0.0, "wavelength": 0.658e-6,
}
_STR_DEFAULTS: dict[str, str] = {
    "probeid": "A0", "pth": "", "eawmethod": "centerin", "filetag": "",
}


def update_op(op: dict | None) -> dict:
    """Returns a **new** dict -- IDL's `create_struct` rebuilds the struct
    at each `:10-43` line and the caller's variable is reassigned
    (`soda2_process_2d.pro:27` passes `op` by reference). Keys are
    normalised to lower case on entry (IDL tag-name comparisons are
    case-insensitive, `:10-43`); an already-lower-case caller sees no
    change."""
    if not op:
        # `:5-7`: `res` INT16 0, `endbins` INT16 [0,1000].
        op = {
            "probetype": "", "res": np.int16(0),
            "endbins": np.array([0, 1000], dtype=np.int16),
            "format": "", "fn": "",
        }
    else:
        op = {str(k).lower(): v for k, v in op.items()}
        op = copy.deepcopy(op)

    for int16_name, int16_value in _INT16_DEFAULTS.items():
        op.setdefault(int16_name, np.int16(int16_value))
    for f32_tag, f32_default in _FLOAT32_DEFAULTS.items():
        op.setdefault(f32_tag, np.float32(f32_default))
    for s_tag, s_default in _STR_DEFAULTS.items():
        op.setdefault(s_tag, s_default)

    # :25 shortname = probetype (evaluated after probetype's own arrival).
    op.setdefault("shortname", op["probetype"])
    # :32 yres = res.
    op.setdefault("yres", op["res"])
    # :30 seatag = [33000,0,0] -- 33000 exceeds INT16 (32767), IDL promotes
    # the whole literal array to LONG (int32). Measure-not-guess per the
    # plan; recorded here from the bank's `help,op,/structure` read (§3).
    op.setdefault("seatag", np.array([33000, 0, 0], dtype=np.int32))
    # :23 numdiodes = 64 (INT16 literal).
    op.setdefault("numdiodes", np.int16(64))
    # :41 dioderange = [0, numdiodes-1] -- after numdiodes has its final value.
    op.setdefault("dioderange", np.array([0, int(op["numdiodes"]) - 1], dtype=np.int16))
    # :42 customdof = fltarr(n_elements(endbins)-1).
    op.setdefault("customdof", np.zeros(len(op["endbins"]) - 1, dtype=np.float32))

    # :47-48 print-only diagnostics -- console output, never returned/raised.

    # :49 probetype 'PIP' -> 'CIP'.
    if op["probetype"] == "PIP":
        op["probetype"] = "CIP"
    # :50 dioderange[1] == 0 -> numdiodes-1 (upper diode range can't be zero).
    dr_dtype = op["dioderange"].dtype if hasattr(op["dioderange"], "dtype") else np.int16
    dr = np.array(op["dioderange"], dtype=dr_dtype)
    if dr[1] == 0:
        dr = dr.copy()
        dr[1] = int(op["numdiodes"]) - 1
    op["dioderange"] = dr
    # :53 probetype '3VCPI' -> subformat=1.
    if op["probetype"] == "3VCPI":
        op["subformat"] = np.int16(1)

    # :55-84 model .txt header parse -- round 7. Refused by name, not by a
    # blanket `NotImplementedError` on every `.txt` filename: only fires on
    # the exact last-four-characters test `:55` performs.
    fn0 = op["fn"][0] if isinstance(op["fn"], (list, tuple, np.ndarray)) else op["fn"]
    if str(fn0)[-4:] == ".txt":
        raise NotImplementedError(
            "soda2_update_op.pro:55-84 (model .txt header parse) is round-7 "
            "scope; not ported.")

    return op
