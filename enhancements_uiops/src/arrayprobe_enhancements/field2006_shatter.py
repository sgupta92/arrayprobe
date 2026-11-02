# SPDX-License-Identifier: BSD-3-Clause AND Apache-2.0
# Derived from NCAR Process2D (Apache-2.0); see LICENSES/ and NOTICE.md.
"""OPT-IN ENHANCEMENT, derived from NCAR Process2D: Field et al. (2006) per-second
inter-arrival fit.

Derived from NCAR ``aircraft_oap`` ``process2d/process2d.cpp`` (Apache-2.0);
every function cites the process2d.cpp lines it transcribes. Not part of the
UIOOPS port or of any engine (Process2D-derived
processing is an enhancement). It runs beside a size distribution, never inside
one: :func:`apply` gives the rejected-particle mask and per-second fit,
:func:`write_diagnostics` adds the fit to a copy of the sd. Numpy (and netCDF4
for the writer).

Process2D keeps a circular queue of the last 400 inter-arrival times (seconds),
bins all 400 into 40 logarithmic bins at each 1-s boundary, fits a double
Poisson mixture by a damped Gauss-Newton iteration, and sets the shattering
cutoff at 1/20 of the first mode's peak, ``0.05 / a1``.

Precision follows the C: the bin endpoints, midpoints and normalised counts are
``float`` (float32), the fit parameters ``double``, ``damp`` and
``percentchange`` ``float``.

The fresh queue's fit is NaN, here as in Process2D. ``itq = {1}`` histograms
to 399 counts in bin 0 and one in bin 34; ``ysum = 400`` passes the :236
low-count test, the near-singular ``JJt`` lets the third damped step drive
``a1`` negative, ``exp(-a1*x)`` overflows and ``a``, ``pcutoff`` and
``corrfac`` all become NaN. A NaN cutoff rejects no particle and the factor
applies as 1 (:1075-1079); the next second with ``ysum >= 10`` restarts from
its own first guess. Pinned by
``test_field2006_shatter.test_fresh_queue_fit_diverges_to_nan_as_process2d_does``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

NITQ = 400
"""Queue length, ``const int nitq = 400`` (process2d.cpp:723)."""

N_INTERARRIVAL_BINS = 40
"""``nInterarrivalBins = 40`` (process2d config.h:24)."""

CUTOFF_FRACTION = 0.05
"""``pcutoff = 1.0/bestfit[1]*0.05`` (process2d.cpp:933)."""

KC = math.log10(math.exp(1))
"""``kc=log10(exp(1))`` (process2d.cpp:224): the model *multiplies* by it."""

_DAMP = float(np.float32(0.2))  # ``float damp=0.2`` (process2d.cpp:226)
_MIN_ITER = 5  # process2d.cpp:227
_MAX_ITER = 50  # process2d.cpp:227


def bin_endpoints() -> np.ndarray:
    """``it_endpoints``: ``10^((i-35)/5)`` for i = 0..40, as float32 (process2d.cpp:736-737)."""
    return np.array(
        [np.float32(10.0 ** (float(np.float32(i - 35)) / 5.0))
         for i in range(N_INTERARRIVAL_BINS + 1)],
        dtype=np.float32)


def bin_midpoints() -> np.ndarray:
    """``it_midpoints``: ``10^((i-34.5)/5)`` for i = 0..39, as float32 (process2d.cpp:738-739)."""
    return np.array(
        [np.float32(10.0 ** ((float(np.float32(i)) - 34.5) / 5.0))
         for i in range(N_INTERARRIVAL_BINS)],
        dtype=np.float32)


def histogram(queue: np.ndarray) -> np.ndarray:
    """Bin every queue entry as process2d.cpp:915-921 does.

    An entry ``>= ep[40]`` (10 s) is dropped; otherwise ``iit`` starts at 0 and
    advances while ``itq > ep[iit+1]``, so there is no lower bound: anything
    ``<= ep[1]`` (including the queue's initial zeros) lands in bin 0. The
    ``binoffset`` of :919 is added on write and on read (:924), so it cancels.
    """
    ep = bin_endpoints().astype(np.float64)
    q = np.asarray(queue, dtype=np.float64)
    q = q[q < ep[N_INTERARRIVAL_BINS]]
    # number of ep[1..39] strictly below the entry == the while loop's iit
    iit = np.searchsorted(ep[1:N_INTERARRIVAL_BINS], q, side="left")
    return np.bincount(iit, minlength=N_INTERARRIVAL_BINS).astype(np.int64)


def invert3(m: np.ndarray) -> tuple[float, np.ndarray]:
    """Cofactor 3x3 inverse, process2d.cpp:188-210.

    Returns ``(det, n)``; when ``det == 0`` ``n`` is left all zero, as the
    caller's ``JJti[3][3]={{0}}`` is (:268, :271).
    """
    n = np.zeros((3, 3))
    det = (m[0][0]*m[1][1]*m[2][2]
           + m[1][0]*m[2][1]*m[0][2]
           + m[2][0]*m[0][1]*m[1][2]
           - m[0][0]*m[2][1]*m[1][2]
           - m[1][0]*m[0][1]*m[2][2]
           - m[2][0]*m[1][1]*m[0][2])
    if det == 0:
        return float(det), n
    n[0][0] = (m[1][1]*m[2][2] - m[1][2]*m[2][1])/det
    n[0][1] = (m[0][2]*m[2][1] - m[2][2]*m[0][1])/det
    n[0][2] = (m[0][1]*m[1][2] - m[1][1]*m[0][2])/det
    n[1][0] = (m[1][2]*m[2][0] - m[2][2]*m[1][0])/det
    n[1][1] = (m[0][0]*m[2][2] - m[2][0]*m[0][2])/det
    n[1][2] = (m[0][2]*m[1][0] - m[1][2]*m[0][0])/det
    n[2][0] = (m[1][0]*m[2][1] - m[2][0]*m[1][1])/det
    n[2][1] = (m[0][1]*m[2][0] - m[2][1]*m[0][0])/det
    n[2][2] = (m[0][0]*m[1][1] - m[1][0]*m[0][1])/det
    return float(det), n


def model(a: np.ndarray, x: np.ndarray) -> np.ndarray:
    """Double-Poisson model, process2d.cpp:245 (and :291), with the ``kc`` factor."""
    x = np.asarray(x, dtype=np.float64)
    return (a[0]*a[1]*x*np.exp(-a[1]*x)*KC
            + (1.0-a[0])*a[2]*x*np.exp(-a[2]*x)*KC)


def dpoisson_fit(x: np.ndarray, y: np.ndarray, a: np.ndarray) -> float:
    """Damped Gauss-Newton double-Poisson fit, process2d.cpp:215-300.

    Updates ``a`` (length 3, float64) **in place** and returns the sum of
    squared residuals, or ``-1`` when the counts sum below 10 — in which case
    ``a`` is untouched (:236 returns before the first guess), so a caller's
    ``bestfit`` carries the previous second's values.
    """
    x64 = np.asarray(x, dtype=np.float32).astype(np.float64)
    yf = np.asarray(y, dtype=np.float32)
    n = yf.size
    ysum = 0.0
    for v in yf:  # :232, sequential double accumulation of floats
        ysum += float(v)
    # :233 ``y[i] /= ysum`` -> double division stored back to float
    yn = (yf.astype(np.float64) / ysum).astype(np.float32) if ysum != 0 else yf
    if ysum < 10:  # :236
        return -1.0
    # :239-242 first guess; maxindex (:172-185) is the first strict maximum above 0
    imax = 0
    ymax = 0.0
    for i in range(n):
        if float(yn[i]) > ymax:
            ymax = float(yn[i])
            imax = i
    a[0] = 0.8
    a[1] = 1.0 / float(x64[imax])
    a[2] = 1.0e6
    y64 = yn.astype(np.float64)
    iteration = 0
    percentchange = float(np.float32(100.0))
    # :245 loop condition
    while ((iteration < _MAX_ITER and percentchange > 1.0)
           or iteration < _MIN_ITER):
        iteration += 1
        e1 = np.exp(-a[1]*x64)
        e2 = np.exp(-a[2]*x64)
        f = a[0]*a[1]*x64*e1*KC + (1.0-a[0])*a[2]*x64*e2*KC  # :249
        diff = y64 - f  # :250
        J = np.empty((3, n))
        J[0] = a[1]*x64*e1*KC - a[2]*x64*e2*KC  # :251
        J[1] = a[0]*x64*e1*KC - a[0]*a[1]*x64*x64*e1*KC  # :252
        J[2] = (1.0-a[0])*x64*e2*KC - (1.0-a[0])*a[2]*x64*x64*e2*KC  # :253
        # :256-263 JJt, sequential sums over k
        JJt = np.zeros((3, 3))
        for i in range(3):
            for j in range(3):
                s = 0.0
                for k in range(n):
                    s = s + float(J[i][k])*float(J[j][k])
                JJt[i][j] = s
        _, JJti = invert3(JJt)  # :265
        # :268-273 JtDiff
        JtDiff = [0.0, 0.0, 0.0]
        for i in range(3):
            s = 0.0
            for j in range(n):
                s = s + float(diff[j])*float(J[i][j])
            JtDiff[i] = s
        # :276-281 deltaA
        deltaA = [0.0, 0.0, 0.0]
        for i in range(3):
            s = 0.0
            for j in range(3):
                s = s + JtDiff[j]*float(JJti[i][j])
            deltaA[i] = s
        # :283-287 update; the change is *signed* (``abs`` only on the new a1)
        olda1 = float(a[1])
        a[0] = a[0] + _DAMP*deltaA[0]
        a[1] = a[1] + _DAMP*deltaA[1]
        a[2] = a[2] + _DAMP*deltaA[2]
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            percentchange = float(np.float32(
                100*(abs(float(a[1]))-olda1)/olda1))
    # :289-294 sum of squared residuals
    fin = model(a, x64)
    diff2 = 0.0
    for i in range(n):
        diff2 = diff2 + (float(y64[i]) - float(fin[i]))**2
    return diff2


def cutoff(a1: float) -> float:
    """``pcutoff = (float)(1.0/bestfit[1]*0.05)`` (process2d.cpp:933).

    ``a1 == 0`` (no fit has ever succeeded) gives ``inf``, as the C division does,
    so every particle is then rejected.
    """
    with np.errstate(divide="ignore"):
        return float(np.float32(np.float64(1.0) / np.float64(a1) * CUTOFF_FRACTION))


def correction_factor(pcutoff: float, a1: float) -> float:
    """``corrfac = (float)(1/(2*exp(-pcutoff*a1)-1))`` (process2d.cpp:934).

    Uses the float32 ``pcutoff`` as the C does. For any ``a1 > 0`` this is
    ``1/(2e^{-0.05}-1) ~= 1.1142`` up to float rounding. A NaN (from
    ``inf * 0``) is returned as NaN; Process2D replaces it by 1 when it applies
    the factor (:1075-1079), which is the caller's job.
    """
    with np.errstate(invalid="ignore", over="ignore"):
        prod = np.float64(pcutoff) * np.float64(a1)
        return float(np.float32(1.0 / (2 * np.exp(-prod) - 1)))


@dataclass
class Field2006State:
    """The state Process2D carries across seconds: the queue and ``bestfit``.

    ``itq`` starts as ``{1}`` -> ``[1.0, 0.0, ..., 0.0]`` and ``iitq`` at 0
    (process2d.cpp:724-726); ``bestfit`` starts ``{0,0,0}`` (:725).
    """

    itq: np.ndarray = field(default_factory=lambda: np.concatenate(
        [[1.0], np.zeros(NITQ - 1)]))
    iitq: int = 0
    bestfit: np.ndarray = field(default_factory=lambda: np.zeros(3))

    def push(self, inttime: float) -> None:
        """process2d.cpp:885-887: write, advance, wrap at ``nitq``."""
        self.itq[self.iitq] = inttime
        self.iitq += 1
        if self.iitq > NITQ - 1:
            self.iitq = 0

    def fit_second(self) -> tuple[float, float, float, float, float]:
        """One 1-s boundary (process2d.cpp:915-934), shatter correction on.

        Returns ``(a0, a1, a2, pcutoff, corrfac)``, each cast to float32 as the
        ``data.*`` stores are.
        """
        counts = histogram(self.itq)
        dpoisson_fit(bin_midpoints(), counts.astype(np.float32), self.bestfit)
        a0, a1, a2 = (float(np.float32(v)) for v in self.bestfit)
        pc = cutoff(float(self.bestfit[1]))
        cf = correction_factor(pc, float(self.bestfit[1]))
        return a0, a1, a2, pc, cf


# ---------------------------------------------------------------------------
# Applying the per-second cutoff to a particle set (opt-in, Process2D-derived)
# ---------------------------------------------------------------------------

STAMP = ("field2006=process2d-derived field2006_nitq=400 field2006_nbins=40 "
         "field2006_frac=0.05 field2006_queue_init=process2d")
"""Run-stamp fragment naming this correction as Process2D-derived."""

DIAGNOSTIC_VARIABLES = ("field2006_a0", "field2006_a1", "field2006_a2",
                        "field2006_cutoff_s", "field2006_corrfac")
"""Variables :func:`write_diagnostics` adds beside an existing size distribution."""


@dataclass
class Field2006Result:
    """Per-particle mask and per-second diagnostics from :func:`apply`."""

    rejected: np.ndarray
    """Per particle, file order: True where the Process2D pair rule rejects it."""
    seconds: np.ndarray
    """The distinct seconds present, in order of first appearance."""
    a0: np.ndarray
    a1: np.ndarray
    a2: np.ndarray
    cutoff_s: np.ndarray
    corrfac: np.ndarray
    """Raw ``corrfac`` per second; NaN where no fit has ever succeeded."""


def apply(inttime: np.ndarray, second: np.ndarray) -> Field2006Result:
    """Run the Process2D queue, fit and pair rule over one particle stream.

    ``inttime`` is each particle's inter-arrival time in seconds and ``second``
    its 1-Hz time, both in file order; ``second`` must be non-decreasing.

    Order follows process2d.cpp:879-934: each particle is pushed before the
    boundary test, so the first particle of second N+1 is in the queue that
    fits second N. Particle i is rejected when ``inttime[i] < pcutoff`` or
    ``inttime[i+1] < pcutoff`` (strict, :531, :955-961), both judged against
    particle i's own second's cutoff, including across a second boundary.

    Not transcribed, a choice of this module: the final second, which no later
    particle closes, is fitted on the queue as it stands at the end of input,
    and its last particle is judged on its own gap only.
    """
    t = np.asarray(inttime, dtype=np.float64)
    s = np.asarray(second)
    if t.shape != s.shape or t.ndim != 1:
        raise ValueError("inttime and second must be 1-D and the same length")
    if s.size and np.any(np.diff(s) < 0):
        raise ValueError("second must be non-decreasing (file order)")
    n = t.size
    state = Field2006State()
    seconds: list = []
    fits: list[tuple[float, float, float, float, float]] = []
    pc_of = np.empty(n)
    start = 0
    for i in range(n):
        state.push(float(t[i]))
        if i > start and s[i] != s[start]:
            fit = state.fit_second()
            seconds.append(s[start])
            fits.append(fit)
            pc_of[start:i] = fit[3]
            start = i
    if n:
        # the final second: no later particle closes it
        fit = state.fit_second()
        seconds.append(s[start])
        fits.append(fit)
        pc_of[start:n] = fit[3]
    pc32 = pc_of.astype(np.float32).astype(np.float64)
    own = t < pc32
    nxt = np.zeros(n, dtype=bool)
    if n > 1:
        nxt[:-1] = t[1:] < pc32[:-1]
    arr = np.array(fits, dtype=np.float64).reshape(-1, 5)
    return Field2006Result(
        rejected=own | nxt,
        seconds=np.asarray(seconds),
        a0=arr[:, 0], a1=arr[:, 1], a2=arr[:, 2],
        cutoff_s=arr[:, 3], corrfac=arr[:, 4])


def applied_corrfac(corrfac: np.ndarray) -> np.ndarray:
    """The factor Process2D multiplies into the counts: NaN -> 1 (process2d.cpp:1075-1079)."""
    c = np.asarray(corrfac, dtype=np.float64)
    return np.where(np.isnan(c), 1.0, c)


def corrected_counts(counts: np.ndarray, corrfac: np.ndarray) -> np.ndarray:
    """Per-second counts of the accepted particles times ``corrfac``.

    ``counts`` has seconds on its first axis, aligned with ``corrfac``; applied
    before any division by sample volume, as process2d.cpp:1075-1079 does.
    """
    c = np.asarray(counts, dtype=np.float64)
    f = applied_corrfac(corrfac)
    return c * f.reshape((-1,) + (1,) * (c.ndim - 1))


def align_to_axis(result: Field2006Result, axis_seconds: np.ndarray) -> dict[str, np.ndarray]:
    """Per-second diagnostics on a size distribution's time axis; NaN where no particle fell."""
    ax = np.asarray(axis_seconds)
    pos = {v: k for k, v in enumerate(result.seconds.tolist())}
    out = {name: np.full(ax.size, np.nan) for name in DIAGNOSTIC_VARIABLES}
    src = dict(zip(DIAGNOSTIC_VARIABLES,
                   (result.a0, result.a1, result.a2, result.cutoff_s, result.corrfac),
                   strict=True))
    for j, v in enumerate(ax.tolist()):
        k = pos.get(v)
        if k is not None:
            for name in DIAGNOSTIC_VARIABLES:
                out[name][j] = src[name][k]
    return out


def write_diagnostics(sd_path: str, out_path: str, time_dim: str,
                      diagnostics: dict[str, np.ndarray]) -> None:
    """Copy ``sd_path`` to ``out_path`` and add the Field-2006 diagnostics beside it.

    Every existing variable and attribute is carried over unchanged; the new
    variables are float32 on ``time_dim`` with fill NaN, and the file gains a
    ``field2006_stamp`` global attribute saying the variables are Process2D-derived.
    """
    import shutil

    import netCDF4

    if out_path == sd_path:
        raise ValueError("write_diagnostics never overwrites its input")
    shutil.copyfile(sd_path, out_path)
    with netCDF4.Dataset(out_path, "a") as nc:
        if time_dim not in nc.dimensions:
            raise ValueError(f"{sd_path} has no dimension {time_dim!r}")
        nt = len(nc.dimensions[time_dim])
        clash = [v for v in DIAGNOSTIC_VARIABLES if v in nc.variables]
        if clash:
            raise ValueError(f"{sd_path} already holds {clash}")
        for name in DIAGNOSTIC_VARIABLES:
            data = np.asarray(diagnostics[name], dtype=np.float32)
            if data.shape != (nt,):
                raise ValueError(f"{name} has shape {data.shape}, expected ({nt},)")
            var = nc.createVariable(name, "f4", (time_dim,), fill_value=np.float32(np.nan))
            var.setncattr("source", "Process2D-derived Field et al. (2006) fit (opt-in enhancement)")
            var[:] = data
        nc.setncattr("field2006_stamp", STAMP)
