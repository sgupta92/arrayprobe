# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""`soda2_probespecs.pro` -- the SODA-2 probe table, 72 probes.

Vendored source: `SODA2/abansemer-soda2-afcea15/soda2_probespecs.pro` (1,479
lines). Bank: `gdl_oracle/run_soda2_probespecs_bank.py`, golden
`tests/data/gdl_soda2_probespecs_golden.json` -- every field of every probe,
and its IDL type, as GDL evaluates the unmodified `.pro`.

**What the routine is.** One `base` structure (`:8-10`), copied 72 times with
its fields overwritten (`x=base`, `x.<tag>=...`, `all=[all,x]`), then
`:1463-1478`: look up by `name=`, by `id=`, or return the whole table.
Units (`:3`): `res`/`yres` um, `armwidth` cm, `tau` s, `wavelength` m.

**Types are the point, not the numbers.** Every assignment converts to the
field's declared type (`:8-10`), and the rest of the chain computes in that
type:

- STRING: `probename`, `shortname`, `format`, `probetype`, `probeid`;
- INT (`numpy.int16`): `subformat` (`0s`), `greythresh`, `firstsliceskip`;
- FLOAT (`numpy.float32`): `res`, `yres`, `armwidth`, `numdiodes`, `tau`,
  `dofthreshold`, `dofconst`, `wavelength`. `x.res=25` is an INT literal stored
  as FLOAT 25.0; `x.tau=41.0e-9` is a FLOAT literal, and the 2D-S's
  `x.wavelength=0.785e-6` (`:955`) is float32 7.849999974e-07 -- the value
  `soda2_samplearea.pro:14`'s Lawson sentinel compares against in FLOAT;
- LONG[3] (`numpy.int32`): `seatag`; INT[2] (`numpy.int16`): `dioderange`.

`numdiodes` is FLOAT here but INT in `soda2_update_op.pro:23`'s default
(`update_op.py` keeps it INT16): the two routes to an `op` disagree on its type.

**A short array into a longer field fills the leading elements (GDL-measured).**
`x.seatag=[33000]` (`:496`) gives `[33000, 0, 0]`; `x.seatag=[33000, 32000]`
(`:156`) gives `[33000, 32000, 0]` -- not a broadcast, not an error. The
trailing elements are `base`'s zeros, because every block starts from
`x=base`. IDL's own behaviour here is not measured (no IDL licence); the port
follows GDL, and `soda2_update_op.pro:30`'s default `[33000,0,0]` -- which
reads as "image tag first, the rest unused" -- is consistent with it.

**Return shape.** IDL structures are always arrays (`size(/n_dimensions)` is 1
for a single structure). This port returns a ``dict`` for a one-element result
and a ``list[dict]`` for more, because a field read through a one-element
structure array is a scalar **under GDL** (measured: `r.res` has
`n_dimensions` 0 for `r = soda2_probespecs(name=...)`), and every `op` in this
port carries scalars. **IDL keeps `Array[1]` there** (read, not measured --
the same GDL collapse the Y2 `process_2d` bank met), so IDL's own
`example_batch.pro:47-52` builds an `op` whose probe fields are one-element
arrays; UND's 0914 HVPS-3 `op` in its SAVE file carries exactly that shape.
The port's scalars are the GDL reading, named here rather than hidden.

**Lookup edges, all banked:** a miss returns `base` silently; the `name` test
(`:1464`) is case- and whitespace-exact; an *array* `name` compares
element-wise against the leading probes only (IDL's shortest-operand rule), so
`name=['HVPS-3']` compares against `all[0]` and misses, and a two-element
`name` halts at `:1465` (`IF` on a two-element condition); `id` is guarded by
`max(id) lt n_elements(all)` (`:1474`), which admits a negative scalar (GDL
wraps it: `id=-1` is the last probe) and a negative entry in an index array
(clipped to 0); `name` wins over `id`; `fn` is ignored except for
`'Simulation'`, where `:1467-1469` hands the probe to `soda2_update_op`
(`update_op.py`, whose `.txt` header parse is refused by name there).
"""
from __future__ import annotations

import copy
from typing import Any

import numpy as np

__all__ = ["IDL_TYPES", "PROBE_NAMES", "SOURCE_LINES", "TAGS", "soda2_probespecs"]

#: The 18 tags of `base` (`:8-10`), in declaration order, lower-case.
TAGS: tuple[str, ...] = (
    "probename", "shortname", "format", "subformat", "probetype", "probeid",
    "greythresh", "res", "yres", "armwidth", "numdiodes", "tau", "firstsliceskip",
    "dofthreshold", "dofconst", "wavelength", "seatag", "dioderange",
)

#: IDL type of each tag, as `base` declares it (`:8-10`) and GDL reports it.
IDL_TYPES: dict[str, str] = {
    "probename": "STRING", "shortname": "STRING", "format": "STRING",
    "subformat": "INT", "probetype": "STRING", "probeid": "STRING",
    "greythresh": "INT", "res": "FLOAT", "yres": "FLOAT", "armwidth": "FLOAT",
    "numdiodes": "FLOAT", "tau": "FLOAT", "firstsliceskip": "INT",
    "dofthreshold": "FLOAT", "dofconst": "FLOAT", "wavelength": "FLOAT",
    "seatag": "LONG", "dioderange": "INT",
}

_DTYPES: dict[str, type] = {"INT": np.int16, "LONG": np.int32, "FLOAT": np.float32}
_ARRAY_LEN: dict[str, int] = {"seatag": 3, "dioderange": 2}   # lonarr(3), intarr(2)

#: The 72 blocks, in source order: the line of each block's `x=base`, then the
#: 17 values its `x.<tag>=` lines assign in `TAGS` order (`probename` ...
#: `seatag`), then `dioderange` (assigned by three blocks only; `None` keeps
#: `base`'s `[0, 0]`). Values are the source literals, unconverted -- `_coerce`
#: applies the field's type, as IDL's assignment does. Transcribed
#: mechanically from the `.pro` and asserted field by field against GDL's
#: evaluation of it (`tests/test_soda2_probespecs.py`).
_ROWS: tuple[tuple[Any, ...], ...] = (
    (18, "NASA Langley CAPS", "CIP10", "DMT", 0, "CIP", "", 0,
     25, 25, 10, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (0,), None),
    (39, "CAPS-Grey", "CIPG", "DMT", 1, "CIPG", "", 2,
     15, 15, 10, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (0,), None),
    (59, "CAPS-Grey (University of Wyoming)", "CIPG", "DMT", 1, "CIPG", "", 2,
     25, 25, 6.1, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (0,), None),
    (79, "NOAA HRD CIP Grey (PADS)", "CIPG", "DMT", 1, "CIPG", "", 2,
     25, 25, 10.0, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (0,), None),
    (99, "DLR CAPS-Grey (PADS)", "CIP_DLR", "DMT", 1, "CIPG", "", 2,
     25, 25, 4.0, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (0,), None),
    (119, "DLR PIP (PADS)", "PIP", "DMT", 1, "CIPG", "", 1,
     100, 100, 26.0, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (0,), None),
    (139, "WMI CIP (SEA M300)", "CIP", "SEA", 1, "CIPG", "", 1,
     15, 15, 10.0, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (33000, 32000,), None),
    (159, "CIRPAS CIP (PACS)", "CIP", "DMT", 0, "CIP", "", 0,
     25, 25, 6.1, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (0,), None),
    (179, "CIRPAS PIP (PACS)", "PIP", "DMT", 0, "CIP", "", 0,
     100, 100, 10, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (0,), None),
    (199, "CIRPAS CIP (PADS)", "CIP", "DMT", 1, "CIP", "", 0,
     25, 25, 6.1, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (0,), None),
    (219, "CIRPAS PIP (PADS)", "PIP", "DMT", 1, "CIP", "", 0,
     100, 100, 10, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (0,), None),
    (239, "NCAR-RAL CIP (PADS)", "CIP", "DMT", 1, "CIP", "", 0,
     25, 25, 10.0, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (0,), None),
    (259, "NCAR-RAL PIP (PADS)", "PIP", "DMT", 1, "CIP", "", 0,
     100, 100, 26.0, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (0,), None),
    (279, "NOAA HRD CIP (PADS)", "CIP", "DMT", 1, "CIP", "", 0,
     25, 25, 10.0, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (0,), None),
    (299, "NOAA HRD PIP (PADS)", "PIP", "DMT", 1, "CIP", "", 0,
     100, 100, 40.0, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (0,), None),
    (319, "University of Oslo CIP (PADS)", "CIP", "DMT", 1, "CIP", "", 0,
     25, 25, 10.0, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (0,), None),
    (338, "FAAM CIP100 (PADS)", "CIP", "DMT", 1, "CIP", "", 0,
     100, 100, 7.0, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (0,), None),
    (359, "FAAM CIP-Grey (PADS)", "CIPG", "DMT", 1, "CIPG", "", 2,
     15, 15, 4.0, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (0,), None),
    (379, "SEA CIP-Grey (SEA M300)", "CIPG", "SEA", 1, "CIPG", "", 2,
     25, 25, 7.0, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (3000, 2000,), None),
    (399, "NASA Glenn CIP-Grey (SEA M300)", "CIPG", "SEA", 1, "CIPG", "", 2,
     15, 15, 10.0, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (23000, 22000,), None),
    (419, "Shanxi CIP-Mono (PADS)", "CIP", "DMT", 1, "CIP", "", 0,
     25, 25, 10.0, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (0,), None),
    (439, "Shanxi PIP-Mono (PADS)", "PIP", "DMT", 1, "CIP", "", 0,
     100, 100, 26.0, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (0,), None),
    (459, "Shanxi PIP-Grey (PADS)", "PIPG", "DMT", 1, "CIPG", "", 2,
     100, 100, 26.0, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (0,), None),
    (479, "Monash CIP (SEA M300)", "CIP", "SEA", 1, "CIP", "", 0,
     25, 25, 7.0, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (33000,), None),
    (499, "NRC CIP (SEA M300)", "CIP", "SEA", 1, "CIP", "", 0,
     15, 15, 7.0, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (33000,), None),
    (519, "NRC PIP (SEA M300)", "PIP", "SEA", 1, "CIP", "", 0,
     100, 100, 22.7, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (31000,), None),
    (539, "NRC 2DC (SEA M300)", "2DC", "SEA", 1, "2DC", "", 0,
     50, 50, 7.7, 32, 0.58e-6, 1, 0.0, 3.0, 0.6328e-6, (7000, 7006, 7007,), None),
    (559, "NRC 2DP (SEA M300)", "2DP", "SEA", 1, "2DC", "", 0,
     200, 200, 26.0, 32, 0.58e-6, 1, 0.0, 3.0, 0.6328e-6, (8000, 8006, 8007,), None),
    (579, "HIWC PIP (SEA M300)", "PIP", "SEA", 1, "CIP", "", 0,
     100, 100, 22.2, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (35000, 34000, 0,), None),
    (599, "HIWC PIP (PADS)", "PIP", "DMT", 1, "CIP", "", 0,
     100, 100, 22.2, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (35000, 34000, 0,), None),
    (619, "CCP from SPEC (SEA M300)", "CIP", "SEA", 1, "CIP", "", 0,
     15, 15, 7.0, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (36000,), None),
    (639, "NIMS CCP (15um)", "CIP", "DMT", 1, "CIP", "", 0,
     15, 15, 4.0, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (0,), None),
    (659, "UNIVIE CIP Greyscale", "CIP", "DMT", 1, "CIPG", "", 2,
     15, 15, 7.0, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (0,), None),
    (679, "UNIVIE PIP Monoscale", "PIP", "DMT", 1, "CIP", "", 0,
     100, 100, 22.5, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (0,), None),
    (699, "NCAR Fast-2DC [C4] (25um)", "F2DC", "RAF", 3, "F2DC", "C4", 0,
     25, 25, 6.1, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (0,), None),
    (719, "NCAR Fast-2DC_v2 [C4] (25um)", "F2DC", "RAF", 3, "F2DC_v2", "C4", 0,
     25, 25, 6.1, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (0,), None),
    (739, "NCAR Fast-2DC [C4] (25um) Pre-2011", "F2DC", "RAF", 0, "F2DC", "C4", 0,
     25, 25, 6.1, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (0,), None),
    (759, "NCAR Fast-2DC (25um) 66% DoF threshold", "F2DC", "RAF", 3, "F2DC66", "C4", 0,
     25, 25, 6.1, 64, 0.051e-6, 0, 66.0, 3.0, 0.658e-6, (0,), None),
    (779, "NCAR Fast-2DC [C5] (25um)", "F2DC", "RAF", 3, "F2DC", "C5", 0,
     25, 25, 6.1, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (0,), None),
    (799, "NCAR Fast-2DC [C6] (10um)", "F2DC10", "RAF", 3, "F2DC", "C6", 0,
     10, 10, 6.1, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (0,), None),
    (819, "NCAR Fast-2DC_v2 [C6] (10um)", "F2DC10", "RAF", 3, "F2DC_v2", "C6", 0,
     10, 10, 6.1, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (0,), None),
    (839, "NCAR 2DP", "2DP", "RAF", 3, "2DC", "P1", 0,
     200, 200, 26.1, 32, 0.6e-6, 1, 0.0, 3.0, 0.6328e-6, (0,), None),
    (859, "NCAR Fast-2DP [P4] (150um)", "F2DP", "RAF", 3, "F2DC", "P4", 0,
     150, 150, 26.1, 64, 0.6e-6, 0, 0.0, 3.0, 0.6328e-6, (0,), None),
    (879, "Wyoming Fast-2DC (NCAR-RAF format)", "F2DC", "RAF", 3, "F2DC", "C5", 0,
     25, 25, 6.0, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (0,), None),
    (899, "Wyoming 2DP (NCAR-RAF format)", "2DP", "RAF", 4, "2DC", "P1", 0,
     200, 200, 26.0, 32, 0.6e-6, 1, 0.0, 3.0, 0.6328e-6, (0,), None),
    (919, "HVPS-3", "HVPS3", "SPEC", 0, "HVPS3", "V", 0,
     150, 150, 16.25, 128, 41.0e-9, 0, 0.0, 8.12, 0.785e-6, (0,), None),
    (939, "2D-S Horizontal Array", "2DS", "SPEC", 0, "2DS", "H", 0,
     10, 10, 6.3, 128, 41.0e-9, 0, 0.0, 8.12, 0.785e-6, (0,), None),
    (959, "2D-S Vertical Array", "2DS", "SPEC", 0, "2DS", "V", 0,
     10, 10, 6.3, 128, 41.0e-9, 0, 0.0, 8.12, 0.785e-6, (0,), None),
    (979, "2D-S Horizontal Array (11um)", "2DS", "SPEC", 0, "2DS", "H", 0,
     11, 10, 6.3, 128, 41.0e-9, 0, 0.0, 8.12, 0.785e-6, (0,), None),
    (999, "2D-S Vertical Array (11um)", "2DS", "SPEC", 0, "2DS", "V", 0,
     11, 10, 6.3, 128, 41.0e-9, 0, 0.0, 8.12, 0.785e-6, (0,), None),
    (1019, "Fast 2D-S Horizontal Array (11um)", "F2DS", "SPEC", 1, "2DS", "H", 0,
     11, 10, 6.3, 128, 41.0e-9, 0, 0.0, 8.12, 0.785e-6, (0,), None),
    (1039, "Fast 2D-S Vertical Array (11um)", "F2DS", "SPEC", 1, "2DS", "V", 0,
     11, 10, 6.3, 128, 41.0e-9, 0, 0.0, 8.12, 0.785e-6, (0,), None),
    (1059, "3VCPI/Hawkeye Horizontal Array", "3VCPI", "SPEC", 1, "3VCPI", "H", 0,
     10, 10, 5.08, 128, 41.0e-9, 0, 0.0, 8.12, 0.785e-6, (0,), None),
    (1079, "3VCPI/Hawkeye Horizontal Array (50um)", "3VCPI", "SPEC", 1, "3VCPI", "H", 0,
     50, 50, 5.08, 128, 41.0e-9, 0, 0.0, 8.12, 0.785e-6, (0,), None),
    (1099, "3VCPI/Hawkeye Vertical Array", "3VCPI", "SPEC", 1, "3VCPI", "V", 0,
     10, 10, 5.08, 128, 41.0e-9, 0, 0.0, 8.12, 0.785e-6, (0,), None),
    (1119, "HVPS-4 Vertical Array (50um)", "HVPS4", "SPEC", 2, "HVPS4", "V50", 0,
     50, 50, 12.0, 128, 41.0e-9, 0, 0.0, 8.12, 0.785e-6, (0,), None),
    (1139, "HVPS-4 Vertical Array (150um)", "HVPS4", "SPEC", 2, "HVPS4", "V150", 0,
     150, 150, 12.0, 128, 41.0e-9, 0, 0.0, 8.12, 0.785e-6, (0,), None),
    (1159, "HVPS-4 Horizontal Array (50um)", "HVPS4", "SPEC", 2, "HVPS4", "H50", 0,
     50, 50, 12.0, 128, 41.0e-9, 0, 0.0, 8.12, 0.785e-6, (0,), None),
    (1179, "HVPS-4 Horizontal Array (150um)", "HVPS4", "SPEC", 2, "HVPS4", "H150", 0,
     150, 150, 12.0, 128, 41.0e-9, 0, 0.0, 8.12, 0.785e-6, (0,), None),
    (1199, "UND 2DC", "2DC", "SEA", 0, "2DC", "", 0,
     30, 30, 6.1, 32, 0.6e-6, 1, 0.0, 3.0, 0.6328e-6, (5000, 5001, 5002,), None),
    (1219, "UND 2DC with Korolev Tips", "2DC7", "SEA", 0, "2DC", "", 0,
     30, 30, 7.0, 32, 0.6e-6, 1, 0.0, 3.0, 0.6328e-6, (5000, 5001, 5002,), None),
    (1239, "UND CIP (SEA M300)", "CIP", "SEA", 1, "CIP", "", 0,
     25, 25, 6.0, 64, 0.051e-6, 0, 0.0, 3.0, 0.658e-6, (33000, 32000, 0,), None),
    (1259, "MSC 2DC", "2DC", "SEA", 0, "2DC", "", 0,
     25, 25, 6.1, 32, 0.58e-6, 1, 0.0, 3.0, 0.6328e-6, (33000,), None),
    (1279, "SEA 1D2D-X (15um)", "1D2D-X", "SEA", 0, "1D2D", "", 0,
     15, 15, 5.83, 64, 0.020e-6, 0, 0.0, 8.0, 0.660e-6, (10000, 10001,), None),
    (1299, "SEA 1D2D-Y (50um)", "1D2D-Y", "SEA", 0, "1D2D", "", 0,
     50, 50, 26.0, 64, 0.020e-6, 0, 0.0, 8.0, 0.660e-6, (11000, 11001,), None),
    (1319, "SDSMT Hail Spectrometer (SEA)", "HAIL", "SEA", 0, "HAIL", "", 0,
     900, 900, 99.0, 64, 0.020e-6, 0, 0.0, 3.0, 0.660e-6, (320,), None),
    (1339, "SDSMT HVPS-1 (SEA)", "HVPS1", "SEA", 0, "HVPS1", "", 0,
     200, 400, 20.0, 256, 0.020e-6, 0, 0.0, 3.0, 0.660e-6, (6000, 6001, 6002,), (40, 230,)),
    (1360, "SDSMT HVPS-1 (1995 Format)", "HVPS1", "HVPS1995", 0, "HVPS1", "", 0,
     200, 400, 20.0, 256, 0.020e-6, 0, 0.0, 3.0, 0.660e-6, (6000, 6001, 6002,), (35, 220,)),
    (1381, "SDSMT 2DC (SEA)", "2DC", "SEA", 0, "2DC", "", 0,
     25, 25, 6.1, 32, 0.051e-6, 1, 0.0, 3.0, 0.632e-6, (300, 301, 302,), None),
    (1401, "SDSMT 2DP (SEA)", "2DP", "SEA", 0, "2DC", "", 0,
     200, 200, 26.0, 32, 0.051e-6, 1, 0.0, 3.0, 0.632e-6, (310, 311, 312,), None),
    (1421, "NCAR HVPS-1", "HVPS1", "RAF", 3, "HVPS1", "H1", 0,
     200, 400, 20.0, 256, 0.020e-6, 0, 0.0, 3.0, 0.660e-6, (0,), (35, 220,)),
    (1442, "Simulation", "SIM", "TXT", 0, "TXT", "", 0,
     0, 0, 0, 0, 0, 0, 0.0, 0.0, 0, (0,), None),
)


def _coerce(tag: str, value: Any) -> Any:
    """`value` converted to `tag`'s declared type, as IDL's field assignment does."""
    kind = IDL_TYPES[tag]
    if kind == "STRING":
        return str(value)
    dtype = _DTYPES[kind]
    if tag in _ARRAY_LEN:
        out: np.ndarray = np.zeros(_ARRAY_LEN[tag], dtype=dtype)
        if value is not None:
            vals = np.atleast_1d(np.asarray(value))
            # GDL-measured: fewer elements than the field fill the leading ones.
            out[: len(vals)] = vals
        return out
    return dtype(value)


def _base() -> dict[str, Any]:
    """`:8-10`: the `base` structure -- what every miss returns."""
    b: dict[str, Any] = {}
    for tag in TAGS:
        kind = IDL_TYPES[tag]
        b[tag] = "" if kind == "STRING" else _coerce(tag, None if tag in _ARRAY_LEN else 0)
    b["dofconst"] = np.float32(3.0)          # `dofconst:3.0`
    return b


def _build(row: tuple[Any, ...]) -> dict[str, Any]:
    x = _base()                               # `x=base`
    for tag, value in zip(TAGS, row[1:], strict=True):
        x[tag] = _coerce(tag, value)
    return x


#: `all`, built once. Never handed out directly: lookups return deep copies,
#: because IDL returns a copy and a caller that edits its `op` must not edit
#: the table for the next caller.
_ALL: tuple[dict[str, Any], ...] = tuple(_build(r) for r in _ROWS)

#: Every probe name, in table order (`all.probename`).
PROBE_NAMES: tuple[str, ...] = tuple(p["probename"] for p in _ALL)

#: Each probe's `x=base` line in the vendored `.pro`, for citation.
SOURCE_LINES: dict[str, int] = {r[1]: r[0] for r in _ROWS}


def _result(items: list[dict[str, Any]]) -> dict[str, Any] | list[dict[str, Any]]:
    items = [copy.deepcopy(p) for p in items]
    return items[0] if len(items) == 1 else items


def soda2_probespecs(
    name: str | list[str] | tuple[str, ...] | None = None,
    id: int | list[int] | tuple[int, ...] | None = None,  # noqa: A002 - the IDL keyword
    fn: str | None = None,
) -> dict[str, Any] | list[dict[str, Any]]:
    """`soda2_probespecs(name=, id=, fn=)`, `:1463-1478`.

    Source: ``soda2_probespecs.pro`` (SODA-2); bare line references here are into that file.

    Returns one probe as a ``dict`` (the table row, or `base` on a miss), or a
    ``list[dict]`` when IDL would return several. See the module docstring for
    every edge; each is a bank case.
    """
    n_all = len(_ALL)
    # :1463 `IF n_elements(name) ne 0`
    if name is not None and not (isinstance(name, (list, tuple)) and len(name) == 0):
        if isinstance(name, str):
            # :1464 scalar `name eq all.probename` -> every probe compared.
            w = [i for i, pn in enumerate(PROBE_NAMES) if pn == name]
            sim = name == "Simulation"
        else:
            names = list(name)
            # Shortest-operand rule: element k against all[k], k < min length.
            m = min(len(names), n_all)
            w = [k for k in range(m) if names[k] == PROBE_NAMES[k]]
            if len(names) > 1:
                # :1465 `IF` on a multi-element condition halts IDL/GDL.
                raise ValueError(
                    "soda2_probespecs.pro:1465: Expression must be a scalar or 1 "
                    "element array in this context (a name array of "
                    f"{len(names)} elements)")
            sim = names[0] == "Simulation"
            if sim and fn is not None:
                raise NotImplementedError(
                    "soda2_probespecs.pro:1465-1469 with a one-element ARRAY name "
                    "'Simulation' and fn=: `where` misses (it compares against "
                    "all[0] only), so :1467 subscripts all[-1]; not banked, "
                    "not ported")
        if sim and fn is not None:
            # :1467 create_struct(all[w], 'fn', fn, 'endbins', [0,0]); :1468.
            from arrayprobe_soda2.update_op import update_op

            probe = copy.deepcopy(_ALL[w[0]])
            probe["fn"] = fn
            probe["endbins"] = np.array([0, 0], dtype=np.int16)
            return update_op(probe)
        # :1471
        return _result([_ALL[i] for i in w]) if w else _base()
    # :1473 `IF n_elements(id) ne 0`
    if id is not None and not (isinstance(id, (list, tuple)) and len(id) == 0):
        if isinstance(id, (list, tuple, np.ndarray)):
            ids = [int(i) for i in np.asarray(id).ravel()]
            if max(ids) >= n_all:                     # :1474 guard
                return _base()
            # Index-array subscript: negative entries clip to 0 (GDL-measured).
            return _result([_ALL[max(i, 0)] for i in ids])
        i = int(id)
        if i >= n_all:
            return _base()
        if i < -n_all:
            raise IndexError(
                f"soda2_probespecs.pro:1474: id={i} is below -{n_all}; the guard "
                "admits it and the subscript is out of range (not banked)")
        # Negative scalar subscript: GDL wraps (id=-1 is the last probe).
        return _result([_ALL[i]])
    # :1478 everything.
    return [copy.deepcopy(p) for p in _ALL]
