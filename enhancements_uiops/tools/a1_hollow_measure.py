# SPDX-License-Identifier: BSD-3-Clause
"""Measure A1's spurious-hollow rate and write it to the tracked registry.

**Why this exists.** A1's headline figure ("of N hollow calls beyond diode 32, M are spurious")
was typed into eleven documents as though it were a constant. It is not: it is a statistic over
whichever flights happen to be decoded in `_decoded/`, a gitignored directory that the
reprocessing runs rewrite. On 2026-08-29 the same test that produced "67 of 110 (60.9 %)" produced
"64 of 106 (60.4 %)" -- not because anything regressed, but because three flights in the corpus had
been replaced by diode-corrected reprocessings since.

So the number goes in a registry with the corpus that produced it, and the prose is checked
against the registry (`tests/test_measurements_registry.py`). This is the project's standing rule
-- numbers in prose are read from a registry, never typed -- applied to the one number most likely
to end up on a conference slide.

Usage, from `enhancements_uiops/`:

    .venv/Scripts/python.exe scripts/a1_hollow_measure.py            # report only
    .venv/Scripts/python.exe scripts/a1_hollow_measure.py --write    # update registry

`--write` refuses to shrink the corpus silently: if fewer flights are present than the registry
already records, it says so and exits non-zero unless `--allow-smaller-corpus` is given. A
measurement taken while a reprocessing run has half the flights on disk is not an update, it is a
worse measurement wearing a newer date.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import netCDF4
import numpy as np

_ROOT = Path(__file__).resolve().parents[1]
_DECODED = _ROOT.parent / "_decoded"
_REGISTRY = _ROOT / "docs" / "measurements.json"

from arrayprobe.reject import is_it_hollow  # noqa: E402
from arrayprobe.render import reconstruct_particle_image  # noqa: E402

from arrayprobe_enhancements.wide_hollow_fix import wide_is_it_hollow  # noqa: E402

SAMPLE_PER_FLIGHT = 200


def _flights() -> list[tuple[str, Path, Path]]:
    found = []
    for proc_path in sorted(_DECODED.glob("proc.*.H.nc")):
        flight = proc_path.name[len("proc."):-len(".H.nc")]
        image_path = _DECODED / f"{flight}.H.cdf"
        if image_path.exists():
            found.append((flight, proc_path, image_path))
    return found


def measure() -> dict:
    """The same systematic-stride sample the test reports, as structured data."""
    per_flight, within, beyond = [], {"n": 0, "orig": 0, "wide": 0}, {"n": 0, "orig": 0, "wide": 0}

    for flight, proc_path, image_path in _flights():
        with netCDF4.Dataset(image_path) as img_ds, netCDF4.Dataset(proc_path) as proc_ds:
            n_particles = len(proc_ds.variables["image_auto_reject"][:])
            stride = max(1, n_particles // min(SAMPLE_PER_FLIGHT, n_particles))
            f_within = {"n": 0, "orig": 0, "wide": 0}
            f_beyond = {"n": 0, "orig": 0, "wide": 0}

            for idx in range(0, n_particles, stride):
                try:
                    shadow = reconstruct_particle_image(img_ds, proc_ds, idx)
                except Exception:
                    continue
                if shadow.shape[0] < 1 or shadow.shape[1] < 33:
                    continue
                cols = np.flatnonzero(shadow.any(axis=0))
                if cols.size == 0:
                    continue
                orig, _, _ = is_it_hollow(shadow, shadow.shape[0], shadow.shape[1])
                wide, _, _ = wide_is_it_hollow(shadow, shadow.shape[0], shadow.shape[1])
                if cols[-1] < 32:
                    for bucket in (f_within, within):
                        bucket["n"] += 1
                        bucket["orig"] += int(orig)
                        bucket["wide"] += int(wide)
                if cols[0] >= 32:
                    for bucket in (f_beyond, beyond):
                        bucket["n"] += 1
                        bucket["orig"] += int(orig)
                        bucket["wide"] += int(wide)

        per_flight.append({"flight": flight, "within_32": f_within, "beyond_32": f_beyond})

    spurious = beyond["orig"] - beyond["wide"]
    pct = round(100.0 * spurious / beyond["orig"], 1) if beyond["orig"] else None
    return {
        "measured": date.today().isoformat(),
        "corpus": [entry["flight"] for entry in per_flight],
        "sampled_particles": within["n"] + beyond["n"],
        "within_32": within,
        "beyond_32": beyond,
        "spurious": spurious,
        "spurious_of": beyond["orig"],
        "spurious_pct": pct,
        "per_flight": per_flight,
    }


def _load_registry() -> dict:
    if _REGISTRY.exists():
        return json.loads(_REGISTRY.read_text(encoding="utf-8"))
    return {}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="update docs/measurements.json")
    ap.add_argument("--allow-smaller-corpus", action="store_true")
    args = ap.parse_args(argv)

    result = measure()
    if not result["corpus"]:
        print("no decoded flight (proc + image pair) present -- nothing to measure")
        return 1

    print(f"corpus: {len(result['corpus'])} flights, "
          f"{result['sampled_particles']} particles sampled")
    for entry in result["per_flight"]:
        w, b = entry["within_32"], entry["beyond_32"]
        print(f"  {entry['flight']}: within-32 n={w['n']} orig={w['orig']} wide={w['wide']}"
              f" | beyond-32 n={b['n']} orig={b['orig']} wide={b['wide']}")
    print(f"beyond-32 spurious: {result['spurious']}/{result['spurious_of']} "
          f"({result['spurious_pct']}%)")
    if result["within_32"]["orig"] != result["within_32"]["wide"]:
        print("WARNING: the two implementations disagree inside 32 diodes -- "
              "that is the equivalence claim failing, not a measurement")
        return 2

    if not args.write:
        return 0

    registry = _load_registry()
    previous = registry.get("a1_spurious_hollow")
    if previous and len(result["corpus"]) < len(previous.get("corpus", [])) \
            and not args.allow_smaller_corpus:
        print(f"REFUSED: corpus shrank {len(previous['corpus'])} -> {len(result['corpus'])} "
              f"flights. Re-run when reprocessing finishes, or pass --allow-smaller-corpus.")
        return 3
    if previous:
        previous.pop("per_flight", None)   # keep history compact: totals and corpus only
        registry.setdefault("a1_spurious_hollow_history", []).append(previous)
    registry["a1_spurious_hollow"] = result
    _REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    _REGISTRY.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {_REGISTRY}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
