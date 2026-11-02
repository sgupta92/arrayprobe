# SPDX-License-Identifier: BSD-3-Clause
"""Write a fully synthetic two-second v3.5 proc file for the TAS data-quality-record test.

``tests/test_v35_sd_tas_qc_attrs.py`` needs a proc input whose particles fall in the seconds
16:41:29 and 16:41:30 (TAS grid 164128, 164129, 164130). This reuses the particle builder and
writer of ``make_v35_sizedist_synthetic.py`` (seeded; nothing read from real data), starting the
two-second span at 16:41:29.

Regenerate::

    python tests/data/make_stock_div_synthetic.py           # both procs
    python tests/data/make_stock_div_synthetic.py out.nc    # base proc only

The midnight proc (``v35_div_synthetic_midnight_proc.nc``) serves the divergence bank's
``midnight`` case (``:806-810`` flight-day carryover). Its particles fill 00:00:00 and 00:00:01
only, while the case's TAS grid is ``[235959; 0; 1]``: the per-second grid crosses midnight
(rolled to 240000, 240001) but the particle times never decrease, so only the ``:806-810``
carryover (+240000 on every particle) puts them in their seconds. A proc whose particles
themselves cross midnight is corrected by the multi-day fix before ``:806``, leaving the carryover
nothing to do, and its mutant would go undetected.
"""

import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SYNTHETIC_OUTPUTS = ("v35_div_synthetic_base_proc.nc", "v35_div_synthetic_midnight_proc.nc")
DEFAULT_OUT = os.path.join(HERE, SYNTHETIC_OUTPUTS[0])
MIDNIGHT_OUT = os.path.join(HERE, SYNTHETIC_OUTPUTS[1])
START_HHMMSS = 164129
N_SECONDS = 2
#: the midnight proc's particles fill 00:00:00 and 00:00:01 only; the ``midnight`` case's TAS
#: grid (235959, 0, 1) starts a second earlier, so the particle stream never crosses midnight
MIDNIGHT_START_HHMMSS = 0
MIDNIGHT_N_SECONDS = 2


def _base():
    spec = importlib.util.spec_from_file_location(
        "make_v35_sizedist_synthetic", os.path.join(HERE, "make_v35_sizedist_synthetic.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def write(path: str = DEFAULT_OUT) -> str:
    base = _base()
    base.START_HHMMSS = START_HHMMSS
    base.N_SECONDS = N_SECONDS
    return base.write(path)


def write_midnight(path: str = MIDNIGHT_OUT) -> str:
    """Two seconds just after midnight (0, 1), no particle before it; same seeded builder."""
    base = _base()
    base.START_HHMMSS = MIDNIGHT_START_HHMMSS
    base.N_SECONDS = MIDNIGHT_N_SECONDS
    return base.write(path)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(write(sys.argv[1]))
    else:
        print(write())
        print(write_midnight())
