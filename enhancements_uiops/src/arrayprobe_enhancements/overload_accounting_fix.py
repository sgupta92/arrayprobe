# SPDX-License-Identifier: BSD-3-Clause
"""A8 -- keep the DOF-overload accounting for seconds that accept no particles.

``sizeDist.m:813`` measures, per second, the inter-arrival time lost to DOF overload
(``time_interval72``).  If that second then accepts no particles, ``:1337`` resets it to zero,
and ``:1571`` turns that into ``sum_IntArr = 1`` -- "live for the whole second, lost nothing" --
the opposite of what ``:813`` measured.  ``sample_vol`` (``:1605``, ``sa2 * 1e-6 *
time_interval200 * tas``) moves with it.  Concentrations are unaffected (zero either way for such
a second); anything that reads ``sum_IntArr`` or ``sample_vol`` directly -- duty cycle, sample
volume aggregated over a leg -- is.  160 of 313 particle-bearing
seconds on 09/06/2016 take this path.  The port reproduces the reset (``sizedist.py``, the
``:1327, :1337-1340`` block).

This enhancement post-processes a written ``sd`` file against its ``proc`` file: for every second
whose accepted population is empty but which holds particles, it recomputes ``:813``'s
``time_interval72`` exactly as the port does -- inter-arrival from the previous particle in the
file, the probetype-2 clock rollback, negatives clipped to zero, MATLAB-order sum over the
particles flagged ``DMT_DOF_SPEC_OVERLOAD ~= 0`` -- and writes ``sum_IntArr = 1 - t72`` and
``sample_vol *= (1 - t72)`` into a *copy* of the ``sd`` file.  The port's files are never
modified.  Seconds past the end of the particle data (``:1486-1517``) also reset, but hold no
particles, so nothing is recomputed for them.

Validation: the core is a pure function over arrays with synthetic cases pinned; on a real pair
the affected seconds are exactly those the finding predicts (``sum_IntArr == 1`` with particles
present), the recomputed ``t72`` reproduces the port's own value for seconds that were *not*
reset (a real oracle for the recomputation), and untouched seconds are byte-identical.

**Conditional on v3.5** (2026-09-14).  A default v3.5 ``sd`` carries neither
``sum_IntArr`` nor ``sample_vol`` at all: v3.5 ``sizeDist.m`` only ``defVar``s them under
``if iSaveIntArrSV == 1`` (``:2363-2372``), and ``scripts/run_flight.py``'s ``V35_CALL`` pins
``i_save_int_arr_sv=0`` (the port's own write gate, ``arrayprobe_uiops/sizedist.py:706``) --
measured on the tracked ``demo_flight_v35_sd.nc``, which holds neither variable.  This module
cannot apply to that file, and says so by name: :func:`apply_overload_accounting` raises
:class:`MissingSizeDistVariables` before writing anything.  It applies unconditionally on
v3.1.4, where both variables are written unconditionally.
"""

from __future__ import annotations

import shutil

import netCDF4
import numpy as np
from arrayprobe.constants import sizedist_config
from arrayprobe.matlab_compat import msum

__all__ = ["overload_time_per_second", "affected_seconds", "apply_overload_accounting",
           "MissingSizeDistVariables"]


class MissingSizeDistVariables(KeyError):
    """The ``sd`` file was never given ``sum_IntArr``/``sample_vol`` to correct.

    v3.5 ``sizeDist.m`` writes both only inside ``if iSaveIntArrSV == 1`` (``:2363``, the
    two ``defVar`` calls at ``:2364``/``:2369``); the port's own write gate is
    ``arrayprobe_uiops/sizedist.py:706``.  ``scripts/run_flight.py``'s ``V35_CALL`` pins
    ``i_save_int_arr_sv=0`` for every default v3.5 run -- **measured**, not assumed: the
    tracked ``tests/data/demo_flight_v35_sd.nc`` (a NETCDF4 v3.5 ``sd``) holds
    neither variable.  So this module has nothing to correct on a default v3.5 run; a caller
    who wants A8 applied on v3.5 must first re-run ``sizedist.run`` with
    ``i_save_int_arr_sv=1``.

    Subclasses :class:`KeyError` on purpose: ``pipeline.py``'s applier
    (``_apply_overload_accounting_fix``) was written against the plain ``KeyError`` this
    module used to raise implicitly (a missing-variable lookup) and its own ``except
    KeyError:`` clause is what turns this into a named, provenance-recorded skip -- keeping
    the subclass relationship means that catch keeps working unchanged.
    """


def _require_int_arr_variables(sd_path) -> None:
    with netCDF4.Dataset(sd_path) as check:
        missing = [name for name in ("sum_IntArr", "sample_vol")
                   if name not in check.variables]
    if missing:
        raise MissingSizeDistVariables(
            f"{sd_path}: sd has no {'/'.join(missing)}: written only under "
            "iSaveIntArrSV=1 (v3.5 sizeDist.m:2363; arrayprobe_uiops/sizedist.py:706); "
            "the v3.5 engine's default call (run_flight.py V35_CALL) pins 0"
        )


def overload_time_per_second(times, time_in_seconds, dof_overload, *, second, res, tas_max,
                             probetype=2):
    """``sizeDist.m:813`` for one second: sum of overload inter-arrival time, as the port does it.

    ``times`` are the proc's per-particle ``Time`` (HHMMSS), ``second`` the HHMMSS value of the
    second to compute.  Returns ``(t72, n_particles)``.
    """
    idx = np.flatnonzero(np.asarray(times, float) == float(second))
    if idx.size == 0:
        return 0.0, 0
    lo, hi = int(idx[0]), int(idx[-1]) + 1
    tis = np.asarray(time_in_seconds, float)
    if probetype == 0:
        int_arr = tis[lo:hi].copy()                                       # :689-690
    elif lo == 0:
        int_arr = np.concatenate([[0.0], np.diff(tis[lo:hi])])            # :693
    else:
        int_arr = np.diff(tis[lo - 1:hi])                                 # :696-697
    if probetype == 2:
        roll = int_arr < -10                                              # :727
        int_arr[roll] += (2 ** 32 - 1) * (res / 1e6 / tas_max)
    elif probetype == 0:
        roll = int_arr < 0                                                # :728-729
        int_arr[roll] += (2 ** 24 - 1) * (res / 1e6 / tas_max)
    int_arr[int_arr < 0] = 0                                              # :746
    if probetype == 0:
        return 0.0, hi - lo                                               # :811
    dof = np.asarray(dof_overload[lo:hi])
    return float(msum(int_arr[dof != 0])), hi - lo                        # :813


def affected_seconds(sd_time, sd_count, sd_sum_intarr, proc_times):
    """Indices of seconds that hold particles but accepted none (``sum_IntArr`` reset to 1)."""
    count = np.nan_to_num(np.asarray(sd_count, float))
    if count.shape[0] != sd_time.size:
        count = count.T
    has_particles = np.isin(np.asarray(sd_time, float), np.unique(np.asarray(proc_times, float)))
    none_accepted = count.sum(axis=1) == 0
    reset = np.asarray(sd_sum_intarr, float) == 1.0
    return np.flatnonzero(has_particles & none_accepted & reset)


def apply_overload_accounting(proc_path, sd_path, out_path, *, projectname="ORACLES",
                              probename="2DS", tree="production"):
    """Write ``out_path``: ``sd_path`` with A8 applied.  Returns a per-second report.

    Never modifies ``sd_path`` or ``proc_path``.  Raises :class:`MissingSizeDistVariables`
    (before any file is written) if ``sd_path`` has neither ``sum_IntArr`` nor
    ``sample_vol`` -- see that class's docstring.
    """
    cfg = sizedist_config(projectname, probename, tree)
    _require_int_arr_variables(sd_path)
    shutil.copyfile(sd_path, out_path)
    with netCDF4.Dataset(proc_path) as p:
        times = np.asarray(p.variables["Time"][:], float)
        tis = np.asarray(p.variables["Time_in_seconds"][:], float)
        dof = np.asarray(p.variables["DMT_DOF_SPEC_OVERLOAD"][:])
    report = []
    with netCDF4.Dataset(out_path, "r+") as d:
        sd_time = np.asarray(d.variables["time"][:], float)
        sum_intarr = np.asarray(d.variables["sum_IntArr"][:], float)
        count = d.variables["count"][:]
        idx = affected_seconds(sd_time, count, sum_intarr, times)
        svol = d.variables["sample_vol"]
        svol_time_first = svol.dimensions[0] == "Time"
        for i in idx:
            t72, n = overload_time_per_second(times, tis, dof, second=sd_time[i], res=cfg.res,
                                              tas_max=cfg.tasMax, probetype=cfg.probetype)
            new = 1.0 - t72
            d.variables["sum_IntArr"][i] = new
            if svol_time_first:
                svol[i, :] = svol[i, :] * new
            else:
                svol[:, i] = svol[:, i] * new
            report.append((int(sd_time[i]), n, t72, new))
    return report
