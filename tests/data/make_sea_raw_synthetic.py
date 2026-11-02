# SPDX-License-Identifier: BSD-3-Clause
"""Write ``sea_raw_synthetic.sea``: a clean synthetic SEA M300 file of DMT CIP
image buffers, for the tests that need a raw SEA input. No probe data.

Deterministic (``SEED``). ``N_BUFFERS`` buffers, each a tag-0 time record and
one tag-33000 compressed CIP image record (4098 bytes) holding
``PARTICLES_PER_BUFFER`` particles, ended by tag 999. No 2DC (tag 5000) record:
``read_binary_SEA.m`` crashes on one (``readers/sea.py``), so the ``.2DC.cdf``
it writes is empty and the reader returns ``(N_BUFFERS, 0, 0)``.

Two clocks, kept disjoint on purpose, as in a real SEA file: the particle
headers carry the probe clock (h=0, seconds of day ``FIRST_PROBE_SOD`` onward,
``BUFFER_STEP_S`` per buffer), while the tag-0 records carry a UTC-like clock
starting at ``UTC_START`` (hh, mm, ss).

The encoding helpers (directory records, particle headers, DMT run-length
coding, buffer assembly) are imported from ``make_soda2_sea_cip_fixture.py``,
whose file is a mixed-defect edge-case bank; this one has no defects.

Run from the repository root:
``.venv/Scripts/python.exe tests/data/make_sea_raw_synthetic.py [out_path]``.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SYNTHETIC_OUTPUTS = ("sea_raw_synthetic.sea",)
OUT = HERE / SYNTHETIC_OUTPUTS[0]
SEED = 20261019
N_BUFFERS = 12
PARTICLES_PER_BUFFER = 20
FIRST_PROBE_SOD = 13
BUFFER_STEP_S = 8
DT_MS = 37
UTC_START = (18, 3, 34)


def _helpers():
    path = HERE / "make_soda2_sea_cip_fixture.py"
    spec = importlib.util.spec_from_file_location("_sea_helpers_for_raw_synthetic", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build() -> tuple[bytes, list[int]]:
    """The file's bytes and the particle count of each buffer."""
    h = _helpers()
    h.RNG = np.random.default_rng(SEED)  # helpers draw from their module RNG
    bufs = []
    counts = []
    pc = 1
    uh, um, us = UTC_START
    for k in range(N_BUFFERS):
        sod = FIRST_PROBE_SOD + BUFFER_STEP_S * k
        parts = h._particles(PARTICLES_PER_BUFFER, 0, sod // 60, sod % 60, 0, pc, dt_ms=DT_MS)
        pc += PARTICLES_PER_BUFFER
        usod = uh * 3600 + um * 60 + us + BUFFER_STEP_S * k
        th, tm, ts = usod // 3600, usod // 60 % 60, usod % 60
        tbytes = h._time(th, tm, ts, 0, 100) + h._time(th, tm, ts, 90, 100)
        bufs.append(h._buffer([(0, tbytes), (33000, h._image_record(parts))]))
        counts.append(len(parts))
    return b"".join(bufs), counts


def main(argv: list[str]) -> int:
    out = Path(argv[1]) if len(argv) > 1 else OUT
    data, _ = build()
    out.write_bytes(data)
    print(f"wrote {out} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
