# SPDX-License-Identifier: BSD-3-Clause
"""Split ``s6_dmt_raw_fixture`` at a PADS buffer boundary into two files.

12 buffers of 4112 bytes -> ``s6_dmt_raw_fixture_part1`` (buffers 1-6, bytes
0..24671) and ``_part2`` (buffers 7-12). Deterministic; the parts concatenate
back to the original byte for byte. Used by
``gdl_oracle/run_soda2_multifile_bank.py`` case ``cip_split``.
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUFFER = 4112
SPLIT = 6 * BUFFER  # 24672


def main() -> int:
    raw = (HERE / "s6_dmt_raw_fixture").read_bytes()
    assert len(raw) == 12 * BUFFER, len(raw)
    (HERE / "s6_dmt_raw_fixture_part1").write_bytes(raw[:SPLIT])
    (HERE / "s6_dmt_raw_fixture_part2").write_bytes(raw[SPLIT:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
