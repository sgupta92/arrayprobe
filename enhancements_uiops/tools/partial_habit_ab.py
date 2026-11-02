# SPDX-License-Identifier: BSD-3-Clause
"""A/B for ``partial_image_habit`` on the dense demo flight (row habit for accepted partial images).

Builds ``build_dense_demo_flight`` (the generator's defaults), runs stages 2-3 of
``scripts/run_flight.py`` (engine v3.1.4) in a subprocess (the driver's own isolation,
``pipeline.py``'s docstring), reconstructs every particle's silhouette, and reports:

* **A** -- what the engine already says about edge contact: ``image_touching_edge`` and
  how many particles carry habit ``'C'`` (withheld, centre-out);
* **B** -- Korolev & Sussman (2000) Sect. 4b's census: how many images RABIT would retrieve
  as complete, how many as accepted partials, and every ambiguous rule set.

The habit *fractions* are not computed: this is a 128-diode 2D-S and the only published
retrieval matrices are the OAP-2DC's (32 diodes), which ``classify_population`` refuses --
the refusal is exercised and printed, not bypassed.

**Why v3.1.4 only.** RABIT reads silhouettes, which are stage 2's (the reader's) output
and identical for both engines; a v3.5 stage 3 needs an aircraft TAS file this flight does
not carry (``scripts/make_demo_reference.py``'s ``RUN_TOML_V35``). The silhouettes measured
here are therefore the ones a v3.5 run would see.

Usage (from the repository root)::

    .venv/Scripts/python.exe enhancements_uiops/tools/partial_habit_ab.py
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

import netCDF4
import numpy as np
from arrayprobe.render import reconstruct_particle_image
from arrayprobe.tools.make_demo_flight import build_dense_demo_flight

from arrayprobe_enhancements import partial_image_habit as pih

REPO = Path(__file__).resolve().parents[2]
RUN_FLIGHT = REPO / "scripts" / "run_flight.py"


def measure_flight() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        raw = out / "base160101000000.2DS"
        build_dense_demo_flight(raw)
        subprocess.run([sys.executable, str(RUN_FLIGHT), str(raw), "--out", str(out),
                        "--stages", "23", "--preset", "DEMO_2DS_H", "--engine", "3.1.4",
                        "--port-validation"],
                       check=True, cwd=str(REPO),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        image_path = next(out.glob(f"{raw.stem}*.cdf"), None) or next(out.glob("*.H.cdf"))
        proc_path = next(p for p in out.glob("proc*.nc"))
        with netCDF4.Dataset(image_path) as image_ds, netCDF4.Dataset(proc_path) as proc_ds:
            n = len(proc_ds.dimensions["time"])
            touching = np.asarray(proc_ds.variables["image_touching_edge"][:]).astype(int)
            habit = np.asarray(proc_ds.variables["holroyd_habit"][:]).astype(int)
            images = [reconstruct_particle_image(image_ds, proc_ds, i) for i in range(n)]
    n_diodes = images[0].shape[1] if images else 0
    result = pih.census(images, n_diodes)
    edge_pixels = sum(int(img[:, 0].sum() + img[:, -1].sum()) for img in images)
    try:
        pih.classify_population(images, n_diodes=n_diodes, pixel_um=10.0)
        refusal = None
    except pih.NoRetrievalMatrixForProbe as exc:
        refusal = str(exc)
    return {
        "engine": "3.1.4",
        "n_particles": n,
        "n_diodes": n_diodes,
        "A_image_touching_edge": dict(sorted(Counter(touching.tolist()).items())),
        "A_habit_C_withheld": int((habit == ord("C")).sum()),
        "B_edge_pixels_total": edge_pixels,
        "B_groups": result.groups,
        "B_retrieved_complete": result.n_complete,
        "B_retrieved_accepted_partial": result.n_partial,
        "fractions_refused": refusal,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.parse_args(argv)
    print(json.dumps(measure_flight(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
