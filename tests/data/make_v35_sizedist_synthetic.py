# SPDX-License-Identifier: BSD-3-Clause
"""Write a fully synthetic v3.5 particle-by-particle (proc) file for the sizeDist banks.

Stands in for the proc cut from real data that the v3.5 ``sizeDist.m`` Octave banks
(``v35_sizedist``, ``v35_default_int_arr_thresh``, ``v35_area_ratio_z``) ran on. Every value
is invented from ``numpy.random.default_rng(SEED)``. The variable set, order and types are
``arrayprobe_uiops.imgproc.imgproc_variables_v35`` (probetype 2, no optional outputs); the
file is NETCDF3_CLASSIC. Features the banks exercise:

* ``N_SECONDS`` whole seconds starting at ``START_HHMMSS`` (12:00:02, far from midnight, so no
  rollover branch is entered by accident), with background particles in every second; the
  banks' first TAS second (12:00:01) holds no particle, so the before-any-data branch
  (``sizeDist.m:1848-1875``) is exercised;
* shattering clusters: bursts of ``CLUSTER_SIZE`` particles spaced ``CLUSTER_GAP_S``
  (2 us, below the 6 us default interarrival threshold);
* two Holroyd habits (``'s'`` and ``'i'``) and a few auto-rejected particles;
* an area-ratio spread (``image_area`` over the area of a circle of ``image_diam_minR``)
  covering ~0.0, ~0.2, ~0.5 and up to 1.

Regenerate (S3 runs Octave on the output)::

    python tests/data/make_v35_sizedist_synthetic.py [out.nc]
"""

import os
import sys

import numpy as np
from netCDF4 import Dataset

HERE = os.path.dirname(os.path.abspath(__file__))
SYNTHETIC_OUTPUTS = ("v35_sizedist_synthetic.proc.nc",)
DEFAULT_OUT = os.path.join(HERE, SYNTHETIC_OUTPUTS[0])

SEED = 20261019
N_SECONDS = 8
START_HHMMSS = 120002
BACKGROUND_PER_SECOND = 40
CLUSTERS_PER_SECOND = 3
CLUSTER_SIZE = 6
CLUSTER_GAP_S = 2e-6
DIODE_SIZE_MM = 0.01
DIODENUM = 128
HABITS = (ord("s"), ord("i"))
AREA_RATIO_ANCHORS = (0.02, 0.2, 0.5)

_NC_TYPE = {"int": "i4", "short": "i2", "double": "f8", "byte": "i1", "float": "f4"}


def _variables():
    from arrayprobe_uiops.imgproc import imgproc_variables_v35
    return list(imgproc_variables_v35(
        iRectEllipse=0, iCalcAllDiodeStats=0, iQC=0, iNewHabit=0,
        extended_ellipse_outputs=None, probetype=2,
    ))


def particles(seed: int = SEED) -> dict:
    """Per-particle arrays, time-ordered, keyed by proc variable name."""
    rng = np.random.default_rng(seed)
    t_rel = []
    for s in range(N_SECONDS):
        t_rel.append(s + np.sort(rng.uniform(0.0, 0.999, BACKGROUND_PER_SECOND)))
        for c in range(CLUSTERS_PER_SECOND):
            t0 = s + (c + 0.5) / (CLUSTERS_PER_SECOND + 1) + rng.uniform(-0.05, 0.05)
            t_rel.append(t0 + CLUSTER_GAP_S * np.arange(CLUSTER_SIZE))
    t_rel = np.sort(np.concatenate(t_rel))
    n = t_rel.size
    whole = np.floor(t_rel).astype(np.int64)
    frac = t_rel - whole
    hh, mm, ss = START_HHMMSS // 10000, (START_HHMMSS // 100) % 100, START_HHMMSS % 100
    sec_of_day = (hh * 3600 + mm * 60 + ss + whole) % 86400  # wraps only a midnight-crossing span
    hhmmss = (sec_of_day // 3600) * 10000 + ((sec_of_day // 60) % 60) * 100 + sec_of_day % 60
    millisec = np.floor(frac * 1000.0)
    microsec = np.round((frac * 1000.0 - millisec) * 1000.0, 3)

    diam_px = rng.integers(2, 60, n)
    diam_mm = diam_px * DIODE_SIZE_MM
    ar = rng.uniform(0.05, 1.0, n)
    ar[: len(AREA_RATIO_ANCHORS) * 10] = np.repeat(AREA_RATIO_ANCHORS, 10)
    rng.shuffle(ar)
    area_mm2 = ar * np.pi / 4.0 * diam_mm ** 2
    habit = np.where(rng.random(n) < 0.5, HABITS[0], HABITS[1])
    # Accepted particles carry ord('0') == 48, as imgProc_sm writes them; a numeric 0 is not
    # an accept code (it decodes to an empty character in the type-3 shattering path).
    reject = np.full(n, ord("0"), dtype=np.int16)
    reject[rng.choice(n, max(1, n // 25), replace=False)] = ord("H")

    tis = (hh * 3600 + mm * 60 + ss) + t_rel
    inter = np.concatenate([[0.0], np.diff(tis)])
    return {
        "Date": np.full(n, 20160906, np.int32),
        "Time": hhmmss.astype(np.int32),
        "msec": millisec.astype(np.int16),
        "Time_in_seconds": tis,
        "SliceCount": diam_px.astype(np.int16),
        "DMT_DOF_SPEC_OVERLOAD": np.zeros(n),
        "Particle_number_all": np.arange(1, n + 1, dtype=np.int32),
        "particle_time": hhmmss.astype(np.int32),
        "particle_millisec": millisec.astype(np.int16),
        "particle_microsec": microsec,
        "parent_rec_num": (np.arange(n) // 10 + 1).astype(np.int32),
        "particle_num": (np.arange(n) % 30000 + 1).astype(np.int16),
        "image_length": diam_px.astype(np.int16),
        "image_width": np.maximum(1, diam_px * ar).astype(np.int16),
        "image_area": area_mm2,
        "image_longest_y": diam_px.astype(np.int16),
        "image_touching_edge": np.zeros(n, np.int8),
        "image_auto_reject": reject,
        "image_center_in": np.ones(n, np.int8),
        "image_axis_ratio": np.clip(ar, 0.05, 1.0),
        "image_diam_minR": diam_mm,
        "image_diam_AreaR": np.sqrt(4.0 * area_mm2 / np.pi),
        "image_perimeter": np.pi * diam_mm,
        "percent_shadow_area": ar * 100.0,
        "holroyd_habit": habit.astype(np.int16),
        "area_hole_ratio": np.zeros(n),
        "inter_arrival": inter,
    }


def write(path: str = DEFAULT_OUT, seed: int = SEED) -> str:
    data = particles(seed)
    n = data["Time"].size
    specs = _variables()
    with Dataset(path, "w", format="NETCDF3_CLASSIC") as ds:
        ds.createDimension("time", None)
        ds.createDimension("pos_count", 2)
        ds.createDimension("bin_count", DIODENUM)
        ds.setncattr("Description", "Synthetic v3.5 proc file (make_v35_sizedist_synthetic.py)")
        ds.setncattr("Probe Type", "2DS")
        for spec in specs:
            # MATLAB-order dims reversed, as ncio does (netCDF C order; time first).
            v = ds.createVariable(spec.name, _NC_TYPE[spec.xtype], tuple(reversed(spec.dims)))
            v.setncattr("Units", spec.units)
            v.setncattr("Description", spec.description)
        for spec in specs:
            if tuple(spec.dims) == ("time",):
                ds.variables[spec.name][:] = data.get(spec.name, np.zeros(n))
        ds.variables["position"][:] = np.vstack([np.arange(n), np.arange(n) + 1]).T % 32000
        ds.variables["bin_stats"][:] = np.zeros(DIODENUM, np.int32)
    return path


if __name__ == "__main__":
    print(write(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT))
