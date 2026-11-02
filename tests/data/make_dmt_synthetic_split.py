# SPDX-License-Identifier: BSD-3-Clause
"""Split the synthetic DMT/PADS raw ``dmt_raw_synthetic.cip`` into two files.

12 buffers of 4112 bytes -> ``dmt_raw_synthetic_part1.cip`` (buffers 1-6,
bytes 0..24671) and ``dmt_raw_synthetic_part2.cip`` (buffers 7-12), written to
a directory the caller names (a temporary one in the tests). Deterministic;
the parts concatenate back to the original byte for byte, so no split binary
is shipped. Used by ``scripts/validation/gdl/run_soda2_multifile_bank.py
--synthetic`` and by ``tests/test_soda2_multifile_*.py``.
"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "dmt_raw_synthetic.cip"
BUFFER = 4112
SPLIT = 6 * BUFFER  # 24672
NAMES = ("dmt_raw_synthetic_part1.cip", "dmt_raw_synthetic_part2.cip")


def write_split(dest: Path) -> list[Path]:
    raw = SOURCE.read_bytes()
    assert len(raw) == 12 * BUFFER, len(raw)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    parts = [dest / NAMES[0], dest / NAMES[1]]
    parts[0].write_bytes(raw[:SPLIT])
    parts[1].write_bytes(raw[SPLIT:])
    return parts


if __name__ == "__main__":
    import sys
    for p in write_split(Path(sys.argv[1]) if len(sys.argv) > 1 else HERE):
        print(p)
