# SPDX-License-Identifier: BSD-3-Clause
"""Known-truth synthetic 2D-S flights: raw ``.2DS`` bytes plus a manifest of every particle.

**What this is for** (author: *"we will eventually use synthetic data also"* and
*"we are seeking the truth ... need evidence"*). Every other validation in this project is
*fidelity*: does the port reproduce what MATLAB (or IDL) wrote. Fidelity cannot say whether the
answer is right. A synthetic flight whose particle population is known exactly can: run it
through a chain and compare the size distribution the chain recovers with the one that was
drawn. This module writes such flights; ``scripts/truth_harness.py`` runs the chains
and does the comparison.

**What a truth test here can and cannot establish.** It establishes how a chain responds to
*this optical model's* images of round droplets: which gates remove which true droplets, how
the chain's assumed depth of field compares with where images actually form, how sizing moves
out-of-focus droplets between bins. It cannot establish that the chain is right on real data:
the optical model is ours (a binary-annulus rendering of Korolev's 50 %-threshold dimensions,
below), real probes add noise, stuck and dirty diodes, non-spherical ice, electronics dead time
and timing jitter that none of this reproduces, and a chain can be right on synthetic data and
wrong on real data. A chain that is *wrong* here, on round droplets under a documented model,
has a finding that does not depend on any archive.

The optical model -- every piece named, and marked where it is ours
------------------------------------------------------------------
* **Image dimensions** are Korolev (2007, JTECH 24:376-389, doi:10.1175/JTECH1980.1), Appendix
  B, p. 388: "Lookup Table for Retrieval of Sizes of Spherical Particles from their Binary
  Images Formed at 50 % Intensity Threshold Level" -- ``Z_d`` from 0 to 8.15 in steps of 0.05,
  ``D_edge/D0`` (the paper's eta for the external diameter, p. 377: "the normalized size of the
  image eta = D_m/D0 is solely a function of Z_d") and ``D_spot/D_edge``. Transcribed in full as
  :data:`KOROLEV_2007_APPENDIX_B` (164 rows) from the page image of
  ``developer/literature/atot-jtech1980_1.pdf``. ``Z_d = 4 lambda Z / D0**2`` (p. 377); beyond
  ``Z_dmax = 8.18`` no area of the image is below the 50 % level (p. 378), so the droplet
  produces no image at all (:data:`KOROLEV_2007_ZDMAX_50`). Lookup is **nearest row**, never
  interpolated: the table jumps where a second ring appears (e.g. ``D_edge/D0`` 1.407 at 1.90,
  1.074 at 1.95), and a linear interpolation would invent images across the jump.
* **The image is rendered as a binary annulus** -- outer diameter ``D_edge``, hole ``D_spot`` --
  **ours, an approximation**: Korolev's Eqs. (1)-(2), p. 378, treat the 50 % image as one ring
  and state the second rings are insignificant for retrieval; the continuous intensity inside
  the ring is not uniform, which this ignores.
* **Diodes**: Korolev p. 379's model for "conventional 2D probes" -- active area 0.8 of the pitch
  across the array by 1 slice along it, triggered when the light integrated over the area is
  decreased by 50 %; with a binary annulus that is "at least half of the active area is inside
  the ring" (:attr:`OpticalModel.active_x`, :attr:`OpticalModel.n_sub`).
* **2D-S geometry**: 128 diodes at 10 um, arm separation 63 mm -- ``sizeDist.m:365-390``'s 2DS
  case, as :func:`arrayprobe.constants.sizedist_config` carries it; wavelength 785 nm, SODA-2's
  2D-S probe specification (``arrayprobe_soda2.probespecs``, ``soda2_probespecs.pro:955``).
  Note that UIOOPS' own depth of field uses a hard-coded 680 nm for every probe
  (``calc_sa_randombins.m``, ``arrayprobe.sample_area``) -- a chain property the harness
  measures, not something this module adopts.
* **Clock**: the particle time word counts one tick per slice, ``pixel / TAS`` seconds -- the
  convention ``imgproc.py:955`` and SODA-2's ``freq`` both decode with. Records never straddle a
  second, and each record's header time is its last particle's time (SODA-2 counts particle
  times backwards from the buffer time, ``processbuffer_spec.py`` ``:352-357``).
* **Arrival**: droplets arrive as a Poisson process in time; the centre is uniform across the
  sampled width and (``depth="uniform"``) uniform in ``Z`` between the arms. Two particles
  closer than the first one's image length plus two slices cannot both be imaged by a real
  array, so a later particle is pushed back to that separation (ours; recorded in the manifest).
* **Shattering bursts** (optional): a burst is a cluster of small in-focus fragments, each
  separated from the previous by a gap drawn uniformly from ``burst_gap_us``. Fragments are
  ``kind="fragment"`` in the manifest and are **not** part of the true droplet population.

The truth
---------
The manifest records every drawn particle, imaged or not: its true diameter, time, position
across the array, distance from the object plane, ``Z_d``, whether it produced an image, whether
that image was clipped by an array end, and the clock value written. The true number
concentration of droplets in a size bin is the count drawn in that bin divided by the volume the
draw covered, ``TAS * T * width * depth`` (:meth:`TruthManifest.sampled_volume_m3`).
"""

from __future__ import annotations

import dataclasses
import json
import math
from pathlib import Path

import numpy as np

from arrayprobe.tools.make_demo_flight import _hk_words, image_packet, raw_file, run_word
from arrayprobe_uiops import spec_core as spec

__all__ = [
    "KOROLEV_2007_APPENDIX_B", "KOROLEV_2007_ZDMAX_50", "korolev_dimensions",
    "OpticalModel", "render_droplet", "image_runs", "PSD", "FlightSpec",
    "TruthManifest", "build_truth_flight", "MANIFEST_SUFFIX", "write_aircraft_tas",
]

# ---------------------------------------------------------------------------
# Korolev (2007) Appendix B, p. 388 -- transcribed from the page, all 164 rows.
# Three column blocks on the page; each string below is one block, one row per
# line: Z_d, D_edge/D0, D_spot/D_edge.
# ---------------------------------------------------------------------------
_APPENDIX_B_TEXT = """
0.00 1.000 0.003
0.05 1.054 0.008
0.10 1.083 0.017
0.15 1.101 0.024
0.20 1.095 0.033
0.25 1.110 0.040
0.30 1.148 0.047
0.35 1.162 0.054
0.40 1.155 0.062
0.45 1.123 0.072
0.50 1.182 0.076
0.55 1.121 0.088
0.60 1.162 0.093
0.65 1.210 0.096
0.70 1.242 0.101
0.75 1.134 0.119
0.80 1.166 0.123
0.85 1.202 0.127
0.90 1.238 0.130
0.95 1.270 0.134
1.00 1.294 0.139
1.05 1.278 0.148
1.10 1.130 0.175
1.15 1.148 0.180
1.20 1.170 0.184
1.25 1.194 0.188
1.30 1.218 0.192
1.35 1.242 0.195
1.40 1.265 0.199
1.45 1.288 0.202
1.50 1.310 0.206
1.55 1.331 0.209
1.60 1.351 0.213
1.65 1.369 0.217
1.70 1.386 0.221
1.75 1.400 0.225
1.80 1.411 0.230
1.85 1.416 0.235
1.90 1.407 0.243
1.95 1.074 0.327
2.00 1.080 0.334
2.05 1.087 0.340
2.10 1.096 0.345
2.15 1.106 0.351
2.20 1.117 0.355
2.25 1.127 0.360
2.30 1.139 0.365
2.35 1.150 0.369
2.40 1.162 0.373
2.45 1.173 0.377
2.50 1.185 0.381
2.55 1.197 0.385
2.60 1.208 0.389
2.65 1.220 0.393
2.70 1.232 0.397
2.75 1.243 0.400
2.80 1.255 0.404
2.85 1.266 0.408
2.90 1.277 0.411
2.95 1.289 0.415
3.00 1.300 0.419
3.05 1.311 0.422
3.10 1.322 0.426
3.15 1.333 0.429
3.20 1.344 0.433
3.25 1.355 0.436
3.30 1.366 0.439
3.35 1.376 0.443
3.40 1.387 0.446
3.45 1.397 0.450
3.50 1.407 0.453
3.55 1.418 0.457
3.60 1.428 0.460
3.65 1.438 0.463
3.70 1.448 0.467
3.75 1.458 0.470
3.80 1.467 0.473
3.85 1.477 0.477
3.90 1.486 0.480
3.95 1.496 0.484
4.00 1.505 0.487
4.05 1.515 0.490
4.10 1.524 0.494
4.15 1.533 0.497
4.20 1.542 0.501
4.25 1.551 0.504
4.30 1.559 0.507
4.35 1.568 0.511
4.40 1.577 0.514
4.45 1.585 0.518
4.50 1.594 0.521
4.55 1.602 0.525
4.60 1.610 0.528
4.65 1.618 0.532
4.70 1.626 0.535
4.75 1.634 0.539
4.80 1.642 0.543
4.85 1.650 0.547
4.90 1.657 0.550
4.95 1.665 0.554
5.00 1.673 0.558
5.05 1.680 0.562
5.10 1.687 0.566
5.15 1.694 0.569
5.20 1.702 0.572
5.25 1.709 0.575
5.30 1.716 0.578
5.35 1.722 0.581
5.40 1.729 0.584
5.45 1.736 0.587
5.50 1.742 0.590
5.55 1.749 0.593
5.60 1.755 0.596
5.65 1.761 0.598
5.70 1.768 0.601
5.75 1.774 0.605
5.80 1.780 0.610
5.85 1.786 0.614
5.90 1.791 0.618
5.95 1.797 0.623
6.00 1.803 0.627
6.05 1.808 0.631
6.10 1.813 0.635
6.15 1.819 0.640
6.20 1.824 0.644
6.25 1.829 0.648
6.30 1.834 0.653
6.35 1.839 0.657
6.40 1.843 0.662
6.45 1.848 0.666
6.50 1.852 0.671
6.55 1.857 0.676
6.60 1.861 0.680
6.65 1.865 0.685
6.70 1.869 0.690
6.75 1.872 0.695
6.80 1.876 0.700
6.85 1.880 0.705
6.90 1.883 0.711
6.95 1.886 0.716
7.00 1.889 0.721
7.05 1.892 0.727
7.10 1.895 0.733
7.15 1.897 0.738
7.20 1.899 0.744
7.25 1.901 0.751
7.30 1.903 0.757
7.35 1.905 0.763
7.40 1.906 0.770
7.45 1.907 0.777
7.50 1.908 0.784
7.55 1.908 0.792
7.60 1.908 0.800
7.65 1.907 0.808
7.70 1.907 0.817
7.75 1.905 0.826
7.80 1.903 0.836
7.85 1.900 0.846
7.90 1.897 0.858
7.95 1.892 0.870
8.00 1.885 0.884
8.05 1.877 0.901
8.10 1.865 0.921
8.15 1.845 0.950
"""

def _parse_appendix_b_row(line: str) -> tuple[float, float, float]:
    """Each row is exactly ``(Z_d, D_edge/D0, D_spot/D_edge)``; unpacking (rather than a
    variable-length ``tuple(float(v) for v in ...)``) is what lets mypy see the fixed width
    the type below declares -- a malformed row now fails loudly here instead of silently
    producing a tuple of the wrong length."""
    a, b, c = line.split()
    return float(a), float(b), float(c)


#: Korolev (2007) Appendix B (p. 388): ``(Z_d, D_edge/D0, D_spot/D_edge)``, 50 % threshold.
KOROLEV_2007_APPENDIX_B: tuple[tuple[float, float, float], ...] = tuple(
    _parse_appendix_b_row(line) for line in _APPENDIX_B_TEXT.strip().splitlines()
)

#: Korolev (2007) p. 378: the largest ``Z_d`` at which any area of the image is below the 50 %
#: intensity level (citing KEA98). Beyond it a droplet produces no image.
KOROLEV_2007_ZDMAX_50: float = 8.18

_ZD = np.array([r[0] for r in KOROLEV_2007_APPENDIX_B])
_EDGE = np.array([r[1] for r in KOROLEV_2007_APPENDIX_B])
_SPOT = np.array([r[2] for r in KOROLEV_2007_APPENDIX_B])


def korolev_dimensions(zd: float) -> tuple[float, float] | None:
    """``(D_edge/D0, D_spot/D_edge)`` at ``zd`` -- the nearest Appendix B row; ``None`` beyond
    ``Z_dmax`` (no image). Never interpolated (see the module docstring)."""
    zd = abs(float(zd))
    if zd > KOROLEV_2007_ZDMAX_50:
        return None
    i = int(np.argmin(np.abs(_ZD - zd)))
    return float(_EDGE[i]), float(_SPOT[i])


# ---------------------------------------------------------------------------
# Rendering onto the diode array
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class OpticalModel:
    """How a droplet becomes a binary image on a 2D-S-like array. Defaults: the 2D-S."""

    pixel_um: float = 10.0        #: diode pitch = slice length (TAS-clocked); sizeDist.m 2DS case
    num_diodes: int = 128         #: sizeDist.m 2DS case
    armdst_mm: float = 63.0       #: arm separation; sizeDist.m 2DS case
    wavelength_um: float = 0.785  #: soda2_probespecs.pro 2D-S rows
    active_x: float = 0.8         #: diode active width / pitch (Korolev 2007 p. 379)
    active_y: float = 1.0         #: diode active length / slice (Korolev 2007 p. 379)
    n_sub: int = 5                #: sub-samples per axis over the active area
    coverage: float = 0.5         #: shadowed when >= this fraction of the active area is dark

    def zd(self, d0_um: float, z_mm: float) -> float:
        """Korolev's ``Z_d = 4 lambda Z / D0**2`` (p. 377), dimensionless."""
        return 4.0 * self.wavelength_um * abs(z_mm) * 1000.0 / (d0_um * d0_um)

    def z_max_mm(self, d0_um: float) -> float:
        """Distance from the object plane at which ``Z_d`` reaches ``Z_dmax`` (8.18)."""
        return KOROLEV_2007_ZDMAX_50 * d0_um * d0_um / (4.0 * self.wavelength_um) / 1000.0


def render_droplet(d0_um: float, zd: float, x_um: float, y_phase: float,
                   model: OpticalModel) -> tuple[np.ndarray, bool] | None:
    """The binary image of one droplet, ``(rows=slices, cols=num_diodes)`` bool, and whether it
    touches an array end; ``None`` if nothing on the array is shadowed.

    ``x_um`` is the centre across the array, measured from the outer edge of diode 1 (so the
    array spans ``[0, num_diodes * pixel_um)``); ``y_phase`` in ``[0, 1)`` places the centre
    within a slice. Diodes outside the array are simply absent -- that is the edge clipping.
    """
    dims = korolev_dimensions(zd)
    if dims is None:
        return None
    edge, spot = dims
    r_out = 0.5 * d0_um * edge
    r_in = r_out * spot
    p = model.pixel_um
    k = (np.arange(model.n_sub) + 0.5) / model.n_sub - 0.5
    sx = k * model.active_x * p
    sy = k * model.active_y * p
    n_rows = int(math.ceil(2.0 * r_out / p)) + 2
    yc = r_out + p + y_phase * p              # centre, from the start of row 0
    rows_c = (np.arange(n_rows) + 0.5) * p     # slice centres
    lo = max(0, int(math.floor((x_um - r_out) / p)) - 1)
    hi = min(model.num_diodes, int(math.ceil((x_um + r_out) / p)) + 1)
    if hi <= lo:
        return None
    cols_c = (np.arange(lo, hi) + 0.5) * p
    dy = rows_c[:, None, None, None] + sy[None, None, :, None] - yc
    dx = cols_c[None, :, None, None] + sx[None, None, None, :] - x_um
    r = np.sqrt(dx * dx + dy * dy)
    dark = ((r <= r_out) & (r >= r_in)).mean(axis=(2, 3)) >= model.coverage
    img = np.zeros((n_rows, model.num_diodes), dtype=bool)
    img[:, lo:hi] = dark
    rows = np.flatnonzero(img.any(axis=1))
    if rows.size == 0:
        return None
    img = img[rows[0]:rows[-1] + 1]
    touches = bool(img[:, 0].any() or img[:, -1].any())
    return img, touches


def image_runs(img: np.ndarray) -> list[int]:
    """Run-length words for a binary image, one slice per row, in the encoding
    the earlier translation's SPEC decoder reads (``read_binary_SPEC.m:223-241``): a
    slice's first word carries the absolute clear count, later words the clear gap from the
    previous run's end (the same rule :func:`arrayprobe.tools.make_demo_flight.ring_runs`
    documents). An empty interior slice is ``run_word(0, 0)``, which the decoder writes as
    nothing; a run longer than 127 diodes is split, since a run field is seven bits."""
    words: list[int] = []
    for j, row in enumerate(img):
        idx = np.flatnonzero(row)
        first = True
        if idx.size == 0:
            words.append(run_word(0, 0, new_slice=(j > 0)))
            continue
        breaks = np.flatnonzero(np.diff(idx) > 1)
        starts = np.concatenate([[idx[0]], idx[breaks + 1]])
        ends = np.concatenate([idx[breaks], [idx[-1]]]) + 1   # exclusive
        prev_end = 0
        for s, e in zip(starts.tolist(), ends.tolist(), strict=True):
            gap = s - prev_end
            length = e - s
            while length > 0:
                aa = min(length, 127)
                words.append(run_word(aa, gap, new_slice=(first and j > 0)))
                first = False
                gap = 0
                length -= aa
            prev_end = e
    return words


# ---------------------------------------------------------------------------
# The population and the flight
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class PSD:
    """The true droplet size distribution the flight draws from.

    ``kind="lognormal"``: ``median_um`` and geometric standard deviation ``gsd``, truncated to
    ``[d_min_um, d_max_um]``. ``kind="discrete"``: ``diameters_um`` drawn uniformly (e.g. one
    diameter per bin centre, for a flat-in-count test).
    """

    kind: str = "lognormal"
    median_um: float = 60.0
    gsd: float = 1.8
    d_min_um: float = 15.0
    d_max_um: float = 500.0
    diameters_um: tuple[float, ...] = ()

    def draw(self, rng: np.random.Generator, n: int) -> np.ndarray:
        """Draw ``n`` true diameters (um) from this distribution using ``rng``."""
        if self.kind == "discrete":
            return rng.choice(np.asarray(self.diameters_um, dtype=float), size=n)
        if self.kind != "lognormal":
            raise ValueError(f"unknown PSD kind {self.kind!r}")
        out = np.empty(0)
        while out.size < n:
            d = np.exp(rng.normal(math.log(self.median_um), math.log(self.gsd), 2 * n + 16))
            out = np.concatenate([out, d[(d >= self.d_min_um) & (d <= self.d_max_um)]])
        return out[:n]


@dataclasses.dataclass(frozen=True)
class FlightSpec:
    """Everything that determines a synthetic flight. Same spec + same seed = same bytes."""

    n_seconds: int = 20
    rate_per_s: float = 400.0      #: mean droplets per second drawn in the sampled volume
    psd: PSD = PSD()
    seed: int = 20260915
    tas_mps: float = 130.0
    depth: str = "uniform"         #: "uniform" in Z between the arms, or "in_focus" (Z = 0)
    across: str = "margin"         #: "margin": centre uniform over the array +- margin_um;
    #: "mid": centre uniform where the in-focus disk cannot touch an array end
    margin_um: float = 600.0
    burst_rate_per_s: float = 0.0  #: shattering bursts per second (0 = none)
    fragments_per_burst: tuple[int, int] = (4, 12)
    fragment_d_um: tuple[float, float] = (20.0, 80.0)
    burst_gap_us: tuple[float, float] = (0.3, 3.0)
    start: tuple[int, int, int] = (6, 6, 40)   #: HH, MM, SS of the first second
    date: tuple[int, int, int, int] = (2016, 9, 2, 6)   #: year, month, day-of-week, day

    def to_dict(self) -> dict:
        """A plain-dict form of this spec, JSON-round-trippable via :meth:`from_dict`."""
        d = dataclasses.asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> FlightSpec:
        """Rebuild a spec from :meth:`to_dict`'s output (tuples restored from lists)."""
        d = dict(d)
        d["psd"] = PSD(**{**d["psd"], "diameters_um": tuple(d["psd"]["diameters_um"])})
        for k in ("fragments_per_burst", "fragment_d_um", "burst_gap_us", "start", "date"):
            d[k] = tuple(d[k])
        return cls(**d)


MANIFEST_SUFFIX = ".truth.json"

#: Manifest columns, in order, with their dtype.
_COLUMNS = {
    "kind": str, "d0_um": float, "t_s": float, "second": int, "x_um": float, "z_mm": float,
    "zd": float, "imaged": bool, "clipped": bool, "n_slices": int, "clock": int,
    "record": int, "pushed_us": float,
}


@dataclasses.dataclass
class TruthManifest:
    """The truth: the spec, the optical model, and one entry per drawn particle (columnar)."""

    spec: FlightSpec
    model: OpticalModel
    columns: dict[str, list]
    raw_name: str = ""

    def __len__(self) -> int:
        return len(self.columns["kind"])

    def array(self, name: str) -> np.ndarray:
        """The named manifest column (see :data:`_COLUMNS`) as a NumPy array."""
        return np.asarray(self.columns[name])

    @property
    def sampled_width_um(self) -> float:
        """Across-array width the centres were drawn over."""
        w = self.model.num_diodes * self.model.pixel_um
        if self.spec.across == "margin":
            return w + 2.0 * self.spec.margin_um
        return w  # "mid": reported as the array width; mid mode is a count-level anchor only

    def sampled_volume_m3(self) -> float:
        """``TAS * T * width * depth`` -- the volume the droplets were drawn in. Meaningful for
        ``depth="uniform"``; an in-focus flight has no depth, so its truth is counts only."""
        if self.spec.depth != "uniform":
            raise ValueError("an in-focus flight has no sampled depth; compare counts")
        return (self.spec.tas_mps * self.spec.n_seconds * self.sampled_width_um * 1e-6
                * self.model.armdst_mm * 1e-3)

    def to_json(self, path) -> Path:
        """Write this manifest (spec, optical model and per-particle columns) as JSON."""
        path = Path(path)
        doc = {"format": "arrayprobe synthetic truth manifest v1", "raw": self.raw_name,
               "spec": self.spec.to_dict(), "model": dataclasses.asdict(self.model),
               "columns": self.columns}
        path.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
        return path

    @classmethod
    def from_json(cls, path) -> TruthManifest:
        """Read a manifest written by :meth:`to_json` back into a :class:`TruthManifest`."""
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        cols = {k: [_COLUMNS[k](v) for v in doc["columns"][k]] for k in _COLUMNS}
        return cls(spec=FlightSpec.from_dict(doc["spec"]), model=OpticalModel(**doc["model"]),
                   columns=cols, raw_name=doc.get("raw", ""))


def _draw_population(spec: FlightSpec, model: OpticalModel, rng: np.random.Generator):
    """Droplets and fragments, time-ordered: (kind, d0, t, x, z) arrays."""
    width = model.num_diodes * model.pixel_um
    kinds, d0s, ts, xs, zs = [], [], [], [], []
    for sec in range(spec.n_seconds):
        n = int(rng.poisson(spec.rate_per_s))
        d = spec.psd.draw(rng, n)
        t = sec + rng.uniform(0.0, 1.0, n)
        if spec.across == "margin":
            x = rng.uniform(-spec.margin_um, width + spec.margin_um, n)
        elif spec.across == "mid":
            # The in-focus disk of diameter d stays two diodes clear of both ends.
            half = 0.5 * d + 2 * model.pixel_um
            x = half + rng.uniform(0.0, 1.0, n) * (width - 2 * half)
        else:
            raise ValueError(f"unknown across mode {spec.across!r}")
        if spec.depth == "uniform":
            z = rng.uniform(-0.5 * model.armdst_mm, 0.5 * model.armdst_mm, n)
        elif spec.depth == "in_focus":
            z = np.zeros(n)
        else:
            raise ValueError(f"unknown depth mode {spec.depth!r}")
        kinds += ["droplet"] * n
        d0s.append(d)
        ts.append(t)
        xs.append(x)
        zs.append(z)
        if spec.burst_rate_per_s > 0:
            for _ in range(int(rng.poisson(spec.burst_rate_per_s))):
                k = int(rng.integers(spec.fragments_per_burst[0], spec.fragments_per_burst[1] + 1))
                t0 = sec + rng.uniform(0.0, 0.99)
                gaps = rng.uniform(*spec.burst_gap_us, k) * 1e-6
                fd = rng.uniform(*spec.fragment_d_um, k)
                fx = rng.uniform(0.25 * width, 0.75 * width, k)
                kinds += ["fragment"] * k
                d0s.append(fd)
                ts.append(t0 + np.cumsum(gaps))
                xs.append(fx)
                zs.append(np.zeros(k))
    kind = np.array(kinds, dtype=object)
    d0 = np.concatenate(d0s) if d0s else np.zeros(0)
    t = np.concatenate(ts) if ts else np.zeros(0)
    x = np.concatenate(xs) if xs else np.zeros(0)
    z = np.concatenate(zs) if zs else np.zeros(0)
    order = np.argsort(t, kind="stable")
    return kind[order], d0[order], t[order], x[order], z[order]


#: Particle clock at the start of the flight (ticks). Low enough that a flight of a few hundred
#: seconds at 170 m/s never wraps the 32-bit counter.
CLOCK0 = 0x0100_0000

#: Image-record payload budget (words): ``DATA_WORDS`` less a margin, so no packet reaches the
#: end of the record.
_RECORD_BUDGET = spec.DATA_WORDS - 8


#: Sub-second stamp of each housekeeping record; see the comment where it is used.
HK_STAMP = 0.990


def build_truth_flight(path, flight: FlightSpec | None = None,
                       model: OpticalModel | None = None) -> TruthManifest:
    """Write the raw ``.2DS`` file at ``path`` and its manifest at ``path + MANIFEST_SUFFIX``.

    ``path``'s stem should follow SPEC's ``base<YYMMDDhhmmss>`` convention if the combine stage
    is to run on it (see :mod:`arrayprobe.tools.make_demo_flight`). Returns the manifest.
    """
    flight = FlightSpec() if flight is None else flight
    model = OpticalModel() if model is None else model
    rng = np.random.default_rng(flight.seed)
    kind, d0, t, x, z = _draw_population(flight, model, rng)
    n = len(t)
    zd = np.array([model.zd(a, b) for a, b in zip(d0, z, strict=True)])
    phase = rng.uniform(0.0, 1.0, n)
    tick_s = model.pixel_um * 1e-6 / flight.tas_mps

    imaged = np.zeros(n, bool)
    clipped = np.zeros(n, bool)
    n_slices = np.zeros(n, np.int64)
    clock = np.full(n, -1, np.int64)
    record = np.full(n, -1, np.int64)
    pushed = np.zeros(n)
    t_eff = t.copy()

    hh, mm, ss = flight.start
    year, month, dow, day = flight.date
    records: list[tuple[tuple, list[int]]] = []
    last_tick = -(10 ** 9)
    last_len = 0
    counter = 0

    def header(sec: int, t_last: float) -> tuple:
        tod = hh * 3600 + mm * 60 + ss + sec
        ms = int(min(999, math.floor((t_last - sec) * 1000.0)))
        return (year, month, dow, day, tod // 3600, (tod // 60) % 60, tod % 60, ms)

    i = 0
    for sec in range(flight.n_seconds):
        payload: list[int] = []
        t_last = float(sec)
        while i < n and t[i] < sec + 1:
            out = render_droplet(d0[i], zd[i], x[i], phase[i], model)
            if out is None:
                i += 1
                continue
            img, touches = out
            tick = int(round(t_eff[i] / tick_s))
            min_tick = last_tick + last_len + 2
            if tick < min_tick:
                pushed[i] = (min_tick - tick) * tick_s * 1e6
                tick = min_tick
                t_eff[i] = tick * tick_s
            if t_eff[i] >= sec + 1:   # pushed out of its second: not imaged in this one
                i += 1
                continue
            runs = image_runs(img)
            counter = (counter + 1) % 65536
            pkt = image_packet(runs, img.shape[0], channel="H", pc=counter,
                               t_particle=CLOCK0 + tick)
            if len(payload) + len(pkt) > _RECORD_BUDGET:
                records.append((header(sec, t_last), payload))
                payload = []
            payload.extend(pkt)
            t_last = t_eff[i]
            imaged[i], clipped[i], n_slices[i] = True, touches, img.shape[0]
            clock[i] = CLOCK0 + tick
            record[i] = len(records)
            last_tick, last_len = tick, img.shape[0]
            i += 1
        if payload:
            records.append((header(sec, t_last), payload))
        tod = hh * 3600 + mm * 60 + ss + sec
        # Stamped at .990, not .999: `read_binary_SPEC.m:302` writes the .tas.csv row as a
        # MATLAB single, and hhmmss.999 rounds up to the next whole second (single spacing is
        # 1/256 s near 06:06:40), which moves every TAS row a second late and leaves the first
        # second's particles uncounted -- measured under Octave, NIGHT_FINDINGS 2026-09-28 #2.
        # .990 stays inside its second at every hhmmss below 240000 (spacing <= 1/64 s).
        records.append((header(sec, sec + HK_STAMP), _hk_words(flight.tas_mps, tod)))
    # One spare housekeeping record after the last second: the last record of a raw file is
    # never a primary (preserved `read_binary_SPEC.m` behaviour), so without it the
    # final second's TAS row -- and with it that second's particles -- would never be counted.
    tod = hh * 3600 + mm * 60 + ss + flight.n_seconds
    records.append((header(flight.n_seconds, flight.n_seconds + HK_STAMP),
                    _hk_words(flight.tas_mps, tod)))
    raw = raw_file(str(path), records)
    # Rounded so the manifest stays small; the rounding is far below any quantity the chains
    # resolve (0.001 um in size, 1 ns in time, 0.01 um across the array, 1 um in depth), and
    # the values written ARE the truth -- the raw bytes were rendered from the same numbers
    # before rounding, which is below one sub-sample of the rendering in every case.
    cols = {
        "kind": kind.tolist(), "d0_um": np.round(d0, 3).tolist(),
        "t_s": np.round(t_eff, 9).tolist(),
        "second": np.floor(t_eff).astype(int).tolist(), "x_um": np.round(x, 2).tolist(),
        "z_mm": np.round(z, 3).tolist(), "zd": np.round(zd, 4).tolist(),
        "imaged": imaged.tolist(), "clipped": clipped.tolist(),
        "n_slices": n_slices.tolist(), "clock": clock.tolist(), "record": record.tolist(),
        "pushed_us": np.round(pushed, 4).tolist(),
    }
    manifest = TruthManifest(spec=flight, model=model, columns=cols, raw_name=raw.name)
    manifest.to_json(str(raw) + MANIFEST_SUFFIX)
    return manifest


def write_aircraft_tas(path, flight: FlightSpec) -> Path:
    """The aircraft file a TAS-reading ``imgProc_sm`` takes as ``varargin{1}``
    (``imgProc_sm.m:183-185``; the v3.1.4 image processing reads ``Time`` as HHMMSS and
    ``TAS`` in m/s): one
    sample per second of the flight, at the flight's constant TAS."""
    import netCDF4

    hh, mm, ss = flight.start
    tod = hh * 3600 + mm * 60 + ss + np.arange(flight.n_seconds)
    hhmmss = (tod // 3600) * 10000 + ((tod // 60) % 60) * 100 + tod % 60
    path = Path(path)
    with netCDF4.Dataset(str(path), "w", format="NETCDF3_CLASSIC") as d:
        d.createDimension("time", len(tod))
        d.createVariable("Time", "f8", ("time",))[:] = hhmmss.astype(float)
        d.createVariable("TAS", "f8", ("time",))[:] = np.full(len(tod), flight.tas_mps)
    return path
