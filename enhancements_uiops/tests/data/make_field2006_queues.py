# SPDX-License-Identifier: BSD-3-Clause
"""Write field2006_queues.csv: fixed, synthetic 400-entry inter-arrival queues.

Input to the Process2D harness (field2006_harness.cpp)
and to tests/test_field2006_vs_process2d.py. Synthetic only: seeded draws from a
two-exponential mixture plus hand-made edge cases. No measured data.

One line per queue: ``queue_id,v0,...,v399`` in seconds, each written with
``repr`` so the C ``strtod`` reads back the identical double.

Run from the repository root:
    .venv/Scripts/python.exe enhancements_uiops/tests/data/make_field2006_queues.py
"""

from __future__ import annotations

import pathlib

import numpy as np

NITQ = 400
OUT = pathlib.Path(__file__).with_name("field2006_queues.csv")


def _mixture(seed: int, p: float, lam1: float, lam2: float) -> np.ndarray:
    rng = np.random.default_rng(seed)
    first = rng.random(NITQ) < p
    return np.where(first, rng.exponential(1.0 / lam1, NITQ),
                    rng.exponential(1.0 / lam2, NITQ))


def queues() -> list[tuple[str, np.ndarray]]:
    out: list[tuple[str, np.ndarray]] = []
    # Process2D's initial queue, itq = {1}: one 1-s entry, the rest zero.
    init = np.zeros(NITQ)
    init[0] = 1.0
    out.append(("initial_queue", init))
    for k, (p, lam1, lam2) in enumerate([
            (0.9, 1.0e2, 1.0e5), (0.7, 1.0e2, 1.0e5), (0.5, 3.0e2, 3.0e4),
            (0.95, 1.0e3, 1.0e6), (0.8, 3.0e1, 1.0e5), (0.6, 1.0e2, 1.0e4)]):
        for seed in range(3):
            out.append((f"mix{k}_s{seed}", _mixture(1000 * k + seed, p, lam1, lam2)))
    # Single-mode (pure natural arrivals).
    rng = np.random.default_rng(77)
    out.append(("single_mode", rng.exponential(1.0e-2, NITQ)))
    # Fewer than 10 entries below 10 s: the fit refuses (returns -1).
    few = np.full(NITQ, 20.0)
    few[:5] = [1e-3, 2e-3, 5e-4, 1e-2, 3e-3]
    out.append(("low_count", few))
    # Entries exactly on bin endpoints and at the 10-s upper limit.
    ep = np.array([np.float32(10.0 ** (float(np.float32(i - 35)) / 5.0))
                   for i in range(41)], dtype=np.float64)
    edge = np.resize(ep, NITQ)
    out.append(("on_endpoints", edge))
    return out


def main() -> None:
    lines = []
    for qid, q in queues():
        assert q.shape == (NITQ,)
        lines.append(qid + "," + ",".join(repr(float(v)) for v in q))
    OUT.write_text("\n".join(lines) + "\n", encoding="ascii", newline="\n")
    print(f"wrote {OUT} ({len(lines)} queues)")


if __name__ == "__main__":
    main()
